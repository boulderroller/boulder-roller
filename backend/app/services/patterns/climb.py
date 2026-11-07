"""
ClimbPattern Detection Algorithm

Detects sustained climbing efforts from tile samples with elevation data.

Pattern Philosophy:
- Captures "I did a substantive climb in this area"
- Route-agnostic: any path through the Arena counts
- Effort-based: vertical gain is the primary metric
- Robust to GPS noise and brief descents

Algorithm:
1. Filter/sort samples with elevation (optionally by Arena)
2. Smooth elevation to reduce GPS noise
3. Segment distinct climbs using a drawdown threshold:
   - Track a running peak since the last "valley"
   - When elevation drops from that peak by > drop_tolerance_m, the climb is ended
4. Emit all qualifying climbs; `detect()` returns the best one (max vert, then min time)

Terrain-Adaptive Detection:
- Uses Rust workout_parse module for high-performance terrain classification
- Automatically adapts thresholds based on terrain type:
  - Flat: 15m min vert, 2% min gradient, 150 VAM
  - Rolling: 25m min vert, 2.5% min gradient, 200 VAM
  - Hilly: 50m min vert, 4% min gradient, 300 VAM (default)
  - Mountainous: 100m min vert, 5% min gradient, 400 VAM
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Set, Tuple

from ..sample_time import infer_sample_time_base, sample_time_seconds
from ..sensor_integrity import SensorIntegrityReport, compute_sensor_integrity
from .climb_profile import RideClimbProfile, build_ride_climb_profile

if TYPE_CHECKING:
    from app.services.patterns.climb_signature import ClimbSignatureGenerator

logger = logging.getLogger(__name__)

# Try to import Rust workout_parse for terrain-adaptive detection
_workout_parse = None


def _get_workout_parse():
    """Lazy import workout_parse module."""
    global _workout_parse
    if _workout_parse is None:
        try:
            import workout_parse
            _workout_parse = workout_parse
        except ImportError:
            pass
    return _workout_parse


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in meters between two lat/lon points."""
    R = 6371000  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _infer_detector_time_base(*sample_sets: Optional[Iterable[Dict]]) -> Any:
    for samples in sample_sets:
        if samples is None:
            continue
        base_time = infer_sample_time_base(samples)
        if base_time is not None:
            return base_time
    return None


def _time_offset_s(value: Any, *, base_time: Any = None, fallback: int = 0) -> int:
    seconds = sample_time_seconds(value, base_time=base_time)
    if seconds is None:
        return fallback
    return max(0, int(round(seconds)))


def _normalize_detector_sample_times(
    samples: List[Dict],
    *,
    base_time: Any = None,
) -> List[Dict]:
    if not samples:
        return []

    normalized: List[Dict] = []
    for sample in samples:
        seconds = sample_time_seconds(sample.get("t", 0), base_time=base_time)
        if seconds is None:
            normalized.append(sample)
            continue

        current_t = sample.get("t")
        if isinstance(current_t, (int, float)) and float(current_t) == seconds:
            normalized.append(sample)
            continue

        next_sample = dict(sample)
        next_sample["t"] = seconds
        normalized.append(next_sample)

    return normalized


@dataclass
class RejectedSegment:
    """
    A segment that was considered but rejected by the climb detector.

    Used for debugging and algorithm transparency.
    """
    start_time_s: int
    end_time_s: int
    vert_m: float
    time_s: int
    vam: float  # Vertical Ascent Meters per hour
    avg_gradient_pct: Optional[float]
    rejection_reason: str  # Why it was rejected
    rejection_details: Dict  # Additional context

    def to_dict(self) -> Dict:
        return {
            "start_time_s": self.start_time_s,
            "end_time_s": self.end_time_s,
            "vert_m": round(self.vert_m, 1),
            "time_s": self.time_s,
            "vam": round(self.vam, 0),
            "avg_gradient_pct": round(self.avg_gradient_pct, 1) if self.avg_gradient_pct else None,
            "rejection_reason": self.rejection_reason,
            "rejection_details": self.rejection_details,
        }


@dataclass
class ClimbDetectionDebug:
    """
    Debug information for a detected climb.

    Shows why the segment was accepted and the detection parameters used.
    """
    gradient_start_idx: int  # Where gradient threshold was crossed
    peak_idx: int  # Where the elevation peak occurred
    drop_triggered_at_idx: Optional[int]  # Where drop tolerance ended the climb
    pre_trim_start_idx: int  # Start before gradient trimming
    pre_trim_end_idx: int  # End before gradient trimming
    trimmed_samples: int  # How many samples were trimmed
    subsegment_extracted: bool  # Whether VAM sub-segment extraction was used
    vam: float  # Final VAM value
    thresholds_used: Dict  # The thresholds that were applied
    algorithm: str = "legacy"  # Which algorithm detected this ("legacy" or "momentum")
    momentum_peak: Optional[float] = None  # Peak momentum value during climb
    momentum_at_start: Optional[float] = None  # Momentum when climb started
    momentum_at_end: Optional[float] = None  # Momentum when climb ended

    def to_dict(self) -> Dict:
        result = {
            "gradient_start_idx": self.gradient_start_idx,
            "peak_idx": self.peak_idx,
            "drop_triggered_at_idx": self.drop_triggered_at_idx,
            "pre_trim_start_idx": self.pre_trim_start_idx,
            "pre_trim_end_idx": self.pre_trim_end_idx,
            "trimmed_samples": self.trimmed_samples,
            "subsegment_extracted": self.subsegment_extracted,
            "vam": round(self.vam, 0),
            "thresholds_used": self.thresholds_used,
            "algorithm": self.algorithm,
        }
        if self.momentum_peak is not None:
            result["momentum_peak"] = round(self.momentum_peak, 2)
        if self.momentum_at_start is not None:
            result["momentum_at_start"] = round(self.momentum_at_start, 2)
        if self.momentum_at_end is not None:
            result["momentum_at_end"] = round(self.momentum_at_end, 2)
        return result


@dataclass
class ClimbPattern:
    """
    A detected climb pattern from an activity.

    Represents a sustained climbing effort that meets minimum
    vertical gain and time constraints.
    """

    vert_m: float  # Total vertical gain in meters
    time_s: int  # Duration in seconds
    avg_power_w: Optional[float] = None  # Average power during climb
    w_per_kg: Optional[float] = None  # Watts per kilogram (if power and weight available)
    avg_hr: Optional[int] = None  # Average heart rate
    start_time_offset_s: int = 0  # Offset from activity start
    end_time_offset_s: int = 0  # Offset from activity start
    arena_id: Optional[str] = None  # Arena this climb occurred in
    tile_ids: Optional[List[str]] = None  # H3 tile IDs for this climb segment
    avg_gradient_pct: Optional[float] = None  # Average gradient percentage
    distance_m: Optional[float] = None  # Horizontal distance in meters
    debug: Optional[ClimbDetectionDebug] = None  # Debug info for algorithm transparency
    signature_hex: Optional[str] = None  # 64-byte signature as hex (for vault matching)
    # Vault match fields (populated by vault matching in ride_processor)
    vault_climb_id: Optional[str] = None  # UUID of matched canonical climb
    vault_climb_name: Optional[str] = None  # Name of matched climb (e.g., "Manayunk Wall")
    vault_climb_slug: Optional[str] = None  # URL-friendly slug
    vault_match_similarity: Optional[float] = None  # Similarity score (0.0-1.0)
    is_strong_match: Optional[bool] = None  # True if above vault's threshold
    detector_mode: Optional[str] = None  # Source path used to choose this climb
    signature_v2_hex: Optional[str] = None
    start_lat: Optional[float] = None
    start_lon: Optional[float] = None
    end_lat: Optional[float] = None
    end_lon: Optional[float] = None
    persistence: Optional[float] = None
    confidence: Optional[float] = None
    confidence_reasons: Optional[List[str]] = None
    proposal_sources: Optional[List[str]] = None
    source_quality: Optional[Dict] = None
    route_profile: Optional[Dict] = None

    def calculate_uci_category(self) -> Optional[str]:
        from ..climb_read_metrics import climb_category
        return climb_category(self.distance_m, self.avg_gradient_pct)

    def to_dict(self) -> Dict:
        """Convert to dictionary for storage/serialization."""
        result = {
            "vert_m": round(self.vert_m, 1),
            "time_s": self.time_s,
            "avg_power_w": round(self.avg_power_w, 1) if self.avg_power_w else None,
            "w_per_kg": round(self.w_per_kg, 2) if self.w_per_kg else None,
            "avg_hr": self.avg_hr,
            "start_time_offset_s": self.start_time_offset_s,
            "end_time_offset_s": self.end_time_offset_s,
            "arena_id": self.arena_id,
            "tile_ids": self.tile_ids,
            "avg_gradient_pct": round(self.avg_gradient_pct, 1) if self.avg_gradient_pct else None,
            "distance_m": round(self.distance_m, 0) if self.distance_m else None,
            "category": self.calculate_uci_category(),
        }
        if self.signature_hex:
            result["signature_hex"] = self.signature_hex
        if self.debug:
            result["debug"] = self.debug.to_dict()
        if self.detector_mode:
            result["detector_mode"] = self.detector_mode
        if self.confidence is not None:
            result["confidence"] = round(self.confidence, 2)
        if self.confidence_reasons:
            result["confidence_reasons"] = self.confidence_reasons
        if self.proposal_sources:
            result["proposal_sources"] = self.proposal_sources
        if self.source_quality:
            result["source_quality"] = self.source_quality
        if self.route_profile:
            result["route_profile"] = self.route_profile
        # Vault match info
        if self.vault_climb_id:
            result["vault_match"] = {
                "vault_climb_id": str(self.vault_climb_id),
                "name": self.vault_climb_name,
                "slug": self.vault_climb_slug,
                "similarity": round(self.vault_match_similarity, 2) if self.vault_match_similarity else None,
                "is_strong_match": self.is_strong_match,
            }
        return result


@dataclass
class RideQualityProfile:
    """Per-ride detector quality profile used by the canonical chooser."""

    source_class: str
    integrity_score: float
    gps_coverage: float
    elev_coverage: float
    median_interval_s: float
    sampling_regularity: float
    gap_ratio: float
    gps_jump_count: int
    sparse_sampling: bool
    degraded_gps: bool
    degraded_elevation: bool
    flags: List[str] = field(default_factory=list)

    @classmethod
    def from_tile_samples(cls, tile_samples: List[Dict]) -> "RideQualityProfile":
        report = compute_sensor_integrity(tile_samples)
        source_class = _infer_quality_source_class(report)
        return cls(
            source_class=source_class,
            integrity_score=report.integrity_score,
            gps_coverage=report.gps_coverage,
            elev_coverage=report.elev_coverage,
            median_interval_s=report.median_interval_s,
            sampling_regularity=report.sampling_regularity,
            gap_ratio=report.gap_ratio,
            gps_jump_count=report.gps_jump_count,
            sparse_sampling=report.median_interval_s >= 3.0 or report.gap_ratio >= 0.10,
            degraded_gps=report.gps_coverage < 0.90 or report.gps_jump_count > 0,
            degraded_elevation=report.elev_coverage < 0.90 or not report.elev_plausible,
            flags=list(report.flags),
        )

    def to_dict(self) -> Dict:
        return {
            "source_class": self.source_class,
            "integrity_score": round(self.integrity_score, 3),
            "gps_coverage": round(self.gps_coverage, 3),
            "elev_coverage": round(self.elev_coverage, 3),
            "median_interval_s": round(self.median_interval_s, 2),
            "sampling_regularity": round(self.sampling_regularity, 3),
            "gap_ratio": round(self.gap_ratio, 3),
            "gps_jump_count": self.gps_jump_count,
            "sparse_sampling": self.sparse_sampling,
            "degraded_gps": self.degraded_gps,
            "degraded_elevation": self.degraded_elevation,
            "flags": self.flags,
        }


@dataclass
class ClimbCandidate:
    """Normalized proposal used by canonical_v2."""

    climb: ClimbPattern
    source: str
    family: str
    ride_quality: RideQualityProfile
    terrain_class: Optional[str] = None
    ride_total_gain_m: Optional[float] = None
    corroborating_sources: List[str] = field(default_factory=list)
    ride_avg_power_w: Optional[float] = None
    corroborating_families: List[str] = field(default_factory=list)
    base_score: float = 0.0
    total_score: float = 0.0
    acceptance_threshold: float = 0.0
    reasons: List[str] = field(default_factory=list)
    tile_samples: Optional[List[Dict]] = None
    frequency_map: Optional[Dict[str, int]] = None
    weak_raw_persistence_support_count: int = 0
    selectable: bool = True

    @property
    def start_s(self) -> int:
        return self.climb.start_time_offset_s

    @property
    def end_s(self) -> int:
        return self.climb.end_time_offset_s

    @property
    def duration_s(self) -> int:
        return max(1, self.end_s - self.start_s)


class ClimbPatternDetector:
    """
    Detects ClimbPattern from tile samples with elevation data.

    Configurable thresholds allow tuning for different contexts:
    - Longer climbs (e.g., mountain passes): higher vert_min, longer time_max
    - Shorter punchy climbs (e.g., urban): lower vert_min, shorter time_max
    """

    # Default configuration (based on TILE_ATTESTATION_ARCHITECTURE.md)
    DEFAULT_VERT_MIN_M = 50  # Minimum vertical gain
    DEFAULT_DROP_TOLERANCE_M = 30  # Max allowed descent within climb
    DEFAULT_TIME_MIN_S = 120  # 2 minutes minimum
    DEFAULT_TIME_MAX_S = 3600  # 60 minutes maximum
    DEFAULT_SMOOTHING_WINDOW = 5  # Samples to smooth elevation noise

    # Gradient trimming configuration
    MIN_CLIMB_GRADIENT_PCT = 4.0  # Minimum gradient to be considered "climbing" (raised from 3%)
    GRADIENT_WINDOW = 5  # Samples to average for gradient calculation (increased for smoothing)
    MAX_TRIM_RATIO = 0.7  # Allow trimming up to 70% of segment (more aggressive)

    # Minimum VAM (vertical ascent meters per hour) to qualify as a climb
    # Filters out rolling terrain with cumulative gain but low intensity
    # 300 VAM ≈ 2.5% sustained gradient at ~12 km/h cycling speed
    MIN_CLIMB_VAM = 300

    # Gradient-based segmentation thresholds (with hysteresis)
    GRADIENT_START_THRESHOLD = 3.0  # Start climb when gradient >= 3%
    GRADIENT_END_THRESHOLD = -1.0   # End climb only when actively descending (negative gradient)
    GRADIENT_CALC_WINDOW = 15       # Samples for gradient smoothing (larger = more forgiving)
    GRADIENT_END_PERSISTENCE = 5    # Must see N consecutive samples below threshold to end

    # Gradient Momentum Model parameters
    # Momentum accumulates when climbing, drains when flat/descending
    MOMENTUM_CLIMB_RATE = 0.15      # How fast momentum builds when climbing
    MOMENTUM_DRAIN_RATE = 0.25      # How fast momentum drains when not climbing (faster drain)
    MOMENTUM_DECAY_RATE = 0.985     # Passive decay per sample on flat terrain
    MOMENTUM_START_THRESHOLD = 2.5  # Momentum level to trigger climb start
    MOMENTUM_END_THRESHOLD = 0.3    # Momentum level to trigger climb end
    MOMENTUM_MAX = 12.0             # Cap to prevent runaway accumulation
    MOMENTUM_GRADIENT_NEUTRAL = 1.5 # Gradient below this is "neutral" (slow decay)

    # Convolution kernels for precise boundary detection
    # These detect the "shape" of climb starts and ends
    CLIMB_START_KERNEL = [-2, -1.5, -1, -0.5, 0, 1, 2, 3, 4, 5]
    CLIMB_END_KERNEL = [5, 4, 3, 2, 1, 0, -1, -2, -3, -4]

    def __init__(
        self,
        vert_min_m: float = DEFAULT_VERT_MIN_M,
        drop_tolerance_m: float = DEFAULT_DROP_TOLERANCE_M,
        time_min_s: int = DEFAULT_TIME_MIN_S,
        time_max_s: int = DEFAULT_TIME_MAX_S,
        smoothing_window: int = DEFAULT_SMOOTHING_WINDOW,
        algorithm: str = "legacy",  # "legacy" or "momentum"
        smart_trim: bool = False,  # Use convolution-based boundary detection
        generate_signatures: bool = True,  # Generate 64-byte climb signatures for vault matching
    ):
        """
        Initialize climb pattern detector with configurable thresholds.

        Args:
            vert_min_m: Minimum vertical gain to qualify as a climb
            drop_tolerance_m: Maximum allowed descent within a climb window
            time_min_s: Minimum duration for a climb
            time_max_s: Maximum duration for a climb
            smoothing_window: Number of samples for elevation smoothing
            algorithm: Detection algorithm - "legacy" (gradient+drop) or "momentum" (physics-based)
            smart_trim: Use convolution kernels for precise boundary detection
            generate_signatures: Generate 64-byte signatures for vault matching
        """
        self.vert_min_m = vert_min_m
        self.drop_tolerance_m = drop_tolerance_m
        self.time_min_s = time_min_s
        self.time_max_s = time_max_s
        self.smoothing_window = smoothing_window
        self.algorithm = algorithm
        self.smart_trim = smart_trim
        self.generate_signatures = generate_signatures
        self._signature_generator = None

    def _get_signature_generator(self):
        """Lazy-load signature generator to avoid circular imports."""
        if self._signature_generator is None and self.generate_signatures:
            from app.services.patterns.climb_signature import ClimbSignatureGenerator
            self._signature_generator = ClimbSignatureGenerator()
        return self._signature_generator

    def _generate_signature_for_segment(
        self,
        samples: List[dict],
        smoothed_elevations: List[float],
        start_idx: int,
        end_idx: int,
    ) -> Optional[str]:
        """Generate 64-byte signature hex for a climb segment."""
        if not self.generate_signatures:
            return None

        gen = self._get_signature_generator()
        if gen is None:
            return None

        try:
            segment_samples = samples[start_idx:end_idx + 1]
            segment_elevations = smoothed_elevations[start_idx:end_idx + 1]

            if len(segment_samples) < 2:
                return None

            timestamps = [int(s["t"]) for s in segment_samples]

            # Use lat/lon for distances if available
            distances = None
            if all(s.get("lat") is not None and s.get("lon") is not None for s in segment_samples):
                distances = [0.0]
                for i in range(1, len(segment_samples)):
                    d = _haversine_m(
                        segment_samples[i-1]["lat"], segment_samples[i-1]["lon"],
                        segment_samples[i]["lat"], segment_samples[i]["lon"]
                    )
                    distances.append(distances[-1] + d)

            sig = gen.generate(segment_elevations, timestamps, distances)
            return sig.hex
        except Exception:
            return None

    def detect(
        self,
        tile_samples: List[dict],
        arena_tiles: Optional[Set[str]] = None,
        user_weight_kg: Optional[float] = None,
    ) -> Optional[ClimbPattern]:
        """
        Detect the best climb pattern from tile samples.

        Args:
            tile_samples: List of dicts with keys:
                - t: int (seconds since ride start)
                - tile_id: str (H3 index)
                - elevation_m: float (optional)
                - power_w: int (optional)
                - hr_bpm: int (optional)
            arena_tiles: Optional set of tile IDs defining the Arena.
                         If provided, only samples in Arena count.
                         If None, uses "World Arena" (all tiles count).
            user_weight_kg: Optional user weight for w/kg calculation

        Returns:
            ClimbPattern if a qualifying climb is found, None otherwise

        Algorithm:
        Returns the best climb from `detect_all()`, ranked by:
        - max vertical gain (vert_m), then
        - min duration (time_s)
        """
        climbs = self.detect_all(
            tile_samples=tile_samples,
            arena_tiles=arena_tiles,
            user_weight_kg=user_weight_kg,
        )
        if not climbs:
            return None
        return max(climbs, key=lambda c: (c.vert_m, -c.time_s))

    def detect_all(
        self,
        tile_samples: List[dict],
        arena_tiles: Optional[Set[str]] = None,
        user_weight_kg: Optional[float] = None,
        max_climbs: int = 25,
    ) -> List[ClimbPattern]:
        """
        Detect all climb patterns from tile samples.

        Returns climbs in chronological order (by start time).
        """
        sample_time_base = _infer_detector_time_base(tile_samples)
        tile_samples = _normalize_detector_sample_times(
            tile_samples,
            base_time=sample_time_base,
        )
        samples_with_elev = [s for s in tile_samples if s.get("elevation_m") is not None]
        if len(samples_with_elev) < 2:
            return []

        if arena_tiles is not None:
            samples_with_elev = [s for s in samples_with_elev if s.get("tile_id") in arena_tiles]
        if len(samples_with_elev) < 2:
            return []

        samples_with_elev = sorted(samples_with_elev, key=lambda s: s["t"])

        smoothed_elevations = self._smooth_elevations(
            [float(s["elevation_m"]) for s in samples_with_elev]
        )

        # Choose segmentation algorithm
        if self.algorithm == "momentum":
            segments = self._segment_climbs_momentum(samples_with_elev, smoothed_elevations)
        else:
            segments = self._segment_climbs(samples_with_elev, smoothed_elevations)
        if not segments:
            return []

        # Precompute cumulative ascent for recalculating vert after trim
        cumulative_ascent: List[float] = [0.0] * len(samples_with_elev)
        for i in range(1, len(samples_with_elev)):
            delta = smoothed_elevations[i] - smoothed_elevations[i - 1]
            cumulative_ascent[i] = cumulative_ascent[i - 1] + (delta if delta > 0 else 0.0)

        def _vert_gain(start: int, end: int) -> float:
            if end <= start:
                return 0.0
            return cumulative_ascent[end] - cumulative_ascent[start]

        # Precompute gradients for smart trimming
        gradients: List[float] = []
        if self.smart_trim:
            for i in range(len(samples_with_elev)):
                gradients.append(self._calculate_local_gradient(samples_with_elev, smoothed_elevations, i))

        climbs: List[ClimbPattern] = []
        for start_idx, end_idx, vert_m, time_s in segments:
            # Trim flat run-ins and run-outs
            if self.smart_trim and gradients:
                trimmed_start, trimmed_end = self._smart_trim_boundaries(
                    samples_with_elev, smoothed_elevations, gradients, start_idx, end_idx
                )
            else:
                trimmed_start, trimmed_end = self._trim_climb_segment(
                    samples_with_elev, smoothed_elevations, start_idx, end_idx
                )

            # Recalculate metrics for trimmed segment
            trimmed_time_s = (
                int(round(float(samples_with_elev[trimmed_end]["t"])))
                - int(round(float(samples_with_elev[trimmed_start]["t"])))
            )
            trimmed_vert_m = _vert_gain(trimmed_start, trimmed_end)

            # Re-validate trimmed segment meets thresholds
            if trimmed_time_s < self.time_min_s or trimmed_time_s > self.time_max_s:
                continue
            if trimmed_vert_m < self.vert_min_m:
                continue

            # Check VAM (vertical ascent meters per hour) to filter rolling terrain
            # VAM = (vert_m / time_s) * 3600
            trimmed_vam = (trimmed_vert_m / trimmed_time_s) * 3600 if trimmed_time_s > 0 else 0
            if trimmed_vam < self.MIN_CLIMB_VAM:
                # Before rejecting, try to find a high-VAM sub-segment within
                # (real climbs often hide at the end of rolling approaches)
                sub_result = self._find_high_vam_subsegment(
                    samples_with_elev, smoothed_elevations, cumulative_ascent,
                    trimmed_start, trimmed_end, _vert_gain
                )
                if sub_result is None:
                    continue
                trimmed_start, trimmed_end = sub_result
                # Recalculate metrics for the sub-segment
                trimmed_time_s = (
                    int(round(float(samples_with_elev[trimmed_end]["t"])))
                    - int(round(float(samples_with_elev[trimmed_start]["t"])))
                )
                trimmed_vert_m = _vert_gain(trimmed_start, trimmed_end)
                trimmed_vam = (trimmed_vert_m / trimmed_time_s) * 3600 if trimmed_time_s > 0 else 0

            window_samples = samples_with_elev[trimmed_start : trimmed_end + 1]
            avg_power_w = self._calculate_average(window_samples, "power_w")
            avg_hr = self._calculate_average(window_samples, "hr_bpm")

            w_per_kg = None
            if avg_power_w is not None and user_weight_kg is not None and user_weight_kg > 0:
                w_per_kg = avg_power_w / user_weight_kg

            # Extract unique tile IDs for this climb segment (preserving order)
            seen_tiles: Set[str] = set()
            tile_ids: List[str] = []
            for sample in window_samples:
                tile_id = sample.get("tile_id")
                if tile_id and tile_id not in seen_tiles:
                    seen_tiles.add(tile_id)
                    tile_ids.append(tile_id)

            # Calculate horizontal distance (for gradient and UCI category)
            distance_m = self._calculate_segment_distance(window_samples)

            # Calculate average gradient
            avg_gradient_pct = None
            if distance_m and distance_m > 0:
                avg_gradient_pct = (trimmed_vert_m / distance_m) * 100.0

            # Generate signature if enabled
            signature_hex = self._generate_signature_for_segment(
                samples_with_elev, smoothed_elevations, trimmed_start, trimmed_end
            )

            climbs.append(
                ClimbPattern(
                    vert_m=trimmed_vert_m,
                    time_s=trimmed_time_s,
                    avg_power_w=avg_power_w,
                    w_per_kg=w_per_kg,
                    avg_hr=int(avg_hr) if avg_hr is not None else None,
                    start_time_offset_s=int(round(float(window_samples[0]["t"]))),
                    end_time_offset_s=int(round(float(window_samples[-1]["t"]))),
                    arena_id=None,
                    tile_ids=tile_ids if tile_ids else None,
                    avg_gradient_pct=avg_gradient_pct,
                    distance_m=distance_m,
                    signature_hex=signature_hex,
                )
            )

            if len(climbs) >= max_climbs:
                break

        return climbs

    def detect_all_with_debug(
        self,
        tile_samples: List[dict],
        arena_tiles: Optional[Set[str]] = None,
        user_weight_kg: Optional[float] = None,
        max_climbs: int = 25,
    ) -> Tuple[List[ClimbPattern], List[RejectedSegment]]:
        """
        Detect all climb patterns with full debug information.

        Returns:
            Tuple of (accepted_climbs, rejected_segments) for algorithm transparency.
        """
        sample_time_base = _infer_detector_time_base(tile_samples)
        tile_samples = _normalize_detector_sample_times(
            tile_samples,
            base_time=sample_time_base,
        )
        samples_with_elev = [s for s in tile_samples if s.get("elevation_m") is not None]
        if len(samples_with_elev) < 2:
            return [], []

        if arena_tiles is not None:
            samples_with_elev = [s for s in samples_with_elev if s.get("tile_id") in arena_tiles]
        if len(samples_with_elev) < 2:
            return [], []

        samples_with_elev = sorted(samples_with_elev, key=lambda s: s["t"])

        smoothed_elevations = self._smooth_elevations(
            [float(s["elevation_m"]) for s in samples_with_elev]
        )

        # Choose segmentation algorithm with debug info
        if self.algorithm == "momentum":
            segments = self._segment_climbs_momentum_with_debug(samples_with_elev, smoothed_elevations)
        else:
            segments = self._segment_climbs_with_debug(samples_with_elev, smoothed_elevations)
        if not segments:
            return [], []

        # Precompute cumulative ascent for recalculating vert after trim
        cumulative_ascent: List[float] = [0.0] * len(samples_with_elev)
        for i in range(1, len(samples_with_elev)):
            delta = smoothed_elevations[i] - smoothed_elevations[i - 1]
            cumulative_ascent[i] = cumulative_ascent[i - 1] + (delta if delta > 0 else 0.0)

        def _vert_gain(start: int, end: int) -> float:
            if end <= start:
                return 0.0
            return cumulative_ascent[end] - cumulative_ascent[start]

        def _calc_gradient(start_idx: int, end_idx: int) -> Optional[float]:
            dist = self._calculate_segment_distance(samples_with_elev[start_idx:end_idx + 1])
            if dist and dist > 0:
                return (_vert_gain(start_idx, end_idx) / dist) * 100.0
            return None

        thresholds_used = {
            "algorithm": self.algorithm,
            "smart_trim": self.smart_trim,
            "vert_min_m": self.vert_min_m,
            "time_min_s": self.time_min_s,
            "time_max_s": self.time_max_s,
            "drop_tolerance_m": self.drop_tolerance_m,
            "min_vam": self.MIN_CLIMB_VAM,
            "gradient_start_threshold": self.GRADIENT_START_THRESHOLD,
        }
        if self.algorithm == "momentum":
            thresholds_used.update({
                "momentum_start_threshold": self.MOMENTUM_START_THRESHOLD,
                "momentum_end_threshold": self.MOMENTUM_END_THRESHOLD,
                "momentum_climb_rate": self.MOMENTUM_CLIMB_RATE,
                "momentum_drain_rate": self.MOMENTUM_DRAIN_RATE,
            })

        # Precompute gradients for smart trimming
        gradients: List[float] = []
        if self.smart_trim:
            for i in range(len(samples_with_elev)):
                gradients.append(self._calculate_local_gradient(samples_with_elev, smoothed_elevations, i))

        climbs: List[ClimbPattern] = []
        rejected: List[RejectedSegment] = []

        for seg_info in segments:
            start_idx = seg_info["start_idx"]
            end_idx = seg_info["end_idx"]
            vert_m = seg_info["vert_m"]
            time_s = seg_info["time_s"]

            # Store original indices for debug
            orig_start, orig_end = start_idx, end_idx

            # Trim flat run-ins and run-outs (smart or simple)
            if self.smart_trim and gradients:
                trimmed_start, trimmed_end = self._smart_trim_boundaries(
                    samples_with_elev, smoothed_elevations, gradients, start_idx, end_idx
                )
            else:
                trimmed_start, trimmed_end = self._trim_climb_segment(
                    samples_with_elev, smoothed_elevations, start_idx, end_idx
                )

            # Recalculate metrics for trimmed segment
            trimmed_time_s = (
                int(round(float(samples_with_elev[trimmed_end]["t"])))
                - int(round(float(samples_with_elev[trimmed_start]["t"])))
            )
            trimmed_vert_m = _vert_gain(trimmed_start, trimmed_end)
            trimmed_vam = (trimmed_vert_m / trimmed_time_s) * 3600 if trimmed_time_s > 0 else 0

            # Re-validate trimmed segment meets thresholds
            if trimmed_time_s < self.time_min_s:
                rejected.append(RejectedSegment(
                    start_time_s=int(round(float(samples_with_elev[trimmed_start]["t"]))),
                    end_time_s=int(round(float(samples_with_elev[trimmed_end]["t"]))),
                    vert_m=trimmed_vert_m,
                    time_s=trimmed_time_s,
                    vam=trimmed_vam,
                    avg_gradient_pct=_calc_gradient(trimmed_start, trimmed_end),
                    rejection_reason="time_too_short",
                    rejection_details={"time_s": trimmed_time_s, "min_required": self.time_min_s},
                ))
                continue

            if trimmed_time_s > self.time_max_s:
                rejected.append(RejectedSegment(
                    start_time_s=int(round(float(samples_with_elev[trimmed_start]["t"]))),
                    end_time_s=int(round(float(samples_with_elev[trimmed_end]["t"]))),
                    vert_m=trimmed_vert_m,
                    time_s=trimmed_time_s,
                    vam=trimmed_vam,
                    avg_gradient_pct=_calc_gradient(trimmed_start, trimmed_end),
                    rejection_reason="time_too_long",
                    rejection_details={"time_s": trimmed_time_s, "max_allowed": self.time_max_s},
                ))
                continue

            if trimmed_vert_m < self.vert_min_m:
                rejected.append(RejectedSegment(
                    start_time_s=int(round(float(samples_with_elev[trimmed_start]["t"]))),
                    end_time_s=int(round(float(samples_with_elev[trimmed_end]["t"]))),
                    vert_m=trimmed_vert_m,
                    time_s=trimmed_time_s,
                    vam=trimmed_vam,
                    avg_gradient_pct=_calc_gradient(trimmed_start, trimmed_end),
                    rejection_reason="vert_too_low",
                    rejection_details={"vert_m": trimmed_vert_m, "min_required": self.vert_min_m},
                ))
                continue

            # Check VAM threshold
            subsegment_extracted = False
            if trimmed_vam < self.MIN_CLIMB_VAM:
                # Try to find a high-VAM sub-segment within
                sub_result = self._find_high_vam_subsegment(
                    samples_with_elev, smoothed_elevations, cumulative_ascent,
                    trimmed_start, trimmed_end, _vert_gain
                )
                if sub_result is None:
                    rejected.append(RejectedSegment(
                        start_time_s=int(round(float(samples_with_elev[trimmed_start]["t"]))),
                        end_time_s=int(round(float(samples_with_elev[trimmed_end]["t"]))),
                        vert_m=trimmed_vert_m,
                        time_s=trimmed_time_s,
                        vam=trimmed_vam,
                        avg_gradient_pct=_calc_gradient(trimmed_start, trimmed_end),
                        rejection_reason="vam_too_low",
                        rejection_details={"vam": trimmed_vam, "min_required": self.MIN_CLIMB_VAM},
                    ))
                    continue
                trimmed_start, trimmed_end = sub_result
                subsegment_extracted = True
                # Recalculate metrics for the sub-segment
                trimmed_time_s = (
                    int(round(float(samples_with_elev[trimmed_end]["t"])))
                    - int(round(float(samples_with_elev[trimmed_start]["t"])))
                )
                trimmed_vert_m = _vert_gain(trimmed_start, trimmed_end)
                trimmed_vam = (trimmed_vert_m / trimmed_time_s) * 3600 if trimmed_time_s > 0 else 0

            window_samples = samples_with_elev[trimmed_start : trimmed_end + 1]
            avg_power_w = self._calculate_average(window_samples, "power_w")
            avg_hr = self._calculate_average(window_samples, "hr_bpm")

            w_per_kg = None
            if avg_power_w is not None and user_weight_kg is not None and user_weight_kg > 0:
                w_per_kg = avg_power_w / user_weight_kg

            # Extract unique tile IDs for this climb segment (preserving order)
            seen_tiles: Set[str] = set()
            tile_ids: List[str] = []
            for sample in window_samples:
                tile_id = sample.get("tile_id")
                if tile_id and tile_id not in seen_tiles:
                    seen_tiles.add(tile_id)
                    tile_ids.append(tile_id)

            # Calculate horizontal distance (for gradient and UCI category)
            distance_m = self._calculate_segment_distance(window_samples)

            # Calculate average gradient
            avg_gradient_pct = None
            if distance_m and distance_m > 0:
                avg_gradient_pct = (trimmed_vert_m / distance_m) * 100.0

            # Build debug info
            debug = ClimbDetectionDebug(
                gradient_start_idx=seg_info.get("gradient_start_idx", start_idx),
                peak_idx=seg_info.get("peak_idx", end_idx),
                drop_triggered_at_idx=seg_info.get("drop_triggered_at_idx"),
                pre_trim_start_idx=orig_start,
                pre_trim_end_idx=orig_end,
                trimmed_samples=(orig_end - orig_start) - (trimmed_end - trimmed_start),
                subsegment_extracted=subsegment_extracted,
                vam=trimmed_vam,
                thresholds_used=thresholds_used,
                algorithm=self.algorithm,
                momentum_peak=seg_info.get("momentum_peak"),
                momentum_at_start=seg_info.get("momentum_at_start"),
                momentum_at_end=seg_info.get("momentum_at_end"),
            )

            # Generate signature if enabled
            signature_hex = self._generate_signature_for_segment(
                samples_with_elev, smoothed_elevations, trimmed_start, trimmed_end
            )

            climbs.append(
                ClimbPattern(
                    vert_m=trimmed_vert_m,
                    time_s=trimmed_time_s,
                    avg_power_w=avg_power_w,
                    w_per_kg=w_per_kg,
                    avg_hr=int(avg_hr) if avg_hr is not None else None,
                    start_time_offset_s=int(round(float(window_samples[0]["t"]))),
                    end_time_offset_s=int(round(float(window_samples[-1]["t"]))),
                    arena_id=None,
                    tile_ids=tile_ids if tile_ids else None,
                    avg_gradient_pct=avg_gradient_pct,
                    distance_m=distance_m,
                    debug=debug,
                    signature_hex=signature_hex,
                )
            )

            if len(climbs) >= max_climbs:
                break

        return climbs, rejected

    def _segment_climbs_with_debug(
        self, samples: List[dict], smoothed_elevations: List[float]
    ) -> List[Dict]:
        """
        Segment distinct climbs with debug information.

        Returns list of dicts with segment info including detection details.
        """
        n = len(samples)
        if n < 2:
            return []

        times_s: List[int] = [int(round(float(s["t"]))) for s in samples]

        # Precompute cumulative ascent for O(1) vertical gain per segment.
        cumulative_ascent: List[float] = [0.0] * n
        for i in range(1, n):
            delta = smoothed_elevations[i] - smoothed_elevations[i - 1]
            cumulative_ascent[i] = cumulative_ascent[i - 1] + (delta if delta > 0 else 0.0)

        def _segment_vert_gain(start_idx: int, end_idx: int) -> float:
            if end_idx <= start_idx:
                return 0.0
            return cumulative_ascent[end_idx] - cumulative_ascent[start_idx]

        # Calculate gradient at each point using a smoothing window
        gradients: List[float] = []
        for i in range(n):
            gradient = self._calculate_local_gradient(samples, smoothed_elevations, i)
            gradients.append(gradient)

        segments: List[Dict] = []

        in_climb = False
        climb_start_idx = 0
        peak_idx = 0
        peak_elev = 0.0

        def _maybe_emit(start_idx: int, end_idx: int, drop_idx: Optional[int] = None) -> None:
            if end_idx <= start_idx:
                return

            time_s = times_s[end_idx] - times_s[start_idx]
            if time_s < self.time_min_s or time_s > self.time_max_s:
                return

            vert_m = _segment_vert_gain(start_idx, end_idx)
            if vert_m < self.vert_min_m:
                return

            segments.append({
                "start_idx": start_idx,
                "end_idx": end_idx,
                "vert_m": vert_m,
                "time_s": time_s,
                "gradient_start_idx": start_idx,
                "peak_idx": end_idx,
                "drop_triggered_at_idx": drop_idx,
            })

        for i in range(n):
            gradient = gradients[i]
            elev = smoothed_elevations[i]

            if not in_climb:
                if gradient >= self.GRADIENT_START_THRESHOLD:
                    in_climb = True
                    climb_start_idx = i
                    peak_idx = i
                    peak_elev = elev
            else:
                if elev > peak_elev:
                    peak_elev = elev
                    peak_idx = i

                if (peak_elev - elev) > self.drop_tolerance_m:
                    _maybe_emit(climb_start_idx, peak_idx, i)
                    in_climb = False

        if in_climb:
            _maybe_emit(climb_start_idx, peak_idx, None)

        segments.sort(key=lambda s: (s["start_idx"], s["end_idx"]))
        return segments

    def _smooth_elevations(self, elevations: List[float]) -> List[float]:
        """
        Apply simple moving average smoothing to elevation data.

        GPS elevation data is notoriously noisy. Smoothing helps
        identify true climbing patterns vs noise.

        Args:
            elevations: List of elevation values

        Returns:
            Smoothed elevation values (same length as input)
        """
        if len(elevations) < self.smoothing_window:
            return elevations

        smoothed = []
        for i in range(len(elevations)):
            start = max(0, i - self.smoothing_window // 2)
            end = min(len(elevations), i + self.smoothing_window // 2 + 1)
            window = elevations[start:end]
            smoothed.append(sum(window) / len(window))

        return smoothed

    def _segment_climbs(
        self, samples: List[dict], smoothed_elevations: List[float]
    ) -> List[Tuple[int, int, float, int]]:
        """
        Segment distinct climbs using gradient-based detection with hysteresis.

        Uses gradient thresholds to detect climb boundaries:
        - Climb STARTS when gradient rises above GRADIENT_START_THRESHOLD (3%)
        - Climb ENDS when gradient falls below GRADIENT_END_THRESHOLD (1.5%)

        Hysteresis prevents noise from creating spurious segments.

        Returns a list of (start_idx, end_idx, vert_m, time_s) tuples.
        """
        n = len(samples)
        if n < 2:
            return []

        times_s: List[int] = [int(round(float(s["t"]))) for s in samples]

        # Precompute cumulative ascent for O(1) vertical gain per segment.
        cumulative_ascent: List[float] = [0.0] * n
        for i in range(1, n):
            delta = smoothed_elevations[i] - smoothed_elevations[i - 1]
            cumulative_ascent[i] = cumulative_ascent[i - 1] + (delta if delta > 0 else 0.0)

        def _segment_vert_gain(start_idx: int, end_idx: int) -> float:
            if end_idx <= start_idx:
                return 0.0
            return cumulative_ascent[end_idx] - cumulative_ascent[start_idx]

        # Calculate gradient at each point using a smoothing window
        gradients: List[float] = []
        for i in range(n):
            gradient = self._calculate_local_gradient(samples, smoothed_elevations, i)
            gradients.append(gradient)

        segments: List[Tuple[int, int, float, int]] = []

        # HYBRID APPROACH:
        # - Use GRADIENT to detect climb START (cuts flat run-ins)
        # - Use DROP_TOLERANCE to detect climb END (tolerates mid-climb dips)
        in_climb = False
        climb_start_idx = 0
        peak_idx = 0
        peak_elev = 0.0

        def _maybe_emit(start_idx: int, end_idx: int) -> None:
            if end_idx <= start_idx:
                return

            time_s = times_s[end_idx] - times_s[start_idx]
            if time_s < self.time_min_s or time_s > self.time_max_s:
                return

            vert_m = _segment_vert_gain(start_idx, end_idx)
            if vert_m < self.vert_min_m:
                return

            segments.append((start_idx, end_idx, vert_m, time_s))

        for i in range(n):
            gradient = gradients[i]
            elev = smoothed_elevations[i]

            if not in_climb:
                # Look for climb start using GRADIENT threshold
                if gradient >= self.GRADIENT_START_THRESHOLD:
                    in_climb = True
                    climb_start_idx = i
                    peak_idx = i
                    peak_elev = elev
            else:
                # Update running peak
                if elev > peak_elev:
                    peak_elev = elev
                    peak_idx = i

                # End climb using DROP_TOLERANCE (not gradient)
                # This tolerates mid-climb dips/switchbacks
                if (peak_elev - elev) > self.drop_tolerance_m:
                    _maybe_emit(climb_start_idx, peak_idx)
                    in_climb = False
                    # Don't reset here - let next iteration potentially start new climb

        # Handle climb that extends to end of data
        if in_climb:
            _maybe_emit(climb_start_idx, peak_idx)

        # Preserve chronological order
        segments.sort(key=lambda s: (s[0], s[1]))
        return segments

    def _segment_climbs_momentum(
        self, samples: List[dict], smoothed_elevations: List[float]
    ) -> List[Tuple[int, int, float, int]]:
        """
        Segment climbs using gradient momentum model.

        Physics-inspired approach where:
        - Climbing builds "momentum" (state accumulates)
        - Flat/descending drains momentum
        - Climb starts when momentum exceeds threshold
        - Climb ends when momentum falls below threshold

        This naturally handles:
        - Brief false flats (momentum carries through)
        - GPS noise (doesn't build enough momentum)
        - Gradual transitions (state changes smoothly)
        """
        n = len(samples)
        if n < 2:
            return []

        times_s: List[int] = [int(round(float(s["t"]))) for s in samples]

        # Precompute cumulative ascent
        cumulative_ascent: List[float] = [0.0] * n
        for i in range(1, n):
            delta = smoothed_elevations[i] - smoothed_elevations[i - 1]
            cumulative_ascent[i] = cumulative_ascent[i - 1] + (delta if delta > 0 else 0.0)

        def _segment_vert_gain(start_idx: int, end_idx: int) -> float:
            if end_idx <= start_idx:
                return 0.0
            return cumulative_ascent[end_idx] - cumulative_ascent[start_idx]

        # Calculate gradients at each point
        gradients: List[float] = []
        for i in range(n):
            gradient = self._calculate_local_gradient(samples, smoothed_elevations, i)
            gradients.append(gradient)

        # Run momentum state machine
        momentum = 0.0
        momentum_history: List[float] = []
        in_climb = False
        climb_start_idx = 0
        peak_idx = 0
        peak_elev = 0.0

        segments: List[Tuple[int, int, float, int]] = []

        for i in range(n):
            gradient = gradients[i]
            elev = smoothed_elevations[i]

            # Update momentum based on gradient
            if gradient >= self.GRADIENT_START_THRESHOLD:
                # Strong climbing: build momentum proportional to gradient intensity
                momentum += (gradient - self.MOMENTUM_GRADIENT_NEUTRAL) * self.MOMENTUM_CLIMB_RATE
            elif gradient >= self.MOMENTUM_GRADIENT_NEUTRAL:
                # Gentle climbing: slow build
                momentum += (gradient - self.MOMENTUM_GRADIENT_NEUTRAL) * self.MOMENTUM_CLIMB_RATE * 0.5
            elif gradient <= -1.0:
                # Descending: drain momentum faster
                momentum += gradient * self.MOMENTUM_DRAIN_RATE
            else:
                # Flat/gentle: passive decay
                momentum *= self.MOMENTUM_DECAY_RATE

            # Clamp momentum
            momentum = max(0.0, min(momentum, self.MOMENTUM_MAX))
            momentum_history.append(momentum)

            # State machine with hysteresis
            if not in_climb:
                if momentum >= self.MOMENTUM_START_THRESHOLD:
                    # Climb started
                    in_climb = True
                    # Find where momentum started building (look back)
                    climb_start_idx = self._find_momentum_start(momentum_history, i)
                    peak_idx = i
                    peak_elev = elev
            else:
                # Track running peak
                if elev > peak_elev:
                    peak_elev = elev
                    peak_idx = i

                # Check for climb end
                if momentum <= self.MOMENTUM_END_THRESHOLD:
                    # Momentum exhausted - emit climb
                    self._emit_segment(
                        segments, samples, times_s, cumulative_ascent,
                        climb_start_idx, peak_idx
                    )
                    in_climb = False

                # Also check drop tolerance as backup
                elif (peak_elev - elev) > self.drop_tolerance_m:
                    self._emit_segment(
                        segments, samples, times_s, cumulative_ascent,
                        climb_start_idx, peak_idx
                    )
                    in_climb = False
                    momentum = 0.0  # Reset momentum on hard drop

        # Handle climb extending to end
        if in_climb:
            self._emit_segment(
                segments, samples, times_s, cumulative_ascent,
                climb_start_idx, peak_idx
            )

        segments.sort(key=lambda s: (s[0], s[1]))
        return segments

    def _segment_climbs_momentum_with_debug(
        self, samples: List[dict], smoothed_elevations: List[float]
    ) -> List[Dict]:
        """
        Segment climbs using momentum model with debug information.

        Returns list of dicts with segment info including momentum values.
        """
        n = len(samples)
        if n < 2:
            return []

        times_s: List[int] = [int(round(float(s["t"]))) for s in samples]

        # Precompute cumulative ascent
        cumulative_ascent: List[float] = [0.0] * n
        for i in range(1, n):
            delta = smoothed_elevations[i] - smoothed_elevations[i - 1]
            cumulative_ascent[i] = cumulative_ascent[i - 1] + (delta if delta > 0 else 0.0)

        def _segment_vert_gain(start_idx: int, end_idx: int) -> float:
            if end_idx <= start_idx:
                return 0.0
            return cumulative_ascent[end_idx] - cumulative_ascent[start_idx]

        # Calculate gradients at each point
        gradients: List[float] = []
        for i in range(n):
            gradient = self._calculate_local_gradient(samples, smoothed_elevations, i)
            gradients.append(gradient)

        # Run momentum state machine
        momentum = 0.0
        momentum_history: List[float] = []
        in_climb = False
        climb_start_idx = 0
        peak_idx = 0
        peak_elev = 0.0
        momentum_at_start = 0.0
        momentum_peak = 0.0

        segments: List[Dict] = []

        def _maybe_emit_debug(start_idx: int, end_idx: int, mom_start: float, mom_peak: float, mom_end: float) -> None:
            if end_idx <= start_idx:
                return

            time_s = times_s[end_idx] - times_s[start_idx]
            if time_s < self.time_min_s or time_s > self.time_max_s:
                return

            vert_m = _segment_vert_gain(start_idx, end_idx)
            if vert_m < self.vert_min_m:
                return

            segments.append({
                "start_idx": start_idx,
                "end_idx": end_idx,
                "vert_m": vert_m,
                "time_s": time_s,
                "gradient_start_idx": start_idx,
                "peak_idx": end_idx,
                "drop_triggered_at_idx": None,
                "momentum_at_start": mom_start,
                "momentum_peak": mom_peak,
                "momentum_at_end": mom_end,
            })

        for i in range(n):
            gradient = gradients[i]
            elev = smoothed_elevations[i]

            # Update momentum based on gradient
            if gradient >= self.GRADIENT_START_THRESHOLD:
                momentum += (gradient - self.MOMENTUM_GRADIENT_NEUTRAL) * self.MOMENTUM_CLIMB_RATE
            elif gradient >= self.MOMENTUM_GRADIENT_NEUTRAL:
                momentum += (gradient - self.MOMENTUM_GRADIENT_NEUTRAL) * self.MOMENTUM_CLIMB_RATE * 0.5
            elif gradient <= -1.0:
                momentum += gradient * self.MOMENTUM_DRAIN_RATE
            else:
                momentum *= self.MOMENTUM_DECAY_RATE

            # Clamp momentum
            momentum = max(0.0, min(momentum, self.MOMENTUM_MAX))
            momentum_history.append(momentum)

            # State machine with hysteresis
            if not in_climb:
                if momentum >= self.MOMENTUM_START_THRESHOLD:
                    in_climb = True
                    climb_start_idx = self._find_momentum_start(momentum_history, i)
                    momentum_at_start = momentum_history[climb_start_idx] if climb_start_idx < len(momentum_history) else momentum
                    momentum_peak = momentum
                    peak_idx = i
                    peak_elev = elev
            else:
                # Track running peak
                if elev > peak_elev:
                    peak_elev = elev
                    peak_idx = i
                if momentum > momentum_peak:
                    momentum_peak = momentum

                # Check for climb end
                if momentum <= self.MOMENTUM_END_THRESHOLD:
                    _maybe_emit_debug(climb_start_idx, peak_idx, momentum_at_start, momentum_peak, momentum)
                    in_climb = False
                elif (peak_elev - elev) > self.drop_tolerance_m:
                    _maybe_emit_debug(climb_start_idx, peak_idx, momentum_at_start, momentum_peak, momentum)
                    in_climb = False
                    momentum = 0.0

        # Handle climb extending to end
        if in_climb:
            _maybe_emit_debug(climb_start_idx, peak_idx, momentum_at_start, momentum_peak, momentum)

        segments.sort(key=lambda s: (s["start_idx"], s["end_idx"]))
        return segments

    def _find_momentum_start(self, momentum_history: List[float], current_idx: int) -> int:
        """
        Look back to find where the momentum started building.

        This gives a tighter start boundary than where momentum crossed threshold.
        """
        if current_idx < 2:
            return 0

        # Walk backwards to find where momentum was near zero
        for i in range(current_idx - 1, -1, -1):
            if momentum_history[i] < 0.5:
                return i + 1  # Start at next sample where momentum began building

        return 0

    def _emit_segment(
        self,
        segments: List[Tuple[int, int, float, int]],
        samples: List[dict],
        times_s: List[int],
        cumulative_ascent: List[float],
        start_idx: int,
        end_idx: int,
    ) -> None:
        """Helper to validate and emit a segment."""
        if end_idx <= start_idx:
            return

        time_s = times_s[end_idx] - times_s[start_idx]
        if time_s < self.time_min_s or time_s > self.time_max_s:
            return

        vert_m = cumulative_ascent[end_idx] - cumulative_ascent[start_idx]
        if vert_m < self.vert_min_m:
            return

        segments.append((start_idx, end_idx, vert_m, time_s))

    def _smart_trim_boundaries(
        self,
        samples: List[dict],
        smoothed_elevations: List[float],
        gradients: List[float],
        start_idx: int,
        end_idx: int,
    ) -> Tuple[int, int]:
        """
        Use convolution with shape-matching kernels to find precise boundaries.

        The kernels detect the characteristic "shape" of a climb start/end:
        - Start: transition from flat/descending to climbing
        - End: transition from climbing to flat/descending
        """
        if end_idx - start_idx < len(self.CLIMB_START_KERNEL) * 2:
            # Segment too short for convolution - use simple trim
            return self._trim_climb_segment(samples, smoothed_elevations, start_idx, end_idx)

        # Extract gradient slice for this segment with padding
        pad = len(self.CLIMB_START_KERNEL)
        slice_start = max(0, start_idx - pad)
        slice_end = min(len(gradients), end_idx + pad)
        gradient_slice = gradients[slice_start:slice_end]

        if len(gradient_slice) < len(self.CLIMB_START_KERNEL):
            return self._trim_climb_segment(samples, smoothed_elevations, start_idx, end_idx)

        # Convolve with start kernel
        start_response = self._convolve(gradient_slice, self.CLIMB_START_KERNEL)

        # Convolve with end kernel
        end_response = self._convolve(gradient_slice, self.CLIMB_END_KERNEL)

        # Find best start (highest response in first half)
        search_range_start = max(0, start_idx - slice_start - pad // 2)
        search_range_mid = min(len(start_response), (end_idx - slice_start) // 2 + pad)
        if search_range_mid <= search_range_start:
            best_start_local = 0
        else:
            best_start_local = search_range_start + max(
                range(search_range_mid - search_range_start),
                key=lambda i: start_response[search_range_start + i] if search_range_start + i < len(start_response) else -999
            )

        # Find best end (highest response in second half)
        search_range_end_start = max(0, (end_idx - slice_start) // 2)
        search_range_end_end = min(len(end_response), end_idx - slice_start + pad // 2)
        if search_range_end_end <= search_range_end_start:
            best_end_local = len(end_response) - 1
        else:
            best_end_local = search_range_end_start + max(
                range(search_range_end_end - search_range_end_start),
                key=lambda i: end_response[search_range_end_start + i] if search_range_end_start + i < len(end_response) else -999
            )

        # Convert back to global indices
        new_start = slice_start + best_start_local
        new_end = slice_start + best_end_local

        # Sanity checks
        new_start = max(start_idx - pad, min(new_start, start_idx + (end_idx - start_idx) // 3))
        new_end = max(end_idx - (end_idx - start_idx) // 3, min(new_end, end_idx + pad))

        if new_end <= new_start:
            return start_idx, end_idx

        return new_start, new_end

    def _convolve(self, signal: List[float], kernel: List[float]) -> List[float]:
        """Simple 1D convolution."""
        n = len(signal)
        k = len(kernel)
        result = []
        for i in range(n):
            total = 0.0
            for j in range(k):
                idx = i - k // 2 + j
                if 0 <= idx < n:
                    total += signal[idx] * kernel[j]
            result.append(total)
        return result

    def _calculate_local_gradient(
        self, samples: List[dict], smoothed_elevations: List[float], idx: int
    ) -> float:
        """
        Calculate local gradient (%) at a specific index using a window.

        Uses forward-looking window to detect upcoming gradient changes.
        """
        n = len(samples)
        if idx >= n - 1:
            return 0.0

        # Use a window to smooth out noise
        window = self.GRADIENT_CALC_WINDOW
        end_idx = min(idx + window, n - 1)

        if end_idx <= idx:
            return 0.0

        elev_delta = smoothed_elevations[end_idx] - smoothed_elevations[idx]
        time_delta = float(samples[end_idx]["t"]) - float(samples[idx]["t"])

        if time_delta <= 0:
            return 0.0

        # Estimate horizontal distance (rough: assume ~5m/s average cycling speed)
        # This gives gradient as percentage
        horiz_dist_m = time_delta * 5.0  # meters

        if horiz_dist_m <= 0:
            return 0.0

        gradient_pct = (elev_delta / horiz_dist_m) * 100.0
        return gradient_pct

    def _calculate_average(self, samples: List[dict], field: str) -> Optional[float]:
        """
        Calculate average value of a field across samples.

        Args:
            samples: List of tile samples
            field: Field name to average (e.g., "power_w", "hr_bpm")

        Returns:
            Average value, or None if no data available
        """
        values = [s[field] for s in samples if s.get(field) is not None]
        if not values:
            return None
        return sum(values) / len(values)

    def _calculate_segment_distance(self, samples: List[dict]) -> Optional[float]:
        """
        Calculate horizontal distance for a segment of samples.

        Uses GPS coordinates if available, otherwise estimates from time.

        Args:
            samples: List of tile samples for the segment

        Returns:
            Distance in meters, or None if cannot calculate
        """
        if len(samples) < 2:
            logger.debug(f"[DistCalc] Too few samples: {len(samples)}")
            return None

        total_dist = 0.0
        has_gps = False
        no_gps_count = 0

        for i in range(1, len(samples)):
            prev = samples[i - 1]
            curr = samples[i]

            lat1 = prev.get("lat")
            lon1 = prev.get("lon")
            lat2 = curr.get("lat")
            lon2 = curr.get("lon")

            if lat1 is not None and lon1 is not None and lat2 is not None and lon2 is not None:
                total_dist += _haversine_m(lat1, lon1, lat2, lon2)
                has_gps = True
            else:
                no_gps_count += 1
                # Fallback: estimate from time at ~5 m/s
                time_delta = float(curr.get("t", 0)) - float(prev.get("t", 0))
                total_dist += abs(time_delta) * 5.0

        # Log debug info about GPS availability
        if no_gps_count > 0 and not has_gps:
            logger.warning(f"[DistCalc] No GPS coords in {len(samples)} samples. Keys in first sample: {list(samples[0].keys()) if samples else 'N/A'}")

        # If we have GPS data, it's more accurate
        # If not, we estimated from time
        return total_dist if total_dist > 0 else None

    def _calculate_gradient_at(
        self, samples: List[dict], smoothed_elevations: List[float], idx: int
    ) -> float:
        """
        Calculate gradient (%) at a specific index using surrounding samples.

        Uses a window of GRADIENT_WINDOW samples to smooth GPS noise.
        """
        if idx < 1 or idx >= len(samples):
            return 0.0

        # Calculate gradient over the window
        window_start = max(0, idx - self.GRADIENT_WINDOW // 2)
        window_end = min(len(samples) - 1, idx + self.GRADIENT_WINDOW // 2)

        if window_end <= window_start:
            return 0.0

        # Get lat/lon for distance
        s_start = samples[window_start]
        s_end = samples[window_end]

        lat1 = s_start.get("lat")
        lon1 = s_start.get("lon")
        lat2 = s_end.get("lat")
        lon2 = s_end.get("lon")

        # Fallback: estimate distance from time if no lat/lon
        if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
            # Assume ~5 m/s cycling speed as rough estimate
            time_delta = float(s_end.get("t", 0)) - float(s_start.get("t", 0))
            dist_m = abs(time_delta) * 5.0
        else:
            dist_m = _haversine_m(lat1, lon1, lat2, lon2)

        if dist_m < 1:
            return 0.0

        elev_delta = smoothed_elevations[window_end] - smoothed_elevations[window_start]
        return (elev_delta / dist_m) * 100

    def _trim_climb_segment(
        self,
        samples: List[dict],
        smoothed_elevations: List[float],
        start_idx: int,
        end_idx: int,
    ) -> Tuple[int, int]:
        """
        Trim flat run-in and run-out from a climb segment.

        Walks inward from both ends until gradient exceeds MIN_CLIMB_GRADIENT_PCT.
        Protects against over-trimming (won't trim more than MAX_TRIM_RATIO).

        Args:
            samples: Full list of samples
            smoothed_elevations: Smoothed elevation values
            start_idx: Original start index
            end_idx: Original end index

        Returns:
            Tuple of (new_start_idx, new_end_idx)
        """
        original_length = end_idx - start_idx
        if original_length < self.GRADIENT_WINDOW * 2:
            # Segment too short to trim safely
            return start_idx, end_idx

        max_trim_samples = int(original_length * self.MAX_TRIM_RATIO)

        # Scan forward: find where climb ACTUALLY starts (gradient >= threshold)
        new_start = start_idx
        for i in range(start_idx, min(start_idx + max_trim_samples, end_idx - self.GRADIENT_WINDOW)):
            gradient = self._calculate_gradient_at(samples, smoothed_elevations, i)
            if gradient >= self.MIN_CLIMB_GRADIENT_PCT:
                new_start = i
                break

        # Scan backward: find where climb ACTUALLY ends (gradient >= threshold)
        new_end = end_idx
        for i in range(end_idx, max(end_idx - max_trim_samples, new_start + self.GRADIENT_WINDOW), -1):
            gradient = self._calculate_gradient_at(samples, smoothed_elevations, i)
            if gradient >= self.MIN_CLIMB_GRADIENT_PCT:
                new_end = i
                break

        # Sanity check: don't produce invalid segment
        if new_end <= new_start + self.GRADIENT_WINDOW:
            return start_idx, end_idx

        return new_start, new_end

    def _find_high_vam_subsegment(
        self,
        samples: List[dict],
        smoothed_elevations: List[float],
        cumulative_ascent: List[float],
        start_idx: int,
        end_idx: int,
        vert_gain_fn,
    ) -> Optional[Tuple[int, int]]:
        """
        Find a high-VAM sub-segment within a rejected low-VAM segment.

        Real climbs often hide at the end of rolling approaches. This method
        scans for the best sub-segment that meets VAM threshold.

        Uses sliding window from the END backwards, since actual climbs
        typically come after flat run-ins.

        Returns:
            Tuple of (sub_start, sub_end) indices, or None if no valid sub-segment.
        """
        segment_len = end_idx - start_idx
        if segment_len < 10:  # Too short to subdivide
            return None

        best_vam = 0.0
        best_start = None
        best_end = None

        # Minimum window: enough samples for time_min_s (roughly 1 sample/sec)
        min_window = max(self.time_min_s, 60)  # At least 60 samples

        # Scan from end backwards with expanding windows
        for sub_end in range(end_idx, start_idx + min_window, -5):
            # Try different window sizes from this end point
            for window_size in range(min_window, min(segment_len, 600), 30):
                sub_start = max(start_idx, sub_end - window_size)
                if sub_start >= sub_end - min_window:
                    continue

                # Calculate sub-segment metrics
                sub_time_s = (
                    int(round(float(samples[sub_end]["t"])))
                    - int(round(float(samples[sub_start]["t"])))
                )
                if sub_time_s < self.time_min_s:
                    continue

                sub_vert = vert_gain_fn(sub_start, sub_end)
                if sub_vert < self.vert_min_m:
                    continue

                sub_vam = (sub_vert / sub_time_s) * 3600 if sub_time_s > 0 else 0

                if sub_vam >= self.MIN_CLIMB_VAM and sub_vam > best_vam:
                    best_vam = sub_vam
                    best_start = sub_start
                    best_end = sub_end

        if best_start is not None and best_end is not None:
            return best_start, best_end
        return None


# =============================================================================
# Terrain-Adaptive Detection via Rust Module
# =============================================================================

CANONICAL_MOMENTUM_TERRAINS = ("auto", "hilly", "urban_hills", "rolling")
CANONICAL_V2_MIN_SCORE = 2.25
CANONICAL_V2_SINGLE_SOURCE_PENALTY = 0.75
CANONICAL_V2_CORROBORATION_OVERLAP_RATIO = 0.40
CANONICAL_V2_BOUNDARY_TOLERANCE_S = 180
RAW_PERSISTENCE_UNCONFIRMED_PENALTY = 99.0
RAW_PERSISTENCE_MIN_PROFILE_VERT_M = 50.0
RAW_PERSISTENCE_MIN_PROFILE_TIME_S = 90.0
RAW_PERSISTENCE_MIN_PROFILE_GRADE_PCT = 3.0
RAW_PERSISTENCE_MIN_CORRECTED_ASCENT_M = 30.0
RAW_PERSISTENCE_MIN_CORRECTED_ASCENT_RATIO = 0.75
RAW_PERSISTENCE_MAX_MASK_GAIN_M = 12.0
RAW_PERSISTENCE_MAX_MASK_GAIN_RATIO = 0.25
RAW_PERSISTENCE_MAX_DESCENT_RATIO = 0.50
RAW_PERSISTENCE_MIN_MATCH_VERT_M = 40.0
RAW_PERSISTENCE_MIN_MATCH_TIME_S = 90.0
RAW_PERSISTENCE_MIN_MATCH_GRADE_PCT = 2.25
RAW_PERSISTENCE_MIN_MATCH_ASCENT_M = 25.0
RAW_PERSISTENCE_MIN_MATCH_ASCENT_RATIO = 0.55
RAW_PERSISTENCE_MAX_MATCH_DESCENT_RATIO = 0.60
RAW_PERSISTENCE_WEAK_SUPPORT_BONUS = 0.60
RAW_PERSISTENCE_MIN_WEAK_SUPPORT_VERT_M = 40.0
RAW_PERSISTENCE_MIN_WEAK_SUPPORT_TIME_S = 90.0
RAW_PERSISTENCE_MIN_WEAK_SUPPORT_GRADE_PCT = 1.5
RAW_PERSISTENCE_MIN_WEAK_SUPPORT_ASCENT_M = 22.0
RAW_PERSISTENCE_MIN_WEAK_SUPPORT_ASCENT_RATIO = 0.45
RAW_PERSISTENCE_MAX_WEAK_SUPPORT_DESCENT_RATIO = 0.80
RAW_PERSISTENCE_MIN_WEAK_SUPPORT_H3_BONUS = -1.0
MOMENTUM_CONSENSUS_EPSILON_BONUS = 0.08
MOMENTUM_CONSENSUS_EPSILON_MAX_MARGIN = 0.08
MOMENTUM_CONSENSUS_MIN_VERT_M = 40.0
MOMENTUM_CONSENSUS_MIN_TIME_S = 150.0
MOMENTUM_CONSENSUS_MIN_GRADE_PCT = 2.5


def _climb_vam(climb: ClimbPattern) -> float:
    if climb.time_s <= 0:
        return 0.0
    return float(climb.vert_m) / (float(climb.time_s) / 3600.0)


def _climb_strength_score(climb: ClimbPattern) -> float:
    score = 0.0
    gradient = float(climb.avg_gradient_pct or 0.0)
    vam = _climb_vam(climb)

    if climb.vert_m >= 90:
        score += 3.0
    elif climb.vert_m >= 60:
        score += 2.0
    elif climb.vert_m >= 30:
        score += 1.0

    if gradient >= 7.0:
        score += 3.0
    elif gradient >= 5.0:
        score += 2.0
    elif gradient >= 3.0:
        score += 1.0

    if vam >= 900:
        score += 3.0
    elif vam >= 600:
        score += 2.0
    elif vam >= 300:
        score += 1.0

    if gradient < 2.0 and climb.time_s >= 1500:
        score -= 2.0
    elif gradient < 2.0 and climb.time_s >= 600:
        score -= 1.0

    return score


def _score_terrain_result(climbs: List[ClimbPattern]) -> float:
    shown = [climb for climb in climbs if climb.vert_m >= 20.0]
    if not shown:
        return -5.0

    scores = sorted((_climb_strength_score(climb) for climb in shown), reverse=True)
    total = sum(scores[:6])
    total -= max(0, len(shown) - 4) * 2.0
    total -= sum(0.5 for score in scores if score < 3.0)
    return total


def _infer_quality_source_class(report: SensorIntegrityReport) -> str:
    if report.median_interval_s >= 5.0 or report.gap_ratio >= 0.20:
        return "sparse_reconstructed"
    if report.gps_coverage < 0.90 or report.elev_coverage < 0.90 or report.gps_jump_count > 0:
        return "degraded_native"
    return "native_dense"


def _candidate_family(source: str) -> str:
    return source.split(":", 1)[0]


def _overlap_seconds(a: ClimbPattern, b: ClimbPattern) -> int:
    return max(
        0,
        min(a.end_time_offset_s, b.end_time_offset_s) - max(a.start_time_offset_s, b.start_time_offset_s),
    )


def _corroboration_overlap_ratio(a: ClimbPattern, b: ClimbPattern) -> float:
    shorter = max(
        1,
        min(
            max(1, a.end_time_offset_s - a.start_time_offset_s),
            max(1, b.end_time_offset_s - b.start_time_offset_s),
        ),
    )
    return _overlap_seconds(a, b) / shorter


def _candidates_corroborate(a: ClimbPattern, b: ClimbPattern) -> bool:
    if _corroboration_overlap_ratio(a, b) >= CANONICAL_V2_CORROBORATION_OVERLAP_RATIO:
        return True
    return (
        abs(a.start_time_offset_s - b.start_time_offset_s) <= CANONICAL_V2_BOUNDARY_TOLERANCE_S
        and abs(a.end_time_offset_s - b.end_time_offset_s) <= CANONICAL_V2_BOUNDARY_TOLERANCE_S
    )


def _candidate_source_prior(source: str, climb: ClimbPattern) -> float:
    if source == "persistence":
        prior = 0.15
        if climb.persistence is not None and climb.persistence >= 25.0:
            prior += 0.35
        return prior
    if source == "momentum:auto":
        return 0.45
    if source == "momentum:hilly":
        return 0.30
    if source == "momentum:urban_hills":
        return 0.20
    return 0.0


def _candidate_fragmentation_penalty(climb: ClimbPattern) -> float:
    gradient = climb.avg_gradient_pct or 0.0
    distance = climb.distance_m or 0.0
    penalty = 0.0

    if climb.vert_m < 28.0 and gradient < 4.0:
        penalty += 0.75
    if climb.time_s < 90 and gradient < 6.0:
        penalty += 0.5
    if distance > 3500.0 and gradient < 2.0:
        penalty += 1.5
    if gradient < 2.5 and climb.time_s >= 600:
        penalty += 2.0
    elif gradient < 3.0 and climb.time_s >= 300:
        penalty += 1.0
    if climb.vert_m >= 200.0 and gradient < 2.5:
        penalty += 1.0
    if distance < 500.0 and climb.vert_m < 25.0:
        penalty += 0.5

    return penalty


def _candidate_quality_penalty(climb: ClimbPattern, ride_quality: RideQualityProfile) -> float:
    penalty = (1.0 - ride_quality.integrity_score) * 3.0

    if ride_quality.sparse_sampling and (climb.vert_m < 35.0 or (climb.distance_m or 0.0) < 900.0):
        penalty += 1.25
    if ride_quality.degraded_gps and (climb.distance_m or 0.0) < 1000.0:
        penalty += 0.6
    if ride_quality.degraded_elevation and (climb.avg_gradient_pct or 0.0) < 4.0:
        penalty += 0.8
    if ride_quality.gps_jump_count > 0:
        penalty += min(1.0, 0.2 * ride_quality.gps_jump_count)

    return min(penalty, 1.5)  # Cap: prevent quality from overwhelming strong climb signals


# ---------------------------------------------------------------------------
# H3 terrain context — terrain-relative scoring
# ---------------------------------------------------------------------------

TERRAIN_NOTABLE_VERT = {
    "flat": 15.0,
    "rolling": 25.0,
    "hilly": 40.0,
    "mountainous": 80.0,
}

TERRAIN_NOTABLE_GRADIENT = {
    "flat": 2.0,
    "rolling": 3.0,
    "hilly": 4.0,
    "mountainous": 5.0,
}


def _h3_terrain_context_bonus(
    climb: ClimbPattern,
    terrain_class: Optional[str],
    ride_total_gain_m: Optional[float],
) -> float:
    """Return a terrain-relative bonus/penalty in [-3, +3].

    A 25 m rise is notable on a flat Philadelphia loop but invisible on a 2000 m
    Colorado mountain ride.  This rescales climb significance relative to the
    ride's terrain classification and total elevation gain.
    """
    if terrain_class is None:
        return 0.0

    notable_vert = TERRAIN_NOTABLE_VERT.get(terrain_class, 40.0)
    notable_gradient = TERRAIN_NOTABLE_GRADIENT.get(terrain_class, 4.0)
    gradient = climb.avg_gradient_pct or 0.0

    bonus = 0.0

    # Vert relative to terrain
    if climb.vert_m >= notable_vert * 2.0:
        bonus += 2.0
    elif climb.vert_m >= notable_vert * 1.5:
        bonus += 1.0
    elif climb.vert_m >= notable_vert:
        bonus += 0.5
    elif climb.vert_m < notable_vert * 0.5:
        bonus -= 1.0

    # Gradient relative to terrain
    if gradient >= notable_gradient * 2.0:
        bonus += 1.0
    elif gradient >= notable_gradient:
        bonus += 0.25
    elif gradient < notable_gradient * 0.5 and terrain_class in ("hilly", "mountainous"):
        bonus -= 0.75

    # Vert fraction of ride total
    if ride_total_gain_m and ride_total_gain_m > 0:
        vert_fraction = climb.vert_m / ride_total_gain_m
        if vert_fraction >= 0.15:
            bonus += 0.75
        elif vert_fraction >= 0.05:
            bonus += 0.25

    return max(-3.0, min(3.0, bonus))


# ---------------------------------------------------------------------------
# H4 intensity score — gradient-weighted intensity bonus
# ---------------------------------------------------------------------------


def _h4_intensity_bonus(climb: ClimbPattern) -> float:
    """Return an intensity bonus in [0, +3] for steep punchy efforts.

    Short steep climbs feel more like climbs than long gradual ones.  A 500 m
    wall at 15 % is seared in memory.  A 5 km road at 2 % might not register.
    Uses ``distance * gradient**2`` to weight gradient more heavily than raw
    vert, plus a bonus for steep punchy efforts.

    Only positive bonuses — the fragmentation penalty already handles the
    negative (low-gradient drag) cases.
    """
    gradient = climb.avg_gradient_pct or 0.0
    time_s = climb.time_s
    distance_m = climb.distance_m or 0.0

    intensity = distance_m * (gradient ** 2)

    bonus = 0.0

    # Intensity tiers (recalibrated: top tier raised from 30K to 50K for precision)
    if intensity >= 50_000:
        bonus += 2.0
    elif intensity >= 20_000:
        bonus += 1.0
    elif intensity >= 8_000:
        bonus += 0.5

    # Steep punch bonus
    if gradient >= 10.0 and 30 <= time_s <= 300:
        bonus += 1.0
    elif gradient >= 7.0 and 60 <= time_s <= 600:
        bonus += 0.5

    return min(3.0, bonus)


def _h2_power_confirmation_bonus(climb: ClimbPattern, ride_avg_power_w: float) -> float:
    """Return a bonus/penalty in [-1.0, +1.5] based on power confirmation.

    If the rider's power during a detected climb is significantly above their
    ride average, their body confirms the GPS/elevation data.  If power is
    BELOW average during a "climb," something is probably wrong — the rider
    was coasting, not climbing.

    Rides without power data get 0.0 — absence of signal is not a negative
    signal.
    """
    if climb.avg_power_w is None or ride_avg_power_w is None or ride_avg_power_w <= 0:
        return 0.0  # No power data = neutral

    ratio = climb.avg_power_w / ride_avg_power_w

    if ratio >= 1.50:
        return 1.5    # Strong confirmation (50%+ above ride avg)
    elif ratio >= 1.30:
        return 1.0    # Good confirmation
    elif ratio >= 1.15:
        return 0.5    # Mild confirmation
    elif ratio >= 0.90:
        return 0.0    # Neutral
    elif ratio >= 0.70:
        return -0.5   # Below-average power — suspicious
    else:
        return -1.0   # Much lower power — likely coasting


def _h9_roller_filter_bonus(climb: ClimbPattern) -> float:
    """Return a penalty in [-2.0, 0] for short-duration low-gradient rollers.

    Rollers are not climbs.  Even if a roller has 30 m of vert, if you can push
    through it in under 90 seconds without changing your effort strategy, it's a
    bump.  This penalizes short-duration, low-gradient efforts and rewards
    sustained elevated effort.

    Uses only gradient and duration (always available — no power data).

    Duration cutoff recalibrated from 60s to 90s based on full-resolution
    tile_samples sweep (2026-03-21).
    """
    gradient = climb.avg_gradient_pct or 0.0
    time_s = climb.time_s

    # Sub-90s: must be very steep to qualify as a climb
    if time_s < 90:
        if gradient >= 12.0:
            return 0.0    # Very steep punch (Manayunk Wall) — allow
        elif gradient >= 8.0:
            return -0.5   # Steep but short — mild penalty
        else:
            return -2.0   # Short and not steep — roller

    # Over 180s: probably a climb regardless of gradient
    if time_s >= 180:
        return 0.0

    # Gray zone (90-180s): use gradient as discriminator
    if gradient >= 6.0:
        return 0.0    # Steep enough for 1.5-3 minutes
    elif gradient >= 4.0:
        return -0.5   # Borderline
    else:
        return -1.5   # Low gradient, short duration = roller


# ---------------------------------------------------------------------------
# H10 topographic isolation — pre/post terrain context
# ---------------------------------------------------------------------------


def _h10_isolation_bonus(
    climb: ClimbPattern,
    tile_samples: Optional[List[Dict]],
) -> float:
    """Return a bonus/penalty in [-1.5, +2.0] based on topographic isolation.

    If the terrain is flat before the climb starts and flat after it ends, the
    climb is topographically isolated — a distinct feature worth detecting.
    If the terrain is already climbing before/after, this may be a fragment of
    a larger climb that was poorly bounded.

    Also rewards steep onset (sharp transition from flat to climbing).
    Scales penalty by climb vert — large climbs get milder penalties.
    """
    if tile_samples is None or len(tile_samples) < 10:
        return 0.0

    base_time = infer_sample_time_base(tile_samples)
    start_s = sample_time_seconds(climb.start_time_offset_s, base_time=base_time)
    end_s = sample_time_seconds(climb.end_time_offset_s, base_time=base_time)
    if start_s is None or end_s is None:
        return 0.0

    samples_with_time = []
    for sample in tile_samples:
        if sample.get("elevation_m") is None:
            continue
        seconds = sample_time_seconds(sample.get("t"), base_time=base_time)
        if seconds is not None:
            samples_with_time.append((seconds, sample))

    # Find pre-climb and post-climb elevation samples
    pre_samples = [(t, s) for t, s in samples_with_time if t < start_s]
    post_samples = [(t, s) for t, s in samples_with_time if t > end_s]

    bonus = 0.0

    # Check pre-climb terrain (60 seconds before)
    pre_window = [(t, s) for t, s in pre_samples if start_s - 60 <= t < start_s]
    if len(pre_window) >= 3:
        elevs = [s["elevation_m"] for _, s in sorted(pre_window, key=lambda item: item[0])]
        rise_m = elevs[-1] - elevs[0]
        if abs(rise_m) < 3.0:
            bonus += 0.75  # Flat before climb — good isolation
        elif rise_m > 5.0:
            bonus -= 0.75  # Already climbing — potential fragment

    # Check post-climb terrain (60 seconds after)
    post_window = [(t, s) for t, s in post_samples if end_s < t <= end_s + 60]
    if len(post_window) >= 3:
        elevs = [s["elevation_m"] for _, s in sorted(post_window, key=lambda item: item[0])]
        rise_m = elevs[-1] - elevs[0]
        if abs(rise_m) < 3.0:
            bonus += 0.75  # Flat after climb — good isolation
        elif rise_m > 5.0:
            bonus -= 0.75  # Still climbing after — potential fragment

    # Steep onset bonus: sharp transition from flat to climbing
    if len(pre_window) >= 3:
        pre_elevs = [s["elevation_m"] for _, s in sorted(pre_window, key=lambda item: item[0])]
        # Get first few seconds of climb
        onset_samples = [
            (t, s)
            for t, s in samples_with_time
            if start_s <= t <= start_s + 15
        ]
        if onset_samples:
            onset_elevs = [s["elevation_m"] for _, s in sorted(onset_samples, key=lambda item: item[0])]
            pre_gradient = abs(pre_elevs[-1] - pre_elevs[0]) / max(1, len(pre_elevs))
            onset_gradient = (onset_elevs[-1] - onset_elevs[0]) / max(1, len(onset_elevs))
            if onset_gradient > 0.5 and pre_gradient < 0.1:
                bonus += 0.5  # Sharp transition from flat to climbing

    # Scale penalty by vert — large climbs deserve milder fragment penalty
    if bonus < 0 and climb.vert_m >= 50.0:
        # Large climbs: reduce penalty by 70%
        bonus *= 0.3

    return max(-1.5, min(2.0, bonus))


# ---------------------------------------------------------------------------
# H12 frequency prior — historical detection frequency at this GPS location
# ---------------------------------------------------------------------------


def _h12_frequency_prior_bonus(
    climb: ClimbPattern,
    frequency_map: Optional[Dict[str, int]],
) -> float:
    """Bonus based on historical detection frequency at this GPS location.

    If many previous rides have had climbs detected starting near this location,
    this is strong evidence that a real climb exists here. This is an empirical
    Bayesian prior — statistical evidence from historical detections.

    Uses H3 resolution 8 (~460m hexagons) for "same general location" matching.

    NOTE: Bonus capped at +1.0 (audit RED H12-decay). A false positive at a
    location permanently inflates the frequency count. Until the frequency map
    uses cross-family corroboration and/or temporal decay, the cap prevents a
    single bad detection from creating a positive feedback loop.

    Returns bonus in [0.0, 1.0]:
      - 20+ detections: +1.0  (well-established climbing location)
      - 10-19:          +0.75 (established)
      - 5-9:            +0.5  (growing confidence)
      - 2-4:            +0.25 (second+ detection)
      - 0-1:            +0.0  (unknown location — neutral)
    """
    if not frequency_map or not climb.start_lat or not climb.start_lon:
        return 0.0

    try:
        import h3
        tile = h3.latlng_to_cell(climb.start_lat, climb.start_lon, 8)
    except ImportError:
        # Approximate: round to ~0.004 degrees (~460m)
        tile = f"{round(climb.start_lat, 3)}_{round(climb.start_lon, 3)}"

    count = frequency_map.get(tile, 0)

    if count >= 20:
        return 1.0    # Well-established climbing location
    elif count >= 10:
        return 0.75   # Established
    elif count >= 5:
        return 0.5    # Growing confidence
    elif count >= 2:
        return 0.25   # Second+ detection
    else:
        return 0.0    # Unknown location — neutral


def _is_steep_isolated_urban_micro_candidate(
    candidate: ClimbCandidate,
    *,
    h4_bonus: float,
    h10_bonus: float,
) -> bool:
    climb = candidate.climb
    gradient = climb.avg_gradient_pct or 0.0
    distance = climb.distance_m or 0.0

    return (
        candidate.source == "momentum:urban_hills"
        and 20.0 <= climb.vert_m < 35.0
        and gradient >= 7.0
        and climb.time_s >= 90
        and distance >= 250.0
        and h4_bonus >= 1.0
        and h10_bonus >= 0.75
    )


def _should_apply_momentum_consensus_epsilon(
    candidate: ClimbCandidate,
    *,
    h3_bonus: float,
    h4_bonus: float,
    h9_bonus: float,
    h10_bonus: float,
    fragmentation_penalty: float,
    quality_penalty: float,
    total: float,
    threshold: float,
) -> bool:
    climb = candidate.climb
    margin = threshold - total

    return (
        candidate.family == "momentum"
        and bool(candidate.corroborating_sources)
        and not candidate.corroborating_families
        and 0.0 < margin <= MOMENTUM_CONSENSUS_EPSILON_MAX_MARGIN
        and climb.vert_m >= MOMENTUM_CONSENSUS_MIN_VERT_M
        and climb.time_s >= MOMENTUM_CONSENSUS_MIN_TIME_S
        and _climb_grade_pct(climb) >= MOMENTUM_CONSENSUS_MIN_GRADE_PCT
        and h3_bonus >= 0.0
        and h4_bonus >= 0.5
        and h9_bonus >= 0.0
        and h10_bonus >= 0.75
        and fragmentation_penalty <= 0.0
        and quality_penalty <= 0.65
        and candidate.ride_quality.integrity_score >= 0.75
        and candidate.ride_quality.source_class == "native_dense"
        and not candidate.ride_quality.degraded_gps
        and not candidate.ride_quality.degraded_elevation
    )


def _score_climb_candidate(candidate: ClimbCandidate) -> Tuple[float, List[str]]:
    reasons: List[str] = []

    strength = _climb_strength_score(candidate.climb)
    if strength > 0:
        reasons.append("strong_effort")

    source_prior = _candidate_source_prior(candidate.source, candidate.climb)
    if source_prior > 0:
        reasons.append(f"source:{candidate.source}")

    support_bonus = 0.0
    if candidate.corroborating_families:
        support_bonus += 1.5 * len(candidate.corroborating_families)
        reasons.append("cross_family_corroboration")
    elif candidate.corroborating_sources:
        support_bonus += 0.5
        reasons.append("same_family_corroboration")

    fragmentation_penalty = _candidate_fragmentation_penalty(candidate.climb)
    if (
        candidate.corroborating_families
        and candidate.climb.vert_m >= 100.0
        and fragmentation_penalty > 0
    ):
        fragmentation_penalty *= 0.3
        reasons.append("corroborated_highvert_frag_discount")
    if fragmentation_penalty > 0:
        reasons.append("fragmentation_penalty")

    quality_penalty = _candidate_quality_penalty(candidate.climb, candidate.ride_quality)
    if quality_penalty > 0.75:
        reasons.append(f"quality:{candidate.ride_quality.source_class}")

    h3_bonus = _h3_terrain_context_bonus(
        candidate.climb, candidate.terrain_class, candidate.ride_total_gain_m
    )
    if h3_bonus != 0:
        reasons.append(f"h3_terrain:{h3_bonus:+.1f}")

    h4_bonus = _h4_intensity_bonus(candidate.climb)
    if h4_bonus != 0:
        reasons.append(f"h4_intensity:{h4_bonus:+.1f}")

    h9_bonus = _h9_roller_filter_bonus(candidate.climb)
    if h9_bonus != 0:
        reasons.append(f"h9_roller:{h9_bonus:+.1f}")

    h2_bonus = _h2_power_confirmation_bonus(candidate.climb, candidate.ride_avg_power_w)
    if h2_bonus != 0:
        reasons.append(f"h2_power:{h2_bonus:+.1f}")

    h10_bonus = _h10_isolation_bonus(candidate.climb, candidate.tile_samples)
    if h10_bonus != 0:
        reasons.append(f"h10_isolation:{h10_bonus:+.1f}")

    weak_support_bonus = 0.0
    if (
        candidate.weak_raw_persistence_support_count > 0
        and candidate.family != "persistence"
        and h3_bonus >= RAW_PERSISTENCE_MIN_WEAK_SUPPORT_H3_BONUS
    ):
        weak_support_bonus = RAW_PERSISTENCE_WEAK_SUPPORT_BONUS
        reasons.append("weak_raw_persistence_support")

    # H12 is historical corroboration only; it should not make single-source
    # candidates acceptable by itself.
    h12_bonus = 0.0
    if candidate.corroborating_families:
        h12_bonus = _h12_frequency_prior_bonus(candidate.climb, candidate.frequency_map)
    if h12_bonus != 0:
        reasons.append(f"h12_frequency:{h12_bonus:+.1f}")

    total = strength + source_prior + support_bonus + weak_support_bonus + h3_bonus + h4_bonus + h9_bonus + h2_bonus + h10_bonus + h12_bonus - fragmentation_penalty - quality_penalty
    threshold = CANONICAL_V2_MIN_SCORE
    if not candidate.corroborating_families:
        if candidate.family == "persistence":
            pass  # Persistence is an independent detection family — no penalty
        else:
            threshold += CANONICAL_V2_SINGLE_SOURCE_PENALTY

    if candidate.ride_quality.sparse_sampling:
        threshold += 0.5
    if candidate.ride_quality.degraded_elevation and candidate.climb.vert_m < 35.0:
        threshold += 0.25
    if (
        candidate.ride_quality.sparse_sampling
        and candidate.climb.vert_m < 60.0
        and (candidate.climb.avg_gradient_pct or 0.0) < 2.0
    ):
        threshold += 2.0
        reasons.append("sparse_low_gradient_suppression")
    if (
        candidate.source == "momentum:urban_hills"
        and candidate.climb.vert_m < 35.0
    ):
        if _is_steep_isolated_urban_micro_candidate(
            candidate,
            h4_bonus=h4_bonus,
            h10_bonus=h10_bonus,
        ):
            reasons.append("steep_isolated_urban_micro")
        else:
            threshold += 99.0
            reasons.append("micro_urban_below_display_floor")

    if _should_apply_momentum_consensus_epsilon(
        candidate,
        h3_bonus=h3_bonus,
        h4_bonus=h4_bonus,
        h9_bonus=h9_bonus,
        h10_bonus=h10_bonus,
        fragmentation_penalty=fragmentation_penalty,
        quality_penalty=quality_penalty,
        total=total,
        threshold=threshold,
    ):
        total += MOMENTUM_CONSENSUS_EPSILON_BONUS
        reasons.append("momentum_consensus_epsilon")

    candidate.base_score = strength
    candidate.acceptance_threshold = threshold
    return total, reasons


def _build_climb_candidates(
    climbs: List[ClimbPattern],
    *,
    source: str,
    ride_quality: RideQualityProfile,
    terrain_class: Optional[str] = None,
    ride_total_gain_m: Optional[float] = None,
    ride_avg_power_w: Optional[float] = None,
    tile_samples: Optional[List[Dict]] = None,
    frequency_map: Optional[Dict[str, int]] = None,
) -> List[ClimbCandidate]:
    family = _candidate_family(source)
    return [
        ClimbCandidate(
            climb=climb,
            source=source,
            family=family,
            ride_quality=ride_quality,
            terrain_class=terrain_class,
            ride_total_gain_m=ride_total_gain_m,
            ride_avg_power_w=ride_avg_power_w,
            tile_samples=tile_samples,
            frequency_map=frequency_map,
        )
        for climb in climbs
    ]


def _cluster_canonical_v2_candidates(candidates: List[ClimbCandidate]) -> List[List[ClimbCandidate]]:
    clusters: List[List[ClimbCandidate]] = []

    for candidate in sorted(candidates, key=lambda c: (c.start_s, c.end_s)):
        placed = False
        for cluster in clusters:
            if any(_candidates_corroborate(candidate.climb, existing.climb) for existing in cluster):
                cluster.append(candidate)
                placed = True
                break
        if not placed:
            clusters.append([candidate])

    return clusters


def _candidate_confidence(candidate: ClimbCandidate) -> float:
    confidence = 0.15 + (candidate.ride_quality.integrity_score * 0.45)
    confidence += 0.15 * len(candidate.corroborating_families)
    if candidate.total_score >= candidate.acceptance_threshold + 1.0:
        confidence += 0.10
    if candidate.ride_quality.sparse_sampling:
        confidence -= 0.10
    if candidate.ride_quality.degraded_elevation:
        confidence -= 0.05
    return max(0.0, min(1.0, confidence))


def _uses_separate_persistence_candidate_samples(
    tile_samples: List[Dict],
    persistence_candidate_samples: Optional[List[Dict]],
) -> bool:
    if persistence_candidate_samples is None:
        return False
    if persistence_candidate_samples is tile_samples:
        return False
    return persistence_candidate_samples != tile_samples


def _climb_grade_pct(climb: ClimbPattern) -> float:
    if climb.avg_gradient_pct is not None:
        return float(climb.avg_gradient_pct)
    if (climb.distance_m or 0.0) > 0.0:
        return (climb.vert_m / float(climb.distance_m)) * 100.0
    return 0.0


def _bridge_neutral_match_confirms_raw_persistence(
    candidate: ClimbCandidate,
    confirmation: ClimbPattern,
    ride_profile: RideClimbProfile,
) -> bool:
    if not _candidates_corroborate(candidate.climb, confirmation):
        return False

    if _climb_grade_pct(candidate.climb) < RAW_PERSISTENCE_MIN_MATCH_GRADE_PCT:
        return False

    confirmation_has_climb_shape = (
        confirmation.vert_m >= RAW_PERSISTENCE_MIN_MATCH_VERT_M
        and confirmation.time_s >= RAW_PERSISTENCE_MIN_MATCH_TIME_S
        and _climb_grade_pct(confirmation) >= RAW_PERSISTENCE_MIN_MATCH_GRADE_PCT
    )
    if not confirmation_has_climb_shape:
        return False

    if not ride_profile.points:
        return True

    metrics = ride_profile.metrics_for_time_window(candidate.start_s, candidate.end_s)
    corrected_ascent = max(0.0, metrics.ascent_m)
    min_ascent = max(
        RAW_PERSISTENCE_MIN_MATCH_ASCENT_M,
        candidate.climb.vert_m * RAW_PERSISTENCE_MIN_MATCH_ASCENT_RATIO,
    )
    has_corrected_ascent = corrected_ascent >= min(min_ascent, candidate.climb.vert_m)
    monotonic_enough = metrics.descent_m <= max(
        20.0,
        corrected_ascent * RAW_PERSISTENCE_MAX_MATCH_DESCENT_RATIO,
    )
    has_grade_support = (metrics.avg_grade_pct or 0.0) >= RAW_PERSISTENCE_MIN_MATCH_GRADE_PCT
    return has_corrected_ascent and monotonic_enough and has_grade_support


def _bridge_neutral_profile_confirms_raw_persistence(
    candidate: ClimbCandidate,
    ride_profile: RideClimbProfile,
) -> bool:
    has_climb_shape = (
        candidate.climb.vert_m >= RAW_PERSISTENCE_MIN_PROFILE_VERT_M
        and candidate.climb.time_s >= RAW_PERSISTENCE_MIN_PROFILE_TIME_S
        and _climb_grade_pct(candidate.climb) >= RAW_PERSISTENCE_MIN_PROFILE_GRADE_PCT
    )
    if not has_climb_shape:
        return False

    metrics = ride_profile.metrics_for_time_window(candidate.start_s, candidate.end_s)
    climb_vert = max(1.0, candidate.climb.vert_m)
    corrected_ascent = max(0.0, metrics.ascent_m)
    mask_gain = max(0.0, climb_vert - corrected_ascent)
    max_mask_gain = max(
        RAW_PERSISTENCE_MAX_MASK_GAIN_M,
        climb_vert * RAW_PERSISTENCE_MAX_MASK_GAIN_RATIO,
    )

    min_ascent = max(
        RAW_PERSISTENCE_MIN_CORRECTED_ASCENT_M,
        climb_vert * RAW_PERSISTENCE_MIN_CORRECTED_ASCENT_RATIO,
    )
    has_near_threshold_ascent = corrected_ascent >= min(min_ascent, climb_vert)
    low_mask_gain_dominance = mask_gain <= max_mask_gain
    monotonic_enough = metrics.descent_m <= max(
        20.0,
        corrected_ascent * RAW_PERSISTENCE_MAX_DESCENT_RATIO,
    )
    boundary_or_grade_support = (
        metrics.boundary_rise_m >= max(8.0, corrected_ascent * 0.30)
        or (metrics.avg_grade_pct or 0.0) >= 2.0
    )

    return (
        has_near_threshold_ascent
        and low_mask_gain_dominance
        and monotonic_enough
        and boundary_or_grade_support
    )


def _raw_persistence_has_bridge_neutral_confirmation(
    candidate: ClimbCandidate,
    *,
    persistence_confirmation_climbs: List[ClimbPattern],
    ride_profile: RideClimbProfile,
) -> bool:
    if any(
        _bridge_neutral_match_confirms_raw_persistence(
            candidate,
            confirmation,
            ride_profile,
        )
        for confirmation in persistence_confirmation_climbs
    ):
        candidate.reasons.append("bridge_neutral_persistence_match")
        return True

    if _bridge_neutral_profile_confirms_raw_persistence(candidate, ride_profile):
        candidate.reasons.append("bridge_neutral_profile_support")
        return True

    candidate.reasons.append("raw_persistence_unconfirmed")
    return False


def _raw_persistence_can_weakly_support_momentum(
    candidate: ClimbCandidate,
    ride_profile: RideClimbProfile,
) -> bool:
    if candidate.family != "persistence":
        return False
    if not ride_profile.points:
        return False

    has_minimal_shape = (
        candidate.climb.vert_m >= RAW_PERSISTENCE_MIN_WEAK_SUPPORT_VERT_M
        and candidate.climb.time_s >= RAW_PERSISTENCE_MIN_WEAK_SUPPORT_TIME_S
        and _climb_grade_pct(candidate.climb) >= RAW_PERSISTENCE_MIN_WEAK_SUPPORT_GRADE_PCT
    )
    if not has_minimal_shape:
        return False

    metrics = ride_profile.metrics_for_time_window(candidate.start_s, candidate.end_s)
    corrected_ascent = max(0.0, metrics.ascent_m)
    min_ascent = max(
        RAW_PERSISTENCE_MIN_WEAK_SUPPORT_ASCENT_M,
        candidate.climb.vert_m * RAW_PERSISTENCE_MIN_WEAK_SUPPORT_ASCENT_RATIO,
    )
    has_corrected_ascent = corrected_ascent >= min(min_ascent, candidate.climb.vert_m)
    monotonic_enough = metrics.descent_m <= max(
        25.0,
        corrected_ascent * RAW_PERSISTENCE_MAX_WEAK_SUPPORT_DESCENT_RATIO,
    )
    has_profile_shape = (
        (metrics.avg_grade_pct or 0.0) >= RAW_PERSISTENCE_MIN_WEAK_SUPPORT_GRADE_PCT
        or metrics.boundary_rise_m >= max(6.0, corrected_ascent * 0.25)
    )

    return has_corrected_ascent and monotonic_enough and has_profile_shape


def _partition_raw_persistence_candidates(
    persistence_candidates: List[ClimbCandidate],
    *,
    persistence_confirmation_climbs: Optional[List[ClimbPattern]],
    ride_profile: RideClimbProfile,
) -> Tuple[List[ClimbCandidate], List[ClimbCandidate]]:
    if persistence_confirmation_climbs is None:
        return persistence_candidates, []

    confirmed: List[ClimbCandidate] = []
    weak_support: List[ClimbCandidate] = []
    for candidate in persistence_candidates:
        if _raw_persistence_has_bridge_neutral_confirmation(
            candidate,
            persistence_confirmation_climbs=persistence_confirmation_climbs,
            ride_profile=ride_profile,
        ):
            confirmed.append(candidate)
        elif _raw_persistence_can_weakly_support_momentum(candidate, ride_profile):
            candidate.selectable = False
            candidate.reasons.append("support_only_raw_persistence")
            weak_support.append(candidate)

    return confirmed, weak_support


def _attach_weak_raw_persistence_support(
    momentum_candidates: List[ClimbCandidate],
    weak_support_candidates: List[ClimbCandidate],
) -> None:
    if not weak_support_candidates:
        return

    for candidate in momentum_candidates:
        if candidate.family == "persistence":
            continue
        candidate.weak_raw_persistence_support_count = sum(
            1
            for support_candidate in weak_support_candidates
            if _candidates_corroborate(candidate.climb, support_candidate.climb)
        )


def _score_candidate_with_canonical_context(
    candidate: ClimbCandidate,
    *,
    ride_profile: RideClimbProfile,
    persistence_confirmation_climbs: Optional[List[ClimbPattern]] = None,
) -> None:
    candidate.total_score, candidate.reasons = _score_climb_candidate(candidate)
    if (
        candidate.family == "persistence"
        and persistence_confirmation_climbs is not None
        and not _raw_persistence_has_bridge_neutral_confirmation(
            candidate,
            persistence_confirmation_climbs=persistence_confirmation_climbs,
            ride_profile=ride_profile,
        )
    ):
        candidate.acceptance_threshold += RAW_PERSISTENCE_UNCONFIRMED_PENALTY


def _should_prefer_persistence_override(
    baseline: ClimbCandidate,
    candidate: ClimbCandidate,
) -> bool:
    if candidate.family != "persistence" or baseline.family != "momentum":
        return False

    baseline_gradient = baseline.climb.avg_gradient_pct or 0.0
    candidate_gradient = candidate.climb.avg_gradient_pct or 0.0
    vert_gain_delta = candidate.climb.vert_m - baseline.climb.vert_m
    starts_earlier = baseline.climb.start_time_offset_s - candidate.climb.start_time_offset_s

    if candidate_gradient + 1.0 < baseline_gradient:
        return False
    if starts_earlier < 90:
        return False

    strong_vert_upgrade = (
        candidate.climb.vert_m >= baseline.climb.vert_m * 1.15
        or vert_gain_delta >= 50.0
    )
    strong_persistence = (candidate.climb.persistence or 0.0) >= 45.0

    return strong_vert_upgrade and strong_persistence


def _score_canonical_v2_momentum_set(
    climbs: List[ClimbPattern],
    *,
    persistence_climbs: List[ClimbPattern],
    ride_quality: RideQualityProfile,
) -> float:
    score = _score_terrain_result(climbs)
    shown = [climb for climb in climbs if climb.vert_m >= 20.0]
    score -= sum(0.75 * _candidate_fragmentation_penalty(climb) for climb in shown)

    corroborated = sum(
        1
        for climb in shown
        if (climb.avg_gradient_pct or 0.0) >= 3.0
        and any(
            _candidates_corroborate(climb, persistence)
            and (persistence.avg_gradient_pct or 0.0) >= 3.0
            for persistence in persistence_climbs
        )
    )
    score += corroborated * 0.75

    if ride_quality.sparse_sampling:
        score -= sum(
            0.75
            for climb in shown
            if climb.vert_m < 35.0 or (climb.avg_gradient_pct or 0.0) < 3.0
        )
    if ride_quality.degraded_elevation:
        score -= sum(0.5 for climb in shown if (climb.avg_gradient_pct or 0.0) < 4.0)

    return score


def _choose_canonical_v2_climbs(
    *,
    ride_quality: RideQualityProfile,
    ride_profile: RideClimbProfile,
    momentum_results: Dict[str, List[ClimbPattern]],
    persistence_climbs: List[ClimbPattern],
    terrain_class: Optional[str] = None,
    ride_total_gain_m: Optional[float] = None,
    ride_avg_power_w: Optional[float] = None,
    tile_samples: Optional[List[Dict]] = None,
    frequency_map: Optional[Dict[str, int]] = None,
    persistence_confirmation_climbs: Optional[List[ClimbPattern]] = None,
) -> List[ClimbPattern]:
    if not momentum_results:
        return []

    # Build candidates from ALL terrains, not just the best
    all_momentum_candidates: List[ClimbCandidate] = []
    for terrain_name, climbs in momentum_results.items():
        candidates = _build_climb_candidates(
            climbs,
            source=f"momentum:{terrain_name}",
            ride_quality=ride_quality,
            terrain_class=terrain_class,
            ride_total_gain_m=ride_total_gain_m,
            ride_avg_power_w=ride_avg_power_w,
            tile_samples=tile_samples,
            frequency_map=frequency_map,
        )
        all_momentum_candidates.extend(candidates)

    persistence_candidates = _build_climb_candidates(
        persistence_climbs,
        source="persistence",
        ride_quality=ride_quality,
        terrain_class=terrain_class,
        ride_total_gain_m=ride_total_gain_m,
        ride_avg_power_w=ride_avg_power_w,
        tile_samples=tile_samples,
        frequency_map=frequency_map,
    )

    weak_persistence_support_candidates: List[ClimbCandidate] = []
    if persistence_confirmation_climbs is not None:
        persistence_candidates, weak_persistence_support_candidates = (
            _partition_raw_persistence_candidates(
                persistence_candidates,
                persistence_confirmation_climbs=persistence_confirmation_climbs,
                ride_profile=ride_profile,
            )
        )
        _attach_weak_raw_persistence_support(
            all_momentum_candidates,
            weak_persistence_support_candidates,
        )

    # Cluster overlapping candidates from all sources
    clusters = _cluster_canonical_v2_candidates(
        all_momentum_candidates + persistence_candidates
    )

    selected: List[ClimbPattern] = []
    used_persistence_ids: Set[int] = set()

    for cluster in clusters:
        # Collect all unique sources and families in this cluster
        cluster_sources = {c.source for c in cluster}
        cluster_families = {c.family for c in cluster}

        # Score each candidate with full cluster context. The highest raw score
        # can still be intentionally disqualified by its acceptance threshold,
        # so selection falls back to the best acceptable candidate in the cluster.
        best_candidate: Optional[ClimbCandidate] = None
        for candidate in cluster:
            other_sources = sorted(cluster_sources - {candidate.source})
            other_families = sorted(cluster_families - {candidate.family})
            candidate.corroborating_sources = other_sources
            candidate.corroborating_families = other_families
            _score_candidate_with_canonical_context(
                candidate,
                ride_profile=ride_profile,
                persistence_confirmation_climbs=persistence_confirmation_climbs,
            )

            if not candidate.selectable:
                continue
            if best_candidate is None or candidate.total_score > best_candidate.total_score:
                best_candidate = candidate

        if best_candidate is None:
            continue

        # Check persistence override: prefer persistence if it starts meaningfully
        # earlier and captures more vert
        for candidate in cluster:
            if (
                candidate.selectable
                and candidate.family == "persistence"
                and candidate.total_score >= candidate.acceptance_threshold
                and best_candidate.family == "momentum"
            ):
                if _should_prefer_persistence_override(best_candidate, candidate):
                    best_candidate = candidate

        acceptable_candidates = [
            candidate
            for candidate in cluster
            if candidate.selectable
            and candidate.total_score >= candidate.acceptance_threshold
        ]
        if best_candidate.total_score < best_candidate.acceptance_threshold and acceptable_candidates:
            best_candidate = max(
                acceptable_candidates,
                key=lambda candidate: candidate.total_score,
            )

        # Track which persistence candidates were part of this cluster
        for candidate in cluster:
            if candidate.selectable and candidate.family == "persistence":
                used_persistence_ids.add(id(candidate))

        if best_candidate.total_score < best_candidate.acceptance_threshold:
            # Cluster rejected — release persistence candidates for rescue path
            for candidate in cluster:
                if candidate.selectable and candidate.family == "persistence":
                    used_persistence_ids.discard(id(candidate))
            continue

        chosen = best_candidate.climb
        chosen.detector_mode = f"canonical_v2:{best_candidate.source}"
        chosen.proposal_sources = sorted(cluster_sources)
        chosen.confidence = _candidate_confidence(best_candidate)
        chosen.confidence_reasons = sorted(set(best_candidate.reasons))
        chosen.source_quality = ride_quality.to_dict()
        chosen.route_profile = ride_profile.metrics_for_time_window(
            chosen.start_time_offset_s,
            chosen.end_time_offset_s,
        ).to_dict()
        selected.append(chosen)

    # Safety-net rescue: persistence candidates not placed in any cluster,
    # or released from rejected clusters, evaluated standalone
    for candidate in persistence_candidates:
        if id(candidate) in used_persistence_ids:
            continue
        # Check if this candidate already overlaps a selected climb
        if any(_candidates_corroborate(candidate.climb, s) for s in selected):
            continue
        corroborating_terrains = sorted(
            terrain_name
            for terrain_name, climbs in momentum_results.items()
            if any(_candidates_corroborate(candidate.climb, climb) for climb in climbs)
        )
        if len(corroborating_terrains) < 1:
            continue

        candidate.corroborating_sources = [f"momentum:{terrain}" for terrain in corroborating_terrains]
        candidate.corroborating_families = ["momentum"]
        _score_candidate_with_canonical_context(
            candidate,
            ride_profile=ride_profile,
            persistence_confirmation_climbs=persistence_confirmation_climbs,
        )
        if candidate.total_score < candidate.acceptance_threshold + 0.5:
            continue

        chosen = candidate.climb
        chosen.detector_mode = "canonical_v2:persistence"
        chosen.proposal_sources = sorted(["persistence", *candidate.corroborating_sources])
        chosen.confidence = _candidate_confidence(candidate)
        chosen.confidence_reasons = sorted(set(candidate.reasons))
        chosen.source_quality = ride_quality.to_dict()
        chosen.route_profile = ride_profile.metrics_for_time_window(
            chosen.start_time_offset_s,
            chosen.end_time_offset_s,
        ).to_dict()
        selected.append(chosen)

    return sorted(selected, key=lambda climb: climb.start_time_offset_s)


def _convert_rust_climbs_to_patterns(
    rust_climbs,
    *,
    sample_source: List[Dict],
    sample_time_base: Any = None,
    algorithm: str,
    user_weight_kg: Optional[float],
) -> List[ClimbPattern]:
    climbs: List[ClimbPattern] = []
    sample_time_base = sample_time_base or _infer_detector_time_base(sample_source)

    def _sample_time_offset_s(index: int) -> int:
        if index < 0 or index >= len(sample_source):
            return 0

        return _time_offset_s(
            sample_source[index].get("t", 0),
            base_time=sample_time_base,
        )

    if algorithm == "persistence":
        for rc in rust_climbs:
            start_offset = _sample_time_offset_s(rc.effort_start_idx)
            end_offset = _sample_time_offset_s(rc.effort_end_idx)

            w_per_kg = None
            if rc.avg_power_w is not None and user_weight_kg:
                w_per_kg = rc.avg_power_w / user_weight_kg

            climb = ClimbPattern(
                vert_m=rc.vert_m,
                time_s=rc.time_s,
                avg_power_w=rc.avg_power_w,
                w_per_kg=w_per_kg,
                avg_hr=int(rc.avg_hr) if rc.avg_hr is not None else None,
                start_time_offset_s=start_offset,
                end_time_offset_s=end_offset,
                arena_id=None,
                tile_ids=rc.tile_ids,
                avg_gradient_pct=rc.avg_gradient_pct,
                distance_m=rc.distance_m,
                signature_hex=rc.signature_v1_hex,
            )
            climb.signature_v2_hex = rc.signature_v2_hex
            climb.start_lat = rc.start_lat
            climb.start_lon = rc.start_lon
            climb.end_lat = rc.end_lat
            climb.end_lon = rc.end_lon
            climb.persistence = rc.persistence
            climbs.append(climb)
        return climbs

    for rc in rust_climbs:
        start_offset = _time_offset_s(
            getattr(rc, "start_time_offset_s", 0),
            base_time=sample_time_base,
        )
        end_offset = _time_offset_s(
            getattr(rc, "end_time_offset_s", 0),
            base_time=sample_time_base,
        )
        climb = ClimbPattern(
            vert_m=rc.vert_m,
            time_s=rc.time_s,
            avg_power_w=rc.avg_power_w,
            w_per_kg=rc.w_per_kg,
            avg_hr=rc.avg_hr,
            start_time_offset_s=start_offset,
            end_time_offset_s=end_offset,
            arena_id=rc.arena_id,
            tile_ids=rc.tile_ids,
            avg_gradient_pct=rc.avg_gradient_pct,
            distance_m=rc.distance_m,
            signature_hex=rc.signature_hex,
        )
        climb.signature_v2_hex = getattr(rc, "signature_v2_hex", None)
        climb.start_lat = getattr(rc, "start_lat", None)
        climb.start_lon = getattr(rc, "start_lon", None)
        climb.end_lat = getattr(rc, "end_lat", None)
        climb.end_lon = getattr(rc, "end_lon", None)
        climbs.append(climb)
    return climbs


def _persistence_sample_space(samples: List[Dict]) -> List[Dict]:
    """Mirror the samples Rust retains before assigning persistence indices."""
    retained: List[Dict] = []
    for sample in samples:
        if not isinstance(sample, dict):
            continue

        timestamp = sample.get("t")
        if isinstance(timestamp, bool):
            continue
        if isinstance(timestamp, int):
            rust_timestamp = timestamp
        elif (
            isinstance(timestamp, float)
            and math.isfinite(timestamp)
            and timestamp.is_integer()
        ):
            rust_timestamp = int(timestamp)
        else:
            continue
        if not -(2**63) <= rust_timestamp <= 2**63 - 1:
            continue

        elevation = sample.get("elevation_m")
        if isinstance(elevation, bool):
            continue
        try:
            numeric_elevation = float(elevation)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(numeric_elevation):
            continue

        normalized = dict(sample)
        normalized["t"] = rust_timestamp
        normalized["elevation_m"] = numeric_elevation
        retained.append(normalized)

    # Python and Rust use stable sorts, so equal timestamps preserve input order.
    return sorted(retained, key=lambda sample: sample["t"])


def _run_rust_detector(
    wp,
    *,
    tile_samples: List[Dict],
    persistence_candidate_samples: Optional[List[Dict]],
    sample_time_base: Any = None,
    terrain: str,
    config_overrides: Optional[Dict],
    arena_tiles: Optional[Set[str]],
    user_weight_kg: Optional[float],
    algorithm: str,
    generate_signatures: bool,
) -> List[ClimbPattern]:
    arena_list = list(arena_tiles) if arena_tiles else None
    sample_source = tile_samples

    if algorithm == "persistence":
        raw_sample_source = persistence_candidate_samples or tile_samples
        sample_source = _persistence_sample_space(raw_sample_source)
        rust_climbs = wp.detect_climbs_persistence(
            tile_samples=sample_source,
            user_weight_kg=user_weight_kg,
        )
    else:
        rust_climbs = wp.detect_climbs_adaptive(
            tile_samples=tile_samples,
            terrain=terrain,
            config_overrides=config_overrides,
            arena_tiles=arena_list,
            user_weight_kg=user_weight_kg,
            algorithm=algorithm,
            generate_signatures=generate_signatures,
        )

    return _convert_rust_climbs_to_patterns(
        rust_climbs,
        sample_source=sample_source,
        sample_time_base=sample_time_base,
        algorithm=algorithm,
        user_weight_kg=user_weight_kg,
    )


def _run_canonical_momentum_sweep(
    wp,
    *,
    tile_samples: List[Dict],
    sample_time_base: Any = None,
    config_overrides: Optional[Dict],
    arena_tiles: Optional[Set[str]],
    user_weight_kg: Optional[float],
    generate_signatures: bool,
) -> Tuple[Dict[str, List[ClimbPattern]], Optional[str], List[ClimbPattern]]:
    terrain_results: Dict[str, List[ClimbPattern]] = {}

    for terrain_name in CANONICAL_MOMENTUM_TERRAINS:
        try:
            terrain_candidates = _run_rust_detector(
                wp,
                tile_samples=tile_samples,
                persistence_candidate_samples=None,
                sample_time_base=sample_time_base,
                terrain=terrain_name,
                config_overrides=config_overrides,
                arena_tiles=arena_tiles,
                user_weight_kg=user_weight_kg,
                algorithm="momentum",
                generate_signatures=generate_signatures,
            )
        except Exception as exc:
            logger.warning(
                "Canonical terrain sweep failed for terrain=%s: %s",
                terrain_name,
                exc,
            )
            continue

        for climb in terrain_candidates:
            climb.detector_mode = f"canonical:momentum:{terrain_name}"
        terrain_results[terrain_name] = terrain_candidates

    if not terrain_results:
        return {}, None, []

    best_terrain, selected = max(
        terrain_results.items(),
        key=lambda item: (_score_terrain_result(item[1]), -len(item[1])),
    )
    logger.debug(
        "Canonical detector selected terrain=%s with %d climbs across %d evaluated terrain sets",
        best_terrain,
        len(selected),
        len(terrain_results),
    )
    return terrain_results, best_terrain, selected


def detect_climbs_with_rust(
    tile_samples: List[Dict],
    persistence_candidate_samples: Optional[List[Dict]] = None,
    terrain: str = "auto",
    config_overrides: Optional[Dict] = None,
    arena_tiles: Optional[Set[str]] = None,
    user_weight_kg: Optional[float] = None,
    algorithm: str = "momentum",
    generate_signatures: bool = True,
    frequency_map: Optional[Dict[str, int]] = None,
) -> List[ClimbPattern]:
    """
    Detect climb patterns using the high-performance Rust module with terrain-adaptive thresholds.

    This is the recommended method for production use. Falls back to Python detector
    if Rust module is not available.

    Args:
        tile_samples: Product-path samples used for terrain classification,
            momentum/canonical detection, and downstream matching/attribution.
        persistence_candidate_samples: Optional higher-fidelity per-point tile
            sequence used only for persistence candidate generation. When unset,
            persistence falls back to tile_samples.
        terrain: Terrain type or "auto" for automatic detection:
            - "flat": 15m min vert, 2% gradient, 150 VAM (Netherlands, Florida)
            - "rolling": 25m min vert, 2.5% gradient, 200 VAM (Philadelphia, UK)
            - "urban_hills": 20m min vert, tight boundaries (Philadelphia walls)
            - "hilly": 50m min vert, 4% gradient, 300 VAM (Bay Area, default)
            - "mountainous": 100m min vert, 5% gradient, 400 VAM (Alps)
            - "auto": Automatically classify terrain from elevation profile
        config_overrides: Optional dict of config values to override terrain preset:
            - vert_min_m, drop_tolerance_m, time_min_s, time_max_s, vam_min
            - gradient_min_pct, gradient_start_threshold, gradient_end_threshold
            - momentum_start_threshold, momentum_end_threshold, momentum_climb_rate, etc.
            - smoothing_window, gradient_window, max_trim_ratio
        arena_tiles: Optional set of tile IDs to filter (None = all tiles)
        user_weight_kg: User weight for W/kg calculation
        algorithm: "canonical", "canonical_v2", "momentum", "legacy", or "persistence"
        generate_signatures: Generate 64-byte vault signatures
        frequency_map: Optional dict of H3 res-8 tile -> detection count for Bayesian
            prior (H12 heuristic). Built from historical climb detections.

    Returns:
        List of ClimbPattern objects sorted by start time
    """
    sample_time_base = _infer_detector_time_base(
        tile_samples,
        persistence_candidate_samples,
    )
    tile_samples = _normalize_detector_sample_times(
        tile_samples,
        base_time=sample_time_base,
    )
    if persistence_candidate_samples is not None:
        persistence_candidate_samples = _normalize_detector_sample_times(
            persistence_candidate_samples,
            base_time=sample_time_base,
        )

    wp = _get_workout_parse()

    if wp is None:
        # Fall back to Python detector (persistence/canonical not available without Rust)
        logger.debug("Rust workout_parse not available, falling back to Python detector")
        fallback_algorithm = "momentum" if algorithm in {"canonical", "canonical_v2", "persistence"} else algorithm
        detector = ClimbPatternDetector(
            algorithm=fallback_algorithm,
            generate_signatures=generate_signatures,
        )
        return detector.detect_all(tile_samples, arena_tiles, user_weight_kg)

    # -------------------------------------------------------------------------
    # Canonical prelaunch detector: momentum terrain sweep + ride-level chooser
    # -------------------------------------------------------------------------
    if algorithm == "canonical":
        terrain_results, _best_terrain, selected = _run_canonical_momentum_sweep(
            wp,
            tile_samples=tile_samples,
            sample_time_base=sample_time_base,
            config_overrides=config_overrides,
            arena_tiles=arena_tiles,
            user_weight_kg=user_weight_kg,
            generate_signatures=generate_signatures,
        )
        if not terrain_results:
            return []
        return selected

    # -------------------------------------------------------------------------
    # Canonical V2 detector: shared proposal schema + fusion chooser
    # -------------------------------------------------------------------------
    if algorithm == "canonical_v2":
        ride_quality = RideQualityProfile.from_tile_samples(tile_samples)
        terrain_info = classify_terrain(tile_samples)
        ride_profile = build_ride_climb_profile(
            tile_samples,
            terrain_class=terrain_info.get("class") if terrain_info else None,
            terrain_confidence=terrain_info.get("confidence") if terrain_info else None,
        )
        terrain_results, best_terrain, momentum_selected = _run_canonical_momentum_sweep(
            wp,
            tile_samples=tile_samples,
            sample_time_base=sample_time_base,
            config_overrides=config_overrides,
            arena_tiles=arena_tiles,
            user_weight_kg=user_weight_kg,
            generate_signatures=generate_signatures,
        )

        persistence_climbs: List[ClimbPattern] = []
        try:
            persistence_climbs = _run_rust_detector(
                wp,
                tile_samples=tile_samples,
                persistence_candidate_samples=persistence_candidate_samples,
                sample_time_base=sample_time_base,
                terrain=terrain,
                config_overrides=config_overrides,
                arena_tiles=arena_tiles,
                user_weight_kg=user_weight_kg,
                algorithm="persistence",
                generate_signatures=generate_signatures,
            )
        except Exception as exc:
            logger.warning("Canonical_v2 persistence proposal generation failed: %s", exc)

        persistence_confirmation_climbs: Optional[List[ClimbPattern]] = None
        if _uses_separate_persistence_candidate_samples(
            tile_samples,
            persistence_candidate_samples,
        ):
            try:
                persistence_confirmation_climbs = _run_rust_detector(
                    wp,
                    tile_samples=tile_samples,
                    persistence_candidate_samples=None,
                    sample_time_base=sample_time_base,
                    terrain=terrain,
                    config_overrides=config_overrides,
                    arena_tiles=arena_tiles,
                    user_weight_kg=user_weight_kg,
                    algorithm="persistence",
                    generate_signatures=generate_signatures,
                )
            except Exception as exc:
                logger.warning(
                    "Canonical_v2 bridge-neutral persistence confirmation failed: %s",
                    exc,
                )
                persistence_confirmation_climbs = []

        v2_terrain_class = terrain_info.get("class") if terrain_info else None
        v2_total_gain_m = (
            terrain_info.get("metrics", {}).get("total_gain_m")
            if terrain_info
            else None
        )

        # Compute ride-level average power for H2 power confirmation heuristic
        power_samples = [
            s.get("power_w")
            for s in tile_samples
            if s.get("power_w") is not None and s.get("power_w") > 0
        ]
        v2_ride_avg_power_w = (
            sum(power_samples) / len(power_samples) if power_samples else None
        )

        selected = _choose_canonical_v2_climbs(
            ride_quality=ride_quality,
            ride_profile=ride_profile,
            momentum_results=terrain_results,
            persistence_climbs=persistence_climbs,
            terrain_class=v2_terrain_class,
            ride_total_gain_m=v2_total_gain_m,
            ride_avg_power_w=v2_ride_avg_power_w,
            tile_samples=tile_samples,
            frequency_map=frequency_map,
            persistence_confirmation_climbs=persistence_confirmation_climbs,
        )
        if selected:
            logger.debug(
                "Canonical_v2 selected %d climbs (quality=%s, momentum_best=%s, persistence=%d)",
                len(selected),
                ride_quality.source_class,
                best_terrain,
                len(persistence_climbs),
            )
            return selected

        # Chooser examined all candidates and rejected them — respect that decision.
        # Opt-in fallback available via CANONICAL_V2_FALLBACK_ENABLED=true for measurement.
        if os.getenv("CANONICAL_V2_FALLBACK_ENABLED", "false").lower() == "true":
            logger.info(
                "Canonical_v2 chooser rejected all candidates; fallback enabled, returning %d momentum climbs with low confidence",
                len(momentum_selected),
            )
            for climb in momentum_selected:
                climb.detector_mode = "canonical_v2:fallback"
                climb.confidence = 0.1
                climb.source_quality = ride_quality.to_dict()
                climb.route_profile = ride_profile.metrics_for_time_window(
                    climb.start_time_offset_s,
                    climb.end_time_offset_s,
                ).to_dict()
            return momentum_selected

        logger.debug(
            "Canonical_v2 chooser rejected all candidates (quality=%s, momentum_best=%s, persistence=%d); returning empty",
            ride_quality.source_class,
            best_terrain,
            len(persistence_climbs),
        )
        return []

    # -------------------------------------------------------------------------
    # V2 Persistence detector (parameter-free topological approach)
    # -------------------------------------------------------------------------
    if algorithm == "persistence":
        try:
            climbs = _run_rust_detector(
                wp,
                tile_samples=tile_samples,
                persistence_candidate_samples=persistence_candidate_samples,
                sample_time_base=sample_time_base,
                terrain=terrain,
                config_overrides=config_overrides,
                arena_tiles=arena_tiles,
                user_weight_kg=user_weight_kg,
                algorithm="persistence",
                generate_signatures=generate_signatures,
            )
            logger.debug(f"Persistence detector found {len(climbs)} climbs")
            return climbs

        except Exception as e:
            logger.warning(f"Persistence detector failed, falling back to momentum: {e}")
            # Fall through to momentum detector
            algorithm = "momentum"

    # -------------------------------------------------------------------------
    # V1 Momentum / Legacy detector
    # -------------------------------------------------------------------------
    try:
        climbs = _run_rust_detector(
            wp,
            tile_samples=tile_samples,
            persistence_candidate_samples=None,
            sample_time_base=sample_time_base,
            terrain=terrain,
            config_overrides=config_overrides,
            arena_tiles=arena_tiles,
            user_weight_kg=user_weight_kg,
            algorithm=algorithm,
            generate_signatures=generate_signatures,
        )

        logger.debug(f"Rust detector found {len(climbs)} climbs with terrain={terrain}")
        return climbs

    except Exception as e:
        logger.warning(f"Rust detector failed, falling back to Python: {e}")
        detector = ClimbPatternDetector(algorithm=algorithm, generate_signatures=generate_signatures)
        return detector.detect_all(tile_samples, arena_tiles, user_weight_kg)


def classify_terrain(tile_samples: List[Dict]) -> Optional[Dict]:
    """
    Classify terrain type from tile samples using Rust module.

    Returns terrain classification with class, confidence, metrics, and difficulty score.
    Returns None if classification fails or Rust module unavailable.

    Example return:
        {
            "class": "rolling",
            "class_value": 1,
            "confidence": 0.85,
            "difficulty_score": 3.2,
            "metrics": {
                "total_gain_m": 412.0,
                "max_sustained_gradient_pct": 4.5,
                ...
            }
        }
    """
    wp = _get_workout_parse()
    if wp is None:
        return None

    try:
        result = wp.classify_terrain(tile_samples)
        if result is None:
            return None
        return result.to_dict()
    except Exception as e:
        logger.debug(f"Terrain classification failed: {e}")
        return None
