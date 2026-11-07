from datetime import datetime, timedelta, timezone

from app.services.sensor_integrity import (
    SensorIntegrityReport,
    compute_sensor_integrity,
    get_abstention_reasons_from_integrity,
)


def _clean_report(**overrides):
    values = {
        "gps_coverage": 1.0,
        "elev_coverage": 1.0,
        "elev_plausible": True,
        "sample_count": 120,
        "gap_ratio": 0.0,
        "gps_jump_count": 0,
        "integrity_score": 0.95,
        "power_coverage": 0.0,
        "hr_coverage": 0.0,
        "speed_coverage": 1.0,
    }
    values.update(overrides)
    return SensorIntegrityReport(**values)


def test_route_only_effort_abstains_from_economics():
    reasons = get_abstention_reasons_from_integrity(_clean_report())

    assert "EFFORT:route_estimate_only" in reasons


def test_heart_rate_effort_is_reward_grade_when_geometry_is_clean():
    reasons = get_abstention_reasons_from_integrity(_clean_report(hr_coverage=0.42))

    assert "EFFORT:route_estimate_only" not in reasons
    assert reasons == []


def test_compute_sensor_integrity_accepts_datetime_sample_times():
    base_time = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)
    samples = [
        {
            "t": base_time + timedelta(seconds=offset),
            "lat": 40.0 + offset / 10000,
            "lon": -105.0 - offset / 10000,
            "elevation_m": 1600.0 + offset / 10,
            "power_w": 220,
            "hr_bpm": 145,
            "speed_mps": 7.5,
        }
        for offset in range(0, 120, 10)
    ]

    report = compute_sensor_integrity(samples)

    assert report.sample_count == len(samples)
    assert report.median_interval_s == 10.0
    assert report.max_gap_s == 10
    assert report.power_coverage == 1.0
    assert report.hr_coverage == 1.0
    assert report.speed_coverage == 1.0


def test_compute_sensor_integrity_ignores_untimed_rows_for_interval_math():
    base_time = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)
    samples = [
        {
            "t": base_time + timedelta(seconds=offset),
            "lat": 40.0 + offset / 10000,
            "lon": -105.0 - offset / 10000,
            "elevation_m": 1600.0,
            "power_w": 220,
        }
        for offset in range(0, 100, 10)
    ]
    samples.append(
        {
            "lat": 40.02,
            "lon": -105.02,
            "elevation_m": 1605.0,
            "power_w": 200,
        }
    )

    report = compute_sensor_integrity(samples)

    assert report.sample_count == len(samples)
    assert report.median_interval_s == 10.0
    assert report.max_gap_s == 10
