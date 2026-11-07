import asyncio
from datetime import datetime

import pytest

from app import db_pool
from app.main import _is_missing_schema_migrations_error
from app.repositories.vault import _leaderboard_recorded_at_iso


class FakePool:
    def __init__(self) -> None:
        self.closed = False
        self.terminated = False

    async def close(self) -> None:
        self.closed = True

    def terminate(self) -> None:
        self.terminated = True


@pytest.fixture(autouse=True)
def reset_db_pool_globals():
    original_pool = db_pool._pool
    original_pool_loop = db_pool._pool_loop
    original_lock = db_pool._pool_lock
    original_lock_loop = db_pool._pool_lock_loop
    db_pool._pool = None
    db_pool._pool_loop = None
    db_pool._pool_lock = None
    db_pool._pool_lock_loop = None
    yield
    db_pool._pool = original_pool
    db_pool._pool_loop = original_pool_loop
    db_pool._pool_lock = original_lock
    db_pool._pool_lock_loop = original_lock_loop


@pytest.mark.asyncio
async def test_close_pool_closes_owner_loop_pool():
    pool = FakePool()
    db_pool._pool = pool
    db_pool._pool_loop = asyncio.get_running_loop()

    await db_pool.close_pool()

    assert pool.closed is True
    assert pool.terminated is False
    assert db_pool._pool is None
    assert db_pool._pool_loop is None


@pytest.mark.asyncio
async def test_close_pool_terminates_non_owner_loop_pool():
    pool = FakePool()
    db_pool._pool = pool
    db_pool._pool_loop = object()

    await db_pool.close_pool()

    assert pool.closed is False
    assert pool.terminated is True
    assert db_pool._pool is None
    assert db_pool._pool_loop is None


def test_missing_schema_migrations_error_is_quiet_startup_condition():
    exc = Exception(
        "{'code': 'PGRST205', 'message': \"Could not find the table "
        "'public.schema_migrations' in the schema cache\"}"
    )

    assert _is_missing_schema_migrations_error(exc) is True
    assert _is_missing_schema_migrations_error(Exception("network timeout")) is False


def test_leaderboard_recorded_at_accepts_indexed_string_timestamps():
    assert _leaderboard_recorded_at_iso("1776037075") == datetime.fromtimestamp(1776037075).isoformat()
    assert _leaderboard_recorded_at_iso(None) is None
