"""Synthetic conformance vectors for Training v3. No retained activity data."""

import struct

import pytest
import workout_parse as wp
from test_training import crc, synthetic_activity
from test_training_gps import gps_activity


def score(hrs, speeds, *, times=None, **kwargs):
    n = len(hrs)
    return wp.compute_training_metrics(
        synthetic_activity(times or list(range(n)), [200] * n, speeds, hrs),
        250, engine_version=3, hr_zones_bpm=[120, 150, 190], **kwargs,
    )


def test_hr_missing_speed_is_not_a_recorded_stop():
    # Missing speed is admitted for HR zones; a recorded zero still stops them.
    result = score([120, 121, 151, 190], [5, None, 0, 5])
    assert result.hr_zone_s == [1, 1, 1]
    assert result.moving_s == 2


def test_gps_derived_motion_keeps_stationary_hr_out_of_zones():
    activity = gps_activity("tcx")
    whole = wp.compute_training_metrics(activity, 250, engine_version=3,
                                        hr_zones_bpm=[150, 190])
    assert whole.hr_zone_s == [whole.moving_s, 0] == [1680, 0]
    stopped = wp.compute_training_metrics(activity, 250, engine_version=3,
                                          hr_zones_bpm=[150, 190],
                                          start_s=900, end_s=1020)
    assert stopped.moving_s == 0
    assert stopped.hr_zone_s == [0, 0]


def test_hr_span_presence_does_not_change_distance_or_speed():
    # Invented FIT: distance is present only outside the selected span.
    fields = [(253, 4, 0x86), (0, 4, 0x85), (1, 4, 0x85),
              (7, 2, 0x84), (6, 2, 0x84), (3, 1, 2), (5, 4, 0x86)]
    body = bytearray(struct.pack("<BBBHB", 0x40, 0, 0, 20, len(fields)))
    for field in fields:
        body.extend(bytes(field))
    for second in range(10):
        body.extend(struct.pack(
            "<BIiiHHBI", 0, 1_000_000 + second,
            round((40 + second * 0.00005) * 2**31 / 180),
            round(-75.2 * 2**31 / 180), 200,
            65535 if second == 4 else 5000, 130,
            0 if second == 0 else 0xFFFFFFFF,
        ))
    header = struct.pack("<BBHI4s", 14, 0x10, 2100, len(body), b".FIT")
    header += struct.pack("<H", crc(header))
    data = header + body
    activity = wp.parse_bytes(data + struct.pack("<H", crc(data)))
    legacy, current = [
        wp.compute_training_metrics(activity, 250, engine_version=version,
                                    start_s=3, end_s=8, hr_zones_bpm=[160, 190])
        for version in (2, 3)
    ]
    assert legacy.distance_m == 0
    assert current.distance_m == legacy.distance_m
    assert current.avg_speed_mps == legacy.avg_speed_mps
    assert current.moving_s == legacy.moving_s == 5
    assert current.hr_zone_s == [6, 0]


def test_hr_missing_readings_have_bounded_zone_one_admission():
    result = score([None] * 7 + [151], [5] * 8)
    assert result.hr_zone_s == [5, 0, 1]
    stopped = score([None] * 7 + [151], [0] * 7 + [5])
    assert stopped.hr_zone_s == [0, 0, 1]
    absent = score([None] * 8, [5] * 8)
    assert absent.hr_zone_s is None


def test_zone_one_fill_stops_after_the_first_hr_reading():
    leading = score([None] * 7 + [151], [5] * 8)
    trailing = score([151] + [None] * 7, [5] * 8)
    after_gap = score([151, None, 151], [5] * 3,
                      times=[0, 31, 32], gap_fill_s=8)
    assert leading.engine_version == trailing.engine_version == after_gap.engine_version == 3
    assert leading.hr_zone_s == [5, 0, 1]
    assert trailing.hr_zone_s == [0, 0, 1]
    assert after_gap.hr_zone_s == [0, 0, 2]


def test_span_cannot_restart_zone_one_fill_after_an_earlier_hr_reading():
    activity = synthetic_activity(list(range(42)), [200] * 42, [5] * 42,
                                  [140] + [None] * 40 + [151])
    result = wp.compute_training_metrics(
        activity, 250, engine_version=3, hr_zones_bpm=[120, 150, 190],
        start_s=31, end_s=41,
    )
    assert result.engine_version == 3
    assert result.hr_zone_s == [0, 0, 1]


def test_span_keeps_the_rides_five_record_leading_hr_limit():
    activity = synthetic_activity(list(range(8)), [200] * 8, [5] * 8,
                                  [None] * 7 + [151])
    result = wp.compute_training_metrics(
        activity, 250, engine_version=3, hr_zones_bpm=[120, 150, 190],
        start_s=3, end_s=7,
    )
    assert result.engine_version == 3
    assert result.hr_zone_s == [2, 0, 1]


def test_hr_hold_and_missing_carry_remain_independent_of_power_gap_fill():
    result = score([120, 151, 120, 151], [5] * 4,
                   times=[0, 10, 20, 51], gap_fill_s=8)
    assert result.hr_zone_s == [11, 0, 11]
    assert result.moving_s == 4
    carry = score([140] + [None] * 7 + [160], [5] * 9)
    assert carry.hr_zone_s == [0, 6, 1]


def test_duplicate_second_uses_last_record_for_hr_availability():
    result = score([None, 151, 120], [None, 0, 5], times=[0, 0, 1])
    assert result.hr_zone_s == [1, 0, 0]


@pytest.mark.parametrize("cadence,expected", [(None, 8), ([90, 0, 90, 0, 90], 3)])
def test_speedless_fallback_remains_explicitly_provisional(cadence, expected):
    activity = synthetic_activity([0, 2, 4, 14, 16], [0] * 5, [None] * 5,
                                  [130] * 5, cadence)
    result = wp.compute_training_metrics(activity, 250, engine_version=3,
                                         hr_zones_bpm=[140, 190])
    assert result.moving_s == expected
    assert result.hr_zone_s == [expected, 0]


def test_current_gap_default_remains_thirty_seconds():
    result = score([120] * 3, [5] * 3, times=[0, 10, 11])
    assert result.moving_s == 12


def test_device_calorie_provenance_and_legacy_versions_replay():
    activity = synthetic_activity(list(range(60)), [200] * 60, [5] * 60,
                                  calories=123)
    for version in (1, 2, 3):
        result = wp.compute_training_metrics(activity, 250, engine_version=version)
        assert result.calories_kcal == 123
        assert result.calories_estimate is (version == 3)
        assert result.calories_basis == "device"
    span = wp.compute_training_metrics(activity, 250, engine_version=3,
                                       start_s=30, end_s=59)
    assert span.calories_basis == "work_kj_div_4.184_div_0.24"
    assert span.calories_kcal == pytest.approx(6 / 4.184 / 0.24)


def test_training_v3_preserves_canonical_and_economic_outputs():
    activity = synthetic_activity(list(range(60)), [200] * 60, [5] * 60,
                                  [130] * 60, calories=123)
    digest = wp.hash_canonical_ride(activity)
    old = wp.compute_metrics(activity, 250)
    wp.compute_training_metrics(activity, 250, engine_version=3, lthr_bpm=160)
    new = wp.compute_metrics(activity, 250)
    assert wp.hash_canonical_ride(activity) == digest
    for name in ("tss", "normalized_power_w", "avg_power_w", "intensity_factor"):
        assert getattr(new, name) == getattr(old, name)
