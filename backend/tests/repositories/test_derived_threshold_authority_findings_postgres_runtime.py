"""Regression proof for the 2026-08-25 derived Threshold review findings."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import threading
import uuid

import psycopg2
import pytest

from backend.tests.repositories.test_derived_threshold_authority_postgres_runtime import (
    DERIVED_SQL,
    _connection,
    _insert_ride,
    _install,
    _register,
    _register_anchors,
)
from backend.tests.services.test_settlement_clock_postgres_runtime import postgres_dsn
from backend.tests.sql.test_account_deletion_migration_runtime import (
    WALLET,
    _apply as _apply_account_deletion,
    _create_request,
    _insert_user,
)


def _seed_user(cursor, user_id: uuid.UUID) -> None:
    cursor.execute("INSERT INTO public.users (id) VALUES (%s)", (user_id,))


def _install_with_account_deletion(cursor) -> None:
    _apply_account_deletion(cursor)
    cursor.execute(
        """
        CREATE TABLE public.reward_threshold_efforts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL
        );
        CREATE TABLE public.reward_threshold_candidates (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL
        );
        CREATE TABLE public.reward_threshold_source_envelopes (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL
        );
        CREATE TABLE public.reward_threshold_ratchets (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL
        );
        CREATE TABLE public.reward_threshold_pending_promotions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id UUID NOT NULL
        );
        """
    )
    integration_start = DERIVED_SQL.index("-- Account deletion 152 landed")
    integration_end = DERIVED_SQL.index(
        "CREATE OR REPLACE FUNCTION public.next_reward_threshold_monday"
    )
    cursor.execute(DERIVED_SQL[integration_start:integration_end])


def test_monotone_closure_records_lower_fit_without_lowering_economic_candidate(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection, connection.cursor() as cursor:
        user_id = uuid.uuid4()
        source_id = uuid.uuid4()
        _install(cursor, lambda seeded: _seed_user(seeded, user_id))
        accepted_at = datetime(2026, 8, 30, 10, tzinfo=timezone.utc)

        first = _insert_ride(
            cursor, user_id=user_id, source_id=source_id, received_at=accepted_at
        )
        _register_anchors(cursor, first, (350, 290, 265), accepted_at)
        short = _insert_ride(
            cursor,
            user_id=user_id,
            source_id=source_id,
            received_at=accepted_at + timedelta(seconds=1),
        )
        _register_anchors(
            cursor, short, (450, None, None), accepted_at + timedelta(seconds=1)
        )

        cursor.execute(
            """
            SELECT fitted_candidate_w, economic_candidate_w, target_ftp_w
            FROM public.reward_threshold_candidates WHERE ride_id = %s
            """,
            (short,),
        )
        fitted, economic, target = cursor.fetchone()
        assert float(fitted) == pytest.approx(204.375, abs=1e-6)
        assert float(economic) == pytest.approx(244.118590, abs=1e-6)
        assert target is None
        cursor.execute(
            "SELECT target_ftp_w FROM public.reward_threshold_pending_promotions WHERE user_id=%s AND status='pending'",
            (user_id,),
        )
        assert cursor.fetchone()[0] == 245
        cursor.execute(
            """
            SELECT accepted_best_180s_w, accepted_candidate_w
            FROM public.reward_threshold_source_envelopes
            WHERE user_id=%s AND power_source_id=%s
            """,
            (user_id, source_id),
        )
        best_short, closure = cursor.fetchone()
        assert float(best_short) == 450
        assert float(closure) == pytest.approx(244.118590, abs=1e-6)


def test_first_valid_fit_establishes_with_the_ratified_coordinatewise_limitation(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection, connection.cursor() as cursor:
        user_id = uuid.uuid4()
        _install(cursor, lambda seeded: _seed_user(seeded, user_id))
        accepted_at = datetime(2026, 8, 30, 10, tzinfo=timezone.utc)
        ride_id = _insert_ride(cursor, user_id=user_id, received_at=accepted_at)

        _register_anchors(cursor, ride_id, (450, 290, 265), accepted_at)

        cursor.execute(
            """
            SELECT fitted_candidate_w, economic_candidate_w, disposition,
                   target_ftp_w
            FROM public.reward_threshold_candidates WHERE ride_id=%s
            """,
            (ride_id,),
        )
        fitted, economic, disposition, target = cursor.fetchone()
        assert float(fitted) == pytest.approx(204.375, abs=1e-6)
        assert float(economic) == pytest.approx(204.375, abs=1e-6)
        assert (disposition, target) == ("pending_establishment", 205)


def test_ride_deletion_detaches_relations_but_preserves_append_only_evidence(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection, connection.cursor() as cursor:
        user_id = uuid.uuid4()
        _install(cursor, lambda seeded: _seed_user(seeded, user_id))
        accepted_at = datetime(2026, 8, 30, 10, tzinfo=timezone.utc)
        ride_id = _insert_ride(cursor, user_id=user_id, received_at=accepted_at)
        _register(cursor, ride_id, 245, accepted_at)
        cursor.execute(
            """
            SELECT effort.evidence, effort.evidence_hash, pending.effective_at
            FROM public.reward_threshold_efforts effort
            JOIN public.reward_threshold_candidates candidate
              ON candidate.effort_id = effort.id
            JOIN public.reward_threshold_pending_promotions pending
              ON pending.candidate_id = candidate.id
            WHERE effort.ride_id = %s
            """,
            (ride_id,),
        )
        evidence, evidence_hash, effective_at = cursor.fetchone()

        with pytest.raises(psycopg2.errors.RaiseException, match="append-only"):
            cursor.execute(
                "UPDATE public.reward_threshold_efforts SET ride_id=NULL WHERE ride_id=%s",
                (ride_id,),
            )
        cursor.execute("DELETE FROM public.rides WHERE id=%s", (ride_id,))
        cursor.execute(
            """
            SELECT effort.ride_id, candidate.ride_id, effort.evidence, effort.evidence_hash
            FROM public.reward_threshold_efforts effort
            JOIN public.reward_threshold_candidates candidate
              ON candidate.effort_id=effort.id
            WHERE effort.user_id=%s
            """,
            (user_id,),
        )
        effort_ride, candidate_ride, retained, retained_hash = cursor.fetchone()
        assert effort_ride is candidate_ride is None
        assert retained == evidence
        assert str(ride_id) == retained["ride_id"]
        assert bytes(retained_hash) == bytes(evidence_hash)
        cursor.execute(
            "SELECT public.seal_due_reward_threshold_promotions_at(%s)",
            (effective_at,),
        )
        assert cursor.fetchone()[0] == 1


def test_late_processing_targets_a_future_monday_and_never_same_tx_seals(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection, connection.cursor() as cursor:
        user_id = uuid.uuid4()
        _install(cursor, lambda seeded: _seed_user(seeded, user_id))
        uploaded_at = datetime(2026, 8, 30, 22, tzinfo=timezone.utc)
        accepted_at = datetime(2026, 8, 31, 13, tzinfo=timezone.utc)
        ride_id = _insert_ride(cursor, user_id=user_id, received_at=uploaded_at)

        _register(cursor, ride_id, 245, accepted_at)

        cursor.execute(
            "SELECT disposition, target_effective_at FROM public.reward_threshold_candidates WHERE ride_id=%s",
            (ride_id,),
        )
        assert cursor.fetchone() == (
            "pending_establishment",
            datetime(2026, 9, 7, 12, tzinfo=timezone.utc),
        )
        cursor.execute(
            "SELECT count(*) FROM public.reward_ftp_authorities WHERE user_id=%s",
            (user_id,),
        )
        assert cursor.fetchone()[0] == 0


def test_small_clock_skew_clamps_receipt_and_large_skew_fails_closed(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection, connection.cursor() as cursor:
        user_id = uuid.uuid4()
        _install(cursor, lambda seeded: _seed_user(seeded, user_id))
        accepted_at = datetime(2026, 8, 31, 11, 59, 45, tzinfo=timezone.utc)
        tolerated = _insert_ride(
            cursor,
            user_id=user_id,
            received_at=accepted_at + timedelta(seconds=30),
        )
        _register(cursor, tolerated, 245, accepted_at)
        cursor.execute(
            "SELECT evidence_received_at FROM public.reward_threshold_efforts WHERE ride_id=%s",
            (tolerated,),
        )
        assert cursor.fetchone()[0] == accepted_at
        cursor.execute(
            """
            SELECT target_effective_at
            FROM public.reward_threshold_candidates WHERE ride_id=%s
            """,
            (tolerated,),
        )
        assert cursor.fetchone()[0] == datetime(
            2026, 9, 7, 12, tzinfo=timezone.utc
        )

        rejected = _insert_ride(
            cursor,
            user_id=user_id,
            received_at=accepted_at + timedelta(minutes=10, microseconds=1),
        )
        with pytest.raises(psycopg2.errors.RaiseException, match="clock skew"):
            _register(cursor, rejected, 250, accepted_at)


def test_invalid_fit_keeps_lifetime_anchors_and_can_recover(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection, connection.cursor() as cursor:
        user_id = uuid.uuid4()
        source_id = uuid.uuid4()
        _install(cursor, lambda seeded: _seed_user(seeded, user_id))
        accepted_at = datetime(2026, 8, 30, 10, tzinfo=timezone.utc)
        invalid = _insert_ride(
            cursor, user_id=user_id, source_id=source_id, received_at=accepted_at
        )
        _register_anchors(cursor, invalid, (800, 300, 150), accepted_at)
        cursor.execute(
            """
            SELECT accepted_best_180s_w, accepted_best_420s_w,
                   accepted_best_900s_w, accepted_candidate_w
            FROM public.reward_threshold_source_envelopes
            WHERE user_id=%s AND power_source_id=%s
            """,
            (user_id, source_id),
        )
        assert cursor.fetchone() == (800, 300, 150, None)

        recovery = _insert_ride(
            cursor,
            user_id=user_id,
            source_id=source_id,
            received_at=accepted_at + timedelta(seconds=1),
        )
        _register_anchors(
            cursor, recovery, (None, 500, 400), accepted_at + timedelta(seconds=1)
        )
        cursor.execute(
            "SELECT fitted_candidate_w, target_ftp_w FROM public.reward_threshold_candidates WHERE ride_id=%s",
            (recovery,),
        )
        fitted, target = cursor.fetchone()
        assert float(fitted) == pytest.approx(292.628205, abs=1e-6)
        assert target == 293


def test_weaker_pending_candidate_is_truthfully_superseded(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection, connection.cursor() as cursor:
        user_id = uuid.uuid4()
        _install(cursor, lambda seeded: _seed_user(seeded, user_id))
        accepted_at = datetime(2026, 8, 30, 10, tzinfo=timezone.utc)
        strong = _insert_ride(cursor, user_id=user_id, received_at=accepted_at)
        _register(cursor, strong, 260, accepted_at)
        weak = _insert_ride(
            cursor, user_id=user_id, received_at=accepted_at + timedelta(seconds=1)
        )
        _register(cursor, weak, 250, accepted_at + timedelta(seconds=1))

        cursor.execute(
            "SELECT disposition, target_ftp_w, target_effective_at FROM public.reward_threshold_candidates WHERE ride_id=%s",
            (weak,),
        )
        assert cursor.fetchone() == ("superseded", None, None)


def test_batch_sealer_isolates_one_user_and_operator_can_supersede_failure(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection, connection.cursor() as cursor:
        bad_user = uuid.uuid4()
        good_user = uuid.uuid4()

        def seed(seeded) -> None:
            _seed_user(seeded, bad_user)
            _seed_user(seeded, good_user)
            seeded.execute(
                """
                INSERT INTO public.reward_ftp_authorities (
                    user_id, ftp_w, source, evidence, evidence_hash,
                    verified_by, verified_at, effective_at
                ) VALUES (
                    %s, 250, 'verified_power_test', '{}'::jsonb,
                    pg_catalog.sha256(pg_catalog.convert_to('{}', 'UTF8')),
                    'legacy-test', '2026-01-01', '2026-01-05 12:00+00'
                )
                """,
                (bad_user,),
            )

        _install(cursor, seed)
        now = datetime.now(timezone.utc)
        due_at = (now - timedelta(days=now.weekday())).replace(
            hour=12, minute=0, second=0, microsecond=0
        )
        if due_at > now:
            due_at -= timedelta(days=7)
        cursor.execute(
            """
            UPDATE public.reward_threshold_pending_promotions
            SET target_ftp_w=200, effective_at=%s
            WHERE user_id=%s
            RETURNING effective_at
            """,
            (due_at, bad_user),
        )
        due_at = cursor.fetchone()[0]
        good_ride = _insert_ride(
            cursor,
            user_id=good_user,
            received_at=due_at - timedelta(days=1),
        )
        _register(cursor, good_ride, 245, due_at - timedelta(days=1))

        cursor.execute(
            "SELECT public.seal_due_reward_threshold_promotions_at(%s)", (due_at,)
        )
        assert cursor.fetchone()[0] == 1
        cursor.execute(
            "SELECT status FROM public.reward_threshold_pending_promotions WHERE user_id=%s",
            (bad_user,),
        )
        assert cursor.fetchone()[0] == "repair_required"
        cursor.execute(
            "SELECT id FROM public.reward_threshold_pending_promotions WHERE user_id=%s",
            (bad_user,),
        )
        pending_id = cursor.fetchone()[0]
        blocked_ride = uuid.uuid4()
        cursor.execute(
            "INSERT INTO public.rides (id, user_id) VALUES (%s, %s)",
            (blocked_ride, bad_user),
        )
        with pytest.raises(
            psycopg2.errors.RaiseException,
            match="requires operator repair",
        ):
            cursor.execute(
                "SELECT * FROM public.bind_ride_reward_ftp(%s, %s)",
                (blocked_ride, due_at + timedelta(seconds=1)),
            )
        cursor.execute(
            "SELECT status FROM public.repair_reward_threshold_promotion(%s, 'supersede', 'standing authority is higher')",
            (pending_id,),
        )
        assert cursor.fetchone()[0] == "superseded"
        cursor.execute(
            "SELECT reward_ftp_w FROM public.bind_ride_reward_ftp(%s, %s)",
            (blocked_ride, due_at + timedelta(seconds=1)),
        )
        assert cursor.fetchone()[0] == 250


def test_batch_sealer_continues_when_failure_state_is_write_fenced(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection, connection.cursor() as cursor:
        fenced_user = uuid.uuid4()
        good_user = uuid.uuid4()

        def seed(seeded) -> None:
            _seed_user(seeded, fenced_user)
            _seed_user(seeded, good_user)
            seeded.execute(
                """
                INSERT INTO public.reward_ftp_authorities (
                    user_id, ftp_w, source, evidence, evidence_hash,
                    verified_by, verified_at, effective_at
                ) VALUES (
                    %s, 250, 'verified_power_test', '{}'::jsonb,
                    pg_catalog.sha256(pg_catalog.convert_to('{}', 'UTF8')),
                    'legacy-test', '2026-01-01', '2026-01-05 12:00+00'
                )
                """,
                (fenced_user,),
            )

        _install(cursor, seed)
        now = datetime.now(timezone.utc)
        due_at = (now - timedelta(days=now.weekday())).replace(
            hour=12, minute=0, second=0, microsecond=0
        )
        if due_at > now:
            due_at -= timedelta(days=7)
        cursor.execute(
            """
            UPDATE public.reward_threshold_pending_promotions
            SET target_ftp_w=200, effective_at=%s
            WHERE user_id=%s
            """,
            (due_at, fenced_user),
        )
        good_ride = _insert_ride(
            cursor,
            user_id=good_user,
            received_at=due_at - timedelta(days=1),
        )
        _register(cursor, good_ride, 245, due_at - timedelta(days=1))
        cursor.execute(
            "SELECT pg_catalog.set_config('app.test_fenced_user', %s, false)",
            (str(fenced_user),),
        )
        cursor.execute(
            """
            CREATE OR REPLACE FUNCTION public.account_deletion_write_fence()
            RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
            BEGIN
                IF TG_OP = 'UPDATE'
                   AND NEW.user_id::TEXT = pg_catalog.current_setting(
                       'app.test_fenced_user', TRUE
                   ) THEN
                    RAISE EXCEPTION 'account_identity_write_fenced'
                        USING ERRCODE = '55000';
                END IF;
                IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
                RETURN NEW;
            END;
            $$;
            """
        )

        cursor.execute(
            "SELECT public.seal_due_reward_threshold_promotions_at(%s)",
            (due_at,),
        )
        assert cursor.fetchone()[0] == 1
        cursor.execute(
            """
            SELECT user_id, status
            FROM public.reward_threshold_pending_promotions
            WHERE user_id IN (%s, %s)
            ORDER BY user_id
            """,
            (fenced_user, good_user),
        )
        statuses = dict(cursor.fetchall())
        assert statuses[fenced_user] == "pending"
        assert statuses[good_user] == "sealed"


def test_repair_state_does_not_break_already_frozen_idempotent_reads(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection, connection.cursor() as cursor:
        candidate_user = uuid.uuid4()
        snapshot_user = uuid.uuid4()

        def seed(seeded) -> None:
            _seed_user(seeded, candidate_user)
            _seed_user(seeded, snapshot_user)
            seeded.execute(
                """
                INSERT INTO public.reward_ftp_authorities (
                    user_id, ftp_w, source, evidence, evidence_hash,
                    verified_by, verified_at, effective_at
                ) VALUES (
                    %s, 250, 'verified_power_test', '{}'::jsonb,
                    pg_catalog.sha256(pg_catalog.convert_to('{}', 'UTF8')),
                    'legacy-test', '2026-01-01', '2026-01-05 12:00+00'
                )
                """,
                (snapshot_user,),
            )

        _install(cursor, seed)
        accepted_at = datetime(2026, 8, 30, 10, tzinfo=timezone.utc)
        candidate_ride = _insert_ride(
            cursor, user_id=candidate_user, received_at=accepted_at
        )
        original_candidate = _register(cursor, candidate_ride, 245, accepted_at)
        cursor.execute(
            """
            UPDATE public.reward_threshold_pending_promotions
            SET status='repair_required', effective_at='2026-08-24 12:00+00'
            WHERE user_id=%s
            """,
            (candidate_user,),
        )

        replayed_candidate = _register(cursor, candidate_ride, 245, accepted_at)
        assert replayed_candidate[0] == original_candidate[0]

        frozen_ride = uuid.uuid4()
        cursor.execute(
            "INSERT INTO public.rides (id, user_id) VALUES (%s, %s)",
            (frozen_ride, snapshot_user),
        )
        cursor.execute(
            "SELECT reward_ftp_w FROM public.bind_ride_reward_ftp(%s, %s)",
            (frozen_ride, accepted_at),
        )
        assert cursor.fetchone()[0] == 250
        cursor.execute(
            """
            UPDATE public.reward_threshold_pending_promotions
            SET status='repair_required', effective_at='2026-08-24 12:00+00'
            WHERE user_id=%s
            """,
            (snapshot_user,),
        )
        cursor.execute(
            "SELECT reward_ftp_w FROM public.bind_ride_reward_ftp(%s, %s)",
            (frozen_ride, accepted_at),
        )
        assert cursor.fetchone()[0] == 250


def test_evidence_hashes_and_timestamp_json_are_timezone_independent(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection, connection.cursor() as cursor:
        user_id = uuid.uuid4()
        _install(cursor, lambda seeded: _seed_user(seeded, user_id))
        accepted_at = datetime(2026, 8, 30, 10, tzinfo=timezone.utc)
        cursor.execute("SET TIME ZONE 'America/Los_Angeles'")
        ride_id = _insert_ride(cursor, user_id=user_id, received_at=accepted_at)
        _register(cursor, ride_id, 245, accepted_at)
        cursor.execute(
            "SELECT evidence, evidence_hash FROM public.reward_threshold_efforts WHERE ride_id=%s",
            (ride_id,),
        )
        evidence, evidence_hash = cursor.fetchone()
        assert evidence["accepted_at"].endswith("+00:00")
        assert evidence["best_180s_w"] is not None
        cursor.execute("SET TIME ZONE 'Asia/Tokyo'")
        cursor.execute(
            "SELECT pg_catalog.sha256(pg_catalog.convert_to(evidence::text, 'UTF8')) FROM public.reward_threshold_efforts WHERE ride_id=%s",
            (ride_id,),
        )
        assert bytes(cursor.fetchone()[0]) == bytes(evidence_hash)


def test_account_deletion_routes_threshold_evidence_to_support_before_storage(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection, connection.cursor() as cursor:
        _install_with_account_deletion(cursor)
        user_id = _insert_user(cursor)
        cursor.execute(
            "INSERT INTO public.reward_threshold_efforts (user_id) VALUES (%s)",
            (user_id,),
        )

        cursor.execute(
            "SELECT public.br_account_deletion_db_blockers(%s, %s)",
            (user_id, WALLET),
        )
        blockers = cursor.fetchone()[0]
        assert any(
            blocker.get("source") == "reward_threshold_evidence"
            and blocker.get("code") == "policy_review_required"
            for blocker in blockers
        )
        request_id, request = _create_request(cursor, user_id)
        assert request[1] == "needs_support"
        cursor.execute(
            "SELECT storage_authorized_at FROM public.deletion_requests WHERE id=%s",
            (request_id,),
        )
        assert cursor.fetchone()[0] is None


def test_active_account_deletion_request_fences_late_threshold_evidence(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection, connection.cursor() as cursor:
        _install_with_account_deletion(cursor)
        user_id = _insert_user(cursor)
        request_id, request = _create_request(cursor, user_id)
        assert request[1] == "queued"

        with pytest.raises(
            psycopg2.errors.ObjectNotInPrerequisiteState,
            match="account_identity_write_fenced",
        ):
            cursor.execute(
                "INSERT INTO public.reward_threshold_efforts (user_id) VALUES (%s)",
                (user_id,),
            )
        cursor.execute(
            "SELECT count(*) FROM public.reward_threshold_efforts WHERE user_id=%s",
            (user_id,),
        )
        assert cursor.fetchone()[0] == 0
        cursor.execute(
            "SELECT storage_authorized_at FROM public.deletion_requests WHERE id=%s",
            (request_id,),
        )
        assert cursor.fetchone()[0] is None


def test_account_deletion_and_threshold_registration_serialize_on_user_owner(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as setup_connection, setup_connection.cursor() as cursor:
        _install_with_account_deletion(cursor)
        user_id = _insert_user(cursor)

    deletion_connection = psycopg2.connect(postgres_dsn)
    writer_finished = threading.Event()
    writer_errors: list[Exception] = []

    def insert_threshold_evidence() -> None:
        writer_connection = psycopg2.connect(postgres_dsn)
        try:
            with writer_connection, writer_connection.cursor() as writer:
                writer.execute("SET lock_timeout = '5s'")
                writer.execute(
                    "INSERT INTO public.reward_threshold_efforts (user_id) VALUES (%s)",
                    (user_id,),
                )
        except Exception as exc:  # pragma: no branch - outcome asserted below
            writer_errors.append(exc)
        finally:
            writer_connection.close()
            writer_finished.set()

    try:
        with deletion_connection.cursor() as deletion_cursor:
            _request_id, request = _create_request(deletion_cursor, user_id)
            assert request[1] == "queued"

        writer = threading.Thread(target=insert_threshold_evidence, daemon=True)
        writer.start()
        finished_before_deletion_commit = writer_finished.wait(timeout=0.25)
        deletion_connection.commit()
        assert writer_finished.wait(timeout=5)
        writer.join(timeout=1)

        assert finished_before_deletion_commit is False
        assert len(writer_errors) == 1
        assert isinstance(
            writer_errors[0], psycopg2.errors.ObjectNotInPrerequisiteState
        )
        assert "account_identity_write_fenced" in str(writer_errors[0])
        with _connection(postgres_dsn) as check_connection, check_connection.cursor() as check:
            check.execute(
                "SELECT count(*) FROM public.reward_threshold_efforts WHERE user_id=%s",
                (user_id,),
            )
            assert check.fetchone()[0] == 0
    finally:
        if deletion_connection.status != psycopg2.extensions.STATUS_READY:
            deletion_connection.rollback()
        deletion_connection.close()
