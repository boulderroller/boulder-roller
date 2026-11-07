import uuid
from unittest.mock import AsyncMock

import pytest

from app.repositories import tile as tile_repo_mod
from app.repositories.tile import TileRepository


@pytest.mark.asyncio
async def test_asyncpg_bulk_insert_retries_transient_connection_state(monkeypatch):
    monkeypatch.setattr(tile_repo_mod, "USE_ASYNCPG_BULK", True)
    repo = TileRepository(client=object())
    ride_id = uuid.uuid4()
    samples = [{"tile_id": "8928308280fffff", "t": 0}]

    repo._store_tile_samples_asyncpg = AsyncMock(
        side_effect=[RuntimeError("cannot perform operation: another operation is in progress"), 1]
    )
    repo._store_tile_samples_postgrest = AsyncMock()

    inserted = await repo.store_activity_tile_samples(ride_id, samples)

    assert inserted == 1
    assert repo._store_tile_samples_asyncpg.await_count == 2
    repo._store_tile_samples_postgrest.assert_not_awaited()


@pytest.mark.asyncio
async def test_asyncpg_bulk_insert_falls_back_after_retry_failure(monkeypatch):
    monkeypatch.setattr(tile_repo_mod, "USE_ASYNCPG_BULK", True)
    repo = TileRepository(client=object())
    ride_id = uuid.uuid4()
    samples = [{"tile_id": "8928308280fffff", "t": 0}]

    repo._store_tile_samples_asyncpg = AsyncMock(
        side_effect=[
            RuntimeError("cannot perform operation: another operation is in progress"),
            RuntimeError("connection was closed"),
        ]
    )
    repo._store_tile_samples_postgrest = AsyncMock(return_value=1)

    inserted = await repo.store_activity_tile_samples(ride_id, samples)

    assert inserted == 1
    assert repo._store_tile_samples_asyncpg.await_count == 2
    repo._store_tile_samples_postgrest.assert_awaited_once()
