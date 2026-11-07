"""Fitness repository - training load and fitness metrics."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from .base import BaseRepository


class FitnessRepository(BaseRepository):
    """Repository for fitness and training load data."""

    def _first_row(self, response) -> Optional[Dict[str, Any]]:
        """Extract first row from response."""
        data = getattr(response, "data", None) or []
        return dict(data[0]) if data else None

    def _with_date_field(self, row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Convert date string to date object if present."""
        if row and "date" in row and isinstance(row["date"], str):
            try:
                row["date"] = date.fromisoformat(row["date"])
            except (ValueError, TypeError):
                pass
        return row

    async def get_daily_training_load(
        self, user_id: str, target_date: date
    ) -> Optional[Dict[str, Any]]:
        """Get training load for a specific date."""
        response = await self._run(
            lambda: self._client.table("daily_training_load")
            .select("*")
            .eq("user_id", str(user_id))
            .eq("date", target_date.isoformat())
            .limit(1)
            .execute()
        )
        row = self._first_row(response)
        return self._with_date_field(row)

    async def upsert_daily_training_load(
        self,
        user_id: str,
        load_date: date,
        total_tss: float,
        ride_count: int,
        total_duration_sec: int,
        total_distance_m: float,
    ) -> Dict[str, Any]:
        """Create or update daily training load."""
        payload = {
            "user_id": str(user_id),
            "date": load_date.isoformat(),
            "total_tss": float(total_tss),
            "ride_count": int(ride_count),
            "total_duration_sec": int(total_duration_sec),
            "total_distance_m": float(total_distance_m),
        }
        response = await self._run(
            lambda: self._client.table("daily_training_load")
            .upsert(payload, on_conflict="user_id,date")
            .execute()
        )
        return self._with_date_field(self._first_row(response) or payload) or payload

    async def get_daily_training_loads(
        self, user_id: str, start_date: date, end_date: date
    ) -> List[Dict[str, Any]]:
        """Get training loads for a date range."""
        response = await self._run(
            lambda: self._client.table("daily_training_load")
            .select("*")
            .eq("user_id", str(user_id))
            .gte("date", start_date.isoformat())
            .lte("date", end_date.isoformat())
            .order("date")
            .execute()
        )
        data = getattr(response, "data", None) or []
        return [self._with_date_field(dict(row)) or dict(row) for row in data]

    async def get_fitness_metrics(
        self, user_id: str, target_date: date
    ) -> Optional[Dict[str, Any]]:
        """Get fitness metrics (CTL/ATL/TSB) for a specific date."""
        response = await self._run(
            lambda: self._client.table("fitness_metrics")
            .select("*")
            .eq("user_id", str(user_id))
            .eq("date", target_date.isoformat())
            .limit(1)
            .execute()
        )
        row = self._first_row(response)
        return self._with_date_field(row)

    async def get_fitness_metrics_range(
        self,
        user_id: str,
        start_date: date,
        end_date: date,
    ) -> List[Dict[str, Any]]:
        """Get fitness metrics for a date range."""
        response = await self._run(
            lambda: self._client.table("fitness_metrics")
            .select("*")
            .eq("user_id", str(user_id))
            .gte("date", start_date.isoformat())
            .lte("date", end_date.isoformat())
            .order("date")
            .execute()
        )
        data = getattr(response, "data", None) or []
        return [self._with_date_field(dict(row)) or dict(row) for row in data]

    async def upsert_fitness_metrics(
        self,
        user_id: str,
        metrics_date: date,
        ctl: float,
        atl: float,
        tsb: float,
        ramp_rate: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Create or update fitness metrics (CTL/ATL/TSB)."""
        payload = {
            "user_id": str(user_id),
            "date": metrics_date.isoformat(),
            "ctl": float(ctl),
            "atl": float(atl),
            "tsb": float(tsb),
            "ramp_rate": float(ramp_rate) if ramp_rate is not None else None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        response = await self._run(
            lambda: self._client.table("fitness_metrics")
            .upsert(payload, on_conflict="user_id,date")
            .execute()
        )
        return self._with_date_field(self._first_row(response) or payload) or payload
