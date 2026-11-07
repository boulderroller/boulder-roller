from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import pytest

from app.services.privacy_resolver import (
    normalize_visibility,
    resolve_profile_visibility,
    resolve_ride_visibility,
)


@dataclass
class Viewer:
    user_id: str


class FakePrivacyRepo:
    def __init__(self, follows: set[tuple[str, str]] | None = None) -> None:
        self.follows = follows or set()

    async def get_follow(self, follower_id: str, following_id: str) -> Optional[dict[str, Any]]:
        if (follower_id, following_id) in self.follows:
            return {"follower_id": follower_id, "following_id": following_id}
        return None


@pytest.mark.asyncio
async def test_owner_can_view_private_ride_without_gps_redaction() -> None:
    decision = await resolve_ride_visibility(
        {"user_id": "owner", "visibility": "private"},
        Viewer("owner"),
        repo=FakePrivacyRepo(),
    )

    assert decision.can_view is True
    assert decision.is_owner is True
    assert decision.redact_gps is False
    assert decision.reason == "owner"


@pytest.mark.asyncio
async def test_public_ride_is_visible_to_anonymous_viewer_with_redaction() -> None:
    decision = await resolve_ride_visibility(
        {"user_id": "owner", "visibility": "public"},
        None,
        repo=FakePrivacyRepo(),
    )

    assert decision.can_view is True
    assert decision.visibility == "public"
    assert decision.redact_gps is True


@pytest.mark.asyncio
async def test_followers_ride_requires_social_edge() -> None:
    not_follower = await resolve_ride_visibility(
        {"user_id": "owner", "visibility": "followers"},
        Viewer("viewer"),
        repo=FakePrivacyRepo(),
    )
    follower = await resolve_ride_visibility(
        {"user_id": "owner", "visibility": "followers"},
        Viewer("viewer"),
        repo=FakePrivacyRepo({("viewer", "owner")}),
    )

    assert not_follower.can_view is False
    assert not_follower.reason == "not_follower"
    assert follower.can_view is True
    assert follower.is_follower is True
    assert follower.reason == "follower"


@pytest.mark.asyncio
async def test_missing_ride_override_inherits_owner_default_visibility() -> None:
    decision = await resolve_ride_visibility(
        {"user_id": "owner"},
        Viewer("viewer"),
        repo=FakePrivacyRepo(),
        owner_profile={"default_ride_visibility": "private"},
    )

    assert decision.can_view is False
    assert decision.visibility == "private"
    assert decision.reason == "private"


@pytest.mark.asyncio
async def test_private_ride_still_surfaces_protocol_public_fact_flags() -> None:
    decision = await resolve_ride_visibility(
        {
            "user_id": "owner",
            "visibility": "private",
            "ride_attestation_pda": "attestation-pda",
            "finalized_at": "2026-04-29T00:00:00+00:00",
        },
        Viewer("viewer"),
        repo=FakePrivacyRepo(),
    )

    assert decision.can_view is False
    assert decision.protocol_public is True
    assert decision.protocol_public_fields == ("ride_attestation_pda", "finalized_at")
    assert decision.to_client_dict()["protocolPublicFields"] == [
        "ride_attestation_pda",
        "finalized_at",
    ]


@pytest.mark.asyncio
async def test_moderation_hidden_ride_blocks_non_owner_even_when_public() -> None:
    viewer_decision = await resolve_ride_visibility(
        {"user_id": "owner", "visibility": "public", "moderation_state": "hidden"},
        Viewer("viewer"),
        repo=FakePrivacyRepo(),
    )
    owner_decision = await resolve_ride_visibility(
        {"user_id": "owner", "visibility": "public", "moderation_state": "hidden"},
        Viewer("owner"),
        repo=FakePrivacyRepo(),
    )

    assert viewer_decision.can_view is False
    assert viewer_decision.reason == "moderation_hidden"
    assert owner_decision.can_view is True
    assert owner_decision.reason == "owner"


@pytest.mark.asyncio
async def test_moderated_owner_profile_blocks_public_ride_for_non_owner() -> None:
    decision = await resolve_ride_visibility(
        {"user_id": "owner", "visibility": "public"},
        Viewer("viewer"),
        repo=FakePrivacyRepo(),
        owner_profile={"id": "owner", "moderation_state": "hidden"},
    )

    assert decision.can_view is False
    assert decision.reason == "owner_moderation_hidden"


@pytest.mark.asyncio
async def test_profile_visibility_distinguishes_owner_from_public_viewer() -> None:
    private_profile = {"id": "owner", "is_public": False}

    public_decision = await resolve_profile_visibility(private_profile, Viewer("viewer"))
    owner_decision = await resolve_profile_visibility(private_profile, Viewer("owner"))

    assert public_decision.can_view is False
    assert public_decision.reason == "private_profile"
    assert owner_decision.can_view is True
    assert owner_decision.reason == "owner"


@pytest.mark.asyncio
async def test_public_profile_visibility_resolves_follower_relationship() -> None:
    decision = await resolve_profile_visibility(
        {"id": "owner", "is_public": True},
        Viewer("viewer"),
        repo=FakePrivacyRepo({("viewer", "owner")}),
    )

    assert decision.can_view is True
    assert decision.is_follower is True
    assert decision.to_client_dict()["isFollower"] is True


@pytest.mark.asyncio
async def test_moderation_removed_profile_blocks_public_viewer_but_not_owner() -> None:
    removed_profile = {"id": "owner", "is_public": True, "moderation_state": "removed"}

    public_decision = await resolve_profile_visibility(removed_profile, Viewer("viewer"))
    owner_decision = await resolve_profile_visibility(removed_profile, Viewer("owner"))

    assert public_decision.can_view is False
    assert public_decision.reason == "moderation_removed"
    assert owner_decision.can_view is True
    assert owner_decision.reason == "owner"


def test_normalize_visibility_falls_back_to_requested_default() -> None:
    assert normalize_visibility("followers") == "followers"
    assert normalize_visibility("garbage", default="private") == "private"
