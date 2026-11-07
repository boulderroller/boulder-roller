from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from psycopg2 import errors

from backend.tests.services.test_settlement_clock_postgres_runtime import (
    _connection,
    postgres_dsn,
)


BACKEND_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_MIGRATION = (
    BACKEND_ROOT / "sql" / "132_dung_circulating_supply_authority.sql"
)
DEPLOY_MIGRATION = (
    BACKEND_ROOT
    / "supabase"
    / "migrations"
    / "20260716_140_dung_circulating_supply_authority.sql"
)
OBSERVABILITY_CANONICAL_MIGRATION = (
    BACKEND_ROOT / "sql" / "133_dung_reservation_observability_backfill.sql"
)
OBSERVABILITY_DEPLOY_MIGRATION = (
    BACKEND_ROOT
    / "supabase"
    / "migrations"
    / "20260716_141_dung_reservation_observability_backfill.sql"
)
U64_MAX = 18_446_744_073_709_551_615


def _bootstrap(cursor: Any) -> None:
    cursor.execute(
        """
        DROP SCHEMA public CASCADE;
        CREATE SCHEMA public;

        CREATE TABLE public.indexed_supply (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            total_minted NUMERIC NOT NULL,
            total_burned NUMERIC NOT NULL,
            circulating NUMERIC GENERATED ALWAYS AS (
                total_minted - total_burned
            ) STORED
        );

        INSERT INTO public.indexed_supply (
            id,
            total_minted,
            total_burned
        ) VALUES (1, 100, 5);
        """
    )


def _assert_update_rejected(connection: Any, cursor: Any, sql: str) -> None:
    connection.autocommit = False
    try:
        with pytest.raises(errors.CheckViolation):
            cursor.execute(sql)
    finally:
        connection.rollback()
        connection.autocommit = True


def test_dung_circulating_supply_migration_is_exactly_mirrored() -> None:
    assert CANONICAL_MIGRATION.read_bytes() == DEPLOY_MIGRATION.read_bytes()


def test_dung_reservation_observability_backfill_is_exactly_mirrored() -> None:
    assert (
        OBSERVABILITY_CANONICAL_MIGRATION.read_bytes()
        == OBSERVABILITY_DEPLOY_MIGRATION.read_bytes()
    )


def test_dung_reservation_observability_backfills_canonical_stream(
    postgres_dsn: str,
) -> None:
    migration = OBSERVABILITY_CANONICAL_MIGRATION.read_text(encoding="utf-8")

    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap(cursor)
            cursor.execute(migration)
            cursor.execute(migration)

            cursor.execute(
                """
                SELECT community_reserved, reservation_policy_version
                FROM public.indexed_supply
                WHERE id = 1
                """
            )
            community_reserved, policy_version = cursor.fetchone()
            assert int(community_reserved) == 0
            assert policy_version == 0

            cursor.execute(
                """
                UPDATE public.indexed_supply
                SET community_reserved = 1069289469981,
                    reservation_policy_version = 1
                WHERE id = 1
                """
            )
            cursor.execute(
                """
                SELECT community_reserved, reservation_policy_version
                FROM public.indexed_supply
                WHERE id = 1
                """
            )
            community_reserved, policy_version = cursor.fetchone()
            assert int(community_reserved) == 1_069_289_469_981
            assert policy_version == 1


def test_spl_mint_supply_is_exact_bounded_and_distinct_from_legacy_derivation(
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
                UPDATE public.indexed_supply
                SET spl_mint_supply = 91,
                    spl_mint_supply_slot = 4321,
                    spl_mint_supply_indexed_at =
                        TIMESTAMPTZ '2026-07-16 12:00:00+00'
                WHERE id = 1
                """
            )
            cursor.execute(
                """
                SELECT circulating, spl_mint_supply, spl_mint_supply_slot
                FROM public.indexed_supply
                WHERE id = 1
                """
            )
            legacy_circulating, canonical_supply, supply_slot = cursor.fetchone()
            assert int(legacy_circulating) == 95
            assert int(canonical_supply) == 91
            assert supply_slot == 4321

            cursor.execute(
                """
                UPDATE public.indexed_supply
                SET spl_mint_supply = 18446744073709551615,
                    spl_mint_supply_slot = 4322,
                    spl_mint_supply_indexed_at =
                        TIMESTAMPTZ '2026-07-16 12:00:01+00'
                WHERE id = 1
                """
            )
            cursor.execute(
                """
                SELECT spl_mint_supply, scale(spl_mint_supply)
                FROM public.indexed_supply
                WHERE id = 1
                """
            )
            exact_supply, exact_scale = cursor.fetchone()
            assert int(exact_supply) == U64_MAX
            assert exact_scale == 0

            _assert_update_rejected(
                connection,
                cursor,
                "UPDATE public.indexed_supply "
                "SET spl_mint_supply = 18446744073709551616 WHERE id = 1",
            )
            _assert_update_rejected(
                connection,
                cursor,
                "UPDATE public.indexed_supply "
                "SET spl_mint_supply = 1.5 WHERE id = 1",
            )
            _assert_update_rejected(
                connection,
                cursor,
                "UPDATE public.indexed_supply "
                "SET spl_mint_supply_slot = NULL WHERE id = 1",
            )

            cursor.execute(
                """
                SELECT col_description(
                    'public.indexed_supply'::regclass,
                    attnum
                )
                FROM pg_attribute
                WHERE attrelid = 'public.indexed_supply'::regclass
                  AND attname = 'circulating'
                """
            )
            assert "not circulating-supply authority" in cursor.fetchone()[0]
