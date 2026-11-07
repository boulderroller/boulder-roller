"""Real PostgreSQL holds and signed bytes; transport and riding are offline fixtures."""
import base64
import copy
import json

import pytest
from solders.compute_budget import set_compute_unit_limit
from solders.hash import Hash
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

from app.services import stage1_keeper_dung as dung
from app.services.stage1_keeper_chain import KeeperChain
from app.services.stage1_keeper_snapshot import build_snapshot
from app.services.stage1_keeper_worker import KeeperWorker
from tests.services.test_stage1_keeper_dung_archive import archive
from tests.services.test_stage1_keeper_snapshot import PEOPLE, ride
from tests.services.test_stage1_keeper_worker import store, migrated_template, due


class OfflineDungChain:
    def __init__(self, snapshot, registrations):
        self.snapshot, self.registrations = snapshot, registrations
        self.genesis = 'local-test'
        self.transport = KeeperChain('http://127.0.0.1:8899', snapshot['context'][0], '/unused')
        self.transport.signer, self.transport.genesis = Keypair(), self.genesis
        self.prepared, self.sent, self.registration_reads = [], [], 0

    async def clock(self, floor=0):
        return {'slot':100, 'now':self.snapshot['registration_cutoff']}

    async def recipient_registrations(self, people, floor=0):
        self.registration_reads += 1
        return 100, copy.deepcopy(self.registrations)

    async def observe(self, scope, week, floor):
        return {'kind':'dung', **await self.clock(), 'mints':{}, 'sets':{},
                'state':{'allocated_lifetime':0,'minted_lifetime':0},
                'hill':{'dung_next_week':1},
                'city':{'dung_start_week_plus_one':2,'dung_tss_ceiling_micros':2_000_000}}

    def signed_bytes(self, scope, op):
        message = MessageV0.try_compile(self.transport.signer.pubkey(),
            [set_compute_unit_limit(1_400_000), *self.transport.instructions(scope, op)], [], Hash.default())
        tx = VersionedTransaction(message, [self.transport.signer])
        return {'signature':str(tx.signatures[0]), 'bytes':base64.b64encode(bytes(tx)).decode(),
                'genesis':self.genesis, 'operation_kind':op['kind'], 'last_valid_block_height':200}

    async def prepare(self, scope, op, floor=0):
        self.prepared.append(copy.deepcopy(op))
        return self.signed_bytes(scope, op)

    def verify_signed_operation(self, scope, op, signed):
        return self.transport.verify_signed_operation(scope, op, signed)

    async def status(self, signed):
        return {'state':'absent','slot':100}

    async def submit(self, signed):
        self.sent.append(signed)


async def setup_worker(store, tmp_path):
    data = archive()
    data['kind'], data['recipients'] = 'dung', {}
    data['freeze_at'] = data['launch'] + 2*604800 + 86400
    other = copy.deepcopy(data['opening']['dung']['lots'][0])
    other.update(owner=PEOPLE[1], deposit_id=2, address=str(Pubkey.find_program_address(
        [b's1v1_lot', bytes(Pubkey.from_string(PEOPLE[1])), (2).to_bytes(8,'little')],
        Pubkey.from_string(data['context'][0]))[0]))
    data['opening']['dung']['lots'].append(other)
    data['opening'] = dung.freeze_dung_opening(data['opening'], data['context'])
    rows = [{**ride(i, receipt=f'ride{i}'), 'canon_id':data['canon_id'], 'tss_micros':200_000}
            for i in range(5)]
    snapshot = build_snapshot(data, rows)
    cutoff = snapshot['registration_cutoff']
    registrations = {PEOPLE[0]:{'recipient':PEOPLE[0], 'registered_at':cutoff},
                     PEOPLE[1]:{'recipient':PEOPLE[1], 'registered_at':cutoff+1}}
    p,c,h,w,m = data['context']
    scope = await store.add_scope(dict(program=p, city=c, hill=h, mint=m, kind='dung',
        canon_id=data['canon_id'], launch=data['launch'], next_week=w))
    async def frozen(*args, **kwargs):
        return copy.deepcopy(snapshot)
    store.snapshot = frozen
    chain = OfflineDungChain(snapshot, registrations)
    return KeeperWorker(store, chain, tmp_path, enabled=True), chain, scope


async def assert_held(store, scope, kind='dung_payable_total_mismatch'):
    async with store.pool.acquire() as c:
        assert tuple(await c.fetchrow('SELECT blocked,block_kind,next_week FROM stage1_keeper_scopes WHERE id=$1', scope)) == (True,kind,1)
        assert await c.fetchval('SELECT state FROM stage1_keeper_jobs WHERE scope_id=$1', scope) == 'blocked'
        assert await c.fetchval('SELECT count(*) FROM stage1_keeper_alerts WHERE scope_id=$1 AND kind=$2', scope,kind) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('role,delta', [(0,1),(0,-1),(1,1),(1,-1)])
async def test_fresh_payable_mismatch_alerts_and_holds_before_signing(store, tmp_path, monkeypatch, role, delta):
    worker, chain, scope = await setup_worker(store, tmp_path)
    original = dung.dung_plan
    def wrong_total(*args):
        derived, allocation, roles, inputs = original(*args)
        inputs['payable_role_totals'][role] += delta
        return derived, allocation, roles, inputs
    monkeypatch.setattr(dung, 'dung_plan', wrong_total)
    try:
        assert await worker.run_once(scope) == 'blocked'
        await assert_held(store, scope)
        assert chain.prepared == chain.sent == []
    finally:
        await chain.transport.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('fault,index', [('input',0),('operation',0),('operation',2),('root',2),
                                        ('missing',0),('boolean',0),('recipient',0),('tss',0),('source',0),('snapshot',0)])
async def test_saved_mismatch_holds_before_publish_or_role_root(store, tmp_path, monkeypatch, fault, index):
    worker, chain, scope = await setup_worker(store, tmp_path)
    save = store.save_plan
    async def save_legacy_plan(claim, plan):
        # Reproduce a bad plan already persisted by an older worker. The new
        # planner's check has run; only the restart guard can catch this copy.
        plan = copy.deepcopy(plan)
        if fault == 'input':
            plan['snapshot']['dung_input']['payable_role_totals'][1] += 1
        elif fault == 'operation':
            plan['operations'][0]['input'] = copy.deepcopy(plan['operations'][0]['input'])
            plan['operations'][0]['input']['payable_role_totals'][0] += 1
        elif fault == 'root':
            plan['operations'][2]['total'] += 1
        elif fault == 'missing':
            del plan['snapshot']['dung_input']['payable_role_totals']
        elif fault == 'boolean':
            plan['snapshot']['dung_input']['payable_role_totals'][0] = True
        elif fault == 'recipient':
            plan['snapshot']['recipients'][PEOPLE[1]] = PEOPLE[1]
        elif fault == 'tss':
            plan['snapshot']['dung_input']['postbond_tss_micros'] += 1
        elif fault == 'source':
            plan['snapshot']['dung_input']['source_snapshot'] = 'ff'*32
        elif fault == 'snapshot':
            plan['snapshot'] = []
        await save(claim, plan)
    monkeypatch.setattr(store, 'save_plan', save_legacy_plan)
    claim = await store.claim(scope)
    try:
        assert await worker.plan(claim, await chain.observe(claim['scope'],1,0), snapshot=chain.snapshot)
        async with store.pool.acquire() as c:
            await c.execute('UPDATE stage1_keeper_jobs SET operation_index=$2 WHERE id=$1', claim['job']['id'],index)
        await store.release(claim)
        restarted = KeeperWorker(store, chain, tmp_path, enabled=True)
        assert await restarted.run_once(scope) == 'blocked'
        await assert_held(store, scope)
        assert chain.prepared == chain.sent == [] and chain.registration_reads == 1
    finally:
        await chain.transport.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('index,fault', [(0,'total'),(2,'total'),(0,'account'),(0,'signature'),(0,'bytes')])
async def test_resend_binds_signed_bytes_to_checked_totals_and_accounts(store, tmp_path, index, fault):
    worker, chain, scope = await setup_worker(store, tmp_path)
    claim = await store.claim(scope)
    try:
        assert await worker.plan(claim, await chain.observe(claim['scope'],1,0), snapshot=chain.snapshot)
        await store.refresh(claim)
        op = copy.deepcopy(claim['job']['operations'][index])
        signing_scope = dict(claim['scope'])
        if fault == 'total':
            if index == 0:
                op['input']['payable_role_totals'][1] += 1
            else:
                op['total'] += 1
        elif fault == 'account':
            signing_scope['hill'] = str(Keypair().pubkey())
        signed = chain.signed_bytes(signing_scope,op)
        if fault == 'signature':
            signed['signature'] = 'wrong-signature'
        elif fault == 'bytes':
            signed['bytes'] = 'malformed'
        async with store.pool.acquire() as c:
            await c.execute('UPDATE stage1_keeper_jobs SET operation_index=$2 WHERE id=$1',claim['job']['id'],index)
        await store.refresh(claim)
        await store.signed(claim,signed)
        await store.release(claim)
        restarted = KeeperWorker(store, chain, tmp_path, enabled=True)
        assert await restarted.run_once(scope) == 'blocked'
        await assert_held(store,scope,'dung_signed_operation_mismatch')
        assert chain.prepared == chain.sent == [] and chain.registration_reads == 1
    finally:
        await chain.transport.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('registered', [True,False])
async def test_frozen_registered_shares_publish_and_resend_without_refreeze(store, tmp_path, registered):
    worker, chain, scope = await setup_worker(store, tmp_path)
    if not registered:
        chain.registrations = {}
    try:
        assert await worker.run_once(scope) == 'submitted'
        async with store.pool.acquire() as c:
            job = await c.fetchrow('SELECT snapshot,allocation,claims,operations,signed FROM stage1_keeper_jobs WHERE scope_id=$1', scope)
        snapshot,allocation,claims,operations,signed = [json.loads(value) for value in job]
        payable = [sum(allocation[name].values()) for name in ('riders','backers')]
        assert payable == snapshot['dung_input']['payable_role_totals'] == [r['total'] for r in claims['roles']]
        assert payable == ([35_000,250_000] if registered else [0,0])
        assert allocation['unminted'] == 1_000_000-sum(payable)
        assert snapshot['recipients'] == ({PEOPLE[0]:PEOPLE[0]} if registered else {})
        assert operations[0]['kind'] == 'dung_publish' and signed == chain.sent[0]
        # Late registration and changed transport responses cannot alter a
        # durable week's shares, including a zero-payable nonzero-potential week.
        chain.registrations = {p:{'recipient':p,'registered_at':snapshot['registration_cutoff']+1} for p in PEOPLE}
        await due(store)
        restarted = KeeperWorker(store,chain,tmp_path,enabled=True)
        assert await restarted.run_once(scope) == 'submitted'
        assert chain.registration_reads == 1 and len(chain.prepared) == 1
        assert chain.sent == [signed,signed]
    finally:
        await chain.transport.close()
