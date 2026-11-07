from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from backend.tests.services.test_settlement_clock_postgres_runtime import (
    _connection,
    postgres_dsn,
)


BACKEND_ROOT = Path(__file__).resolve().parents[2]
LEGACY_RECORD_MIGRATION = (
    BACKEND_ROOT / "sql" / "093_post_ride_cascade_detail.sql"
)
CANONICAL_MIGRATION = (
    BACKEND_ROOT / "sql" / "128_completion_projection_ownership.sql"
)
DEPLOY_MIGRATION = (
    BACKEND_ROOT
    / "supabase"
    / "migrations"
    / "20260715_136_completion_projection_ownership.sql"
)


def _bootstrap(cursor: Any) -> None:
    cursor.execute(
        """
        DROP SCHEMA public CASCADE;
        CREATE SCHEMA public;
        CREATE ROLE anon NOLOGIN;
        CREATE ROLE authenticated NOLOGIN;
        CREATE ROLE service_role NOLOGIN;
        GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;

        CREATE TABLE public.indexed_vaults (
            signature_hex TEXT PRIMARY KEY,
            total_completions BIGINT NOT NULL,
            chain_slot BIGINT,
            indexed_at TIMESTAMPTZ
        );

        CREATE TABLE public.vault_completions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            vault_signature TEXT NOT NULL,
            wallet TEXT NOT NULL,
            activity_id TEXT NOT NULL,
            time_seconds BIGINT,
            completed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            validated BOOLEAN DEFAULT true,
            validation_notes TEXT,
            cal_tribute NUMERIC NOT NULL DEFAULT 0,
            best_time_seconds BIGINT,
            best_time_achieved_at TIMESTAMPTZ,
            total_completions INTEGER DEFAULT 1,
            on_chain_tx TEXT,
            on_chain_tx_error TEXT,
            chain_confirmation_status TEXT,
            completion_receipt_pda TEXT,
            completion_evidence_hash BYTEA,
            completion_evidence_version SMALLINT,
            chain_confirmed_at TIMESTAMPTZ,
            UNIQUE (vault_signature, activity_id)
        );

        CREATE TABLE public.ride_economic_plans (
            ride_id UUID PRIMARY KEY,
            wallet TEXT NOT NULL,
            state TEXT NOT NULL,
            lease_owner UUID,
            lease_expires_at TIMESTAMPTZ
        );

        CREATE TABLE public.ride_economic_completion_steps (
            ride_id UUID NOT NULL,
            step_index INTEGER NOT NULL,
            state TEXT NOT NULL,
            chain_confirmed_at TIMESTAMPTZ,
            vault_signature TEXT NOT NULL,
            completion_time_s BIGINT,
            completed_at TIMESTAMPTZ NOT NULL,
            exact_tribute_base_units NUMERIC NOT NULL,
            actual_tx_signature TEXT,
            expected_receipt_pda TEXT,
            completion_evidence_hash BYTEA,
            completion_evidence_version SMALLINT,
            PRIMARY KEY (ride_id, step_index)
        );

        CREATE OR REPLACE FUNCTION public.br_bind_vault_completion_evidence_version()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = ''
        AS $$
        DECLARE
            v_version SMALLINT;
        BEGIN
            IF NEW.chain_confirmation_status = 'confirmed' THEN
                SELECT step.completion_evidence_version INTO v_version
                FROM public.ride_economic_completion_steps AS step
                WHERE step.expected_receipt_pda = NEW.completion_receipt_pda
                  AND step.completion_evidence_hash = NEW.completion_evidence_hash;
                IF FOUND THEN
                    NEW.completion_evidence_version := v_version;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER br_bind_vault_completion_evidence_version
        BEFORE INSERT OR UPDATE ON public.vault_completions
        FOR EACH ROW
        EXECUTE FUNCTION public.br_bind_vault_completion_evidence_version();

        CREATE OR REPLACE FUNCTION public.increment_vault_completions(
            p_signature_hex TEXT
        ) RETURNS VOID
        LANGUAGE plpgsql
        AS $$
        BEGIN
            UPDATE public.indexed_vaults
            SET total_completions = total_completions + 1
            WHERE signature_hex = p_signature_hex;
        END;
        $$;

        CREATE OR REPLACE FUNCTION public.reconcile_confirmed_vault_completion(
            p_ride_id UUID,
            p_lease_owner UUID,
            p_step_index INTEGER
        ) RETURNS JSONB
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = ''
        AS $$
        DECLARE
            v_plan public.ride_economic_plans%ROWTYPE;
            v_step public.ride_economic_completion_steps%ROWTYPE;
            v_completion JSONB;
            v_inserted BOOLEAN;
        BEGIN
            SELECT * INTO v_plan FROM public.ride_economic_plans
            WHERE ride_id = p_ride_id
              AND state = 'cal_confirmed'
              AND lease_owner = p_lease_owner
              AND lease_expires_at > clock_timestamp();
            IF NOT FOUND THEN RETURN NULL; END IF;

            SELECT * INTO v_step FROM public.ride_economic_completion_steps
            WHERE ride_id = p_ride_id
              AND step_index = p_step_index
              AND state IN ('confirmed', 'projected')
              AND chain_confirmed_at IS NOT NULL;
            IF NOT FOUND THEN RETURN NULL; END IF;

            INSERT INTO public.vault_completions AS target (
                vault_signature, wallet, activity_id, time_seconds, completed_at,
                validated, validation_notes, cal_tribute, best_time_seconds,
                best_time_achieved_at, total_completions, on_chain_tx,
                on_chain_tx_error, chain_confirmation_status,
                completion_receipt_pda, completion_evidence_hash,
                chain_confirmed_at
            ) VALUES (
                v_step.vault_signature, v_plan.wallet, p_ride_id::TEXT,
                v_step.completion_time_s, v_step.completed_at, true, NULL,
                v_step.exact_tribute_base_units, v_step.completion_time_s,
                v_step.completed_at, 1, v_step.actual_tx_signature, NULL,
                'confirmed', v_step.expected_receipt_pda,
                v_step.completion_evidence_hash, v_step.chain_confirmed_at
            )
            ON CONFLICT (vault_signature, activity_id) DO UPDATE SET
                wallet = EXCLUDED.wallet,
                chain_confirmation_status = 'confirmed',
                completion_receipt_pda = EXCLUDED.completion_receipt_pda,
                completion_evidence_hash = EXCLUDED.completion_evidence_hash,
                chain_confirmed_at = EXCLUDED.chain_confirmed_at
            RETURNING (xmax = 0), to_jsonb(target)
            INTO v_inserted, v_completion;

            IF v_inserted THEN
                PERFORM public.increment_vault_completions(
                    v_step.vault_signature
                );
            END IF;
            RETURN v_completion;
        END;
        $$;

        INSERT INTO public.indexed_vaults (
            signature_hex, total_completions, chain_slot, indexed_at
        ) VALUES (
            'vault-a', 70, 800, TIMESTAMPTZ '2026-07-15 12:00:00+00'
        );
        """
    )


def _record_completion(cursor: Any, activity_id: str) -> tuple[bool, dict[str, Any]]:
    cursor.execute(
        """
        SELECT inserted, completion
        FROM public.record_vault_completion_projection(
            'vault-a',
            'rider-a',
            %s,
            321,
            TIMESTAMPTZ '2026-07-15 13:00:00+00',
            true,
            NULL,
            11
        )
        """,
        (activity_id,),
    )
    return cursor.fetchone()


def _assert_chain_projection(
    cursor: Any,
    *,
    total_completions: int,
    chain_slot: int,
) -> None:
    cursor.execute(
        """
        SELECT total_completions, chain_slot
        FROM public.indexed_vaults
        WHERE signature_hex = 'vault-a'
        """
    )
    assert cursor.fetchone() == (total_completions, chain_slot)


def test_completion_projection_migration_is_exactly_mirrored() -> None:
    assert CANONICAL_MIGRATION.read_bytes() == DEPLOY_MIGRATION.read_bytes()


def test_backend_completion_evidence_cannot_mutate_chain_projection(
    postgres_dsn: str,
) -> None:
    migration = CANONICAL_MIGRATION.read_text(encoding="utf-8")
    ride_id = uuid.uuid4()
    lease_owner = uuid.uuid4()

    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap(cursor)
            cursor.execute(
                LEGACY_RECORD_MIGRATION.read_text(encoding="utf-8")
            )
            cursor.execute(migration)

            for signature in (
                "public.record_vault_completion_projection(text,text,text,integer,timestamp with time zone,boolean,text,numeric)",
                "public.reconcile_confirmed_vault_completion(uuid,uuid,integer)",
                "public.increment_vault_completions(text)",
            ):
                cursor.execute(
                    """
                    SELECT
                        has_function_privilege('service_role', %s, 'EXECUTE'),
                        has_function_privilege('anon', %s, 'EXECUTE'),
                        has_function_privilege('authenticated', %s, 'EXECUTE')
                    """,
                    (signature, signature, signature),
                )
                assert cursor.fetchone() == (True, False, False), signature

            first_inserted, _ = _record_completion(cursor, "ride-before-chain")
            assert first_inserted is True
            _assert_chain_projection(
                cursor,
                total_completions=70,
                chain_slot=800,
            )

            cursor.execute(
                """
                UPDATE public.indexed_vaults
                SET total_completions = 77,
                    chain_slot = 900,
                    indexed_at = TIMESTAMPTZ '2026-07-15 14:00:00+00'
                WHERE signature_hex = 'vault-a'
                """
            )

            retry_inserted, _ = _record_completion(cursor, "ride-before-chain")
            second_inserted, _ = _record_completion(cursor, "ride-after-chain")
            assert retry_inserted is False
            assert second_inserted is True

            cursor.execute(
                """
                INSERT INTO public.ride_economic_plans (
                    ride_id, wallet, state, lease_owner, lease_expires_at
                ) VALUES (%s, 'rider-a', 'cal_confirmed', %s, now() + interval '5 minutes');

                INSERT INTO public.ride_economic_completion_steps (
                    ride_id, step_index, state, chain_confirmed_at,
                    vault_signature, completion_time_s, completed_at,
                    exact_tribute_base_units, actual_tx_signature,
                    expected_receipt_pda, completion_evidence_hash,
                    completion_evidence_version
                ) VALUES (
                    %s, 0, 'confirmed', now(), 'vault-a', 300,
                    TIMESTAMPTZ '2026-07-15 14:05:00+00', 13,
                    'tx-recovery', 'receipt-recovery',
                    decode(repeat('ab', 32), 'hex'), 2
                );
                """,
                (str(ride_id), str(lease_owner), str(ride_id)),
            )
            cursor.execute(
                "SELECT public.reconcile_confirmed_vault_completion(%s::UUID, %s::UUID, 0)",
                (str(ride_id), str(lease_owner)),
            )
            recovered = cursor.fetchone()[0]
            assert recovered["activity_id"] == str(ride_id)
            assert recovered["completion_evidence_version"] == 2
            cursor.execute(
                "SELECT public.reconcile_confirmed_vault_completion(%s::UUID, %s::UUID, 0)",
                (str(ride_id), str(lease_owner)),
            )
            recovered_retry = cursor.fetchone()[0]
            assert recovered_retry["activity_id"] == str(ride_id)
            assert recovered_retry["completion_evidence_version"] == 2

            _assert_chain_projection(
                cursor,
                total_completions=77,
                chain_slot=900,
            )
            cursor.execute("SET ROLE service_role")
            cursor.execute("SELECT public.increment_vault_completions('vault-a')")
            cursor.execute("RESET ROLE")
            _assert_chain_projection(
                cursor,
                total_completions=77,
                chain_slot=900,
            )
            cursor.execute(
                "SELECT count(*) FROM public.vault_completions WHERE vault_signature = 'vault-a'"
            )
            assert cursor.fetchone()[0] == 3
            cursor.execute(
                "SELECT to_regprocedure('public.increment_vault_completions(text)')"
            )
            assert cursor.fetchone()[0] is not None
