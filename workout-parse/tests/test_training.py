"""Synthetic streams only; no local activity data or stored scorer values."""
import importlib.util
from pathlib import Path
import struct

import pytest
import workout_parse as wp

_path = Path(__file__).resolve().parents[2] / "tools/analytics_reference/icu_reference.py"
_spec = importlib.util.spec_from_file_location("icu_reference", _path)
reference = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reference)


def crc(data):
    value = 0
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ (0xA001 if value & 1 else 0)
    return value


def synthetic_activity(times, powers, speeds, hrs=None, cadence=None, calories=None,
                       session_hr=None, session_distance=None):
    """Build a tiny FIT in memory from explicitly synthetic test inputs."""
    fields = [(253, 4, 0x86), (7, 2, 0x84), (6, 2, 0x84),
              (3, 1, 2), (4, 1, 2)]
    body = bytearray(struct.pack("<BBBHB", 0x40, 0, 0, 20, len(fields)))
    for field in fields:
        body.extend(bytes(field))
    for i, (t, p, s) in enumerate(zip(times, powers, speeds)):
        body.extend(struct.pack("<BIHHBB", 0, 1_000_000 + t,
                                65535 if p is None else p,
                                65535 if s is None else round(s * 1000),
                                255 if hrs is None or hrs[i] is None else hrs[i],
                                255 if cadence is None or cadence[i] is None else cadence[i]))
    session_fields = []
    session_data = b""
    if calories is not None:
        session_fields.append((11, 2, 0x84))
        session_data += struct.pack("<H", calories)
    if session_distance is not None:
        session_fields.append((9, 4, 0x86))
        session_data += struct.pack("<I", round(session_distance * 100))
    if session_hr is not None:
        session_fields.extend([(16, 1, 2), (17, 1, 2)])
        session_data += bytes(session_hr)
    if session_fields:
        body.extend(struct.pack("<BBBHB", 0x41, 0, 0, 18, len(session_fields)))
        for field in session_fields:
            body.extend(bytes(field))
        body.extend(bytes((1,)) + session_data)
    header = struct.pack("<BBHI4s", 14, 0x10, 2100, len(body), b".FIT")
    header += struct.pack("<H", crc(header))
    data = header + body
    return wp.parse_bytes(data + struct.pack("<H", crc(data)))


@pytest.mark.parametrize("gap", range(1, 41))
@pytest.mark.parametrize("gap_fill", [8, 30])
def test_gap_and_autopause_reference(gap, gap_fill):
    times = [0, 1, 1 + gap, 2 + gap, 3 + gap, 4 + gap]
    powers = [180, 300, 420, None, None, 210]
    speeds = [4, 4, 4, 0, 0, 4]
    activity = synthetic_activity(times, powers, speeds)
    result = wp.compute_training_metrics(activity, 250, gap_fill_s=gap_fill)
    expected = reference.summarize(times, powers, speeds, 250, gap_fill)
    for name, value in expected.items():
        assert getattr(result, name) == pytest.approx(value), name
    assert result.engine_version == wp.TRAINING_ENGINE_VERSION == 1


def test_partial_window_stopped_missing_and_spike():
    times = list(range(12))
    powers = [200, 260, None, 5000, 0, 190, None, None, None, 100, 200, 300]
    speeds = [4] * 6 + [0] * 3 + [0.05] * 3
    result = wp.compute_training_metrics(synthetic_activity(times, powers, speeds), 250)
    for name, value in reference.summarize(times, powers, speeds, 250).items():
        assert getattr(result, name) == pytest.approx(value), name


def test_absent_sensors_do_not_invent_sensor_metrics():
    result = wp.compute_training_metrics(synthetic_activity([0, 1, 2], [None] * 3,
                                                         [None] * 3), 0)
    assert result.moving_s == 3  # provisional recording-time fallback
    for name in ["np_w", "np_raw_w", "load", "intensity_pct",
                 "avg_power_w", "work_j", "power_zone_s", "hr_zone_s",
                 "avg_hr_bpm", "max_hr_bpm", "avg_cadence_rpm",
                 "distance_m", "elevation_gain_m", "calories_kcal", "decoupling_pct"]:
        assert getattr(result, name) is None, name


@pytest.mark.parametrize("cadence", [None, [None] * 90, [90] * 30 + [0] * 30 + [90] * 30])
def test_no_speed_uses_cadence_then_recording_time(cadence):
    """Provisional: the local conformance corpus has no speedless recordings."""
    times = list(range(90))
    powers = [200] * 30 + [0] * 30 + [300] * 30
    hr = [130] * 90
    result = wp.compute_training_metrics(
        synthetic_activity(times, powers, [None] * 90, hr, cadence), 250,
        hr_zones_bpm=[130, 180])
    power, moving = reference.timeline(times, powers, None, cadence=cadence)
    np_raw = reference.normalized_power(power, moving)
    np_w = reference.half_up(np_raw)
    assert result.moving_s == sum(moving)
    assert result.np_raw_w == pytest.approx(np_raw)
    assert result.np_w == np_w
    assert result.load == reference.load(np_w, 250, sum(moving))
    assert result.intensity_pct == reference.intensity_pct(np_w, 250)
    repaired = reference.repair_power_samples(times, powers, cadence)
    assert result.power_zone_s == reference.power_zone_times(repaired, moving, 250)
    heart, active = reference.hr_zone_timeline(times, hr, moving, has_speed=False)
    assert result.hr_zone_s == reference.hr_zone_times(heart, active, [130, 180])


def test_no_speed_recording_fallback_excludes_abnormal_gaps():
    # Median positive interval is 2 s. The 10 s pause's interior is not moving,
    # even though gap_fill_s allows power interpolation across it.
    activity = synthetic_activity([0, 2, 4, 14, 16], [0] * 5, [None] * 5, [130] * 5)
    result = wp.compute_training_metrics(activity, 250, hr_zones_bpm=[130, 180])
    assert result.moving_s == 8
    assert result.np_w == result.load == 0
    assert result.power_zone_s == [8, 0, 0, 0, 0, 0, 0, 0]
    assert result.hr_zone_s == [8, 0]


def test_recorded_stationary_speed_takes_precedence_over_cadence():
    activity = synthetic_activity(list(range(60)), [200] * 60, [0] * 60,
                                  cadence=[90] * 60)
    result = wp.compute_training_metrics(activity, 250)
    assert result.moving_s == 0
    assert result.np_w is None


def test_training_does_not_change_effort_metrics_or_hash():
    activity = synthetic_activity(list(range(90)), [220] * 30 + [0] * 30 + [320] * 30,
                                  [5] * 30 + [0] * 30 + [5] * 30)
    before = wp.compute_metrics(activity, 250)
    ride_hash = wp.hash_canonical_ride(activity)
    wp.compute_training_metrics(activity, 250)
    after = wp.compute_metrics(activity, 250)
    assert wp.hash_canonical_ride(activity) == ride_hash
    for name in ["normalized_power_w", "tss", "intensity_factor", "avg_power_w"]:
        assert getattr(after, name) == getattr(before, name)


def test_session_calories_precede_estimate_and_do_not_change_hash():
    args = (list(range(60)), [200] * 60, [5] * 60)
    bare = synthetic_activity(*args)
    device = synthetic_activity(*args, calories=123)
    assert wp.compute_training_metrics(device, 250).calories_kcal == 123
    assert wp.compute_training_metrics(bare, 250).calories_kcal == pytest.approx(12000 / 1000 / 4.184 / 0.24)
    assert wp.hash_canonical_ride(bare) == wp.hash_canonical_ride(device)


def test_session_hr_is_retained_outside_the_hash():
    args = (list(range(60)), [200] * 60, [5] * 60)
    bare = synthetic_activity(*args)
    device = synthetic_activity(*args, session_hr=(130, 170))
    assert device.device_summary["avg_hr_bpm"] == 130
    assert device.device_summary["max_hr_bpm"] == 170
    assert wp.hash_canonical_ride(bare) == wp.hash_canonical_ride(device)


@pytest.mark.parametrize("missing", [True, False])
@pytest.mark.parametrize("length", range(1, 11))
def test_repaired_work_and_zones_reference(missing, length):
    times = list(range(80))
    powers = [220] * 80
    powers[10:10 + length] = [None if missing else 0] * length
    powers[40] = 5000  # no model curve was supplied: preserve the spike
    cadence = [90] * 80
    cadence[11] = 0  # protects this point for both missing and recorded zero power
    speeds = [5] * 80
    speeds[60:70] = [0] * 10
    hrs = [130 + i % 5 for i in times]
    activity = synthetic_activity(times, powers, speeds, hrs, cadence)
    result = wp.compute_training_metrics(activity, 251, hr_zones_bpm=[130, 132, 180])
    repaired = reference.repair_power_samples(times, powers, cadence)
    clean, moving = reference.timeline(times, repaired, speeds)
    expected_work = sum(clean)
    assert result.work_j == pytest.approx(expected_work)
    assert result.avg_power_w == pytest.approx(expected_work / reference.recording_time(times))
    assert result.power_zone_s == reference.power_zone_times(clean, moving, 251)
    assert sum(result.power_zone_s[:7]) == result.moving_s
    assert result.hr_zone_s == reference.hr_zone_times(hrs, moving, [130, 132, 180])
    assert result.np_w == reference.summarize(times, powers, speeds, 251)["np_w"]


def test_hr_and_power_zone_boundaries_and_missing_zones():
    times = list(range(60))
    activity = synthetic_activity(times, [110] * 60, [5] * 60, [130] * 60)
    result = wp.compute_training_metrics(activity, 200, hr_zones_bpm=[130, 180],
                                         sweet_spot_pct=(55, 55))
    assert result.power_zone_s == [60, 0, 0, 0, 0, 0, 0, 60]
    assert result.hr_zone_s == [60, 0]
    assert wp.compute_training_metrics(activity, 200).hr_zone_s is None
    assert wp.compute_training_metrics(activity, 0).power_zone_s is None
    for kwargs in [{"power_zones_pct": [55, 45, 90, 105, 120, 150]},
                   {"hr_zones_bpm": []}, {"sweet_spot_pct": (97, 84)}]:
        with pytest.raises(ValueError):
            wp.compute_training_metrics(activity, 200, **kwargs)


def test_session_hr_precedes_sample_summary():
    activity = synthetic_activity(list(range(60)), [220] * 60, [5] * 60,
                                  [131] * 60, session_hr=(130, 170))
    result = wp.compute_training_metrics(activity, 250)
    assert result.avg_hr_bpm == 130
    assert result.max_hr_bpm == 170
    assert result.efficiency_factor == pytest.approx(220 / 130)


def test_long_zero_run_is_not_split_at_missing_readings():
    powers = [220] * 10 + [0] * 8 + [None] * 8 + [220] * 14
    activity = synthetic_activity(list(range(40)), powers, [5] * 40, cadence=[90] * 40)
    assert wp.compute_training_metrics(activity, 250).work_j == 24 * 220


@pytest.mark.parametrize("length", [2, 5, 6, 12])
def test_missing_power_carries_at_most_five_points_and_respects_cadence(length):
    times = list(range(40))
    powers = [200] * 10 + [None] * length + [300] * (30 - length)
    cadence = [90] * 40
    cadence[11] = 0
    result = wp.compute_training_metrics(
        synthetic_activity(times, powers, [5] * 40, cadence=cadence), 250)
    assert result.work_j == 200 * (10 + min(5, length) - 1) + 300 * (30 - length)
    assert result.np_w == reference.summarize(times, powers, [5] * 40, 250)["np_w"]


def test_hr_zones_hold_previous_reading_across_gaps_up_to_thirty_seconds():
    times = [0, 10, 20, 51]
    heart_rate = [120, 150, 120, 150]
    activity = synthetic_activity(times, [200] * 4, [5] * 4, heart_rate)
    result = wp.compute_training_metrics(activity, 250, gap_fill_s=8,
                                         hr_zones_bpm=[130, 180])
    _, moving = reference.timeline(times, [200] * 4, [5] * 4, 8)
    heart, active = reference.hr_zone_timeline(times, heart_rate, moving, 8)
    assert result.hr_zone_s == reference.hr_zone_times(heart, active, [130, 180]) == [11, 11]
    assert result.moving_s == 4  # HR timing does not alter the phase-1 mask.


def test_hr_zones_carry_first_five_missing_readings():
    activity = synthetic_activity(list(range(16)), [200] * 16,
                                  [5] * 4 + [0] * 8 + [5] * 4,
                                  [120] * 4 + [None] * 8 + [150] * 4)
    result = wp.compute_training_metrics(activity, 250, hr_zones_bpm=[130, 180])
    assert result.hr_zone_s == [9, 4]
    assert result.moving_s == 8
