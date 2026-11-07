"""Bridge used only by the real-validator test. Synthetic DB rides, real claims."""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid
from urllib.parse import urlparse

import asyncpg

from app.services.stage1_keeper_store import KeeperStore
from app.services.stage1_keeper_chain import KeeperChain
from app.services.stage1_keeper_worker import KeeperWorker, check_accounting

BACKEND = Path(__file__).resolve().parents[2]


from tests.services.stage1_keeper_schema import schema


async def bind_captured_replay(store, chain, scopes, request):
    """Test-only owner migration across verified 1c synthetic geneses.

    replay() compares all captured account bytes/owners/lamports before return.
    Production never rebinds a database. Here each completed week is explicitly
    moved to a fresh local genesis to advance Clock without a program override.
    """
    async with store.pool.acquire() as c:
        previous = await c.fetchval('SELECT genesis FROM stage1_keeper_network')
    if previous is None or previous == chain.genesis:
        await store.bind_genesis(chain.genesis)
        return
    dsn = urlparse(os.environ['STAGE1_KEEPER_TEST_DSN'])
    rpc = urlparse(request['rpc'])
    if (os.getenv('STAGE1_LOCALNET') != '1' or dsn.hostname != '127.0.0.1'
        or not dsn.path.startswith('/keeper_') or rpc.hostname != '127.0.0.1'
        or chain.cluster != 'localnet' or request.get('previous_genesis') != previous):
        raise ValueError('not an authorized captured local test replay')
    async with store.pool.acquire() as c, c.transaction():
        if await c.fetchval("SELECT EXISTS(SELECT 1 FROM stage1_keeper_jobs WHERE state<>'complete' OR signed IS NOT NULL) OR EXISTS(SELECT 1 FROM stage1_keeper_scopes WHERE lease_until>now()) OR EXISTS(SELECT 1 FROM stage1_keeper_payout_actions WHERE state='ready' AND signed IS NOT NULL)"):
            raise ValueError('cannot migrate an unfinished local replay')
        known = await c.fetch('SELECT * FROM stage1_keeper_scopes')
        if {(r['program'],r['hill'],r['mint']) for r in known} != {(s['program'],s['hill'],s['mint']) for s in scopes}:
            raise ValueError('replay changed admitted scopes')
        for scope in known:
            observed = await chain.observe(dict(scope), scope['next_week'], 0)
            check_accounting(observed, await store.published(scope['program'],scope['mint']))
        # This is fixture restoration by the disposable database owner, after
        # completeness and captured-ledger checks, not a keeper retry path.
        await c.execute('ALTER TABLE stage1_keeper_network DISABLE TRIGGER stage1_keeper_network_immutable')
        await c.execute('UPDATE stage1_keeper_network SET genesis=$1',chain.genesis)
        await c.execute('ALTER TABLE stage1_keeper_network ENABLE TRIGGER stage1_keeper_network_immutable')
    await store.bind_genesis(chain.genesis)
    with (Path(request['export_dir']).parent / 'captured-replay-genesis.jsonl').open('a') as out:
        out.write(json.dumps({'previous':previous,'current':chain.genesis,'week':request['week'],
            'evidence':'test-only verified captured-state replay; prior jobs complete; inventory reconciled'})+'\n')


async def seed_canon(c, canon):
    canon = uuid.UUID(str(canon))
    await c.execute("""INSERT INTO canon_climbs(id,canon_id,status,candidate_fingerprint,display_name,
        centerline_polyline,centerline_geom,corridor_geom,gate_start_line,gate_end_line,canonical_profile,
        length_m,vert_m,avg_gradient_pct,dem_source,compiler_version,ratified_by,ratified_at)
        VALUES($1,$1,'ratified',$2,'Synthetic keeper hill','fixture',
        ST_GeomFromText('LINESTRING(0 0,0 0.01)',4326),
        ST_GeomFromText('MULTIPOLYGON(((0 0,0.01 0,0.01 0.01,0 0)))',4326),
        ST_GeomFromText('LINESTRING(0 0,0.001 0)',4326),
        ST_GeomFromText('LINESTRING(0 0.01,0.001 0.01)',4326),'[]',1000,100,10,'fixture','fixture','fixture',to_timestamp(1791201600))
        ON CONFLICT DO NOTHING""", canon, str(canon))


async def seed_ride(c, canon, person, week, launch, number, release=False, offset=100, powered=False):
    # Synthetic source facts in actual migrated relations, never real-rider proof.
    ride_id = uuid.uuid5(uuid.NAMESPACE_OID, f"{person}-{week}-{number}")
    at = datetime.fromtimestamp(launch+week*604800+offset+number, timezone.utc)
    duration = 60 if powered else 50
    before = datetime.fromtimestamp(launch+week*604800+offset-duration+number, timezone.utc)
    evidence = hashlib.sha256(ride_id.bytes).digest()
    user = await c.fetchval("SELECT user_id FROM br_get_or_create_active_user(gen_random_uuid(),$1)", person)
    pipeline = await c.fetchrow("SELECT id,ride_parser_version,policy_version FROM pipeline_versions WHERE deactivated_at IS NULL ORDER BY id DESC LIMIT 1")
    await c.execute("""INSERT INTO rides(id,user_id,started_at,completed_at,upload_verified_at,phase2_completed_at)
        VALUES($1,$2,$3,$4,$4,$4) ON CONFLICT DO NOTHING""", ride_id,user,before,at)
    extra_columns, extra_values, extra_args = '', '', []
    if powered:
        snapshot = await c.fetchrow('SELECT * FROM bind_ride_reward_ftp($1,$2)',ride_id,before)
        await c.execute('UPDATE rides SET economic_tss=1.666666 WHERE id=$1',ride_id)
        spans = json.dumps([[int(before.timestamp()*1000),int(at.timestamp()*1000)]])
        extra_columns = ',reward_ftp_w,reward_ftp_source,reward_ftp_authority_id,reward_ftp_policy_version,effort_spans,paid_spans,covered_spans'
        extra_values = ",$12,$13,$14,$15,ride_effort_spans_from_ms($16::jsonb),ride_effort_spans_from_ms($16::jsonb),'{}'::tstzmultirange"
        extra_args = [*list(snapshot.values())[:4],spans]
    await c.execute(f"""INSERT INTO ride_economic_plans(ride_id,user_id,wallet,ride_hash,attestation_commitment,
        parser_version,policy_version,reward_policy,source_kind,started_at,completed_at,total_tss,
        total_distance_m,total_vert_m,exact_cal_base_units,climbs_crossed,exact_tribute_base_units,
        plan_evidence_hash,expected_attestation_pda,expected_cal_receipt_pda,state,
        attestation_actual_tx_signature,attestation_confirmed_at,cal_actual_tx_signature,cal_confirmed_at,
        terminal_projected_at,pipeline_version_id{extra_columns})
        VALUES($1,$2,$3,$4,$4,$5,$6,'fixture',0,$7,$8,{1 if powered else 100},1000,100,0,1,0,$4,$9,$10,'complete',
        'fixture-attestation',$8,'fixture-cal',$8,$8,$11{extra_values}) ON CONFLICT DO NOTHING""",
        ride_id,user,person,evidence,pipeline['ride_parser_version'],pipeline['policy_version'],before,at,
        f'attestation-{ride_id}',f'cal-{ride_id}',pipeline['id'],*extra_args)
    if powered:
        from types import SimpleNamespace
        from app.services.canon_traversal_evidence import CanonTraversalEvidence
        import h3
        canonical = CanonTraversalEvidence.build(ride_id=ride_id,ride_hash_hex=evidence.hex(),ride_parser_version=pipeline['ride_parser_version'],
            parsed_ride=SimpleNamespace(started_at=before,records=[{'t':i,'lat':40+i/10000,'lon':-75,'power':200} for i in range(61)]),
            tile_service=SimpleNamespace(lat_lng_to_tile=h3.latlng_to_cell)).to_row()
        await c.execute("""INSERT INTO canon_traversal_evidence(ride_id,ride_hash_hex,ride_parser_version,evidence_version,
            sample_count,sample_digest,samples) VALUES($1,$2,$3,$4,$5,$6,$7::jsonb) ON CONFLICT DO NOTHING""",
            ride_id,evidence.hex(),pipeline['ride_parser_version'],canonical['evidence_version'],canonical['sample_count'],canonical['sample_digest'],json.dumps(canonical['samples']))
    else:
        await c.execute("""INSERT INTO canon_traversal_evidence(ride_id,ride_hash_hex,ride_parser_version,evidence_version,
        sample_count,sample_digest,samples) VALUES($1,$2,$3,'canon_traversal_evidence_v1',0,$2,'[]') ON CONFLICT DO NOTHING""",
            ride_id,evidence.hex(),pipeline['ride_parser_version'])
    trace = {'registry_id':str(canon),'canon_id':str(canon),'canon_version':1,
        'trace_version':'canon_traversal_trace_v1','gate_crossings':{'start_time_s_raw':0,'finish_time_s_raw':duration},
        'monotonic_progress':{'accepted':True}}
    await c.execute("""INSERT INTO patterns_climb(id,activity_id,wallet,vert_m,time_s,detector_version,match_trace,created_at)
        VALUES($1,$2,$3,100,$6,'canon_traversal_v1',$4::jsonb,$5) ON CONFLICT DO NOTHING""",
        uuid.uuid5(ride_id,'canon'),ride_id,person,json.dumps(trace),at,duration)
    return ride_id


async def execute(request):
    dsn = os.environ["STAGE1_KEEPER_TEST_DSN"]
    if "127.0.0.1" not in dsn:
        raise ValueError("disposable local test database only")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
    chain = KeeperChain(request["rpc"], request["program"], request["publisher_path"])
    try:
        async with pool.acquire() as c:
            if request.get("initialize"):
                await schema(c,request.get('powered_wallets',()))
                canon = uuid.UUID(request["canon_id"])
                await seed_canon(c, canon)
        store = KeeperStore(pool)
        scopes = await chain.discover()
        await bind_captured_replay(store, chain, scopes, request)
        for admitted in scopes:
            await store.add_scope(admitted)
        scope = next(s for s in scopes if s["hill"] == request["hill"] and s["mint"] == request["mint"])
        scope_id = await store.add_scope(scope)
        if request.get('payout'):
            from app.services.stage1_keeper_payout import PayoutWorker
            worker = PayoutWorker(store,chain)
            if request.get('lookup_probe'):
                async with pool.acquire() as c:
                    job_id=await c.fetchval('SELECT id FROM stage1_keeper_jobs WHERE scope_id=$1 AND week=$2',scope_id,request['week'])
                await worker.action({**scope,'id':scope_id},job_id,{'kind':'lookup','week':request['week'],'addresses':request['lookup_probe'],'refs':[]})
            rpc_counts = {}
            original_rpc = chain.rpc
            async def counted_rpc(method,params):
                rpc_counts[method] = rpc_counts.get(method,0)+1
                return await original_rpc(method,params)
            chain.rpc = counted_rpc
            transitions = {}
            for _ in range(500):
                result = await worker.run_once(scope_id)
                transitions[result] = transitions.get(result,0)+1
                if result in ('idle','terminal','blocked','settlement_paused'):
                    async with pool.acquire() as c:
                        open_tables=await c.fetchval('SELECT count(*) FROM stage1_keeper_lookup_tables WHERE scope_id=$1 AND NOT closed',scope_id)
                    if not request.get('lookup_probe') or not open_tables or result=='blocked':
                        break
                await asyncio.sleep(1)
            async with pool.acquire() as c:
                outstanding = await c.fetchval('SELECT count(*) FROM stage1_keeper_proofs p JOIN stage1_keeper_jobs j ON j.id=p.job_id WHERE j.scope_id=$1 AND p.paid_slot IS NULL',scope_id)
                closed = await c.fetchval("SELECT count(*) FROM stage1_keeper_jobs j, LATERAL jsonb_each(j.publications) p WHERE j.scope_id=$1 AND p.value->'closed'<>'null'::jsonb",scope_id)
                failed = await c.fetchval("SELECT count(*) FROM stage1_keeper_payout_actions WHERE scope_id=$1 AND state='failed'",scope_id)
                alerts = [dict(r) for r in await c.fetch('SELECT kind,count(*) AS count FROM stage1_keeper_alerts WHERE scope_id=$1 GROUP BY kind',scope_id)]
                sponsorships = await c.fetchval('SELECT count(*) FROM stage1_keeper_token_accounts WHERE creation_signature IS NOT NULL')
                tables=[dict(r) for r in await c.fetch('SELECT address,closed,deposited_lamports FROM stage1_keeper_lookup_tables WHERE scope_id=$1',scope_id)]
                refunds=await c.fetchval("SELECT coalesce(sum((evidence->>'lookup_refund_lamports')::bigint),0)::bigint FROM stage1_keeper_payout_actions WHERE scope_id=$1",scope_id)
            return {'rpc_calls':rpc_counts,'alerts':alerts,'sponsorships':sponsorships,'lookup_tables':tables,'lookup_refunds':refunds,'transitions':transitions,'unpaid_leaves':outstanding,'closed_sets':closed,'failed_actions':failed,'costs':await store.weekly_costs()}
        if request.get("audit"):
            observation = await chain.observe(scope, request["week"], 0)
            result = check_accounting(observation, await store.published(scope["program"], scope["mint"]))
            await store.record_paid(scope, observation)
            return result
        week = request["week"]
        async with pool.acquire() as c:
            for i, person in enumerate(request["people"]):
                async with c.transaction():
                    await seed_ride(c, request["canon_id"], person, week, scope["launch"], i, release=i == 4,powered=request.get('powered',False))
        archive = {"context": [scope["program"],scope["city"],scope["hill"],week,scope["mint"]],
                   "canon_id": str(scope["canon_id"]), "launch": scope["launch"],
                   "opening": request["opening"], "closing": request["closing"]}
        await store.archive_boundary(scope_id, week, archive)
        worker = KeeperWorker(store, chain, request["export_dir"], enabled=True)
        transitions = {}
        for _ in range(220):
            status = await worker.run_once(scope_id)
            transitions[status] = transitions.get(status, 0) + 1
            if request.get('stop_after_publish_submit') and status=='submitted':
                async with pool.acquire() as c:
                    pending=await c.fetchrow("SELECT signed,operations,operation_index FROM stage1_keeper_jobs WHERE scope_id=$1 AND week=$2",scope_id,week)
                if json.loads(pending['operations'])[pending['operation_index']]['kind']=='publish':
                    return {'pending_signature':json.loads(pending['signed'])['signature']}
            if status in ("complete", "blocked"):
                break
            await asyncio.sleep(1)
        async with pool.acquire() as c:
            job = await c.fetchrow("SELECT id,state,claims,allocation,operations,lookup_address FROM stage1_keeper_jobs WHERE scope_id=$1 AND week=$2", scope_id, week)
            if not job or job["state"] != "complete":
                alerts = await c.fetch("SELECT kind,details FROM stage1_keeper_alerts")
                raise RuntimeError(f"keeper did not complete: {transitions} alerts={[dict(r) for r in alerts]}")
            proof = await c.fetchval("SELECT leaf FROM stage1_keeper_proofs WHERE job_id=$1 ORDER BY leaf_index LIMIT 1", job["id"])
        return {"job": job["id"], "claims": json.loads(job["claims"]), "proof": json.loads(proof) if proof else None,
                "allocation": json.loads(job["allocation"]), "operations":json.loads(job["operations"]), "lookup_address":job["lookup_address"], "transitions": transitions}
    finally:
        await chain.close()
        await pool.close()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(execute(json.load(sys.stdin)))))
