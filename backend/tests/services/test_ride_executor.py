from __future__ import annotations

import hashlib
import struct
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from app.solana_direct import (
    _derive_cal_mint_receipt_pda,
    _derive_climb_completion_receipt_pda,
    _derive_vault_pda,
    derive_ride_attestation_pda,
)
from app.services.ride_attester import OnchainRideIdentity
from app.services.ride_executor import RideExecutor


def _identity() -> OnchainRideIdentity:
    ride_hash = bytes.fromhex("ab" * 32)
    return OnchainRideIdentity(
        ride_hash=ride_hash,
        attestation_commitment=ride_hash,
        parser_version=7,
        source_kind=1,
    )


def _account_discriminator(name: str) -> bytes:
    return hashlib.sha256(f"account:{name}".encode()).digest()[:8]


def _ride_attestation_data(
    *,
    rider: Pubkey,
    identity: OnchainRideIdentity,
    completed_at: int,
    started_at: int,
    total_tss: int,
    total_distance_m: int,
    total_vert_m: int,
    cal_earned: int,
    climbs_crossed: int,
    attester: Pubkey,
    bump: int,
    parser_version: int | None = None,
    settled_at: int = 0,
) -> bytes:
    return b"".join(
        (
            _account_discriminator("RideAttestation"),
            bytes(rider),
            identity.ride_hash,
            identity.attestation_commitment,
            struct.pack("<I", identity.parser_version if parser_version is None else parser_version),
            struct.pack("<B", identity.source_kind),
            struct.pack("<q", completed_at),
            struct.pack("<q", started_at),
            struct.pack("<I", total_tss),
            struct.pack("<I", total_distance_m),
            struct.pack("<I", total_vert_m),
            struct.pack("<Q", cal_earned),
            struct.pack("<H", climbs_crossed),
            bytes(attester),
            struct.pack("<qQQ?B", settled_at, 0, 0, False, bump),
        )
    )


def _cal_receipt_data(
    *, ride_attestation: Pubkey, rider: Pubkey, amount: int, bump: int
) -> bytes:
    return b"".join(
        (
            _account_discriminator("CalMintReceipt"),
            bytes(ride_attestation),
            bytes(rider),
            struct.pack("<QB", amount, bump),
        )
    )


def _completion_receipt_data(
    *,
    ride_attestation: Pubkey,
    vault: Pubkey,
    evidence_hash: bytes,
    bump: int,
) -> bytes:
    return b"".join(
        (
            _account_discriminator("ClimbCompletionReceipt"),
            bytes(ride_attestation),
            bytes(vault),
            evidence_hash,
            struct.pack("<B", bump),
        )
    )


def _completion_receipt_v2_data(
    *,
    ride_attestation: Pubkey,
    vault: Pubkey,
    cal_tributed: int,
    evidence_hash: bytes,
    bump: int,
) -> bytes:
    return b"".join(
        (
            _account_discriminator("ClimbCompletionReceiptV2"),
            bytes(ride_attestation),
            bytes(vault),
            struct.pack("<BQ", 2, cal_tributed),
            evidence_hash,
            struct.pack("<B", bump),
        )
    )


@pytest.mark.asyncio
async def test_record_ride_attestation_uses_chain_config_and_returns_existing_pda() -> None:
    expected_pda = Pubkey.default()
    record_ride = AsyncMock(return_value=f"exists:{expected_pda}")
    derive = MagicMock(return_value=(expected_pda, 255))
    identity = _identity()
    account_reader = AsyncMock(
        return_value=SimpleNamespace(
            owner=Pubkey.default(),
            data=_ride_attestation_data(
                rider=Pubkey.default(),
                identity=identity,
                completed_at=1_776_430_800,
                started_at=1_776_427_200,
                total_tss=84,
                total_distance_m=12000,
                total_vert_m=300,
                cal_earned=84_000_000_000,
                climbs_crossed=2,
                attester=Keypair().pubkey(),
                bump=255,
                settled_at=1_776_431_100,
            ),
        )
    )
    executor = RideExecutor(
        config_loader=lambda: SimpleNamespace(
            program_id=Pubkey.default(), rpc_url="https://rpc.invalid"
        ),
        record_ride_fn=record_ride,
        derive_ride_attestation_pda_fn=derive,
        account_reader=account_reader,
    )

    result = await executor.record_ride_attestation(
        rider_wallet=str(Pubkey.default()),
        identity=identity,
        completed_at=datetime(2026, 4, 17, 13, 0, tzinfo=timezone.utc),
        started_at=datetime(2026, 4, 17, 12, 0, tzinfo=timezone.utc),
        total_tss=84,
        total_distance_m=12000,
        total_vert_m=300,
        cal_earned=84_000_000_000,
        climbs_crossed=2,
    )

    assert result.reference == f"exists:{expected_pda}"
    assert result.pda == str(expected_pda)
    assert result.tx_signature is None
    assert result.attested_at == "2026-04-17T13:05:00+00:00"
    record_ride.assert_awaited_once()
    kwargs = record_ride.await_args.kwargs
    assert kwargs["parser_version"] == 7
    assert kwargs["completed_at"] == 1_776_430_800
    assert kwargs["started_at"] == 1_776_427_200
    assert kwargs["cal_earned"] == 84_000_000_000
    account_reader.assert_awaited_once_with("https://rpc.invalid", expected_pda)


@pytest.mark.asyncio
async def test_record_ride_attestation_derives_pda_for_new_transaction() -> None:
    record_ride = AsyncMock(return_value="tx-sig")
    derive = MagicMock(return_value=(Pubkey.default(), 255))
    identity = _identity()
    account_reader = AsyncMock(
        return_value=SimpleNamespace(
            owner=Pubkey.default(),
            data=_ride_attestation_data(
                rider=Pubkey.default(),
                identity=identity,
                completed_at=1_776_430_800,
                started_at=1_776_427_200,
                total_tss=84,
                total_distance_m=12000,
                total_vert_m=300,
                cal_earned=84_000_000_000,
                climbs_crossed=2,
                attester=Keypair().pubkey(),
                bump=255,
                settled_at=1_776_431_100,
            ),
        )
    )
    executor = RideExecutor(
        config_loader=lambda: SimpleNamespace(
            program_id=Pubkey.default(), rpc_url="https://rpc.invalid"
        ),
        record_ride_fn=record_ride,
        derive_ride_attestation_pda_fn=derive,
        account_reader=account_reader,
    )

    result = await executor.record_ride_attestation(
        rider_wallet=str(Pubkey.default()),
        identity=identity,
        completed_at=datetime(2026, 4, 17, 13, 0, tzinfo=timezone.utc),
        started_at=datetime(2026, 4, 17, 12, 0, tzinfo=timezone.utc),
        total_tss=84,
        total_distance_m=12000,
        total_vert_m=300,
        cal_earned=84_000_000_000,
        climbs_crossed=2,
    )

    assert result.reference == "tx-sig"
    assert result.tx_signature == "tx-sig"
    assert result.pda == str(Pubkey.default())
    assert result.attested_at == "2026-04-17T13:05:00+00:00"
    derive.assert_called_once()


@pytest.mark.asyncio
async def test_record_ride_attestation_rejects_mismatched_existing_pda() -> None:
    expected_pda = Pubkey.default()
    unexpected_pda = Pubkey.from_bytes(bytes([1]) * 32)
    record_ride = AsyncMock(return_value=f"exists:{unexpected_pda}")
    derive = MagicMock(return_value=(expected_pda, 255))
    executor = RideExecutor(
        config_loader=lambda: SimpleNamespace(program_id=Pubkey.default()),
        record_ride_fn=record_ride,
        derive_ride_attestation_pda_fn=derive,
    )

    with pytest.raises(ValueError, match="does not match expected PDA"):
        await executor.record_ride_attestation(
            rider_wallet=str(Pubkey.default()),
            identity=_identity(),
            completed_at=datetime(2026, 4, 17, 13, 0, tzinfo=timezone.utc),
            started_at=datetime(2026, 4, 17, 12, 0, tzinfo=timezone.utc),
            total_tss=84,
            total_distance_m=12000,
            total_vert_m=300,
            cal_earned=84_000_000_000,
            climbs_crossed=2,
        )


@pytest.mark.asyncio
async def test_credit_cal_and_climb_completion_load_chain_config() -> None:
    config = SimpleNamespace(
        program_id=Pubkey.default(), rpc_url="https://rpc.invalid"
    )
    credit_cal = AsyncMock(return_value="credit-sig")
    record_completion = AsyncMock(return_value="completion-sig")
    ride_hash = bytes.fromhex("cd" * 32)
    evidence_hash = bytes.fromhex("ef" * 32)
    rider = Pubkey.default()
    attestation, _ = derive_ride_attestation_pda(
        rider, ride_hash, config.program_id
    )
    cal_receipt, cal_bump = _derive_cal_mint_receipt_pda(
        attestation, rider, config.program_id
    )
    vault, _ = _derive_vault_pda(9, config.program_id)
    completion_receipt, completion_bump = _derive_climb_completion_receipt_pda(
        attestation, vault, config.program_id
    )

    async def read_account(_rpc_url: str, address: Pubkey):
        if address == cal_receipt:
            data = _cal_receipt_data(
                ride_attestation=attestation,
                rider=rider,
                amount=42,
                bump=cal_bump,
            )
        elif address == completion_receipt:
            data = _completion_receipt_v2_data(
                ride_attestation=attestation,
                vault=vault,
                cal_tributed=42,
                evidence_hash=evidence_hash,
                bump=completion_bump,
            )
        else:
            raise AssertionError(f"unexpected finalized account read: {address}")
        return SimpleNamespace(owner=config.program_id, data=data)

    executor = RideExecutor(
        config_loader=lambda: config,
        credit_cal_fn=credit_cal,
        record_climb_completion_fn=record_completion,
        account_reader=read_account,
    )

    credit_sig = await executor.credit_cal(
        rider_wallet=str(Pubkey.default()),
        ride_hash=ride_hash,
        amount=42,
    )
    completion_sig = await executor.record_climb_completion(
        rider_wallet=str(Pubkey.default()),
        ride_hash=ride_hash,
        vault_id=9,
        completion_time_s=123,
        cal_tribute=42,
        completion_evidence_version=2,
        completion_evidence_hash=evidence_hash,
    )

    assert credit_sig == "credit-sig"
    assert completion_sig == "completion-sig"
    assert credit_cal.await_args.kwargs["config"] is config
    assert credit_cal.await_args.kwargs["ride_hash"] == ride_hash
    assert record_completion.await_args.kwargs["config"] is config
    assert record_completion.await_args.kwargs["vault_id"] == 9
    assert record_completion.await_args.kwargs["completion_time_s"] == 123
    assert record_completion.await_args.kwargs["cal_tribute"] == 42
    assert record_completion.await_args.kwargs["completion_evidence_hash"] == evidence_hash


@pytest.mark.asyncio
async def test_existing_cal_receipt_placeholder_is_not_a_transaction_signature() -> None:
    program_id = Keypair().pubkey()
    rider = Keypair().pubkey()
    ride_hash = bytes.fromhex("cd" * 32)
    attestation, _ = derive_ride_attestation_pda(rider, ride_hash, program_id)
    expected_pda, bump = _derive_cal_mint_receipt_pda(
        attestation, rider, program_id
    )
    credit_cal = AsyncMock(return_value=f"exists:{expected_pda}")
    account_reader = AsyncMock(
        return_value=SimpleNamespace(
            owner=program_id,
            data=_cal_receipt_data(
                ride_attestation=attestation,
                rider=rider,
                amount=42,
                bump=bump,
            ),
        )
    )
    executor = RideExecutor(
        config_loader=lambda: SimpleNamespace(
            program_id=program_id, rpc_url="https://rpc.invalid"
        ),
        credit_cal_fn=credit_cal,
        account_reader=account_reader,
    )

    execution = await executor.credit_cal_receipt(
        rider_wallet=str(rider),
        ride_hash=ride_hash,
        amount=42,
        expected_pda=str(expected_pda),
    )

    assert execution.reference == f"exists:{expected_pda}"
    assert execution.pda == str(expected_pda)
    assert execution.tx_signature is None


@pytest.mark.asyncio
async def test_existing_attestation_with_wrong_frozen_field_is_rejected() -> None:
    program_id = Keypair().pubkey()
    rider = Keypair().pubkey()
    identity = _identity()
    pda, bump = derive_ride_attestation_pda(rider, identity.ride_hash, program_id)
    account_reader = AsyncMock(
        return_value=SimpleNamespace(
            owner=program_id,
            data=_ride_attestation_data(
                rider=rider,
                identity=identity,
                completed_at=1_776_430_800,
                started_at=1_776_427_200,
                total_tss=84,
                total_distance_m=12000,
                total_vert_m=300,
                cal_earned=84_000_000_000,
                climbs_crossed=2,
                attester=Keypair().pubkey(),
                bump=bump,
                parser_version=identity.parser_version + 1,
            ),
        )
    )
    executor = RideExecutor(
        config_loader=lambda: SimpleNamespace(
            program_id=program_id, rpc_url="https://rpc.invalid"
        ),
        record_ride_fn=AsyncMock(return_value=f"exists:{pda}"),
        account_reader=account_reader,
    )

    with pytest.raises(ValueError, match="parser_version"):
        await executor.record_ride_attestation(
            rider_wallet=str(rider),
            identity=identity,
            completed_at=datetime(2026, 4, 17, 13, 0, tzinfo=timezone.utc),
            started_at=datetime(2026, 4, 17, 12, 0, tzinfo=timezone.utc),
            total_tss=84,
            total_distance_m=12000,
            total_vert_m=300,
            cal_earned=84_000_000_000,
            climbs_crossed=2,
            expected_pda=str(pda),
        )


@pytest.mark.asyncio
async def test_existing_cal_receipt_with_wrong_amount_is_rejected() -> None:
    program_id = Keypair().pubkey()
    rider = Keypair().pubkey()
    ride_hash = bytes.fromhex("cd" * 32)
    attestation, _ = derive_ride_attestation_pda(rider, ride_hash, program_id)
    receipt, bump = _derive_cal_mint_receipt_pda(attestation, rider, program_id)
    executor = RideExecutor(
        config_loader=lambda: SimpleNamespace(
            program_id=program_id, rpc_url="https://rpc.invalid"
        ),
        credit_cal_fn=AsyncMock(return_value=f"exists:{receipt}"),
        account_reader=AsyncMock(
            return_value=SimpleNamespace(
                owner=program_id,
                data=_cal_receipt_data(
                    ride_attestation=attestation,
                    rider=rider,
                    amount=41,
                    bump=bump,
                ),
            )
        ),
    )

    with pytest.raises(ValueError, match="amount"):
        await executor.credit_cal_receipt(
            rider_wallet=str(rider),
            ride_hash=ride_hash,
            amount=42,
            expected_pda=str(receipt),
        )


@pytest.mark.asyncio
async def test_existing_completion_with_wrong_evidence_hash_is_rejected() -> None:
    program_id = Keypair().pubkey()
    rider = Keypair().pubkey()
    ride_hash = bytes.fromhex("cd" * 32)
    attestation, _ = derive_ride_attestation_pda(rider, ride_hash, program_id)
    vault, _ = _derive_vault_pda(9, program_id)
    receipt, bump = _derive_climb_completion_receipt_pda(
        attestation, vault, program_id
    )
    executor = RideExecutor(
        config_loader=lambda: SimpleNamespace(
            program_id=program_id, rpc_url="https://rpc.invalid"
        ),
        record_climb_completion_fn=AsyncMock(return_value=f"exists:{receipt}"),
        account_reader=AsyncMock(
            return_value=SimpleNamespace(
                owner=program_id,
                data=_completion_receipt_v2_data(
                    ride_attestation=attestation,
                    vault=vault,
                    cal_tributed=42,
                    evidence_hash=bytes.fromhex("aa" * 32),
                    bump=bump,
                ),
            )
        ),
    )

    with pytest.raises(ValueError, match="completion_evidence_hash"):
        await executor.record_climb_completion_receipt(
            rider_wallet=str(rider),
            ride_hash=ride_hash,
            vault_id=9,
            completion_time_s=123,
            cal_tribute=42,
            completion_evidence_version=2,
            completion_evidence_hash=bytes.fromhex("ef" * 32),
            expected_pda=str(receipt),
        )


@pytest.mark.asyncio
async def test_unreadable_existing_account_is_retryable_not_confirmed() -> None:
    program_id = Keypair().pubkey()
    rider = Keypair().pubkey()
    ride_hash = bytes.fromhex("cd" * 32)
    attestation, _ = derive_ride_attestation_pda(rider, ride_hash, program_id)
    receipt, _ = _derive_cal_mint_receipt_pda(attestation, rider, program_id)
    executor = RideExecutor(
        config_loader=lambda: SimpleNamespace(
            program_id=program_id, rpc_url="https://rpc.invalid"
        ),
        credit_cal_fn=AsyncMock(return_value=f"exists:{receipt}"),
        account_reader=AsyncMock(return_value=None),
    )

    with pytest.raises(RuntimeError, match="unavailable"):
        await executor.credit_cal_receipt(
            rider_wallet=str(rider),
            ride_hash=ride_hash,
            amount=42,
            expected_pda=str(receipt),
        )


@pytest.mark.asyncio
async def test_fresh_signature_without_finalized_account_remains_retryable() -> None:
    program_id = Keypair().pubkey()
    rider = Keypair().pubkey()
    ride_hash = bytes.fromhex("cd" * 32)
    account_reader = AsyncMock(return_value=None)
    executor = RideExecutor(
        config_loader=lambda: SimpleNamespace(
            program_id=program_id, rpc_url="https://rpc.invalid"
        ),
        credit_cal_fn=AsyncMock(return_value="confirmed-fork-signature"),
        account_reader=account_reader,
        finalization_attempts=2,
        finalization_poll_seconds=0,
    )

    with pytest.raises(RuntimeError, match="unavailable"):
        await executor.credit_cal_receipt(
            rider_wallet=str(rider),
            ride_hash=ride_hash,
            amount=42,
        )
    assert account_reader.await_count == 2
