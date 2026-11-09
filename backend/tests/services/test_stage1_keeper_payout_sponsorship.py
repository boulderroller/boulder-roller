"""Offline RPC doubles and real PostgreSQL; actual-chain proof is composed localnet."""
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
import pytest
from solders.hash import Hash
from solders.keypair import Keypair
from solders.message import MessageV0
from app.services.stage1_keeper_chain import KeeperChain, SponsorUnfunded
from app.services.stage1_keeper_payout import PayoutWorker
from tests.services.test_stage1_keeper_worker import store, migrated_template
from tests.services.test_stage1_keeper_erasure import settled_fixture


@pytest.mark.asyncio
async def test_genesis_once_per_cycle_and_256_signature_chunks():
    chain=KeeperChain('http://127.0.0.1:8899',str(Keypair().pubkey()),'/unused')
    chain.signer=Keypair();calls=[]
    async def rpc(method,params):
        calls.append((method,params))
        if method=='getGenesisHash': return 'local'
        assert method=='getSignatureStatuses'
        return {'context':{'slot':100},'value':[{'slot':90,'err':None,'confirmationStatus':'finalized'} for _ in params[0]]}
    chain.rpc=rpc
    try:
        async with chain.cycle():
            await chain.start();await chain.get_genesis_hash()
            statuses=await chain.status_batch([{'signature':str(i),'genesis':'local'} for i in range(600)])
        assert len(statuses)==600 and all(v['state']=='finalized' for v in statuses.values())
        assert [m for m,p in calls].count('getGenesisHash')==1
        assert [len(p[0]) for m,p in calls if m=='getSignatureStatuses']==[256,256,88]
        async with chain.cycle(): pass
        assert [m for m,p in calls].count('getGenesisHash')==2
    finally: await chain.close()


@pytest.mark.asyncio
async def test_sol_precheck_reserves_inflight_rent_and_resumes_when_funded():
    chain=KeeperChain('http://127.0.0.1:8899',str(Keypair().pubkey()),'/unused')
    chain.signer=Keypair();balance=100
    async def rpc(method,params):
        if method=='getMinimumBalanceForRentExemption': return 200
        return {'context':{'slot':90},'value':balance if method=='getBalance' else 5}
    chain.rpc=rpc
    message=MessageV0.try_compile(chain.signer.pubkey(),[],[],Hash.default())
    try:
        with pytest.raises(SponsorUnfunded): await chain.check_sol({'kind':'cash_claim','create_ata':True},message,50)
        balance=205
        assert await chain.check_sol({'kind':'cash_claim','create_ata':True},message,50)==205
        chain.in_cycle=True;chain.reserved_lamports=205
        with pytest.raises(SponsorUnfunded): await chain.check_sol({'kind':'cash_claim','create_ata':False},message,50)
        balance=210
        assert await chain.check_sol({'kind':'cash_claim','create_ata':False},message,50)==5
    finally: await chain.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('error',[
    {'err':'InsufficientFundsForFee'}, {'err':{'InsufficientFundsForRent':{'account_index':1}}},
    {'err':{'InstructionError':[0,{'Custom':1}]},'logs':['Transfer: insufficient lamports 1, need 200']},
])
async def test_account_creation_lamport_refusal_is_wait(error):
    chain=KeeperChain('http://127.0.0.1:8899',str(Keypair().pubkey()),'/unused')
    await chain.client.aclose()
    chain.client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'error':{'code':-32002,'data':error}})))
    try:
        with pytest.raises(SponsorUnfunded): await chain.rpc('sendTransaction',[])
    finally: await chain.close()


async def fixture(store,tmp_path,monkeypatch):
    from app.services import stage1_keeper_payout as module
    _,scope,_,_,claims,job_id=await settled_fixture(store,tmp_path)
    account={'paid':0,'total':claims['total'],'claimed_count':0,'leaf_count':claims['count'],'bitmap':'00','rent_payer':'publisher'}
    async with store.pool.acquire() as c:
        await c.execute('UPDATE stage1_keeper_jobs SET publications=$2::jsonb WHERE id=$1',job_id,json.dumps({'set':{'account':account,'closed':None,'terms':{}}}))
    observed={'slot':100,'sets':{'set':account},'books':{},'receipts':[]}
    states={l['recipient']:'missing' for l in claims['leaves']}
    chain=SimpleNamespace(observe=AsyncMock(return_value=observed),claim_address=lambda *a:'set',
        destination=lambda s,l:l['recipient'],destination_fingerprint=lambda s,l:hashlib.sha256((s['mint']+l['recipient']).encode()).hexdigest(),
        destinations=AsyncMock(side_effect=lambda s,leaves,f:(100,states)),
        payout_batches=lambda s,leaves,**kw:[{'kind':'cash_claim','leaves':[l],'create_ata':l['create_ata']} for l in leaves],
        prepare=AsyncMock(side_effect=lambda s,op,f:{'signature':op['leaves'][0]['person'],'bytes':'offline','genesis':'local-test'}),
        submit=AsyncMock(),status_batch=AsyncMock(),transaction_evidence=AsyncMock(side_effect=lambda *a,**kw:{'signature':'offline','slot':100,'fee':5,'sponsored_ata_deposits_lamports':200}))
    monkeypatch.setattr(module,'reconcile',AsyncMock())
    return scope,job_id,claims,observed,states,chain


@pytest.mark.asyncio
async def test_sends_all_before_polling_and_reclaimed_ata_is_never_responsored(store,tmp_path,monkeypatch):
    scope,job_id,claims,observed,states,chain=await fixture(store,tmp_path,monkeypatch)
    worker=PayoutWorker(store,chain)
    assert await worker.run_once(scope['id'])=='submitted'
    assert chain.submit.await_count==len(claims['leaves'])
    assert chain.observe.await_count==1 and chain.status_batch.await_count==0
    async with store.pool.acquire() as c:
        from app.services.stage1_keeper_store import unpack
        actions=[unpack(r) for r in await c.fetch('SELECT * FROM stage1_keeper_payout_actions')]
    for action in actions: await worker._finish(scope,action,observed,{'slot':100})
    restarted=PayoutWorker(store,chain);chain.submit.reset_mock()
    assert await restarted.run_once(scope['id'])=='idle'
    chain.submit.assert_not_awaited()
    await restarted.run_once(scope['id'])
    async with store.pool.acquire() as c:
        assert await c.fetchval('SELECT count(*) FROM stage1_keeper_token_accounts')==len(claims['leaves'])
        assert await c.fetchval("SELECT count(*) FROM stage1_keeper_alerts WHERE kind='payout_unpayable'")==len(claims['leaves'])
        assert not await c.fetchval('SELECT payout_done FROM stage1_keeper_jobs WHERE id=$1',job_id)


@pytest.mark.asyncio
@pytest.mark.parametrize('problem',[SponsorUnfunded('low'),ValueError('unexpected private message')])
async def test_one_failed_item_does_not_prevent_other_payouts(store,tmp_path,monkeypatch,problem):
    scope,job_id,claims,observed,states,chain=await fixture(store,tmp_path,monkeypatch)
    victim=claims['leaves'][0]['person']
    def prepare(s,op,f):
        if op['leaves'][0]['person']==victim: raise problem
        return {'signature':op['leaves'][0]['person'],'bytes':'offline','genesis':'local-test'}
    chain.prepare.side_effect=prepare
    assert await PayoutWorker(store,chain).run_once(scope['id'])=='submitted'
    assert chain.submit.await_count==len(claims['leaves'])-1
    async with store.pool.acquire() as c:
        row=await c.fetchrow("SELECT state,signed,retries,retry_at>now() AS delayed FROM stage1_keeper_payout_actions WHERE signed IS NULL")
        assert row['state']=='ready' and row['retries']==1 and row['delayed']
        assert await c.fetchval("SELECT count(*) FROM stage1_keeper_payout_actions WHERE state='failed'")==0
        assert not await c.fetchval("SELECT EXISTS(SELECT 1 FROM stage1_keeper_alerts WHERE strpos(details::text,'private message')>0)")


@pytest.mark.asyncio
async def test_failed_close_keeps_work_ready_with_backoff(store,tmp_path,monkeypatch):
    scope,job_id,_,observed,_,chain=await fixture(store,tmp_path,monkeypatch)
    worker=PayoutWorker(store,chain)
    action=await worker.action(scope,job_id,{'kind':'funding_close','week':1,'funding':'book','rent_payer':'publisher'})
    await worker.persist_signed(action,{'signature':'close','bytes':'offline','genesis':'local-test'})
    chain.status_batch.return_value={'close':{'state':'failed','slot':100}}
    chain.observe.side_effect=RuntimeError('stop after failure was recorded')
    assert await worker.run_once(scope['id'])=='retry'
    async with store.pool.acquire() as c:
        row=await c.fetchrow('SELECT state,signed,retries,retry_at>now() AS delayed FROM stage1_keeper_payout_actions WHERE id=$1',action['id'])
        assert row['state']=='ready' and row['signed'] is None and row['retries']==1 and row['delayed']


@pytest.mark.asyncio
async def test_lost_creation_signature_recovers_sponsorship_from_paid_bitmap(store,tmp_path,monkeypatch):
    scope,job_id,claims,observed,_,chain=await fixture(store,tmp_path,monkeypatch)
    worker=PayoutWorker(store,chain)
    ref={'job_id':job_id,'role':-1,'index':0,'claim_set':'set'}
    fingerprint=chain.destination_fingerprint(scope,claims['leaves'][0])
    action=await worker.action(scope,job_id,{'kind':'cash_claim','week':1,'refs':[ref],'destination':fingerprint,'create_ata':True})
    await worker.persist_signed(action,{'signature':'lost','bytes':'offline','genesis':'local-test'})
    chain.status_batch.return_value={'lost':{'state':'expired','slot':100}}
    observed['sets']['set']['bitmap']='01'
    observed['receipts']=[{'claim_set':'set','index':0,'amount':claims['leaves'][0]['amount']}]
    await worker.run_once(scope['id'])
    async with store.pool.acquire() as c:
        assert await c.fetchval('SELECT EXISTS(SELECT 1 FROM stage1_keeper_token_accounts WHERE fingerprint=$1)',fingerprint)


@pytest.mark.asyncio
async def test_pending_signature_does_not_starve_other_people(store,tmp_path,monkeypatch):
    scope,job_id,claims,observed,_,chain=await fixture(store,tmp_path,monkeypatch)
    worker=PayoutWorker(store,chain);leaf=claims['leaves'][0]
    action=await worker.action(scope,job_id,{'kind':'cash_claim','week':1,'refs':[{'job_id':job_id,'role':-1,'index':0,'claim_set':'set'}],
        'destination':chain.destination_fingerprint(scope,leaf),'create_ata':True})
    await worker.persist_signed(action,{'signature':'waiting','bytes':'offline','genesis':'local-test'})
    chain.status_batch.return_value={'waiting':{'state':'pending'}}
    assert await worker.run_once(scope['id'])=='submitted'
    assert chain.submit.await_count==len(claims['leaves'])-1
    assert chain.observe.await_count==1


@pytest.mark.asyncio
async def test_failed_fee_is_idempotent_after_crash_before_retry_transition(store,tmp_path,monkeypatch):
    scope,job_id,_,_,_,chain=await fixture(store,tmp_path,monkeypatch)
    worker=PayoutWorker(store,chain)
    action=await worker.action(scope,job_id,{'kind':'funding_close','week':1,'funding':'book','rent_payer':'publisher'})
    await worker.persist_signed(action,{'signature':'offline','bytes':'offline','genesis':'local-test'})
    from app.services.stage1_keeper_store import unpack
    for _ in range(2):
        async with store.pool.acquire() as c: action=unpack(await c.fetchrow('SELECT * FROM stage1_keeper_payout_actions WHERE id=$1',action['id']))
        await worker.failed_evidence(action,{'slot':100})
    async with store.pool.acquire() as c:
        assert await c.fetchval("SELECT (evidence->>'fee')::int FROM stage1_keeper_payout_actions WHERE id=$1",action['id'])==5


@pytest.mark.asyncio
async def test_observed_ata_replaces_an_excluded_creation_and_cannot_be_responsored(store,tmp_path,monkeypatch):
    scope,_,claims,_,states,chain=await fixture(store,tmp_path,monkeypatch)
    worker=PayoutWorker(store,chain);leaf=claims['leaves'][0]
    fingerprint=chain.destination_fingerprint(scope,leaf)
    await worker.remember_destination(fingerprint,90,established=False)
    async with store.pool.acquire() as c:
        await c.execute('UPDATE stage1_keeper_token_accounts SET creation_excluded=true WHERE fingerprint=$1',fingerprint)
    await worker.remember_destination(fingerprint,100)
    await worker.run_once(scope['id'])
    assert all(call.args[1].get('destination')!=fingerprint for call in chain.prepare.await_args_list)
    async with store.pool.acquire() as c:
        assert await c.fetchval("SELECT count(*) FROM stage1_keeper_alerts WHERE kind='payout_unpayable' AND details->>'destination'=$1",fingerprint)==1


@pytest.mark.asyncio
async def test_funded_missing_lookup_requires_refund_witness_and_keeps_recovery_floor(store,tmp_path,monkeypatch):
    from app.services.stage1_keeper_store import unpack
    scope,job_id,_,_,_,chain=await fixture(store,tmp_path,monkeypatch)
    worker=PayoutWorker(store,chain)
    action=await worker.action(scope,job_id,{'kind':'lookup','week':1,'addresses':['ata'],'refs':[]})
    await worker.persist_signed(action,{'signature':'create','bytes':'offline','lookup_address':'table'})
    await store.reserve_lookup(scope,{'_job_id':job_id,'addresses':['ata']},'table')
    async with store.pool.acquire() as c:
        await c.execute("UPDATE stage1_keeper_lookup_tables SET deposited_lamports=200 WHERE address='table'")
        job=unpack(await c.fetchrow('SELECT * FROM stage1_keeper_jobs WHERE id=$1',job_id))
    chain.status_batch.return_value={'create':{'state':'expired','slot':100}}
    chain.lookup_close_witness=AsyncMock(return_value=None)
    await worker.recover_missing_lookup(scope,job,'table')
    async with store.pool.acquire() as c:
        assert not await c.fetchval("SELECT closed FROM stage1_keeper_lookup_tables WHERE address='table'")
    chain.lookup_close_witness.return_value={'signature':'refund','slot':150,'lookup_refund_lamports':200,'fee':5}
    assert await worker.recover_missing_lookup(scope,job,'table')==150
    async with store.pool.acquire() as c:
        assert await c.fetchval("SELECT closed FROM stage1_keeper_lookup_tables WHERE address='table'")
        assert await c.fetchval('SELECT floor_slot FROM stage1_keeper_jobs WHERE id=$1',job_id)==150


@pytest.mark.asyncio
async def test_lookup_reservation_cannot_be_reused_by_another_owner_or_after_refund(store,tmp_path,monkeypatch):
    scope,job_id,_,_,_,_=await fixture(store,tmp_path,monkeypatch)
    op={'_job_id':job_id,'addresses':['ata']}
    await store.reserve_lookup(scope,op,'table')
    await store.reserve_lookup(scope,op,'table')
    with pytest.raises(RuntimeError): await store.reserve_lookup(scope,{**op,'addresses':['other']},'table')
    async with store.pool.acquire() as c:
        await c.execute("UPDATE stage1_keeper_lookup_tables SET closed=true WHERE address='table'")
    with pytest.raises(RuntimeError): await store.reserve_lookup(scope,op,'table')


@pytest.mark.asyncio
async def test_ownerless_token_metadata_cannot_authorize_repeat_sponsorship():
    chain=KeeperChain('http://127.0.0.1:8899',str(Keypair().pubkey()),'/unused')
    scope={'mint':str(Keypair().pubkey())};leaf={'recipient':str(Keypair().pubkey())}
    fingerprint=chain.destination_fingerprint(scope,leaf)
    tx={'slot':100,'transaction':{'message':{'accountKeys':[chain.destination(scope,leaf)]}},
        'meta':{'err':None,'postTokenBalances':[{'mint':scope['mint'],'accountIndex':0}],
                'preBalances':[0],'postBalances':[200]}}
    chain.rpc=AsyncMock(return_value=tx)
    try:
        proof=await chain.sponsorship_evidence(scope,fingerprint,'created')
        assert proof and proof['established'] and proof['sponsored_ata_deposits_lamports']==200
        tx['meta']['postTokenBalances']=[]
        assert await chain.sponsorship_evidence(scope,fingerprint,'created') is None
        tx['meta']['err']='failed'
        assert (await chain.sponsorship_evidence(scope,fingerprint,'failed'))['established'] is False
    finally: await chain.close()


@pytest.mark.asyncio
async def test_failed_batch_isolates_bad_destination_with_only_one_alert(store,tmp_path,monkeypatch):
    scope,job_id,claims,_,states,chain=await fixture(store,tmp_path,monkeypatch)
    worker=PayoutWorker(store,chain)
    refs=[{'job_id':job_id,'role':-1,'index':l['index'],'claim_set':'set'} for l in claims['leaves'][:2]]
    parent=await worker.action(scope,job_id,{'kind':'cash_claim','week':1,'refs':refs})
    await worker.persist_signed(parent,{'signature':'batch','bytes':'offline','genesis':'local-test'})
    chain.status_batch.return_value={'batch':{'state':'failed','slot':100}}
    states[claims['leaves'][0]['recipient']]='frozen'
    assert await worker.run_once(scope['id'])=='submitted'
    assert chain.submit.await_count==len(claims['leaves'])-1
    async with store.pool.acquire() as c:
        alerts=await c.fetch('SELECT kind FROM stage1_keeper_alerts')
        assert [r['kind'] for r in alerts]==['payout_unpayable']
        assert await c.fetchval("SELECT (evidence->>'split')::bool FROM stage1_keeper_payout_actions WHERE id=$1",parent['id'])


@pytest.mark.asyncio
async def test_paid_proof_atomically_retains_sponsorship_attempt_through_real_erasure(store,tmp_path):
    from tests.services.test_stage1_keeper_erasure import deletion,PEOPLE
    from app.services.stage1_keeper_erasure import redact_export
    user,scope,_,_,claims,job_id=await settled_fixture(store,tmp_path)
    leaf=next(l for l in claims['leaves'] if l['person']==PEOPLE[0])
    fingerprint=hashlib.sha256(('program/mint/'+leaf['recipient']).encode()).hexdigest()
    worker=PayoutWorker(store,None)
    action=await worker.action(scope,job_id,{'kind':'cash_claim','week':1,'create_ata':True,'destination':fingerprint,
        'refs':[{'job_id':job_id,'role':-1,'index':leaf['index'],'claim_set':'set'}]})
    await worker.persist_signed(action,{'signature':'public-creation-signature','bytes':'private-signed-transaction'})
    async with store.pool.acquire() as c:
        await c.execute('UPDATE stage1_keeper_proofs SET paid_slot=NULL WHERE job_id=$1 AND person=$2',job_id,PEOPLE[0])
    await store.record_paid(scope,{'slot':100,'sets':{'set':{'hill':scope['hill'],'week':1}},
                                  'receipts':[{'claim_set':'set','index':leaf['index']}]})
    async with store.pool.acquire() as c:
        marker=dict(await c.fetchrow('SELECT * FROM stage1_keeper_token_accounts WHERE fingerprint=$1',fingerprint))
        assert marker['attempt_signature']=='public-creation-signature' and not marker['established']
        assert await c.fetchval('SELECT paid_slot FROM stage1_keeper_proofs WHERE job_id=$1 AND person=$2',job_id,PEOPLE[0])==100
        request,token=await deletion(c,user)
        prepared=json.loads(await c.fetchval('SELECT stage1_keeper_prepare_erasure($1,$2)',request,token))
        for entry in prepared['exports']:
            new_digest=redact_export(entry,tmp_path)
            await c.execute('SELECT stage1_keeper_record_erasure($1,$2,$3,$4,$5)',request,token,entry['job_id'],entry['digest'],new_digest)
        assert await c.fetchval('SELECT status FROM finalize_account_anonymization($1,$2,$3)',request,user,token)=='completed'
        assert dict(await c.fetchrow('SELECT * FROM stage1_keeper_token_accounts WHERE fingerprint=$1',fingerprint))==marker
        saved=json.loads(await c.fetchval('SELECT signed FROM stage1_keeper_payout_actions WHERE id=$1',action['id']))
        assert 'bytes' not in saved and saved['signature']=='public-creation-signature'
