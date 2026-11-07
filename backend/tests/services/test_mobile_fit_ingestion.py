from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

pytest.importorskip("workout_parse")

from app.services.workout_parse_adapter import (  # noqa: E402
    _activity_to_parsed_ride,
    calculate_metrics_rust,
    parse_ride_file_bytes_rust,
)


FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "mobile_sensor_ride_fit_v1.base64"
)


def test_mobile_generated_sensor_fit_is_ingested_with_power_hr_and_cadence() -> None:
    fit_bytes = base64.b64decode(FIXTURE_PATH.read_text().strip())

    parsed = parse_ride_file_bytes_rust(fit_bytes, "fit")

    assert len(parsed.records) == 3
    assert len(parsed.gps_track) == 3
    assert [r.power_w for r in parsed.records] == [200, 220, 240]
    assert [r.heart_rate_bpm for r in parsed.records] == [140, 145, 150]
    assert [r.cadence_rpm for r in parsed.records] == [85, 88, 90]
    assert [round(r.speed_mps or 0, 1) for r in parsed.records] == [5.0, 6.0, 7.0]

    metrics = calculate_metrics_rust(parsed, user_ftp_w=245)

    assert metrics.metrics_version == "workout_parse_metrics_v1"
    assert metrics.avg_power_w == 220
    assert metrics.max_power_w == 240
    assert metrics.normalized_power_w is None
    assert metrics.moving_time_sec == 3
    assert metrics.power_sample_count == 3
    assert metrics.power_sample_coverage_bps == 10_000
    assert metrics.avg_hr_bpm == 145
    assert metrics.max_hr_bpm == 150
    assert metrics.avg_cadence_rpm == 88
    assert metrics.avg_speed_mps == 6.0
    assert metrics.max_speed_mps == 7.0
    assert metrics.tss == 0.0


def test_rust_adapter_preserves_missing_sensor_values_as_none() -> None:
    fake_wp = SimpleNamespace(
        MISSING_I32=-2147483648,
        MISSING_U16=65535,
        MISSING_U8=255,
    )
    activity = SimpleNamespace(
        time_ms=np.array([1_000, 2_000, 3_000]),
        lat_e7=np.array([40_0000000, 40_0001000, 40_0002000]),
        lon_e7=np.array([-105_0000000, -105_0001000, -105_0002000]),
        elevation_m=np.array([100.0, 101.0, 102.0], dtype=np.float32),
        pwr_w=np.array([250, fake_wp.MISSING_U16, 260], dtype=np.uint16),
        hr_bpm=np.array([fake_wp.MISSING_U8, 151, 152], dtype=np.uint8),
        cadence_rpm=np.array([92, fake_wp.MISSING_U8, 94], dtype=np.uint8),
        speed_mps=np.array([5.5, 0.0, 6.5], dtype=np.float32),
        dist_m=None,
        started_at_ms=1_000,
        device_name=None,
        sport="cycling",
    )

    parsed = _activity_to_parsed_ride(activity, fake_wp)

    assert [record.power_w for record in parsed.records] == [250, None, 260]
    assert [record.heart_rate_bpm for record in parsed.records] == [None, 151, 152]
    assert [record.cadence_rpm for record in parsed.records] == [92, None, 94]
    assert [record.speed_mps for record in parsed.records] == [pytest.approx(5.5), None, pytest.approx(6.5)]


def test_rust_adapter_preserves_half_coordinate_as_malformed_gps_evidence() -> None:
    fake_wp = SimpleNamespace(
        MISSING_I32=-2147483648,
        MISSING_U16=65535,
        MISSING_U8=255,
    )
    activity = SimpleNamespace(
        time_ms=np.array([1_000, 2_000]),
        lat_e7=np.array([40_0000000, 40_0001000]),
        lon_e7=np.array([fake_wp.MISSING_I32, -105_0001000]),
        elevation_m=np.array([100.0, 101.0], dtype=np.float32),
        pwr_w=None,
        hr_bpm=None,
        cadence_rpm=None,
        speed_mps=None,
        dist_m=None,
        started_at_ms=1_000,
        device_name=None,
        sport="cycling",
    )

    parsed = _activity_to_parsed_ride(activity, fake_wp)

    assert parsed.records[0].lat == 40.0
    assert parsed.records[0].lon is None
    assert len(parsed.gps_track) == 1
    assert parsed.gps_track[0].lat == pytest.approx(40.0001)


def test_rust_adapter_maps_nan_elevation_to_missing_without_losing_sea_level_zero() -> None:
    activity = SimpleNamespace(
        time_ms=np.array([1_000, 2_000, 3_000]),
        lat_e7=np.array([40_0000000, 40_0001000, 40_0002000]),
        lon_e7=np.array([-105_0000000, -105_0001000, -105_0002000]),
        elevation_m=np.array([np.nan, 0.0, 123.4], dtype=np.float32),
        pwr_w=None,
        hr_bpm=None,
        cadence_rpm=None,
        speed_mps=None,
        dist_m=None,
        started_at_ms=1_000,
        device_name=None,
        sport="cycling",
    )
    fake_wp = SimpleNamespace(
        MISSING_I32=-2147483648,
        MISSING_U16=65535,
        MISSING_U8=255,
    )

    parsed = _activity_to_parsed_ride(activity, fake_wp)

    assert [record.elevation_m for record in parsed.records] == [None, 0.0, pytest.approx(123.4)]
    assert [point.elevation_m for point in parsed.gps_track] == [None, 0.0, pytest.approx(123.4)]
