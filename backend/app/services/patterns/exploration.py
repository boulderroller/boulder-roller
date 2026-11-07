"""
ExplorationPattern detection for Boulder Rollers tile-based attestations.

This module detects when riders explore new territory or ride at unusual times,
rewarding discovery and adventure over pure performance.

Pattern Detection Criteria:
- New tiles to wallet: 20%+ of ride tiles are new to this rider
- Global discovery: 10+ tiles never seen by any rider
- Night riding: Significant time during unusual hours (22:00-04:00)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import List, Optional, Set


@dataclass
class ExplorationPattern:
    """
    Represents a detected exploration pattern in a ride.

    Captures "I went somewhere new or unusual" - rewarding riders for:
    - Discovering new routes and territories
    - Riding at unusual times (night riding)
    - Venturing into globally unexplored areas
    """

    activity_id: str
    new_tiles_wallet: int  # Count of tiles new to this wallet
    new_tiles_global: int  # Count of tiles new to the entire system
    night_minutes: float  # Minutes spent riding at night (22:00-04:00)
    total_tiles: int  # Total unique tiles in this activity
    start_time_offset_s: int  # Seconds from ride start
    end_time_offset_s: int  # Seconds from ride end

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "activity_id": self.activity_id,
            "new_tiles_wallet": self.new_tiles_wallet,
            "new_tiles_global": self.new_tiles_global,
            "night_minutes": self.night_minutes,
            "total_tiles": self.total_tiles,
            "start_time_offset_s": self.start_time_offset_s,
            "end_time_offset_s": self.end_time_offset_s,
        }


@dataclass
class ExplorationConfig:
    """
    Configuration for exploration pattern detection thresholds.

    These values can be tuned to adjust sensitivity of exploration detection.
    """

    # Minimum ratio of new tiles to total tiles (e.g., 0.2 = 20%)
    new_tile_ratio_min: float = 0.2

    # Minimum count of globally new tiles to trigger detection
    global_new_tiles_min: int = 10

    # Minimum night minutes to trigger detection
    night_minutes_min: float = 15.0  # 15 minutes

    # Night hours definition (start_hour, end_hour in 24h format)
    # Default: 22:00 (10 PM) to 04:00 (4 AM)
    night_start_hour: int = 22
    night_end_hour: int = 4


class ExplorationPatternDetector:
    """
    Detects exploration patterns from tile sequences.

    The detector compares activity tiles against:
    1. Wallet's historical tile visits
    2. Global tile history (optional)
    3. Ride timing (for night riding detection)

    Eligibility (any of):
    - new_tiles_wallet / total_tiles >= 0.2 (20% new to rider)
    - new_tiles_global >= 10 (new tiles never seen by anyone)
    - night_minutes >= 15 (riding in unusual hours)
    """

    def __init__(self, config: Optional[ExplorationConfig] = None):
        """
        Initialize detector with optional configuration.

        Args:
            config: Configuration object with detection thresholds
        """
        self.config = config or ExplorationConfig()

    def detect(
        self,
        activity_id: str,
        tile_samples: List[dict],
        wallet_tile_history: Set[str],
        global_tile_history: Optional[Set[str]] = None,
        ride_start_time: Optional[datetime] = None,
    ) -> Optional[ExplorationPattern]:
        """
        Detect exploration pattern from tile samples and history.

        Args:
            activity_id: Unique identifier for this activity
            tile_samples: List of dicts with keys 't' (seconds) and 'tile_id' (H3 index)
            wallet_tile_history: Set of tile IDs previously visited by this wallet
            global_tile_history: Optional set of all tiles ever visited by anyone
            ride_start_time: Optional datetime when ride started (for night detection)

        Returns:
            ExplorationPattern if any eligibility threshold is met, None otherwise

        Algorithm:
        1. Extract unique tiles from this activity
        2. Compare to wallet's historical tiles
        3. Calculate new_tiles_wallet ratio
        4. Optionally check global new tiles
        5. Check for night riding (if timestamps available)
        6. Return ExplorationPattern if any threshold met
        """
        if not tile_samples:
            return None

        # Step 1: Get unique tiles from this activity
        activity_tiles = self._get_unique_tiles(tile_samples)
        total_tiles = len(activity_tiles)

        if total_tiles == 0:
            return None

        # Step 2: Compare to wallet's historical tiles
        new_tiles_wallet = activity_tiles - wallet_tile_history
        new_tiles_wallet_count = len(new_tiles_wallet)

        # Step 3: Calculate new tile ratio
        new_tile_ratio = new_tiles_wallet_count / total_tiles

        # Step 4: Check global new tiles (if provided)
        new_tiles_global_count = 0
        if global_tile_history is not None:
            new_tiles_global = activity_tiles - global_tile_history
            new_tiles_global_count = len(new_tiles_global)

        # Step 5: Check for night riding
        night_minutes = 0.0
        if ride_start_time is not None:
            night_minutes = self._calculate_night_minutes(tile_samples, ride_start_time)

        # Step 6: Check eligibility thresholds
        eligible = False

        # Threshold 1: New tile ratio (20% of tiles are new to rider)
        if new_tile_ratio >= self.config.new_tile_ratio_min:
            eligible = True

        # Threshold 2: Global new tiles (discovered 10+ tiles new to system)
        if new_tiles_global_count >= self.config.global_new_tiles_min:
            eligible = True

        # Threshold 3: Night riding (15+ minutes at night)
        if night_minutes >= self.config.night_minutes_min:
            eligible = True

        if not eligible:
            return None

        # Get time range for pattern
        start_offset_s = int(tile_samples[0]["t"])
        end_offset_s = int(tile_samples[-1]["t"])

        return ExplorationPattern(
            activity_id=activity_id,
            new_tiles_wallet=new_tiles_wallet_count,
            new_tiles_global=new_tiles_global_count,
            night_minutes=night_minutes,
            total_tiles=total_tiles,
            start_time_offset_s=start_offset_s,
            end_time_offset_s=end_offset_s,
        )

    def _get_unique_tiles(self, tile_samples: List[dict]) -> Set[str]:
        """
        Extract unique tile IDs from tile samples.

        Args:
            tile_samples: List of dicts with 'tile_id' keys

        Returns:
            Set of unique tile ID strings
        """
        return {sample["tile_id"] for sample in tile_samples if "tile_id" in sample}

    def _calculate_night_minutes(
        self,
        tile_samples: List[dict],
        ride_start_time: datetime,
    ) -> float:
        """
        Calculate minutes spent riding during night hours.

        Night hours are defined by config (default: 22:00-04:00).

        Args:
            tile_samples: List of dicts with 't' (seconds since start) keys
            ride_start_time: Datetime when ride started

        Returns:
            Total minutes spent riding at night
        """
        if not tile_samples:
            return 0.0

        night_seconds = 0.0

        # Process samples in pairs to calculate time in each interval
        for i in range(len(tile_samples) - 1):
            current_sample = tile_samples[i]
            next_sample = tile_samples[i + 1]

            # Calculate actual time for this sample
            sample_time = ride_start_time.timestamp() + current_sample["t"]
            sample_datetime = datetime.fromtimestamp(sample_time, tz=ride_start_time.tzinfo)

            # Check if sample is during night hours
            if self._is_night_time(sample_datetime.time()):
                # Add the duration until next sample
                duration_s = next_sample["t"] - current_sample["t"]
                night_seconds += duration_s

        # Check the last sample
        last_sample = tile_samples[-1]
        last_time = ride_start_time.timestamp() + last_sample["t"]
        last_datetime = datetime.fromtimestamp(last_time, tz=ride_start_time.tzinfo)

        if self._is_night_time(last_datetime.time()):
            # Assume the last sample represents at least 1 second
            night_seconds += 1.0

        return night_seconds / 60.0  # Convert to minutes

    def _is_night_time(self, time_of_day: time) -> bool:
        """
        Check if a given time falls within night hours.

        Night hours can wrap around midnight (e.g., 22:00-04:00).

        Args:
            time_of_day: Time to check

        Returns:
            True if time is during night hours, False otherwise
        """
        hour = time_of_day.hour

        # Handle wrap-around case (e.g., 22:00-04:00)
        if self.config.night_start_hour > self.config.night_end_hour:
            # Night wraps around midnight
            return hour >= self.config.night_start_hour or hour < self.config.night_end_hour
        else:
            # Night is within same day
            return self.config.night_start_hour <= hour < self.config.night_end_hour


def detect_exploration_pattern(
    activity_id: str,
    tile_samples: List[dict],
    wallet_tile_history: Set[str],
    global_tile_history: Optional[Set[str]] = None,
    ride_start_time: Optional[datetime] = None,
    config: Optional[ExplorationConfig] = None,
) -> Optional[ExplorationPattern]:
    """
    Convenience function to detect exploration pattern with default detector.

    Args:
        activity_id: Unique identifier for this activity
        tile_samples: List of dicts with 't' and 'tile_id' keys
        wallet_tile_history: Set of tiles previously visited by this wallet
        global_tile_history: Optional set of all tiles ever visited
        ride_start_time: Optional datetime when ride started
        config: Optional configuration for detection thresholds

    Returns:
        ExplorationPattern if detected, None otherwise
    """
    detector = ExplorationPatternDetector(config)
    return detector.detect(
        activity_id=activity_id,
        tile_samples=tile_samples,
        wallet_tile_history=wallet_tile_history,
        global_tile_history=global_tile_history,
        ride_start_time=ride_start_time,
    )
