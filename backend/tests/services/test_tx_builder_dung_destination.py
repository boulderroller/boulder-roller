from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from solders.hash import Hash
from solders.keypair import Keypair

from app.solana_direct import (
    DEFAULT_BOULDER_PROGRAM_ID,
    DEFAULT_DUNG_MINT_ADDRESS,
    _derive_ata,
)
from app.services.tx_builder import TxBuilder


@pytest.mark.asyncio
async def test_harvest_build_result_names_the_exact_wallet_dung_ata() -> None:
    rider = Keypair().pubkey()
    builder = object.__new__(TxBuilder)
    builder.fee_payer = Keypair()
    builder.dung_mint = DEFAULT_DUNG_MINT_ADDRESS
    builder.program_id = DEFAULT_BOULDER_PROGRAM_ID
    builder._resolve_protocol_treasury = AsyncMock(return_value=Keypair().pubkey())
    builder._check_ata_exists = AsyncMock(return_value=True)
    builder._get_recent_blockhash = AsyncMock(return_value=(Hash.new_unique(), 123))
    builder._build_unsigned_tx = MagicMock(return_value=b"prepared-harvest")

    result = await builder.build_harvest_tx(
        user_wallet=str(rider),
        vault_id=42,
    )

    expected_ata = _derive_ata(rider, DEFAULT_DUNG_MINT_ADDRESS)
    assert result.pda == str(expected_ata)
    assert result.message == "Collect DUNG from vault 42"
