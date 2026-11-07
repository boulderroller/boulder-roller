from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.tests.services.test_settlement_clock_postgres_runtime import (
    _connection,
    postgres_dsn,
)


BACKEND_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_MIGRATION = BACKEND_ROOT / "sql" / "136_indexed_stakes_live_lp_indexes.sql"
DEPLOY_MIGRATION = (
    BACKEND_ROOT
    / "supabase"
    / "migrations"
    / "20260717_144_indexed_stakes_live_lp_indexes.sql"
)


def _bootstrap(cursor: Any) -> None:
    cursor.execute(
        """
        DROP SCHEMA public CASCADE;
        CREATE SCHEMA public;

        CREATE TABLE public.indexed_stakes (
            user_pubkey TEXT NOT NULL,
            vault_id BIGINT NOT NULL,
            cal_staked NUMERIC NOT NULL DEFAULT 0,
            lp_tokens NUMERIC NOT NULL DEFAULT 0,
            PRIMARY KEY (user_pubkey, vault_id)
        );

        INSERT INTO public.indexed_stakes (
            user_pubkey,
            vault_id,
            cal_staked,
            lp_tokens
        ) VALUES
            ('dust-rider', 7, 0, 2),
            ('exited-rider', 7, 0, 0),
            ('principal-rider', 8, 100, 100);
        """
    )


def test_live_lp_index_migration_is_exactly_mirrored() -> None:
    assert CANONICAL_MIGRATION.read_bytes() == DEPLOY_MIGRATION.read_bytes()


def test_live_lp_indexes_support_zero_principal_redeemable_positions(
    postgres_dsn: str,
) -> None:
    migration = CANONICAL_MIGRATION.read_text(encoding="utf-8")

    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap(cursor)
            cursor.execute(migration)
            cursor.execute(migration)

            cursor.execute(
                """
                SELECT c.relname, pg_get_expr(i.indpred, i.indrelid)
                FROM pg_index AS i
                JOIN pg_class AS c ON c.oid = i.indexrelid
                WHERE c.relname IN (
                    'idx_indexed_stakes_user_live_lp',
                    'idx_indexed_stakes_vault_live_lp'
                )
                ORDER BY c.relname
                """
            )
            predicates = cursor.fetchall()
            assert len(predicates) == 2
            assert all("lp_tokens >" in predicate for _, predicate in predicates)
            assert all("cal_staked" not in predicate for _, predicate in predicates)

            cursor.execute("SET enable_seqscan = off")
            cursor.execute(
                """
                EXPLAIN (COSTS OFF)
                SELECT *
                FROM public.indexed_stakes
                WHERE vault_id = 7 AND lp_tokens > 0
                """
            )
            vault_plan = "\n".join(row[0] for row in cursor.fetchall())
            assert "idx_indexed_stakes_vault_live_lp" in vault_plan

            cursor.execute(
                """
                SELECT user_pubkey, cal_staked, lp_tokens
                FROM public.indexed_stakes
                WHERE vault_id = 7 AND lp_tokens > 0
                ORDER BY user_pubkey
                """
            )
            assert cursor.fetchall() == [("dust-rider", 0, 2)]
