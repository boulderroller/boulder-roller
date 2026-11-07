"""Synthetic native -> frozen inputs -> stored reads and replay integration."""

import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
import workout_parse as wp

from app.services.training_metrics import (
    compute,
    physiology,
    project_training,
    TrainingMetricsService,
)
from app.services.training_backfill import backfill_training
from app.services.fitness_analytics import training_date
from app.services.climb_read_metrics import climb_category

spec = importlib.util.spec_from_file_location(
    "synthetic_training_vectors",
    Path(__file__).resolve().parents[3] / "workout-parse/tests/test_training.py",
)
vectors = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vectors)


class Repo:
    def __init__(self):
        self.inputs = {}
        self.metrics = {}
        self.calls = []

    async def bind_training_inputs(self, ride, user, started, evidence):
        self.calls.append(ride)
        return self.inputs.setdefault(
            ride,
            {
                "started_at": started.isoformat(),
                "threshold": {
                    "value": 250,
                    "estimate": True,
                    "basis": "threshold_cp_3_7_15_v1",
                },
                "settings": {"timezone": "America/New_York"},
                **evidence,
                "observed_max_hr_bpm": evidence.get("max_hr_bpm"),
            },
        )

    async def training_climb_patterns(self, ride):
        return []

    async def finish_training_replay(self, ride, user, error_class=None, *, scoring_inputs=None):
        pass

    async def store_training_metrics(self, ride, user, inputs, metrics, evidence):
        self.metrics[ride] = metrics
        return metrics


def parsed(power=True):
    activity = vectors.synthetic_activity(
        list(range(1800)), [200 if power else None] * 1800, [5] * 1800, [160] * 1800
    )
    return SimpleNamespace(
        _native_activity=activity,
        started_at=datetime(2026, 10, 8, 1, tzinfo=timezone.utc),
    )


def test_device_clock_survives_inferred_timezone_in_stored_metrics():
    inputs = {
        "started_at": "2026-10-08T01:00:00Z",
        "timezone": None,
        "utc_offset_s": -14400,
        "timezone_basis": "device",
        "local_date": "2026-10-07",
        "settings": {"timezone": "UTC", "timezone_source": "inferred"},
    }
    metrics = compute(parsed()._native_activity, inputs)
    assert metrics["timezone"] is None
    assert metrics["utc_offset_s"] == -14400
    assert metrics["timezone_basis"] == "device"
    assert metrics["local_date"] == "2026-10-07"


@pytest.mark.asyncio
async def test_native_score_uses_frozen_inputs_and_private_projection():
    repo = Repo()
    ride = parsed()
    before = wp.compute_metrics(ride._native_activity, 250).tss
    score = await TrainingMetricsService(repo).score(
        ride_id="r", user_id="u", parsed_ride=ride
    )
    assert score["load"] == 32
    assert score["local_date"] == "2026-10-07"
    assert score["estimates"]["load"]["estimate"] is True
    assert score["physiology"]["threshold_hr"]["basis"] == "95_percent_best_20m_hr"
    assert score["power_zone_ranges_w"][:2] == [[0, 137], [138, 187]]
    assert wp.compute_metrics(ride._native_activity, 250).tss == before
    raw = {
        "processing_status": "completed",
        "tss": 900,
        "duration_sec": 999,
        "economic_tss": before,
        "training_inputs": repo.inputs["r"],
        "training_evidence": {"private": True},
        "training_metrics": score,
    }
    owner = project_training(raw, owner=True)
    public = project_training(raw, owner=False)
    assert (
        owner["tss"] == 32 and owner["duration_sec"] == public["duration_sec"] == 1799
    )
    assert owner["economic_tss"] == before
    assert public["tss"] is None
    for key in ("threshold", "physiology", "load"):
        assert key not in public["training_metrics"]
    assert "training_inputs" not in owner and "training_evidence" not in public
    assert public["training_metrics"]["estimates"]["calories"]["estimate"] is True


@pytest.mark.asyncio
async def test_hr_only_score_and_unavailable_hr_are_explicit():
    repo = Repo()
    ride = parsed(False)
    score = await TrainingMetricsService(repo).score(
        ride_id="r", user_id="u", parsed_ride=ride
    )
    assert score["load"] > 0 and score["load_basis"] == "hrss"
    assert score["estimates"]["load"]["estimate"] is True
    assert score["physiology"]["resting_hr"]["basis"] == "intervals_default_60"
    assert physiology({})["max_hr"] is None
    assert (
        physiology(
            {
                "settings": {
                    "threshold_hr_bpm": 170,
                    "resting_hr_bpm": 50,
                    "max_hr_bpm": 195,
                }
            }
        )["threshold_hr"]["estimate"]
        is False
    )


@pytest.mark.asyncio
async def test_backfill_orders_skips_retries_and_preserves_inputs():
    repo = Repo()
    parse = AsyncMock(return_value=parsed())
    rides = [
        {
            "id": str(n),
            "user_id": "u",
            "started_at": f"2026-10-0{n}T12:00:00Z",
            "raw_file_path": "synthetic",
            "processing_status": "completed",
        }
        for n in (2, 1)
    ]
    dry = await backfill_training(repo, rides, parse)
    assert dry["eligible"] == 2 and dry["scored"] == 0
    parse.assert_not_awaited()
    done = await backfill_training(repo, rides, parse, apply=True)
    assert done["scored"] == 2 and repo.calls == ["1", "2"]
    inputs = dict(repo.inputs)
    for r in rides:
        r["training_metrics"] = repo.metrics[r["id"]]
    again = await backfill_training(repo, rides, parse, apply=True)
    assert again["skipped"] == 2 and repo.calls == ["1", "2"]
    assert (await backfill_training(repo, rides, parse, apply=True, force=True))[
        "scored"
    ] == 2
    assert inputs == repo.inputs
    parse.side_effect = ValueError("bad original")
    assert (await backfill_training(repo, rides, parse, apply=True, force=True))[
        "failed"
    ] == 2
    assert (
        await backfill_training(
            repo,
            [{**rides[0], "training_metrics": None, "raw_file_path": None}],
            parse,
            apply=True,
        )
    )["unavailable"] == 1


def test_local_day_dst_invalid_dates_and_climb_integral():
    assert (
        str(
            training_date(
                {
                    "started_at": "2026-11-01T03:30:00Z",
                    "training_metrics": {"timezone": "America/New_York"},
                }
            )
        )
        == "2026-10-31"
    )
    assert (
        str(
            training_date(
                {
                    "started_at": "2026-11-01T06:30:00Z",
                    "training_metrics": {"timezone": "America/New_York"},
                }
            )
        )
        == "2026-11-01"
    )
    with pytest.raises(ValueError):
        training_date({"started_at": "bad"}, "UTC")
    assert [
        climb_category(n, 1) for n in (8000, 8001, 16000, 16001, 32001, 64001, 80001)
    ] == [None, "4", "4", "3", "2", "1", "HC"]


def test_historical_climb_replay_retains_original_mass_and_never_guesses_it():
    from app.services.climb_read_metrics import retained_climb_reads

    activity = vectors.synthetic_activity([0, 2, 10], [100, 300, 100], [5, 5, 5])
    patterns = [
        {
            "id": "p",
            "start_offset_s": 0,
            "end_offset_s": 10,
            "avg_power_w": 500,
            "w_per_kg": 5,
        },
        {
            "id": "unknown",
            "start_offset_s": 0,
            "end_offset_s": 10,
            "avg_power_w": None,
            "w_per_kg": None,
        },
    ]
    reads = retained_climb_reads(activity, patterns)
    expected = wp.compute_training_metrics(
        activity, 0, engine_version=2, start_s=0, end_s=10
    ).avg_power_w
    assert reads["p"]["avg_power_w"] == expected
    assert reads["p"]["w_per_kg"] == expected / 100
    assert reads["unknown"]["w_per_kg"] is None
    assert patterns[0]["avg_power_w"] == 500


def test_missing_training_fact_never_erases_retained_ride_fact():
    from app.services.training_metrics import project_training

    ride = {
        "processing_status": "completed",
        "distance_m": 1000,
        "avg_hr_bpm": 120,
        "training_metrics": {
            "engine_version": 2,
            "distance_m": None,
            "avg_hr_bpm": None,
        },
    }
    for owner in (True, False):
        projected = project_training(ride, owner=owner)
        assert projected["distance_m"] == 1000
        assert projected["avg_hr_bpm"] == 120
