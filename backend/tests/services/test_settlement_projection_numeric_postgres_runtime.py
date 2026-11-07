from __future__ import annotations

from pathlib import Path
from typing import Any

import psycopg2
import pytest

from backend.tests.services.test_settlement_clock_postgres_runtime import (
    _connection,
    postgres_dsn,
)


BACKEND_ROOT = Path(__file__).resolve().parents[2]
MIGRATION = BACKEND_ROOT / "sql" / "138_settlement_projection_numeric_identifiers.sql"
DEPLOY_MIRROR = (
    BACKEND_ROOT
    / "supabase"
    / "migrations"
    / "20260718_146_settlement_projection_numeric_identifiers.sql"
)
U64_MAX = 18_446_744_073_709_551_615


def _bootstrap(cursor: Any) -> None:
    cursor.execute(
        """
        DROP SCHEMA public CASCADE;
        CREATE SCHEMA public;

        CREATE TABLE public.indexed_epoch_distributions (
            tx_signature TEXT NOT NULL,
            event_index INTEGER NOT NULL,
            vault_id NUMERIC(39, 0) NOT NULL
                CHECK (vault_id BETWEEN 0 AND 18446744073709551615::NUMERIC),
            epoch NUMERIC(39, 0) NOT NULL
                CHECK (epoch BETWEEN 0 AND 18446744073709551615::NUMERIC),
            block_time BIGINT,
            finalized_at TIMESTAMPTZ GENERATED ALWAYS AS (
                CASE WHEN block_time IS NOT NULL THEN to_timestamp(block_time) END
            ) STORED,
            PRIMARY KEY (tx_signature, event_index)
        );
        CREATE TABLE public.epoch_distributions (
            id TEXT PRIMARY KEY,
            epoch NUMERIC(39, 0) NOT NULL,
            vault_id NUMERIC(39, 0),
            vault_signature TEXT,
            finalized_at TIMESTAMPTZ
        );
        CREATE TABLE public.indexed_vaults (
            id NUMERIC(39, 0) PRIMARY KEY,
            signature_hex TEXT NOT NULL UNIQUE
        );
        CREATE TABLE public.indexed_climb_completion_flows (
            vault_id NUMERIC(20, 0) NOT NULL,
            credited_settlement_week NUMERIC(20, 0) NOT NULL,
            completion_evidence_hash BYTEA NOT NULL,
            completion_evidence_version INTEGER NOT NULL,
            cal_tributed NUMERIC(39, 0) NOT NULL
        );
        CREATE TABLE public.vault_completions (
            activity_id TEXT NOT NULL,
            vault_signature TEXT NOT NULL,
            completion_evidence_hash BYTEA NOT NULL,
            completion_evidence_version INTEGER NOT NULL,
            cal_tribute NUMERIC(39, 0) NOT NULL,
            chain_confirmation_status TEXT NOT NULL
        );
        CREATE TABLE public.ride_refresh_log (
            activity_id TEXT NOT NULL,
            refreshed_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE FUNCTION public.br_refresh_ride_finalized_at(p_activity_id TEXT)
        RETURNS VOID
        LANGUAGE plpgsql
        AS $$
        BEGIN
            INSERT INTO public.ride_refresh_log (activity_id) VALUES (p_activity_id);
        END;
        $$;

        -- The exact installed migration-125 defect: helper arguments narrow
        -- while the trigger source columns are exact NUMERIC values.
        CREATE FUNCTION public.br_refresh_distribution_dependents(
            p_vault_id BIGINT,
            p_epoch BIGINT
        )
        RETURNS VOID
        LANGUAGE sql
        AS $$ SELECT $$;

        CREATE FUNCTION public.br_sync_epoch_distribution_finalized_at()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP <> 'DELETE' THEN
                PERFORM public.br_refresh_distribution_dependents(NEW.vault_id, NEW.epoch);
            ELSE
                PERFORM public.br_refresh_distribution_dependents(OLD.vault_id, OLD.epoch);
            END IF;
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$;

        CREATE TRIGGER br_indexed_epoch_distribution_finalized_at_trigger
        AFTER INSERT OR UPDATE OR DELETE ON public.indexed_epoch_distributions
        FOR EACH ROW
        EXECUTE FUNCTION public.br_sync_epoch_distribution_finalized_at();

        INSERT INTO public.indexed_vaults (id, signature_hex)
        VALUES (9, 'vault-9');
        INSERT INTO public.epoch_distributions (
            id, epoch, vault_id, vault_signature, finalized_at
        ) VALUES ('legacy-9-44', 44, 9, 'vault-9', NULL);
        INSERT INTO public.indexed_climb_completion_flows (
            vault_id, credited_settlement_week, completion_evidence_hash,
            completion_evidence_version, cal_tributed
        ) VALUES (9, 44, decode(repeat('ab', 32), 'hex'), 2, 11);
        INSERT INTO public.vault_completions (
            activity_id, vault_signature, completion_evidence_hash,
            completion_evidence_version, cal_tribute, chain_confirmation_status
        ) VALUES (
            'ride-9-44', 'vault-9', decode(repeat('ab', 32), 'hex'),
            2, 11, 'confirmed'
        );
        """
    )


def test_numeric_projection_helper_repairs_installed_trigger_composition(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap(cursor)

            with pytest.raises(psycopg2.errors.UndefinedFunction):
                cursor.execute(
                    """
                    INSERT INTO public.indexed_epoch_distributions (
                        tx_signature, event_index, vault_id, epoch, block_time
                    ) VALUES ('pre-fix', 0, 9, 44, 1000)
                    """
                )
            cursor.execute(MIGRATION.read_text(encoding="utf-8"))

            cursor.execute(
                """
                SELECT
                    to_regprocedure(
                        'public.br_refresh_distribution_dependents(numeric,numeric)'
                    ) IS NOT NULL,
                    to_regprocedure(
                        'public.br_refresh_distribution_dependents(bigint,bigint)'
                    ) IS NULL
                """
            )
            assert cursor.fetchone() == (True, True)

            cursor.execute(
                """
                INSERT INTO public.indexed_epoch_distributions (
                    tx_signature, event_index, vault_id, epoch, block_time
                ) VALUES ('post-fix', 0, 9, 44, 1000)
                """
            )
            cursor.execute(
                """
                SELECT finalized_at = to_timestamp(1000)
                FROM public.epoch_distributions
                WHERE id = 'legacy-9-44'
                """
            )
            assert cursor.fetchone()[0] is True
            cursor.execute(
                "SELECT COUNT(*) FROM public.ride_refresh_log WHERE activity_id = 'ride-9-44'"
            )
            assert cursor.fetchone()[0] == 1

            cursor.execute(
                """
                UPDATE public.indexed_epoch_distributions
                SET block_time = 1001
                WHERE tx_signature = 'post-fix'
                """
            )
            cursor.execute(
                """
                SELECT finalized_at = to_timestamp(1001)
                FROM public.epoch_distributions
                WHERE id = 'legacy-9-44'
                """
            )
            assert cursor.fetchone()[0] is True

            cursor.execute(
                "DELETE FROM public.indexed_epoch_distributions WHERE tx_signature = 'post-fix'"
            )
            cursor.execute(
                "SELECT finalized_at IS NULL FROM public.epoch_distributions WHERE id = 'legacy-9-44'"
            )
            assert cursor.fetchone()[0] is True

            above_i64 = 9_223_372_036_854_775_808
            cursor.execute(
                """
                INSERT INTO public.indexed_epoch_distributions (
                    tx_signature, event_index, vault_id, epoch, block_time
                ) VALUES ('above-i64', 0, %s, %s, 2000)
                """,
                (above_i64, U64_MAX),
            )
            cursor.execute(
                "UPDATE public.indexed_epoch_distributions SET block_time = 2001 WHERE tx_signature = 'above-i64'"
            )
            cursor.execute(
                "DELETE FROM public.indexed_epoch_distributions WHERE tx_signature = 'above-i64'"
            )

            for vault_id, epoch in ((-1, 1), (1.5, 1), (U64_MAX + 1, 1)):
                with pytest.raises(
                    psycopg2.errors.NumericValueOutOfRange,
                    match="unsigned u64",
                ):
                    cursor.execute(
                        "SELECT public.br_refresh_distribution_dependents(%s, %s)",
                        (vault_id, epoch),
                    )


def test_numeric_projection_migration_is_exactly_mirrored() -> None:
    assert MIGRATION.read_bytes() == DEPLOY_MIRROR.read_bytes()
