from datetime import datetime, timedelta, timezone

from app.services.patterns.climb_profile import build_ride_climb_profile


def test_build_ride_climb_profile_accumulates_distance_and_window_metrics():
    samples = [
        {"t": 0, "lat": 39.95, "lon": -75.16, "elevation_m": 100.0, "tile_id": "a"},
        {"t": 60, "lat": 39.951, "lon": -75.16, "elevation_m": 110.0, "tile_id": "b"},
        {"t": 120, "lat": 39.952, "lon": -75.16, "elevation_m": 118.0, "tile_id": "c"},
        {"t": 180, "lat": 39.953, "lon": -75.16, "elevation_m": 116.0, "tile_id": "d"},
    ]

    profile = build_ride_climb_profile(samples, terrain_class="rolling", terrain_confidence=0.8)

    assert len(profile.points) == 4
    assert profile.total_distance_m > 300.0
    assert profile.points[-1].distance_m == profile.total_distance_m
    assert profile.terrain_class == "rolling"

    metrics = profile.metrics_for_time_window(0, 180)
    assert metrics.start_distance_m == 0.0
    assert metrics.end_distance_m == profile.total_distance_m
    assert metrics.ascent_m > 0.0
    assert metrics.avg_grade_pct is not None


def test_build_ride_climb_profile_falls_back_to_speed_when_gps_missing():
    samples = [
        {"t": 0, "elevation_m": 100.0, "speed_mps": 6.0, "tile_id": "a"},
        {"t": 10, "elevation_m": 102.0, "speed_mps": 6.0, "tile_id": "b"},
        {"t": 20, "elevation_m": 105.0, "speed_mps": 6.0, "tile_id": "c"},
    ]

    profile = build_ride_climb_profile(samples)

    assert profile.total_distance_m == 120.0
    metrics = profile.metrics_for_time_window(0, 20)
    assert metrics.span_distance_m == 120.0
    assert metrics.boundary_rise_m > 0.0


def test_build_ride_climb_profile_accepts_datetime_samples():
    base = datetime(2026, 6, 12, 18, 0, tzinfo=timezone.utc)
    samples = [
        {
            "t": base + timedelta(seconds=offset),
            "elevation_m": elevation,
            "speed_mps": 6.0,
            "tile_id": tile_id,
        }
        for offset, elevation, tile_id in (
            (0, 100.0, "a"),
            (60, 110.0, "b"),
            (120, 118.0, "c"),
        )
    ]

    profile = build_ride_climb_profile(samples)

    assert [point.t for point in profile.points] == [0.0, 60.0, 120.0]
    assert profile.total_distance_m == 720.0
    metrics = profile.metrics_for_time_window(0, 120)
    assert metrics.end_time_s == 120
    assert metrics.boundary_rise_m > 0.0
