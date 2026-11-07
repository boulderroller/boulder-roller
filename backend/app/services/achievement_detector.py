"""
Achievement Detector: Identifies achievements earned from a ride.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from uuid import UUID

from ..repositories.achievement import AchievementRepository
from .ride_metrics import RideMetrics

if TYPE_CHECKING:
    from .pattern_engine import PatternResults


@dataclass
class Achievement:
    achievement_type: str
    title: str
    description: str
    value: Optional[float]
    rank: Optional[int]
    pattern_type: Optional[str]  # CLIMB, STEADY, EXPLORATION
    metadata: Dict[str, Any]


class AchievementDetector:
    """Detects and awards achievements based on ride data."""

    DISTANCE_MILESTONES = [100, 500, 1000, 2500, 5000, 10000]
    ELEVATION_MILESTONES = [1000, 5000, 10000, 25000, 50000, 100000]

    async def detect_achievements(
        self,
        user_id: UUID,
        ride_id: UUID,
        metrics: RideMetrics,
        pattern_results: Optional["PatternResults"],
        user_repo,
        achievement_repo: Optional[AchievementRepository] = None,
    ) -> List[Achievement]:
        achievements: List[Achievement] = []

        # Pattern-based achievements
        if pattern_results:
            # Significant climb achievements
            for climb in pattern_results.climb_patterns:
                if climb.vert_m >= 500:
                    achievements.append(Achievement(
                        achievement_type="big_climb",
                        title=f"Big Climb: {int(climb.vert_m)}m",
                        description=f"Conquered a {int(climb.vert_m)}m climb!",
                        value=float(climb.vert_m),
                        rank=None,
                        pattern_type="CLIMB",
                        metadata={"vert_m": climb.vert_m, "time_s": climb.time_s},
                    ))
                if climb.w_per_kg and climb.w_per_kg >= 4.0:
                    achievements.append(Achievement(
                        achievement_type="high_power_climb",
                        title=f"Power Climber: {climb.w_per_kg:.1f} W/kg",
                        description=f"Sustained {climb.w_per_kg:.1f} W/kg on a climb!",
                        value=float(climb.w_per_kg),
                        rank=None,
                        pattern_type="CLIMB",
                        metadata={"w_per_kg": climb.w_per_kg, "vert_m": climb.vert_m},
                    ))

            # Endurance achievements
            if pattern_results.steady_pattern:
                steady = pattern_results.steady_pattern
                if steady.duration_s >= 3600:  # 1 hour
                    achievements.append(Achievement(
                        achievement_type="endurance_hour",
                        title="Hour of Power",
                        description=f"Sustained steady effort for {steady.duration_s // 60} minutes!",
                        value=float(steady.duration_s),
                        rank=None,
                        pattern_type="STEADY",
                        metadata={"duration_s": steady.duration_s, "avg_power_w": steady.avg_power_w},
                    ))

            # Exploration achievements
            if pattern_results.exploration_pattern:
                explore = pattern_results.exploration_pattern
                if explore.new_tiles_wallet >= 50:
                    achievements.append(Achievement(
                        achievement_type="explorer",
                        title=f"Explorer: {explore.new_tiles_wallet} New Areas",
                        description=f"Discovered {explore.new_tiles_wallet} new areas!",
                        value=float(explore.new_tiles_wallet),
                        rank=None,
                        pattern_type="EXPLORATION",
                        metadata={"new_tiles": explore.new_tiles_wallet},
                    ))

        power_achievement = await self._check_power_record(user_id, metrics, user_repo)
        if power_achievement:
            achievements.append(power_achievement)

        distance_achievement = await self._check_distance_milestone(user_id, metrics, user_repo)
        if distance_achievement:
            achievements.append(distance_achievement)

        elevation_achievement = await self._check_elevation_milestone(user_id, metrics, user_repo)
        if elevation_achievement:
            achievements.append(elevation_achievement)

        if await self._is_first_ride(user_id, user_repo):
            achievements.append(
                Achievement(
                    achievement_type="first_ride",
                    title="First Ride!",
                    description="Welcome to Boulder Rollers! You've completed your first ride.",
                    value=None,
                    rank=None,
                    pattern_type=None,
                    metadata={},
                )
            )

        streak_achievement = await self._check_streak(user_id, user_repo)
        if streak_achievement:
            achievements.append(streak_achievement)

        for achievement in achievements:
            await self._store_achievement(user_id, ride_id, achievement, achievement_repo)

        return achievements

    # Note: Segment-based KOM/PR achievements have been replaced by pattern-based achievements
    # The leaderboard system now uses effort-based (W/kg) rankings instead of time-based

    async def _check_power_record(self, user_id: UUID, metrics: RideMetrics, user_repo) -> Optional[Achievement]:
        if not metrics.max_power_w:
            return None

        prev_max = await user_repo.get_user_max_power(user_id)
        if prev_max and metrics.max_power_w <= prev_max:
            return None

        return Achievement(
            achievement_type="power_record",
            title="New Power Record!",
            description=f"You hit {metrics.max_power_w}W - your highest ever!",
            value=float(metrics.max_power_w),
            rank=None,
            pattern_type=None,
            metadata={"previous_max": prev_max},
        )

    async def _check_distance_milestone(self, user_id: UUID, metrics: RideMetrics, user_repo) -> Optional[Achievement]:
        prev_total = await user_repo.get_user_total_distance(user_id)
        new_total = prev_total + (metrics.distance_m or 0) / 1000.0

        for milestone in self.DISTANCE_MILESTONES:
            if prev_total < milestone <= new_total:
                return Achievement(
                    achievement_type="distance_milestone",
                    title=f"{milestone}km Club!",
                    description=f"You've ridden a total of {milestone}km!",
                    value=float(milestone),
                    rank=None,
                    pattern_type=None,
                    metadata={"total_km": new_total},
                )
        return None

    async def _check_elevation_milestone(self, user_id: UUID, metrics: RideMetrics, user_repo) -> Optional[Achievement]:
        prev_total = await user_repo.get_user_total_elevation(user_id)
        new_total = prev_total + (metrics.elevation_gain_m or 0)

        for milestone in self.ELEVATION_MILESTONES:
            if prev_total < milestone <= new_total:
                return Achievement(
                    achievement_type="elevation_milestone",
                    title=f"{milestone}m Climber!",
                    description=f"You've climbed a total of {milestone}m!",
                    value=float(milestone),
                    rank=None,
                    pattern_type=None,
                    metadata={"total_m": new_total},
                )
        return None

    async def _is_first_ride(self, user_id: UUID, user_repo) -> bool:
        return await user_repo.get_user_ride_count(user_id) == 1

    async def _check_streak(self, user_id: UUID, user_repo) -> Optional[Achievement]:
        streak = await user_repo.get_user_riding_streak(user_id)
        milestones = [7, 14, 30, 60, 100, 365]
        for days in milestones:
            if streak == days:
                return Achievement(
                    achievement_type="streak",
                    title=f"{days}-Day Streak!",
                    description=f"You've ridden {days} days in a row!",
                    value=float(days),
                    rank=None,
                    pattern_type=None,
                    metadata={"streak_days": streak},
                )
        return None

    async def _store_achievement(
        self,
        user_id: UUID,
        ride_id: UUID,
        achievement: Achievement,
        achievement_repo: AchievementRepository,
    ) -> None:
        await achievement_repo.create_achievement(
            user_id=user_id,
            ride_id=ride_id,
            achievement_type=achievement.achievement_type,
            title=achievement.title,
            description=achievement.description,
            value=achievement.value,
            rank=achievement.rank,
            pattern_type=achievement.pattern_type,
            metadata=achievement.metadata,
        )
