"""PostgreSQL runtime proof for Threshold holds and establishment release batches."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
from pathlib import Path
import threading
from typing import Any
import uuid

import psycopg2
from psycopg2.extras import Json, register_uuid
import pytest

from backend.tests.repositories.test_derived_threshold_authority_postgres_runtime import (
    _connection,
    _insert_ride,
    _install,
    _register,
)
from backend.tests.repositories.test_derived_threshold_authority_findings_postgres_runtime import (
    _install_with_account_deletion,
)
from backend.tests.services.test_settlement_clock_postgres_runtime import postgres_dsn
from backend.tests.sql.test_account_deletion_migration_runtime import (
    WALLET,
    _create_request,
    _insert_user,
)


BACKEND_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = BACKEND_ROOT / "sql" / "155_threshold_provisional_hold.sql"
RIDER_PROJECTION_MIGRATION_PATH = (
    BACKEND_ROOT / "sql" / "156_threshold_rider_projection.sql"
)
SEGMENT_TSS_RELEASE_MIGRATION_PATH = (
    BACKEND_ROOT / "sql" / "158_segment_tss_threshold_release.sql"
)
register_uuid()


def _migration_sql() -> str:
    assert MIGRATION_PATH.exists(), "migration 155 must own the Threshold hold authority"
    return MIGRATION_PATH.read_text(encoding="utf-8")


def _digest(label: str) -> bytes:
    return hashlib.sha256(label.encode("utf-8")).digest()


def _install_hold_release_deletion_integration(cursor: Any) -> None:
    _install_with_account_deletion(cursor)
    cursor.execute(
        """
        CREATE TABLE public.reward_threshold_provisional_holds (
            id UUID PRIMARY KEY DEFAULT pg_catalog.gen_random_uuid(),
            user_id UUID NOT NULL
        );
        CREATE TABLE public.reward_threshold_release_batches (
            id UUID PRIMARY KEY DEFAULT pg_catalog.gen_random_uuid(),
            user_id UUID NOT NULL
        );
        CREATE TABLE public.reward_threshold_release_snapshots (
            id UUID PRIMARY KEY DEFAULT pg_catalog.gen_random_uuid(),
            user_id UUID NOT NULL
        );
        CREATE TABLE public.indexed_held_ride_release_authorities (
            pda TEXT PRIMARY KEY,
            rider_pubkey TEXT NOT NULL
        );
        """
    )
    migration = _migration_sql()
    integration_start = migration.index(
        "-- Migration 154 extended the account-deletion policy gate"
    )
    integration_end = migration.index(
        "CREATE OR REPLACE FUNCTION public.validate_reward_threshold_release_snapshot"
    )
    cursor.execute(migration[integration_start:integration_end])


_RELEASE_PLAN_EVIDENCE_FIELDS = (
    "batch_item_id",
    "ride_id",
    "user_id",
    "wallet",
    "ride_hash_hex",
    "admitted_at",
    "established_at",
    "reward_ftp_authority_id",
    "reward_ftp_authority_evidence_hash_hex",
    "reward_ftp_w",
    "reward_ftp_source",
    "reward_ftp_policy_version",
    "economic_tss",
    "total_tss",
    "exact_cal_base_units",
    "exact_tribute_budget_base_units",
    "expected_release_authority_pda",
    "expected_cal_receipt_pda",
)


def _attach_canonical_release_evidence(
    snapshot: dict[str, Any],
    steps: list[dict[str, Any]],
    claim: dict[str, Any],
    *,
    domain: str = "BR_THRESHOLD_HELD_RIDE_RELEASE_PLAN_V1",
) -> dict[str, Any]:
    snapshot["snapshot_evidence"] = {
        "domain": domain,
        "plan": {field: snapshot[field] for field in _RELEASE_PLAN_EVIDENCE_FIELDS},
        "steps": steps,
        "hold_evidence_hash_hex": claim["hold_evidence_hash_hex"],
        "admission_plan_evidence_hash_hex": claim[
            "admission_plan_evidence_hash_hex"
        ],
    }
    return snapshot


def _release_snapshot_from_claim(
    claim: dict[str, Any],
    *,
    economic_tss: float,
    exact_cal_base_units: int,
    exact_tribute_budget_base_units: int,
    steps: list[dict[str, Any]],
    pda_prefix: str,
) -> dict[str, Any]:
    snapshot = {
        "snapshot_id": str(uuid.uuid4()),
        **{
            field: claim[field]
            for field in (
                "batch_item_id",
                "ride_id",
                "user_id",
                "wallet",
                "ride_hash_hex",
                "admitted_at",
                "established_at",
                "reward_ftp_authority_id",
                "reward_ftp_authority_evidence_hash_hex",
                "reward_ftp_w",
                "reward_ftp_source",
                "reward_ftp_policy_version",
            )
        },
        "economic_tss": economic_tss,
        "total_tss": int(economic_tss),
        "exact_cal_base_units": exact_cal_base_units,
        "exact_tribute_budget_base_units": exact_tribute_budget_base_units,
        "expected_release_authority_pda": f"{pda_prefix}-release-pda",
        "expected_cal_receipt_pda": f"{pda_prefix}-cal-pda",
    }
    return _attach_canonical_release_evidence(snapshot, steps, claim)


def _insert_hold(
    cursor: Any,
    *,
    user_id: uuid.UUID,
    held_at: datetime,
    admitted_at: datetime | None = None,
    insert_admission: bool = True,
    hold_evidence: dict[str, Any] | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    ride_id = _insert_ride(
        cursor,
        user_id=user_id,
        received_at=held_at,
        eligible=False,
    )
    started_at = held_at - timedelta(hours=1)
    cursor.execute(
        "SELECT * FROM public.bind_ride_reward_ftp(%s, %s)",
        (ride_id, started_at),
    )
    assert cursor.fetchone()[:3] == (200, "network_default", None)
    cursor.execute(
        "UPDATE public.rides SET economic_tss = 84 WHERE id = %s",
        (ride_id,),
    )

    hold_id = uuid.uuid4()
    cursor.execute(
        """
        INSERT INTO public.reward_threshold_provisional_holds (
            id, ride_id, user_id, held_at, ride_started_at,
            admission_plan_evidence_hash, hold_evidence, hold_evidence_hash
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            hold_id,
            ride_id,
            user_id,
            held_at,
            started_at,
            psycopg2.Binary(_digest(f"admission:{ride_id}")),
            Json(hold_evidence or {"version": 1, "ride_id": str(ride_id)}),
            psycopg2.Binary(_digest(f"hold:{ride_id}")),
        ),
    )
    if insert_admission:
        cursor.execute(
            """
            INSERT INTO public.reward_threshold_provisional_hold_admissions (
                hold_id, ride_id, admitted_at, ride_attestation_pda
            ) VALUES (%s, %s, %s, %s)
            """,
            (
                hold_id,
                ride_id,
                admitted_at or held_at,
                f"parent-attestation:{ride_id}",
            ),
        )
    return hold_id, ride_id


def _establish_with_edge_holds(
    cursor: Any,
    *,
    current_hold_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    user_id = uuid.uuid4()
    _install(
        cursor,
        lambda seed_cursor: seed_cursor.execute(
            "INSERT INTO public.users (id) VALUES (%s)", (user_id,)
        ),
    )
    # The compact authority fixture predates these long-lived rider projection
    # columns; migrations 155/156 consume the production columns at release.
    cursor.execute(
        """
        ALTER TABLE public.rides
            ADD COLUMN IF NOT EXISTS cal_earned INTEGER,
            ADD COLUMN IF NOT EXISTS tss NUMERIC
        """
    )
    cursor.execute(_migration_sql())

    established_at = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)
    edge_hold, edge_ride = _insert_hold(
        cursor,
        user_id=user_id,
        held_at=established_at - timedelta(weeks=16),
    )
    lapsed_hold, lapsed_ride = _insert_hold(
        cursor,
        user_id=user_id,
        held_at=established_at - timedelta(weeks=16, microseconds=1),
    )
    current_hold, current_ride = _insert_hold(
        cursor,
        user_id=user_id,
        held_at=established_at - timedelta(days=1),
        hold_evidence=current_hold_evidence,
    )

    candidate_ride = _insert_ride(
        cursor,
        user_id=user_id,
        received_at=established_at - timedelta(days=1, hours=1),
    )
    _register(
        cursor,
        candidate_ride,
        245.0,
        established_at - timedelta(days=1),
    )
    cursor.execute(
        "SELECT public.seal_due_reward_threshold_promotions_at(%s)",
        (established_at,),
    )
    assert cursor.fetchone()[0] == 1

    cursor.execute(
        """
        SELECT id, established_authority_id
        FROM public.reward_threshold_release_batches
        WHERE user_id = %s
        """,
        (user_id,),
    )
    batch_id, authority_id = cursor.fetchone()
    return {
        "user_id": user_id,
        "established_at": established_at,
        "batch_id": batch_id,
        "authority_id": authority_id,
        "edge_hold": edge_hold,
        "edge_ride": edge_ride,
        "lapsed_hold": lapsed_hold,
        "lapsed_ride": lapsed_ride,
        "current_hold": current_hold,
        "current_ride": current_ride,
    }


def _insert_complete_zero_parent_plan(
    cursor: Any,
    *,
    ride_id: uuid.UUID,
    user_id: uuid.UUID,
    started_at: datetime,
    completed_at: datetime,
    terminal_projected: bool = True,
) -> None:
    cursor.execute(
        """
        SELECT reward_ftp_policy_version
        FROM public.rides
        WHERE id = %s
        """,
        (ride_id,),
    )
    reward_policy_version = cursor.fetchone()[0]
    cursor.execute(
        """
        SELECT ride_parser_version, policy_version
        FROM public.pipeline_versions
        WHERE deactivated_at IS NULL
        ORDER BY id DESC
        LIMIT 1
        """
    )
    parser_version, policy_version = cursor.fetchone()
    cursor.execute(
        """
        INSERT INTO public.ride_economic_plans (
            ride_id, user_id, wallet, ride_hash, attestation_commitment,
            parser_version, policy_version, reward_policy, source_kind,
            started_at, completed_at, total_tss, total_distance_m, total_vert_m,
            exact_cal_base_units, climbs_crossed, exact_tribute_base_units,
            plan_evidence_hash, expected_attestation_pda, expected_cal_receipt_pda,
            state, attestation_confirmed_at, cal_confirmed_at,
            terminal_projected_at,
            reward_ftp_w, reward_ftp_source, reward_ftp_authority_id,
            reward_ftp_policy_version
        ) VALUES (
            %s, %s, 'rider-wallet', %s, %s,
            %s, %s,
            'threshold_provisional_hold_v1', 1,
            %s, %s, 0, 1000, 10,
            0, 0, 0,
            %s, %s, 'ordinary-cal-pda',
            'complete', %s, %s, %s,
            200, 'network_default', NULL,
            %s
        )
        """,
        (
            ride_id,
            user_id,
            psycopg2.Binary(_digest(f"ride:{ride_id}")),
            psycopg2.Binary(_digest(f"attestation:{ride_id}")),
            parser_version,
            policy_version,
            started_at,
            completed_at,
            psycopg2.Binary(_digest(f"admission:{ride_id}")),
            f"parent-attestation:{ride_id}",
            completed_at,
            completed_at,
            completed_at if terminal_projected else None,
            reward_policy_version,
        ),
    )


def _zero_hold_plan(
    cursor: Any,
    *,
    ride_id: uuid.UUID,
    user_id: uuid.UUID,
    started_at: datetime,
    completed_at: datetime,
) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT ride_parser_version, policy_version
        FROM public.pipeline_versions
        WHERE deactivated_at IS NULL
        ORDER BY id DESC
        LIMIT 1
        """
    )
    parser_version, policy_version = cursor.fetchone()
    return {
        "ride_id": str(ride_id),
        "user_id": str(user_id),
        "wallet": "rider-wallet",
        "ride_hash_hex": _digest(f"ride:{ride_id}").hex(),
        "attestation_commitment_hex": _digest(f"attestation:{ride_id}").hex(),
        "parser_version": parser_version,
        "policy_version": policy_version,
        "reward_policy": "threshold_provisional_hold_v1",
        "reward_ftp_w": 200,
        "reward_ftp_source": "network_default",
        "reward_ftp_authority_id": None,
        "reward_ftp_policy_version": (
            "reward_ftp_policy_2026_08_24_threshold_v1"
        ),
        "source_kind": 1,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "total_tss": 0,
        "total_distance_m": 1_000,
        "total_vert_m": 10,
        "exact_cal_base_units": "0",
        "climbs_crossed": 0,
        "exact_tribute_base_units": "0",
        "plan_evidence_hash_hex": _digest(f"admission:{ride_id}").hex(),
        "expected_attestation_pda": f"parent-attestation:{ride_id}",
        "expected_cal_receipt_pda": f"ordinary-cal:{ride_id}",
    }


def test_zero_parent_and_hold_evidence_freeze_atomically(
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
            cursor.execute(_migration_sql())
            completed_at = datetime(2026, 8, 24, 11, tzinfo=timezone.utc)
            started_at = completed_at - timedelta(hours=1)
            ride_id = _insert_ride(
                cursor,
                user_id=user_id,
                received_at=completed_at,
                eligible=False,
            )
            cursor.execute(
                "SELECT * FROM public.bind_ride_reward_ftp(%s, %s)",
                (ride_id, started_at),
            )
            assert cursor.fetchone()[:3] == (200, "network_default", None)
            cursor.execute(
                "UPDATE public.rides SET economic_tss = 0 WHERE id = %s",
                (ride_id,),
            )
            plan = _zero_hold_plan(
                cursor,
                ride_id=ride_id,
                user_id=user_id,
                started_at=started_at,
                completed_at=completed_at,
            )
            hold = {
                "ride_id": str(ride_id),
                "user_id": str(user_id),
                "ride_started_at": started_at.isoformat(),
                "admission_plan_evidence_hash_hex": plan[
                    "plan_evidence_hash_hex"
                ],
                "hold_evidence": {
                    "version": 1,
                    "ride_id": str(ride_id),
                    "reward_ftp_w": 200,
                },
            }

            with pytest.raises(psycopg2.Error, match="invalid Threshold hold evidence"):
                cursor.execute(
                    "SELECT public.freeze_ride_economic_plan(%s, %s, %s)",
                    (Json(plan), Json([]), Json({**hold, "hold_evidence": None})),
                )
            cursor.execute(
                """
                SELECT
                    (SELECT count(*) FROM public.ride_economic_plans WHERE ride_id=%s),
                    (SELECT count(*) FROM public.reward_threshold_provisional_holds WHERE ride_id=%s)
                """,
                (ride_id, ride_id),
            )
            assert cursor.fetchone() == (0, 0)

            cursor.execute(
                "SELECT public.freeze_ride_economic_plan(%s, %s, %s)",
                (Json(plan), Json([]), Json(hold)),
            )
            frozen = cursor.fetchone()[0]
            assert frozen["ride_id"] == str(ride_id)
            cursor.execute(
                """
                SELECT count(*), bool_and(hold.held_at = plan.created_at)
                FROM public.reward_threshold_provisional_holds AS hold
                JOIN public.ride_economic_plans AS plan ON plan.ride_id = hold.ride_id
                WHERE hold.ride_id = %s
                """,
                (ride_id,),
            )
            assert cursor.fetchone() == (1, True)


def test_atomic_hold_rejects_valid_evidence_from_another_zero_parent(
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
            cursor.execute(_migration_sql())
            completed_at = datetime(2026, 8, 24, 11, tzinfo=timezone.utc)

            plans: dict[uuid.UUID, dict[str, Any]] = {}
            holds: dict[uuid.UUID, dict[str, Any]] = {}
            for offset_hours in (0, 2):
                ride_completed_at = completed_at + timedelta(hours=offset_hours)
                ride_started_at = ride_completed_at - timedelta(hours=1)
                ride_id = _insert_ride(
                    cursor,
                    user_id=user_id,
                    received_at=ride_completed_at,
                    eligible=False,
                )
                cursor.execute(
                    "SELECT * FROM public.bind_ride_reward_ftp(%s, %s)",
                    (ride_id, ride_started_at),
                )
                assert cursor.fetchone()[:3] == (200, "network_default", None)
                cursor.execute(
                    "UPDATE public.rides SET economic_tss = 0 WHERE id = %s",
                    (ride_id,),
                )
                plan = _zero_hold_plan(
                    cursor,
                    ride_id=ride_id,
                    user_id=user_id,
                    started_at=ride_started_at,
                    completed_at=ride_completed_at,
                )
                plans[ride_id] = plan
                holds[ride_id] = {
                    "ride_id": str(ride_id),
                    "user_id": str(user_id),
                    "ride_started_at": ride_started_at.isoformat(),
                    "admission_plan_evidence_hash_hex": plan[
                        "plan_evidence_hash_hex"
                    ],
                    "hold_evidence": {
                        "version": 1,
                        "ride_id": str(ride_id),
                    },
                }

            ride_a, ride_b = tuple(plans)
            cursor.execute(
                "SELECT public.freeze_ride_economic_plan(%s, %s, %s)",
                (Json(plans[ride_b]), Json([]), Json(holds[ride_b])),
            )
            assert cursor.fetchone()[0]["ride_id"] == str(ride_b)

            with pytest.raises(
                psycopg2.Error,
                match="Threshold hold evidence does not bind zero parent plan",
            ):
                cursor.execute(
                    "SELECT public.freeze_ride_economic_plan(%s, %s, %s)",
                    (Json(plans[ride_a]), Json([]), Json(holds[ride_b])),
                )

            cursor.execute(
                """
                SELECT
                    (SELECT count(*) FROM public.ride_economic_plans WHERE ride_id=%s),
                    (SELECT count(*) FROM public.reward_threshold_provisional_holds WHERE ride_id=%s),
                    (SELECT count(*) FROM public.ride_economic_plans WHERE ride_id=%s),
                    (SELECT count(*) FROM public.reward_threshold_provisional_holds WHERE ride_id=%s)
                """,
                (ride_a, ride_a, ride_b, ride_b),
            )
            assert cursor.fetchone() == (0, 0, 1, 1)


def test_deleting_a_held_ride_retains_immutable_authority_identity(
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
            cursor.execute(_migration_sql())
            held_at = datetime(2026, 8, 23, 12, tzinfo=timezone.utc)
            hold_id, ride_id = _insert_hold(
                cursor,
                user_id=user_id,
                held_at=held_at,
            )
            cursor.execute(
                "SELECT public.br_account_deletion_db_blockers(%s, %s)",
                (user_id, "rider-wallet"),
            )
            blockers = cursor.fetchone()[0]
            assert any(
                blocker.get("source")
                == "reward_threshold_hold_release_evidence"
                and blocker.get("action") == "contact_support"
                for blocker in blockers
            )

            cursor.execute("DELETE FROM public.rides WHERE id = %s", (ride_id,))
            assert cursor.rowcount == 1
            cursor.execute(
                """
                SELECT hold.ride_id, admission.ride_id,
                       hold.hold_evidence, hold.hold_evidence_hash
                FROM public.reward_threshold_provisional_holds AS hold
                JOIN public.reward_threshold_provisional_hold_admissions AS admission
                  ON admission.hold_id = hold.id
                WHERE hold.id = %s
                """,
                (hold_id,),
            )
            held_ride_id, admitted_ride_id, evidence, evidence_hash = (
                cursor.fetchone()
            )
            assert held_ride_id == ride_id
            assert admitted_ride_id == ride_id
            assert evidence["ride_id"] == str(ride_id)
            assert bytes(evidence_hash) == _digest(f"hold:{ride_id}")


def test_indexed_release_authority_blocks_deletion_before_storage(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _install_hold_release_deletion_integration(cursor)
            user_id = _insert_user(cursor)
            cursor.execute(
                """
                INSERT INTO public.indexed_held_ride_release_authorities (
                    pda, rider_pubkey
                ) VALUES ('indexed-release-before-deletion', %s)
                """,
                (WALLET,),
            )

            cursor.execute(
                "SELECT public.br_account_deletion_db_blockers(%s, %s)",
                (user_id, WALLET),
            )
            blockers = cursor.fetchone()[0]
            assert any(
                blocker.get("source")
                == "reward_threshold_hold_release_evidence"
                and blocker.get("count") == 1
                for blocker in blockers
            )
            request_id, request = _create_request(cursor, user_id)
            assert request[1] == "needs_support"
            cursor.execute(
                "SELECT storage_authorized_at FROM public.deletion_requests WHERE id=%s",
                (request_id,),
            )
            assert cursor.fetchone()[0] is None


def test_deletion_fence_rejects_late_indexed_release_authority(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _install_hold_release_deletion_integration(cursor)
            user_id = _insert_user(cursor)
            _request_id, request = _create_request(cursor, user_id)
            assert request[1] == "queued"

            with pytest.raises(
                psycopg2.errors.ObjectNotInPrerequisiteState,
                match="account_deletion_pending",
            ):
                cursor.execute(
                    """
                    INSERT INTO public.indexed_held_ride_release_authorities (
                        pda, rider_pubkey
                    ) VALUES ('late-indexed-release', %s)
                    """,
                    (WALLET,),
                )


def test_deletion_fence_rejects_tombstoned_release_authority_wallet(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _install_hold_release_deletion_integration(cursor)
            cursor.execute(
                "INSERT INTO public.deleted_wallets (wallet) VALUES (%s)",
                (WALLET,),
            )

            with pytest.raises(
                psycopg2.errors.ObjectNotInPrerequisiteState,
                match="account_deleted",
            ):
                cursor.execute(
                    """
                    INSERT INTO public.indexed_held_ride_release_authorities (
                        pda, rider_pubkey
                    ) VALUES ('tombstoned-indexed-release', %s)
                    """,
                    (WALLET,),
                )


def test_deletion_request_and_indexed_release_insert_serialize_by_wallet(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as setup_connection:
        with setup_connection.cursor() as cursor:
            _install_hold_release_deletion_integration(cursor)
            user_id = _insert_user(cursor)

    deletion_connection = psycopg2.connect(postgres_dsn)
    writer_finished = threading.Event()
    writer_errors: list[Exception] = []

    def insert_indexed_release() -> None:
        writer_connection = psycopg2.connect(postgres_dsn)
        try:
            with writer_connection:
                with writer_connection.cursor() as writer:
                    writer.execute("SET lock_timeout = '5s'")
                    writer.execute(
                        """
                        INSERT INTO public.indexed_held_ride_release_authorities (
                            pda, rider_pubkey
                        ) VALUES ('racing-indexed-release', %s)
                        """,
                        (WALLET,),
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

        writer = threading.Thread(target=insert_indexed_release, daemon=True)
        writer.start()
        finished_before_deletion_commit = writer_finished.wait(timeout=0.25)
        deletion_connection.commit()
        assert writer_finished.wait(timeout=5)
        writer.join(timeout=1)

        assert finished_before_deletion_commit is False
        assert len(writer_errors) == 1
        assert "account_deletion_pending" in str(writer_errors[0])
        with _connection(postgres_dsn) as check_connection:
            with check_connection.cursor() as check:
                check.execute(
                    """
                    SELECT count(*)
                    FROM public.indexed_held_ride_release_authorities
                    WHERE rider_pubkey = %s
                    """,
                    (WALLET,),
                )
                assert check.fetchone()[0] == 0
    finally:
        deletion_connection.rollback()
        deletion_connection.close()


@pytest.mark.parametrize(
    ("conflicting_field", "conflicting_value"),
    [
        ("rider_pubkey", "different-rider-wallet"),
        ("threshold_authority_commitment_hex", "0" * 64),
        ("threshold_effective_at", 0),
        ("release_plan_hash_hex", "f" * 64),
    ],
)
def test_zero_step_terminal_rejects_conflicting_indexed_release_authority(
    postgres_dsn: str,
    conflicting_field: str,
    conflicting_value: str | int,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            state = _establish_with_edge_holds(cursor)
            completed_at = state["established_at"] - timedelta(days=1)
            _insert_complete_zero_parent_plan(
                cursor,
                ride_id=state["current_ride"],
                user_id=state["user_id"],
                started_at=completed_at - timedelta(hours=1),
                completed_at=completed_at,
            )
            lease_owner = uuid.uuid4()
            cursor.execute(
                "SELECT public.claim_due_reward_threshold_release_item(%s, 60)",
                (lease_owner,),
            )
            claim = cursor.fetchone()[0]
            snapshot = _release_snapshot_from_claim(
                claim,
                economic_tss=1.0,
                exact_cal_base_units=1_000_000_000,
                exact_tribute_budget_base_units=100_000_000,
                steps=[],
                pda_prefix=f"zero-step-{conflicting_field}",
            )
            cursor.execute(
                "SELECT public.freeze_reward_threshold_release_snapshot(%s, %s, %s)",
                (Json(snapshot), Json([]), lease_owner),
            )
            frozen = cursor.fetchone()[0]
            snapshot_id = uuid.UUID(frozen["snapshot_id"])
            cursor.execute(
                """
                UPDATE public.reward_threshold_release_executions
                SET state = 'complete',
                    release_authority_actual_tx_signature = 'release-tx',
                    release_authority_confirmed_at = %s,
                    cal_actual_tx_signature = 'cal-tx',
                    cal_confirmed_at = %s,
                    terminal_projected_at = NULL
                WHERE snapshot_id = %s
                """,
                (completed_at, completed_at, snapshot_id),
            )
            cursor.execute(
                """
                SELECT pg_catalog.encode(evidence_hash, 'hex'),
                       EXTRACT(epoch FROM effective_at)::BIGINT,
                       ftp_w
                FROM public.reward_ftp_authorities
                WHERE id = %s
                """,
                (state["authority_id"],),
            )
            authority_commitment, authority_effective_at, authority_w = (
                cursor.fetchone()
            )
            indexed = {
                "rider_pubkey": "rider-wallet",
                "threshold_authority_commitment_hex": authority_commitment,
                "threshold_effective_at": authority_effective_at,
                "release_plan_hash_hex": frozen[
                    "release_plan_evidence_hash_hex"
                ],
            }
            indexed[conflicting_field] = conflicting_value
            release_pda = snapshot["expected_release_authority_pda"]
            cursor.execute(
                """
                INSERT INTO public.indexed_held_ride_release_authorities (
                    pda, ride_attestation_pda, rider_pubkey,
                    threshold_authority_id_hex,
                    threshold_authority_commitment_hex,
                    threshold_effective_at, threshold_w,
                    threshold_policy_version, economic_tss, cal_earned,
                    cal_tribute_budget, release_plan_hash_hex, released_at,
                    released_slot, release_settlement_week, attester, bump
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, 1, 1,
                    1000000000, 100000000, %s, %s, 100, 42,
                    'release-attester', 1
                )
                """,
                (
                    release_pda,
                    f"parent-attestation:{state['current_ride']}",
                    indexed["rider_pubkey"],
                    state["authority_id"].hex,
                    indexed["threshold_authority_commitment_hex"],
                    indexed["threshold_effective_at"],
                    authority_w,
                    indexed["release_plan_hash_hex"],
                    int(completed_at.timestamp()),
                ),
            )
            cursor.execute(
                """
                INSERT INTO public.indexed_cal_mint_receipts (
                    pda, ride_attestation_pda, rider_pubkey, amount,
                    release_authority_pda, release_settlement_week
                ) VALUES (%s, %s, 'rider-wallet', 1000000000, %s, 42)
                """,
                (
                    snapshot["expected_cal_receipt_pda"],
                    f"parent-attestation:{state['current_ride']}",
                    release_pda,
                ),
            )
            execution_lease_owner = uuid.uuid4()
            cursor.execute(
                "SELECT public.claim_due_reward_threshold_release_execution(%s, 60)",
                (execution_lease_owner,),
            )
            assert cursor.fetchone()[0]["state"] == "complete"

            connection.autocommit = False
            cursor.execute("SAVEPOINT before_terminal_projection_conflict")
            with pytest.raises(
                psycopg2.DatabaseError,
                match="indexed Threshold release authority conflicts",
            ) as captured:
                cursor.execute(
                    "SELECT public.project_reward_threshold_release_terminal(%s)",
                    (snapshot_id,),
                )
            assert captured.value.pgcode == "BRR01"
            cursor.execute("ROLLBACK TO SAVEPOINT before_terminal_projection_conflict")

            cursor.execute(
                """
                SELECT public.mark_reward_threshold_release_review(
                    %s, %s, 'terminal indexed authority conflict', %s
                )
                """,
                (
                    snapshot_id,
                    execution_lease_owner,
                    Json(
                        {
                            "version": 1,
                            "kind": "indexed_threshold_release_authority_conflict",
                            "phase": "terminal",
                            "sqlstate": captured.value.pgcode,
                        }
                    ),
                ),
            )
            reviewed = cursor.fetchone()[0]
            assert reviewed["state"] == "review"
            cursor.execute(
                """
                SELECT review_from_state, terminal_projected_at
                FROM public.reward_threshold_release_executions
                WHERE snapshot_id = %s
                """,
                (snapshot_id,),
            )
            assert cursor.fetchone() == ("complete", None)

            cursor.execute(
                "SELECT public.repair_reward_threshold_release_execution(%s, %s)",
                (snapshot_id, "operator verified terminal indexed authority"),
            )
            repaired = cursor.fetchone()[0]
            assert repaired["state"] == "complete"
            assert repaired["release_authority_actual_tx_signature"] == "release-tx"
            assert repaired["cal_actual_tx_signature"] == "cal-tx"
            cursor.execute(
                "SELECT public.claim_due_reward_threshold_release_execution(%s, 60)",
                (uuid.uuid4(),),
            )
            assert cursor.fetchone()[0]["state"] == "complete"


def test_deleting_a_ride_after_release_freeze_retains_snapshot_authority(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            state = _establish_with_edge_holds(cursor)
            completed_at = state["established_at"] - timedelta(days=1)
            _insert_complete_zero_parent_plan(
                cursor,
                ride_id=state["current_ride"],
                user_id=state["user_id"],
                started_at=completed_at - timedelta(hours=1),
                completed_at=completed_at,
            )
            lease_owner = uuid.uuid4()
            cursor.execute(
                "SELECT public.claim_due_reward_threshold_release_item(%s, 60)",
                (lease_owner,),
            )
            claim = cursor.fetchone()[0]
            snapshot = _release_snapshot_from_claim(
                claim,
                economic_tss=1.0,
                exact_cal_base_units=1_000_000_000,
                exact_tribute_budget_base_units=100_000_000,
                steps=[],
                pda_prefix="retained-after-delete",
            )
            cursor.execute(
                "SELECT public.freeze_reward_threshold_release_snapshot(%s, %s, %s)",
                (Json(snapshot), Json([]), lease_owner),
            )
            frozen = cursor.fetchone()[0]

            cursor.execute(
                "DELETE FROM public.rides WHERE id = %s",
                (state["current_ride"],),
            )
            assert cursor.rowcount == 1
            cursor.execute(
                """
                SELECT hold.ride_id, admission.ride_id, snapshot.ride_id,
                       snapshot.snapshot_evidence,
                       snapshot.snapshot_evidence_hash
                FROM public.reward_threshold_provisional_holds AS hold
                JOIN public.reward_threshold_provisional_hold_admissions AS admission
                  ON admission.hold_id = hold.id
                JOIN public.reward_threshold_release_batch_items AS item
                  ON item.hold_id = hold.id
                JOIN public.reward_threshold_release_snapshots AS snapshot
                  ON snapshot.batch_item_id = item.id
                WHERE snapshot.id = %s
                """,
                (uuid.UUID(frozen["snapshot_id"]),),
            )
            (
                held_ride_id,
                admitted_ride_id,
                snapshot_ride_id,
                snapshot_evidence,
                snapshot_evidence_hash,
            ) = cursor.fetchone()
            assert (held_ride_id, admitted_ride_id, snapshot_ride_id) == (
                state["current_ride"],
                state["current_ride"],
                state["current_ride"],
            )
            assert snapshot_evidence["plan"]["ride_id"] == str(
                state["current_ride"]
            )
            assert bytes(snapshot_evidence_hash).hex() == frozen[
                "snapshot_evidence_hash_hex"
            ]
            cursor.execute(
                "SELECT count(*) FROM public.ride_economic_plans WHERE ride_id = %s",
                (state["current_ride"],),
            )
            assert cursor.fetchone()[0] == 1

            # If chain economics finish after the mutable ride is gone, exact
            # authority still has to validate and terminal recovery must stop.
            cursor.execute(
                """
                UPDATE public.reward_threshold_release_executions
                SET state = 'complete',
                    release_authority_actual_tx_signature = 'release-tx',
                    release_authority_confirmed_at = %s,
                    cal_actual_tx_signature = 'cal-tx',
                    cal_confirmed_at = %s,
                    next_attempt_at = pg_catalog.clock_timestamp()
                        - INTERVAL '1 second',
                    terminal_projected_at = NULL
                WHERE snapshot_id = %s
                """,
                (completed_at, completed_at, uuid.UUID(frozen["snapshot_id"])),
            )
            release_pda = "retained-after-delete-release-pda"
            cal_pda = "retained-after-delete-cal-pda"
            parent_pda = f"parent-attestation:{state['current_ride']}"
            cursor.execute(
                """
                SELECT pg_catalog.encode(evidence_hash, 'hex'),
                       EXTRACT(epoch FROM effective_at)::BIGINT,
                       ftp_w
                FROM public.reward_ftp_authorities
                WHERE id = %s
                """,
                (state["authority_id"],),
            )
            authority_commitment, authority_effective_at, authority_w = (
                cursor.fetchone()
            )
            cursor.execute(
                """
                INSERT INTO public.indexed_held_ride_release_authorities (
                    pda, ride_attestation_pda, rider_pubkey,
                    threshold_authority_id_hex,
                    threshold_authority_commitment_hex,
                    threshold_effective_at, threshold_w,
                    threshold_policy_version, economic_tss, cal_earned,
                    cal_tribute_budget, release_plan_hash_hex, released_at,
                    released_slot, release_settlement_week, attester, bump
                ) VALUES (
                    %s, %s, 'rider-wallet', %s, %s, %s, %s, 1, 1,
                    1000000000, 100000000, %s, %s, 100, 42,
                    'release-attester', 1
                )
                """,
                (
                    release_pda,
                    parent_pda,
                    state["authority_id"].hex,
                    authority_commitment,
                    authority_effective_at,
                    authority_w,
                    frozen["release_plan_evidence_hash_hex"],
                    int(completed_at.timestamp()),
                ),
            )
            cursor.execute(
                """
                INSERT INTO public.indexed_cal_mint_receipts (
                    pda, ride_attestation_pda, rider_pubkey, amount,
                    release_authority_pda, release_settlement_week
                ) VALUES (%s, %s, 'rider-wallet', 1000000000, %s, 42)
                """,
                (cal_pda, parent_pda, release_pda),
            )
            projection_owner = uuid.uuid4()
            cursor.execute(
                "SELECT public.claim_due_reward_threshold_release_execution(%s, 60)",
                (projection_owner,),
            )
            assert cursor.fetchone()[0]["state"] == "complete"
            cursor.execute(
                "SELECT public.project_reward_threshold_release_terminal(%s)",
                (uuid.UUID(frozen["snapshot_id"]),),
            )
            projected = cursor.fetchone()[0]
            assert projected["terminal_projected_at"] is not None
            cursor.execute(
                "SELECT count(*) FROM public.rides WHERE id = %s",
                (state["current_ride"],),
            )
            assert cursor.fetchone()[0] == 0


def _insert_positive_default_parent_plan(
    cursor: Any,
    *,
    ride_id: uuid.UUID,
    user_id: uuid.UUID,
    started_at: datetime,
    completed_at: datetime,
) -> None:
    cursor.execute(
        "SELECT reward_ftp_policy_version FROM public.rides WHERE id = %s",
        (ride_id,),
    )
    reward_policy_version = cursor.fetchone()[0]
    cursor.execute(
        """
        SELECT ride_parser_version, policy_version
        FROM public.pipeline_versions
        WHERE deactivated_at IS NULL
        ORDER BY id DESC
        LIMIT 1
        """
    )
    parser_version, policy_version = cursor.fetchone()
    cursor.execute(
        """
        INSERT INTO public.ride_economic_plans (
            ride_id, user_id, wallet, ride_hash, attestation_commitment,
            parser_version, policy_version, reward_policy, source_kind,
            started_at, completed_at, total_tss, total_distance_m, total_vert_m,
            exact_cal_base_units, climbs_crossed, exact_tribute_base_units,
            plan_evidence_hash, expected_attestation_pda, expected_cal_receipt_pda,
            state, reward_ftp_w, reward_ftp_source, reward_ftp_authority_id,
            reward_ftp_policy_version
        ) VALUES (
            %s, %s, 'rider-wallet', %s, %s,
            %s, %s, 'rewardable', 1,
            %s, %s, 84, 1000, 10,
            84000000000, 0, 0,
            %s, %s, 'ordinary-cal-pda',
            'planned', 200, 'network_default', NULL, %s
        )
        """,
        (
            ride_id,
            user_id,
            psycopg2.Binary(_digest(f"ride:{ride_id}")),
            psycopg2.Binary(_digest(f"attestation:{ride_id}")),
            parser_version,
            policy_version,
            started_at,
            completed_at,
            psycopg2.Binary(_digest(f"positive-default:{ride_id}")),
            f"parent-attestation:{ride_id}",
            reward_policy_version,
        ),
    )


def test_cutover_fails_closed_on_executable_positive_network_default(
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
            completed_at = datetime(2026, 8, 24, 11, tzinfo=timezone.utc)
            started_at = completed_at - timedelta(hours=1)
            ride_id = _insert_ride(
                cursor,
                user_id=user_id,
                received_at=completed_at,
                eligible=False,
            )
            cursor.execute(
                "SELECT * FROM public.bind_ride_reward_ftp(%s, %s)",
                (ride_id, started_at),
            )
            assert cursor.fetchone()[:3] == (200, "network_default", None)
            cursor.execute(
                "UPDATE public.rides SET economic_tss = 84 WHERE id = %s",
                (ride_id,),
            )
            _insert_positive_default_parent_plan(
                cursor,
                ride_id=ride_id,
                user_id=user_id,
                started_at=started_at,
                completed_at=completed_at,
            )

            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="Threshold cutover blocked by executable 200 W network-default economics",
            ):
                cursor.execute(_migration_sql())


def test_establishment_creates_one_batch_and_uses_an_inclusive_16_week_edge(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            state = _establish_with_edge_holds(cursor)

            cursor.execute(
                """
                SELECT hold.id, item.disposition
                FROM public.reward_threshold_release_batch_items AS item
                JOIN public.reward_threshold_provisional_holds AS hold
                  ON hold.id = item.hold_id
                WHERE item.batch_id = %s
                ORDER BY hold.held_at, hold.id
                """,
                (state["batch_id"],),
            )
            dispositions = dict(cursor.fetchall())
            assert dispositions == {
                state["lapsed_hold"]: "lapsed",
                state["edge_hold"]: "eligible",
                state["current_hold"]: "eligible",
            }

            cursor.execute(
                "SELECT public.create_reward_threshold_release_batch(%s, %s)",
                (state["authority_id"], state["established_at"]),
            )
            assert cursor.fetchone()[0] == state["batch_id"]
            cursor.execute(
                """
                SELECT count(*), count(DISTINCT established_authority_id)
                FROM public.reward_threshold_release_batches
                WHERE user_id = %s
                """,
                (state["user_id"],),
            )
            assert cursor.fetchone() == (1, 1)
            cursor.execute(
                """
                SELECT count(*), count(DISTINCT hold_id)
                FROM public.reward_threshold_release_batch_items
                WHERE batch_id = %s
                """,
                (state["batch_id"],),
            )
            assert cursor.fetchone() == (3, 3)

            for ride_id in (
                state["edge_ride"],
                state["lapsed_ride"],
                state["current_ride"],
            ):
                cursor.execute(
                    """
                    SELECT reward_ftp_w, reward_ftp_source,
                           reward_ftp_authority_id, economic_tss
                    FROM public.rides WHERE id = %s
                    """,
                    (ride_id,),
                )
                assert cursor.fetchone() == (200, "network_default", None, 84)


def test_eligibility_uses_chain_admission_not_prechain_hold_clock(
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
            cursor.execute(_migration_sql())
            established_at = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)
            hold_id, _ride_id = _insert_hold(
                cursor,
                user_id=user_id,
                held_at=established_at - timedelta(weeks=16, days=1),
                admitted_at=established_at - timedelta(weeks=16),
            )
            candidate_ride = _insert_ride(
                cursor,
                user_id=user_id,
                received_at=established_at - timedelta(days=1),
            )
            _register(cursor, candidate_ride, 245.0, established_at - timedelta(days=1))
            cursor.execute(
                "SELECT public.seal_due_reward_threshold_promotions_at(%s)",
                (established_at,),
            )
            assert cursor.fetchone()[0] == 1
            cursor.execute(
                """
                SELECT disposition
                FROM public.reward_threshold_release_batch_items
                WHERE hold_id = %s
                """,
                (hold_id,),
            )
            assert cursor.fetchone()[0] == "eligible"


def test_delayed_admission_checkpoint_binds_first_establishment_not_later_raise(
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
            cursor.execute(_migration_sql())
            first_monday = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)
            admitted_at = first_monday - timedelta(days=1)
            hold_id, ride_id = _insert_hold(
                cursor,
                user_id=user_id,
                held_at=admitted_at,
                insert_admission=False,
            )
            _insert_complete_zero_parent_plan(
                cursor,
                ride_id=ride_id,
                user_id=user_id,
                started_at=admitted_at - timedelta(hours=1),
                completed_at=admitted_at,
            )

            establishing_ride = _insert_ride(
                cursor,
                user_id=user_id,
                received_at=first_monday - timedelta(days=2),
            )
            _register(
                cursor,
                establishing_ride,
                245.0,
                first_monday - timedelta(days=2),
            )
            cursor.execute(
                "SELECT public.seal_due_reward_threshold_promotions_at(%s)",
                (first_monday,),
            )
            assert cursor.fetchone()[0] == 1
            cursor.execute(
                "SELECT sealed_authority_id FROM public.reward_threshold_ratchets "
                "WHERE user_id = %s",
                (user_id,),
            )
            first_authority_id = cursor.fetchone()[0]

            second_monday = first_monday + timedelta(weeks=1)
            raising_ride = _insert_ride(
                cursor,
                user_id=user_id,
                received_at=first_monday + timedelta(days=1),
            )
            _register(
                cursor,
                raising_ride,
                270.0,
                first_monday + timedelta(days=1),
            )
            cursor.execute(
                "SELECT public.seal_due_reward_threshold_promotions_at(%s)",
                (second_monday,),
            )
            assert cursor.fetchone()[0] == 1
            cursor.execute(
                "SELECT sealed_authority_id FROM public.reward_threshold_ratchets "
                "WHERE user_id = %s",
                (user_id,),
            )
            raise_authority_id = cursor.fetchone()[0]
            assert raise_authority_id != first_authority_id
            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="Threshold release requires the first sealed establishment authority",
            ):
                cursor.execute(
                    "SELECT public.create_reward_threshold_release_batch(%s, %s)",
                    (raise_authority_id, second_monday),
                )

            cursor.execute(
                "SELECT public.record_reward_threshold_provisional_hold_admission"
                "(%s, %s, %s)",
                (ride_id, admitted_at, f"parent-attestation:{ride_id}"),
            )
            checkpoint = cursor.fetchone()[0]
            assert checkpoint["disposition"] == "eligible"
            cursor.execute(
                """
                SELECT batch.established_authority_id, batch.established_at
                FROM public.reward_threshold_release_batch_items AS item
                JOIN public.reward_threshold_release_batches AS batch
                  ON batch.id = item.batch_id
                WHERE item.hold_id = %s
                """,
                (hold_id,),
            )
            authority_id, established_at = cursor.fetchone()
            assert authority_id == first_authority_id
            assert established_at == first_monday


def test_release_waits_for_parent_zero_terminal_projection(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            state = _establish_with_edge_holds(cursor)
            started_at = state["established_at"] - timedelta(days=1, hours=1)
            completed_at = state["established_at"] - timedelta(days=1)
            _insert_complete_zero_parent_plan(
                cursor,
                ride_id=state["current_ride"],
                user_id=state["user_id"],
                started_at=started_at,
                completed_at=completed_at,
                terminal_projected=False,
            )

            cursor.execute(
                "SELECT public.claim_due_reward_threshold_release_item(%s, 60)",
                (uuid.uuid4(),),
            )
            assert cursor.fetchone()[0] is None

            cursor.execute(
                """
                UPDATE public.ride_economic_plans
                SET terminal_projected_at = %s
                WHERE ride_id = %s
                """,
                (completed_at, state["current_ride"]),
            )
            cursor.execute(
                "SELECT public.claim_due_reward_threshold_release_item(%s, 60)",
                (uuid.uuid4(),),
            )
            assert cursor.fetchone()[0]["ride_id"] == str(state["current_ride"])


def test_lifecycle_ops_and_planner_review_repair_are_truthful(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            state = _establish_with_edge_holds(cursor)
            completed_at = state["established_at"] - timedelta(days=1)
            _insert_complete_zero_parent_plan(
                cursor,
                ride_id=state["current_ride"],
                user_id=state["user_id"],
                started_at=completed_at - timedelta(hours=1),
                completed_at=completed_at,
            )
            cursor.execute(
                "SELECT public.resolve_reward_threshold_release_lifecycle(%s)",
                (state["lapsed_ride"],),
            )
            assert cursor.fetchone()[0]["status"] == "lapsed"
            cursor.execute(
                "SELECT public.resolve_reward_threshold_release_lifecycle(%s)",
                (state["current_ride"],),
            )
            assert cursor.fetchone()[0]["status"] == "planning"

            lease_owner = uuid.uuid4()
            cursor.execute(
                "SELECT public.claim_due_reward_threshold_release_item(%s, 60)",
                (lease_owner,),
            )
            claim = cursor.fetchone()[0]
            cursor.execute(
                """
                SELECT public.mark_reward_threshold_release_item_terminal(
                    %s, %s, 'review', 'raw power evidence mismatch', %s
                )
                """,
                (
                    claim["batch_item_id"],
                    lease_owner,
                    Json({"kind": "raw_power_evidence_mismatch"}),
                ),
            )
            assert cursor.fetchone()[0]["disposition"] == "review"
            cursor.execute(
                "SELECT public.resolve_reward_threshold_release_lifecycle(%s)",
                (state["current_ride"],),
            )
            assert cursor.fetchone()[0]["status"] == "under_review"
            cursor.execute(
                """
                SELECT lifecycle_status, terminal_reason
                FROM public.reward_threshold_release_ops
                WHERE ride_id = %s
                """,
                (state["current_ride"],),
            )
            assert cursor.fetchone() == (
                "under_review",
                "raw power evidence mismatch",
            )

            cursor.execute(
                "SELECT public.repair_reward_threshold_release_item_review(%s, %s)",
                (claim["batch_item_id"], "source evidence restored"),
            )
            assert cursor.fetchone()[0]["status"] == "planning"
            cursor.execute(
                """
                SELECT lifecycle_status, planner_repair_reason
                FROM public.reward_threshold_release_ops
                WHERE ride_id = %s
                """,
                (state["current_ride"],),
            )
            assert cursor.fetchone() == ("planning", "source evidence restored")
            cursor.execute(
                "SELECT public.claim_due_reward_threshold_release_item(%s, 60)",
                (uuid.uuid4(),),
            )
            assert cursor.fetchone()[0]["ride_id"] == str(state["current_ride"])


def test_hold_batch_item_and_release_snapshot_authority_is_append_only(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            state = _establish_with_edge_holds(cursor)
            cursor.execute(
                """
                SELECT id
                FROM public.reward_threshold_release_batch_items
                WHERE batch_id = %s AND hold_id = %s
                """,
                (state["batch_id"], state["edge_hold"]),
            )
            item_id = cursor.fetchone()[0]

            snapshot_id = uuid.uuid4()
            cursor.execute(
                """
                INSERT INTO public.reward_threshold_release_snapshots (
                    id, batch_item_id, ride_id, user_id,
                    reward_ftp_authority_id, reward_ftp_w, reward_ftp_source,
                    reward_ftp_policy_version, economic_tss,
                    exact_cal_base_units, exact_tribute_budget_base_units,
                    snapshot_evidence, snapshot_evidence_hash
                ) VALUES (
                    %s, %s, %s, %s, %s, 245, 'derived_eftp',
                    'reward_ftp_policy_2026_08_24_threshold_v1', 56.0,
                    56000000000, 5600000000, %s, %s
                )
                """,
                (
                    snapshot_id,
                    item_id,
                    state["edge_ride"],
                    state["user_id"],
                    state["authority_id"],
                    Json({"version": 1, "threshold_w": 245}),
                    psycopg2.Binary(_digest(f"snapshot:{snapshot_id}")),
                ),
            )

            mutations = (
                (
                    "UPDATE public.reward_threshold_provisional_hold_admissions "
                    "SET admitted_at = admitted_at + interval '1 second' "
                    "WHERE hold_id = %s",
                    state["edge_hold"],
                ),
                (
                    "UPDATE public.reward_threshold_provisional_holds "
                    "SET held_at = held_at + interval '1 second' WHERE id = %s",
                    state["edge_hold"],
                ),
                (
                    "DELETE FROM public.reward_threshold_release_batches WHERE id = %s",
                    state["batch_id"],
                ),
                (
                    "UPDATE public.reward_threshold_release_batch_items "
                    "SET disposition = 'lapsed' WHERE id = %s",
                    item_id,
                ),
                (
                    "UPDATE public.reward_threshold_release_snapshots "
                    "SET reward_ftp_w = 244 WHERE id = %s",
                    snapshot_id,
                ),
                (
                    "DELETE FROM public.reward_threshold_release_snapshots WHERE id = %s",
                    snapshot_id,
                ),
            )
            for statement, identifier in mutations:
                with pytest.raises(
                    psycopg2.errors.RaiseException,
                    match="Threshold hold and release authority is immutable",
                ):
                    cursor.execute(statement, (identifier,))

            cursor.execute(
                "SELECT count(*) FROM public.reward_threshold_release_snapshots WHERE id = %s",
                (snapshot_id,),
            )
            assert cursor.fetchone()[0] == 1


def test_threshold_hold_authority_is_rls_private_and_helper_is_internal(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _install(cursor)
            cursor.execute(_migration_sql())

            tables = (
                "reward_threshold_provisional_holds",
                "reward_threshold_provisional_hold_admissions",
                "reward_threshold_release_batches",
                "reward_threshold_release_batch_items",
                "reward_threshold_release_snapshots",
            )
            cursor.execute(
                """
                SELECT relname, relrowsecurity
                FROM pg_catalog.pg_class
                WHERE relnamespace = 'public'::regnamespace
                  AND relname = ANY(%s)
                """,
                (list(tables),),
            )
            assert dict(cursor.fetchall()) == {table: True for table in tables}

            for table in tables:
                for role in ("anon", "authenticated"):
                    for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                        cursor.execute(
                            "SELECT has_table_privilege(%s, %s, %s)",
                            (role, f"public.{table}", privilege),
                        )
                        assert cursor.fetchone()[0] is False
                cursor.execute(
                    "SELECT has_table_privilege('service_role', %s, 'SELECT')",
                    (f"public.{table}",),
                )
                assert cursor.fetchone()[0] is True
                for privilege in ("INSERT", "UPDATE", "DELETE"):
                    cursor.execute(
                        "SELECT has_table_privilege('service_role', %s, %s)",
                        (f"public.{table}", privilege),
                    )
                    assert cursor.fetchone()[0] is False

            helper = (
                "public.create_reward_threshold_release_batch"
                "(uuid,timestamp with time zone)"
            )
            # anon/authenticated inherit PUBLIC, so both also prove that the
            # default PostgreSQL function EXECUTE grant was removed.
            for role in ("anon", "authenticated", "service_role"):
                cursor.execute(
                    "SELECT has_function_privilege(%s, %s, 'EXECUTE')",
                    (role, helper),
                )
                assert cursor.fetchone()[0] is False


def test_release_power_inputs_are_service_only_and_immutable(
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
            cursor.execute(
                "ALTER TABLE public.rides ADD COLUMN processing_status TEXT"
            )
            cursor.execute(_migration_sql())
            cursor.execute(
                "GRANT INSERT, UPDATE, SELECT ON public.rides TO authenticated"
            )
            cursor.execute("GRANT USAGE ON SCHEMA public TO authenticated")

            prepopulated_ride = uuid.uuid4()
            cursor.execute("SET ROLE authenticated")
            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="Threshold release power inputs are service-only",
            ):
                cursor.execute(
                    """
                    INSERT INTO public.rides (
                        id, user_id, normalized_power_raw_w,
                        normalized_power_duration_s
                    ) VALUES (%s, %s, 250.5, 3600)
                    """,
                    (prepopulated_ride, user_id),
                )
            cursor.execute("RESET ROLE")

            ride_id = uuid.uuid4()
            cursor.execute(
                "INSERT INTO public.rides (id, user_id) VALUES (%s, %s)",
                (ride_id, user_id),
            )
            cursor.execute(
                """
                UPDATE public.rides
                SET normalized_power_raw_w = 245.25,
                    normalized_power_duration_s = 3600
                WHERE id = %s
                """,
                (ride_id,),
            )
            # Idempotent service recovery is allowed.
            cursor.execute(
                """
                UPDATE public.rides
                SET normalized_power_raw_w = 245.25,
                    normalized_power_duration_s = 3600
                WHERE id = %s
                """,
                (ride_id,),
            )

            cursor.execute("SET ROLE authenticated")
            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="Threshold release power inputs are service-only",
            ):
                cursor.execute(
                    """
                    UPDATE public.rides
                    SET normalized_power_raw_w = 300,
                        normalized_power_duration_s = 3600
                    WHERE id = %s
                    """,
                    (ride_id,),
                )
            cursor.execute("RESET ROLE")

            cursor.execute(
                """
                UPDATE public.rides
                SET normalized_power_raw_w = 246.25,
                    processing_status = 'metrics_ready'
                WHERE id = %s
                RETURNING normalized_power_raw_w,
                          normalized_power_duration_s, processing_status
                """,
                (ride_id,),
            )
            assert cursor.fetchone() == (245.25, 3600, "metrics_ready")


def test_released_v3_completion_enters_local_legend_once_only_when_terminal(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            state = _establish_with_edge_holds(cursor)
            ride_id = state["current_ride"]
            completed_at = state["established_at"] - timedelta(days=1)
            _insert_complete_zero_parent_plan(
                cursor,
                ride_id=ride_id,
                user_id=state["user_id"],
                started_at=completed_at - timedelta(hours=1),
                completed_at=completed_at,
            )
            cursor.execute(
                """
                SELECT id
                FROM public.reward_threshold_release_batch_items
                WHERE batch_id = %s AND hold_id = %s
                """,
                (state["batch_id"], state["current_hold"]),
            )
            item_id = cursor.fetchone()[0]
            snapshot_id = uuid.uuid4()
            evidence_hash = _digest(f"legend-v3:{snapshot_id}")
            receipt_pda = f"release-completion:{snapshot_id}"
            release_pda = f"release-authority:{snapshot_id}"
            parent_pda = f"parent-attestation:{ride_id}"
            cursor.execute(
                """
                INSERT INTO public.reward_threshold_release_snapshots (
                    id, batch_item_id, ride_id, user_id,
                    reward_ftp_authority_id, reward_ftp_w, reward_ftp_source,
                    reward_ftp_policy_version, economic_tss,
                    exact_cal_base_units, exact_tribute_budget_base_units,
                    snapshot_evidence, snapshot_evidence_hash
                ) VALUES (
                    %s, %s, %s, %s, %s, 245, 'derived_eftp',
                    'reward_ftp_policy_2026_08_24_threshold_v1', 64,
                    64000000000, 6400000000, %s, %s
                )
                """,
                (
                    snapshot_id,
                    item_id,
                    ride_id,
                    state["user_id"],
                    state["authority_id"],
                    Json({"version": 1, "local_legend": True}),
                    psycopg2.Binary(_digest(f"snapshot:{snapshot_id}")),
                ),
            )
            cursor.execute(
                """
                INSERT INTO public.reward_threshold_release_executions (
                    snapshot_id, wallet, ride_hash, release_plan_evidence_hash,
                    expected_release_authority_pda, expected_cal_receipt_pda,
                    state, release_authority_actual_tx_signature,
                    release_authority_confirmed_at, cal_actual_tx_signature,
                    cal_confirmed_at
                ) VALUES (
                    %s, 'rider-wallet', %s, %s, %s, %s,
                    'cal_confirmed', 'release-tx', %s, 'cal-tx', %s
                )
                """,
                (
                    snapshot_id,
                    psycopg2.Binary(_digest(f"ride:{ride_id}")),
                    psycopg2.Binary(_digest(f"release-plan:{snapshot_id}")),
                    release_pda,
                    f"released-cal:{snapshot_id}",
                    completed_at,
                    completed_at,
                ),
            )
            cursor.execute(
                """
                INSERT INTO public.reward_threshold_release_steps (
                    snapshot_id, step_index, pattern_id, vault_id,
                    vault_signature, completion_time_s, completed_at,
                    exact_tribute_base_units, completion_evidence_version,
                    completion_evidence_hash, expected_receipt_pda, state,
                    actual_tx_signature, chain_confirmed_at
                ) VALUES (
                    %s, 0, %s, 7, %s, 420, %s,
                    1000000000, 3, %s, %s, 'confirmed',
                    'completion-tx', %s
                )
                """,
                (
                    snapshot_id,
                    uuid.uuid4(),
                    "07" * 32,
                    completed_at,
                    psycopg2.Binary(evidence_hash),
                    receipt_pda,
                    completed_at,
                ),
            )
            cursor.execute(
                """
                INSERT INTO public.indexed_climb_completion_receipts (
                    pda, ride_attestation_pda, vault_pda,
                    completion_evidence_version, completion_evidence_hash,
                    cal_tributed, release_authority_pda,
                    credited_settlement_week
                ) VALUES (%s, %s, 'vault-7', 3, %s, 1000000000, %s, 42)
                """,
                (
                    receipt_pda,
                    parent_pda,
                    psycopg2.Binary(evidence_hash),
                    release_pda,
                ),
            )
            cursor.execute(
                """
                INSERT INTO public.indexed_climb_completion_flows (
                    tx_signature, event_index, vault_id, ride_attestation,
                    completion_evidence_hash, credited_settlement_week,
                    cal_tributed, slot, completion_evidence_version,
                    release_authority_pda
                ) VALUES (
                    'completion-tx', 0, 7, %s, %s, 42,
                    1000000000, 100, 3, %s
                )
                """,
                (parent_pda, psycopg2.Binary(evidence_hash), release_pda),
            )
            cursor.execute(
                """
                INSERT INTO public.vault_completions (
                    vault_signature, wallet, activity_id, time_seconds,
                    completed_at, validated, cal_tribute, on_chain_tx,
                    chain_confirmation_status, completion_receipt_pda,
                    completion_evidence_hash, completion_evidence_version,
                    chain_confirmed_at
                ) VALUES (
                    %s, 'rider-wallet', %s, 420, %s, true,
                    1000000000, 'completion-tx', 'confirmed', %s, %s, 3, %s
                )
                """,
                (
                    "07" * 32,
                    str(ride_id),
                    completed_at,
                    receipt_pda,
                    psycopg2.Binary(evidence_hash),
                    completed_at,
                ),
            )

            def legend_candidates() -> dict[str, Any]:
                cursor.execute(
                    "SELECT public.get_confirmed_local_legend_candidates(%s, %s, %s)",
                    (
                        7,
                        completed_at - timedelta(seconds=1),
                        completed_at + timedelta(seconds=1),
                    ),
                )
                return cursor.fetchone()[0]

            assert legend_candidates()["confirmed_receipt_count"] == 0
            cursor.execute(
                """
                UPDATE public.reward_threshold_release_executions
                SET state = 'complete', terminal_projected_at = %s
                WHERE snapshot_id = %s
                """,
                (completed_at, snapshot_id),
            )
            assert legend_candidates()["confirmed_receipt_count"] == 0
            cursor.execute(
                """
                UPDATE public.reward_threshold_release_steps
                SET state = 'projected', projected_at = %s
                WHERE snapshot_id = %s AND step_index = 0
                """,
                (completed_at, snapshot_id),
            )
            legend = legend_candidates()
            assert legend["confirmed_receipt_count"] == 1
            assert legend["wallet_count"] == 1
            assert len(legend["candidates"]) == 1
            candidate = legend["candidates"][0]
            assert candidate["wallet"] == "rider-wallet"
            assert candidate["completion_count"] == 1
            assert datetime.fromisoformat(candidate["first_completed_at"]) == completed_at


def test_zero_weight_release_freezes_and_complete_projection_remains_claimable(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            state = _establish_with_edge_holds(cursor)
            cursor.execute(
                SEGMENT_TSS_RELEASE_MIGRATION_PATH.read_text(encoding="utf-8")
            )
            cursor.execute(
                RIDER_PROJECTION_MIGRATION_PATH.read_text(encoding="utf-8")
            )
            started_at = state["established_at"] - timedelta(days=1, hours=1)
            completed_at = state["established_at"] - timedelta(days=1)
            _insert_complete_zero_parent_plan(
                cursor,
                ride_id=state["current_ride"],
                user_id=state["user_id"],
                started_at=started_at,
                completed_at=completed_at,
            )

            lease_owner = uuid.uuid4()
            cursor.execute(
                "SELECT public.claim_due_reward_threshold_release_item(%s, 60)",
                (lease_owner,),
            )
            claim = cursor.fetchone()[0]
            assert claim["ride_id"] == str(state["current_ride"])

            snapshot_id = uuid.uuid4()
            snapshot = {
                "snapshot_id": str(snapshot_id),
                "batch_item_id": claim["batch_item_id"],
                "ride_id": str(state["current_ride"]),
                "user_id": str(state["user_id"]),
                "wallet": "rider-wallet",
                "ride_hash_hex": _digest(f"ride:{state['current_ride']}").hex(),
                "admitted_at": claim["admitted_at"],
                "established_at": claim["established_at"],
                "reward_ftp_authority_id": str(state["authority_id"]),
                "reward_ftp_authority_evidence_hash_hex": claim[
                    "reward_ftp_authority_evidence_hash_hex"
                ],
                "reward_ftp_w": 245,
                "reward_ftp_source": "derived_eftp",
                "reward_ftp_policy_version": (
                    "reward_ftp_policy_2026_08_24_threshold_v1"
                ),
                "economic_tss": 0.999999999,
                "total_tss": 0,
                "exact_cal_base_units": 999_999_999,
                "exact_tribute_budget_base_units": 99_999_999,
                "expected_release_authority_pda": "release-authority-pda",
                "expected_cal_receipt_pda": "released-cal-pda",
            }
            _attach_canonical_release_evidence(snapshot, [], claim)

            lease_tainted = deepcopy(snapshot)
            lease_tainted["snapshot_evidence"]["planner_lease_owner"] = str(
                lease_owner
            )
            with pytest.raises(
                psycopg2.Error,
                match="Threshold release snapshot evidence is not canonical",
            ):
                cursor.execute(
                    "SELECT public.freeze_reward_threshold_release_snapshot(%s, %s, %s)",
                    (Json(lease_tainted), Json([]), lease_owner),
                )
            cursor.execute(
                "SELECT count(*) FROM public.reward_threshold_release_snapshots"
            )
            assert cursor.fetchone()[0] == 0

            cursor.execute(
                "SELECT public.freeze_reward_threshold_release_snapshot(%s, %s, %s)",
                (Json(snapshot), Json([]), lease_owner),
            )
            frozen = cursor.fetchone()[0]
            assert frozen["snapshot_id"] == str(snapshot_id)
            assert frozen["steps"] == []
            assert frozen["exact_tribute_budget_base_units"] == 99_999_999
            assert frozen["release_plan_evidence_hash_hex"] == frozen[
                "snapshot_evidence_hash_hex"
            ]
            cursor.execute(
                """
                SELECT pg_catalog.encode(
                    pg_catalog.sha256(
                        pg_catalog.convert_to(%s::JSONB::TEXT, 'UTF8')
                    ),
                    'hex'
                )
                """,
                (Json(frozen["snapshot_evidence"]),),
            )
            assert frozen["release_plan_evidence_hash_hex"] == cursor.fetchone()[0]
            assert frozen["snapshot_evidence"]["plan"]["admitted_at"].endswith(
                ".000000+00:00"
            )
            assert frozen["snapshot_evidence"]["plan"]["established_at"].endswith(
                ".000000+00:00"
            )

            # Semantically equivalent timestamp offsets and numeric scales
            # must replay to the one authoritative snapshot/hash. The planner
            # lease is deliberately different: lease ownership is transient
            # coordination state and cannot taint permanent plan authority.
            replay = deepcopy(snapshot)
            offset = timezone(timedelta(hours=-4))
            for field in ("admitted_at", "established_at"):
                equivalent_timestamp = datetime.fromisoformat(
                    replay[field]
                ).astimezone(offset).isoformat()
                replay[field] = equivalent_timestamp
                replay["snapshot_evidence"]["plan"][field] = equivalent_timestamp
            cursor.execute(
                """
                SELECT public.freeze_reward_threshold_release_snapshot(
                    pg_catalog.jsonb_set(
                        pg_catalog.jsonb_set(
                            %s::JSONB,
                            '{economic_tss}',
                            '0.9999999990'::JSONB,
                            false
                        ),
                        '{snapshot_evidence,plan,economic_tss}',
                        '0.9999999990'::JSONB,
                        false
                    ),
                    '[]'::JSONB,
                    %s
                )
                """,
                (Json(replay), uuid.uuid4()),
            )
            replayed = cursor.fetchone()[0]
            assert replayed["snapshot_id"] == frozen["snapshot_id"]
            assert replayed["snapshot_evidence_hash_hex"] == frozen[
                "snapshot_evidence_hash_hex"
            ]

            execution_owner = uuid.uuid4()
            cursor.execute(
                "SELECT public.claim_due_reward_threshold_release_execution(%s, 60)",
                (execution_owner,),
            )
            assert cursor.fetchone()[0]["state"] == "planned"
            cursor.execute(
                """
                SELECT public.advance_reward_threshold_release_execution(
                    %s, %s, 'planned', 'release_authority_confirmed', %s
                )
                """,
                (
                    snapshot_id,
                    execution_owner,
                    Json({"release_authority_confirmed_at": completed_at.isoformat()}),
                ),
            )
            assert cursor.fetchone()[0]["state"] == "release_authority_confirmed"
            cursor.execute(
                """
                SELECT public.advance_reward_threshold_release_execution(
                    %s, %s, 'release_authority_confirmed',
                    'cal_confirmed', %s
                )
                """,
                (
                    snapshot_id,
                    execution_owner,
                    Json({"cal_confirmed_at": completed_at.isoformat()}),
                ),
            )
            assert cursor.fetchone()[0]["state"] == "cal_confirmed"
            cursor.execute(
                """
                SELECT public.advance_reward_threshold_release_execution(
                    %s, %s, 'cal_confirmed', 'completions_confirmed',
                    '{}'::JSONB
                )
                """,
                (snapshot_id, execution_owner),
            )
            recovered_without_signatures = cursor.fetchone()[0]
            assert recovered_without_signatures["state"] == "completions_confirmed"
            assert recovered_without_signatures["release_authority_actual_tx_signature"] is None
            assert recovered_without_signatures["cal_actual_tx_signature"] is None

            cursor.execute(
                """
                UPDATE public.reward_threshold_release_executions
                SET state = 'complete',
                    release_authority_actual_tx_signature = 'release-tx',
                    release_authority_confirmed_at = %s,
                    cal_actual_tx_signature = 'cal-tx',
                    cal_confirmed_at = %s,
                    lease_expires_at = pg_catalog.clock_timestamp()
                        - INTERVAL '1 second',
                    terminal_projected_at = NULL
                WHERE snapshot_id = %s
                """,
                (completed_at, completed_at, snapshot_id),
            )
            recovery_owner = uuid.uuid4()
            cursor.execute(
                "SELECT public.claim_due_reward_threshold_release_execution(%s, 60)",
                (recovery_owner,),
            )
            recovered = cursor.fetchone()[0]
            assert recovered["snapshot_id"] == str(snapshot_id)
            assert recovered["state"] == "complete"

            # The due index must include chain-complete executions until their
            # terminal rider projection is durable.
            cursor.execute("SET enable_seqscan = off")
            cursor.execute(
                """
                EXPLAIN (FORMAT TEXT)
                SELECT snapshot_id
                FROM public.reward_threshold_release_executions
                WHERE state <> 'review'
                  AND (
                      state <> 'complete'
                      OR terminal_projected_at IS NULL
                      OR training_projected_at IS NULL
                  )
                ORDER BY next_attempt_at, created_at
                LIMIT 1
                """
            )
            explain = "\n".join(row[0] for row in cursor.fetchall())
            cursor.execute("RESET enable_seqscan")
            assert "idx_reward_threshold_release_execution_due" in explain

            with pytest.raises(
                psycopg2.Error,
                match="terminal projection lacks exact indexed authority",
            ):
                cursor.execute(
                    "SELECT public.project_reward_threshold_release_terminal(%s)",
                    (snapshot_id,),
                )
            cursor.execute(
                """
                SELECT public.checkpoint_reward_threshold_release_retry(
                    %s, %s, 'indexer lag', NULL, 30
                )
                """,
                (snapshot_id, recovery_owner),
            )
            assert cursor.fetchone()[0] is True
            cursor.execute(
                """
                SELECT next_attempt_at > pg_catalog.clock_timestamp(),
                       lease_owner, lease_expires_at
                FROM public.reward_threshold_release_executions
                WHERE snapshot_id = %s
                """,
                (snapshot_id,),
            )
            assert cursor.fetchone() == (True, None, None)
            cursor.execute(
                "SELECT public.claim_due_reward_threshold_release_execution(%s, 60)",
                (uuid.uuid4(),),
            )
            assert cursor.fetchone()[0] is None
            cursor.execute(
                """
                UPDATE public.reward_threshold_release_executions
                SET next_attempt_at = pg_catalog.clock_timestamp()
                    - INTERVAL '1 second'
                WHERE snapshot_id = %s
                """,
                (snapshot_id,),
            )
            projection_owner = uuid.uuid4()
            cursor.execute(
                "SELECT public.claim_due_reward_threshold_release_execution(%s, 60)",
                (projection_owner,),
            )
            assert cursor.fetchone()[0]["state"] == "complete"

            release_pda = "release-authority-pda"
            cal_pda = "released-cal-pda"
            parent_pda = f"parent-attestation:{state['current_ride']}"
            cursor.execute(
                """
                SELECT pg_catalog.encode(evidence_hash, 'hex'),
                       EXTRACT(epoch FROM effective_at)::BIGINT,
                       ftp_w
                FROM public.reward_ftp_authorities
                WHERE id = %s
                """,
                (state["authority_id"],),
            )
            authority_commitment, authority_effective_at, authority_w = (
                cursor.fetchone()
            )
            cursor.execute(
                """
                INSERT INTO public.indexed_held_ride_release_authorities (
                    pda, ride_attestation_pda, rider_pubkey,
                    threshold_authority_id_hex,
                    threshold_authority_commitment_hex,
                    threshold_effective_at, threshold_w,
                    threshold_policy_version, economic_tss, cal_earned,
                    cal_tribute_budget, release_plan_hash_hex, released_at,
                    released_slot, release_settlement_week, attester, bump
                ) VALUES (
                    %s, %s, 'rider-wallet', %s, %s, %s, %s, 1, 0,
                    999999999, 99999999, %s, %s, 100, 42,
                    'release-attester', 1
                )
                """,
                (
                    release_pda,
                    parent_pda,
                    state["authority_id"].hex,
                    authority_commitment,
                    authority_effective_at,
                    authority_w,
                    frozen["release_plan_evidence_hash_hex"],
                    int(completed_at.timestamp()),
                ),
            )
            cursor.execute(
                """
                INSERT INTO public.indexed_cal_mint_receipts (
                    pda, ride_attestation_pda, rider_pubkey, amount,
                    release_authority_pda, release_settlement_week
                ) VALUES (%s, %s, 'rider-wallet', 999999999, %s, 42)
                """,
                (cal_pda, parent_pda, release_pda),
            )
            cursor.execute(
                "SELECT public.project_reward_threshold_release_terminal(%s)",
                (snapshot_id,),
            )
            projected = cursor.fetchone()[0]
            assert projected["terminal_projected_at"] is not None
            cursor.execute(
                """
                SELECT cal_earned, tss, threshold_training_w,
                       threshold_training_kind, threshold_training_authority_id
                FROM public.rides
                WHERE id = %s
                """,
                (state["current_ride"],),
            )
            # 999,999,999 base units are real released CAL but truncate to
            # zero whole CAL on the legacy integer rider projection.
            assert cursor.fetchone() == (
                0,
                Decimal("0.999999999"),
                245,
                "sealed",
                state["authority_id"],
            )
            cursor.execute(
                """
                SELECT lease_owner, training_projected_at
                FROM public.reward_threshold_release_executions
                WHERE snapshot_id = %s
                """,
                (snapshot_id,),
            )
            assert cursor.fetchone() == (projection_owner, None)


def test_v2_release_recomputes_measured_climb_tss_from_frozen_hold(
    postgres_dsn: str,
) -> None:
    completed_at = datetime(2026, 8, 23, 12, tzinfo=timezone.utc)
    pattern_id = uuid.uuid4()
    frozen_step = {
        "pattern_id": str(pattern_id),
        "vault_id": 7,
        "vault_signature": "07" * 32,
        "completion_time_s": 60,
        "completed_at": completed_at.isoformat(),
        "segment_start_offset_s": 60,
        "segment_end_offset_s": 119,
        "segment_np_w": 200,
        "segment_np_milliwatts": 200_000,
        "segment_np_duration_s": 60,
        "segment_power_sample_count": 60,
        "segment_power_coverage_bps": 10_000,
        "segment_power_metrics_version": "workout_parse_metrics_v1",
        "tribute_weight": 0,
        "climb_distance_m": 600,
        "climb_vert_m": 60,
    }
    hold_evidence = {"version": 2, "completion_steps": [frozen_step]}
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            state = _establish_with_edge_holds(
                cursor, current_hold_evidence=hold_evidence
            )
            cursor.execute(
                SEGMENT_TSS_RELEASE_MIGRATION_PATH.read_text(encoding="utf-8")
            )
            _insert_complete_zero_parent_plan(
                cursor,
                ride_id=state["current_ride"],
                user_id=state["user_id"],
                started_at=completed_at - timedelta(hours=1),
                completed_at=completed_at,
            )
            lease_owner = uuid.uuid4()
            cursor.execute(
                "SELECT public.claim_due_reward_threshold_release_item(%s, 60)",
                (lease_owner,),
            )
            claim = cursor.fetchone()[0]
            tribute = 1_110_648_340
            step = {
                **frozen_step,
                "step_index": 0,
                "exact_tribute_base_units": tribute,
                "intensity_bps": 8_163,
                "completion_evidence_version": 3,
                "completion_evidence_hash_hex": _digest("v2-tss-step").hex(),
                "expected_receipt_pda": "v2-tss-completion-pda",
            }
            snapshot = _release_snapshot_from_claim(
                claim,
                economic_tss=10.0,
                exact_cal_base_units=10_000_000_000,
                exact_tribute_budget_base_units=tribute,
                steps=[step],
                pda_prefix="v2-tss",
            )
            _attach_canonical_release_evidence(
                snapshot,
                [step],
                claim,
                domain="BR_THRESHOLD_HELD_RIDE_RELEASE_PLAN_V2",
            )

            cursor.execute(
                "SELECT public.freeze_reward_threshold_release_snapshot(%s, %s, %s)",
                (Json(snapshot), Json([step]), lease_owner),
            )
            frozen = cursor.fetchone()[0]
            assert frozen["exact_tribute_budget_base_units"] == tribute
            assert frozen["steps"][0]["exact_tribute_base_units"] == tribute
            cursor.execute(
                "SELECT public.resolve_reward_threshold_release_lifecycle(%s)",
                (state["current_ride"],),
            )
            lifecycle = cursor.fetchone()[0]
            assert lifecycle["snapshot"]["snapshot_evidence"]["domain"] == (
                "BR_THRESHOLD_HELD_RIDE_RELEASE_PLAN_V2"
            )


def test_nonempty_release_cannot_freeze_an_underallocated_tribute_budget(
    postgres_dsn: str,
) -> None:
    completed_at = datetime(2026, 8, 23, 12, tzinfo=timezone.utc)
    pattern_id = uuid.uuid4()
    hold_evidence = {
        "version": 1,
        "completion_steps": [
            {
                "pattern_id": str(pattern_id),
                "vault_id": 7,
                "vault_signature": "07" * 32,
                "completion_time_s": 420,
                "completed_at": completed_at.isoformat(),
                "segment_start_offset_s": 60,
                "segment_end_offset_s": 480,
                "segment_np_w": 250,
                "segment_power_sample_count": 420,
                "segment_power_coverage_bps": 10_000,
                "segment_power_metrics_version": "workout_parse_metrics_v1",
                "tribute_weight": 105_000,
                "climb_distance_m": 1_200,
                "climb_vert_m": 90,
            }
        ],
    }
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            state = _establish_with_edge_holds(
                cursor, current_hold_evidence=hold_evidence
            )
            _insert_complete_zero_parent_plan(
                cursor,
                ride_id=state["current_ride"],
                user_id=state["user_id"],
                started_at=completed_at - timedelta(hours=1),
                completed_at=completed_at,
            )
            lease_owner = uuid.uuid4()
            cursor.execute(
                "SELECT public.claim_due_reward_threshold_release_item(%s, 60)",
                (lease_owner,),
            )
            claim = cursor.fetchone()[0]
            step = {
                **hold_evidence["completion_steps"][0],
                "step_index": 0,
                "exact_tribute_base_units": 99_999_999,
                "intensity_bps": 10_204,
                "completion_evidence_version": 3,
                "completion_evidence_hash_hex": _digest("underallocated-step").hex(),
                "expected_receipt_pda": "underallocated-completion-pda",
            }
            snapshot = {
                "snapshot_id": str(uuid.uuid4()),
                "batch_item_id": claim["batch_item_id"],
                "ride_id": claim["ride_id"],
                "user_id": claim["user_id"],
                "wallet": claim["wallet"],
                "ride_hash_hex": claim["ride_hash_hex"],
                "admitted_at": claim["admitted_at"],
                "established_at": claim["established_at"],
                "reward_ftp_authority_id": claim["reward_ftp_authority_id"],
                "reward_ftp_authority_evidence_hash_hex": claim[
                    "reward_ftp_authority_evidence_hash_hex"
                ],
                "reward_ftp_w": claim["reward_ftp_w"],
                "reward_ftp_source": claim["reward_ftp_source"],
                "reward_ftp_policy_version": claim["reward_ftp_policy_version"],
                "economic_tss": 1.0,
                "total_tss": 1,
                "exact_cal_base_units": 1_000_000_000,
                "exact_tribute_budget_base_units": 100_000_000,
                "expected_release_authority_pda": "underallocated-release-pda",
                "expected_cal_receipt_pda": "underallocated-cal-pda",
            }
            _attach_canonical_release_evidence(snapshot, [step], claim)

            with pytest.raises(
                psycopg2.Error,
                match="Threshold release tribute allocation is not canonical",
            ):
                cursor.execute(
                    "SELECT public.freeze_reward_threshold_release_snapshot(%s, %s, %s)",
                    (Json(snapshot), Json([step]), lease_owner),
                )
            cursor.execute(
                """
                SELECT
                    (SELECT count(*) FROM public.reward_threshold_release_snapshots),
                    (SELECT count(*) FROM public.reward_threshold_release_executions),
                    (SELECT count(*) FROM public.reward_threshold_release_steps)
                """
            )
            assert cursor.fetchone() == (0, 0, 0)


def test_release_cannot_redistribute_a_conserved_budget_between_vaults(
    postgres_dsn: str,
) -> None:
    completed_at = datetime(2026, 8, 23, 12, tzinfo=timezone.utc)
    provisional_steps = [
        {
            "pattern_id": str(uuid.uuid4()),
            "vault_id": 7,
            "vault_signature": "07" * 32,
            "completion_time_s": 400,
            "completed_at": completed_at.isoformat(),
            "segment_start_offset_s": 60,
            "segment_end_offset_s": 460,
            "segment_np_w": 200,
            "segment_power_sample_count": 400,
            "segment_power_coverage_bps": 10_000,
            "segment_power_metrics_version": "workout_parse_metrics_v1",
            "tribute_weight": 80_000,
            "climb_distance_m": 1_000,
            "climb_vert_m": 80,
        },
        {
            "pattern_id": str(uuid.uuid4()),
            "vault_id": 9,
            "vault_signature": "09" * 32,
            "completion_time_s": 500,
            "completed_at": completed_at.isoformat(),
            "segment_start_offset_s": 600,
            "segment_end_offset_s": 1_100,
            "segment_np_w": 300,
            "segment_power_sample_count": 500,
            "segment_power_coverage_bps": 10_000,
            "segment_power_metrics_version": "workout_parse_metrics_v1",
            "tribute_weight": 150_000,
            "climb_distance_m": 2_000,
            "climb_vert_m": 160,
        },
    ]
    budget = 100_000_000
    total_weight = sum(step["tribute_weight"] for step in provisional_steps)
    shares = [
        step["tribute_weight"] * budget // total_weight
        for step in provisional_steps
    ]
    remainders = [
        (
            step["tribute_weight"] * budget % total_weight,
            step["vault_id"],
            index,
        )
        for index, step in enumerate(provisional_steps)
    ]
    for _, _, index in sorted(remainders, key=lambda item: (-item[0], item[1]))[
        : budget - sum(shares)
    ]:
        shares[index] += 1
    skewed_shares = list(reversed(shares))
    assert sum(skewed_shares) == budget
    assert skewed_shares != shares

    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            state = _establish_with_edge_holds(
                cursor,
                current_hold_evidence={
                    "version": 1,
                    "completion_steps": provisional_steps,
                },
            )
            _insert_complete_zero_parent_plan(
                cursor,
                ride_id=state["current_ride"],
                user_id=state["user_id"],
                started_at=completed_at - timedelta(hours=1),
                completed_at=completed_at,
            )
            lease_owner = uuid.uuid4()
            cursor.execute(
                "SELECT public.claim_due_reward_threshold_release_item(%s, 60)",
                (lease_owner,),
            )
            claim = cursor.fetchone()[0]
            steps = []
            for index, (provisional, tribute) in enumerate(
                zip(provisional_steps, skewed_shares)
            ):
                steps.append(
                    {
                        **provisional,
                        "step_index": index,
                        "exact_tribute_base_units": tribute,
                        "intensity_bps": (
                            provisional["segment_np_w"] * 10_000 // 245
                        ),
                        "completion_evidence_version": 3,
                        "completion_evidence_hash_hex": _digest(
                            f"skewed-step:{index}"
                        ).hex(),
                        "expected_receipt_pda": f"skewed-receipt-{index}",
                    }
                )
            snapshot = _release_snapshot_from_claim(
                claim,
                economic_tss=1.0,
                exact_cal_base_units=1_000_000_000,
                exact_tribute_budget_base_units=budget,
                steps=steps,
                pda_prefix="skewed",
            )

            with pytest.raises(
                psycopg2.Error,
                match="Threshold release tribute allocation is not canonical",
            ):
                cursor.execute(
                    "SELECT public.freeze_reward_threshold_release_snapshot(%s, %s, %s)",
                    (Json(snapshot), Json(steps), lease_owner),
                )
            cursor.execute(
                "SELECT count(*) FROM public.reward_threshold_release_snapshots"
            )
            assert cursor.fetchone()[0] == 0


def test_all_zero_weight_steps_freeze_zero_tribute_under_the_budget_cap(
    postgres_dsn: str,
) -> None:
    completed_at = datetime(2026, 8, 23, 12, tzinfo=timezone.utc)
    provisional = {
        "pattern_id": str(uuid.uuid4()),
        "vault_id": 7,
        "vault_signature": "07" * 32,
        "completion_time_s": 420,
        "completed_at": completed_at.isoformat(),
        "segment_start_offset_s": 60,
        "segment_end_offset_s": 480,
        "segment_np_w": None,
        "segment_power_sample_count": 0,
        "segment_power_coverage_bps": 0,
        "segment_power_metrics_version": "workout_parse_metrics_v1",
        "tribute_weight": 0,
        "climb_distance_m": 1_200,
        "climb_vert_m": 90,
    }
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            state = _establish_with_edge_holds(
                cursor,
                current_hold_evidence={
                    "version": 1,
                    "completion_steps": [provisional],
                },
            )
            _insert_complete_zero_parent_plan(
                cursor,
                ride_id=state["current_ride"],
                user_id=state["user_id"],
                started_at=completed_at - timedelta(hours=1),
                completed_at=completed_at,
            )
            lease_owner = uuid.uuid4()
            cursor.execute(
                "SELECT public.claim_due_reward_threshold_release_item(%s, 60)",
                (lease_owner,),
            )
            claim = cursor.fetchone()[0]
            step = {
                **provisional,
                "step_index": 0,
                "exact_tribute_base_units": 0,
                "intensity_bps": 0,
                "completion_evidence_version": 3,
                "completion_evidence_hash_hex": _digest("zero-weight-step").hex(),
                "expected_receipt_pda": "zero-weight-receipt",
            }
            snapshot = _release_snapshot_from_claim(
                claim,
                economic_tss=1.0,
                exact_cal_base_units=1_000_000_000,
                exact_tribute_budget_base_units=100_000_000,
                steps=[step],
                pda_prefix="zero-weight",
            )

            cursor.execute(
                "SELECT public.freeze_reward_threshold_release_snapshot(%s, %s, %s)",
                (Json(snapshot), Json([step]), lease_owner),
            )
            frozen = cursor.fetchone()[0]
            assert frozen["exact_tribute_budget_base_units"] == 100_000_000
            assert frozen["steps"][0]["exact_tribute_base_units"] == 0


def test_review_repair_preserves_cal_and_confirmed_completion_receipts(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            state = _establish_with_edge_holds(cursor)
            completed_at = state["established_at"] - timedelta(days=1)
            _insert_complete_zero_parent_plan(
                cursor,
                ride_id=state["current_ride"],
                user_id=state["user_id"],
                started_at=completed_at - timedelta(hours=1),
                completed_at=completed_at,
            )
            cursor.execute(
                """
                SELECT id
                FROM public.reward_threshold_release_batch_items
                WHERE batch_id = %s AND hold_id = %s
                """,
                (state["batch_id"], state["current_hold"]),
            )
            item_id = cursor.fetchone()[0]
            snapshot_id = uuid.uuid4()
            cursor.execute(
                """
                INSERT INTO public.reward_threshold_release_snapshots (
                    id, batch_item_id, ride_id, user_id,
                    reward_ftp_authority_id, reward_ftp_w, reward_ftp_source,
                    reward_ftp_policy_version, economic_tss,
                    exact_cal_base_units, exact_tribute_budget_base_units,
                    snapshot_evidence, snapshot_evidence_hash
                ) VALUES (
                    %s, %s, %s, %s, %s, 245, 'derived_eftp',
                    'reward_ftp_policy_2026_08_24_threshold_v1', 10,
                    10000000000, 1000000000, %s, %s
                )
                """,
                (
                    snapshot_id,
                    item_id,
                    state["current_ride"],
                    state["user_id"],
                    state["authority_id"],
                    Json({"version": 1, "review_repair": True}),
                    psycopg2.Binary(_digest(f"repair-snapshot:{snapshot_id}")),
                ),
            )
            cursor.execute(
                """
                INSERT INTO public.reward_threshold_release_executions (
                    snapshot_id, wallet, ride_hash, release_plan_evidence_hash,
                    expected_release_authority_pda, expected_cal_receipt_pda,
                    state, release_authority_actual_tx_signature,
                    release_authority_confirmed_at, cal_actual_tx_signature,
                    cal_confirmed_at
                ) VALUES (
                    %s, 'rider-wallet', %s, %s, %s, %s,
                    'cal_confirmed', 'release-tx', %s, 'cal-tx', %s
                )
                """,
                (
                    snapshot_id,
                    psycopg2.Binary(_digest(f"ride:{state['current_ride']}")),
                    psycopg2.Binary(_digest(f"repair-plan:{snapshot_id}")),
                    f"release:{snapshot_id}",
                    f"cal:{snapshot_id}",
                    completed_at,
                    completed_at,
                ),
            )
            for step_index, step_state in ((0, "confirmed"), (1, "planned")):
                cursor.execute(
                    """
                    INSERT INTO public.reward_threshold_release_steps (
                        snapshot_id, step_index, pattern_id, vault_id,
                        vault_signature, completion_time_s, completed_at,
                        exact_tribute_base_units, completion_evidence_hash,
                        expected_receipt_pda, state, actual_tx_signature,
                        chain_confirmed_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, 300, %s,
                        500000000, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        snapshot_id,
                        step_index,
                        uuid.uuid4(),
                        70 + step_index,
                        f"vault-{step_index}",
                        completed_at,
                        psycopg2.Binary(
                            _digest(f"repair-step:{snapshot_id}:{step_index}")
                        ),
                        f"receipt:{snapshot_id}:{step_index}",
                        step_state,
                        "completion-0-tx" if step_index == 0 else None,
                        completed_at if step_index == 0 else None,
                    ),
                )

            lease_owner = uuid.uuid4()
            cursor.execute(
                "SELECT public.claim_due_reward_threshold_release_execution(%s, 60)",
                (lease_owner,),
            )
            assert cursor.fetchone()[0]["state"] == "cal_confirmed"
            cursor.execute(
                """
                SELECT public.mark_reward_threshold_release_review(
                    %s, %s, 'receipt mismatch', %s
                )
                """,
                (snapshot_id, lease_owner, Json({"step_index": 1})),
            )
            assert cursor.fetchone()[0]["state"] == "review"
            cursor.execute(
                """
                SELECT step_index, state, actual_tx_signature
                FROM public.reward_threshold_release_steps
                WHERE snapshot_id = %s
                ORDER BY step_index
                """,
                (snapshot_id,),
            )
            assert cursor.fetchall() == [
                (0, "confirmed", "completion-0-tx"),
                (1, "review", None),
            ]

            cursor.execute(
                "SELECT public.repair_reward_threshold_release_execution(%s, %s)",
                (snapshot_id, "operator verified step 1 authority"),
            )
            repaired = cursor.fetchone()[0]
            assert repaired["state"] == "cal_confirmed"
            assert repaired["release_authority_actual_tx_signature"] == "release-tx"
            assert repaired["cal_actual_tx_signature"] == "cal-tx"
            assert repaired["review_reason"] is None
            cursor.execute(
                """
                SELECT step_index, state, actual_tx_signature
                FROM public.reward_threshold_release_steps
                WHERE snapshot_id = %s
                ORDER BY step_index
                """,
                (snapshot_id,),
            )
            assert cursor.fetchall() == [
                (0, "confirmed", "completion-0-tx"),
                (1, "planned", None),
            ]
            cursor.execute(
                "SELECT public.claim_due_reward_threshold_release_execution(%s, 60)",
                (uuid.uuid4(),),
            )
            assert cursor.fetchone()[0]["state"] == "cal_confirmed"
