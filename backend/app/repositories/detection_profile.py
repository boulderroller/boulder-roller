"""
Detection Profile Repository

Manages climb detection profiles and regional assignments.
These are protocol-managed settings, not user-configurable.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from supabase import Client

logger = logging.getLogger(__name__)


@dataclass
class DetectionProfile:
    """A climb detection configuration profile."""

    name: str
    base_terrain: str
    description: Optional[str] = None

    # Core thresholds
    vert_min_m: Optional[float] = None
    drop_tolerance_m: Optional[float] = None
    time_min_s: Optional[int] = None
    time_max_s: Optional[int] = None
    vam_min: Optional[float] = None

    # Gradient thresholds
    gradient_min_pct: Optional[float] = None
    gradient_start_threshold: Optional[float] = None
    gradient_end_threshold: Optional[float] = None

    # Momentum model
    momentum_start_threshold: Optional[float] = None
    momentum_end_threshold: Optional[float] = None
    momentum_climb_rate: Optional[float] = None
    momentum_drain_rate: Optional[float] = None
    momentum_decay_rate: Optional[float] = None
    momentum_max: Optional[float] = None
    momentum_gradient_neutral: Optional[float] = None

    # Processing params
    smoothing_window: Optional[int] = None
    gradient_window: Optional[int] = None
    max_trim_ratio: Optional[float] = None

    def to_config_overrides(self) -> Dict[str, Any]:
        """
        Convert profile to config_overrides dict for Rust binding.

        Only includes non-None values to allow base_terrain to provide defaults.
        """
        overrides = {}

        # Core thresholds
        if self.vert_min_m is not None:
            overrides["vert_min_m"] = self.vert_min_m
        if self.drop_tolerance_m is not None:
            overrides["drop_tolerance_m"] = self.drop_tolerance_m
        if self.time_min_s is not None:
            overrides["time_min_s"] = self.time_min_s
        if self.time_max_s is not None:
            overrides["time_max_s"] = self.time_max_s
        if self.vam_min is not None:
            overrides["vam_min"] = self.vam_min

        # Gradient thresholds
        if self.gradient_min_pct is not None:
            overrides["gradient_min_pct"] = self.gradient_min_pct
        if self.gradient_start_threshold is not None:
            overrides["gradient_start_threshold"] = self.gradient_start_threshold
        if self.gradient_end_threshold is not None:
            overrides["gradient_end_threshold"] = self.gradient_end_threshold

        # Momentum model
        if self.momentum_start_threshold is not None:
            overrides["momentum_start_threshold"] = self.momentum_start_threshold
        if self.momentum_end_threshold is not None:
            overrides["momentum_end_threshold"] = self.momentum_end_threshold
        if self.momentum_climb_rate is not None:
            overrides["momentum_climb_rate"] = self.momentum_climb_rate
        if self.momentum_drain_rate is not None:
            overrides["momentum_drain_rate"] = self.momentum_drain_rate
        if self.momentum_decay_rate is not None:
            overrides["momentum_decay_rate"] = self.momentum_decay_rate
        if self.momentum_max is not None:
            overrides["momentum_max"] = self.momentum_max
        if self.momentum_gradient_neutral is not None:
            overrides["momentum_gradient_neutral"] = self.momentum_gradient_neutral

        # Processing params
        if self.smoothing_window is not None:
            overrides["smoothing_window"] = self.smoothing_window
        if self.gradient_window is not None:
            overrides["gradient_window"] = self.gradient_window
        if self.max_trim_ratio is not None:
            overrides["max_trim_ratio"] = self.max_trim_ratio

        return overrides

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DetectionProfile":
        """Create profile from database row dict."""
        return cls(
            name=data["name"],
            base_terrain=data.get("base_terrain", "auto"),
            description=data.get("description"),
            vert_min_m=data.get("vert_min_m"),
            drop_tolerance_m=data.get("drop_tolerance_m"),
            time_min_s=data.get("time_min_s"),
            time_max_s=data.get("time_max_s"),
            vam_min=data.get("vam_min"),
            gradient_min_pct=data.get("gradient_min_pct"),
            gradient_start_threshold=data.get("gradient_start_threshold"),
            gradient_end_threshold=data.get("gradient_end_threshold"),
            momentum_start_threshold=data.get("momentum_start_threshold"),
            momentum_end_threshold=data.get("momentum_end_threshold"),
            momentum_climb_rate=data.get("momentum_climb_rate"),
            momentum_drain_rate=data.get("momentum_drain_rate"),
            momentum_decay_rate=data.get("momentum_decay_rate"),
            momentum_max=data.get("momentum_max"),
            momentum_gradient_neutral=data.get("momentum_gradient_neutral"),
            smoothing_window=data.get("smoothing_window"),
            gradient_window=data.get("gradient_window"),
            max_trim_ratio=data.get("max_trim_ratio"),
        )


class DetectionProfileRepository:
    """Repository for climb detection profiles."""

    # Cache for profiles (they change rarely)
    _profile_cache: Dict[str, DetectionProfile] = {}
    _region_cache: Dict[str, str] = {}  # h3_index -> profile_name

    def __init__(self, client: Client):
        self.client = client

    async def get_profile_by_name(self, name: str) -> Optional[DetectionProfile]:
        """Get a profile by name."""
        # Check cache first
        if name in self._profile_cache:
            return self._profile_cache[name]

        result = (
            self.client.from_("climb_detection_profiles")
            .select("*")
            .eq("name", name)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )

        if not result.data:
            return None

        profile = DetectionProfile.from_dict(result.data[0])
        self._profile_cache[name] = profile
        return profile

    async def get_profile_for_h3(self, h3_index: str) -> Optional[DetectionProfile]:
        """
        Get the detection profile for an H3 cell.

        Looks up the regional assignment using H3 resolution 4 prefix.
        Returns None if no regional profile is assigned.
        """
        # H3 resolution 4 index is approximately 11 characters
        h3_r4 = h3_index[:11] if len(h3_index) >= 11 else h3_index

        # Check cache
        if h3_r4 in self._region_cache:
            profile_name = self._region_cache[h3_r4]
            return await self.get_profile_by_name(profile_name)

        # Query regional assignment
        result = (
            self.client.from_("detection_profile_regions")
            .select("profile_name")
            .eq("h3_index_r4", h3_r4)
            .limit(1)
            .execute()
        )

        if not result.data:
            # Cache the miss to avoid repeated lookups
            self._region_cache[h3_r4] = ""
            return None

        profile_name = result.data[0]["profile_name"]
        self._region_cache[h3_r4] = profile_name
        return await self.get_profile_by_name(profile_name)

    async def get_profile_for_location(
        self, lat: float, lon: float
    ) -> Optional[DetectionProfile]:
        """
        Get the detection profile for a lat/lon location.

        Converts location to H3 and looks up regional assignment.
        """
        try:
            import h3
        except ImportError:
            logger.warning("h3 library not available, cannot look up regional profile")
            return None

        # Get H3 cell at resolution 10 (our standard), then truncate to r4
        h3_index = h3.latlng_to_cell(lat, lon, 10)
        return await self.get_profile_for_h3(h3_index)



# Singleton instance
_detection_profile_repo: Optional[DetectionProfileRepository] = None


def get_detection_profile_repository(client: Client) -> DetectionProfileRepository:
    """Get or create the detection profile repository singleton."""
    global _detection_profile_repo
    if _detection_profile_repo is None:
        _detection_profile_repo = DetectionProfileRepository(client)
    return _detection_profile_repo
