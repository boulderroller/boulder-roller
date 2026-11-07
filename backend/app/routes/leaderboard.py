"""
Leaderboard Routes: Effort-based leaderboards for tile patterns.

These leaderboards replace segment-based competition with pattern-based rankings:
- Climb: Best climbing efforts by W/kg or VAM (route-agnostic)
- Steady: Longest/strongest aerobic blocks
- Exploration: Most new tiles discovered

Key difference from Strava: Effort-based (W/kg) rather than time-based.

NOT MOUNTED (boulderroller-v2-pvrwy, 20 Oct 2026). The climb board ranks other
riders by W/kg, and W/kg reveals body weight (weight = avg power / W/kg). Tim,
19 Oct 2026: W/kg reaches others only through the explicit share_wkg opt-in,
which defaults off. Threshold-scaled values and max HR remain owner-only. No client calls this router, so main.py leaves it out and
the code is kept. Remove W/kg from the output, or gate it on that opt-in,
before mounting it again.
"""

from fastapi import APIRouter, Depends, Query, HTTPException, Request, status
from typing import Optional

from ..dependencies import get_repository
from ..middleware.rate_limiter import rate_limit
from ..repositories import DatabaseRepository
from ..services.leaderboard_service import (
    LeaderboardService,
    LeaderboardMetric,
    LeaderboardPeriod,
    PublicLeaderboardPrivacyUnavailable,
)

router = APIRouter(prefix="/leaderboard", tags=["leaderboard"])


def get_leaderboard_service(
    repo: DatabaseRepository = Depends(get_repository),
) -> LeaderboardService:
    return LeaderboardService(repo)


# =====================================================
# CLIMB LEADERBOARDS
# =====================================================

@router.get("/climb")
@rate_limit(category="leaderboard")
async def get_climb_leaderboard(
    request: Request,
    arena_id: Optional[str] = Query(None, description="Arena UUID (null = World Arena)"),
    metric: str = Query("w_per_kg", description="Ranking metric: w_per_kg, vam, vert_m"),
    period: str = Query("week", description="Time period: today, week, month, all_time"),
    limit: int = Query(50, le=100, description="Max entries"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    service: LeaderboardService = Depends(get_leaderboard_service),
):
    """
    Get climb leaderboard for an arena.

    Rankings based on effort (W/kg, VAM) rather than absolute speed.
    Route-agnostic: any path through the Arena counts.
    """
    try:
        metric_enum = LeaderboardMetric(metric)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid metric: {metric}. Valid options: w_per_kg, vam, vert_m"
        )

    try:
        period_enum = LeaderboardPeriod(period)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid period: {period}. Valid options: today, week, month, all_time"
        )

    try:
        result = await service.get_climb_leaderboard(
            arena_id=arena_id,
            metric=metric_enum,
            period=period_enum,
            limit=limit,
            offset=offset,
        )
    except PublicLeaderboardPrivacyUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Public leaderboard privacy projection is temporarily unavailable",
        ) from exc

    return result.to_dict()


# =====================================================
# STEADY LEADERBOARDS
# =====================================================

@router.get("/steady")
@rate_limit(category="leaderboard")
async def get_steady_leaderboard(
    request: Request,
    metric: str = Query("duration_s", description="Ranking metric: duration_s, avg_power_w, intensity_index"),
    period: str = Query("week", description="Time period"),
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
    service: LeaderboardService = Depends(get_leaderboard_service),
):
    """
    Get steady effort leaderboard (global).

    Rankings based on sustained aerobic work in Z2-Z3 intensity band.
    """
    try:
        metric_enum = LeaderboardMetric(metric)
    except ValueError:
        metric_enum = LeaderboardMetric.DURATION

    try:
        period_enum = LeaderboardPeriod(period)
    except ValueError:
        period_enum = LeaderboardPeriod.WEEK

    try:
        result = await service.get_steady_leaderboard(
            metric=metric_enum,
            period=period_enum,
            limit=limit,
            offset=offset,
        )
    except PublicLeaderboardPrivacyUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Public leaderboard privacy projection is temporarily unavailable",
        ) from exc

    return result.to_dict()


# =====================================================
# EXPLORATION LEADERBOARDS
# =====================================================

@router.get("/exploration")
@rate_limit(category="leaderboard")
async def get_exploration_leaderboard(
    request: Request,
    metric: str = Query("new_tiles_wallet", description="Ranking metric: new_tiles_wallet, total_tiles"),
    period: str = Query("week", description="Time period"),
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
    service: LeaderboardService = Depends(get_leaderboard_service),
):
    """
    Get exploration leaderboard (global).

    Rankings based on new tile discovery and adventure riding.
    """
    try:
        metric_enum = LeaderboardMetric(metric)
    except ValueError:
        metric_enum = LeaderboardMetric.NEW_TILES

    try:
        period_enum = LeaderboardPeriod(period)
    except ValueError:
        period_enum = LeaderboardPeriod.WEEK

    try:
        result = await service.get_exploration_leaderboard(
            metric=metric_enum,
            period=period_enum,
            limit=limit,
            offset=offset,
        )
    except PublicLeaderboardPrivacyUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Public leaderboard privacy projection is temporarily unavailable",
        ) from exc

    return result.to_dict()


# =====================================================
# ARENA INFO (for leaderboard context)
# =====================================================

@router.get("/arenas")
@rate_limit(category="leaderboard")
async def list_arenas(
    request: Request,
    active_only: bool = Query(True, description="Only return active arenas"),
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    List available arenas for leaderboard filtering.
    """
    query = repo._client.table("arenas").select("id, name, description, is_active")

    if active_only:
        query = query.eq("is_active", True)

    response = await repo._run(lambda: query.execute())
    data = getattr(response, "data", None) or []

    return {
        "arenas": data,
        "count": len(data),
    }

