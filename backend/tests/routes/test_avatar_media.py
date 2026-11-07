from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.dependencies import AuthenticatedUser
from app.avatar_media_contracts import AVATAR_SIGNED_URL_EXPIRY_SECONDS
from app.routes.users import (
    avatar_upload_complete,
    avatar_upload_init,
    delete_my_avatar,
    get_user_profile,
    update_my_profile,
)
from app.schemas import AvatarUploadCompleteRequest, AvatarUploadInitRequest, UserProfileUpdate


def _current_user(user_id: str = "user-1") -> AuthenticatedUser:
    return AuthenticatedUser(
        wallet="wallet-1",
        user_id=user_id,
        device_id="device-1",
    )


def _profile(**overrides):
    data = {
        "id": "11111111-1111-1111-1111-111111111111",
        "wallet": "wallet-1",
        "username": "tim",
        "display_name": "Tim",
        "bio": None,
        "avatar_url": None,
        "avatar_storage_path": None,
        "is_public": True,
        "default_ride_visibility": "public",
        "weight_kg": 75,
        "ftp_w": 200,
        "preferred_units": "metric",
        "theme_id": "hoo-breddin",
        "is_dark_mode": True,
        "rider_type": "climber",
    }
    data.update(overrides)
    return data


@pytest.mark.asyncio
async def test_avatar_upload_init_complete_persists_and_signs_profile_avatar() -> None:
    user_repo = MagicMock()
    ride_repo = MagicMock()
    ride_repo.get_user_rides_for_date = AsyncMock(return_value=[])
    user_repo.get_user_stats = AsyncMock(return_value={})

    pending_profile = _profile(
        avatar_pending_upload_id="upload-1",
        avatar_pending_storage_path="avatars/user-1/upload-1.jpg",
        avatar_pending_mime_type="image/jpeg",
        avatar_pending_size_bytes=12345,
    )
    ready_profile = _profile(
        avatar_storage_path="avatars/user-1/upload-1.jpg",
        avatar_mime_type="image/jpeg",
        avatar_size_bytes=12345,
    )
    user_repo.get_private_user_profile = AsyncMock(side_effect=[_profile(), pending_profile, ready_profile])
    user_repo.begin_avatar_upload = AsyncMock()
    user_repo.complete_avatar_upload = AsyncMock(return_value=ready_profile)

    storage = MagicMock()
    storage.create_signed_upload_url = AsyncMock(
        return_value={"signed_url": "https://example.test/avatar-upload"}
    )
    storage.file_exists = AsyncMock(return_value=True)
    storage.get_file_size = AsyncMock(return_value=12345)
    storage.prepare_photo = AsyncMock(side_effect=lambda path, mime, size: SimpleNamespace(path="sanitized/" + path, size_bytes=12345, width=16, height=24, mime_type="image/jpeg"))
    storage.get_signed_url = AsyncMock(return_value="https://example.test/avatar-read")

    current_user = _current_user()
    with patch("app.routes.users.create_file_storage_service", return_value=storage):
        with patch("app.avatar_media_contracts.create_file_storage_service", return_value=storage):
            init_response = await avatar_upload_init(
                init_request=AvatarUploadInitRequest(
                    file_name="avatar.jpg",
                    mime_type="image/jpeg",
                    file_size=12345,
                ),
                current_user=current_user,
                user_repo=user_repo,
            )

            begin_kwargs = user_repo.begin_avatar_upload.await_args.kwargs
            upload_id = begin_kwargs["upload_id"]
            pending_for_complete = _profile(
                avatar_pending_upload_id=upload_id,
                avatar_pending_storage_path=begin_kwargs["storage_path"],
                avatar_pending_mime_type="image/jpeg",
                avatar_pending_size_bytes=12345,
            )
            ready_profile = _profile(
                avatar_storage_path=begin_kwargs["storage_path"],
                avatar_mime_type="image/jpeg",
                avatar_size_bytes=12345,
            )
            user_repo.get_private_user_profile.side_effect = [pending_for_complete, ready_profile]
            complete_response = await avatar_upload_complete(
                complete_request=AvatarUploadCompleteRequest(upload_id=upload_id),
                current_user=current_user,
                user_repo=user_repo,
                ride_repo=ride_repo,
            )

    assert init_response.signed_url == "https://example.test/avatar-upload"
    assert begin_kwargs["user_id"] == "user-1"
    assert begin_kwargs["mime_type"] == "image/jpeg"
    assert begin_kwargs["storage_path"].startswith("avatars/user-1/")
    storage.prepare_photo.assert_awaited_once_with(begin_kwargs["storage_path"], "image/jpeg", 12345)
    user_repo.complete_avatar_upload.assert_awaited_once_with(
        user_id="user-1",
        upload_id=upload_id,
        storage_path="sanitized/" + begin_kwargs["storage_path"],
        size_bytes=12345,
        mime_type="image/jpeg",
    )
    assert complete_response.avatar_url == "https://example.test/avatar-read"
    assert complete_response.rider is not None
    assert complete_response.rider.avatar_url == "https://example.test/avatar-read"


@pytest.mark.asyncio
async def test_avatar_upload_init_rejects_overlapping_pending_upload() -> None:
    user_repo = MagicMock()
    user_repo.get_private_user_profile = AsyncMock(return_value=_profile(
        avatar_pending_upload_id="upload-1",
        avatar_pending_storage_path="avatars/user-1/upload-1.jpg",
        avatar_pending_created_at=datetime.now(timezone.utc).isoformat(),
    ))
    user_repo.begin_avatar_upload = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await avatar_upload_init(
            init_request=AvatarUploadInitRequest(
                file_name="avatar.jpg",
                mime_type="image/jpeg",
                file_size=12345,
            ),
            current_user=_current_user(),
            user_repo=user_repo,
        )

    assert exc.value.status_code == 409
    user_repo.begin_avatar_upload.assert_not_awaited()


@pytest.mark.asyncio
async def test_avatar_upload_init_cleans_expired_pending_upload_before_replacing() -> None:
    user_repo = MagicMock()
    expired_at = datetime.now(timezone.utc) - timedelta(seconds=AVATAR_SIGNED_URL_EXPIRY_SECONDS + 5)
    user_repo.get_private_user_profile = AsyncMock(return_value=_profile(
        avatar_pending_upload_id="upload-1",
        avatar_pending_storage_path="avatars/user-1/upload-1.jpg",
        avatar_pending_created_at=expired_at.isoformat(),
    ))
    user_repo.begin_avatar_upload = AsyncMock()

    storage = MagicMock()
    storage.delete_photo_files = AsyncMock()
    storage.create_signed_upload_url = AsyncMock(
        return_value={"signed_url": "https://example.test/avatar-upload"}
    )

    with patch("app.routes.users.create_file_storage_service", return_value=storage):
        response = await avatar_upload_init(
            init_request=AvatarUploadInitRequest(
                file_name="avatar.jpg",
                mime_type="image/jpeg",
                file_size=12345,
            ),
            current_user=_current_user(),
            user_repo=user_repo,
        )

    assert response.signed_url == "https://example.test/avatar-upload"
    storage.delete_photo_files.assert_awaited_once_with("avatars/user-1/upload-1.jpg")
    user_repo.begin_avatar_upload.assert_awaited_once()


@pytest.mark.asyncio
async def test_profile_update_logs_field_names_without_values(caplog: pytest.LogCaptureFixture) -> None:
    user_repo = MagicMock()
    ride_repo = MagicMock()
    user_repo.get_private_user_profile = AsyncMock(return_value=_profile())
    user_repo.update_user_profile = AsyncMock(return_value=_profile(bio="secret ftp note"))
    user_repo.get_user_stats = AsyncMock(return_value={})
    ride_repo.get_user_rides_for_date = AsyncMock(return_value=[])

    caplog.set_level(logging.INFO, logger="app.routes.users")
    await update_my_profile(
        updates=UserProfileUpdate(bio="secret ftp note"),
        current_user=_current_user(),
        user_repo=user_repo,
        ride_repo=ride_repo,
    )

    assert "fields=['bio']" in caplog.text
    assert "secret ftp note" not in caplog.text


@pytest.mark.asyncio
async def test_private_profile_redacts_signed_avatar_from_nested_rider() -> None:
    repo = MagicMock()
    repo.get_user_by_identifier = AsyncMock(
        return_value=_profile(
            is_public=False,
            avatar_storage_path="avatars/11111111-1111-1111-1111-111111111111/avatar.jpg",
        )
    )

    storage = MagicMock()
    storage.get_signed_url = AsyncMock(return_value="https://example.test/signed-avatar")

    with patch("app.avatar_media_contracts.create_file_storage_service", return_value=storage):
        profile = await get_user_profile(
            "tim",
            current_user=_current_user("viewer-user"),
            repo=repo,
        )

    assert profile.avatar_url is None
    assert profile.display_name is None
    assert profile.rider is not None
    assert profile.rider.avatar_url is None
    assert profile.rider.display_name is None
    assert profile.rider.is_public is False


@pytest.mark.asyncio
async def test_delete_avatar_nulls_contract_after_storage_cleanup() -> None:
    user_repo = MagicMock()
    ride_repo = MagicMock()
    ride_repo.get_user_rides_for_date = AsyncMock(return_value=[])
    user_repo.get_user_stats = AsyncMock(return_value={})
    user_repo.get_private_user_profile = AsyncMock(side_effect=[
        _profile(avatar_storage_path="avatars/user-1/old.jpg"),
        _profile(),
    ])
    user_repo.delete_avatar = AsyncMock(return_value=_profile())

    storage = MagicMock()
    storage.delete_photo_files = AsyncMock()

    with patch("app.routes.users.create_file_storage_service", return_value=storage):
        response = await delete_my_avatar(
            current_user=_current_user(),
            user_repo=user_repo,
            ride_repo=ride_repo,
        )

    user_repo.delete_avatar.assert_awaited_once_with("user-1", expected_profile=_profile(avatar_storage_path="avatars/user-1/old.jpg"))
    storage.delete_photo_files.assert_awaited_once_with("avatars/user-1/old.jpg")
    assert response.avatar_url is None
    assert response.rider is not None
    assert response.rider.avatar_url is None


@pytest.mark.asyncio
async def test_public_profile_exposes_signed_avatar_url_from_rider_ref() -> None:
    user_id = str(uuid4())
    repo = MagicMock()
    repo.get_user_by_identifier = AsyncMock(return_value=_profile(
        id=user_id,
        avatar_storage_path="avatars/user-1/avatar.webp",
        avatar_mime_type="image/webp",
        avatar_size_bytes=4567,
    ))
    repo.get_user_stats = AsyncMock(return_value={"total_rides": 3})

    storage = MagicMock()
    storage.get_signed_url = AsyncMock(return_value="https://example.test/signed-avatar")

    with patch("app.avatar_media_contracts.create_file_storage_service", return_value=storage):
        response = await get_user_profile(
            identifier="tim",
            current_user=None,
            repo=repo,
        )

    assert response.avatar_url == "https://example.test/signed-avatar"
    assert response.rider is not None
    assert response.rider.avatar_url == "https://example.test/signed-avatar"
    dumped = response.model_dump() if hasattr(response, "model_dump") else response.dict()
    assert "wallet" not in dumped
