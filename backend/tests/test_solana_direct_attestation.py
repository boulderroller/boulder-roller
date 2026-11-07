import asyncio
import hashlib
import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey

import app.solana_direct as solana_direct
from app.solana_direct import (
    DirectConfig,
    _derive_cal_mint_receipt_pda,
    _derive_climb_completion_receipt_pda,
    _derive_program_config_pda,
    _derive_ride_attestation_pda,
    _derive_ride_tribute_budget_pda,
    _derive_rider_soul_pda,
    _derive_vault_activation_pda,
    _derive_vault_completion_pda,
    _derive_vault_leaderboard_pda,
    _derive_vault_pda,
    make_credit_cal_ix,
    make_record_climb_completion_v2_ix,
    make_record_ride_ix,
    send_credit_cal,
    send_record_climb_completion,
    send_record_ride,
)
from app.services.vault_completion_evidence import (
    build_climb_completion_evidence_v2,
    build_vault_completion_evidence_hash,
)


PROGRAM_ID = Pubkey.from_string("EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH")
RIDER = Pubkey.from_string("Ch8uwuNxXkQBTJfBNbCq57yhaKdADCTiLLHqzb7G9uXF")
PAYER = Keypair()
BACKEND_AUTHORITY = Keypair()
VAULT_ID = 42
RIDE_HASH = hashlib.sha256(b"canonical-ride").digest()
ATTESTATION_COMMITMENT = hashlib.sha256(b"attestation-commitment").digest()
COMPLETION_EVIDENCE_HASH = hashlib.sha256(b"completion-evidence").digest()


def make_config() -> DirectConfig:
    return DirectConfig(
        rpc_url="https://api.devnet.solana.com",
        program_id=PROGRAM_ID,
        payer=PAYER,
        backend_authority=BACKEND_AUTHORITY,
    )


def test_raw_admin_cal_mint_builders_absent():
    assert not hasattr(solana_direct, "make_admin_credit_cal_ix")
    assert not hasattr(solana_direct, "send_admin_credit_cal")


def test_record_ride_discriminator_and_layout():
    ix = make_record_ride_ix(
        authority=BACKEND_AUTHORITY.pubkey(),
        payer=PAYER.pubkey(),
        rider=RIDER,
        ride_hash=RIDE_HASH,
        attestation_commitment=ATTESTATION_COMMITMENT,
        parser_version=1,
        source_kind=1,
        completed_at=1_713_456_789,
        started_at=1_713_453_600,
        total_tss=123,
        total_distance_m=45678,
        total_vert_m=789,
        cal_earned=123_000_000_000,
        climbs_crossed=3,
        program_id=PROGRAM_ID,
    )

    expected_disc = hashlib.sha256(b"global:record_ride").digest()[:8]
    assert bytes(ix.data[:8]) == expected_disc
    assert len(ix.data) == 115
    assert ix.data[8:40] == RIDE_HASH
    assert ix.data[40:72] == ATTESTATION_COMMITMENT
    assert struct.unpack_from("<I", ix.data, 72)[0] == 1
    assert struct.unpack_from("<B", ix.data, 76)[0] == 1
    assert struct.unpack_from("<q", ix.data, 77)[0] == 1_713_456_789
    assert struct.unpack_from("<q", ix.data, 85)[0] == 1_713_453_600
    assert struct.unpack_from("<I", ix.data, 93)[0] == 123
    assert struct.unpack_from("<I", ix.data, 97)[0] == 45678
    assert struct.unpack_from("<I", ix.data, 101)[0] == 789
    assert struct.unpack_from("<Q", ix.data, 105)[0] == 123_000_000_000
    assert struct.unpack_from("<H", ix.data, 113)[0] == 3

    ride_attestation_pda, _ = _derive_ride_attestation_pda(RIDER, RIDE_HASH, PROGRAM_ID)
    rider_soul_pda, _ = _derive_rider_soul_pda(RIDER, PROGRAM_ID)
    program_config_pda, _ = _derive_program_config_pda(PROGRAM_ID)

    assert len(ix.accounts) == 7
    assert ix.accounts[0].pubkey == ride_attestation_pda
    assert ix.accounts[1].pubkey == rider_soul_pda
    assert ix.accounts[2].pubkey == RIDER
    assert ix.accounts[3].pubkey == program_config_pda
    assert ix.accounts[4].pubkey == BACKEND_AUTHORITY.pubkey()
    assert ix.accounts[5].pubkey == PAYER.pubkey()
    assert ix.accounts[4].is_signer is True
    assert ix.accounts[5].is_signer is True


def test_credit_cal_account_order():
    config = make_config()
    ix = make_credit_cal_ix(
        authority=BACKEND_AUTHORITY.pubkey(),
        payer=PAYER.pubkey(),
        rider=RIDER,
        ride_hash=RIDE_HASH,
        amount=321_000_000_000,
        config=config,
    )

    ride_attestation_pda, _ = _derive_ride_attestation_pda(RIDER, RIDE_HASH, PROGRAM_ID)
    receipt_pda, _ = _derive_cal_mint_receipt_pda(ride_attestation_pda, RIDER, PROGRAM_ID)
    program_config_pda, _ = _derive_program_config_pda(PROGRAM_ID)

    expected_disc = hashlib.sha256(b"global:credit_cal").digest()[:8]
    assert bytes(ix.data[:8]) == expected_disc
    assert struct.unpack_from("<Q", ix.data, 8)[0] == 321_000_000_000
    assert len(ix.accounts) == 11
    assert ix.accounts[0].pubkey == ride_attestation_pda
    assert ix.accounts[1].pubkey == receipt_pda
    assert ix.accounts[2].pubkey == RIDER
    assert ix.accounts[3].pubkey == program_config_pda
    assert ix.accounts[4].pubkey == BACKEND_AUTHORITY.pubkey()
    assert ix.accounts[8].pubkey == PAYER.pubkey()


def test_record_climb_completion_v2_account_order():
    ix = make_record_climb_completion_v2_ix(
        authority=BACKEND_AUTHORITY.pubkey(),
        rider=RIDER,
        ride_hash=RIDE_HASH,
        vault_id=VAULT_ID,
        completion_time_s=600,
        cal_tribute=123_000_000_000,
        completion_evidence_hash=COMPLETION_EVIDENCE_HASH,
        program_id=PROGRAM_ID,
    )

    ride_attestation_pda, _ = _derive_ride_attestation_pda(RIDER, RIDE_HASH, PROGRAM_ID)
    ride_tribute_budget_pda, _ = _derive_ride_tribute_budget_pda(
        ride_attestation_pda,
        PROGRAM_ID,
    )
    vault_pda, _ = _derive_vault_pda(VAULT_ID, PROGRAM_ID)
    receipt_pda, _ = _derive_climb_completion_receipt_pda(ride_attestation_pda, vault_pda, PROGRAM_ID)
    completion_pda, _ = _derive_vault_completion_pda(RIDER, VAULT_ID, PROGRAM_ID)
    leaderboard_pda, _ = _derive_vault_leaderboard_pda(VAULT_ID, PROGRAM_ID)
    activation_pda, _ = _derive_vault_activation_pda(VAULT_ID, PROGRAM_ID)
    program_config_pda, _ = _derive_program_config_pda(PROGRAM_ID)

    expected_disc = hashlib.sha256(b"global:record_climb_completion_v2").digest()[:8]
    assert bytes(ix.data[:8]) == expected_disc
    assert len(ix.data) == 52
    assert struct.unpack_from("<I", ix.data, 8)[0] == 600
    assert struct.unpack_from("<Q", ix.data, 12)[0] == 123_000_000_000
    assert bytes(ix.data[20:52]) == COMPLETION_EVIDENCE_HASH
    assert len(ix.accounts) == 11
    assert ix.accounts[0].pubkey == ride_attestation_pda
    assert ix.accounts[1].pubkey == receipt_pda
    assert ix.accounts[2].pubkey == vault_pda
    assert ix.accounts[3].pubkey == completion_pda
    assert ix.accounts[4].pubkey == leaderboard_pda
    assert ix.accounts[5].pubkey == activation_pda
    assert ix.accounts[6].pubkey == RIDER
    assert ix.accounts[7].pubkey == program_config_pda
    assert ix.accounts[8].pubkey == BACKEND_AUTHORITY.pubkey()
    assert ix.accounts[8].is_writable is True
    assert ix.accounts[10].pubkey == ride_tribute_budget_pda
    assert ix.accounts[10].is_writable is True


def test_vault_completion_evidence_hash_matches_frozen_byte_layout():
    evidence_hash = build_vault_completion_evidence_hash(
        wallet=RIDER,
        vault_id=VAULT_ID,
        activity_id="ride-42",
        completed_at=1_713_456_789,
        time_s=600,
        signature_hash=hashlib.sha256(b"normalized-signature").digest(),
    )
    assert len(evidence_hash) == 32
    assert evidence_hash == build_vault_completion_evidence_hash(
        wallet=str(RIDER),
        vault_id=VAULT_ID,
        activity_id="ride-42",
        completed_at=1_713_456_789,
        time_s=600,
        signature_hash=hashlib.sha256(b"normalized-signature").digest(),
    )


@pytest.mark.asyncio
async def test_send_record_ride_short_circuits_existing_attestation():
    config = make_config()
    ride_attestation_pda, _ = _derive_ride_attestation_pda(RIDER, RIDE_HASH, PROGRAM_ID)

    with patch("app.solana_direct._account_exists", new=AsyncMock(return_value=True)):
        result = await send_record_ride(
            config=config,
            rider_wallet=str(RIDER),
            ride_hash=RIDE_HASH,
            attestation_commitment=ATTESTATION_COMMITMENT,
            parser_version=1,
            source_kind=1,
            completed_at=1_713_456_789,
            started_at=1_713_453_600,
            total_tss=123,
            total_distance_m=45678,
            total_vert_m=789,
            cal_earned=123_000_000_000,
            climbs_crossed=2,
        )

    assert result == f"exists:{ride_attestation_pda}"


@pytest.mark.asyncio
async def test_send_record_ride_uses_backend_authority_and_payer():
    config = make_config()
    submit_mock = AsyncMock(return_value=SimpleNamespace(failed=False, signature="ride-sig"))

    with patch("app.solana_direct._account_exists", new=AsyncMock(return_value=False)), patch(
        "app.services.solana_submit.submit_and_confirm",
        submit_mock,
    ):
        signature = await send_record_ride(
            config=config,
            rider_wallet=str(RIDER),
            ride_hash=RIDE_HASH,
            attestation_commitment=ATTESTATION_COMMITMENT,
            parser_version=1,
            source_kind=1,
            completed_at=1_713_456_789,
            started_at=1_713_453_600,
            total_tss=123,
            total_distance_m=45678,
            total_vert_m=789,
            cal_earned=123_000_000_000,
            climbs_crossed=2,
        )

    assert signature == "ride-sig"
    signers = submit_mock.await_args.kwargs["signers"]
    signer_pubkeys = {str(s.pubkey()) for s in signers}
    assert str(PAYER.pubkey()) in signer_pubkeys
    assert str(BACKEND_AUTHORITY.pubkey()) in signer_pubkeys
    assert submit_mock.await_args.kwargs["commitment"] == "finalized"


@pytest.mark.asyncio
async def test_send_credit_cal_waits_for_finalized_submission():
    config = make_config()
    submit_mock = AsyncMock(return_value=SimpleNamespace(failed=False, signature="cal-sig"))

    with patch(
        "app.solana_direct._account_exists",
        new=AsyncMock(side_effect=[False, True]),
    ), patch(
        "app.services.solana_submit.submit_and_confirm",
        submit_mock,
    ):
        signature = await send_credit_cal(
            config=config,
            rider_wallet=str(RIDER),
            ride_hash=RIDE_HASH,
            amount=123_000_000_000,
        )

    assert signature == "cal-sig"
    assert submit_mock.await_args.kwargs["commitment"] == "finalized"


@pytest.mark.asyncio
async def test_send_record_climb_completion_uses_evidence_hash_reference_id():
    config = make_config()
    submit_mock = AsyncMock(return_value=SimpleNamespace(failed=False, signature="climb-sig"))
    ride_attestation, _ = _derive_ride_attestation_pda(RIDER, RIDE_HASH, PROGRAM_ID)
    vault, _ = _derive_vault_pda(VAULT_ID, PROGRAM_ID)
    evidence_hash = build_climb_completion_evidence_v2(
        ride_attestation=ride_attestation,
        vault=vault,
        completion_time_s=600,
        cal_tribute=123_000_000_000,
    )

    with patch("app.solana_direct._account_exists", new=AsyncMock(return_value=False)), patch(
        "app.services.solana_submit.submit_and_confirm",
        submit_mock,
    ):
        signature = await send_record_climb_completion(
            config=config,
            rider_wallet=str(RIDER),
            ride_hash=RIDE_HASH,
            vault_id=VAULT_ID,
            completion_time_s=600,
            cal_tribute=123_000_000_000,
            completion_evidence_version=2,
            completion_evidence_hash=evidence_hash,
        )

    assert signature == "climb-sig"
    assert submit_mock.await_args.kwargs["tx_type"] == "record_climb_completion_v2"
    assert submit_mock.await_args.kwargs["reference_type"] == "vault_completion"
    assert submit_mock.await_args.kwargs["reference_id"] == evidence_hash.hex()
    assert submit_mock.await_args.kwargs["commitment"] == "finalized"
