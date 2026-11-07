from types import SimpleNamespace

import pytest

from app.services.tile_service import TileAttributionService, TileService


def test_get_tile_sequence_skips_malformed_coordinates():
    service = TileService()
    points = [
        {"lat": 40.0000, "lon": -75.0000, "timestamp": 1000.0, "elevation_m": 10.0},
        {"lat": -214.7483648, "lon": -75.0001, "timestamp": 1001.0, "elevation_m": 12.0},
        {"lat": 40.0002, "lon": -75.0002, "timestamp": 1002.0, "elevation_m": 20.0},
    ]

    samples = service.get_tile_sequence(points, resolution=10, start_time=1000.0)

    assert len(samples) == 2
    assert [sample.t for sample in samples] == [0.0, 2.0]
    assert all(sample.tile_id for sample in samples)


def test_get_tile_run_sequence_skips_malformed_coordinates():
    service = TileService()
    points = [
        {"lat": 40.0000, "lon": -75.0000, "timestamp": 1000.0, "elevation_m": 10.0},
        {"lat": -214.7483648, "lon": -75.0001, "timestamp": 1001.0, "elevation_m": 12.0},
        {"lat": 40.0002, "lon": -75.0002, "timestamp": 1002.0, "elevation_m": 20.0},
    ]

    tile_runs = service.get_tile_run_sequence(points=points, resolution=10, start_time=1000.0)

    assert len(tile_runs) == 1
    assert tile_runs[0]["t"] == 0
    assert tile_runs[0]["duration_s"] == 2
    assert tile_runs[0]["samples"] == 2
    assert tile_runs[0]["tile_id"]


class _TableQuery:
    def __init__(self, rows=None, error=None):
        self.rows = rows or []
        self.error = error

    def select(self, *_args, **_kwargs):
        return self

    def in_(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def execute(self):
        if self.error:
            raise self.error
        return SimpleNamespace(data=self.rows)


class _RpcQuery:
    def __init__(self, rows=None, error=None):
        self.rows = rows or []
        self.error = error

    def execute(self):
        if self.error:
            raise self.error
        return SimpleNamespace(data=self.rows)


class _AttributionClient:
    def __init__(self, table_rows=None, table_error=None, rpc_rows=None, rpc_error=None):
        self.table_rows = table_rows
        self.table_error = table_error
        self.rpc_rows = rpc_rows
        self.rpc_error = rpc_error
        self.rpc_called = False

    def table(self, name):
        assert name == "road_features"
        return _TableQuery(self.table_rows, self.table_error)

    def rpc(self, name, params):
        assert name == "get_tile_attribution"
        self.rpc_called = True
        return _RpcQuery(self.rpc_rows, self.rpc_error)


@pytest.mark.asyncio
async def test_tile_attribution_uses_current_road_features_schema():
    client = _AttributionClient(
        table_rows=[
            {
                "tile_id": "tile-a",
                "feature_type": "road_segment",
                "name": "Old Baldy",
                "highway_class": "residential",
            },
            {
                "tile_id": "tile-b",
                "feature_type": "road_segment",
                "name": "Old Baldy",
                "highway_class": "primary",
            },
            {
                "tile_id": "tile-b",
                "feature_type": "road_segment",
                "name": "Side Road",
                "highway_class": "residential",
            },
        ]
    )
    service = TileAttributionService(client)

    result = await service.attribute_tiles(["tile-a", "tile-b"])

    assert result.primary_road is not None
    assert result.primary_road.road_name == "Old Baldy"
    assert result.primary_road.tile_count == 2
    assert result.coverage_pct == 100.0
    assert client.rpc_called is False


@pytest.mark.asyncio
async def test_tile_attribution_falls_back_when_current_schema_absent():
    client = _AttributionClient(
        table_error=RuntimeError('column "feature_type" does not exist'),
        rpc_rows=[
            {
                "road_name": "Legacy Wall",
                "road_class": "Primary",
                "grade": 8.5,
                "tile_count": 1,
                "coverage_pct": 50.0,
            }
        ],
    )
    service = TileAttributionService(client)

    result = await service.attribute_tiles(["tile-a", "tile-b"])

    assert result.primary_road is not None
    assert result.primary_road.road_name == "Legacy Wall"
    assert client.rpc_called is True
