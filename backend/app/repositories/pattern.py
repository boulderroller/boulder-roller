"""Pattern repository - climb, steady, and exploration patterns."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from .base import BaseRepository


class PatternRepository(BaseRepository):
    """Repository for ride pattern storage and retrieval."""

    async def clear_patterns_for_activity(self, activity_id: uuid.UUID) -> None:
        """Remove previously detected patterns for an activity before rewriting them."""
        activity = str(activity_id)
        await self._run(
            lambda: self._client.table("patterns_climb")
            .delete()
            .eq("activity_id", activity)
            .execute()
        )
        await self._run(
            lambda: self._client.table("patterns_steady")
            .delete()
            .eq("activity_id", activity)
            .execute()
        )
        await self._run(
            lambda: self._client.table("patterns_exploration")
            .delete()
            .eq("activity_id", activity)
            .execute()
        )

    async def store_climb_pattern(
        self,
        pattern_id: uuid.UUID,
        activity_id: uuid.UUID,
        wallet: str,
        vert_m: float,
        time_s: int,
        start_offset_s: int,
        end_offset_s: int,
        arena_id: Optional[uuid.UUID] = None,
        avg_power_w: Optional[float] = None,
        w_per_kg: Optional[float] = None,
        avg_hr: Optional[int] = None,
        road_name: Optional[str] = None,
        road_grade: Optional[float] = None,
        road_coverage_pct: Optional[float] = None,
        attribution_summary: Optional[str] = None,
        tile_ids: Optional[List[str]] = None,
        distance_m: Optional[float] = None,
        avg_gradient_pct: Optional[float] = None,
        signature_hex: Optional[str] = None,
        signature_v2_hex: Optional[str] = None,
        persistence_m: Optional[float] = None,
        significance_g: Optional[float] = None,
        significance_percentile: Optional[float] = None,
        significance_return_period: Optional[float] = None,
        significance_confidence_tier: Optional[int] = None,
        significance_bootstrapped: Optional[bool] = None,
        significance_cell_h3: Optional[str] = None,
        start_lat: Optional[float] = None,
        start_lon: Optional[float] = None,
        end_lat: Optional[float] = None,
        end_lon: Optional[float] = None,
        economic_eligible: bool = True,
        abstention_reasons: Optional[List[str]] = None,
        match_trace: Optional[Dict] = None,
        detector_version: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Store a detected climb pattern."""
        payload = {
            "id": str(pattern_id),
            "activity_id": str(activity_id),
            "wallet": wallet,
            "arena_id": str(arena_id) if arena_id else None,
            "vert_m": vert_m,
            "time_s": time_s,
            "avg_power_w": avg_power_w,
            "w_per_kg": w_per_kg,
            "avg_hr": avg_hr,
            "start_offset_s": start_offset_s,
            "end_offset_s": end_offset_s,
            "road_name": road_name,
            "road_grade": road_grade,
            "road_coverage_pct": road_coverage_pct,
            "attribution_summary": attribution_summary,
            "tile_ids": tile_ids,
            "distance_m": distance_m,
            "avg_gradient_pct": avg_gradient_pct,
            "signature_hex": signature_hex,
            "signature_v2_hex": signature_v2_hex,
            "persistence_m": persistence_m,
            "significance_g": significance_g,
            "significance_percentile": significance_percentile,
            "significance_return_period": significance_return_period,
            "significance_confidence_tier": significance_confidence_tier,
            "significance_bootstrapped": significance_bootstrapped,
            "significance_cell_h3": significance_cell_h3,
            "start_lat": start_lat,
            "start_lon": start_lon,
            "end_lat": end_lat,
            "end_lon": end_lon,
            "economic_eligible": economic_eligible,
            "abstention_reasons": abstention_reasons,
            "match_trace": match_trace,
            "detector_version": detector_version,
        }
        response = await self._run(
            lambda: self._client.table("patterns_climb").insert(payload).execute()
        )
        data = getattr(response, "data", None) or []
        return data[0] if data else payload

    async def store_steady_pattern(
        self,
        pattern_id: uuid.UUID,
        activity_id: uuid.UUID,
        wallet: str,
        duration_s: int,
        start_offset_s: int,
        end_offset_s: int,
        avg_power_w: Optional[float] = None,
        np_power_w: Optional[float] = None,
        avg_hr: Optional[int] = None,
        intensity_index: Optional[float] = None,
        variability_index: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Store a detected steady pattern."""
        payload = {
            "id": str(pattern_id),
            "activity_id": str(activity_id),
            "wallet": wallet,
            "duration_s": duration_s,
            "avg_power_w": avg_power_w,
            "np_power_w": np_power_w,
            "avg_hr": avg_hr,
            "intensity_index": intensity_index,
            "variability_index": variability_index,
            "start_offset_s": start_offset_s,
            "end_offset_s": end_offset_s,
        }
        response = await self._run(
            lambda: self._client.table("patterns_steady").insert(payload).execute()
        )
        data = getattr(response, "data", None) or []
        return data[0] if data else payload

    async def store_exploration_pattern(
        self,
        pattern_id: uuid.UUID,
        activity_id: uuid.UUID,
        wallet: str,
        new_tiles_wallet: int,
        total_tiles: int,
        start_offset_s: int,
        end_offset_s: int,
        new_tiles_global: Optional[int] = None,
        night_minutes: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Store a detected exploration pattern."""
        payload = {
            "id": str(pattern_id),
            "activity_id": str(activity_id),
            "wallet": wallet,
            "new_tiles_wallet": new_tiles_wallet,
            "new_tiles_global": new_tiles_global,
            "total_tiles": total_tiles,
            "night_minutes": night_minutes,
            "start_offset_s": start_offset_s,
            "end_offset_s": end_offset_s,
        }
        response = await self._run(
            lambda: self._client.table("patterns_exploration").insert(payload).execute()
        )
        data = getattr(response, "data", None) or []
        return data[0] if data else payload

    async def get_patterns_for_activity(
        self,
        activity_id: uuid.UUID,
    ) -> Dict[str, Any]:
        """Get all patterns for an activity."""
        climb_response = await self._run(
            lambda: self._client.table("patterns_climb")
            .select("*")
            .eq("activity_id", str(activity_id))
            .execute()
        )
        steady_response = await self._run(
            lambda: self._client.table("patterns_steady")
            .select("*")
            .eq("activity_id", str(activity_id))
            .limit(1)
            .execute()
        )
        exploration_response = await self._run(
            lambda: self._client.table("patterns_exploration")
            .select("*")
            .eq("activity_id", str(activity_id))
            .limit(1)
            .execute()
        )

        climb_data = getattr(climb_response, "data", None) or []
        steady_data = getattr(steady_response, "data", None) or []
        exploration_data = getattr(exploration_response, "data", None) or []

        return {
            "climb_patterns": climb_data,
            "steady_pattern": steady_data[0] if steady_data else None,
            "exploration_pattern": exploration_data[0] if exploration_data else None,
        }
