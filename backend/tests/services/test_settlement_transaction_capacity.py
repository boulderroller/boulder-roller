from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from solders.address_lookup_table_account import (
    AddressLookupTable,
    AddressLookupTableAccount,
    LookupTableMeta,
)
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from app.services.solana_submit import (
    PACKET_DATA_SIZE,
    TransactionPacketSizeError,
    _build_signed_transaction,
)
from app.solana_direct import (
    SETTLEMENT_COMPUTE_UNIT_LIMIT,
    _validate_settlement_lookup_table_state,
    make_create_ata_ix,
    make_distribute_epoch_rewards_ix,
)


VAULT_ID = 42


def _distribution_instruction(
    *,
    authority: Pubkey,
    program_id: Pubkey,
    recipient_count: int = 11,
    stake_count: int,
) -> Instruction:
    recipients = [
        AccountMeta(Pubkey.new_unique(), is_signer=False, is_writable=True)
        for _ in range(recipient_count)
    ]
    stakes = [
        AccountMeta(Pubkey.new_unique(), is_signer=False, is_writable=True)
        for _ in range(stake_count)
    ]
    return make_distribute_epoch_rewards_ix(
        authority=authority,
        vault_id=VAULT_ID,
        settlement_week=10,
        pol_account=Pubkey.new_unique(),
        protocol_treasury=Pubkey.new_unique(),
        dung_mint=Pubkey.new_unique(),
        program_id=program_id,
        local_legend=Pubkey.new_unique(),
        extra_accounts=recipients + stakes,
    )


def _settlement_instructions(distribution: Instruction) -> list[Instruction]:
    return [
        set_compute_unit_limit(SETTLEMENT_COMPUTE_UNIT_LIMIT),
        set_compute_unit_price(50_000),
        distribution,
    ]


def _lookup_table_for_instruction(ix: Instruction) -> AddressLookupTableAccount:
    addresses = list(
        {
            meta.pubkey: None
            for meta in ix.accounts
            if not meta.is_signer
        }
    )
    return AddressLookupTableAccount(Pubkey.new_unique(), addresses)


def test_full_board_legacy_boundary_is_red_and_v0_carries_ten_stakers() -> None:
    payer = Keypair()
    authority = Keypair()
    program_id = Pubkey.new_unique()
    blockhash = Hash.default()

    legacy_four_ix = _distribution_instruction(
        authority=authority.pubkey(),
        program_id=program_id,
        stake_count=4,
    )
    legacy_four = _build_signed_transaction(
        instructions=_settlement_instructions(legacy_four_ix),
        fee_payer=payer.pubkey(),
        signers=[payer, authority],
        blockhash=blockhash,
    )
    assert len(bytes(legacy_four)) == PACKET_DATA_SIZE

    legacy_five_ix = _distribution_instruction(
        authority=authority.pubkey(),
        program_id=program_id,
        stake_count=5,
    )
    with pytest.raises(TransactionPacketSizeError, match="1,265.*1,232"):
        _build_signed_transaction(
            instructions=_settlement_instructions(legacy_five_ix),
            fee_payer=payer.pubkey(),
            signers=[payer, authority],
            blockhash=blockhash,
        )

    v0_ten_ix = _distribution_instruction(
        authority=authority.pubkey(),
        program_id=program_id,
        stake_count=10,
    )
    v0_ten = _build_signed_transaction(
        instructions=_settlement_instructions(v0_ten_ix),
        fee_payer=payer.pubkey(),
        signers=[payer, authority],
        blockhash=blockhash,
        address_lookup_table_accounts=[_lookup_table_for_instruction(v0_ten_ix)],
    )

    assert v0_ten.version() == 0
    assert len(bytes(v0_ten)) < PACKET_DATA_SIZE


@pytest.mark.parametrize(
    ("state", "current_slot", "required", "message"),
    [
        (
            AddressLookupTable(
                LookupTableMeta(last_extended_slot=100, authority=Pubkey.new_unique()),
                [Pubkey.new_unique()],
            ),
            100,
            [],
            "not active yet",
        ),
        (
            AddressLookupTable(
                LookupTableMeta(deactivation_slot=99, authority=Pubkey.new_unique()),
                [Pubkey.new_unique()],
            ),
            100,
            [],
            "deactivated",
        ),
    ],
)
def test_lookup_table_state_rejects_inactive_transport(
    state: AddressLookupTable,
    current_slot: int,
    required: list[Pubkey],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _validate_settlement_lookup_table_state(
            address=Pubkey.new_unique(),
            state=state,
            current_slot=current_slot,
            expected_authority=state.meta.authority,
            required_addresses=required,
        )


def test_lookup_table_state_rejects_wrong_authority_and_incomplete_inventory() -> None:
    authority = Pubkey.new_unique()
    included = Pubkey.new_unique()
    missing = Pubkey.new_unique()
    state = AddressLookupTable(
        LookupTableMeta(last_extended_slot=10, authority=authority),
        [included],
    )

    with pytest.raises(ValueError, match="authority mismatch"):
        _validate_settlement_lookup_table_state(
            address=Pubkey.new_unique(),
            state=state,
            current_slot=11,
            expected_authority=Pubkey.new_unique(),
            required_addresses=[included],
        )

    with pytest.raises(ValueError, match="missing 1 required account"):
        _validate_settlement_lookup_table_state(
            address=Pubkey.new_unique(),
            state=state,
            current_slot=11,
            expected_authority=authority,
            required_addresses=[included, missing],
        )


@pytest.mark.asyncio
async def test_recipient_ata_instruction_is_idempotent_and_prepared_separately() -> None:
    payer = Keypair()
    owner = Pubkey.new_unique()
    mint = Pubkey.new_unique()
    ata_ix = make_create_ata_ix(
        payer=payer.pubkey(),
        owner=owner,
        mint=mint,
        idempotent=True,
    )

    assert ata_ix.data == bytes([1])

    submit = AsyncMock(
        return_value=SimpleNamespace(
            failed=False,
            signature="ata-prepared",
            error=None,
            status="finalized",
        )
    )
    with patch("app.services.solana_submit.submit_and_confirm", new=submit):
        from app.solana_direct import _prepare_settlement_recipient_atas

        signatures = await _prepare_settlement_recipient_atas(
            rpc_url="http://example.invalid",
            payer=payer,
            vault_id=VAULT_ID,
            instructions=[ata_ix],
        )

    submit.assert_awaited_once()
    assert signatures == ["ata-prepared"]
    kwargs = submit.await_args.kwargs
    assert kwargs["tx_type"] == "settlement_recipient_ata_prepare"
    assert kwargs["reference_id"] == str(VAULT_ID)
    assert kwargs["instructions"] == [ata_ix]
    assert "on_prepared" not in kwargs
    assert "on_submitted" not in kwargs
