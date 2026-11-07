"""Shared asyncpg connection pool for direct Postgres access.

The Supabase REST API has egress quotas. Heavy READ operations should use
this pool instead.  WRITE operations that depend on Supabase RPC functions
(atomic ops) should continue to use the Supabase client.

Usage:
    from app.db_pool import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM indexed_vaults")
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_pool = None
_pool_loop = None
_pool_lock = None
_pool_lock_loop = None


def _get_lock():
    """Lazy-create an asyncio lock (must be called inside a running loop)."""
    import asyncio

    global _pool_lock, _pool_lock_loop
    loop = asyncio.get_running_loop()
    if (
        _pool_lock is None
        or _pool_lock_loop is not loop
        or getattr(_pool_lock_loop, "is_closed", lambda: False)()
    ):
        _pool_lock = asyncio.Lock()
        _pool_lock_loop = loop
    return _pool_lock


async def get_pool():
    """Get or create the shared asyncpg connection pool.

    Initializes lazily on first call.  Requires ``DATABASE_URL`` env var.
    Pool size: min=2, max=10 (appropriate for a single API container).
    """
    import asyncio

    global _pool, _pool_loop
    loop = asyncio.get_running_loop()

    if _pool is not None and _pool_loop is loop:
        return _pool
    if _pool is not None:
        try:
            _pool.terminate()
        except Exception as exc:
            logger.debug("Failed to terminate asyncpg pool from another event loop: %s", exc)
        _pool = None
        _pool_loop = None

    lock = _get_lock()
    async with lock:
        # Double-check after acquiring lock
        if _pool is not None and _pool_loop is loop:
            return _pool
        if _pool is not None:
            try:
                _pool.terminate()
            except Exception as exc:
                logger.debug("Failed to terminate asyncpg pool from another event loop: %s", exc)
            _pool = None
            _pool_loop = None

        import asyncpg

        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError(
                "DATABASE_URL environment variable is required for asyncpg pool. "
                "Direct Postgres access is unavailable."
            )

        _pool = await asyncpg.create_pool(
            database_url,
            min_size=2,
            max_size=10,
            command_timeout=60,
        )
        _pool_loop = loop
        logger.info("Shared asyncpg pool created (min=2, max=10)")
        return _pool


async def close_pool():
    """Close the shared pool (call during app shutdown)."""
    import asyncio

    global _pool, _pool_loop
    if _pool is None:
        return

    pool = _pool
    pool_loop = _pool_loop
    _pool = None
    _pool_loop = None

    current_loop = asyncio.get_running_loop()
    if pool_loop is current_loop and not current_loop.is_closed():
        await pool.close()
        logger.info("Shared asyncpg pool closed")
        return

    try:
        pool.terminate()
        logger.info("Shared asyncpg pool terminated from non-owner event loop")
    except Exception as exc:
        logger.warning("Error terminating asyncpg pool from non-owner event loop: %s", exc)
