"""Retained closed-record witnesses and namespace rejection (offline proof)."""
import copy
import base64
import struct
import uuid
from contextlib import asynccontextmanager

import pytest
from solders.keypair import Keypair

from app.services.stage1_keeper_chain import KeeperChain, CLOCK
from app.services.stage1_keeper_payout import PayoutWorker
from app.services.stage1_keeper_records import restore_cash_books


def test_carried_hold_preserves_closed_funding_lifetime_income():
    original={'holds':[10,0,0,0,0],'pool':0,'lineage':[1]*32,'harvested_net':10,'admitted_cash':0}
    carried={**original,'harvested_net':0,'admitted_cash':999,'closed_source':True}
    observed={'books':{'book':carried},'carried':{'book':carried}}
    restore_cash_books(observed,[{'week':1,'funding_publication':{'address':'book','account':original,'closed':{'signature':'finalized-close'}}}])
    assert observed['books']['book']['harvested_net']==10
    assert observed['books']['book']['admitted_cash']==0


@pytest.mark.asyncio
async def test_close_keeps_publication_baseline_for_replaying_later_hold_expiry():
    from types import SimpleNamespace
    import json
    original = {'holds':[10,0,0,0,0],'pool':0,'lineage':[1]*32,'rent_payer':'sponsor'}
    current = {**original,'holds':[0]*5,'pool':10}
    job = {'id':'one','week':1,'funding_publication':{'address':'book','account':original,'transaction':{'slot':1},'closed':None}}
    saved = []
    class Connection:
        async def execute(self,sql,job_id,record):
            saved.append(json.loads(record))
    @asynccontextmanager
    async def acquire():
        yield Connection()
    worker = PayoutWorker(SimpleNamespace(pool=SimpleNamespace(acquire=acquire)),SimpleNamespace(funding=lambda s,w:'book'))
    await worker.weekly_close({},job,{'books':{'book':current},'slot':100})
    retained = saved[0]
    retained['closed'] = {'signature':'finalized-close'}
    after = {'books':{},'carried':{}}
    restore_cash_books(after,[{**job,'funding_publication':retained},
        {'week':27,'state':'complete','allocation':{'holds':{}},'operations':[{'kind':'expire','source':'book'}]}])
    assert after['books']['book']['pool']==10
    assert retained['account']==original


@pytest.mark.asyncio
@pytest.mark.parametrize('fault',['program','city','hill','canon_id','launch','mint'])
async def test_dung_and_admission_refuse_foreign_namespace_before_inventory(fault):
    chain = KeeperChain('http://127.0.0.1:8899',str(Keypair().pubkey()),'/unused')
    chain.signer,chain.genesis = Keypair(),'local'
    canon = uuid.uuid4()
    scope = {'program':str(chain.program),'city':chain.pda('s1v1_city'),
        'hill':chain.pda('s1v1_hill',canon.bytes),'canon_id':str(canon),'launch':1791201600,
        'mint':str(Keypair().pubkey()),'kind':'dung'}
    clock = bytearray(40); struct.pack_into('<q',clock,32,scope['launch']+604800)
    city = {'publisher':str(chain.signer.pubkey()),'season_anchor':scope['launch']}
    hill = {'city':scope['city'],'canon_id':list(canon.bytes),'bonded':True,'bonded_at':scope['launch']}
    config = {'dung_mint':scope['mint']}
    async def multiple(addresses,floor=0,**kwargs):
        return 100,{a:({'data':[base64.b64encode(clock).decode(),'base64']} if a==CLOCK else
            config if a==chain.pda('program_config') else hill if a==scope['hill'] else
            None if a==chain.pda('s1v1_dung_state') else city) for a in addresses}
    async def filtered(*args,**kwargs):
        pytest.fail('invalid namespace reached inventory')
    chain.multiple,chain.filtered,chain.decode = multiple,filtered,lambda row,kind:row
    bad = copy.deepcopy(scope)
    bad[fault] = scope['launch']+1 if fault=='launch' else str(uuid.uuid4()) if fault=='canon_id' else str(Keypair().pubkey())
    # Route the changed address to its forged but otherwise valid account.
    async def forged(addresses,floor=0,**kwargs):
        _,rows = await multiple(addresses,floor,**kwargs)
        rows[bad['hill']] = hill
        rows[bad['city']] = city
        return 100,{a:rows[a] for a in addresses}
    chain.multiple = forged
    try:
        with pytest.raises(ValueError,match='namespace|scope'):
            await chain.observe_dung(bad,1,0)
        if fault!='mint':
            with pytest.raises(ValueError,match='namespace|scope'):
                await chain.admission_bond(bad)
    finally:
        await chain.close()
