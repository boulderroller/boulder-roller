"""Real PostgreSQL leases; the transport in this suite is explicitly a fake."""
import asyncio
import copy
import json
import hashlib
import struct
import os
from pathlib import Path
import uuid

import asyncpg
import pytest
import psycopg2
from solders.pubkey import Pubkey
from contextlib import asynccontextmanager

from app.services.stage1_keeper_store import KeeperStore, LeaseLost
from app.services.stage1_keeper_worker import KeeperWorker
from app.services.stage1_keeper_worker import check_accounting, Blocked
from tests.services.test_stage1_keeper_allocation import measurement

DSN = os.getenv("STAGE1_KEEPER_TEST_DSN")


@pytest.fixture(scope="session")
def migrated_template():
    if not DSN:
        pytest.skip("STAGE1_KEEPER_TEST_DSN must point to disposable local PostgreSQL")
    connection = psycopg2.connect(DSN)
    connection.autocommit = True
    cursor = connection.cursor()
    template = "keeper_template_" + uuid.uuid4().hex
    cursor.execute(f'CREATE DATABASE "{template}"')
    async def setup():
        from tests.services.stage1_keeper_schema import schema
        c = await asyncpg.connect(DSN, database=template)
        try:
            await schema(c)
        finally:
            await c.close()
    asyncio.run(setup())
    yield template
    cursor.execute(f'DROP DATABASE "{template}"')
    cursor.close()
    connection.close()


@pytest.fixture
def store(migrated_template):
    connection = psycopg2.connect(DSN)
    connection.autocommit = True
    cursor = connection.cursor()
    name = "keeper_" + uuid.uuid4().hex
    cursor.execute(f'CREATE DATABASE "{name}" TEMPLATE "{migrated_template}"')
    for role in ("anon", "authenticated", "service_role"):
        cursor.execute(f"DO $$ BEGIN CREATE ROLE {role} NOLOGIN BYPASSRLS; EXCEPTION WHEN duplicate_object THEN NULL; END $$")
    class Pool:
        @asynccontextmanager
        async def acquire(self):
            c = await asyncpg.connect(DSN, database=name)
            try:
                yield c
            finally:
                await c.close()
    pool = Pool()
    result = KeeperStore(pool)
    result.test_database = name
    async def setup():
        await result.bind_genesis('local-test')
        result.test_scope_id = await result.add_scope({"program": "program", "city": "city", "hill": "hill", "mint": "mint",
                                                     "canon_id": str(uuid.uuid4()), "launch": 1791201600, "next_week": 1})
    asyncio.run(setup())
    async def snapshot(claim, registrations, freeze_at=None, held_people=()):
        s = measurement()
        s.update(schema=2, registration_cutoff=1791201600 + 5*604800)
        s["commitment"] = "ff" * 32
        s["context"][3] = claim["job"]["week"]
        return s
    result.snapshot = snapshot
    yield result
    cursor.execute(f'DROP DATABASE "{name}"')
    cursor.close()
    connection.close()


class FakeChain:
    def __init__(self):
        self.genesis = 'local-test'
        self.sent, self.statuses, self.operations = [], {}, {}
        self.dropped = False
        self.slot = 100
        self.cursor = {"next_week": 1, "holds": [0] * 26}
        self.books = {"book1": {"hill": "hill", "week": 1, "due_week": 1, "available": 950, "harvested_net": 950,
                                "lineage": "aa"*32, "snapshot": "00"*32, "cap": 0, "published": False,
                                "holds": [0]*5, "pool": 0, "proposed": False}}
        self.sets = {}
        self.ledger = {"deposited": 1000, "owner_custody": 0, "owner_returns": 0, "earnings": 1000,
                       "paid": 0, "claimable": 0, "held": 950, "pool": 0}
        self.stale = False
        self.expire = False

    def funding(self, scope, week):
        return f"book{week}"

    def claim_address(self, scope, week):
        return str(Pubkey.default())

    async def clock(self, floor=0):
        return {"slot": self.slot, "now": 1791201600 + 5*604800}

    async def recipient_registrations(self, people, floor=0):
        return self.slot, {p: {"recipient": str(Pubkey.from_bytes(bytes([int(p[1:])+1])*32)), "registered_at": 1791201600} for p in people}

    async def observe(self, scope, week, floor):
        if self.stale:
            raise RuntimeError("stale finalized read")
        return copy.deepcopy({"slot": self.slot, "now": 1791201600 + 5*604800, "cursor": self.cursor,
            "books": self.books, "sets": self.sets, "asset": {"ledger": self.ledger, "harvested_units": 1000, "fees_assessed": 50},
            "lots": [{"units": 0, "owner_units": 0, "returned_units": 0, "harvested_units": 1000}],
            "earnings_balance": 1000, "recipients": {}, "receipts": []})

    async def prepare(self, scope, op, floor=0):
        sig = f"sig{len(self.operations)}"
        self.operations[sig] = op
        return {"signature": sig, "bytes": "c2lnbmVk", "last_valid_block_height": 200}

    async def status(self, signed):
        return self.statuses.get(signed["signature"], {"state": "expired" if self.expire else "absent", "slot": self.slot})

    async def submit(self, signed):
        signature = signed["signature"]
        self.sent.append(signature)
        if signature in self.statuses:
            return
        op = self.operations[signature]
        kind = op["kind"]
        if kind == "freeze":
            self.books["book1"].update(snapshot=op["snapshot"], cap=op["cap"])
        elif kind == "publish":
            self.books["book1"].update(available=0, published=True, holds=op["holds"])
            self.sets[self.claim_address({},1)] = {"hill": "hill", "week": 1, "root": op["root"], "total": op["total"],
                                 "snapshot": self.books["book1"]["snapshot"], "cap": self.books["book1"]["cap"], "paid": 0, "leaf_count":op["count"], "sealed":True}
            self.ledger["claimable"] += op["total"]
            self.ledger["held"] -= op["total"]
            self.cursor["next_week"] += 1
            await self.transaction_evidence(signature)
        elif kind == "skip":
            self.cursor["next_week"] = op["through"] + 1
        self.slot += 1
        self.statuses[signature] = {"state": "finalized", "slot": self.slot}
        if self.dropped:
            self.dropped = False
            raise ConnectionError("response lost after application")

    async def transaction_evidence(self, signature, floor=0, **kwargs):
        op = self.operations[signature]
        if op['kind']!='publish':
            return {'signature':signature,'slot':self.slot,'fee':5000,'events':[]}
        book = self.books['book1']
        address = self.claim_address({},1)
        audit = {'snapshot':list(bytes.fromhex(book['snapshot'])), 'source_lineage':list(bytes.fromhex(book['lineage'])),
                 'release_commitment':[0]*32,'boost_commitment':[0]*32,'new_holds':op['holds']}
        ah = hashlib.sha256(b'BR-stage1-v2:cash-audit\0'+b''.join(bytes(audit[k]) for k in ('snapshot','source_lineage','release_commitment','boost_commitment'))+struct.pack('<5Q',*op['holds'])).digest()
        self.sets[address]['metadata_hash'] = hashlib.sha256(b'BR-stage1-v2:claim-terms\0'+bytes(Pubkey.from_string(address))+struct.pack('<Qq',book['cap'],1)+ah).hexdigest()
        return {'signature':signature,'slot':self.slot,'fee':5000,'events':[{'name':'Stage1CashPublished','data':{
            'claim_set':address,'root':list(bytes.fromhex(op['root'])),'total':op['total'],'leaf_count':op['count'],
            'terms':{'cap':book['cap'],'frozen_at':1,'audit_hash':list(ah)},'audit':audit}}]}

    def verify_operation(self, scope, op, observed):
        assert self.operation_applied(scope, op, observed)

    def operation_applied(self, scope, op, observed):
        return any(self.operations[s] == op for s in self.statuses)

    def verify_plan(self, scope, job, observed):
        assert observed["cursor"]["next_week"] == job["through_week"] + 1


async def due(store):
    async with store.pool.acquire() as c:
        await c.execute("UPDATE stage1_keeper_scopes SET retry_at=now()")


async def finish(worker, store, limit=20):
    for _ in range(limit):
        await due(store)
        result = await worker.run_once(store.test_scope_id)
        if result in ("complete", "blocked"):
            return result
    raise AssertionError("worker did not converge")


@pytest.mark.asyncio
async def test_flag_off_performs_no_io():
    assert await KeeperWorker(None, None, "/not/created").run_once() == "disabled"


@pytest.mark.asyncio
async def test_genesis_binding_rejects_unsigned_plan_reuse(store, tmp_path):
    await store.bind_genesis('local-test')
    chain = FakeChain()
    worker = KeeperWorker(store, chain, tmp_path, enabled=True)
    claim = await store.claim(store.test_scope_id)
    assert await worker.plan(claim, await chain.observe(claim['scope'],1,0))
    restarted = KeeperStore(store.pool)
    with pytest.raises(ValueError, match='genesis'):
        await restarted.bind_genesis('EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG')
    async with store.pool.acquire() as c:
        assert await c.fetchval('SELECT state FROM stage1_keeper_jobs') == 'running'
        assert await c.fetchval('SELECT signed FROM stage1_keeper_jobs') is None
        for sql in ('UPDATE stage1_keeper_network SET genesis=\'other\'', 'DELETE FROM stage1_keeper_network'):
            with pytest.raises(asyncpg.RaiseError, match='immutable'):
                await c.execute(sql)
    assert not chain.sent


@pytest.mark.asyncio
async def test_legacy_unbound_state_cannot_be_adopted(store):
    # Reproduce an older keeper DB without a known genesis. This setup runs
    # only in this test's disposable database, never in application code.
    async with store.pool.acquire() as c:
        await c.execute('ALTER TABLE stage1_keeper_network DISABLE TRIGGER stage1_keeper_network_immutable')
        await c.execute('DELETE FROM stage1_keeper_network')
        await c.execute('ALTER TABLE stage1_keeper_network ENABLE TRIGGER stage1_keeper_network_immutable')
    with pytest.raises(ValueError, match='unbound'):
        await KeeperStore(store.pool).bind_genesis('local-test')


@pytest.mark.asyncio
async def test_service_role_can_check_genesis_without_mutation_privileges(store):
    class ServicePool:
        @asynccontextmanager
        async def acquire(self):
            async with store.pool.acquire() as c:
                # The minimal predecessor omits Supabase's schema usage and
                # service-role BYPASSRLS attribute; reproduce that role here.
                await c.execute('ALTER ROLE service_role BYPASSRLS')
                await c.execute('GRANT USAGE ON SCHEMA public TO service_role')
                await c.execute('SET ROLE service_role')
                yield c
    await KeeperStore(ServicePool()).bind_genesis('local-test')
    async with store.pool.acquire() as c:
        assert not await c.fetchval("SELECT has_table_privilege('service_role','stage1_keeper_network','TRUNCATE')")
        assert await c.fetchval("SELECT relrowsecurity FROM pg_class WHERE oid='stage1_keeper_network'::regclass")
        for role in ('anon', 'authenticated'):
            assert not await c.fetchval("SELECT has_table_privilege($1,'stage1_keeper_network','SELECT,INSERT,UPDATE,DELETE')", role)


@pytest.mark.asyncio
async def test_dropped_response_replay_and_durable_proofs(store, tmp_path):
    chain = FakeChain()
    chain.dropped = True
    worker = KeeperWorker(store, chain, tmp_path, enabled=True)
    assert await finish(worker, store) == "complete"
    assert len(chain.sent) == len(set(chain.sent)) == 3
    async with store.pool.acquire() as c:
        assert await c.fetchval("SELECT count(*) FROM stage1_keeper_proofs") == 5
        assert await c.fetchval("SELECT count(*) FROM stage1_keeper_attempts WHERE finalized_slot IS NOT NULL") == 3
        assert await c.fetchval("SELECT count(*) FROM stage1_keeper_reconciliations") == 1
        assert await c.fetchval("SELECT count(*) FROM stage1_keeper_alerts") == 0
    exported = json.loads(next(tmp_path.glob("*.json")).read_bytes())
    assert exported["claims"]["total"] == 950


@pytest.mark.asyncio
async def test_competing_workers_and_expired_lease_fence(store):
    first, second = await asyncio.gather(store.claim(store.test_scope_id), store.claim(store.test_scope_id))
    assert sum(c is not None for c in (first, second)) == 1
    original = first or second
    async with store.pool.acquire() as c:
        await c.execute("UPDATE stage1_keeper_scopes SET lease_until=now()-interval '1 second'")
    replacement = await store.claim(store.test_scope_id)
    assert replacement["token"] != original["token"]
    with pytest.raises(LeaseLost):
        await store.renew(original)


@pytest.mark.asyncio
async def test_crash_after_signing_reuses_identical_durable_bytes(store, tmp_path):
    chain = FakeChain()
    worker = KeeperWorker(store, chain, tmp_path, enabled=True)
    original = chain.submit
    async def crash(signed):
        raise SystemExit("crash before submission")
    chain.submit = crash
    with pytest.raises(SystemExit):
        await worker.run_once(store.test_scope_id)
    async with store.pool.acquire() as c:
        signed = json.loads(await c.fetchval("SELECT signed FROM stage1_keeper_jobs"))
    chain.submit = original
    assert await finish(KeeperWorker(store, chain, tmp_path, enabled=True), store) == "complete"
    assert chain.sent[0] == signed["signature"]


@pytest.mark.asyncio
async def test_stale_read_defers_and_mismatch_blocks_next_week(store, tmp_path):
    chain = FakeChain()
    chain.stale = True
    worker = KeeperWorker(store, chain, tmp_path, enabled=True)
    assert await worker.run_once(store.test_scope_id) == "retry"
    assert not chain.sent
    chain.stale = False
    assert await finish(worker, store) == "complete"
    chain.ledger["claimable"] += 1
    await due(store)
    assert await worker.run_once(store.test_scope_id) == "blocked"
    async with store.pool.acquire() as c:
        assert await c.fetchval("SELECT kind FROM stage1_keeper_alerts") == "ledger_mismatch"


@pytest.mark.asyncio
async def test_oracle_disagreement_is_durable_and_never_signed(store, tmp_path):
    async def wrong(snapshot, sources):
        return {"allocation": "different"}
    chain = FakeChain()
    worker = KeeperWorker(store, chain, tmp_path, enabled=True, recompute=wrong)
    assert await worker.run_once(store.test_scope_id) == "blocked"
    assert not chain.sent and not chain.operations
    async with store.pool.acquire() as c:
        details = json.loads(await c.fetchval("SELECT details FROM stage1_keeper_alerts"))
        assert "backend" in details and "oracle" in details


@pytest.mark.asyncio
async def test_zero_income_weeks_skip_without_discarding_measurement(store, tmp_path):
    chain = FakeChain()
    assert await finish(KeeperWorker(store, chain, tmp_path, enabled=True), store) == "complete"
    assert await finish(KeeperWorker(store, chain, tmp_path, enabled=True), store) == "complete"
    assert await finish(KeeperWorker(store, chain, tmp_path, enabled=True), store) == "complete"
    assert [op["kind"] for op in chain.operations.values()] == ["freeze", "prepare_set", "publish", "skip", "skip"]
    async with store.pool.acquire() as c:
        assert await c.fetchval("SELECT count(*) FROM stage1_keeper_jobs WHERE snapshot IS NOT NULL AND state='complete'") == 3


@pytest.mark.asyncio
async def test_expired_unsubmitted_signature_rebuilds_only_after_no_effect(store, tmp_path):
    chain = FakeChain()
    worker = KeeperWorker(store, chain, tmp_path, enabled=True)
    original = chain.submit
    async def drop_before(signed):
        raise ConnectionError("before submit")
    chain.submit = drop_before
    assert await worker.run_once(store.test_scope_id) == "retry"
    chain.expire = True
    await due(store)
    assert await worker.run_once(store.test_scope_id) == "expired_no_effect"
    chain.expire = False
    chain.submit = original
    assert await finish(worker, store) == "complete"
    async with store.pool.acquire() as c:
        assert await c.fetchval("SELECT count(*) FROM stage1_keeper_attempts") == 4


@pytest.mark.asyncio
async def test_completed_database_root_cannot_disappear_from_chain():
    chain = FakeChain()
    observed = await chain.observe({}, 1, 0)
    job = {"state": "complete", "week": 0, "claims": {"context": ["program", "city", "hill", 0, "mint"],
           "root": "99"*32, "total": 100, "leaves": []}, "operations": [{"kind": "publish"}]}
    with pytest.raises(Blocked, match="ledger_mismatch"):
        check_accounting(observed, [job])


@pytest.mark.asyncio
async def test_plan_save_failure_cannot_orphan_a_conflicting_export(store, tmp_path):
    chain = FakeChain()
    worker = KeeperWorker(store, chain, tmp_path, enabled=True)
    original_save, original_snapshot = store.save_plan, store.snapshot
    snapshots = []
    async def changing_snapshot(*args):
        result = await original_snapshot(*args)
        result["ascents"]["r0"] = len(snapshots)+1
        snapshots.append(result)
        return result
    async def fail_save(*args):
        raise ConnectionError("database interrupted before immutable plan")
    store.snapshot, store.save_plan = changing_snapshot, fail_save
    assert await worker.run_once(store.test_scope_id) == "retry"
    assert not chain.sent
    store.save_plan = original_save
    await due(store)
    assert await worker.run_once(store.test_scope_id) == "submitted"


@pytest.mark.asyncio
async def test_missing_export_recovers_from_frozen_database_plan(store, tmp_path, monkeypatch):
    from app.services import stage1_keeper_worker as module
    chain = FakeChain()
    worker = KeeperWorker(store, chain, tmp_path, enabled=True)
    original_export = module.export_claims
    def fail_export(*args):
        raise OSError("export volume temporarily unavailable")
    monkeypatch.setattr(module, "export_claims", fail_export)
    assert await worker.run_once(store.test_scope_id) == "retry"
    async with store.pool.acquire() as c:
        assert await c.fetchval("SELECT state FROM stage1_keeper_jobs") == "running"
        assert await c.fetchval("SELECT count(*) FROM stage1_keeper_proofs") == 5
    assert not chain.sent
    monkeypatch.setattr(module, "export_claims", original_export)
    assert await finish(worker, store) == "complete"


@pytest.mark.asyncio
async def test_existing_holds_cannot_plan_a_skip(store, tmp_path):
    chain = FakeChain()
    chain.books["book1"].update(week=0, available=0, harvested_net=950, published=True, holds=[950,0,0,0,0])
    chain.books["book0"] = chain.books.pop("book1")
    chain.cursor["holds"][0] = 950
    worker = KeeperWorker(store, chain, tmp_path, enabled=True)
    claim = await store.claim(store.test_scope_id)
    observed = await chain.observe(claim["scope"], 1, 0)
    assert await worker.plan(claim, observed)
    await store.refresh(claim)
    assert all(op["kind"] != "skip" for op in claim["job"]["operations"])


@pytest.mark.asyncio
async def test_cannot_finalize_until_close_plus_grace(store, tmp_path):
    chain = FakeChain()
    claim = await store.claim(store.test_scope_id)
    observed = await chain.observe(claim["scope"], 1, 0)
    observed["now"] = claim["scope"]["launch"] + 2*604800 + 86399
    assert not await KeeperWorker(store, chain, tmp_path, enabled=True).plan(claim, observed)


@pytest.mark.asyncio
@pytest.mark.parametrize('seconds_before_grace,delay', [(3600,900), (20,20)])
async def test_idle_planning_only_reads_clock(store, tmp_path, seconds_before_grace, delay):
    chain = FakeChain()
    async def clock(floor):
        return {'slot': 100, 'now': 1791201600 + 2*604800 + 86400 - seconds_before_grace}
    async def no_inventory(*args):
        pytest.fail('idle scope must not read inventory')
    chain.clock, chain.observe = clock, no_inventory
    assert await KeeperWorker(store, chain, tmp_path, enabled=True).run_once(store.test_scope_id) == 'not_due'
    async with store.pool.acquire() as c:
        remaining = await c.fetchval('SELECT extract(epoch from retry_at-now()) FROM stage1_keeper_scopes')
        assert delay-3 < remaining <= delay


@pytest.mark.asyncio
async def test_late_archive_retries_without_blocking_other_hill(store, tmp_path):
    from app.services.stage1_keeper_store import WaitingForArchive
    original = store.snapshot
    async def missing(*args):
        raise WaitingForArchive("missing historical boundary")
    store.snapshot = missing
    chain = FakeChain()
    original_observe = chain.observe
    async def no_inventory(*args):
        pytest.fail('waiting for archive must not read inventory')
    chain.observe = no_inventory
    worker = KeeperWorker(store, chain, tmp_path, enabled=True)
    assert await worker.run_once(store.test_scope_id) == "waiting_for_archive"
    async with store.pool.acquire() as c:
        assert not await c.fetchval("SELECT blocked FROM stage1_keeper_scopes")
        assert await c.fetchval("SELECT state FROM stage1_keeper_jobs") == "planning"
        assert 897 < await c.fetchval('SELECT extract(epoch from retry_at-now()) FROM stage1_keeper_scopes') <= 900
    store.snapshot = original
    chain.observe = original_observe
    assert await finish(worker, store) == "complete"


@pytest.mark.asyncio
async def test_unblock_replans_before_any_signature(store, tmp_path):
    async def wrong(*args):
        return {}
    worker = KeeperWorker(store, FakeChain(), tmp_path, enabled=True, recompute=wrong)
    assert await worker.run_once(store.test_scope_id) == "blocked"
    async with store.pool.acquire() as c:
        job_id = await c.fetchval("SELECT id FROM stage1_keeper_jobs")
    await store.unblock(job_id)
    assert await finish(KeeperWorker(store, worker.chain, tmp_path, enabled=True), store) == "complete"


@pytest.mark.asyncio
async def test_lost_lease_while_blocking_still_alerts_without_crashing(store,tmp_path,caplog):
    async def lose_lease(snapshot,sources):
        async with store.pool.acquire() as c:
            await c.execute("UPDATE stage1_keeper_scopes SET lease_until=now()-interval '1 second'")
        return {}
    worker=KeeperWorker(store,FakeChain(),tmp_path,enabled=True,recompute=lose_lease)
    assert await worker.run_once(store.test_scope_id)=='lease_lost'
    async with store.pool.acquire() as c:
        assert await c.fetchval("SELECT kind FROM stage1_keeper_alerts")=='oracle_disagreement'
    assert 'stage1_keeper_alert kind=oracle_disagreement' in caplog.text


@pytest.mark.asyncio
async def test_program_refusal_does_not_resign_or_retry_forever(store,tmp_path):
    chain=FakeChain()
    async def refuse(signed):
        raise Blocked('program_refusal',{'instruction_error':[0,{'Custom':6001}]})
    chain.submit=refuse
    worker=KeeperWorker(store,chain,tmp_path,enabled=True)
    assert await worker.run_once(store.test_scope_id)=='blocked'
    assert await worker.run_once(store.test_scope_id)=='idle'
    assert len(chain.operations)==1


@pytest.mark.asyncio
@pytest.mark.parametrize('other_state',['complete','running'])
async def test_token_lock_spans_chain_and_database_and_refreshes_floor(store,tmp_path,other_state):
    async with store.pool.acquire() as c:
        scope=dict(await c.fetchrow('SELECT * FROM stage1_keeper_scopes'))
    async with store.asset_lock(scope) as held:
        assert held
        chain=FakeChain()
        assert await KeeperWorker(store,chain,tmp_path,enabled=True).run_once(store.test_scope_id)=='asset_busy'
        assert not chain.operations
    # A claim made before another hill records a finalized effect inherits its floor
    # only after the asset lock, rather than report that finalized set missing.
    other=await store.add_scope({**scope,'hill':'other','next_week':1})
    claim=await store.claim(other)
    async with store.pool.acquire() as c:
        await c.execute('UPDATE stage1_keeper_jobs SET floor_slot=500,state=$2 WHERE scope_id=$1',scope['id'],other_state)
    await store.refresh(claim)
    assert claim['job']['floor_slot']==500
    third=await store.add_scope({**scope,'hill':'third','next_week':1})
    assert (await store.claim(third))['job']['floor_slot']==500


@pytest.mark.asyncio
async def test_token_retry_reconciles_before_releasing_affected_siblings(store,tmp_path):
    async with store.pool.acquire() as c:
        scope=dict(await c.fetchrow('SELECT * FROM stage1_keeper_scopes'))
    await store.add_scope({**scope,'hill':'other'})
    chain=FakeChain();chain.ledger['held']+=1
    worker=KeeperWorker(store,chain,tmp_path,enabled=True)
    assert await worker.run_once(store.test_scope_id)=='blocked'
    async with store.pool.acquire() as c:
        job=await c.fetchval('SELECT id FROM stage1_keeper_jobs')
    with pytest.raises(Blocked,match='ledger_mismatch'):
        await worker.retry(job)
    chain.ledger['held']-=1
    await worker.retry(job)
    async with store.pool.acquire() as c:
        assert await c.fetchval('SELECT count(*) FROM stage1_keeper_scopes WHERE blocked')==0
    assert await finish(worker,store)=='complete'


@pytest.mark.asyncio
async def test_retry_rechecks_block_reason_after_acquiring_token_lock(store,tmp_path):
    async def wrong(*args):
        return {}
    chain=FakeChain()
    worker=KeeperWorker(store,chain,tmp_path,enabled=True,recompute=wrong)
    assert await worker.run_once(store.test_scope_id)=='blocked'
    async with store.pool.acquire() as c:
        job=await c.fetchval('SELECT id FROM stage1_keeper_jobs')
    real_lock=store.asset_lock
    @asynccontextmanager
    async def interleaved_lock(scope):
        # A sibling detects a ledger mismatch after retry_context reads the
        # original oracle block, but before this retry owns the token lock.
        async with store.pool.acquire() as c:
            await c.execute("UPDATE stage1_keeper_scopes SET block_kind='ledger_mismatch'")
        chain.ledger['held']+=1
        async with real_lock(scope) as locked:
            yield locked
    store.asset_lock=interleaved_lock
    with pytest.raises(Blocked,match='ledger_mismatch'):
        await worker.retry(job)
    async with store.pool.acquire() as c:
        assert await c.fetchval('SELECT blocked FROM stage1_keeper_scopes')
