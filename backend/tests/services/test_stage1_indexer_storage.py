"""Real PostgreSQL deletion and durable-source behavior; synthetic source records."""
import hashlib
import json
import copy
from pathlib import Path

import pytest
from app.services.stage1_keeper_merkle import canonical, digest
from app.services.stage1_keeper_erasure import redact_export
from tests.services.test_stage1_keeper_worker import store, migrated_template
from tests.services.test_stage1_keeper_erasure import deletion
from tests.services.test_stage1_boundary import sources, key, LAUNCH


@pytest.mark.asyncio
async def test_indexer_erasure_keeps_shared_checkpoints_and_unrelated_archives(store,tmp_path):
    wallet=key(8)
    checkpoint=json.loads((Path(__file__).parents[3]/'indexer/test/fixtures/stage1-boundaries.json').read_text())[0]['checkpoint']
    tx=dict(signature='sig',slot=101,block_time=LAUNCH-1,person=wallet,writes=[key(5)])
    payload=[{'opening':{'person':wallet}}]
    ident=digest(['boundary-export']);path=tmp_path/(ident+'.json')
    data=canonical(payload)+b'\n';path.write_bytes(data)
    async with store.pool.acquire() as c:
        user=await c.fetchval('SELECT user_id FROM br_get_or_create_active_user(gen_random_uuid(),$1)',wallet)
        await c.execute('INSERT INTO stage1_indexer_checkpoints(digest,genesis,program,slot,block_time,checkpoint) VALUES($1,$2,$3,100,$4,$5::jsonb)',digest(checkpoint),'local-test',key(9),LAUNCH-1,json.dumps(checkpoint))
        await c.execute('INSERT INTO stage1_indexer_transactions VALUES($1,$2,$3,$4::jsonb,$5)','sig',101,LAUNCH-1,json.dumps(tx),digest(tx))
        await c.execute('INSERT INTO indexed_stage1_recipients(address,data,chain_slot) VALUES($1,$2::jsonb,100)',key(10),json.dumps({'person':wallet,'recipient':wallet}))
        await c.execute('INSERT INTO stage1_boundary_exports(id,path,digest,payload) VALUES($1,$2,$3,$4::jsonb)',ident,str(path),hashlib.sha256(data).hexdigest(),json.dumps(payload))
        # Another hill depends on the same full-GPA source without naming this wallet in its archive.
        source_id=digest(['shared-source'])
        await c.execute('INSERT INTO stage1_boundary_witnesses VALUES($1,$2,$3,$4,$5,$6::jsonb)',source_id,'local-test',key(9),key(20),LAUNCH,json.dumps({'source':checkpoint}))
        dependent=[{'inputs':{'opening':{'producer_witness':source_id},'closing':{'producer_witness':source_id}}}]
        await c.execute("INSERT INTO stage1_boundary_tasks(genesis,program,hill,week,state,archive) VALUES($1,$2,$3,0,'complete',$4::jsonb)",'local-test',key(9),key(20),json.dumps(dependent))
        assert await c.fetchval('SELECT stage1_keeper_has_personal_data($1)',wallet)
        request,token=await deletion(c,user,wallet)
        prepared=json.loads(await c.fetchval('SELECT stage1_keeper_prepare_erasure($1,$2)',request,token))
        entry,=prepared['exports'];assert entry['kind']=='boundary'
        with pytest.raises(Exception,match='exports_not_removed'):
            await c.fetchval('SELECT status FROM finalize_account_anonymization($1,$2,$3)',request,user,token)
        assert await c.fetchval('SELECT stage1_boundary_validate_erasure($1,$2,$3,$4,$5::jsonb)',request,token,ident,entry['digest'],json.dumps(entry['payload']))
        redacted=redact_export(entry,tmp_path)
        await c.execute('SELECT stage1_boundary_record_erasure($1,$2,$3,$4,$5)',request,token,ident,entry['digest'],redacted)
        assert await c.fetchval('SELECT status FROM finalize_account_anonymization($1,$2,$3)',request,user,token)=='completed'
        assert wallet not in path.read_text()
        assert await c.fetchval('SELECT state FROM stage1_boundary_tasks')=='complete'
        assert await c.fetchval('SELECT count(*) FROM stage1_boundary_witnesses')==1
        assert not json.loads(await c.fetchval('SELECT witness FROM stage1_indexer_transactions')).get('erased')
        assert len(json.loads(await c.fetchval('SELECT checkpoint FROM stage1_indexer_checkpoints'))['accounts'])==len(checkpoint['accounts'])
        assert wallet not in await c.fetchval('SELECT data::text FROM indexed_stage1_recipients')
        assert not await c.fetchval('SELECT stage1_keeper_has_personal_data($1)',wallet)
        await c.execute('INSERT INTO indexed_stage1_recipients(address,data,chain_slot) VALUES($1,$2::jsonb,200)',key(10),json.dumps({'person':wallet}))
        assert wallet not in await c.fetchval('SELECT data::text FROM indexed_stage1_recipients')


@pytest.mark.asyncio
async def test_two_riders_tied_board_erasure_preserves_verified_survivor_and_import_prunes(store,tmp_path):
    from app.services.stage1_boundary import materialize_boundary,verify_boundary,verify_retained_boundary,closing_envelope
    vector=json.loads((Path(__file__).parents[3]/'indexer/test/fixtures/stage1-boundaries.json').read_text())[0]
    wallet,other=key(8),key(10)
    opening=materialize_boundary(vector['checkpoint'],vector['coverage'],[],vector['hill'],LAUNCH)
    closing=materialize_boundary(vector['checkpoint'],vector['coverage'],[],vector['hill'],LAUNCH+604800)
    scope=await store.add_scope(dict(program=key(9),city=key(1),hill=key(2),mint=key(7),canon_id=opening['canon_id'],launch=LAUNCH,next_week=0))
    second=await store.add_scope(dict(program=key(9),city=key(1),hill=key(2),mint=key(11),canon_id=opening['canon_id'],launch=LAUNCH,next_week=0))
    inputs=dict(context=[key(9),key(1),key(2),0,key(7)],canon_id=opening['canon_id'],launch=LAUNCH,
        opening={**opening['opening'],'producer_witness':opening['digest']},closing=closing_envelope(closing))
    async with store.pool.acquire() as c:
        user=await c.fetchval('SELECT user_id FROM br_get_or_create_active_user(gen_random_uuid(),$1)',wallet)
        for a in vector['checkpoint']['accounts']:
            if a['type'] in ('Stage1HillBond','Stage1CityConfig'):
                table='indexed_stage1_hills' if a['type']=='Stage1HillBond' else 'indexed_stage1_cities'
                await c.execute(f'INSERT INTO {table}(address,data,chain_slot) VALUES($1,$2::jsonb,100)',a['address'],json.dumps(a['fields']))
        for value in (opening,closing):
            await c.execute('INSERT INTO stage1_boundary_witnesses VALUES($1,$2,$3,$4,$5,$6::jsonb)',value['digest'],'local-test',key(9),key(2),value['boundary'],json.dumps(value))
            await verify_retained_boundary(c,value['digest'],value)
        archive=[dict(scope_id=scope,week=0,inputs=inputs),dict(scope_id=second,week=0,inputs={**inputs,'context':[key(9),key(1),key(2),0,key(11)]})]
        await c.execute("INSERT INTO stage1_boundary_tasks(genesis,program,hill,week,state,archive) VALUES('local-test',$1,$2,0,'complete',$3::jsonb)",key(9),key(2),json.dumps(archive))
        assert json.loads(await c.fetchval('SELECT stage1_refresh_archive($1::jsonb,$2,$3)',json.dumps(archive),key(98),'anonymous:unrelated'))==archive
        export_id=digest(['two-riders-export']);path=tmp_path/(export_id+'.json')
        data=canonical(archive)+b'\n';path.write_bytes(data)
        await c.execute('INSERT INTO stage1_boundary_exports(id,path,digest,payload) VALUES($1,$2,$3,$4::jsonb)',export_id,str(path),hashlib.sha256(data).hexdigest(),json.dumps(archive))
    await store.archive_boundary(scope,0,inputs)
    # An imported week may have unprocessed assets; keep this producer archive
    # pending while exercising the keeper's actual shared measurement freeze.
    claim={'scope':dict(id=scope,program=key(9),city=key(1),hill=key(2),mint=key(7),canon_id=opening['canon_id'],launch=LAUNCH),'job':{'week':0}}
    del store.snapshot  # This regression exercises KeeperStore, not the worker fixture stub.
    before=await store.snapshot(claim,{})
    assert set(before['rider_tie_ranks'])=={wallet,other}
    async with store.pool.acquire() as c:
        request,token=await deletion(c,user,wallet)
        prepared=json.loads(await c.fetchval('SELECT stage1_keeper_prepare_erasure($1,$2)',request,token))
        entry,=prepared['exports'];assert entry['kind']=='boundary'
        redacted=redact_export(entry,tmp_path)
        await c.execute('SELECT stage1_boundary_record_erasure($1,$2,$3,$4,$5)',request,token,export_id,entry['digest'],redacted)
        assert await c.fetchval('SELECT status FROM finalize_account_anonymization($1,$2,$3)',request,user,token)=='completed'
        assert await c.fetchval('SELECT state FROM stage1_boundary_tasks WHERE hill=$1',key(2))=='complete'
        raw=await c.fetchval('SELECT witness FROM stage1_boundary_witnesses WHERE digest=$1',closing['digest'])
        assert wallet not in raw
        retained=json.loads(raw)
        checked=await verify_retained_boundary(c,closing['digest'],retained)
        survivor=next(r for r in checked['records']['board'] if r['person']==other)
        assert survivor==next(r for r in closing['records']['board'] if r['person']==other)
        board=next(a for a in checked['source']['checkpoint']['accounts'] if a['type']=='VaultLeaderboard')
        original=next(a for a in vector['checkpoint']['accounts'] if a['type']=='VaultLeaderboard')
        assert [p for p in board['parts'] if p['path'][:2]==['entries','1']]==[p for p in original['parts'] if p['path'][:2]==['entries','1']]
        assert any(p.get('erased') for p in board['parts'])
        receipt=await c.fetchrow('SELECT * FROM stage1_boundary_redactions WHERE witness_id=$1',closing['digest'])
        tampered=copy.deepcopy(retained)
        next(p for p in next(a for a in tampered['source']['checkpoint']['accounts'] if a['type']=='VaultLeaderboard')['parts'] if p['path']==['entries','1','timeS'])['data']='AAAAAA=='
        with pytest.raises(ValueError): verify_boundary(tampered,require_raw=True,redaction_receipt=receipt)
        remaining=json.loads(await c.fetchval('SELECT archive FROM stage1_boundary_tasks WHERE hill=$1',key(2)))
        assert [e['scope_id'] for e in remaining]==[second]
        assert not await c.fetchval('SELECT stage1_keeper_has_personal_data($1)',wallet)
    after=await store.snapshot(claim,{})
    assert other in after['board'] and other in after['rider_tie_ranks']
    assert after['rider_tie_ranks'][other]==before['rider_tie_ranks'][other]
    assert sorted(after['rider_tie_ranks'].values())==sorted(before['rider_tie_ranks'].values())
    from app.services.stage1_keeper_allocation import allocate
    # Survivor's allocation remains calculable after the other person's erasure.
    assert after['closing']['seats'][1]==other
    assert allocate(after,[dict(id='source',born=0,due=0,kind='sponsor',buckets=[100,0,0,0,0])])['holds']==allocate(before,[dict(id='source',born=0,due=0,kind='sponsor',buckets=[100,0,0,0,0])])['holds']
    exported=json.loads(path.read_text())
    assert [e['scope_id'] for e in exported]==[second]
    for entry in exported:
        await store.archive_boundary(entry['scope_id'],entry['week'],entry['inputs'])
        await store.archive_boundary(entry['scope_id'],entry['week'],entry['inputs'])
    async with store.pool.acquire() as c:
        assert await c.fetchval('SELECT imported_at IS NOT NULL FROM stage1_boundary_tasks WHERE hill=$1',key(2))
        assert await c.fetchval('SELECT count(*) FROM stage1_boundary_witnesses WHERE hill=$1',key(2))==0
        frozen=json.loads(await c.fetchval('SELECT inputs FROM stage1_keeper_boundaries WHERE scope_id=$1',scope))
        assert other in frozen['closing']['seats']


@pytest.mark.asyncio
async def test_erasure_pda_verifier_matches_independent_solders_and_rejects_forgery(store):
    from solders.pubkey import Pubkey
    raw=[hashlib.sha256(str(i).encode()).digest() for i in range(256)]
    p=2**255-19
    raw += [(y+(sign<<255)).to_bytes(32,'little') for y in (0,1,p-1,p,p+1,2**255-1) for sign in (0,1)]
    program=key(9)
    async with store.pool.acquire() as c:
        rows=await c.fetch('SELECT stage1_source_on_curve(x) AS value FROM unnest($1::bytea[]) x',raw)
        assert [r['value'] for r in rows]==[Pubkey(x).is_on_curve() for x in raw]
        for n in (0,1,2,255,2**63,2**64-1):
            for exiting in (False,True):
                fields={'owner':key(8),'depositId':str(n),'exiting':exiting,'exitRequest':key(10)}
                seeds=[b's1v1_exit',bytes(Pubkey.from_string(key(10)))] if exiting else [b's1v1_lot',bytes(Pubkey.from_string(key(8))),n.to_bytes(8,'little')]
                expected,bump=Pubkey.find_program_address(seeds,Pubkey.from_string(program))
                assert await c.fetchval('SELECT stage1_source_lot_address($1,$2::jsonb)',program,json.dumps(fields))==str(expected)
                if not exiting and n==0:assert bump<255
        vector=json.loads((Path(__file__).parents[3]/'indexer/test/fixtures/stage1-boundaries.json').read_text())[2]
        cp=vector['checkpoint']
        await c.execute('SELECT stage1_source_pristine($1::jsonb)',json.dumps(cp))
        next(a for a in cp['accounts'] if a['type']=='Stage1PledgeLot')['address']=key(17)
        with pytest.raises(Exception,match='source_lot_pda_mismatch'):
            await c.execute('SELECT stage1_source_pristine($1::jsonb)',json.dumps(cp))


@pytest.mark.asyncio
async def test_finalized_sources_and_namespace_are_immutable(store):
    checkpoint,_=sources()
    async with store.pool.acquire() as c:
        await c.execute('INSERT INTO stage1_indexer_network(singleton,genesis,program,from_slot,from_time,through_slot,through_time,through_epoch) VALUES(true,$1,$2,100,$3,100,$3,0)','local-test',key(9),LAUNCH-1)
        with pytest.raises(Exception,match='immutable'):
            await c.execute("UPDATE stage1_indexer_network SET genesis='foreign'")
        await c.execute('INSERT INTO stage1_indexer_checkpoints(digest,genesis,program,slot,block_time,checkpoint) VALUES($1,$2,$3,100,$4,$5::jsonb)',digest(checkpoint),'local-test',key(9),LAUNCH-1,json.dumps(checkpoint))
        with pytest.raises(Exception,match='immutable'):
            await c.execute('DELETE FROM stage1_indexer_checkpoints')


@pytest.mark.asyncio
@pytest.mark.parametrize('lot_state',['none','cancelled','historical_live'])
async def test_deletion_before_witness_and_future_capture_keep_shared_record_bytes(store,lot_state):
    import base64
    import subprocess
    from solders.pubkey import Pubkey
    from app.services.stage1_boundary import materialize_boundary,verify_retained_boundary,verify_boundary
    from app.services.stage1_boundary_source import verify_accounts
    vector=json.loads((Path(__file__).parents[3]/'indexer/test/fixtures/stage1-boundaries.json').read_text())[0 if lot_state=='none' else 2]
    wallet,other=key(8),key(10)
    cp=vector['checkpoint']
    cp['accounts']=[a for a in cp['accounts'] if a['type']!='Stage1PledgeLot']
    if lot_state!='none':
        lot=next(a for a in json.loads((Path(__file__).parents[3]/'indexer/test/fixtures/stage1-boundaries.json').read_text())[2]['checkpoint']['accounts'] if a['type']=='Stage1PledgeLot')
        def change(row,changes):
            row['fields'].update(changes)
            for part in row['parts']:
                if len(part['path'])==1 and part['path'][0] in changes:
                    value=changes[part['path'][0]]
                    data=bytes(Pubkey.from_string(value)) if part['kind']=='publicKey' else int(value).to_bytes(part['length'],'little')
                    part.update(data=base64.b64encode(data).decode(),digest=hashlib.sha256(data).hexdigest())
            row['parts_digest']=digest([{k:v for k,v in p.items() if k!='data'} for p in row['parts']])
            row['raw_digest']=hashlib.sha256(b''.join(base64.b64decode(p['data']) for p in row['parts'])).hexdigest()
        if lot_state=='cancelled':change(lot,{'cancelled':True,'units':'0','basisLamports':'0'})
        cp['accounts'].append(lot)
        surviving=copy.deepcopy(lot);change(surviving,{'owner':other,'cancelled':False,'units':'100','basisLamports':'100'})
        surviving['address']=str(Pubkey.find_program_address([b's1v1_lot',bytes(Pubkey.from_string(other)),int(surviving['fields']['depositId']).to_bytes(8,'little')],Pubkey.from_string(cp['program']))[0])
        cp['accounts'].append(surviving)
    original_value=materialize_boundary(cp,vector['coverage'],[],vector['hill'],LAUNCH)
    board=next(a for a in cp['accounts'] if a['type']=='VaultLeaderboard')
    raw=b''.join(base64.b64decode(p['data']) for p in board['parts'])
    padding=bytes(Pubkey.from_string(wallet))
    board['parts'].append(dict(path=['$padding'],kind='bytes',offset=len(raw),length=32,digest=hashlib.sha256(padding).hexdigest(),data=base64.b64encode(padding).decode()))
    board['parts_digest']=digest([{k:v for k,v in p.items() if k!='data'} for p in board['parts']])
    board['raw_digest']=hashlib.sha256(raw+padding).hexdigest()
    verify_accounts(cp['accounts'])
    async with store.pool.acquire() as c:
        for original in cp['accounts']:
            raw_original=b''.join(base64.b64decode(p['data']) for p in original['parts'])
            decoded=json.loads(await c.fetchval("SELECT stage1_source_read(stage1_source_layout()->$1,$2,8,ARRAY[]::text[],stage1_source_layout())",original['type'],raw_original))
            assert decoded['value']==original['fields'],original['type']
            expected=[{k:v for k,v in p.items() if k not in ('digest','data')} for p in original['parts'][1:] if p['path']!=['$padding']]
            assert decoded['spans']==expected,original['type']
        user=await c.fetchval('SELECT user_id FROM br_get_or_create_active_user(gen_random_uuid(),$1)',wallet)
        await c.execute('INSERT INTO stage1_indexer_checkpoints(digest,genesis,program,hill,slot,block_time,checkpoint) VALUES($1,$2,$3,$4,$5,$6,$7::jsonb)',digest(cp),cp['genesis'],cp['program'],vector['hill'],cp['slot'],cp['block_time'],json.dumps(cp))
        request,token=await deletion(c,user,wallet)
        await c.fetchval('SELECT stage1_keeper_prepare_erasure($1,$2)',request,token)
        assert await c.fetchval('SELECT status FROM finalize_account_anonymization($1,$2,$3)',request,user,token)=='completed'
        retained=json.loads(await c.fetchval('SELECT checkpoint FROM stage1_indexer_checkpoints'))
        future=json.loads(await c.fetchval('SELECT stage1_indexer_filter_checkpoint($1::jsonb)',json.dumps(cp)))
        for source in (retained,future):
            assert wallet not in json.dumps(source)
            account=next(a for a in source['accounts'] if a['type']=='VaultLeaderboard')
            assert not any(a.get('omitted') for a in source['accounts'])
            assert account['parts'][-1]['discarded'] and 'data' not in account['parts'][-1]
            assert all(padding not in base64.b64decode(p['data']) for a in source['accounts'] for p in a['parts'] if 'data' in p)
            value=materialize_boundary(source,vector['coverage'],[],vector['hill'],LAUNCH)
            assert value['opening']['backing']==original_value['opening']['backing']
            with pytest.raises(ValueError,match='unverified source redaction'):
                verify_boundary(value,require_raw=True)
            checked=await verify_retained_boundary(c,value['digest'],value)
            script=Path(__file__).with_name('stage1_boundary_rebuild.cjs')
            rebuilt=subprocess.run(['node',str(script)],input=json.dumps(dict(checkpoint=source,coverage=vector['coverage'],transactions=[],hill=vector['hill'],boundary=LAUNCH)),text=True,capture_output=True,timeout=30)
            assert rebuilt.returncode==0,rebuilt.stderr
            assert json.loads(rebuilt.stdout)==checked
            assert checked['records']['seats'][1]==other
            tx=dict(signature='survivor-improves',slot=101,block_time=LAUNCH-5,block_index=0,writes=[account['address']],
                instructions=[dict(name='recordClimbCompletionV2')],events=[dict(name='ClimbCompletedV2',fields=dict(vaultId=account['fields']['vaultId'],rider=other,timeS=50,completedAt=str(LAUNCH-5)))])
            improved=materialize_boundary(source,vector['coverage'],[tx],vector['hill'],LAUNCH)
            assert improved['records']['seats'][0]==other
            assert improved['records']['board'][0]['time_s']==50
            assert next(r for r in checked['records']['board'] if r['person']==other)==dict(person=other,time_s=60,recorded_at=LAUNCH-10)
            if lot_state!='none':
                own_lot=next(a for a in cp['accounts'] if a['type']=='Stage1PledgeLot' and a['fields']['owner']==wallet)
                tx=dict(signature='owned-lot-change',slot=101,block_time=LAUNCH-1,writes=[own_lot['address']],instructions=[dict(name='beginWithdrawal',keys=[own_lot['address']])],events=[])
                from app.services.stage1_boundary import MissingBoundary
                with pytest.raises(MissingBoundary,match='unrecoverable_boundary_mutation'):
                    materialize_boundary(source,vector['coverage'],[tx],vector['hill'],LAUNCH)

        forged=copy.deepcopy(cp)
        next(a for a in forged['accounts'] if a['type']=='VaultLeaderboard')['record_order']=[other,wallet]
        with pytest.raises(Exception,match='source_must_be_pristine'):
            await c.fetchval('SELECT stage1_indexer_filter_checkpoint($1::jsonb)',json.dumps(forged))
        forged=copy.deepcopy(cp)
        board=next(a for a in forged['accounts'] if a['type']=='VaultLeaderboard')
        board['fields']['entries'][0]['recordedAt']=str(LAUNCH-100)
        with pytest.raises(Exception,match='source_layout_disagrees'):
            await c.fetchval('SELECT stage1_indexer_filter_checkpoint($1::jsonb)',json.dumps(forged))


@pytest.mark.asyncio
async def test_mislabeled_wallet_span_cannot_pass_verification_or_witness_erasure(store):
    from app.services.stage1_boundary import materialize_boundary, verify_boundary
    vector=json.loads((Path(__file__).parents[3]/'indexer/test/fixtures/stage1-boundaries.json').read_text())[0]
    board=next(a for a in vector['checkpoint']['accounts'] if a['type']=='VaultLeaderboard')
    next(p for p in board['parts'] if p['path']==['entries','0','user'])['path']=['shadow']
    board['parts'].append(dict(path=['entries','0','user'],kind='publicKey',
        offset=board['parts'][-1]['offset']+board['parts'][-1]['length'],
        length=0,digest=hashlib.sha256(b'').hexdigest(),data=''))
    board['parts_digest']=digest([{k:v for k,v in p.items() if k not in ('data','discarded')} for p in board['parts']])
    value=materialize_boundary(vector['checkpoint'],vector['coverage'],[],vector['hill'],LAUNCH)
    with pytest.raises(ValueError,match='independent source span layout disagrees'):
        verify_boundary(value,require_raw=True)
    async with store.pool.acquire() as c:
        user=await c.fetchval('SELECT user_id FROM br_get_or_create_active_user(gen_random_uuid(),$1)',key(8))
        await c.execute('INSERT INTO stage1_boundary_witnesses VALUES($1,$2,$3,$4,$5,$6::jsonb)',
            value['digest'],'local-test',key(9),key(2),LAUNCH,json.dumps(value))
        # The former verifier accepted this source. Simulate that historical
        # receipt to exercise the SQL defense independently of the Python fix.
        await c.execute('INSERT INTO stage1_boundary_checks VALUES($1,$1)',value['digest'])
        request,token=await deletion(c,user,key(8))
        await c.fetchval('SELECT stage1_keeper_prepare_erasure($1,$2)',request,token)
        with pytest.raises(Exception,match='source_layout_disagrees'):
            await c.fetchval('SELECT status FROM finalize_account_anonymization($1,$2,$3)',request,user,token)
        assert not await c.fetchval('SELECT EXISTS(SELECT 1 FROM stage1_boundary_redactions)')
        assert json.loads(await c.fetchval('SELECT witness FROM stage1_boundary_witnesses'))==value
        assert await c.fetchval('SELECT account_state FROM users WHERE id=$1',user)!='anonymized'


@pytest.mark.asyncio
@pytest.mark.parametrize("phases", [("first", "restart"), ("empty",), ("halt", "halt-restart"), ("empty-halt",)])
async def test_program_stream_recovery_and_new_hill_projection(store, phases):
    import os
    import subprocess
    from urllib.parse import urlsplit,urlunsplit
    root=Path(__file__).parents[3]
    parsed=urlsplit(os.environ['STAGE1_KEEPER_TEST_DSN'])
    env={**os.environ,'DATABASE_URL':urlunsplit(parsed._replace(path='/'+store.test_database)),
        'PROGRAM_ID':key(9),'SOLANA_RPC_URL':'http://127.0.0.1:8899','STAGE1_LOCALNET':'1'}
    script=root/'backend/tests/services/stage1_indexer_restart.cjs'
    for phase in phases:
        result=subprocess.run(['node',str(script),phase],cwd=root,env=env,capture_output=True,text=True,timeout=60)
        assert result.returncode==0,result.stdout+result.stderr


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["legacy", "stage1"])
async def test_program_replay_finishes_rate_limited_burst_in_one_poll(store, mode):
    import os
    import subprocess
    from urllib.parse import urlsplit,urlunsplit
    root=Path(__file__).parents[3]
    parsed=urlsplit(os.environ['STAGE1_KEEPER_TEST_DSN'])
    env={**os.environ,'DATABASE_URL':urlunsplit(parsed._replace(path='/'+store.test_database)),
         'PROGRAM_ID':key(9)}
    result=subprocess.run(['node',str(root/'backend/tests/services/stage1_indexer_rate_limit.cjs'),mode],
                          cwd=root,env=env,capture_output=True,text=True,timeout=60)
    assert result.returncode==0,result.stdout+result.stderr


@pytest.mark.asyncio
async def test_pruning_uses_covered_banks_and_keeps_fully_before_snapshot(store):
    vector=json.loads((Path(__file__).parents[3]/'indexer/test/fixtures/stage1-boundaries.json').read_text())[0]
    base=vector['checkpoint'];hill=vector['hill']
    async with store.pool.acquire() as c:
        for a in base['accounts']:
            if a['type'] in ('Stage1HillBond','Stage1CityConfig'):
                table='indexed_stage1_hills' if a['type']=='Stage1HillBond' else 'indexed_stage1_cities'
                await c.execute(f'INSERT INTO {table}(address,data,chain_slot) VALUES($1,$2::jsonb,100)',a['address'],json.dumps(a['fields']))
        await c.execute("INSERT INTO stage1_boundary_tasks(genesis,program,hill,week) VALUES('local-test',$1,$2,0)",key(9),hill)
        await c.execute("INSERT INTO stage1_indexer_hill_coverage VALUES('local-test',$1,$2,90,$3,210,$4,0)",key(9),hill,LAUNCH-30,LAUNCH+20)
        for slot,at,through in [(90,LAUNCH-30,90),(100,LAUNCH-20,100),(110,LAUNCH-10,200),(210,LAUNCH+10,210),(220,LAUNCH+20,230)]:
            cp=copy.deepcopy(base);cp.update(hill=hill,slot=slot,block_time=at,through_slot=through)
            if slot==110:
                cp['accounts'][0].update(observed_slot=200,observed_time=LAUNCH+1)
            await c.execute('INSERT INTO stage1_indexer_checkpoints(digest,genesis,program,hill,slot,block_time,checkpoint) VALUES($1,$2,$3,$4,$5,$6,$7::jsonb)',digest(cp),cp['genesis'],cp['program'],hill,slot,at,json.dumps(cp))
        banks=await c.fetch('SELECT slot FROM stage1_boundary_banks($1,$2,$3,$4) ORDER BY slot','local-test',key(9),hill,LAUNCH)
        assert [r['slot'] for r in banks]==[100,110,210]
        await c.execute('SELECT stage1_indexer_prune_sources()')
        slots=[r['slot'] for r in await c.fetch('SELECT slot FROM stage1_indexer_checkpoints ORDER BY slot')]
        assert slots==[100,110,210,220]


@pytest.mark.asyncio
@pytest.mark.parametrize("completed", [True, False])
async def test_delayed_program_stream_omits_erased_personal_projections(store, completed):
    import os
    import subprocess
    from urllib.parse import urlsplit, urlunsplit
    async with store.pool.acquire() as c:
        user=await c.fetchval('SELECT user_id FROM br_get_or_create_active_user(gen_random_uuid(),$1)',key(8))
        request,token=await deletion(c,user,key(8))
        if completed:
            await c.fetchval('SELECT stage1_keeper_prepare_erasure($1,$2)',request,token)
            assert await c.fetchval('SELECT status FROM finalize_account_anonymization($1,$2,$3)',request,user,token)=='completed'
    root=Path(__file__).parents[3]
    parsed=urlsplit(os.environ['STAGE1_KEEPER_TEST_DSN'])
    env={**os.environ,'DATABASE_URL':urlunsplit(parsed._replace(path='/'+store.test_database)),
         'PROGRAM_ID':key(9),'SOLANA_RPC_URL':'http://127.0.0.1:8899'}
    result=subprocess.run(['node',str(root/'backend/tests/services/stage1_stream_privacy.cjs'),'completed' if completed else 'pending'],cwd=root,env=env,capture_output=True,text=True,timeout=60)
    assert result.returncode==0,result.stdout+result.stderr
