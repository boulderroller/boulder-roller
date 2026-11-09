"""Offline RPC fakes plus disposable PostgreSQL; never broadcasts a transaction."""
import asyncio
import base64
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient
from solders.pubkey import Pubkey

from app.dependencies import AuthenticatedUser, get_current_user, get_repository, get_user_repository
from app.routes import stage1, stage1_actions as routes
from app.services import stage1_availability

WALLET = '8qbHbw2BbbTHBW1sbeqakYXVKRQM8Ne7pLK7m6CVfeR'


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv('STAGE1_ACTIONS_ENABLED', 'true')
    monkeypatch.setattr(stage1_availability, 'stored_network', AsyncMock(return_value={'program': WALLET, 'genesis': 'local-test'}))
    builder = SimpleNamespace(program_id=Pubkey.from_string(WALLET),
        require_enabled_chain=AsyncMock(side_effect=AssertionError('Read must not refresh version')),
        account=AsyncMock(return_value={'owner': WALLET, 'pending_request': WALLET, 'season_anchor': 1791201600}),
        pda=lambda *args: Pubkey.from_string(WALLET), clock=AsyncMock(return_value=1791201600 + 604800 + 1),
        plan=AsyncMock(side_effect=lambda action, payload, wallet, **kwargs: payload), simulate=AsyncMock(return_value=True),
        rpc_url='local', requires_lookup=lambda _: False)
    builder.discovery_reader = lambda: builder
    monkeypatch.setattr(routes, 'get_stage1_tx_builder', lambda: builder)
    if hasattr(routes, 'claim_cache'):
        routes.claim_cache.clear()
    @asynccontextmanager
    async def acquire():
        # Claim discovery binds proofs to the stored release genesis.
        yield SimpleNamespace(fetch=AsyncMock(return_value=[]), fetchval=AsyncMock(return_value='local-test'))
    monkeypatch.setattr(routes, 'get_pool', AsyncMock(return_value=SimpleNamespace(acquire=acquire)))
    # Clear only this service's local preflight cache between isolated tests.
    if hasattr(routes, 'eligibility_cache'):
        routes.eligibility_cache.clear()
    from app.middleware.rate_limiter import rate_limiter
    monkeypatch.setattr(rate_limiter, 'check_rate_limit', AsyncMock(return_value=(True, 10, 60)))
    app = FastAPI()
    app.include_router(stage1.router, prefix='/stage1')
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(wallet=WALLET, user_id='owner', device_id='test')
    app.dependency_overrides[get_repository] = lambda: None
    app.dependency_overrides[get_user_repository] = lambda: None
    return TestClient(app), app, builder


def test_claim_and_eligibility_reads_use_stored_version_without_rpc_write(api):
    client, _, builder = api
    assert client.get('/stage1/me/claims').status_code == 200
    result = client.post('/stage1/me/eligibility', json={'lot': WALLET})
    assert result.status_code == 200, result.text
    assert result.json()['chain_time'] == str(1791201600 + 604800 + 1)
    assert result.json()['week'] == '1'
    builder.require_enabled_chain.assert_not_awaited()


def test_eligibility_cache_is_per_person_wallet_and_lot_and_rate_limited(api, monkeypatch):
    # A cached result never outlives its chain week (it ends 19 Oct 2026 12:00 UTC
    # here), so pin the wall clock inside that week, clear of the Monday-noon pause.
    import time
    monkeypatch.setattr(time, 'time', lambda: 1791201600 + 604800 + 3600)
    client, app, builder = api
    first = client.post('/stage1/me/eligibility', json={'lot': WALLET})
    assert first.status_code == 200
    count = builder.simulate.await_count
    assert client.post('/stage1/me/eligibility', json={'lot': WALLET}).json() == first.json()
    assert builder.simulate.await_count == count
    from app.middleware.rate_limiter import rate_limiter
    rate_limiter.check_rate_limit.return_value = (False, 0, 60)
    assert client.post('/stage1/me/eligibility', json={'lot': str(Pubkey.new_unique())}).status_code == 429
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(wallet=WALLET, user_id='different-person', device_id='test')
    assert client.post('/stage1/me/eligibility', json={'lot': WALLET}).status_code == 429
    assert builder.simulate.await_count == count


def test_durable_lookup_discovery_is_owner_scoped_and_survives_new_client(api, monkeypatch):
    client, app, builder = api
    reads = []
    async def fetch(sql, *args):
        reads.append((sql, args))
        return [{'reference_id': WALLET, 'closed': False}]
    @asynccontextmanager
    async def acquire():
        yield SimpleNamespace(fetch=fetch)
    monkeypatch.setattr(routes, 'get_pool', AsyncMock(return_value=SimpleNamespace(acquire=acquire)))
    builder.lookup_state = AsyncMock(return_value='active')
    for session in (client, TestClient(app)):
        result = session.get('/stage1/me/lookups')
        assert result.status_code == 200, result.text
        assert result.json() == {'tables': [{'address': WALLET, 'state': 'active'}], 'next_offset': None}
    assert all('rider_account_id=$1' in sql and 'protocol_wallet=$2' in sql for sql, _ in reads)
    assert reads[0][1][:4] == ('owner', WALLET, WALLET, 'local-test')
    builder.lookup_state.assert_awaited_with(WALLET, Pubkey.from_string(WALLET))
    builder.lookup_state.side_effect = ValueError('Other authority')
    assert client.get('/stage1/me/lookups').json()['tables'] == []
    del app.dependency_overrides[get_current_user]
    assert client.get('/stage1/me/lookups').status_code in (401, 403)

# The real database, not a process-local lock, arbitrates the simultaneous tabs.
from tests.services.test_stage1_keeper_worker import store, migrated_template, DSN


@pytest.mark.asyncio
async def test_two_tabs_same_pledge_intent_only_one_durable_operation_and_send(store, monkeypatch):
    import psycopg2
    from psycopg2.extras import Json
    from httpx import ASGITransport, AsyncClient
    from solders.hash import Hash
    from solders.keypair import Keypair
    from solders.transaction import Transaction
    from app.services.balance_transaction_coordinator import BalanceTransactionCoordinator, InMemoryBalanceOperationLog, BalanceOperationError
    from scripts.generate_stage1_transaction_fixtures import fixture_builder, WALLET as owner
    backend = Path(__file__).parents[2]
    async with store.pool.acquire() as connection:
        await connection.execute('DROP TABLE balance_operations CASCADE')
        await connection.execute((backend/'sql/172_balance_operations.sql').read_text())
        migration = backend/'sql/174_stage1_pending_intents.sql'
        if migration.exists():
            await connection.execute(migration.read_text())
    class Ledger(InMemoryBalanceOperationLog):
        def insert(self, record):
            with psycopg2.connect(DSN, database=store.test_database) as c:
                row = record.to_row()
                try:
                    with c.cursor() as cursor:
                        cursor.execute('INSERT INTO balance_operations (' + ','.join(row) + ') VALUES (' + ','.join(['%s']*len(row)) + ')',
                            [Json(v) if isinstance(v,dict) else v for v in row.values()])
                except psycopg2.IntegrityError as exc:
                    raise BalanceOperationError('Conflict') from exc
            super().insert(record)
    log = Ledger()
    builder, *_ = fixture_builder()
    builder.fee_payer = Keypair.from_seed(bytes([2]*32))
    builder._get_recent_blockhash = AsyncMock(return_value=(Hash.default(), 123456))
    entered, release = asyncio.Event(), asyncio.Event()
    async def send(tx, **kwargs):
        entered.set()
        await release.wait()
        return str(Transaction.from_bytes(base64.b64decode(tx)).signatures[0])
    builder.submit_signed_transaction = AsyncMock(side_effect=send)
    monkeypatch.setattr(routes, '_balance_coordinator', lambda _: BalanceTransactionCoordinator(sink=log))
    monkeypatch.setattr(routes, 'load_record', lambda c, id, user: log.get(id))
    monkeypatch.setattr(routes, 'get_pool', AsyncMock(return_value=store.pool))
    vector = json.loads((backend.parent/'web/portal/scripts/fixtures/prepared-stage1-transactions.json').read_text())
    request = next(v['request'] for v in vector if v['name']=='pledge_bonded')
    app = FastAPI()
    app.include_router(stage1.router, prefix='/stage1')
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(wallet=str(owner), user_id='owner', device_id='test')
    app.dependency_overrides[get_repository] = lambda: SimpleNamespace(client=object())
    app.dependency_overrides[routes.action_builder] = lambda: builder
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://local') as client:
        payloads=[]
        for tab in (1,2):
            payload={**request,'deposit_id':str(tab)}
            prepared=await client.post('/stage1/me/pledge/prepare',json=payload)
            assert prepared.status_code==200, prepared.text
            tx=Transaction.from_bytes(base64.b64decode(prepared.json()['prepared_transaction']['transaction']))
            tx.partial_sign([Keypair.from_seed(bytes([7]*32))],tx.message.recent_blockhash)
            payloads.append({**payload,'signed_transaction':base64.b64encode(bytes(tx)).decode(),'last_valid_block_height':123456,'client_request_id':f'tab-{tab}'})
        first=asyncio.create_task(client.post('/stage1/me/pledge',json=payloads[0]))
        await asyncio.wait_for(entered.wait(),5)
        second=asyncio.create_task(client.post('/stage1/me/pledge',json=payloads[1]))
        # Let both requests reach the atomic insert while the first send waits.
        for _ in range(100):
            if second.done() or builder.submit_signed_transaction.await_count > 1: break
            await asyncio.sleep(.01)
        release.set()
        responses=await asyncio.gather(first,second)
        assert [r.status_code for r in responses]==[200,409], [r.text for r in responses]
        assert responses[1].json()['detail']['operation_id']==responses[0].json()['operation']['operation_id']
        assert builder.submit_signed_transaction.await_count==1
        async with store.pool.acquire() as connection:
            assert await connection.fetchval('SELECT count(*) FROM balance_operations')==1


@pytest.mark.asyncio
@pytest.mark.parametrize('ready', [True, False])
async def test_stale_indexer_keeps_status_and_notifications_admitted_but_reads_unavailable(store, monkeypatch, ready):
    from app import db_pool, solana_direct
    from app.routes import health, notifications
    from fastapi import HTTPException
    monkeypatch.setenv('STAGE1_UI_ENABLED', 'true')
    monkeypatch.setenv('STAGE1_ACTIONS_ENABLED', 'true')
    monkeypatch.setattr(db_pool, 'get_pool', AsyncMock(return_value=store.pool))
    monkeypatch.setattr(stage1, 'get_pool', AsyncMock(return_value=store.pool))
    monkeypatch.setattr(solana_direct, 'load_readonly_config', lambda: SimpleNamespace(program_id='program'))
    async with store.pool.acquire() as connection:
        await connection.execute("INSERT INTO program_version_observations VALUES('local-test','program',77)")
        await connection.execute("""INSERT INTO stage1_indexer_network
            (genesis,program,from_slot,from_time,through_slot,through_time,through_epoch,ready,updated_at)
            VALUES('local-test','program',1,1,100,1,0,$1,now()-interval '91 seconds')""", ready)
    assert await health.stage1_availability() == {'live': True, 'actions': True}
    user = AuthenticatedUser(wallet=WALLET, user_id='owner', device_id='test')
    repo = SimpleNamespace(get_wallet_notifications=AsyncMock(return_value=[]), get_unread_count=AsyncMock(return_value=1))
    assert (await notifications.get_notifications(current_user=user, repo=repo))['unread_count'] == 1
    assert repo.get_wallet_notifications.call_args.kwargs['exclude_stage1'] is False
    assert repo.get_unread_count.call_args.kwargs['exclude_stage1'] is False
    with pytest.raises(HTTPException) as failure:
        await anext(stage1.stage1_connection(Response()))
    assert failure.value.status_code == 503


@pytest.mark.asyncio
async def test_lookup_cooldown_uses_finalized_slot_hashes_and_rejects_other_authority(monkeypatch):
    import struct
    from app.services import stage1_transactions as txs
    from scripts.generate_stage1_transaction_fixtures import fixture_builder, WALLET as owner
    builder, *_ = fixture_builder()
    raw = bytearray(56)
    struct.pack_into('<IQQ', raw, 0, 1, 1000, 1)
    raw[21] = 1
    raw[22:54] = bytes(owner)
    history = struct.pack('<Q', 1) + struct.pack('<Q', 1000) + bytes(32)
    response = SimpleNamespace(context=SimpleNamespace(slot=2000), value=[
        SimpleNamespace(owner=txs.LOOKUP, executable=False, data=bytes(raw)), SimpleNamespace(data=history)])
    rpc = SimpleNamespace(get_multiple_accounts=AsyncMock(return_value=response))
    @asynccontextmanager
    async def client(*args, **kwargs): yield rpc
    monkeypatch.setattr(txs, 'AsyncClient', client)
    assert await builder.lookup_state(str(owner), owner) == 'cooling'  # 1000+512 is insufficient.
    response.context.slot = 1001
    response.value[1].data = struct.pack('<Q', 1) + struct.pack('<Q', 1001) + bytes(32)
    assert await builder.lookup_state(str(owner), owner) == 'closeable'  # Skipped slots need not wait 512.
    with pytest.raises(ValueError, match='owner mismatch'):
        await builder.lookup_state(str(owner), Pubkey.new_unique())
    assert rpc.get_multiple_accounts.call_args.kwargs['commitment'] == 'finalized'


@pytest.mark.asyncio
async def test_monday_withdrawal_plan_and_intent_use_the_same_live_week(monkeypatch):
    from app.services import stage1_transactions as txs
    from scripts.generate_stage1_transaction_fixtures import fixture_builder, WALLET as owner
    builder, rows, _, _, lot, request, _ = fixture_builder()
    city = rows[str(builder.pda('s1v1_city'))]
    city['season_anchor'] = 1791201600  # Monday noon UTC.
    now = city['season_anchor'] + 40*604800 + 60
    monkeypatch.setattr(txs, 'time', SimpleNamespace(time=lambda: now))
    builder.clock = AsyncMock(return_value=now)
    payload = routes.WithdrawalRequest(lot=str(lot), request=str(request))
    plan = await builder.plan('begin-withdrawal', payload, str(owner))
    assert plan.intent['week'] == '40'
    # One read prevents the sweep and independently checked intent straddling weeks.
    builder.clock.assert_awaited_once()
    from struct import pack
    open_week = next(ix for ix in plan.instructions if bytes(ix.data).endswith(pack('<Q', 40)))
    assert open_week is not None


@pytest.mark.asyncio
async def test_cached_eligibility_expires_at_monday_before_withdrawal_prepare(monkeypatch):
    from app.services import stage1_transactions as txs
    from scripts.generate_stage1_transaction_fixtures import fixture_builder, WALLET as owner
    from app.middleware.rate_limiter import rate_limiter
    builder, rows, _, _, lot, request, _ = fixture_builder()
    anchor = 1791201600
    rows[str(builder.pda('s1v1_city'))]['season_anchor'] = anchor
    boundary = anchor + 40*604800
    wall, monotonic = [boundary-1], [1]
    monkeypatch.setattr(routes, 'time', SimpleNamespace(time=lambda:wall[0], monotonic=lambda:monotonic[0]))
    monkeypatch.setattr(txs, 'time', SimpleNamespace(time=lambda:wall[0]))
    monkeypatch.setattr(rate_limiter, 'check_rate_limit', AsyncMock(return_value=(True,10,60)))
    builder.clock = AsyncMock(side_effect=lambda:wall[0])
    builder.simulate = AsyncMock(return_value=True)
    routes.eligibility_cache.clear()
    user = AuthenticatedUser(wallet=str(owner), user_id='boundary-owner', device_id='test')
    payload = routes.EligibilityRequest(lot=str(lot))
    first = await routes.eligibility(payload, Response(), user, builder)
    assert first['week'] == '39'
    wall[0], monotonic[0] = boundary+60, 62
    second = await routes.eligibility(payload, Response(), user, builder)
    plan = await builder.plan('begin-withdrawal', routes.WithdrawalRequest(lot=str(lot), request=str(request)), str(owner))
    assert second['week'] == plan.intent['week'] == '40'
    assert second['chain_time'] == str(boundary+60)
