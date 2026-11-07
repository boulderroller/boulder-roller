"""Territory repository - wallet tile history and territory stats."""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from ..utils.postgrest_paging import order_by, window
from .base import BaseRepository

logger = logging.getLogger(__name__)


class TerritoryRepository(BaseRepository):
    """Repository for territory/map queries against wallet_tile_history."""

    async def get_user_tiles(
        self,
        wallet: str,
        limit: int = 10000,
    ) -> List[Dict[str, Any]]:
        """Get all tiles visited by a wallet with visit metadata."""
        all_data: List[Dict[str, Any]] = []
        page_size = 1000
        offset = 0

        while len(all_data) < limit:
            batch_limit = min(page_size, limit - len(all_data))
            # An exact window keeps the limit; a short one is the last.
            response = await self._run(
                lambda offset=offset, batch_limit=batch_limit: window(
                    order_by(
                        self._client.table("wallet_tile_history")
                        .select("tile_id, visit_count, first_visited_at, last_visited_at")
                        .eq("wallet", wallet),
                        "visit_count.desc",
                        "tile_id",
                    ),
                    offset,
                    batch_limit,
                ).execute()
            )
            page_data = getattr(response, "data", None) or []
            all_data.extend(page_data)
            offset += len(page_data)
            if len(page_data) < batch_limit:
                break

        return all_data

    async def get_territory_stats(self, wallet: str) -> Dict[str, Any]:
        """Get territory summary stats for a wallet."""
        # Total unique tiles and total visits
        response = await self._run(
            lambda: self._client.table("wallet_tile_history")
            .select("tile_id, visit_count, first_visited_at", count="exact")
            .eq("wallet", wallet)
            .execute()
        )
        data = getattr(response, "data", None) or []
        total_tiles = response.count if hasattr(response, "count") and response.count is not None else len(data)
        total_visits = sum(row.get("visit_count", 1) for row in data)

        # Tiles discovered this week
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        week_response = await self._run(
            lambda: self._client.table("wallet_tile_history")
            .select("tile_id", count="exact")
            .eq("wallet", wallet)
            .gte("first_visited_at", week_ago)
            .execute()
        )
        tiles_this_week = week_response.count if hasattr(week_response, "count") and week_response.count is not None else len(getattr(week_response, "data", None) or [])

        # Tiles discovered this month
        month_ago = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        month_response = await self._run(
            lambda: self._client.table("wallet_tile_history")
            .select("tile_id", count="exact")
            .eq("wallet", wallet)
            .gte("first_visited_at", month_ago)
            .execute()
        )
        tiles_this_month = month_response.count if hasattr(month_response, "count") and month_response.count is not None else len(getattr(month_response, "data", None) or [])

        return {
            "total_tiles": total_tiles,
            "total_visits": total_visits,
            "tiles_this_week": tiles_this_week,
            "tiles_this_month": tiles_this_month,
        }

    async def get_heatmap_tiles(
        self,
        wallet: str,
        resolution: int = 7,
    ) -> List[Dict[str, Any]]:
        """Get aggregated heatmap data at a lower H3 resolution.

        Since H3 parent conversion requires h3 library which is not available
        server-side easily, we return all tiles and let the frontend aggregate.
        For large datasets, we limit and return the most-visited tiles.
        """
        response = await self._run(
            lambda: self._client.table("wallet_tile_history")
            .select("tile_id, visit_count")
            .eq("wallet", wallet)
            .order("visit_count", desc=True)
            .limit(5000)
            .execute()
        )
        return getattr(response, "data", None) or []
