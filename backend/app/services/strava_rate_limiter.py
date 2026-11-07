"""
Strava Rate Limiter: Redis-backed outbound rate tracking for Strava API.

Strava enforces two rate windows:
  - 100 requests per 15 minutes
  - 1000 requests per day

This module tracks our outbound usage and blocks requests that would exceed
the budget. When Redis is unavailable, falls back to in-memory tracking.

Usage:
    limiter = StravaRateLimiter()
    if await limiter.acquire():
        response = await httpx_client.get(...)
        limiter.update_from_headers(dict(response.headers))
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from enum import IntEnum
from typing import Any, Dict, Optional

from ..metrics import (
    record_strava_rate_blocked,
    set_strava_rate_state,
)
logger = logging.getLogger(__name__)

# Strava rate limits
LIMIT_15MIN = 100
LIMIT_DAILY = 1000

# Redis key prefixes
REDIS_KEY_15MIN = "strava:rate:15m"
REDIS_KEY_DAILY = "strava:rate:daily"

# 15-minute window in seconds
WINDOW_15MIN = 15 * 60
# 1 day in seconds
WINDOW_DAILY = 24 * 60 * 60


class Priority(IntEnum):
    """Request priority levels. Lower number = higher priority."""
    REALTIME = 1   # Webhook-triggered processing
    BACKFILL = 10  # Historical backfill (can wait)


class StravaRateLimiter:
    """
    NATS KV-backed rate limiter for outbound Strava API requests.

    Falls back to in-memory counters when NATS is unavailable.
    """

    KV_BUCKET = "STRAVA_RATE"

    def __init__(self, redis_url: Optional[str] = None):
        # redis_url param kept for backward compat but unused
        self._kv = None
        self._kv_init_attempted = False

        # In-memory fallback counters
        self._mem_15min_count = 0
        self._mem_15min_window_start = time.time()
        self._mem_daily_count = 0
        self._mem_daily_window_start = time.time()

        # State from Strava response headers (authoritative when available)
        self._header_15min_usage = 0
        self._header_daily_usage = 0
        self._header_15min_limit = LIMIT_15MIN
        self._header_daily_limit = LIMIT_DAILY

    def _publish_rate_metrics(self, usage_15min: int, usage_daily: int) -> None:
        set_strava_rate_state(
            usage_15min=usage_15min,
            limit_15min=self._header_15min_limit,
            usage_daily=usage_daily,
            limit_daily=self._header_daily_limit,
        )

    async def _ensure_kv(self):
        """Lazily initialize the NATS KV bucket for Strava rate tracking."""
        if self._kv is not None or self._kv_init_attempted:
            return self._kv

        self._kv_init_attempted = True
        try:
            from .nats_client import get_nats_client
            client = get_nats_client()
            await client.connect()

            js = client._js
            try:
                self._kv = await js.key_value(self.KV_BUCKET)
            except Exception:
                self._kv = await js.create_key_value(
                    bucket=self.KV_BUCKET,
                    ttl=WINDOW_DAILY + 120,
                )
            logger.info("[StravaRateLimit] NATS KV bucket '%s' ready", self.KV_BUCKET)
        except Exception as e:
            logger.warning(f"[StravaRateLimit] NATS KV unavailable, using in-memory fallback: {e}")
            self._kv = None
        return self._kv

    def _current_15min_window(self) -> str:
        """Get the current 15-minute window identifier."""
        window_id = int(time.time()) // WINDOW_15MIN
        return f"{REDIS_KEY_15MIN}:{window_id}"

    def _current_daily_window(self) -> str:
        """Get the current daily window identifier."""
        from datetime import datetime, timezone
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return f"{REDIS_KEY_DAILY}:{day}"

    async def acquire(self, cost: int = 1, priority: Priority = Priority.REALTIME) -> bool:
        """
        Check if under rate budget and decrement if yes.

        Args:
            cost: Number of API calls this request represents
            priority: Request priority (lower priority requests get blocked earlier)

        Returns:
            True if request is allowed, False if rate limited
        """
        # For backfill priority, reserve 20% headroom for realtime
        headroom_factor = 1.0 if priority == Priority.REALTIME else 0.8

        kv = await self._ensure_kv()
        if kv:
            return await self._acquire_kv(kv, cost, headroom_factor, priority)
        return self._acquire_memory(cost, headroom_factor, priority)

    async def _acquire_kv(self, kv, cost: int, headroom_factor: float, priority: Priority) -> bool:
        """Acquire rate budget from NATS KV."""
        try:
            key_15min = self._current_15min_window()
            key_daily = self._current_daily_window()

            try:
                entry = await kv.get(key_15min)
                current_15min = int(entry.value.decode()) if entry and entry.value else 0
            except Exception:
                current_15min = 0

            try:
                entry = await kv.get(key_daily)
                current_daily = int(entry.value.decode()) if entry and entry.value else 0
            except Exception:
                current_daily = 0

            limit_15min = int(self._header_15min_limit * headroom_factor)
            limit_daily = int(self._header_daily_limit * headroom_factor)

            if current_15min + cost > limit_15min:
                logger.warning(
                    f"[StravaRateLimit] 15-min limit reached: {current_15min}/{limit_15min}"
                )
                record_strava_rate_blocked(priority=priority.name.lower(), window="15m")
                self._publish_rate_metrics(current_15min, current_daily)
                return False

            if current_daily + cost > limit_daily:
                logger.warning(
                    f"[StravaRateLimit] Daily limit reached: {current_daily}/{limit_daily}"
                )
                record_strava_rate_blocked(priority=priority.name.lower(), window="daily")
                self._publish_rate_metrics(current_15min, current_daily)
                return False

            # Increment counters
            await kv.put(key_15min, str(current_15min + cost).encode())
            await kv.put(key_daily, str(current_daily + cost).encode())
            self._publish_rate_metrics(current_15min + cost, current_daily + cost)

            return True

        except Exception as e:
            logger.warning(f"[StravaRateLimit] NATS KV error, falling back to memory: {e}")
            self._kv = None
            self._kv_init_attempted = False
            return self._acquire_memory(cost, headroom_factor, priority)

    def _acquire_memory(self, cost: int, headroom_factor: float, priority: Priority) -> bool:
        """Acquire rate budget from in-memory counters."""
        now = time.time()

        # Reset 15-min window if expired
        if now - self._mem_15min_window_start >= WINDOW_15MIN:
            self._mem_15min_count = 0
            self._mem_15min_window_start = now

        # Reset daily window if expired
        if now - self._mem_daily_window_start >= WINDOW_DAILY:
            self._mem_daily_count = 0
            self._mem_daily_window_start = now

        limit_15min = int(self._header_15min_limit * headroom_factor)
        limit_daily = int(self._header_daily_limit * headroom_factor)

        if self._mem_15min_count + cost > limit_15min:
            record_strava_rate_blocked(priority=priority.name.lower(), window="15m")
            self._publish_rate_metrics(self._mem_15min_count, self._mem_daily_count)
            return False
        if self._mem_daily_count + cost > limit_daily:
            record_strava_rate_blocked(priority=priority.name.lower(), window="daily")
            self._publish_rate_metrics(self._mem_15min_count, self._mem_daily_count)
            return False

        self._mem_15min_count += cost
        self._mem_daily_count += cost
        self._publish_rate_metrics(self._mem_15min_count, self._mem_daily_count)
        return True

    async def wait_for_capacity(
        self,
        cost: int = 1,
        priority: Priority = Priority.REALTIME,
        max_wait: float = 60,
    ) -> bool:
        """
        Poll until rate capacity is available or timeout.

        Args:
            cost: Number of API calls
            priority: Request priority
            max_wait: Maximum seconds to wait

        Returns:
            True if acquired, False if timed out
        """
        start = time.time()
        while time.time() - start < max_wait:
            if await self.acquire(cost, priority):
                return True
            await asyncio.sleep(2.0)
        return False

    def update_from_headers(self, headers: Dict[str, str]) -> None:
        """
        Update rate state from Strava response headers.

        Strava returns:
            X-RateLimit-Limit: "100,1000"  (15min, daily)
            X-RateLimit-Usage: "34,421"    (15min, daily)

        Args:
            headers: Response headers dict
        """
        limit_header = headers.get("X-RateLimit-Limit") or headers.get("x-ratelimit-limit")
        usage_header = headers.get("X-RateLimit-Usage") or headers.get("x-ratelimit-usage")

        if limit_header:
            try:
                parts = limit_header.split(",")
                self._header_15min_limit = int(parts[0].strip())
                if len(parts) > 1:
                    self._header_daily_limit = int(parts[1].strip())
            except (ValueError, IndexError):
                pass

        if usage_header:
            try:
                parts = usage_header.split(",")
                self._header_15min_usage = int(parts[0].strip())
                if len(parts) > 1:
                    self._header_daily_usage = int(parts[1].strip())

                # Sync Redis/memory with authoritative header values
                self._sync_usage_from_headers()
            except (ValueError, IndexError):
                pass

    def _sync_usage_from_headers(self) -> None:
        """Sync internal counters with Strava's reported usage (authoritative)."""
        redis = self._get_redis()
        if redis:
            try:
                key_15min = self._current_15min_window()
                key_daily = self._current_daily_window()
                redis.set(key_15min, self._header_15min_usage)
                redis.expire(key_15min, WINDOW_15MIN + 60)
                redis.set(key_daily, self._header_daily_usage)
                redis.expire(key_daily, WINDOW_DAILY + 60)
            except Exception:
                pass
        else:
            self._mem_15min_count = self._header_15min_usage
            self._mem_daily_count = self._header_daily_usage
        self._publish_rate_metrics(self._header_15min_usage, self._header_daily_usage)

    def seconds_until_15min_reset(self) -> float:
        """Seconds until the current 15-minute window resets."""
        window_id = int(time.time()) // WINDOW_15MIN
        window_end = (window_id + 1) * WINDOW_15MIN
        return max(0, window_end - time.time())

    def snapshot(self) -> Dict[str, Any]:
        """Return the current rate-limiter state for admin monitoring."""
        redis = self._get_redis()
        storage = "redis" if redis is not None else "memory"

        if redis is not None:
            try:
                current_15min = int(redis.get(self._current_15min_window()) or 0)
                current_daily = int(redis.get(self._current_daily_window()) or 0)
            except Exception:
                current_15min = self._mem_15min_count
                current_daily = self._mem_daily_count
                storage = "memory"
        else:
            current_15min = self._mem_15min_count
            current_daily = self._mem_daily_count

        self._publish_rate_metrics(current_15min, current_daily)

        return {
            "storage": storage,
            "redis_available": redis is not None,
            "usage_15min": current_15min,
            "limit_15min": self._header_15min_limit,
            "remaining_15min": max(0, self._header_15min_limit - current_15min),
            "usage_daily": current_daily,
            "limit_daily": self._header_daily_limit,
            "remaining_daily": max(0, self._header_daily_limit - current_daily),
            "reset_in_seconds_15min": int(self.seconds_until_15min_reset()),
        }


# Singleton instance
_rate_limiter: Optional[StravaRateLimiter] = None


def get_strava_rate_limiter() -> StravaRateLimiter:
    """Get or create the singleton rate limiter."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = StravaRateLimiter()
    return _rate_limiter
