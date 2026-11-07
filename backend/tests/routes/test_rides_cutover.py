from __future__ import annotations

from unittest.mock import ANY, AsyncMock, MagicMock, call, patch
from uuid import UUID, uuid4

import pytest

from app.dependencies import AuthenticatedUser
from fastapi import HTTPException
from app.routes import rides as rides_routes
from app.routes.rides import get_ride_detail, list_rides, reprocess_ride, upload_complete
from app.schemas import UploadCompleteRequest
from app.services.ride_ingest import RideIngestEnqueueResult
from app.ride_media_contracts import serialize_ride_media_list as canonical_serialize_ride_media_list


@pytest.mark.asyncio
async def test_ride_original_returns_an_owner_only_signed_download_without_storage_path():
    user_id = str(uuid4())
    ride_id = str(uuid4())
    repo = MagicMock()
    repo.get_ride = AsyncMock(
        return_value={
            "id": ride_id,
            "user_id": user_id,
            "visibility": "public",
            "raw_file_path": f"rides/{user_id}/private/source.fit",
            "file_name": "../Morning Ride.fit",
            "file_type": "fit",
        }
    )
    storage = MagicMock()
    storage.get_signed_url = AsyncMock(return_value="https://storage.example.test/signed")
    current_user = AuthenticatedUser(
        wallet="wallet-1", user_id=user_id, device_id="device-1"
    )

    with patch("app.routes.rides.create_file_storage_service", return_value=storage):
        response = await rides_routes.get_ride_original(
            ride_id=ride_id,
            current_user=current_user,
            repo=repo,
        )

    assert response == {
        "signedUrl": "https://storage.example.test/signed",
        "fileName": "Morning Ride.fit",
        "fileType": "fit",
        "mimeType": "application/vnd.ant.fit",
        "expiresIn": 600,
    }
    assert "raw_file_path" not in response
    storage.get_signed_url.assert_awaited_once_with(
        f"rides/{user_id}/private/source.fit", expires_in=600
    )


@pytest.mark.asyncio
async def test_ride_original_refuses_a_ride_without_a_stored_source():
    user_id = str(uuid4())
    ride_id = str(uuid4())
    repo = MagicMock()
    repo.get_ride = AsyncMock(
        return_value={
            "id": ride_id,
            "user_id": user_id,
            "visibility": "private",
            "raw_file_path": None,
        }
    )
    current_user = AuthenticatedUser(
        wallet="wallet-1", user_id=user_id, device_id="device-1"
    )

    with pytest.raises(HTTPException) as exc_info:
        await rides_routes.get_ride_original(
            ride_id=ride_id,
            current_user=current_user,
            repo=repo,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Original ride file is not available"


@pytest.mark.asyncio
async def test_list_rides_honors_pagination_and_batches_media_lookup():
    user_id = str(uuid4())
    ride_id = str(uuid4())
    media_id = str(uuid4())
    ride_repo = MagicMock()
    ride_repo.list_counted_climb_steps = AsyncMock(return_value={
        ride_id: [{"segment_start_offset_s": 0, "segment_end_offset_s": 10,
                   "exact_tribute_base_units": "1"}],
    })
    ride_repo.list_rides_for_user = AsyncMock(
        return_value=[
            {
                "id": ride_id,
                "user_id": user_id,
                "processing_status": "completed",
                "started_at": "2026-05-18T12:00:00+00:00",
                "kcals": 500,
                "gps_track": [
                    {"latitude": 40, "longitude": -75, "distance_m": 0, "elevation_m": 10, "timestamp": 0},
                    {"latitude": 40.001, "longitude": -75, "distance_m": 100, "elevation_m": 20, "timestamp": 10},
                ],
                "visibility": "public",
            }
        ]
    )
    ride_repo.list_ride_media_for_rides = AsyncMock(
        return_value={
            ride_id: [
                {
                    "id": media_id,
                    "ride_id": ride_id,
                    "file_name": "cover.jpg",
                    "mime_type": "image/jpeg",
                    "size_bytes": 123,
                    "sort_order": 0,
                    "role": "cover",
                    "moderation_state": "visible",
                }
            ]
        }
    )
    current_user = AuthenticatedUser(wallet="wallet-1", user_id=user_id, device_id="device-1")
    storage = MagicMock()
    storage.get_signed_url = AsyncMock(return_value="https://storage.example.test/media")

    async def serialize_with_test_storage(rows):
        return await canonical_serialize_ride_media_list(rows, storage=storage)

    with patch("app.routes.rides.serialize_ride_media_list", side_effect=serialize_with_test_storage):
        records = await list_rides(
            current_user=current_user,
            ride_repo=ride_repo,
            limit=7,
            offset=14,
        )

    ride_repo.list_rides_for_user.assert_awaited_once_with(user_id, limit=7, offset=14)
    ride_repo.list_ride_media_for_rides.assert_awaited_once_with([ride_id])
    assert len(records) == 1
    assert records[0].id == UUID(ride_id)
    assert len(records[0].elevation_profile) == 2
    assert records[0].counted_spans[0].end_distance_m == 100
    ride_repo.get_activity_stream.assert_not_called()
    assert len(records[0].media) == 1
    assert records[0].media[0].id == UUID(media_id)


@pytest.mark.asyncio
async def test_ride_detail_contract_returns_first_paint_shell_without_reward_projection_for_processing_ride():
    user_id = str(uuid4())
    ride_id = str(uuid4())
    ride_repo = MagicMock()
    ride_repo.client = MagicMock()
    ride_repo.get_ride = AsyncMock(
        return_value={
            "id": ride_id,
            "user_id": user_id,
            "processing_status": "processing",
            "visibility": "public",
            "comments_enabled": True,
            "file_name": "first-paint.fit",
            "distance_m": 1234,
            "duration_sec": 456,
        }
    )
    ride_repo.list_ride_media = AsyncMock(return_value=[])
    ride_repo.get_interaction_summaries = AsyncMock(
        return_value={
            ride_id: {
                "kudosCount": 3,
                "commentCount": 0,
                "viewerHasKudos": True,
            }
        }
    )
    ride_repo.get_comments = AsyncMock(return_value=[])
    current_user = AuthenticatedUser(wallet="wallet-1", user_id=user_id, device_id="device-1")

    with patch(
        "app.routes.links._resolve_link",
        new=AsyncMock(return_value={"targetType": "ride", "targetId": ride_id, "canView": True}),
    ):
        response = await get_ride_detail(
            ride_id=ride_id,
            current_user=current_user,
            repo=ride_repo,
            comments_limit=5,
        )

    assert response["contractVersion"] == "ride_detail.v1"
    assert response["ride"]["id"] == ride_id
    assert response["ride"]["isOwner"] is True
    assert response["status"]["status"] == "processing"
    assert response["status"]["climb_earnings"] == []
    assert response["interactions"]["kudosCount"] == 3
    assert response["comments"]["comments"] == []
    assert response["link"]["targetId"] == ride_id
    assert response["freshness"]["status"] == "processing"
    ride_repo.client.table.assert_not_called()


@pytest.mark.asyncio
async def test_non_owner_ride_detail_omits_exact_economy_from_ride_and_status():
    user_id = str(uuid4())
    ride_id = str(uuid4())
    ride_repo = MagicMock()
    ride_repo.client = MagicMock()
    ride_repo.get_ride = AsyncMock(
        return_value={
            "id": ride_id,
            "user_id": user_id,
            "processing_status": "completed",
            "visibility": "public",
            "comments_enabled": True,
            "started_at": "2026-08-24T12:00:00+00:00",
            "file_name": "privacy.fit",
            "cal_earned": 222,
            "dung_minted": 44,
            "estimated_cal": 240,
            "rewardable_cal": 222,
            "tributable_cal": 22,
            "reward_policy": "rewardable",
        }
    )
    ride_repo.list_ride_media = AsyncMock(return_value=[])
    ride_repo.get_interaction_summaries = AsyncMock(return_value={})
    ride_repo.get_comments = AsyncMock(return_value=[])
    user_repo = MagicMock()
    user_repo.get_user_by_id = AsyncMock(
        return_value={"id": user_id, "username": "rider", "is_public": True}
    )
    decision = MagicMock(is_owner=False, can_view=True)
    decision.to_client_dict.return_value = {
        "visibility": "public",
        "canView": True,
        "isOwner": False,
        "isFollower": False,
        "redactGps": True,
        "mapVisibility": "hide_entire",
        "mapHideStartM": 0,
        "mapHideEndM": 0,
        "protocolPublic": False,
        "protocolPublicFields": [],
        "reason": "public",
    }

    with patch(
        "app.routes.rides.check_ride_access",
        AsyncMock(return_value=decision),
    ), patch(
        "app.routes.rides._route_preview_points_for_record",
        AsyncMock(return_value=([], [])),
    ), patch(
        "app.routes.rides._fetch_terminal_threshold_release_authority",
        return_value=(None, None),
    ), patch(
        "app.routes.rides._fetch_ride_climb_earnings_for_client",
        return_value=[],
    ), patch(
        "app.routes.links._resolve_link",
        new=AsyncMock(return_value={"targetType": "ride", "targetId": ride_id, "canView": True}),
    ):
        response = await get_ride_detail(
            ride_id=ride_id,
            current_user=None,
            repo=ride_repo,
            user_repo=user_repo,
            comments_limit=5,
        )

    for field in (
        "calEarned",
        "dungEarned",
        "estimatedCal",
        "rewardableCal",
        "tributableCal",
        "calItemization",
    ):
        assert field not in response["ride"]
    assert "cal_earned" not in response["status"]
    assert "dung_minted" not in response["status"]
    assert "earnings" not in response["status"]
    assert "estimated_cal" not in response["status"]["effort_policy"]
    assert "rewardable_cal" not in response["status"]["effort_policy"]
    assert "tributable_cal" not in response["status"]["effort_policy"]


@pytest.mark.asyncio
async def test_upload_complete_uses_canonical_ingest_job_for_direct_upload():
    upload_id = "b7d39f86-bada-4d12-87c8-a056adf0c7f1"
    ride_repo = MagicMock()
    ride_repo.get_ride = AsyncMock(
        return_value={
            "id": upload_id,
            "user_id": "user-1",
            "processing_status": "uploading",
            "raw_file_path": "rides/user-1/file.fit",
            "raw_file_size_bytes": 1234,
            "file_type": "fit",
        }
    )
    ride_repo.transition_ride_status = AsyncMock(return_value=True)

    user_repo = MagicMock()
    user_repo.get_user_profile = AsyncMock(return_value={"weight_kg": 68.5})

    storage = MagicMock()
    storage.file_exists = AsyncMock(return_value=True)
    storage.get_file_size = AsyncMock(return_value=1234)
    storage.download_ride_file = AsyncMock(return_value=b"uploaded fit bytes")
    storage.compute_file_hash.return_value = "verified-file-hash"

    user = AuthenticatedUser(wallet="wallet-1", user_id="user-1", device_id="device-1")
    enqueue_result = RideIngestEnqueueResult(accepted=True, backend="nats")

    with patch("app.routes.rides.create_file_storage_service", return_value=storage):
        with patch("app.routes.rides.enqueue_ride_ingest", new=AsyncMock(return_value=enqueue_result)) as enqueue_mock:
            response = await upload_complete(
                http_request=MagicMock(),
                complete_request=UploadCompleteRequest(upload_id=upload_id),
                current_user=user,
                ride_repo=ride_repo,
                user_repo=user_repo,
            )

    assert response.ride_id == upload_id
    assert response.status == "processing"
    ride_repo.transition_ride_status.assert_has_awaits(
        [
                call(
                    UUID(upload_id),
                    expected_status="uploading",
                    new_status="pending",
                    upload_verified_at=ANY,
                ),
            call(UUID(upload_id), expected_status="pending", new_status="processing"),
        ]
    )
    enqueue_job = enqueue_mock.await_args.args[0]
    assert enqueue_job.ride_id == upload_id
    assert enqueue_job.user_id == "user-1"
    assert enqueue_job.wallet == "wallet-1"
    assert enqueue_job.file_path == "rides/user-1/file.fit"
    assert enqueue_job.file_type == "fit"
    assert enqueue_job.user_weight_kg == 68.5
    assert not hasattr(enqueue_job, "user_ftp_w")
    assert enqueue_job.source == "manual_upload_direct"


@pytest.mark.asyncio
async def test_upload_complete_marks_pending_when_queue_unavailable():
    upload_id = "29a55495-e403-4f4c-b0f4-c7df7c0aa0e3"
    ride_repo = MagicMock()
    ride_repo.get_ride = AsyncMock(
        return_value={
            "id": upload_id,
            "user_id": "user-1",
            "processing_status": "uploading",
            "raw_file_path": "rides/user-1/file.fit",
            "raw_file_size_bytes": 1200,
            "file_type": "fit",
        }
    )
    ride_repo.transition_ride_status = AsyncMock(side_effect=[True, True])

    user_repo = MagicMock()
    user_repo.get_user_profile = AsyncMock(return_value=None)

    storage = MagicMock()
    storage.file_exists = AsyncMock(return_value=True)
    storage.get_file_size = AsyncMock(return_value=1200)
    storage.download_ride_file = AsyncMock(return_value=b"uploaded fit bytes")
    storage.compute_file_hash.return_value = "verified-file-hash"

    user = AuthenticatedUser(wallet="wallet-1", user_id="user-1", device_id="device-1")
    enqueue_result = RideIngestEnqueueResult(
        accepted=False,
        backend="nats",
        error="queue unavailable",
    )

    with patch("app.routes.rides.create_file_storage_service", return_value=storage):
        with patch("app.routes.rides.enqueue_ride_ingest", new=AsyncMock(return_value=enqueue_result)):
            response = await upload_complete(
                http_request=MagicMock(),
                complete_request=UploadCompleteRequest(upload_id=upload_id),
                current_user=user,
                ride_repo=ride_repo,
                user_repo=user_repo,
            )

    assert response.status == "pending"
    ride_repo.transition_ride_status.assert_has_awaits(
        [
                call(
                    UUID(upload_id),
                    expected_status="uploading",
                    new_status="pending",
                    upload_verified_at=ANY,
                ),
            call(
                UUID(upload_id),
                expected_status="pending",
                new_status="pending",
                error_message="queue unavailable",
            ),
        ]
    )


@pytest.mark.asyncio
async def test_reprocess_ride_surfaces_queue_failure_after_resetting_state():
    ride_id = "9849d4f4-8ad9-464d-bf0f-1d07de5ca19d"
    ride_repo = MagicMock()
    ride_repo.get_ride = AsyncMock(
        return_value={
            "id": ride_id,
            "user_id": "user-1",
            "processing_status": "failed",
            "raw_file_path": "rides/user-1/file.fit",
            "file_type": "fit",
        }
    )
    ride_repo.update_ride_status = AsyncMock()
    ride_repo.clear_ride_error = AsyncMock()
    ride_repo.increment_reprocess_count = AsyncMock()

    user_repo = MagicMock()
    user_repo.get_user_profile = AsyncMock(return_value={"weight_kg": 72.0, "ftp_w": 240})

    user = AuthenticatedUser(wallet="wallet-1", user_id="user-1", device_id="device-1")
    enqueue_result = RideIngestEnqueueResult(
        accepted=False,
        backend="nats",
        error="nats unavailable",
    )

    with patch("app.routes.rides.enqueue_ride_ingest", new=AsyncMock(return_value=enqueue_result)):
        with pytest.raises(HTTPException) as exc_info:
            await reprocess_ride(
                ride_id=ride_id,
                current_user=user,
                ride_repo=ride_repo,
                user_repo=user_repo,
            )

    assert getattr(exc_info.value, "status_code", None) == 503
    assert "queue unavailable" in str(exc_info.value.detail).lower()
    ride_repo.update_ride_status.assert_has_awaits(
        [
            call(UUID(ride_id), "processing"),
            call(UUID(ride_id), "pending", error_message="nats unavailable"),
        ]
    )
    ride_repo.clear_ride_error.assert_awaited_once_with(ride_id)
    ride_repo.increment_reprocess_count.assert_awaited_once_with(ride_id)
