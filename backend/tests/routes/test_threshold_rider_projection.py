from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.dependencies import AuthenticatedUser
from app.routes.users import get_my_threshold
from app.routes.rides import _project_threshold_training_for_owner
from app.services.reward_threshold import parse_threshold_rider_projection


NOW = datetime(2026, 8, 24, 18, 0, tzinfo=timezone.utc)


def test_projection_keeps_unscheduled_candidate_private() -> None:
    projection = parse_threshold_rider_projection(
        {
            "state": "established",
            "current_w": 245,
            "established_at": "2026-08-17T12:00:00+00:00",
            "last_raised_at": None,
            "pending_monday": None,
            "training_denominator": {
                "watts": 245,
                "kind": "sealed",
                "provisional": False,
            },
        },
        as_of=NOW,
    )

    assert projection.current_w == 245
    assert projection.pending_monday is None
    assert projection.last_raised_at is None


def test_projection_accepts_only_a_genuine_future_raise() -> None:
    projection = parse_threshold_rider_projection(
        {
            "state": "established",
            "current_w": 245,
            "established_at": "2026-08-17T12:00:00+00:00",
            "last_raised_at": "2026-08-24T12:00:00+00:00",
            "pending_monday": {
                "promotion_id": str(uuid4()),
                "watts": 251,
                "effective_at": "2026-08-31T12:00:00+00:00",
            },
            "training_denominator": {
                "watts": 251,
                "kind": "pending",
                "provisional": True,
            },
        },
        as_of=NOW,
    )

    assert projection.pending_monday is not None
    assert projection.pending_monday.watts == 251
    assert projection.training_denominator.watts == 251


def test_projection_rejects_placeholder_as_a_rider_threshold() -> None:
    payload = {
        "state": "establishing",
        "current_w": 200,
        "established_at": None,
        "last_raised_at": None,
        "pending_monday": None,
        "training_denominator": {
            "watts": 200,
            "kind": "network_placeholder",
            "provisional": True,
        },
    }
    with pytest.raises(ValueError):
        parse_threshold_rider_projection(payload, as_of=NOW)


def test_projection_preserves_sealed_current_across_an_expired_cached_raise() -> None:
    projection = parse_threshold_rider_projection(
        {
            "state": "established",
            "current_w": 245,
            "established_at": "2026-08-17T12:00:00+00:00",
            "last_raised_at": None,
            "pending_monday": {
                "promotion_id": str(uuid4()),
                "watts": 251,
                "effective_at": "2026-08-24T12:00:00+00:00",
            },
            "training_denominator": {
                "watts": 251,
                "kind": "pending",
                "provisional": True,
            },
        },
        as_of=NOW,
    )
    assert projection.current_w == 245
    assert projection.pending_monday is None
    assert projection.training_denominator.watts == 245
    assert projection.sealing_in_progress is True


@pytest.mark.asyncio
async def test_threshold_endpoint_returns_establishing_without_200() -> None:
    repo = AsyncMock()
    repo.get_reward_threshold_rider_projection.return_value = {
        "state": "establishing",
        "current_w": None,
        "established_at": None,
        "last_raised_at": None,
        "pending_monday": None,
        "training_denominator": {
            "watts": 200,
            "kind": "network_placeholder",
            "provisional": True,
        },
    }
    response = await get_my_threshold(
        current_user=AuthenticatedUser("wallet", str(uuid4()), "device"),
        ride_repo=repo,
    )

    body = response.model_dump(mode="json", by_alias=True)
    assert body == {
        "contractVersion": "threshold.v1",
        "state": "establishing",
        "currentW": None,
        "establishedAt": None,
        "lastRaisedAt": None,
        "pendingMonday": None,
        "sealingInProgress": False,
    }


@pytest.mark.asyncio
async def test_threshold_endpoint_fails_closed_when_authority_is_unavailable() -> None:
    repo = AsyncMock()
    repo.get_reward_threshold_rider_projection.side_effect = RuntimeError("offline")

    with pytest.raises(HTTPException) as exc:
        await get_my_threshold(
            current_user=AuthenticatedUser("wallet", str(uuid4()), "device"),
            ride_repo=repo,
        )

    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_later_threshold_cannot_reprice_frozen_training_load() -> None:
    repo = AsyncMock()
    repo.get_reward_threshold_rider_projection.side_effect = AssertionError("must not reprice history")
    score = {"engine_version":2,"load":67,"threshold":{"value":245,"estimate":False,"basis":"ios_threshold"}}
    projected = await _project_threshold_training_for_owner(repo,str(uuid4()),[{
        "id":str(uuid4()),"processing_status":"completed","tss":999,"training_metrics":score,
        "threshold_training_kind":"sealed","threshold_training_w":245}])
    assert projected[0]["tss"] == 67
    assert projected[0]["training_metrics"]["threshold"]["value"] == 245
    assert projected[0]["threshold_training_state"] is None
    repo.get_reward_threshold_rider_projection.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_training_projection_does_not_fall_back_to_legacy_tss() -> None:
    projected = await _project_threshold_training_for_owner(AsyncMock(),str(uuid4()),[{
        "id":str(uuid4()),"processing_status":"completed","tss":100,"normalized_power_raw_w":200,"normalized_power_duration_s":3600}])
    assert projected[0]["tss"] is None
    assert projected[0]["threshold_training_state"] is None
