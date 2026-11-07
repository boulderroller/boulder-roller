from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest

from app.repositories import canon as canon_repository
from app.repositories.canon import CanonRegistryError, CanonRepository


REGISTRY_ID = "11111111-1111-4111-8111-111111111111"
CANON_ID = "22222222-2222-4222-8222-222222222222"
PROFILE_HASH = "e557be81d1615c5d03d6ca5624649b2dfc8b898079879e377f05a10523e6d81d"


class _Query:
    def __init__(self, client, table):
        self.client = client
        self.table = table
        self.operations = []

    def select(self, columns):
        self.operations.append(("select", columns))
        return self

    def eq(self, column, value):
        self.operations.append(("eq", column, value))
        return self

    def in_(self, column, values):
        self.operations.append(("in", column, tuple(values)))
        return self

    def order(self, column):
        self.operations.append(("order", column))
        return self

    def range(self, start, end):
        self.operations.append(("range", start, end))
        return self

    def execute(self):
        self.client.queries.append(self)
        rows = list(self.client.rows[self.table])
        for operation in self.operations:
            if operation[0] == "eq":
                _, column, value = operation
                rows = [row for row in rows if row.get(column) == value]
            elif operation[0] == "in":
                _, column, values = operation
                rows = [row for row in rows if row.get(column) in values]
        order_columns = [op[1] for op in self.operations if op[0] == "order"]
        if order_columns:
            rows.sort(key=lambda row: tuple(str(row.get(column) or "") for column in order_columns))
        ranges = [op for op in self.operations if op[0] == "range"]
        if ranges:
            _, start, end = ranges[-1]
            rows = rows[start : end + 1]
        return SimpleNamespace(data=rows)


class _Client:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def table(self, table):
        return _Query(self, table)


def _row(**overrides):
    row = {
        "id": REGISTRY_ID,
        "canon_id": CANON_ID,
        "version": 2,
        "status": "ratified",
        "candidate_fingerprint": "f" * 64,
        "display_name": "Test Hill: lower gate to upper gate",
        "route_name": "Test Hill",
        "centerline_geom": {
            "type": "LineString",
            "coordinates": [[-75.0, 40.0], [-75.0, 40.001]],
        },
        "corridor_geom": {
            "type": "MultiPolygon",
            "coordinates": [
                [[
                    [-75.0002, 39.9999],
                    [-74.9998, 39.9999],
                    [-74.9998, 40.0011],
                    [-75.0002, 40.0011],
                    [-75.0002, 39.9999],
                ]]
            ],
        },
        "gate_start_line": "LINESTRING(-75.0003 40.0001,-74.9997 40.0001)",
        "gate_end_line": "SRID=4326;LINESTRING(-75.0003 40.0009,-74.9997 40.0009)",
        "canonical_profile": [
            {"dist_m": 0.0, "elev_m": 10.0},
            {"dist_m": 100.0, "elev_m": 30.0},
        ],
        "length_m": "100.00",
        "vert_m": "20.00",
        "avg_gradient_pct": "20.000",
        "compiler_version": "canon-compile-v0.2.3",
        "provenance": {
            "canonical_profile_hash": {
                "algorithm": "blake3_canonical_profile_v1",
                "value": PROFILE_HASH,
            }
        },
        "odbl_source": "OpenStreetMap contributors",
    }
    row.update(overrides)
    return row


@pytest.mark.asyncio
async def test_canon_publication_between_cell_and_row_lookup_keeps_current_family(monkeypatch):
    successor_id = '33333333-3333-4333-8333-333333333333'
    old_cell = {'canon_climb_id': REGISTRY_ID, 'h3_resolution': 10,
                'tile_id': 'old-tile', 'coverage_role': 'corridor'}
    new_cell = {**old_cell, 'canon_climb_id': successor_id, 'tile_id': 'new-tile'}
    client = _Client({'canon_climbs': [_row(version=1)], 'canon_corridor_cells': [old_cell]})
    repository = CanonRepository(client)
    load = repository._load_cells_by_tiles

    async def publish_after_cell_read(tiles):
        retained = await load(tiles)
        client.rows['canon_climbs'] = [_row(version=1, status='retired'), _row(id=successor_id)]
        client.rows['canon_corridor_cells'].append(new_cell)
        return retained

    monkeypatch.setattr(repository, '_load_cells_by_tiles', publish_after_cell_read)
    climbs = await repository.load_ratified_for_tiles(['old-tile'])
    assert len(climbs) == 1
    assert climbs[0].registry_id == UUID(successor_id)
    assert climbs[0].version == 2 and climbs[0].corridor_tile_ids == ('new-tile',)


@pytest.mark.asyncio
async def test_candidate_owned_cell_does_not_hide_ratified_climb():
    candidate_id = '33333333-3333-4333-8333-333333333333'
    cell = {'canon_climb_id': REGISTRY_ID, 'h3_resolution': 10,
            'tile_id': 'tile-a', 'coverage_role': 'corridor'}
    client = _Client({'canon_climbs': [_row(), _row(id=candidate_id, status='candidate')],
                      'canon_corridor_cells': [cell, {**cell, 'canon_climb_id': candidate_id}]})
    climbs = await CanonRepository(client).load_ratified_for_tiles(['tile-a'])
    assert [climb.registry_id for climb in climbs] == [UUID(REGISTRY_ID)]
    identity_queries = [q for q in client.queries if ('select', 'id') in q.operations]
    assert len(identity_queries) == 1
    assert identity_queries[0].operations == [('select', 'id'), ('in', 'id', (candidate_id,))]


@pytest.mark.asyncio
async def test_canon_rollback_between_cell_and_row_lookup_requires_retry(monkeypatch):
    cell = {'canon_climb_id': REGISTRY_ID, 'h3_resolution': 10,
            'tile_id': 'tile-a', 'coverage_role': 'corridor'}
    client = _Client({'canon_climbs': [_row()], 'canon_corridor_cells': [cell]})
    repository = CanonRepository(client)
    load = repository._load_cells_by_tiles

    async def remove_after_cell_read(tiles):
        retained = await load(tiles)
        client.rows['canon_climbs'] = []
        client.rows['canon_corridor_cells'] = []
        return retained

    monkeypatch.setattr(repository, '_load_cells_by_tiles', remove_after_cell_read)
    with pytest.raises(CanonRegistryError, match='retry matching'):
        await repository.load_ratified_for_tiles(['tile-a'])


def test_parse_geojson_mapping_survives_multipolygon_constructor_incompatibility(
    monkeypatch,
):
    def incompatible_shape(_value):
        raise TypeError("MultiPolygon constructor is incompatible with this NumPy")

    monkeypatch.setattr(canon_repository, "shape", incompatible_shape)

    geometry = canon_repository._parse_geometry(
        _row()["corridor_geom"],
        field_name="corridor_geom",
    )

    assert geometry.geom_type == "MultiPolygon"
    assert geometry.is_valid


@pytest.mark.asyncio
async def test_load_ratified_for_tiles_uses_h3_only_as_prefilter_and_builds_snapshot():
    client = _Client(
        {
            "canon_corridor_cells": [
                {
                    "canon_climb_id": REGISTRY_ID,
                    "h3_resolution": 10,
                    "tile_id": "tile-a",
                    "coverage_role": "corridor",
                },
                {
                    "canon_climb_id": REGISTRY_ID,
                    "h3_resolution": 10,
                    "tile_id": "tile-b",
                    "coverage_role": "gate_end",
                },
            ],
            "canon_climbs": [_row()],
        }
    )
    repository = CanonRepository(client)

    climbs = await repository.load_ratified_for_tiles(["tile-b", "tile-a", "tile-a"])

    assert len(climbs) == 1
    climb = climbs[0]
    assert climb.registry_id == UUID(REGISTRY_ID)
    assert climb.canon_id == UUID(CANON_ID)
    assert climb.version == 2
    assert climb.corridor_tile_ids == ("tile-a", "tile-b")
    assert climb.centerline.geom_type == "LineString"
    assert climb.corridor.geom_type == "MultiPolygon"
    assert climb.profile_hash == PROFILE_HASH
    assert climb.registry_snapshot_digest.startswith("sha256:")
    assert len(climb.registry_snapshot_digest) == len("sha256:") + 64

    cell_query, climb_query, active_query, full_cell_query = client.queries
    assert ("eq", "h3_resolution", 10) in cell_query.operations
    assert ("in", "tile_id", ("tile-a", "tile-b")) in cell_query.operations
    assert ("select", "id,canon_id,status") in climb_query.operations
    assert ("in", "status", ("ratified", "retired")) in climb_query.operations
    assert ("in", "id", (REGISTRY_ID,)) in climb_query.operations
    assert ("eq", "status", "ratified") in active_query.operations
    assert ("in", "canon_id", (CANON_ID,)) in active_query.operations
    assert ("in", "canon_climb_id", (REGISTRY_ID,)) in full_cell_query.operations


@pytest.mark.asyncio
async def test_load_ratified_for_tiles_fails_closed_on_invalid_profile_hash():
    bad_row = _row(
        provenance={
            "canonical_profile_hash": {
                "algorithm": "blake3_canonical_profile_v1",
                "value": "not-a-hash",
            }
        }
    )
    client = _Client(
        {
            "canon_corridor_cells": [
                {
                    "canon_climb_id": REGISTRY_ID,
                    "h3_resolution": 10,
                    "tile_id": "tile-a",
                    "coverage_role": "corridor",
                }
            ],
            "canon_climbs": [bad_row],
        }
    )

    with pytest.raises(CanonRegistryError, match="canonical profile hash"):
        await CanonRepository(client).load_ratified_for_tiles(["tile-a"])


@pytest.mark.asyncio
async def test_load_ratified_for_tiles_fails_closed_when_profile_hash_does_not_match():
    client = _Client(
        {
            "canon_corridor_cells": [
                {
                    "canon_climb_id": REGISTRY_ID,
                    "h3_resolution": 10,
                    "tile_id": "tile-a",
                    "coverage_role": "corridor",
                }
            ],
            "canon_climbs": [
                _row(
                    provenance={
                        "canonical_profile_hash": {
                            "algorithm": "blake3_canonical_profile_v1",
                            "value": "ab" * 32,
                        }
                    }
                )
            ],
        }
    )

    with pytest.raises(CanonRegistryError, match="does not match canonical profile"):
        await CanonRepository(client).load_ratified_for_tiles(["tile-a"])


@pytest.mark.asyncio
async def test_load_ratified_for_tiles_fails_closed_when_summary_metrics_diverge_from_profile():
    client = _Client(
        {
            "canon_corridor_cells": [
                {
                    "canon_climb_id": REGISTRY_ID,
                    "h3_resolution": 10,
                    "tile_id": "tile-a",
                    "coverage_role": "corridor",
                }
            ],
            "canon_climbs": [_row(vert_m="999.00")],
        }
    )

    with pytest.raises(CanonRegistryError, match="vert_m disagrees with canonical profile"):
        await CanonRepository(client).load_ratified_for_tiles(["tile-a"])


@pytest.mark.asyncio
async def test_load_ratified_for_tiles_fails_closed_on_multiple_ratified_versions():
    second_id = "33333333-3333-4333-8333-333333333333"
    cells = [
        {
            "canon_climb_id": registry_id,
            "h3_resolution": 10,
            "tile_id": "tile-a",
            "coverage_role": "corridor",
        }
        for registry_id in (REGISTRY_ID, second_id)
    ]
    client = _Client(
        {
            "canon_corridor_cells": cells,
            "canon_climbs": [_row(), _row(id=second_id, version=3)],
        }
    )

    with pytest.raises(CanonRegistryError, match="multiple ratified versions"):
        await CanonRepository(client).load_ratified_for_tiles(["tile-a"])


@pytest.mark.asyncio
async def test_load_fails_closed_on_disjoint_ratified_version_not_hit_by_ride():
    second_id = "33333333-3333-4333-8333-333333333333"
    client = _Client(
        {
            "canon_corridor_cells": [
                {
                    "canon_climb_id": REGISTRY_ID,
                    "h3_resolution": 10,
                    "tile_id": "tile-a",
                    "coverage_role": "corridor",
                },
                {
                    "canon_climb_id": second_id,
                    "h3_resolution": 10,
                    "tile_id": "tile-b",
                    "coverage_role": "corridor",
                },
            ],
            "canon_climbs": [_row(), _row(id=second_id, version=3)],
        }
    )

    with pytest.raises(CanonRegistryError, match="multiple ratified versions"):
        await CanonRepository(client).load_ratified_for_tiles(["tile-a"])


@pytest.mark.asyncio
async def test_load_ratified_for_tiles_returns_empty_without_a_prefilter_hit():
    client = _Client({"canon_corridor_cells": [], "canon_climbs": []})

    assert await CanonRepository(client).load_ratified_for_tiles([]) == []
    assert client.queries == []


@pytest.mark.asyncio
async def test_full_corridor_cell_load_is_paginated_without_silent_truncation():
    cells = [
        {
            "canon_climb_id": REGISTRY_ID,
            "h3_resolution": 10,
            "tile_id": f"tile-{index:04d}",
            "coverage_role": "corridor",
        }
        for index in range(1005)
    ]
    client = _Client(
        {
            "canon_corridor_cells": cells,
            "canon_climbs": [_row()],
        }
    )

    climbs = await CanonRepository(client).load_ratified_for_tiles(["tile-0000"])

    assert len(climbs[0].corridor_tile_ids) == 1005
    full_cell_queries = [
        query
        for query in client.queries
        if ("in", "canon_climb_id", (REGISTRY_ID,)) in query.operations
    ]
    assert [op for query in full_cell_queries for op in query.operations if op[0] == "range"] == [
        ("range", 0, 999),
        ("range", 1000, 1999),
    ]


@pytest.mark.asyncio
async def test_prefilter_cell_load_is_paginated_without_silent_candidate_omission():
    cells = [
        {
            "canon_climb_id": f"00000000-0000-4000-8000-{index:012d}",
            "h3_resolution": 10,
            "tile_id": "shared-tile",
            "coverage_role": "corridor",
        }
        for index in range(1005)
    ]
    client = _Client(
        {
            "canon_corridor_cells": cells,
            "canon_climbs": [{"id": cell["canon_climb_id"], "canon_id": CANON_ID,
                              "status": "retired"} for cell in cells],
        }
    )

    assert await CanonRepository(client).load_ratified_for_tiles(["shared-tile"]) == []

    prefilter_queries = [
        query
        for query in client.queries
        if ("in", "tile_id", ("shared-tile",)) in query.operations
    ]
    assert [op for query in prefilter_queries for op in query.operations if op[0] == "range"] == [
        ("range", 0, 999),
        ("range", 1000, 1999),
    ]


@pytest.mark.asyncio
async def test_registry_snapshot_digest_is_stable_across_disjoint_ride_prefilters():
    cells = [
        {
            "canon_climb_id": REGISTRY_ID,
            "h3_resolution": 10,
            "tile_id": tile_id,
            "coverage_role": "corridor",
        }
        for tile_id in ("tile-a", "tile-b", "tile-c")
    ]
    client = _Client(
        {
            "canon_corridor_cells": cells,
            "canon_climbs": [_row()],
        }
    )
    repository = CanonRepository(client)

    from_a = await repository.load_ratified_for_tiles(["tile-a"])
    from_b = await repository.load_ratified_for_tiles(["tile-b"])

    assert from_a[0].corridor_tile_ids == ("tile-a", "tile-b", "tile-c")
    assert from_a[0].registry_snapshot_digest == from_b[0].registry_snapshot_digest


# The pinned client's range() is end-exclusive and only its first order() is
# applied by PostgREST. These loads run through that real client against an
# in-memory PostgREST, so pages are 999 rows and ties come back unstably.

def _route(climb_count, cells_for):
    climbs, cells = [], []
    for index in range(climb_count):
        registry_id = str(UUID(int=0x10_0000 + index))
        climbs.append(_row(id=registry_id, canon_id=str(UUID(int=0x20_0000 + index))))
        cells.extend(
            {"canon_climb_id": registry_id, "h3_resolution": 10,
             "tile_id": tile_id, "coverage_role": "corridor"}
            for tile_id in cells_for(index)
        )
    return climbs, cells


def _snapshots(climbs):
    return {str(c.registry_id): (c.corridor_tile_ids, c.registry_snapshot_digest) for c in climbs}


@pytest.mark.asyncio
async def test_long_route_loads_every_climb_through_the_pinned_client():
    from tests.pinned_postgrest import PinnedPostgrest

    # 35 climbs; neighbours share 40 of 80 cells, so both the 500-tile
    # prefilter batches and the 35-climb full read exceed one page.
    def tiles(index):
        return [f"8a2a1072b{n:06d}" for n in range(index * 40, index * 40 + 80)]

    climbs, cells = _route(35, tiles)
    ride_tiles = sorted({cell["tile_id"] for cell in cells})
    expected = {row["id"]: tuple(sorted(tiles(i))) for i, row in enumerate(climbs)}

    loads = [
        _snapshots(await CanonRepository(PinnedPostgrest(
            {"canon_climbs": climbs, "canon_corridor_cells": cells}, seed=seed,
        ).client).load_ratified_for_tiles(ride_tiles))
        for seed in (1, 2, 3)
    ]

    assert {key: value[0] for key, value in loads[0].items()} == expected
    # Ties come back in a different order on every request; one total sort
    # keeps every page boundary, and so every snapshot digest, the same.
    assert loads[0] == loads[1] == loads[2]


@pytest.mark.asyncio
async def test_eighteen_climb_ride_keeps_all_1021_cells_through_the_pinned_client():
    from tests.pinned_postgrest import PinnedPostgrest

    # The measured ride: 18 climbs, 1,021 corridor cells in one full read.
    def tiles(index):
        return [f"8a2a1072c{index:02d}{n:04d}" for n in range(52 if index == 17 else 57)]

    climbs, cells = _route(18, tiles)
    assert len(cells) == 1021
    server = PinnedPostgrest({"canon_climbs": climbs, "canon_corridor_cells": cells})

    loaded = await CanonRepository(server.client).load_ratified_for_tiles(
        sorted({cell["tile_id"] for cell in cells})
    )

    assert sum(len(climb.corridor_tile_ids) for climb in loaded) == 1021
    assert {str(c.registry_id): c.corridor_tile_ids for c in loaded} == {
        row["id"]: tuple(sorted(tiles(i))) for i, row in enumerate(climbs)
    }
    # One order parameter carries every sort key; PostgREST drops repeats.
    assert all(len(request.url.params.get_list("order")) <= 1 for request in server.requests)


class _RangeBlindQuery(_Query):
    def range(self, start, end):
        return self  # Every request returns the whole matching table.


class _RangeBlindClient(_Client):
    def table(self, table):
        return _RangeBlindQuery(self, table)


@pytest.mark.asyncio
async def test_paged_canon_reads_terminate_when_the_server_ignores_range():
    from app.utils.postgrest_paging import MAX_PAGES, PagingRunaway

    cells = [{"canon_climb_id": REGISTRY_ID, "h3_resolution": 10,
              "tile_id": f"tile-{index:04d}", "coverage_role": "corridor"} for index in range(1005)]

    # A short answer ends the read even though the window was ignored.
    small = _RangeBlindClient({"canon_corridor_cells": cells[:3], "canon_climbs": [_row()]})
    climbs = await CanonRepository(small).load_ratified_for_tiles(["tile-0000"])
    assert climbs[0].corridor_tile_ids == ("tile-0000", "tile-0001", "tile-0002")

    # Full pages forever: the read raises at its page bound instead of growing.
    blind = _RangeBlindClient({"canon_corridor_cells": cells, "canon_climbs": [_row()]})
    with pytest.raises(PagingRunaway):
        await CanonRepository(blind).load_ratified_for_tiles(["tile-0000"])
    full_reads = [q for q in blind.queries if ("in", "canon_climb_id", (REGISTRY_ID,)) in q.operations]
    assert len(full_reads) == MAX_PAGES
