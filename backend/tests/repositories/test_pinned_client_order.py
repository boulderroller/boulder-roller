"""Sorted reads keep their tie-breakers through the pinned postgrest-py client.

Each read runs through the real client, which sends every chained ``order()``
call as its own ``order`` parameter, against the in-memory PostgREST in
tests.pinned_postgrest, which applies only the first and returns ties in a
different order on each request. Before the fix, these reads returned rows
that tie on their first sort key in arbitrary order.
"""

from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from tests.pinned_postgrest import PinnedPostgrest


def _at(seconds: int) -> str:
    return (datetime(2026, 6, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _photo(number: int, ride_id: str, sort_order: int, seconds: int, role: str = "photo") -> dict:
    return {"id": str(UUID(int=number)), "ride_id": ride_id, "sort_order": sort_order,
            "created_at": _at(seconds), "role": role, "upload_status": "ready",
            "moderation_state": "visible"}


@pytest.mark.asyncio
@pytest.mark.parametrize("repository", [
    "app.repositories.ride.RideRepository",
    "app.repositories_legacy.SupabaseRepository",
])
async def test_ride_photos_come_back_in_display_order(repository):
    module, name = repository.rsplit(".", 1)
    ride_a, ride_b = str(UUID(int=1)), str(UUID(int=2))
    # Choosing a cover moves it to sort_order 0 without moving the old cover,
    # so after two cover changes three photos share 0 and upload time orders them.
    photos_a = [_photo(11, ride_a, 0, 0), _photo(12, ride_a, 0, 60),
                _photo(13, ride_a, 0, 120, role="cover"), _photo(14, ride_a, 1, 30),
                _photo(15, ride_a, 2, 90)]
    photos_b = [_photo(20 + i, ride_b, i, 600 - i) for i in range(4)]
    server = PinnedPostgrest({"ride_media": list(reversed(photos_a + photos_b))})
    repo = getattr(importlib.import_module(module), name)(server.client)

    single = [[row["id"] for row in await repo.list_ride_media(ride_a)] for _ in range(3)]
    grouped = await repo.list_ride_media_for_rides([ride_a, ride_b])

    assert single == [[photo["id"] for photo in photos_a]] * 3
    assert [row["id"] for row in grouped[ride_a]] == [photo["id"] for photo in photos_a]
    assert [row["id"] for row in grouped[ride_b]] == [photo["id"] for photo in photos_b]


@pytest.mark.asyncio
@pytest.mark.parametrize("read", ["bounds", "tiles"])
async def test_vault_candidates_cut_at_the_limit_by_id_among_ties(read):
    from app.services.climb_vault import ClimbVaultService

    tile = "8a2a1072b59ffff"
    # Five tall climbs, then 25 that tie on vertical: the limit of 20 cuts the tie.
    climbs = [{"id": str(UUID(int=n)), "name": f"Climb {n}", "active": True,
               "bounds_min_lat": 40.0, "bounds_max_lat": 40.1,
               "bounds_min_lon": -75.3, "bounds_max_lon": -75.2, "h3_tile_ids": [tile],
               "total_vert_m": 200.0 if n <= 5 else 100.0, "avg_gradient_pct": 6.0,
               "distance_m": 1500.0, "signature_hex": "00"} for n in range(30, 0, -1)]
    service = ClimbVaultService(PinnedPostgrest({"climb_vault": climbs}).client)

    if read == "bounds":
        found = await service.find_climbs_in_bounds(39.9, 40.2, -75.4, -75.1, limit=20)
    else:
        found = await service.find_climbs_by_tiles([tile], limit=20)

    assert [climb.id for climb in found] == [UUID(int=n) for n in range(1, 21)]
