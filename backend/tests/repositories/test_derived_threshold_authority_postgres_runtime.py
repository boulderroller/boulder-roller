"""PostgreSQL runtime proof for derived Threshold Monday authority."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import threading
import time
import uuid

import psycopg2
import pytest
from psycopg2.extras import Json

from backend.tests.repositories.test_parser_provenance_postgres_runtime import (
    PROVENANCE_SQL,
    _bootstrap,
    _connection,
)
from backend.tests.services.test_settlement_clock_postgres_runtime import postgres_dsn


BACKEND_ROOT = Path(__file__).resolve().parents[2]
REVIEW_REPAIR_SQL = (
    BACKEND_ROOT / "sql" / "115_ride_economic_review_repair.sql"
).read_text(encoding="utf-8")
TRIBUTE_CONSERVATION_SQL = (
    BACKEND_ROOT / "sql" / "121_tribute_conservation.sql"
).read_text(encoding="utf-8")
AUTHORITATIVE_SQL = (
    BACKEND_ROOT / "sql" / "122_authoritative_ride_metrics.sql"
).read_text(encoding="utf-8")
REWARD_FTP_SQL = (
    BACKEND_ROOT / "sql" / "123_reward_ftp_authority.sql"
).read_text(encoding="utf-8")
DERIVED_SQL = (
    BACKEND_ROOT / "sql" / "154_derived_threshold_authority.sql"
).read_text(encoding="utf-8")


def _install(cursor, before_derived=None) -> None:
    cursor.execute(
        """
        DROP SCHEMA IF EXISTS public CASCADE;
        CREATE SCHEMA public;
        DROP SCHEMA IF EXISTS extensions CASCADE;
        DROP EXTENSION IF EXISTS pgcrypto CASCADE;
        DROP ROLE IF EXISTS anon;
        DROP ROLE IF EXISTS authenticated;
        DROP ROLE IF EXISTS service_role;
        """
    )
    _bootstrap(cursor)
    cursor.execute("CREATE SCHEMA extensions")
    cursor.execute("ALTER EXTENSION pgcrypto SET SCHEMA extensions")
    cursor.execute(REVIEW_REPAIR_SQL)
    cursor.execute(PROVENANCE_SQL)
    cursor.execute(TRIBUTE_CONSERVATION_SQL)
    cursor.execute(AUTHORITATIVE_SQL)
    cursor.execute(
        """
        ALTER TABLE public.rides
            ADD COLUMN file_hash CHAR(64),
            ADD COLUMN uploaded_at TIMESTAMPTZ,
            ADD COLUMN import_diagnostics JSONB,
            ADD COLUMN canonical_match BOOLEAN,
            ADD COLUMN power_verified BOOLEAN;
        ALTER TABLE public.users
            ADD COLUMN account_state TEXT NOT NULL DEFAULT 'active';
        """
    )
    cursor.execute(REWARD_FTP_SQL)
    cursor.execute(
        """
        CREATE OR REPLACE FUNCTION public.br_account_deletion_db_blockers(
            p_user_id UUID, p_wallet TEXT
        ) RETURNS JSONB LANGUAGE sql SECURITY DEFINER SET search_path = '' AS $$
            SELECT '[]'::JSONB
        $$;
        CREATE OR REPLACE FUNCTION
        public.br_account_deletion_assert_wallet_write_allowed(p_wallet TEXT)
        RETURNS VOID LANGUAGE sql SECURITY DEFINER SET search_path = '' AS $$
            SELECT NULL::VOID
        $$;
        CREATE OR REPLACE FUNCTION public.account_deletion_write_fence()
        RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
        DECLARE
            v_user_id UUID;
        BEGIN
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            v_user_id := NULLIF(pg_catalog.to_jsonb(NEW)->>'user_id', '')::UUID;
            IF v_user_id IS NOT NULL AND EXISTS (
                SELECT 1 FROM public.users AS "user"
                WHERE "user".id = v_user_id
                  AND "user".account_state <> 'active'
            ) THEN
                RAISE EXCEPTION 'account_identity_write_fenced'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    if before_derived is not None:
        before_derived(cursor)
    cursor.execute(DERIVED_SQL)


def _insert_ride(
    cursor,
    *,
    user_id: uuid.UUID,
    received_at: datetime,
    eligible: bool = True,
    source_id: uuid.UUID | None = None,
    ride_id: uuid.UUID | None = None,
) -> uuid.UUID:
    ride_id = ride_id or uuid.uuid4()
    source_id = source_id or uuid.uuid4()
    cursor.execute(
        """
        INSERT INTO public.rides (
            id, user_id, file_hash, upload_verified_at, import_diagnostics,
            canonical_match, threshold_recording_source,
            threshold_power_source_id, threshold_source_identity_complete,
            threshold_source_evidence
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        """,
        (
            ride_id,
            user_id,
            "a" * 64,
            received_at,
            Json({"provenance_tier": "first_party_recorded" if eligible else "manual_file_upload"}),
            eligible,
            "br_ios" if eligible else None,
            source_id if eligible else None,
            eligible,
            Json(
                {
                    "recording_source": "br_ios" if eligible else None,
                    "power_source_ids": [str(source_id)] if eligible else [],
                    "identity_complete": eligible,
                    "eligibility_reason": "eligible" if eligible else "not_br_ios_recording",
                }
            ),
        ),
    )
    return ride_id


def _anchors(cp_w: float, work_capacity_j: float = 18_000.0) -> tuple[float, float, float]:
    return tuple(cp_w + work_capacity_j / duration for duration in (180, 420, 900))


def _register(cursor, ride_id: uuid.UUID, cp_w: float, accepted_at: datetime):
    cursor.execute(
        "SELECT * FROM public.register_reward_threshold_effort_at(%s, %s, %s, %s, %s)",
        (ride_id, *_anchors(cp_w), accepted_at),
    )
    return cursor.fetchone()


def _register_anchors(
    cursor,
    ride_id: uuid.UUID,
    anchors: tuple[float | None, float | None, float | None],
    accepted_at: datetime,
):
    cursor.execute(
        "SELECT * FROM public.register_reward_threshold_effort_at(%s, %s, %s, %s, %s)",
        (ride_id, *anchors, accepted_at),
    )
    return cursor.fetchone()


def _wait_for_advisory_waits(connection, backend_pids: list[int]) -> bool:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*)
                FROM pg_catalog.pg_stat_activity
                WHERE pid = ANY(%s)
                  AND wait_event = 'advisory'
                """,
                (backend_pids,),
            )
            if cursor.fetchone()[0] == len(backend_pids):
                return True
        time.sleep(0.02)
    return False


def test_migration_skips_deletion_pending_users_during_legacy_backfill(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection, connection.cursor() as cursor:
        user_id = uuid.uuid4()

        def seed_deletion_pending(seeded) -> None:
            seeded.execute(
                "INSERT INTO public.users (id, account_state) VALUES (%s, 'deletion_pending')",
                (user_id,),
            )
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
                (user_id,),
            )

        _install(cursor, seed_deletion_pending)

        cursor.execute(
            "SELECT count(*) FROM public.reward_threshold_ratchets WHERE user_id=%s",
            (user_id,),
        )
        assert cursor.fetchone()[0] == 0
        cursor.execute(
            """
            SELECT count(*) FROM public.reward_threshold_pending_promotions
            WHERE user_id=%s
            """,
            (user_id,),
        )
        assert cursor.fetchone()[0] == 0


def test_threshold_initializes_from_highest_legacy_and_seals_candidate_less_monday(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            user_id = uuid.uuid4()
            high_authority_id = uuid.uuid4()
            low_authority_id = uuid.uuid4()

            def seed_legacy(seed_cursor) -> None:
                seed_cursor.execute(
                    "INSERT INTO public.users (id) VALUES (%s)", (user_id,)
                )
                seed_cursor.execute(
                    """
                    INSERT INTO public.reward_ftp_authorities (
                        id, user_id, ftp_w, source, evidence, evidence_hash, verified_by,
                        verified_at, effective_at
                    ) VALUES
                        (%s, %s, 250, 'verified_power_test', '{}'::jsonb,
                         pg_catalog.sha256(pg_catalog.convert_to('{}', 'UTF8')),
                         'legacy-test', '2026-01-01', '2026-01-05 12:00+00'),
                        (%s, %s, 225, 'operator_verified', '{}'::jsonb,
                         pg_catalog.sha256(pg_catalog.convert_to('{}', 'UTF8')),
                         'legacy-test', '2026-02-01', '2026-02-02 12:00+00')
                    """,
                    (
                        high_authority_id,
                        user_id,
                        low_authority_id,
                        user_id,
                    ),
                )

            _install(cursor, seed_legacy)
            cursor.execute(
                """
                SELECT sealed_authority_id, sealed_ftp_w, established_at
                FROM public.reward_threshold_ratchets
                WHERE user_id = %s
                """,
                (user_id,),
            )
            assert cursor.fetchone() == (
                high_authority_id,
                250,
                datetime(2026, 1, 5, 12, tzinfo=timezone.utc),
            )
            cursor.execute(
                """
                SELECT candidate_id, baseline_authority_id, promotion_kind,
                       target_ftp_w, effective_at, status
                FROM public.reward_threshold_pending_promotions
                WHERE user_id = %s
                """,
                (user_id,),
            )
            pending = cursor.fetchone()
            assert pending[:4] == (
                None,
                high_authority_id,
                "initialization",
                250,
            )
            initialization_at = pending[4]
            initialization_utc = initialization_at.astimezone(timezone.utc)
            assert initialization_utc.weekday() == 0
            assert (initialization_utc.hour, initialization_utc.minute) == (12, 0)
            assert pending[5] == "pending"

            before_ride = uuid.uuid4()
            cursor.execute(
                """
                INSERT INTO public.rides (id, user_id) VALUES (%s, %s);
                SELECT reward_ftp_w, reward_ftp_authority_id
                FROM public.bind_ride_reward_ftp(%s, %s)
                """,
                (
                    before_ride,
                    user_id,
                    before_ride,
                    initialization_at - timedelta(seconds=1),
                ),
            )
            assert cursor.fetchone() == (225, low_authority_id)

            cursor.execute(
                "SELECT public.seal_due_reward_threshold_promotions_at(%s)",
                (initialization_at,),
            )
            assert cursor.fetchone()[0] == 1
            cursor.execute(
                """
                SELECT ftp_w, source, effective_at,
                       evidence->>'promotion_kind', evidence->>'candidate_id'
                FROM public.reward_ftp_authorities
                WHERE user_id = %s AND source = 'derived_eftp'
                """,
                (user_id,),
            )
            assert cursor.fetchone() == (
                250,
                "derived_eftp",
                initialization_at,
                "initialization",
                None,
            )

            after_ride = uuid.uuid4()
            cursor.execute(
                """
                INSERT INTO public.rides (id, user_id) VALUES (%s, %s);
                SELECT reward_ftp_w, reward_ftp_source
                FROM public.bind_ride_reward_ftp(%s, %s)
                """,
                (
                    after_ride,
                    user_id,
                    after_ride,
                    initialization_at + timedelta(seconds=1),
                ),
            )
            assert cursor.fetchone() == (250, "derived_eftp")


def test_threshold_source_envelopes_never_mix_meter_histories(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            user_id = uuid.uuid4()
            source_a = uuid.uuid4()
            source_b = uuid.uuid4()
            _install(
                cursor,
                lambda seed_cursor: seed_cursor.execute(
                    "INSERT INTO public.users (id) VALUES (%s)", (user_id,)
                ),
            )
            accepted_at = datetime.now(timezone.utc)
            cp_anchors = _anchors(200.0)

            empty = _insert_ride(
                cursor,
                user_id=user_id,
                source_id=source_a,
                received_at=accepted_at,
            )
            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="at least one power anchor",
            ):
                _register_anchors(
                    cursor,
                    empty,
                    (None, None, None),
                    accepted_at + timedelta(milliseconds=500),
                )
            cursor.execute(
                "SELECT count(*) FROM public.reward_threshold_efforts WHERE ride_id=%s",
                (empty,),
            )
            assert cursor.fetchone()[0] == 0

            a_short = _insert_ride(
                cursor,
                user_id=user_id,
                source_id=source_a,
                received_at=accepted_at,
            )
            _register_anchors(
                cursor,
                a_short,
                (cp_anchors[0], None, None),
                accepted_at + timedelta(seconds=1),
            )
            b_long = _insert_ride(
                cursor,
                user_id=user_id,
                source_id=source_b,
                received_at=accepted_at + timedelta(seconds=2),
            )
            _register_anchors(
                cursor,
                b_long,
                (None, cp_anchors[1], cp_anchors[2]),
                accepted_at + timedelta(seconds=3),
            )

            cursor.execute(
                """
                SELECT ride_id, disposition
                FROM public.reward_threshold_candidates
                WHERE ride_id IN (%s, %s)
                ORDER BY ride_id
                """,
                (a_short, b_long),
            )
            assert {row[1] for row in cursor.fetchall()} == {"insufficient_history"}
            cursor.execute(
                "SELECT count(*) FROM public.reward_threshold_pending_promotions"
            )
            assert cursor.fetchone()[0] == 0

            b_short = _insert_ride(
                cursor,
                user_id=user_id,
                source_id=source_b,
                received_at=accepted_at + timedelta(seconds=4),
            )
            _register_anchors(
                cursor,
                b_short,
                (cp_anchors[0], None, None),
                accepted_at + timedelta(seconds=5),
            )
            cursor.execute(
                """
                SELECT disposition, power_source_id, target_ftp_w
                FROM public.reward_threshold_candidates
                WHERE ride_id = %s
                """,
                (b_short,),
            )
            assert cursor.fetchone() == ("pending_establishment", source_b, 200)

            cursor.execute(
                """
                SELECT power_source_id, accepted_best_180s_w,
                       accepted_best_420s_w, accepted_best_900s_w
                FROM public.reward_threshold_source_envelopes
                WHERE user_id = %s
                ORDER BY power_source_id
                """,
                (user_id,),
            )
            envelopes = {row[0]: row[1:] for row in cursor.fetchall()}
            assert float(envelopes[source_a][0]) == pytest.approx(cp_anchors[0])
            assert envelopes[source_a][1:] == (None, None)
            assert tuple(float(value) for value in envelopes[source_b]) == pytest.approx(
                cp_anchors
            )

            a_long = _insert_ride(
                cursor,
                user_id=user_id,
                source_id=source_a,
                received_at=accepted_at + timedelta(seconds=6),
            )
            _register_anchors(
                cursor,
                a_long,
                (None, cp_anchors[1], cp_anchors[2]),
                accepted_at + timedelta(seconds=7),
            )
            cursor.execute(
                """
                SELECT disposition, power_source_id
                FROM public.reward_threshold_candidates
                WHERE ride_id = %s
                """,
                (a_long,),
            )
            disposition, candidate_source = cursor.fetchone()
            assert candidate_source == source_a
            assert disposition in {"pending_establishment", "superseded"}
            cursor.execute(
                """
                SELECT disposition
                FROM public.reward_threshold_candidates
                WHERE ride_id IN (%s, %s)
                """,
                (a_long, b_short),
            )
            assert {row[0] for row in cursor.fetchall()} == {
                "pending_establishment",
                "superseded",
            }

            source_c = uuid.uuid4()
            extreme_short = _insert_ride(
                cursor,
                user_id=user_id,
                source_id=source_c,
                received_at=accepted_at + timedelta(seconds=8),
            )
            _register_anchors(
                cursor,
                extreme_short,
                (2000.0, None, None),
                accepted_at + timedelta(seconds=9),
            )
            completes_invalid_fit = _insert_ride(
                cursor,
                user_id=user_id,
                source_id=source_c,
                received_at=accepted_at + timedelta(seconds=10),
            )
            _register_anchors(
                cursor,
                completes_invalid_fit,
                (None, 300.0, 250.0),
                accepted_at + timedelta(seconds=11),
            )
            cursor.execute(
                """
                SELECT accepted_best_180s_w, accepted_best_420s_w,
                       accepted_best_900s_w, accepted_candidate_w
                FROM public.reward_threshold_source_envelopes
                WHERE user_id=%s AND power_source_id=%s
                """,
                (user_id, source_c),
            )
            assert cursor.fetchone() == (2000, 300, 250, None)


def test_power_verified_without_structural_source_remains_display_only(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            user_id = uuid.uuid4()
            _install(
                cursor,
                lambda seed_cursor: seed_cursor.execute(
                    "INSERT INTO public.users (id) VALUES (%s)", (user_id,)
                ),
            )
            received_at = datetime.now(timezone.utc)
            ride_id = _insert_ride(
                cursor,
                user_id=user_id,
                received_at=received_at,
                eligible=False,
            )
            cursor.execute(
                "UPDATE public.rides SET power_verified = TRUE WHERE id = %s",
                (ride_id,),
            )
            _register(
                cursor,
                ride_id,
                300.0,
                received_at + timedelta(seconds=1),
            )
            cursor.execute(
                """
                SELECT disposition, power_source_id, economic_candidate_w
                FROM public.reward_threshold_candidates
                WHERE ride_id = %s
                """,
                (ride_id,),
            )
            assert cursor.fetchone() == ("display_only", None, None)
            cursor.execute(
                """
                SELECT display_candidate_w
                FROM public.reward_threshold_ratchets
                WHERE user_id = %s
                """,
                (user_id,),
            )
            assert float(cursor.fetchone()[0]) == pytest.approx(300.0, abs=1e-6)
            cursor.execute(
                "SELECT count(*) FROM public.reward_threshold_source_envelopes"
            )
            assert cursor.fetchone()[0] == 0
            cursor.execute(
                "SELECT count(*) FROM public.reward_threshold_pending_promotions"
            )
            assert cursor.fetchone()[0] == 0


def test_threshold_raw_deadband_ceil_projection_and_review_do_not_poison_state(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            user_id = uuid.uuid4()
            source_id = uuid.uuid4()

            def seed_legacy(seed_cursor) -> None:
                seed_cursor.execute(
                    "INSERT INTO public.users (id) VALUES (%s)", (user_id,)
                )
                seed_cursor.execute(
                    """
                    INSERT INTO public.reward_ftp_authorities (
                        user_id, ftp_w, source, evidence, evidence_hash,
                        verified_by, verified_at, effective_at
                    ) VALUES (
                        %s, 201, 'verified_power_test', '{}'::jsonb,
                        pg_catalog.sha256(pg_catalog.convert_to('{}', 'UTF8')),
                        'legacy-test', '2026-01-05 12:00+00',
                        '2026-01-05 12:00+00'
                    )
                    """,
                    (user_id,),
                )

            _install(cursor, seed_legacy)
            accepted_at = datetime.now(timezone.utc)

            below = _insert_ride(
                cursor,
                user_id=user_id,
                source_id=source_id,
                received_at=accepted_at,
            )
            _register(
                cursor,
                below,
                206.0249,
                accepted_at + timedelta(seconds=1),
            )
            cursor.execute(
                "SELECT disposition FROM public.reward_threshold_candidates WHERE ride_id=%s",
                (below,),
            )
            assert cursor.fetchone()[0] == "below_deadband"

            exact = _insert_ride(
                cursor,
                user_id=user_id,
                source_id=source_id,
                received_at=accepted_at + timedelta(seconds=2),
            )
            _register(
                cursor,
                exact,
                206.025,
                accepted_at + timedelta(seconds=3),
            )
            cursor.execute(
                """
                SELECT candidate.disposition, candidate.target_ftp_w,
                       pending.effective_at
                FROM public.reward_threshold_candidates AS candidate
                JOIN public.reward_threshold_pending_promotions AS pending
                  ON pending.candidate_id = candidate.id
                WHERE candidate.ride_id = %s
                """,
                (exact,),
            )
            disposition, target_w, target_at = cursor.fetchone()
            assert (disposition, target_w) == ("pending_raise", 207)

            review = _insert_ride(
                cursor,
                user_id=user_id,
                source_id=source_id,
                received_at=accepted_at + timedelta(seconds=4),
            )
            _register(
                cursor,
                review,
                501.0,
                accepted_at + timedelta(seconds=5),
            )
            cursor.execute(
                """
                SELECT candidate.disposition, envelope.accepted_candidate_w,
                       pending.target_ftp_w
                FROM public.reward_threshold_candidates AS candidate
                JOIN public.reward_threshold_source_envelopes AS envelope
                  ON envelope.user_id = candidate.user_id
                 AND envelope.power_source_id = candidate.power_source_id
                JOIN public.reward_threshold_pending_promotions AS pending
                  ON pending.user_id = candidate.user_id
                 AND pending.status = 'pending'
                WHERE candidate.ride_id = %s
                """,
                (review,),
            )
            review_disposition, accepted_candidate, pending_target = cursor.fetchone()
            assert review_disposition == "above_bounds_review"
            assert float(accepted_candidate) == pytest.approx(206.025, abs=1e-6)
            assert pending_target == 207
            cursor.execute(
                """
                SELECT display_candidate_w
                FROM public.reward_threshold_ratchets
                WHERE user_id = %s
                """,
                (user_id,),
            )
            assert float(cursor.fetchone()[0]) == pytest.approx(206.025, abs=1e-6)

            cursor.execute(
                "SELECT public.seal_due_reward_threshold_promotions_at(%s)",
                (target_at,),
            )
            assert cursor.fetchone()[0] == 1
            cursor.execute(
                """
                SELECT ftp_w, evidence->>'rounding'
                FROM public.reward_ftp_authorities
                WHERE user_id = %s AND source = 'derived_eftp'
                """,
                (user_id,),
            )
            assert cursor.fetchone() == (207, "ceil_after_raw_deadband")


def test_cumulative_duration_bests_cross_deadband_and_weaker_pending_cannot_replace(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            user_id = uuid.uuid4()
            source_id = uuid.uuid4()

            def seed_legacy(seed_cursor) -> None:
                seed_cursor.execute(
                    "INSERT INTO public.users (id) VALUES (%s)", (user_id,)
                )
                seed_cursor.execute(
                    """
                    INSERT INTO public.reward_ftp_authorities (
                        user_id, ftp_w, source, evidence, evidence_hash,
                        verified_by, effective_at
                    ) VALUES (
                        %s, 250, 'verified_power_test', '{}'::jsonb,
                        pg_catalog.sha256(pg_catalog.convert_to('{}', 'UTF8')),
                        'legacy-test', '2026-01-05 12:00+00'
                    )
                    """,
                    (user_id,),
                )

            _install(cursor, seed_legacy)
            cursor.execute(
                """
                SELECT effective_at
                FROM public.reward_threshold_pending_promotions
                WHERE user_id = %s
                """,
                (user_id,),
            )
            boundary = cursor.fetchone()[0]
            base = _anchors(250.0)

            base_ride = _insert_ride(
                cursor,
                user_id=user_id,
                source_id=source_id,
                received_at=boundary - timedelta(days=3),
            )
            _register_anchors(
                cursor,
                base_ride,
                base,
                boundary - timedelta(days=3) + timedelta(seconds=1),
            )
            medium_ride = _insert_ride(
                cursor,
                user_id=user_id,
                source_id=source_id,
                received_at=boundary - timedelta(days=2),
            )
            _register_anchors(
                cursor,
                medium_ride,
                (None, base[1] + 5.0, None),
                boundary - timedelta(days=2) + timedelta(seconds=1),
            )
            cursor.execute(
                "SELECT disposition FROM public.reward_threshold_candidates WHERE ride_id=%s",
                (medium_ride,),
            )
            assert cursor.fetchone()[0] == "below_deadband"

            long_ride = _insert_ride(
                cursor,
                user_id=user_id,
                source_id=source_id,
                received_at=boundary - timedelta(days=1),
            )
            _register_anchors(
                cursor,
                long_ride,
                (None, None, base[2] + 5.0),
                boundary - timedelta(days=1) + timedelta(seconds=1),
            )
            cursor.execute(
                """
                SELECT id, economic_candidate_w, target_ftp_w
                FROM public.reward_threshold_candidates
                WHERE ride_id=%s
                """,
                (long_ride,),
            )
            strong_candidate_id, strong_raw, strong_target = cursor.fetchone()
            assert float(strong_raw) > 256.25
            assert strong_target == 257

            weaker_ride = _insert_ride(
                cursor,
                user_id=user_id,
                source_id=uuid.uuid4(),
                received_at=boundary - timedelta(hours=12),
            )
            _register(
                cursor,
                weaker_ride,
                256.5,
                boundary - timedelta(hours=12) + timedelta(seconds=1),
            )
            cursor.execute(
                """
                SELECT candidate_id, target_candidate_w, target_ftp_w
                FROM public.reward_threshold_pending_promotions
                WHERE user_id=%s AND status='pending'
                """,
                (user_id,),
            )
            pending_candidate_id, pending_raw, pending_target = cursor.fetchone()
            assert pending_candidate_id == strong_candidate_id
            assert float(pending_raw) == pytest.approx(float(strong_raw), abs=1e-6)
            assert pending_target == 257


def test_registration_after_monday_seals_due_baseline_before_deadband(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            user_id = uuid.uuid4()

            def seed_legacy(seed_cursor) -> None:
                seed_cursor.execute(
                    "INSERT INTO public.users (id) VALUES (%s)", (user_id,)
                )
                seed_cursor.execute(
                    """
                    INSERT INTO public.reward_ftp_authorities (
                        user_id, ftp_w, source, evidence, evidence_hash,
                        verified_by, effective_at
                    ) VALUES (
                        %s, 200, 'verified_power_test', '{}'::jsonb,
                        pg_catalog.sha256(pg_catalog.convert_to('{}', 'UTF8')),
                        'legacy-test', '2026-01-05 12:00+00'
                    )
                    """,
                    (user_id,),
                )

            _install(cursor, seed_legacy)
            cursor.execute(
                """
                SELECT effective_at
                FROM public.reward_threshold_pending_promotions
                WHERE user_id = %s
                """,
                (user_id,),
            )
            boundary = cursor.fetchone()[0]

            due_ride = _insert_ride(
                cursor,
                user_id=user_id,
                received_at=boundary - timedelta(days=1),
            )
            _register(
                cursor,
                due_ride,
                205.0,
                boundary - timedelta(days=1) + timedelta(seconds=1),
            )

            after_ride = _insert_ride(
                cursor,
                user_id=user_id,
                received_at=boundary + timedelta(seconds=1),
            )
            _register(
                cursor,
                after_ride,
                207.0,
                boundary + timedelta(seconds=2),
            )
            cursor.execute(
                """
                SELECT disposition, baseline_ftp_w
                FROM public.reward_threshold_candidates
                WHERE ride_id = %s
                """,
                (after_ride,),
            )
            assert cursor.fetchone() == ("below_deadband", 205)
            cursor.execute(
                """
                SELECT ftp_w, effective_at
                FROM public.reward_ftp_authorities
                WHERE user_id = %s AND source = 'derived_eftp'
                """,
                (user_id,),
            )
            assert cursor.fetchall() == [(205, boundary)]
            cursor.execute(
                """
                SELECT count(*)
                FROM public.reward_threshold_pending_promotions
                WHERE user_id = %s AND status = 'pending'
                """,
                (user_id,),
            )
            assert cursor.fetchone()[0] == 0


def test_upload_before_boundary_coalesces_after_acceptance_without_reopening_snapshot(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            user_id = uuid.uuid4()

            def seed_legacy(seed_cursor) -> None:
                seed_cursor.execute(
                    "INSERT INTO public.users (id) VALUES (%s)", (user_id,)
                )
                seed_cursor.execute(
                    """
                    INSERT INTO public.reward_ftp_authorities (
                        user_id, ftp_w, source, evidence, evidence_hash,
                        verified_by, effective_at
                    ) VALUES (
                        %s, 200, 'verified_power_test', '{}'::jsonb,
                        pg_catalog.sha256(pg_catalog.convert_to('{}', 'UTF8')),
                        'legacy-test', '2026-01-05 12:00+00'
                    )
                    """,
                    (user_id,),
                )

            _install(cursor, seed_legacy)
            cursor.execute(
                """
                SELECT effective_at
                FROM public.reward_threshold_pending_promotions
                WHERE user_id = %s
                """,
                (user_id,),
            )
            boundary = cursor.fetchone()[0]

            first = _insert_ride(
                cursor,
                user_id=user_id,
                received_at=boundary - timedelta(days=1),
            )
            _register(
                cursor,
                first,
                205.0,
                boundary - timedelta(days=1) + timedelta(seconds=1),
            )

            old_activity = _insert_ride(
                cursor,
                user_id=user_id,
                received_at=boundary - timedelta(seconds=1),
            )
            activity_started_at = datetime(2026, 1, 12, 12, tzinfo=timezone.utc)
            cursor.execute(
                """
                SELECT reward_ftp_w, reward_ftp_source
                FROM public.bind_ride_reward_ftp(%s, %s)
                """,
                (old_activity, activity_started_at),
            )
            assert cursor.fetchone() == (200, "verified_power_test")

            _register(
                cursor,
                old_activity,
                207.0,
                boundary + timedelta(seconds=1),
            )
            cursor.execute(
                """
                SELECT disposition, target_ftp_w, target_effective_at
                FROM public.reward_threshold_candidates
                WHERE ride_id = %s
                """,
                (old_activity,),
            )
            assert cursor.fetchone() == ("below_deadband", None, None)
            cursor.execute(
                """
                SELECT ftp_w, effective_at
                FROM public.reward_ftp_authorities
                WHERE user_id = %s AND source = 'derived_eftp'
                """,
                (user_id,),
            )
            assert cursor.fetchall() == [(205, boundary)]
            cursor.execute(
                """
                SELECT reward_ftp_w, reward_ftp_source
                FROM public.rides WHERE id = %s
                """,
                (old_activity,),
            )
            assert cursor.fetchone() == (200, "verified_power_test")

            already_sealed = _insert_ride(
                cursor,
                user_id=user_id,
                received_at=boundary - timedelta(seconds=2),
            )
            _register(
                cursor,
                already_sealed,
                213.0,
                boundary + timedelta(seconds=2),
            )
            cursor.execute(
                """
                SELECT target_ftp_w, target_effective_at
                FROM public.reward_threshold_candidates
                WHERE ride_id = %s
                """,
                (already_sealed,),
            )
            assert cursor.fetchone() == (
                213,
                boundary + timedelta(days=7),
            )


def test_binding_waits_for_the_same_user_sealer_before_freezing_snapshot(
    postgres_dsn: str,
) -> None:
    user_id = uuid.uuid4()
    ride_id = uuid.uuid4()

    with _connection(postgres_dsn) as setup_connection:
        with setup_connection.cursor() as setup_cursor:
            def seed_legacy(seed_cursor) -> None:
                seed_cursor.execute(
                    "INSERT INTO public.users (id) VALUES (%s)", (user_id,)
                )
                seed_cursor.execute(
                    """
                    INSERT INTO public.reward_ftp_authorities (
                        user_id, ftp_w, source, evidence, evidence_hash,
                        verified_by, effective_at
                    ) VALUES (
                        %s, 200, 'verified_power_test', '{}'::jsonb,
                        pg_catalog.sha256(pg_catalog.convert_to('{}', 'UTF8')),
                        'legacy-test', '2026-01-05 12:00+00'
                    )
                    """,
                    (user_id,),
                )

            _install(setup_cursor, seed_legacy)
            setup_cursor.execute(
                """
                SELECT effective_at
                FROM public.reward_threshold_pending_promotions
                WHERE user_id = %s
                """,
                (user_id,),
            )
            boundary = setup_cursor.fetchone()[0]
            setup_cursor.execute(
                "INSERT INTO public.rides (id, user_id) VALUES (%s, %s)",
                (ride_id, user_id),
            )

        sealer_connection = psycopg2.connect(postgres_dsn)
        binder_connection = psycopg2.connect(postgres_dsn)
        sealer_connection.autocommit = False
        binder_connection.autocommit = True
        result: list[tuple[int, str]] = []
        errors: list[BaseException] = []
        try:
            with sealer_connection.cursor() as sealer_cursor:
                sealer_cursor.execute(
                    """
                    SELECT pg_catalog.pg_advisory_xact_lock(
                        pg_catalog.hashtextextended(%s, 2982)
                    )
                    """,
                    (str(user_id),),
                )

            binder_pid = binder_connection.get_backend_pid()

            def bind_ride() -> None:
                try:
                    with binder_connection.cursor() as binder_cursor:
                        binder_cursor.execute("SET lock_timeout = '10s'")
                        binder_cursor.execute(
                            """
                            SELECT reward_ftp_w, reward_ftp_source
                            FROM public.bind_ride_reward_ftp(%s, %s)
                            """,
                            (ride_id, boundary + timedelta(seconds=1)),
                        )
                        result.append(binder_cursor.fetchone())
                except BaseException as exc:  # pragma: no cover - surfaced below
                    errors.append(exc)

            thread = threading.Thread(target=bind_ride, daemon=True)
            thread.start()

            wait_deadline = time.monotonic() + 5
            observed_advisory_wait = False
            while time.monotonic() < wait_deadline:
                with setup_connection.cursor() as setup_cursor:
                    setup_cursor.execute(
                        """
                        SELECT wait_event
                        FROM pg_catalog.pg_stat_activity
                        WHERE pid = %s
                        """,
                        (binder_pid,),
                    )
                    row = setup_cursor.fetchone()
                if row and row[0] == "advisory":
                    observed_advisory_wait = True
                    break
                time.sleep(0.02)
            assert observed_advisory_wait is True

            with sealer_connection.cursor() as sealer_cursor:
                sealer_cursor.execute(
                    """
                    SELECT public.seal_due_reward_threshold_promotions_for_user_at(
                        %s, %s
                    )
                    """,
                    (user_id, boundary),
                )
                assert sealer_cursor.fetchone()[0] == 1
            sealer_connection.commit()

            thread.join(timeout=5)
            assert thread.is_alive() is False
            assert errors == []
            assert result == [(200, "derived_eftp")]
        finally:
            if sealer_connection.closed == 0:
                sealer_connection.rollback()
                sealer_connection.close()
            if binder_connection.closed == 0:
                binder_connection.close()


def test_concurrent_registration_and_sealing_coalesce_once_and_replay_is_inert(
    postgres_dsn: str,
) -> None:
    user_id = uuid.uuid4()
    source_id = uuid.uuid4()
    ride_ids = [uuid.uuid4(), uuid.uuid4()]

    with _connection(postgres_dsn) as setup_connection:
        with setup_connection.cursor() as setup_cursor:
            _install(
                setup_cursor,
                lambda seed_cursor: seed_cursor.execute(
                    "INSERT INTO public.users (id) VALUES (%s)", (user_id,)
                ),
            )
            setup_cursor.execute(
                "SELECT public.next_reward_threshold_monday(clock_timestamp())"
            )
            boundary = setup_cursor.fetchone()[0]
            received_at = boundary - timedelta(days=2)
            for ride_id in ride_ids:
                _insert_ride(
                    setup_cursor,
                    user_id=user_id,
                    source_id=source_id,
                    received_at=received_at,
                    ride_id=ride_id,
                )

        gate_connection = psycopg2.connect(postgres_dsn)
        gate_connection.autocommit = True
        register_connections = [psycopg2.connect(postgres_dsn) for _ in ride_ids]
        for connection in register_connections:
            connection.autocommit = True
        registration_errors: list[BaseException] = []
        try:
            with gate_connection.cursor() as gate_cursor:
                gate_cursor.execute(
                    "SELECT pg_catalog.pg_advisory_lock(pg_catalog.hashtextextended(%s, 2982))",
                    (str(user_id),),
                )

            def register(index: int, cp_w: float) -> None:
                try:
                    with register_connections[index].cursor() as cursor:
                        cursor.execute(
                            """
                            SELECT *
                            FROM public.register_reward_threshold_effort_at(
                                %s, %s, %s, %s, %s
                            )
                            """,
                            (
                                ride_ids[index],
                                *_anchors(cp_w),
                                boundary - timedelta(days=1),
                            ),
                        )
                        cursor.fetchone()
                except BaseException as exc:  # pragma: no cover - surfaced below
                    registration_errors.append(exc)

            register_threads = [
                threading.Thread(target=register, args=(0, 260.0), daemon=True),
                threading.Thread(target=register, args=(1, 270.0), daemon=True),
            ]
            for thread in register_threads:
                thread.start()
            assert _wait_for_advisory_waits(
                setup_connection,
                [connection.get_backend_pid() for connection in register_connections],
            )
            with gate_connection.cursor() as gate_cursor:
                gate_cursor.execute(
                    "SELECT pg_catalog.pg_advisory_unlock(pg_catalog.hashtextextended(%s, 2982))",
                    (str(user_id),),
                )
                assert gate_cursor.fetchone()[0] is True
            for thread in register_threads:
                thread.join(timeout=5)
                assert thread.is_alive() is False
            assert registration_errors == []

            with setup_connection.cursor() as setup_cursor:
                setup_cursor.execute(
                    """
                    SELECT count(*), max(economic_candidate_w)
                    FROM public.reward_threshold_candidates
                    WHERE user_id = %s
                    """,
                    (user_id,),
                )
                candidate_count, maximum_candidate = setup_cursor.fetchone()
                assert candidate_count == 2
                assert float(maximum_candidate) == pytest.approx(270.0, abs=1e-6)
                setup_cursor.execute(
                    """
                    SELECT count(*), max(target_ftp_w)
                    FROM public.reward_threshold_pending_promotions
                    WHERE user_id = %s AND status = 'pending'
                    """,
                    (user_id,),
                )
                assert setup_cursor.fetchone() == (1, 270)
                setup_cursor.execute(
                    """
                    SELECT accepted_candidate_w
                    FROM public.reward_threshold_source_envelopes
                    WHERE user_id = %s AND power_source_id = %s
                    """,
                    (user_id, source_id),
                )
                assert float(setup_cursor.fetchone()[0]) == pytest.approx(270.0, abs=1e-6)

                _register(
                    setup_cursor,
                    ride_ids[0],
                    499.0,
                    boundary - timedelta(hours=12),
                )
                setup_cursor.execute(
                    """
                    SELECT
                        (SELECT count(*) FROM public.reward_threshold_efforts WHERE user_id=%s),
                        (SELECT count(*) FROM public.reward_threshold_candidates WHERE user_id=%s),
                        (SELECT count(*) FROM public.reward_threshold_pending_promotions
                         WHERE user_id=%s AND status='pending')
                    """,
                    (user_id, user_id, user_id),
                )
                assert setup_cursor.fetchone() == (2, 2, 1)

                with pytest.raises(
                    psycopg2.errors.RaiseException,
                    match="upload verification time is immutable",
                ):
                    setup_cursor.execute(
                        "UPDATE public.rides SET upload_verified_at = upload_verified_at + interval '1 second' WHERE id=%s",
                        (ride_ids[0],),
                    )
                with pytest.raises(
                    psycopg2.errors.RaiseException,
                    match="source evidence is immutable",
                ):
                    setup_cursor.execute(
                        "UPDATE public.rides SET threshold_power_source_id = %s WHERE id=%s",
                        (uuid.uuid4(), ride_ids[0]),
                    )

            sealer_connections = [psycopg2.connect(postgres_dsn) for _ in range(2)]
            for connection in sealer_connections:
                connection.autocommit = True
            seal_results: list[int] = []
            seal_errors: list[BaseException] = []
            with gate_connection.cursor() as gate_cursor:
                gate_cursor.execute(
                    "SELECT pg_catalog.pg_advisory_lock(pg_catalog.hashtextextended(%s, 2982))",
                    (str(user_id),),
                )

            def seal(index: int) -> None:
                try:
                    with sealer_connections[index].cursor() as cursor:
                        cursor.execute(
                            "SELECT public.seal_due_reward_threshold_promotions_at(%s)",
                            (boundary,),
                        )
                        seal_results.append(cursor.fetchone()[0])
                except BaseException as exc:  # pragma: no cover - surfaced below
                    seal_errors.append(exc)

            seal_threads = [
                threading.Thread(target=seal, args=(index,), daemon=True)
                for index in range(2)
            ]
            for thread in seal_threads:
                thread.start()
            assert _wait_for_advisory_waits(
                setup_connection,
                [connection.get_backend_pid() for connection in sealer_connections],
            )
            with gate_connection.cursor() as gate_cursor:
                gate_cursor.execute(
                    "SELECT pg_catalog.pg_advisory_unlock(pg_catalog.hashtextextended(%s, 2982))",
                    (str(user_id),),
                )
                assert gate_cursor.fetchone()[0] is True
            for thread in seal_threads:
                thread.join(timeout=5)
                assert thread.is_alive() is False
            assert seal_errors == []
            assert sorted(seal_results) == [0, 1]

            with setup_connection.cursor() as setup_cursor:
                setup_cursor.execute(
                    """
                    SELECT count(*), max(ftp_w)
                    FROM public.reward_ftp_authorities
                    WHERE user_id=%s AND source='derived_eftp'
                    """,
                    (user_id,),
                )
                assert setup_cursor.fetchone() == (1, 270)
                setup_cursor.execute(
                    "SELECT public.seal_due_reward_threshold_promotions_at(%s)",
                    (boundary,),
                )
                assert setup_cursor.fetchone()[0] == 0
        finally:
            for connection in register_connections:
                connection.close()
            for connection in locals().get("sealer_connections", []):
                connection.close()
            gate_connection.close()


def test_threshold_deadband_bounds_forward_time_and_policy_compatibility(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            user_id = uuid.uuid4()
            high_user_id = uuid.uuid4()
            old_ride = uuid.uuid4()

            def seed_old_snapshot(seed_cursor) -> None:
                seed_cursor.execute(
                    "INSERT INTO public.users (id) VALUES (%s), (%s)",
                    (user_id, high_user_id),
                )
                seed_cursor.execute(
                    "INSERT INTO public.rides (id, user_id) VALUES (%s, %s)",
                    (old_ride, user_id),
                )
                seed_cursor.execute(
                    "SELECT * FROM public.bind_ride_reward_ftp(%s, %s)",
                    (old_ride, datetime(2026, 8, 1, tzinfo=timezone.utc)),
                )
                seed_cursor.execute(
                    """
                    INSERT INTO public.reward_ftp_authorities (
                        user_id, ftp_w, source, evidence, evidence_hash,
                        verified_by, verified_at, effective_at
                    ) VALUES (
                        %s, 200, 'verified_power_test', '{}'::jsonb,
                        pg_catalog.sha256(pg_catalog.convert_to('{}', 'UTF8')),
                        'legacy-test', '2026-08-17 12:00+00',
                        '2026-08-17 12:00+00'
                    )
                    """,
                    (user_id,),
                )

            _install(cursor, seed_old_snapshot)

            below = _insert_ride(
                cursor,
                user_id=user_id,
                received_at=datetime(2026, 8, 24, 12, tzinfo=timezone.utc),
            )
            _register(
                cursor,
                below,
                204.99,
                datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc),
            )
            cursor.execute(
                "SELECT disposition FROM public.reward_threshold_candidates WHERE ride_id = %s",
                (below,),
            )
            assert cursor.fetchone()[0] == "below_deadband"

            crossing = _insert_ride(
                cursor,
                user_id=user_id,
                received_at=datetime(2026, 8, 24, 12, 0, 1, tzinfo=timezone.utc),
            )
            _register(
                cursor,
                crossing,
                205.0,
                datetime(2026, 8, 24, 12, 0, 2, tzinfo=timezone.utc),
            )
            cursor.execute(
                """
                SELECT target_ftp_w, effective_at
                FROM public.reward_threshold_pending_promotions
                WHERE user_id = %s
                """,
                (user_id,),
            )
            assert cursor.fetchone() == (
                205,
                datetime(2026, 8, 31, 12, tzinfo=timezone.utc),
            )

            implausible = _insert_ride(
                cursor,
                user_id=high_user_id,
                received_at=datetime(2026, 8, 25, 8, tzinfo=timezone.utc),
            )
            _register(
                cursor,
                implausible,
                501.0,
                datetime(2026, 8, 25, 8, 1, tzinfo=timezone.utc),
            )
            cursor.execute(
                "SELECT disposition FROM public.reward_threshold_candidates WHERE ride_id = %s",
                (implausible,),
            )
            assert cursor.fetchone()[0] == "above_bounds_review"
            cursor.execute(
                "SELECT count(*) FROM public.reward_threshold_pending_promotions WHERE user_id = %s",
                (high_user_id,),
            )
            assert cursor.fetchone()[0] == 0

            new_ride = uuid.uuid4()
            cursor.execute(
                "INSERT INTO public.rides (id, user_id) VALUES (%s, %s)",
                (new_ride, user_id),
            )
            cursor.execute(
                "SELECT reward_ftp_policy_version FROM public.bind_ride_reward_ftp(%s, %s)",
                (old_ride, datetime(2026, 8, 1, tzinfo=timezone.utc)),
            )
            assert cursor.fetchone()[0] == "reward_ftp_policy_2026_07_14"
            cursor.execute(
                "SELECT reward_ftp_policy_version FROM public.bind_ride_reward_ftp(%s, %s)",
                (new_ride, datetime(2026, 8, 18, tzinfo=timezone.utc)),
            )
            assert cursor.fetchone()[0] == "reward_ftp_policy_2026_08_24_threshold_v1"

            cursor.execute(
                "SELECT public.next_reward_threshold_monday('2026-08-24 12:00+00')"
            )
            assert cursor.fetchone()[0] == datetime(2026, 8, 31, 12, tzinfo=timezone.utc)

            cursor.execute(
                """
                SELECT
                    has_function_privilege(
                        'service_role',
                        'public.register_reward_ftp_authority(uuid,integer,text,jsonb,text,timestamptz)',
                        'EXECUTE'
                    ),
                    has_function_privilege(
                        'service_role',
                        'public.register_reward_threshold_effort(uuid,numeric,numeric,numeric)',
                        'EXECUTE'
                    ),
                    has_function_privilege(
                        'service_role',
                        'public.seal_due_reward_threshold_promotions()',
                        'EXECUTE'
                    ),
                    has_function_privilege(
                        'authenticated',
                        'public.register_reward_threshold_effort(uuid,numeric,numeric,numeric)',
                        'EXECUTE'
                    )
                """
            )
            assert cursor.fetchone() == (False, True, True, False)

            cursor.execute(
                """
                SELECT relname, relrowsecurity
                FROM pg_catalog.pg_class
                WHERE relnamespace = 'public'::regnamespace
                  AND relname = ANY(%s)
                ORDER BY relname
                """,
                (
                    [
                        "reward_threshold_candidates",
                        "reward_threshold_efforts",
                        "reward_threshold_pending_promotions",
                        "reward_threshold_ratchets",
                        "reward_threshold_source_envelopes",
                    ],
                ),
            )
            rls_rows = cursor.fetchall()
            assert len(rls_rows) == 5
            assert all(enabled is True for _, enabled in rls_rows)
            for table_name, _ in rls_rows:
                cursor.execute(
                    """
                    SELECT
                        has_table_privilege('anon', %s, 'SELECT'),
                        has_table_privilege('authenticated', %s, 'SELECT'),
                        has_table_privilege('service_role', %s, 'INSERT,UPDATE,DELETE')
                    """,
                    (
                        f"public.{table_name}",
                        f"public.{table_name}",
                        f"public.{table_name}",
                    ),
                )
                assert cursor.fetchone() == (False, False, False)

            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="derived-only after Threshold cutover",
            ):
                cursor.execute(
                    """
                    INSERT INTO public.reward_ftp_authorities (
                        user_id, ftp_w, source, evidence, evidence_hash,
                        verified_by, effective_at
                    ) VALUES (
                        %s, 210, 'operator_verified', '{}'::jsonb,
                        pg_catalog.sha256(pg_catalog.convert_to('{}', 'UTF8')),
                        'forbidden-test', '2026-09-07 12:00+00'
                    )
                    """,
                    (user_id,),
                )

            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="seal Monday at 12:00 UTC",
            ):
                cursor.execute(
                    """
                    INSERT INTO public.reward_ftp_authorities (
                        user_id, ftp_w, source, evidence, evidence_hash,
                        verified_by, effective_at
                    ) VALUES (
                        %s, 300, 'derived_eftp', '{}'::jsonb,
                        pg_catalog.sha256(pg_catalog.convert_to('{}', 'UTF8')),
                        'derived-threshold-v1', '2026-09-01 12:00+00'
                    )
                    """,
                    (user_id,),
                )

            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="cannot lower lifetime authority",
            ):
                cursor.execute(
                    """
                    INSERT INTO public.reward_ftp_authorities (
                        user_id, ftp_w, source, evidence, evidence_hash,
                        verified_by, effective_at
                    ) VALUES (
                        %s, 199, 'derived_eftp', '{}'::jsonb,
                        pg_catalog.sha256(pg_catalog.convert_to('{}', 'UTF8')),
                        'derived-threshold-v1', '2026-09-07 12:00+00'
                    )
                    """,
                    (user_id,),
                )

            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="lacks its pending commitment",
            ):
                cursor.execute(
                    """
                    INSERT INTO public.reward_ftp_authorities (
                        user_id, ftp_w, source, evidence, evidence_hash,
                        verified_by, effective_at
                    ) VALUES (
                        %s, 300, 'derived_eftp',
                        jsonb_build_object(
                            'policy_version', 'reward_ftp_policy_2026_08_24_threshold_v1',
                            'model_version', 'threshold_cp_3_7_15_v1'
                        ),
                        pg_catalog.sha256(pg_catalog.convert_to('{}', 'UTF8')),
                        'derived-threshold-v1', '2026-09-07 12:00+00'
                    )
                    """,
                    (user_id,),
                )

            with pytest.raises(psycopg2.errors.RaiseException, match="append-only"):
                cursor.execute(
                    "UPDATE public.reward_threshold_efforts SET best_180s_w=1 WHERE ride_id=%s",
                    (below,),
                )
