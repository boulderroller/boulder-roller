from __future__ import annotations

import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from solders.keypair import Keypair

from app.solana_direct import (
    DEFAULT_BOULDER_PROGRAM_ID,
    DEFAULT_DUNG_MINT_ADDRESS,
    TOKEN_PROGRAM_ID,
    _derive_ata,
    _derive_rider_balance_auth_pda,
    _derive_rider_balance_token_pda,
    get_balance_dung_balance_source,
    get_wallet_dung_balance_source,
)


def _token_account_data(*, owner, amount: int) -> bytes:
    data = bytearray(165)
    data[0:32] = bytes(DEFAULT_DUNG_MINT_ADDRESS)
    data[32:64] = bytes(owner)
    struct.pack_into("<Q", data, 64, amount)
    data[108] = 1
    return bytes(data)


def _rpc_client(*, account_owner, token_owner, amount: int, slot: int = 123):
    response = SimpleNamespace(
        context=SimpleNamespace(slot=slot),
        value=SimpleNamespace(
            owner=account_owner,
            data=_token_account_data(owner=token_owner, amount=amount),
        ),
    )
    client = AsyncMock()
    client.get_account_info = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


@pytest.mark.asyncio
async def test_wallet_dung_source_reads_exact_ata_amount_and_slot() -> None:
    rider = Keypair().pubkey()
    amount = 9_007_199_254_740_993
    client = _rpc_client(
        account_owner=TOKEN_PROGRAM_ID,
        token_owner=rider,
        amount=amount,
        slot=456,
    )

    with patch("app.solana_direct.AsyncClient", return_value=client):
        result = await get_wallet_dung_balance_source(
            str(rider),
            rpc_url="https://rpc.example",
            program_id=DEFAULT_BOULDER_PROGRAM_ID,
        )

    expected_ata = _derive_ata(rider, DEFAULT_DUNG_MINT_ADDRESS)
    client.get_account_info.assert_awaited_once_with(expected_ata)
    assert result.amount_base_units == amount
    assert result.token_account == str(expected_ata)
    assert result.source == "spl_wallet_ata"
    assert result.status == "live"
    assert result.exists
    assert result.slot == 456


@pytest.mark.asyncio
async def test_balance_dung_source_reads_only_the_rider_balance_token_pda() -> None:
    rider = Keypair().pubkey()
    balance_authority, _ = _derive_rider_balance_auth_pda(
        rider,
        DEFAULT_BOULDER_PROGRAM_ID,
    )
    client = _rpc_client(
        account_owner=TOKEN_PROGRAM_ID,
        token_owner=balance_authority,
        amount=42,
        slot=789,
    )

    with patch("app.solana_direct.AsyncClient", return_value=client):
        result = await get_balance_dung_balance_source(
            str(rider),
            rpc_url="https://rpc.example",
            program_id=DEFAULT_BOULDER_PROGRAM_ID,
        )

    expected_pda, _ = _derive_rider_balance_token_pda(
        rider,
        DEFAULT_DUNG_MINT_ADDRESS,
        DEFAULT_BOULDER_PROGRAM_ID,
    )
    client.get_account_info.assert_awaited_once_with(expected_pda)
    assert result.amount_base_units == 42
    assert result.token_account == str(expected_pda)
    assert result.source == "rider_balance_token_pda"
    assert result.status == "live"
    assert result.exists
    assert result.slot == 789


@pytest.mark.asyncio
async def test_missing_wallet_ata_is_known_zero_not_rpc_unavailable() -> None:
    rider = Keypair().pubkey()
    response = SimpleNamespace(context=SimpleNamespace(slot=321), value=None)
    client = AsyncMock()
    client.get_account_info = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.solana_direct.AsyncClient", return_value=client):
        result = await get_wallet_dung_balance_source(
            str(rider),
            rpc_url="https://rpc.example",
            program_id=DEFAULT_BOULDER_PROGRAM_ID,
        )

    assert result.amount_base_units == 0
    assert result.status == "not_initialized"
    assert not result.exists
    assert result.slot == 321


@pytest.mark.asyncio
async def test_balance_reader_rejects_a_token_account_owned_by_the_wallet() -> None:
    rider = Keypair().pubkey()
    client = _rpc_client(
        account_owner=TOKEN_PROGRAM_ID,
        token_owner=rider,
        amount=42,
    )

    with (
        patch("app.solana_direct.AsyncClient", return_value=client),
        pytest.raises(ValueError, match="token owner"),
    ):
        await get_balance_dung_balance_source(
            str(rider),
            rpc_url="https://rpc.example",
            program_id=DEFAULT_BOULDER_PROGRAM_ID,
        )
