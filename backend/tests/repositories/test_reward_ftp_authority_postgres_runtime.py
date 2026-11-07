"""PostgreSQL runtime proof for immutable reward-FTP authority."""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta, timezone
from pathlib import Path
from threading import Barrier
import uuid

import psycopg2
import pytest
from psycopg2.extras import Json

from backend.tests.repositories.test_parser_provenance_postgres_runtime import (
    PROVENANCE_SQL,
    _bootstrap,
    _connection,
    _plan,
)
from backend.tests.services.test_settlement_clock_postgres_runtime import postgres_dsn


BACKEND_ROOT = Path(__file__).resolve().parents[2]
AUTHORITATIVE_SQL = (
    BACKEND_ROOT / "sql" / "122_authoritative_ride_metrics.sql"
).read_text(encoding="utf-8")
REVIEW_REPAIR_SQL = (
    BACKEND_ROOT / "sql" / "115_ride_economic_review_repair.sql"
).read_text(encoding="utf-8")
TRIBUTE_CONSERVATION_SQL = (
    BACKEND_ROOT / "sql" / "121_tribute_conservation.sql"
).read_text(encoding="utf-8")
REWARD_FTP_SQL = (
    BACKEND_ROOT / "sql" / "123_reward_ftp_authority.sql"
).read_text(encoding="utf-8")
POLICY = "ride_effort_policy_2026_07_14_ftp_v1"
IMPLEMENTATION_COMMIT = "9f97a5a92c3987d7d36b617cb01dde50f46f94e4"


def test_reward_ftp_authority_binds_by_ride_time_and_freezes_plan_provenance(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap(cursor)
            cursor.execute("CREATE SCHEMA extensions")
            cursor.execute("ALTER EXTENSION pgcrypto SET SCHEMA extensions")
            cursor.execute(
                """
                SELECT
                    to_regprocedure('public.digest(bytea,text)') IS NULL,
                    to_regprocedure('extensions.digest(bytea,text)') IS NOT NULL,
                    to_regprocedure('pg_catalog.sha256(bytea)') IS NOT NULL
                """
            )
            assert cursor.fetchone() == (True, True, True)
            cursor.execute(REVIEW_REPAIR_SQL)
            cursor.execute(PROVENANCE_SQL)
            cursor.execute(TRIBUTE_CONSERVATION_SQL)
            cursor.execute(AUTHORITATIVE_SQL)

            user_id = uuid.uuid4()
            historical_ride_id = uuid.uuid4()
            cursor.execute("INSERT INTO public.users (id) VALUES (%s)", (user_id,))
            cursor.execute(
                "INSERT INTO public.rides (id, user_id) VALUES (%s, %s)",
                (historical_ride_id, user_id),
            )
            historical_plan = _plan(historical_ride_id, user_id, 3)
            historical_plan["policy_version"] = "ride_effort_policy_2026_07_14"
            cursor.execute(
                "SELECT public.freeze_ride_economic_plan(%s, %s)",
                (Json(historical_plan), Json([])),
            )

            cursor.execute(REWARD_FTP_SQL)
            cursor.execute(REWARD_FTP_SQL)

            cursor.execute(
                """
                SELECT reward_ftp_w, reward_ftp_source,
                       reward_ftp_authority_id, reward_ftp_policy_version,
                       economic_tss
                FROM public.rides WHERE id = %s
                """,
                (historical_ride_id,),
            )
            assert cursor.fetchone() == (None, None, None, None, None)
            cursor.execute(
                """
                SELECT reward_ftp_w, reward_ftp_source,
                       reward_ftp_authority_id, reward_ftp_policy_version
                FROM public.ride_economic_plans WHERE ride_id = %s
                """,
                (historical_ride_id,),
            )
            assert cursor.fetchone() == (None, None, None, None)

            cursor.execute(
                """
                SELECT id, effective_at, evidence_hash
                FROM public.register_reward_ftp_authority(
                    %s, 250, 'verified_power_test',
                    '{"protocol":"ramp_test"}'::JSONB, 'test-verifier', NULL
                )
                """,
                (user_id,),
            )
            authority_id, effective_at, evidence_hash = cursor.fetchone()
            assert len(bytes(evidence_hash)) == 32
            assert bytes(evidence_hash).hex() == hashlib.sha256(
                b'{"protocol": "ramp_test"}'
            ).hexdigest()
            effective_at_utc = effective_at.astimezone(timezone.utc)
            assert effective_at_utc.weekday() == 0
            assert (effective_at_utc.hour, effective_at_utc.minute) == (12, 0)
            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="cannot activate before next Monday 12:00 UTC",
            ):
                cursor.execute(
                    """
                    SELECT id FROM public.register_reward_ftp_authority(
                        %s, 260, 'operator_verified', '{}'::JSONB,
                        'test-verifier', %s
                    )
                    """,
                    (user_id, effective_at - timedelta(seconds=1)),
                )
            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="must activate Monday 12:00 UTC",
            ):
                cursor.execute(
                    """
                    SELECT id FROM public.register_reward_ftp_authority(
                        %s, 260, 'operator_verified', '{}'::JSONB,
                        'test-verifier', %s
                    )
                    """,
                    (user_id, effective_at + timedelta(days=1)),
                )

            second_effective_at = effective_at + timedelta(weeks=1)
            cursor.execute(
                """
                SELECT id, supersedes_id
                FROM public.register_reward_ftp_authority(
                    %s, 225, 'operator_verified',
                    '{"reason":"verified_decrease"}'::JSONB,
                    'test-verifier', %s
                )
                """,
                (user_id, second_effective_at),
            )
            second_authority_id, supersedes_id = cursor.fetchone()
            assert supersedes_id == authority_id
            before_effective = effective_at - timedelta(seconds=1)
            after_effective = effective_at + timedelta(seconds=1)

            before_ride_id = uuid.uuid4()
            after_ride_id = uuid.uuid4()
            cursor.execute(
                "INSERT INTO public.rides (id, user_id) VALUES (%s, %s), (%s, %s)",
                (before_ride_id, user_id, after_ride_id, user_id),
            )
            cursor.execute(
                "SELECT * FROM public.bind_ride_reward_ftp(%s, %s)",
                (before_ride_id, before_effective),
            )
            assert cursor.fetchone()[:4] == (
                200,
                "network_default",
                None,
                "reward_ftp_policy_2026_07_14",
            )
            cursor.execute(
                "SELECT * FROM public.bind_ride_reward_ftp(%s, %s)",
                (after_ride_id, after_effective),
            )
            assert cursor.fetchone()[:4] == (
                250,
                "verified_power_test",
                authority_id,
                "reward_ftp_policy_2026_07_14",
            )

            cursor.execute(
                "SELECT * FROM public.bind_ride_reward_ftp(%s, %s)",
                (before_ride_id, after_effective),
            )
            assert cursor.fetchone()[:3] == (200, "network_default", None)

            decreased_ride_id = uuid.uuid4()
            cursor.execute(
                "INSERT INTO public.rides (id, user_id) VALUES (%s, %s)",
                (decreased_ride_id, user_id),
            )
            cursor.execute(
                "SELECT * FROM public.bind_ride_reward_ftp(%s, %s)",
                (decreased_ride_id, second_effective_at + timedelta(seconds=1)),
            )
            assert cursor.fetchone()[:3] == (
                225,
                "operator_verified",
                second_authority_id,
            )

            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="append-only",
            ):
                cursor.execute(
                    "UPDATE public.reward_ftp_authorities SET ftp_w = 251 WHERE id = %s",
                    (authority_id,),
                )
            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="snapshot is immutable",
            ):
                cursor.execute(
                    "UPDATE public.rides SET reward_ftp_w = 201 WHERE id = %s",
                    (before_ride_id,),
                )

            cursor.execute(
                "UPDATE public.rides SET economic_tss = 84.5 WHERE id = %s",
                (after_ride_id,),
            )
            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="economic TSS snapshot is immutable",
            ):
                cursor.execute(
                    "UPDATE public.rides SET economic_tss = 85 WHERE id = %s",
                    (after_ride_id,),
                )

            mismatch_ride_id = uuid.uuid4()
            cursor.execute(
                "INSERT INTO public.rides (id, user_id) VALUES (%s, %s)",
                (mismatch_ride_id, user_id),
            )
            cursor.execute(
                "SELECT * FROM public.bind_ride_reward_ftp(%s, %s)",
                (mismatch_ride_id, before_effective),
            )
            cursor.execute(
                "UPDATE public.rides SET economic_tss = 84.5 WHERE id = %s",
                (mismatch_ride_id,),
            )
            mismatch_plan = _plan(mismatch_ride_id, user_id, 3)
            mismatch_plan.update(
                {
                    "policy_version": POLICY,
                    "started_at": before_effective.isoformat(),
                    "completed_at": (
                        before_effective + timedelta(hours=1)
                    ).isoformat(),
                    "total_tss": 85,
                    "reward_ftp_w": 200,
                    "reward_ftp_source": "network_default",
                    "reward_ftp_authority_id": None,
                    "reward_ftp_policy_version": "reward_ftp_policy_2026_07_14",
                }
            )
            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="differs from ride snapshot",
            ):
                cursor.execute(
                    "SELECT public.freeze_ride_economic_plan(%s, %s)",
                    (Json(mismatch_plan), Json([])),
                )

            plan = _plan(after_ride_id, user_id, 3)
            plan.update(
                {
                    "policy_version": POLICY,
                    "started_at": after_effective.isoformat(),
                    "completed_at": (after_effective + timedelta(hours=1)).isoformat(),
                    "reward_ftp_w": 250,
                    "reward_ftp_source": "verified_power_test",
                    "reward_ftp_authority_id": str(authority_id),
                    "reward_ftp_policy_version": "reward_ftp_policy_2026_07_14",
                }
            )
            cursor.execute(
                "SELECT public.freeze_ride_economic_plan(%s, %s)",
                (Json(plan), Json([])),
            )
            cursor.execute(
                """
                SELECT plan.reward_ftp_w, plan.reward_ftp_source,
                       plan.reward_ftp_authority_id,
                       plan.reward_ftp_policy_version,
                       version.policy_version, version.git_commit
                FROM public.ride_economic_plans AS plan
                JOIN public.pipeline_versions AS version
                  ON version.id = plan.pipeline_version_id
                WHERE plan.ride_id = %s
                """,
                (after_ride_id,),
            )
            assert cursor.fetchone() == (
                250,
                "verified_power_test",
                authority_id,
                "reward_ftp_policy_2026_07_14",
                POLICY,
                IMPLEMENTATION_COMMIT,
            )
            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="frozen plan reward FTP provenance cannot be changed",
            ):
                cursor.execute(
                    """
                    UPDATE public.ride_economic_plans
                    SET reward_ftp_w = 249 WHERE ride_id = %s
                    """,
                    (after_ride_id,),
                )

            cursor.execute(
                """
                SELECT parser_version, ride_parser_version, policy_version,
                       economics_version, git_commit
                FROM public.pipeline_versions
                WHERE deactivated_at IS NULL
                """
            )
            assert cursor.fetchall() == [
                ("3-ftp-v1", 3, POLICY, POLICY, IMPLEMENTATION_COMMIT)
            ]
            cursor.execute(
                """
                SELECT
                    has_function_privilege(
                        'service_role',
                        'public.bind_ride_reward_ftp(uuid,timestamptz)',
                        'EXECUTE'
                    ),
                    has_function_privilege(
                        'authenticated',
                        'public.bind_ride_reward_ftp(uuid,timestamptz)',
                        'EXECUTE'
                    ),
                    has_function_privilege(
                        'service_role',
                        'public.freeze_ride_economic_plan_without_reward_ftp(jsonb,jsonb)',
                        'EXECUTE'
                    )
                """
            )
            assert cursor.fetchone() == (True, False, False)

            concurrent_ride_id = uuid.uuid4()
            cursor.execute(
                "INSERT INTO public.rides (id, user_id) VALUES (%s, %s)",
                (concurrent_ride_id, user_id),
            )
            cursor.execute(
                "SELECT * FROM public.bind_ride_reward_ftp(%s, %s)",
                (concurrent_ride_id, before_effective),
            )
            cursor.execute(
                "UPDATE public.rides SET economic_tss = 84 WHERE id = %s",
                (concurrent_ride_id,),
            )
            concurrent_plan = _plan(concurrent_ride_id, user_id, 3)
            concurrent_plan.update(
                {
                    "policy_version": POLICY,
                    "started_at": before_effective.isoformat(),
                    "completed_at": (
                        before_effective + timedelta(hours=1)
                    ).isoformat(),
                    "reward_ftp_w": 200,
                    "reward_ftp_source": "network_default",
                    "reward_ftp_authority_id": None,
                    "reward_ftp_policy_version": "reward_ftp_policy_2026_07_14",
                }
            )
            conflicting_plan = dict(concurrent_plan)
            conflicting_plan["plan_evidence_hash_hex"] = "f" * 64
            barrier = Barrier(2)

            def freeze(plan_payload: dict) -> None:
                with _connection(postgres_dsn) as worker_connection:
                    with worker_connection.cursor() as worker_cursor:
                        barrier.wait()
                        worker_cursor.execute(
                            "SELECT public.freeze_ride_economic_plan(%s, %s)",
                            (Json(plan_payload), Json([])),
                        )

            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(freeze, concurrent_plan),
                    executor.submit(freeze, conflicting_plan),
                ]
                for future in futures:
                    future.result()

            cursor.execute(
                "SELECT state FROM public.ride_economic_plans WHERE ride_id = %s",
                (concurrent_ride_id,),
            )
            assert cursor.fetchone()[0] == "review"
            cursor.execute(
                """
                SELECT count(*) FROM public.ride_economic_plan_audits
                WHERE ride_id = %s
                  AND event_type = 'nonterminal_plan_evidence_mismatch'
                """,
                (concurrent_ride_id,),
            )
            assert cursor.fetchone()[0] == 1
