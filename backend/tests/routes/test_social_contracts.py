from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app.dependencies import AuthenticatedUser
from app.notification_contracts import build_notification_insert
from app.repositories_legacy import SupabaseRepository
from app.routes.interactions import (
    CommentCreate,
    CommentUpdate,
    add_comment_to_ride,
    delete_ride_comment,
    get_ride_interactions,
    get_ride_comments,
    give_kudos_to_ride,
    update_ride_comment,
)
from app.routes import users as user_routes
from app.routes.feed import get_feed, get_global_feed
from app.routes.social import (
    SocialReportCreate,
    SocialReportResolve,
    follow_user,
    get_followers,
    get_moderation_reports,
    get_my_social_report,
    get_my_social_reports,
    get_suggested_riders,
    report_social_content,
    resolve_moderation_report,
)
from app.routes.users import (
    get_public_user_beetle_cards,
    get_public_user_profile_bootstrap,
    get_public_user_recent_rides,
    get_user_leaderboard_positions,
    get_user_profile,
)
from app.services.public_record_board_privacy import PublicRecordBoardProjection
from app.utils.polyline import encode_gps_track


class FakeNotificationInsert:
    def __init__(self, captured: dict[str, Any]) -> None:
        self.captured = captured

    def insert(self, payload: dict[str, Any]) -> "FakeNotificationInsert":
        self.captured.update(payload)
        return self

    def execute(self) -> SimpleNamespace:
        return SimpleNamespace(data=[dict(self.captured)])


class FakeSupabaseClient:
    def __init__(self) -> None:
        self.inserted: dict[str, Any] = {}

    def table(self, name: str) -> FakeNotificationInsert:
        assert name == "notifications"
        return FakeNotificationInsert(self.inserted)


class FakeSocialRepo:
    def __init__(self) -> None:
        self.viewer_id = "viewer-user"
        self.owner_id = "owner-user"
        self.target_id = "target-user"
        self.ride_id = str(uuid4())
        self.ride_media_id = str(uuid4())
        self.users = {
            self.viewer_id: {
                "id": self.viewer_id,
                "wallet": "viewer-wallet",
                "username": "viewer",
            },
            self.owner_id: {
                "id": self.owner_id,
                "wallet": "owner-wallet",
                "username": "owner",
            },
            self.target_id: {
                "id": self.target_id,
                "wallet": "target-wallet",
                "username": "target",
            },
        }
        self.ride: dict[str, Any] = {
            "id": self.ride_id,
            "user_id": self.owner_id,
            "visibility": "public",
            "comments_enabled": True,
            "moderation_state": "visible",
        }
        self.ride_media: dict[str, Any] = {
            "id": self.ride_media_id,
            "ride_id": self.ride_id,
            "user_id": self.owner_id,
            "upload_status": "ready",
            "moderation_state": "visible",
        }
        self.follows: set[tuple[str, str]] = set()
        self.comments: list[dict[str, Any]] = []
        self.kudos: set[tuple[str, str, str]] = set()
        self.notifications: list[dict[str, Any]] = []
        self.notification_preferences: Optional[dict[str, Any]] = None
        self.kudos_count = 0
        self.followed_rides: list[dict[str, Any]] = []
        self.global_rides: list[dict[str, Any]] = []
        self.reports: list[dict[str, Any]] = []
        self.moderation_actions: list[dict[str, Any]] = []

    async def get_ride(self, ride_id: str) -> Optional[dict[str, Any]]:
        return dict(self.ride) if ride_id == self.ride_id else None

    async def get_ride_media(self, media_id: str) -> Optional[dict[str, Any]]:
        return dict(self.ride_media) if media_id == self.ride_media_id else None

    async def get_user_by_id(self, user_id: str) -> Optional[dict[str, Any]]:
        return self.users.get(user_id)

    async def get_users_by_ids(self, user_ids: list[str]) -> list[dict[str, Any]]:
        return [self.users[user_id] for user_id in user_ids if user_id in self.users]

    async def get_follow(self, follower_id: str, following_id: str) -> Optional[dict[str, Any]]:
        if (follower_id, following_id) in self.follows:
            return {"follower_id": follower_id, "following_id": following_id}
        return None

    async def create_follow(self, follower_id: str, following_id: str) -> dict[str, Any]:
        self.follows.add((follower_id, following_id))
        return {"follower_id": follower_id, "following_id": following_id}

    async def get_following_ids(self, user_id: str) -> list[str]:
        return [following_id for follower_id, following_id in self.follows if follower_id == user_id]

    async def get_feed_rides(
        self,
        user_ids: list[str],
        limit: int = 20,
        before: Optional[Any] = None,
    ) -> list[dict[str, Any]]:
        return [
            ride
            for ride in self.followed_rides
            if ride.get("user_id") in user_ids
        ][:limit]

    async def get_global_rides(
        self,
        limit: int = 20,
        before: Optional[Any] = None,
    ) -> list[dict[str, Any]]:
        return self.global_rides[:limit]

    async def get_notification_preferences(self, user_id: str) -> Optional[dict[str, Any]]:
        return self.notification_preferences

    async def create_notification(
        self,
        user_id: str,
        notification_type: str,
        title: str,
        message: Optional[str],
        data: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        user = self.users[user_id]
        notification = build_notification_insert(
            user_id=user_id,
            wallet=user["wallet"],
            notification_type=notification_type,
            title=title,
            message=message,
            data=data,
            **kwargs,
        )
        notification.update({
            "id": str(uuid4()),
            "read": False,
            "created_at": notification["occurred_at"],
        })
        self.notifications.append(notification)
        return notification

    async def create_comment(
        self,
        user_id: str,
        target_type: str,
        target_id: str,
        content: str,
        parent_id: Optional[str] = None,
    ) -> dict[str, Any]:
        comment = {
            "id": str(uuid4()),
            "userId": user_id,
            "targetType": target_type,
            "targetId": target_id,
            "content": content,
            "createdAt": "2026-04-28T13:10:00+00:00",
            "updatedAt": "2026-04-28T13:10:00+00:00",
            "parentId": parent_id,
            "moderationState": "visible",
        }
        self.comments.append(comment)
        return comment

    async def get_comment(self, comment_id: str) -> Optional[dict[str, Any]]:
        for comment in self.comments:
            if comment["id"] == comment_id:
                return dict(comment)
        return None

    async def update_comment(self, comment_id: str, user_id: str, content: str) -> Optional[dict[str, Any]]:
        for comment in self.comments:
            if comment["id"] == comment_id and comment["userId"] == user_id:
                comment["content"] = content
                comment["updatedAt"] = "2026-04-28T13:20:00+00:00"
                return dict(comment)
        return None

    async def delete_comment(self, comment_id: str, user_id: str) -> bool:
        before = len(self.comments)
        self.comments = [
            comment
            for comment in self.comments
            if not (comment["id"] == comment_id and comment["userId"] == user_id)
        ]
        return len(self.comments) < before

    async def get_comments(self, target_type: str, target_id: str) -> list[dict[str, Any]]:
        return [
            comment
            for comment in self.comments
            if comment["targetType"] == target_type and comment["targetId"] == target_id
            and comment.get("moderationState", "visible") == "visible"
        ]

    async def get_kudos(self, user_id: str, target_type: str, target_id: str) -> Optional[dict[str, Any]]:
        if (user_id, target_type, target_id) in self.kudos:
            return {"user_id": user_id, "target_type": target_type, "target_id": target_id}
        return None

    async def create_kudos(self, user_id: str, target_type: str, target_id: str) -> dict[str, Any]:
        self.kudos.add((user_id, target_type, target_id))
        return {"user_id": user_id, "target_type": target_type, "target_id": target_id}

    async def delete_kudos(self, user_id: str, target_type: str, target_id: str) -> bool:
        key = (user_id, target_type, target_id)
        if key not in self.kudos:
            return False
        self.kudos.remove(key)
        return True

    async def increment_kudos_count(self, target_type: str, target_id: str) -> None:
        self.kudos_count += 1

    async def decrement_kudos_count(self, target_type: str, target_id: str) -> None:
        self.kudos_count = max(0, self.kudos_count - 1)

    async def get_interaction_summaries(
        self,
        target_type: str,
        target_ids: list[str],
        viewer_user_id: Optional[str] = None,
    ) -> dict[str, dict[str, Any]]:
        summaries = {
            target_id: {
                "kudosCount": 0,
                "commentCount": 0,
                "viewerHasKudos": False,
                "viewerReported": False,
                "reportStatus": None,
            }
            for target_id in target_ids
        }
        for comment in self.comments:
            target_id = comment["targetId"]
            if (
                comment["targetType"] == target_type
                and target_id in summaries
                and comment.get("moderationState", "visible") == "visible"
            ):
                summaries[target_id]["commentCount"] += 1
        for user_id, kudos_type, target_id in self.kudos:
            if kudos_type == target_type and target_id in summaries:
                summaries[target_id]["kudosCount"] += 1
                if viewer_user_id and user_id == viewer_user_id:
                    summaries[target_id]["viewerHasKudos"] = True
        if viewer_user_id:
            report_summaries = await self.get_report_summaries(target_type, target_ids, viewer_user_id)
            for target_id, report_summary in report_summaries.items():
                if target_id in summaries:
                    summaries[target_id].update(report_summary)
        return summaries

    async def create_social_report(
        self,
        reporter_id: str,
        target_type: str,
        target_id: str,
        reason: str,
        details: Optional[str] = None,
        moderation_metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        for report in self.reports:
            if (
                report["reporterId"] == reporter_id
                and report["targetType"] == target_type
                and report["targetId"] == target_id
                and report["status"] in {"open", "reviewing"}
            ):
                return dict(report)
        report = {
            "id": str(uuid4()),
            "reporterId": reporter_id,
            "targetType": target_type,
            "targetId": target_id,
            "reason": reason,
            "details": details,
            "status": "open",
            "createdAt": "2026-04-29T13:00:00+00:00",
            "updatedAt": "2026-04-29T13:00:00+00:00",
            "reviewedBy": None,
            "reviewedAt": None,
            "resolutionNote": None,
            "resolutionAction": None,
            "reporterOutcome": None,
            "reporterMessage": None,
            "moderationMetadata": moderation_metadata or {},
            "actionHistory": [],
        }
        self.reports.append(report)
        return dict(report)

    async def get_report_summaries(
        self,
        target_type: str,
        target_ids: list[str],
        reporter_id: str,
    ) -> dict[str, dict[str, Any]]:
        summaries = {
            target_id: {"viewerReported": False, "reportStatus": None, "reportId": None}
            for target_id in target_ids
        }
        for report in self.reports:
            target_id = report["targetId"]
            if (
                report["reporterId"] == reporter_id
                and report["targetType"] == target_type
                and target_id in summaries
            ):
                summaries[target_id] = {
                    "viewerReported": True,
                    "reportStatus": report["status"],
                    "reportId": report["id"],
                }
        return summaries

    async def list_social_reports(
        self,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        reports = [report for report in self.reports if status is None or report["status"] == status]
        return [dict(report) for report in reports[offset:offset + limit]]

    async def resolve_social_report(
        self,
        report_id: str,
        reviewer_id: str,
        status: str,
        resolution_note: Optional[str] = None,
        resolution_action: Optional[str] = None,
        reporter_message: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        for report in self.reports:
            if report["id"] == report_id:
                report["status"] = status
                report["reviewedBy"] = reviewer_id
                report["reviewedAt"] = "2026-04-29T13:10:00+00:00"
                report["resolutionNote"] = resolution_note
                action = resolution_action or ("review_started" if status == "reviewing" else "leave_visible")
                report["resolutionAction"] = action
                if status == "resolved" and action in {"hide", "remove"}:
                    moderation_state = "hidden" if action == "hide" else "removed"
                    if report["targetType"] == "ride" and report["targetId"] == self.ride_id:
                        self.ride.update({
                            "visibility": "private",
                            "comments_enabled": False,
                            "moderation_state": moderation_state,
                        })
                    elif report["targetType"] == "comment":
                        for comment in self.comments:
                            if comment["id"] == report["targetId"]:
                                comment["moderationState"] = moderation_state
                                break
                    elif report["targetType"] == "user" and report["targetId"] in self.users:
                        self.users[report["targetId"]]["is_public"] = False
                        self.users[report["targetId"]]["moderation_state"] = moderation_state
                    action_status = "applied"
                    reporter_outcome = moderation_state
                    default_message = "Your report was reviewed and action was taken."
                else:
                    action_status = "applied"
                    reporter_outcome = "dismissed" if status == "dismissed" else status
                    default_message = (
                        "Your report is being reviewed."
                        if status == "reviewing"
                        else "Your report was reviewed and resolved."
                    )
                report["reporterOutcome"] = reporter_outcome
                report["reporterMessage"] = reporter_message or default_message
                action_row = {
                    "id": str(uuid4()),
                    "reportId": report_id,
                    "actorId": reviewer_id,
                    "actionType": action,
                    "actionStatus": action_status,
                    "targetType": report["targetType"],
                    "targetId": report["targetId"],
                    "note": resolution_note,
                    "metadata": {"status": status},
                    "createdAt": "2026-04-29T13:10:00+00:00",
                }
                self.moderation_actions.append(action_row)
                report["actionHistory"] = [action_row]
                return dict(report)
        return None

    async def list_user_social_reports(
        self,
        reporter_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        reports = [report for report in self.reports if report["reporterId"] == reporter_id]
        sanitized = []
        for report in reports[offset:offset + limit]:
            copy = dict(report)
            copy.pop("resolutionNote", None)
            copy.pop("actionHistory", None)
            sanitized.append(copy)
        return sanitized

    async def get_social_report_for_reporter(
        self,
        report_id: str,
        reporter_id: str,
    ) -> Optional[dict[str, Any]]:
        for report in self.reports:
            if report["id"] == report_id and report["reporterId"] == reporter_id:
                copy = dict(report)
                copy.pop("resolutionNote", None)
                copy.pop("actionHistory", None)
                return copy
        return None


class FakePublicRiderRepo:
    def __init__(self) -> None:
        self.user_id = str(uuid4())
        self.private_user_id = str(uuid4())
        self.wallet = "rider-wallet"
        self.users = {
            "rider": {
                "id": self.user_id,
                "wallet": self.wallet,
                "username": "rider",
                "display_name": "Rider One",
                "avatar_url": "https://example.test/rider.png",
                "bio": "Climber",
                "is_public": True,
                "created_at": "2026-04-29T12:00:00+00:00",
                "follower_count": 7,
                "following_count": 3,
            },
            "private": {
                "id": self.private_user_id,
                "wallet": "private-wallet",
                "username": "private",
                "is_public": False,
                "follower_count": 2,
                "following_count": 1,
            },
        }
        ride_id = str(uuid4())
        self.rides = [
            {
                "id": ride_id,
                "user_id": self.user_id,
                "file_name": "Hill Work.fit",
                "processing_status": "completed",
                "started_at": "2026-04-29T10:00:00+00:00",
                "created_at": "2026-04-29T10:30:00+00:00",
                "distance_m": 18000,
                "elevation_gain_m": 620,
                "duration_sec": 3600,
                "dung_minted": 12,
                "visibility": "public",
                "map_visibility": "hide_entire",
                "map_hide_start_m": 0,
                "map_hide_end_m": 0,
                "moderation_state": "visible",
                "gps_track": encode_gps_track([
                    {"latitude": 39.95, "longitude": -75.17, "timestamp": 0},
                    {"latitude": 39.96, "longitude": -75.16, "timestamp": 60},
                    {"latitude": 39.97, "longitude": -75.15, "timestamp": 120},
                ]),
                "location": "Philadelphia, PA",
            }
        ]
        self.ride_media = {
            ride_id: [
                {
                    "id": str(uuid4()),
                    "ride_id": ride_id,
                    "storage_path": f"ride-media/{self.user_id}/{ride_id}/cover.jpg",
                    "file_name": "cover.jpg",
                    "mime_type": "image/jpeg",
                    "size_bytes": 1200,
                    "width": 1200,
                    "height": 800,
                    "sort_order": 0,
                    "role": "cover",
                    "moderation_state": "visible",
                    "upload_status": "ready",
                    "created_at": "2026-04-29T10:35:00+00:00",
                }
            ]
        }
        self.cards = [
            {
                "id": str(uuid4()),
                "wallet": self.wallet,
                "cardType": "CLIMB",
                "scopeId": str(uuid4()),
                "scopeName": "Manayunk Wall",
                "score": 420,
                "level": 3,
                "patternsScored": 12,
                "createdAt": "2026-04-29T12:00:00+00:00",
                "updatedAt": "2026-04-29T12:00:00+00:00",
            }
        ]
        self.recent_rides_limits: list[int] = []
        self.follows: set[tuple[str, str]] = set()

    async def get_user_by_identifier(self, identifier: str) -> Optional[dict[str, Any]]:
        for user in self.users.values():
            if identifier in {
                str(user.get("id")),
                str(user.get("wallet")),
                str(user.get("username")),
            }:
                return dict(user)
        return None

    async def get_user_stats(self, user_id: str) -> dict[str, Any]:
        return {
            "total_rides": 23,
            "total_distance_km": 512.5,
            "total_elevation_m": 9400,
            "total_dung_earned": 88,
        }

    async def get_public_user_recent_rides(self, user_id: str, limit: int = 10) -> list[dict[str, Any]]:
        self.recent_rides_limits.append(limit)
        return [ride for ride in self.rides if ride["user_id"] == user_id][:limit]

    async def list_ride_media_for_rides(
        self,
        ride_ids: list[str],
        *,
        include_uploading: bool = False,
    ) -> dict[str, list[dict[str, Any]]]:
        return {
            ride_id: list(self.ride_media.get(ride_id, []))
            for ride_id in ride_ids
        }

    async def get_public_beetle_cards_for_wallet(self, wallet: str) -> list[dict[str, Any]]:
        return [card for card in self.cards if card["wallet"] == wallet]

    async def get_follow(self, follower_id: str, following_id: str) -> Optional[dict[str, Any]]:
        if (follower_id, following_id) in self.follows:
            return {"follower_id": follower_id, "following_id": following_id}
        return None


class FakeVaultRepo:
    client = object()

    async def get_user_leaderboard_positions(self, wallet: str) -> list[dict[str, Any]]:
        return [
            {
                "vault_id": 7,
                "vault_name": "Manayunk Wall",
                "vault_signature": "sig",
                "rank": 1,
                "best_time_seconds": 312,
                "is_kom": True,
                "total_riders": 42,
            }
        ]

    async def get_user_leaderboard_stats(self, wallet: str) -> dict[str, Any]:
        return {
            "total_positions": 1,
            "kom_count": 1,
            "podium_count": 1,
            "top10_count": 1,
            "total_vaults_completed": 1,
            "best_percentile": 1,
        }

    async def get_vault_by_id(self, vault_id: int) -> dict[str, Any] | None:
        if vault_id != 7:
            return None
        return {
            "id": 7,
            "pda": "vault-pda-7",
            "name": "Manayunk Wall",
            "signature_hex": "sig",
            "kom_holder": "rider-wallet",
            "kom_time_s": 312,
        }

    async def get_vault_record_board_entries(
        self,
        vault_id: int,
    ) -> list[dict[str, Any]]:
        assert vault_id == 7
        return [
            {
                "user": "rider-wallet",
                "time_s": 312,
                "recorded_at": 1_700_000_000,
            }
        ]


@pytest.fixture
def viewer() -> AuthenticatedUser:
    return AuthenticatedUser(wallet="viewer-wallet", user_id="viewer-user", device_id="device-1")


@pytest.mark.asyncio
async def test_user_notifications_are_wallet_addressed_and_metadata_mirrored() -> None:
    client = FakeSupabaseClient()
    repo = SupabaseRepository(client)  # type: ignore[arg-type]

    async def get_user_by_id(user_id: str) -> dict[str, Any]:
        return {"id": user_id, "wallet": "wallet-1"}

    repo.get_user_by_id = get_user_by_id  # type: ignore[method-assign]

    created = await repo.create_notification(
        user_id="user-1",
        notification_type="comment",
        title="New comment",
        message="A rider commented",
        data={"ride_id": "ride-1"},
    )

    assert created["wallet"] == "wallet-1"
    assert created["notification_type"] == "comment_created"
    assert created["event_type"] == "comment_created"
    assert created["target_type"] is None
    assert created["data"] == {"ride_id": "ride-1"}
    assert created["metadata"] == {"ride_id": "ride-1"}


@pytest.mark.asyncio
async def test_follow_route_notification_contract(viewer: AuthenticatedUser) -> None:
    repo = FakeSocialRepo()
    target_uuid = uuid4()
    repo.target_id = str(target_uuid)
    repo.users[repo.target_id] = {
        "id": repo.target_id,
        "wallet": "target-wallet",
        "username": "target",
    }

    response = await follow_user(
        user_id=target_uuid,
        request=None,  # type: ignore[arg-type]
        current_user=viewer,
        repo=repo,  # type: ignore[arg-type]
    )

    assert response == {"status": "followed", "following_id": str(target_uuid)}
    assert repo.notifications[-1]["wallet"] == "target-wallet"
    assert repo.notifications[-1]["notification_type"] == "follow_created"
    assert repo.notifications[-1]["actor_id"] == viewer.user_id
    assert repo.notifications[-1]["target_type"] == "user"
    assert repo.notifications[-1]["target_id"] == viewer.user_id
    assert repo.notifications[-1]["metadata"]["follower_id"] == viewer.user_id


@pytest.mark.asyncio
async def test_social_graph_redacts_private_profiles_before_avatar_signing() -> None:
    private_id = str(uuid4())
    public_id = str(uuid4())
    repo = MagicMock()
    repo.get_user_by_id = AsyncMock(return_value={"id": str(uuid4()), "is_public": True})
    repo.get_followers = AsyncMock(return_value=[
        {
            "id": private_id,
            "wallet": "private-wallet",
            "username": "private",
            "display_name": "Private Rider",
            "bio": "Hidden",
            "avatar_storage_path": "avatars/private/avatar.jpg",
            "is_public": False,
        },
        {
            "id": public_id,
            "wallet": "public-wallet",
            "username": "public",
            "display_name": "Public Rider",
            "avatar_storage_path": "avatars/public/avatar.jpg",
            "is_public": True,
        },
    ])

    storage = MagicMock()
    storage.get_signed_url = AsyncMock(return_value="https://example.test/public-avatar")

    with patch("app.avatar_media_contracts.create_file_storage_service", return_value=storage):
        followers = await get_followers(
            user_id=uuid4(),
            current_user=None,
            request=None,  # type: ignore[arg-type]
            repo=repo,  # type: ignore[arg-type]
        )

    private, public = followers
    assert str(private.id) == private_id
    assert private.display_name is None
    assert private.bio is None
    assert private.avatar_url is None
    assert private.rider is not None
    assert private.rider.display_name is None
    assert private.rider.avatar_url is None
    assert private.rider.is_public is False
    assert public.display_name == "Public Rider"
    assert public.avatar_url == "https://example.test/public-avatar"
    storage.get_signed_url.assert_awaited_once_with(
        "avatars/public/avatar.jpg",
        expires_in=3600,
    )


@pytest.mark.asyncio
async def test_suggested_riders_excludes_private_profiles_before_signing(viewer: AuthenticatedUser) -> None:
    private_id = str(uuid4())
    public_id = str(uuid4())
    repo = MagicMock()
    repo.get_following_ids = AsyncMock(return_value=[])
    repo._run = AsyncMock(return_value=SimpleNamespace(data=[
        {
            "id": private_id,
            "wallet": "private-wallet",
            "username": "private",
            "display_name": "Private Rider",
            "avatar_storage_path": "avatars/private/avatar.jpg",
            "is_public": False,
        },
        {
            "id": public_id,
            "wallet": "public-wallet",
            "username": "public",
            "display_name": "Public Rider",
            "avatar_storage_path": "avatars/public/avatar.jpg",
            "is_public": True,
        },
    ]))

    storage = MagicMock()
    storage.get_signed_url = AsyncMock(return_value="https://example.test/public-avatar")

    with patch("app.avatar_media_contracts.create_file_storage_service", return_value=storage):
        response = await get_suggested_riders(
            request=None,  # type: ignore[arg-type]
            limit=10,
            current_user=viewer,
            repo=repo,  # type: ignore[arg-type]
        )

    assert response["count"] == 1
    assert response["suggestions"][0]["id"] == public_id
    assert response["suggestions"][0]["avatarUrl"] == "https://example.test/public-avatar"
    assert response["suggestions"][0]["rider"]["avatarUrl"] == "https://example.test/public-avatar"
    storage.get_signed_url.assert_awaited_once_with(
        "avatars/public/avatar.jpg",
        expires_in=3600,
    )


@pytest.mark.asyncio
async def test_comments_redact_private_author_avatar_before_signing(viewer: AuthenticatedUser) -> None:
    repo = FakeSocialRepo()
    private_author_id = str(uuid4())
    repo.comments.append({
        "id": str(uuid4()),
        "userId": private_author_id,
        "targetType": "ride",
        "targetId": repo.ride_id,
        "username": "private",
        "displayName": "Private Rider",
        "avatar_storage_path": "avatars/private/comment.jpg",
        "isPublic": False,
        "content": "Private profile comment",
        "createdAt": "2026-04-28T13:10:00+00:00",
        "updatedAt": "2026-04-28T13:10:00+00:00",
        "moderationState": "visible",
    })

    storage = MagicMock()
    storage.get_signed_url = AsyncMock(return_value="https://example.test/private-avatar")

    with patch("app.avatar_media_contracts.create_file_storage_service", return_value=storage):
        response = await get_ride_comments(
            ride_id=UUID(repo.ride_id),
            request=None,  # type: ignore[arg-type]
            current_user=viewer,
            repo=repo,  # type: ignore[arg-type]
        )

    comment = response["comments"][0]
    assert comment["displayName"] is None
    assert comment["avatarUrl"] is None
    assert comment["author"]["displayName"] is None
    assert comment["author"]["avatarUrl"] is None
    assert comment["author"]["isPublic"] is False
    storage.get_signed_url.assert_not_awaited()


@pytest.mark.asyncio
async def test_feed_redacts_private_actor_avatar_before_signing(viewer: AuthenticatedUser) -> None:
    repo = FakeSocialRepo()
    repo.users[repo.owner_id].update({
        "display_name": "Private Owner",
        "avatar_storage_path": "avatars/private/feed.jpg",
        "is_public": False,
    })
    repo.follows.add((viewer.user_id, repo.owner_id))
    repo.followed_rides = [
        {
            "id": repo.ride_id,
            "user_id": repo.owner_id,
            "file_name": "Private Actor.fit",
            "processing_status": "completed",
            "started_at": "2026-04-28T13:00:00+00:00",
            "created_at": "2026-04-28T13:05:00+00:00",
            "visibility": "public",
            "map_visibility": "hide_start_end",
            "map_hide_start_m": 200,
            "map_hide_end_m": 200,
            "moderation_state": "visible",
        }
    ]

    storage = MagicMock()
    storage.get_signed_url = AsyncMock(return_value="https://example.test/private-avatar")

    with patch("app.avatar_media_contracts.create_file_storage_service", return_value=storage):
        response = await get_feed(
            limit=20,
            before=None,
            current_user=viewer,
            repo=repo,  # type: ignore[arg-type]
        )

    actor = response["activities"][0]["actor"]
    assert actor["id"] == repo.owner_id
    assert actor["displayName"] is None
    assert actor["avatarUrl"] is None
    assert actor["isPublic"] is False
    storage.get_signed_url.assert_not_awaited()


@pytest.mark.asyncio
async def test_comments_respect_disabled_comments(viewer: AuthenticatedUser) -> None:
    repo = FakeSocialRepo()
    repo.ride["comments_enabled"] = False

    with pytest.raises(HTTPException) as exc:
        await add_comment_to_ride(
            ride_id=UUID(repo.ride_id),
            comment=CommentCreate(content="Nice ride"),
            request=None,  # type: ignore[arg-type]
            current_user=viewer,
            repo=repo,  # type: ignore[arg-type]
        )

    assert exc.value.status_code == 403
    assert repo.comments == []


@pytest.mark.asyncio
async def test_comment_reply_parent_must_belong_to_same_ride(viewer: AuthenticatedUser) -> None:
    repo = FakeSocialRepo()
    other_ride_id = str(uuid4())
    parent_id = str(uuid4())
    repo.comments.append({
        "id": parent_id,
        "userId": repo.owner_id,
        "targetType": "ride",
        "targetId": other_ride_id,
        "content": "Other ride",
        "createdAt": "2026-04-28T13:00:00+00:00",
        "updatedAt": "2026-04-28T13:00:00+00:00",
        "parentId": None,
        "moderationState": "visible",
    })

    with pytest.raises(HTTPException) as exc:
        await add_comment_to_ride(
            ride_id=UUID(repo.ride_id),
            comment=CommentCreate(content="Cross ride reply", parentId=UUID(parent_id)),
            request=None,  # type: ignore[arg-type]
            current_user=viewer,
            repo=repo,  # type: ignore[arg-type]
        )

    assert exc.value.status_code == 404
    assert len(repo.comments) == 1


@pytest.mark.asyncio
async def test_comments_and_kudos_respect_ride_visibility(viewer: AuthenticatedUser) -> None:
    repo = FakeSocialRepo()
    repo.ride["visibility"] = "private"

    with pytest.raises(HTTPException) as comments_exc:
        await get_ride_comments(
            ride_id=UUID(repo.ride_id),
            request=None,  # type: ignore[arg-type]
            current_user=viewer,
            repo=repo,  # type: ignore[arg-type]
        )
    assert comments_exc.value.status_code == 404

    with pytest.raises(HTTPException) as kudos_exc:
        await give_kudos_to_ride(
            ride_id=UUID(repo.ride_id),
            request=None,  # type: ignore[arg-type]
            current_user=viewer,
            repo=repo,  # type: ignore[arg-type]
        )
    assert kudos_exc.value.status_code == 404
    assert repo.kudos_count == 0


@pytest.mark.asyncio
async def test_followers_can_comment_on_followers_only_rides(viewer: AuthenticatedUser) -> None:
    repo = FakeSocialRepo()
    repo.ride["visibility"] = "followers"
    repo.follows.add((viewer.user_id, repo.owner_id))

    created = await add_comment_to_ride(
        ride_id=UUID(repo.ride_id),
        comment=CommentCreate(content="  Strong effort  "),
        request=None,  # type: ignore[arg-type]
        current_user=viewer,
        repo=repo,  # type: ignore[arg-type]
    )

    assert created["content"] == "Strong effort"
    assert repo.notifications[-1]["wallet"] == "owner-wallet"
    assert repo.notifications[-1]["event_type"] == "comment_created"
    assert repo.notifications[-1]["actor_id"] == viewer.user_id
    assert repo.notifications[-1]["target_type"] == "ride"
    assert repo.notifications[-1]["target_id"] == repo.ride_id
    assert repo.notifications[-1]["metadata"]["ride_id"] == repo.ride_id


@pytest.mark.asyncio
async def test_following_feed_returns_real_followed_rides(viewer: AuthenticatedUser) -> None:
    repo = FakeSocialRepo()
    repo.follows.add((viewer.user_id, repo.owner_id))
    repo.followed_rides = [
        {
            "id": repo.ride_id,
            "user_id": repo.owner_id,
            "file_name": "Morning Ride.fit",
            "processing_status": "completed",
            "started_at": "2026-04-28T13:00:00+00:00",
            "created_at": "2026-04-28T13:05:00+00:00",
            "distance_m": 32100,
            "elevation_gain_m": 870,
            "duration_sec": 5020,
            "dung_minted": 42,
            "visibility": "public",
            "map_visibility": "hide_start_end",
            "map_hide_start_m": 200,
            "map_hide_end_m": 200,
            "moderation_state": "visible",
        }
    ]

    response = await get_feed(
        limit=20,
        before=None,
        current_user=viewer,
        repo=repo,  # type: ignore[arg-type]
    )

    assert response["has_more"] is False
    assert response["contractVersion"] == "feed.v1"
    assert response["activities"][0]["id"] == repo.ride_id
    assert response["activities"][0]["type"] == "ride"
    assert response["activities"][0]["eventType"] == "ride_completed"
    assert response["activities"][0]["title"] == "Morning Ride"
    assert response["activities"][0]["target"]["type"] == "ride"
    assert response["activities"][0]["target"]["id"] == repo.ride_id
    assert response["activities"][0]["primaryAction"] == "open_ride"
    assert response["activities"][0]["viewerCapabilities"]["canView"] is True
    assert response["activities"][0]["user"]["username"] == "owner"
    assert response["activities"][0]["metadata"]["kudosCount"] == 0
    assert response["activities"][0]["metadata"]["commentCount"] == 0
    assert response["activities"][0]["metadata"]["viewerHasKudos"] is False
    assert "calEarned" not in response["activities"][0]["metadata"]
    assert "dungEarned" not in response["activities"][0]["metadata"]
    assert response["next_cursor"] == "2026-04-28T13:00:00+00:00"


@pytest.mark.asyncio
@pytest.mark.parametrize("persisted_cal", [0, 222])
async def test_following_feed_suppresses_cal_for_threshold_provisional_hold_parent(
    viewer: AuthenticatedUser,
    persisted_cal: int,
) -> None:
    repo = FakeSocialRepo()
    repo.follows.add((viewer.user_id, repo.owner_id))
    repo.followed_rides = [
        {
            "id": repo.ride_id,
            "user_id": repo.owner_id,
            "file_name": "Held Ride.fit",
            "processing_status": "completed",
            "started_at": "2026-04-28T13:00:00+00:00",
            "created_at": "2026-04-28T13:05:00+00:00",
            "cal_earned": persisted_cal,
            "reward_policy": "threshold_provisional_hold_v1",
            "visibility": "public",
            "moderation_state": "visible",
        }
    ]

    response = await get_feed(
        limit=20,
        before=None,
        current_user=viewer,
        repo=repo,  # type: ignore[arg-type]
    )

    assert "calEarned" not in response["activities"][0]["metadata"]
    assert "dungEarned" not in response["activities"][0]["metadata"]


@pytest.mark.asyncio
@pytest.mark.parametrize("persisted_cal", [0, 222])
async def test_global_feed_suppresses_cal_for_threshold_provisional_hold_parent(
    persisted_cal: int,
) -> None:
    repo = FakeSocialRepo()
    repo.global_rides = [
        {
            "id": repo.ride_id,
            "user_id": repo.owner_id,
            "file_name": "Held Ride.fit",
            "processing_status": "completed",
            "started_at": "2026-04-28T13:00:00+00:00",
            "created_at": "2026-04-28T13:05:00+00:00",
            "cal_earned": persisted_cal,
            "reward_policy": "threshold_provisional_hold_v1",
            "visibility": "public",
            "moderation_state": "visible",
        }
    ]

    response = await get_global_feed(
        limit=20,
        before=None,
        activity_type=None,
        repo=repo,  # type: ignore[arg-type]
    )

    assert "calEarned" not in response["activities"][0]["metadata"]
    assert "dungEarned" not in response["activities"][0]["metadata"]


@pytest.mark.asyncio
async def test_following_feed_includes_the_signed_in_riders_own_rides(
    viewer: AuthenticatedUser,
) -> None:
    repo = FakeSocialRepo()
    repo.followed_rides = [
        {
            "id": repo.ride_id,
            "user_id": repo.viewer_id,
            "file_name": "Lunch Ride.fit",
            "processing_status": "completed",
            "started_at": "2026-04-28T13:00:00+00:00",
            "created_at": "2026-04-28T13:05:00+00:00",
            "distance_m": 12_300,
            "elevation_gain_m": 230,
            "duration_sec": 2_900,
            "visibility": "followers",
            "map_visibility": "hide_start_end",
            "map_hide_start_m": 200,
            "map_hide_end_m": 200,
            "moderation_state": "visible",
        }
    ]

    response = await get_feed(
        limit=20,
        before=None,
        current_user=viewer,
        repo=repo,  # type: ignore[arg-type]
    )

    assert [activity["id"] for activity in response["activities"]] == [repo.ride_id]
    assert response["activities"][0]["actor"]["id"] == repo.viewer_id


@pytest.mark.asyncio
async def test_following_feed_excludes_non_user_visible_ride_noise(viewer: AuthenticatedUser) -> None:
    repo = FakeSocialRepo()
    repo.follows.add((viewer.user_id, repo.owner_id))
    repo.followed_rides = [
        {
            "id": repo.ride_id,
            "user_id": repo.owner_id,
            "file_name": "Still Uploading.fit",
            "processing_status": "pending",
            "started_at": "2026-04-28T13:00:00+00:00",
            "created_at": "2026-04-28T13:05:00+00:00",
            "visibility": "public",
            "map_visibility": "hide_start_end",
            "map_hide_start_m": 200,
            "map_hide_end_m": 200,
            "moderation_state": "visible",
        }
    ]

    response = await get_feed(
        limit=20,
        before=None,
        current_user=viewer,
        repo=repo,  # type: ignore[arg-type]
    )

    assert response["activities"] == []
    assert response["next_cursor"] is None


@pytest.mark.asyncio
async def test_interaction_summary_exposes_counts_and_viewer_state(viewer: AuthenticatedUser) -> None:
    repo = FakeSocialRepo()
    await repo.create_comment(
        user_id=repo.owner_id,
        target_type="ride",
        target_id=repo.ride_id,
        content="Good climb",
    )

    await give_kudos_to_ride(
        ride_id=UUID(repo.ride_id),
        request=None,  # type: ignore[arg-type]
        current_user=viewer,
        repo=repo,  # type: ignore[arg-type]
    )

    response = await get_ride_interactions(
        ride_id=UUID(repo.ride_id),
        request=None,  # type: ignore[arg-type]
        current_user=viewer,
        repo=repo,  # type: ignore[arg-type]
    )

    assert response == {
        "rideId": repo.ride_id,
        "kudosCount": 1,
        "commentCount": 1,
        "viewerHasKudos": True,
        "viewerReported": False,
        "reportStatus": None,
        "commentsEnabled": True,
        "canComment": True,
    }


@pytest.mark.asyncio
async def test_owner_can_update_and_delete_own_comment(viewer: AuthenticatedUser) -> None:
    repo = FakeSocialRepo()
    created = await add_comment_to_ride(
        ride_id=UUID(repo.ride_id),
        comment=CommentCreate(content="  First pass  "),
        request=None,  # type: ignore[arg-type]
        current_user=viewer,
        repo=repo,  # type: ignore[arg-type]
    )

    updated = await update_ride_comment(
        ride_id=UUID(repo.ride_id),
        comment_id=UUID(created["id"]),
        update=CommentUpdate(content="  Cleaned up  "),
        request=None,  # type: ignore[arg-type]
        current_user=viewer,
        repo=repo,  # type: ignore[arg-type]
    )

    assert updated["content"] == "Cleaned up"

    deleted = await delete_ride_comment(
        ride_id=UUID(repo.ride_id),
        comment_id=UUID(created["id"]),
        request=None,  # type: ignore[arg-type]
        current_user=viewer,
        repo=repo,  # type: ignore[arg-type]
    )

    assert deleted == {"status": "comment_deleted", "comment_id": created["id"]}
    assert repo.comments == []


@pytest.mark.asyncio
async def test_cannot_update_or_delete_someone_elses_comment(viewer: AuthenticatedUser) -> None:
    repo = FakeSocialRepo()
    created = await repo.create_comment(
        user_id=repo.owner_id,
        target_type="ride",
        target_id=repo.ride_id,
        content="Owner note",
    )

    with pytest.raises(HTTPException) as update_exc:
        await update_ride_comment(
            ride_id=UUID(repo.ride_id),
            comment_id=UUID(created["id"]),
            update=CommentUpdate(content="Nope"),
            request=None,  # type: ignore[arg-type]
            current_user=viewer,
            repo=repo,  # type: ignore[arg-type]
        )

    with pytest.raises(HTTPException) as delete_exc:
        await delete_ride_comment(
            ride_id=UUID(repo.ride_id),
            comment_id=UUID(created["id"]),
            request=None,  # type: ignore[arg-type]
            current_user=viewer,
            repo=repo,  # type: ignore[arg-type]
        )

    assert update_exc.value.status_code == 403
    assert delete_exc.value.status_code == 403
    assert repo.comments == [created]


@pytest.mark.asyncio
async def test_reporting_comment_marks_viewer_state_without_changing_counts(viewer: AuthenticatedUser) -> None:
    repo = FakeSocialRepo()
    created = await repo.create_comment(
        user_id=repo.owner_id,
        target_type="ride",
        target_id=repo.ride_id,
        content="Sketchy comment",
    )

    report = await report_social_content(
        report=SocialReportCreate(
            target_type="comment",
            target_id=UUID(created["id"]),
            reason="spam",
            details="Looks automated",
        ),
        request=None,  # type: ignore[arg-type]
        current_user=viewer,
        repo=repo,  # type: ignore[arg-type]
    )

    comments = await get_ride_comments(
        ride_id=UUID(repo.ride_id),
        request=None,  # type: ignore[arg-type]
        current_user=viewer,
        repo=repo,  # type: ignore[arg-type]
    )
    interactions = await get_ride_interactions(
        ride_id=UUID(repo.ride_id),
        request=None,  # type: ignore[arg-type]
        current_user=viewer,
        repo=repo,  # type: ignore[arg-type]
    )

    assert report["status"] == "open"
    assert comments["comments"][0]["author"]["contractVersion"] == "public_rider_ref.v1"
    assert comments["comments"][0]["author"]["id"] == repo.owner_id
    assert "wallet" not in comments["comments"][0]["author"]
    assert comments["comments"][0]["viewerReported"] is True
    assert comments["comments"][0]["reportStatus"] == "open"
    assert interactions["commentCount"] == 1


@pytest.mark.asyncio
async def test_reporting_ride_marks_interaction_state(viewer: AuthenticatedUser) -> None:
    repo = FakeSocialRepo()

    await report_social_content(
        report=SocialReportCreate(
            target_type="ride",
            target_id=UUID(repo.ride_id),
            reason="privacy",
        ),
        request=None,  # type: ignore[arg-type]
        current_user=viewer,
        repo=repo,  # type: ignore[arg-type]
    )

    interactions = await get_ride_interactions(
        ride_id=UUID(repo.ride_id),
        request=None,  # type: ignore[arg-type]
        current_user=viewer,
        repo=repo,  # type: ignore[arg-type]
    )

    assert interactions["viewerReported"] is True
    assert interactions["reportStatus"] == "open"


@pytest.mark.asyncio
async def test_reporting_ride_photo_validates_visible_foreign_ride(viewer: AuthenticatedUser) -> None:
    repo = FakeSocialRepo()

    report = await report_social_content(
        report=SocialReportCreate(
            target_type="ride_media",
            target_id=UUID(repo.ride_media_id),
            reason="privacy",
            details="Face visible",
        ),
        request=None,  # type: ignore[arg-type]
        current_user=viewer,
        repo=repo,  # type: ignore[arg-type]
    )

    owner = AuthenticatedUser(
        wallet="owner-wallet",
        user_id=repo.owner_id,
        device_id="owner-device",
    )
    with pytest.raises(HTTPException) as owner_exc:
        await report_social_content(
            report=SocialReportCreate(
                target_type="ride_media",
                target_id=UUID(repo.ride_media_id),
                reason="privacy",
            ),
            request=None,  # type: ignore[arg-type]
            current_user=owner,
            repo=repo,  # type: ignore[arg-type]
        )

    assert report["targetType"] == "ride_media"
    assert report["targetId"] == repo.ride_media_id
    assert report["target"]["type"] == "ride_media"
    assert report["target"]["metadata"]["rideId"] == repo.ride_id
    assert report["target"]["metadata"]["mediaId"] == repo.ride_media_id
    assert report["primaryAction"] == "open_ride"
    assert owner_exc.value.status_code == 400


@pytest.mark.asyncio
async def test_admin_can_list_and_resolve_social_reports(viewer: AuthenticatedUser) -> None:
    repo = FakeSocialRepo()
    report = await repo.create_social_report(
        reporter_id=viewer.user_id,
        target_type="ride",
        target_id=repo.ride_id,
        reason="spam",
    )
    admin_id = uuid4()

    queue = await get_moderation_reports(
        request=None,  # type: ignore[arg-type]
        report_status="open",
        limit=10,
        offset=0,
        admin_ctx=(admin_id, "admin"),
        repo=repo,  # type: ignore[arg-type]
    )
    resolved = await resolve_moderation_report(
        report_id=UUID(report["id"]),
        update=SocialReportResolve(status="resolved", action="hide", resolutionNote="Handled"),
        request=None,  # type: ignore[arg-type]
        admin_ctx=(admin_id, "admin"),
        repo=repo,  # type: ignore[arg-type]
    )
    with pytest.raises(HTTPException) as rereport_exc:
        await report_social_content(
            report=SocialReportCreate(
                target_type="ride",
                target_id=UUID(repo.ride_id),
                reason="safety",
            ),
            request=None,  # type: ignore[arg-type]
            current_user=viewer,
            repo=repo,  # type: ignore[arg-type]
        )

    assert queue["count"] == 1
    assert resolved["status"] == "resolved"
    assert resolved["reviewedBy"] == str(admin_id)
    assert resolved["resolutionAction"] == "hide"
    assert resolved["actionHistory"][0]["actionStatus"] == "applied"
    assert resolved["reporterOutcome"] == "hidden"
    assert repo.ride["visibility"] == "private"
    assert repo.ride["moderation_state"] == "hidden"
    assert repo.notifications[-1]["notification_type"] == "report_resolved"
    assert repo.notifications[-1]["target_type"] == "report"
    assert repo.notifications[-1]["metadata"]["reporter_outcome"] == "hidden"
    assert rereport_exc.value.status_code == 404


@pytest.mark.asyncio
async def test_moderation_hide_removes_ride_from_social_surfaces(viewer: AuthenticatedUser) -> None:
    repo = FakeSocialRepo()
    repo.follows.add((viewer.user_id, repo.owner_id))
    repo.followed_rides = [{
        "id": repo.ride_id,
        "user_id": repo.owner_id,
        "file_name": "Reported Ride.fit",
        "processing_status": "completed",
        "started_at": "2026-04-28T13:00:00+00:00",
        "created_at": "2026-04-28T13:05:00+00:00",
        "visibility": "public",
        "map_visibility": "hide_start_end",
        "map_hide_start_m": 200,
        "map_hide_end_m": 200,
        "moderation_state": "visible",
    }]
    report = await repo.create_social_report(
        reporter_id=viewer.user_id,
        target_type="ride",
        target_id=repo.ride_id,
        reason="privacy",
    )

    await resolve_moderation_report(
        report_id=UUID(report["id"]),
        update=SocialReportResolve(status="resolved", action="hide", resolutionNote="Handled"),
        request=None,  # type: ignore[arg-type]
        admin_ctx=(uuid4(), "admin"),
        repo=repo,  # type: ignore[arg-type]
    )
    repo.followed_rides[0].update({
        "visibility": repo.ride["visibility"],
        "moderation_state": repo.ride["moderation_state"],
    })

    response = await get_feed(
        limit=20,
        before=None,
        current_user=viewer,
        repo=repo,  # type: ignore[arg-type]
    )
    with pytest.raises(HTTPException) as comments_exc:
        await get_ride_comments(
            ride_id=UUID(repo.ride_id),
            request=None,  # type: ignore[arg-type]
            current_user=viewer,
            repo=repo,  # type: ignore[arg-type]
        )

    assert response["activities"] == []
    assert comments_exc.value.status_code == 404


@pytest.mark.asyncio
async def test_moderation_remove_hides_comment_from_counts_and_threads(viewer: AuthenticatedUser) -> None:
    repo = FakeSocialRepo()
    comment = await repo.create_comment(
        user_id=repo.owner_id,
        target_type="ride",
        target_id=repo.ride_id,
        content="spam",
    )
    report = await repo.create_social_report(
        reporter_id=viewer.user_id,
        target_type="comment",
        target_id=comment["id"],
        reason="spam",
    )

    resolved = await resolve_moderation_report(
        report_id=UUID(report["id"]),
        update=SocialReportResolve(status="resolved", action="remove", resolutionNote="Removed"),
        request=None,  # type: ignore[arg-type]
        admin_ctx=(uuid4(), "admin"),
        repo=repo,  # type: ignore[arg-type]
    )
    comments = await get_ride_comments(
        ride_id=UUID(repo.ride_id),
        request=None,  # type: ignore[arg-type]
        current_user=viewer,
        repo=repo,  # type: ignore[arg-type]
    )
    interactions = await get_ride_interactions(
        ride_id=UUID(repo.ride_id),
        request=None,  # type: ignore[arg-type]
        current_user=viewer,
        repo=repo,  # type: ignore[arg-type]
    )

    assert resolved["actionHistory"][0]["actionStatus"] == "applied"
    assert resolved["reporterOutcome"] == "removed"
    assert comments["comments"] == []
    assert interactions["commentCount"] == 0


@pytest.mark.asyncio
async def test_reporter_can_see_outcome_without_internal_notes(viewer: AuthenticatedUser) -> None:
    repo = FakeSocialRepo()
    report = await repo.create_social_report(
        reporter_id=viewer.user_id,
        target_type="ride",
        target_id=repo.ride_id,
        reason="spam",
    )
    await repo.resolve_social_report(
        report_id=report["id"],
        reviewer_id=str(uuid4()),
        status="dismissed",
        resolution_note="Internal moderator note",
        resolution_action="leave_visible",
        reporter_message="We reviewed this report and dismissed it.",
    )

    list_response = await get_my_social_reports(
        request=None,  # type: ignore[arg-type]
        limit=10,
        offset=0,
        current_user=viewer,
        repo=repo,  # type: ignore[arg-type]
    )
    detail_response = await get_my_social_report(
        report_id=UUID(report["id"]),
        request=None,  # type: ignore[arg-type]
        current_user=viewer,
        repo=repo,  # type: ignore[arg-type]
    )

    assert list_response["count"] == 1
    assert list_response["reports"][0]["reporterOutcome"] == "dismissed"
    assert list_response["reports"][0]["reporterMessage"] == "We reviewed this report and dismissed it."
    assert "resolutionNote" not in list_response["reports"][0]
    assert "resolutionNote" not in detail_response


@pytest.mark.asyncio
async def test_public_rider_profile_exposes_social_counts_and_public_modules() -> None:
    repo = FakePublicRiderRepo()

    profile = await get_user_profile(
        identifier="rider",
        repo=repo,  # type: ignore[arg-type]
    )
    storage = SimpleNamespace(get_signed_url=AsyncMock(return_value="https://media.example.test/cover.jpg"))
    with patch("app.ride_media_contracts.create_file_storage_service", return_value=storage):
        rides = await get_public_user_recent_rides(
            identifier="rider",
            limit=10,
            repo=repo,  # type: ignore[arg-type]
        )
    cards = await get_public_user_beetle_cards(
        identifier="rider",
        repo=repo,  # type: ignore[arg-type]
    )

    assert profile.follower_count == 7
    assert profile.following_count == 3
    assert profile.rider is not None
    assert profile.rider.id == repo.user_id
    assert profile.rider.username == "rider"
    assert profile.rider.display_name == "Rider One"
    assert "total_dung_earned" not in profile.model_dump()
    assert rides["is_public"] is True
    assert rides["rides"][0]["title"] == "Hill Work"
    assert "dung_minted" not in rides["rides"][0]
    assert rides["rides"][0]["routePreview"]["contractVersion"] == "route_preview.v1"
    assert rides["rides"][0]["routePreview"]["pointCount"] == 0
    assert rides["rides"][0]["routePreview"]["placeLabel"] == "Philadelphia, PA"
    assert rides["rides"][0]["routePreview"]["fallbackReason"] == "privacy_redacted"
    assert rides["rides"][0]["primaryMedia"]["url"] == "https://media.example.test/cover.jpg"
    assert rides["rides"][0]["media"][0]["role"] == "cover"
    assert cards["is_public"] is True
    assert cards["cards"][0]["scopeName"] == "Manayunk Wall"
    assert "wallet" not in cards["cards"][0]


@pytest.mark.asyncio
async def test_public_rider_profile_accepts_user_id_identifier() -> None:
    repo = FakePublicRiderRepo()

    profile = await get_user_profile(
        identifier=repo.user_id,
        repo=repo,  # type: ignore[arg-type]
    )
    rides = await get_public_user_recent_rides(
        identifier=repo.user_id,
        limit=10,
        repo=repo,  # type: ignore[arg-type]
    )
    cards = await get_public_user_beetle_cards(
        identifier=repo.user_id,
        repo=repo,  # type: ignore[arg-type]
    )

    assert str(profile.id) == repo.user_id
    assert profile.username == "rider"
    assert profile.display_name == "Rider One"
    assert profile.rider is not None
    assert profile.rider.id == repo.user_id
    assert rides["is_public"] is True
    assert rides["rides"][0]["title"] == "Hill Work"
    assert cards["is_public"] is True
    assert cards["cards"][0]["scopeName"] == "Manayunk Wall"
    assert "wallet" not in cards["cards"][0]


@pytest.mark.asyncio
async def test_owner_rider_profile_keeps_self_only_aggregate_economy() -> None:
    repo = FakePublicRiderRepo()
    owner = AuthenticatedUser(
        wallet=repo.wallet,
        user_id=repo.user_id,
        device_id="device-1",
    )

    profile = await get_user_profile(
        identifier="rider",
        current_user=owner,
        repo=repo,  # type: ignore[arg-type]
    )

    assert profile.model_dump()["total_dung_earned"] == 88


@pytest.mark.asyncio
async def test_public_rider_profile_bootstrap_returns_one_public_identity_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakePublicRiderRepo()
    monkeypatch.setattr(
        user_routes,
        "project_public_record_board",
        lambda *_args, **_kwargs: PublicRecordBoardProjection(
            entries=[
                {
                    "user": "rider-wallet",
                    "time_s": 312,
                    "recorded_at": 1_700_000_000,
                    "position": 1,
                    "rank": 1,
                    "tie_size": 1,
                    "is_tied": False,
                }
            ],
            kom_holder="rider-wallet",
            kom_time_s=312,
        ),
    )

    response = await get_public_user_profile_bootstrap(
        identifier="rider",
        limit=30,
        current_user=None,
        repo=repo,  # type: ignore[arg-type]
        vault_repo=FakeVaultRepo(),  # type: ignore[arg-type]
    )

    assert response["contractVersion"] == "public_rider_profile.v1"
    assert response["rider"] == {
        "contractVersion": "public_rider_ref.v1",
        "id": repo.user_id,
        "username": "rider",
        "displayName": "Rider One",
        "avatarUrl": "https://example.test/rider.png",
        "isPublic": True,
        "viewerRelationship": "none",
    }
    assert "wallet" not in response["rider"]
    assert response["profile"]["rider"] == response["rider"]
    assert "total_dung_earned" not in response["profile"]
    assert response["recentRides"]["rides"][0]["title"] == "Hill Work"
    assert "dung_minted" not in response["recentRides"]["rides"][0]
    assert response["beetleCards"]["cards"][0]["scopeName"] == "Manayunk Wall"
    assert "wallet" not in response["beetleCards"]["cards"][0]
    assert response["leaderboard"]["positions"][0]["vault_name"] == "Manayunk Wall"
    assert response["viewerCapabilities"]["canView"] is True
    assert response["viewerCapabilities"]["canFollow"] is False
    assert response["viewerCapabilities"]["canReport"] is False
    assert response["viewerCapabilities"]["canShare"] is True
    assert response["viewerCapabilities"]["canOpenScan"] is True
    assert response["viewerCapabilities"]["viewerRelationship"] == "none"
    assert response["modules"][0]["contractVersion"] == "public_profile_module.v1"
    assert {module["id"] for module in response["modules"]} >= {"recent_rides", "beetle_cards", "leaderboard"}
    assert repo.recent_rides_limits[-1] == 30


@pytest.mark.asyncio
async def test_public_rider_profile_bootstrap_reconciles_follower_relationship_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = FakePublicRiderRepo()
    viewer = AuthenticatedUser(
        wallet="viewer-wallet",
        user_id="viewer-user",
        device_id="device-1",
    )
    repo.follows.add((viewer.user_id, repo.user_id))
    monkeypatch.setattr(
        user_routes,
        "project_public_record_board",
        lambda *_args, **_kwargs: PublicRecordBoardProjection(
            entries=[],
            kom_holder=None,
            kom_time_s=None,
        ),
    )

    response = await get_public_user_profile_bootstrap(
        identifier="rider",
        limit=5,
        current_user=viewer,
        repo=repo,  # type: ignore[arg-type]
        vault_repo=FakeVaultRepo(),  # type: ignore[arg-type]
    )

    assert response["followState"]["isFollowing"] is True
    assert response["privacy"]["isFollower"] is True
    assert response["profile"]["privacy"]["isFollower"] is True
    assert response["rider"]["viewerRelationship"] == "following"
    assert response["profile"]["rider"]["viewerRelationship"] == "following"
    assert response["viewerCapabilities"]["viewerRelationship"] == "following"


@pytest.mark.asyncio
async def test_private_rider_public_modules_do_not_leak_activity() -> None:
    repo = FakePublicRiderRepo()

    profile = await get_user_profile(
        identifier="private",
        repo=repo,  # type: ignore[arg-type]
    )
    rides = await get_public_user_recent_rides(
        identifier="private",
        limit=10,
        repo=repo,  # type: ignore[arg-type]
    )
    cards = await get_public_user_beetle_cards(
        identifier="private",
        repo=repo,  # type: ignore[arg-type]
    )

    assert profile.is_public is False
    assert rides["is_public"] is False
    assert rides["rides"] == []
    assert rides["count"] == 0
    assert rides["privacy"]["reason"] == "private_profile"
    assert cards["is_public"] is False
    assert cards["cards"] == []
    assert cards["count"] == 0
    assert cards["privacy"]["reason"] == "private_profile"


@pytest.mark.asyncio
async def test_direct_wallet_leaderboard_positions_respect_private_profile(viewer: AuthenticatedUser) -> None:
    repo = FakePublicRiderRepo()

    with pytest.raises(HTTPException) as excinfo:
        await get_user_leaderboard_positions(
            wallet="private-wallet",
            current_user=viewer,
            repo=repo,  # type: ignore[arg-type]
            vault_repo=FakeVaultRepo(),  # type: ignore[arg-type]
        )

    assert excinfo.value.status_code == 404
