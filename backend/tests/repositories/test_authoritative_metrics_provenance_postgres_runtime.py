"""PostgreSQL runtime contract for authoritative ride-metrics provenance."""

from __future__ import annotations

import uuid
from pathlib import Path

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
IMPLEMENTATION_COMMIT = "5d4c2c2eb150115a9b2deb771e7bcde2e199f3c7"
POLICY = "ride_effort_policy_2026_07_14"


def test_migration_activates_v3_and_preserves_historical_null_evidence(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap(cursor)
            historical_ride_id = uuid.uuid4()
            user_id = uuid.uuid4()
            cursor.execute("INSERT INTO public.users (id) VALUES (%s)", (user_id,))
            cursor.execute(
                "INSERT INTO public.rides (id, user_id) VALUES (%s, %s)",
                (historical_ride_id, user_id),
            )

            cursor.execute(PROVENANCE_SQL)
            cursor.execute(AUTHORITATIVE_SQL)
            cursor.execute(AUTHORITATIVE_SQL)

            cursor.execute(
                """
                SELECT moving_time_sec, metrics_version,
                       power_sample_count, power_sample_coverage_bps,
                       heart_rate_sample_count, heart_rate_sample_coverage_bps
                FROM public.rides
                WHERE id = %s
                """,
                (historical_ride_id,),
            )
            assert cursor.fetchone() == (None, None, None, None, None, None)

            cursor.execute(
                """
                SELECT parser_version, ride_parser_version, policy_version,
                       economics_version, git_commit
                FROM public.pipeline_versions
                WHERE deactivated_at IS NULL
                """
            )
            assert cursor.fetchall() == [
                ("3", 3, POLICY, POLICY, IMPLEMENTATION_COMMIT)
            ]
            cursor.execute(
                """
                SELECT count(*)
                FROM public.pipeline_versions
                WHERE parser_version = '2'
                  AND ride_parser_version = 2
                  AND deactivated_at IS NOT NULL
                """
            )
            assert cursor.fetchone()[0] == 1

            ride_id = uuid.uuid4()
            plan = _plan(ride_id, user_id, 3)
            plan["policy_version"] = POLICY
            cursor.execute(
                "SELECT public.freeze_ride_economic_plan(%s, %s)",
                (Json(plan), Json([])),
            )
            cursor.execute(
                """
                SELECT version.ride_parser_version, version.policy_version,
                       version.git_commit
                FROM public.ride_economic_plans AS plan
                JOIN public.pipeline_versions AS version
                  ON version.id = plan.pipeline_version_id
                WHERE plan.ride_id = %s
                """,
                (ride_id,),
            )
            assert cursor.fetchone() == (3, POLICY, IMPLEMENTATION_COMMIT)

            old_plan = _plan(uuid.uuid4(), user_id, 2)
            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="no active immutable pipeline version",
            ):
                cursor.execute(
                    "SELECT public.freeze_ride_economic_plan(%s, %s)",
                    (Json(old_plan), Json([])),
                )

            for statement in (
                "UPDATE public.rides SET moving_time_sec = -1 WHERE id = %s",
                "UPDATE public.rides SET power_sample_count = -1 WHERE id = %s",
                "UPDATE public.rides SET power_sample_coverage_bps = 10001 "
                "WHERE id = %s",
                "UPDATE public.rides SET heart_rate_sample_count = -1 WHERE id = %s",
                "UPDATE public.rides SET heart_rate_sample_coverage_bps = 10001 "
                "WHERE id = %s",
            ):
                with pytest.raises(psycopg2.errors.CheckViolation):
                    cursor.execute(statement, (historical_ride_id,))

            cursor.execute(
                """
                UPDATE public.rides
                SET moving_time_sec = 0,
                    metrics_version = 'workout_parse_metrics_v1',
                    power_sample_count = 0,
                    power_sample_coverage_bps = 10000,
                    heart_rate_sample_count = 0,
                    heart_rate_sample_coverage_bps = 0
                WHERE id = %s
                """,
                (historical_ride_id,),
            )

            cursor.execute(
                """
                UPDATE public.pipeline_versions
                SET deactivated_at = now()
                WHERE deactivated_at IS NULL
                """
            )
            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="inactive and cannot be reactivated",
            ):
                cursor.execute(AUTHORITATIVE_SQL)
