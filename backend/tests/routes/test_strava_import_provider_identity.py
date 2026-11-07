from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.dependencies import AuthenticatedUser
from app.routes.strava import StravaError, import_activities
from app.schemas import StravaImportRequest
from app.services.ride_privacy import PrivacySettingsUnavailable, RidePrivacyPolicy
from app.services.ride_ingest import RideIngestEnqueueResult


@pytest.fixture(autouse=True)
def _enable_legacy_strava_sync_for_import_contracts(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.routes.strava.load_strava_settings",
        lambda: SimpleNamespace(sync_enabled=True),
    )


def _user() -> AuthenticatedUser:
    return AuthenticatedUser(wallet="wallet-1", user_id="user-1", device_id="device-1")


def _privacy_policy(
    *,
    visibility: str = "followers",
    map_visibility: str = "show_all",
    map_hide_start_m: int = 0,
    map_hide_end_m: int = 0,
) -> RidePrivacyPolicy:
    return RidePrivacyPolicy.from_values(
        visibility=visibility,
        map_visibility=map_visibility,
        map_hide_start_m=map_hide_start_m,
        map_hide_end_m=map_hide_end_m,
    )


@pytest.mark.asyncio
async def test_import_activities_requeues_existing_pending_provider_ride_before_download() -> None:
    activity_id = 12345
    ride_id = uuid4()
    connection_id = uuid4()
    strava = MagicMock()
    strava.get_connection.return_value = SimpleNamespace(id=connection_id)
    strava.download_activity_file_with_diagnostics = AsyncMock()

    ride_repo = MagicMock()
    ride_repo.find_ride_by_import_identity = AsyncMock(
        return_value={
            "id": str(ride_id),
            "processing_status": "pending",
            "raw_file_path": "rides/user-1/ride.gpx",
            "file_type": "gpx",
        }
    )
    ride_repo.get_ride = AsyncMock(
        return_value={
            "id": str(ride_id),
            "processing_status": "pending",
            "raw_file_path": "rides/user-1/ride.gpx",
            "file_type": "gpx",
        }
    )
    policy = _privacy_policy(visibility="private", map_visibility="hide_entire")
    ride_repo.get_ride.return_value.update(policy.to_storage_dict())
    events: list[str] = []

    async def resolve_policy(*_args, **_kwargs):
        events.append("privacy_resolved")
        return policy

    async def update_metadata(*_args, **_kwargs):
        events.append("privacy_persisted")

    ride_repo.resolve_ride_privacy_policy = AsyncMock(side_effect=resolve_policy)
    ride_repo.update_ride_metadata = AsyncMock(side_effect=update_metadata)
    ride_repo.update_ride_status = AsyncMock()
    ride_repo.find_ride_by_hash = AsyncMock()

    user_repo = MagicMock()
    user_repo.get_user_profile = AsyncMock(return_value={"weight_kg": 70, "ftp_w": 250})

    async def enqueue_after_privacy(_job):
        events.append("queued")
        return RideIngestEnqueueResult(accepted=True, backend="nats")

    with (
        patch("app.routes.strava.create_file_storage_service", return_value=MagicMock()),
        patch(
            "app.services.provider_imports.enqueue_ride_ingest",
            new=AsyncMock(side_effect=enqueue_after_privacy),
        ) as enqueue_mock,
    ):
        response = await import_activities(
            request=MagicMock(),
            payload=StravaImportRequest(
                activity_ids=[activity_id],
                visibility="private",
                map_visibility="hide_entire",
                map_hide_start_m=0,
                map_hide_end_m=0,
            ),
            user=_user(),
            strava=strava,
            ride_repo=ride_repo,
            user_repo=user_repo,
        )

    assert response.imported_count == 1
    assert response.failed_count == 0
    assert response.results[0].success is True
    assert response.results[0].activity_id == ride_id
    strava.download_activity_file_with_diagnostics.assert_not_awaited()
    ride_repo.find_ride_by_hash.assert_not_awaited()
    assert events == ["privacy_resolved", "privacy_persisted", "queued"]
    ride_repo.resolve_ride_privacy_policy.assert_awaited_once_with(
        "user-1",
        visibility="private",
        map_visibility="hide_entire",
        map_hide_start_m=0,
        map_hide_end_m=0,
    )
    ride_repo.update_ride_metadata.assert_awaited_once_with(
        str(ride_id),
        policy.to_storage_dict(),
    )
    ride_repo.update_ride_status.assert_awaited_once_with(UUID(str(ride_id)), "processing")
    strava.mark_activity_imported.assert_called_once_with(
        connection_id=connection_id,
        strava_activity_id=activity_id,
        activity_id=str(ride_id),
    )
    enqueue_job = enqueue_mock.await_args.args[0]
    assert enqueue_job.ride_id == str(ride_id)
    assert enqueue_job.source == "strava_manual_import_retry"
    assert enqueue_job.source_id == str(activity_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("resolved_policy", [None, object()])
async def test_import_activities_blocks_pending_provider_retry_when_policy_is_malformed(
    resolved_policy: object,
) -> None:
    activity_id = 12346
    ride_id = uuid4()
    strava = MagicMock()
    strava.get_connection.return_value = SimpleNamespace(id=uuid4())
    strava.download_activity_file_with_diagnostics = AsyncMock()

    ride_repo = MagicMock()
    ride_repo.find_ride_by_import_identity = AsyncMock(
        return_value={
            "id": str(ride_id),
            "processing_status": "pending",
            "raw_file_path": "rides/user-1/ride.gpx",
            "file_type": "gpx",
        }
    )
    ride_repo.resolve_ride_privacy_policy = AsyncMock(return_value=resolved_policy)
    ride_repo.update_ride_metadata = AsyncMock()
    ride_repo.update_ride_status = AsyncMock()

    user_repo = MagicMock()
    user_repo.get_user_profile = AsyncMock(return_value={"weight_kg": 70, "ftp_w": 250})
    enqueue_mock = AsyncMock(
        return_value=RideIngestEnqueueResult(accepted=True, backend="nats")
    )

    with (
        patch("app.routes.strava.create_file_storage_service", return_value=MagicMock()),
        patch("app.services.provider_imports.enqueue_ride_ingest", new=enqueue_mock),
    ):
        with pytest.raises(StravaError) as exc:
            await import_activities(
                request=MagicMock(),
                payload=StravaImportRequest(activity_ids=[activity_id]),
                user=_user(),
                strava=strava,
                ride_repo=ride_repo,
                user_repo=user_repo,
            )

    assert exc.value.status_code == 503
    strava.download_activity_file_with_diagnostics.assert_not_awaited()
    ride_repo.update_ride_metadata.assert_not_awaited()
    ride_repo.update_ride_status.assert_not_awaited()
    enqueue_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_import_activities_blocks_pending_provider_retry_when_policy_read_fails() -> None:
    activity_id = 12347
    ride_id = uuid4()
    strava = MagicMock()
    strava.get_connection.return_value = SimpleNamespace(id=uuid4())
    strava.download_activity_file_with_diagnostics = AsyncMock()

    ride_repo = MagicMock()
    ride_repo.find_ride_by_import_identity = AsyncMock(
        return_value={
            "id": str(ride_id),
            "processing_status": "pending",
            "raw_file_path": "rides/user-1/ride.gpx",
            "file_type": "gpx",
        }
    )
    ride_repo.resolve_ride_privacy_policy = AsyncMock(
        side_effect=PrivacySettingsUnavailable("database unavailable")
    )
    ride_repo.update_ride_metadata = AsyncMock()
    ride_repo.update_ride_status = AsyncMock()

    user_repo = MagicMock()
    user_repo.get_user_profile = AsyncMock(return_value={"weight_kg": 70, "ftp_w": 250})
    enqueue_mock = AsyncMock(
        return_value=RideIngestEnqueueResult(accepted=True, backend="nats")
    )

    with (
        patch("app.routes.strava.create_file_storage_service", return_value=MagicMock()),
        patch("app.services.provider_imports.enqueue_ride_ingest", new=enqueue_mock),
    ):
        with pytest.raises(StravaError) as exc:
            await import_activities(
                request=MagicMock(),
                payload=StravaImportRequest(activity_ids=[activity_id]),
                user=_user(),
                strava=strava,
                ride_repo=ride_repo,
                user_repo=user_repo,
            )

    assert exc.value.status_code == 503
    strava.download_activity_file_with_diagnostics.assert_not_awaited()
    ride_repo.update_ride_metadata.assert_not_awaited()
    ride_repo.update_ride_status.assert_not_awaited()
    enqueue_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_import_activities_blocks_pending_provider_retry_when_policy_write_fails() -> None:
    activity_id = 12349
    ride_id = uuid4()
    strava = MagicMock()
    strava.get_connection.return_value = SimpleNamespace(id=uuid4())
    strava.download_activity_file_with_diagnostics = AsyncMock()

    ride_repo = MagicMock()
    ride_repo.find_ride_by_import_identity = AsyncMock(
        return_value={
            "id": str(ride_id),
            "processing_status": "pending",
            "raw_file_path": "rides/user-1/ride.gpx",
            "file_type": "gpx",
        }
    )
    policy = _privacy_policy(visibility="private", map_visibility="hide_entire")
    ride_repo.resolve_ride_privacy_policy = AsyncMock(return_value=policy)
    ride_repo.update_ride_metadata = AsyncMock(
        side_effect=RuntimeError("database unavailable")
    )
    ride_repo.update_ride_status = AsyncMock()

    user_repo = MagicMock()
    user_repo.get_user_profile = AsyncMock(return_value={"weight_kg": 70, "ftp_w": 250})
    enqueue_mock = AsyncMock(
        return_value=RideIngestEnqueueResult(accepted=True, backend="nats")
    )

    with (
        patch("app.routes.strava.create_file_storage_service", return_value=MagicMock()),
        patch("app.services.provider_imports.enqueue_ride_ingest", new=enqueue_mock),
    ):
        with pytest.raises(StravaError) as exc:
            await import_activities(
                request=MagicMock(),
                payload=StravaImportRequest(
                    activity_ids=[activity_id],
                    visibility="private",
                    map_visibility="hide_entire",
                    map_hide_start_m=0,
                    map_hide_end_m=0,
                ),
                user=_user(),
                strava=strava,
                ride_repo=ride_repo,
                user_repo=user_repo,
            )

    assert exc.value.status_code == 503
    ride_repo.update_ride_metadata.assert_awaited_once_with(
        str(ride_id),
        policy.to_storage_dict(),
    )
    strava.download_activity_file_with_diagnostics.assert_not_awaited()
    ride_repo.update_ride_status.assert_not_awaited()
    enqueue_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_import_activities_does_not_rewrite_completed_provider_duplicate() -> None:
    activity_id = 12348
    ride_id = uuid4()
    strava = MagicMock()
    strava.get_connection.return_value = SimpleNamespace(id=uuid4())
    strava.download_activity_file_with_diagnostics = AsyncMock()

    ride_repo = MagicMock()
    ride_repo.find_ride_by_import_identity = AsyncMock(
        return_value={
            "id": str(ride_id),
            "processing_status": "complete",
            "visibility": "public",
        }
    )
    ride_repo.resolve_ride_privacy_policy = AsyncMock()
    ride_repo.update_ride_metadata = AsyncMock()
    ride_repo.update_ride_status = AsyncMock()

    user_repo = MagicMock()
    user_repo.get_user_profile = AsyncMock(return_value={"weight_kg": 70, "ftp_w": 250})
    enqueue_mock = AsyncMock()

    with (
        patch("app.routes.strava.create_file_storage_service", return_value=MagicMock()),
        patch("app.services.provider_imports.enqueue_ride_ingest", new=enqueue_mock),
    ):
        response = await import_activities(
            request=MagicMock(),
            payload=StravaImportRequest(
                activity_ids=[activity_id],
                visibility="private",
                map_visibility="hide_entire",
                map_hide_start_m=0,
                map_hide_end_m=0,
            ),
            user=_user(),
            strava=strava,
            ride_repo=ride_repo,
            user_repo=user_repo,
        )

    assert response.imported_count == 0
    assert response.failed_count == 1
    assert response.results[0].activity_id == ride_id
    assert "Already imported" in str(response.results[0].error)
    strava.download_activity_file_with_diagnostics.assert_not_awaited()
    ride_repo.resolve_ride_privacy_policy.assert_not_awaited()
    ride_repo.update_ride_metadata.assert_not_awaited()
    ride_repo.update_ride_status.assert_not_awaited()
    enqueue_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_import_activities_resolves_explicit_privacy_before_storage() -> None:
    activity_id = 24680
    connection_id = uuid4()
    diagnostics = SimpleNamespace(
        import_source="strava_stream_reconstructed_gpx",
        source_activity_id=str(activity_id),
        to_dict=lambda: {
            "import_source": "strava_stream_reconstructed_gpx",
            "source_activity_id": str(activity_id),
        },
    )
    strava = MagicMock()
    strava.get_connection.return_value = SimpleNamespace(id=connection_id)
    strava.download_activity_file_with_diagnostics = AsyncMock(
        return_value=(b"gpx-bytes", "gpx", diagnostics)
    )

    events: list[str] = []
    policy = _privacy_policy()

    async def resolve_policy(*_args, **_kwargs):
        events.append("privacy_resolved")
        return policy

    ride_repo = MagicMock()
    ride_repo.find_ride_by_import_identity = AsyncMock(return_value=None)
    ride_repo.find_ride_by_hash = AsyncMock(return_value=None)
    ride_repo.resolve_ride_privacy_policy = AsyncMock(side_effect=resolve_policy)
    ride_repo.create_ride = AsyncMock()

    async def upload_file(**_kwargs):
        events.append("file_stored")
        return SimpleNamespace(
            path="rides/user-1/new.gpx",
            size_bytes=9,
            file_hash="hash-1",
        )

    storage = MagicMock()
    storage.compute_file_hash.return_value = "hash-1"
    storage.upload_ride_file = AsyncMock(side_effect=upload_file)

    user_repo = MagicMock()
    user_repo.get_user_profile = AsyncMock(return_value={"weight_kg": 70, "ftp_w": 250})
    enqueue_result = RideIngestEnqueueResult(accepted=True, backend="nats")

    with (
        patch("app.routes.strava.create_file_storage_service", return_value=storage),
        patch(
            "app.routes.strava.enqueue_ride_ingest",
            new=AsyncMock(return_value=enqueue_result),
        ),
    ):
        response = await import_activities(
            request=MagicMock(),
            payload=StravaImportRequest(
                activity_ids=[activity_id],
                visibility="followers",
                map_visibility="show_all",
                map_hide_start_m=0,
                map_hide_end_m=0,
            ),
            user=_user(),
            strava=strava,
            ride_repo=ride_repo,
            user_repo=user_repo,
        )

    assert response.imported_count == 1
    assert response.failed_count == 0
    assert events == ["privacy_resolved", "file_stored"]
    ride_repo.resolve_ride_privacy_policy.assert_awaited_once_with(
        "user-1",
        visibility="followers",
        map_visibility="show_all",
        map_hide_start_m=0,
        map_hide_end_m=0,
    )
    assert ride_repo.create_ride.await_args.kwargs["privacy_policy"] is policy


@pytest.mark.asyncio
async def test_import_activities_blocks_storage_when_privacy_is_unavailable() -> None:
    activity_id = 13579
    diagnostics = SimpleNamespace(
        import_source="strava_stream_reconstructed_gpx",
        source_activity_id=str(activity_id),
        to_dict=lambda: {},
    )
    strava = MagicMock()
    strava.get_connection.return_value = SimpleNamespace(id=uuid4())
    strava.download_activity_file_with_diagnostics = AsyncMock(
        return_value=(b"gpx-bytes", "gpx", diagnostics)
    )

    storage = MagicMock()
    storage.compute_file_hash.return_value = "hash-1"
    storage.upload_ride_file = AsyncMock()

    ride_repo = MagicMock()
    ride_repo.find_ride_by_import_identity = AsyncMock(return_value=None)
    ride_repo.find_ride_by_hash = AsyncMock(return_value=None)
    ride_repo.resolve_ride_privacy_policy = AsyncMock(
        side_effect=PrivacySettingsUnavailable("database unavailable")
    )
    ride_repo.create_ride = AsyncMock()

    user_repo = MagicMock()
    user_repo.get_user_profile = AsyncMock(return_value={"weight_kg": 70, "ftp_w": 250})

    with patch("app.routes.strava.create_file_storage_service", return_value=storage):
        with pytest.raises(StravaError) as exc:
            await import_activities(
                request=MagicMock(),
                payload=StravaImportRequest(activity_ids=[activity_id]),
                user=_user(),
                strava=strava,
                ride_repo=ride_repo,
                user_repo=user_repo,
            )

    assert exc.value.status_code == 503
    strava.download_activity_file_with_diagnostics.assert_not_awaited()
    storage.upload_ride_file.assert_not_awaited()
    ride_repo.create_ride.assert_not_awaited()


@pytest.mark.asyncio
async def test_import_activities_requeues_pending_hash_duplicate_before_marking_imported() -> None:
    activity_id = 67890
    ride_id = uuid4()
    connection_id = uuid4()
    diagnostics = SimpleNamespace(
        import_source="strava_stream_reconstructed_gpx",
        source_activity_id=str(activity_id),
        to_dict=lambda: {
            "import_source": "strava_stream_reconstructed_gpx",
            "source_activity_id": str(activity_id),
        },
    )
    strava = MagicMock()
    strava.get_connection.return_value = SimpleNamespace(id=connection_id)
    strava.download_activity_file_with_diagnostics = AsyncMock(
        return_value=(b"gpx-bytes", "gpx", diagnostics)
    )

    storage = MagicMock()
    storage.compute_file_hash.return_value = "hash-1"

    ride_repo = MagicMock()
    ride_repo.find_ride_by_import_identity = AsyncMock(return_value=None)
    ride_repo.find_ride_by_hash = AsyncMock(
        return_value={
            "id": str(ride_id),
            "processing_status": "pending",
            "raw_file_path": "rides/user-1/ride.gpx",
            "file_type": "gpx",
        }
    )
    policy = _privacy_policy()
    ride_repo.resolve_ride_privacy_policy = AsyncMock(return_value=policy)
    ride_repo.update_ride_metadata = AsyncMock()
    ride_repo.get_ride = AsyncMock(
        return_value={
            "id": str(ride_id),
            "processing_status": "pending",
            "raw_file_path": "rides/user-1/ride.gpx",
            "file_type": "gpx",
            **policy.to_storage_dict(),
        }
    )
    ride_repo.update_ride_status = AsyncMock()

    user_repo = MagicMock()
    user_repo.get_user_profile = AsyncMock(return_value={"weight_kg": 70, "ftp_w": 250})

    enqueue_result = RideIngestEnqueueResult(accepted=True, backend="nats")
    with (
        patch("app.routes.strava.create_file_storage_service", return_value=storage),
        patch(
            "app.services.provider_imports.enqueue_ride_ingest",
            new=AsyncMock(return_value=enqueue_result),
        ),
    ):
        response = await import_activities(
            request=MagicMock(),
            payload=StravaImportRequest(activity_ids=[activity_id]),
            user=_user(),
            strava=strava,
            ride_repo=ride_repo,
            user_repo=user_repo,
        )

    assert response.imported_count == 1
    assert response.failed_count == 0
    assert response.results[0].success is True
    ride_repo.create_ride.assert_not_called()
    ride_repo.update_ride_metadata.assert_awaited_once_with(
        str(ride_id),
        policy.to_storage_dict(),
    )
    ride_repo.update_ride_status.assert_awaited_once_with(UUID(str(ride_id)), "processing")
    strava.mark_activity_imported.assert_called_once_with(
        connection_id=connection_id,
        strava_activity_id=activity_id,
        activity_id=str(ride_id),
    )
