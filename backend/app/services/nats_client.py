"""
NATS JetStream client for ride processing events.

Provides a singleton async NATS connection with JetStream context.
Events are published best-effort — NATS failures never block ride processing.

Stream: RIDES
Subjects: rides.events.>
    - rides.events.uploaded       — ride file uploaded, ready for processing
    - rides.events.metrics_ready  — Phase 1 complete (parse, metrics, GPS)
    - rides.events.enriched       — Phase 2 complete (tiles, patterns, vaults)
    - rides.events.completed      — Phase 3 complete (points, achievements)

Usage:
    from .nats_client import get_nats_client

    client = get_nats_client()
    await client.publish("rides.events.uploaded", {"ride_id": "...", "wallet": "..."})
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable, Coroutine, Dict, Optional

import nats
from nats.aio.client import Client as NATSClient
from nats.js import JetStreamContext

logger = logging.getLogger(__name__)

NATS_URL = os.getenv("NATS_URL", "nats://localhost:4222")


def _nats_enabled() -> bool:
    return os.getenv("NATS_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")

# Stream configuration
STREAM_NAME = "RIDES"
STREAM_SUBJECTS = ["rides.events.>"]


class NatsClient:
    """Async NATS JetStream client with lazy connection and graceful reconnection."""

    def __init__(self, url: str = NATS_URL) -> None:
        self._url = url
        self._nc: Optional[NATSClient] = None
        self._js: Optional[JetStreamContext] = None
        self._connected = False

    async def connect(self) -> None:
        """
        Connect to NATS and create JetStream context.

        Ensures the RIDES stream exists, creating it if necessary.
        Reconnection is handled automatically by the nats-py client.
        """
        if self._connected and self._nc and self._nc.is_connected:
            return

        if not _nats_enabled():
            self._connected = False
            raise RuntimeError("NATS disabled via NATS_ENABLED=false")

        try:
            self._nc = await nats.connect(
                self._url,
                reconnect_time_wait=2,       # seconds between reconnect attempts
                max_reconnect_attempts=-1,   # unlimited reconnection attempts
                error_cb=self._on_error,
                disconnected_cb=self._on_disconnect,
                reconnected_cb=self._on_reconnect,
                closed_cb=self._on_close,
            )
            self._js = self._nc.jetstream()

            # Ensure the RIDES stream exists
            await self._ensure_stream()

            self._connected = True
            logger.info(f"[NATS] Connected to {self._url}")

        except Exception as exc:
            logger.warning(f"[NATS] Failed to connect to {self._url}: {exc}")
            self._connected = False
            raise

    async def _ensure_stream(self) -> None:
        """Create or update the RIDES stream if it doesn't exist."""
        try:
            await self._js.find_stream_name_by_subject("rides.events.uploaded")
            logger.info(f"[NATS] Stream '{STREAM_NAME}' already exists")
        except nats.js.errors.NotFoundError:
            logger.info(f"[NATS] Creating stream '{STREAM_NAME}'")
            await self._js.add_stream(
                name=STREAM_NAME,
                subjects=STREAM_SUBJECTS,
                retention="limits",      # Retain by limits (max age, max msgs, etc.)
                max_age=7 * 24 * 3600,  # 7 days retention (seconds, passed as int)
                storage="file",          # Persist to disk
                num_replicas=1,          # Single node
                duplicate_window=120,    # 2 minute dedup window (seconds)
            )
            logger.info(f"[NATS] Stream '{STREAM_NAME}' created")

    async def publish(self, subject: str, payload: Dict[str, Any]) -> bool:
        """
        Publish a JSON message to a JetStream subject.

        Best-effort: logs warning on failure, never raises. Returns True when
        JetStream accepted the message and False when publishing failed.

        Args:
            subject: NATS subject (e.g., "rides.events.uploaded")
            payload: Dict to be JSON-serialized
        """
        try:
            if not self._connected or not self._nc or not self._nc.is_connected:
                await self.connect()

            data = json.dumps(payload).encode("utf-8")

            # Use ride_id as dedup key if present
            headers = {}
            if "ride_id" in payload:
                headers["Nats-Msg-Id"] = f"{subject}:{payload['ride_id']}"

            ack = await self._js.publish(
                subject,
                data,
                headers=headers if headers else None,
            )
            logger.info(
                f"[NATS] Published {subject} seq={ack.seq} "
                f"ride_id={payload.get('ride_id', 'N/A')}"
            )
            return True

        except Exception as exc:
            logger.warning(
                f"[NATS] Failed to publish {subject}: {exc} "
                f"(ride_id={payload.get('ride_id', 'N/A')})"
            )
            return False

    async def subscribe(
        self,
        subject: str,
        queue_group: str,
        handler: Callable[[Any], Coroutine],
        durable: Optional[str] = None,
    ) -> Any:
        """
        Subscribe to a JetStream subject with a queue group for load balancing.

        Uses a pull-based consumer with durable name for at-least-once delivery.

        Args:
            subject: NATS subject pattern (e.g., "rides.events.>")
            queue_group: Queue group name for load balancing (e.g., "ride-workers")
            handler: Async callback receiving (msg) — must call msg.ack() on success
            durable: Durable consumer name (defaults to queue_group)

        Returns:
            The subscription object (for later unsubscribe)
        """
        if not self._connected or not self._nc or not self._nc.is_connected:
            await self.connect()

        durable_name = durable or queue_group
        sub = await self._js.subscribe(
            subject,
            queue=queue_group,
            durable=durable_name,
            cb=handler,
            manual_ack=True,
        )
        logger.info(
            f"[NATS] Subscribed to {subject} "
            f"queue={queue_group} durable={durable_name}"
        )
        return sub

    async def close(self) -> None:
        """Gracefully close the NATS connection."""
        if self._nc and self._nc.is_connected:
            await self._nc.drain()
            logger.info("[NATS] Connection drained and closed")
        self._connected = False
        self._nc = None
        self._js = None

    @property
    def is_connected(self) -> bool:
        return self._connected and self._nc is not None and self._nc.is_connected

    # ---- Callbacks ----

    async def _on_error(self, exc: Exception) -> None:
        logger.error(f"[NATS] Error: {exc}")

    async def _on_disconnect(self) -> None:
        logger.info("[NATS] Disconnected")
        self._connected = False

    async def _on_reconnect(self) -> None:
        logger.info("[NATS] Reconnected")
        self._connected = True

    async def _on_close(self) -> None:
        logger.info("[NATS] Connection closed")
        self._connected = False


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_client: Optional[NatsClient] = None


def get_nats_client() -> NatsClient:
    """Return the module-level NatsClient singleton."""
    global _client
    if _client is None:
        _client = NatsClient(NATS_URL)
    return _client


async def close_nats_client() -> None:
    """Close the module-level NatsClient singleton (call on shutdown)."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None
