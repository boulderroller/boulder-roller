from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.repositories.notification import NotificationRepository


class FakeNotificationClient:
    def __init__(self) -> None:
        self.current_table = ""
        self.operation = ""
        self.filters: dict[str, Any] = {}
        self.inserted: list[dict[str, Any]] = []

    def from_(self, table: str) -> "FakeNotificationClient":
        self.current_table = table
        self.operation = ""
        self.filters = {}
        return self

    def select(self, *_args: Any, **_kwargs: Any) -> "FakeNotificationClient":
        self.operation = "select"
        return self

    def eq(self, key: str, value: Any) -> "FakeNotificationClient":
        self.filters[key] = value
        return self

    def limit(self, *_args: Any, **_kwargs: Any) -> "FakeNotificationClient":
        return self

    def insert(self, payload: dict[str, Any]) -> "FakeNotificationClient":
        self.operation = "insert"
        self.inserted.append(payload)
        return self

    def execute(self) -> SimpleNamespace:
        if self.current_table == "users":
            if self.filters.get("wallet") == "wallet-1":
                return SimpleNamespace(data=[{"id": "user-1"}])
            return SimpleNamespace(data=[])
        if self.current_table == "notification_preferences":
            if self.filters.get("user_id") == "user-1":
                return SimpleNamespace(data=[{"user_id": "user-1", "leaderboard_updates": False}])
            return SimpleNamespace(data=[])
        if self.current_table == "notifications":
            return SimpleNamespace(data=[{"id": "notification-1"}])
        return SimpleNamespace(data=[])


@pytest.mark.asyncio
async def test_wallet_only_notifications_respect_resolved_user_preferences() -> None:
    client = FakeNotificationClient()
    repo = NotificationRepository(client)  # type: ignore[arg-type]

    async def run_sync(func: Any, operation: str = "supabase") -> Any:
        return func()

    repo._run = run_sync  # type: ignore[method-assign]

    notification_id = await repo.create_event_notification(
        wallet="wallet-1",
        notification_type="local_legend_moved",
        title="Local Legend updated",
        target_type="local_legend",
        target_id="7",
    )

    assert notification_id is None
    assert client.inserted == []


@pytest.mark.asyncio
async def test_event_board_snapshot_is_persisted_without_later_board_read() -> None:
    client = FakeNotificationClient()
    repo = NotificationRepository(client)
    async def run_sync(func, operation='fixture'):
        return func()
    repo._run = run_sync
    snapshot = dict(revision='event:7', occurredAt='2026-09-08T20:00:00Z', climbId='climb-7', before=[dict(wallet='wallet-2', place=4)], after=[])
    result = await repo.create_event_notification(wallet='wallet-2', notification_type='leaderboard_bumped', title='', board_snapshot=snapshot)
    assert result == 'notification-1'
    snapshot['before'][0]['place'] = 1
    assert client.inserted[0]['metadata']['transition'] == dict(revision='event:7', occurredAt='2026-09-08T20:00:00Z', climbId='climb-7', beforePlace=4, afterPlace=None)


@pytest.mark.asyncio
async def test_dark_stage1_notifications_are_left_out_through_the_pinned_client() -> None:
    # The real pinned client has no or_(); the route asks for this filter
    # whenever Stage 1 is not live.
    from tests.pinned_postgrest import PinnedPostgrest

    def notification(day: int, *, stage1: Any = None, read: bool = False, dismissed: bool = False) -> dict:
        return {"id": f"notification-{day}", "wallet": "wallet-1", "read": read,
                "metadata": {} if stage1 is None else {"stage1": stage1},
                "dismissed_at": "2026-10-25T00:00:00+00:00" if dismissed else None,
                "created_at": f"2026-10-{day:02d}T00:00:00+00:00"}

    rows = [notification(21), notification(22, stage1=True), notification(23, stage1=False, read=True),
            notification(24, dismissed=True)]
    repo = NotificationRepository(PinnedPostgrest({"notifications": rows}).client)

    visible = await repo.get_wallet_notifications("wallet-1", exclude_stage1=True)
    unread = await repo.get_unread_count("wallet-1", exclude_stage1=True)

    assert [row["id"] for row in visible] == ["notification-23", "notification-21"]
    assert unread == 1
