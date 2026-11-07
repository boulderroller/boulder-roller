from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.routes import stage1
from app.dependencies import get_current_user, get_repository, get_user_repository, AuthenticatedUser
from tests.services.test_stage1_keeper_worker import store, migrated_template


@pytest.mark.asyncio
async def test_owner_read_queries_execute_against_the_migrated_projection_schema(store, monkeypatch):
    from app.routes import stage1_actions
    from fastapi import Response
    user = AuthenticatedUser(wallet='owner-wallet', user_id='owner', device_id='test')
    async with store.pool.acquire() as connection:
        assert await stage1.registration(user=user, c=connection) == {'registration': None, 'held': []}
        assert await stage1.pledges(limit=50, offset=0, user=user, c=connection) == {'pledges': []}
        assert await stage1.owner_pay(connection, user.wallet, None, None, None, 50, 0) == {'paid': [], 'pending': [], 'has_more': False}
        @asynccontextmanager
        async def proofs(action):
            yield connection
        monkeypatch.setattr(stage1_actions, 'proof_connection', proofs)
        claims = await stage1_actions.claims(Response(), limit=20, offset=0, user=user, builder=SimpleNamespace(program_id='program'))
        assert claims['claims'] == []


@pytest.fixture
def api():
    app=FastAPI();app.include_router(stage1.router,prefix='/stage1')
    db=SimpleNamespace(fetch=AsyncMock(return_value=[]),fetchrow=AsyncMock(return_value=None))
    async def connection():
        yield db
    app.dependency_overrides[stage1.stage1_connection]=connection
    if hasattr(stage1,'public_stage1_connection'):
        app.dependency_overrides[stage1.public_stage1_connection]=connection
    app.dependency_overrides[get_repository]=lambda:SimpleNamespace()
    app.dependency_overrides[get_user_repository]=lambda:SimpleNamespace()
    app.dependency_overrides[get_current_user]=lambda:AuthenticatedUser(wallet='owner-wallet',user_id='owner',device_id='test')
    return TestClient(app),db,app


@pytest.mark.parametrize('route',['registration','pay','pledges','dung'])
def test_owner_reads_bind_the_authenticated_wallet(api,route):
    client,db,app=api
    response=client.get('/stage1/me/'+route+'?wallet=someone-else')
    assert response.status_code==200
    calls=db.fetch.call_args_list+db.fetchrow.call_args_list
    assert calls and all('owner-wallet' in call.args[1:] for call in calls)
    assert all('someone-else' not in call.args for call in calls)
    del app.dependency_overrides[get_current_user]
    assert client.get('/stage1/me/'+route).status_code in (401,403)


def test_no_public_person_payment_or_proof_route(api):
    client,_,_=api
    for path in ('/stage1/people/owner-wallet/pay','/stage1/proofs','/stage1/pay?person=owner-wallet'):
        assert client.get(path).status_code==404


def test_missing_hill_is_absent(api):
    client,_,_=api
    assert client.get('/stage1/hills/11111111111111111111111111111111/bonding').status_code==404


def test_climb_hill_identity_requires_unique_canonical_mapping(api):
    client, db, _ = api
    climb = '00000000-0000-0000-0000-000000000001'
    assert client.get(f'/stage1/climbs/{climb}/hill').json() == {'hill': None}
    db.fetch.return_value = [{'hill': 'admitted-hill'}]
    assert client.get(f'/stage1/climbs/{climb}/hill').json() == {'hill': 'admitted-hill'}
    sql = db.fetch.call_args.args[0]
    assert 'quarantined' in sql and 'canon_climbs' in sql
    db.fetch.return_value = [{'hill': 'one'}, {'hill': 'two'}]
    assert client.get(f'/stage1/climbs/{climb}/hill').json() == {'hill': None}


def test_registration_reports_only_owner_holds_and_hill_scope(api):
    client, db, _ = api
    db.fetch.return_value = [{'hill': 'h', 'mint': 'm', 'amount': '9007199254740993', 'week': 4}]
    body = client.get('/stage1/me/registration?hill=h').json()
    assert body['registration'] is None
    assert body['held'][0]['amount'] == '9007199254740993'
    sql, *args = db.fetch.call_args.args
    assert args == ['owner-wallet', 'h']
    assert 'DISTINCT ON' in sql and "state='complete'" in sql


def test_bonding_split_comes_from_keeper_constants(api):
    from app.services.stage1_keeper_allocation import SPLIT
    client, db, _ = api
    db.fetchrow.return_value = {'hill': {'city': 'c', 'bonded': True, 'foundingCount': '7', 'founder': 'private-founder-wallet'},
                               'city': {'seasonAnchor': '0', 'lineLamports': '100'},
                               'chain_slot': 100, 'through_time': 604800, 'through_epoch': 1}
    stage1._bonding_cache.clear()
    body = client.get('/stage1/hills/11111111111111111111111111111111/bonding').json()
    assert body['split'] == SPLIT
    assert 'private-founder-wallet' not in str(body) and 'founder' not in body['hill_state']


def test_unmaterialized_founder_has_effective_lock_not_raw_zero(api):
    client, db, _ = api
    lot = dict(hill='hill', owner='owner-wallet', mint='mint', units='120', basisLamports='100',
               cancelled=False, exiting=False, converted=False, founding=False, sequence='1', assetSlot=0,
               lockWeeks=0, lockEnd='0')
    hill = dict(bonded=True, bondedAt='1000', foundingCutoff='2', foundingFreshSlots=1, founder='another-rider-wallet',
                quotedNumerators=['2'], quotedDenominators=['1'])
    db.fetch.return_value = [dict(address='lot', data=lot, hill_data=hill, chain_slot=100, withdrawals=[])]
    pledge = client.get('/stage1/me/pledges').json()['pledges'][0]
    assert pledge['founding'] is True
    assert pledge['lockWeeks'] == 26
    assert pledge['lockEnd'] == str(1000 + 26*604800)
    assert pledge['units'] == '50'
    assert 'another-rider-wallet' not in str(pledge)
    hill['foundingFreshSlots'] = 0
    pledge = client.get('/stage1/me/pledges').json()['pledges'][0]
    assert pledge['founding'] is False and pledge['lockWeeks'] == 0


def test_finalized_payment_is_not_pending_while_keeper_paid_slot_lags(api):
    import struct
    from solders.pubkey import Pubkey
    client, db, _ = api
    program, hill, mint = [Pubkey.from_bytes(bytes([n])*32) for n in (1,2,3)]
    claim = str(Pubkey.find_program_address([b's1v1_claims',bytes(hill),bytes(mint),struct.pack('<Q',4)],program)[0])
    pending = dict(hill=str(hill), mint=str(mint), program=str(program), week=4, kind='cash',
                   role=-1, leaf_index=7, recipient='owner-wallet', amount='55')
    db.fetch.side_effect = [[], [pending], [{'claim_set': claim, 'leaf_index': 7}]]
    assert client.get('/stage1/me/pay').json()['pending'] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("available", [True, False])
async def test_owner_projection_freshness_fences_without_rpc(monkeypatch, available):
    from app import solana_direct
    from fastapi import Response, HTTPException
    db=SimpleNamespace(fetchrow=AsyncMock(return_value={'through_slot':100,'updated_at':None} if available else None))
    @asynccontextmanager
    async def acquire():
        yield db
    monkeypatch.setattr(stage1,'get_pool',AsyncMock(return_value=SimpleNamespace(acquire=acquire)))
    monkeypatch.setattr(solana_direct,'load_readonly_config',lambda:SimpleNamespace(rpc_url='http://127.0.0.1:1',program_id='program'))
    rpc=AsyncMock(side_effect=AssertionError('owner reads must not call RPC'))
    monkeypatch.setattr(solana_direct,'get_stage1_program_config_account',rpc)
    response=Response();generator=stage1.stage1_connection(response)
    if available:
        assert await anext(generator) is db
        assert response.headers['cache-control']=='private, no-store'
        assert response.headers['x-indexed-slot']=='100'
        await generator.aclose()
    else:
        with pytest.raises(HTTPException) as failure:
            await anext(generator)
        assert failure.value.status_code==503
    rpc.assert_not_called()
    sql=db.fetchrow.call_args.args[0]
    assert 'n.ready' in sql and '90 seconds' in sql and 'v.highest_version IN (77,78)' in sql


def test_public_bonding_reads_projections_without_rpc_and_has_a_short_cache(monkeypatch):
    from app import solana_direct
    from app.middleware.rate_limiter import rate_limiter
    rpc=AsyncMock(side_effect=AssertionError('public reads must not call RPC'))
    monkeypatch.setattr(solana_direct,'get_stage1_program_config_account',rpc)
    monkeypatch.setattr(solana_direct,'load_readonly_config',lambda:SimpleNamespace(program_id='program',rpc_url='http://127.0.0.1:1'))
    hill={'data':None,'hill':{'city':'city','bonded':False,'foundingCount':'0'},'city':{'seasonAnchor':'1791201600','lineLamports':'100'},'chain_slot':100,'through_time':1791201601,'through_epoch':0}
    db=SimpleNamespace(fetch=AsyncMock(return_value=[]),fetchrow=AsyncMock(side_effect=lambda sql,*args: hill if 'indexed_stage1_hills' in sql else {'through_slot':100,'updated_at':None}))
    @asynccontextmanager
    async def acquire():yield db
    monkeypatch.setattr(stage1,'get_pool',AsyncMock(return_value=SimpleNamespace(acquire=acquire)))
    monkeypatch.setattr(rate_limiter,'_ensure_kv',AsyncMock())
    rate_limiter.reset_fallback()
    app=FastAPI();app.include_router(stage1.router,prefix='/stage1')
    with TestClient(app) as client:
        response=client.get('/stage1/hills/11111111111111111111111111111111/bonding')
    assert response.status_code==200,response.text
    assert response.headers['cache-control']=='public, max-age=15'
    rpc.assert_not_called()


def test_bonding_never_counts_sponsor_cash_toward_the_line(api):
    client, db, _ = api
    db.fetchrow.return_value = {'hill': {'city': 'c', 'bonded': True, 'foundingCount': '1'},
                               'city': {'seasonAnchor': '0', 'lineLamports': '100'},
                               'chain_slot': 100, 'through_time': 604800, 'through_epoch': 1}
    pool = {'city': 'c', 'mint': 'pool-mint', 'adapter': 5, 'slot': 0, 'admittedEpoch': '1', 'lastFreshUntil': '0',
            'admittedNumerator': '1', 'admittedDenominator': '1'}
    cash = {**pool, 'mint': 'cash-mint', 'adapter': 254}
    db.fetch.side_effect = lambda sql, *args: [{'address': a['mint'], 'asset': a} for a in (cash, pool)] if 'indexed_stage1_assets' in sql else []
    stage1._bonding_cache.clear()
    body = client.get('/stage1/hills/11111111111111111111111111111111/bonding').json()
    by_mint = {a['mint']: a for a in body['assets']}
    assert by_mint['cash-mint']['backing_eligible'] is False and 'backing_lamports' not in by_mint['cash-mint']
    assert by_mint['pool-mint']['backing_eligible'] is True and by_mint['pool-mint']['backing_lamports'] == '0'
