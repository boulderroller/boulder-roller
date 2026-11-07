from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services.ride_idle_evidence import assess_idle_recording, IDLE_REVIEW_REASON

START = datetime(2026, 9, 20, tzinfo=timezone.utc)


def records(seconds=120, **channels):
    return [SimpleNamespace(timestamp=START + timedelta(seconds=i), **channels) for i in range(seconds)]


@pytest.mark.parametrize("channels", [
    {"speed_mps": 0, "cadence_rpm": 0, "power_w": 0},
    {"speed_mps": 0, "power_w": 0},
    {"distance_m": 10, "power_w": 0},
    {"lat": 40.0, "lon": -75.0, "power_w": 0},
    {"cadence_rpm": 0, "power_w": 0},  # trainer without speed/GPS
])
def test_positive_stationary_evidence_enters_review(channels):
    evidence = assess_idle_recording(records(**channels))
    assert evidence.recorded_duration_s == evidence.stationary_duration_s == 119
    assert evidence.review_reason == IDLE_REVIEW_REASON


@pytest.mark.parametrize("channels", [
    {"speed_mps": 8, "cadence_rpm": 0, "power_w": 0},  # coasting
    {"speed_mps": 0, "cadence_rpm": 85, "power_w": 250},  # trainer
    {"cadence_rpm": 85, "power_w": 250},
    {"power_w": 250},
    {"power_w": 0},  # unknown movement, not evidence of stationary time
    {"cadence_rpm": 0},
    {"speed_mps": float("nan"), "power_w": 0},
    {},
])
def test_motion_effort_and_unknown_signals_do_not_become_stationary(channels):
    evidence = assess_idle_recording(records(**channels))
    assert evidence.stationary_duration_s == 0
    assert evidence.review_reason is None


@pytest.mark.parametrize("seconds,stationary", [(31, 0), (32, 31)])
def test_stationary_span_must_exceed_30_seconds(seconds, stationary):
    assert assess_idle_recording(records(seconds, speed_mps=0)).stationary_duration_s == stationary


def test_recording_gaps_never_become_idle_or_join_short_stops():
    samples = records(31, speed_mps=0) + [
        SimpleNamespace(timestamp=START + timedelta(seconds=i), speed_mps=0)
        for i in range(3600, 3631)
    ]
    evidence = assess_idle_recording(samples)
    assert evidence.recorded_duration_s == 60
    assert evidence.stationary_duration_s == 0
    assert evidence.review_reason is None


def test_sparse_recording_is_time_weighted_and_retains_unknown_denominator():
    samples = [SimpleNamespace(timestamp=START + timedelta(seconds=i), speed_mps=0)
               for i in range(0, 120, 10)]
    samples += [SimpleNamespace(timestamp=START + timedelta(seconds=i)) for i in range(120, 131)]
    evidence = assess_idle_recording(samples)
    assert evidence.recorded_duration_s == 130
    assert evidence.stationary_duration_s == 110
    assert evidence.stationary_share_bps == 8461
    assert evidence.review_reason is None


@pytest.mark.parametrize("idle_seconds,review", [(9261, False), (9262, True), (9263, True)])
def test_ratified_review_boundary_is_92_62_percent_of_recorded_time(idle_seconds, review):
    # 10000 one-second intervals; boundary interval is deliberately unknown.
    samples = records(10001, speed_mps=8)
    for record in samples[:idle_seconds + 1]:
        record.speed_mps = 0
    evidence = assess_idle_recording(samples)
    assert evidence.stationary_share_bps == idle_seconds
    assert (evidence.review_reason is not None) is review
    assert evidence.policy_version == "stationary_recording_review_v2"
    assert evidence.review_share_bps == 9262
    assert evidence.stationary_max_speed_mps == 0.5
    assert evidence.stationary_min_span_s == 30


def test_positive_cadence_or_power_vetoes_zero_speed():
    for field in ("cadence_rpm", "power_w"):
        samples = records(speed_mps=0, cadence_rpm=0, power_w=0)
        for record in samples:
            setattr(record, field, 1)
        assert assess_idle_recording(samples).review_reason is None


def test_distance_and_gps_movement_preserve_zero_watt_coasting():
    for field in ("distance_m", "lat"):
        samples = records(power_w=0, cadence_rpm=0, lat=40.0, lon=-75.0)
        for i, record in enumerate(samples):
            setattr(record, field, i * 8 if field == "distance_m" else 40 + i * .0001)
        assert assess_idle_recording(samples).stationary_duration_s == 0


def test_real_power_ride_with_moving_zero_watt_samples_is_unchanged():
    from pathlib import Path
    pytest.importorskip("workout_parse")
    from app.services.workout_parse_adapter import parse_ride_file_bytes_rust, calculate_metrics_rust

    ride = parse_ride_file_bytes_rust(
        (Path(__file__).resolve().parents[3] / "docs/in_the_bag_.fit").read_bytes(), "fit"
    )
    before = calculate_metrics_rust(ride, user_ftp_w=250)
    assert sum(r.power_w == 0 and (r.speed_mps or 0) > .5 for r in ride.records) == 2432
    assert assess_idle_recording(ride.records).review_reason is None
    after = calculate_metrics_rust(ride, user_ftp_w=250)
    assert before == after
    assert after.tss == 404.3
    assert after.normalized_power_duration_s == 16259


@pytest.mark.parametrize("ridden,power,total,expected,review", [
    (3600, 250, 129600, 598.106323, True),
    (600, 300, 129600, 345.791992, True),
    (3600, 250, 7200, 141.243973, False),
])
def test_padded_recording_retains_standard_tss_and_separate_review(ridden, power, total, expected, review):
    wp = pytest.importorskip("workout_parse")
    times = [i * 1000 for i in range(total)]
    powers = [power] * ridden + [0] * (total - ridden)
    # The same native function serves climb windows. It must retain its exact
    # recorded-zero semantics; a rejected ride receives no CAL or climb tribute.
    measured = wp.compute_segment_power_metrics(times, powers)
    tss = wp.calculate_tss_from_power(measured.normalized_power_duration_s, measured.normalized_power_raw_w, 250)
    assert tss == pytest.approx(expected, abs=.001)
    assert measured.normalized_power_duration_s == total
    samples = [SimpleNamespace(timestamp=START + timedelta(seconds=i), power_w=powers[i],
                               speed_mps=8 if i < ridden else 0, cadence_rpm=85 if i < ridden else 0)
               for i in range(total)]
    evidence = assess_idle_recording(samples)
    assert (evidence.review_reason is not None) is review
    alone = wp.compute_segment_power_metrics(times[:ridden], powers[:ridden])
    alone_tss = wp.calculate_tss_from_power(alone.normalized_power_duration_s, alone.normalized_power_raw_w, 250)
    assert alone_tss == pytest.approx(100 if ridden == 3600 else 24, abs=.001)


@pytest.mark.parametrize("channel", ("distance_m", "lat"))
def test_moving_descent_is_not_stationary_when_speed_sensor_is_stuck(channel):
    samples = records(speed_mps=0, power_w=0, cadence_rpm=0, distance_m=0, lat=40., lon=-75.)
    for i, sample in enumerate(samples):
        setattr(sample, channel, i * 8 if channel == "distance_m" else 40 + i * .0001)
    assert assess_idle_recording(samples).stationary_duration_s == 0


def _trainer_fit(*, missing_speed=False):
    import runpy
    import struct
    from pathlib import Path
    helpers = runpy.run_path(str(Path(__file__).resolve().parents[3] /
                                "workout-parse/tests/fixtures/torture/generate_corpus.py"))
    body = bytearray(helpers["fit_definition"](0, 20, [(253, 4, 0x86), (7, 2, 0x84), (6, 2, 0x84)]))
    start = helpers["fit_timestamp"]("2026-09-20T00:00:00Z")
    for i in range(3660):
        speed = 8000 if i < 60 else (65535 if missing_speed else 0)
        body.extend(helpers["fit_data"](0, struct.pack("<IHH", start+i, 250 if i < 60 else 0, speed)))
    return helpers["wrap_fit"](bytes(body))


def test_speed_only_trainer_fit_keeps_explicit_zero_separate_from_missing():
    wp = pytest.importorskip("workout_parse")
    from app.services.workout_parse_adapter import parse_ride_file_bytes_rust
    stopped = parse_ride_file_bytes_rust(_trainer_fit(), "fit")
    missing = parse_ride_file_bytes_rust(_trainer_fit(missing_speed=True), "fit")
    # Captured from origin/main before the evidence sidecar was added. Presence
    # is deliberately outside the canonical ride hash and metrics version.
    for ride in (stopped, missing):
        assert wp.hash_canonical_ride(ride._native_activity) == (
            "425e4386591e80aab6a70b872f9e5cc9c68608a6a332ee43d48bf3dbfbe417e8"
        )
    assert stopped.records[60].speed_mps == 0
    assert missing.records[60].speed_mps is None
    assert assess_idle_recording(stopped.records).review_reason == IDLE_REVIEW_REASON
    assert assess_idle_recording(missing.records).review_reason is None


@pytest.mark.parametrize("speed,review", [(8, False), (0, True)])
def test_tcx_trainer_speed_extension_preserves_coasting(speed, review):
    pytest.importorskip("workout_parse")
    from app.services.workout_parse_adapter import parse_ride_file_bytes_rust
    points = "".join(
        f"<Trackpoint><Time>{(START + timedelta(seconds=i)).isoformat()}</Time>"
        f"<Cadence>0</Cadence><Extensions><TPX><Speed>{speed}</Speed><Watts>0</Watts>"
        "</TPX></Extensions></Trackpoint>" for i in range(120)
    )
    ride = parse_ride_file_bytes_rust(
        (f'<TrainingCenterDatabase><Activities><Activity Sport="Biking"><Lap><Track>{points}'
         '</Track></Lap></Activity></Activities></TrainingCenterDatabase>').encode(), "tcx"
    )
    assert (assess_idle_recording(ride.records).review_reason is not None) is review
    assert ride.records[1].speed_mps == speed
    assert ride._native_activity.speed_mps is None  # historical hash/metrics channel unchanged
