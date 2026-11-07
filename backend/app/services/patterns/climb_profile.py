from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
import math
from typing import Dict, List, Optional

from app.services.sample_time import infer_sample_time_base, sample_time_seconds


ESTIMATED_CYCLING_SPEED_MPS = 5.0
MAX_STEP_DISTANCE_M = 500.0


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _is_valid_gps(lat: Optional[float], lon: Optional[float]) -> bool:
    if lat is None or lon is None:
        return False
    if lat == 0.0 and lon == 0.0:
        return False
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return False
    return True


def _smooth_elevation(values: List[Optional[float]], window: int = 7) -> List[Optional[float]]:
    if not values:
        return []
    if len(values) <= window:
        return list(values)
    half_window = max(1, window // 2)
    smoothed: List[Optional[float]] = []
    for idx, value in enumerate(values):
        if value is None:
            smoothed.append(None)
            continue
        window_values = [
            sample
            for sample in values[max(0, idx - half_window): min(len(values), idx + half_window + 1)]
            if sample is not None
        ]
        smoothed.append(sum(window_values) / len(window_values) if window_values else value)
    return smoothed


@dataclass
class RouteProfilePoint:
    index: int
    t: float
    distance_m: float
    lat: Optional[float]
    lon: Optional[float]
    elevation_m: Optional[float]
    smoothed_elevation_m: Optional[float]
    grade_pct: Optional[float]
    tile_id: Optional[str]


@dataclass
class RouteWindowMetrics:
    start_idx: int
    end_idx: int
    start_time_s: int
    end_time_s: int
    start_distance_m: float
    end_distance_m: float
    span_distance_m: float
    ascent_m: float
    descent_m: float
    boundary_rise_m: float
    avg_grade_pct: Optional[float]

    def to_dict(self) -> Dict:
        return {
            "start_idx": self.start_idx,
            "end_idx": self.end_idx,
            "start_time_s": self.start_time_s,
            "end_time_s": self.end_time_s,
            "start_distance_m": round(self.start_distance_m, 1),
            "end_distance_m": round(self.end_distance_m, 1),
            "span_distance_m": round(self.span_distance_m, 1),
            "ascent_m": round(self.ascent_m, 1),
            "descent_m": round(self.descent_m, 1),
            "boundary_rise_m": round(self.boundary_rise_m, 1),
            "avg_grade_pct": round(self.avg_grade_pct, 2) if self.avg_grade_pct is not None else None,
        }


@dataclass
class RideClimbProfile:
    points: List[RouteProfilePoint]
    total_distance_m: float
    terrain_class: Optional[str] = None
    terrain_confidence: Optional[float] = None

    @property
    def times_s(self) -> List[float]:
        return [point.t for point in self.points]

    def closest_index_for_time(self, t: float) -> int:
        if not self.points:
            return 0
        times = self.times_s
        idx = bisect_left(times, t)
        if idx <= 0:
            return 0
        if idx >= len(times):
            return len(times) - 1
        before = times[idx - 1]
        after = times[idx]
        return idx if abs(after - t) < abs(t - before) else idx - 1

    def metrics_for_time_window(self, start_s: int, end_s: int) -> RouteWindowMetrics:
        if not self.points:
            return RouteWindowMetrics(
                start_idx=0,
                end_idx=0,
                start_time_s=start_s,
                end_time_s=end_s,
                start_distance_m=0.0,
                end_distance_m=0.0,
                span_distance_m=0.0,
                ascent_m=0.0,
                descent_m=0.0,
                boundary_rise_m=0.0,
                avg_grade_pct=None,
            )

        start_idx = self.closest_index_for_time(start_s)
        end_idx = self.closest_index_for_time(end_s)
        if end_idx < start_idx:
            start_idx, end_idx = end_idx, start_idx

        segment = self.points[start_idx: end_idx + 1]
        start_point = segment[0]
        end_point = segment[-1]

        ascent_m = 0.0
        descent_m = 0.0
        prev_elev = segment[0].smoothed_elevation_m
        for point in segment[1:]:
            elev = point.smoothed_elevation_m
            if prev_elev is None or elev is None:
                prev_elev = elev
                continue
            delta = elev - prev_elev
            if delta > 0:
                ascent_m += delta
            elif delta < 0:
                descent_m += -delta
            prev_elev = elev

        boundary_rise_m = 0.0
        if start_point.smoothed_elevation_m is not None and end_point.smoothed_elevation_m is not None:
            boundary_rise_m = end_point.smoothed_elevation_m - start_point.smoothed_elevation_m

        span_distance_m = max(0.0, end_point.distance_m - start_point.distance_m)
        avg_grade_pct = (ascent_m / span_distance_m) * 100.0 if span_distance_m > 0 else None

        return RouteWindowMetrics(
            start_idx=start_idx,
            end_idx=end_idx,
            start_time_s=int(round(start_point.t)),
            end_time_s=int(round(end_point.t)),
            start_distance_m=start_point.distance_m,
            end_distance_m=end_point.distance_m,
            span_distance_m=span_distance_m,
            ascent_m=ascent_m,
            descent_m=descent_m,
            boundary_rise_m=boundary_rise_m,
            avg_grade_pct=avg_grade_pct,
        )


def build_ride_climb_profile(
    tile_samples: List[Dict],
    *,
    terrain_class: Optional[str] = None,
    terrain_confidence: Optional[float] = None,
) -> RideClimbProfile:
    if not tile_samples:
        return RideClimbProfile(points=[], total_distance_m=0.0, terrain_class=terrain_class, terrain_confidence=terrain_confidence)

    base_time = infer_sample_time_base(tile_samples)
    samples_with_time = [
        (sample, seconds)
        for sample in tile_samples
        if (seconds := sample_time_seconds(sample.get("t"), base_time=base_time)) is not None
    ]
    if not samples_with_time:
        return RideClimbProfile(points=[], total_distance_m=0.0, terrain_class=terrain_class, terrain_confidence=terrain_confidence)

    samples_with_time = sorted(samples_with_time, key=lambda item: item[1])
    ordered = [sample for sample, _seconds in samples_with_time]
    sample_seconds = [seconds for _sample, seconds in samples_with_time]
    elevations = [sample.get("elevation_m") for sample in ordered]
    smoothed = _smooth_elevation(elevations)

    points: List[RouteProfilePoint] = []
    total_distance = 0.0

    for idx, sample in enumerate(ordered):
        if idx > 0:
            prev = ordered[idx - 1]
            lat1 = prev.get("lat")
            lon1 = prev.get("lon")
            lat2 = sample.get("lat")
            lon2 = sample.get("lon")
            if _is_valid_gps(lat1, lon1) and _is_valid_gps(lat2, lon2):
                step_distance = min(MAX_STEP_DISTANCE_M, _haversine_m(lat1, lon1, lat2, lon2))
            else:
                dt = max(0.0, sample_seconds[idx] - sample_seconds[idx - 1])
                speed = sample.get("speed_mps") or prev.get("speed_mps") or ESTIMATED_CYCLING_SPEED_MPS
                step_distance = min(MAX_STEP_DISTANCE_M, dt * float(speed))
            total_distance += step_distance

        grade_pct: Optional[float] = None
        if idx > 0 and smoothed[idx - 1] is not None and smoothed[idx] is not None:
            delta = smoothed[idx] - smoothed[idx - 1]
            prev_distance = points[-1].distance_m if points else 0.0
            dist_delta = max(0.0, total_distance - prev_distance)
            if dist_delta > 0.0:
                grade_pct = (delta / dist_delta) * 100.0

        points.append(
            RouteProfilePoint(
                index=idx,
                t=sample_seconds[idx],
                distance_m=total_distance,
                lat=sample.get("lat"),
                lon=sample.get("lon"),
                elevation_m=sample.get("elevation_m"),
                smoothed_elevation_m=smoothed[idx],
                grade_pct=grade_pct,
                tile_id=sample.get("tile_id"),
            )
        )

    return RideClimbProfile(
        points=points,
        total_distance_m=total_distance,
        terrain_class=terrain_class,
        terrain_confidence=terrain_confidence,
    )
