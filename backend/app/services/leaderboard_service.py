"""
LeaderboardService: Effort-based leaderboards for tile patterns.

This service provides rankings based on detected patterns, NOT segments.
Key differentiators from Strava:
- Effort-based (W/kg, VAM) rather than time-based
- Route-agnostic: any path through an Arena counts
- Free to compete: no CAL required to appear on leaderboards

Leaderboard Types:
- Climb: Best climbing efforts by W/kg or VAM
- Steady: Longest/strongest aerobic blocks
- Exploration: Most new tiles discovered
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional

from ..repositories import DatabaseRepository
from ..utils.polyline import decode_gps_track
from .public_record_board_privacy import route_span_is_public
from .ride_privacy import (
    PrivacySettingsUnavailable,
    RidePrivacyPolicy,
    project_route_points,
)

logger = logging.getLogger(__name__)

_LEADERBOARD_CANDIDATE_LIMIT = int(os.getenv("LEADERBOARD_CANDIDATE_LIMIT", "500"))


class PublicLeaderboardPrivacyUnavailable(RuntimeError):
    """The public leaderboard cannot be projected without risking private data."""


def _ride_allows_public_leaderboard(row: Optional[dict[str, Any]]) -> bool:
    if not row:
        return False
    return (
        row.get("visibility") == "public"
        and row.get("hide_from_leaderboards") is False
        and str(row.get("moderation_state") or "").lower() == "visible"
    )


def _profile_allows_public_leaderboard(row: Optional[dict[str, Any]]) -> bool:
    if not row:
        return False
    return (
        row.get("is_public") is True
        and str(row.get("moderation_state") or "").lower() == "visible"
    )


def _privacy_rows(response: Any) -> list[dict[str, Any]]:
    data = getattr(response, "data", None)
    if not isinstance(data, list):
        raise PublicLeaderboardPrivacyUnavailable(
            "public leaderboard privacy projection unavailable"
        )
    return [dict(row) for row in data if isinstance(row, Mapping)]


class LeaderboardMetric(str, Enum):
    """Metrics available for leaderboard ranking."""
    # Climb metrics
    W_PER_KG = "w_per_kg"  # Watts per kilogram (primary effort metric)
    VAM = "vam"  # Vertical Ascent Meters per hour
    VERT = "vert_m"  # Total vertical gain

    # Steady metrics
    DURATION = "duration_s"  # Longest steady effort
    AVG_POWER = "avg_power_w"  # Highest average power
    INTENSITY = "intensity_index"  # Highest intensity factor

    # Exploration metrics
    NEW_TILES = "new_tiles_wallet"  # Most new tiles discovered
    TOTAL_TILES = "total_tiles"  # Most tiles covered


class LeaderboardPeriod(str, Enum):
    """Time periods for leaderboard filtering."""
    TODAY = "today"
    WEEK = "week"
    MONTH = "month"
    ALL_TIME = "all_time"


@dataclass
class LeaderboardEntry:
    """A single entry on a leaderboard."""
    rank: int
    wallet: str
    username: Optional[str]
    avatar_url: Optional[str]
    activity_id: str
    pattern_id: str
    value: float  # The metric value (W/kg, vert_m, etc.)
    secondary_value: Optional[float] = None  # e.g., time_s for climb
    created_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rank": self.rank,
            "wallet": self.wallet,
            "username": self.username,
            "avatar_url": self.avatar_url,
            "activity_id": self.activity_id,
            "pattern_id": self.pattern_id,
            "value": round(self.value, 2) if self.value else None,
            "secondary_value": round(self.secondary_value, 2) if self.secondary_value else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass
class LeaderboardResponse:
    """Response containing leaderboard data."""
    leaderboard_type: str  # "climb", "steady", "exploration"
    metric: str
    period: str
    arena_id: Optional[str]
    arena_name: Optional[str]
    entries: List[LeaderboardEntry]
    total_count: int
    updated_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        return {
            "leaderboard_type": self.leaderboard_type,
            "metric": self.metric,
            "period": self.period,
            "arena_id": self.arena_id,
            "arena_name": self.arena_name,
            "entries": [e.to_dict() for e in self.entries],
            "total_count": self.total_count,
            "updated_at": self.updated_at.isoformat(),
        }


class LeaderboardService:
    """
    Service for querying effort-based leaderboards.

    Leaderboards are derived from detected patterns, providing
    route-agnostic competition based on effort rather than speed.
    """

    # World Arena UUID (seeded in migration)
    WORLD_ARENA_ID = "00000000-0000-0000-0000-000000000001"

    def __init__(self, repo: DatabaseRepository):
        self.repo = repo

    async def get_climb_leaderboard(
        self,
        arena_id: Optional[str] = None,
        metric: LeaderboardMetric = LeaderboardMetric.W_PER_KG,
        period: LeaderboardPeriod = LeaderboardPeriod.WEEK,
        limit: int = 50,
        offset: int = 0,
    ) -> LeaderboardResponse:
        """
        Get climb leaderboard for an arena.

        Args:
            arena_id: Arena UUID (None = World Arena)
            metric: Ranking metric (w_per_kg, vam, vert_m)
            period: Time period filter
            limit: Max entries to return
            offset: Pagination offset

        Returns:
            LeaderboardResponse with ranked entries
        """
        # Calculate date filter
        date_filter = self._get_date_filter(period)

        # Build query based on metric
        order_column = metric.value
        if metric == LeaderboardMetric.VAM:
            # VAM needs to be calculated: (vert_m / time_s) * 3600
            order_column = "vam_calculated"

        # Query patterns
        entries = await self._query_climb_patterns(
            arena_id=arena_id,
            order_by=order_column,
            date_filter=date_filter,
            limit=limit,
            offset=offset,
        )

        # Get total count for pagination
        total_count = await self._count_climb_patterns(
            arena_id=arena_id,
            order_by=order_column,
            date_filter=date_filter,
        )

        # Get arena name
        arena_name = "World Arena"
        if arena_id and arena_id != self.WORLD_ARENA_ID:
            arena = await self._get_arena(arena_id)
            arena_name = arena.get("name", "Unknown Arena") if arena else "Unknown Arena"

        response = LeaderboardResponse(
            leaderboard_type="climb",
            metric=metric.value,
            period=period.value,
            arena_id=arena_id,
            arena_name=arena_name,
            entries=entries,
            total_count=total_count,
            updated_at=datetime.now(timezone.utc),
        )
        return response

    async def get_steady_leaderboard(
        self,
        metric: LeaderboardMetric = LeaderboardMetric.DURATION,
        period: LeaderboardPeriod = LeaderboardPeriod.WEEK,
        limit: int = 50,
        offset: int = 0,
    ) -> LeaderboardResponse:
        """
        Get steady effort leaderboard (global).

        Args:
            metric: Ranking metric (duration_s, avg_power_w, intensity_index)
            period: Time period filter
            limit: Max entries to return
            offset: Pagination offset

        Returns:
            LeaderboardResponse with ranked entries
        """
        date_filter = self._get_date_filter(period)

        entries = await self._query_steady_patterns(
            order_by=metric.value,
            date_filter=date_filter,
            limit=limit,
            offset=offset,
        )

        # Get total count for pagination
        total_count = await self._count_steady_patterns(
            order_by=metric.value,
            date_filter=date_filter,
        )

        response = LeaderboardResponse(
            leaderboard_type="steady",
            metric=metric.value,
            period=period.value,
            arena_id=None,
            arena_name="Global",
            entries=entries,
            total_count=total_count,
            updated_at=datetime.now(timezone.utc),
        )
        return response

    async def get_exploration_leaderboard(
        self,
        metric: LeaderboardMetric = LeaderboardMetric.NEW_TILES,
        period: LeaderboardPeriod = LeaderboardPeriod.WEEK,
        limit: int = 50,
        offset: int = 0,
    ) -> LeaderboardResponse:
        """
        Get exploration leaderboard (global).

        Args:
            metric: Ranking metric (new_tiles_wallet, total_tiles)
            period: Time period filter
            limit: Max entries to return
            offset: Pagination offset

        Returns:
            LeaderboardResponse with ranked entries
        """
        date_filter = self._get_date_filter(period)

        entries = await self._query_exploration_patterns(
            order_by=metric.value,
            date_filter=date_filter,
            limit=limit,
            offset=offset,
        )

        # Get total count for pagination
        total_count = await self._count_exploration_patterns(
            date_filter=date_filter,
        )

        response = LeaderboardResponse(
            leaderboard_type="exploration",
            metric=metric.value,
            period=period.value,
            arena_id=None,
            arena_name="Global",
            entries=entries,
            total_count=total_count,
            updated_at=datetime.now(timezone.utc),
        )
        return response

    async def get_user_rankings(
        self,
        wallet: str,
        period: LeaderboardPeriod = LeaderboardPeriod.WEEK,
    ) -> Dict[str, Any]:
        """
        Get a user's current rankings across all leaderboards.

        Returns summary of user's best positions.
        """
        # Get user's best patterns in each category
        date_filter = self._get_date_filter(period)

        climb_rank = await self._get_user_rank_climb(wallet, date_filter)
        steady_rank = await self._get_user_rank_steady(wallet, date_filter)
        exploration_rank = await self._get_user_rank_exploration(wallet, date_filter)

        return {
            "wallet": wallet,
            "period": period.value,
            "rankings": {
                "climb": climb_rank,
                "steady": steady_rank,
                "exploration": exploration_rank,
            },
        }

    def _get_date_filter(self, period: LeaderboardPeriod) -> Optional[datetime]:
        """Convert period to datetime filter."""
        now = datetime.now(timezone.utc)
        if period == LeaderboardPeriod.TODAY:
            return now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == LeaderboardPeriod.WEEK:
            return now - timedelta(days=7)
        elif period == LeaderboardPeriod.MONTH:
            return now - timedelta(days=30)
        else:  # ALL_TIME
            return None

    async def _query_climb_patterns(
        self,
        arena_id: Optional[str],
        order_by: str,
        date_filter: Optional[datetime],
        limit: int,
        offset: int,
    ) -> List[LeaderboardEntry]:
        """Query climb patterns from database."""
        # Build query
        query = self.repo._client.table("patterns_climb").select(
            "id, activity_id, wallet, vert_m, time_s, w_per_kg, avg_power_w, "
            "start_offset_s, end_offset_s, created_at"
        )

        # Filter by arena
        if arena_id:
            query = query.eq("arena_id", arena_id)

        # Filter by date
        if date_filter:
            query = query.gte("created_at", date_filter.isoformat())

        # Filter out null values for the metric
        if order_by == "w_per_kg":
            query = query.not_.is_("w_per_kg", "null")
        elif order_by == "vam_calculated":
            # VAM requires vert and time
            query = query.gt("time_s", 0)

        # Order and fetch bounded candidates. Eligibility depends on ride and
        # profile visibility, so pagination happens after filtering.
        if order_by == "vam_calculated":
            # Can't order by calculated field in Supabase, fetch all and sort
            query = query.limit(_LEADERBOARD_CANDIDATE_LIMIT)
        else:
            query = query.order(order_by, desc=True).limit(_LEADERBOARD_CANDIDATE_LIMIT)

        response = await self.repo._run(lambda: query.execute())
        data = _privacy_rows(response)

        # Calculate VAM if needed and sort
        if order_by == "vam_calculated":
            for row in data:
                if row.get("time_s", 0) > 0:
                    row["vam_calculated"] = (row["vert_m"] / row["time_s"]) * 3600
                else:
                    row["vam_calculated"] = 0
            data.sort(key=lambda x: x.get("vam_calculated", 0), reverse=True)
            order_by_value = "vam_calculated"
        else:
            order_by_value = order_by

        data = await self._filter_public_leaderboard_rows(
            data,
            require_visible_span=True,
        )
        data = data[offset:offset + limit]

        # Convert to LeaderboardEntry
        entries = []
        for i, row in enumerate(data):
            # Get user info
            user_info = await self._get_user_info(row["wallet"])

            value = row.get(order_by_value, 0) or 0
            entries.append(LeaderboardEntry(
                rank=offset + i + 1,
                wallet=row["wallet"],
                username=user_info.get("username"),
                avatar_url=user_info.get("avatar_url"),
                activity_id=row["activity_id"],
                pattern_id=row["id"],
                value=value,
                secondary_value=row.get("time_s"),
                created_at=datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")) if row.get("created_at") else None,
            ))

        return entries

    async def _query_steady_patterns(
        self,
        order_by: str,
        date_filter: Optional[datetime],
        limit: int,
        offset: int,
    ) -> List[LeaderboardEntry]:
        """Query steady patterns from database."""
        query = self.repo._client.table("patterns_steady").select(
            "id, activity_id, wallet, duration_s, avg_power_w, intensity_index, created_at"
        )

        if date_filter:
            query = query.gte("created_at", date_filter.isoformat())

        # Filter out null values
        if order_by in ["avg_power_w", "intensity_index"]:
            query = query.not_.is_(order_by, "null")

        query = query.order(order_by, desc=True).limit(_LEADERBOARD_CANDIDATE_LIMIT)

        response = await self.repo._run(lambda: query.execute())
        data = _privacy_rows(response)

        data = await self._filter_public_leaderboard_rows(data)
        data = data[offset:offset + limit]

        entries = []
        for i, row in enumerate(data):
            user_info = await self._get_user_info(row["wallet"])

            entries.append(LeaderboardEntry(
                rank=offset + i + 1,
                wallet=row["wallet"],
                username=user_info.get("username"),
                avatar_url=user_info.get("avatar_url"),
                activity_id=row["activity_id"],
                pattern_id=row["id"],
                value=row.get(order_by, 0) or 0,
                secondary_value=row.get("avg_power_w") if order_by != "avg_power_w" else row.get("duration_s"),
                created_at=datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")) if row.get("created_at") else None,
            ))

        return entries

    async def _query_exploration_patterns(
        self,
        order_by: str,
        date_filter: Optional[datetime],
        limit: int,
        offset: int,
    ) -> List[LeaderboardEntry]:
        """Query exploration patterns from database."""
        query = self.repo._client.table("patterns_exploration").select(
            "id, activity_id, wallet, new_tiles_wallet, total_tiles, night_minutes, created_at"
        )

        if date_filter:
            query = query.gte("created_at", date_filter.isoformat())

        query = query.order(order_by, desc=True).limit(_LEADERBOARD_CANDIDATE_LIMIT)

        response = await self.repo._run(lambda: query.execute())
        data = _privacy_rows(response)

        data = await self._filter_public_leaderboard_rows(data)
        data = data[offset:offset + limit]

        entries = []
        for i, row in enumerate(data):
            user_info = await self._get_user_info(row["wallet"])

            entries.append(LeaderboardEntry(
                rank=offset + i + 1,
                wallet=row["wallet"],
                username=user_info.get("username"),
                avatar_url=user_info.get("avatar_url"),
                activity_id=row["activity_id"],
                pattern_id=row["id"],
                value=row.get(order_by, 0) or 0,
                secondary_value=row.get("total_tiles") if order_by != "total_tiles" else row.get("new_tiles_wallet"),
                created_at=datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")) if row.get("created_at") else None,
            ))

        return entries

    async def _count_climb_patterns(
        self,
        arena_id: Optional[str],
        order_by: str,
        date_filter: Optional[datetime],
    ) -> int:
        """Count climb patterns matching the filter criteria."""
        query = self.repo._client.table("patterns_climb").select(
            "id, activity_id, wallet, start_offset_s, end_offset_s"
        )

        if arena_id:
            query = query.eq("arena_id", arena_id)

        if date_filter:
            query = query.gte("created_at", date_filter.isoformat())

        if order_by == "w_per_kg":
            query = query.not_.is_("w_per_kg", "null")
        elif order_by == "vam_calculated":
            query = query.gt("time_s", 0)

        query = query.limit(_LEADERBOARD_CANDIDATE_LIMIT)
        response = await self.repo._run(lambda: query.execute())
        data = await self._filter_public_leaderboard_rows(
            _privacy_rows(response),
            require_visible_span=True,
        )
        return len(data)

    async def _count_steady_patterns(
        self,
        order_by: str,
        date_filter: Optional[datetime],
    ) -> int:
        """Count steady patterns matching the filter criteria."""
        query = self.repo._client.table("patterns_steady").select("id, activity_id, wallet")

        if date_filter:
            query = query.gte("created_at", date_filter.isoformat())

        if order_by in ["avg_power_w", "intensity_index"]:
            query = query.not_.is_(order_by, "null")

        query = query.limit(_LEADERBOARD_CANDIDATE_LIMIT)
        response = await self.repo._run(lambda: query.execute())
        data = await self._filter_public_leaderboard_rows(_privacy_rows(response))
        return len(data)

    async def _count_exploration_patterns(
        self,
        date_filter: Optional[datetime],
    ) -> int:
        """Count exploration patterns matching the filter criteria."""
        query = self.repo._client.table("patterns_exploration").select("id, activity_id, wallet")

        if date_filter:
            query = query.gte("created_at", date_filter.isoformat())

        query = query.limit(_LEADERBOARD_CANDIDATE_LIMIT)
        response = await self.repo._run(lambda: query.execute())
        data = await self._filter_public_leaderboard_rows(_privacy_rows(response))
        return len(data)

    async def _filter_public_leaderboard_rows(
        self,
        rows: List[Dict[str, Any]],
        *,
        require_visible_span: bool = False,
    ) -> List[Dict[str, Any]]:
        """Project public entries from complete ride, profile, and map privacy state."""
        if not rows:
            return []

        activity_ids = sorted({
            str(row.get("activity_id"))
            for row in rows
            if row.get("activity_id")
        })
        try:
            rides_by_id: dict[str, dict[str, Any]] = {}
            if activity_ids:
                response = await self.repo._run(
                    lambda: self.repo._client.table("rides")
                    .select(
                        "id,user_id,visibility,map_visibility,map_hide_start_m,"
                        "map_hide_end_m,hide_from_leaderboards,moderation_state,gps_track"
                    )
                    .in_("id", activity_ids)
                    .execute()
                )
                rides_by_id = {
                    str(row.get("id")): row
                    for row in _privacy_rows(response)
                    if row.get("id")
                }

            user_ids = sorted({
                str(ride.get("user_id"))
                for ride in rides_by_id.values()
                if ride.get("user_id")
            })
            users_by_id: dict[str, dict[str, Any]] = {}
            if user_ids:
                response = await self.repo._run(
                    lambda: self.repo._client.table("users")
                    .select("id,wallet,is_public,moderation_state")
                    .in_("id", user_ids)
                    .execute()
                )
                users_by_id = {
                    str(row.get("id")): row
                    for row in _privacy_rows(response)
                    if row.get("id")
                }

            zones_by_user: dict[str, list[dict[str, Any]]] = {
                user_id: [] for user_id in user_ids
            }
            if require_visible_span and user_ids:
                response = await self.repo._run(
                    lambda: self.repo._client.table("privacy_zones")
                    .select("user_id,latitude,longitude,radius_m")
                    .in_("user_id", user_ids)
                    .execute()
                )
                for zone in _privacy_rows(response):
                    user_id = str(zone.get("user_id") or "")
                    if user_id in zones_by_user:
                        zones_by_user[user_id].append(zone)
        except PublicLeaderboardPrivacyUnavailable:
            raise
        except Exception as exc:
            raise PublicLeaderboardPrivacyUnavailable(
                "public leaderboard privacy projection unavailable"
            ) from exc

        public_rows: list[dict[str, Any]] = []
        for row in rows:
            ride = rides_by_id.get(str(row.get("activity_id")))
            if not _ride_allows_public_leaderboard(ride):
                continue
            user_id = str((ride or {}).get("user_id") or "")
            profile = users_by_id.get(user_id)
            if not _profile_allows_public_leaderboard(profile):
                continue
            if str((profile or {}).get("wallet") or "") != str(row.get("wallet") or ""):
                continue

            try:
                policy = RidePrivacyPolicy.from_values(
                    visibility=(ride or {}).get("visibility"),
                    map_visibility=(ride or {}).get("map_visibility"),
                    map_hide_start_m=(ride or {}).get("map_hide_start_m"),
                    map_hide_end_m=(ride or {}).get("map_hide_end_m"),
                )
            except PrivacySettingsUnavailable:
                continue

            if require_visible_span:
                try:
                    points = decode_gps_track((ride or {}).get("gps_track"))
                    if not points:
                        continue
                    projected_points = project_route_points(
                        points,
                        policy,
                        privacy_zones=zones_by_user.get(user_id),
                    )
                except (
                    PrivacySettingsUnavailable,
                    IndexError,
                    KeyError,
                    OverflowError,
                    TypeError,
                    ValueError,
                ):
                    continue
                if not route_span_is_public(
                    projected_points,
                    start_offset_s=row.get("start_offset_s"),
                    end_offset_s=row.get("end_offset_s"),
                ):
                    continue
            public_rows.append(row)
        return public_rows

    async def _get_arena(self, arena_id: str) -> Optional[Dict[str, Any]]:
        """Get arena details."""
        response = await self.repo._run(
            lambda: self.repo._client.table("arenas")
            .select("id, name, description")
            .eq("id", arena_id)
            .limit(1)
            .execute()
        )
        data = _privacy_rows(response)
        return data[0] if data else None

    async def _get_user_info(self, wallet: str) -> Dict[str, Any]:
        """Get user display info for a wallet."""
        response = await self.repo._run(
            lambda: self.repo._client.table("users")
            .select("username, is_public, moderation_state")
            .eq("wallet", wallet)
            .limit(1)
            .execute()
        )
        data = getattr(response, "data", None) or []
        if data and _profile_allows_public_leaderboard(data[0]):
            return {"username": data[0].get("username"), "avatar_url": None}
        return {"username": None, "avatar_url": None}

    async def _get_user_rank_climb(
        self,
        wallet: str,
        date_filter: Optional[datetime],
    ) -> Optional[Dict[str, Any]]:
        """Get user's best climb rank."""
        # Get user's best W/kg pattern
        query = self.repo._client.table("patterns_climb").select(
            "id, vert_m, time_s, w_per_kg"
        ).eq("wallet", wallet).not_.is_("w_per_kg", "null")

        if date_filter:
            query = query.gte("created_at", date_filter.isoformat())

        query = query.order("w_per_kg", desc=True).limit(1)

        response = await self.repo._run(lambda: query.execute())
        data = getattr(response, "data", None) or []

        if not data:
            return None

        best = data[0]
        # Count how many have higher W/kg
        count_query = self.repo._client.table("patterns_climb").select(
            "id", count="exact"
        ).gt("w_per_kg", best["w_per_kg"])

        if date_filter:
            count_query = count_query.gte("created_at", date_filter.isoformat())

        count_response = await self.repo._run(lambda: count_query.execute())
        higher_count = getattr(count_response, "count", 0) or 0

        return {
            "rank": higher_count + 1,
            "value": best["w_per_kg"],
            "metric": "w_per_kg",
        }

    async def _get_user_rank_steady(
        self,
        wallet: str,
        date_filter: Optional[datetime],
    ) -> Optional[Dict[str, Any]]:
        """Get user's best steady rank."""
        query = self.repo._client.table("patterns_steady").select(
            "id, duration_s"
        ).eq("wallet", wallet)

        if date_filter:
            query = query.gte("created_at", date_filter.isoformat())

        query = query.order("duration_s", desc=True).limit(1)

        response = await self.repo._run(lambda: query.execute())
        data = getattr(response, "data", None) or []

        if not data:
            return None

        best = data[0]
        count_query = self.repo._client.table("patterns_steady").select(
            "id", count="exact"
        ).gt("duration_s", best["duration_s"])

        if date_filter:
            count_query = count_query.gte("created_at", date_filter.isoformat())

        count_response = await self.repo._run(lambda: count_query.execute())
        higher_count = getattr(count_response, "count", 0) or 0

        return {
            "rank": higher_count + 1,
            "value": best["duration_s"],
            "metric": "duration_s",
        }

    async def _get_user_rank_exploration(
        self,
        wallet: str,
        date_filter: Optional[datetime],
    ) -> Optional[Dict[str, Any]]:
        """Get user's best exploration rank."""
        query = self.repo._client.table("patterns_exploration").select(
            "id, new_tiles_wallet"
        ).eq("wallet", wallet)

        if date_filter:
            query = query.gte("created_at", date_filter.isoformat())

        query = query.order("new_tiles_wallet", desc=True).limit(1)

        response = await self.repo._run(lambda: query.execute())
        data = getattr(response, "data", None) or []

        if not data:
            return None

        best = data[0]
        count_query = self.repo._client.table("patterns_exploration").select(
            "id", count="exact"
        ).gt("new_tiles_wallet", best["new_tiles_wallet"])

        if date_filter:
            count_query = count_query.gte("created_at", date_filter.isoformat())

        count_response = await self.repo._run(lambda: count_query.execute())
        higher_count = getattr(count_response, "count", 0) or 0

        return {
            "rank": higher_count + 1,
            "value": best["new_tiles_wallet"],
            "metric": "new_tiles_wallet",
        }
