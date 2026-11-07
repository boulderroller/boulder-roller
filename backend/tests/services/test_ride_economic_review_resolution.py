from __future__ import annotations

import hashlib
import inspect
import struct
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from app.solana_direct import (
    _derive_cal_mint_receipt_pda,
    _derive_climb_completion_receipt_pda,
    _derive_vault_pda,
    derive_ride_attestation_pda,
)
from app.services.ride_chain_accounts import (
    ChainAccount,
    ChainAccountMismatchError,
    ChainAccountUnavailableError,
    FinalizedChainSnapshot,
    LegacyCompletionEvidenceError,
)
from app.services.ride_economic_review import (
    FinalizedRideEconomicEvidenceCollector,
    RideEconomicReviewResolutionService,
)


def _discriminator(name: str) -> bytes:
    return hashlib.sha256(f"account:{name}".encode("utf-8")).digest()[:8]


def _plan(program_id: Pubkey, rider: Pubkey) -> dict:
    ride_hash = bytes.fromhex("11" * 32)
    attestation_commitment = bytes.fromhex("22" * 32)
    attestation, _ = derive_ride_attestation_pda(rider, ride_hash, program_id)
    cal_receipt, _ = _derive_cal_mint_receipt_pda(
        attestation, rider, program_id
    )
    vault, _ = _derive_vault_pda(9, program_id)
    completion, _ = _derive_climb_completion_receipt_pda(
        attestation, vault, program_id
    )
    return {
        "ride_id": str(uuid4()),
        "state": "review",
        "review_version": 4,
        "wallet": str(rider),
        "ride_hash_hex": ride_hash.hex(),
        "attestation_commitment_hex": attestation_commitment.hex(),
        "parser_version": 7,
        "source_kind": 1,
        "started_at": "2026-07-13T12:00:00+00:00",
        "completed_at": "2026-07-13T13:00:00+00:00",
        "total_tss": 84,
        "total_distance_m": 12000,
        "total_vert_m": 300,
        "exact_cal_base_units": 101,
        "climbs_crossed": 1,
        "expected_attestation_pda": str(attestation),
        "expected_cal_receipt_pda": str(cal_receipt),
        "steps": [
            {
                "step_index": 0,
                "vault_id": 9,
                "exact_tribute_base_units": 11,
                "completion_evidence_version": 2,
                "completion_evidence_hash_hex": "33" * 32,
                "expected_receipt_pda": str(completion),
            }
        ],
    }


def _attestation_data(
    *,
    plan: dict,
    rider: Pubkey,
    attester: Pubkey,
    bump: int,
    parser_version: int = 7,
) -> bytes:
    return b"".join(
        (
            _discriminator("RideAttestation"),
            bytes(rider),
            bytes.fromhex(plan["ride_hash_hex"]),
            bytes.fromhex(plan["attestation_commitment_hex"]),
            struct.pack("<I", parser_version),
            struct.pack("<B", plan["source_kind"]),
            struct.pack(
                "<q",
                int(datetime.fromisoformat(plan["completed_at"]).timestamp()),
            ),
            struct.pack(
                "<q", int(datetime.fromisoformat(plan["started_at"]).timestamp())
            ),
            struct.pack("<I", plan["total_tss"]),
            struct.pack("<I", plan["total_distance_m"]),
            struct.pack("<I", plan["total_vert_m"]),
            struct.pack("<Q", plan["exact_cal_base_units"]),
            struct.pack("<H", plan["climbs_crossed"]),
            bytes(attester),
            struct.pack("<qQQ?B", 0, 0, 0, False, bump),
        )
    )


def _completion_data(
    *,
    ride_attestation: Pubkey,
    vault: Pubkey,
    evidence_hash: bytes,
    bump: int,
) -> bytes:
    return b"".join(
        (
            _discriminator("ClimbCompletionReceipt"),
            bytes(ride_attestation),
            bytes(vault),
            evidence_hash,
            struct.pack("<B", bump),
        )
    )


def _completion_data_v2(
    *,
    ride_attestation: Pubkey,
    vault: Pubkey,
    cal_tributed: int,
    evidence_hash: bytes,
    bump: int,
) -> bytes:
    return b"".join(
        (
            _discriminator("ClimbCompletionReceiptV2"),
            bytes(ride_attestation),
            bytes(vault),
            struct.pack("<BQ", 2, cal_tributed),
            evidence_hash,
            struct.pack("<B", bump),
        )
    )


def _service(
    *,
    repository,
    collector,
) -> RideEconomicReviewResolutionService:
    return RideEconomicReviewResolutionService(
        repository=repository,
        evidence_collector=collector,
    )


def _resolution_kwargs(plan: dict) -> dict:
    return {
        "ride_id": UUID(plan["ride_id"]),
        "expected_review_version": plan["review_version"],
        "request_id": uuid4(),
        "actor_id": uuid4(),
        "outcome": "resume",
        "selected_checkpoint": "planned",
        "reason": "finalized account snapshot proves a clean restart",
        "liability_disposition": None,
        "effects_disposition": None,
    }


def _inspection(plan: dict, resolution=None) -> dict:
    return {
        "plan": plan,
        "review": {"review_version": plan["review_version"]},
        "resolution": resolution,
    }


@pytest.mark.asyncio
async def test_resolution_service_never_accepts_operator_chain_evidence() -> None:
    program_id = Keypair().pubkey()
    plan = _plan(program_id, Keypair().pubkey())
    repository = SimpleNamespace(
        get_review=AsyncMock(return_value=_inspection(plan)),
        resolve_review=AsyncMock(),
    )
    collector = SimpleNamespace(collect=AsyncMock())
    service = _service(repository=repository, collector=collector)

    assert "chain_evidence" not in inspect.signature(service.resolve).parameters
    with pytest.raises(TypeError, match="chain_evidence"):
        await service.resolve(
            **_resolution_kwargs(plan),
            chain_evidence={"commitment": "finalized", "forged": True},
        )

    collector.collect.assert_not_awaited()
    repository.resolve_review.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolution_uses_only_collector_verified_snapshot() -> None:
    program_id = Keypair().pubkey()
    plan = _plan(program_id, Keypair().pubkey())
    verified = {
        "version": 1,
        "commitment": "finalized",
        "cluster": "devnet",
        "finalized_slot": "99",
        "verified_at": "2026-07-13T20:00:00+00:00",
        "attestation": {"status": "absent"},
        "completions": [
            {
                "step_index": 0,
                "status": "absent",
                "completion_evidence_version": 2,
                "tribute_bound": True,
            }
        ],
        "cal": {"status": "absent"},
    }
    repository = SimpleNamespace(
        get_review=AsyncMock(return_value=_inspection(plan)),
        resolve_review=AsyncMock(return_value={"result_state": "planned"}),
    )
    collector = SimpleNamespace(collect=AsyncMock(return_value=verified))
    service = _service(repository=repository, collector=collector)
    kwargs = _resolution_kwargs(plan)

    result = await service.resolve(**kwargs)

    assert result == {"result_state": "planned"}
    collector.collect.assert_awaited_once_with(plan)
    repository.resolve_review.assert_awaited_once_with(
        **kwargs,
        chain_evidence=verified,
    )


@pytest.mark.asyncio
async def test_lost_response_retry_returns_stored_decision_without_recollecting() -> None:
    program_id = Keypair().pubkey()
    plan = _plan(program_id, Keypair().pubkey())
    plan["state"] = "planned"
    kwargs = _resolution_kwargs(plan)
    stored = {
        "request_id": str(kwargs["request_id"]),
        "ride_id": plan["ride_id"],
        "review_version": kwargs["expected_review_version"],
        "actor_id": str(kwargs["actor_id"]),
        "outcome": kwargs["outcome"],
        "selected_checkpoint": kwargs["selected_checkpoint"],
        "verified_checkpoint": "planned",
        "result_state": "planned",
        "reason": kwargs["reason"],
        "liability_disposition": None,
        "effects_disposition": None,
        "chain_evidence": {
            "finalized_slot": "100",
            "verified_at": "2026-07-13T20:00:00+00:00",
        },
    }
    repository = SimpleNamespace(
        get_review=AsyncMock(return_value=_inspection(plan, stored)),
        resolve_review=AsyncMock(),
    )
    collector = SimpleNamespace(
        collect=AsyncMock(
            return_value={
                "finalized_slot": "101",
                "verified_at": "2026-07-13T20:01:00+00:00",
            }
        )
    )
    service = _service(repository=repository, collector=collector)

    result = await service.resolve(**kwargs)

    assert result["replayed"] is True
    assert result["chain_evidence"] == stored["chain_evidence"]
    collector.collect.assert_not_awaited()
    repository.resolve_review.assert_not_awaited()


@pytest.mark.asyncio
async def test_finalized_account_mismatch_fails_closed_before_resolution() -> None:
    program_id = Keypair().pubkey()
    rider = Keypair().pubkey()
    plan = _plan(program_id, rider)
    attestation_pda, bump = derive_ride_attestation_pda(
        rider,
        bytes.fromhex(plan["ride_hash_hex"]),
        program_id,
    )
    assert str(attestation_pda) == plan["expected_attestation_pda"]
    snapshot_reader = AsyncMock(
        return_value=FinalizedChainSnapshot(
            slot=999,
            accounts=(
                ChainAccount(
                    owner=program_id,
                    data=_attestation_data(
                        plan=plan,
                        rider=rider,
                        attester=Keypair().pubkey(),
                        bump=bump,
                        parser_version=8,
                    ),
                ),
                None,
                None,
            ),
        )
    )
    collector = FinalizedRideEconomicEvidenceCollector(
        config_loader=lambda: SimpleNamespace(
            program_id=program_id,
            rpc_url="https://rpc.invalid",
            cluster="devnet",
        ),
        snapshot_reader=snapshot_reader,
        now=lambda: datetime(2026, 7, 13, 20, 0, tzinfo=timezone.utc),
    )
    repository = SimpleNamespace(
        get_review=AsyncMock(return_value=_inspection(plan)),
        resolve_review=AsyncMock(),
    )
    service = _service(repository=repository, collector=collector)

    with pytest.raises(
        ChainAccountMismatchError,
        match="parser_version does not match frozen value",
    ):
        await service.resolve(**_resolution_kwargs(plan))

    repository.resolve_review.assert_not_awaited()


@pytest.mark.asyncio
async def test_collector_accepts_strict_finalized_attestation_and_completion() -> None:
    program_id = Keypair().pubkey()
    rider = Keypair().pubkey()
    plan = _plan(program_id, rider)
    ride_hash = bytes.fromhex(plan["ride_hash_hex"])
    attestation, attestation_bump = derive_ride_attestation_pda(
        rider,
        ride_hash,
        program_id,
    )
    vault, _ = _derive_vault_pda(9, program_id)
    completion, completion_bump = _derive_climb_completion_receipt_pda(
        attestation,
        vault,
        program_id,
    )
    snapshot_reader = AsyncMock(
        return_value=FinalizedChainSnapshot(
            slot=999,
            accounts=(
                ChainAccount(
                    owner=program_id,
                    data=_attestation_data(
                        plan=plan,
                        rider=rider,
                        attester=Keypair().pubkey(),
                        bump=attestation_bump,
                    ),
                ),
                ChainAccount(
                    owner=program_id,
                    data=_completion_data_v2(
                        ride_attestation=attestation,
                        vault=vault,
                        cal_tributed=plan["steps"][0]["exact_tribute_base_units"],
                        evidence_hash=bytes.fromhex(
                            plan["steps"][0]["completion_evidence_hash_hex"]
                        ),
                        bump=completion_bump,
                    ),
                ),
                None,
            ),
        )
    )
    collector = FinalizedRideEconomicEvidenceCollector(
        config_loader=lambda: SimpleNamespace(
            program_id=program_id,
            rpc_url="https://rpc.invalid",
            cluster="devnet",
        ),
        snapshot_reader=snapshot_reader,
        now=lambda: datetime(2026, 7, 13, 20, 0, tzinfo=timezone.utc),
    )

    evidence = await collector.collect(plan)

    assert evidence["finalized_slot"] == "999"
    assert evidence["attestation"]["status"] == "finalized"
    assert evidence["attestation"]["confirmed_at"] == evidence["verified_at"]
    assert evidence["completions"][0]["status"] == "finalized"
    assert evidence["completions"][0]["completion_evidence_version"] == 2
    assert evidence["completions"][0]["tribute_bound"] is True
    assert evidence["completions"][0]["confirmed_at"] == evidence["verified_at"]
    assert evidence["cal"]["status"] == "absent"
    assert evidence["attestation"]["account_data_hash_hex"] == hashlib.sha256(
        snapshot_reader.return_value.accounts[0].data
    ).hexdigest()
    assert str(completion) == plan["steps"][0]["expected_receipt_pda"]


@pytest.mark.asyncio
async def test_legacy_completion_is_visible_but_cannot_resume_review() -> None:
    program_id = Keypair().pubkey()
    rider = Keypair().pubkey()
    plan = _plan(program_id, rider)
    plan["steps"][0]["completion_evidence_version"] = 1
    ride_hash = bytes.fromhex(plan["ride_hash_hex"])
    attestation, attestation_bump = derive_ride_attestation_pda(
        rider, ride_hash, program_id
    )
    vault, _ = _derive_vault_pda(9, program_id)
    _, completion_bump = _derive_climb_completion_receipt_pda(
        attestation, vault, program_id
    )
    snapshot_reader = AsyncMock(
        return_value=FinalizedChainSnapshot(
            slot=999,
            accounts=(
                ChainAccount(
                    owner=program_id,
                    data=_attestation_data(
                        plan=plan,
                        rider=rider,
                        attester=Keypair().pubkey(),
                        bump=attestation_bump,
                    ),
                ),
                ChainAccount(
                    owner=program_id,
                    data=_completion_data(
                        ride_attestation=attestation,
                        vault=vault,
                        evidence_hash=bytes.fromhex(
                            plan["steps"][0]["completion_evidence_hash_hex"]
                        ),
                        bump=completion_bump,
                    ),
                ),
                None,
            ),
        )
    )
    collector = FinalizedRideEconomicEvidenceCollector(
        config_loader=lambda: SimpleNamespace(
            program_id=program_id,
            rpc_url="https://rpc.invalid",
            cluster="devnet",
        ),
        snapshot_reader=snapshot_reader,
    )
    repository = SimpleNamespace(
        get_review=AsyncMock(return_value=_inspection(plan)),
        resolve_review=AsyncMock(),
    )
    service = _service(repository=repository, collector=collector)

    with pytest.raises(
        LegacyCompletionEvidenceError,
        match="cannot authorize a non-reject review resolution",
    ):
        await service.resolve(**_resolution_kwargs(plan))

    repository.resolve_review.assert_not_awaited()


@pytest.mark.asyncio
async def test_finalized_rpc_unavailability_fails_closed_before_resolution() -> None:
    program_id = Keypair().pubkey()
    plan = _plan(program_id, Keypair().pubkey())
    snapshot_reader = AsyncMock(
        side_effect=ChainAccountUnavailableError("finalized RPC unavailable")
    )
    collector = FinalizedRideEconomicEvidenceCollector(
        config_loader=lambda: SimpleNamespace(
            program_id=program_id,
            rpc_url="https://rpc.invalid",
            cluster="devnet",
        ),
        snapshot_reader=snapshot_reader,
    )
    repository = SimpleNamespace(
        get_review=AsyncMock(return_value=_inspection(plan)),
        resolve_review=AsyncMock(),
    )
    service = _service(repository=repository, collector=collector)

    with pytest.raises(
        ChainAccountUnavailableError,
        match="finalized RPC unavailable",
    ):
        await service.resolve(**_resolution_kwargs(plan))

    repository.resolve_review.assert_not_awaited()


@pytest.mark.asyncio
async def test_collector_fails_closed_above_atomic_rpc_account_limit() -> None:
    program_id = Keypair().pubkey()
    rider = Keypair().pubkey()
    plan = _plan(program_id, rider)
    attestation = Pubkey.from_string(plan["expected_attestation_pda"])
    steps = []
    for step_index in range(99):
        vault_id = step_index + 1
        vault, _ = _derive_vault_pda(vault_id, program_id)
        receipt, _ = _derive_climb_completion_receipt_pda(
            attestation,
            vault,
            program_id,
        )
        steps.append(
            {
                "step_index": step_index,
                "vault_id": vault_id,
                "exact_tribute_base_units": 0,
                "completion_evidence_hash_hex": f"{step_index + 1:064x}",
                "expected_receipt_pda": str(receipt),
            }
        )
    plan["steps"] = steps
    plan["climbs_crossed"] = len(steps)
    snapshot_reader = AsyncMock()
    collector = FinalizedRideEconomicEvidenceCollector(
        config_loader=lambda: SimpleNamespace(
            program_id=program_id,
            rpc_url="https://rpc.invalid",
            cluster="devnet",
        ),
        snapshot_reader=snapshot_reader,
    )

    with pytest.raises(
        ChainAccountUnavailableError,
        match="101 accounts, exceeding the 100-account atomic finalized RPC limit",
    ):
        await collector.collect(plan)

    snapshot_reader.assert_not_awaited()
