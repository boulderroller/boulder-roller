"""Real deletion RPCs and repository/lifecycle; synthetic local data and transport."""
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import psycopg2
from psycopg2 import sql
from psycopg2.extras import Json
import pytest

from app.compliance_repository import ComplianceRepository
from app.services.account_deletion import execute_account_deletion, DeletionExecutionStatus
from app.services.stage1_keeper_worker import KeeperWorker
from tests.services.test_account_deletion_lifecycle import _ready_snapshot
from tests.services.test_stage1_keeper_erasure import settled_fixture, deletion, POLICY_FIXTURE
from tests.services.test_stage1_keeper_snapshot import PEOPLE, inputs
from tests.services.test_stage1_keeper_worker import store, migrated_template, DSN, FakeChain


@pytest.mark.asyncio
async def test_erasure_scrubs_own_lookup_but_preserves_other_riders_signed_action(store, tmp_path):
    from app.services.stage1_keeper_erasure import redact_export
    user, scope, _, _, claims, job_id = await settled_fixture(store, tmp_path)
    paid = next(l for l in claims['leaves'] if l['person'] == PEOPLE[0])
    other = next(l for l in claims['leaves'] if l['person'] != PEOPLE[0])
    async with store.pool.acquire() as c:
        for ident, leaf in [('paid', paid), ('unpaid', other)]:
            op = {'kind':'lookup','week':1,'addresses':[leaf['person'],leaf['recipient'],'ata-'+leaf['person']],
                  'refs':[{'job_id':job_id,'role':-1,'index':leaf['index'],'claim_set':'set'}]}
            await c.execute("""INSERT INTO stage1_keeper_payout_actions(id,scope_id,job_id,operation,state,signed,attempts)
                VALUES($1,$2,$3,$4::jsonb,'ready',$5::jsonb,jsonb_build_array($5::jsonb))""",
                ident,scope['id'],job_id,json.dumps(op),json.dumps({'bytes':'signed-'+ident,'signature':'signature-'+ident}))
        before = dict(await c.fetchrow("SELECT * FROM stage1_keeper_payout_actions WHERE id='unpaid'"))
        request, token = await deletion(c, user)
        prepared = json.loads(await c.fetchval('SELECT stage1_keeper_prepare_erasure($1,$2)',request,token))
        for entry in prepared['exports']:
            sha = redact_export(entry,tmp_path)
            await c.execute('SELECT stage1_keeper_record_erasure($1,$2,$3,$4,$5)',request,token,entry['job_id'],entry['digest'],sha)
        assert await c.fetchval('SELECT status FROM finalize_account_anonymization($1,$2,$3)',request,user,token) == 'completed'
        assert dict(await c.fetchrow("SELECT * FROM stage1_keeper_payout_actions WHERE id='unpaid'")) == before
        erased = dict(await c.fetchrow("SELECT * FROM stage1_keeper_payout_actions WHERE id='paid'"))
        assert PEOPLE[0] not in json.dumps(erased,default=str)
        assert 'addresses' not in json.loads(erased['operation'])
        assert 'bytes' not in json.loads(erased['signed'])
        assert not await c.fetchval('SELECT stage1_keeper_has_personal_data($1)',PEOPLE[0])


@pytest.mark.asyncio
async def test_publication_privacy_block_does_not_block_older_payouts(store):
    from app.services.stage1_keeper_payout import PayoutWorker
    async with store.pool.acquire() as c:
        await c.execute("UPDATE stage1_keeper_scopes SET blocked=true,block_kind='account_deletion_write_refused'")
        scope = dict(await c.fetchrow('SELECT * FROM stage1_keeper_scopes'))
    # With no completed obligations, payout can still inspect the scope and idle.
    # Custody failures remain fenced before inspection.
    assert await PayoutWorker(store, None)._locked(scope) == 'idle'
    scope['block_kind'] = 'ledger_mismatch'
    assert await PayoutWorker(store, None)._locked(scope) == 'blocked'


class LocalRpc:
    """Replace HTTP only: execute the repository's actual RPC names/arguments."""
    def __init__(self, database, before=None):
        self.database, self.before, self.calls = database, before, []

    def rpc(self, name, args):
        def execute():
            self.calls.append(name)
            with psycopg2.connect(DSN, dbname=self.database) as connection, connection.cursor() as c:
                if self.before:
                    self.before(c, name)
                c.execute("SELECT proretset FROM pg_proc WHERE pronamespace='public'::regnamespace AND proname=%s", (name,))
                returns_set = c.fetchone()[0]
                arguments = sql.SQL(',').join(sql.SQL('{} => %s').format(sql.Identifier(k)) for k in args)
                c.execute(sql.SQL('SELECT to_jsonb(r) FROM public.{}({}) r').format(sql.Identifier(name), arguments),
                          [Json(v) if isinstance(v, (dict, list)) else v for v in args.values()])
                rows = [r[0] for r in c.fetchall()]
                return SimpleNamespace(data=rows if returns_set else rows[0])
        return SimpleNamespace(execute=execute)


@pytest.mark.asyncio
@pytest.mark.parametrize('keeper_data,late_blocker', [
    (False, None), (False, 'legacy'), (True, None), (True, 'legacy'),
    (True, 'keeper'), (True, 'export'),
])
async def test_live_deletion_outcomes_with_keeper_off(store, tmp_path, monkeypatch, keeper_data, late_blocker):
    from pathlib import Path

    monkeypatch.setenv('STAGE1_KEEPER_ENABLED', 'false')
    monkeypatch.delenv('STAGE1_KEEPER_EXPORT_DIR', raising=False)
    async with store.pool.acquire() as c:
        wrappers = await c.fetch("""SELECT oid,pg_get_functiondef(oid) AS definition
            FROM pg_proc WHERE oid IN ('br_account_deletion_db_blockers(uuid,text)'::regprocedure,
                'finalize_account_anonymization(uuid,uuid,uuid)'::regprocedure) ORDER BY oid""")
        attributes = await c.fetch("""SELECT oid,proowner,proacl,prosecdef,proconfig FROM pg_proc
            WHERE oid IN ('br_account_deletion_db_blockers_pre_threshold(uuid,text)'::regprocedure,
                'br_account_deletion_db_blockers_pre_keeper(uuid,text)'::regprocedure,
                'finalize_account_anonymization_pre_keeper(uuid,uuid,uuid)'::regprocedure) ORDER BY oid""")
        await c.execute('DROP TABLE balance_operations')
        await c.execute((Path(__file__).parents[2]/'sql/172_balance_operations.sql').read_text())
        assert await c.fetch("""SELECT oid,pg_get_functiondef(oid) AS definition
            FROM pg_proc WHERE oid IN ('br_account_deletion_db_blockers(uuid,text)'::regprocedure,
                'finalize_account_anonymization(uuid,uuid,uuid)'::regprocedure) ORDER BY oid""") == wrappers
        assert await c.fetch("""SELECT oid,proowner,proacl,prosecdef,proconfig FROM pg_proc
            WHERE oid IN ('br_account_deletion_db_blockers_pre_threshold(uuid,text)'::regprocedure,
                'br_account_deletion_db_blockers_pre_keeper(uuid,text)'::regprocedure,
                'finalize_account_anonymization_pre_keeper(uuid,uuid,uuid)'::regprocedure) ORDER BY oid""") == attributes
    if keeper_data:
        user, _, _, _, _, _ = await settled_fixture(store, tmp_path)
        monkeypatch.setenv('STAGE1_KEEPER_EXPORT_DIR', str(tmp_path))
    else:
        async with store.pool.acquire() as c:
            user = await c.fetchval("SELECT user_id FROM br_get_or_create_active_user(gen_random_uuid(),$1)", PEOPLE[0])
    request = uuid.uuid4()
    async with store.pool.acquire() as c:
        await c.execute("""INSERT INTO balance_operations(operation_id,rider_account_id,protocol_wallet,
            action_type,authority_model,idempotency_key,confirmation_status,projection_status,amount,asset)
            VALUES('terminal-stage1',$1,$2,'stage1_register','wallet_boundary','terminal-key',
                'confirmed','recorded','123','USDC')""", str(user), PEOPLE[0])
        assert await c.fetchval("SELECT status FROM create_account_deletion_request($1,$2,$3,true,$4,$5::jsonb,'{}')",
                               request, user, PEOPLE[0], 'a'*64, POLICY_FIXTURE) == 'queued'
    original_exports = {p: p.read_bytes() for p in tmp_path.glob('*.json')}

    def late(c, name):
        if name != 'stage1_keeper_prepare_erasure':
            return
        # Same explicit race fixture as the existing migration-152 tests:
        # inject legacy value after storage authorization, bypassing only the
        # fixture's write trigger, then restore it before the real finalizer.
        if late_blocker == 'legacy':
            c.execute('ALTER TABLE user_state DISABLE TRIGGER account_deletion_write_fence')
            c.execute('INSERT INTO user_state(user_id,cal_balance) VALUES(%s,1) ON CONFLICT(user_id) DO UPDATE SET cal_balance=1', (str(user),))
            c.execute('ALTER TABLE user_state ENABLE TRIGGER account_deletion_write_fence')
        elif late_blocker == 'keeper':
            c.execute('UPDATE stage1_keeper_proofs SET paid_slot=NULL WHERE person=%s', (PEOPLE[0],))
        elif late_blocker == 'export':
            c.execute('UPDATE stage1_keeper_jobs SET export_suspended=true,erasure_request_id=%s', (str(uuid.uuid4()),))

    client = LocalRpc(store.test_database, late)
    repository = ComplianceRepository.__new__(ComplianceRepository)
    repository._client = client
    async def run(call):
        return call()
    repository._run = run
    reader = SimpleNamespace(read=AsyncMock(return_value=_ready_snapshot()))
    result = await execute_account_deletion(str(request), repository=repository,
                                           preflight_reader=reader, storage=AsyncMock())
    assert result.status is (DeletionExecutionStatus.NEEDS_SUPPORT if late_blocker else DeletionExecutionStatus.COMPLETED)
    async with store.pool.acquire() as c:
        row = await c.fetchrow('SELECT * FROM deletion_requests WHERE id=$1', request)
        assert row['status'] == ('needs_support' if late_blocker else 'completed')
        assert await c.fetchval('SELECT count(*) FROM stage1_keeper_erasure_sessions') == 0
        if late_blocker:
            assert row['failure_code'] == 'blocker_after_storage_authorization'
            assert row['worker_lease_token'] is None
            assert await c.fetchval('SELECT account_state FROM users WHERE id=$1', user) == 'deletion_pending'
            assert {p: p.read_bytes() for p in original_exports} == original_exports
            assert 'stage1_keeper_validate_erasure' not in client.calls
            assert await c.fetchval("SELECT protocol_wallet FROM balance_operations WHERE operation_id='terminal-stage1'") == PEOPLE[0]
        else:
            assert row['completion_verified_at'] is not None
            assert not await c.fetchval('SELECT EXISTS(SELECT 1 FROM users WHERE id=$1)', user)
            retained = dict(await c.fetchrow("SELECT * FROM balance_operations WHERE action_type='stage1_register'"))
            assert retained['protocol_wallet'].startswith('anonymous:')
            assert (retained['asset'],retained['amount']) == ('USDC','123')
            assert PEOPLE[0] not in json.dumps(retained,default=str)
    if not keeper_data:
        assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_no_keeper_data_preparation_is_a_noop(store):
    async with store.pool.acquire() as c:
        assert json.loads(await c.fetchval('SELECT stage1_keeper_prepare_erasure($1,$2)', uuid.uuid4(), uuid.uuid4())) == {
            'exports': [], 'request': None}


@pytest.mark.asyncio
@pytest.mark.parametrize('week', [1, 2])
async def test_refused_archive_alerts_without_blocking_other_weeks(store, week):
    async with store.pool.acquire() as c:
        user = await c.fetchval("SELECT user_id FROM br_get_or_create_active_user(gen_random_uuid(),$1)", PEOPLE[0])
        scope = dict(await c.fetchrow('SELECT * FROM stage1_keeper_scopes'))
        await c.execute("SELECT * FROM create_account_deletion_request($1,$2,$3,true,$4,$5::jsonb,'{}')",
                        uuid.uuid4(), user, PEOPLE[0], 'a'*64, POLICY_FIXTURE)
    data = inputs(week)
    data['canon_id'] = str(scope['canon_id'])
    with pytest.raises(ValueError, match='account_deletion_write_refused'):
        await store.archive_boundary(scope['id'], week, data)
    async with store.pool.acquire() as c:
        assert await c.fetchval('SELECT count(*) FROM stage1_keeper_boundaries') == 0
        assert not await c.fetchval('SELECT blocked FROM stage1_keeper_scopes')
        alert = await c.fetchrow('SELECT * FROM stage1_keeper_alerts')
        assert alert['kind'] == 'account_deletion_write_refused' and alert['job_id'] is None
        assert json.loads(alert['details']) == {'week': week, 'reason': 'account_deletion_pending', 'write': 'boundary'}
        assert PEOPLE[0] not in alert['details']
    clean = inputs(0)
    clean['canon_id'], clean['recipients'] = str(scope['canon_id']), {}
    assert PEOPLE[0] not in json.dumps(clean)
    await store.archive_boundary(scope['id'], 0, clean)


@pytest.mark.asyncio
@pytest.mark.parametrize('deleted', [False, True])
async def test_refused_personal_write_alerts_only_affected_week(store, tmp_path, caplog, deleted):
    async with store.pool.acquire() as c:
        user = await c.fetchval("SELECT user_id FROM br_get_or_create_active_user(gen_random_uuid(),$1)", PEOPLE[0])
        scope = dict(await c.fetchrow('SELECT * FROM stage1_keeper_scopes'))
        if deleted:
            # A legacy tombstone is an actual write-fence authority.
            await c.execute('INSERT INTO deleted_wallets(wallet) VALUES($1)', PEOPLE[0])
        else:
            await c.execute("SELECT * FROM create_account_deletion_request($1,$2,$3,true,$4,$5::jsonb,'{}')",
                            uuid.uuid4(), user, PEOPLE[0], 'a'*64, POLICY_FIXTURE)
    other = await store.add_scope({**scope, 'hill': 'unrelated-hill'})
    original_snapshot = store.snapshot
    async def snapshot(claim, *args):
        if claim['scope']['id'] == scope['id']:
            async with store.pool.acquire() as c:
                await c.execute('UPDATE stage1_keeper_jobs SET snapshot=$1::jsonb WHERE id=$2',
                                json.dumps({'person': PEOPLE[0]}), claim['job']['id'])
        result = await original_snapshot(claim, *args)
        result['context'][2] = claim['scope']['hill']
        return result
    store.snapshot = snapshot
    chain = FakeChain()
    # This hill's people have no registration; the default FakeChain assigns
    # r0 the same payout wallet as PEOPLE[0], which would make it affected too.
    chain.recipient_registrations = AsyncMock(return_value=(chain.slot, {}))
    worker = KeeperWorker(store, chain, tmp_path, enabled=True)
    assert await worker.run_once(scope['id']) == 'blocked'
    async with store.pool.acquire() as c:
        alert = await c.fetchrow('SELECT * FROM stage1_keeper_alerts')
        assert alert['kind'] == 'account_deletion_write_refused'
        assert json.loads(alert['details']) == {'week': 1, 'reason': 'account_deleted' if deleted else 'account_deletion_pending'}
        assert await c.fetchval('SELECT state FROM stage1_keeper_jobs WHERE id=$1', alert['job_id']) == 'blocked'
        assert await c.fetchval('SELECT blocked FROM stage1_keeper_scopes WHERE id=$1', scope['id'])
        assert not await c.fetchval('SELECT blocked FROM stage1_keeper_scopes WHERE id=$1', other)
        assert await c.fetchval('SELECT count(*) FROM stage1_keeper_attempts') == 0
    assert 'stage1_keeper_alert kind=account_deletion_write_refused' in caplog.text
    assert PEOPLE[0] not in caplog.text
    assert await worker.run_once(scope['id']) == 'idle'
    assert await worker.run_once(other) == 'submitted'


@pytest.mark.asyncio
async def test_service_continues_other_hills_after_a_block(store, tmp_path, monkeypatch):
    import asyncpg
    from app.services import stage1_keeper, stage1_keeper_chain, stage1_keeper_store, stage1_keeper_worker
    async with store.pool.acquire() as c:
        scope = dict(await c.fetchrow('SELECT * FROM stage1_keeper_scopes'))
    other = {**scope, 'hill': 'unrelated-hill'}
    chain = SimpleNamespace(start=AsyncMock(), compatibility=AsyncMock(return_value=SimpleNamespace(stage1_available=True)), discover=AsyncMock(return_value=[scope, other]), close=AsyncMock(), genesis='local-test', cluster='localnet')
    pool = SimpleNamespace(acquire=store.pool.acquire, close=AsyncMock())
    monkeypatch.setattr(asyncpg, 'create_pool', AsyncMock(return_value=pool))
    monkeypatch.setattr(stage1_keeper_chain, 'KeeperChain', lambda *a, **k: chain)
    monkeypatch.setattr(stage1_keeper_store, 'KeeperStore', lambda p: store)
    seen = []
    async def step(scope_id):
        seen.append(scope_id)
        if scope_id == scope['id']:
            async with store.pool.acquire() as c:
                await c.execute("UPDATE stage1_keeper_scopes SET blocked=true,block_kind='account_deletion_write_refused' WHERE id=$1", scope_id)
            return 'blocked'
        return 'complete'
    monkeypatch.setattr(stage1_keeper_worker, 'KeeperWorker', lambda *a, **k: SimpleNamespace(run_once=step))
    monkeypatch.setenv('STAGE1_KEEPER_ENABLED', 'true')
    monkeypatch.setenv('STAGE1_KEEPER_PUBLISHER_KEYS', '{}')
    for name in ('RPC_URL', 'PROGRAM_ID', 'PUBLISHER_KEYPAIR', 'EXPORT_DIR', 'DATABASE_URL'):
        monkeypatch.setenv('STAGE1_KEEPER_'+name, str(tmp_path))
    result = await stage1_keeper.run(SimpleNamespace(archive=None, retry_job=None, max_steps=1, through_week=None, once=True))
    assert len(seen) == 2
    assert result['transitions'] == {'blocked': 1, 'complete': 1}
    assert result['state'] == 'blocked'
