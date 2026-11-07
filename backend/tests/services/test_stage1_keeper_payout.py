"""Durable payout races with real PostgreSQL and explicit offline signatures."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.services.stage1_keeper_payout import PayoutWorker
from app.services.stage1_keeper_erasure import redact_export
from tests.services.test_stage1_keeper_worker import store,migrated_template
from tests.services.test_stage1_keeper_erasure import settled_fixture,deletion


@pytest.mark.asyncio
async def test_finalizer_locks_request_before_asset_and_stale_signer_cannot_restore_bytes(store,tmp_path):
    user,scope,_,_,claims,job_id=await settled_fixture(store,tmp_path)
    worker=PayoutWorker(store,SimpleNamespace())
    action=await worker.action(scope,job_id,{'kind':'cash_claim','week':1,'refs':[
        {'job_id':job_id,'role':-1,'index':0,'claim_set':'offline-set'}]})
    async with store.pool.acquire() as c:
        request,token=await deletion(c,user)
        prepared=json.loads(await c.fetchval('SELECT stage1_keeper_prepare_erasure($1,$2)',request,token))
        for entry in prepared['exports']:
            sha=redact_export(entry,tmp_path)
            await c.execute('SELECT stage1_keeper_record_erasure($1,$2,$3,$4,$5)',request,token,entry['job_id'],entry['digest'],sha)
    async with store.pool.acquire() as first,store.pool.acquire() as second:
        pending=None
        try:
            async with first.transaction():
                await first.execute('SELECT 1 FROM deletion_requests WHERE id=$1 FOR UPDATE',request)
                pid=second.get_server_pid()
                pending=asyncio.create_task(second.fetchval('SELECT status FROM finalize_account_anonymization($1,$2,$3)',request,user,token))
                for _ in range(100):
                    if await first.fetchval("SELECT wait_event='transactionid' FROM pg_stat_activity WHERE pid=$1",pid):
                        break
                    await asyncio.sleep(.01)
                else:
                    raise AssertionError('finalizer did not wait for the request row')
                name=f"stage1:{scope['program']}:{scope['mint']}"
                assert await first.fetchval('SELECT pg_try_advisory_xact_lock(hashtextextended($1,0))',name), 'finalizer inverted the request/asset lock order'
        finally:
            if pending:
                assert await asyncio.wait_for(pending,5)=='completed'
    assert not await worker.persist_signed(action,{'signature':'offline-stale','bytes':'private-payload'})
    async with store.pool.acquire() as c:
        assert not await c.fetchval("SELECT EXISTS(SELECT 1 FROM stage1_keeper_payout_actions WHERE strpos(coalesce(signed,'{}')::text,'private-payload')>0)")


@pytest.mark.asyncio
@pytest.mark.parametrize('block_kind', [None,'dung_payable_total_mismatch','dung_signed_operation_mismatch'])
async def test_restart_resubmits_exact_persisted_signature_before_new_planning(store,tmp_path,monkeypatch,block_kind):
    _,scope,_,_,_,job_id=await settled_fixture(store,tmp_path)
    chain=SimpleNamespace(status=AsyncMock(return_value={'state':'absent'}),submit=AsyncMock(),observe=AsyncMock(side_effect=RuntimeError('offline inventory unavailable after signature recovery')))
    worker=PayoutWorker(store,chain)
    action=await worker.action(scope,job_id,{'kind':'cash_claim','week':1,'refs':[{'job_id':job_id,'role':-1,'index':0,'claim_set':'offline-set'}]})
    signed={'signature':'offline-durable','bytes':'exact-signed-bytes','last_valid_block_height':200,'genesis':'local-test'}
    assert await worker.persist_signed(action,signed)
    assert not await worker.persist_signed(action,{**signed,'bytes':'replacement'})
    if block_kind:
        # A refused future publication must not strand the completed week's
        # already checked payout; ordinary inventory checks still follow.
        async with store.pool.acquire() as c:
            await c.execute('UPDATE stage1_keeper_scopes SET blocked=true,block_kind=$2 WHERE id=$1',scope['id'],block_kind)
    restarted=PayoutWorker(store,chain)
    assert await restarted.run_once(scope['id'])=='retry'
    chain.submit.assert_awaited_once_with(signed)
    chain.observe.assert_awaited_once()


@pytest.mark.asyncio
async def test_verified_payout_fence_recovery_preserves_completed_publication(store,tmp_path):
    _,scope,_,_,_,job_id=await settled_fixture(store,tmp_path)
    async with store.pool.acquire() as c:
        before=await c.fetchval('SELECT claims FROM stage1_keeper_jobs WHERE id=$1',job_id)
        await c.execute("UPDATE stage1_keeper_scopes SET blocked=true,block_kind='ledger_mismatch' WHERE id=$1",scope['id'])
    with pytest.raises(ValueError):
        await store.unblock(job_id)
    await store.unblock(job_id,token_reconciled=True)
    async with store.pool.acquire() as c:
        assert await c.fetchval('SELECT state FROM stage1_keeper_jobs WHERE id=$1',job_id)=='complete'
        assert await c.fetchval('SELECT claims FROM stage1_keeper_jobs WHERE id=$1',job_id)==before
        assert not await c.fetchval('SELECT blocked FROM stage1_keeper_scopes WHERE id=$1',scope['id'])


@pytest.mark.asyncio
async def test_closed_nonempty_dung_role_recovers_paid_proof_namespace(store,tmp_path):
    from app.services.stage1_keeper_payout import recover_closed_publication
    _,scope,_,_,_,job_id=await settled_fixture(store,tmp_path)
    scope={**scope,'kind':'dung'}
    async with store.pool.acquire() as c:
        await c.execute('UPDATE stage1_keeper_proofs SET role=0,paid_slot=NULL WHERE job_id=$1',job_id)
    witness={'rent_payer':'sponsor','leaf_count':1,'paid':0,'claimed_count':0,'sealed':False,'role':0,'dung':'mint-record'}
    observed={'slot':60,'sets':{}}
    chain=SimpleNamespace(closure_witness=AsyncMock(return_value={'signature':'offline-close','slot':55}))
    event={'claim_set':'role-set','root':[1]*32,'total':5,'leaf_count':1,'published_at':123}
    await recover_closed_publication(chain,scope,{'signed':{'publication_witness':{'set':witness}}},
        {'kind':'dung_root','week':1},observed,event,{'slot':50})
    observed['receipts']=[{'claim_set':'role-set','index':0,'role':0,'amount':5}]
    await store.record_paid(scope,observed)
    async with store.pool.acquire() as c:
        assert await c.fetchval('SELECT paid_slot FROM stage1_keeper_proofs WHERE job_id=$1 AND leaf_index=0',job_id)==60


@pytest.mark.asyncio
async def test_publication_close_witness_and_floor_survive_crash_before_advance(store,tmp_path):
    from app.services.stage1_keeper_payout import capture_publication
    _,scope,_,_,_,job_id=await settled_fixture(store,tmp_path)
    claim=await store.claim(scope['id'])
    claim['scope']['kind']='dung'
    claim['job']['signed']={'publication_witness':{'set':{'rent_payer':'sponsor','role':0,'dung':'mint-record'}}}
    event={'claim_set':'role-set','root':[1]*32,'total':5,'leaf_count':1,'published_at':123}
    chain=SimpleNamespace(dung_claim_address=lambda *args:'role-set',closure_witness=AsyncMock(return_value={'signature':'offline-close','slot':55}))
    await capture_publication(store,chain,claim,{'kind':'dung_root','week':1,'role':0,'root':'01'*32,'total':5,'count':1},
        {'slot':60,'sets':{}},{'slot':50,'events':[{'name':'Stage1DungRolePublished','data':event}]})
    # No advance()/record_paid(): this is the durable state after a crash here.
    async with store.pool.acquire() as c:
        saved=await c.fetchrow('SELECT floor_slot,publications FROM stage1_keeper_jobs WHERE id=$1',job_id)
        assert json.loads(saved['publications'])['role-set']['closed']['slot']==55
        assert saved['floor_slot']==60


@pytest.mark.asyncio
@pytest.mark.parametrize('field,inventory',[('publications','sets'),('funding_publication','books'),('dung_publication','mints')])
async def test_external_close_floor_is_atomic_before_accounting_can_crash(store,tmp_path,monkeypatch,field,inventory):
    from app.services import stage1_keeper_payout as module
    _,scope,_,_,_,job_id=await settled_fixture(store,tmp_path)
    record={'address':'record','account':{'hill':scope['hill'],'rent_payer':'sponsor','leaf_count':1,'total':5,'role_totals':[5,0]},'transaction':{'slot':50},'closed':None}
    async with store.pool.acquire() as c:
        await c.execute(f'UPDATE stage1_keeper_jobs SET {field}=$2::jsonb WHERE id=$1',job_id,json.dumps({'record':record} if field=='publications' else record))
    def crash(*args):
        raise RuntimeError('offline crash after witness persistence')
    monkeypatch.setattr(module,'check_accounting',crash)
    chain=SimpleNamespace(closure_witness=AsyncMock(return_value={'signature':'offline-close','slot':55}))
    with pytest.raises(RuntimeError,match='offline crash'):
        await module.reconcile(store,chain,scope,{'slot':60,'sets':{},'books':{},'mints':{}})
    async with store.pool.acquire() as c:
        saved=await c.fetchrow(f'SELECT floor_slot,{field} FROM stage1_keeper_jobs WHERE id=$1',job_id)
        retained=json.loads(saved[field])
        assert (retained['record'] if field=='publications' else retained)['closed']['slot']==55
        assert saved['floor_slot']==60


@pytest.mark.asyncio
async def test_expired_lookup_with_retained_table_cannot_create_another_deposit(store,tmp_path,monkeypatch):
    from app.services import stage1_keeper_payout as module
    _,scope,_,_,_,job_id=await settled_fixture(store,tmp_path)
    chain=SimpleNamespace(status=AsyncMock(return_value={'state':'expired','slot':100}),
        lookup_exists=AsyncMock(return_value=True),observe=AsyncMock(side_effect=RuntimeError('stop after retry was recorded')))
    worker=PayoutWorker(store,chain)
    action=await worker.action(scope,job_id,{'kind':'lookup','week':1,'addresses':['recipient-ata'],'refs':[]})
    signed={'signature':'lost-history','bytes':'preserved','lookup_address':'existing-table'}
    assert await worker.persist_signed(action,signed)
    monkeypatch.setattr(module,'reconcile',AsyncMock())
    assert await worker.run_once(scope['id'])=='retry'
    chain.lookup_exists.assert_awaited_once_with('existing-table',100)
    async with store.pool.acquire() as c:
        assert await c.fetchval('SELECT state FROM stage1_keeper_payout_actions WHERE id=$1',action['id'])=='ready'
        assert json.loads(await c.fetchval('SELECT signed FROM stage1_keeper_payout_actions WHERE id=$1',action['id']))==signed
        assert await c.fetchval("SELECT count(*) FROM stage1_keeper_alerts WHERE kind='lookup_history_wait'")==1


@pytest.mark.asyncio
async def test_rent_refund_blocks_erasure_until_closed_then_removes_all_witness_preimages(store,tmp_path):
    from solders.keypair import Keypair
    _,scope,_,_,_,job_id=await settled_fixture(store,tmp_path)
    wallet=str(Keypair().pubkey())  # Permissionless opener, not a claim recipient.
    record={'address':'funding','account':{'rent_payer':wallet},'closed':None}
    signed={'signature':'public-signature','bytes':'opaque-private-transaction','publication_witness':{'funding':record['account']}}
    async with store.pool.acquire() as c:
        user=await c.fetchval('SELECT user_id FROM br_get_or_create_active_user(gen_random_uuid(),$1)',wallet)
        await c.execute('UPDATE stage1_keeper_jobs SET funding_publication=$2::jsonb WHERE id=$1',job_id,json.dumps(record))
        blockers=json.loads(await c.fetchval('SELECT br_account_deletion_db_blockers($1,$2)',user,wallet))
        assert any(b['source']=='stage1_keeper' and b['code']=='claim_remains' for b in blockers)
        record['closed']={'slot':55,'signature':'closed'}
        await c.execute('UPDATE stage1_keeper_jobs SET funding_publication=$2::jsonb,signed=$3::jsonb,publications=$4::jsonb,dung_publication=$2::jsonb WHERE id=$1',
            job_id,json.dumps(record),json.dumps(signed),json.dumps({'set':record}))
        await c.execute("INSERT INTO stage1_keeper_attempts(job_id,signature,operation_index,signed,finalized_slot) VALUES($1,'public-signature',0,$2::jsonb,50)",job_id,json.dumps(signed))
        await c.execute('INSERT INTO stage1_keeper_reconciliations(job_id,evidence) VALUES($1,$2::jsonb)',job_id,json.dumps(record))
        await c.execute("INSERT INTO stage1_keeper_payout_actions(id,scope_id,job_id,operation,state,signed,attempts,evidence) VALUES('refund',$1,$2,$3::jsonb,'complete',$4::jsonb,$5::jsonb,$6::jsonb)",
            scope['id'],job_id,json.dumps({'kind':'funding_close','week':1,'rent_payer':wallet}),json.dumps(signed),json.dumps([signed]),json.dumps(record))
        request,token=await deletion(c,user,wallet)
        # The final close observation may arrive while deletion is pending.
        await c.execute('UPDATE stage1_keeper_jobs SET funding_publication=$2::jsonb WHERE id=$1',job_id,json.dumps(record))
        prepared=json.loads(await c.fetchval('SELECT stage1_keeper_prepare_erasure($1,$2)',request,token))
        for entry in prepared['exports']:
            sha=redact_export(entry,tmp_path)
            await c.execute('SELECT stage1_keeper_record_erasure($1,$2,$3,$4,$5)',request,token,entry['job_id'],entry['digest'],sha)
        assert await c.fetchval('SELECT status FROM finalize_account_anonymization($1,$2,$3)',request,user,token)=='completed'
        for table in ('stage1_keeper_jobs','stage1_keeper_attempts','stage1_keeper_reconciliations','stage1_keeper_payout_actions'):
            assert not await c.fetchval(f'SELECT EXISTS(SELECT 1 FROM {table} t WHERE strpos(to_jsonb(t)::text,$1)>0 OR strpos(to_jsonb(t)::text,$2)>0)',wallet,signed['bytes']),table
        with pytest.raises(Exception,match='account_deleted'):
            await c.execute('UPDATE stage1_keeper_jobs SET funding_publication=$2::jsonb WHERE id=$1',job_id,json.dumps(record))


@pytest.mark.asyncio
async def test_suspended_close_job_refuses_stale_signature_without_proof_refs(store,tmp_path):
    _,scope,_,_,_,job_id=await settled_fixture(store,tmp_path)
    worker=PayoutWorker(store,SimpleNamespace())
    action=await worker.action(scope,job_id,{'kind':'funding_close','week':1,'funding':'book','rent_payer':'sponsor'})
    async with store.pool.acquire() as c:
        await c.execute('UPDATE stage1_keeper_jobs SET export_suspended=true WHERE id=$1',job_id)
    assert not await worker.persist_signed(action,{'signature':'offline-stale-close','bytes':'private-refund'})
