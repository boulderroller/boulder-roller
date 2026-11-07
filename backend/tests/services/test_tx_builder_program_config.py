from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from solders.hash import Hash
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from app.solana_direct import DirectConfig
from app.services import tx_builder as tx_builder_module
from app.services.tx_builder import TxBuilder


def _new_pubkey() -> Pubkey:
    return Keypair().pubkey()


def _builder(monkeypatch: pytest.MonkeyPatch) -> tuple[TxBuilder, DirectConfig]:
    payer = Keypair()
    backend_authority = Keypair()
    config = DirectConfig(
        rpc_url="http://127.0.0.1:8899",
        program_id=_new_pubkey(),
        payer=payer,
        backend_authority=backend_authority,
        dung_mint_address=_new_pubkey(),
        cal_mint_address=_new_pubkey(),
    )
    monkeypatch.setattr(tx_builder_module, "load_default_config", lambda: config)
    return (
        TxBuilder(
            rpc_url=config.rpc_url,
            program_id=config.program_id,
            dung_mint=config.dung_mint_address,
            cal_mint=config.cal_mint_address,
            fee_payer=payer,
            backend_authority=backend_authority,
        ),
        config,
    )


async def _recent_blockhash() -> tuple[Hash, int]:
    return Hash.default(), 123


@pytest.mark.asyncio
async def test_add_funds_usdc_uses_program_config_mint(monkeypatch: pytest.MonkeyPatch) -> None:
    builder, _config = _builder(monkeypatch)
    rider = Keypair().pubkey()
    usdc_mint = _new_pubkey()
    usdc_treasury = _new_pubkey()
    checked_mints: list[Pubkey] = []

    monkeypatch.setattr(
        tx_builder_module,
        "get_program_config_account",
        AsyncMock(
            return_value={
                "usdc_mint": str(usdc_mint),
                "usdc_treasury_token_account": str(usdc_treasury),
            }
        ),
    )

    async def check_ata(_owner: Pubkey, mint: Pubkey) -> bool:
        checked_mints.append(mint)
        return True

    monkeypatch.setattr(builder, "_check_ata_exists", check_ata)
    monkeypatch.setattr(builder, "_check_account_exists", AsyncMock(return_value=True))
    monkeypatch.setattr(builder, "_get_recent_blockhash", _recent_blockhash)

    result = await builder.build_add_funds_to_balance_tx(
        user_wallet=str(rider),
        asset="USDC",
        amount=2_000_000,
    )

    assert result.message == "Add USDC to Boulder Roller Balance"
    assert usdc_mint in checked_mints
    tx_builder_module.get_program_config_account.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_vault_with_usdc_uses_program_config_payment_accounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder, config = _builder(monkeypatch)
    rider = Keypair().pubkey()
    usdc_mint = _new_pubkey()
    usdc_treasury = _new_pubkey()
    captured: dict[str, Pubkey] = {}
    original_make_ix = tx_builder_module.make_create_vault_with_usdc_ix

    monkeypatch.setattr(
        tx_builder_module,
        "get_program_config_account",
        AsyncMock(
            return_value={
                "usdc_mint": str(usdc_mint),
                "usdc_treasury_token_account": str(usdc_treasury),
            }
        ),
    )

    def capture_make_create_vault_with_usdc_ix(**kwargs):
        captured["creator_usdc_account"] = kwargs["creator_usdc_account"]
        captured["protocol_usdc_account"] = kwargs["protocol_usdc_account"]
        return original_make_ix(**kwargs)

    monkeypatch.setattr(
        tx_builder_module,
        "make_create_vault_with_usdc_ix",
        capture_make_create_vault_with_usdc_ix,
    )
    monkeypatch.setattr(builder, "_check_ata_exists", AsyncMock(return_value=True))
    monkeypatch.setattr(builder, "_get_recent_blockhash", _recent_blockhash)

    result = await builder.build_create_vault_with_usdc_tx(
        user_wallet=str(rider),
        climb_pda=str(_new_pubkey()),
        display_name="Devnet ProgramConfig Climb",
        vault_id=42,
    )

    assert result.message.startswith("Create Vault for Devnet ProgramConfig Climb")
    assert captured == {
        "creator_usdc_account": tx_builder_module._derive_ata(rider, usdc_mint),
        "protocol_usdc_account": usdc_treasury,
    }
    tx_builder_module.get_program_config_account.assert_awaited_once()
    assert config.cal_mint_address != usdc_mint


@pytest.mark.asyncio
async def test_usdc_balance_actions_fail_when_program_config_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builder, _config = _builder(monkeypatch)
    monkeypatch.setattr(
        tx_builder_module,
        "get_program_config_account",
        AsyncMock(return_value=None),
    )

    with pytest.raises(ValueError, match="ProgramConfig USDC mint not configured"):
        await builder.build_withdraw_to_wallet_tx(
            user_wallet=str(Keypair().pubkey()),
            asset="USDC",
            amount=1,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("payment_method", ["dung", "cal_usdc"])
async def test_v4b_vault_constructor_is_partially_signed_by_backend_authority(
    monkeypatch: pytest.MonkeyPatch,
    payment_method: str,
) -> None:
    builder, _config = _builder(monkeypatch)
    rider = Keypair().pubkey()
    climb = Keypair().pubkey()
    captured_signers: list[Keypair] = []

    monkeypatch.setattr(builder, "_check_ata_exists", AsyncMock(return_value=True))
    monkeypatch.setattr(builder, "_get_recent_blockhash", _recent_blockhash)

    def capture_build(_payer, _instructions, _blockhash, partial_signers):
        captured_signers.extend(partial_signers)
        return b"backend-authorized-vault-constructor"

    monkeypatch.setattr(builder, "_build_unsigned_tx", capture_build)
    if payment_method == "cal_usdc":
        monkeypatch.setattr(
            builder,
            "_resolve_usdc_payment_config",
            AsyncMock(return_value=(_new_pubkey(), _new_pubkey())),
        )
        await builder.build_create_vault_with_usdc_tx(
            user_wallet=str(rider),
            climb_pda=str(climb),
            display_name="Authorized Climb",
            vault_id=42,
        )
    else:
        await builder.build_create_vault_tx(
            user_wallet=str(rider),
            climb_pda=str(climb),
            display_name="Authorized Climb",
            vault_id=42,
        )

    assert builder.backend_authority in captured_signers
