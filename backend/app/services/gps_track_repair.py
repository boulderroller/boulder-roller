"""Repair helpers for persisted GPS track projection artifacts."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..utils.polyline import decode_gps_track, encode_gps_track
from .patterns.climb import detect_climbs_with_rust
from .tile_service import TileService
from .workout_parse_adapter import parse_ride_file_bytes_rust

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class V1ElevationSentinelAnalysis:
    """Evidence that a v1 stored track may contain missing elevation as 0m."""

    suspicious: bool
    reason: Optional[str]
    version: Optional[int]
    point_count: int
    zero_prefix_count: int
    first_nonzero_index: Optional[int]
    first_nonzero_elevation_m: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "suspicious": self.suspicious,
            "reason": self.reason,
            "version": self.version,
            "point_count": self.point_count,
            "zero_prefix_count": self.zero_prefix_count,
            "first_nonzero_index": self.first_nonzero_index,
            "first_nonzero_elevation_m": self.first_nonzero_elevation_m,
        }


@dataclass
class ReparsedRideProjection:
    """Projection produced by reparsing a raw ride file with current code."""

    encoded_gps_track: Dict[str, Any]
    decoded_points: List[Dict[str, Any]]
    tile_runs: List[Dict[str, Any]]
    climbs: List[Any]

    @property
    def summary(self) -> Dict[str, Any]:
        missing_ranges = self.encoded_gps_track.get("elevation_missing_ranges") or []
        return {
            "gps_track_version": self.encoded_gps_track.get("version"),
            "elevation_missing_ranges": missing_ranges[:5],
            "elevation_missing_range_count": len(missing_ranges),
            "decoded_points": len(self.decoded_points),
            "decoded_points_with_elevation": sum(
                1 for point in self.decoded_points if point.get("elevation_m") is not None
            ),
            "tile_runs": len(self.tile_runs),
            "tile_runs_with_elevation": sum(
                1 for sample in self.tile_runs if sample.get("elevation_m") is not None
            ),
            "climbs": [summarize_climb(climb) for climb in self.climbs],
        }


def analyze_v1_elevation_sentinel(
    gps_track: Any,
    *,
    min_zero_prefix: int = 5,
    min_jump_m: float = 50.0,
    zero_tolerance_m: float = 0.05,
) -> V1ElevationSentinelAnalysis:
    """Detect old stored tracks where missing altitude likely became 0m.

    Version 1 GPS tracks did not have a missing-elevation mask. The Corey-class
    failure looks like a prefix of exact 0m samples followed by an abrupt jump to
    real mountain altitude. Legitimate sea-level rides should not jump from 0m
    to hundreds of meters at the first nonzero sample.
    """
    if not isinstance(gps_track, dict) or not gps_track.get("polyline"):
        return V1ElevationSentinelAnalysis(False, "not_polyline_track", None, 0, 0, None, None)

    version = gps_track.get("version")
    if version and int(version) >= 2:
        return V1ElevationSentinelAnalysis(False, "already_v2", int(version), 0, 0, None, None)

    points = decode_gps_track(gps_track)
    zero_prefix_count = 0
    first_nonzero_index: Optional[int] = None
    first_nonzero_elevation_m: Optional[float] = None

    for idx, point in enumerate(points):
        elevation = point.get("elevation_m")
        if elevation is None:
            break
        try:
            elevation_m = float(elevation)
        except (TypeError, ValueError):
            break
        if abs(elevation_m) <= zero_tolerance_m and first_nonzero_index is None:
            zero_prefix_count += 1
            continue
        first_nonzero_index = idx
        first_nonzero_elevation_m = elevation_m
        break

    suspicious = (
        zero_prefix_count >= min_zero_prefix
        and first_nonzero_elevation_m is not None
        and abs(first_nonzero_elevation_m) >= min_jump_m
    )
    reason = "zero_prefix_altitude_jump" if suspicious else "no_v1_zero_prefix_jump"
    return V1ElevationSentinelAnalysis(
        suspicious=suspicious,
        reason=reason,
        version=int(version) if version is not None else None,
        point_count=len(points),
        zero_prefix_count=zero_prefix_count,
        first_nonzero_index=first_nonzero_index,
        first_nonzero_elevation_m=first_nonzero_elevation_m,
    )


def gps_track_records_from_parsed_ride(parsed_ride: Any) -> List[Dict[str, Any]]:
    """Convert parser GPS objects into the compact encoder's record schema."""
    records: List[Dict[str, Any]] = []
    for idx, point in enumerate(getattr(parsed_ride, "gps_track", []) or []):
        lat = getattr(point, "lat", None)
        if lat is None:
            lat = getattr(point, "latitude", None)
        lon = getattr(point, "lon", None)
        if lon is None:
            lon = getattr(point, "longitude", None)
        timestamp = getattr(point, "timestamp", None)
        if lat is None or lon is None or timestamp is None:
            continue
        records.append(
            {
                "sequence_num": idx,
                "timestamp": timestamp.isoformat() if hasattr(timestamp, "isoformat") else timestamp,
                "latitude": lat,
                "longitude": lon,
                "elevation_m": getattr(point, "elevation_m", None),
                "distance_m": getattr(point, "distance_m", None),
            }
        )
    return records


def reparse_raw_ride_projection(
    file_bytes: bytes,
    file_type: str,
    *,
    detector_algorithm: str = "canonical_v2",
    user_weight_kg: float = 75.0,
    resolution: int = TileService.DEFAULT_RESOLUTION,
) -> ReparsedRideProjection:
    """Reparse a raw ride file and rebuild GPS/climb projections."""
    parsed = parse_ride_file_bytes_rust(file_bytes, file_type)
    records = gps_track_records_from_parsed_ride(parsed)
    encoded = encode_gps_track(records)
    decoded = decode_gps_track(encoded)
    tile_runs = TileService().get_tile_run_sequence(
        points=decoded,
        resolution=resolution,
        start_time=None,
    )
    climbs = detect_climbs_with_rust(
        tile_samples=tile_runs,
        terrain="auto",
        user_weight_kg=user_weight_kg,
        algorithm=detector_algorithm,
        generate_signatures=True,
    )
    return ReparsedRideProjection(
        encoded_gps_track=encoded,
        decoded_points=decoded,
        tile_runs=tile_runs,
        climbs=climbs,
    )


def evaluate_climb_source_quality(
    climb: Any,
    samples: List[Dict[str, Any]],
    *,
    context: str,
) -> Dict[str, Any]:
    """Build an evidence trace and abstention decision for a detected climb."""
    start_t = int(getattr(climb, "start_time_offset_s", 0) or 0)
    end_t = int(getattr(climb, "end_time_offset_s", 0) or 0)

    def sample_get(sample: Any, key: str, default: Any = None) -> Any:
        if isinstance(sample, dict):
            return sample.get(key, default)
        return getattr(sample, key, default)

    def overlaps_climb(sample: Any) -> bool:
        sample_start = int(sample_get(sample, "t", 0) or 0)
        sample_end = int(sample_get(sample, "t_end", sample_start) or sample_start)
        return sample_end >= start_t and sample_start <= end_t

    climb_samples = [sample for sample in samples if overlaps_climb(sample)]
    total = len(climb_samples)
    elev_count = sum(1 for sample in climb_samples if sample_get(sample, "elevation_m") is not None)
    gps_count = sum(
        1
        for sample in climb_samples
        if sample_get(sample, "lat") is not None and sample_get(sample, "lon") is not None
    )
    elevation_coverage = (elev_count / total) if total else 0.0
    gps_coverage = (gps_count / total) if total else 0.0

    vert_m = float(getattr(climb, "vert_m", 0.0) or 0.0)
    time_s = int(getattr(climb, "time_s", 0) or 0)
    distance_m = float(getattr(climb, "distance_m", 0.0) or 0.0)
    avg_gradient_pct = getattr(climb, "avg_gradient_pct", None)
    gradient = float(avg_gradient_pct) if avg_gradient_pct is not None else None
    vam = (vert_m / time_s) * 3600.0 if time_s > 0 else 0.0

    reasons: List[str] = []
    if total == 0:
        reasons.append("CLIMB_SENSOR:no_samples_in_window")
    if total and elevation_coverage < 0.80:
        reasons.append(f"CLIMB_SENSOR:elev_coverage_{elevation_coverage:.0%}")
    if total and gps_coverage < 0.50:
        reasons.append(f"CLIMB_SENSOR:gps_coverage_{gps_coverage:.0%}")
    if vam > 2000:
        reasons.append(f"CLIMB_SENSOR:high_vam_{vam:.0f}")
    if vert_m >= 3000 and distance_m >= 30000 and gradient is not None and gradient >= 8.0:
        reasons.append("CLIMB_SHAPE:extreme_distance_grade_requires_raw_replay")

    return {
        "context": context,
        "sample_count": total,
        "elevation_coverage": round(elevation_coverage, 4),
        "gps_coverage": round(gps_coverage, 4),
        "vert_m": round(vert_m, 1),
        "time_s": time_s,
        "distance_m": round(distance_m, 1),
        "avg_gradient_pct": round(gradient, 2) if gradient is not None else None,
        "vam": round(vam, 1),
        "economic_eligible": not reasons,
        "abstention_reasons": reasons,
    }


def pattern_quality_kwargs(
    climb: Any,
    samples: List[Dict[str, Any]],
    *,
    context: str,
) -> Dict[str, Any]:
    """Return PatternRepository kwargs for quality/abstention evidence."""
    quality = evaluate_climb_source_quality(climb, samples, context=context)
    return {
        "economic_eligible": bool(quality["economic_eligible"]),
        "abstention_reasons": quality["abstention_reasons"] or None,
        "match_trace": {"source_quality": quality},
    }


def summarize_climb(climb: Any) -> Dict[str, Any]:
    return {
        "vert_m": round(float(getattr(climb, "vert_m", 0.0) or 0.0), 1),
        "time_s": int(getattr(climb, "time_s", 0) or 0),
        "distance_m": round(float(getattr(climb, "distance_m", 0.0) or 0.0), 1),
        "avg_gradient_pct": round(float(getattr(climb, "avg_gradient_pct", 0.0) or 0.0), 2),
        "start_s": int(getattr(climb, "start_time_offset_s", 0) or 0),
        "end_s": int(getattr(climb, "end_time_offset_s", 0) or 0),
        "persistence_m": round(float(getattr(climb, "persistence", 0.0) or 0.0), 1),
    }
