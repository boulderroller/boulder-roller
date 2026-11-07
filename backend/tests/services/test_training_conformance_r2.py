"""Synthetic production-path conformance regressions; no retained ride data."""

import pytest
import workout_parse as wp

from app.services.training_metrics import compute, project_training
from backend.tests.services.test_training_pipeline import vectors


def inputs(**settings):
    return {
        "started_at": "2026-01-01T12:00:00Z",
        "timezone": "UTC",
        "threshold": {"value": 250, "estimate": False, "basis": "ios"},
        "settings": {"threshold_hr_bpm": 160, "max_hr_bpm": 190, **settings},
    }


def test_frozen_explicit_hr_tops_win_over_derived_friel_zones():
    activity = vectors.synthetic_activity(
        list(range(6)), [200] * 6, [5] * 6, [119, 120, 121, 150, 151, 190]
    )
    result = compute(activity, inputs(hr_zone_tops_bpm=[120, 150, 190]))
    assert result["hr_zone_s"] == [2, 2, 2]
    assert result["hr_zone_tops_bpm"] == [120, 150, 190]


def test_friel_hr_zones_use_readings_without_power_smoothing():
    activity = vectors.synthetic_activity(
        list(range(10)), [200] * 10, [5] * 10, [100] * 5 + [180] * 5
    )
    assert compute(activity, inputs())["hr_zone_s"] == [5, 0, 0, 0, 0, 0, 5]


@pytest.mark.parametrize("power", [200, None])
def test_device_calories_keep_device_basis_and_estimate_mark(power):
    calories = 123
    activity = vectors.synthetic_activity(
        list(range(60)), [power] * 60, [5] * 60, calories=calories
    )
    result = compute(activity, inputs())
    assert result["calories_kcal"] == calories
    assert result["calories_estimate"] is True
    assert result["estimates"]["calories"] == {
        "value": calories, "estimate": True, "basis": "device"
    }
    public = project_training(
        {"processing_status": "completed", "training_metrics": result}, owner=False
    )
    assert public["training_metrics"]["estimates"]["calories"] == result["estimates"]["calories"]


@pytest.mark.parametrize("power", [200, None])
def test_zero_device_calories_use_work_or_remain_absent(power):
    def result(calories):
        activity = vectors.synthetic_activity(
            list(range(60)), [power] * 60, [5] * 60, calories=calories
        )
        return compute(activity, inputs())

    zero, missing = result(0), result(None)
    assert zero["engine_version"] == missing["engine_version"] == 3
    # Compare to the no-device path so this fails on zero admission alone,
    # independently of the work-efficiency rule.
    assert zero["calories_kcal"] == missing["calories_kcal"]
    assert zero["estimates"]["calories"] == missing["estimates"]["calories"]
    if power is None:
        assert zero["calories_kcal"] is None
        assert zero["calories_basis"] is None
        assert zero["calories_estimate"] is False


def test_work_fallback_keeps_ratified_formula_and_economics():
    activity = vectors.synthetic_activity(list(range(60)), [200] * 60, [5] * 60)
    before = wp.compute_metrics(activity, 250).tss
    digest = wp.hash_canonical_ride(activity)
    result = compute(activity, inputs())
    assert result["engine_version"] == 3
    assert result["estimates"]["calories"] == {
        "value": pytest.approx(12 / 4.184 / 0.24),
        "estimate": True,
        "basis": "work_kj_div_4.184_div_0.24",
    }
    assert wp.compute_metrics(activity, 250).tss == before
    assert wp.hash_canonical_ride(activity) == digest
