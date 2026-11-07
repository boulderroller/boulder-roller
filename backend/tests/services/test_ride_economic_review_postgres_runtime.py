from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import struct
import subprocess
import time
import uuid
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator

import psycopg2
import pytest
from psycopg2.extras import Json, register_uuid
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from app.solana_direct import (
    _derive_cal_mint_receipt_pda,
    _derive_climb_completion_receipt_pda,
    _derive_vault_pda,
    derive_ride_attestation_pda,
)
from app.services.ride_chain_accounts import ChainAccount, FinalizedChainSnapshot
from app.services.ride_economic_review import (
    FinalizedRideEconomicEvidenceCollector,
    RideEconomicReviewResolutionService,
)


BACKEND_ROOT = Path(__file__).resolve().parents[2]
BASE_MIGRATION = BACKEND_ROOT / "sql" / "114_ride_economic_recovery.sql"
REPAIR_MIGRATION = BACKEND_ROOT / "sql" / "115_ride_economic_review_repair.sql"
CONSERVATION_MIGRATION = BACKEND_ROOT / "sql" / "121_tribute_conservation.sql"
OWNERSHIP_MIGRATION = (
    BACKEND_ROOT / "sql" / "128_completion_projection_ownership.sql"
)
register_uuid()


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        check=check,
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="module")
def postgres_dsn() -> Iterator[str]:
    external_dsn = os.environ.get("TEST_POSTGRES_DSN")
    if external_dsn:
        yield external_dsn
        return
    if shutil.which("docker") is None:
        pytest.skip("Docker is required for the PostgreSQL ride review contract")
    probe = _docker("info", check=False)
    if probe.returncode != 0:
        pytest.skip("Docker daemon is unavailable for the PostgreSQL ride review contract")

    container = f"br-ride-review-pgtest-{uuid.uuid4().hex[:10]}"
    started = _docker(
        "run",
        "--rm",
        "-d",
        "--name",
        container,
        "-e",
        "POSTGRES_PASSWORD=postgres",
        "-P",
        "postgres:17",
    )
    assert started.stdout.strip()
    try:
        port_result = _docker(
            "inspect",
            "-f",
            '{{(index (index .NetworkSettings.Ports "5432/tcp") 0).HostPort}}',
            container,
        )
        port = int(port_result.stdout.strip())
        dsn = (
            f"host=127.0.0.1 port={port} dbname=postgres "
            "user=postgres password=postgres"
        )
        deadline = time.monotonic() + 30
        while True:
            try:
                connection = psycopg2.connect(dsn)
                connection.close()
                break
            except psycopg2.OperationalError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)
        yield dsn
    finally:
        _docker("rm", "-f", "-v", container, check=False)  # -v: drop the data volume too


@contextmanager
def _connection(dsn: str):
    connection = psycopg2.connect(dsn)
    connection.autocommit = True
    try:
        yield connection
    finally:
        connection.close()


def _hex(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _plan(ride_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, Any]:
    marker = ride_id.hex
    return {
        "ride_id": str(ride_id),
        "user_id": str(user_id),
        "wallet": f"wallet-{marker}",
        "ride_hash_hex": _hex(f"ride:{marker}"),
        "attestation_commitment_hex": _hex(f"commitment:{marker}"),
        "parser_version": 7,
        "policy_version": "policy-v1",
        "reward_policy": "rewardable",
        "source_kind": 1,
        "started_at": "2026-07-13T12:00:00+00:00",
        "completed_at": "2026-07-13T13:00:00+00:00",
        "total_tss": 84,
        "total_distance_m": 12000,
        "total_vert_m": 300,
        "exact_cal_base_units": "101",
        "climbs_crossed": 1,
        "exact_tribute_base_units": "11",
        "plan_evidence_hash_hex": _hex(f"plan:{marker}"),
        "expected_attestation_pda": f"attestation-{marker}",
        "expected_cal_receipt_pda": f"cal-{marker}",
    }


def _steps(ride_id: uuid.UUID) -> list[dict[str, Any]]:
    marker = ride_id.hex
    return [
        {
            "step_index": 0,
            "pattern_id": str(uuid.uuid5(ride_id, "pattern:0")),
            "vault_id": "9",
            "vault_signature": f"vault-{marker}",
            "completion_time_s": 321,
            "completed_at": "2026-07-13T13:00:00+00:00",
            "exact_tribute_base_units": "11",
            "intensity_bps": 10000,
            "climb_distance_m": 500,
            "climb_vert_m": 42,
            "completion_evidence_hash_hex": _hex(f"completion:{marker}:0"),
            "expected_receipt_pda": f"completion-{marker}-0",
        }
    ]


def _effect_observation(
    *,
    status: str,
    pda: str,
    account_seed: str,
    extra: dict[str, Any],
) -> dict[str, Any]:
    observation = {
        "status": status,
        "pda": pda,
        "observed_slot": "123456",
        **extra,
    }
    if status == "finalized":
        observation.update(
            {
                "account_data_hash_hex": _hex(account_seed),
                "tx_signature": f"tx-{_hex(account_seed)[:24]}",
                "confirmed_at": "2026-07-13T20:00:00+00:00",
            }
        )
    return observation


def _chain_evidence(
    plan: dict[str, Any],
    steps: list[dict[str, Any]],
    *,
    attestation: str,
    finalized_steps: set[int],
    cal: str,
) -> dict[str, Any]:
    return {
        "version": 1,
        "commitment": "finalized",
        "cluster": "devnet",
        "finalized_slot": "123456",
        "verified_at": "2026-07-13T20:00:00+00:00",
        "attestation": _effect_observation(
            status=attestation,
            pda=plan["expected_attestation_pda"],
            account_seed=f"attestation:{plan['ride_id']}",
            extra={
                "ride_hash_hex": plan["ride_hash_hex"],
                "attestation_commitment_hex": plan[
                    "attestation_commitment_hex"
                ],
            },
        ),
        "completions": [
            _effect_observation(
                status="finalized" if int(step["step_index"]) in finalized_steps else "absent",
                pda=step["expected_receipt_pda"],
                account_seed=f"completion:{plan['ride_id']}:{step['step_index']}",
                extra={
                    "step_index": step["step_index"],
                    "vault_id": step["vault_id"],
                    "exact_tribute_base_units": step[
                        "exact_tribute_base_units"
                    ],
                    "completion_evidence_hash_hex": step[
                        "completion_evidence_hash_hex"
                    ],
                },
            )
            for step in steps
        ],
        "cal": _effect_observation(
            status=cal,
            pda=plan["expected_cal_receipt_pda"],
            account_seed=f"cal:{plan['ride_id']}",
            extra={
                "ride_hash_hex": plan["ride_hash_hex"],
                "amount_base_units": plan["exact_cal_base_units"],
            },
        ),
    }


def _conflict(operation: str) -> dict[str, Any]:
    return {
        "version": 1,
        "kind": "pda_mismatch",
        "operation": operation,
        "message": "finalized account data conflicts with the frozen plan",
        "observed_at": "2026-07-13T20:00:00+00:00",
    }


def _freeze(cursor, ride_id: uuid.UUID, user_id: uuid.UUID):
    plan = _plan(ride_id, user_id)
    steps = _steps(ride_id)
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


def _acquire(cursor, ride_id: uuid.UUID, lease_owner: uuid.UUID):
    cursor.execute(
        "SELECT public.acquire_ride_economic_plan(%s, %s, 300)",
        (ride_id, lease_owner),
    )
    return cursor.fetchone()[0]


def _confirm_attestation(cursor, ride_id: uuid.UUID, lease_owner: uuid.UUID):
    cursor.execute(
        """
        SELECT public.advance_ride_economic_plan(
            %s, %s, 'planned', 'attestation_confirmed',
            jsonb_build_object(
                'attestation_actual_tx_signature', 'attestation-tx',
                'attestation_confirmed_at', '2026-07-13T20:00:00+00:00'
            )
        )
        """,
        (ride_id, lease_owner),
    )
    assert cursor.fetchone()[0]["state"] == "attestation_confirmed"


def _mark_review(
    cursor,
    ride_id: uuid.UUID,
    lease_owner: uuid.UUID,
    operation: str,
) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT public.mark_ride_economic_review(
            %s, %s, %s, %s, %s::jsonb
        )
        """,
        (
            ride_id,
            lease_owner,
            f"pda_mismatch:{operation}",
            "service:ride-economic-coordinator",
            Json(_conflict(operation)),
        ),
    )
    return cursor.fetchone()[0]


def _resolve(
    cursor,
    *,
    ride_id: uuid.UUID,
    review_version: int,
    request_id: uuid.UUID,
    actor_id: uuid.UUID,
    outcome: str | None,
    selected_checkpoint: str | None,
    reason: str,
    evidence: dict[str, Any],
    liability_disposition: str | None = None,
    effects_disposition: str | None = None,
) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT public.resolve_ride_economic_review(
            %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s
        )
        """,
        (
            ride_id,
            review_version,
            request_id,
            actor_id,
            outcome,
            selected_checkpoint,
            reason,
            Json(evidence),
            liability_disposition,
            effects_disposition,
        ),
    )
    return cursor.fetchone()[0]


def _frozen_row(cursor, ride_id: uuid.UUID):
    cursor.execute(
        """
        SELECT user_id, wallet, encode(ride_hash, 'hex'),
               encode(attestation_commitment, 'hex'), parser_version,
               policy_version, reward_policy, source_kind, started_at,
               completed_at, total_tss, total_distance_m, total_vert_m,
               exact_cal_base_units, climbs_crossed,
               exact_tribute_base_units, encode(plan_evidence_hash, 'hex'),
               expected_attestation_pda, expected_cal_receipt_pda
        FROM public.ride_economic_plans
        WHERE ride_id = %s
        """,
        (ride_id,),
    )
    return cursor.fetchone()


def _account_discriminator(name: str) -> bytes:
    return hashlib.sha256(f"account:{name}".encode("utf-8")).digest()[:8]


def _attestation_account_data(
    *,
    plan: dict[str, Any],
    rider: Pubkey,
    attester: Pubkey,
    bump: int,
) -> bytes:
    return b"".join(
        (
            _account_discriminator("RideAttestation"),
            bytes(rider),
            bytes.fromhex(plan["ride_hash_hex"]),
            bytes.fromhex(plan["attestation_commitment_hex"]),
            struct.pack("<I", int(plan["parser_version"])),
            struct.pack("<B", int(plan["source_kind"])),
            struct.pack(
                "<q",
                int(datetime.fromisoformat(plan["completed_at"]).timestamp()),
            ),
            struct.pack(
                "<q",
                int(datetime.fromisoformat(plan["started_at"]).timestamp()),
            ),
            struct.pack("<I", int(plan["total_tss"])),
            struct.pack("<I", int(plan["total_distance_m"])),
            struct.pack("<I", int(plan["total_vert_m"])),
            struct.pack("<Q", int(plan["exact_cal_base_units"])),
            struct.pack("<H", int(plan["climbs_crossed"])),
            bytes(attester),
            struct.pack("<qQQ?B", 0, 0, 0, False, bump),
        )
    )


def _completion_account_data(
    *,
    attestation: Pubkey,
    vault: Pubkey,
    evidence_hash: bytes,
    bump: int,
) -> bytes:
    return b"".join(
        (
            _account_discriminator("ClimbCompletionReceipt"),
            bytes(attestation),
            bytes(vault),
            evidence_hash,
            struct.pack("<B", bump),
        )
    )


class _PostgresReviewRepository:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    async def get_review(self, ride_id: uuid.UUID) -> dict[str, Any] | None:
        with _connection(self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT public.get_ride_economic_review(%s)",
                    (ride_id,),
                )
                return cursor.fetchone()[0]

    async def resolve_review(self, **kwargs) -> dict[str, Any]:
        with _connection(self.dsn) as connection:
            with connection.cursor() as cursor:
                return _resolve(
                    cursor,
                    ride_id=kwargs["ride_id"],
                    review_version=kwargs["expected_review_version"],
                    request_id=kwargs["request_id"],
                    actor_id=kwargs["actor_id"],
                    outcome=kwargs["outcome"],
                    selected_checkpoint=kwargs["selected_checkpoint"],
                    reason=kwargs["reason"],
                    evidence=kwargs["chain_evidence"],
                    liability_disposition=kwargs["liability_disposition"],
                    effects_disposition=kwargs["effects_disposition"],
                )


def test_postgres17_review_repair_privileges_fencing_and_outcomes(
    postgres_dsn: str,
) -> None:
    base_sql = BASE_MIGRATION.read_text(encoding="utf-8")
    repair_sql = REPAIR_MIGRATION.read_text(encoding="utf-8")
    conservation_sql = CONSERVATION_MIGRATION.read_text(encoding="utf-8")
    ownership_sql = OWNERSHIP_MIGRATION.read_text(encoding="utf-8")
    actor_id = uuid.uuid4()

    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE ROLE anon NOLOGIN;
                CREATE ROLE authenticated NOLOGIN;
                CREATE ROLE service_role NOLOGIN;
                CREATE TABLE public.users (id UUID PRIMARY KEY);
                CREATE TABLE public.rides (
                    id UUID PRIMARY KEY,
                    user_id UUID REFERENCES public.users(id) ON DELETE CASCADE
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
                """
            )
            cursor.execute(base_sql)
            cursor.execute(repair_sql)
            cursor.execute(conservation_sql)
            cursor.execute(ownership_sql)

            invalid_ride_id = uuid.uuid4()
            invalid_user_id = uuid.uuid4()
            invalid_plan = _plan(invalid_ride_id, invalid_user_id)
            invalid_plan["exact_cal_base_units"] = "10"
            invalid_plan["exact_tribute_base_units"] = "11"
            cursor.execute(
                "INSERT INTO public.users (id) VALUES (%s)",
                (invalid_user_id,),
            )
            cursor.execute(
                "INSERT INTO public.rides (id, user_id) VALUES (%s, %s)",
                (invalid_ride_id, invalid_user_id),
            )
            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="aggregate tribute exceeds exact CAL budget",
            ):
                cursor.execute(
                    "SELECT public.freeze_ride_economic_plan(%s::jsonb, %s::jsonb)",
                    (Json(invalid_plan), Json(_steps(invalid_ride_id))),
                )

            cursor.execute(
                """
                SELECT
                    has_table_privilege(
                        'service_role',
                        'public.ride_economic_reviews',
                        'SELECT'
                    ),
                    has_table_privilege(
                        'service_role',
                        'public.ride_economic_reviews',
                        'INSERT'
                    ),
                    has_table_privilege(
                        'service_role',
                        'public.ride_economic_reviews',
                        'UPDATE'
                    ),
                    has_table_privilege(
                        'service_role',
                        'public.ride_economic_reviews',
                        'DELETE'
                    ),
                    has_table_privilege(
                        'service_role',
                        'public.ride_economic_review_resolutions',
                        'SELECT'
                    ),
                    has_table_privilege(
                        'service_role',
                        'public.ride_economic_review_resolutions',
                        'INSERT'
                    )
                """
            )
            assert cursor.fetchone() == (True, False, False, False, True, False)

            function_privileges = {
                "public.ride_economic_frozen_facts(uuid)": False,
                "public.ride_economic_prior_checkpoint(uuid)": False,
                "public.ride_economic_known_finalized_evidence(uuid)": False,
                (
                    "public.enter_ride_economic_review(uuid,uuid,boolean,text,"
                    "text,jsonb)"
                ): False,
                "public.validate_ride_economic_chain_evidence(uuid,jsonb)": False,
                "public.reject_ride_economic_audit_mutation()": False,
                (
                    "public.freeze_ride_economic_plan_unreviewed(jsonb,jsonb)"
                ): False,
                "public.freeze_ride_economic_plan(jsonb,jsonb)": True,
                "public.acquire_ride_economic_plan(uuid,uuid,integer)": True,
                (
                    "public.checkpoint_ride_economic_retry(uuid,uuid,text,"
                    "integer,integer)"
                ): True,
                (
                    "public.mark_ride_economic_review(uuid,uuid,text,text,jsonb)"
                ): True,
                (
                    "public.resolve_ride_economic_review(uuid,bigint,uuid,uuid,"
                    "text,text,text,jsonb,text,text)"
                ): True,
                "public.get_ride_economic_review(uuid)": True,
            }
            for signature, service_can_execute in function_privileges.items():
                cursor.execute(
                    """
                    SELECT
                        to_regprocedure(%s) IS NOT NULL,
                        has_function_privilege('service_role', %s, 'EXECUTE'),
                        has_function_privilege('anon', %s, 'EXECUTE'),
                        has_function_privilege('authenticated', %s, 'EXECUTE')
                    """,
                    (signature, signature, signature, signature),
                )
                assert cursor.fetchone() == (
                    True,
                    service_can_execute,
                    False,
                    False,
                ), signature
                cursor.execute(
                    """
                    SELECT 'search_path=""' = ANY (p.proconfig)
                    FROM pg_catalog.pg_proc p
                    WHERE p.oid = to_regprocedure(%s)
                    """,
                    (signature,),
                )
                assert cursor.fetchone()[0] is True, signature

            cursor.execute("SET ROLE service_role")
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cursor.execute(
                    "UPDATE public.ride_economic_reviews SET reason = reason WHERE false"
                )
            cursor.execute("RESET ROLE")

            freeze_review_ride = uuid.uuid4()
            freeze_review_user = uuid.uuid4()
            freeze_review_lease = uuid.uuid4()
            freeze_plan, freeze_steps = _freeze(
                cursor,
                freeze_review_ride,
                freeze_review_user,
            )
            assert _acquire(cursor, freeze_review_ride, freeze_review_lease)
            _confirm_attestation(
                cursor,
                freeze_review_ride,
                freeze_review_lease,
            )
            cursor.execute(
                "SELECT public.checkpoint_ride_economic_retry(%s, %s, 'retry', NULL, 1)",
                (freeze_review_ride, freeze_review_lease),
            )
            assert cursor.fetchone()[0] is True
            replay_plan = {
                **freeze_plan,
                "plan_evidence_hash_hex": _hex(
                    f"conflict:{freeze_review_ride}"
                ),
            }
            cursor.execute(
                "SELECT public.freeze_ride_economic_plan(%s::jsonb, %s::jsonb)",
                (Json(replay_plan), Json(freeze_steps)),
            )
            replay_result = cursor.fetchone()[0]
            assert replay_result["state"] == "review"
            assert replay_result["review_version"] == 1
            cursor.execute(
                """
                SELECT prior_state,
                       conflict_evidence->>'kind',
                       frozen_facts->>'plan_evidence_hash_hex',
                       prior_checkpoint->'steps'->0->>'state'
                FROM public.ride_economic_reviews
                WHERE ride_id = %s AND review_version = 1
                """,
                (freeze_review_ride,),
            )
            assert cursor.fetchone() == (
                "attestation_confirmed",
                "frozen_plan_evidence_mismatch",
                freeze_plan["plan_evidence_hash_hex"],
                "planned",
            )
            cursor.execute(
                """
                SELECT count(*)
                FROM public.ride_economic_plan_audits
                WHERE ride_id = %s
                  AND event_type = 'nonterminal_plan_evidence_mismatch'
                """,
                (freeze_review_ride,),
            )
            assert cursor.fetchone()[0] == 1

            boundary_ride = uuid.uuid4()
            boundary_user = uuid.uuid4()
            boundary_lease = uuid.uuid4()
            boundary_plan, boundary_steps = _freeze(
                cursor,
                boundary_ride,
                boundary_user,
            )
            assert _acquire(cursor, boundary_ride, boundary_lease)
            boundary_review = _mark_review(
                cursor,
                boundary_ride,
                boundary_lease,
                "attestation",
            )
            boundary_evidence = _chain_evidence(
                boundary_plan,
                boundary_steps,
                attestation="absent",
                finalized_steps=set(),
                cal="absent",
            )

            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="outcome must be reconcile, resume, or reject",
            ):
                _resolve(
                    cursor,
                    ride_id=boundary_ride,
                    review_version=boundary_review["review_version"],
                    request_id=uuid.uuid4(),
                    actor_id=actor_id,
                    outcome=None,
                    selected_checkpoint=None,
                    reason="null outcome must fail closed",
                    evidence=boundary_evidence,
                )

            for field in ("liability_disposition", "effects_disposition"):
                kwargs = {
                    "liability_disposition": "liability accepted",
                    "effects_disposition": "effects retained",
                    field: "x" * 2001,
                }
                with pytest.raises(
                    psycopg2.errors.RaiseException,
                    match="dispositions must be bounded",
                ):
                    _resolve(
                        cursor,
                        ride_id=boundary_ride,
                        review_version=boundary_review["review_version"],
                        request_id=uuid.uuid4(),
                        actor_id=actor_id,
                        outcome="reject",
                        selected_checkpoint=None,
                        reason="oversized audit disposition must fail closed",
                        evidence=boundary_evidence,
                        **kwargs,
                    )

            for liability, effects in (
                ("l" * 2001, "effects retained"),
                ("liability accepted", "e" * 2001),
            ):
                with pytest.raises(psycopg2.errors.CheckViolation):
                    cursor.execute(
                        """
                        INSERT INTO public.ride_economic_review_resolutions (
                            request_id, ride_id, review_version, actor_id,
                            outcome, selected_checkpoint, verified_checkpoint,
                            result_state, reason, chain_evidence,
                            liability_disposition, effects_disposition
                        ) VALUES (
                            %s, %s, %s, %s, 'reject', NULL, 'planned',
                            'rejected', 'direct constraint probe', '{}'::jsonb,
                            %s, %s
                        )
                        """,
                        (
                            uuid.uuid4(),
                            boundary_ride,
                            boundary_review["review_version"],
                            actor_id,
                            liability,
                            effects,
                        ),
                    )

            bounded = _resolve(
                cursor,
                ride_id=boundary_ride,
                review_version=boundary_review["review_version"],
                request_id=uuid.uuid4(),
                actor_id=actor_id,
                outcome="reject",
                selected_checkpoint=None,
                reason="bounded audit dispositions are accepted",
                evidence=boundary_evidence,
                liability_disposition="l" * 2000,
                effects_disposition="e" * 2000,
            )
            assert bounded["result_state"] == "rejected"
            assert len(bounded["liability_disposition"]) == 2000
            assert len(bounded["effects_disposition"]) == 2000

    verified_ride = uuid.uuid4()
    verified_user = uuid.uuid4()
    verified_lease = uuid.uuid4()
    program_id = Keypair().pubkey()
    rider = Keypair().pubkey()
    verified_plan = _plan(verified_ride, verified_user)
    verified_steps = _steps(verified_ride)
    verified_plan["wallet"] = str(rider)
    ride_hash = bytes.fromhex(verified_plan["ride_hash_hex"])
    attestation, attestation_bump = derive_ride_attestation_pda(
        rider,
        ride_hash,
        program_id,
    )
    cal_receipt, _ = _derive_cal_mint_receipt_pda(
        attestation,
        rider,
        program_id,
    )
    vault, _ = _derive_vault_pda(9, program_id)
    completion, completion_bump = _derive_climb_completion_receipt_pda(
        attestation,
        vault,
        program_id,
    )
    verified_plan["expected_attestation_pda"] = str(attestation)
    verified_plan["expected_cal_receipt_pda"] = str(cal_receipt)
    verified_steps[0]["expected_receipt_pda"] = str(completion)
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO public.users (id) VALUES (%s)",
                (verified_user,),
            )
            cursor.execute(
                "INSERT INTO public.rides (id, user_id) VALUES (%s, %s)",
                (verified_ride, verified_user),
            )
            cursor.execute(
                "SELECT public.freeze_ride_economic_plan(%s::jsonb, %s::jsonb)",
                (Json(verified_plan), Json(verified_steps)),
            )
            assert _acquire(cursor, verified_ride, verified_lease)
            _confirm_attestation(cursor, verified_ride, verified_lease)
            cursor.execute(
                """
                SELECT public.confirm_ride_economic_completion(
                    %s, %s, 0, %s, NULL,
                    '2026-07-13T20:00:00+00:00'
                )
                """,
                (
                    verified_ride,
                    verified_lease,
                    str(completion),
                ),
            )
            assert cursor.fetchone()[0]["state"] == "confirmed"
            verified_review = _mark_review(
                cursor,
                verified_ride,
                verified_lease,
                "cal",
            )

    attestation_data = _attestation_account_data(
        plan=verified_plan,
        rider=rider,
        attester=Keypair().pubkey(),
        bump=attestation_bump,
    )
    completion_data = _completion_account_data(
        attestation=attestation,
        vault=vault,
        evidence_hash=bytes.fromhex(
            verified_steps[0]["completion_evidence_hash_hex"]
        ),
        bump=completion_bump,
    )

    async def snapshot_reader(rpc_url: str, addresses) -> FinalizedChainSnapshot:
        assert rpc_url == "https://rpc.invalid"
        assert tuple(str(address) for address in addresses) == (
            str(attestation),
            str(completion),
            str(cal_receipt),
        )
        return FinalizedChainSnapshot(
            slot=777777,
            accounts=(
                ChainAccount(owner=program_id, data=attestation_data),
                ChainAccount(owner=program_id, data=completion_data),
                None,
            ),
        )

    collector = FinalizedRideEconomicEvidenceCollector(
        config_loader=lambda: SimpleNamespace(
            program_id=program_id,
            rpc_url="https://rpc.invalid",
            cluster="devnet",
        ),
        snapshot_reader=snapshot_reader,
        now=lambda: datetime(2026, 7, 13, 21, 0, tzinfo=timezone.utc),
    )
    service = RideEconomicReviewResolutionService(
        repository=_PostgresReviewRepository(postgres_dsn),
        evidence_collector=collector,
    )
    service_result = asyncio.run(
        service.resolve(
            ride_id=verified_ride,
            expected_review_version=verified_review["review_version"],
            request_id=uuid.uuid4(),
            actor_id=actor_id,
            outcome="reject",
            selected_checkpoint=None,
            reason="legacy completion evidence cannot bind exact tribute",
            liability_disposition="legacy completion liability rejected",
            effects_disposition="no additional economic effects authorized",
        )
    )
    assert service_result["result_state"] == "rejected"
    assert service_result["chain_evidence"]["finalized_slot"] == "777777"
    assert service_result["chain_evidence"]["attestation"][
        "account_data_hash_hex"
    ] == hashlib.sha256(attestation_data).hexdigest()
    assert service_result["chain_evidence"]["completions"][0][
        "confirmed_at"
    ] == "2026-07-13T21:00:00+00:00"

    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            reconcile_ride = uuid.uuid4()
            reconcile_user = uuid.uuid4()
            reconcile_lease = uuid.uuid4()
            reconcile_plan, reconcile_steps = _freeze(
                cursor, reconcile_ride, reconcile_user
            )
            frozen_before = _frozen_row(cursor, reconcile_ride)
            assert _acquire(cursor, reconcile_ride, reconcile_lease)
            _confirm_attestation(cursor, reconcile_ride, reconcile_lease)
            cursor.execute(
                """
                SELECT public.confirm_ride_economic_completion(
                    %s, %s, 0, %s, 'completion-tx',
                    '2026-07-13T20:00:00+00:00'
                )
                """,
                (
                    reconcile_ride,
                    reconcile_lease,
                    reconcile_steps[0]["expected_receipt_pda"],
                ),
            )
            assert cursor.fetchone()[0]["state"] == "confirmed"

            review = _mark_review(
                cursor, reconcile_ride, reconcile_lease, "cal"
            )
            assert review["state"] == "review"
            assert review["review_version"] == 1
            cursor.execute(
                """
                SELECT prior_state, frozen_facts, prior_checkpoint,
                       finalized_evidence, reason, actor, entered_at
                FROM public.ride_economic_reviews
                WHERE ride_id = %s AND review_version = 1
                """,
                (reconcile_ride,),
            )
            review_row = cursor.fetchone()
            assert review_row[0] == "attestation_confirmed"
            assert review_row[1]["plan_evidence_hash_hex"] == reconcile_plan[
                "plan_evidence_hash_hex"
            ]
            assert review_row[2]["steps"][0]["state"] == "confirmed"
            assert review_row[3]["attestation"]["status"] == "finalized"
            assert review_row[3]["completions"][0]["status"] == "finalized"
            assert review_row[4] == "pda_mismatch:cal"
            assert review_row[5] == "service:ride-economic-coordinator"
            assert review_row[6] is not None

            assert _acquire(cursor, reconcile_ride, uuid.uuid4()) is None
            reconcile_request = uuid.uuid4()
            reconcile_evidence = _chain_evidence(
                reconcile_plan,
                reconcile_steps,
                attestation="finalized",
                finalized_steps={0},
                cal="absent",
            )
            resolved = _resolve(
                cursor,
                ride_id=reconcile_ride,
                review_version=1,
                request_id=reconcile_request,
                actor_id=actor_id,
                outcome="reconcile",
                selected_checkpoint=None,
                reason="adopt verified finalized receipt accounts",
                evidence=reconcile_evidence,
            )
            assert resolved["result_state"] == "completions_confirmed"
            assert resolved["replayed"] is False
            assert _frozen_row(cursor, reconcile_ride) == frozen_before

            replay_evidence = deepcopy(reconcile_evidence)
            replay_evidence["finalized_slot"] = "123457"
            replay_evidence["verified_at"] = "2026-07-13T20:01:00+00:00"
            replay_evidence["attestation"]["observed_slot"] = "123457"
            replay_evidence["cal"]["observed_slot"] = "123457"
            for observation in replay_evidence["completions"]:
                observation["observed_slot"] = "123457"
            replayed = _resolve(
                cursor,
                ride_id=reconcile_ride,
                review_version=1,
                request_id=reconcile_request,
                actor_id=actor_id,
                outcome="reconcile",
                selected_checkpoint=None,
                reason="adopt verified finalized receipt accounts",
                evidence=replay_evidence,
            )
            assert replayed["request_id"] == str(reconcile_request)
            assert replayed["replayed"] is True
            assert replayed["chain_evidence"]["finalized_slot"] == "123456"
            cursor.execute(
                "SELECT count(*) FROM public.ride_economic_review_resolutions WHERE ride_id = %s",
                (reconcile_ride,),
            )
            assert cursor.fetchone()[0] == 1

            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="request_id payload conflict",
            ):
                _resolve(
                    cursor,
                    ride_id=reconcile_ride,
                    review_version=1,
                    request_id=reconcile_request,
                    actor_id=actor_id,
                    outcome="reconcile",
                    selected_checkpoint=None,
                    reason="changed replay payload",
                    evidence=reconcile_evidence,
                )
            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="already resolved",
            ):
                _resolve(
                    cursor,
                    ride_id=reconcile_ride,
                    review_version=1,
                    request_id=uuid.uuid4(),
                    actor_id=actor_id,
                    outcome="reconcile",
                    selected_checkpoint=None,
                    reason="competing decision",
                    evidence=reconcile_evidence,
                )

            resume_ride = uuid.uuid4()
            resume_user = uuid.uuid4()
            resume_lease = uuid.uuid4()
            resume_plan, resume_steps = _freeze(cursor, resume_ride, resume_user)
            resume_frozen = _frozen_row(cursor, resume_ride)
            assert _acquire(cursor, resume_ride, resume_lease)
            resume_review = _mark_review(
                cursor, resume_ride, resume_lease, "attestation"
            )
            resume_evidence = _chain_evidence(
                resume_plan,
                resume_steps,
                attestation="absent",
                finalized_steps=set(),
                cal="absent",
            )
            resumed = _resolve(
                cursor,
                ride_id=resume_ride,
                review_version=resume_review["review_version"],
                request_id=uuid.uuid4(),
                actor_id=actor_id,
                outcome="resume",
                selected_checkpoint="planned",
                reason="finalized absence proves a clean restart",
                evidence=resume_evidence,
            )
            assert resumed["result_state"] == "planned"
            assert _frozen_row(cursor, resume_ride) == resume_frozen
            assert _acquire(cursor, resume_ride, uuid.uuid4()) is not None

            unsafe_ride = uuid.uuid4()
            unsafe_user = uuid.uuid4()
            unsafe_lease = uuid.uuid4()
            unsafe_plan, unsafe_steps = _freeze(cursor, unsafe_ride, unsafe_user)
            assert _acquire(cursor, unsafe_ride, unsafe_lease)
            _confirm_attestation(cursor, unsafe_ride, unsafe_lease)
            unsafe_review = _mark_review(
                cursor, unsafe_ride, unsafe_lease, "completion"
            )
            unsafe_evidence = _chain_evidence(
                unsafe_plan,
                unsafe_steps,
                attestation="finalized",
                finalized_steps=set(),
                cal="finalized",
            )
            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="CAL cannot be finalized before every completion",
            ):
                _resolve(
                    cursor,
                    ride_id=unsafe_ride,
                    review_version=unsafe_review["review_version"],
                    request_id=uuid.uuid4(),
                    actor_id=actor_id,
                    outcome="resume",
                    selected_checkpoint="cal_confirmed",
                    reason="unsafe operator request",
                    evidence=unsafe_evidence,
                )
            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="review version fence failed",
            ):
                _resolve(
                    cursor,
                    ride_id=unsafe_ride,
                    review_version=unsafe_review["review_version"] + 1,
                    request_id=uuid.uuid4(),
                    actor_id=actor_id,
                    outcome="resume",
                    selected_checkpoint="attestation_confirmed",
                    reason="stale review decision",
                    evidence=_chain_evidence(
                        unsafe_plan,
                        unsafe_steps,
                        attestation="finalized",
                        finalized_steps=set(),
                        cal="absent",
                    ),
                )
            cursor.execute(
                "SELECT state FROM public.ride_economic_plans WHERE ride_id = %s",
                (unsafe_ride,),
            )
            assert cursor.fetchone()[0] == "review"

            reject_ride = uuid.uuid4()
            reject_user = uuid.uuid4()
            reject_lease = uuid.uuid4()
            reject_plan, reject_steps = _freeze(cursor, reject_ride, reject_user)
            reject_frozen = _frozen_row(cursor, reject_ride)
            assert _acquire(cursor, reject_ride, reject_lease)
            _confirm_attestation(cursor, reject_ride, reject_lease)
            reject_review = _mark_review(
                cursor, reject_ride, reject_lease, "completion"
            )
            reject_evidence = _chain_evidence(
                reject_plan,
                reject_steps,
                attestation="finalized",
                finalized_steps=set(),
                cal="absent",
            )
            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="liability disposition",
            ):
                _resolve(
                    cursor,
                    ride_id=reject_ride,
                    review_version=reject_review["review_version"],
                    request_id=uuid.uuid4(),
                    actor_id=actor_id,
                    outcome="reject",
                    selected_checkpoint=None,
                    reason="terminal adjudication",
                    evidence=reject_evidence,
                    effects_disposition="attestation retained; no CAL or completion",
                )
            rejected = _resolve(
                cursor,
                ride_id=reject_ride,
                review_version=reject_review["review_version"],
                request_id=uuid.uuid4(),
                actor_id=actor_id,
                outcome="reject",
                selected_checkpoint=None,
                reason="terminal adjudication",
                evidence=reject_evidence,
                liability_disposition="manual rider liability case opened",
                effects_disposition="attestation retained; no CAL or completion",
            )
            assert rejected["result_state"] == "rejected"
            assert _frozen_row(cursor, reject_ride) == reject_frozen
            assert _acquire(cursor, reject_ride, uuid.uuid4()) is None
            cursor.execute(
                """
                SELECT liability_disposition, effects_disposition,
                       chain_evidence->'attestation'->>'status'
                FROM public.ride_economic_review_resolutions
                WHERE ride_id = %s
                """,
                (reject_ride,),
            )
            assert cursor.fetchone() == (
                "manual rider liability case opened",
                "attestation retained; no CAL or completion",
                "finalized",
            )

            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="append-only",
            ):
                cursor.execute(
                    "UPDATE public.ride_economic_reviews SET reason = 'rewrite' WHERE ride_id = %s",
                    (reject_ride,),
                )
            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="append-only",
            ):
                cursor.execute(
                    "DELETE FROM public.ride_economic_review_resolutions WHERE ride_id = %s",
                    (reject_ride,),
                )
            with pytest.raises(
                psycopg2.errors.RaiseException,
                match="append-only",
            ):
                cursor.execute(
                    "UPDATE public.ride_economic_plan_audits SET details = '{}' WHERE ride_id = %s",
                    (freeze_review_ride,),
                )

    concurrent_ride = uuid.uuid4()
    concurrent_user = uuid.uuid4()
    concurrent_lease = uuid.uuid4()
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            concurrent_plan, concurrent_steps = _freeze(
                cursor, concurrent_ride, concurrent_user
            )
            assert _acquire(cursor, concurrent_ride, concurrent_lease)
            review = _mark_review(
                cursor, concurrent_ride, concurrent_lease, "attestation"
            )
    concurrent_evidence = _chain_evidence(
        concurrent_plan,
        concurrent_steps,
        attestation="absent",
        finalized_steps=set(),
        cal="absent",
    )

    def competing_resolution(request_id: uuid.UUID) -> tuple[str, str]:
        try:
            with _connection(postgres_dsn) as connection:
                with connection.cursor() as cursor:
                    result = _resolve(
                        cursor,
                        ride_id=concurrent_ride,
                        review_version=review["review_version"],
                        request_id=request_id,
                        actor_id=actor_id,
                        outcome="resume",
                        selected_checkpoint="planned",
                        reason=f"concurrent decision {request_id}",
                        evidence=concurrent_evidence,
                    )
                    return "resolved", result["request_id"]
        except psycopg2.Error as exc:
            return "conflict", str(exc)

    requests = [uuid.uuid4(), uuid.uuid4()]
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(competing_resolution, requests))
    assert [result[0] for result in results].count("resolved") == 1
    assert [result[0] for result in results].count("conflict") == 1
    assert "already resolved" in next(
        result[1] for result in results if result[0] == "conflict"
    )

    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*), min(outcome), min(result_state)
                FROM public.ride_economic_review_resolutions
                WHERE ride_id = %s
                """,
                (concurrent_ride,),
            )
            assert cursor.fetchone() == (1, "resume", "planned")

    same_request_ride = uuid.uuid4()
    same_request_user = uuid.uuid4()
    same_request_lease = uuid.uuid4()
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            same_plan, same_steps = _freeze(
                cursor,
                same_request_ride,
                same_request_user,
            )
            assert _acquire(cursor, same_request_ride, same_request_lease)
            same_review = _mark_review(
                cursor,
                same_request_ride,
                same_request_lease,
                "attestation",
            )
    base_same_evidence = _chain_evidence(
        same_plan,
        same_steps,
        attestation="absent",
        finalized_steps=set(),
        cal="absent",
    )
    same_request_id = uuid.uuid4()

    def identical_resolution(slot: int) -> dict[str, Any]:
        evidence = deepcopy(base_same_evidence)
        evidence["finalized_slot"] = str(slot)
        evidence["verified_at"] = f"2026-07-13T20:{slot % 60:02d}:00+00:00"
        evidence["attestation"]["observed_slot"] = str(slot)
        evidence["cal"]["observed_slot"] = str(slot)
        for observation in evidence["completions"]:
            observation["observed_slot"] = str(slot)
        with _connection(postgres_dsn) as connection:
            with connection.cursor() as cursor:
                return _resolve(
                    cursor,
                    ride_id=same_request_ride,
                    review_version=same_review["review_version"],
                    request_id=same_request_id,
                    actor_id=actor_id,
                    outcome="resume",
                    selected_checkpoint="planned",
                    reason="same lost-response operator intent",
                    evidence=evidence,
                )

    with ThreadPoolExecutor(max_workers=2) as executor:
        identical_results = list(executor.map(identical_resolution, (200001, 200002)))
    assert sorted(result["replayed"] for result in identical_results) == [False, True]
    assert {result["request_id"] for result in identical_results} == {
        str(same_request_id)
    }
    assert {
        result["chain_evidence"]["finalized_slot"] for result in identical_results
    } in ({"200001"}, {"200002"})
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*)
                FROM public.ride_economic_review_resolutions
                WHERE ride_id = %s AND request_id = %s
                """,
                (same_request_ride, same_request_id),
            )
            assert cursor.fetchone()[0] == 1

    service_race_ride = uuid.uuid4()
    service_race_user = uuid.uuid4()
    service_race_lease = uuid.uuid4()
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            race_plan, race_steps = _freeze(
                cursor,
                service_race_ride,
                service_race_user,
            )
            assert _acquire(cursor, service_race_ride, service_race_lease)
            race_review = _mark_review(
                cursor,
                service_race_ride,
                service_race_lease,
                "attestation",
            )
    race_base_evidence = _chain_evidence(
        race_plan,
        race_steps,
        attestation="absent",
        finalized_steps=set(),
        cal="absent",
    )
    race_request_id = uuid.uuid4()

    async def run_service_race() -> list[dict[str, Any]]:
        ready = asyncio.Event()
        arrival_count = 0

        class Collector:
            def __init__(self, slot: int) -> None:
                self.slot = slot

            async def collect(self, plan) -> dict[str, Any]:
                nonlocal arrival_count
                arrival_count += 1
                if arrival_count == 2:
                    ready.set()
                await ready.wait()
                evidence = deepcopy(race_base_evidence)
                evidence["finalized_slot"] = str(self.slot)
                evidence["verified_at"] = (
                    f"2026-07-13T22:{self.slot % 60:02d}:00+00:00"
                )
                evidence["attestation"]["observed_slot"] = str(self.slot)
                evidence["cal"]["observed_slot"] = str(self.slot)
                for observation in evidence["completions"]:
                    observation["observed_slot"] = str(self.slot)
                return evidence

        services = [
            RideEconomicReviewResolutionService(
                repository=_PostgresReviewRepository(postgres_dsn),
                evidence_collector=Collector(slot),
            )
            for slot in (300001, 300002)
        ]
        return await asyncio.gather(
            *(
                service.resolve(
                    ride_id=service_race_ride,
                    expected_review_version=race_review["review_version"],
                    request_id=race_request_id,
                    actor_id=actor_id,
                    outcome="reject",
                    selected_checkpoint=None,
                    reason="same concurrent legacy rejection request",
                    liability_disposition="legacy completion liability rejected",
                    effects_disposition="no additional economic effects authorized",
                )
                for service in services
            )
        )

    service_race_results = asyncio.run(run_service_race())
    assert sorted(result["replayed"] for result in service_race_results) == [
        False,
        True,
    ]
    assert {
        result["chain_evidence"]["finalized_slot"]
        for result in service_race_results
    } in ({"300001"}, {"300002"})
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*)
                FROM public.ride_economic_review_resolutions
                WHERE ride_id = %s AND request_id = %s
                """,
                (service_race_ride, race_request_id),
            )
            assert cursor.fetchone()[0] == 1
