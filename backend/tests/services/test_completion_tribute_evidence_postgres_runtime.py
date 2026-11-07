from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any

import psycopg2
import pytest
from psycopg2.extras import Json, register_uuid

from backend.tests.services.test_settlement_clock_postgres_runtime import (
    _connection,
    postgres_dsn,
)


SQL_ROOT = Path(__file__).resolve().parents[2] / "sql"
PREREQUISITES = (
    SQL_ROOT / "114_ride_economic_recovery.sql",
    SQL_ROOT / "115_ride_economic_review_repair.sql",
    SQL_ROOT / "120_exact_credited_settlement_flow.sql",
    SQL_ROOT / "121_tribute_conservation.sql",
)
MIGRATION = SQL_ROOT / "125_completion_tribute_evidence_v2.sql"
register_uuid()


def _hash(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _plan(ride_id: uuid.UUID, user_id: uuid.UUID, *, tribute: str = "11") -> dict[str, Any]:
    marker = ride_id.hex
    return {
        "ride_id": str(ride_id),
        "user_id": str(user_id),
        "wallet": f"wallet-{marker}",
        "ride_hash_hex": _hash(f"ride:{marker}"),
        "attestation_commitment_hex": _hash(f"commitment:{marker}"),
        "parser_version": 7,
        "policy_version": "policy-v2",
        "reward_policy": "rewardable",
        "source_kind": 1,
        "started_at": "2026-07-13T12:00:00+00:00",
        "completed_at": "2026-07-13T13:00:00+00:00",
        "total_tss": 84,
        "total_distance_m": 12000,
        "total_vert_m": 300,
        "exact_cal_base_units": "101",
        "climbs_crossed": 1,
        "exact_tribute_base_units": tribute,
        "plan_evidence_hash_hex": _hash(f"plan:{marker}"),
        "expected_attestation_pda": f"attestation-{marker}",
        "expected_cal_receipt_pda": f"cal-{marker}",
    }


def _steps(
    ride_id: uuid.UUID,
    *,
    evidence_version: int | None,
    tribute: str = "11",
) -> list[dict[str, Any]]:
    marker = ride_id.hex
    step = {
        "step_index": 0,
        "pattern_id": str(uuid.uuid5(ride_id, "pattern:0")),
        "vault_id": "9",
        "vault_signature": "vault-9",
        "completion_time_s": 321,
        "completed_at": "2026-07-13T13:00:00+00:00",
        "exact_tribute_base_units": tribute,
        "intensity_bps": 10000,
        "climb_distance_m": 500,
        "climb_vert_m": 42,
        "completion_evidence_hash_hex": _hash(f"completion:{marker}:0"),
        "expected_receipt_pda": f"completion-{marker}-0",
    }
    if evidence_version is not None:
        step["completion_evidence_version"] = evidence_version
    return [step]


def _bootstrap(cursor: Any) -> None:
    cursor.execute(
        """
        DROP SCHEMA public CASCADE;
        CREATE SCHEMA public;
        DO $$ BEGIN
            CREATE ROLE anon NOLOGIN;
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        DO $$ BEGIN
            CREATE ROLE authenticated NOLOGIN;
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        DO $$ BEGIN
            CREATE ROLE service_role NOLOGIN;
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;

        CREATE TABLE public.users (id UUID PRIMARY KEY);
        CREATE TABLE public.rides (
            id UUID PRIMARY KEY,
            user_id UUID REFERENCES public.users(id) ON DELETE CASCADE,
            finalized_at TIMESTAMPTZ
        );
        CREATE TABLE public.vault_completions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            vault_signature TEXT NOT NULL,
            wallet TEXT NOT NULL,
            activity_id TEXT NOT NULL,
            time_seconds BIGINT,
            completed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            validated BOOLEAN DEFAULT true,
            validation_override BOOLEAN DEFAULT false,
            validation_notes TEXT,
            cal_tribute NUMERIC NOT NULL DEFAULT 0,
            best_time_seconds BIGINT,
            best_time_achieved_at TIMESTAMPTZ,
            total_completions INTEGER DEFAULT 1,
            on_chain_tx TEXT,
            on_chain_tx_error TEXT,
            UNIQUE (vault_signature, activity_id)
        );
        CREATE OR REPLACE FUNCTION public.increment_vault_completions(TEXT)
        RETURNS VOID LANGUAGE sql AS $$ SELECT $$;

        CREATE TABLE public.indexed_vaults (
            id BIGINT PRIMARY KEY,
            signature_hex TEXT NOT NULL UNIQUE
        );
        CREATE TABLE public.indexed_events (vault_id BIGINT);
        CREATE TABLE public.indexed_epoch_distributions (
            tx_signature TEXT NOT NULL,
            event_index INTEGER NOT NULL,
            vault_id BIGINT NOT NULL,
            epoch BIGINT NOT NULL,
            block_time BIGINT,
            finalized_at TIMESTAMPTZ GENERATED ALWAYS AS (
                CASE WHEN block_time IS NOT NULL THEN to_timestamp(block_time) END
            ) STORED,
            PRIMARY KEY (tx_signature, event_index)
        );
        CREATE TABLE public.epoch_distributions (
            id TEXT PRIMARY KEY,
            epoch BIGINT NOT NULL,
            vault_id BIGINT,
            vault_signature TEXT,
            finalized_at TIMESTAMPTZ
        );
        CREATE TABLE public.indexed_climb_completion_receipts (
            pda TEXT PRIMARY KEY,
            ride_attestation_pda TEXT NOT NULL,
            vault_pda TEXT NOT NULL,
            chain_slot NUMERIC NOT NULL,
            indexed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            bump INTEGER NOT NULL
        );

        INSERT INTO public.indexed_vaults (id, signature_hex)
        VALUES (9, 'vault-9');
        """
    )


def _freeze(
    cursor: Any,
    *,
    ride_id: uuid.UUID,
    user_id: uuid.UUID,
    evidence_version: int | None,
    tribute: str = "11",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    plan = _plan(ride_id, user_id, tribute=tribute)
    steps = _steps(ride_id, evidence_version=evidence_version, tribute=tribute)
    cursor.execute("INSERT INTO public.users (id) VALUES (%s)", (user_id,))
    cursor.execute(
        "INSERT INTO public.rides (id, user_id) VALUES (%s, %s)",
        (ride_id, user_id),
    )
    cursor.execute(
        "SELECT public.freeze_ride_economic_plan(%s::jsonb, %s::jsonb)",
        (Json(plan), Json(steps)),
    )
    return plan, steps


def _insert_confirmed_completion(
    cursor: Any,
    *,
    ride_id: uuid.UUID,
    plan: dict[str, Any],
    step: dict[str, Any],
    cal_tribute: int,
) -> None:
    cursor.execute(
        """
        INSERT INTO public.vault_completions (
            vault_signature, wallet, activity_id, time_seconds, completed_at,
            cal_tribute, on_chain_tx, chain_confirmation_status,
            completion_receipt_pda, completion_evidence_hash, chain_confirmed_at
        ) VALUES (
            'vault-9', %s, %s, 321, to_timestamp(100),
            %s, 'tx-completion', 'confirmed', %s, decode(%s, 'hex'), now()
        )
        """,
        (
            plan["wallet"],
            str(ride_id),
            cal_tribute,
            step["expected_receipt_pda"],
            step["completion_evidence_hash_hex"],
        ),
    )


def _insert_flow(
    cursor: Any,
    *,
    suffix: str,
    step: dict[str, Any],
    cal_tributed: int,
) -> None:
    cursor.execute(
        """
        INSERT INTO public.indexed_climb_completion_flows (
            tx_signature, event_index, vault_id, ride_attestation,
            completion_evidence_hash, completion_evidence_version,
            credited_settlement_week, cal_tributed, slot, block_time
        ) VALUES (
            %s, 0, 9, %s, decode(%s, 'hex'), 2, 44, %s, 500, 900
        )
        """,
        (
            f"flow-{suffix}",
            f"attestation-{suffix}",
            step["completion_evidence_hash_hex"],
            cal_tributed,
        ),
    )


def test_postgres_v2_cutover_fences_legacy_and_requires_exact_tribute(
    postgres_dsn: str,
) -> None:
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap(cursor)
            for migration in PREREQUISITES:
                cursor.execute(migration.read_text(encoding="utf-8"))

            legacy_ride = uuid.uuid4()
            legacy_user = uuid.uuid4()
            _freeze(
                cursor,
                ride_id=legacy_ride,
                user_id=legacy_user,
                evidence_version=None,
            )

            cursor.execute(MIGRATION.read_text(encoding="utf-8"))

            cursor.execute(
                "SELECT state, review_reason FROM public.ride_economic_plans WHERE ride_id = %s",
                (legacy_ride,),
            )
            assert cursor.fetchone() == (
                "review",
                "legacy_completion_evidence_v1_cutover",
            )

            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="require tribute-bound V2 completion evidence",
            ):
                _freeze(
                    cursor,
                    ride_id=uuid.uuid4(),
                    user_id=uuid.uuid4(),
                    evidence_version=1,
                )

            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="cannot authorize a non-reject review resolution",
            ):
                cursor.execute(
                    """
                    INSERT INTO public.ride_economic_review_resolutions (
                        request_id, ride_id, review_version, actor_id, outcome,
                        selected_checkpoint, verified_checkpoint, result_state,
                        reason, chain_evidence
                    ) VALUES (
                        %s, %s, 1, %s, 'resume', 'planned', 'planned', 'planned',
                        'legacy evidence cannot resume',
                        '{"completions":[{"completion_evidence_version":1,"tribute_bound":false}]}'::jsonb
                    )
                    """,
                    (uuid.uuid4(), legacy_ride, uuid.uuid4()),
                )

            exact_ride = uuid.uuid4()
            exact_user = uuid.uuid4()
            exact_plan, exact_steps = _freeze(
                cursor,
                ride_id=exact_ride,
                user_id=exact_user,
                evidence_version=2,
            )
            cursor.execute(
                """
                SELECT completion_evidence_version
                FROM public.ride_economic_completion_steps
                WHERE ride_id = %s
                """,
                (exact_ride,),
            )
            assert cursor.fetchone()[0] == 2

            _insert_confirmed_completion(
                cursor,
                ride_id=exact_ride,
                plan=exact_plan,
                step=exact_steps[0],
                cal_tribute=11,
            )
            _insert_flow(
                cursor,
                suffix="exact",
                step=exact_steps[0],
                cal_tributed=11,
            )
            cursor.execute(
                """
                INSERT INTO public.indexed_epoch_distributions (
                    tx_signature, event_index, vault_id, epoch, block_time
                ) VALUES ('distribution-exact', 0, 9, 44, 1000)
                """
            )
            cursor.execute(
                "SELECT finalized_at = to_timestamp(1000) FROM public.rides WHERE id = %s",
                (exact_ride,),
            )
            assert cursor.fetchone()[0] is True

            mismatch_ride = uuid.uuid4()
            mismatch_user = uuid.uuid4()
            mismatch_plan, mismatch_steps = _freeze(
                cursor,
                ride_id=mismatch_ride,
                user_id=mismatch_user,
                evidence_version=2,
            )
            _insert_confirmed_completion(
                cursor,
                ride_id=mismatch_ride,
                plan=mismatch_plan,
                step=mismatch_steps[0],
                cal_tribute=11,
            )
            _insert_flow(
                cursor,
                suffix="mismatch",
                step=mismatch_steps[0],
                cal_tributed=10,
            )
            cursor.execute(
                "SELECT finalized_at FROM public.rides WHERE id = %s",
                (mismatch_ride,),
            )
            assert cursor.fetchone()[0] is None

            cursor.execute(
                """
                INSERT INTO public.indexed_climb_completion_receipts (
                    pda, ride_attestation_pda, vault_pda,
                    completion_evidence_version, completion_evidence_hash,
                    cal_tributed, chain_slot, bump
                ) VALUES (
                    'receipt-u64-max', 'attestation-u64-max', 'vault-pda',
                    2, decode(repeat('ab', 32), 'hex'),
                    18446744073709551615, 1, 255
                )
                RETURNING cal_tributed::TEXT
                """
            )
            assert cursor.fetchone()[0] == "18446744073709551615"
