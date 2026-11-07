"""Canonical effort reads, using generated FIT/GPX/TCX and synthetic D11 gates."""

import importlib.util
import math
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "effort_vectors", Path(__file__).resolve().parents[3] / "workout-parse/tests/test_training.py"
)
vectors = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vectors)


def score(times, powers, speeds, start, end, **kwargs):
    from app.services.climb_effort_metrics import compute_effort, effort_timeline

    activity = vectors.synthetic_activity(
        times, powers, speeds, kwargs.pop("hrs", None), kwargs.pop("cadence", None)
    )
    return compute_effort(
        effort_timeline(activity), start_s=start, end_s=end,
        time_s=round(end - start), distance_m=100, net_gain_m=10,
        threshold_w=kwargs.pop("threshold_w", 250), **kwargs,
    )


def test_np_carries_the_rides_window_into_the_effort():
    result = score(list(range(91)), [400] * 60 + [100] * 31, [5] * 91, 60, 90)
    rolling = [(400 * (29 - i) + 100 * (i + 1)) / 30 for i in range(30)]
    expected = math.floor((sum(p**4 for p in rolling) / 30) ** 0.25 + 0.5)
    assert result["np_w"] == expected
    assert result["np_w"] != 100  # restarting at the gate would produce 100
    assert result["avg_power_w"] == 100
    assert result["power_kind"] == "measured"


def test_finish_stop_is_included_in_time_and_flushed_at_gate():
    result = score(
        list(range(31)), [200] * 31, [5] * 15 + [0.5] * 5 + [4] * 11,
        5, 20, cadence=[80] * 31,
    )
    assert result["time_s"] == 15
    assert result["moving_s"] == 15  # stop threshold differs from analytics moving
    stop, = result["stops"]
    assert stop["duration_s"] == 5
    assert stop["start_m"] == pytest.approx(50 / 52.5 * 100)
    assert stop["end_m"] == 100
    assert stop["cost"]["estimate"] is True
    assert stop["cost"]["seconds"] == 4.5
    assert stop["cost"]["range_s"] == pytest.approx([3.5, 5])


def test_estimate_is_standard_mass_and_has_no_measured_power_derivatives():
    result = score(list(range(21)), [None] * 21, [5] * 21, 0, 20, weight_kg=51)
    other = score(list(range(21)), [None] * 21, [5] * 21, 0, 20, weight_kg=120)
    angle = math.atan(10 / 100)
    expected = (83 * 9.80665 * (math.sin(angle) + 0.005 * math.cos(angle)) * 5
                + 0.5 * 1.225 * 0.32 * 5**3) / 0.975
    assert result["estimated_power_w"] == pytest.approx(expected)
    assert "avg_power_w" not in result
    assert result["estimated_power_range_w"][0] < expected < result["estimated_power_range_w"][1]
    assert other["estimated_power_w"] == result["estimated_power_w"]
    assert result["power_kind"] == "estimated"
    for key in ("np_w", "intensity_factor", "load", "w_per_kg", "power_zone_s", "max_power_w"):
        assert key not in result
    assert "avg_hr_bpm" not in result


@pytest.mark.parametrize("power,zone", [(137, 0), (138, 1), (187, 1), (188, 2),
                                      (225, 2), (226, 3), (262, 3), (263, 4),
                                      (300, 4), (301, 5), (375, 5), (376, 6)])
def test_zone_tops_are_floored_and_inclusive(power, zone):
    result = score(list(range(11)), [power] * 11, [5] * 11, 0, 10)
    assert result["power_zone_tops_w"] == [137, 187, 225, 262, 300, 375]
    assert result["power_zone_s"] == [10 if i == zone else 0 for i in range(7)]


def test_load_uses_whole_watt_np_moving_seconds_and_half_up():
    result = score(list(range(19)), [250] * 19, [5] * 19, 0, 18)
    assert result["intensity_factor"] == 1
    assert result["load"] == 1  # 0.5 must not round to even/zero


def test_left_sum_fractional_bounds_and_sensor_omission():
    result = score([0, 1, 2, 3], [100, 200, 300, 400], [5] * 4, 0.5, 2.5,
                   weight_kg=50, hrs=[0, 120, 140, 0], cadence=[0, 60, 90, 0])
    assert result["avg_power_w"] == 150
    assert result["w_per_kg"] == 3
    assert result["avg_cadence_rpm"] == 70
    assert result["avg_hr_bpm"] == pytest.approx(380 / 3)
    assert result["max_hr_bpm"] == 140
    assert result["avg_torque_nm"] == pytest.approx(200 / (2 * math.pi))
    assert "best_30s_w" not in result and "best_60s_w" not in result


def test_turnaround_below_start_uses_the_restarted_d11_span():
    from backend.tests.services.test_canon_traversal import _evaluate, _sample
    from app.services.climb_effort_metrics import canonical_span

    evaluation = _evaluate([
        _sample(0, 0), _sample(10, 0.2), _sample(20, 0),
        _sample(30, 0.2), _sample(40, 0.4), _sample(50, 0.6),
        _sample(60, 0.8), _sample(70, 1),
    ])
    pattern, = evaluation.climb_patterns
    start, end = canonical_span(pattern.to_dict())
    assert start == pytest.approx(25, abs=0.01)
    assert end == pytest.approx(65, abs=0.01)
    result = score(list(range(71)), [400] * 25 + [200] * 46, [5] * 71, start, end)
    assert result["time_s"] == 40
    assert result["avg_power_w"] == pytest.approx(200, abs=0.01)


def test_power_bracketing_a_short_recording_gap_covers_its_effort():
    result = score([0, 10, 20, 30], [100, 200, 300, 400], [5] * 4, 12, 18)
    assert result["power_kind"] == "measured"
    assert result["avg_power_w"] == 245


def test_complete_best_windows_include_fractional_gate_boundaries():
    result = score(list(range(62)), [200] * 62, [5] * 62, 0.5, 60.5)
    assert result["best_30s_w"] == 200
    assert result["best_60s_w"] == 200


def test_long_recording_gap_is_zero_power_not_a_stop_or_a_window_restart():
    result = score([0, 1, 40, 41, 42], [300] * 5, [5] * 5, 1, 42)
    assert result["power_kind"] == "measured"
    assert result["moving_s"] == 3
    assert result["avg_power_w"] == pytest.approx(900 / 41)
    assert result["stops"] == []


def test_effort_entirely_without_power_is_estimated_even_if_ride_has_power():
    result = score([0, 200], [300, 300], [5, 5], 50, 150)
    assert result["power_kind"] == "estimated"


def test_fractional_last_recording_second_can_contain_the_finish_gate():
    import workout_parse as wp
    from app.services.climb_effort_metrics import compute_effort, effort_timeline

    points = "".join(
        f'<trkpt lat="{40 + i * .001}" lon="-75"><time>2026-10-01T12:00:{t}Z</time></trkpt>'
        for i, t in enumerate(("00", "10", "20", "30.500"))
    )
    activity = wp.parse_bytes(f'<gpx version="1.1"><trk><trkseg>{points}</trkseg></trk></gpx>'.encode())
    result = compute_effort(effort_timeline(activity), start_s=10.5, end_s=30.25,
                            time_s=20, distance_m=200, net_gain_m=10)
    assert result["time_s"] == 20
    assert result["power_kind"] == "estimated"


def test_house_np_moving_only_and_load_moving_only():
    result = score(list(range(37)), [250] * 37, [5] * 18 + [0] * 19, 0, 36)
    assert result['np_w'] == 250
    assert result['moving_s'] == 18
    assert result['load'] == 1  # elapsed would round to 1 too; use 3x Threshold below
    result = score(list(range(37)), [750] * 37, [5] * 18 + [0] * 19, 0, 36)
    assert result['load'] == 5  # 4.5 half-up, not elapsed-time 9


def test_house_np_half_up_and_zones_use_five_seconds():
    from app.services.climb_effort_metrics import effort_timeline, compute_effort
    timeline = effort_timeline(vectors.synthetic_activity([0, 1, 2], [100, 101, 101], [5] * 3))
    result = compute_effort(timeline, start_s=1, end_s=2, time_s=1, distance_m=5, net_gain_m=1)
    assert result['np_w'] == 101  # partial trailing average is exactly 100.5
    result = score(list(range(11)), [100] * 5 + [400] * 6, [5] * 11, 5, 10)
    assert result['power_zone_s'] == [0, 1, 1, 0, 1, 1, 1]


@pytest.mark.parametrize('speed,length,expected', [(0.5, 2, 0), (0.5, 3, 1), (1, 4, 0)])
def test_house_stop_duration_and_strict_speed(speed, length, expected):
    result = score(list(range(21)), [200] * 21, [5] * 5 + [speed] * length + [5] * (16-length), 0, 20)
    assert len(result['stops']) == expected


def test_house_torque_gate_vam_official_time_and_bracketing():
    result = score([0, 1, 2, 3, 4], [200] * 5, [5] * 5, 0.1, 3.5, cadence=[19, 20, 20, 19, 19])
    assert result['avg_torque_nm'] == pytest.approx(200 / (2 * math.pi * 20 / 60))
    assert result['vam_m_per_hour'] == 12000  # official 3 s, not raw 3.4 s
    result = score(list(range(21)), [None] * 2 + [200] * 19, [5] * 21, 1, 20)
    assert result['power_kind'] == 'estimated'


def test_meter_requires_95_percent_moving_coverage():
    for missing, kind in [(5, 'measured'), (6, 'estimated')]:
        result = score(list(range(101)), [200] * 20 + [None] * missing + [200] * (81-missing), [5] * 101, 0, 100)
        assert result['power_kind'] == kind


def test_whole_second_average_and_training_vi():
    result = score([0, 1, 2, 3], [100, 201, 300, 400], [5] * 4, 0.5, 2.5)
    assert result['avg_power_w'] == 150.5
    assert result['variability_index'] == result['np_w'] / 151


def test_auto_pause_gap_counts_without_changing_training_motion():
    result = score([0, 1, 2, 38, 39, 40], [200] * 6, [5, 5, 0, 0, 5, 5], 0, 40)
    stop, = result['stops']
    assert stop['duration_s'] == 37
    assert result['time_s'] == 40 and result['moving_s'] == 3
    assert stop['cost']['seconds'] == 37


def test_regular_two_second_sampling_does_not_invent_a_stop():
    result = score([0, 2, 4, 6, 8], [200] * 5, [2, 0, 2, 2, 2], 0, 8)
    assert result['stops'] == []


def test_finish_stop_has_one_sided_wider_cost_range():
    result = score(list(range(21)), [200] * 21, [5] * 10 + [0] * 11, 0, 20)
    stop, = result['stops']
    assert stop['cost']['seconds'] == 10
    assert stop['cost']['range_s'][0] < 10 <= stop['cost']['range_s'][1]


def test_missing_speed_is_unknown_and_export_does_not_change_training():
    import workout_parse as wp
    from app.services.climb_effort_metrics import effort_timeline, compute_effort
    activity = vectors.synthetic_activity(list(range(21)), [200] * 21, [None] * 21)
    before = wp.compute_training_metrics(activity, 250, engine_version=3)
    original_hash = wp.hash_canonical_ride(activity)
    timeline = effort_timeline(activity)
    assert timeline['speed_mps'] == [None] * 21
    result = compute_effort(timeline, start_s=0, end_s=20, time_s=20, distance_m=100, net_gain_m=10)
    assert result['stops'] == []
    after = wp.compute_training_metrics(activity, 250, engine_version=3)
    assert after.moving_s == before.moving_s and after.np_w == before.np_w
    assert wp.hash_canonical_ride(activity) == original_hash


@pytest.mark.parametrize('powers', [[None] + [200] * 100, [200] * 99 + [None] * 2])
def test_high_coverage_does_not_substitute_for_power_at_both_gates(powers):
    result = score(list(range(101)), powers, [5] * 101, 0, 100)
    assert result['power_kind'] == 'estimated'  # 99% observed, but not bracketed


def xml_motion(times, distances, *, kind='gpx', speeds=None, missing=(), distance_channel=True):
    from datetime import datetime, timedelta, timezone
    import workout_parse as wp
    origin = datetime(2026, 10, 1, tzinfo=timezone.utc)
    points = []
    for i, (t, distance) in enumerate(zip(times, distances)):
        stamp = (origin + timedelta(seconds=t)).isoformat().replace('+00:00', 'Z')
        lat = 40 + distance / 111195
        if kind == 'gpx':
            coordinate = f' lat="{lat:.8f}" lon="-75"' if i not in missing else ''
            points.append(f'<trkpt{coordinate}><time>{stamp}</time></trkpt>')
        else:
            position = f'<Position><LatitudeDegrees>{lat:.8f}</LatitudeDegrees><LongitudeDegrees>-75</LongitudeDegrees></Position>' if i not in missing else ''
            speed = f'<Speed>{speeds[i]}</Speed>' if speeds is not None else ''
            device_distance = f'<DistanceMeters>{distance}</DistanceMeters>' if distance_channel else ''
            points.append(f'<Trackpoint><Time>{stamp}</Time>{position}{device_distance}'
                          f'<Extensions><TPX>{speed}</TPX></Extensions></Trackpoint>')
    data = ('<gpx><trk><trkseg>' + ''.join(points) + '</trkseg></trk></gpx>' if kind == 'gpx' else
            '<TrainingCenterDatabase><Activities><Activity><Lap><Track>' + ''.join(points) +
            '</Track></Lap></Activity></Activities></TrainingCenterDatabase>')
    return wp.parse_file_bytes(data.encode(), kind)


@pytest.mark.parametrize('kind,with_speed,step', [('gpx', False, 1), ('gpx', False, 5), ('tcx', False, 1), ('tcx', True, 1)])
def test_gps_stand_is_fifteen_seconds_and_recorded_tcx_speed_wins(kind, with_speed, step):
    from app.services.climb_effort_metrics import compute_effort, effort_timeline
    speeds = [0 if 30 <= t < 45 else 5 for t in range(91)]
    distances = [sum(speeds[:t]) for t in range(91)]
    timeline = effort_timeline(xml_motion(range(0, 91, step), distances[::step], kind=kind,
                                         speeds=speeds[::step] if with_speed else None))
    result = compute_effort(timeline, start_s=5, end_s=85, time_s=80, distance_m=400, net_gain_m=20)
    stop, = result['stops']
    assert stop['start_s'] == 25 and stop['duration_s'] == 15
    assert stop['cost']['seconds'] == pytest.approx(15)
    if with_speed:
        assert timeline['speed_mps'] == speeds


def test_gpx_autopause_has_stop_and_cost_without_speed_or_distance_channels():
    from app.services.climb_effort_metrics import compute_effort, effort_timeline
    timeline = effort_timeline(xml_motion([0, 1, 2, 42, 43, 44], [0, 5, 10, 10, 15, 20]))
    result = compute_effort(timeline, start_s=0, end_s=44, time_s=44, distance_m=20, net_gain_m=1)
    stop, = result['stops']
    assert stop['duration_s'] >= 40
    assert stop['cost']['estimate'] and stop['cost']['seconds'] >= 39
    assert stop['cost']['range_s'][0] <= stop['cost']['seconds'] <= stop['cost']['range_s'][1]


def test_gpx_autopause_after_stationary_samples_is_one_stop():
    from app.services.climb_effort_metrics import compute_effort, effort_timeline
    # iOS records the 5 s at or below 0.5 m/s before auto-pause, then no samples until resume.
    times = list(range(15)) + list(range(55, 70))
    distances = [5 * t for t in range(10)] + [45] * 5 + [53 + 5 * (t - 55) for t in range(55, 70)]
    result = compute_effort(effort_timeline(xml_motion(times, distances)), start_s=0, end_s=69,
                            time_s=69, distance_m=120, net_gain_m=5)
    stop, = result['stops']
    assert (stop['start_s'], stop['end_s']) == (9, 55)


def test_missing_gpx_coordinate_does_not_become_a_zero_speed_stop():
    from app.services.climb_effort_metrics import compute_effort, effort_timeline
    timeline = effort_timeline(xml_motion(range(31), [5*t for t in range(31)], missing=range(10, 20)))
    # The unchanged GPX parser omits coordinate-less records. The surviving
    # valid segment is moving; its absent samples must not become zero speed.
    assert all(v is not None and v > 4.9 for v in timeline['speed_mps'][9:20])
    assert timeline['speed_mps'][0] == pytest.approx(5, abs=.01)
    result = compute_effort(timeline, start_s=0, end_s=30, time_s=30, distance_m=150, net_gain_m=5)
    assert result['stops'] == []


def test_speedless_tcx_stop_after_missing_coordinate_keeps_cost_but_not_cross_break_positions():
    from app.services.climb_effort_metrics import compute_effort, effort_timeline
    speeds = [0 if 30 <= t < 45 else 5 for t in range(61)]
    timeline = effort_timeline(xml_motion(range(61), [sum(speeds[:t]) for t in range(61)],
                                         kind='tcx', missing=[10], distance_channel=False))
    assert timeline['speed_mps'][9:11] == [None, None]
    result = compute_effort(timeline, start_s=0, end_s=60, time_s=60, distance_m=300, net_gain_m=10)
    stop, = result['stops']
    assert stop['duration_s'] == 15 and stop['cost']['seconds'] == pytest.approx(15)
    assert 'start_m' not in stop and 'end_m' not in stop


def fit_distance(times, speeds, distances):
    import struct
    import workout_parse as wp
    fields = [(253, 4, 0x86), (7, 2, 0x84), (6, 2, 0x84), (5, 4, 0x86)]
    body = bytearray(struct.pack('<BBBHB', 0x40, 0, 0, 20, len(fields)))
    for field in fields:
        body.extend(bytes(field))
    for t, speed, distance in zip(times, speeds, distances):
        body.extend(struct.pack('<BIHHI', 0, 1000000+t, 200, round(speed*1000), round(distance*100)))
    header = struct.pack('<BBHI4s', 14, 0x10, 2100, len(body), b'.FIT')
    header += struct.pack('<H', vectors.crc(header))
    data = header + body
    return wp.parse_bytes(data + struct.pack('<H', vectors.crc(data)))


@pytest.mark.parametrize('advance,has_stop', [(10, True), (40, True), (41, False), (200, False)])
def test_gap_with_fast_edges_uses_distance_and_has_a_cost(advance, has_stop):
    from app.services.climb_effort_metrics import compute_effort, effort_timeline
    times = list(range(60)) + list(range(100, 160))
    distances = [5*t if t < 60 else 295+advance+5*(t-100) for t in times]
    timeline = effort_timeline(fit_distance(times, [5]*120, distances))
    result = compute_effort(timeline, start_s=5, end_s=155, time_s=150, distance_m=600, net_gain_m=30)
    assert bool(result['stops']) == has_stop
    if has_stop:
        assert timeline['speed_mps'][60] == pytest.approx(advance/41)
        stop, = result['stops']
        assert stop['cost']['seconds'] == pytest.approx(40 - (advance*40/41)/5)
        assert stop['cost']['range_s'][0] <= stop['cost']['seconds'] <= stop['cost']['range_s'][1]
    else:
        assert timeline['speed_mps'][60] is None  # no pause evidence to fill this unrecorded gap


def test_gap_edge_is_strict_and_short_recording_intervals_keep_interpolation():
    from app.services.climb_effort_metrics import effort_timeline
    long = effort_timeline(vectors.synthetic_activity([0, 1, 42, 43], [200]*4, [5, 1, 1, 5]))
    assert long['speed_mps'][10] is None  # speed exactly 1 does not establish a pause
    short = effort_timeline(vectors.synthetic_activity([0, 1, 21, 22], [200]*4, [5, 0, 5, 5]))
    assert short['speed_mps'][11] == 2.5  # 20-second ordinary sampling stays interpolated


def test_fractional_gap_finish_keeps_the_recorded_endpoint_speed():
    from app.services.climb_effort_metrics import effort_timeline
    timeline = effort_timeline(xml_motion([0, 1, 42.5, 43.5, 44.5], [0, 5, 5, 10, 15]))
    assert timeline['speed_mps'][42] == pytest.approx(5, abs=.01)


def test_stop_positions_are_scaled_to_canon_distance():
    result = score(list(range(31)), [200]*31, [5]*10 + [0]*5 + [5]*16, 0, 30)
    stop, = result['stops']
    assert stop['start_m'] == pytest.approx(40)  # device 50 / 125, canon 100
    assert stop['end_m'] == pytest.approx(40)
    assert stop['cost']['seconds'] == 5  # cost stays in matching device distance/speed units


def test_estimate_range_endpoints_and_rounded_average_start():
    from app.services.climb_effort_metrics import estimate_power
    point, bounds = estimate_power(1000, 300, 100)
    angle = math.atan2(300, 1000)
    expected = lambda cda, crr: (83*9.80665*(math.sin(angle)+crr*math.cos(angle))*10 + .5*1.225*cda*10**3)/.975
    assert [point, *bounds] == pytest.approx([expected(.32,.005), expected(.28,.004), expected(.36,.006)], abs=1e-9)
    result = score([0,1,2,3], [100,200,300,400], [5]*4, .75, 2.75)
    assert result['avg_power_w'] == 250
