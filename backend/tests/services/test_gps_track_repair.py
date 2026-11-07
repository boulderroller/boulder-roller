from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services.gps_track_repair import (
    analyze_v1_elevation_sentinel,
    evaluate_climb_source_quality,
    gps_track_records_from_parsed_ride,
)
from app.utils.polyline import encode_delta_array, encode_polyline, encode_gps_track


def _v1_track_with_elevations(elevations_m: list[float]) -> dict:
    coords = [(40.0 + i * 0.0001, -105.0 - i * 0.0001) for i in range(len(elevations_m))]
    elevations_dm = [round(elevation * 10) for elevation in elevations_m]
    return {
        "polyline": encode_polyline(coords),
        "elevations": encode_delta_array(elevations_dm),
        "timestamps": encode_delta_array(list(range(len(elevations_m)))),
        "distances": encode_delta_array([i * 10 for i in range(len(elevations_m))]),
        "precision": 5,
        "version": 1,
    }


def test_analyze_v1_elevation_sentinel_flags_corey_like_zero_prefix_jump() -> None:
    track = _v1_track_with_elevations([0, 0, 0, 0, 0, 2300.4, 2302.2])

    analysis = analyze_v1_elevation_sentinel(track)

    assert analysis.suspicious is True
    assert analysis.reason == "zero_prefix_altitude_jump"
    assert analysis.zero_prefix_count == 5
    assert analysis.first_nonzero_index == 5
    assert analysis.first_nonzero_elevation_m == pytest.approx(2300.4)


def test_analyze_v1_elevation_sentinel_does_not_flag_gradual_sea_level_start() -> None:
    track = _v1_track_with_elevations([0, 0, 0, 0, 0, 1.2, 2.6, 4.0])

    analysis = analyze_v1_elevation_sentinel(track)

    assert analysis.suspicious is False
    assert analysis.reason == "no_v1_zero_prefix_jump"


def test_analyze_v1_elevation_sentinel_skips_already_masked_v2_track() -> None:
    track = encode_gps_track([
        {
            "latitude": 40.0,
            "longitude": -105.0,
            "elevation_m": None,
            "timestamp": 0,
        },
        {
            "latitude": 40.1,
            "longitude": -105.1,
            "elevation_m": 2300.4,
            "timestamp": 1,
        },
    ])

    analysis = analyze_v1_elevation_sentinel(track)

    assert analysis.suspicious is False
    assert analysis.reason == "already_v2"


def test_gps_track_records_from_parsed_ride_preserves_missing_and_real_zero() -> None:
    started_at = datetime(2020, 7, 18, 15, 14, 12, tzinfo=timezone.utc)
    parsed = SimpleNamespace(
        gps_track=[
            SimpleNamespace(timestamp=started_at, lat=40.0, lon=-105.0, elevation_m=None),
            SimpleNamespace(timestamp=started_at, lat=40.1, lon=-105.1, elevation_m=0.0),
            SimpleNamespace(timestamp=started_at, lat=40.2, lon=-105.2, elevation_m=123.4),
        ]
    )

    records = gps_track_records_from_parsed_ride(parsed)
    encoded = encode_gps_track(records)

    assert [record["elevation_m"] for record in records] == [None, 0.0, 123.4]
    assert encoded["version"] == 2
    assert [list(item) for item in encoded["elevation_missing_ranges"]] == [[0, 1]]


def test_gps_track_records_from_parsed_ride_keeps_zero_coordinates() -> None:
    started_at = datetime(2020, 7, 18, 15, 14, 12, tzinfo=timezone.utc)
    parsed = SimpleNamespace(
        gps_track=[
            SimpleNamespace(timestamp=started_at, lat=0.0, lon=0.0, elevation_m=1.0),
        ]
    )

    records = gps_track_records_from_parsed_ride(parsed)

    assert records[0]["latitude"] == 0.0
    assert records[0]["longitude"] == 0.0


def test_evaluate_climb_source_quality_counts_overlapping_tile_runs() -> None:
    climb = SimpleNamespace(
        vert_m=100.0,
        time_s=400,
        distance_m=1000.0,
        avg_gradient_pct=10.0,
        start_time_offset_s=50,
        end_time_offset_s=150,
    )
    samples = [
        SimpleNamespace(t=0, t_end=75, lat=20.0, lon=-156.0, elevation_m=10.0),
        SimpleNamespace(t=150, t_end=200, lat=20.1, lon=-156.1, elevation_m=110.0),
    ]

    quality = evaluate_climb_source_quality(climb, samples, context="test")

    assert quality["sample_count"] == 2
    assert quality["economic_eligible"] is True


def test_evaluate_climb_source_quality_marks_extreme_shape_for_review() -> None:
    climb = SimpleNamespace(
        vert_m=4280.8,
        time_s=12564,
        distance_m=42087.9,
        avg_gradient_pct=10.17,
        start_time_offset_s=0,
        end_time_offset_s=12564,
    )
    samples = [
        {"t": 0, "lat": 20.0, "lon": -156.0, "elevation_m": 0.0},
        {"t": 12564, "lat": 20.5, "lon": -156.5, "elevation_m": 4280.8},
    ]

    quality = evaluate_climb_source_quality(climb, samples, context="test")

    assert quality["economic_eligible"] is False
    assert "CLIMB_SHAPE:extreme_distance_grade_requires_raw_replay" in quality["abstention_reasons"]
