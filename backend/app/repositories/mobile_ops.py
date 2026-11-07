"""Mobile operability storage: crash diagnostics + push machinery.

Bead boulderroller-v2-k7387 (iOS halves: odmi6.8 / odmi6.14).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from .base import BaseRepository

logger = logging.getLogger(__name__)

# The only notification types the push worker may ever touch — the product
# law is two push categories, settlement and displacement (Law 7: pushes,
# not rooms). Everything else fails closed at the payload builder too.
PUSH_NOTIFICATION_TYPES: dict[str, str] = {
    "settlement_finalized": "settlement",
    "leaderboard_bumped": "displacement",
}


class MobileOpsRepository(BaseRepository):
    # ------------------------------------------------------------------
    # Crash diagnostics ingest
    # ------------------------------------------------------------------

    async def insert_diagnostics(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        result = await self._run(
            lambda: self.client.table("ios_diagnostics").insert(rows).execute(),
            operation="ios_diagnostics_insert",
        )
        return len(result.data or [])

    # ------------------------------------------------------------------
    # Push device registration
    # ------------------------------------------------------------------

    async def upsert_push_device(
        self,
        *,
        device_id: str,
        wallet: str,
        apns_token: str,
        environment: str,
        app_version: Optional[str],
    ) -> None:
        await self._run(
            lambda: self.client.table("mobile_push_devices")
            .upsert(
                {
                    "device_id": device_id,
                    "wallet": wallet,
                    "apns_token": apns_token,
                    "environment": environment,
                    "app_version": app_version,
                    "updated_at": "now()",
                },
                on_conflict="device_id",
            )
            .execute(),
            operation="mobile_push_devices_upsert",
        )

    async def delete_push_device(self, *, device_id: str, wallet: str) -> bool:
        """Delete one registration; the wallet guard keeps a signed-in rider
        from removing someone else's device row."""
        result = await self._run(
            lambda: self.client.table("mobile_push_devices")
            .delete()
            .eq("device_id", device_id)
            .eq("wallet", wallet)
            .execute(),
            operation="mobile_push_devices_delete",
        )
        return bool(result.data)

    async def devices_for_wallet(self, wallet: str) -> list[dict[str, Any]]:
        result = await self._run(
            lambda: self.client.table("mobile_push_devices")
            .select("device_id, apns_token, environment")
            .eq("wallet", wallet)
            .execute(),
            operation="mobile_push_devices_for_wallet",
        )
        return result.data or []

    async def delete_push_token(self, apns_token: str) -> None:
        """Drop a token APNs reported as gone (410 Unregistered)."""
        await self._run(
            lambda: self.client.table("mobile_push_devices")
            .delete()
            .eq("apns_token", apns_token)
            .execute(),
            operation="mobile_push_devices_delete_token",
        )

    # ------------------------------------------------------------------
    # Send worker scan + exactly-once ledger
    # ------------------------------------------------------------------

    async def pending_push_notifications(
        self, *, since_iso: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Recent notifications of the two push types that have no delivery
        row yet. Two bounded reads (notifications window, then existing
        ledger ids) — fine at cohort scale and index-friendly."""
        notif_result = await self._run(
            lambda: self.client.table("notifications")
            .select("id, wallet, notification_type, title, message, data, created_at")
            .in_("notification_type", list(PUSH_NOTIFICATION_TYPES.keys()))
            .gte("created_at", since_iso)
            .order("created_at", desc=False)
            .limit(limit)
            .execute(),
            operation="push_worker_scan_notifications",
        )
        candidates = [row for row in (notif_result.data or []) if row.get("wallet")]
        if not candidates:
            return []
        ids = [row["id"] for row in candidates]
        delivered_result = await self._run(
            lambda: self.client.table("mobile_push_deliveries")
            .select("notification_id")
            .in_("notification_id", ids)
            .execute(),
            operation="push_worker_scan_deliveries",
        )
        delivered = {row["notification_id"] for row in (delivered_result.data or [])}
        return [row for row in candidates if row["id"] not in delivered]

    async def record_push_delivery(
        self,
        *,
        notification_id: str,
        wallet: str,
        category: str,
        mode: str,
        device_count: int,
        detail: Optional[dict[str, Any]] = None,
    ) -> bool:
        """Insert the exactly-once ledger row. Returns False when another
        worker already claimed this notification (unique violation)."""
        try:
            await self._run(
                lambda: self.client.table("mobile_push_deliveries")
                .insert(
                    {
                        "notification_id": notification_id,
                        "wallet": wallet,
                        "category": category,
                        "mode": mode,
                        "device_count": device_count,
                        "detail": detail,
                    }
                )
                .execute(),
                operation="mobile_push_deliveries_insert",
            )
            return True
        except Exception as exc:  # unique violation = already handled
            message = str(exc).lower()
            if "duplicate key" in message or "23505" in message or "conflict" in message:
                return False
            raise


def create_mobile_ops_repository() -> MobileOpsRepository:
    from .base import get_supabase_client

    return MobileOpsRepository(get_supabase_client())
