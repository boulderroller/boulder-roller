from datetime import date
import pytest
from app.services.fitness_analytics import FitnessAnalyticsService, normalize_to_date


def test_bad_training_date_never_becomes_today():
    with pytest.raises(ValueError):
        normalize_to_date("not-a-date")


def test_load_reads_frozen_training_score_not_current_threshold():
    rides = [
        {
            "id": "r",
            "started_at": "2026-10-08T01:00:00Z",
            "processing_status": "completed",
            "threshold_training_kind": "sealed",
            "normalized_power_raw_w": 300,
            "normalized_power_duration_s": 3600,
            "training_metrics": {
                "engine_version": 2,
                "load": 100,
                "local_date": "2026-10-07",
                "load_estimate": False,
            },
        }
    ]
    result = FitnessAnalyticsService.threshold_training_snapshot(
        rides,
        threshold_w=500,
        threshold={"threshold_version": "v2"},
        start_date=date(2026, 10, 1),
        target_date=date(2026, 10, 7),
    )
    assert result["training_load"]["daily_loads"][0]["date"] == "2026-10-07"
    assert result["training_load"]["total_tss"] == 100
    assert result["training_load"]["avg_daily_tss"] == pytest.approx(100 / 7)
    assert result["fitness_metrics"]["tsb"] == 2 - 13


@pytest.mark.parametrize(
    "form,expected",
    [
        (21, "Transition"),
        (20, "Fresh"),
        (5, "Grey zone"),
        (-10, "Optimal"),
        (-30, "High risk"),
    ],
)
def test_form_band_slots(form, expected):
    assert FitnessAnalyticsService._get_form_status(form) == expected


def test_climb_category_strict_boundaries_and_below_category_absent():
    from app.services.patterns.climb import ClimbPattern

    assert (
        ClimbPattern(
            vert_m=50, time_s=30, distance_m=500, avg_gradient_pct=10
        ).calculate_uci_category()
        is None
    )
    assert (
        ClimbPattern(
            vert_m=100, time_s=30, distance_m=800, avg_gradient_pct=10
        ).calculate_uci_category()
        is None
    )
    assert (
        ClimbPattern(
            vert_m=100, time_s=30, distance_m=801, avg_gradient_pct=10
        ).calculate_uci_category()
        == "4"
    )
