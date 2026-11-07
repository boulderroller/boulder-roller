from datetime import date
from unittest.mock import AsyncMock
import pytest

from app.services.fitness_analytics import FitnessAnalyticsService
from app.services.training_metrics import project_training
from app.services.training_backfill import replay_training_batch
from app.services.fitness_analytics import training_date


def test_unavailable_load_is_partial_and_failed_uploads_do_not_count():
    rides = [
        {
            "id": "scored",
            "started_at": "2026-10-08",
            "processing_status": "failed",
            "training_metrics": {"load": 100},
        },
        {
            "id": "sensorless",
            "started_at": "2026-10-08",
            "processing_status": "completed",
            "training_metrics": {"load": None},
        },
        {
            "id": "missing",
            "started_at": "2026-10-08",
            "processing_status": "completed",
            "training_replay_state": {"error_class": "missing_original"},
        },
    ]
    result = FitnessAnalyticsService.threshold_training_snapshot(
        rides,
        threshold_w=0,
        threshold={"threshold_version": "training.v2"},
        start_date=date(2026, 10, 1),
        target_date=date(2026, 10, 8),
    )
    assert result["training_load"]["total_tss"] == 0
    assert result["coverage"] == {
        "completeness": "partial",
        "population": "0 / 2 rides",
        "observed_count": 0,
        "expected_count": 2,
        "pending_count": 0,
        "unavailable_count": 2,
    }


def test_public_training_exact_field_set_preserves_privacy():
    metrics = {
        name: 190
        for name in ("max_hr_bpm", "max_cadence_rpm", "max_speed_mps", "max_power_w")
    }
    public = project_training(
        {"processing_status": "completed", "training_metrics": metrics, "max_hr_bpm": 190}, owner=False
    )
    assert "max_hr_bpm" not in public
    assert set(public["training_metrics"]) == {
        "engine_version",
        "elapsed_s",
        "recording_s",
        "moving_s",
        "distance_m",
        "elevation_gain_m",
        "avg_power_w",
        "np_w",
        "avg_hr_bpm",
        "avg_cadence_rpm",
        "avg_speed_mps",
        "work_j",
        "calories_kcal",
        "calories_estimate",
        "estimates",
    }


def test_frozen_local_day_does_not_move_with_viewer_timezone():
    ride = {
        "started_at": "2026-10-08T01:00:00Z",
        "training_metrics": {"local_date": "2026-10-07"},
    }
    assert training_date(ride, "Asia/Tokyo") == date(2026, 10, 7)
    assert training_date(ride) == date(2026, 10, 7)


def test_week_totals_use_frozen_days_and_engine_clocks():
    from app.services.riding_days import aggregate_training_weeks

    rides = [
        {
            "started_at": "2026-10-05T01:00:00Z",
            "processing_status": "completed",
            "distance_m": 999,
            "duration_sec": 999,
            "training_metrics": {
                "local_date": "2026-10-04",
                "distance_m": 1000,
                "moving_s": 120,
                "elevation_gain_m": 30,
            },
        }
    ]
    result = aggregate_training_weeks(rides, end_date=date(2026, 10, 8), weeks=2)
    assert result[0] == {
        "week_start": "2026-09-28",
        "distance_m": 1000,
        "duration_s": 120,
        "climb_m": 30,
        "partial": False,
    }
    assert result[1]["distance_m"] == 0


@pytest.mark.asyncio
async def test_automatic_replay_is_bounded_and_reports_only_failed_ids_and_classes():
    repo = AsyncMock()
    repo.claim_training_replay.return_value = [
        {
            "id": "bad",
            "processing_status": "completed",
            "user_id": "u",
            "started_at": "2026-10-01",
            "raw_file_path": "private",
        },
        {
            "id": "missing",
            "processing_status": "completed",
            "user_id": "u",
            "started_at": "2026-10-02",
            "raw_file_path": None,
        },
    ]
    result = await replay_training_batch(
        repo, limit=2, parse=AsyncMock(side_effect=ValueError("private file content"))
    )
    repo.claim_training_replay.assert_awaited_once_with(2)
    assert result["errors"] == [
        {"ride_id": "bad", "error_class": "ValueError"},
        {"ride_id": "missing", "error_class": "missing_original"},
    ]
    assert repo.finish_training_replay.await_count == 2


def test_unknown_ride_zone_never_invents_a_daily_or_weekly_total():
    from app.services.riding_days import aggregate_riding_days, aggregate_training_weeks

    rides = [
        {
            "started_at": "2026-10-08T01:00:00Z",
            "processing_status": "completed",
            "training_metrics": {
                "local_date": None,
                "moving_s": 100,
                "distance_m": 1000,
                "elevation_gain_m": 20,
            },
        }
    ]
    assert (
        aggregate_riding_days(
            rides, start_date=date(2026, 10, 1), end_date=date(2026, 10, 8)
        )
        == []
    )
    weeks = aggregate_training_weeks(rides, end_date=date(2026, 10, 8))
    assert weeks[-1]["partial"] and weeks[-1]["distance_m"] is None
    assert all(not r["partial"] for r in weeks[:-1])


def test_daily_read_totals_share_frozen_date_and_do_not_turn_missing_into_zero():
    from app.services.riding_days import aggregate_riding_days

    rides = [
        {
            "started_at": "2026-10-08T01:00:00Z",
            "processing_status": "completed",
            "training_metrics": {
                "local_date": "2026-10-07",
                "moving_s": None,
                "distance_m": 1234,
                "elevation_gain_m": 22,
            },
        }
    ]
    result = aggregate_riding_days(
        rides, start_date=date(2026, 10, 1), end_date=date(2026, 10, 8)
    )
    assert result == [
        {
            "date": "2026-10-07",
            "moving_s": None,
            "distance_m": 1234,
            "elevation_gain_m": 22,
            "ride_count": 1,
        }
    ]


def test_estimate_marker_expires_when_no_displayed_value_depends_on_old_estimate():
    rides = [
        {
            "id": "old",
            "processing_status": "completed",
            "started_at": "2020-01-01",
            "training_metrics": {"load": 100, "load_estimate": True},
        }
    ]
    result = FitnessAnalyticsService.threshold_training_snapshot(
        rides,
        threshold_w=0,
        threshold={"threshold_version": "training.v2"},
        start_date=date(2026, 10, 1),
        target_date=date(2026, 10, 8),
    )
    assert result["estimate"] is False


@pytest.mark.asyncio
async def test_mixed_batch_keeps_good_ride_when_one_date_is_absent(monkeypatch):
    from app.services.training_backfill import backfill_training, TrainingMetricsService

    async def score(self, **kwargs):
        if kwargs["ride_id"] == "undated":
            raise ValueError("invalid date")
        return {"load": 10}

    monkeypatch.setattr(TrainingMetricsService, "score", score)
    rides = [
        {"id": "undated", "user_id": "u", "processing_status": "completed", "started_at": None, "raw_file_path": "a"},
        {
            "id": "dated",
            "processing_status": "completed",
            "user_id": "u",
            "started_at": "2026-10-08",
            "raw_file_path": "b",
        },
    ]
    result = await backfill_training(AsyncMock(), rides, AsyncMock(), apply=True)
    assert result["scored"] == 1
    assert result["errors"] == [{"ride_id": "undated", "error_class": "ValueError"}]
