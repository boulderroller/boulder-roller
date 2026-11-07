"""Stored upload time belongs only to the authenticated owner's ride list."""
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import AuthenticatedUser, get_current_user, get_ride_repository
from app.feed_contracts import build_ride_feed_event
from app.public_preview_contracts import build_ride_public_preview
from app.routes import rides, search
from app.routes.users import _public_ride_summary
from app.schemas import RideRecord
from app.services.privacy_resolver import VisibilityDecision


UPLOADED_AT = "2026-05-02T15:00:00Z"


@pytest.fixture
def owner():
    return AuthenticatedUser(wallet="fixture-wallet", user_id=str(uuid4()), device_id="fixture-device")


@pytest.fixture
def ride(owner):
    return {
        "id": str(uuid4()), "user_id": owner.user_id,
        "started_at": "2026-04-30T11:00:00Z", "uploaded_at": UPLOADED_AT,
        "file_name": "Original file.gpx", "processing_status": "completed",
        "visibility": "public", "map_visibility": "hide_entire",
        "reward_ftp_source": "measured",
    }


def list_response(rows, viewer):
    repo = MagicMock()
    repo.list_rides_for_user = AsyncMock(return_value=rows)
    repo.list_ride_media_for_rides = AsyncMock(return_value={})
    repo.list_counted_climb_steps = AsyncMock(return_value={})
    app = FastAPI()
    app.include_router(rides.router, prefix="/rides")
    app.dependency_overrides[get_current_user] = lambda: viewer
    app.dependency_overrides[get_ride_repository] = lambda: repo
    with TestClient(app) as client:
        response = client.get("/rides?limit=50&offset=0")
    assert response.status_code == 200, response.text
    repo.list_rides_for_user.assert_awaited_once_with(viewer.user_id, limit=50, offset=0)
    return response.json()


def assert_no_upload_date(payload):
    serialized = json.dumps(payload, default=str)
    assert "uploadedAt" not in serialized
    assert "uploaded_at" not in serialized
    assert UPLOADED_AT not in serialized


@pytest.mark.parametrize("status", ["failed", "completed"])
def test_owner_list_emits_stored_upload_date_without_reordering(ride, owner, status):
    ride["processing_status"] = status
    earlier = {**ride, "id": str(uuid4()), "started_at": "2026-04-20T11:00:00Z",
               "uploaded_at": "2026-05-03T15:00:00Z"}
    payload = list_response([ride, earlier], owner)
    assert [row["id"] for row in payload] == [ride["id"], earlier["id"]]
    assert payload[0]["startedAt"] == ride["started_at"]
    assert payload[0]["uploadedAt"] == UPLOADED_AT
    assert payload[1]["uploadedAt"] == earlier["uploaded_at"]
    assert "uploaded_at" not in payload[0]


@pytest.mark.parametrize("stored", [None, "", "invalid"])
def test_owner_list_omits_missing_upload_date_without_start_time_fallback(ride, owner, stored):
    ride["uploaded_at"] = stored
    payload = list_response([ride], owner)[0]
    assert payload["startedAt"] == ride["started_at"]
    assert_no_upload_date(payload)


def test_list_checks_record_ownership_even_if_repository_returns_another_riders_row(ride, owner):
    ride["user_id"] = str(uuid4())
    payload = list_response([ride], owner)[0]
    assert payload["privacy"]["isOwner"] is False
    assert_no_upload_date(payload)


@pytest.mark.parametrize("by_alias", [False, True])
def test_upload_date_is_an_optional_additive_schema_field(by_alias):
    schema = RideRecord.model_json_schema(by_alias=by_alias)
    key = "uploadedAt" if by_alias else "uploaded_at"
    assert key not in schema["required"]
    assert {"type": "string", "format": "date-time"} in schema["properties"][key]["anyOf"]


@pytest.mark.parametrize("is_owner", [False, True])
def test_shared_detail_projection_never_copies_upload_date(ride, is_owner):
    privacy = VisibilityDecision(can_view=True, visibility="public", reason="fixture", is_owner=is_owner).to_client_dict()
    record = rides._to_ride_record(ride, privacy=privacy)
    assert_no_upload_date(record.model_dump(by_alias=True))
    assert_no_upload_date(record.model_dump(by_alias=False))


@pytest.mark.parametrize("is_owner", [None, False, True])
def test_schema_and_non_owner_serializer_fail_closed(ride, is_owner):
    privacy = None if is_owner is None else VisibilityDecision(
        can_view=True, visibility="public", reason="fixture", is_owner=is_owner,
    ).to_client_dict()
    record = rides._to_ride_record(ride, privacy=privacy)
    # Even an incorrectly populated record must not expose the date to a non-owner.
    record = record.model_copy(update={"uploaded_at": datetime(2026, 5, 2, 15, tzinfo=timezone.utc)})
    if is_owner is not True:
        assert_no_upload_date(record.model_dump(by_alias=True))
        assert_no_upload_date(record.model_dump(by_alias=False))
    assert_no_upload_date(rides._serialize_ride_record(record, is_owner=False))


@pytest.mark.asyncio
@pytest.mark.parametrize("is_owner", [False, True])
async def test_upload_date_stays_out_of_feed_preview_profile_and_search(ride, owner, is_owner):
    privacy = VisibilityDecision(can_view=True, visibility="public", reason="fixture", is_owner=is_owner).to_client_dict()
    projections = [
        build_ride_feed_event(ride, None, {}, privacy),
        build_ride_public_preview(ride, privacy=privacy),
        _public_ride_summary({**ride, "privacy": privacy}),
    ]
    repo = MagicMock()
    repo.get_users_by_ids = AsyncMock(return_value=[])
    repo.get_interaction_summaries = AsyncMock(return_value={})
    repo.get_following_ids = AsyncMock(return_value=[])
    projections.append(await search._build_ride_results([ride], "Original", owner if is_owner else None, repo))
    for payload in projections:
        assert payload
        assert_no_upload_date(payload)
