"""Segment repository - segments, efforts, pools, epochs, and leaderboards."""
from __future__ import annotations

import uuid
import warnings
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from .base import BaseRepository


class SegmentRepository(BaseRepository):
    """Repository for segment and effort operations."""

    def _first_row(self, response) -> Optional[Dict[str, Any]]:
        """Extract first row from response."""
        data = getattr(response, "data", None) or []
        return dict(data[0]) if data else None

    async def get_segment_by_id(self, segment_id: str) -> Optional[Dict[str, Any]]:
        """Get a segment by ID."""
        response = await self._run(
            lambda: self._client.table("segments")
            .select("*")
            .eq("id", segment_id)
            .limit(1)
            .execute()
        )
        return self._first_row(response)

    async def list_segments(
        self,
        bbox: Optional[tuple[float, float, float, float]] = None,
        query: Optional[str] = None,
        min_lat: Optional[float] = None,
        max_lat: Optional[float] = None,
        min_lon: Optional[float] = None,
        max_lon: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """List segments with optional geographic/name filters.

        DEPRECATED: Segment infrastructure has been replaced by pattern-based system.
        This method is kept for backwards compatibility with existing staking.
        Use pattern-based APIs instead.
        """
        warnings.warn(
            "list_segments is deprecated. Use pattern-based APIs instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        # Normalize bbox inputs (can come from tuple or explicit bounds)
        if bbox is None and all(v is not None for v in (min_lon, min_lat, max_lon, max_lat)):
            bbox = (min_lon, min_lat, max_lon, max_lat)  # type: ignore[assignment]

        if bbox or query or any(v is not None for v in (min_lat, max_lat, min_lon, max_lon)):
            params: Dict[str, Any] = {
                "west": bbox[0] if bbox else min_lon,
                "south": bbox[1] if bbox else min_lat,
                "east": bbox[2] if bbox else max_lon,
                "north": bbox[3] if bbox else max_lat,
                "name_query": query,
            }
            response = await self._run(
                lambda: self._client.rpc("segments_search", params).execute()
            )
        else:
            response = await self._run(
                lambda: self._client.table("segments").select("*").execute()
            )
        data = getattr(response, "data", None) or []
        return [dict(row) for row in data]

    async def get_segment_pool(self, segment_id: str) -> Dict[str, float]:
        """Get total staked DUNG and LP tokens for a segment."""
        response = await self._run(
            lambda: self._client.table("claims")
            .select("amount, lp_tokens")
            .eq("segment_id", segment_id)
            .execute()
        )
        data = getattr(response, "data", None) or []
        total_dung = sum(float(row.get("amount") or 0) for row in data)
        total_lp = sum(float(row.get("lp_tokens") or 0) for row in data)
        return {"total_dung": total_dung, "total_lp": total_lp}

    # Segment efforts
    async def create_segment_effort(
        self,
        ride_id: uuid.UUID,
        user_id: uuid.UUID,
        segment_id: Union[uuid.UUID, int],
        elapsed_time_sec: int,
        effort_score: float,
        average_power_w: Optional[float],
        average_hr_bpm: Optional[float],
        elevation_gain_m: Optional[float],
        distance_m: Optional[float],
        is_pr: bool,
        is_kom: bool,
        rank_at_time: Optional[int],
    ) -> uuid.UUID:
        """Create a segment effort record."""
        effort_id = str(uuid.uuid4())
        payload = {
            "id": effort_id,
            "ride_id": str(ride_id),
            "user_id": str(user_id),
            "segment_id": str(segment_id),
            "elapsed_time_sec": elapsed_time_sec,
            "effort_score": float(effort_score),
            "average_power_w": average_power_w,
            "average_hr_bpm": average_hr_bpm,
            "elevation_gain_m": elevation_gain_m,
            "distance_m": distance_m,
            "is_pr": is_pr,
            "is_kom": is_kom,
            "rank_at_time": rank_at_time,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        await self._run(
            lambda: self._client.table("segment_efforts").insert(payload).execute()
        )
        return uuid.UUID(effort_id)

    async def get_segment_best_effort(
        self, segment_id: Union[uuid.UUID, int]
    ) -> Optional[Dict[str, Any]]:
        """Get the best (fastest) effort for a segment."""
        response = await self._run(
            lambda: self._client.table("segment_efforts")
            .select("*")
            .eq("segment_id", str(segment_id))
            .order("elapsed_time_sec")
            .limit(1)
            .execute()
        )
        return self._first_row(response)

    async def get_user_best_segment_effort(
        self, user_id: uuid.UUID, segment_id: Union[uuid.UUID, int]
    ) -> Optional[Dict[str, Any]]:
        """Get a user's best effort for a segment."""
        response = await self._run(
            lambda: self._client.table("segment_efforts")
            .select("*")
            .eq("segment_id", str(segment_id))
            .eq("user_id", str(user_id))
            .order("elapsed_time_sec")
            .limit(1)
            .execute()
        )
        return self._first_row(response)

    async def get_segment_effort_rank(
        self, segment_id: Union[uuid.UUID, int], elapsed_time_sec: int
    ) -> Optional[int]:
        """Get the rank for a given time on a segment."""
        response = await self._run(
            lambda: self._client.table("segment_efforts")
            .select("id", count="exact")
            .eq("segment_id", str(segment_id))
            .lt("elapsed_time_sec", elapsed_time_sec)
            .execute()
        )
        count = getattr(response, "count", None)
        if count is None:
            return None
        return int(count) + 1

    async def get_ride_segment_efforts(
        self, ride_id: uuid.UUID
    ) -> List[Dict[str, Any]]:
        """Get all segment efforts for a ride."""
        response = await self._run(
            lambda: self._client.table("segment_efforts")
            .select("*")
            .eq("ride_id", str(ride_id))
            .order("elapsed_time_sec")
            .execute()
        )
        data = getattr(response, "data", None) or []
        return [dict(row) for row in data]

    # Epochs
    async def get_current_epoch(self, segment_id: str) -> Optional[Dict[str, Any]]:
        """Get the current active epoch for a segment."""
        response = await self._run(
            lambda: self._client.table("epochs")
            .select("*")
            .eq("segment_id", segment_id)
            .gt("end_time", datetime.now(timezone.utc).isoformat())
            .order("epoch_number", desc=True)
            .limit(1)
            .execute()
        )
        return self._first_row(response)

    async def get_epoch(
        self, segment_id: str, epoch_number: int
    ) -> Optional[Dict[str, Any]]:
        """Get a specific epoch for a segment."""
        response = await self._run(
            lambda: self._client.table("epochs")
            .select("*")
            .eq("segment_id", segment_id)
            .eq("epoch_number", epoch_number)
            .limit(1)
            .execute()
        )
        return self._first_row(response)

    async def get_segment_epoch_activity(
        self, segment_id: str, epoch_number: int
    ) -> Dict[str, Any]:
        """Get activity stats for a segment epoch."""
        response = await self._run(
            lambda: self._client.table("segment_activity")
            .select("*")
            .eq("segment_id", segment_id)
            .eq("epoch_number", epoch_number)
            .limit(1)
            .execute()
        )
        return self._first_row(response) or {}

    # Leaderboards
    async def get_leaderboard(
        self, segment_id: str, epoch_number: int, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get leaderboard entries for a segment epoch."""
        response = await self._run(
            lambda: self._client.table("leaderboard_entries")
            .select("*")
            .eq("segment_id", segment_id)
            .eq("epoch_number", epoch_number)
            .order("rank")
            .limit(limit)
            .execute()
        )
        data = getattr(response, "data", None) or []
        return [dict(row) for row in data]
