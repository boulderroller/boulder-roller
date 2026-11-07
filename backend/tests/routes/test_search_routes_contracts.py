from __future__ import annotations

from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.dependencies import AuthenticatedUser
from app.routes.search import get_search_schema, search_app, search_suggestions


class FakeSearchRepo:
    def __init__(self) -> None:
        self.users = {
            "viewer-user": {
                "id": "viewer-user",
                "wallet": "ViewerWallet11111111111111111111111111111",
                "username": "viewer",
                "display_name": "Viewer",
                "is_public": False,
                "total_rides": 3,
                "moderation_state": "visible",
            },
            "public-user": {
                "id": "public-user",
                "wallet": "PublicWallet11111111111111111111111111111",
                "username": "tim",
                "display_name": "Tim",
                "avatar_url": None,
                "is_public": True,
                "location": "Philadelphia",
                "total_rides": 12,
                "total_elevation_m": 1707,
                "moderation_state": "visible",
            },
            "private-user": {
                "id": "private-user",
                "wallet": "PrivateWallet111111111111111111111111111",
                "username": "quiet",
                "display_name": "Quiet",
                "avatar_storage_path": "avatars/private/search.jpg",
                "is_public": False,
                "moderation_state": "visible",
            },
            "hidden-user": {
                "id": "hidden-user",
                "wallet": "HiddenWallet111111111111111111111111111",
                "username": "hidden",
                "display_name": "Hidden",
                "is_public": True,
                "moderation_state": "hidden",
            },
        }
        self.rides = {
            "ride-public": {
                "id": "ride-public",
                "user_id": "public-user",
                "file_name": "Rolling Boulders.fit",
                "started_at": "2026-04-30T12:00:00+00:00",
                "distance_m": 121300,
                "elevation_gain_m": 1707,
                "duration_sec": 16168,
                "processing_status": "completed",
                "visibility": "public",
                "moderation_state": "visible",
                "ride_attestation_tx_signature": "tx-public",
                "finalized_at": "2026-04-30T13:00:00+00:00",
            },
            "ride-private": {
                "id": "ride-private",
                "user_id": "public-user",
                "file_name": "Private Boulders.fit",
                "processing_status": "completed",
                "visibility": "private",
                "moderation_state": "visible",
            },
            "ride-owner-private": {
                "id": "ride-owner-private",
                "user_id": "viewer-user",
                "file_name": "Viewer Private Ride.fit",
                "processing_status": "completed",
                "visibility": "private",
                "moderation_state": "visible",
            },
            "ride-private-profile-owner": {
                "id": "ride-private-profile-owner",
                "user_id": "private-user",
                "file_name": "Quiet Public Boulder.fit",
                "processing_status": "completed",
                "visibility": "public",
                "moderation_state": "visible",
            },
        }
        self.climbs = {
            "142": {
                "id": "142",
                "name": "Manayunk Wall",
                "region": "Philadelphia",
                "distance_m": 950,
                "total_vert_m": 85,
                "avg_gradient_pct": 8.9,
                "signature_hex": "ab" * 64,
                "total_completions": 12,
            }
        }
        self.following_ids = {"viewer-user": ["public-user"]}

    async def search_riders(self, query: str, limit: int) -> list[dict[str, Any]]:
        query = query.lower()
        return [
            dict(user)
            for user in self.users.values()
            if query in str(user.get("username", "")).lower()
            or query in str(user.get("display_name", "")).lower()
            or query in str(user.get("wallet", "")).lower()
        ][:limit]

    async def search_climbs(self, query: str, limit: int) -> list[dict[str, Any]]:
        query = query.lower()
        return [
            dict(climb)
            for climb in self.climbs.values()
            if query in str(climb.get("name", "")).lower()
            or query in str(climb.get("region", "")).lower()
            or query == str(climb.get("id"))
        ][:limit]

    async def search_rides(
        self,
        query: str,
        limit: int,
        current_user: Optional[AuthenticatedUser],
    ) -> list[dict[str, Any]]:
        query = query.lower()
        return [
            dict(ride)
            for ride in self.rides.values()
            if query in str(ride.get("file_name", "")).lower()
            or (current_user and ride.get("user_id") == current_user.user_id)
        ][:limit]

    async def get_users_by_ids(self, user_ids: list[str]) -> list[dict[str, Any]]:
        return [dict(self.users[user_id]) for user_id in user_ids if user_id in self.users]

    async def get_follow(self, follower_id: str, following_id: str) -> Optional[dict[str, Any]]:
        if following_id in self.following_ids.get(follower_id, []):
            return {"follower_id": follower_id, "following_id": following_id}
        return None

    async def get_following_ids(self, user_id: str) -> list[str]:
        return list(self.following_ids.get(user_id, []))

    async def get_following(self, user_id: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        ids = self.following_ids.get(user_id, [])[offset:offset + limit]
        return [dict(self.users[user_id]) for user_id in ids]

    async def list_rides_for_user(
        self,
        user_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return [
            dict(ride)
            for ride in self.rides.values()
            if ride.get("user_id") == user_id
        ][offset:offset + limit]

    async def get_feed_rides(self, user_ids: list[str], limit: int = 20, before: Any = None) -> list[dict[str, Any]]:
        del before
        return [
            dict(ride)
            for ride in self.rides.values()
            if ride.get("user_id") in user_ids and ride.get("visibility") in {"public", "followers"}
        ][:limit]

    async def get_global_rides(self, limit: int = 20, before: Any = None) -> list[dict[str, Any]]:
        del before
        return [dict(ride) for ride in self.rides.values() if ride.get("visibility") == "public"][:limit]

    async def suggest_climbs(self, limit: int) -> list[dict[str, Any]]:
        return sorted(
            (dict(climb) for climb in self.climbs.values()),
            key=lambda climb: climb.get("total_completions") or 0,
            reverse=True,
        )[:limit]

    async def get_interaction_summaries(
        self,
        target_type: str,
        target_ids: list[str],
        viewer_id: Optional[str],
    ) -> dict[str, dict[str, Any]]:
        return {
            target_id: {"kudosCount": 2, "commentCount": 1, "viewerHasKudos": target_id == "ride-public"}
            for target_id in target_ids
        }


@pytest.fixture
def viewer() -> AuthenticatedUser:
    return AuthenticatedUser(
        wallet="ViewerWallet11111111111111111111111111111",
        user_id="viewer-user",
        device_id="device-1",
    )


@pytest.mark.asyncio
async def test_search_schema_exposes_search_v1() -> None:
    schema = await get_search_schema()

    assert schema["contractVersion"] == "search.v1"
    assert "climbs" in schema["types"]
    assert "scan_tx" in schema["targets"]
    assert "suggestions" in schema["capabilities"]


@pytest.mark.asyncio
async def test_search_all_returns_privacy_aware_navigation_results(viewer: AuthenticatedUser) -> None:
    response = await search_app(
        request=None,
        q="boulder",
        result_type="all",
        limit=10,
        current_user=viewer,
        repo=FakeSearchRepo(),  # type: ignore[arg-type]
    )

    ids = [result["id"] for result in response["results"]]
    assert "ride:ride-public" in ids
    assert "ride:ride-owner-private" in ids
    assert "ride:ride-private" not in ids

    public_ride = next(result for result in response["results"] if result["id"] == "ride:ride-public")
    assert public_ride["target"]["contractVersion"] == "target_action.v1"
    assert public_ride["target"]["type"] == "ride"
    assert public_ride["target"]["id"] == "ride-public"
    assert public_ride["privacy"]["visibility"] == "public"
    assert public_ride["metadata"]["kudosCount"] == 2
    assert public_ride["scanState"] == "finalized"

    owner_ride = next(result for result in response["results"] if result["id"] == "ride:ride-owner-private")
    assert owner_ride["privacy"]["reason"] == "owner"


@pytest.mark.asyncio
async def test_search_all_keeps_other_branches_when_rider_search_fails(viewer: AuthenticatedUser) -> None:
    class RiderFailingRepo(FakeSearchRepo):
        async def search_riders(self, query: str, limit: int) -> list[dict[str, Any]]:
            raise RuntimeError("production schema drift")

    response = await search_app(
        request=None,
        q="boulder",
        result_type="all",
        limit=10,
        current_user=viewer,
        repo=RiderFailingRepo(),  # type: ignore[arg-type]
    )

    ids = [result["id"] for result in response["results"]]
    assert "ride:ride-public" in ids
    assert "ride:ride-owner-private" in ids
    assert all(not result_id.startswith("rider:") for result_id in ids)


@pytest.mark.asyncio
async def test_search_riders_excludes_private_and_moderated_profiles(viewer: AuthenticatedUser) -> None:
    storage = MagicMock()
    storage.get_signed_url = AsyncMock(return_value="https://example.test/rider-avatar")
    with patch("app.avatar_media_contracts.create_file_storage_service", return_value=storage):
        response = await search_app(
            request=None,
            q="i",
            result_type="riders",
            limit=10,
            current_user=viewer,
            repo=FakeSearchRepo(),  # type: ignore[arg-type]
        )

    ids = [result["id"] for result in response["results"]]
    assert "rider:tim" in ids
    assert "rider:quiet" not in ids
    assert "rider:hidden" not in ids

    rider = next(result for result in response["results"] if result["id"] == "rider:tim")
    assert rider["webPath"] == "/riders/tim"
    assert rider["privacy"]["reason"] == "public_profile"
    assert rider["privacy"]["isFollower"] is True
    assert rider["metadata"]["rider"]["viewerRelationship"] == "following"
    assert rider["metadata"]["isFollowing"] is True


@pytest.mark.asyncio
async def test_ride_search_redacts_private_owner_avatar_before_signing(viewer: AuthenticatedUser) -> None:
    storage = MagicMock()
    storage.get_signed_url = AsyncMock(return_value="https://example.test/private-avatar")

    with patch("app.avatar_media_contracts.create_file_storage_service", return_value=storage):
        response = await search_app(
            request=None,
            q="quiet public",
            result_type="rides",
            limit=10,
            current_user=viewer,
            repo=FakeSearchRepo(),  # type: ignore[arg-type]
        )

    result = next(item for item in response["results"] if item["id"] == "ride:ride-private-profile-owner")
    owner = result["metadata"]["owner"]
    assert owner["id"] == "private-user"
    assert owner["displayName"] is None
    assert owner["avatarUrl"] is None
    assert owner["isPublic"] is False
    assert "Quiet" not in result["subtitle"]
    storage.get_signed_url.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_climbs_returns_protocol_public_scan_targets() -> None:
    response = await search_app(
        request=None,
        q="manayunk",
        result_type="climbs",
        limit=10,
        current_user=None,
        repo=FakeSearchRepo(),  # type: ignore[arg-type]
    )

    result = response["results"][0]
    assert result["id"] == "climb:142"
    assert result["target"]["contractVersion"] == "target_action.v1"
    assert result["target"]["type"] == "climb"
    assert result["target"]["id"] == "142"
    assert result["webPath"] == "/climbs/142"
    assert result["scanTargets"][0]["type"] == "vault"


@pytest.mark.asyncio
async def test_search_climbs_uses_indexed_vault_id_for_scan_targets() -> None:
    repo = FakeSearchRepo()
    repo.climbs = {
        "canonical": {
            "id": "11111111-1111-1111-1111-111111111111",
            "vault_id": 142,
            "name": "Canonical Wall",
            "region": "Philadelphia",
            "distance_m": 950,
            "total_vert_m": 85,
            "avg_gradient_pct": 8.9,
            "signature_hex": "ab" * 64,
            "total_completions": 12,
        }
    }

    response = await search_app(
        request=None,
        q="canonical",
        result_type="climbs",
        limit=10,
        current_user=None,
        repo=repo,  # type: ignore[arg-type]
    )

    result = response["results"][0]
    assert result["id"] == "climb:142"
    assert result["target"]["id"] == "142"
    assert result["scanTargets"][0]["id"] == "142"
    assert result["scanTargets"][0]["url"].endswith("/vault/142")


@pytest.mark.asyncio
async def test_search_climbs_marks_place_matches() -> None:
    response = await search_app(
        request=None,
        q="philadelphia",
        result_type="climbs",
        limit=10,
        current_user=None,
        repo=FakeSearchRepo(),  # type: ignore[arg-type]
    )

    result = response["results"][0]
    assert result["id"] == "climb:142"
    assert result["summary"] == "Place match"
    assert result["metadata"]["placeHint"] == "Philadelphia"


@pytest.mark.asyncio
async def test_search_suggestions_return_recent_social_and_popular_sections(viewer: AuthenticatedUser) -> None:
    response = await search_suggestions(
        request=None,
        limit=3,
        current_user=viewer,
        repo=FakeSearchRepo(),  # type: ignore[arg-type]
    )

    sections = {section["id"]: section for section in response["sections"]}
    assert response["contractVersion"] == "search.v1"
    assert "your_recent_rides" in sections
    assert "following_rides" in sections
    assert "following_riders" in sections
    assert "popular_climbs" in sections
    assert sections["your_recent_rides"]["results"][0]["metadata"]["isOwner"] is True
    assert sections["following_riders"]["results"][0]["metadata"]["isFollowing"] is True
    assert sections["popular_climbs"]["results"][0]["id"] == "climb:142"


@pytest.mark.asyncio
async def test_search_proofs_routes_exact_protocol_inputs() -> None:
    signature = "3KMUV89vL7A4jtH9Azi5X2B8QftzrVTbF3r8RL4zkDqz3bUxn9r3b1n4pY2Wm8Lh"
    response = await search_app(
        request=None,
        q=signature,
        result_type="proofs",
        limit=5,
        current_user=None,
        repo=FakeSearchRepo(),  # type: ignore[arg-type]
    )

    assert response["results"][0]["target"]["contractVersion"] == "target_action.v1"
    assert response["results"][0]["target"]["type"] == "scan_tx"
    assert response["results"][0]["target"]["id"] == signature
    assert response["results"][0]["webPath"] == f"/notifications?scanTx={signature}"
    assert response["results"][0]["scanTargets"][0]["url"].endswith(f"/tx/{signature}")
