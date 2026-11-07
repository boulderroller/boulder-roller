from __future__ import annotations

import hashlib
import struct
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from app.solana_direct import (
    DirectConfig,
    _derive_cal_mint_receipt_pda,
    _derive_climb_completion_receipt_pda,
    _derive_held_ride_release_pda,
    _derive_program_config_pda,
    _derive_ride_attestation_pda,
    _derive_ride_tribute_budget_pda,
    _derive_rider_soul_pda,
    _derive_vault_activation_pda,
    _derive_vault_completion_pda,
    _derive_vault_leaderboard_pda,
    _derive_vault_pda,
    make_authorize_held_ride_release_ix,
    make_credit_released_cal_ix,
    make_record_released_climb_completion_ix,
    send_authorize_held_ride_release,
    send_credit_released_cal,
    send_record_released_climb_completion,
)
from app.services.ride_chain_accounts import (
    decode_held_ride_release_authority,
    decode_released_cal_mint_receipt,
    decode_released_climb_completion_receipt,
)
from app.services.ride_chain_accounts import ChainAccountMismatchError
from app.services.threshold_release_executor import ThresholdReleaseExecutor
from app.services.vault_completion_evidence import (
    build_released_climb_completion_evidence_v3,
)


PROGRAM_ID = Pubkey.from_string("EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH")
RIDER = Pubkey.from_string("Ch8uwuNxXkQBTJfBNbCq57yhaKdADCTiLLHqzb7G9uXF")
PAYER = Keypair()
AUTHORITY = Keypair()
RIDE_HASH = hashlib.sha256(b"held-canonical-ride").digest()
THRESHOLD_AUTHORITY_ID = UUID("8cd95f97-26ad-4b82-a667-c09537f5b302")
THRESHOLD_COMMITMENT = hashlib.sha256(b"threshold-authority").digest()
RELEASE_PLAN_HASH = hashlib.sha256(b"release-plan").digest()
THRESHOLD_EFFECTIVE_AT = 1_777_363_200
THRESHOLD_W = 287
ECONOMIC_TSS = 94
CAL_EARNED = 94_000_000_000
CAL_TRIBUTE_BUDGET = 9_400_000_000
VAULT_ID = 42
COMPLETION_TIME_S = 611
CAL_TRIBUTE = 3_100_000_000


def _account_discriminator(name: str) -> bytes:
    return hashlib.sha256(f"account:{name}".encode()).digest()[:8]


def _config() -> DirectConfig:
    return DirectConfig(
        rpc_url="https://rpc.invalid",
        program_id=PROGRAM_ID,
        payer=PAYER,
        backend_authority=AUTHORITY,
    )


def _held_release_data(
    *,
    ride_attestation: Pubkey,
    release_bump: int,
    cal_earned: int = CAL_EARNED,
) -> bytes:
    return b"".join(
        (
            _account_discriminator("HeldRideReleaseAuthority"),
            bytes(ride_attestation),
            bytes(RIDER),
            THRESHOLD_AUTHORITY_ID.bytes,
            THRESHOLD_COMMITMENT,
            struct.pack(
                "<qHBIQQ",
                THRESHOLD_EFFECTIVE_AT,
                THRESHOLD_W,
                1,
                ECONOMIC_TSS,
                cal_earned,
                CAL_TRIBUTE_BUDGET,
            ),
            RELEASE_PLAN_HASH,
            struct.pack("<qQQ", THRESHOLD_EFFECTIVE_AT + 10, 55, 13),
            bytes(AUTHORITY.pubkey()),
            struct.pack("<B", release_bump),
        )
    )


def _released_cal_receipt_data(
    *,
    ride_attestation: Pubkey,
    release_authority: Pubkey,
    bump: int,
) -> bytes:
    return b"".join(
        (
            _account_discriminator("ReleasedCalMintReceipt"),
            bytes(ride_attestation),
            bytes(release_authority),
            bytes(RIDER),
            struct.pack("<QQB", CAL_EARNED, 13, bump),
        )
    )


def _released_completion_receipt_data(
    *,
    ride_attestation: Pubkey,
    release_authority: Pubkey,
    vault: Pubkey,
    evidence_hash: bytes,
    bump: int,
    credited_week: int = 13,
) -> bytes:
    return b"".join(
        (
            _account_discriminator("ReleasedClimbCompletionReceipt"),
            bytes(ride_attestation),
            bytes(release_authority),
            bytes(vault),
            struct.pack("<BQ", 3, CAL_TRIBUTE),
            evidence_hash,
            struct.pack("<QB", credited_week, bump),
        )
    )


def test_authorize_held_ride_release_instruction_matches_anchor_layout() -> None:
    ix = make_authorize_held_ride_release_ix(
        authority=AUTHORITY.pubkey(),
        rider=RIDER,
        ride_hash=RIDE_HASH,
        threshold_authority_id=THRESHOLD_AUTHORITY_ID.bytes,
        threshold_authority_commitment=THRESHOLD_COMMITMENT,
        threshold_effective_at=THRESHOLD_EFFECTIVE_AT,
        threshold_w=THRESHOLD_W,
        threshold_policy_version=1,
        economic_tss=ECONOMIC_TSS,
        cal_earned=CAL_EARNED,
        cal_tribute_budget=CAL_TRIBUTE_BUDGET,
        release_plan_hash=RELEASE_PLAN_HASH,
        program_id=PROGRAM_ID,
    )

    attestation, _ = _derive_ride_attestation_pda(RIDER, RIDE_HASH, PROGRAM_ID)
    release, _ = _derive_held_ride_release_pda(attestation, PROGRAM_ID)
    config, _ = _derive_program_config_pda(PROGRAM_ID)
    assert ix.data[:8] == hashlib.sha256(
        b"global:authorize_held_ride_release"
    ).digest()[:8]
    assert len(ix.data) == 119
    assert ix.data[8:24] == THRESHOLD_AUTHORITY_ID.bytes
    assert ix.data[24:56] == THRESHOLD_COMMITMENT
    assert struct.unpack_from("<qHBIQQ", ix.data, 56) == (
        THRESHOLD_EFFECTIVE_AT,
        THRESHOLD_W,
        1,
        ECONOMIC_TSS,
        CAL_EARNED,
        CAL_TRIBUTE_BUDGET,
    )
    assert ix.data[87:119] == RELEASE_PLAN_HASH
    assert [meta.pubkey for meta in ix.accounts] == [
        attestation,
        release,
        RIDER,
        config,
        AUTHORITY.pubkey(),
        Pubkey.default(),
    ]
    assert ix.accounts[4].is_signer is True
    assert ix.accounts[4].is_writable is True


def test_credit_released_cal_instruction_has_no_amount_and_exact_accounts() -> None:
    config = _config()
    ix = make_credit_released_cal_ix(
        authority=AUTHORITY.pubkey(),
        payer=PAYER.pubkey(),
        rider=RIDER,
        ride_hash=RIDE_HASH,
        config=config,
    )

    attestation, _ = _derive_ride_attestation_pda(RIDER, RIDE_HASH, PROGRAM_ID)
    release, _ = _derive_held_ride_release_pda(attestation, PROGRAM_ID)
    receipt, _ = _derive_cal_mint_receipt_pda(attestation, RIDER, PROGRAM_ID)
    rider_soul, _ = _derive_rider_soul_pda(RIDER, PROGRAM_ID)
    program_config, _ = _derive_program_config_pda(PROGRAM_ID)
    assert ix.data == hashlib.sha256(b"global:credit_released_cal").digest()[:8]
    assert [meta.pubkey for meta in ix.accounts[:7]] == [
        attestation,
        release,
        receipt,
        rider_soul,
        RIDER,
        program_config,
        AUTHORITY.pubkey(),
    ]
    assert ix.accounts[10].pubkey == PAYER.pubkey()
    assert len(ix.accounts) == 13


def test_record_released_completion_instruction_binds_release_and_budget() -> None:
    attestation, _ = _derive_ride_attestation_pda(RIDER, RIDE_HASH, PROGRAM_ID)
    release, _ = _derive_held_ride_release_pda(attestation, PROGRAM_ID)
    vault, _ = _derive_vault_pda(VAULT_ID, PROGRAM_ID)
    evidence_hash = build_released_climb_completion_evidence_v3(
        release_authority=release,
        ride_attestation=attestation,
        vault=vault,
        completion_time_s=COMPLETION_TIME_S,
        cal_tribute=CAL_TRIBUTE,
    )
    ix = make_record_released_climb_completion_ix(
        authority=AUTHORITY.pubkey(),
        rider=RIDER,
        ride_hash=RIDE_HASH,
        vault_id=VAULT_ID,
        completion_time_s=COMPLETION_TIME_S,
        cal_tribute=CAL_TRIBUTE,
        completion_evidence_hash=evidence_hash,
        program_id=PROGRAM_ID,
    )

    receipt, _ = _derive_climb_completion_receipt_pda(attestation, vault, PROGRAM_ID)
    completion, _ = _derive_vault_completion_pda(RIDER, VAULT_ID, PROGRAM_ID)
    leaderboard, _ = _derive_vault_leaderboard_pda(VAULT_ID, PROGRAM_ID)
    activation, _ = _derive_vault_activation_pda(VAULT_ID, PROGRAM_ID)
    program_config, _ = _derive_program_config_pda(PROGRAM_ID)
    budget, _ = _derive_ride_tribute_budget_pda(attestation, PROGRAM_ID)
    assert ix.data[:8] == hashlib.sha256(
        b"global:record_released_climb_completion"
    ).digest()[:8]
    assert struct.unpack_from("<IQ", ix.data, 8) == (COMPLETION_TIME_S, CAL_TRIBUTE)
    assert ix.data[20:52] == evidence_hash
    assert [meta.pubkey for meta in ix.accounts] == [
        attestation,
        release,
        receipt,
        vault,
        completion,
        leaderboard,
        activation,
        RIDER,
        program_config,
        AUTHORITY.pubkey(),
        Pubkey.default(),
        budget,
    ]


def test_release_account_decoders_match_stable_discriminators_and_layouts() -> None:
    attestation, _ = _derive_ride_attestation_pda(RIDER, RIDE_HASH, PROGRAM_ID)
    release, release_bump = _derive_held_ride_release_pda(attestation, PROGRAM_ID)
    vault, _ = _derive_vault_pda(VAULT_ID, PROGRAM_ID)
    cal_receipt, cal_bump = _derive_cal_mint_receipt_pda(attestation, RIDER, PROGRAM_ID)
    del cal_receipt
    completion_receipt, completion_bump = _derive_climb_completion_receipt_pda(
        attestation, vault, PROGRAM_ID
    )
    del completion_receipt
    evidence_hash = build_released_climb_completion_evidence_v3(
        release_authority=release,
        ride_attestation=attestation,
        vault=vault,
        completion_time_s=COMPLETION_TIME_S,
        cal_tribute=CAL_TRIBUTE,
    )

    authority = decode_held_ride_release_authority(
        _held_release_data(ride_attestation=attestation, release_bump=release_bump)
    )
    cal = decode_released_cal_mint_receipt(
        _released_cal_receipt_data(
            ride_attestation=attestation,
            release_authority=release,
            bump=cal_bump,
        )
    )
    completion = decode_released_climb_completion_receipt(
        _released_completion_receipt_data(
            ride_attestation=attestation,
            release_authority=release,
            vault=vault,
            evidence_hash=evidence_hash,
            bump=completion_bump,
        )
    )
    assert authority.threshold_authority_id == THRESHOLD_AUTHORITY_ID.bytes
    assert authority.cal_earned == CAL_EARNED
    assert authority.release_settlement_week == 13
    assert cal.release_authority == release
    assert cal.release_settlement_week == 13
    assert completion.evidence_version == 3
    assert completion.credited_settlement_week == 13


def test_executor_exposes_stable_planner_pda_and_evidence_apis() -> None:
    executor = ThresholdReleaseExecutor(
        config_loader=lambda: SimpleNamespace(program_id=PROGRAM_ID, rpc_url="rpc")
    )
    release = executor.derive_held_ride_release_pda(
        rider_wallet=str(RIDER),
        ride_hash=RIDE_HASH,
    )
    assert release == executor.derive_release_authority_pda(
        rider_wallet=str(RIDER),
        ride_hash=RIDE_HASH,
    )
    attestation, _ = _derive_ride_attestation_pda(RIDER, RIDE_HASH, PROGRAM_ID)
    cal_receipt, _ = _derive_cal_mint_receipt_pda(
        attestation, RIDER, PROGRAM_ID
    )
    assert executor.derive_cal_receipt_pda(
        rider_wallet=str(RIDER), ride_hash=RIDE_HASH
    ) == str(cal_receipt)
    evidence_hash = executor.build_released_completion_evidence_v3(
        rider_wallet=str(RIDER),
        ride_hash=RIDE_HASH,
        vault_id=VAULT_ID,
        completion_time_s=COMPLETION_TIME_S,
        cal_tribute=CAL_TRIBUTE,
        expected_release_authority_pda=release,
    )
    vault, _ = _derive_vault_pda(VAULT_ID, PROGRAM_ID)
    assert evidence_hash == build_released_climb_completion_evidence_v3(
        release_authority=release,
        ride_attestation=attestation,
        vault=vault,
        completion_time_s=COMPLETION_TIME_S,
        cal_tribute=CAL_TRIBUTE,
    )
    with pytest.raises(ValueError, match="release PDA"):
        executor.build_released_completion_evidence_v3(
            rider_wallet=str(RIDER),
            ride_hash=RIDE_HASH,
            vault_id=VAULT_ID,
            completion_time_s=COMPLETION_TIME_S,
            cal_tribute=CAL_TRIBUTE,
            expected_release_authority_pda=str(Pubkey.default()),
        )


@pytest.mark.asyncio
async def test_direct_release_senders_submit_stable_instructions() -> None:
    config = _config()
    attestation, _ = _derive_ride_attestation_pda(RIDER, RIDE_HASH, PROGRAM_ID)
    release, _ = _derive_held_ride_release_pda(attestation, PROGRAM_ID)
    vault, _ = _derive_vault_pda(VAULT_ID, PROGRAM_ID)
    evidence_hash = build_released_climb_completion_evidence_v3(
        release_authority=release,
        ride_attestation=attestation,
        vault=vault,
        completion_time_s=COMPLETION_TIME_S,
        cal_tribute=CAL_TRIBUTE,
    )
    submit = AsyncMock(
        return_value=SimpleNamespace(failed=False, signature="release-tx")
    )
    with patch("app.solana_direct._account_exists", new=AsyncMock(return_value=False)):
        with patch("app.services.solana_submit.submit_and_confirm", new=submit):
            assert await send_authorize_held_ride_release(
                config=config,
                rider_wallet=str(RIDER),
                ride_hash=RIDE_HASH,
                threshold_authority_id=THRESHOLD_AUTHORITY_ID.bytes,
                threshold_authority_commitment=THRESHOLD_COMMITMENT,
                threshold_effective_at=THRESHOLD_EFFECTIVE_AT,
                threshold_w=THRESHOLD_W,
                threshold_policy_version=1,
                economic_tss=ECONOMIC_TSS,
                cal_earned=CAL_EARNED,
                cal_tribute_budget=CAL_TRIBUTE_BUDGET,
                release_plan_hash=RELEASE_PLAN_HASH,
            ) == "release-tx"
    assert submit.await_args.kwargs["tx_type"] == "authorize_held_ride_release"

    submit.reset_mock()
    with patch(
        "app.solana_direct._account_exists",
        new=AsyncMock(side_effect=[False, False]),
    ):
        with patch("app.services.solana_submit.submit_and_confirm", new=submit):
            assert await send_credit_released_cal(
                config=config,
                rider_wallet=str(RIDER),
                ride_hash=RIDE_HASH,
            ) == "release-tx"
    instructions = submit.await_args.kwargs["instructions"]
    assert len(instructions) == 2
    assert instructions[-1].data == hashlib.sha256(
        b"global:credit_released_cal"
    ).digest()[:8]

    submit.reset_mock()
    with patch("app.solana_direct._account_exists", new=AsyncMock(return_value=False)):
        with patch("app.services.solana_submit.submit_and_confirm", new=submit):
            assert await send_record_released_climb_completion(
                config=config,
                rider_wallet=str(RIDER),
                ride_hash=RIDE_HASH,
                vault_id=VAULT_ID,
                completion_time_s=COMPLETION_TIME_S,
                cal_tribute=CAL_TRIBUTE,
                completion_evidence_version=3,
                completion_evidence_hash=evidence_hash,
            ) == "release-tx"
    assert submit.await_args.kwargs["tx_type"] == (
        "record_released_climb_completion"
    )


@pytest.mark.asyncio
async def test_executor_authorizes_and_validates_release_authority() -> None:
    attestation, _ = _derive_ride_attestation_pda(RIDER, RIDE_HASH, PROGRAM_ID)
    release, release_bump = _derive_held_ride_release_pda(attestation, PROGRAM_ID)
    sender = AsyncMock(return_value=f"exists:{release}")
    reader = AsyncMock(
        return_value=SimpleNamespace(
            owner=PROGRAM_ID,
            data=_held_release_data(
                ride_attestation=attestation,
                release_bump=release_bump,
            ),
        )
    )
    executor = ThresholdReleaseExecutor(
        config_loader=lambda: SimpleNamespace(program_id=PROGRAM_ID, rpc_url="rpc"),
        authorize_held_ride_release_fn=sender,
        account_reader=reader,
    )

    result = await executor.authorize_held_ride_release_receipt(
        rider_wallet=str(RIDER),
        ride_hash=RIDE_HASH,
        reward_ftp_authority_id=THRESHOLD_AUTHORITY_ID,
        reward_ftp_authority_evidence_hash=THRESHOLD_COMMITMENT,
        reward_ftp_policy_version="reward_ftp_policy_2026_08_24_threshold_v1",
        reward_ftp_w=THRESHOLD_W,
        admitted_at=datetime(2026, 4, 20, tzinfo=timezone.utc),
        established_at=datetime.fromtimestamp(THRESHOLD_EFFECTIVE_AT, timezone.utc),
        total_tss=ECONOMIC_TSS,
        exact_cal_base_units=CAL_EARNED,
        exact_tribute_budget_base_units=CAL_TRIBUTE_BUDGET,
        release_plan_evidence_hash=RELEASE_PLAN_HASH,
        expected_pda=str(release),
    )

    assert result.reference == f"exists:{release}"
    assert result.confirmed_at == datetime.fromtimestamp(
        THRESHOLD_EFFECTIVE_AT + 10, timezone.utc
    ).isoformat()
    kwargs = sender.await_args.kwargs
    assert kwargs["threshold_authority_id"] == THRESHOLD_AUTHORITY_ID.bytes
    assert kwargs["threshold_policy_version"] == 1
    assert kwargs["threshold_effective_at"] == THRESHOLD_EFFECTIVE_AT
    assert kwargs["economic_tss"] == ECONOMIC_TSS


@pytest.mark.asyncio
async def test_executor_credit_released_cal_validates_authority_before_mint() -> None:
    attestation, _ = _derive_ride_attestation_pda(RIDER, RIDE_HASH, PROGRAM_ID)
    release, release_bump = _derive_held_ride_release_pda(attestation, PROGRAM_ID)
    receipt, receipt_bump = _derive_cal_mint_receipt_pda(attestation, RIDER, PROGRAM_ID)
    sender = AsyncMock(return_value=f"exists:{receipt}")

    async def reader(_rpc_url: str, address: Pubkey):
        if address == release:
            data = _held_release_data(
                ride_attestation=attestation,
                release_bump=release_bump,
            )
        elif address == receipt:
            data = _released_cal_receipt_data(
                ride_attestation=attestation,
                release_authority=release,
                bump=receipt_bump,
            )
        else:
            raise AssertionError(f"unexpected read: {address}")
        return SimpleNamespace(owner=PROGRAM_ID, data=data)

    executor = ThresholdReleaseExecutor(
        config_loader=lambda: SimpleNamespace(program_id=PROGRAM_ID, rpc_url="rpc"),
        credit_released_cal_fn=sender,
        account_reader=reader,
    )
    result = await executor.credit_released_cal_receipt(
        rider_wallet=str(RIDER),
        ride_hash=RIDE_HASH,
        amount=CAL_EARNED,
        expected_release_authority_pda=str(release),
        expected_pda=str(receipt),
    )

    assert result.reference == f"exists:{receipt}"
    assert result.confirmed_at == datetime.fromtimestamp(
        THRESHOLD_EFFECTIVE_AT + 10, timezone.utc
    ).isoformat()
    sender.assert_awaited_once_with(
        config=executor._config_loader(),
        rider_wallet=str(RIDER),
        ride_hash=RIDE_HASH,
    )


@pytest.mark.asyncio
async def test_executor_rejects_wrong_release_amount_before_mint() -> None:
    attestation, _ = _derive_ride_attestation_pda(RIDER, RIDE_HASH, PROGRAM_ID)
    release, release_bump = _derive_held_ride_release_pda(attestation, PROGRAM_ID)
    receipt, _ = _derive_cal_mint_receipt_pda(attestation, RIDER, PROGRAM_ID)
    sender = AsyncMock(return_value="should-not-send")
    reader = AsyncMock(
        return_value=SimpleNamespace(
            owner=PROGRAM_ID,
            data=_held_release_data(
                ride_attestation=attestation,
                release_bump=release_bump,
                cal_earned=CAL_EARNED + 1,
            ),
        )
    )
    executor = ThresholdReleaseExecutor(
        config_loader=lambda: SimpleNamespace(program_id=PROGRAM_ID, rpc_url="rpc"),
        credit_released_cal_fn=sender,
        account_reader=reader,
    )

    with pytest.raises(ValueError, match="cal_earned"):
        await executor.credit_released_cal_receipt(
            rider_wallet=str(RIDER),
            ride_hash=RIDE_HASH,
            amount=CAL_EARNED,
            expected_release_authority_pda=str(release),
            expected_pda=str(receipt),
        )
    sender.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("vault_week", [12, 13])
async def test_executor_records_v3_release_bound_completion(vault_week: int) -> None:
    attestation, _ = _derive_ride_attestation_pda(RIDER, RIDE_HASH, PROGRAM_ID)
    release, _ = _derive_held_ride_release_pda(attestation, PROGRAM_ID)
    vault, _ = _derive_vault_pda(VAULT_ID, PROGRAM_ID)
    receipt, receipt_bump = _derive_climb_completion_receipt_pda(
        attestation, vault, PROGRAM_ID
    )
    evidence_hash = build_released_climb_completion_evidence_v3(
        release_authority=release,
        ride_attestation=attestation,
        vault=vault,
        completion_time_s=COMPLETION_TIME_S,
        cal_tribute=CAL_TRIBUTE,
    )
    sender = AsyncMock(return_value=f"exists:{receipt}")
    async def reader(_rpc_url: str, address: Pubkey):
        if address == release:
            data = _held_release_data(
                ride_attestation=attestation,
                release_bump=_derive_held_ride_release_pda(
                    attestation, PROGRAM_ID
                )[1],
            )
        elif address == receipt:
            data = _released_completion_receipt_data(
                ride_attestation=attestation,
                release_authority=release,
                vault=vault,
                evidence_hash=evidence_hash,
                bump=receipt_bump,
            )
        else:
            raise AssertionError(f"unexpected read: {address}")
        return SimpleNamespace(owner=PROGRAM_ID, data=data)
    executor = ThresholdReleaseExecutor(
        config_loader=lambda: SimpleNamespace(program_id=PROGRAM_ID, rpc_url="rpc"),
        record_released_climb_completion_fn=sender,
        account_reader=reader,
        vault_account_reader=AsyncMock(
            return_value={"open_settlement_week": vault_week}
        ),
    )

    result = await executor.record_released_climb_completion_receipt(
        rider_wallet=str(RIDER),
        ride_hash=RIDE_HASH,
        vault_id=VAULT_ID,
        completion_time_s=COMPLETION_TIME_S,
        cal_tribute=CAL_TRIBUTE,
        completion_evidence_version=3,
        completion_evidence_hash=evidence_hash,
        expected_release_authority_pda=str(release),
        expected_pda=str(receipt),
    )
    assert result.reference == f"exists:{receipt}"
    assert result.confirmed_at == datetime.fromtimestamp(
        THRESHOLD_EFFECTIVE_AT + 10, timezone.utc
    ).isoformat()
    sender.assert_awaited_once()


@pytest.mark.asyncio
async def test_executor_refuses_release_completion_after_frozen_week() -> None:
    attestation, _ = _derive_ride_attestation_pda(RIDER, RIDE_HASH, PROGRAM_ID)
    release, release_bump = _derive_held_ride_release_pda(attestation, PROGRAM_ID)
    vault, _ = _derive_vault_pda(VAULT_ID, PROGRAM_ID)
    receipt, _ = _derive_climb_completion_receipt_pda(
        attestation, vault, PROGRAM_ID
    )
    evidence_hash = build_released_climb_completion_evidence_v3(
        release_authority=release,
        ride_attestation=attestation,
        vault=vault,
        completion_time_s=COMPLETION_TIME_S,
        cal_tribute=CAL_TRIBUTE,
    )
    sender = AsyncMock(return_value="must-not-send")
    reader = AsyncMock(
        return_value=SimpleNamespace(
            owner=PROGRAM_ID,
            data=_held_release_data(
                ride_attestation=attestation,
                release_bump=release_bump,
            ),
        )
    )
    executor = ThresholdReleaseExecutor(
        config_loader=lambda: SimpleNamespace(program_id=PROGRAM_ID, rpc_url="rpc"),
        record_released_climb_completion_fn=sender,
        account_reader=reader,
        vault_account_reader=AsyncMock(
            return_value={"open_settlement_week": 14}
        ),
    )

    with pytest.raises(ChainAccountMismatchError):
        await executor.record_released_climb_completion_receipt(
            rider_wallet=str(RIDER),
            ride_hash=RIDE_HASH,
            vault_id=VAULT_ID,
            completion_time_s=COMPLETION_TIME_S,
            cal_tribute=CAL_TRIBUTE,
            completion_evidence_version=3,
            completion_evidence_hash=evidence_hash,
            expected_release_authority_pda=str(release),
            expected_pda=str(receipt),
        )
    sender.assert_not_awaited()


@pytest.mark.asyncio
async def test_executor_rejects_non_v3_or_unbound_released_completion() -> None:
    sender = AsyncMock(return_value="should-not-send")
    executor = ThresholdReleaseExecutor(
        config_loader=lambda: SimpleNamespace(program_id=PROGRAM_ID, rpc_url="rpc"),
        record_released_climb_completion_fn=sender,
    )
    release = executor.derive_release_authority_pda(
        rider_wallet=str(RIDER), ride_hash=RIDE_HASH
    )
    receipt = executor.derive_completion_receipt_pda(
        rider_wallet=str(RIDER), ride_hash=RIDE_HASH, vault_id=VAULT_ID
    )
    with pytest.raises(ValueError, match="V3"):
        await executor.record_released_climb_completion_receipt(
            rider_wallet=str(RIDER),
            ride_hash=RIDE_HASH,
            vault_id=VAULT_ID,
            completion_time_s=COMPLETION_TIME_S,
            cal_tribute=CAL_TRIBUTE,
            completion_evidence_version=2,
            completion_evidence_hash=b"x" * 32,
            expected_release_authority_pda=release,
            expected_pda=receipt,
        )
    with pytest.raises(ValueError, match="does not match"):
        await executor.record_released_climb_completion_receipt(
            rider_wallet=str(RIDER),
            ride_hash=RIDE_HASH,
            vault_id=VAULT_ID,
            completion_time_s=COMPLETION_TIME_S,
            cal_tribute=CAL_TRIBUTE,
            completion_evidence_version=3,
            completion_evidence_hash=b"x" * 32,
            expected_release_authority_pda=release,
            expected_pda=receipt,
        )
    sender.assert_not_awaited()
