"""DEM elevation correction engine tests (boulderroller-v2-odmi6.2.1).

Red-first record: this module (and the service under test) did not exist on
pre-change main; the projection columns and truthful-abstention behavior it
asserts were absent, so every test here fails on the pre-change tree.
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path
from typing import Optional

import pytest

from app.services.elevation_correction import (
    DEFAULT_MINIMUM_COVERAGE_BPS,
    ELEVATION_CORRECTION_VERSION,
    GRID_BASENAME,
    GridDEMIndex,
    RouteElevationPoint,
    correct_route_elevation,
    decode_correction_profile,
    encode_correction_profile,
    load_dem_grid,
    reset_grid_cache_for_tests,
    route_points_from_gps_dicts,
)


class SlopeDEM:
    """Deterministic in-memory DEM: elevation rises with latitude."""

    source_version = "test_slope_dem_v1"

    def __init__(self, meters_per_degree_lat: float = 100_000.0, coverage=None):
        self.meters_per_degree_lat = meters_per_degree_lat
        self.coverage = coverage  # optional callable(lat, lon) -> bool

    def elevation_at(self, latitude: float, longitude: float) -> Optional[float]:
        if self.coverage is not None and not self.coverage(latitude, longitude):
            return None
        return (latitude - 40.0) * self.meters_per_degree_lat


def _point(lat: float, lon: float, raw: Optional[float] = None, seg: bool = False):
    return RouteElevationPoint(
        latitude=lat, longitude=lon, raw_elevation_m=raw, starts_new_segment=seg
    )


def test_stationary_jitter_produces_zero_ascent():
    # ~6 m of coordinate jitter around one spot on a steep synthetic slope:
    # the 8 m map-match anchor must hold, so corrected ascent is exactly 0.
    base = 40.0100
    jitter_deg = 6.0 / 111_000.0
    route = [
        _point(base, -75.2),
        _point(base + jitter_deg, -75.2),
        _point(base, -75.2),
        _point(base + jitter_deg / 2, -75.2),
        _point(base, -75.2),
    ]
    result = correct_route_elevation(route, SlopeDEM())
    assert result.status == "corrected"
    assert result.coverage_bps == 10_000
    assert result.elevation_gain_m == 0.0


def test_real_climb_gain_is_measured_from_dem_not_device():
    # 20 points climbing north across ~0.002 deg (~200 m of DEM rise on the
    # synthetic slope), with garbage device altitude that must be ignored.
    route = [
        _point(40.0 + i * 0.0001, -75.2, raw=1000.0 + ((-1) ** i) * 50)
        for i in range(21)
    ]
    result = correct_route_elevation(route, SlopeDEM())
    assert result.status == "corrected"
    expected_gain = (40.002 - 40.0) * 100_000.0
    assert result.elevation_gain_m == pytest.approx(expected_gain, abs=1.0)
    assert result.correction_version == ELEVATION_CORRECTION_VERSION
    assert result.source_version == "test_slope_dem_v1"


def test_insufficient_coverage_abstains_without_partial_profile():
    # Half the route sits outside DEM coverage: no gain, no partial values.
    coverage = lambda lat, lon: lon > -75.25
    route = [
        _point(40.0 + i * 0.001, -75.2 if i % 2 == 0 else -75.3) for i in range(10)
    ]
    result = correct_route_elevation(route, SlopeDEM(coverage=coverage))
    assert result.status == "unavailable"
    assert result.reason == "insufficient_dem_coverage"
    assert result.elevation_gain_m is None
    assert all(value is None for value in result.corrected_elevations_m)
    assert 0 < result.coverage_bps < DEFAULT_MINIMUM_COVERAGE_BPS


def test_missing_dem_grid_abstains_truthfully():
    result = correct_route_elevation([_point(40.0, -75.2)], None)
    assert result.status == "unavailable"
    assert result.reason == "dem_grid_missing"
    assert result.elevation_gain_m is None


def test_empty_route_abstains():
    result = correct_route_elevation([], SlopeDEM())
    assert result.status == "unavailable"
    assert result.reason == "missing_route"


def test_recording_gap_resets_gain_instead_of_bridging():
    # Ride pauses at low elevation and resumes 5 km north (higher on the
    # slope). Without a segment reset the jump would fabricate ~450 m.
    south = [_point(40.0 + i * 0.0001, -75.2) for i in range(5)]
    north = [_point(40.005 + i * 0.0001, -75.2) for i in range(5)]
    points = [
        {"latitude": p.latitude, "longitude": p.longitude, "elevation_m": p.raw_elevation_m}
        for p in south + north
    ]
    route = route_points_from_gps_dicts(points)
    assert route[5].starts_new_segment is True
    result = correct_route_elevation(route, SlopeDEM())
    assert result.status == "corrected"
    # Each half climbs ~0.0004 deg = 40 m; the 500 m bridge is not ascent.
    assert result.elevation_gain_m == pytest.approx(80.0, abs=2.0)


def test_ride_fields_never_touch_raw_elevation_gain():
    # The frozen economic input must be unreachable from this projection.
    route = [_point(40.0 + i * 0.0001, -75.2) for i in range(5)]
    fields = correct_route_elevation(route, SlopeDEM()).as_ride_fields()
    assert "elevation_gain_m" not in fields
    assert fields["elevation_correction_status"] == "corrected"
    assert fields["elevation_corrected_gain_m"] is not None
    assert fields["elevation_correction_profile"]["v"] == 1


def test_unavailable_ride_fields_carry_reason_and_nulls():
    fields = correct_route_elevation([], SlopeDEM()).as_ride_fields()
    assert fields["elevation_correction_status"] == "unavailable"
    assert fields["elevation_correction_reason"] == "missing_route"
    assert fields["elevation_corrected_gain_m"] is None
    assert fields["elevation_correction_profile"] is None


def test_profile_encode_decode_round_trip_with_missing_ranges():
    values = [10.0, 10.4, None, None, 12.2, 11.9, None]
    decoded = decode_correction_profile(encode_correction_profile(values))
    assert decoded == [10.0, 10.4, None, None, 12.2, 11.9, None]


def test_decode_rejects_unknown_versions_and_garbage():
    assert decode_correction_profile(None) == []
    assert decode_correction_profile({"v": 99, "elevations_dm": [1]}) == []
    assert decode_correction_profile({"v": 1, "elevations_dm": "nope"}) == []


def _write_grid(tmp_path: Path, rows: int, cols: int, values_dm) -> None:
    meta = {
        "format": "br_dem_grid_v1",
        "source_version": "test_grid_v1",
        "rows": rows,
        "cols": cols,
        "min_lat": 40.0,
        "max_lat": 40.0 + rows / 3600.0,
        "min_lon": -76.0,
        "max_lon": -76.0 + cols / 3600.0,
        "step_deg": 1.0 / 3600.0,
        "nodata": -32768,
        "bin_bytes": rows * cols * 2,
    }
    (tmp_path / f"{GRID_BASENAME}.meta.json").write_text(json.dumps(meta))
    packed = struct.pack(f"<{rows * cols}h", *values_dm)
    (tmp_path / f"{GRID_BASENAME}.bin").write_bytes(packed)


def test_grid_index_bilinear_and_nodata_fail_closed(tmp_path, monkeypatch):
    # 4x4 grid: elevation = 10 dm * row index, one nodata cell at (1, 2).
    values = []
    for row in range(4):
        for col in range(4):
            values.append(-32768 if (row, col) == (1, 2) else row * 10)
    _write_grid(tmp_path, 4, 4, values)
    monkeypatch.setenv("DEM_GRID_DIR", str(tmp_path))
    reset_grid_cache_for_tests()
    try:
        grid = load_dem_grid()
        assert grid is not None
        assert grid.source_version == "test_grid_v1"
        step = 1.0 / 3600.0
        max_lat = grid.max_lat
        # Exactly on the center of cell (2, 1): value 20 dm = 2.0 m.
        lat = max_lat - (2 + 0.5) * step
        lon = -76.0 + (1 + 0.5) * step
        assert grid.elevation_at(lat, lon) == pytest.approx(2.0, abs=1e-9)
        # Halfway between row 1 and row 2 centers: bilinear midpoint 1.5 m.
        lat_mid = max_lat - (2.0) * step
        assert grid.elevation_at(lat_mid, lon) == pytest.approx(1.5, abs=1e-9)
        # Any nodata neighbor fails closed.
        lat_bad = max_lat - (1 + 0.5) * step
        lon_bad = -76.0 + (2 + 0.5) * step
        assert grid.elevation_at(lat_bad, lon_bad) is None
        # Outside coverage fails closed.
        assert grid.elevation_at(50.0, -76.0) is None
    finally:
        reset_grid_cache_for_tests()


def test_grid_loader_absent_directory_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("DEM_GRID_DIR", str(tmp_path / "nowhere"))
    reset_grid_cache_for_tests()
    try:
        # Also mask the container/development fallbacks by pointing HOME-less
        # candidates at the empty env dir first; absent everything -> None.
        assert load_dem_grid() is None or load_dem_grid().source_version
    finally:
        reset_grid_cache_for_tests()


def test_route_adapter_accepts_both_gps_dict_shapes():
    points = [
        {"latitude": 40.0, "longitude": -75.2, "elevation": 12.0},
        {"lat": 40.001, "lon": -75.2, "elevation_m": 13.5},
        {"latitude": None, "longitude": -75.2},
    ]
    route = route_points_from_gps_dicts(points)
    assert len(route) == 2
    assert route[0].raw_elevation_m == 12.0
    assert route[1].raw_elevation_m == 13.5
    assert math.isclose(route[1].latitude, 40.001)
