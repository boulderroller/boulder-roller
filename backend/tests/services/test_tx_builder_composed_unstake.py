"""Composed collect-before-unstake transaction building (boulderroller-v2-71o2v).

Withdraw is one Balance action: when the position still carries unclaimed
DUNG, the same atomic transaction must collect it BEFORE burning LP so a
withdraw can never forfeit pending rewards.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from solders.hash import Hash
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from app.services import tx_builder as tx_builder_module
from app.services.tx_builder import TxBuilder
from app.solana_direct import DirectConfig, _discriminator


COLLECT_DISCRIMINATOR = _discriminator("collect_stake_rewards_for")
UNSTAKE_DISCRIMINATOR = _discriminator("unstake_cal_from_vault")


def _make_builder(monkeypatch, protocol_treasury: Pubkey | None) -> TxBuilder:
    payer = Keypair()
    backend_authority = Keypair()
    config = DirectConfig(
        rpc_url="http://127.0.0.1:8899",
        program_id=Keypair().pubkey(),
        payer=payer,
        backend_authority=backend_authority,
        dung_mint_address=Keypair().pubkey(),
        cal_mint_address=Keypair().pubkey(),
    )
    monkeypatch.setattr(tx_builder_module, "load_default_config", lambda: config)
    return TxBuilder(
        rpc_url=config.rpc_url,
        program_id=config.program_id,
        dung_mint=config.dung_mint_address,
        cal_mint=config.cal_mint_address,
        fee_payer=payer,
        backend_authority=backend_authority,
        protocol_treasury=protocol_treasury,
    )


@pytest.fixture
def builder(monkeypatch):
    tx_builder = _make_builder(monkeypatch, Keypair().pubkey())
    captured: dict = {}

    def fake_build_unsigned_tx(fee_payer, instructions, blockhash, partial_signers):
        captured["instructions"] = list(instructions)
        captured["partial_signers"] = list(partial_signers)
        return b"tx-bytes"

    monkeypatch.setattr(tx_builder, "_build_unsigned_tx", fake_build_unsigned_tx)
    monkeypatch.setattr(
        tx_builder,
        "_get_recent_blockhash",
        AsyncMock(return_value=(Hash.default(), 123)),
    )
    monkeypatch.setattr(tx_builder, "_check_ata_exists", AsyncMock(return_value=True))
    tx_builder._captured = captured
    return tx_builder


def _discriminators(instructions) -> list[bytes]:
    return [bytes(ix.data[:8]) for ix in instructions]


@pytest.mark.asyncio
async def test_plain_unstake_contains_no_collect_instruction(builder) -> None:
    result = await builder.build_unstake_tx(
        user_wallet=str(Pubkey.new_unique()),
        vault_id=16,
        lp_amount=1_000_000_000,
    )
    discs = _discriminators(builder._captured["instructions"])
    assert COLLECT_DISCRIMINATOR not in discs
    assert discs[-1] == UNSTAKE_DISCRIMINATOR
    assert result.message == "Withdraw CAL from vault 16"


@pytest.mark.asyncio
async def test_composed_withdraw_collects_before_unstake(builder) -> None:
    result = await builder.build_unstake_tx(
        user_wallet=str(Pubkey.new_unique()),
        vault_id=16,
        lp_amount=1_000_000_000,
        collect_rewards=True,
    )
    discs = _discriminators(builder._captured["instructions"])
    assert COLLECT_DISCRIMINATOR in discs
    assert UNSTAKE_DISCRIMINATOR in discs
    # Protocol rule: collect first, then burn LP — inside one transaction.
    assert discs.index(COLLECT_DISCRIMINATOR) < discs.index(UNSTAKE_DISCRIMINATOR)
    assert result.message == "Collect DUNG and withdraw CAL from vault 16"


@pytest.mark.asyncio
async def test_composed_withdraw_creates_missing_dung_ata(builder) -> None:
    builder._check_ata_exists = AsyncMock(return_value=False)
    await builder.build_unstake_tx(
        user_wallet=str(Pubkey.new_unique()),
        vault_id=16,
        lp_amount=1_000_000_000,
        collect_rewards=True,
    )
    instructions = builder._captured["instructions"]
    discs = _discriminators(instructions)
    # ATA creation precedes the collect instruction it feeds.
    collect_index = discs.index(COLLECT_DISCRIMINATOR)
    assert collect_index >= 1
    assert discs[-1] == UNSTAKE_DISCRIMINATOR


@pytest.mark.asyncio
async def test_composed_withdraw_requires_configured_treasury(monkeypatch) -> None:
    tx_builder = _make_builder(monkeypatch, None)
    monkeypatch.setattr(
        tx_builder, "_resolve_protocol_treasury", AsyncMock(return_value=None)
    )
    with pytest.raises(ValueError, match="PROTOCOL_TREASURY_ACCOUNT"):
        await tx_builder.build_unstake_tx(
            user_wallet=str(Pubkey.new_unique()),
            vault_id=16,
            lp_amount=1,
            collect_rewards=True,
        )


def test_pending_rewards_parser_is_exact() -> None:
    from app.routes.vaults import _pending_rewards_base_units

    assert _pending_rewards_base_units(None) == 0
    assert _pending_rewards_base_units({}) == 0
    assert _pending_rewards_base_units({"rewards_earned": 0}) == 0
    assert _pending_rewards_base_units({"rewards_earned": "12345000000"}) == 12345000000
    # Invalid on-chain state degrades to zero rather than raising in-route.
    assert _pending_rewards_base_units({"rewards_earned": "not-a-number"}) == 0
