"""PostgreSQL runtime proof for parser V4 pipeline provenance."""

from __future__ import annotations

from pathlib import Path

import psycopg2
import pytest

from backend.tests.repositories.test_parser_provenance_postgres_runtime import (
    PROVENANCE_SQL,
    _bootstrap,
    _connection,
)
from backend.tests.repositories.test_reward_ftp_authority_postgres_runtime import (
    AUTHORITATIVE_SQL,
    REVIEW_REPAIR_SQL,
    REWARD_FTP_SQL,
    TRIBUTE_CONSERVATION_SQL,
)
from backend.tests.services.test_settlement_clock_postgres_runtime import postgres_dsn


BACKEND_ROOT = Path(__file__).resolve().parents[2]
PARSER_V4_SQL = (
    BACKEND_ROOT / "sql" / "127_parser_v4_climb_authority.sql"
).read_text(encoding="utf-8")
DETECTOR_PARAMS_HASH = (
    "a6ee436905f21e6769f82966b4779eca5f95796b77c33de457063179284b5af2"
)


def test_parser_v4_replaces_v3_exactly_and_reruns_idempotently(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap(cursor)
            cursor.execute("CREATE SCHEMA extensions")
            cursor.execute("ALTER EXTENSION pgcrypto SET SCHEMA extensions")
            cursor.execute(
                """
                CREATE TABLE public.detector_configs (
                    id SERIAL PRIMARY KEY,
                    algorithm TEXT NOT NULL,
                    version TEXT NOT NULL,
                    params JSONB NOT NULL,
                    params_hash CHAR(64) NOT NULL UNIQUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    notes TEXT
                )
                """
            )
            cursor.execute(REVIEW_REPAIR_SQL)
            cursor.execute(PROVENANCE_SQL)
            cursor.execute(TRIBUTE_CONSERVATION_SQL)
            cursor.execute(AUTHORITATIVE_SQL)
            cursor.execute(REWARD_FTP_SQL)

            cursor.execute(PARSER_V4_SQL)
            cursor.execute(PARSER_V4_SQL)

            cursor.execute(
                """
                SELECT parser_version, ride_parser_version,
                       detector_algorithm, detector_version,
                       detector_params_hash, sig_format_version,
                       sig_match_version, economics_version, policy_version,
                       btrim(git_commit), deactivated_at IS NULL
                FROM public.pipeline_versions
                ORDER BY id
                """
            )
            rows = cursor.fetchall()
            active = [row for row in rows if row[-1]]
            assert active == [
                (
                    "4-ftp-v1",
                    4,
                    "canonical_v2",
                    "2.0.0",
                    DETECTOR_PARAMS_HASH,
                    "v2",
                    "dct6-h3r7-geometry25-oriented150-sim090",
                    "ride_effort_policy_2026_07_14_ftp_v1",
                    "ride_effort_policy_2026_07_14_ftp_v1",
                    "bb7604ddc0af3f983d0a21191bf27bddfa463e80",
                    True,
                )
            ]
            assert any(row[0] == "3-ftp-v1" and not row[-1] for row in rows)

            cursor.execute(
                """
                SELECT algorithm, version, params_hash
                FROM public.detector_configs
                WHERE params_hash = %s
                """,
                (DETECTOR_PARAMS_HASH,),
            )
            assert cursor.fetchone() == (
                "canonical_v2",
                "2.0.0",
                DETECTOR_PARAMS_HASH,
            )

            cursor.execute(
                """
                UPDATE public.pipeline_versions
                SET deactivated_at = now()
                WHERE parser_version = '4-ftp-v1'
                """
            )
            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="inactive and cannot be reactivated",
            ):
                cursor.execute(PARSER_V4_SQL)
