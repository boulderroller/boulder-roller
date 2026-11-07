"""Mobile push send worker — to the APNs key boundary.

Bead boulderroller-v2-k7387 (L1.08 / LIST THREE item 6; iOS half odmi6.8).

Exactly two notification categories exist (Law 7: pushes, not rooms):

    settlement_finalized  -> category "settlement"    -> Settlements room
    leaderboard_bumped    -> category "displacement"  -> climb sheet

The worker scans the canonical ``notifications`` table for fresh rows of
those two types, builds APNs payloads through a fail-closed allowlist, and
records an exactly-once ledger row per notification.

Key boundary / flags:
  * ``MOBILE_PUSH_WORKER_ENABLED`` (default **false**) — the loop does not
    run at all until explicitly enabled.
  * ``MOBILE_PUSH_DRY_RUN`` (default **true**) — logs the exact payload it
    would send instead of sending.
  * Real sends additionally require the APNs ``.p8`` at ``APNS_KEY_PATH``
    (founder's Apple Developer account; never in git) **and** ratified
    copy — ``COPY_RATIFIED`` below stays False until Tim replaces the
    placeholder strings, so flipping env flags alone can never ship
    placeholder copy.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from ..repositories.mobile_ops import (
    PUSH_NOTIFICATION_TYPES,
    MobileOpsRepository,
    create_mobile_ops_repository,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rider-facing copy slots — [COPY: Tim]
# ---------------------------------------------------------------------------
# PLACEHOLDERS, not shipped copy. Strava-shaped so the payload structure is
# real, clearly marked so nobody mistakes them for ratified strings. The
# worker refuses real (non-dry-run) sends while COPY_RATIFIED is False; Tim
# ratifies the strings and flips it in the same change.
COPY_RATIFIED = False

SETTLEMENT_PUSH_TITLE = "[COPY: Tim] Weekly settlement posted"
SETTLEMENT_PUSH_BODY = "[COPY: Tim] Your DUNG receipt is ready."
DISPLACEMENT_PUSH_TITLE = "[COPY: Tim] You lost a Leaderboard seat"
DISPLACEMENT_PUSH_BODY = "[COPY: Tim] {climb_name} — your time was beaten."


class PushPayloadError(ValueError):
    """A notification row the allowlist refuses to turn into a push."""


def _routable_climb_id(data: dict[str, Any]) -> Optional[str]:
    """Deep-link target for displacement: the climb (vault) the seat was
    lost on. Mirrors notification_contracts target routing keys."""
    for key in ("climb_id", "climbId", "vault_id", "vaultId"):
        value = data.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return None


def build_push_payload(notification: dict[str, Any]) -> dict[str, Any]:
    """Build the APNs JSON body for one canonical notification row.

    Fail-closed: any type outside the two-category allowlist, and any
    displacement without a routable climb id, raises PushPayloadError.
    The ``br`` envelope mirrors the iOS parser exactly
    (ios/BoulderRoller/Push/PushMachinery.swift, PushDeepLink.parse).
    """
    notification_type = str(notification.get("notification_type") or "")
    category = PUSH_NOTIFICATION_TYPES.get(notification_type)
    if category is None:
        raise PushPayloadError(
            f"notification type {notification_type!r} is not a push category"
        )

    data = notification.get("data") or {}
    if not isinstance(data, dict):
        data = {}

    if category == "settlement":
        return {
            "aps": {
                "alert": {
                    "title": SETTLEMENT_PUSH_TITLE,
                    "body": SETTLEMENT_PUSH_BODY,
                },
                "sound": "default",
            },
            "br": {"category": "settlement"},
        }

    # displacement
    climb_id = _routable_climb_id(data)
    if not climb_id:
        raise PushPayloadError("displacement notification has no routable climb id")
    climb_name = str(data.get("vault_name") or data.get("climb_name") or "").strip()
    return {
        "aps": {
            "alert": {
                "title": DISPLACEMENT_PUSH_TITLE,
                "body": DISPLACEMENT_PUSH_BODY.format(
                    climb_name=climb_name or "A climb"
                ),
            },
            "sound": "default",
        },
        "br": {
            "category": "displacement",
            "climb_id": climb_id,
            **({"transition": deepcopy(data["transition"])}
               if isinstance(data.get("transition"), dict) else {}),
        },
    }


class ApnsConfigError(RuntimeError):
    """Real sending was requested but the key boundary is not crossed."""


class ApnsClient:
    """Minimal token-based APNs HTTP/2 client (PyJWT ES256 + httpx).

    Constructed only for real sends. Refuses to exist without the .p8 —
    the truthful failure names exactly what is missing.
    """

    SANDBOX_HOST = "https://api.sandbox.push.apple.com"
    PRODUCTION_HOST = "https://api.push.apple.com"

    def __init__(
        self,
        *,
        key_path: str,
        key_id: str,
        team_id: str,
        topic: str,
    ) -> None:
        missing = [
            name
            for name, value in (
                ("APNS_KEY_PATH", key_path),
                ("APNS_KEY_ID", key_id),
                ("APNS_TEAM_ID", team_id),
                ("APNS_TOPIC", topic),
            )
            if not value
        ]
        if missing:
            raise ApnsConfigError(
                "APNs sending requires " + ", ".join(missing) + " — these come "
                "from the founder's Apple Developer account (ios/RELEASE.md)."
            )
        if not os.path.isfile(key_path):
            raise ApnsConfigError(
                f"APNs .p8 not found at {key_path} — the key stays out of git; "
                "place it on the droplet and point APNS_KEY_PATH at it."
            )
        with open(key_path, "r", encoding="utf-8") as handle:
            self._private_key = handle.read()
        self._key_id = key_id
        self._team_id = team_id
        self._topic = topic
        self._jwt: Optional[str] = None
        self._jwt_issued_at = 0.0

    def _auth_token(self) -> str:
        import jwt as pyjwt

        # APNs accepts provider tokens for up to an hour; refresh at 45 min.
        if self._jwt is None or (time.time() - self._jwt_issued_at) > 45 * 60:
            issued_at = int(time.time())
            self._jwt = pyjwt.encode(
                {"iss": self._team_id, "iat": issued_at},
                self._private_key,
                algorithm="ES256",
                headers={"kid": self._key_id},
            )
            self._jwt_issued_at = float(issued_at)
        return self._jwt

    async def send(
        self, *, token: str, environment: str, payload: dict[str, Any]
    ) -> tuple[int, str]:
        import httpx

        host = self.SANDBOX_HOST if environment == "sandbox" else self.PRODUCTION_HOST
        headers = {
            "authorization": f"bearer {self._auth_token()}",
            "apns-topic": self._topic,
            "apns-push-type": "alert",
            "apns-priority": "10",
        }
        async with httpx.AsyncClient(http2=True, timeout=10) as client:
            response = await client.post(
                f"{host}/3/device/{token}", headers=headers, json=payload
            )
            return response.status_code, response.text


class MobilePushWorker:
    """Scan → build → (dry-run log | send) → exactly-once ledger row."""

    def __init__(
        self,
        repository: Optional[MobileOpsRepository] = None,
        *,
        dry_run: Optional[bool] = None,
        interval_seconds: Optional[float] = None,
        scan_window_hours: Optional[float] = None,
    ) -> None:
        self.repository = repository or create_mobile_ops_repository()
        self.dry_run = (
            dry_run
            if dry_run is not None
            else os.getenv("MOBILE_PUSH_DRY_RUN", "true").lower()
            in ("1", "true", "yes")
        )
        self.interval_seconds = interval_seconds or float(
            os.getenv("MOBILE_PUSH_INTERVAL_SECONDS", "30")
        )
        self.scan_window_hours = scan_window_hours or float(
            os.getenv("MOBILE_PUSH_SCAN_WINDOW_HOURS", "48")
        )
        self._apns: Optional[ApnsClient] = None

    def _apns_client(self) -> ApnsClient:
        if self._apns is None:
            self._apns = ApnsClient(
                key_path=os.getenv("APNS_KEY_PATH", ""),
                key_id=os.getenv("APNS_KEY_ID", ""),
                team_id=os.getenv("APNS_TEAM_ID", ""),
                topic=os.getenv("APNS_TOPIC", "com.boulderroller.app"),
            )
        return self._apns

    async def run_cycle(self) -> dict[str, int]:
        """One scan pass. Returns counters for logs/tests."""
        since = datetime.now(timezone.utc) - timedelta(hours=self.scan_window_hours)
        pending = await self.repository.pending_push_notifications(
            since_iso=since.isoformat()
        )
        counters = {"scanned": len(pending), "dry_run": 0, "sent": 0,
                    "no_devices": 0, "failed": 0}
        for notification in pending:
            outcome = await self._handle(notification)
            counters[outcome] = counters.get(outcome, 0) + 1
        if pending:
            logger.info("[MobilePush] cycle handled %s", counters)
        return counters

    async def _handle(self, notification: dict[str, Any]) -> str:
        notification_id = str(notification.get("id"))
        wallet = str(notification.get("wallet"))
        notification_type = str(notification.get("notification_type") or "")
        category = PUSH_NOTIFICATION_TYPES.get(notification_type, "settlement")

        try:
            payload = build_push_payload(notification)
        except PushPayloadError as exc:
            await self.repository.record_push_delivery(
                notification_id=notification_id,
                wallet=wallet,
                category=category,
                mode="failed",
                device_count=0,
                detail={"error": str(exc)},
            )
            return "failed"

        devices = await self.repository.devices_for_wallet(wallet)
        if not devices:
            await self.repository.record_push_delivery(
                notification_id=notification_id,
                wallet=wallet,
                category=payload["br"]["category"],
                mode="no_devices",
                device_count=0,
            )
            return "no_devices"

        if self.dry_run:
            # The documented pre-key operating mode: log exactly what would
            # be sent, to how many devices, and stop.
            logger.info(
                "[MobilePush] DRY RUN %s -> %d device(s) for %s...: %s",
                payload["br"]["category"],
                len(devices),
                "[redacted]",
                json.dumps(payload),
            )
            await self.repository.record_push_delivery(
                notification_id=notification_id,
                wallet=wallet,
                category=payload["br"]["category"],
                mode="dry_run",
                device_count=len(devices),
                detail={"payload": payload},
            )
            return "dry_run"

        if not COPY_RATIFIED:
            # Flags alone can never ship placeholder copy.
            await self.repository.record_push_delivery(
                notification_id=notification_id,
                wallet=wallet,
                category=payload["br"]["category"],
                mode="failed",
                device_count=0,
                detail={"error": "notification copy is not ratified ([COPY: Tim])"},
            )
            logger.error(
                "[MobilePush] refusing real send: copy slots are still "
                "[COPY: Tim] placeholders"
            )
            return "failed"

        client = self._apns_client()  # raises ApnsConfigError without the p8
        statuses: list[dict[str, Any]] = []
        delivered = 0
        for device in devices:
            status, body = await client.send(
                token=device["apns_token"],
                environment=device["environment"],
                payload=payload,
            )
            statuses.append({"device_id": device["device_id"], "status": status})
            if status == 200:
                delivered += 1
            elif status == 410:
                await self.repository.delete_push_token(device["apns_token"])
            else:
                logger.warning(
                    "[MobilePush] APNs %s for device %s: %s",
                    status, device["device_id"], body[:200],
                )
        await self.repository.record_push_delivery(
            notification_id=notification_id,
            wallet=wallet,
            category=payload["br"]["category"],
            mode="sent" if delivered else "failed",
            device_count=delivered,
            detail={"statuses": statuses},
        )
        return "sent" if delivered else "failed"

    async def run(self) -> None:
        logger.info(
            "[MobilePush] worker started (dry_run=%s, interval=%ss, window=%sh)",
            self.dry_run, self.interval_seconds, self.scan_window_hours,
        )
        while True:
            try:
                await self.run_cycle()
            except ApnsConfigError as exc:
                # Truthful and loud, then keep cycling — dry-run state is
                # re-checkable without a restart if env changes at redeploy.
                logger.error("[MobilePush] %s", exc)
            except Exception:
                logger.exception("[MobilePush] cycle failed")
            await asyncio.sleep(self.interval_seconds)


def push_worker_enabled() -> bool:
    return os.getenv("MOBILE_PUSH_WORKER_ENABLED", "false").lower() in (
        "1", "true", "yes",
    )


async def start_mobile_push_worker() -> asyncio.Task:
    """Start the worker loop (call from app lifespan when enabled)."""
    worker = MobilePushWorker()
    task = asyncio.create_task(worker.run())
    logger.info("[MobilePush] background worker task created")
    return task
