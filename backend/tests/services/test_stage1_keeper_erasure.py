"""Actual deletion RPCs; settled claim/ride fixtures are explicitly offline evidence."""
import json
import uuid

import pytest

from app.services.stage1_keeper_allocation import allocate
from app.services.stage1_keeper_erasure import redact_export
from app.services.stage1_keeper_merkle import canonical, claim_set, digest, root_from_hashes
from app.services.stage1_keeper_snapshot import build_snapshot
from app.services.stage1_keeper_worker import proof_payload, verify_export, export_claims, Blocked
from tests.services.test_stage1_keeper_worker import store, migrated_template
from tests.services.test_stage1_keeper_snapshot import inputs, ride, PEOPLE

POLICY_FIXTURE = json.dumps({'allowed':True,'available':True,'destructive_boundary_available':True,'blockers':[]})


async def settled_fixture(store, directory):
    async with store.pool.acquire() as c:
        user = await c.fetchval("SELECT user_id FROM br_get_or_create_active_user(gen_random_uuid(),$1)", PEOPLE[0])
        scope = dict(await c.fetchrow("SELECT * FROM stage1_keeper_scopes"))
    data = inputs()
    data['canon_id'] = str(scope['canon_id'])
    data['closing']['assets'].append('mint2')
    data['closing']['board'] = [{'person':p,'time_s':60,'recorded_at':data['launch']+2} for p in PEOPLE[:5]]
    rows = [{**ride(i,receipt=f'r{i}'),'canon_id':data['canon_id']} for i in range(5)]
    snapshot = build_snapshot(data, rows)
    sources = [{'id':'book','born':1,'due':1,'kind':'yield','buckets':[1000,0,0,0,0]}]
    allocation = allocate(snapshot,sources)
    claims = claim_set(snapshot['context'],allocation['payments'],snapshot['recipients'])
    await store.archive_boundary(scope['id'],1,data)
    claim = await store.claim(scope['id'])
    payload = proof_payload(snapshot,allocation,claims,False)
    path,sha = export_claims(directory,claim['job']['id'],payload)
    await store.save_plan(claim,dict(snapshot=snapshot,sources=sources,allocation=allocation,claims=claims,
        operations=[{'kind':'publish'}],floor_slot=50,export_path=path,export_digest=sha,through_week=1))
    async with store.pool.acquire() as c:
        shared = {k:data[k] for k in ('opening','canon_id','launch')}
        shared.update(closing=snapshot['closing'],rows=snapshot['admissions'])
        await c.execute("INSERT INTO stage1_keeper_measurements VALUES('program','hill',1,$1::jsonb)",canonical(shared).decode())
        # Fixture marks the chain-paid state; production writes this only after
        # finalized receipt/leaf verification in check_accounting + record_paid.
        await c.execute("UPDATE stage1_keeper_proofs SET paid_slot=50 WHERE person=$1",PEOPLE[0])
        await c.execute("UPDATE stage1_keeper_jobs SET state='complete'")
    await store.release(claim)
    return user, scope, data, snapshot, claims, claim['job']['id']


async def deletion(c, user, wallet=PEOPLE[0]):
    request = uuid.uuid4()
    row = await c.fetchrow("SELECT * FROM create_account_deletion_request($1,$2,$3,true,$4,$5::jsonb,'{}')",
                           request,user,wallet,'a'*64,POLICY_FIXTURE)
    assert row['status'] == 'queued', row['blockers']
    token = await c.fetchval("SELECT worker_lease_token FROM claim_account_deletion_request($1,$2,300)",request,uuid.uuid4())
    await c.execute("SELECT * FROM authorize_account_deletion_storage($1,$2,$3::jsonb)",request,token,POLICY_FIXTURE)
    await c.execute("SELECT * FROM mark_account_deletion_storage_removed($1,$2,$3::jsonb)",request,token,POLICY_FIXTURE)
    return request,token


@pytest.mark.asyncio
async def test_real_finalizer_erases_exports_keys_times_and_preserves_roots_and_future_field(store,tmp_path):
    user,scope,data,snapshot,claims,job_id = await settled_fixture(store,tmp_path)
    async with store.pool.acquire() as c:
        request,token = await deletion(c,user)
        prepared = json.loads(await c.fetchval("SELECT stage1_keeper_prepare_erasure($1,$2)",request,token))
        assert prepared['request'] is None
        manifest = prepared['exports']
        assert len(manifest)==1
        entry=dict(manifest[0])
        assert await c.fetchval("SELECT stage1_keeper_validate_erasure($1,$2,$3,$4,$5::jsonb)",request,token,job_id,entry['digest'],json.dumps(entry['payload']))
        with pytest.raises(Exception,match='lease_or_manifest_changed'):
            await c.fetchval("SELECT stage1_keeper_validate_erasure($1,$2,$3,$4,'{}')",request,token,job_id,entry['digest'])
        with pytest.raises(Exception,match='lease_or_manifest_changed'):
            await c.fetchval("SELECT stage1_keeper_validate_erasure($1,$2,$3,$4,$5::jsonb)",request,uuid.uuid4(),job_id,entry['digest'],json.dumps(entry['payload']))
        # Kill-before-final-link orphan belongs to this exact export manifest.
        (tmp_path/f'.{job_id}-crash').write_bytes(b'private interrupted export')
        with pytest.raises(Exception,match='exports_not_removed'):
            await c.fetchval("SELECT status FROM finalize_account_anonymization($1,$2,$3)",request,user,token)
        for row in manifest:
            entry=dict(row)
            new_digest=redact_export(entry,tmp_path)
            assert redact_export(entry,tmp_path)==new_digest # crash/retry before receipt
            await c.execute("SELECT stage1_keeper_record_erasure($1,$2,$3,$4,$5)",request,token,row['job_id'],row['digest'],new_digest)
        assert len(list(tmp_path.glob('*.json')))==1
        assert not list(tmp_path.glob(f'.{job_id}-*'))
        assert await c.fetchval("SELECT status FROM finalize_account_anonymization($1,$2,$3)",request,user,token)=='completed'
        with pytest.raises(Exception,match='lease_or_manifest_changed'):
            await c.fetchval("SELECT stage1_keeper_validate_erasure($1,$2,$3,$4,$5::jsonb)",request,token,job_id,entry['digest'],json.dumps(entry['payload']))
        marker = await c.fetchval("SELECT wallet FROM users WHERE account_state='anonymized'")
        for table in ('stage1_keeper_boundaries','stage1_keeper_measurements','stage1_keeper_jobs','stage1_keeper_proofs','stage1_keeper_alerts'):
            assert not await c.fetchval(f"SELECT EXISTS(SELECT 1 FROM {table} t WHERE strpos(to_jsonb(t)::text,$1)>0)",PEOPLE[0])
        saved = json.loads(await c.fetchval("SELECT snapshot FROM stage1_keeper_jobs"))
        assert digest(saved['commitment_inputs'])==snapshot['commitment']
        anonymized = next(r for r in saved['admissions'] if r['person']==marker)
        assert not any(k in anonymized for k in ('ridden_at','uploaded_at','verified_at','ride_day_key'))
        boundary = await c.fetchrow("SELECT commitment_inputs,digest FROM stage1_keeper_boundaries")
        assert digest(json.loads(boundary['commitment_inputs']))==boundary['digest']
        saved_claims = json.loads(await c.fetchval("SELECT claims FROM stage1_keeper_jobs"))
        assert root_from_hashes(saved_claims['context'],saved_claims['leaves'])==(claims['root'],claims['total'])
        assert [l for l in saved_claims['leaves'] if l['person']!=marker]==[l for l in claims['leaves'] if l['person']!=PEOPLE[0]]
        await c.execute("INSERT INTO stage1_keeper_alerts(scope_id,kind,details) VALUES($1,'late',$2::jsonb)",scope['id'],json.dumps({'reason':'receipt mismatch for '+PEOPLE[0]}))
        alert=json.loads(await c.fetchval("SELECT details FROM stage1_keeper_alerts WHERE kind='late'"))
        assert set(alert)=={'withheld_private_details_sha256'}
        with pytest.raises(Exception,match='account_deleted'):
            await c.execute("UPDATE stage1_keeper_jobs SET snapshot=$1::jsonb WHERE id=$2",json.dumps({'reason':'receipt mismatch for '+PEOPLE[0]}),job_id)
        await c.execute("UPDATE stage1_keeper_scopes SET next_week=2")
    # Same frozen week on a second cash asset still has its anonymous sporting
    # fact. No private timestamp or original wallet is needed to reconstruct it.
    del store.snapshot
    two = await store.add_scope({**scope,'mint':'mint2','next_week':1})
    # Both assets' admitted list must have matched at the original boundary.
    async with store.pool.acquire() as c:
        shared = json.loads(await c.fetchval("SELECT inputs FROM stage1_keeper_measurements"))
    second = {**data,'context':['program','city','hill',1,'mint2'], 'opening':shared['opening'],'closing':shared['closing']}
    second.pop('recipients')
    await store.archive_boundary(two,1,second)
    claim = await store.claim(two)
    other_asset = await store.snapshot(claim,{})
    assert marker in other_asset['field_people'] and other_asset['field']
    assert other_asset['ascents'][marker]==1 and other_asset['board'][0]==saved['board'][0]
    later = inputs(2); later['canon_id']=str(scope['canon_id'])
    later.pop('recipients')
    await store.archive_boundary(scope['id'],2,later)
    claim = await store.claim(scope['id'])
    next_week = await store.snapshot(claim,{})
    assert marker in next_week['field_people'] and next_week['field'] and next_week['ascents']=={}
    from app.services.stage1_keeper_store import unpack
    async with store.pool.acquire() as c:
        erased_job=unpack(await c.fetchrow("SELECT * FROM stage1_keeper_jobs WHERE id=$1",job_id))
    verify_export(erased_job)
    from pathlib import Path
    exported=json.loads(Path(erased_job['export_path']).read_text())
    assert PEOPLE[0] not in json.dumps(exported)
    assert [l for l in exported['claims']['leaves'] if not l.get('identity_erased')]==[l for l in claims['leaves'] if l['person']!=PEOPLE[0]]
    Path(erased_job['export_path']).unlink()
    verify_export(erased_job) # regenerates the same redacted file from current DB
    assert json.loads(Path(erased_job['export_path']).read_text())==exported
    # Original archive retries remain idempotent after erasure, without writes.
    await store.archive_boundary(scope['id'],1,data)


@pytest.mark.asyncio
async def test_unpaid_value_gate_and_unauthorized_scrub(store,tmp_path):
    user,scope,data,snapshot,claims,job_id = await settled_fixture(store,tmp_path)
    async with store.pool.acquire() as c:
        await c.execute("UPDATE stage1_keeper_proofs SET paid_slot=NULL WHERE person=$1",PEOPLE[0])
        blockers=json.loads(await c.fetchval("SELECT br_account_deletion_db_blockers($1,$2)",user,PEOPLE[0]))
        assert any(b['source']=='stage1_keeper' and b['code']=='claim_remains' for b in blockers)
        async with c.transaction():
            await c.execute("SELECT set_config('app.account_deletion_request_id',$1,true)",str(uuid.uuid4()))
            with pytest.raises(Exception,match='immutable'):
                await c.execute("UPDATE stage1_keeper_boundaries SET inputs='{}'")


def test_export_erasure_refuses_changed_file_or_missing_volume(tmp_path):
    path,sha=export_claims(tmp_path,'a'*64,{'wallet':PEOPLE[0]})
    manifest={'path':path,'digest':sha,'job_id':'a'*64,'payload':{'identity_erased':True}}
    with pytest.raises(ValueError,match='volume'):
        redact_export(manifest,tmp_path/'missing')
    from pathlib import Path
    Path(path).write_text('changed')
    with pytest.raises(ValueError,match='digest'):
        redact_export(manifest,tmp_path)


def test_paused_export_worker_cannot_restore_a_later_erased_person(tmp_path,monkeypatch):
    import hashlib
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from app.services import stage1_keeper_erasure as module
    job='b'*64
    path,sha=export_claims(tmp_path,job,{'people':PEOPLE[:2]})
    first={'path':path,'digest':sha,'job_id':job,'payload':{'people':[PEOPLE[1]]}}
    second={**first,'digest':hashlib.sha256(canonical(first['payload'])+b'\n').hexdigest(),
            'payload':{'people':[]}}
    paused,resume,newer_done=threading.Event(),threading.Event(),threading.Event()
    replace=module.os.replace
    def delayed_replace(source,target):
        if threading.current_thread().name.startswith('old'):
            paused.set()
            assert resume.wait(5)
        replace(source,target)
    monkeypatch.setattr(module.os,'replace',delayed_replace)
    def newer_deletions():
        redact_export(first,tmp_path)
        redact_export(second,tmp_path)
        newer_done.set()
    with ThreadPoolExecutor(1,thread_name_prefix='old') as old, ThreadPoolExecutor(1) as newer:
        pending=old.submit(redact_export,first,tmp_path)
        assert paused.wait(5)
        next_deletions=newer.submit(newer_deletions)
        try:
            assert not newer_done.wait(.2), 'newer deletion overtook a paused export writer'
        finally:
            resume.set()
        pending.result()
        next_deletions.result()
    from pathlib import Path
    assert json.loads(Path(path).read_text())==second['payload']


@pytest.mark.asyncio
async def test_redaction_preserves_distinct_person_and_shared_recipient(store):
    async with store.pool.acquire() as c:
        payload={'leaves':[{'person':PEOPLE[0],'recipient':PEOPLE[1],'amount':10},
                           {'person':PEOPLE[2],'recipient':PEOPLE[1],'amount':20}],
                 'recipients':{PEOPLE[0]:PEOPLE[1]}}
        result=json.loads(await c.fetchval("SELECT stage1_keeper_redact($1::jsonb,$2,'anonymous:marker')",json.dumps(payload),PEOPLE[1]))
        assert [l['person'] for l in result['leaves']]==[PEOPLE[0],PEOPLE[2]]
        assert all(l['recipient']=='anonymous:marker' for l in result['leaves'])
        result=json.loads(await c.fetchval("SELECT stage1_keeper_redact($1::jsonb,$2,'anonymous:marker')",json.dumps(payload),PEOPLE[0]))
        assert result['leaves'][0]['recipient']==PEOPLE[1]
        assert result['recipients']=={'anonymous:marker':PEOPLE[1]}
