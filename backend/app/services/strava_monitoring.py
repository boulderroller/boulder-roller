"""Strava monitoring snapshot helpers for admin UI and Prometheus scrapes."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from ..config import load_strava_settings
from ..metrics import (
    set_strava_connection_state,
    set_strava_last_webhook_event,
    set_strava_subscription_active,
)
from ..repositories import get_supabase_client
from .strava_rate_limiter import get_strava_rate_limiter

logger = logging.getLogger(__name__)


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _health_status(
    *,
    provider_configured: bool,
    sync_enabled: bool,
    subscription_active: bool,
    active_connections: int,
    alerts: list[str],
) -> str:
    if not sync_enabled:
        if subscription_active or active_connections or alerts:
            return "WARNING"
        return "HEALTHY"
    if not provider_configured:
        return "CRITICAL"
    if not subscription_active or alerts:
        return "WARNING"
    return "HEALTHY"


async def get_strava_health_snapshot() -> Dict[str, Any]:
    """Collect current Strava integration health for admin monitoring."""
    settings = load_strava_settings()
    db = get_supabase_client()
    rate_limiter = get_strava_rate_limiter()
    rate_snapshot = rate_limiter.snapshot()

    async def fetch_subscription():
        return await asyncio.to_thread(
            lambda: db.table("strava_webhook_subscriptions")
            .select("*")
            .eq("is_active", True)
            .limit(1)
            .execute()
        )

    async def fetch_connections():
        return await asyncio.to_thread(
            lambda: db.table("strava_connections")
            .select("id,last_sync_at,last_webhook_at,backfill_status", count="exact")
            .eq("is_active", True)
            .execute()
        )

    state_verified = True
    try:
        subscription_result, connections_result = await asyncio.gather(
            fetch_subscription(),
            fetch_connections(),
        )
    except Exception as exc:
        logger.warning("Failed to build Strava monitoring snapshot: %s", exc)
        state_verified = False
        subscription_result = None
        connections_result = None

    subscription_row = None
    if subscription_result is not None:
        data = getattr(subscription_result, "data", None) or []
        subscription_row = data[0] if data else None

    rows = []
    active_connections = 0
    if connections_result is not None:
        rows = getattr(connections_result, "data", None) or []
        active_connections = getattr(connections_result, "count", None) or len(rows)

    now = datetime.now(timezone.utc)
    synced_cutoff = now - timedelta(hours=24)
    stale_cutoff = now - timedelta(days=7)
    recent_sync_24h = 0
    stale_sync_7d = 0
    latest_webhook_at: Optional[datetime] = None
    backfill_counts: Dict[str, int] = {"none": 0, "in_progress": 0, "complete": 0}

    for row in rows:
        last_sync_at = _parse_datetime(row.get("last_sync_at"))
        last_webhook_at = _parse_datetime(row.get("last_webhook_at"))
        backfill_status = row.get("backfill_status") or "none"

        backfill_counts[backfill_status] = backfill_counts.get(backfill_status, 0) + 1

        if last_sync_at and last_sync_at >= synced_cutoff:
            recent_sync_24h += 1
        if not last_sync_at or last_sync_at < stale_cutoff:
            stale_sync_7d += 1
        if last_webhook_at and (latest_webhook_at is None or last_webhook_at > latest_webhook_at):
            latest_webhook_at = last_webhook_at

    subscription_active = bool(subscription_row)
    if state_verified:
        set_strava_subscription_active(subscription_active)
        set_strava_connection_state(
            active_connections=active_connections,
            backfill_counts=backfill_counts,
        )
        if latest_webhook_at is not None:
            set_strava_last_webhook_event(latest_webhook_at.timestamp())

    alerts: list[str] = []
    if not state_verified:
        alerts.append("Unable to verify Strava cutover state.")
    if settings.sync_enabled and not settings.enabled:
        alerts.append("Strava OAuth credentials are not configured.")
    if settings.sync_enabled and settings.enabled and not subscription_active:
        alerts.append("Webhook subscription is inactive.")
    if not settings.sync_enabled and subscription_active:
        alerts.append("Webhook subscription remains active in file-import-only mode.")
    if not settings.sync_enabled and active_connections > 0:
        alerts.append("Active Strava connections remain in file-import-only mode.")
    if settings.sync_enabled and rate_snapshot["storage"] != "redis":
        alerts.append("Rate limiter is running without Redis-backed shared state.")
    if (
        settings.sync_enabled
        and rate_snapshot["limit_15min"]
        and rate_snapshot["usage_15min"] / rate_snapshot["limit_15min"] >= 0.8
    ):
        alerts.append("15-minute Strava quota is above 80%.")
    if (
        settings.sync_enabled
        and rate_snapshot["limit_daily"]
        and rate_snapshot["usage_daily"] / rate_snapshot["limit_daily"] >= 0.8
    ):
        alerts.append("Daily Strava quota is above 80%.")
    if (
        settings.sync_enabled
        and active_connections > 0
        and latest_webhook_at is None
    ):
        alerts.append("No webhook events have been recorded for active Strava connections yet.")
    elif (
        settings.sync_enabled
        and active_connections > 0
        and latest_webhook_at
        and latest_webhook_at < synced_cutoff
    ):
        alerts.append("No Strava webhook has been seen in the last 24 hours.")

    return {
        "health_status": _health_status(
            provider_configured=settings.enabled,
            sync_enabled=settings.sync_enabled,
            subscription_active=subscription_active,
            active_connections=active_connections,
            alerts=alerts,
        ),
        "enabled": settings.enabled,
        "sync_enabled": settings.sync_enabled,
        "integration_mode": (
            "strava_sync" if settings.sync_enabled else "file_import_only"
        ),
        "state_verified": state_verified,
        "redirect_uri": settings.redirect_uri,
        "webhook_callback_url": settings.webhook_callback_url,
        "subscription": {
            "active": subscription_active,
            "subscription_id": (
                subscription_row.get("subscription_id") if subscription_row else None
            ),
            "callback_url": (
                subscription_row.get("callback_url")
                if subscription_row
                else settings.webhook_callback_url
            ),
            "created_at": subscription_row.get("created_at") if subscription_row else None,
        },
        "connections": {
            "active_count": active_connections,
            "recent_sync_24h": recent_sync_24h,
            "stale_sync_7d": stale_sync_7d,
            "last_webhook_at": latest_webhook_at.isoformat() if latest_webhook_at else None,
        },
        "backfill": backfill_counts,
        "rate_limits": rate_snapshot,
        "alerts": alerts,
        "generated_at": now.isoformat(),
    }


async def refresh_strava_monitoring_gauges() -> None:
    """Best-effort refresh used before Prometheus scrapes."""
    try:
        await get_strava_health_snapshot()
    except Exception as exc:  # pragma: no cover - defensive path
        logger.debug("Skipping Strava monitoring refresh during metrics scrape: %s", exc)
