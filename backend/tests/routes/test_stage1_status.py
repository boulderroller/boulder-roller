"""Local mocks only: the UI gate never enables itself from a flag alone."""
from types import SimpleNamespace
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import health
from app import solana_direct, db_pool


@pytest.mark.parametrize('flag,version,live', [
    (None, 77, False), ('false', 77, False), ('true', 76, False),
    ('true', 77, True), ('true', 78, True), ('true', 79, False), ('true', None, False),
])
def test_status_stage1_requires_flag_and_a_stage1_version(monkeypatch, flag, version, live):
    monkeypatch.delenv('STAGE1_UI_ENABLED', raising=False)
    monkeypatch.setenv('STAGE1_ACTIONS_ENABLED', 'true')
    if flag is not None:
        monkeypatch.setenv('STAGE1_UI_ENABLED', flag)
    monkeypatch.setattr(solana_direct, 'load_readonly_config', lambda: SimpleNamespace(program_id='program'))
    read = AsyncMock(return_value={'through_slot': 1} if version in (77, 78) else None)
    if version is None:
        read.side_effect = RuntimeError('unavailable')
    @asynccontextmanager
    async def acquire():
        yield SimpleNamespace(fetchrow=read)
    monkeypatch.setattr(db_pool, 'get_pool', AsyncMock(return_value=SimpleNamespace(acquire=acquire)))
    rpc = AsyncMock(side_effect=AssertionError('UI gate must never call RPC'))
    monkeypatch.setattr(solana_direct, 'get_stage1_program_config_account', rpc)
    app = FastAPI()
    app.include_router(health.router)
    with TestClient(app) as client:
        response = client.get('/status')
    rpc.assert_not_called()
    if read.call_count:
        sql = read.call_args.args[0]
        assert 'v.highest_version IN (77,78)' in sql and 'n.ready' not in sql and '90 seconds' not in sql
        assert not any(word in sql.upper() for word in ['INSERT', 'UPDATE ', 'DELETE'])
    assert response.status_code == 200
    assert response.json()['stage1'] == {'live': live, 'actions': version in (77, 78)}
    assert read.call_count == 1
