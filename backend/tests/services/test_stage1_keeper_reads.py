"""Read-scope and calendar probes; RPC responses here are explicit fixtures."""
import base64
import copy
import struct
import uuid

import pytest
from solders.keypair import Keypair

from app.services.stage1_keeper_chain import KeeperChain, CLOCK


@pytest.mark.asyncio
async def test_idle_clock_uses_one_exact_read_after_startup():
    chain = KeeperChain('http://127.0.0.1:8899', str(Keypair().pubkey()), '/not/read')
    chain.genesis = 'local'
    calls = []
    async def rpc(method, params):
        calls.append((method, params))
        raw = bytearray(40)
        struct.pack_into('<q', raw, 32, 1791201600)
        return {'context': {'slot': 101}, 'value': [{'data': [base64.b64encode(raw).decode(), 'base64']}]}
    chain.rpc = rpc
    try:
        assert await chain.clock(100) == {'slot': 101, 'now': 1791201600}
        assert len(calls) == 1 and calls[0][0] == 'getMultipleAccounts'
        assert calls[0][1][0] == [CLOCK]
    finally:
        await chain.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,offset', [('Stage1WeekFunding', 104), ('Stage1ClaimSet', 104), ('Stage1PledgeLot', 105), ('Stage1ClaimReceipt', 8)])
async def test_inventory_queries_filter_discriminator_and_scope(kind, offset):
    chain = KeeperChain('http://127.0.0.1:8899', str(Keypair().pubkey()), '/not/read')
    address = str(Keypair().pubkey())
    async def rpc(method, params):
        assert method == 'getProgramAccounts'
        options = params[1]
        assert options['commitment'] == 'finalized' and options['minContextSlot'] == 100
        assert len(options['filters']) == 2
        assert options['filters'][0]['memcmp']['offset'] == 0
        assert options['filters'][1] == {'memcmp': {'offset': offset, 'bytes': address}}
        return {'context': {'slot': 101}, 'value': []}
    chain.rpc = rpc
    try:
        assert await chain.filtered(kind, offset, address, 100) == (101, {})
    finally:
        await chain.close()


@pytest.mark.asyncio
async def test_exact_registration_reads_are_batched_and_skip_erased_people():
    chain = KeeperChain('http://127.0.0.1:8899', str(Keypair().pubkey()), '/not/read')
    people = {str(Keypair().pubkey()) for _ in range(101)}
    from solders.pubkey import Pubkey
    expected = {chain.pda('s1v1_recipient', bytes(Pubkey.from_string(p))) for p in people}
    seen, floors = [], []
    async def rpc(method, params):
        assert method == 'getMultipleAccounts' and len(params[0]) <= 100
        seen.extend(params[0]); floors.append(params[1]['minContextSlot'])
        return {'context': {'slot': 101 + len(floors)}, 'value': [None]*len(params[0])}
    chain.rpc = rpc
    try:
        assert await chain.recipient_registrations(people | {'anonymous:erased'}, 100) == (103, {})
        assert set(seen) == expected and len(seen) == 101 and floors == [100, 102]
    finally:
        await chain.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', ['changed', 'stale', None])
async def test_inventory_closing_fence_covers_receipts_and_registrations(fault):
    from app.services.stage1_keeper_chain import TOKEN
    chain = KeeperChain('http://127.0.0.1:8899', str(Keypair().pubkey()), '/not/read')
    chain.genesis, chain.signer = 'local', Keypair()
    scope = {'program': str(chain.program), 'city': chain.pda('s1v1_city'), 'hill': str(Keypair().pubkey()),
             'mint': str(Keypair().pubkey()), 'canon_id': str(uuid.uuid4()), 'launch': 1791201600}
    from solders.pubkey import Pubkey
    asset = chain.pda('s1v1_asset', bytes(Pubkey.from_string(scope['mint'])))
    earnings = chain.pda('s1v1_earnings', bytes(Pubkey.from_string(scope['mint'])))
    cursor = chain.cursor_address(scope)
    account_set = chain.claim_address(scope, 1)
    person = str(Keypair().pubkey())
    clock = bytearray(40); struct.pack_into('<q', clock, 32, scope['launch']+3*604800)
    token = bytes(Pubkey.from_string(scope['mint'])) + bytes(Pubkey.from_string(asset)) + bytes(8)
    rows = {scope['city']: {'publisher': str(chain.signer.pubkey()), 'season_anchor': scope['launch']},
            scope['hill']: {'city': scope['city'], 'bonded': True, 'canon_id': list(uuid.UUID(scope['canon_id']).bytes)},
            asset: {'city': scope['city'], 'mint': scope['mint']}, cursor: None,
            CLOCK: {'data': [base64.b64encode(clock).decode(), 'base64']},
            earnings: {'owner': TOKEN, 'data': [base64.b64encode(token).decode(), 'base64']}}
    chain.decode = lambda row, kind: row
    floors = []
    async def rpc(method, params):
        assert method == 'getMultipleAccounts'
        floors.append(params[1]['minContextSlot'])
        values = [copy.deepcopy(rows[a]) for a in params[0]]
        if len(floors) == 2 and fault == 'changed':
            values[0]['changed'] = True
        slot = floors[-1] + 1
        if len(floors) == 2 and fault == 'stale':
            slot -= 2
        return {'context': {'slot': slot}, 'value': values}
    async def filtered(kind, offset, address, floor):
        values = {account_set: {'hill': scope['hill'], 'week': 1, 'paid': 1}} if kind == 'Stage1ClaimSet' else {}
        if kind == 'Stage1ClaimReceipt':
            values = {'receipt': {'person': person, 'claim_set': account_set}}
        return floor+10, values
    async def registrations(people, floor):
        assert people == {person}
        return floor+10, {person: {'recipient': person, 'registered_at': scope['launch']}}
    async def bitmaps(scope, floor):
        return floor+10, {account_set:{'hill':scope['hill'],'week':1,'paid':1}}
    chain.cash_claim_inventory = bitmaps
    chain.rpc, chain.filtered, chain.recipient_registrations = rpc, filtered, registrations
    try:
        if fault:
            with pytest.raises(RuntimeError, match='changed|stale'):
                await chain.observe(scope, 1, 100)
        else:
            observation = await chain.observe(scope, 1, 100)
            assert observation['slot'] == 162 and observation['receipts'] == []
        assert floors == [100, 161]
    finally:
        await chain.close()
