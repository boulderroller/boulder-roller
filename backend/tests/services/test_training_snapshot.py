from __future__ import annotations

from datetime import date, timedelta

from app.services.fitness_analytics import FitnessAnalyticsService

TARGET = date(2026, 9, 24)
THRESHOLD = {
    "threshold_state": "established",
    "threshold_training_state": None,
    "threshold_version": "sealed:250:2026-08-17T12:00:00+00:00",
}


def _ride(day: date, *, status: str = "completed", ride_id: str | None = None) -> dict:
    return {
        "id": ride_id or f"ride-{day.isoformat()}",
        "started_at": f"{day.isoformat()}T12:00:00+00:00",
        "processing_status": status,
        "duration_sec": 3600,
        "normalized_power_duration_s": 3600,
        "normalized_power_raw_w": 200,
        "threshold_training_kind": "sealed",
        "tss": 999,
        "training_metrics": {"engine_version":2,"load":64,"load_estimate":False},
    }


def _history(days: int) -> list[dict]:
    return [_ride(TARGET - timedelta(days=offset)) for offset in range(0, days, 3)]


def _snapshot(rides: list[dict], *, window_days: int = 28) -> dict:
    return FitnessAnalyticsService.threshold_training_snapshot(
        rides,
        threshold_w=250,
        threshold=THRESHOLD,
        start_date=TARGET - timedelta(days=window_days),
        target_date=TARGET,
    )


def test_snapshot_binds_model_and_visible_loads_to_one_read() -> None:
    rides = _history(90)
    snapshot = _snapshot(rides)

    assert snapshot["initialization"] == "initialized"
    assert snapshot["as_of"] == "2026-09-24T23:59:59.999999+00:00"
    assert snapshot["coverage"] == {
        "completeness": "complete",
        "population": "30 rides",
        "observed_count": 30,
        "expected_count": 30,
        "pending_count": 0,
        "unavailable_count": 0,
    }
    assert snapshot["fitness_metrics"] == {
        **FitnessAnalyticsService.calculate_threshold_fitness_metrics(
            rides,
            threshold_w=250,
            target_date=TARGET,
        ),
        **THRESHOLD,
    }
    window_start = (TARGET - timedelta(days=28)).isoformat()
    loads = snapshot["training_load"]["daily_loads"]
    assert loads and all(row["date"] >= window_start for row in loads)
    assert snapshot["training_load"]["total_tss"] == sum(row["total_tss"] for row in loads)
    assert snapshot["training_load"]["threshold_version"] == THRESHOLD["threshold_version"]


def test_snapshot_revision_is_stable_and_moves_with_its_inputs() -> None:
    rides = _history(90)
    assert _snapshot(rides)["revision"] == _snapshot(list(rides))["revision"]
    added = rides + [_ride(TARGET, ride_id="second-ride-today")]
    assert _snapshot(added)["revision"] != _snapshot(rides)["revision"]


def test_short_history_is_still_initializing() -> None:
    snapshot = _snapshot(_history(30))
    assert snapshot["initialization"] == "initializing"


def test_ride_still_processing_is_outside_training_population() -> None:
    rides = _history(90) + [_ride(TARGET, status="processing", ride_id="in-flight")]
    rides[-1]["training_metrics"] = None
    coverage = _snapshot(rides)["coverage"]
    assert coverage["completeness"] == "complete"
    assert coverage["observed_count"] == 30
    assert coverage["expected_count"] == 30


def test_one_ride_reads_singular() -> None:
    snapshot = _snapshot([_ride(TARGET - timedelta(days=50))])
    assert snapshot["coverage"]["population"] == "1 ride"
