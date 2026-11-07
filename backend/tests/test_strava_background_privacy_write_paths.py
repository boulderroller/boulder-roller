from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from app import tasks
from app.services.ride_privacy import PrivacySettingsUnavailable, RidePrivacyPolicy


@pytest.fixture(autouse=True)
def _enable_legacy_strava_sync_for_task_contracts(monkeypatch) -> None:
    monkeypatch.setattr(
        tasks,
        "load_strava_settings",
        lambda: SimpleNamespace(sync_enabled=True),
    )


class _FakeAsyncClient:
    def __init__(self, response: httpx.Response) -> None:
        self.response = response

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def get(self, *_args, **_kwargs) -> httpx.Response:
        return self.response


class _FakeRateLimiter:
    async def wait_for_capacity(self, **_kwargs) -> bool:
        return True

    def update_from_headers(self, _headers: dict) -> None:
        return None

    def seconds_until_15min_reset(self) -> int:
        return 60


def _privacy_policy() -> RidePrivacyPolicy:
    return RidePrivacyPolicy.from_values(
        visibility="public",
        map_visibility="hide_start_end",
        map_hide_start_m=200,
        map_hide_end_m=200,
    )


def _connection() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        wallet="wallet-1",
        access_token="access-token",
    )


def _diagnostics(activity_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        import_source="strava_stream_reconstructed_gpx",
        source_activity_id=str(activity_id),
        to_dict=lambda: {
            "import_source": "strava_stream_reconstructed_gpx",
            "source_activity_id": str(activity_id),
        },
    )


def _storage(events: list[str]) -> MagicMock:
    storage = MagicMock()
    storage.compute_file_hash.return_value = "hash-1"

    async def upload_file(**_kwargs):
        events.append("file_stored")
        return SimpleNamespace(
            path="rides/user-1/new.gpx",
            size_bytes=9,
            file_hash="hash-1",
        )

    storage.upload_ride_file = AsyncMock(side_effect=upload_file)
    return storage


def _ride_repository(events: list[str], policy: RidePrivacyPolicy) -> MagicMock:
    ride_repo = MagicMock()
    ride_repo.find_ride_by_import_identity = AsyncMock(return_value=None)
    ride_repo.find_ride_by_hash = AsyncMock(return_value=None)

    async def resolve_policy(*_args, **_kwargs):
        events.append("privacy_resolved")
        return policy

    ride_repo.resolve_ride_privacy_policy = AsyncMock(side_effect=resolve_policy)
    ride_repo.create_ride = AsyncMock()
    ride_repo.update_ride_status = AsyncMock()
    return ride_repo


def _user_repository() -> MagicMock:
    user_repo = MagicMock()
    user_repo.get_user_id = AsyncMock(return_value="user-1")
    user_repo.get_user_profile = AsyncMock(return_value={"weight_kg": 70, "ftp_w": 250})
    return user_repo


def test_celery_strava_webhook_resolves_privacy_before_storage() -> None:
    activity_id = 24680
    connection = _connection()
    strava = MagicMock()
    strava.get_connection_by_athlete_id.return_value = connection
    strava.ensure_valid_token = AsyncMock(return_value=connection)
    strava._get_imported_activity_ids.return_value = set()
    strava.download_activity_file_with_diagnostics = AsyncMock(
        return_value=(b"gpx-bytes", "gpx", _diagnostics(activity_id))
    )

    events: list[str] = []
    policy = _privacy_policy()
    storage = _storage(events)
    ride_repo = _ride_repository(events, policy)
    user_repo = _user_repository()
    enqueue = AsyncMock(return_value=SimpleNamespace(accepted=True, error=None))
    response = httpx.Response(
        200,
        json={"type": "Ride"},
        request=httpx.Request("GET", f"https://www.strava.com/api/v3/activities/{activity_id}"),
    )

    with (
        patch("app.services.strava_service.StravaService", return_value=strava),
        patch(
            "app.services.strava_rate_limiter.get_strava_rate_limiter",
            return_value=_FakeRateLimiter(),
        ),
        patch("app.services.file_storage.create_file_storage_service", return_value=storage),
        patch.object(tasks, "create_ride_repository", return_value=ride_repo),
        patch("app.repositories.create_user_repository", return_value=user_repo),
        patch.object(tasks, "enqueue_ride_ingest", new=enqueue),
        patch("httpx.AsyncClient", return_value=_FakeAsyncClient(response)),
        patch.object(tasks, "_update_queue_depth"),
    ):
        result = tasks.process_strava_webhook_event.run(
            object_type="activity",
            aspect_type="create",
            owner_id=987,
            object_id=activity_id,
        )

    assert result["action"] == "imported"
    assert events == ["privacy_resolved", "file_stored"]
    ride_repo.resolve_ride_privacy_policy.assert_awaited_once_with("user-1")
    assert ride_repo.create_ride.await_args.kwargs["privacy_policy"] is policy


def test_celery_strava_webhook_retries_without_storage_when_privacy_is_unavailable() -> None:
    activity_id = 13579
    connection = _connection()
    strava = MagicMock()
    strava.get_connection_by_athlete_id.return_value = connection
    strava.ensure_valid_token = AsyncMock(return_value=connection)
    strava._get_imported_activity_ids.return_value = set()
    strava.download_activity_file_with_diagnostics = AsyncMock(
        return_value=(b"gpx-bytes", "gpx", _diagnostics(activity_id))
    )

    events: list[str] = []
    storage = _storage(events)
    ride_repo = _ride_repository(events, _privacy_policy())
    ride_repo.resolve_ride_privacy_policy = AsyncMock(
        side_effect=PrivacySettingsUnavailable("database unavailable")
    )
    retry_signal = RuntimeError("privacy retry scheduled")
    response = httpx.Response(
        200,
        json={"type": "Ride"},
        request=httpx.Request("GET", f"https://www.strava.com/api/v3/activities/{activity_id}"),
    )

    with (
        patch("app.services.strava_service.StravaService", return_value=strava),
        patch(
            "app.services.strava_rate_limiter.get_strava_rate_limiter",
            return_value=_FakeRateLimiter(),
        ),
        patch("app.services.file_storage.create_file_storage_service", return_value=storage),
        patch.object(tasks, "create_ride_repository", return_value=ride_repo),
        patch("app.repositories.create_user_repository", return_value=_user_repository()),
        patch("httpx.AsyncClient", return_value=_FakeAsyncClient(response)),
        patch.object(tasks.process_strava_webhook_event, "retry", return_value=retry_signal) as retry,
        patch.object(tasks, "_update_queue_depth"),
    ):
        with pytest.raises(RuntimeError, match="privacy retry scheduled"):
            tasks.process_strava_webhook_event.run(
                object_type="activity",
                aspect_type="create",
                owner_id=987,
                object_id=activity_id,
            )

    strava.download_activity_file_with_diagnostics.assert_not_awaited()
    storage.upload_ride_file.assert_not_awaited()
    ride_repo.create_ride.assert_not_awaited()
    retry.assert_called_once()


def _backfill_strava(activity_id: int, connection: SimpleNamespace) -> MagicMock:
    strava = MagicMock()
    query = MagicMock()
    query.select.return_value.eq.return_value.limit.return_value.execute.return_value = SimpleNamespace(
        data=[{
            "id": str(connection.id),
            "is_active": True,
            "backfill_cursor": 1,
            "total_activities_synced": 0,
        }]
    )
    query.update.return_value.eq.return_value.execute.return_value = SimpleNamespace(data=[])
    strava.db.table.return_value = query
    strava._row_to_connection.return_value = connection
    strava.ensure_valid_token = AsyncMock(return_value=connection)
    strava._get_imported_activity_ids.return_value = set()
    strava.download_activity_file_with_diagnostics = AsyncMock(
        return_value=(b"gpx-bytes", "gpx", _diagnostics(activity_id))
    )
    return strava


def test_celery_strava_backfill_resolves_privacy_before_storage() -> None:
    activity_id = 11223
    connection = _connection()
    strava = _backfill_strava(activity_id, connection)
    events: list[str] = []
    policy = _privacy_policy()
    storage = _storage(events)
    ride_repo = _ride_repository(events, policy)
    response = httpx.Response(
        200,
        json=[{"id": activity_id, "type": "Ride"}],
        request=httpx.Request("GET", "https://www.strava.com/api/v3/athlete/activities"),
    )

    with (
        patch("app.services.strava_service.StravaService", return_value=strava),
        patch(
            "app.services.strava_rate_limiter.get_strava_rate_limiter",
            return_value=_FakeRateLimiter(),
        ),
        patch("app.services.file_storage.create_file_storage_service", return_value=storage),
        patch.object(tasks, "create_ride_repository", return_value=ride_repo),
        patch("app.repositories.create_user_repository", return_value=_user_repository()),
        patch.object(
            tasks,
            "enqueue_ride_ingest",
            new=AsyncMock(return_value=SimpleNamespace(accepted=True, error=None)),
        ),
        patch("httpx.AsyncClient", return_value=_FakeAsyncClient(response)),
        patch.object(tasks, "_update_queue_depth"),
    ):
        result = tasks.backfill_strava_history.run(connection_id=str(connection.id))

    assert result["status"] == "complete"
    assert result["imported"] == 1
    assert events == ["privacy_resolved", "file_stored"]
    ride_repo.resolve_ride_privacy_policy.assert_awaited_once_with("user-1")
    assert ride_repo.create_ride.await_args.kwargs["privacy_policy"] is policy


def test_celery_strava_backfill_retries_without_storage_when_privacy_is_unavailable() -> None:
    activity_id = 44556
    connection = _connection()
    strava = _backfill_strava(activity_id, connection)
    events: list[str] = []
    storage = _storage(events)
    ride_repo = _ride_repository(events, _privacy_policy())
    ride_repo.resolve_ride_privacy_policy = AsyncMock(
        side_effect=PrivacySettingsUnavailable("database unavailable")
    )
    retry_signal = RuntimeError("privacy retry scheduled")
    response = httpx.Response(
        200,
        json=[{"id": activity_id, "type": "Ride"}],
        request=httpx.Request("GET", "https://www.strava.com/api/v3/athlete/activities"),
    )

    with (
        patch("app.services.strava_service.StravaService", return_value=strava),
        patch(
            "app.services.strava_rate_limiter.get_strava_rate_limiter",
            return_value=_FakeRateLimiter(),
        ),
        patch("app.services.file_storage.create_file_storage_service", return_value=storage),
        patch.object(tasks, "create_ride_repository", return_value=ride_repo),
        patch("app.repositories.create_user_repository", return_value=_user_repository()),
        patch("httpx.AsyncClient", return_value=_FakeAsyncClient(response)),
        patch.object(tasks.backfill_strava_history, "retry", return_value=retry_signal) as retry,
        patch.object(tasks, "_update_queue_depth"),
    ):
        with pytest.raises(RuntimeError, match="privacy retry scheduled"):
            tasks.backfill_strava_history.run(connection_id=str(connection.id))

    strava.download_activity_file_with_diagnostics.assert_not_awaited()
    storage.upload_ride_file.assert_not_awaited()
    ride_repo.create_ride.assert_not_awaited()
    retry.assert_called_once()
