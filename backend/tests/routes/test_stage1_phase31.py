"""Local PostgreSQL and unsigned/synthetic wallet fixtures; no chain broadcasts."""
import asyncio
import base64
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import asyncpg
import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from solders.hash import Hash
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import Transaction

from app.dependencies import AuthenticatedUser, get_current_user, get_repository
from app.routes import stage1, stage1_actions as routes
from app.services import stage1_transactions as txs
from app.services.balance_transaction_coordinator import BalanceTransactionCoordinator, InMemoryBalanceOperationLog
from scripts.generate_stage1_transaction_fixtures import fixture_builder, WALLET
from tests.routes.test_stage1_phase3 import api
from tests.services.test_stage1_keeper_worker import store, migrated_template

BACKEND = Path(__file__).parents[2]
MONDAY_NOON = 1791201600 + 40 * 604800


@pytest.fixture
def withdrawal_api(monkeypatch):
    wall = [MONDAY_NOON - 1]
    monkeypatch.setattr(txs, 'time', SimpleNamespace(time=lambda: wall[0]), raising=False)
    monkeypatch.setattr(routes, 'time', SimpleNamespace(time=lambda: wall[0], monotonic=lambda: wall[0]))
    builder, rows, _, _, lot, request, exit_lot = fixture_builder()
    rows[str(builder.pda('s1v1_city'))]['season_anchor'] = 1791201600
    rows[str(lot)]['pending_request'] = str(request)
    builder.clock = AsyncMock(side_effect=lambda: int(wall[0]) - 13)
    builder.simulate = AsyncMock(return_value=True)
    builder.fee_payer = Keypair.from_seed(bytes([2] * 32))
    builder._get_recent_blockhash = AsyncMock(return_value=(Hash.default(), 123456))
    builder.submit_signed_transaction = AsyncMock(side_effect=lambda raw, **kw: str(Transaction.from_bytes(base64.b64decode(raw)).signatures[0]))
    log = InMemoryBalanceOperationLog()
    builder.test_log = log
    monkeypatch.setattr(routes, 'load_record', lambda c, id, user: log.get(id))
    monkeypatch.setattr(routes, '_balance_coordinator', lambda _: BalanceTransactionCoordinator(sink=log))
    routes.eligibility_cache.clear()
    app = FastAPI()
    app.include_router(stage1.router, prefix='/stage1')
    user = AuthenticatedUser(wallet=str(WALLET), user_id='owner', device_id='test')
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_repository] = lambda: SimpleNamespace(client=object())
    app.dependency_overrides[routes.action_builder] = lambda: builder
    app.dependency_overrides[routes.action_read_builder] = lambda: builder
    return TestClient(app), builder, wall, lot, request, exit_lot, user


@pytest.mark.parametrize('action', ['begin-withdrawal', 'complete-withdrawal'])
@pytest.mark.parametrize('offset', [-1, 0, 12, 59.999, 60, 86400])
def test_withdrawal_prepare_pauses_only_first_monday_noon_minute(withdrawal_api, action, offset):
    client, builder, wall, lot, request, exit_lot, _ = withdrawal_api
    wall[0] = MONDAY_NOON + offset
    result = client.post(f'/stage1/me/{action}/prepare', json={
        'lot': str(exit_lot if action == 'complete-withdrawal' else lot), 'request': str(request)})
    paused = 0 <= offset < 60
    assert result.status_code == (409 if paused else 200), result.text
    if paused:
        assert result.json()['detail'] == {'code': 'stage1_withdrawal_paused', 'retry_at': str(MONDAY_NOON + 60)}
        builder._get_recent_blockhash.assert_not_awaited()
    builder.submit_signed_transaction.assert_not_awaited()


@pytest.mark.parametrize('action', ['begin-withdrawal', 'complete-withdrawal'])
def test_prepared_withdrawal_cannot_submit_during_pause(withdrawal_api, action):
    client, builder, wall, lot, request, exit_lot, _ = withdrawal_api
    payload = {'lot': str(exit_lot if action == 'complete-withdrawal' else lot), 'request': str(request)}
    prepared = client.post(f'/stage1/me/{action}/prepare', json=payload)
    assert prepared.status_code == 200, prepared.text
    tx = Transaction.from_bytes(base64.b64decode(prepared.json()['prepared_transaction']['transaction']))
    tx.partial_sign([Keypair.from_seed(bytes([7] * 32))], tx.message.recent_blockhash)
    wall[0] = MONDAY_NOON + 1  # Finalized clock still belongs to the old week.
    result = client.post(f'/stage1/me/{action}', json={**payload,
        'signed_transaction': base64.b64encode(bytes(tx)).decode(),
        'last_valid_block_height': 123456, 'client_request_id': 'prepared-before-noon'})
    assert result.status_code == 409, result.text
    assert result.json()['detail']['code'] == 'stage1_withdrawal_paused'
    builder.submit_signed_transaction.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ['begin-withdrawal', 'complete-withdrawal'])
async def test_direct_withdrawal_plan_refuses_wall_clock_pause(withdrawal_api, action):
    _, builder, wall, lot, request, exit_lot, _ = withdrawal_api
    wall[0] = MONDAY_NOON
    with pytest.raises(ValueError, match='withdrawal pause'):
        await builder.plan(action, routes.WithdrawalRequest(
            lot=str(exit_lot if action == 'complete-withdrawal' else lot), request=str(request)), str(WALLET))


@pytest.mark.parametrize('action', ['begin-withdrawal', 'complete-withdrawal'])
def test_rpc_preflight_crossing_noon_never_sends_and_preserves_pending_record(withdrawal_api, monkeypatch, action):
    from app.services import tx_builder
    client, builder, wall, lot, request, exit_lot, _ = withdrawal_api
    builder.submit_signed_transaction = tx_builder.TxBuilder.submit_signed_transaction.__get__(builder)
    payload = {'lot': str(exit_lot if action == 'complete-withdrawal' else lot), 'request': str(request)}
    prepared = client.post(f'/stage1/me/{action}/prepare', json=payload)
    assert prepared.status_code == 200, prepared.text
    tx = Transaction.from_bytes(base64.b64decode(prepared.json()['prepared_transaction']['transaction']))
    tx.partial_sign([Keypair.from_seed(bytes([7] * 32))], tx.message.recent_blockhash)
    rpc = SimpleNamespace(get_signature_statuses=AsyncMock(return_value=SimpleNamespace(value=[None])),
        get_block_height=AsyncMock(return_value=SimpleNamespace(value=1)),
        send_raw_transaction=AsyncMock(return_value=SimpleNamespace(value=tx.signatures[0])))
    @asynccontextmanager
    async def rpc_client(*args, **kwargs):
        yield rpc
    async def validity(*args, **kwargs):
        wall[0] = MONDAY_NOON + 1
        return SimpleNamespace(value=True)
    monkeypatch.setattr(tx_builder, 'AsyncClient', rpc_client)
    monkeypatch.setattr(tx_builder, 'is_blockhash_valid_compat', validity)
    monkeypatch.setattr(tx_builder, 'confirm_signature_with_retry', AsyncMock(return_value=SimpleNamespace(slot=123)))
    signed = {**payload, 'signed_transaction': base64.b64encode(bytes(tx)).decode(),
        'last_valid_block_height': 123456, 'client_request_id': 'crossing-during-rpc'}
    # Repeat through the existing-operation path as well as the first insertion.
    for attempt in range(2):
        wall[0] = MONDAY_NOON - 1
        result = client.post(f'/stage1/me/{action}', json=signed)
        assert result.status_code == 200, result.text
        assert result.json().get('withdrawals_paused_until') == str(MONDAY_NOON + 60)
        assert result.json()['operation']['confirmation_status'] == 'prepared'
        assert result.json()['next_step'] == 'pending'
        rpc.send_raw_transaction.assert_not_awaited()
        assert len(builder.test_log.records) == 1
    # Only subsequent finalized expiry releases this reservation for retry.
    from app.services import stage1_operation_status as status
    from app.services.balance_operation_status import operation_status_from_record
    from app.routes.balance_operations import _rider_response
    monkeypatch.setenv('STAGE1_ACTIONS_ENABLED', 'true')
    builder.require_enabled_chain = AsyncMock()
    monkeypatch.setattr(txs, 'get_stage1_tx_builder', lambda: builder)
    monkeypatch.setattr(status, 'load_record', lambda client, id, user: builder.test_log.get(id))
    coordinator = BalanceTransactionCoordinator(sink=builder.test_log)
    monkeypatch.setattr(status, 'BalanceTransactionCoordinator', lambda **kw: coordinator)
    rpc.get_genesis_hash = AsyncMock(return_value=SimpleNamespace(value='offline-genesis'))
    monkeypatch.setattr(status, 'AsyncClient', rpc_client)
    monkeypatch.setattr(status, 'is_blockhash_valid_compat', AsyncMock(return_value=SimpleNamespace(value=False)))
    record = next(iter(builder.test_log.records.values()))
    recovered = asyncio.run(status.reconcile_stage1_operation(operation_status_from_record(record), object()))
    assert recovered.support.confirmation_status == 'expired'
    assert builder.test_log.get(record.operation_id).confirmation_status == 'expired'
    assert _rider_response(recovered).stage1_terminal_failure is True


@pytest.mark.asyncio
async def test_eligibility_pause_overrides_cached_actions_and_recovers_at_1201(withdrawal_api):
    _, builder, wall, lot, _, _, user = withdrawal_api
    payload = routes.EligibilityRequest(lot=str(lot))
    first = await routes.eligibility(payload, Response(), user, builder)
    assert 'begin-withdrawal' in first['actions']
    wall[0] = MONDAY_NOON + 1
    paused = await routes.eligibility(payload, Response(), user, builder)
    assert paused.get('withdrawals_paused_until') == str(MONDAY_NOON + 60)
    assert 'begin-withdrawal' not in paused['actions']
    assert 'complete-withdrawal' not in paused['actions']
    assert 'convert-pledge' in paused['actions']
    wall[0] = MONDAY_NOON + 55  # Finality has caught up; the cache must still end at 12:01.
    assert (await routes.eligibility(payload, Response(), user, builder))['withdrawals_paused_until'] == str(MONDAY_NOON + 60)
    wall[0] = MONDAY_NOON + 60
    resumed = await routes.eligibility(payload, Response(), user, builder)
    assert not resumed.get('withdrawals_paused_until')
    assert resumed['week'] == '40'
    assert 'begin-withdrawal' in resumed['actions']


async def balance_schema(connection):
    await connection.execute('DROP TABLE balance_operations CASCADE')
    await connection.execute((BACKEND / 'sql/172_balance_operations.sql').read_text())


@pytest.mark.asyncio
async def test_migration_174_times_out_behind_open_writer_then_applies(store):
    migration = (BACKEND / 'sql/174_stage1_pending_intents.sql').read_text()
    assert migration == (BACKEND / 'supabase/migrations/20261015233000_174_stage1_pending_intents.sql').read_text()
    async with store.pool.acquire() as holder, store.pool.acquire() as migrator:
        await balance_schema(holder)
        async with holder.transaction():
            await holder.execute('LOCK TABLE balance_operations IN ROW EXCLUSIVE MODE')
            with pytest.raises(asyncpg.LockNotAvailableError):
                await asyncio.wait_for(migrator.execute(migration), timeout=7)
            await migrator.execute('ROLLBACK')
        await migrator.execute(migration)
        assert await migrator.fetchval("SELECT indisvalid FROM pg_index WHERE indexrelid='idx_balance_stage1_pending_intent'::regclass")


@pytest.mark.asyncio
async def test_lookup_pagination_recovers_51_owner_references_and_excludes_other_owners(store, api, monkeypatch):
    _, app, builder = api
    owner = '8qbHbw2BbbTHBW1sbeqakYXVKRQM8Ne7pLK7m6CVfeR'
    addresses = sorted(str(Pubkey.new_unique()) for _ in range(51))
    other_addresses = [str(Pubkey.new_unique()) for _ in range(4)]
    async with store.pool.acquire() as connection:
        await balance_schema(connection)
        records = [(f'owner-{i}', 'owner', owner, address, owner, 'local-test') for i, address in enumerate(addresses)]
        # Repeated ledger operations must not repeat a lookup reference.
        records.append(('owner-repeat', 'owner', owner, addresses[0], owner, 'local-test'))
        records.extend([
            ('other-person', 'someone-else', owner, other_addresses[0], owner, 'local-test'),
            ('other-wallet', 'owner', str(Pubkey.new_unique()), other_addresses[1], owner, 'local-test'),
            ('other-program', 'owner', owner, other_addresses[2], str(Pubkey.new_unique()), 'local-test'),
            ('other-genesis', 'owner', owner, other_addresses[3], owner, 'another-network'),
        ])
        await connection.executemany("""INSERT INTO balance_operations
            (operation_id,idempotency_key,rider_account_id,protocol_wallet,action_type,authority_model,
             reference_type,reference_id,confirmation_status,metadata)
            VALUES($1,$1,$2,$3,'stage1_claim_transport','wallet_boundary','stage1',$4,'finalized',
              jsonb_build_object('program',$5::text,'genesis',$6::text,'transport_mode','create'))""", records)
    monkeypatch.setattr(routes, 'get_pool', AsyncMock(return_value=store.pool))
    builder.lookup_state = AsyncMock(return_value='active')
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://local') as client:
        first = await client.get('/stage1/me/lookups')
        assert first.status_code == 200, first.text
        assert first.json()['next_offset'] == 50
        assert len(first.json()['tables']) == 50
        second = await client.get('/stage1/me/lookups', params={'offset': first.json()['next_offset']})
        assert second.status_code == 200, second.text
        assert second.json()['next_offset'] is None
        assert len(second.json()['tables']) == 1
    actual = [row['address'] for page in (first, second) for row in page.json()['tables']]
    assert actual == addresses
    assert set(actual).isdisjoint(other_addresses)
    assert builder.lookup_state.await_count == 51
    assert all(call.args[1] == Pubkey.from_string(owner) for call in builder.lookup_state.await_args_list)
