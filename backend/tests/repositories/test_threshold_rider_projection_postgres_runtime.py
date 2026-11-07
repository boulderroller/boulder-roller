"""PostgreSQL runtime proof for the private rider Threshold projection."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from backend.tests.repositories.test_derived_threshold_authority_postgres_runtime import (
    _insert_ride,
    _register,
)
from backend.tests.repositories.test_threshold_provisional_hold_postgres_runtime import (
    _connection,
    _establish_with_edge_holds,
)
from backend.tests.services.test_settlement_clock_postgres_runtime import postgres_dsn


BACKEND_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_SQL = (BACKEND_ROOT / "sql" / "156_threshold_rider_projection.sql").read_text(
    encoding="utf-8"
)


def test_projection_hides_unscheduled_candidate_and_exposes_only_scheduled_raise(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            facts = _establish_with_edge_holds(cursor)
            cursor.execute(MIGRATION_SQL)

            as_of = facts["established_at"] + timedelta(days=1)
            sub_deadband_ride = _insert_ride(
                cursor,
                user_id=facts["user_id"],
                received_at=as_of,
            )
            _register(cursor, sub_deadband_ride, 247.0, as_of)
            cursor.execute(
                "SELECT public.get_reward_threshold_rider_projection(%s, %s)",
                (facts["user_id"], as_of),
            )
            projection = cursor.fetchone()[0]
            assert projection["state"] == "established"
            assert projection["current_w"] == 245
            assert projection["last_raised_at"] is None
            assert projection["pending_monday"] is None
            assert projection["training_denominator"]["kind"] == "sealed"
            assert projection["training_denominator"]["watts"] == 245

            raise_ride = _insert_ride(
                cursor,
                user_id=facts["user_id"],
                received_at=as_of + timedelta(hours=1),
            )
            _register(cursor, raise_ride, 252.0, as_of + timedelta(hours=1))
            cursor.execute(
                "SELECT public.get_reward_threshold_rider_projection(%s, %s)",
                (facts["user_id"], as_of + timedelta(hours=2)),
            )
            scheduled = cursor.fetchone()[0]
            assert scheduled["current_w"] == 245
            assert scheduled["pending_monday"]["watts"] == 252
            assert scheduled["training_denominator"]["kind"] == "pending"
            assert scheduled["training_denominator"]["watts"] == 252
            assert "display_candidate_w" not in scheduled

            seal_boundary = scheduled["pending_monday"]["effective_at"]
            cursor.execute(
                "SELECT public.get_reward_threshold_rider_projection(%s, %s)",
                (facts["user_id"], seal_boundary),
            )
            sealing = cursor.fetchone()[0]
            assert sealing["current_w"] == 245
            assert sealing["pending_monday"] is None
            assert sealing["training_denominator"]["kind"] == "sealed"
            assert sealing["training_denominator"]["watts"] == 245
            assert sealing["sealing_in_progress"] is True

            cursor.execute(
                """
                SELECT
                    has_function_privilege(
                        'authenticated',
                        'public.get_reward_threshold_rider_projection(uuid,timestamptz)',
                        'EXECUTE'
                    ),
                    has_function_privilege(
                        'service_role',
                        'public.get_reward_threshold_rider_projection(uuid,timestamptz)',
                        'EXECUTE'
                    )
                """
            )
            assert cursor.fetchone() == (False, True)
