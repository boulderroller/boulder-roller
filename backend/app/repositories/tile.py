"""Tile repository - H3 tile samples and wallet territory history."""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from .base import BaseRepository

logger = logging.getLogger(__name__)

# Feature flag for asyncpg bulk inserts (COPY-based, 10-50x faster than PostgREST)
USE_ASYNCPG_BULK = os.getenv("USE_ASYNCPG_BULK", "false").lower() in ("1", "true", "yes", "on")


def _is_transient_asyncpg_bulk_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "another operation is in progress" in text
        or "connectiondoesnotexisterror" in exc.__class__.__name__.lower()
        or "connection was closed" in text
        or "connection is closed" in text
    )


class TileRepository(BaseRepository):
    """Repository for H3 tile and territory operations."""

    async def store_activity_tile_samples(
        self,
        ride_id: uuid.UUID,
        tile_samples: List[Dict[str, Any]],
    ) -> int:
        """Store H3 tile samples for an activity.

        Expected tile_sample format:
        {
            "tile_id": str,  # H3 index
            "t": int,  # seconds since ride start
            "elevation_m": Optional[float],
            "power_w": Optional[int],
            "hr_bpm": Optional[int],
            "speed_mps": Optional[float],
        }

        When USE_ASYNCPG_BULK=true, uses asyncpg COPY for 10-50x faster inserts.
        Falls back to PostgREST batch inserts if asyncpg fails.
        """
        if not tile_samples:
            return 0

        # Try asyncpg COPY path first if enabled
        if USE_ASYNCPG_BULK:
            try:
                return await self._store_tile_samples_asyncpg(ride_id, tile_samples)
            except Exception as e:
                if _is_transient_asyncpg_bulk_error(e):
                    logger.warning(
                        "asyncpg bulk insert hit transient connection state; retrying once: %s",
                        e,
                    )
                    await asyncio.sleep(0.1)
                    try:
                        return await self._store_tile_samples_asyncpg(ride_id, tile_samples)
                    except Exception as retry_error:
                        logger.warning(
                            "asyncpg bulk insert retry failed, falling back to PostgREST: %s",
                            retry_error,
                        )
                        return await self._store_tile_samples_postgrest(ride_id, tile_samples)
                logger.warning(
                    f"asyncpg bulk insert failed, falling back to PostgREST: {e}"
                )

        # Default: PostgREST batch inserts
        return await self._store_tile_samples_postgrest(ride_id, tile_samples)

    async def _store_tile_samples_postgrest(
        self,
        ride_id: uuid.UUID,
        tile_samples: List[Dict[str, Any]],
    ) -> int:
        """Store tile samples using PostgREST batch inserts (original path)."""
        all_records = [
            {
                "activity_id": str(ride_id),
                "tile_id": sample["tile_id"],
                "t": sample.get("t", i),
                "elevation_m": sample.get("elevation_m"),
                "power_w": sample.get("power_w"),
                "hr_bpm": sample.get("hr_bpm"),
                "speed_mps": sample.get("speed_mps"),
            }
            for i, sample in enumerate(tile_samples)
        ]

        # Batch inserts to avoid Supabase row limits
        BATCH_SIZE = 1000
        total_inserted = 0

        for i in range(0, len(all_records), BATCH_SIZE):
            batch = all_records[i:i + BATCH_SIZE]
            response = await self._run(
                lambda batch=batch: self._client.table("activity_tile_samples").insert(batch).execute()
            )
            data = getattr(response, "data", None) or []
            total_inserted += len(data)

        return total_inserted

    async def _store_tile_samples_asyncpg(
        self,
        ride_id: uuid.UUID,
        tile_samples: List[Dict[str, Any]],
    ) -> int:
        """Store tile samples using asyncpg COPY (10-50x faster than PostgREST).

        Uses copy_records_to_table for bulk binary COPY protocol.
        The id column uses gen_random_uuid() default so we omit it.
        The created_at column uses NOW() default so we omit it.
        """
        from ..db_pool import get_pool
        pool = await get_pool()

        ride_id_str = str(ride_id)

        # Build records as tuples matching the column order
        records = []
        for i, sample in enumerate(tile_samples):
            records.append((
                uuid.UUID(ride_id_str),       # activity_id (UUID)
                sample.get("t", i),           # t (INTEGER)
                sample["tile_id"],            # tile_id (TEXT)
                sample.get("elevation_m"),    # elevation_m (FLOAT)
                sample.get("power_w"),        # power_w (FLOAT — schema is FLOAT not INT)
                sample.get("hr_bpm"),         # hr_bpm (INTEGER)
                sample.get("speed_mps"),      # speed_mps (FLOAT)
            ))

        columns = [
            "activity_id",
            "t",
            "tile_id",
            "elevation_m",
            "power_w",
            "hr_bpm",
            "speed_mps",
        ]

        async with pool.acquire() as conn:
            result = await conn.copy_records_to_table(
                "activity_tile_samples",
                records=records,
                columns=columns,
            )
            # result is a status string like "COPY 1234"
            count = int(result.split()[-1]) if result else len(records)
            logger.info(
                f"asyncpg COPY inserted {count} tile samples for ride {ride_id}"
            )
            return count

    async def update_wallet_tile_history(
        self,
        user_id: uuid.UUID,
        tile_ids: List[str],
        visited_at: Optional[datetime] = None,
    ) -> int:
        """Update wallet tile history for exploration tracking.

        Returns the count of new tiles explored.
        """
        if not tile_ids:
            return 0

        # Get wallet address from user
        user_response = await self._run(
            lambda: self._client.table("users")
            .select("wallet")
            .eq("id", str(user_id))
            .limit(1)
            .execute()
        )
        user_data = getattr(user_response, "data", None) or []
        if not user_data or not user_data[0].get("wallet"):
            return 0

        wallet = user_data[0]["wallet"]
        visited_timestamp = visited_at or datetime.now(timezone.utc)
        unique_tiles = list(set(tile_ids))

        # Check existing tiles for this wallet in batches
        BATCH_SIZE = 200
        existing_tile_ids: Set[str] = set()

        for i in range(0, len(unique_tiles), BATCH_SIZE):
            batch = unique_tiles[i:i + BATCH_SIZE]
            existing_response = await self._run(
                lambda batch=batch: self._client.table("wallet_tile_history")
                .select("tile_id")
                .eq("wallet", wallet)
                .in_("tile_id", batch)
                .execute()
            )
            existing_data = getattr(existing_response, "data", None) or []
            existing_tile_ids.update(row["tile_id"] for row in existing_data)

        # Find new tiles
        new_tiles = [tile_id for tile_id in unique_tiles if tile_id not in existing_tile_ids]

        if not new_tiles:
            return 0

        # Insert new tile history records in batches
        INSERT_BATCH_SIZE = 500
        total_inserted = 0

        for i in range(0, len(new_tiles), INSERT_BATCH_SIZE):
            batch_tiles = new_tiles[i:i + INSERT_BATCH_SIZE]
            records = [
                {
                    "wallet": wallet,
                    "tile_id": tile_id,
                    "first_visited_at": visited_timestamp.isoformat(),
                    "visit_count": 1,
                }
                for tile_id in batch_tiles
            ]

            response = await self._run(
                lambda records=records: self._client.table("wallet_tile_history").insert(records).execute()
            )
            data = getattr(response, "data", None) or []
            total_inserted += len(data)

        return total_inserted

    async def get_wallet_tile_history(self, wallet: str) -> Set[str]:
        """Get all tile IDs previously visited by a wallet."""
        response = await self._run(
            lambda: self._client.table("wallet_tile_history")
            .select("tile_id")
            .eq("wallet", wallet)
            .execute()
        )
        data = getattr(response, "data", None) or []
        return {row["tile_id"] for row in data}

    async def get_global_tile_coverage(self) -> Set[str]:
        """Get all tile IDs ever visited by any wallet."""
        response = await self._run(
            lambda: self._client.table("wallet_tile_history")
            .select("tile_id")
            .execute()
        )
        data = getattr(response, "data", None) or []
        return {row["tile_id"] for row in data}
