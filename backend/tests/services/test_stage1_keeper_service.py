"""Real version-window persistence with an explicitly mocked chain transport."""
import base64
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from solders.keypair import Keypair

from tests.services.test_stage1_keeper_worker import store,migrated_template


@pytest.mark.asyncio
async def test_disabled_service_reads_no_configuration(monkeypatch):
    from app.services.stage1_keeper import run
    monkeypatch.delenv('STAGE1_KEEPER_ENABLED',raising=False)
    assert await run(SimpleNamespace())=={'state':'disabled'}


@pytest.mark.asyncio
async def test_4c_plans_nothing_and_same_process_starts_at_4d_with_idle_backoff(store,monkeypatch,tmp_path):
    import asyncpg
    from app.services import stage1_keeper,stage1_keeper_chain
    chain=stage1_keeper_chain.KeeperChain('http://127.0.0.1:8899',str(Keypair().pubkey()),'/unused')
    chain.genesis,chain.cluster='local-test','localnet'
    chain.start=AsyncMock()
    chain.discover=AsyncMock(return_value=[])
    version=[0x4c]
    async def multiple(addresses,floor=0):
        data=hashlib.sha256(b'account:ProgramConfig').digest()[:8]+bytes(64)+bytes(version)
        return 1,{addresses[0]:{'owner':str(chain.program),'executable':False,'data':[base64.b64encode(data).decode(),'base64']}}
    chain.multiple=multiple
    chain.rpc=AsyncMock(return_value='local-test')
    pool=SimpleNamespace(acquire=store.pool.acquire,close=AsyncMock())
    monkeypatch.setattr(asyncpg,'create_pool',AsyncMock(return_value=pool))
    monkeypatch.setattr(stage1_keeper_chain,'KeeperChain',lambda *a,**k:chain)
    sleeps=[]
    async def sleep(seconds):
        sleeps.append(seconds)
        if version[0]==0x4c:
            chain.discover.assert_not_awaited()
            async with store.pool.acquire() as c:
                assert await c.fetchval('SELECT count(*) FROM stage1_keeper_jobs')==0
            version[0]=0x4d
    monkeypatch.setattr(stage1_keeper.asyncio,'sleep',sleep)
    monkeypatch.setenv('STAGE1_KEEPER_ENABLED','true')
    monkeypatch.setenv('STAGE1_KEEPER_PUBLISHER_KEYS','{}')
    for name in ('RPC_URL','PROGRAM_ID','PUBLISHER_KEYPAIR','EXPORT_DIR','DATABASE_URL'):
        monkeypatch.setenv('STAGE1_KEEPER_'+name,str(tmp_path))
    result=await stage1_keeper.run(SimpleNamespace(archive=None,retry_job=None,max_steps=2,through_week=None,once=False))
    assert result['state']=='stopped' and result['transitions']=={}
    assert sleeps==[900,900,900]
    chain.discover.assert_awaited_once()
