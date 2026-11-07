from __future__ import annotations

import base64
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

os.environ.setdefault("ACCESS_TOKEN_SECRET", "test-access-secret")
os.environ.setdefault("REFRESH_TOKEN_SECRET", "test-refresh-secret")

from app.dependencies import AuthenticatedUser
from app.routes.rides import update_ride, upload_ride
from app.schemas import RideUpdateRequest, RideUploadRequest
from app.services.ride_ingest import RideIngestEnqueueResult
from app.services.ride_privacy import PrivacySettingsUnavailable, RidePrivacyPolicy


def _user() -> AuthenticatedUser:
    return AuthenticatedUser(
        wallet="wallet-1",
        user_id="user-1",
        device_id="device-1",
    )


def _policy() -> RidePrivacyPolicy:
    return RidePrivacyPolicy.from_values(
        visibility="followers",
        map_visibility="hide_start_end",
        map_hide_start_m=400,
        map_hide_end_m=200,
    )


@pytest.mark.asyncio
async def test_inline_upload_freezes_explicit_privacy_before_file_storage() -> None:
    ride_repo = MagicMock()
    ride_repo.find_ride_by_hash = AsyncMock(return_value=None)
    ride_repo.resolve_ride_privacy_policy = AsyncMock(return_value=_policy())
    ride_repo.create_ride = AsyncMock()

    user_repo = MagicMock()
    user_repo.get_user_profile = AsyncMock(return_value={"weight_kg": 72, "ftp_w": 260})

    storage = MagicMock()
    storage.compute_file_hash.return_value = "ab" * 32
    storage.upload_ride_file = AsyncMock(
        return_value=SimpleNamespace(
            path="rides/user-1/ride.fit",
            size_bytes=4,
            file_hash="ab" * 32,
        )
    )

    request = RideUploadRequest(
        fileDataB64=base64.b64encode(b"ride").decode("ascii"),
        fileType="fit",
        visibility="followers",
        mapVisibility="hide_start_end",
        mapHideStartM=400,
        mapHideEndM=200,
    )

    with (
        patch("app.routes.rides.create_file_storage_service", return_value=storage),
        patch(
            "app.routes.rides.enqueue_ride_ingest",
            new=AsyncMock(return_value=RideIngestEnqueueResult(True, "nats")),
        ),
    ):
        await upload_ride(
            http_request=MagicMock(),
            ride_request=request,
            force=False,
            current_user=_user(),
            ride_repo=ride_repo,
            user_repo=user_repo,
        )

    ride_repo.resolve_ride_privacy_policy.assert_awaited_once_with(
        "user-1",
        visibility="followers",
        map_visibility="hide_start_end",
        map_hide_start_m=400,
        map_hide_end_m=200,
    )
    storage.upload_ride_file.assert_awaited_once()
    assert ride_repo.create_ride.await_args.kwargs["privacy_policy"] == _policy()
    assert ride_repo.create_ride.await_args.kwargs["upload_verified_at"] is not None


@pytest.mark.asyncio
async def test_inline_upload_blocks_storage_mutation_when_privacy_is_unavailable() -> None:
    ride_repo = MagicMock()
    ride_repo.find_ride_by_hash = AsyncMock(return_value=None)
    ride_repo.resolve_ride_privacy_policy = AsyncMock(
        side_effect=PrivacySettingsUnavailable("database unavailable")
    )
    ride_repo.create_ride = AsyncMock()

    storage = MagicMock()
    storage.compute_file_hash.return_value = "ab" * 32
    storage.upload_ride_file = AsyncMock()

    with patch("app.routes.rides.create_file_storage_service", return_value=storage):
        with pytest.raises(HTTPException) as exc_info:
            await upload_ride(
                http_request=MagicMock(),
                ride_request=RideUploadRequest(
                    fileDataB64=base64.b64encode(b"ride").decode("ascii"),
                    fileType="fit",
                ),
                force=False,
                current_user=_user(),
                ride_repo=ride_repo,
                user_repo=MagicMock(),
            )

    assert exc_info.value.status_code == 503
    storage.upload_ride_file.assert_not_awaited()
    ride_repo.create_ride.assert_not_awaited()


@pytest.mark.asyncio
async def test_ride_privacy_edit_writes_one_complete_validated_snapshot() -> None:
    repo = MagicMock()
    repo.get_ride = AsyncMock(
        return_value={
            "id": "ride-1",
            "user_id": "user-1",
            "visibility": "public",
            "map_visibility": "hide_start_end",
            "map_hide_start_m": 200,
            "map_hide_end_m": 200,
        }
    )
    repo.update_ride_metadata = AsyncMock()

    response = await update_ride(
        ride_id="ride-1",
        update_request=RideUpdateRequest(
            visibility="private",
            map_visibility="hide_entire",
            map_hide_start_m=0,
            map_hide_end_m=0,
        ),
        current_user=_user(),
        repo=repo,
    )

    assert response == {"status": "updated", "ride_id": "ride-1"}
    repo.update_ride_metadata.assert_awaited_once_with(
        "ride-1",
        {
            "visibility": "private",
            "map_visibility": "hide_entire",
            "map_hide_start_m": 0,
            "map_hide_end_m": 0,
        },
    )


@pytest.mark.asyncio
async def test_ride_privacy_edit_fails_closed_when_snapshot_is_incomplete() -> None:
    repo = MagicMock()
    repo.get_ride = AsyncMock(
        return_value={
            "id": "ride-1",
            "user_id": "user-1",
            "visibility": "public",
        }
    )
    repo.update_ride_metadata = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await update_ride(
            ride_id="ride-1",
            update_request=RideUpdateRequest(visibility="private"),
            current_user=_user(),
            repo=repo,
        )

    assert exc_info.value.status_code == 503
    repo.update_ride_metadata.assert_not_awaited()
