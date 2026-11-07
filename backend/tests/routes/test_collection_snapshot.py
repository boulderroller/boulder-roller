from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from solders.pubkey import Pubkey
from app import solana_direct as chain
from app.services import collection_snapshot as producer


@pytest.mark.asyncio
@pytest.mark.parametrize('amounts,broken,total', [([4250000000,800000000],False,'5050000000'), ([0,0],False,'0'), ([],False,'0'), ([4250000000,800000000],True,None)])
async def test_single_revision_collection(amounts, broken, total):
    rider = Pubkey.new_unique()
    program = Pubkey.new_unique()
    rows, decoded = [], {}
    for vault_id, amount in enumerate(amounts, 1):
        pda, bump = chain._derive_vault_stake_pda(rider, vault_id, program)
        rows.append(SimpleNamespace(pubkey=pda, account=SimpleNamespace(owner=program, data=b'account')))
        decoded[str(pda)] = dict(user=str(rider), vault_id=vault_id, bump=bump, lp_tokens=1, rewards_earned=amount)
    if broken:
        decoded[str(rows[-1].pubkey)]['user'] = 'wrong-rider'
    response = SimpleNamespace(value=SimpleNamespace(context=SimpleNamespace(slot=987), value=rows))
    client = AsyncMock()
    client._provider.make_request.return_value = response
    with patch.object(producer, 'AsyncClient') as factory, patch.object(chain, 'load_readonly_config', return_value=SimpleNamespace(rpc_url='http://fixture', program_id=program)), patch.object(chain, '_decode_anchor_vault_stake_account', side_effect=lambda data,pda: decoded[str(pda)]):
        factory.return_value.__aenter__.return_value = client
        snapshot = await producer.get_collection_snapshot(str(rider))
    assert snapshot['uncollectedDungBaseUnits'] == total
    assert snapshot['coverage'] == dict(completeness='partial' if broken else 'complete', population='wallet_vault_stakes', observedCount=len(rows)-int(broken), expectedCount=len(rows))
    assert snapshot['revision'].endswith(':987')
    assert [p['dungReadyBaseUnits'] for p in snapshot['positions']] == [str(a) for a in (amounts[:-1] if broken else amounts)]
    client._provider.make_request.assert_awaited_once()
