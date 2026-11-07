from pathlib import Path

import psycopg2

from backend.scripts.apply_sql_migrations import (
    applied_checksums,
    apply_migration,
    discover_migrations,
    ensure_ledger,
)
from backend.tests.services.test_settlement_clock_postgres_runtime import postgres_dsn


BACKEND_ROOT = Path(__file__).parents[2]
MIGRATION_NAME = "131_staker_remainder_semantics.sql"


def test_forward_policy_projection_migration_applies_after_ledger_through_130(
    postgres_dsn: str,
) -> None:
    migration = next(
        item
        for item in discover_migrations(BACKEND_ROOT / "sql")
        if item.filename == MIGRATION_NAME
    )
    connection = psycopg2.connect(postgres_dsn)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE public.indexed_vaults (
                    id BIGINT PRIMARY KEY,
                    carry_stakers NUMERIC(39, 0) NOT NULL DEFAULT 0
                );
                INSERT INTO public.indexed_vaults (id, carry_stakers) VALUES (12, 42);
                CREATE TABLE public.indexed_epoch_distributions (
                    locked_staker_amount NUMERIC(39, 0) NOT NULL DEFAULT 0
                );
                CREATE TABLE public.epoch_distributions (
                    locked_staker_amount NUMERIC(39, 0) NOT NULL DEFAULT 0
                );
                CREATE TABLE public.vault_distributions (
                    locked_staker_amount NUMERIC(39, 0) NOT NULL DEFAULT 0
                );
                """
            )
        connection.commit()

        ensure_ledger(connection)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO public.br_sql_migrations (filename, checksum)
                VALUES ('130_cal_tribute_policy.sql', 'already-applied-through-130')
                """
            )
        connection.commit()

        assert MIGRATION_NAME not in applied_checksums(connection)
        apply_migration(connection, migration)

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT carry_stakers, staker_remainder_policy_version
                FROM public.indexed_vaults
                WHERE id = 12
                """
            )
            assert cursor.fetchone() == (42, 0)
            cursor.execute(
                """
                SELECT col_description(
                    'public.indexed_vaults'::regclass,
                    attnum
                )
                FROM pg_attribute
                WHERE attrelid = 'public.indexed_vaults'::regclass
                  AND attname = 'staker_remainder_policy_version'
                """
            )
            assert "legacy" in cursor.fetchone()[0].lower()

        applied = applied_checksums(connection)
        assert applied["130_cal_tribute_policy.sql"] == "already-applied-through-130"
        assert applied[MIGRATION_NAME] == migration.checksum
    finally:
        connection.close()
