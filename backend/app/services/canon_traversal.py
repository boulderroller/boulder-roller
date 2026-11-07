"""Exact D11 traversal of ratified climb-canon geometry.

H3 cells are only a candidate prefilter. Every acceptance decision in this
module uses dense raw GPS samples against the exact gates, corridor, and
centerline stored in ``canon_climbs``.
"""

from __future__ import annotations

import asyncio
import math
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from uuid import NAMESPACE_URL, UUID, uuid5

from pyproj import CRS, Transformer
from shapely.geometry import GeometryCollection, LineString, MultiPoint, Point
from shapely.ops import transform

from ..models.canon import CanonClimb
from ..models.patterns import ClimbPattern
from ..repositories.canon import CanonRepository


CORRIDOR_COVERAGE_THRESHOLD = 0.80
BACKTRACK_JITTER_TOLERANCE_M = 12.0
CENTERLINE_AMBIGUITY_DISTANCE_M = 0.50
MIN_DIRECTION_PROGRESS_M = 1e-6
_GATE_SIDE_EPSILON_M = 0.02
_DUPLICATE_CROSSING_TIME_S = 1e-3
_DUPLICATE_CROSSING_DISTANCE_M = 0.05
_MAX_CONTIGUOUS_COVERAGE_GAP_S = 30.0
_TRACE_VERSION = "canon_traversal_trace_v1"
_DETECTOR_VERSION = "canon_traversal_v1"
_PENDING_ACTIVATION_REASON = "MATCH:canon_activation_required"


def authoritative_canon_climb_id(pattern_row: Mapping[str, Any]) -> Optional[str]:
    """Canon registry row UUID for a stored climb-pattern row, authority only.

    Returns the registry UUID (``canon_climbs.id`` — the climb-sheet key, same
    space as ``indexed_vaults.canon_climb_id``) exactly when the pattern IS an
    authoritative canon traversal: written by this engine and still carrying
    its canon keys. Detector-era or discovery-only rows had those keys moved
    into ``non_authoritative_detector_claim`` by enrichment, so they return
    ``None`` here — no similarity guessing, completion state irrelevant.
    (boulderroller-v2-nrbu5)
    """

    if pattern_row.get("detector_version") != _DETECTOR_VERSION:
        return None
    trace = pattern_row.get("match_trace")
    if isinstance(trace, str):
        try:
            import json

            trace = json.loads(trace)
        except (TypeError, ValueError):
            return None
    if not isinstance(trace, Mapping):
        return None
    if trace.get("authority") == "discovery_only":
        return None
    registry_id = trace.get("registry_id")
    if not registry_id:
        return None
    try:
        return str(UUID(str(registry_id)))
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class RawTraversalSample:
    """Normalized raw GPS sample with its stable source position."""

    source_index: int
    t_s: float
    lat: float
    lon: float
    tile_id: Optional[str] = None
    power_w: Optional[float] = None
    hr_bpm: Optional[float] = None


@dataclass(frozen=True)
class GateCrossing:
    """Interpolated intersection between one GPS segment and one canon gate."""

    gate: str
    time_s: float
    lon: float
    lat: float
    interpolation_u: float
    segment_start_source_index: int
    segment_end_source_index: int
    segment_start_time_s: float
    segment_end_time_s: float
    segment_start_lon: float
    segment_start_lat: float
    segment_end_lon: float
    segment_end_lat: float
    before_progress_m: float
    after_progress_m: float
    before_gate_side_m: float
    after_gate_side_m: float
    gate_position_m: float
    gate_length_m: float
    direction_before_source_index: int
    direction_after_source_index: int
    direction_before_lon: float
    direction_before_lat: float
    direction_after_lon: float
    direction_after_lat: float

    @property
    def crosses_gate(self) -> bool:
        straddles = (
            self.before_gate_side_m < -_GATE_SIDE_EPSILON_M
            and self.after_gate_side_m > _GATE_SIDE_EPSILON_M
        ) or (
            self.before_gate_side_m > _GATE_SIDE_EPSILON_M
            and self.after_gate_side_m < -_GATE_SIDE_EPSILON_M
        )
        return straddles

    @property
    def direction(self) -> int:
        delta = self.after_progress_m - self.before_progress_m
        if delta > MIN_DIRECTION_PROGRESS_M:
            return 1
        if delta < -MIN_DIRECTION_PROGRESS_M:
            return -1
        return 0

    def to_trace(self) -> Dict[str, Any]:
        return {
            "time_s_raw": self.time_s,
            "interpolation_u": self.interpolation_u,
            "bracketing_samples": {
                "start": {
                    "source_index": self.segment_start_source_index,
                    "t_s": self.segment_start_time_s,
                },
                "end": {
                    "source_index": self.segment_end_source_index,
                    "t_s": self.segment_end_time_s,
                },
            },
            "direction_evidence": {
                "before": {
                    "source_index": self.direction_before_source_index,
                    "gate_side_m": self.before_gate_side_m,
                    "along_track_m": self.before_progress_m,
                },
                "after": {
                    "source_index": self.direction_after_source_index,
                    "gate_side_m": self.after_gate_side_m,
                    "along_track_m": self.after_progress_m,
                },
                "gate_position_m": self.gate_position_m,
                "gate_length_m": self.gate_length_m,
                "endpoint_policy": "inclusive",
            },
        }


@dataclass
class CanonTraversalAttempt:
    """One paired D11 window, accepted or rejected with a stable reason."""

    canon_id: UUID
    canon_version: int
    start: Optional[GateCrossing]
    finish: Optional[GateCrossing]
    accepted: bool
    rejection_code: Optional[str]
    inside_count: int = 0
    intermediate_count: int = 0
    coverage_ratio: float = 0.0
    max_backtrack_m: float = 0.0
    pattern: Optional[ClimbPattern] = None


@dataclass
class CanonTraversalEvaluation:
    """All traversal evidence for one ride, including accepted repeats."""

    climb_patterns: List[ClimbPattern] = field(default_factory=list)
    attempts: List[CanonTraversalAttempt] = field(default_factory=list)
    best_per_canon: Dict[str, ClimbPattern] = field(default_factory=dict)
    covered_intervals: List[Tuple[float, float]] = field(default_factory=list)
    considered_tile_ids: set = field(default_factory=set)
    rejections: Dict[str, int] = field(default_factory=dict)

    def overlaps_canon_coverage(self, start_s: float, end_s: float) -> bool:
        """Whether a detector-shaped effort overlaps exact canon geography."""

        low, high = sorted((float(start_s), float(end_s)))
        return any(low <= interval_end and high >= interval_start for interval_start, interval_end in self.covered_intervals)


@dataclass(frozen=True)
class _ProjectedCandidate:
    forward: Transformer
    inverse: Transformer
    centerline: LineString
    gate_start: LineString
    gate_end: LineString


def _finite_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _normalize_samples(
    raw_samples: Sequence[Mapping[str, Any]],
) -> Tuple[List[RawTraversalSample], List[float], int]:
    samples: List[RawTraversalSample] = []
    malformed_timed: List[float] = []
    malformed = 0
    for fallback_source_index, raw in enumerate(raw_samples):
        source_index_raw = raw.get("source_index", fallback_source_index)
        source_index = (
            source_index_raw
            if isinstance(source_index_raw, int)
            and not isinstance(source_index_raw, bool)
            and source_index_raw >= 0
            else fallback_source_index
        )
        t_s = _finite_float(raw.get("t"))
        lat = _finite_float(raw.get("lat"))
        lon = _finite_float(raw.get("lon"))
        if t_s is None or lat is None or lon is None:
            malformed += 1
            if t_s is not None:
                malformed_timed.append(t_s)
            continue
        power_w = _finite_float(raw.get("power_w"))
        hr_bpm = _finite_float(raw.get("hr_bpm"))
        tile_id = raw.get("tile_id")
        samples.append(
            RawTraversalSample(
                source_index=source_index,
                t_s=t_s,
                lat=lat,
                lon=lon,
                tile_id=str(tile_id) if tile_id else None,
                power_w=power_w,
                hr_bpm=hr_bpm,
            )
        )
    samples.sort(key=lambda item: (item.t_s, item.source_index))
    malformed_timed.sort()
    return samples, malformed_timed, malformed


def _project_candidate(candidate: CanonClimb) -> _ProjectedCandidate:
    midpoint = candidate.centerline.interpolate(0.5, normalized=True)
    local_crs = CRS.from_proj4(
        "+proj=aeqd "
        f"+lat_0={midpoint.y:.12f} +lon_0={midpoint.x:.12f} "
        "+datum=WGS84 +units=m +no_defs"
    )
    forward = Transformer.from_crs("EPSG:4326", local_crs, always_xy=True)
    inverse = Transformer.from_crs(local_crs, "EPSG:4326", always_xy=True)
    return _ProjectedCandidate(
        forward=forward,
        inverse=inverse,
        centerline=transform(forward.transform, candidate.centerline),
        gate_start=transform(forward.transform, candidate.gate_start),
        gate_end=transform(forward.transform, candidate.gate_end),
    )


def _intersection_points(geometry: Any) -> List[Point]:
    if geometry.is_empty:
        return []
    if isinstance(geometry, Point):
        return [geometry]
    if isinstance(geometry, MultiPoint):
        return list(geometry.geoms)
    if isinstance(geometry, GeometryCollection):
        points: List[Point] = []
        for item in geometry.geoms:
            points.extend(_intersection_points(item))
        return points
    # A ride segment travelling along a gate is a touch/overlap, not a
    # side-to-side crossing. It produces no timing event.
    return []


def _signed_gate_side_m(gate: LineString, point: Point) -> float:
    start = gate.coords[0]
    end = gate.coords[-1]
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return 0.0
    return float((dx * (point.y - start[1]) - dy * (point.x - start[0])) / length)


def _gate_observations(
    *,
    gate_name: str,
    gate: LineString,
    projected: _ProjectedCandidate,
    samples: Sequence[RawTraversalSample],
) -> List[GateCrossing]:
    observations: List[GateCrossing] = []
    for segment_index, (sample_a, sample_b) in enumerate(
        zip(samples, samples[1:])
    ):
        if sample_b.t_s <= sample_a.t_s:
            continue
        x0, y0 = projected.forward.transform(sample_a.lon, sample_a.lat)
        x1, y1 = projected.forward.transform(sample_b.lon, sample_b.lat)
        segment = LineString([(x0, y0), (x1, y1)])
        if segment.length == 0:
            continue
        intersection = segment.intersection(gate)
        for point in _intersection_points(intersection):
            direction_before = sample_a
            direction_before_point = Point(x0, y0)
            direction_before_side = _signed_gate_side_m(
                gate,
                direction_before_point,
            )
            before_index = segment_index - 1
            while (
                abs(direction_before_side) <= _GATE_SIDE_EPSILON_M
                and before_index >= 0
            ):
                direction_before = samples[before_index]
                before_x, before_y = projected.forward.transform(
                    direction_before.lon,
                    direction_before.lat,
                )
                direction_before_point = Point(before_x, before_y)
                direction_before_side = _signed_gate_side_m(
                    gate,
                    direction_before_point,
                )
                before_index -= 1

            direction_after = sample_b
            direction_after_point = Point(x1, y1)
            direction_after_side = _signed_gate_side_m(
                gate,
                direction_after_point,
            )
            after_index = segment_index + 2
            while (
                abs(direction_after_side) <= _GATE_SIDE_EPSILON_M
                and after_index < len(samples)
            ):
                direction_after = samples[after_index]
                after_x, after_y = projected.forward.transform(
                    direction_after.lon,
                    direction_after.lat,
                )
                direction_after_point = Point(after_x, after_y)
                direction_after_side = _signed_gate_side_m(
                    gate,
                    direction_after_point,
                )
                after_index += 1

            u = float(max(0.0, min(1.0, segment.project(point) / segment.length)))
            time_s = sample_a.t_s + u * (sample_b.t_s - sample_a.t_s)
            lon, lat = projected.inverse.transform(point.x, point.y)
            crossing = GateCrossing(
                gate=gate_name,
                time_s=time_s,
                lon=float(lon),
                lat=float(lat),
                interpolation_u=u,
                segment_start_source_index=sample_a.source_index,
                segment_end_source_index=sample_b.source_index,
                segment_start_time_s=sample_a.t_s,
                segment_end_time_s=sample_b.t_s,
                segment_start_lon=sample_a.lon,
                segment_start_lat=sample_a.lat,
                segment_end_lon=sample_b.lon,
                segment_end_lat=sample_b.lat,
                before_progress_m=float(
                    projected.centerline.project(direction_before_point)
                ),
                after_progress_m=float(
                    projected.centerline.project(direction_after_point)
                ),
                before_gate_side_m=direction_before_side,
                after_gate_side_m=direction_after_side,
                gate_position_m=float(gate.project(point)),
                gate_length_m=float(gate.length),
                direction_before_source_index=direction_before.source_index,
                direction_after_source_index=direction_after.source_index,
                direction_before_lon=direction_before.lon,
                direction_before_lat=direction_before.lat,
                direction_after_lon=direction_after.lon,
                direction_after_lat=direction_after.lat,
            )
            if observations:
                previous = observations[-1]
                previous_x, previous_y = projected.forward.transform(previous.lon, previous.lat)
                duplicate = (
                    abs(previous.time_s - crossing.time_s) <= _DUPLICATE_CROSSING_TIME_S
                    and Point(previous_x, previous_y).distance(point)
                    <= _DUPLICATE_CROSSING_DISTANCE_M
                )
                if duplicate:
                    # Keep the first segment as the timing bracket, but use the
                    # last adjacent segment to decide whether the rider really
                    # passed through the gate or merely touched and returned.
                    observations[-1] = replace(
                        previous,
                        after_progress_m=crossing.after_progress_m,
                        after_gate_side_m=crossing.after_gate_side_m,
                        direction_after_source_index=(
                            crossing.direction_after_source_index
                        ),
                        direction_after_lon=crossing.direction_after_lon,
                        direction_after_lat=crossing.direction_after_lat,
                    )
                    continue
            observations.append(crossing)
    return observations


def _covered_intervals(
    candidate: CanonClimb,
    samples: Sequence[RawTraversalSample],
) -> List[Tuple[float, float]]:
    intervals: List[Tuple[float, float]] = []
    start: Optional[float] = None
    previous_inside: Optional[float] = None
    for sample in samples:
        inside = candidate.corridor.covers(Point(sample.lon, sample.lat))
        gap = (
            sample.t_s - previous_inside
            if previous_inside is not None
            else 0.0
        )
        if inside and (
            start is None
            or gap <= _MAX_CONTIGUOUS_COVERAGE_GAP_S
        ):
            if start is None:
                start = sample.t_s
            previous_inside = sample.t_s
            continue
        if start is not None and previous_inside is not None:
            intervals.append((start, previous_inside))
            start = None
            previous_inside = None
        if inside:
            start = sample.t_s
            previous_inside = sample.t_s
    if start is not None and previous_inside is not None:
        intervals.append((start, previous_inside))
    return intervals


def _mean(values: Iterable[Optional[float]]) -> Optional[float]:
    present = [float(value) for value in values if value is not None]
    if not present:
        return None
    return sum(present) / len(present)


def _continuity_aware_progress(
    centerline: LineString,
    points: Sequence[Point],
) -> List[float]:
    """Project samples without jumping between nearby switchback arms."""

    coordinates = list(centerline.coords)
    segments: List[Tuple[LineString, float]] = []
    cumulative = 0.0
    for start, end in zip(coordinates, coordinates[1:]):
        segment = LineString([start, end])
        if segment.length == 0:
            continue
        segments.append((segment, cumulative))
        cumulative += segment.length
    if not segments:
        return [0.0 for _ in points]

    progress: List[float] = []
    previous: Optional[float] = None
    for point in points:
        choices = [
            (
                float(point.distance(segment)),
                float(offset + segment.project(point)),
            )
            for segment, offset in segments
        ]
        minimum_distance = min(distance for distance, _ in choices)
        plausible = [
            (distance, along_track)
            for distance, along_track in choices
            if distance <= minimum_distance + CENTERLINE_AMBIGUITY_DISTANCE_M
        ]
        if previous is None:
            _, selected = min(plausible, key=lambda choice: (choice[0], choice[1]))
        else:
            _, selected = min(
                plausible,
                key=lambda choice: (
                    abs(choice[1] - previous),
                    choice[0],
                    choice[1],
                ),
            )
        progress.append(selected)
        previous = selected
    return progress


def _rounded_whole_second(value: float) -> int:
    # Match the established detector/storage convention. The raw fractional
    # value remains in match_trace for audit and boundary replay.
    return int(round(value))


class CanonTraversalEngine:
    """Pure, deterministic evaluator for locked D11 traversal semantics."""

    def evaluate(
        self,
        *,
        activity_id: UUID,
        wallet: str,
        candidates: Sequence[CanonClimb],
        raw_samples: Sequence[Mapping[str, Any]],
        user_weight_kg: Optional[float] = None,
    ) -> CanonTraversalEvaluation:
        samples, malformed_timed_samples, malformed_sample_count = _normalize_samples(
            raw_samples
        )
        evaluation = CanonTraversalEvaluation()
        aggregate_rejections: Counter = Counter()
        if malformed_sample_count:
            aggregate_rejections["malformed_sample"] += malformed_sample_count

        for candidate in sorted(candidates, key=lambda item: (str(item.canon_id), item.version)):
            projected = _project_candidate(candidate)
            candidate_tiles = set(candidate.corridor_tile_ids)
            ride_tiles = {sample.tile_id for sample in samples if sample.tile_id}
            prefilter_tiles = sorted(candidate_tiles.intersection(ride_tiles))
            evaluation.considered_tile_ids.update(prefilter_tiles)

            evaluation.covered_intervals.extend(_covered_intervals(candidate, samples))

            starts = _gate_observations(
                gate_name="start",
                gate=projected.gate_start,
                projected=projected,
                samples=samples,
            )
            finishes = _gate_observations(
                gate_name="finish",
                gate=projected.gate_end,
                projected=projected,
                samples=samples,
            )
            events = sorted(starts + finishes, key=lambda event: (event.time_s, event.gate))
            attempts, pairing_rejections = self._pair_attempts(candidate, events)
            aggregate_rejections.update(pairing_rejections)

            accepted_for_candidate: List[ClimbPattern] = []
            for attempt in attempts:
                if attempt.start is None or attempt.finish is None:
                    evaluation.attempts.append(attempt)
                    continue
                self._evaluate_window(
                    attempt=attempt,
                    candidate=candidate,
                    projected=projected,
                    samples=samples,
                    malformed_timed_samples=malformed_timed_samples,
                    activity_id=activity_id,
                    wallet=wallet,
                    user_weight_kg=user_weight_kg,
                    prefilter_tiles=prefilter_tiles,
                )
                evaluation.attempts.append(attempt)
                if attempt.accepted and attempt.pattern is not None:
                    accepted_for_candidate.append(attempt.pattern)
                elif attempt.rejection_code:
                    aggregate_rejections[attempt.rejection_code] += 1

            accepted_for_candidate.sort(
                key=lambda pattern: (
                    pattern.start_offset_s,
                    pattern.end_offset_s,
                    str(pattern.id),
                )
            )
            if accepted_for_candidate:
                best_time_s = min(
                    pattern.time_s for pattern in accepted_for_candidate
                )
                tied_best = [
                    pattern
                    for pattern in accepted_for_candidate
                    if pattern.time_s == best_time_s
                ]
                representative = min(
                    tied_best,
                    key=lambda pattern: (
                        pattern.start_offset_s,
                        pattern.end_offset_s,
                        str(pattern.id),
                    ),
                )
                pass_count = len(accepted_for_candidate)
                for pass_index, pattern in enumerate(accepted_for_candidate, start=1):
                    pattern.match_trace["pass_index"] = pass_index
                    pattern.match_trace["pass_count"] = pass_count
                    pattern.match_trace["best_for_canon"] = (
                        pattern.time_s == best_time_s
                    )
                    pattern.match_trace["best_tie_count"] = len(tied_best)
                    pattern.match_trace["best_representative"] = (
                        pattern.id == representative.id
                    )
                evaluation.best_per_canon[str(candidate.canon_id)] = representative
                evaluation.climb_patterns.extend(accepted_for_candidate)

        evaluation.climb_patterns.sort(
            key=lambda pattern: (pattern.start_offset_s, pattern.end_offset_s, str(pattern.id))
        )
        evaluation.covered_intervals = self._merge_intervals(evaluation.covered_intervals)
        evaluation.rejections = dict(sorted(aggregate_rejections.items()))
        for pattern in evaluation.climb_patterns:
            pattern.match_trace["ride_rejection_counters"] = evaluation.rejections.copy()
        return evaluation

    @staticmethod
    def _pair_attempts(
        candidate: CanonClimb,
        events: Sequence[GateCrossing],
    ) -> Tuple[List[CanonTraversalAttempt], Counter]:
        attempts: List[CanonTraversalAttempt] = []
        rejections: Counter = Counter()
        active_start: Optional[GateCrossing] = None

        for event in events:
            if not event.crosses_gate:
                rejections["gate_touch_without_crossing"] += 1
                attempts.append(
                    CanonTraversalAttempt(
                        canon_id=candidate.canon_id,
                        canon_version=candidate.version,
                        start=event if event.gate == "start" else None,
                        finish=event if event.gate == "finish" else None,
                        accepted=False,
                        rejection_code="gate_touch_without_crossing",
                    )
                )
                continue
            if event.direction < 0:
                rejections["reverse_direction"] += 1
                attempts.append(
                    CanonTraversalAttempt(
                        canon_id=candidate.canon_id,
                        canon_version=candidate.version,
                        start=event if event.gate == "start" else None,
                        finish=event if event.gate == "finish" else None,
                        accepted=False,
                        rejection_code="reverse_direction",
                    )
                )
                if active_start is not None and event.gate == "start":
                    attempts.append(
                        CanonTraversalAttempt(
                            canon_id=candidate.canon_id,
                            canon_version=candidate.version,
                            start=active_start,
                            finish=None,
                            accepted=False,
                            rejection_code="u_turn",
                        )
                    )
                    rejections["u_turn"] += 1
                    active_start = None
                continue
            if event.direction == 0:
                rejections["gate_touch_without_crossing"] += 1
                attempts.append(
                    CanonTraversalAttempt(
                        canon_id=candidate.canon_id,
                        canon_version=candidate.version,
                        start=event if event.gate == "start" else None,
                        finish=event if event.gate == "finish" else None,
                        accepted=False,
                        rejection_code="gate_touch_without_crossing",
                    )
                )
                continue

            if event.gate == "start":
                if active_start is not None:
                    attempts.append(
                        CanonTraversalAttempt(
                            canon_id=candidate.canon_id,
                            canon_version=candidate.version,
                            start=active_start,
                            finish=None,
                            accepted=False,
                            rejection_code="restart_before_finish",
                        )
                    )
                    rejections["restart_before_finish"] += 1
                active_start = event
                continue

            if active_start is None:
                attempts.append(
                    CanonTraversalAttempt(
                        canon_id=candidate.canon_id,
                        canon_version=candidate.version,
                        start=None,
                        finish=event,
                        accepted=False,
                        rejection_code="partial_traversal",
                    )
                )
                rejections["partial_traversal"] += 1
                continue
            if event.time_s <= active_start.time_s:
                rejections["finish_before_start"] += 1
                continue
            attempts.append(
                CanonTraversalAttempt(
                    canon_id=candidate.canon_id,
                    canon_version=candidate.version,
                    start=active_start,
                    finish=event,
                    accepted=False,
                    rejection_code=None,
                )
            )
            active_start = None

        if active_start is not None:
            attempts.append(
                CanonTraversalAttempt(
                    canon_id=candidate.canon_id,
                    canon_version=candidate.version,
                    start=active_start,
                    finish=None,
                    accepted=False,
                    rejection_code="partial_traversal",
                )
            )
            rejections["partial_traversal"] += 1
        return attempts, rejections

    @staticmethod
    def _evaluate_window(
        *,
        attempt: CanonTraversalAttempt,
        candidate: CanonClimb,
        projected: _ProjectedCandidate,
        samples: Sequence[RawTraversalSample],
        malformed_timed_samples: Sequence[float],
        activity_id: UUID,
        wallet: str,
        user_weight_kg: Optional[float],
        prefilter_tiles: Sequence[str],
    ) -> None:
        assert attempt.start is not None and attempt.finish is not None
        intermediate = [
            sample
            for sample in samples
            if attempt.start.time_s < sample.t_s < attempt.finish.time_s
        ]
        malformed_in_window = sum(
            attempt.start.time_s < time_s < attempt.finish.time_s
            for time_s in malformed_timed_samples
        )
        attempt.intermediate_count = len(intermediate) + malformed_in_window
        if not intermediate:
            attempt.rejection_code = "no_intermediate_points"
            return

        inside = [
            sample
            for sample in intermediate
            if candidate.corridor.covers(Point(sample.lon, sample.lat))
        ]
        attempt.inside_count = len(inside)
        attempt.coverage_ratio = attempt.inside_count / attempt.intermediate_count
        if attempt.coverage_ratio < CORRIDOR_COVERAGE_THRESHOLD:
            attempt.rejection_code = "corridor_coverage_below_threshold"
            return

        projected_points: List[Point] = []
        for sample in intermediate:
            x, y = projected.forward.transform(sample.lon, sample.lat)
            projected_points.append(Point(x, y))
        progress = _continuity_aware_progress(projected.centerline, projected_points)
        running_max = progress[0]
        max_backtrack = 0.0
        for value in progress[1:]:
            max_backtrack = max(max_backtrack, running_max - value)
            running_max = max(running_max, value)
        attempt.max_backtrack_m = max_backtrack
        if max_backtrack > BACKTRACK_JITTER_TOLERANCE_M:
            attempt.rejection_code = "u_turn"
            return

        raw_duration = attempt.finish.time_s - attempt.start.time_s
        time_s = _rounded_whole_second(raw_duration)
        start_offset_s = _rounded_whole_second(attempt.start.time_s)
        end_offset_s = _rounded_whole_second(attempt.finish.time_s)
        crossed_tiles: List[str] = []
        candidate_tiles = set(candidate.corridor_tile_ids)
        for sample in inside:
            if sample.tile_id and sample.tile_id in candidate_tiles and sample.tile_id not in crossed_tiles:
                crossed_tiles.append(sample.tile_id)
        if not crossed_tiles:
            crossed_tiles = list(prefilter_tiles)

        avg_power_w = _mean(sample.power_w for sample in intermediate)
        avg_hr_value = _mean(sample.hr_bpm for sample in intermediate)
        avg_hr = _rounded_whole_second(avg_hr_value) if avg_hr_value is not None else None
        weight = _finite_float(user_weight_kg)
        w_per_kg = avg_power_w / weight if avg_power_w is not None and weight and weight > 0 else None
        deterministic_id = uuid5(
            NAMESPACE_URL,
            "boulderroller:canon-traversal-v1:"
            f"{activity_id}:{candidate.canon_id}:{candidate.version}:"
            f"{candidate.registry_snapshot_digest}:"
            f"{attempt.start.time_s:.9f}:{attempt.finish.time_s:.9f}",
        )

        trace: Dict[str, Any] = {
            "trace_version": _TRACE_VERSION,
            "canon_id": str(candidate.canon_id),
            "registry_id": str(candidate.registry_id),
            "canon_version": candidate.version,
            "version": candidate.version,
            "candidate_fingerprint": candidate.candidate_fingerprint,
            "registry_snapshot_digest": candidate.registry_snapshot_digest,
            "compiler_version": candidate.compiler_version,
            "prefilter": {
                "h3_resolution": 10,
                "matched_tile_ids": list(prefilter_tiles),
            },
            "gate_crossings": {
                "start_time_s_raw": attempt.start.time_s,
                "finish_time_s_raw": attempt.finish.time_s,
                "start": attempt.start.to_trace(),
                "finish": attempt.finish.to_trace(),
            },
            "gate_start_crossing_at": attempt.start.time_s,
            "gate_end_crossing_at": attempt.finish.time_s,
            "duration_s_raw": raw_duration,
            "duration_s_whole": time_s,
            "whole_second_rounding": "python_round_ties_to_even",
            "corridor_coverage": {
                "inside_count": attempt.inside_count,
                "intermediate_count": attempt.intermediate_count,
                "ratio": attempt.coverage_ratio,
                "threshold": CORRIDOR_COVERAGE_THRESHOLD,
                "malformed_coordinate_count": malformed_in_window,
            },
            "corridor_coverage_pct": attempt.coverage_ratio * 100.0,
            "monotonic_progress": {
                "accepted": True,
                "max_backtrack_m": max_backtrack,
                "backtrack_tolerance_m": BACKTRACK_JITTER_TOLERANCE_M,
                "centerline_ambiguity_distance_m": CENTERLINE_AMBIGUITY_DISTANCE_M,
            },
            "canonical_profile_hash": {
                "algorithm": candidate.profile_hash_algorithm,
                "value": candidate.profile_hash,
            },
            "profile_hash": candidate.profile_hash,
            "canonical_metrics": {
                "distance_m": candidate.length_m,
                "vert_m": candidate.vert_m,
                "avg_gradient_pct": candidate.avg_gradient_pct,
            },
            "odbl_source": candidate.odbl_source,
            "pass_index": 0,
            "pass_count": 0,
            "best_for_canon": False,
            "best_tie_count": 0,
            "best_representative": False,
        }
        pattern = ClimbPattern(
            id=deterministic_id,
            activity_id=activity_id,
            wallet=wallet,
            arena_id=None,
            vert_m=candidate.vert_m,
            time_s=time_s,
            avg_power_w=avg_power_w,
            w_per_kg=w_per_kg,
            avg_hr=avg_hr,
            start_offset_s=start_offset_s,
            end_offset_s=end_offset_s,
            road_name=candidate.route_name or candidate.display_name,
            road_grade=candidate.avg_gradient_pct,
            road_coverage_pct=attempt.coverage_ratio * 100.0,
            attribution_summary=(
                f"{candidate.display_name} · {candidate.odbl_source}"
            ),
            tile_ids=crossed_tiles,
            distance_m=candidate.length_m,
            avg_gradient_pct=candidate.avg_gradient_pct,
            start_lat=attempt.start.lat,
            start_lon=attempt.start.lon,
            end_lat=attempt.finish.lat,
            end_lon=attempt.finish.lon,
            economic_eligible=False,
            abstention_reasons=[_PENDING_ACTIVATION_REASON],
            match_trace=trace,
            detector_version=_DETECTOR_VERSION,
        )
        attempt.accepted = True
        attempt.rejection_code = None
        attempt.pattern = pattern

    @staticmethod
    def _merge_intervals(intervals: Sequence[Tuple[float, float]]) -> List[Tuple[float, float]]:
        if not intervals:
            return []
        ordered = sorted((min(start, end), max(start, end)) for start, end in intervals)
        merged: List[Tuple[float, float]] = [ordered[0]]
        for start, end in ordered[1:]:
            previous_start, previous_end = merged[-1]
            if start <= previous_end:
                merged[-1] = (previous_start, max(previous_end, end))
            else:
                merged.append((start, end))
        return merged


class CanonTraversalService:
    """Upload-path adapter: private registry lookup followed by pure D11 math."""

    def __init__(
        self,
        repository: CanonRepository,
        engine: Optional[CanonTraversalEngine] = None,
    ) -> None:
        self.repository = repository
        self.engine = engine or CanonTraversalEngine()

    async def evaluate_ride(
        self,
        *,
        activity_id: UUID,
        wallet: str,
        tile_samples: Sequence[Mapping[str, Any]],
        raw_samples: Sequence[Mapping[str, Any]],
        user_weight_kg: Optional[float] = None,
    ) -> CanonTraversalEvaluation:
        if not raw_samples:
            return CanonTraversalEvaluation()
        tile_ids = {
            str(sample.get("tile_id"))
            for sample in tile_samples
            if sample.get("tile_id")
        }
        if not tile_ids:
            tile_ids = {
                str(sample.get("tile_id"))
                for sample in raw_samples
                if sample.get("tile_id")
            }
        candidates = await self.repository.load_ratified_for_tiles(sorted(tile_ids))
        if not candidates:
            return CanonTraversalEvaluation()
        # Seconds of geometry per ride: keep the loop free for the API and for
        # the JetStream ack heartbeat that stops a 30 s redelivery.
        return await asyncio.to_thread(
            self.engine.evaluate,
            activity_id=activity_id,
            wallet=wallet,
            candidates=candidates,
            raw_samples=raw_samples,
            user_weight_kg=user_weight_kg,
        )
