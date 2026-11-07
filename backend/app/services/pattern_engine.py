"""
PatternEngine: Orchestrates pattern detection for tile-based attestations.

This is the main entry point for detecting all pattern types from ride data.
Patterns are detected automatically after ride upload and stored for:
- Display in ride summaries
- Effort-based leaderboards
- Optional CAL-gated scoring for DUNG rewards

Flow:
    Ride Upload -> Tile Projection -> Pattern Engine -> Pattern Storage

The Pattern Engine runs all detectors and returns detected patterns:
- ClimbPattern: Sustained vertical gain
- SteadyPattern: Z2-Z3 aerobic blocks
- ExplorationPattern: New tile discovery
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Set

# Climb algorithm env var: "canonical_v2" (default), "canonical", "momentum", "legacy", or "persistence"
_CLIMB_ALGORITHM = os.getenv("CLIMB_ALGORITHM", "canonical_v2").strip().lower()

from ..models.patterns import (
    ClimbPattern as ClimbPatternModel,
    SteadyPattern as SteadyPatternModel,
    ExplorationPattern as ExplorationPatternModel,
    PatternType,
)
from .patterns.climb import ClimbPatternDetector, ClimbPattern, detect_climbs_with_rust, classify_terrain
from .road_enrichment import enrich_climbs, EnrichedClimb
from .patterns.steady import SteadyPatternDetector, SteadyConfig
from .patterns.exploration import (
    ExplorationPatternDetector,
    ExplorationConfig,
    ExplorationPattern,
)
from .patterns.climb_signature import (
    ClimbSignatureGenerator,
    InvalidRewardGradeCandidate,
    InvalidRewardGradeQuery,
    REWARD_GRADE_MIN_SIMILARITY,
    RewardGradeMatcherError,
    RewardGradeMatcherUnavailable,
    match_reward_grade_v2,
    validate_reward_grade_v2_native,
)
from .patterns.template_matching import (
    SegmentTemplate,
    TemplateMatch,
    match_ride_against_templates,
    prepare_template,
)
from .sensor_integrity import (
    SensorIntegrityReport,
    compute_sensor_integrity,
    get_abstention_reasons_from_integrity,
)
from .sample_time import infer_sample_time_base, sample_in_time_window, sample_time_seconds
from .vault_indexer import VaultSignatureCache, IndexedVault, get_vault_signature_cache
from .vault_activation_policy import is_reward_authoritative_vault
from ..repositories.detection_profile import (
    DetectionProfileRepository,
    DetectionProfile,
    get_detection_profile_repository,
)

# Vault matching thresholds
VAULT_MIN_SIMILARITY = REWARD_GRADE_MIN_SIMILARITY

logger = logging.getLogger(__name__)


class ClimbFrequencyMap:
    """Cached map of H3 res-8 tiles to historical climb detection counts.

    Used as a Bayesian prior (H12 heuristic) in canonical_v2 climb scoring.
    Locations with many historical detections get a confidence bonus, which
    helps distinguish real climbs from noise in ambiguous cases.

    Follows the same singleton/load-at-startup pattern as VaultSignatureCache.
    """

    def __init__(self):
        self._map: Dict[str, int] = {}
        self._loaded: bool = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def count(self) -> int:
        return len(self._map)

    async def load(self, supabase_client) -> int:
        """Load frequency map from patterns_climb table.

        Counts economically-eligible climbs per H3 res-8 tile.
        Only includes climbs with GPS coordinates (start_lat/start_lon).

        Returns:
            Number of distinct H3 res-8 tiles loaded
        """
        try:
            import h3
        except ImportError:
            logger.warning("[ClimbFrequencyMap] h3 not available, frequency map disabled")
            self._loaded = True
            return 0

        try:
            # Query all economically-eligible climbs with GPS coordinates
            response = supabase_client.from_("patterns_climb") \
                .select("start_lat, start_lon") \
                .not_.is_("start_lat", "null") \
                .not_.is_("start_lon", "null") \
                .eq("economic_eligible", True) \
                .execute()

            freq: Dict[str, int] = {}
            for row in response.data or []:
                lat = row.get("start_lat")
                lon = row.get("start_lon")
                if lat is not None and lon is not None:
                    try:
                        tile = h3.latlng_to_cell(float(lat), float(lon), 8)
                        freq[tile] = freq.get(tile, 0) + 1
                    except Exception:
                        continue

            self._map = freq
            self._loaded = True
            logger.info(
                f"[ClimbFrequencyMap] Loaded {len(freq)} distinct res-8 tiles "
                f"from {len(response.data or [])} eligible climbs"
            )
            return len(freq)

        except Exception as e:
            logger.warning(f"[ClimbFrequencyMap] Failed to load: {e}")
            self._loaded = True  # Mark loaded so we don't block; returns 0 for all lookups
            return 0

    def get(self, tile: str) -> int:
        """Get detection count for an H3 res-8 tile."""
        return self._map.get(tile, 0)

    def to_dict(self) -> Dict[str, int]:
        """Return the raw map (for passing to detect_climbs_with_rust)."""
        return self._map if self._loaded else {}


# Module-level singleton for frequency map
_frequency_map: Optional[ClimbFrequencyMap] = None


def get_climb_frequency_map() -> ClimbFrequencyMap:
    """Get or create the climb frequency map singleton."""
    global _frequency_map
    if _frequency_map is None:
        _frequency_map = ClimbFrequencyMap()
    return _frequency_map


@dataclass
class UserProfile:
    """User profile data needed for pattern detection."""

    wallet: str
    weight_kg: Optional[float] = None  # For W/kg calculation
    ftp_w: Optional[int] = None  # Functional Threshold Power
    threshold_hr: Optional[int] = None  # Threshold heart rate


@dataclass
class VaultCompletion:
    """Match and provenance for a climb that qualifies for a vault completion."""
    vault_id: int
    vault_name: str
    climb_pattern_id: uuid.UUID
    similarity: float
    completion_time_s: int
    is_new_kom: bool = False
    solana_signature: Optional[str] = None


@dataclass
class PatternResults:
    """Results from pattern detection for a single activity."""

    activity_id: uuid.UUID
    wallet: str
    climb_patterns: List[ClimbPatternModel] = field(default_factory=list)
    steady_pattern: Optional[SteadyPatternModel] = None
    exploration_pattern: Optional[ExplorationPatternModel] = None
    vault_completions: List[VaultCompletion] = field(default_factory=list)
    sensor_integrity: Optional[SensorIntegrityReport] = None

    @property
    def total_patterns(self) -> int:
        """Total number of patterns detected."""
        count = len(self.climb_patterns)
        if self.steady_pattern:
            count += 1
        if self.exploration_pattern:
            count += 1
        return count

    def to_dict(self) -> Dict:
        """Convert to dictionary for API responses."""
        return {
            "activity_id": str(self.activity_id),
            "wallet": self.wallet,
            "total_patterns": self.total_patterns,
            "climb_patterns": [p.to_dict() for p in self.climb_patterns],
            "steady_pattern": self.steady_pattern.to_dict() if self.steady_pattern else None,
            "exploration_pattern": self.exploration_pattern.to_dict() if self.exploration_pattern else None,
            "sensor_integrity": self.sensor_integrity.to_dict() if self.sensor_integrity else None,
            "vault_completions": [
                {
                    "vault_id": vc.vault_id,
                    "vault_name": vc.vault_name,
                    "similarity": vc.similarity,
                    "completion_time_s": vc.completion_time_s,
                    "is_new_kom": vc.is_new_kom,
                    "solana_signature": vc.solana_signature,
                }
                for vc in self.vault_completions
            ],
        }

    def summary(self) -> str:
        """Human-readable summary of detected patterns."""
        parts = []

        if self.climb_patterns:
            total_vert = sum(p.vert_m for p in self.climb_patterns)
            parts.append(f"{int(total_vert)}m climbed")

        if self.vault_completions:
            vault_names = [vc.vault_name for vc in self.vault_completions]
            parts.append(f"{len(vault_names)} vault(s): {', '.join(vault_names)}")

        if self.steady_pattern:
            mins = self.steady_pattern.duration_s // 60
            parts.append(f"{mins}min steady")

        if self.exploration_pattern:
            parts.append(f"{self.exploration_pattern.new_tiles_wallet} new areas explored")

        if not parts:
            return "No patterns detected"

        return ", ".join(parts)


class PatternEngine:
    """
    Orchestrates pattern detection from tile samples.

    The engine runs all detectors in sequence and aggregates results.
    Each detector is independent and can fail gracefully.

    After climb detection, matches are checked against on-chain Vaults.
    High-similarity matches (>= 0.90) trigger vault completion recording.

    Usage:
        engine = PatternEngine()
        results = await engine.detect_patterns(
            activity_id=ride_id,
            tile_samples=tile_data,
            user_profile=UserProfile(wallet="..."),
            wallet_tile_history={"tile1", "tile2"},
        )
    """

    def __init__(
        self,
        climb_detector: Optional[ClimbPatternDetector] = None,
        steady_detector: Optional[SteadyPatternDetector] = None,
        exploration_detector: Optional[ExplorationPatternDetector] = None,
        vault_cache: Optional[VaultSignatureCache] = None,
        terrain_mode: str = "auto",
        use_rust_detector: bool = True,
        config_overrides: Optional[Dict] = None,
        detection_profile_repo: Optional[DetectionProfileRepository] = None,
        climb_algorithm: str = _CLIMB_ALGORITHM,
        frequency_map: Optional[ClimbFrequencyMap] = None,
    ):
        """
        Initialize pattern engine with optional custom detectors.

        Args:
            climb_detector: Custom climb detector (uses default if None)
            steady_detector: Custom steady detector (uses default if None)
            exploration_detector: Custom exploration detector (uses default if None)
            vault_cache: Vault signature cache for matching (uses singleton if None)
            terrain_mode: Terrain classification mode for climb detection:
                - "auto": Auto-detect terrain from elevation profile (recommended)
                - "flat": Use flat terrain thresholds (15m vert, 2% gradient)
                - "rolling": Use rolling terrain thresholds (25m vert, 2.5% gradient)
                - "urban_hills": Short punchy climbs (20m vert, tight boundaries)
                - "hilly": Use hilly terrain thresholds (50m vert, 4% gradient)
                - "mountainous": Use mountainous terrain thresholds (100m vert, 5% gradient)
            use_rust_detector: Use high-performance Rust detector (recommended)
            config_overrides: Optional dict of config overrides to apply on top of terrain preset.
                Keys: vert_min_m, drop_tolerance_m, time_min_s, vam_min, gradient_min_pct, etc.
            detection_profile_repo: Repository for loading regional detection profiles.
                If provided, will look up profile based on ride location.
            climb_algorithm: Climb detection algorithm:
                - "canonical_v2": Default production path: conservative chooser over momentum + persistence
                - "canonical": Legacy prelaunch path (momentum terrain chooser)
                - "momentum": Single-terrain momentum detector
                - "persistence": Research path for topological comparison
                - "legacy": Original gradient-based (deprecated)
            frequency_map: ClimbFrequencyMap for H12 Bayesian prior. Uses singleton if None.
        """
        self.climb_detector = climb_detector or ClimbPatternDetector()
        self.steady_detector = steady_detector or SteadyPatternDetector()
        self.exploration_detector = exploration_detector or ExplorationPatternDetector()
        self.vault_cache = vault_cache or get_vault_signature_cache()
        self.signature_generator = ClimbSignatureGenerator()
        self.terrain_mode = terrain_mode
        self.use_rust_detector = use_rust_detector
        self.config_overrides = config_overrides
        self.detection_profile_repo = detection_profile_repo
        self.climb_algorithm = climb_algorithm
        self._frequency_map_obj = frequency_map or get_climb_frequency_map()

    @property
    def frequency_map(self) -> Optional[Dict[str, int]]:
        """Return the frequency map dict for passing to detect_climbs_with_rust.

        Returns None if the map hasn't been loaded yet, which causes
        the H12 heuristic to return 0.0 (neutral) for all locations.
        """
        if self._frequency_map_obj.is_loaded and self._frequency_map_obj.count > 0:
            return self._frequency_map_obj.to_dict()
        return None

    async def detect_patterns(
        self,
        activity_id: uuid.UUID,
        tile_samples: List[Dict],
        user_profile: UserProfile,
        wallet_tile_history: Set[str],
        raw_climb_samples: Optional[List[Dict]] = None,
        global_tile_history: Optional[Set[str]] = None,
        arena_tiles: Optional[Set[str]] = None,
        ride_start_time: Optional[datetime] = None,
    ) -> PatternResults:
        """
        Detect all patterns from product tile samples, optionally using a
        higher-fidelity sample stream for climb candidate generation.

        Args:
            activity_id: UUID of the activity
            tile_samples: List of product tile sample dicts with keys:
                - t: int (seconds since ride start)
                - tile_id: str (H3 index)
                - elevation_m: float (optional)
                - power_w: int (optional)
                - hr_bpm: int (optional)
            raw_climb_samples: Optional per-point tile sample dicts used for
                persistence candidate generation when available.
            user_profile: User profile with wallet, weight, FTP, etc.
            wallet_tile_history: Set of tile IDs previously visited by wallet
            global_tile_history: Optional set of all tiles ever visited
            arena_tiles: Optional set of tile IDs for Arena filtering
            ride_start_time: Optional start time for night riding detection

        Returns:
            PatternResults with all detected patterns
        """
        results = PatternResults(
            activity_id=activity_id,
            wallet=user_profile.wallet,
        )

        if not tile_samples:
            logger.debug(f"No tile samples for activity {activity_id}")
            return results

        logger.info(f"Detecting patterns for activity {activity_id} ({len(tile_samples)} samples)")

        # Compute sensor integrity once per activity (shared across all
        # detectors). Use dense raw samples when available; product tile runs
        # intentionally collapse long same-tile spans and should not be scored
        # as if they were the sensor sampling cadence.
        integrity_samples = raw_climb_samples or tile_samples
        integrity = compute_sensor_integrity(integrity_samples)
        results.sensor_integrity = integrity
        if integrity.flags:
            logger.info(
                f"[SensorIntegrity] Activity {activity_id}: "
                f"score={integrity.integrity_score:.2f}, flags={integrity.flags}"
            )

        # Run all detectors
        try:
            climb_patterns = await self._detect_climb_patterns(
                tile_samples=tile_samples,
                raw_climb_samples=raw_climb_samples,
                user_profile=user_profile,
                activity_id=activity_id,
                arena_tiles=arena_tiles,
                sensor_integrity=integrity,
            )

            # Template matching: match ride GPS track against vault polylines.
            # Template/profile evidence is identity/display evidence only. It may
            # add a non-economic known-climb surface when the elevation detector
            # missed a vault corridor, but it cannot create rewardable evidence by
            # itself. Rewardable vault completions still require a ride-only climb
            # candidate from the canonical detector.
            try:
                template_patterns = self._run_template_matching(
                    tile_samples=tile_samples,
                    raw_climb_samples=raw_climb_samples,
                    existing_patterns=climb_patterns,
                    user_profile=user_profile,
                    activity_id=activity_id,
                    sensor_integrity=integrity,
                )
                if template_patterns:
                    logger.info(
                        f"[TemplateMatch] Added {len(template_patterns)} template-matched "
                        f"climb(s) to {len(climb_patterns)} elevation-detected climb(s)"
                    )
                    climb_patterns.extend(template_patterns)
            except Exception as e:
                logger.warning(f"[TemplateMatch] Template matching failed (non-fatal): {e}")

            results.climb_patterns = climb_patterns

            # Match climbs against on-chain vaults (from indexed cache)
            if climb_patterns and not self.vault_cache.is_loaded:
                logger.warning(
                    "[PatternEngine] Vault cache not loaded — skipping reward-grade "
                    "vault matching for %d climb(s). Is this a Celery worker?",
                    len(climb_patterns),
                )
            if climb_patterns and self.vault_cache.is_loaded:
                vault_completions = await self._match_vaults_and_record(
                    climb_patterns=climb_patterns,
                    tile_samples=tile_samples,
                    user_profile=user_profile,
                    activity_id=activity_id,
                )
                results.vault_completions = vault_completions

        except RewardGradeMatcherError:
            raise
        except Exception as e:
            logger.error(f"Climb detection failed: {e}")

        try:
            steady_pattern = self._detect_steady_pattern(
                tile_samples=tile_samples,
                user_profile=user_profile,
                activity_id=activity_id,
            )
            results.steady_pattern = steady_pattern
        except Exception as e:
            logger.error(f"Steady detection failed: {e}")

        try:
            exploration_pattern = self._detect_exploration_pattern(
                tile_samples=tile_samples,
                user_profile=user_profile,
                activity_id=activity_id,
                wallet_tile_history=wallet_tile_history,
                global_tile_history=global_tile_history,
                ride_start_time=ride_start_time,
            )
            results.exploration_pattern = exploration_pattern
        except Exception as e:
            logger.error(f"Exploration detection failed: {e}")

        logger.info(f"Detected {results.total_patterns} patterns: {results.summary()}")

        return results

    async def _get_effective_config_overrides(
        self,
        tile_samples: List[Dict],
    ) -> Optional[Dict]:
        """
        Get effective config overrides by merging regional profile with explicit overrides.

        Priority: explicit overrides > regional profile > None

        Args:
            tile_samples: Tile samples to extract location from (uses first sample with lat/lon)

        Returns:
            Merged config overrides dict, or None if no overrides
        """
        regional_overrides = {}

        # Try to load regional profile if repo is available
        if self.detection_profile_repo and tile_samples:
            # Find first sample with lat/lon
            for sample in tile_samples:
                lat = sample.get("lat")
                lon = sample.get("lon")
                if lat is not None and lon is not None:
                    try:
                        profile = await self.detection_profile_repo.get_profile_for_location(lat, lon)
                        if profile:
                            regional_overrides = profile.to_config_overrides()
                            logger.info(
                                f"[ClimbDetect] Using regional profile '{profile.name}' "
                                f"(base={profile.base_terrain}, overrides={len(regional_overrides)} params)"
                            )
                            # Also use profile's base_terrain if we're in auto mode
                            if self.terrain_mode == "auto" and profile.base_terrain:
                                self.terrain_mode = profile.base_terrain
                    except Exception as e:
                        logger.warning(f"[ClimbDetect] Failed to load regional profile: {e}")
                    break

        # Merge: regional profile (base) + explicit overrides (priority)
        if regional_overrides or self.config_overrides:
            effective = {**regional_overrides, **(self.config_overrides or {})}
            if effective:
                logger.debug(f"[ClimbDetect] Effective config overrides: {effective}")
                return effective

        return None

    async def _detect_climb_patterns(
        self,
        tile_samples: List[Dict],
        raw_climb_samples: Optional[List[Dict]],
        user_profile: UserProfile,
        activity_id: uuid.UUID,
        arena_tiles: Optional[Set[str]] = None,
        sensor_integrity: Optional[SensorIntegrityReport] = None,
    ) -> List[ClimbPatternModel]:
        """
        Detect climb patterns from tile samples using terrain-adaptive thresholds.

        Uses the high-performance Rust detector by default with automatic terrain
        classification for optimal climb detection across different terrain types.

        When raw_climb_samples (per-second, full-resolution) are available, they
        are used as the primary input to the detector instead of tile_samples
        (H3-aggregated tile_runs, ~7x downsampled). This provides +11.7pp recall
        by preserving fine-grained elevation transitions that aggregation masks.

        Returns list of climb patterns (multiple distinct climbs per activity).
        Each pattern includes tile_ids for road attribution.
        """
        # Use full-resolution samples for detection when available.
        # raw_climb_samples = per-second tile sequence (full GPS/elevation fidelity)
        # tile_samples = H3-aggregated tile_runs (~7x fewer samples, averaged sensors)
        # The full-resolution stream preserves elevation transitions that aggregation
        # masks, yielding +11.7pp recall improvement.
        if raw_climb_samples:
            detector_samples = raw_climb_samples
            logger.info(
                f"[ClimbDetect] Activity {activity_id}: using {len(raw_climb_samples)} "
                f"raw samples (full resolution) instead of {len(tile_samples)} tile_runs"
            )
        else:
            detector_samples = tile_samples
            logger.info(
                f"[ClimbDetect] Activity {activity_id}: using {len(tile_samples)} "
                f"tile_runs (no raw samples available)"
            )

        # Debug: Log sample structure to diagnose missing lat/lon
        if detector_samples:
            sample_keys = list(detector_samples[0].keys())
            has_lat = "lat" in detector_samples[0]
            has_lon = "lon" in detector_samples[0]
            logger.info(
                f"[ClimbDetect] Activity {activity_id}: {len(detector_samples)} samples, "
                f"keys={sample_keys}, has_lat={has_lat}, has_lon={has_lon}"
            )
            if detector_samples and (has_lat or has_lon):
                # Log first sample lat/lon values
                sample = detector_samples[0]
                logger.info(f"[ClimbDetect] First sample: lat={sample.get('lat')}, lon={sample.get('lon')}")

        # Build config overrides: regional profile + explicit overrides
        effective_overrides = await self._get_effective_config_overrides(detector_samples)

        # Bridge elevation preprocessing: interpolate elevation across bridges
        # to prevent false climbs from barometric altimeter readings on bridges
        try:
            from .road_enrichment import preprocess_bridge_elevations
            detector_samples = preprocess_bridge_elevations(detector_samples)
        except Exception as e:
            logger.warning(f"Bridge preprocessing failed, proceeding without: {e}")

        # Use Rust terrain-adaptive detector if enabled
        if self.use_rust_detector:
            climbs = detect_climbs_with_rust(
                tile_samples=detector_samples,
                persistence_candidate_samples=None,  # No separate stream needed; detector_samples is already full-res
                terrain=self.terrain_mode,
                config_overrides=effective_overrides,
                arena_tiles=arena_tiles,
                user_weight_kg=user_profile.weight_kg,
                algorithm=self.climb_algorithm,
                generate_signatures=True,
                frequency_map=self.frequency_map,
            )

            # Log terrain classification for debugging
            if self.terrain_mode == "auto":
                terrain_info = classify_terrain(detector_samples)
                if terrain_info:
                    logger.debug(
                        f"Terrain classified as {terrain_info.get('class')} "
                        f"(confidence={terrain_info.get('confidence', 0):.2f}, "
                        f"difficulty={terrain_info.get('difficulty_score', 0):.1f})"
                    )
        else:
            # Fall back to Python detector
            climbs = self.climb_detector.detect_all(
                tile_samples=detector_samples,
                arena_tiles=arena_tiles,
                user_weight_kg=user_profile.weight_kg,
            )

        if not climbs:
            return []

        # Debug: Log climb values to diagnose null distance/gradient
        for i, climb in enumerate(climbs):
            logger.info(
                f"[ClimbDetect] Climb {i+1}/{len(climbs)}: "
                f"vert_m={climb.vert_m}, distance_m={climb.distance_m}, "
                f"avg_gradient_pct={climb.avg_gradient_pct}, tile_ids={len(climb.tile_ids) if climb.tile_ids else 0}"
            )

        # Road enrichment: query OSM road features and enrich climbs
        # with bridge suppression, road names, boundary refinement, split candidates
        try:
            enrichments = enrich_climbs(climbs, detector_samples)
        except Exception as e:
            logger.warning(f"Road enrichment failed, proceeding without: {e}")
            enrichments = [EnrichedClimb() for _ in climbs]

        patterns: List[ClimbPatternModel] = []
        for climb, enriched in zip(climbs, enrichments):
            pattern = ClimbPatternModel(
                id=uuid.uuid4(),
                activity_id=activity_id,
                wallet=user_profile.wallet,
                arena_id=None,  # World Arena for now
                vert_m=climb.vert_m,
                time_s=climb.time_s,
                avg_power_w=climb.avg_power_w,
                w_per_kg=climb.w_per_kg,
                avg_hr=climb.avg_hr,
                start_offset_s=climb.start_time_offset_s,
                end_offset_s=climb.end_time_offset_s,
                tile_ids=climb.tile_ids,
                distance_m=climb.distance_m,
                avg_gradient_pct=climb.avg_gradient_pct,
                signature_hex=climb.signature_hex,
                signature_v2_hex=getattr(climb, 'signature_v2_hex', None),
                start_lat=getattr(climb, 'start_lat', None),
                start_lon=getattr(climb, 'start_lon', None),
                end_lat=getattr(climb, 'end_lat', None),
                end_lon=getattr(climb, 'end_lon', None),
                persistence_m=getattr(climb, 'persistence', None),
                detector_version=self.climb_algorithm,
                road_name=enriched.road_name,
            )

            # Carry enrichment metadata for abstention and decision trace
            pattern._road_enrichment = enriched
            patterns.append(pattern)

        # Evaluate abstention for each pattern (includes road-based suppression)
        for pattern in patterns:
            self._evaluate_abstention(pattern, detector_samples, sensor_integrity)

        return patterns

    def _run_template_matching(
        self,
        tile_samples: List[Dict],
        raw_climb_samples: Optional[List[Dict]],
        existing_patterns: List[ClimbPatternModel],
        user_profile: UserProfile,
        activity_id: uuid.UUID,
        sensor_integrity: Optional[SensorIntegrityReport] = None,
    ) -> List[ClimbPatternModel]:
        """
        Run GPS template matching against vault polylines.

        Matches the ride's GPS track against vault GPS corridors to identify
        known climbs that elevation-based detection may have missed.

        Only returns template matches that do NOT overlap with existing
        elevation-based detections (overlap = >50% time overlap). Returned
        template-only patterns are display/identity-only and economically
        ineligible because they are not backed by a ride-only climb candidate.

        Requires vaults to have polyline_json stored. If no vaults have polylines,
        returns empty list gracefully.

        Args:
            tile_samples: H3-aggregated tile_runs (used for elevation lookup)
            raw_climb_samples: Per-second full-resolution samples (preferred for GPS)
            existing_patterns: Already-detected climb patterns from elevation detector
            user_profile: User profile
            activity_id: Activity UUID
            sensor_integrity: Sensor integrity report for abstention evaluation

        Returns:
            List of new ClimbPatternModel from template matches (non-overlapping only)
        """
        if not self.vault_cache.is_loaded:
            return []

        # Build ride GPS track and times from raw samples (prefer full-res)
        samples = raw_climb_samples if raw_climb_samples else tile_samples
        if not samples:
            return []
        sample_time_base = infer_sample_time_base(samples)

        ride_latlng = []
        ride_times = []
        ride_elevations = []
        for s in samples:
            lat = s.get("lat")
            lon = s.get("lon")
            t = s.get("t", 0)
            if lat is not None and lon is not None:
                t_seconds = sample_time_seconds(t, base_time=sample_time_base)
                if t_seconds is None:
                    continue
                ride_latlng.append((float(lat), float(lon)))
                ride_times.append(int(round(t_seconds)))
                ride_elevations.append(s.get("elevation_m"))

        if len(ride_latlng) < 10:
            return []

        # Build templates from vaults that have polyline data
        templates = []
        vault_by_template_id = {}
        for vault in self.vault_cache._vaults.values():
            polyline_json = getattr(vault, "polyline_json", None)
            if not polyline_json:
                continue

            try:
                import json
                polyline_data = json.loads(polyline_json)
                if not isinstance(polyline_data, list) or len(polyline_data) < 2:
                    continue

                # polyline_json is stored as [[lat, lon], [lat, lon], ...]
                polyline_pts = [(float(p[0]), float(p[1])) for p in polyline_data]

                tmpl = SegmentTemplate(
                    template_id=vault.id,
                    name=vault.name,
                    polyline=polyline_pts,
                    expected_vert_m=vault.vert_m,
                    expected_grade_pct=vault.avg_gradient_pct,
                    expected_distance_m=float(vault.distance_m),
                )
                prepare_template(tmpl)
                templates.append(tmpl)
                vault_by_template_id[vault.id] = vault
            except Exception as e:
                logger.debug(f"[TemplateMatch] Failed to build template for vault {vault.id}: {e}")
                continue

        if not templates:
            return []

        logger.debug(
            f"[TemplateMatch] Activity {activity_id}: matching against "
            f"{len(templates)} vault templates ({len(ride_latlng)} GPS points)"
        )

        # Run template matching
        matches = match_ride_against_templates(
            ride_latlng=ride_latlng,
            ride_times=ride_times,
            templates=templates,
            corridor_width_m=50.0,
            min_coverage=0.60,
            ride_elevations=ride_elevations,
        )

        if not matches:
            return []

        # Filter out matches that overlap with existing elevation-based detections
        # Overlap = >50% of the shorter pattern's duration falls within the other
        existing_ranges = [
            (p.start_offset_s, p.end_offset_s) for p in existing_patterns
        ]

        new_patterns = []
        for match in matches:
            match_start = match.start_time_s
            match_end = match.end_time_s
            match_duration = max(1, match_end - match_start)

            overlaps = False
            for ex_start, ex_end in existing_ranges:
                overlap_start = max(match_start, ex_start)
                overlap_end = min(match_end, ex_end)
                overlap_duration = max(0, overlap_end - overlap_start)
                shorter_duration = min(match_duration, max(1, ex_end - ex_start))
                if overlap_duration / shorter_duration >= 0.50:
                    overlaps = True
                    break

            if overlaps:
                logger.debug(
                    f"[TemplateMatch] Skipping {match.template_name} "
                    f"(overlaps with existing detection)"
                )
                continue

            # Build a ClimbPatternModel from the template match
            vault = vault_by_template_id.get(match.template_id)
            if not vault:
                continue

            # Compute actual metrics from ride data in the matched time window
            match_samples = [
                s for s in samples
                if sample_in_time_window(
                    s,
                    match_start,
                    match_end,
                    base_time=sample_time_base,
                )
            ]

            # Power/HR from matched samples
            power_vals = [s.get("power_w") for s in match_samples if s.get("power_w")]
            hr_vals = [s.get("hr_bpm") for s in match_samples if s.get("hr_bpm")]
            avg_power = sum(power_vals) / len(power_vals) if power_vals else None
            avg_hr = int(sum(hr_vals) / len(hr_vals)) if hr_vals else None
            w_per_kg = avg_power / user_profile.weight_kg if avg_power and user_profile.weight_kg else None

            # Tile IDs from matched samples
            tile_ids = list(dict.fromkeys(
                s.get("tile_id") for s in match_samples if s.get("tile_id")
            ))

            # GPS coordinates from first/last matched points
            start_lat = ride_latlng[match.start_idx][0] if match.start_idx < len(ride_latlng) else None
            start_lon = ride_latlng[match.start_idx][1] if match.start_idx < len(ride_latlng) else None
            end_lat = ride_latlng[match.end_idx][0] if match.end_idx < len(ride_latlng) else None
            end_lon = ride_latlng[match.end_idx][1] if match.end_idx < len(ride_latlng) else None

            pattern = ClimbPatternModel(
                id=uuid.uuid4(),
                activity_id=activity_id,
                wallet=user_profile.wallet,
                arena_id=None,
                vert_m=match.actual_vert_m if match.actual_vert_m > 0 else match.expected_vert_m,
                time_s=max(1, match_end - match_start),
                avg_power_w=avg_power,
                w_per_kg=w_per_kg,
                avg_hr=avg_hr,
                start_offset_s=match_start,
                end_offset_s=match_end,
                tile_ids=tile_ids,
                distance_m=match.expected_vert_m / (match.expected_grade_pct / 100.0) if match.expected_grade_pct > 0 else vault.distance_m,
                avg_gradient_pct=match.expected_grade_pct,
                signature_hex=vault.signature_hex,
                signature_v2_hex=vault.signature_v2_hex,
                indexed_vault_id=vault.id,
                indexed_vault_name=vault.name,
                vault_climb_name=vault.name,
                vault_match_similarity=match.coverage,
                is_strong_match=False,
                start_lat=start_lat,
                start_lon=start_lon,
                end_lat=end_lat,
                end_lon=end_lon,
                detector_version=f"template_match:{self.climb_algorithm}",
                road_name=vault.name,
            )

            # Evaluate abstention. Template-only patterns remain economic-ineligible
            # even if generic sensor/signature checks pass.
            self._evaluate_abstention(pattern, samples, sensor_integrity)

            new_patterns.append(pattern)
            logger.info(
                f"[TemplateMatch] New detection: {match.template_name} "
                f"({match.actual_vert_m:.0f}m, coverage={match.coverage:.0%}, "
                f"t={match_start}-{match_end}s, economic_eligible=False)"
            )

        return new_patterns

    def _evaluate_abstention(
        self,
        pattern: ClimbPatternModel,
        tile_samples: List[Dict],
        sensor_integrity: Optional[SensorIntegrityReport] = None,
    ) -> None:
        """
        Evaluate whether a climb should abstain from economic actions.

        Two-layer check:
        1. Activity-level: Uses SensorIntegrityReport (computed once per ride)
        2. Climb-level: Per-climb checks for significance, VAM, signatures,
           and local GPS/elevation coverage within the climb's time window

        Implements ABSTENTION_POLICY.md. Sets pattern.economic_eligible and
        pattern.abstention_reasons in place.
        """
        reasons = []

        # === Activity-level checks (from sensor integrity report) ===
        if sensor_integrity is not None:
            activity_reasons = get_abstention_reasons_from_integrity(sensor_integrity)
            reasons.extend(activity_reasons)
            if sensor_integrity.median_interval_s >= 30:
                reasons.append(
                    f"SENSOR:sparse_sampling_{sensor_integrity.median_interval_s:.0f}s"
                )

        # === Climb-level checks ===

        # Template/profile matches answer "which known climb was traversed?",
        # not "did the ride-only detector find a rewardable climb?". Keep them
        # visible for product identity while blocking all economic actions unless
        # an overlapping canonical climb owns the reward path.
        detector_version = pattern.detector_version or ""
        if detector_version.startswith(("template_match:", "profile_match:")):
            reasons.append("SOURCE:identity_only_no_ride_candidate")

        # 1. Significance confidence tier
        if pattern.significance_confidence_tier == 0:
            reasons.append("SIGNIFICANCE:tier_0_unbootstrapped")

        # 2. Per-climb GPS and elevation coverage (within climb window)
        start_t = pattern.start_offset_s
        end_t = pattern.end_offset_s
        sample_time_base = infer_sample_time_base(tile_samples)
        climb_samples = [
            s
            for s in tile_samples
            if sample_in_time_window(s, start_t, end_t, base_time=sample_time_base)
        ]
        if climb_samples:
            gps_count = sum(1 for s in climb_samples if s.get("lat") is not None)
            gps_coverage = gps_count / len(climb_samples)
            if gps_coverage < 0.50:
                reasons.append(f"CLIMB_SENSOR:gps_coverage_{gps_coverage:.0%}")

            elev_count = sum(1 for s in climb_samples if s.get("elevation_m") is not None)
            elev_coverage = elev_count / len(climb_samples)
            if elev_coverage < 0.80:
                reasons.append(f"CLIMB_SENSOR:elev_coverage_{elev_coverage:.0%}")

            # Time gap within climb window
            climb_sample_times = [
                sample_time_seconds(s.get("t"), base_time=sample_time_base)
                for s in climb_samples
            ]
            climb_sample_times = sorted(t for t in climb_sample_times if t is not None)
            for i in range(1, len(climb_sample_times)):
                gap = climb_sample_times[i] - climb_sample_times[i - 1]
                if gap > 300:
                    reasons.append(f"CLIMB_SENSOR:time_gap_{gap}s")
                    break

        # 3. VAM sanity (borderline sensor artifact)
        if pattern.time_s and pattern.time_s > 0:
            vam = (pattern.vert_m / pattern.time_s) * 3600
            if vam > 2000:
                reasons.append(f"CLIMB_SENSOR:high_vam_{vam:.0f}")

        # 4. Signature integrity
        if not pattern.signature_v2_hex:
            reasons.append("SIGNATURE:no_v2_sig")

        # 5. Road enrichment: bridge suppression
        enrichment = getattr(pattern, "_road_enrichment", None)
        if enrichment and enrichment.suppressed:
            reasons.append(enrichment.suppression_reason or "INFRA:suppressed")

        # Deduplicate (activity-level reasons may overlap with climb-level)
        seen = set()
        unique_reasons = []
        for r in reasons:
            if r not in seen:
                seen.add(r)
                unique_reasons.append(r)

        pattern.economic_eligible = len(unique_reasons) == 0
        pattern.abstention_reasons = unique_reasons if unique_reasons else None

        if unique_reasons:
            logger.debug(
                f"[Abstention] Climb {pattern.id}: abstained ({', '.join(unique_reasons)})"
            )

    def _detect_steady_pattern(
        self,
        tile_samples: List[Dict],
        user_profile: UserProfile,
        activity_id: uuid.UUID,
    ) -> Optional[SteadyPatternModel]:
        """Detect steady pattern from tile samples."""
        steady = self.steady_detector.detect(
            tile_samples=tile_samples,
            user_ftp=user_profile.ftp_w,
            user_threshold_hr=user_profile.threshold_hr,
            wallet=user_profile.wallet,
            activity_id=activity_id,
        )

        if not steady:
            return None

        # The detector already returns a SteadyPattern model
        return steady

    def _detect_exploration_pattern(
        self,
        tile_samples: List[Dict],
        user_profile: UserProfile,
        activity_id: uuid.UUID,
        wallet_tile_history: Set[str],
        global_tile_history: Optional[Set[str]] = None,
        ride_start_time: Optional[datetime] = None,
    ) -> Optional[ExplorationPatternModel]:
        """Detect exploration pattern from tile samples."""
        exploration = self.exploration_detector.detect(
            activity_id=str(activity_id),
            tile_samples=tile_samples,
            wallet_tile_history=wallet_tile_history,
            global_tile_history=global_tile_history,
            ride_start_time=ride_start_time,
        )

        if not exploration:
            return None

        # Convert detector result to model
        return ExplorationPatternModel(
            id=uuid.uuid4(),
            activity_id=activity_id,
            wallet=user_profile.wallet,
            new_tiles_wallet=exploration.new_tiles_wallet,
            new_tiles_global=exploration.new_tiles_global,
            total_tiles=exploration.total_tiles,
            night_minutes=int(exploration.night_minutes) if exploration.night_minutes else None,
            start_offset_s=exploration.start_time_offset_s,
            end_offset_s=exploration.end_time_offset_s,
        )

    async def _match_vaults_and_record(
        self,
        climb_patterns: List[ClimbPatternModel],
        tile_samples: List[Dict],
        user_profile: UserProfile,
        activity_id: uuid.UUID,
    ) -> List[VaultCompletion]:
        """
        Match detected climbs against on-chain vaults and record completions.

        For each climb pattern:
        1. Require a canonical v2 signature and both oriented GPS endpoints
        2. Find matching vaults through the reward-grade matcher
        3. Return match and completion provenance without economic amounts

        Args:
            climb_patterns: Detected climb patterns with time ranges
            tile_samples: Original tile samples with elevation data
            user_profile: User profile with wallet address
            activity_id: Activity UUID

        Returns:
            List of VaultCompletion records for matched vaults
        """
        if not self.vault_cache.is_loaded:
            logger.warning("Vault cache not loaded, skipping vault matching")
            return []

        completions: List[VaultCompletion] = []

        for pattern in climb_patterns:
            # Initialize decision trace
            trace = {
                "detector": {"algorithm": self.climb_algorithm},
                "detection": {
                    "persistence_m": pattern.persistence_m,
                    "effort_bounds": [pattern.start_offset_s, pattern.end_offset_s],
                },
                "signatures": {
                    "v1_present": pattern.signature_hex is not None,
                    "v2_present": pattern.signature_v2_hex is not None,
                },
                "match_attempts": [],
                "best_match": None,
                "abstention": {
                    "eligible": pattern.economic_eligible,
                    "reasons": pattern.abstention_reasons or [],
                },
                "economic_action": None,
            }

            try:
                pattern.indexed_vault_id = None
                pattern.indexed_vault_name = None
                has_reward_evidence = bool(pattern.signature_v2_hex) and all(
                    getattr(pattern, field, None) is not None
                    for field in ("start_lat", "start_lon", "end_lat", "end_lon")
                )
                if not has_reward_evidence:
                    reasons = list(pattern.abstention_reasons or [])
                    if "MATCH:geographic_v2_required" not in reasons:
                        reasons.append("MATCH:geographic_v2_required")
                    pattern.abstention_reasons = reasons
                    pattern.economic_eligible = False
                    trace["match_attempts"].append(
                        {
                            "method": "geographic_v2",
                            "result": "abstain",
                            "reason": "missing_signature_or_endpoint",
                        }
                    )
                    trace["abstention"] = {
                        "eligible": False,
                        "reasons": reasons,
                    }
                    continue

                matches = self._find_matches_reward_grade(
                    signature_v2_hex=pattern.signature_v2_hex,
                    start_lat=pattern.start_lat,
                    start_lon=pattern.start_lon,
                    end_lat=pattern.end_lat,
                    end_lon=pattern.end_lon,
                )
                match_method = "geographic_v2"

                if not matches:
                    trace["match_attempts"].append(
                        {"method": match_method, "result": "no_match"}
                    )
                    pattern.match_trace = trace
                    continue

                if len(matches) > 1:
                    reasons = list(pattern.abstention_reasons or [])
                    reason = "MATCH:ambiguous_active_vaults"
                    if reason not in reasons:
                        reasons.append(reason)
                    pattern.abstention_reasons = reasons
                    pattern.economic_eligible = False
                    trace["match_attempts"].append(
                        {
                            "method": match_method,
                            "result": "abstain",
                            "reason": "multiple_active_vaults",
                            "candidate_vault_ids": [
                                match[0].id for match in matches
                            ],
                        }
                    )
                    trace["abstention"] = {
                        "eligible": False,
                        "reasons": reasons,
                    }
                    pattern.match_trace = trace
                    continue

                # Take best match (IndexedVault, similarity)
                best_vault, similarity = matches[0]

                # Record match in trace
                trace["match_attempts"].append({
                    "method": match_method,
                    "vault_id": best_vault.id,
                    "vault_name": best_vault.name,
                    "similarity": round(similarity, 4),
                })
                trace["best_match"] = {
                    "vault_id": best_vault.id,
                    "vault_name": best_vault.name,
                    "similarity": round(similarity, 4),
                    "method": match_method,
                }

                logger.info(
                    f"Vault match: {best_vault.name} "
                    f"(id={best_vault.id}, similarity={similarity:.2f}, "
                    f"method={match_method})"
                )

                # Store match metadata on pattern regardless of abstention
                pattern.indexed_vault_id = best_vault.id
                pattern.indexed_vault_name = best_vault.name
                pattern.vault_match_similarity = similarity
                pattern.is_strong_match = similarity >= 0.95

                # Check abstention before economic action
                if not pattern.economic_eligible:
                    logger.info(
                        f"[Abstention] Climb {pattern.id} matched {best_vault.name} "
                        f"but abstained: {pattern.abstention_reasons}"
                    )
                    pattern.match_trace = trace
                    continue

                # Check if this would be a new KOM
                is_new_kom = (
                    best_vault.kom_time_s == 0 or
                    pattern.time_s < best_vault.kom_time_s
                )

                trace["economic_action"] = {
                    "type": "vault_completion",
                    "is_new_kom": is_new_kom,
                }

                # Create completion record
                completion = VaultCompletion(
                    vault_id=best_vault.id,
                    vault_name=best_vault.name,
                    climb_pattern_id=pattern.id,
                    similarity=similarity,
                    completion_time_s=pattern.time_s,
                    is_new_kom=is_new_kom,
                )
                completions.append(completion)

            except InvalidRewardGradeQuery as e:
                reasons = list(pattern.abstention_reasons or [])
                reason = "MATCH:invalid_geographic_evidence"
                if reason not in reasons:
                    reasons.append(reason)
                pattern.abstention_reasons = reasons
                pattern.economic_eligible = False
                trace["abstention"] = {"eligible": False, "reasons": reasons}
                trace["error"] = str(e)
                logger.warning(
                    "Invalid climb geography; withholding vault economics: %s",
                    e,
                )
            except RewardGradeMatcherError as e:
                reasons = list(pattern.abstention_reasons or [])
                failure_reason = (
                    "MATCH:matcher_unavailable"
                    if isinstance(e, RewardGradeMatcherUnavailable)
                    else "MATCH:matcher_failure"
                )
                if failure_reason not in reasons:
                    reasons.append(failure_reason)
                pattern.abstention_reasons = reasons
                pattern.economic_eligible = False
                trace["abstention"] = {"eligible": False, "reasons": reasons}
                trace["error"] = str(e)
                logger.error("Reward-grade vault matcher unavailable: %s", e)
                raise
            except Exception as e:
                logger.error(f"Vault matching failed for climb pattern: {e}")
                trace["error"] = str(e)
            finally:
                pattern.match_trace = trace

        if completions:
            logger.info(f"Matched {len(completions)} vault(s) for activity {activity_id}")

        return completions

    def _find_matches_reward_grade(
        self,
        signature_v2_hex: str,
        start_lat: float,
        start_lon: float,
        end_lat: float,
        end_lon: float,
    ) -> List[tuple]:
        """Find cached vaults through the shared reward-grade v2 matcher."""
        validate_reward_grade_v2_native(
            signature_v2_hex=signature_v2_hex,
            role="query",
        )
        if not self.vault_cache.is_loaded:
            return []

        matches = []
        for vault in self.vault_cache._vaults.values():
            if not is_reward_authoritative_vault(vault):
                continue
            if not vault.signature_v2_hex or any(
                getattr(vault, field, None) is None
                for field in ("start_lat", "start_lon", "end_lat", "end_lon")
            ):
                continue

            try:
                evidence = match_reward_grade_v2(
                    query_signature_v2_hex=signature_v2_hex,
                    candidate_signature_v2_hex=vault.signature_v2_hex,
                    query_start=(start_lat, start_lon),
                    query_end=(end_lat, end_lon),
                    candidate_start=(vault.start_lat, vault.start_lon),
                    candidate_end=(vault.end_lat, vault.end_lon),
                )
            except RewardGradeMatcherError:
                raise
            except InvalidRewardGradeCandidate as exc:
                logger.warning(
                    "Invalid geographic v2 evidence for cached vault %s: %s",
                    vault.id,
                    exc,
                )
                continue
            if evidence is not None and evidence.similarity >= VAULT_MIN_SIMILARITY:
                matches.append((vault, evidence.similarity))

        matches.sort(key=lambda match: (-match[1], match[0].id))
        return matches


# Singleton instance for convenience
_default_engine: Optional[PatternEngine] = None


def get_pattern_engine() -> PatternEngine:
    """Get or create the default pattern engine instance."""
    global _default_engine
    if _default_engine is None:
        _default_engine = PatternEngine()
    return _default_engine


async def detect_patterns(
    activity_id: uuid.UUID,
    tile_samples: List[Dict],
    user_profile: UserProfile,
    wallet_tile_history: Set[str],
    raw_climb_samples: Optional[List[Dict]] = None,
    **kwargs,
) -> PatternResults:
    """
    Convenience function to detect patterns using default engine.

    See PatternEngine.detect_patterns for full documentation.
    """
    engine = get_pattern_engine()
    return await engine.detect_patterns(
        activity_id=activity_id,
        tile_samples=tile_samples,
        raw_climb_samples=raw_climb_samples,
        user_profile=user_profile,
        wallet_tile_history=wallet_tile_history,
        **kwargs,
    )
