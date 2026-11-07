"""
Database-backed lease helper for singleton background workers.

Multiple API instances may start the same background loop. These helpers use
database RPCs to ensure only one instance actively performs the work at a time.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from uuid import uuid4

logger = logging.getLogger(__name__)

DEFAULT_LOCK_TTL_SECONDS = 900


def _build_default_owner_id(job_name: str) -> str:
    owner_prefix = os.getenv("BACKGROUND_JOB_LOCK_OWNER_ID")
    if owner_prefix:
        return f"{owner_prefix}:{job_name}"
    return f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}:{job_name}"


def _coerce_rpc_bool(data: object) -> bool:
    """Handle the shapes Supabase RPC responses use for scalar values."""
    if isinstance(data, list):
        if not data:
            return False
        return _coerce_rpc_bool(data[0])
    if isinstance(data, dict):
        if "acquired" in data:
            return bool(data["acquired"])
        if "released" in data:
            return bool(data["released"])
        if data:
            return bool(next(iter(data.values())))
        return False
    return bool(data)


def _is_missing_lock_infrastructure(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "acquire_background_job_lock" in message
        or "release_background_job_lock" in message
        or "background_job_locks" in message
        or "could not find the function" in message
        or "does not exist" in message
    )


class BackgroundJobLock:
    """Small async wrapper around the background-job lock RPCs."""

    def __init__(
        self,
        supabase_client,
        job_name: str,
        ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
        owner_id: str | None = None,
    ) -> None:
        self._client = supabase_client
        self.job_name = job_name
        self.ttl_seconds = max(ttl_seconds, 30)
        self.owner_id = owner_id or _build_default_owner_id(job_name)
        self._has_lock = False
        self._compat_mode = False

    async def acquire(self) -> bool:
        if self._compat_mode:
            self._record_state(True)
            return True

        try:
            result = await asyncio.to_thread(
                lambda: self._client.rpc(
                    "acquire_background_job_lock",
                    {
                        "p_job_name": self.job_name,
                        "p_owner_id": self.owner_id,
                        "p_ttl_seconds": self.ttl_seconds,
                    },
                ).execute()
            )
        except Exception as exc:
            if not _is_missing_lock_infrastructure(exc):
                raise
            self._compat_mode = True
            logger.warning(
                "[BackgroundJobLock] Lease RPC unavailable for %s; falling back "
                "to uncoordinated execution until migration 083 is applied",
                self.job_name,
            )
            self._record_state(True)
            return True

        acquired = _coerce_rpc_bool(getattr(result, "data", None))
        self._record_state(acquired)
        return acquired

    async def release(self) -> bool:
        if self._compat_mode:
            self._has_lock = False
            return False

        result = await asyncio.to_thread(
            lambda: self._client.rpc(
                "release_background_job_lock",
                {
                    "p_job_name": self.job_name,
                    "p_owner_id": self.owner_id,
                },
            ).execute()
        )
        released = _coerce_rpc_bool(getattr(result, "data", None))
        if released and self._has_lock:
            logger.info(
                "[BackgroundJobLock] Released lease for %s (owner=%s)",
                self.job_name,
                self.owner_id,
            )
        self._has_lock = False
        return released

    def _record_state(self, acquired: bool) -> None:
        if acquired and not self._has_lock:
            logger.info(
                "[BackgroundJobLock] Acquired lease for %s (owner=%s)",
                self.job_name,
                self.owner_id,
            )
        elif not acquired and self._has_lock:
            logger.warning(
                "[BackgroundJobLock] Lost lease for %s (owner=%s)",
                self.job_name,
                self.owner_id,
            )
        self._has_lock = acquired
