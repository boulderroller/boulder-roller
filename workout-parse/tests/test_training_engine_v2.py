"""Synthetic wiring vectors; no third-party rides or provider values."""

import pytest
import workout_parse as wp
from test_training import synthetic_activity


def test_v2_calorie_definition_is_versioned_and_v1_replays():
    activity = synthetic_activity(list(range(60)), [200] * 60, [5] * 60)
    old = wp.compute_training_metrics(activity, 250)
    new = wp.compute_training_metrics(activity, 250, engine_version=2)
    assert old.engine_version == 1
    assert old.calories_kcal == pytest.approx(12 / 4.184 / 0.24)
    assert new.engine_version == 2
    assert new.calories_kcal == pytest.approx(12 / 4.184 / 0.22)
    assert new.calories_estimate is True
    assert old.load == new.load


def test_hrss_hour_at_threshold_is_100_and_does_not_price_effort():
    activity = synthetic_activity(
        list(range(3600)), [None] * 3600, [5] * 3600, [160] * 3600
    )
    result = wp.compute_training_metrics(
        activity, 0, engine_version=2, lthr_bpm=160, resting_hr_bpm=60, max_hr_bpm=190
    )
    assert result.load == 100
    assert result.load_basis == "hrss"
    assert result.best_20m_hr_bpm == 160
    assert sum(result.hr_zone_s) == 3600
    assert result.hr_zone_tops_bpm == [128, 143, 149, 159, 163, 168]
    assert wp.compute_metrics(activity, 250).tss is None


def test_clean_curve_uses_elapsed_seconds_and_keeps_zero_gaps():
    result = wp.compute_training_metrics(
        synthetic_activity([0, 1, 40, 41], [200] * 4, [5] * 4), 250, engine_version=2
    )
    assert result.power_curve_w[result.power_curve_s.index(30)] == pytest.approx(
        400 / 30
    )
    assert result.power_zone_tops_w == [137, 187, 225, 262, 300, 375]


def test_friel_zones_use_five_second_smoothing():
    result = wp.compute_training_metrics(
        synthetic_activity(
            list(range(10)), [None] * 10, [5] * 10, [100] * 5 + [180] * 5
        ),
        0,
        engine_version=2,
        lthr_bpm=160,
        resting_hr_bpm=60,
        max_hr_bpm=190,
    )
    assert result.hr_zone_s == [6, 1, 1, 0, 0, 1, 1]


def test_device_calories_are_not_estimated():
    result = wp.compute_training_metrics(
        synthetic_activity(list(range(60)), [200] * 60, [5] * 60, calories=123),
        250,
        engine_version=2,
    )
    assert result.calories_kcal == 123
    assert result.calories_estimate is False


def test_span_reads_same_engine_and_cannot_use_whole_device_totals():
    activity = synthetic_activity(
        list(range(60)), [100] * 30 + [300] * 30, [5] * 60, calories=900
    )
    result = wp.compute_training_metrics(
        activity, 250, engine_version=2, start_s=30, end_s=59
    )
    assert result.elapsed_s == 29
    assert result.np_w == 300
    assert result.calories_estimate is True
    assert result.work_j == 9000


def test_average_speed_excludes_stopped_time():
    result = wp.compute_training_metrics(
        synthetic_activity(list(range(3600)), [180] * 3600, [8] * 3000 + [0] * 600),
        250,
        engine_version=2,
    )
    assert result.avg_speed_mps == pytest.approx(8)


def test_power_without_threshold_falls_back_to_hrss():
    activity = synthetic_activity(
        list(range(3600)), [180] * 3600, [5] * 3600, [150] * 3600
    )
    result = wp.compute_training_metrics(
        activity, 0, engine_version=2, lthr_bpm=160, resting_hr_bpm=60, max_hr_bpm=190
    )
    assert result.load == 78
    assert result.load_basis == "hrss"


def test_average_speed_uses_the_selected_device_distance():
    activity = synthetic_activity(
        list(range(60)), [200] * 60, [5] * 60, session_distance=600
    )
    result = wp.compute_training_metrics(activity, 250, engine_version=2)
    assert result.distance_m == 600
    assert result.avg_speed_mps == pytest.approx(600 / result.moving_s)
