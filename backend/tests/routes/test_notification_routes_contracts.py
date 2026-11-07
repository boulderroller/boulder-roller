from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

import pytest

from app.dependencies import AuthenticatedUser
from app.routes.notifications import (
    create_notification,
    get_notifications,
    mark_all_notifications_read,
    mark_notification_read,
)


class FakeWalletNotificationRepo:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = [
            {
                "id": str(uuid4()),
                "wallet": "wallet-1",
                "notification_type": "comment",
                "title": "New comment",
                "message": "Nice ride",
                "data": {"ride_id": "ride-1", "comment_id": "comment-1"},
                "actor_id": "user-2",
                "read": False,
                "created_at": "2026-04-30T12:00:00+00:00",
            },
            {
                "id": str(uuid4()),
                "wallet": "wallet-1",
                "notification_type": "follow_created",
                "title": "New follower",
                "message": "alice followed you",
                "metadata": {"follower_id": "user-3"},
                "read": True,
                "read_at": "2026-04-30T12:05:00+00:00",
                "created_at": "2026-04-30T12:01:00+00:00",
            },
        ]

    async def get_wallet_notifications(
        self,
        wallet: str,
        limit: int = 50,
        unread_only: bool = False,
        notification_types: Optional[list[str]] = None,
        exclude_stage1: bool = False,
    ) -> list[dict[str, Any]]:
        rows = [row for row in self.rows if row["wallet"] == wallet]
        if exclude_stage1:
            rows = [row for row in rows if row.get('metadata', {}).get('stage1') is not True]
        if unread_only:
            rows = [row for row in rows if not row.get("read")]
        if notification_types:
            rows = [
                row
                for row in rows
                if row.get("notification_type") in notification_types
                or row.get("event_type") in notification_types
            ]
        return rows[:limit]

    async def get_unread_count(self, wallet: str, exclude_stage1: bool = False) -> int:
        return len([row for row in self.rows if row["wallet"] == wallet and not row.get("read")
                    and not (exclude_stage1 and row.get('metadata', {}).get('stage1') is True)])


    async def mark_read(self, notification_id: str, wallet: str) -> bool:
        for row in self.rows:
            if row["id"] == notification_id and row["wallet"] == wallet:
                row["read"] = True
                row["read_at"] = row.get("read_at") or datetime.now(timezone.utc).isoformat()
                return True
        return False

    async def mark_all_read(self, wallet: str) -> int:
        count = 0
        for row in self.rows:
            if row["wallet"] == wallet and not row.get("read"):
                row["read"] = True
                row["read_at"] = datetime.now(timezone.utc).isoformat()
                count += 1
        return count


class FakeNotificationCreateRepo:
    def __init__(self, preferences: Optional[dict[str, Any]] = None) -> None:
        self.preferences = preferences
        self.created: list[dict[str, Any]] = []

    async def get_notification_preferences(self, user_id: str) -> Optional[dict[str, Any]]:
        return self.preferences

    async def create_notification(
        self,
        user_id: str,
        notification_type: str,
        title: str,
        message: Optional[str],
        data: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        notification = {
            "user_id": user_id,
            "notification_type": notification_type,
            "title": title,
            "message": message,
            "data": data or {},
            **kwargs,
        }
        self.created.append(notification)
        return notification


@pytest.fixture
def current_user() -> AuthenticatedUser:
    return AuthenticatedUser(wallet="wallet-1", user_id="user-1", device_id="device-1")


@pytest.mark.asyncio
async def test_inbox_route_serializes_notification_contract(current_user: AuthenticatedUser) -> None:
    repo = FakeWalletNotificationRepo()

    response = await get_notifications(
        limit=20,
        unread_only=False,
        current_user=current_user,
        repo=repo,  # type: ignore[arg-type]
    )

    assert response["contractVersion"] == "notification.v1"
    assert response["unread_count"] == 1
    assert response["notifications"][0]["notificationType"] == "comment_created"
    assert response["notifications"][0]["legacyType"] == "comment"
    target = response["notifications"][0]["target"]
    assert target["contractVersion"] == "target_action.v1"
    assert target["type"] == "ride"
    assert target["id"] == "ride-1"
    assert response["notifications"][0]["actor"]["id"] == "user-2"


@pytest.mark.asyncio
async def test_mark_read_is_idempotent_for_owned_notifications(current_user: AuthenticatedUser) -> None:
    repo = FakeWalletNotificationRepo()
    notification_id = repo.rows[0]["id"]

    first = await mark_notification_read(
        notification_id=UUID(notification_id),
        current_user=current_user,
        repo=repo,  # type: ignore[arg-type]
    )
    second = await mark_notification_read(
        notification_id=UUID(notification_id),
        current_user=current_user,
        repo=repo,  # type: ignore[arg-type]
    )

    assert first == {"status": "read"}
    assert second == {"status": "read"}
    assert await repo.get_unread_count(current_user.wallet) == 0


@pytest.mark.asyncio
async def test_mark_all_read_returns_changed_unread_count(current_user: AuthenticatedUser) -> None:
    repo = FakeWalletNotificationRepo()

    response = await mark_all_notifications_read(
        current_user=current_user,
        repo=repo,  # type: ignore[arg-type]
    )

    assert response == {"status": "read", "count": 1}
    assert await repo.get_unread_count(current_user.wallet) == 0


@pytest.mark.asyncio
async def test_create_notification_respects_preference_suppression_hook() -> None:
    repo = FakeNotificationCreateRepo({"social_activity": False})

    created = await create_notification(
        repo=repo,  # type: ignore[arg-type]
        user_id="user-1",
        notification_type="comment_created",
        title="New comment",
        message="Nice ride",
        data={"ride_id": "ride-1"},
        actor_id="user-2",
        target_type="ride",
        target_id="ride-1",
    )

    assert created is None
    assert repo.created == []


@pytest.mark.asyncio
async def test_dark_stage1_notifications_do_not_consume_pages_or_unread_count():
    repo = FakeWalletNotificationRepo()
    legacy = list(repo.rows)
    repo.rows = [{**legacy[0], 'id': str(uuid4()), 'metadata': {'stage1': True}} for _ in range(51)] + legacy
    result = await get_notifications(limit=20, unread_only=False,
        current_user=AuthenticatedUser(wallet='wallet-1', user_id='user-1', device_id='device'), repo=repo)
    assert len(result['notifications']) == 2
    assert result['unread_count'] == 1
