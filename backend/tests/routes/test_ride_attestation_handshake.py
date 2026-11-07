from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock, call, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app.client_contracts import RideStatusResponse
from app.dependencies import AuthenticatedUser
from app.routes.admin import cleanup_stale_ride_media
from app.routes.rides import (
    _derive_attestation_status,
    _delete_ride_storage_objects,
    delete_ride_media,
    get_ride_gps,
    get_ride_patterns,
    get_ride_status,
    get_ride_streams,
    get_ride_tiles,
    reorder_ride_media,
    ride_media_upload_complete,
    ride_media_upload_init,
    update_ride_media,
    upload_complete,
    upload_init,
)
from app.schemas import (
    RideMediaCompleteRequest,
    RideMediaInitRequest,
    RideMediaReorderRequest,
    RideMediaUpdateRequest,
    UploadCompleteRequest,
    UploadInitRequest,
)
from app.services.file_storage import StorageUnavailableError
from app.services.ride_ingest import RideIngestEnqueueResult, RideIngestJob
from app.services.ride_privacy import PrivacySettingsUnavailable, RidePrivacyPolicy
from app.services.ride_provenance_policy import (
    ECONOMIC_GUARDRAIL_FIRST_PARTY_STAMP,
    ECONOMIC_GUARDRAIL_MANUAL_FILE,
    PROVENANCE_TIER_FIRST_PARTY_RECORDED,
    PROVENANCE_TIER_MANUAL_FILE_UPLOAD,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
UPLOAD_HANDSHAKE_FIXTURE = REPO_ROOT / "tests/fixtures/upload_init_handshake_v1.json"


def _default_privacy_policy() -> RidePrivacyPolicy:
    return RidePrivacyPolicy.from_values(
        visibility="public",
        map_visibility="hide_start_end",
        map_hide_start_m=200,
        map_hide_end_m=200,
    )


class UploadDuplicateCandidateRepo:
    def __init__(self, candidates: list[dict[str, str]]) -> None:
        self.candidates = candidates
        self.create_ride = AsyncMock()
        self.update_ride_status = AsyncMock()

    async def find_rides_by_hash(
        self,
        user_id: str,
        file_hash: str,
    ) -> list[dict[str, str]]:
        return self.candidates


class RideDeleteStorageRepo:
    async def list_ride_media(self, ride_id: str, include_uploading: bool = False) -> list[dict]:
        assert ride_id == "ride-1"
        assert include_uploading is True
        return [
            {"storage_path": "ride-media/user-1/ride-1/photo.jpg"},
            {"storage_path": "ride-media/user-1/ride-1/photo.jpg"},
        ]


def test_upload_init_shared_handshake_fixture_matches_backend_schema() -> None:
    fixture = json.loads(UPLOAD_HANDSHAKE_FIXTURE.read_text())
    assert fixture["schema"] == "boulderroller.upload_init_handshake.v1"

    for case in fixture["cases"]:
        source_bytes = (REPO_ROOT / case["source_path"]).read_bytes()
        assert hashlib.sha256(source_bytes).hexdigest() == case["file_hash"]
        assert len(source_bytes) == case["file_size"]

        request = UploadInitRequest.model_validate(case["expected_payload"])
        assert request.file_type == case["file_type"]
        assert request.file_hash == case["file_hash"]
        assert request.file_size == case["file_size"]
        assert request.preliminary_ride_hash == case["preliminary_ride_hash"]
        assert request.parser_version == case["parser_version"]


def test_upload_init_accepts_complete_per_ride_privacy_choice() -> None:
    request = UploadInitRequest.model_validate({
        "file_type": "fit",
        "file_hash": "ab" * 32,
        "file_size": 1234,
        "visibility": "followers",
        "mapVisibility": "hide_start_end",
        "mapHideStartM": 400,
        "mapHideEndM": 800,
    })

    assert request.visibility == "followers"
    assert request.map_visibility == "hide_start_end"
    assert request.map_hide_start_m == 400
    assert request.map_hide_end_m == 800


@pytest.mark.asyncio
async def test_ride_delete_removes_raw_and_media_storage_objects() -> None:
    storage = MagicMock()
    storage.delete_ride_file = AsyncMock(return_value=True)
    storage.delete_photo_files = AsyncMock(return_value=1)

    with patch("app.routes.rides.create_file_storage_service", return_value=storage):
        deleted_count = await _delete_ride_storage_objects(
            {"id": "ride-1", "raw_file_path": "rides/user-1/ride-1.fit"},
            RideDeleteStorageRepo(),
        )

    assert deleted_count == 2
    assert [call.args[0] for call in storage.delete_ride_file.await_args_list] == [
        "rides/user-1/ride-1.fit",
    ]
    storage.delete_photo_files.assert_awaited_once_with("ride-media/user-1/ride-1/photo.jpg")


@pytest.mark.asyncio
async def test_ride_media_upload_roundtrip_persists_and_signs_photo() -> None:
    ride_id = str(uuid4())
    ride_repo = MagicMock()
    ride_repo.get_ride = AsyncMock(return_value={"id": ride_id, "user_id": "user-1"})
    ride_repo.list_ride_media = AsyncMock(return_value=[])
    ride_repo.create_ride_media = AsyncMock()

    storage = MagicMock()
    storage.create_signed_upload_url = AsyncMock(
        return_value={"signed_url": "https://example.test/photo-upload"}
    )

    current_user = AuthenticatedUser(
        wallet="wallet-1",
        user_id="user-1",
        device_id="device-1",
    )

    with patch("app.routes.rides.create_file_storage_service", return_value=storage):
        init_response = await ride_media_upload_init(
            http_request=MagicMock(),
            ride_id=ride_id,
            init_request=RideMediaInitRequest(
                file_name="summit.jpg",
                mime_type="image/jpeg",
                file_size=12345,
                sort_order=0,
                role="cover",
            ),
            current_user=current_user,
            ride_repo=ride_repo,
        )

    assert init_response.media_id
    assert init_response.signed_url == "https://example.test/photo-upload"
    create_kwargs = ride_repo.create_ride_media.await_args.kwargs
    assert create_kwargs["ride_id"] == ride_id
    assert create_kwargs["user_id"] == "user-1"
    assert create_kwargs["mime_type"] == "image/jpeg"
    assert create_kwargs["role"] == "cover"
    assert create_kwargs["storage_path"].startswith(f"ride-media/user-1/{ride_id}/")

    media_row = {
        **create_kwargs,
        "id": init_response.media_id,
        "upload_status": "uploading",
        "moderation_state": "visible",
        "created_at": "2026-05-13T12:00:00Z",
    }
    ready_row = {**media_row, "upload_status": "ready"}
    ride_repo.get_ride_media = AsyncMock(return_value=media_row)
    ride_repo.complete_ride_media_upload = AsyncMock(return_value=ready_row)
    storage.file_exists = AsyncMock(return_value=True)
    storage.get_file_size = AsyncMock(return_value=12345)
    storage.prepare_photo = AsyncMock(return_value=SimpleNamespace(path="sanitized/" + create_kwargs["storage_path"], size_bytes=12345, width=16, height=24, mime_type="image/jpeg"))
    storage.get_signed_url = AsyncMock(return_value="https://example.test/photo-read")

    with patch("app.routes.rides.create_file_storage_service", return_value=storage):
        media = await ride_media_upload_complete(
            http_request=MagicMock(),
            ride_id=ride_id,
            complete_request=RideMediaCompleteRequest(media_id=init_response.media_id),
            current_user=current_user,
            ride_repo=ride_repo,
        )

    assert str(media.id) == init_response.media_id
    assert media.url == "https://example.test/photo-read"
    assert media.role == "cover"
    ride_repo.complete_ride_media_upload.assert_awaited_once_with(
        init_response.media_id,
        ride_id=ride_id,
        storage_path="sanitized/" + create_kwargs["storage_path"],
        size_bytes=12345,
        mime_type="image/jpeg",
        width=16,
        height=24,
    )


@pytest.mark.asyncio
async def test_ride_media_init_reissues_exact_stable_photo_without_duplicate_row() -> None:
    ride_id = str(uuid4())
    media_id = str(uuid4())
    storage_path = f"ride-media/user-1/{ride_id}/{media_id}.jpg"
    ride_repo = MagicMock()
    ride_repo.get_ride = AsyncMock(return_value={"id": ride_id, "user_id": "user-1"})
    ride_repo.get_ride_media = AsyncMock(return_value={
        "id": media_id,
        "ride_id": ride_id,
        "user_id": "user-1",
        "storage_path": storage_path,
        "file_name": "summit.jpg",
        "mime_type": "image/jpeg",
        "size_bytes": 12345,
        "sort_order": 0,
        "role": "cover",
        "upload_status": "uploading",
        "moderation_state": "visible",
    })
    ride_repo.list_ride_media = AsyncMock(return_value=[])
    ride_repo.create_ride_media = AsyncMock()
    storage = MagicMock()
    storage.create_signed_upload_url = AsyncMock(
        return_value={"signed_url": "https://example.test/photo-retry"}
    )

    with patch("app.routes.rides.create_file_storage_service", return_value=storage):
        response = await ride_media_upload_init(
            http_request=MagicMock(),
            ride_id=ride_id,
            init_request=RideMediaInitRequest(
                client_request_id=UUID(media_id),
                file_name="summit.jpg",
                mime_type="image/jpeg",
                file_size=12345,
                sort_order=0,
                role="cover",
            ),
            current_user=AuthenticatedUser(
                wallet="wallet-1", user_id="user-1", device_id="device-1"
            ),
            ride_repo=ride_repo,
        )

    assert response.media_id == media_id
    assert response.signed_url == "https://example.test/photo-retry"
    ride_repo.create_ride_media.assert_not_awaited()
    storage.create_signed_upload_url.assert_awaited_once_with(storage_path)


@pytest.mark.asyncio
async def test_ride_media_complete_keeps_missing_storage_object_retryable() -> None:
    ride_id = str(uuid4())
    media_id = str(uuid4())
    current_user = AuthenticatedUser(
        wallet="wallet-1",
        user_id="user-1",
        device_id="device-1",
    )
    ride_repo = MagicMock()
    ride_repo.get_ride_media = AsyncMock(return_value={
        "id": media_id,
        "ride_id": ride_id,
        "user_id": "user-1",
        "storage_path": f"ride-media/user-1/{ride_id}/{media_id}.jpg",
        "upload_status": "uploading",
        "mime_type": "image/jpeg",
    })
    ride_repo.mark_ride_media_failed = AsyncMock()

    storage = MagicMock()
    from app.services.file_storage import FileNotFoundError
    storage.prepare_photo = AsyncMock(side_effect=FileNotFoundError("absent"))

    with patch("app.routes.rides.create_file_storage_service", return_value=storage):
        with pytest.raises(HTTPException) as exc:
            await ride_media_upload_complete(
                http_request=MagicMock(),
                ride_id=ride_id,
                complete_request=RideMediaCompleteRequest(media_id=media_id),
                current_user=current_user,
                ride_repo=ride_repo,
            )

    assert exc.value.status_code == 400
    ride_repo.mark_ride_media_failed.assert_not_awaited()


@pytest.mark.asyncio
async def test_public_ride_gps_projects_endpoint_hiding_for_non_owner() -> None:
    ride_id = str(uuid4())
    owner_id = str(uuid4())
    repo = MagicMock()
    repo.get_ride = AsyncMock(return_value={
        "id": ride_id,
        "user_id": owner_id,
        "visibility": "public",
        "map_visibility": "hide_start_end",
        "map_hide_start_m": 200,
        "map_hide_end_m": 200,
        "moderation_state": "visible",
    })
    repo.get_gps_track = AsyncMock(return_value=[
        {
            "latitude": 0.0,
            "longitude": index / 1000,
            "timestamp": f"2026-05-14T10:00:0{index}Z",
        }
        for index in range(6)
    ])
    repo._run = AsyncMock(return_value=SimpleNamespace(data=[]))

    response = await get_ride_gps(
        ride_id=ride_id,
        current_user=None,
        repo=repo,  # type: ignore[arg-type]
    )

    assert [point.get("redacted", False) for point in response["gps_points"]] == [
        True,
        True,
        False,
        False,
        True,
        True,
    ]
    assert response["gps_points"][2]["longitude"] == pytest.approx(0.002)
    assert response["gps_points"][3]["longitude"] == pytest.approx(0.003)


@pytest.mark.asyncio
async def test_public_ride_gps_hidden_points_carry_no_elevation_or_time() -> None:
    """A hidden start/end keeps only its position in the sequence: distance and
    the redacted flag. Elevation and time would let a viewer locate it."""
    ride_id = str(uuid4())
    owner_id = str(uuid4())
    ride = {
        "id": ride_id,
        "user_id": owner_id,
        "visibility": "public",
        "map_visibility": "hide_start_end",
        "map_hide_start_m": 200,
        "map_hide_end_m": 200,
        "moderation_state": "visible",
    }
    track = [
        {
            "latitude": 0.0,
            "longitude": index / 1000,
            "timestamp": f"2026-05-14T10:00:0{index}Z",
            "elevation_m": 30.0 + index,
            "elevation_corrected_m": 31.0 + index,
            "distance_m": 111.2 * index,
        }
        for index in range(6)
    ]
    repo = MagicMock()
    repo.get_ride = AsyncMock(return_value=ride)
    repo.get_gps_track = AsyncMock(return_value=[dict(point) for point in track])
    repo._run = AsyncMock(return_value=SimpleNamespace(data=[]))

    response = await get_ride_gps(ride_id=ride_id, current_user=None, repo=repo)  # type: ignore[arg-type]
    points = response["gps_points"]

    for index in (0, 1, 4, 5):
        hidden = points[index]
        assert hidden["redacted"] is True
        for key in ("latitude", "longitude", "timestamp", "elevation_m", "elevation_corrected_m"):
            assert hidden.get(key) is None, (index, key)
        assert hidden["distance_m"] == pytest.approx(111.2 * index)
    for index in (2, 3):
        visible = points[index]
        assert visible.get("redacted", False) is False
        assert visible["timestamp"] == f"2026-05-14T10:00:0{index}Z"
        assert visible["elevation_m"] == pytest.approx(30.0 + index)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stream_type",
    ["power", "heart_rate", "cadence", "speed", "temperature"],
)
async def test_public_ride_streams_redact_exact_samples_for_non_owner_without_querying_storage(
    stream_type: str,
) -> None:
    ride_id = str(uuid4())
    repo = MagicMock()
    repo.get_ride = AsyncMock(return_value={
        "id": ride_id,
        "user_id": str(uuid4()),
        "visibility": "public",
        "moderation_state": "visible",
    })
    repo.get_activity_stream = AsyncMock(return_value={
        "id": str(uuid4()),
        "ride_id": ride_id,
        "stream_type": stream_type,
        "timestamps": [0, 5],
        "values": [998, 999],
        "sample_count": 2,
        "min_value": 998,
        "max_value": 999,
        "avg_value": 998.5,
    })

    response = await get_ride_streams(
        ride_id=ride_id,
        type=stream_type,
        current_user=None,
        repo=repo,  # type: ignore[arg-type]
    )

    expected = {
        "id": None,
        "ride_id": ride_id,
        "stream_type": stream_type,
        "timestamps": [],
        "values": [],
        "sample_count": 0,
        "min_value": None,
        "max_value": None,
        "avg_value": None,
        "redacted": True,
    }
    assert {
        "response": response,
        "storage_query_count": repo.get_activity_stream.await_count,
    } == {
        "response": expected,
        "storage_query_count": 0,
    }
    repo.get_activity_stream.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("visibility", "moderation_state", "follows", "expected_status"),
    [
        ("followers", "visible", True, 200),
        ("followers", "visible", False, 404),
        ("private", "visible", False, 404),
        ("public", "hidden", False, 404),
        ("public", "removed", False, 404),
    ],
)
async def test_non_owner_ride_streams_preserve_visibility_and_moderation_boundary(
    visibility: str,
    moderation_state: str,
    follows: bool,
    expected_status: int,
) -> None:
    ride_id = str(uuid4())
    owner_id = str(uuid4())
    viewer_id = str(uuid4())
    current_user = AuthenticatedUser(
        wallet="viewer-wallet",
        user_id=viewer_id,
        device_id="viewer-device",
    )
    repo = MagicMock()
    repo.get_ride = AsyncMock(return_value={
        "id": ride_id,
        "user_id": owner_id,
        "visibility": visibility,
        "moderation_state": moderation_state,
    })
    repo.get_follow = AsyncMock(return_value=follows)
    repo.get_activity_stream = AsyncMock(return_value={
        "ride_id": ride_id,
        "stream_type": "power",
        "timestamps": [0, 5],
        "values": [998, 999],
        "sample_count": 2,
    })

    if expected_status == 200:
        response = await get_ride_streams(
            ride_id=ride_id,
            type="power",
            current_user=current_user,
            repo=repo,  # type: ignore[arg-type]
        )
        assert response == {
            "id": None,
            "ride_id": ride_id,
            "stream_type": "power",
            "timestamps": [],
            "values": [],
            "sample_count": 0,
            "min_value": None,
            "max_value": None,
            "avg_value": None,
            "redacted": True,
        }
    else:
        with pytest.raises(HTTPException) as exc:
            await get_ride_streams(
                ride_id=ride_id,
                type="power",
                current_user=current_user,
                repo=repo,  # type: ignore[arg-type]
            )
        assert exc.value.status_code == expected_status

    if visibility == "followers" and moderation_state == "visible":
        repo.get_follow.assert_awaited_once_with(viewer_id, owner_id)
    else:
        repo.get_follow.assert_not_awaited()
    repo.get_activity_stream.assert_not_awaited()


@pytest.mark.asyncio
async def test_public_ride_patterns_redact_route_reconstruction_fields_for_non_owner() -> None:
    ride_id = str(uuid4())
    repo = MagicMock()
    repo.get_ride = AsyncMock(return_value={
        "id": ride_id,
        "user_id": str(uuid4()),
        "visibility": "public",
        "moderation_state": "visible",
    })
    repo.get_patterns_for_activity = AsyncMock(return_value={
        "climb_patterns": [{
            "id": "pattern-1",
            "wallet": "owner-wallet",
            "vert_m": 120,
            "time_s": 600,
            "start_lat": 39.95,
            "start_lon": -75.17,
            "end_lat": 39.96,
            "end_lon": -75.16,
            "tile_ids": ["892a"],
            "start_offset_s": 10,
            "end_offset_s": 610,
            "signature_hex": "ab" * 32,
            "match_trace": {
                "canon_id": "22222222-2222-4222-8222-222222222222",
                "gate_crossings": {
                    "start": {
                        "point": {"lat": 39.95, "lon": -75.17},
                        "bracketing_samples": {
                            "start": {"lat": 39.949, "lon": -75.171, "t_s": 9.5},
                            "end": {"lat": 39.951, "lon": -75.169, "t_s": 10.5},
                        },
                    }
                },
                "corridor_coverage_pct": 100.0,
            },
        }],
        "steady_pattern": {"duration_s": 900, "start_offset_s": 30, "tile_ids": ["892b"]},
        "exploration_pattern": {"new_tiles_wallet": 3, "tile_ids": ["892c"]},
    })

    response = await get_ride_patterns(
        ride_id=ride_id,
        current_user=None,
        repo=repo,  # type: ignore[arg-type]
    )

    climb = response["patterns"]["climb_patterns"][0]
    assert climb["duration_s"] == 600
    assert climb["vam"] == 720.0
    assert "start_lat" not in climb
    assert "startLat" not in climb
    assert "startOffsetS" not in climb
    assert "tileIds" not in climb
    assert "wallet" not in climb
    assert "signatureHex" not in climb
    assert "match_trace" not in climb
    assert "tile_ids" not in response["patterns"]["steady_pattern"]
    assert "tile_ids" not in response["patterns"]["exploration_pattern"]


@pytest.mark.asyncio
async def test_public_ride_tiles_redact_samples_for_non_owner_without_querying_tiles() -> None:
    ride_id = str(uuid4())
    repo = MagicMock()
    repo.get_ride = AsyncMock(return_value={
        "id": ride_id,
        "user_id": str(uuid4()),
        "visibility": "public",
        "moderation_state": "visible",
    })
    repo._run = AsyncMock()

    response = await get_ride_tiles(
        ride_id=ride_id,
        current_user=None,
        repo=repo,  # type: ignore[arg-type]
    )

    assert response == {
        "ride_id": ride_id,
        "tile_samples": [],
        "total_samples": 0,
        "unique_tiles": 0,
        "redacted": True,
    }
    repo._run.assert_not_awaited()


@pytest.mark.asyncio
async def test_ride_media_owner_controls_cover_reorder_and_delete() -> None:
    ride_id = str(uuid4())
    media_id = str(uuid4())
    other_media_id = str(uuid4())
    current_user = AuthenticatedUser(
        wallet="wallet-1",
        user_id="user-1",
        device_id="device-1",
    )
    media_row = {
        "id": media_id,
        "ride_id": ride_id,
        "user_id": "user-1",
        "storage_path": f"ride-media/user-1/{ride_id}/{media_id}.jpg",
        "file_name": "summit.jpg",
        "mime_type": "image/jpeg",
        "size_bytes": 12345,
        "sort_order": 1,
        "role": "photo",
        "upload_status": "ready",
        "moderation_state": "visible",
        "created_at": "2026-05-13T12:00:00Z",
    }
    other_media_row = {
        **media_row,
        "id": other_media_id,
        "storage_path": f"ride-media/user-1/{ride_id}/{other_media_id}.jpg",
        "sort_order": 0,
    }

    ride_repo = MagicMock()
    ride_repo.get_ride = AsyncMock(return_value={"id": ride_id, "user_id": "user-1"})
    ride_repo.get_ride_media = AsyncMock(return_value=media_row)
    ride_repo.list_ride_media = AsyncMock(return_value=[media_row, other_media_row])
    ride_repo.reorder_ride_media = AsyncMock(return_value=[other_media_row, media_row])
    ride_repo.set_ride_media_cover = AsyncMock(return_value={**media_row, "role": "cover", "sort_order": 0})
    ride_repo.delete_ride_media = AsyncMock()

    storage = MagicMock()
    storage.get_signed_url = AsyncMock(return_value="https://example.test/photo-read")
    storage.delete_photo_files = AsyncMock(return_value=True)

    with patch("app.ride_media_contracts.create_file_storage_service", return_value=storage):
        reordered = await reorder_ride_media(
            ride_id=ride_id,
            reorder_request=RideMediaReorderRequest.model_validate({
                "items": [
                    {"mediaId": other_media_id, "sortOrder": 0},
                    {"mediaId": media_id, "sortOrder": 1},
                ]
            }),
            current_user=current_user,
            ride_repo=ride_repo,
        )

        cover = await update_ride_media(
            ride_id=ride_id,
            media_id=media_id,
            update_request=RideMediaUpdateRequest(role="cover"),
            current_user=current_user,
            ride_repo=ride_repo,
        )

    assert [str(item.id) for item in reordered] == [other_media_id, media_id]
    assert cover.role == "cover"
    ride_repo.reorder_ride_media.assert_awaited_once_with(
        ride_id,
        {other_media_id: 0, media_id: 1},
    )
    ride_repo.set_ride_media_cover.assert_awaited_once_with(ride_id=ride_id, media_id=media_id)

    ride_repo.get_ride_media.return_value = {**media_row, "role": "cover"}
    ride_repo.list_ride_media.return_value = [other_media_row]

    with patch("app.routes.rides.create_file_storage_service", return_value=storage):
        deleted = await delete_ride_media(
            ride_id=ride_id,
            media_id=media_id,
            current_user=current_user,
            ride_repo=ride_repo,
        )
    assert deleted == {"status": "deleted", "mediaId": media_id}
    storage.delete_photo_files.assert_awaited_once_with(media_row["storage_path"])
    ride_repo.delete_ride_media.assert_awaited_once_with(media_id)
    assert ride_repo.set_ride_media_cover.await_args_list[-1].kwargs == {
        "ride_id": ride_id,
        "media_id": other_media_id,
    }


@pytest.mark.asyncio
async def test_empty_ride_media_reorder_checks_owner_before_serializing() -> None:
    ride_id = str(uuid4())
    current_user = AuthenticatedUser(
        wallet="wallet-2",
        user_id="user-2",
        device_id="device-2",
    )
    ride_repo = MagicMock()
    ride_repo.get_ride = AsyncMock(return_value={"id": ride_id, "user_id": "user-1"})
    ride_repo.list_ride_media = AsyncMock(return_value=[
        {
            "id": str(uuid4()),
            "ride_id": ride_id,
            "user_id": "user-1",
            "storage_path": f"ride-media/user-1/{ride_id}/photo.jpg",
            "mime_type": "image/jpeg",
            "size_bytes": 12345,
            "upload_status": "ready",
            "moderation_state": "visible",
        }
    ])

    with pytest.raises(HTTPException) as exc:
        await reorder_ride_media(
            ride_id=ride_id,
            reorder_request=RideMediaReorderRequest.model_validate({"items": []}),
            current_user=current_user,
            ride_repo=ride_repo,
        )

    assert exc.value.status_code == 403
    ride_repo.list_ride_media.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_ride_media_cleanup_deletes_rows_and_storage_objects() -> None:
    media_id = str(uuid4())
    ride_repo = MagicMock()
    ride_repo.list_stale_ride_media_uploads = AsyncMock(
        return_value=[
            {
                "id": media_id,
                "storage_path": "ride-media/user-1/ride-1/photo.jpg",
            },
        ]
    )
    ride_repo.delete_ride_media = AsyncMock()

    storage = MagicMock()
    storage.delete_photo_files = AsyncMock(return_value=1)

    with patch("app.routes.admin.create_file_storage_service", return_value=storage):
        response = await cleanup_stale_ride_media(
            request=MagicMock(),
            older_than_hours=2,
            limit=50,
            admin_ctx=(uuid4(), "admin"),
            ride_repo=ride_repo,
        )

    assert response.scanned == 1
    assert response.deleted_rows == 1
    assert response.deleted_objects == 1
    assert response.failed == 0
    ride_repo.list_stale_ride_media_uploads.assert_awaited_once()
    ride_repo.delete_ride_media.assert_awaited_once_with(media_id)
    storage.delete_photo_files.assert_awaited_once_with("ride-media/user-1/ride-1/photo.jpg")


@pytest.mark.asyncio
async def test_upload_init_persists_preliminary_attestation_fields() -> None:
    ride_repo = MagicMock()
    ride_repo.find_ride_by_hash = AsyncMock(return_value=None)
    ride_repo.create_ride = AsyncMock()
    ride_repo.resolve_ride_privacy_policy = AsyncMock(return_value=_default_privacy_policy())

    storage = MagicMock()
    storage.create_signed_upload_url = AsyncMock(
        return_value={"signed_url": "https://example.test/upload"}
    )

    current_user = AuthenticatedUser(
        wallet="wallet-1",
        user_id="user-1",
        device_id="device-1",
    )

    with patch("app.routes.rides.create_file_storage_service", return_value=storage):
        response = await upload_init(
            http_request=MagicMock(),
            init_request=UploadInitRequest(
                file_type="fit",
                file_hash="ab" * 32,
                file_size=1234,
                preliminary_ride_hash="cd" * 32,
                parser_version=1,
                visibility="public",
                map_visibility="hide_start_end",
                map_hide_start_m=200,
                map_hide_end_m=200,
            ),
            force=False,
            current_user=current_user,
            ride_repo=ride_repo,
        )

    assert response.upload_id
    assert response.signed_url == "https://example.test/upload"
    ride_repo.create_ride.assert_awaited_once()
    kwargs = ride_repo.create_ride.await_args.kwargs
    assert kwargs["preliminary_ride_hash_hex"] == "cd" * 32
    assert kwargs["preliminary_parser_version"] == 1
    assert kwargs["privacy_policy"].to_storage_dict() == _default_privacy_policy().to_storage_dict()


@pytest.mark.asyncio
async def test_upload_init_blocks_before_storage_when_privacy_defaults_are_unavailable() -> None:
    ride_repo = MagicMock()
    ride_repo.find_ride_by_hash = AsyncMock(return_value=None)
    ride_repo.resolve_ride_privacy_policy = AsyncMock(
        side_effect=PrivacySettingsUnavailable("database unavailable")
    )
    ride_repo.create_ride = AsyncMock()

    with patch("app.routes.rides.create_file_storage_service") as storage_factory:
        with pytest.raises(HTTPException) as exc:
            await upload_init(
                http_request=MagicMock(),
                init_request=UploadInitRequest(
                    file_type="fit",
                    file_hash="ab" * 32,
                    file_size=1234,
                ),
                force=False,
                current_user=AuthenticatedUser(
                    wallet="wallet-1",
                    user_id="user-1",
                    device_id="device-1",
                ),
                ride_repo=ride_repo,
            )

    assert exc.value.status_code == 503
    storage_factory.assert_not_called()
    ride_repo.create_ride.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_init_records_pre_economy_client_timestamp_for_warning() -> None:
    ride_repo = MagicMock()
    ride_repo.find_ride_by_hash = AsyncMock(return_value=None)
    ride_repo.create_ride = AsyncMock()
    ride_repo.resolve_ride_privacy_policy = AsyncMock(return_value=_default_privacy_policy())

    storage = MagicMock()
    storage.create_signed_upload_url = AsyncMock(
        return_value={"signed_url": "https://example.test/upload"}
    )

    current_user = AuthenticatedUser(
        wallet="wallet-1",
        user_id="user-1",
        device_id="device-1",
    )

    with patch("app.routes.rides.create_file_storage_service", return_value=storage):
        response = await upload_init(
            http_request=MagicMock(),
            init_request=UploadInitRequest(
                file_type="fit",
                file_hash="ab" * 32,
                file_size=1234,
                client_completed_at=datetime(2015, 6, 26, 12, 0, tzinfo=timezone.utc),
            ),
            force=False,
            current_user=current_user,
            ride_repo=ride_repo,
        )

    assert response.upload_id
    ride_repo.create_ride.assert_awaited_once()
    diagnostics = ride_repo.create_ride.await_args.kwargs["import_diagnostics"]
    assert diagnostics["client_completed_at"] == "2015-06-26T12:00:00+00:00"
    assert diagnostics["pre_economy_activity"] is True
    assert diagnostics["economy_review_reason"] == "activity_before_economy_start"
    assert diagnostics["provenance_tier"] == PROVENANCE_TIER_MANUAL_FILE_UPLOAD
    assert diagnostics["ingest_source"] == PROVENANCE_TIER_MANUAL_FILE_UPLOAD
    assert diagnostics["economic_guardrail_profile"] == ECONOMIC_GUARDRAIL_MANUAL_FILE
    assert diagnostics["preliminary_attestation_required"] is False
    assert diagnostics["preliminary_ride_hash_present"] is False
    assert diagnostics["preliminary_parser_version_present"] is False
    assert "missing_preliminary_attestation" not in diagnostics


def _stable_upload_row(
    request_id: UUID,
    *,
    user_id: str = "user-stable",
    processing_status: str = "uploading",
    file_size: int = 1234,
) -> dict[str, object]:
    return {
        "id": str(request_id),
        "user_id": user_id,
        "processing_status": processing_status,
        "file_type": "gpx",
        "raw_file_path": f"rides/{user_id}/{request_id}.gpx",
        "raw_file_size_bytes": file_size,
        "file_hash": "ab" * 32,
        "preliminary_ride_hash_hex": "cd" * 32,
        "preliminary_parser_version": 1,
        "visibility": "private",
        "map_visibility": "hide_entire",
        "map_hide_start_m": 0,
        "map_hide_end_m": 0,
    }


def _stable_upload_request(request_id: UUID, *, file_size: int = 1234) -> UploadInitRequest:
    return UploadInitRequest.model_validate(
        {
            "clientRequestId": str(request_id),
            "file_type": "gpx",
            "file_hash": "ab" * 32,
            "file_size": file_size,
            "preliminary_ride_hash": "cd" * 32,
            "parser_version": 1,
            "visibility": "private",
            "mapVisibility": "hide_entire",
            "mapHideStartM": 0,
            "mapHideEndM": 0,
        }
    )


@pytest.mark.asyncio
async def test_upload_init_reissues_exact_stable_upload_without_mutating_row() -> None:
    request_id = uuid4()
    ride_repo = MagicMock()
    ride_repo.get_ride = AsyncMock(return_value=_stable_upload_row(request_id))
    ride_repo.create_ride = AsyncMock()
    ride_repo.update_ride_status = AsyncMock()
    ride_repo.resolve_ride_privacy_policy = AsyncMock()

    storage = MagicMock()
    storage.create_signed_upload_url = AsyncMock(
        return_value={"signed_url": "https://example.test/reissued"}
    )
    current_user = AuthenticatedUser(
        wallet="wallet-stable",
        user_id="user-stable",
        device_id="device-stable",
    )

    with patch("app.routes.rides.create_file_storage_service", return_value=storage):
        response = await upload_init(
            http_request=MagicMock(),
            init_request=_stable_upload_request(request_id),
            force=False,
            current_user=current_user,
            ride_repo=ride_repo,
        )

    assert response.upload_id == str(request_id)
    assert response.signed_url == "https://example.test/reissued"
    storage.create_signed_upload_url.assert_awaited_once_with(
        f"rides/user-stable/{request_id}.gpx"
    )
    ride_repo.create_ride.assert_not_awaited()
    ride_repo.update_ride_status.assert_not_awaited()
    ride_repo.resolve_ride_privacy_policy.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_init_stable_id_rejects_changed_input_without_storage_access() -> None:
    request_id = uuid4()
    ride_repo = MagicMock()
    ride_repo.get_ride = AsyncMock(return_value=_stable_upload_row(request_id))

    with patch("app.routes.rides.create_file_storage_service") as storage_factory:
        with pytest.raises(HTTPException) as exc:
            await upload_init(
                http_request=MagicMock(),
                init_request=_stable_upload_request(request_id, file_size=4321),
                force=False,
                current_user=AuthenticatedUser(
                    wallet="wallet-stable",
                    user_id="user-stable",
                    device_id="device-stable",
                ),
                ride_repo=ride_repo,
            )

    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "upload_request_mismatch"
    assert exc.value.detail["existing_ride_id"] == str(request_id)
    assert exc.value.detail["existing_status"] == "uploading"
    storage_factory.assert_not_called()


@pytest.mark.asyncio
async def test_upload_init_stable_id_hides_other_rider_row() -> None:
    request_id = uuid4()
    ride_repo = MagicMock()
    ride_repo.get_ride = AsyncMock(
        return_value=_stable_upload_row(request_id, user_id="another-user")
    )

    with patch("app.routes.rides.create_file_storage_service") as storage_factory:
        with pytest.raises(HTTPException) as exc:
            await upload_init(
                http_request=MagicMock(),
                init_request=_stable_upload_request(request_id),
                force=False,
                current_user=AuthenticatedUser(
                    wallet="wallet-stable",
                    user_id="user-stable",
                    device_id="device-stable",
                ),
                ride_repo=ride_repo,
            )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Upload not found"
    storage_factory.assert_not_called()


@pytest.mark.asyncio
async def test_upload_init_stable_id_reports_later_status_for_reconciliation() -> None:
    request_id = uuid4()
    ride_repo = MagicMock()
    ride_repo.get_ride = AsyncMock(
        return_value=_stable_upload_row(request_id, processing_status="processing")
    )

    with patch("app.routes.rides.create_file_storage_service") as storage_factory:
        with pytest.raises(HTTPException) as exc:
            await upload_init(
                http_request=MagicMock(),
                init_request=_stable_upload_request(request_id),
                force=False,
                current_user=AuthenticatedUser(
                    wallet="wallet-stable",
                    user_id="user-stable",
                    device_id="device-stable",
                ),
                ride_repo=ride_repo,
            )

    assert exc.value.status_code == 409
    assert exc.value.detail == {
        "error": "upload_already_initialized",
        "message": "This upload has already moved beyond file transfer.",
        "existing_ride_id": str(request_id),
        "existing_status": "processing",
    }
    storage_factory.assert_not_called()


@pytest.mark.asyncio
async def test_upload_init_storage_outage_leaves_stable_upload_retryable() -> None:
    request_id = uuid4()
    ride_repo = MagicMock()
    ride_repo.get_ride = AsyncMock(
        side_effect=[None, _stable_upload_row(request_id)]
    )
    ride_repo.find_ride_by_hash = AsyncMock(return_value=None)
    ride_repo.create_ride = AsyncMock()
    ride_repo.update_ride_status = AsyncMock()
    ride_repo.resolve_ride_privacy_policy = AsyncMock(
        return_value=RidePrivacyPolicy.from_values(
            visibility="private",
            map_visibility="hide_entire",
            map_hide_start_m=0,
            map_hide_end_m=0,
        )
    )

    storage = MagicMock()
    storage.create_signed_upload_url = AsyncMock(
        side_effect=[
            StorageUnavailableError("temporarily unavailable"),
            {"signed_url": "https://example.test/recovered"},
        ]
    )
    current_user = AuthenticatedUser(
        wallet="wallet-stable",
        user_id="user-stable",
        device_id="device-stable",
    )

    with patch("app.routes.rides.create_file_storage_service", return_value=storage):
        with pytest.raises(HTTPException) as exc:
            await upload_init(
                http_request=MagicMock(),
                init_request=_stable_upload_request(request_id),
                force=False,
                current_user=current_user,
                ride_repo=ride_repo,
            )
        recovered = await upload_init(
            http_request=MagicMock(),
            init_request=_stable_upload_request(request_id),
            force=False,
            current_user=current_user,
            ride_repo=ride_repo,
        )

    assert exc.value.status_code == 503
    assert recovered.upload_id == str(request_id)
    assert recovered.signed_url == "https://example.test/recovered"
    ride_repo.create_ride.assert_awaited_once()
    assert ride_repo.create_ride.await_args.kwargs["ride_id"] == str(request_id)
    assert ride_repo.create_ride.await_args.kwargs["raw_file_path"] == (
        f"rides/user-stable/{request_id}.gpx"
    )
    ride_repo.update_ride_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_complete_replay_returns_current_status_without_second_enqueue() -> None:
    upload_id = str(uuid4())
    ride_repo = MagicMock()
    ride_repo.get_ride = AsyncMock(
        return_value={
            "id": upload_id,
            "user_id": "user-stable",
            "processing_status": "processing",
        }
    )
    ride_repo.transition_ride_status = AsyncMock()
    current_user = AuthenticatedUser(
        wallet="wallet-stable",
        user_id="user-stable",
        device_id="device-stable",
    )

    with (
        patch("app.routes.rides.create_file_storage_service") as storage_factory,
        patch("app.routes.rides.enqueue_ride_ingest", new_callable=AsyncMock) as enqueue,
    ):
        response = await upload_complete(
            http_request=MagicMock(),
            complete_request=UploadCompleteRequest(upload_id=upload_id),
            current_user=current_user,
            ride_repo=ride_repo,
            user_repo=MagicMock(),
        )

    assert response.ride_id == upload_id
    assert response.status == "processing"
    storage_factory.assert_not_called()
    enqueue.assert_not_awaited()
    ride_repo.transition_ride_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_complete_hides_other_rider_job_on_replay() -> None:
    upload_id = str(uuid4())
    ride_repo = MagicMock()
    ride_repo.get_ride = AsyncMock(
        return_value={
            "id": upload_id,
            "user_id": "another-user",
            "processing_status": "pending",
        }
    )
    ride_repo.transition_ride_status = AsyncMock()

    with (
        patch("app.routes.rides.create_file_storage_service") as storage_factory,
        patch("app.routes.rides.enqueue_ride_ingest", new_callable=AsyncMock) as enqueue,
    ):
        with pytest.raises(HTTPException) as exc:
            await upload_complete(
                http_request=MagicMock(),
                complete_request=UploadCompleteRequest(upload_id=upload_id),
                current_user=AuthenticatedUser(
                    wallet="wallet-stable",
                    user_id="user-stable",
                    device_id="device-stable",
                ),
                ride_repo=ride_repo,
                user_repo=MagicMock(),
            )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Upload not found"
    storage_factory.assert_not_called()
    enqueue.assert_not_awaited()
    ride_repo.transition_ride_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_complete_missing_object_returns_stable_retry_code() -> None:
    upload_id = uuid4()
    ride_repo = MagicMock()
    ride_repo.get_ride = AsyncMock(return_value=_stable_upload_row(upload_id))
    ride_repo.transition_ride_status = AsyncMock()
    storage = MagicMock()
    storage.file_exists = AsyncMock(return_value=False)

    with patch("app.routes.rides.create_file_storage_service", return_value=storage):
        with pytest.raises(HTTPException) as exc:
            await upload_complete(
                http_request=MagicMock(),
                complete_request=UploadCompleteRequest(upload_id=str(upload_id)),
                current_user=AuthenticatedUser(
                    wallet="wallet-stable",
                    user_id="user-stable",
                    device_id="device-stable",
                ),
                ride_repo=ride_repo,
                user_repo=MagicMock(),
            )

    assert exc.value.status_code == 400
    assert exc.value.detail == {
        "error": "file_missing",
        "message": "File not found in storage. Upload may have failed or expired.",
    }
    ride_repo.transition_ride_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_complete_pending_replay_enqueues_and_advances_after_acceptance() -> None:
    upload_id = uuid4()
    ride_repo = MagicMock()
    ride_repo.get_ride = AsyncMock(
        return_value=_stable_upload_row(upload_id, processing_status="pending")
    )
    ride_repo.transition_ride_status = AsyncMock(return_value=True)
    user_repo = MagicMock()
    user_repo.get_user_profile = AsyncMock(
        return_value={"weight_kg": 72.5, "ftp_w": 275}
    )
    enqueue = AsyncMock(
        return_value=RideIngestEnqueueResult(accepted=True, backend="nats")
    )

    with (
        patch("app.routes.rides.create_file_storage_service") as storage_factory,
        patch("app.routes.rides.enqueue_ride_ingest", enqueue),
    ):
        response = await upload_complete(
            http_request=MagicMock(),
            complete_request=UploadCompleteRequest(upload_id=str(upload_id)),
            current_user=AuthenticatedUser(
                wallet="wallet-stable",
                user_id="user-stable",
                device_id="device-stable",
            ),
            ride_repo=ride_repo,
            user_repo=user_repo,
        )

    assert response.status == "processing"
    storage_factory.assert_not_called()
    enqueue.assert_awaited_once()
    assert enqueue.await_args.args[0] == RideIngestJob(
        ride_id=str(upload_id),
        wallet="wallet-stable",
        user_id="user-stable",
        file_type="gpx",
        file_path=f"rides/user-stable/{upload_id}.gpx",
        user_weight_kg=72.5,
        source="manual_upload_direct",
    )
    ride_repo.transition_ride_status.assert_awaited_once_with(
        upload_id,
        expected_status="pending",
        new_status="processing",
    )


@pytest.mark.asyncio
async def test_upload_complete_pending_replay_queue_failure_remains_pending() -> None:
    upload_id = uuid4()
    ride_repo = MagicMock()
    ride_repo.get_ride = AsyncMock(
        return_value=_stable_upload_row(upload_id, processing_status="pending")
    )
    ride_repo.transition_ride_status = AsyncMock(return_value=True)
    user_repo = MagicMock()
    user_repo.get_user_profile = AsyncMock(return_value=None)
    enqueue = AsyncMock(
        return_value=RideIngestEnqueueResult(
            accepted=False,
            backend="nats",
            error="NATS unavailable",
        )
    )

    with (
        patch("app.routes.rides.create_file_storage_service") as storage_factory,
        patch("app.routes.rides.enqueue_ride_ingest", enqueue),
    ):
        response = await upload_complete(
            http_request=MagicMock(),
            complete_request=UploadCompleteRequest(upload_id=str(upload_id)),
            current_user=AuthenticatedUser(
                wallet="wallet-stable",
                user_id="user-stable",
                device_id="device-stable",
            ),
            ride_repo=ride_repo,
            user_repo=user_repo,
        )

    assert response.status == "pending"
    storage_factory.assert_not_called()
    enqueue.assert_awaited_once()
    ride_repo.transition_ride_status.assert_awaited_once_with(
        upload_id,
        expected_status="pending",
        new_status="pending",
        error_message="NATS unavailable",
    )


@pytest.mark.asyncio
async def test_upload_complete_crash_after_verification_replays_durable_pending_job() -> None:
    upload_id = uuid4()
    uploading_row = _stable_upload_row(upload_id, processing_status="uploading")
    pending_row = _stable_upload_row(upload_id, processing_status="pending")
    ride_repo = MagicMock()
    ride_repo.get_ride = AsyncMock(side_effect=[uploading_row, pending_row])
    ride_repo.transition_ride_status = AsyncMock(side_effect=[True, True])

    storage = MagicMock()
    storage.file_exists = AsyncMock(return_value=True)
    storage.get_file_size = AsyncMock(return_value=1234)
    storage.download_ride_file = AsyncMock(return_value=b"uploaded ride bytes")
    storage.compute_file_hash = MagicMock(return_value="ab" * 32)

    user_repo = MagicMock()
    user_repo.get_user_profile = AsyncMock(return_value=None)
    enqueue = AsyncMock(
        side_effect=[
            RuntimeError("process interrupted after durable pending transition"),
            RideIngestEnqueueResult(accepted=True, backend="nats"),
        ]
    )
    current_user = AuthenticatedUser(
        wallet="wallet-stable",
        user_id="user-stable",
        device_id="device-stable",
    )

    with (
        patch("app.routes.rides.create_file_storage_service", return_value=storage),
        patch("app.routes.rides.enqueue_ride_ingest", enqueue),
    ):
        with pytest.raises(RuntimeError, match="process interrupted"):
            await upload_complete(
                http_request=MagicMock(),
                complete_request=UploadCompleteRequest(upload_id=str(upload_id)),
                current_user=current_user,
                ride_repo=ride_repo,
                user_repo=user_repo,
            )
        recovered = await upload_complete(
            http_request=MagicMock(),
            complete_request=UploadCompleteRequest(upload_id=str(upload_id)),
            current_user=current_user,
            ride_repo=ride_repo,
            user_repo=user_repo,
        )

    assert recovered.status == "processing"
    storage.file_exists.assert_awaited_once()
    storage.download_ride_file.assert_awaited_once()
    assert enqueue.await_count == 2
    assert enqueue.await_args_list[0].args[0] == enqueue.await_args_list[1].args[0]
    assert ride_repo.transition_ride_status.await_args_list == [
        call(
            upload_id,
            expected_status="uploading",
            new_status="pending",
            upload_verified_at=ANY,
        ),
        call(
            upload_id,
            expected_status="pending",
            new_status="processing",
        ),
    ]


@pytest.mark.asyncio
async def test_upload_init_allows_retry_after_stranded_uploading_duplicate() -> None:
    stranded_upload_id = str(uuid4())
    ride_repo = MagicMock()
    ride_repo.find_ride_by_hash = AsyncMock(
        return_value={
            "id": stranded_upload_id,
            "processing_status": "uploading",
            "uploaded_at": "2026-05-06T16:00:00Z",
        }
    )
    ride_repo.create_ride = AsyncMock()
    ride_repo.update_ride_status = AsyncMock()
    ride_repo.resolve_ride_privacy_policy = AsyncMock(return_value=_default_privacy_policy())

    storage = MagicMock()
    storage.create_signed_upload_url = AsyncMock(
        return_value={"signed_url": "https://example.test/upload"}
    )

    current_user = AuthenticatedUser(
        wallet="wallet-1",
        user_id="user-1",
        device_id="device-1",
    )

    with patch("app.routes.rides.create_file_storage_service", return_value=storage):
        response = await upload_init(
            http_request=MagicMock(),
            init_request=UploadInitRequest(
                file_type="gpx",
                file_hash="ab" * 32,
                file_size=1234,
            ),
            force=False,
            current_user=current_user,
            ride_repo=ride_repo,
        )

    assert response.upload_id
    ride_repo.update_ride_status.assert_awaited_once_with(
        UUID(stranded_upload_id),
        "failed",
        error_message="Superseded by retry before upload completed",
    )
    ride_repo.create_ride.assert_awaited_once()


@pytest.mark.asyncio
async def test_upload_init_reports_completed_duplicate_with_existing_status() -> None:
    existing_ride_id = str(uuid4())
    ride_repo = MagicMock()
    ride_repo.find_ride_by_hash = AsyncMock(
        return_value={
            "id": existing_ride_id,
            "processing_status": "completed",
            "uploaded_at": "2026-05-06T16:00:00Z",
        }
    )
    ride_repo.create_ride = AsyncMock()

    current_user = AuthenticatedUser(
        wallet="wallet-1",
        user_id="user-1",
        device_id="device-1",
    )

    with pytest.raises(HTTPException) as exc_info:
        await upload_init(
            http_request=MagicMock(),
            init_request=UploadInitRequest(
                file_type="gpx",
                file_hash="ab" * 32,
                file_size=1234,
            ),
            force=False,
            current_user=current_user,
            ride_repo=ride_repo,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error"] == "duplicate_file"
    assert exc_info.value.detail["message"] == "This file has already been uploaded."
    assert exc_info.value.detail["existing_ride_id"] == existing_ride_id
    assert exc_info.value.detail["existing_status"] == "completed"
    ride_repo.create_ride.assert_not_called()


@pytest.mark.asyncio
async def test_upload_init_completed_duplicate_wins_over_newer_failed_attempt() -> None:
    failed_attempt_id = str(uuid4())
    completed_ride_id = str(uuid4())
    ride_repo = UploadDuplicateCandidateRepo(
        [
            {
                "id": failed_attempt_id,
                "processing_status": "failed",
                "uploaded_at": "2026-05-06T16:10:00Z",
            },
            {
                "id": completed_ride_id,
                "processing_status": "completed",
                "uploaded_at": "2026-05-06T16:00:00Z",
            },
        ]
    )

    current_user = AuthenticatedUser(
        wallet="wallet-1",
        user_id="user-1",
        device_id="device-1",
    )

    with pytest.raises(HTTPException) as exc_info:
        await upload_init(
            http_request=MagicMock(),
            init_request=UploadInitRequest(
                file_type="gpx",
                file_hash="ab" * 32,
                file_size=1234,
            ),
            force=False,
            current_user=current_user,
            ride_repo=ride_repo,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["existing_ride_id"] == completed_ride_id
    assert exc_info.value.detail["existing_status"] == "completed"
    ride_repo.create_ride.assert_not_called()
    ride_repo.update_ride_status.assert_not_called()


@pytest.mark.asyncio
async def test_upload_init_complete_queue_and_status_preserve_attestation_boundary() -> None:
    ride_repo = MagicMock()
    ride_repo.find_ride_by_hash = AsyncMock(return_value=None)
    ride_repo.create_ride = AsyncMock()
    ride_repo.update_ride_status = AsyncMock()
    ride_repo.resolve_ride_privacy_policy = AsyncMock(return_value=_default_privacy_policy())

    storage = MagicMock()
    storage.create_signed_upload_url = AsyncMock(
        return_value={"signed_url": "https://example.test/upload"}
    )
    storage.file_exists = AsyncMock(return_value=True)
    storage.get_file_size = AsyncMock(return_value=4321)
    storage.download_ride_file = AsyncMock(return_value=b"uploaded ride bytes")
    storage.compute_file_hash = MagicMock(return_value="ab" * 32)

    user_repo = MagicMock()
    user_repo.get_user_profile = AsyncMock(return_value={"weight_kg": 72.5})

    current_user = AuthenticatedUser(
        wallet="wallet-queue",
        user_id="user-queue",
        device_id="device-queue",
    )

    with patch("app.routes.rides.create_file_storage_service", return_value=storage):
        init_response = await upload_init(
            http_request=MagicMock(),
            init_request=UploadInitRequest(
                file_type="gpx",
                file_hash="ab" * 32,
                file_size=4321,
                preliminary_ride_hash="cd" * 32,
                parser_version=1,
            ),
            force=False,
            current_user=current_user,
            ride_repo=ride_repo,
        )

    init_kwargs = ride_repo.create_ride.await_args.kwargs
    diagnostics = init_kwargs["import_diagnostics"]
    assert diagnostics["provenance_tier"] == PROVENANCE_TIER_FIRST_PARTY_RECORDED
    assert diagnostics["ingest_source"] == PROVENANCE_TIER_FIRST_PARTY_RECORDED
    assert diagnostics["economic_guardrail_profile"] == ECONOMIC_GUARDRAIL_FIRST_PARTY_STAMP
    assert diagnostics["preliminary_attestation_required"] is True
    assert diagnostics["preliminary_ride_hash_present"] is True
    assert diagnostics["preliminary_parser_version_present"] is True
    upload_row = {
        "id": init_response.upload_id,
        "user_id": current_user.user_id,
        "processing_status": "uploading",
        "file_type": init_kwargs["file_type"],
        "raw_file_path": init_kwargs["raw_file_path"],
        "raw_file_size_bytes": init_kwargs["raw_file_size_bytes"],
        "file_hash": init_kwargs["file_hash"],
        "preliminary_ride_hash_hex": init_kwargs["preliminary_ride_hash_hex"],
        "preliminary_parser_version": init_kwargs["preliminary_parser_version"],
    }
    ride_repo.get_ride = AsyncMock(return_value=upload_row)
    ride_repo.transition_ride_status = AsyncMock(side_effect=[True, True])

    enqueue = AsyncMock(return_value=RideIngestEnqueueResult(accepted=True, backend="nats"))
    with (
        patch("app.routes.rides.create_file_storage_service", return_value=storage),
        patch("app.routes.rides.enqueue_ride_ingest", enqueue),
    ):
        complete_response = await upload_complete(
            http_request=MagicMock(),
            complete_request=UploadCompleteRequest(upload_id=init_response.upload_id),
            current_user=current_user,
            ride_repo=ride_repo,
            user_repo=user_repo,
        )

    assert complete_response.ride_id == init_response.upload_id
    assert complete_response.status == "processing"
    storage.file_exists.assert_awaited_once_with(init_kwargs["raw_file_path"])
    storage.download_ride_file.assert_awaited_once_with(init_kwargs["raw_file_path"])
    storage.compute_file_hash.assert_called_once_with(b"uploaded ride bytes")
    assert ride_repo.transition_ride_status.await_args_list == [
        call(
            UUID(init_response.upload_id),
            expected_status="uploading",
            new_status="pending",
            upload_verified_at=ANY,
        ),
        call(
            UUID(init_response.upload_id),
            expected_status="pending",
            new_status="processing",
        ),
    ]
    ride_repo.update_ride_status.assert_not_awaited()
    enqueue.assert_awaited_once()
    job = enqueue.await_args.args[0]
    assert job.ride_id == init_response.upload_id
    assert job.wallet == current_user.wallet
    assert job.user_id == current_user.user_id
    assert job.file_type == "gpx"
    assert job.file_path == init_kwargs["raw_file_path"]
    assert job.user_weight_kg == 72.5
    assert not hasattr(job, "user_ftp_w")
    assert job.source == "manual_upload_direct"

    status_repo = MagicMock()
    status_repo.get_ride = AsyncMock(
        return_value={
            **upload_row,
            "processing_status": "processing",
        }
    )
    status_response = await get_ride_status(
        ride_id=init_response.upload_id,
        current_user=current_user,
        repo=status_repo,
    )
    assert status_response["status"] == "processing"
    assert status_response["attestation_status"] == "pending"
    assert status_response["preliminary_ride_hash_hex"] == "cd" * 32
    assert status_response["preliminary_parser_version"] == 1
    assert status_response["earnings"] is None
    RideStatusResponse.model_validate(status_response)


@pytest.mark.asyncio
async def test_upload_complete_rejects_mismatched_uploaded_hash() -> None:
    upload_id = str(uuid4())
    ride_repo = MagicMock()
    ride_repo.get_ride = AsyncMock(
        return_value={
            "id": upload_id,
            "user_id": "user-queue",
            "processing_status": "uploading",
            "file_type": "gpx",
            "raw_file_path": f"rides/user-queue/{upload_id}.gpx",
            "raw_file_size_bytes": 100,
            "file_hash": "ab" * 32,
        }
    )
    ride_repo.update_ride_status = AsyncMock()

    storage = MagicMock()
    storage.file_exists = AsyncMock(return_value=True)
    storage.get_file_size = AsyncMock(return_value=100)
    storage.download_ride_file = AsyncMock(return_value=b"wrong bytes")
    storage.compute_file_hash = MagicMock(return_value="cd" * 32)

    current_user = AuthenticatedUser(
        wallet="wallet-queue",
        user_id="user-queue",
        device_id="device-queue",
    )

    with patch("app.routes.rides.create_file_storage_service", return_value=storage):
        with pytest.raises(HTTPException) as exc:
            await upload_complete(
                http_request=MagicMock(),
                complete_request=UploadCompleteRequest(upload_id=upload_id),
                current_user=current_user,
                ride_repo=ride_repo,
                user_repo=MagicMock(),
            )

    assert exc.value.status_code == 400
    assert exc.value.detail == "File hash does not match uploaded content"
    ride_repo.update_ride_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_ride_status_exposes_under_review_fields() -> None:
    ride_id = str(uuid4())
    repo = MagicMock()
    repo.get_ride = AsyncMock(
        return_value={
            "id": ride_id,
            "user_id": "user-1",
            "processing_status": "under_review",
            "ride_hash_hex": "ab" * 32,
            "attestation_commitment_hex": "cd" * 32,
            "ride_parser_version": 1,
            "preliminary_ride_hash_hex": "ef" * 32,
            "preliminary_parser_version": 1,
            "canonical_match": False,
            "review_reason": "preliminary_hash_mismatch",
        }
    )
    current_user = AuthenticatedUser(wallet="wallet-1", user_id="user-1", device_id="device-1")

    response = await get_ride_status(
        ride_id=ride_id,
        current_user=current_user,
        repo=repo,
    )

    assert response["status"] == "under_review"
    assert response["attestation_status"] == "under_review"
    assert response["preliminary_ride_hash_hex"] == "ef" * 32
    assert response["preliminary_parser_version"] == 1
    assert response["canonical_match"] is False
    assert response["review_reason"] == "preliminary_hash_mismatch"


def test_derive_attestation_status_prefers_under_review() -> None:
    assert _derive_attestation_status({"processing_status": "under_review"}) == "under_review"
    assert _derive_attestation_status({"canonical_match": False}) == "under_review"
    assert _derive_attestation_status(
        {"processing_status": "completed", "ride_attestation_pda": "2" * 44}
    ) == "attested"


@pytest.mark.asyncio
async def test_get_ride_status_preserves_completed_onchain_proof_references() -> None:
    ride_id = str(uuid4())
    finalized_at = datetime(2026, 4, 20, 13, 30, tzinfo=timezone.utc).isoformat()
    repo = MagicMock()
    repo.get_ride = AsyncMock(
        return_value={
            "id": ride_id,
            "user_id": "user-1",
            "processing_status": "completed",
            "ride_hash_hex": "ab" * 32,
            "attestation_commitment_hex": "ab" * 32,
            "ride_parser_version": 1,
            "preliminary_ride_hash_hex": "ab" * 32,
            "preliminary_parser_version": 1,
            "canonical_match": True,
            "ride_attestation_pda": "RideAttestation111111111111111111111111111111",
            "ride_attestation_tx_signature": "ride-attestation-tx",
            "ride_attested_at": "2026-04-20T13:08:00+00:00",
            "tx_signature": "credit-cal-tx",
            "cal_earned": 84,
            "dung_minted": 0,
            "tss": 84.7,
            "kcals": 512.0,
            "distance_m": 12345.6,
            "elevation_gain_m": 321.0,
            "duration_sec": 450,
            "avg_power_w": 218.0,
            "normalized_power_w": 234.0,
            "finalized_at": finalized_at,
        }
    )
    current_user = AuthenticatedUser(wallet="wallet-1", user_id="user-1", device_id="device-1")

    response = await get_ride_status(
        ride_id=ride_id,
        current_user=current_user,
        repo=repo,
    )
    contract = RideStatusResponse.model_validate(response)

    assert contract.attestation_status == "attested"
    assert contract.ride_attestation_pda == "RideAttestation111111111111111111111111111111"
    assert contract.ride_attestation_tx_signature == "ride-attestation-tx"
    assert contract.tx_signature == "credit-cal-tx"
    assert contract.earnings is not None
    assert contract.earnings.truth_source == "onchain"
    assert contract.earnings.cal_earned == 84
    assert contract.finalized_at == finalized_at


# ---------------------------------------------------------------------------
# BACKEND_TRUTHS §3.3 — `finalized_at` first-class timestamp (bead mfab.2)
# ---------------------------------------------------------------------------


def test_ride_record_finalized_at_null_when_epoch_pending() -> None:
    """A ride whose settlement week has not yet finalized must surface
    finalized_at=None. NULL means "earnings not yet locked", never "data
    missing". BACKEND_TRUTHS §3.3."""
    from app.routes.rides import _to_ride_record

    ride_row = {
        "id": "11111111-1111-1111-1111-111111111111",
        "user_id": "22222222-2222-2222-2222-222222222222",
        "processing_status": "completed",
        "started_at": "2026-04-17T12:00:00+00:00",
        "completed_at": "2026-04-17T13:30:00+00:00",
        "finalized_at": None,
    }
    record = _to_ride_record(ride_row)
    assert record.finalized_at is None

    # Frontend alias surface — camelCase and present in payload.
    dumped = record.model_dump(by_alias=True)
    assert "finalizedAt" in dumped
    assert dumped["finalizedAt"] is None


def test_ride_record_finalized_at_populated_when_settlement_closed() -> None:
    """When the chain finalizes the ride's settlement week, `finalized_at` is
    present and round-trips through the schema.

    Arrow of truth: the value is passed in from the DB (sourced from the
    chain's EpochRewardsDistributed block_time, never from wall-clock).
    """
    from app.routes.rides import _to_ride_record

    ride_row = {
        "id": "33333333-3333-3333-3333-333333333333",
        "user_id": "44444444-4444-4444-4444-444444444444",
        "processing_status": "completed",
        "started_at": "2026-04-10T12:00:00+00:00",
        "completed_at": "2026-04-10T13:30:00+00:00",
        # Settlement week containing 2026-04-10 closed on Sun 2026-04-12
        # 12:00 UTC + 24h grace + on-chain finalize.
        "finalized_at": "2026-04-13T13:05:00+00:00",
    }
    record = _to_ride_record(ride_row)
    assert record.finalized_at is not None
    # ISO surface for the mobile UI / demo narrative.
    dumped = record.model_dump(by_alias=True)
    assert dumped["finalizedAt"] is not None
    assert "2026-04-13" in dumped["finalizedAt"].isoformat() if hasattr(dumped["finalizedAt"], "isoformat") else "2026-04-13" in str(dumped["finalizedAt"])


@pytest.mark.asyncio
async def test_get_ride_surfaces_finalized_at_alias() -> None:
    """`GET /rides/{id}` must surface `finalizedAt` (camelCase alias) on
    finalized rides so the mobile UI can enforce the §3.3 distinction."""
    from unittest.mock import patch
    from app.routes.rides import get_ride

    ride_id = str(uuid4())
    user_id = str(uuid4())
    finalized_iso = "2026-04-13T13:05:00+00:00"

    ride_row = {
        "id": ride_id,
        "user_id": user_id,
        "processing_status": "completed",
        "started_at": "2026-04-10T12:00:00+00:00",
        "completed_at": "2026-04-10T13:30:00+00:00",
        "finalized_at": finalized_iso,
        "visibility": "public",
        "patterns": [],
    }

    repo = MagicMock()
    repo.get_ride = AsyncMock(return_value=ride_row)
    # No indexed vault lookup needed — patterns is empty.
    repo.client = MagicMock()

    current_user = AuthenticatedUser(
        wallet="wallet-1", user_id=user_id, device_id="device-1"
    )

    response = await get_ride(
        ride_id=ride_id,
        current_user=current_user,
        repo=repo,
    )

    # Response is a dict built from model_dump(by_alias=True).
    assert "finalizedAt" in response
    assert response["finalizedAt"] is not None


@pytest.mark.asyncio
async def test_get_ride_null_finalized_at_for_pending_epoch() -> None:
    """When a ride's settlement week has not yet finalized, the API surface
    must honestly report `finalizedAt=None`. The mobile UI reads this as
    "pending" and surfaces the projection accordingly."""
    from app.routes.rides import get_ride

    ride_id = str(uuid4())
    user_id = str(uuid4())

    ride_row = {
        "id": ride_id,
        "user_id": user_id,
        "processing_status": "completed",
        "started_at": "2026-04-17T12:00:00+00:00",
        "completed_at": "2026-04-17T13:30:00+00:00",
        "finalized_at": None,
        "visibility": "public",
        "patterns": [],
    }

    repo = MagicMock()
    repo.get_ride = AsyncMock(return_value=ride_row)
    repo.client = MagicMock()

    current_user = AuthenticatedUser(
        wallet="wallet-1", user_id=user_id, device_id="device-1"
    )

    response = await get_ride(
        ride_id=ride_id,
        current_user=current_user,
        repo=repo,
    )
    assert response["finalizedAt"] is None
