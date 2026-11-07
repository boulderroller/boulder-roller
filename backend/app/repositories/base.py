"""Shared repository infrastructure."""
from __future__ import annotations

import asyncio
import logging
import time
from functools import lru_cache
from typing import Any, Callable

from supabase.lib.client_options import ClientOptions

from ..config import load_supabase_settings
from ..supabase_client import BackendSupabaseClient, create_backend_supabase_client

logger = logging.getLogger(__name__)


class BaseRepository:
    """Base class with shared Supabase client and async wrapper."""

    def __init__(self, client: BackendSupabaseClient) -> None:
        self._client = client

    @property
    def client(self) -> BackendSupabaseClient:
        """Expose the Supabase client for direct queries if needed."""
        return self._client

    async def _run(self, func: Callable[[], Any], operation: str = "supabase") -> Any:
        """Run sync Supabase call in thread pool with metrics."""
        from ..metrics import (
            SUPABASE_REQUEST_DURATION,
            SUPABASE_REQUEST_ERRORS,
            SUPABASE_REQUESTS_IN_FLIGHT,
        )

        start = time.perf_counter()
        SUPABASE_REQUESTS_IN_FLIGHT.inc()
        try:
            return await asyncio.to_thread(func)
        except Exception:
            SUPABASE_REQUEST_ERRORS.labels(operation=operation).inc()
            raise
        finally:
            SUPABASE_REQUESTS_IN_FLIGHT.dec()
            SUPABASE_REQUEST_DURATION.labels(operation=operation).observe(
                time.perf_counter() - start
            )

    async def health(self) -> bool:
        """Check database connectivity."""
        try:
            await self._run(
                lambda: self._client.table("users").select("id").limit(1).execute()
            )
            return True
        except Exception:
            return False


@lru_cache(maxsize=1)
def _build_supabase_client() -> BackendSupabaseClient:
    """Build and cache a Supabase client instance."""
    settings = load_supabase_settings()
    if not settings:
        raise RuntimeError(
            "Supabase configuration is missing. "
            "Ensure SUPABASE_URL and service key are set."
        )
    # Increase timeout from default 5s to 60s to handle large batch inserts
    # Long rides (7+ hours) can have 18,000+ GPS points
    options = ClientOptions(postgrest_client_timeout=60)
    return create_backend_supabase_client(
        settings.url,
        settings.service_key,
        options=options,
    )


def get_supabase_client() -> BackendSupabaseClient:
    """Get the shared Supabase client instance."""
    return _build_supabase_client()
