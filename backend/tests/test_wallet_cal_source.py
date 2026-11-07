from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import struct
import pytest
from solders.pubkey import Pubkey
from app import solana_direct as chain


@pytest.mark.asyncio
@pytest.mark.parametrize('amount', [None, 0, 123, 9007199254740993])
async def test_wallet_cal_existence_is_rpc_evidence(amount):
    rider = Pubkey.new_unique()
    data = bytearray(165)
    data[:32] = bytes(chain.DEFAULT_CAL_MINT_ADDRESS)
    data[32:64] = bytes(rider)
    struct.pack_into('<Q', data, 64, amount or 0)
    data[108] = 1
    account = None if amount is None else SimpleNamespace(owner=chain.TOKEN_PROGRAM_ID, data=bytes(data))
    client = AsyncMock()
    client.get_account_info.return_value = SimpleNamespace(value=account, context=SimpleNamespace(slot=17))
    with patch.object(chain, 'AsyncClient') as factory:
        factory.return_value.__aenter__.return_value = client
        source = await chain.get_wallet_cal_balance_source(str(rider), rpc_url='http://fixture', program_id=Pubkey.default())
    assert source.exists is (amount is not None)
    assert source.status == ('not_initialized' if amount is None else 'live')
    assert source.amount_base_units == (amount or 0)
    assert source.slot == 17
    client.get_account_info.assert_awaited_once_with(chain._derive_ata(rider, chain.DEFAULT_CAL_MINT_ADDRESS))
    client.get_token_account_balance.assert_not_awaited()
