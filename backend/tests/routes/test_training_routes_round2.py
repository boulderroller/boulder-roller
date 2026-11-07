from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.routes import rides, analytics
from app.dependencies import (
    AuthenticatedUser,
    get_current_user,
    get_repository,
    get_ride_repository,
    get_optional_current_user,
    get_fitness_repository,
)


@pytest.fixture
def training_client(monkeypatch):
    repo = MagicMock()
    repo.get_ride = AsyncMock(
        return_value={
            "id": "r",
            "user_id": "u",
            "raw_file_path": "r.gpx",
            "file_type": "gpx",
            "training_inputs": {"started_at": "2026-10-08T01:00:00Z"},
            "processing_status": "completed",
            "training_metrics": {"load": 81},
        }
    )
    repo.training_settings = AsyncMock(
        return_value={"timezone": "America/New_York", "resting_hr_bpm": 50}
    )
    repo.append_training_settings = AsyncMock(
        side_effect=lambda user, settings: {
            **repo.training_settings.return_value,
            **settings,
        }
    )
    user = AuthenticatedUser(user_id="u", wallet="w", device_id="d")
    app = FastAPI()
    app.include_router(rides.router, prefix="/rides")
    app.include_router(analytics.router, prefix="/analytics")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_optional_current_user] = lambda: user
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_ride_repository] = lambda: repo
    app.dependency_overrides[get_fitness_repository] = lambda: MagicMock()
    from app.middleware.rate_limiter import rate_limiter

    rate_limiter.reset_fallback()
    return TestClient(app), repo


def test_span_owner_access_validation_and_parse_cache(training_client, monkeypatch):
    client, repo = training_client
    from app.services.file_storage import FileStorageService
    from app.services import workout_parse_adapter, training_metrics

    download = AsyncMock(return_value=b"synthetic")
    monkeypatch.setattr(FileStorageService, "__init__", lambda self: None)
    monkeypatch.setattr(FileStorageService, "download_ride_file", download)
    parse = MagicMock(
        return_value=MagicMock(_native_activity=MagicMock(time_ms=[0, 1]))
    )
    from app.services.training_activity_cache import _entries

    _entries.clear()
    monkeypatch.setattr(workout_parse_adapter, "parse_ride_file_bytes_rust", parse)
    monkeypatch.setattr(
        training_metrics,
        "compute",
        lambda activity, inputs, **kw: {"moving_s": 42, **kw},
    )
    assert client.get("/rides/r/training?start_s=0").status_code == 422
    assert client.get("/rides/r/training?start_s=20&end_s=10").status_code == 422
    assert client.get("/rides/r/training?start_s=0&end_s=60").json()["moving_s"] == 42
    assert client.get("/rides/r/training?start_s=10&end_s=60").status_code == 200
    assert download.await_count == parse.call_count == 1
    repo.get_ride.return_value["user_id"] = "other"
    assert client.get("/rides/r/training?start_s=0&end_s=60").status_code in (403, 404)
    assert download.await_count == 1  # cache never bypasses authorization


@pytest.mark.parametrize("span", ["", "?start_s=0&end_s=60"])
def test_ineligible_whole_and_span_training_are_absent(training_client, monkeypatch, span):
    from app.services import training_activity_cache

    client, repo = training_client
    repo.get_ride.return_value["processing_status"] = "failed"
    parse = AsyncMock(return_value=MagicMock())
    monkeypatch.setattr(training_activity_cache, "activity_for_span", parse)
    response = client.get("/rides/r/training" + span)
    assert response.status_code == 200 and response.json() is None
    parse.assert_not_awaited()


def test_partial_settings_preserve_rider_values(training_client):
    client, repo = training_client
    result = client.put("/analytics/settings", json={"max_hr_bpm": 190})
    assert result.status_code == 200
    assert result.json() == {
        "max_hr_bpm": 190,
        "resting_hr_bpm": 50,
        "timezone": "America/New_York",
    }


def test_conflicting_partial_settings_are_rejected_as_client_error(training_client):
    client, repo = training_client
    repo.training_settings.return_value = {
        "threshold_hr_bpm": 180,
        "resting_hr_bpm": 60,
    }
    result = client.put("/analytics/settings", json={"max_hr_bpm": 170})
    assert result.status_code == 422
    repo.append_training_settings.assert_not_awaited()


def test_default_analytics_timezone_uses_frozen_ride_day_and_curve_ladder(
    training_client,
):
    client, repo = training_client
    repo.list_threshold_training_rides = AsyncMock(
        return_value=[
            {
                "id": "r",
                "started_at": "2026-10-08T01:00:00Z",
                "processing_status": "completed",
                "training_metrics": {
                    "load": 81,
                    "local_date": "2026-10-07",
                    "timezone": "America/New_York",
                    "moving_s": 3200,
                    "power_curve_s": [5, 7200],
                    "power_curve_w": [300, 180],
                },
            }
        ]
    )
    repo.current_training_threshold = AsyncMock(return_value=None)
    result = client.get("/analytics/training-load?days=365").json()
    travel = client.get("/analytics/training-load?days=365&timezone=Asia/Tokyo").json()
    assert (
        result["daily_loads"]
        == travel["daily_loads"]
        == [
            {
                "date": "2026-10-07",
                "total_tss": 81,
                "estimate": False,
                "basis": "stored_ride_loads",
            }
        ]
    )
    assert result["snapshot"]["timezone"] == "America/New_York"
    curve = client.get("/analytics/power-curve").json()
    assert curve["durationsS"] == [5, 7200] and curve["bestW"] == [300, 180]


@pytest.mark.parametrize("status", ["failed", "uploading", "queued", "processing", "recovery_pending"])
def test_every_training_endpoint_ignores_ineligible_stored_metrics(training_client, status):
    client, repo = training_client
    repo.list_threshold_training_rides = AsyncMock(return_value=[{
        "id": "excluded", "processing_status": status,
        "started_at": "2026-10-07T12:00:00Z",
        "training_metrics": {"engine_version": 2, "load": 100, "local_date": "2026-10-07",
                             "moving_s": 3600, "distance_m": 20000, "elevation_gain_m": 300,
                             "power_curve_s": [180], "power_curve_w": [400]},
    }])
    repo.current_training_threshold = AsyncMock(return_value=None)
    fitness = client.get("/analytics/fitness").json()
    assert fitness["ctl"] is None and fitness["atl"] is None and fitness["tsb"] is None
    load = client.get("/analytics/training-load").json()
    assert load["total_tss"] == 0 and load["snapshot"]["coverage"]["expected_count"] == 0
    assert client.get("/analytics/riding-days").json()["days"] == []
    assert all(w["distance_m"] == 0 and not w["partial"] for w in client.get("/analytics/weeks").json())
    curve = client.get("/analytics/power-curve").json()
    assert curve["rideCount"] == 0 and curve["bestW"] == []


def test_today_uses_rider_clock_even_after_a_virtual_or_travelling_ride(
    training_client, monkeypatch
):
    client, repo = training_client

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 8, 14, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(analytics, "datetime", Clock)
    repo.list_threshold_training_rides = AsyncMock(
        return_value=[
            {
                "id": "r",
                "started_at": "2026-10-07T23:00:00Z",
                "processing_status": "completed",
                "training_metrics": {
                    "timezone": "Pacific/Guadalcanal",
                    "local_date": "2026-10-07",
                    "load": 50,
                },
            }
        ]
    )
    repo.current_training_threshold = AsyncMock(return_value=None)
    result = client.get("/analytics/training-load").json()["snapshot"]
    assert result["as_of"].startswith("2026-10-08")
    assert result["timezone"] == "America/New_York"
    assert client.get("/analytics/riding-days").json()["endDate"] == "2026-10-08"

    repo.training_settings.return_value = {}
    metrics = repo.list_threshold_training_rides.return_value[0]["training_metrics"]
    metrics.update(timezone=None, utc_offset_s=-14400, timezone_basis="device")
    result = client.get("/analytics/training-load").json()["snapshot"]
    assert result['clock'] == {'basis': 'utc_fallback', 'fallback': True}


@pytest.mark.parametrize("status,power,watts_per_kg", [("completed", 200, 2.5), ("failed", 999, 99)])
def test_patterns_use_eligible_stored_engine_span_values(training_client, monkeypatch, status, power, watts_per_kg):
    from types import SimpleNamespace

    client, repo = training_client
    monkeypatch.setattr(rides, "check_ride_access", AsyncMock())
    # The fixture viewer "u" owns ride "r"; W/kg is owner-only (pvrwy).
    monkeypatch.setattr(
        rides,
        "resolve_ride_visibility",
        AsyncMock(return_value=SimpleNamespace(redact_gps=False, is_owner=True)),
    )
    monkeypatch.setattr(rides, "_fetch_pattern_vault_matches", lambda *args: {})
    repo.get_user_by_id = AsyncMock(return_value={"id": "u", "account_state": "active"})
    monkeypatch.setattr(rides, "ClimbEffortRepository", lambda _: SimpleNamespace(
        get_efforts=AsyncMock(return_value=[]), recorded_power_rides=AsyncMock(return_value=set()),
    ))
    repo.get_ride.return_value["training_metrics"] = {
        "climbs": {"climb": {"avg_power_w": 200, "w_per_kg": 2.5, "basis": "training_engine_span"}}
    }
    repo.get_ride.return_value["processing_status"] = status
    repo.get_patterns_for_activity = AsyncMock(
        return_value={
            "climb_patterns": [
                {
                    "id": "climb",
                    "detector_version": "canon_traversal_v1",
                    "distance_m": 4321,
                    "avg_gradient_pct": 7.4,
                    "avg_power_w": 999,
                    "w_per_kg": 99,
                    "time_s": 600,
                    "vert_m": 300,
                    "start_offset_s": 0,
                    "end_offset_s": 600,
                }
            ]
        }
    )
    row = client.get("/rides/r/patterns").json()["patterns"]["climb_patterns"][0]
    assert (
        row["avg_power_w"] == power and row["w_per_kg"] == watts_per_kg and row["category"] == "3"
    )


@pytest.mark.asyncio
async def test_feed_and_search_fetch_and_display_one_public_projection(monkeypatch):
    from types import SimpleNamespace
    from app.routes import feed, search
    from app.repositories_legacy import SupabaseRepository

    assert "training_metrics" in SupabaseRepository._GLOBAL_RIDE_FEED_SELECTION.split(
        ", "
    )
    row = {
        "id": "r",
        "user_id": "u",
        "file_name": "Morning.fit",
        "started_at": "2026-10-07T12:00:00Z",
        "processing_status": "completed",
        "distance_m": 999,
        "training_metrics": {
            "distance_m": 12345,
            "elapsed_s": 1200,
            "elevation_gain_m": 234,
            "max_hr_bpm": 199,
            "physiology": {"private": True},
        },
    }
    query = MagicMock()
    for method in ("select", "ilike", "order", "limit"):
        getattr(query, method).return_value = query
    query.execute.return_value.data = [row]
    repo = SimpleNamespace(
        client=SimpleNamespace(from_=lambda table: query),
        get_users_by_ids=AsyncMock(return_value=[]),
    )
    selected = await search._search_ride_rows(repo, "Morning", 5, None)
    assert "training_metrics" in query.select.call_args.args[0]
    monkeypatch.setattr(
        feed, "_route_preview_points_for_feed", AsyncMock(return_value=None)
    )
    projected = await feed._ride_for_feed_event(
        selected[0], {"isOwner": False}, repo, media=[]
    )
    assert (
        projected["distance_m"] == 12345
        and "max_hr_bpm" not in projected["training_metrics"]
    )
    monkeypatch.setattr(
        search,
        "resolve_ride_visibility",
        AsyncMock(
            return_value=SimpleNamespace(
                can_view=True,
                to_client_dict=lambda: {"canView": True, "isOwner": False},
            )
        ),
    )
    monkeypatch.setattr(search, "_public_search_actor", AsyncMock(return_value=None))
    results = await search._build_ride_results(selected, "Morning", None, repo)
    stats = {stat["label"]: stat["value"] for stat in results[0]["stats"]}
    assert stats["Distance"] == "12.3 km"
    assert stats["Time"] == "20m"
