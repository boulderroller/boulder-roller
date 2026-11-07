from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from backend.tests.routes.test_training_routes_round2 import training_client
from app.routes import analytics


@pytest.mark.parametrize(
    "query,basis",
    [
        ("?timezone=America/New_York", "client"),
        ("", "outdoor_ride"),
    ],
)
def test_evening_owner_today_preserves_fatigue_form_and_streak(
    training_client, monkeypatch, query, basis
):
    client, repo = training_client

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 8, 0, 30, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(analytics, "datetime", Clock)
    repo.training_settings.return_value = {}
    repo.current_training_threshold = AsyncMock(return_value=None)
    repo.list_threshold_training_rides = AsyncMock(
        return_value=[
            {
                "id": "ios",
                "started_at": "2026-10-07T23:00:00Z",
                "processing_status": "completed",
                "training_metrics": {
                    "local_date": "2026-10-07",
                    "timezone": "America/New_York",
                    "timezone_basis": "start_position",
                    "load": 80,
                    "moving_s": 1800,
                },
            }
        ]
    )
    snapshot = client.get("/analytics/training-load" + query).json()["snapshot"]
    assert snapshot["as_of"].startswith("2026-10-07")
    assert snapshot["fitness_metrics"]["atl"] == 11
    assert snapshot["fitness_metrics"]["tsb"] == -9
    assert snapshot["clock"]["basis"] == basis
    days = client.get("/analytics/riding-days" + query).json()
    assert days["endDate"] == days["days"][-1]["date"] == "2026-10-07"
    assert days["days"][-1]["ride_count"] == 1  # heatmap's current-streak day
    # The client changes the as-of clock only, not this ride's frozen date.
    travel = client.get("/analytics/training-load?timezone=Asia/Tokyo").json()[
        "snapshot"
    ]
    assert travel["training_load"]["daily_loads"][0]["date"] == "2026-10-07"


def test_clock_priority_and_explicit_utc_fallback(training_client):
    client, repo = training_client
    repo.current_training_threshold = AsyncMock(return_value=None)
    repo.list_threshold_training_rides = AsyncMock(return_value=[])
    result = client.get("/analytics/training-load?timezone=Asia/Tokyo").json()[
        "snapshot"
    ]
    assert result["timezone"] == "America/New_York"
    assert result["clock"] == {"basis": "rider", "fallback": False}
    repo.training_settings.return_value = {}
    repo.list_threshold_training_rides.return_value = [
        {
            "id": "virtual",
            "started_at": "2026-10-07T23:00:00Z",
            "processing_status": "completed",
            "training_metrics": {
                "local_date": "2026-10-07",
                "timezone": None,
                "utc_offset_s": -14400,
                "timezone_basis": "device",
                "load": 80,
            },
        }
    ]
    result = client.get("/analytics/training-load").json()["snapshot"]
    assert result["timezone"] == "UTC"
    assert result["clock"] == {"basis": "utc_fallback", "fallback": True}
    assert client.get("/analytics/weeks?timezone=not-a-zone").status_code == 422


def test_owner_today_keeps_inferred_timezone_and_marks_its_basis(training_client):
    client, repo = training_client
    repo.training_settings.return_value = {
        "timezone": "America/New_York",
        "timezone_source": "inferred",
    }
    repo.current_training_threshold = AsyncMock(return_value=None)
    repo.list_threshold_training_rides = AsyncMock(return_value=[])
    snapshot = client.get("/analytics/training-load?timezone=UTC").json()["snapshot"]
    assert snapshot["timezone"] == "America/New_York"
    assert snapshot["clock"] == {"basis": "inferred", "fallback": False}
