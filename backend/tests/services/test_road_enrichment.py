from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Optional

from app.services import road_enrichment
from app.services.road_enrichment import RoadFeature


class FakeRoadFeaturesTable:
    def __init__(self) -> None:
        self.batches: list[list[str]] = []
        self._batch: list[str] = []

    def select(self, _columns: str) -> "FakeRoadFeaturesTable":
        return self

    def in_(self, _column: str, batch: list[str]) -> "FakeRoadFeaturesTable":
        self._batch = list(batch)
        self.batches.append(self._batch)
        return self

    def execute(self):
        rows = [
            {
                "tile_id": tile_id,
                "feature_type": "road_segment",
                "osm_id": index,
                "name": f"Road {tile_id}",
                "highway_class": "residential",
                "lat": 40.0,
                "lon": -75.0,
                "road_names": [],
                "degree": None,
                "tags": None,
            }
            for index, tile_id in enumerate(self._batch)
        ]
        return type(
            "Response",
            (),
            {"data": list(reversed(rows))},
        )()


class FakeSupabase:
    def __init__(self) -> None:
        self.road_features = FakeRoadFeaturesTable()

    def table(self, name: str) -> FakeRoadFeaturesTable:
        assert name == "road_features"
        return self.road_features


def test_fetch_road_features_batches_tiles_deterministically(monkeypatch) -> None:
    fake = FakeSupabase()
    monkeypatch.setattr(road_enrichment, "get_supabase_client", lambda: fake)
    tile_ids = {f"tile-{idx:03d}" for idx in range(121, 0, -1)}

    features = road_enrichment.fetch_road_features_for_tiles(tile_ids)

    assert [feature.tile_id for feature in features] == sorted(tile_ids)
    assert [len(batch) for batch in fake.road_features.batches] == [50, 50, 21]
    assert fake.road_features.batches[0] == sorted(tile_ids)[:50]


def bridge_feature(start_lat: float, start_lon: float, end_lat: float, end_lon: float, length_m: float) -> RoadFeature:
    return RoadFeature(
        tile_id="tile-001",
        feature_type="bridge",
        osm_id=123,
        name="Test Bridge",
        highway_class="residential",
        lat=start_lat,
        lon=start_lon,
        road_names=[],
        degree=None,
        tags={
            "bridge_start_lat": start_lat,
            "bridge_start_lon": start_lon,
            "bridge_end_lat": end_lat,
            "bridge_end_lon": end_lon,
            "bridge_length_m": length_m,
        },
    )


def sample(idx: int, lat: float, lon: float, elevation_m: float, t: Optional[int] = None) -> dict:
    return {
        "tile_id": "tile-001",
        "t": idx if t is None else t,
        "lat": lat,
        "lon": lon,
        "elevation_m": elevation_m,
    }


def test_bridge_preprocessing_interpolates_plausible_bridge_span() -> None:
    samples = [
        sample(0, 40.0, -75.0000, 100.0),
        sample(1, 40.0, -74.9999, 112.0),
        sample(2, 40.0, -74.9998, 130.0),
        sample(3, 40.0, -74.9997, 90.0),
        sample(4, 40.0, -74.9996, 104.0),
    ]
    bridge = bridge_feature(40.0, -75.0000, 40.0, -74.9996, length_m=35.0)
    diagnostics: list[dict] = []

    result = road_enrichment.preprocess_bridge_elevations(samples, [bridge], diagnostics)

    assert result is samples
    assert samples[2]["orig_elevation_m"] == 130.0
    assert samples[2]["elevation_m"] == 102.0
    assert diagnostics[0]["status"] == "accepted"
    assert diagnostics[0]["reason"] == "interpolated"
    assert diagnostics[0]["span_samples"] == 4
    assert diagnostics[0]["track_distance_m"] is not None


def test_bridge_preprocessing_skips_endpoint_match_with_implausible_track_span() -> None:
    samples = [
        sample(0, 40.0, -75.0000, 100.0, t=0),
        sample(1, 40.0200, -75.0200, 140.0, t=10),
        sample(2, 40.0300, -75.0300, 155.0, t=20),
        sample(3, 40.0200, -75.0200, 145.0, t=30),
        sample(4, 40.0, -74.9996, 104.0, t=40),
    ]
    original_elevations = [row["elevation_m"] for row in samples]
    bridge = bridge_feature(40.0, -75.0000, 40.0, -74.9996, length_m=35.0)
    diagnostics: list[dict] = []

    road_enrichment.preprocess_bridge_elevations(samples, [bridge], diagnostics)

    assert [row["elevation_m"] for row in samples] == original_elevations
    assert all("orig_elevation_m" not in row for row in samples)
    assert diagnostics[0]["status"] == "skipped"
    assert diagnostics[0]["reason"] == "track_span_too_large"
    assert diagnostics[0]["track_distance_m"] > 1000


def test_time_to_sample_idx_maps_datetime_samples_from_activity_start() -> None:
    base = datetime(2026, 6, 12, 18, 0, tzinfo=timezone.utc)
    samples = [
        sample(0, 40.0, -75.0000, 100.0, t=base + timedelta(seconds=offset))
        for offset in (0, 10, 20, 30)
    ]

    assert road_enrichment._time_to_sample_idx(samples, 20) == 2
    assert road_enrichment._time_to_sample_idx(samples, base + timedelta(seconds=30)) == 3


def test_time_to_sample_idx_preserves_numeric_sample_axis() -> None:
    samples = [
        sample(idx, 40.0, -75.0000, 100.0, t=120 + idx * 10)
        for idx in range(5)
    ]

    assert road_enrichment._time_to_sample_idx(samples, 20) == 2


def test_enrich_climbs_accepts_datetime_offsets(monkeypatch) -> None:
    base = datetime(2026, 6, 12, 18, 0, tzinfo=timezone.utc)
    samples = [
        sample(idx, 40.0, -75.0 + idx * 0.0001, 100.0 + idx * 5.0, t=base + timedelta(seconds=idx * 10))
        for idx in range(8)
    ]
    climb = SimpleNamespace(
        start_time_offset_s=base + timedelta(seconds=10),
        end_time_offset_s=base + timedelta(seconds=50),
        tile_ids=[],
        vert_m=25.0,
        time_s=40,
    )
    monkeypatch.setattr(road_enrichment, "fetch_road_features_for_tiles", lambda _tile_ids: [])

    enriched = road_enrichment.enrich_climbs([climb], samples)

    assert len(enriched) == 1
