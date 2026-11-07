"""
Leaderboard Repository

Database operations for global aggregate leaderboards (KOM count, earnings rankings).
"""

from __future__ import annotations

import logging
from typing import List, Optional, Dict, Any, TypedDict

from .base import BaseRepository

logger = logging.getLogger(__name__)


# =============================================================================
# TYPED DICTS FOR DATABASE RESPONSES
# =============================================================================


class GlobalKomEntryDict(TypedDict, total=False):
    """Typed dict for global KOM leaderboard entries."""
    rank: int
    wallet: str
    kom_count: int
    podium_count: int
    top10_count: int
    total_vaults: int
    most_recent_kom_at: Optional[str]


class GlobalEarningsEntryDict(TypedDict, total=False):
    """Typed dict for global earnings leaderboard entries."""
    rank: int
    wallet: str
    total_earnings: float
    leaderboard_earnings: float
    staking_earnings: float
    legend_earnings: float
    vaults_with_earnings: int
    last_earning_at: Optional[str]


class UserGlobalKomRankDict(TypedDict, total=False):
    """Typed dict for user's global KOM rank."""
    user_rank: int
    total_users: int
    kom_count: int
    podium_count: int
    top10_count: int
    percentile: float


class UserGlobalEarningsRankDict(TypedDict, total=False):
    """Typed dict for user's global earnings rank."""
    user_rank: int
    total_users: int
    total_earnings: float
    leaderboard_earnings: float
    staking_earnings: float
    legend_earnings: float
    percentile: float


# Valid time filter values
TIME_FILTERS = ("all_time", "this_epoch", "last_30_days")


class LeaderboardRepository(BaseRepository):
    """Repository for global aggregate leaderboard operations."""

    # =========================================================================
    # GLOBAL KOM LEADERBOARD
    # =========================================================================

    async def get_global_kom_leaderboard(
        self,
        time_filter: str = "all_time",
        limit: int = 50,
        offset: int = 0,
    ) -> List[GlobalKomEntryDict]:
        """
        Get global KOM count leaderboard.

        Users ranked by total number of top-1 positions held across all vaults.

        Args:
            time_filter: One of 'all_time', 'this_epoch', 'last_30_days'
            limit: Maximum results to return
            offset: Pagination offset

        Returns:
            List of GlobalKomEntryDict with rank, wallet, kom_count, etc.
        """
        if time_filter not in TIME_FILTERS:
            time_filter = "all_time"

        result = self.client.rpc(
            "get_global_kom_leaderboard",
            {
                "p_time_filter": time_filter,
                "p_limit": limit,
                "p_offset": offset,
            }
        ).execute()
        return result.data or []

    async def count_global_kom_leaderboard(
        self,
        time_filter: str = "all_time",
    ) -> int:
        """
        Count total users on global KOM leaderboard (for pagination).

        Args:
            time_filter: One of 'all_time', 'this_epoch', 'last_30_days'

        Returns:
            Total count of users with at least one KOM
        """
        if time_filter not in TIME_FILTERS:
            time_filter = "all_time"

        result = self.client.rpc(
            "count_global_kom_leaderboard",
            {"p_time_filter": time_filter}
        ).execute()
        return result.data if result.data else 0

    async def get_user_global_kom_rank(
        self,
        wallet: str,
        time_filter: str = "all_time",
    ) -> Optional[UserGlobalKomRankDict]:
        """
        Get user's rank on the global KOM leaderboard.

        Args:
            wallet: User's wallet address
            time_filter: One of 'all_time', 'this_epoch', 'last_30_days'

        Returns:
            UserGlobalKomRankDict with rank, total_users, kom_count, etc.
            None if user has no KOMs
        """
        if time_filter not in TIME_FILTERS:
            time_filter = "all_time"

        result = self.client.rpc(
            "get_user_global_kom_rank",
            {
                "p_wallet": wallet,
                "p_time_filter": time_filter,
            }
        ).execute()
        if result.data:
            return result.data[0] if isinstance(result.data, list) else result.data
        return None

    # =========================================================================
    # GLOBAL EARNINGS LEADERBOARD
    # =========================================================================

    async def get_global_earnings_leaderboard(
        self,
        time_filter: str = "all_time",
        limit: int = 50,
        offset: int = 0,
    ) -> List[GlobalEarningsEntryDict]:
        """
        Get global earnings leaderboard.

        Users ranked by total DUNG earned from vault distributions
        (Record Board payouts, staking earnings, Local Legend rewards).

        Args:
            time_filter: One of 'all_time', 'this_epoch', 'last_30_days'
            limit: Maximum results to return
            offset: Pagination offset

        Returns:
            List of GlobalEarningsEntryDict with rank, wallet, total_earnings, etc.
        """
        if time_filter not in TIME_FILTERS:
            time_filter = "all_time"

        result = self.client.rpc(
            "get_global_earnings_leaderboard",
            {
                "p_time_filter": time_filter,
                "p_limit": limit,
                "p_offset": offset,
            }
        ).execute()
        return result.data or []

    async def count_global_earnings_leaderboard(
        self,
        time_filter: str = "all_time",
    ) -> int:
        """
        Count total users on global earnings leaderboard (for pagination).

        Args:
            time_filter: One of 'all_time', 'this_epoch', 'last_30_days'

        Returns:
            Total count of users with vault earnings
        """
        if time_filter not in TIME_FILTERS:
            time_filter = "all_time"

        result = self.client.rpc(
            "count_global_earnings_leaderboard",
            {"p_time_filter": time_filter}
        ).execute()
        return result.data if result.data else 0

    async def get_user_global_earnings_rank(
        self,
        wallet: str,
        time_filter: str = "all_time",
    ) -> Optional[UserGlobalEarningsRankDict]:
        """
        Get user's rank on the global earnings leaderboard.

        Args:
            wallet: User's wallet address
            time_filter: One of 'all_time', 'this_epoch', 'last_30_days'

        Returns:
            UserGlobalEarningsRankDict with rank, total_users, earnings breakdown, etc.
            None if user has no vault earnings
        """
        if time_filter not in TIME_FILTERS:
            time_filter = "all_time"

        result = self.client.rpc(
            "get_user_global_earnings_rank",
            {
                "p_wallet": wallet,
                "p_time_filter": time_filter,
            }
        ).execute()
        if result.data:
            return result.data[0] if isinstance(result.data, list) else result.data
        return None
