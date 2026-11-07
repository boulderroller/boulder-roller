"""
Notification Repository

Database operations for notifications, specifically leaderboard notifications.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Sequence, TypedDict

from ..notification_contracts import build_notification_insert, notification_is_suppressed
from .base import BaseRepository

logger = logging.getLogger(__name__)
UNREAD_COUNT_CACHE_TTL_SECONDS = 10

_unread_count_cache: Dict[str, tuple[float, int]] = {}


class NotificationDict(TypedDict, total=False):
    """Typed dict for notifications database rows."""
    id: str
    user_id: Optional[str]
    wallet: str
    notification_type: str
    schema_version: str
    event_type: str
    actor_id: Optional[str]
    target_type: Optional[str]
    target_id: Optional[str]
    title: str
    message: str
    data: Dict[str, Any]
    metadata: Dict[str, Any]
    delivery_status: str
    delivery_channels: List[str]
    dedupe_key: Optional[str]
    vault_signature: Optional[str]
    read: bool
    read_at: Optional[str]
    occurred_at: str
    created_at: str


class LeaderboardUpdateResult(TypedDict, total=False):
    """Result from leaderboard update with notification info."""
    new_rank: Optional[int]
    is_kom: bool
    previous_rank: Optional[int]
    bumped_wallet: Optional[str]
    bumped_rank: Optional[int]


class NotificationRepository(BaseRepository):
    """Repository for notification operations."""

    @staticmethod
    def _get_cached_unread_count(wallet: str) -> Optional[int]:
        cached = _unread_count_cache.get(wallet)
        if not cached:
            return None
        cached_at, value = cached
        if time.monotonic() - cached_at >= UNREAD_COUNT_CACHE_TTL_SECONDS:
            _unread_count_cache.pop(wallet, None)
            return None
        return value

    @staticmethod
    def _set_cached_unread_count(wallet: str, value: int) -> None:
        _unread_count_cache[wallet] = (time.monotonic(), value)

    @staticmethod
    def _invalidate_unread_count(wallet: str) -> None:
        _unread_count_cache.pop(wallet, None)

    # =========================================================================
    # NOTIFICATION QUERIES
    # =========================================================================

    async def _wallet_for_user_id(self, user_id: Optional[str]) -> Optional[str]:
        if not user_id:
            return None
        response = await self._run(
            lambda: self.client.from_("users")
            .select("wallet")
            .eq("id", user_id)
            .limit(1)
            .execute(),
            operation="notifications_user_wallet",
        )
        rows = getattr(response, "data", None) or []
        if not rows:
            return None
        wallet = rows[0].get("wallet")
        return str(wallet) if wallet else None

    async def _user_id_for_wallet(self, wallet: Optional[str]) -> Optional[str]:
        if not wallet:
            return None
        response = await self._run(
            lambda: self.client.from_("users")
            .select("id")
            .eq("wallet", wallet)
            .limit(1)
            .execute(),
            operation="notifications_wallet_user",
        )
        rows = getattr(response, "data", None) or []
        if not rows:
            return None
        user_id = rows[0].get("id")
        return str(user_id) if user_id else None

    async def _preferences_for_user_id(self, user_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not user_id:
            return None
        response = await self._run(
            lambda: self.client.from_("notification_preferences")
            .select("*")
            .eq("user_id", user_id)
            .limit(1)
            .execute(),
            operation="notifications_preferences",
        )
        rows = getattr(response, "data", None) or []
        return dict(rows[0]) if rows else None

    async def create_event_notification(
        self,
        *,
        notification_type: str,
        title: str,
        message: Optional[str] = None,
        user_id: Optional[str] = None,
        wallet: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        actor_id: Optional[str] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        occurred_at: Optional[str] = None,
        delivery_channels: Optional[Sequence[str]] = None,
        dedupe_key: Optional[str] = None,
        board_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Create a canonical notification.v1 row from lifecycle producers."""
        wallet = wallet or await self._wallet_for_user_id(user_id)
        if not wallet:
            logger.warning(
                "[NotificationRepo] Skipping %s notification without recipient wallet",
                notification_type,
            )
            return None

        recipient_user_id = user_id or await self._user_id_for_wallet(wallet)
        preferences = await self._preferences_for_user_id(recipient_user_id)
        if notification_is_suppressed(notification_type, preferences):
            return None

        payload = build_notification_insert(
            user_id=recipient_user_id,
            wallet=wallet,
            notification_type=notification_type,
            title=title,
            message=message,
            metadata=metadata,
            actor_id=actor_id,
            target_type=target_type,
            target_id=target_id,
            occurred_at=occurred_at,
            delivery_channels=delivery_channels,
            dedupe_key=dedupe_key,
            board_snapshot=board_snapshot,
        )
        response = await self._run(
            lambda: self.client.from_("notifications").insert(payload).execute(),
            operation="notifications_create_event",
        )
        rows = getattr(response, "data", None) or []
        notification_id = rows[0].get("id") if rows else payload.get("id")
        self._invalidate_unread_count(wallet)
        return str(notification_id) if notification_id else None

    async def get_wallet_notifications(
        self,
        wallet: str,
        limit: int = 50,
        unread_only: bool = False,
        notification_types: Optional[List[str]] = None,
        exclude_stage1: bool = False,
    ) -> List[NotificationDict]:
        """
        Get notifications for a wallet.

        Args:
            wallet: User's wallet address
            limit: Maximum notifications to return
            unread_only: Only return unread notifications
            notification_types: Filter by specific types (e.g., ['leaderboard_entered', 'kom_achieved'])

        Returns:
            List of notifications ordered by created_at DESC
        """
        if exclude_stage1:
            def visible_query():
                query = self.client.from_("notifications").select("*").eq("wallet", wallet) \
                    .is_("dismissed_at", "null") \
                    .or_("metadata->>stage1.is.null,metadata->>stage1.neq.true")
                if unread_only:
                    query = query.eq("read", False)
                if notification_types:
                    query = query.in_("notification_type", notification_types)
                return query.order("created_at", desc=True).limit(limit).execute()
            result = await self._run(visible_query, operation="notifications_visible_wallet")
            return result.data or []
        try:
            result = await self._run(
                lambda: self.client.rpc(
                    "get_wallet_notifications",
                    {
                        "p_wallet": wallet,
                        "p_limit": limit,
                        "p_unread_only": unread_only,
                        "p_notification_types": notification_types,
                    },
                ).execute(),
                operation="notifications_get_wallet",
            )
            return result.data or []
        except Exception as e:
            logger.warning(f"[NotificationRepo] RPC failed, falling back to direct query: {e}")
            # Fallback to direct query
            def _query():
                query = self.client.from_("notifications") \
                    .select("*") \
                    .eq("wallet", wallet) \
                    .is_("dismissed_at", "null") \
                    .order("created_at", desc=True) \
                    .limit(limit)

                if unread_only:
                    query = query.eq("read", False)

                if notification_types:
                    query = query.in_("notification_type", notification_types)

                return query.execute()

            result = await self._run(_query, operation="notifications_get_wallet_fallback")
            return result.data or []

    async def get_unread_count(self, wallet: str, exclude_stage1: bool = False) -> int:
        """Get count of unread notifications for a wallet."""
        if exclude_stage1:
            result = await self._run(
                lambda: self.client.from_("notifications").select("id", count="exact")
                    .eq("wallet", wallet).eq("read", False).is_("dismissed_at", "null")
                    .or_("metadata->>stage1.is.null,metadata->>stage1.neq.true").execute(),
                operation="notifications_visible_unread_count",
            )
            return int(result.count or 0)
        cached_count = self._get_cached_unread_count(wallet)
        if cached_count is not None:
            return cached_count

        try:
            result = await self._run(
                lambda: self.client.rpc(
                    "get_wallet_unread_count",
                    {
                        "p_wallet": wallet,
                    },
                ).execute(),
                operation="notifications_get_unread_count",
            )
            count = result.data if isinstance(result.data, int) else 0
        except Exception as e:
            logger.warning(f"[NotificationRepo] RPC failed, falling back to direct query: {e}")
            result = await self._run(
                lambda: self.client.from_("notifications") \
                    .select("id", count="exact") \
                    .eq("wallet", wallet) \
                    .eq("read", False) \
                    .is_("dismissed_at", "null") \
                    .execute(),
                operation="notifications_get_unread_count_fallback",
            )
            count = result.count or 0

        self._set_cached_unread_count(wallet, int(count))
        return int(count)

    async def mark_read(
        self,
        notification_id: str,
        wallet: str,
    ) -> bool:
        """
        Mark a specific notification as read.

        Args:
            notification_id: UUID of the notification
            wallet: User's wallet (for ownership verification)

        Returns:
            True if notification was marked read, False if not found
        """
        result = await self._run(
            lambda: self.client.from_("notifications") \
                .update({
                    "read": True,
                    "read_at": datetime.now(timezone.utc).isoformat(),
                }) \
                .eq("id", notification_id) \
                .eq("wallet", wallet) \
                .execute(),
            operation="notifications_mark_read",
        )

        success = len(result.data or []) > 0
        if success:
            self._invalidate_unread_count(wallet)
        return success

    async def mark_all_read(self, wallet: str) -> int:
        """
        Mark all notifications as read for a wallet.

        Returns:
            Number of notifications marked as read
        """
        try:
            result = await self._run(
                lambda: self.client.rpc(
                    "mark_wallet_notifications_read",
                    {
                        "p_wallet": wallet,
                        "p_notification_ids": None,
                    },
                ).execute(),
                operation="notifications_mark_all_read",
            )
            count = result.data if isinstance(result.data, int) else 0
        except Exception as e:
            logger.warning(f"[NotificationRepo] RPC failed, falling back to direct update: {e}")
            result = await self._run(
                lambda: self.client.from_("notifications") \
                    .update({
                        "read": True,
                        "read_at": datetime.now(timezone.utc).isoformat(),
                    }) \
                    .eq("wallet", wallet) \
                    .eq("read", False) \
                    .execute(),
                operation="notifications_mark_all_read_fallback",
            )
            count = len(result.data or [])

        self._invalidate_unread_count(wallet)
        return int(count)

    # =========================================================================
    # LEADERBOARD NOTIFICATIONS
    # =========================================================================

    async def create_leaderboard_notification(
        self,
        wallet: str,
        notification_type: str,
        vault_name: str,
        vault_signature: Optional[str] = None,
        rank: Optional[int] = None,
        old_rank: Optional[int] = None,
        bumped_by: Optional[str] = None,
        payout_amount: Optional[float] = None,
        time_seconds: Optional[int] = None,
    ) -> Optional[str]:
        """
        Create a leaderboard notification using the database function.

        Args:
            wallet: User's wallet to notify
            notification_type: One of: leaderboard_entered, leaderboard_bumped,
                             rank_changed, payout_received, kom_achieved, stake_payout, legend_payout
            vault_name: Display name of the vault
            vault_signature: 64-byte signature hex
            rank: Current rank (for leaderboard_entered, rank_changed, kom_achieved)
            old_rank: Previous rank (for rank_changed)
            bumped_by: Wallet that bumped this user (for leaderboard_bumped)
            payout_amount: Points/DUNG received (for payout notifications)
            time_seconds: Time achieved (for kom_achieved)

        Returns:
            Notification UUID or None if creation failed
        """
        try:
            result = await self._run(
                lambda: self.client.rpc(
                    "create_leaderboard_notification",
                    {
                        "p_wallet": wallet,
                        "p_type": notification_type,
                        "p_vault_name": vault_name,
                        "p_vault_signature": vault_signature,
                        "p_rank": rank,
                        "p_old_rank": old_rank,
                        "p_bumped_by": bumped_by,
                        "p_payout_amount": payout_amount,
                        "p_time_seconds": time_seconds,
                    },
                ).execute(),
                operation="notifications_create_leaderboard",
            )

            notification_id = result.data
            if notification_id:
                self._invalidate_unread_count(wallet)
                logger.info(
                    f"[NotificationRepo] Created {notification_type} notification for [redacted]... "
                    f"on {vault_name}"
                )
            return notification_id
        except Exception as e:
            logger.error(f"[NotificationRepo] Failed to create notification: {e}")
            return None

    # =========================================================================
    # LEADERBOARD UPDATE WITH NOTIFICATIONS
    # =========================================================================

    async def update_leaderboard_with_notifications(
        self,
        vault_signature: str,
        wallet: str,
        time_seconds: int,
        vault_name: str,
        avg_power_w: Optional[int] = None,
        completion_id: Optional[str] = None,
        achieved_at: Optional[str] = None,
    ) -> LeaderboardUpdateResult:
        """
        Disabled legacy path.

        Record Board updates now happen on-chain through climb-completion
        instructions and are projected back through the indexer. This method is
        kept only to make any stale caller fail closed instead of silently
        mutating the legacy DB cache.

        Args:
            vault_signature: 64-byte signature hex
            wallet: User's wallet
            time_seconds: Completion time in seconds
            vault_name: Display name (for notification messages)
            avg_power_w: Average power (optional)
            completion_id: UUID of the completion record
            achieved_at: ISO timestamp (for backfills)

        Returns:
            Never returns successfully. Legacy DB-native Record Board mutation
            is no longer a supported runtime operation.
        """
        raise RuntimeError(
            "Legacy DB-native Record Board writes are disabled. Record Board "
            "truth is on-chain; repair projections by reindexing from chain."
        )
