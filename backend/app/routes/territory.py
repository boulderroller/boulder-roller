"""
Territory API Routes

Map territory endpoints: user tiles, stats, and heatmap data.
"""

import logging

from fastapi import APIRouter, Depends, Query

from ..dependencies import AuthenticatedUser, get_current_user, get_territory_repository
from ..repositories.territory import TerritoryRepository

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/tiles")
async def get_territory_tiles(
    limit: int = Query(10000, ge=1, le=50000),
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: TerritoryRepository = Depends(get_territory_repository),
):
    """Get user's tile history for map territory visualization."""
    tiles = await repo.get_user_tiles(current_user.wallet, limit=limit)
    return {
        "tiles": tiles,
        "count": len(tiles),
    }


@router.get("/stats")
async def get_territory_stats(
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: TerritoryRepository = Depends(get_territory_repository),
):
    """Get territory summary statistics."""
    stats = await repo.get_territory_stats(current_user.wallet)
    return stats


@router.get("/heatmap")
async def get_territory_heatmap(
    resolution: int = Query(7, ge=1, le=15),
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: TerritoryRepository = Depends(get_territory_repository),
):
    """Get aggregated heatmap data for zoomed-out territory view."""
    tiles = await repo.get_heatmap_tiles(
        current_user.wallet,
        resolution=resolution,
    )
    return {
        "tiles": tiles,
        "resolution": resolution,
        "count": len(tiles),
    }
