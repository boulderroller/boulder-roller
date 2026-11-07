from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.tests.services.test_settlement_clock_postgres_runtime import (
    _connection,
    postgres_dsn,
)


BACKEND_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_MIGRATION = BACKEND_ROOT / "sql" / "134_indexed_legends_bootstrap_projection.sql"
DEPLOY_MIGRATION = (
    BACKEND_ROOT
    / "supabase"
    / "migrations"
    / "20260717_142_indexed_legends_bootstrap_projection.sql"
)


def _bootstrap(cursor: Any) -> None:
    cursor.execute(
        """
        DROP SCHEMA public CASCADE;
        CREATE SCHEMA public;

        CREATE TABLE public.indexed_legends (
            vault_id BIGINT PRIMARY KEY,
            election_period BIGINT NOT NULL DEFAULT 0,
            completions_at_election INTEGER NOT NULL DEFAULT 0,
            is_active BOOLEAN NOT NULL DEFAULT false
        );

        INSERT INTO public.indexed_legends (
            vault_id,
            election_period,
            completions_at_election,
            is_active
        ) VALUES
            (1, 0, 0, true),
            (2, 1, 0, true),
            (3, 0, 0, false);
        """
    )


def test_local_legend_bootstrap_projection_migration_is_exactly_mirrored() -> None:
    assert CANONICAL_MIGRATION.exists()
    assert DEPLOY_MIGRATION.exists()
    assert CANONICAL_MIGRATION.read_bytes() == DEPLOY_MIGRATION.read_bytes()


def test_local_legend_bootstrap_projection_backfills_legacy_rows_once(
    postgres_dsn: str,
) -> None:
    migration = CANONICAL_MIGRATION.read_text(encoding="utf-8")

    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap(cursor)
            cursor.execute(migration)

            cursor.execute(
                """
                SELECT vault_id, is_bootstrap
                FROM public.indexed_legends
                ORDER BY vault_id
                """
            )
            assert cursor.fetchall() == [(1, True), (2, False), (3, False)]

            cursor.execute(
                """
                INSERT INTO public.indexed_legends (
                    vault_id,
                    election_period,
                    completions_at_election,
                    is_active,
                    is_bootstrap
                ) VALUES (4, 0, 0, true, false)
                """
            )
            cursor.execute(migration)
            cursor.execute(
                """
                SELECT is_bootstrap
                FROM public.indexed_legends
                WHERE vault_id = 4
                """
            )
            assert cursor.fetchone() == (False,)

            cursor.execute(
                """
                SELECT is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'indexed_legends'
                  AND column_name = 'is_bootstrap'
                """
            )
            is_nullable, column_default = cursor.fetchone()
            assert is_nullable == "NO"
            assert column_default == "false"
