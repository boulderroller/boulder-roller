"""
GPS Template Matching for Climb Detection (Path H).

Matches a ride's GPS track against known climbing segment GPS corridors.
If a ride passes through a known segment's geographic corridor with sufficient
coverage, we detect a climb at that location using the segment's known boundaries
and the rider's actual time/power data.

This is analogous to Strava's segment matching (US9208175B2) — it bypasses
elevation detection entirely for known segments.

Usage (corpus evaluation):
    templates = load_templates_from_db(conn)
    matches = match_ride_against_templates(ride_latlng, ride_times, templates)

Usage (production — future):
    templates = load_templates_from_vaults(indexed_vaults)
    matches = match_ride_against_templates(ride_latlng, ride_times, templates)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SegmentTemplate:
    """A known climbing segment's GPS corridor used as a matching template."""

    template_id: int  # segment_id or vault_id
    name: str
    polyline: List[Tuple[float, float]]  # [(lat, lon), ...]
    expected_vert_m: float
    expected_grade_pct: float
    expected_distance_m: float = 0.0

    # Precomputed bounding box (populated by _prepare_template)
    bbox_min_lat: float = 0.0
    bbox_max_lat: float = 0.0
    bbox_min_lon: float = 0.0
    bbox_max_lon: float = 0.0

    # Precomputed cumulative distances along the template polyline
    _cumulative_distances: List[float] = field(default_factory=list, repr=False)
    _total_length_m: float = 0.0


@dataclass
class TemplateMatch:
    """Result of matching a ride against a segment template."""

    template_id: int
    template_name: str
    start_idx: int  # index into ride GPS track where match starts
    end_idx: int  # index into ride GPS track where match ends
    start_time_s: int  # timestamp when rider entered corridor
    end_time_s: int  # timestamp when rider exited corridor
    coverage: float  # fraction of template length covered (0.0-1.0)
    direction: str  # "forward" or "reverse"
    actual_vert_m: float  # rider's actual elevation gain in the matched section
    expected_vert_m: float  # template's expected elevation gain
    expected_grade_pct: float  # template's expected gradient
    in_corridor_count: int  # number of ride points inside corridor
    total_template_points: int  # number of points in the template


# ---------------------------------------------------------------------------
# Haversine
# ---------------------------------------------------------------------------

_EARTH_RADIUS_M = 6_371_000.0


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in meters between two (lat, lon) points."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return _EARTH_RADIUS_M * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


# ---------------------------------------------------------------------------
# Template preparation
# ---------------------------------------------------------------------------

# Bounding box expansion in degrees (~50 m at mid-latitudes)
_BBOX_PAD_DEG = 0.0006


def prepare_template(tmpl: SegmentTemplate) -> SegmentTemplate:
    """
    Precompute bounding box and cumulative distances for a template.

    Mutates the template in place and returns it for convenience.
    """
    if not tmpl.polyline:
        return tmpl

    lats = [p[0] for p in tmpl.polyline]
    lons = [p[1] for p in tmpl.polyline]
    tmpl.bbox_min_lat = min(lats) - _BBOX_PAD_DEG
    tmpl.bbox_max_lat = max(lats) + _BBOX_PAD_DEG
    tmpl.bbox_min_lon = min(lons) - _BBOX_PAD_DEG
    tmpl.bbox_max_lon = max(lons) + _BBOX_PAD_DEG

    cumul = [0.0]
    for i in range(1, len(tmpl.polyline)):
        d = _haversine_m(
            tmpl.polyline[i - 1][0],
            tmpl.polyline[i - 1][1],
            tmpl.polyline[i][0],
            tmpl.polyline[i][1],
        )
        cumul.append(cumul[-1] + d)
    tmpl._cumulative_distances = cumul
    tmpl._total_length_m = cumul[-1] if cumul else 0.0
    return tmpl


# ---------------------------------------------------------------------------
# Nearest-point projection onto template
# ---------------------------------------------------------------------------


def _nearest_template_index(
    lat: float,
    lon: float,
    template_pts: List[Tuple[float, float]],
    search_start: int = 0,
    search_window: int = 0,
) -> Tuple[int, float]:
    """
    Find the index of the nearest point on the template polyline.

    Returns (index, distance_m).

    When *search_window* > 0 the search is restricted to
    [search_start, search_start + search_window] to exploit temporal locality
    (consecutive ride points tend to match nearby template points).
    """
    best_idx = search_start
    best_dist = float("inf")

    if search_window > 0:
        lo = max(0, search_start - 5)  # small look-back for jitter
        hi = min(len(template_pts), search_start + search_window)
    else:
        lo = 0
        hi = len(template_pts)

    for i in range(lo, hi):
        d = _haversine_m(lat, lon, template_pts[i][0], template_pts[i][1])
        if d < best_dist:
            best_dist = d
            best_idx = i
    return best_idx, best_dist


# ---------------------------------------------------------------------------
# Core matching
# ---------------------------------------------------------------------------

# How many template points ahead to search from the last matched position.
# Keeps the search O(n * W) instead of O(n * m).
_SEARCH_WINDOW = 40


def _ride_bbox(latlng: List[Tuple[float, float]]) -> Tuple[float, float, float, float]:
    """Return (min_lat, max_lat, min_lon, max_lon) for a ride GPS track."""
    lats = [p[0] for p in latlng]
    lons = [p[1] for p in latlng]
    return min(lats), max(lats), min(lons), max(lons)


def _bboxes_overlap(
    a_min_lat: float, a_max_lat: float, a_min_lon: float, a_max_lon: float,
    b_min_lat: float, b_max_lat: float, b_min_lon: float, b_max_lon: float,
) -> bool:
    if a_max_lat < b_min_lat or a_min_lat > b_max_lat:
        return False
    if a_max_lon < b_min_lon or a_min_lon > b_max_lon:
        return False
    return True


def match_ride_against_templates(
    ride_latlng: List[Tuple[float, float]],
    ride_times: List[int],
    templates: List[SegmentTemplate],
    corridor_width_m: float = 50.0,
    min_coverage: float = 0.60,
    ride_elevations: Optional[List[Optional[float]]] = None,
) -> List[TemplateMatch]:
    """
    Match a ride's GPS track against known segment GPS templates.

    Args:
        ride_latlng: Full ride GPS track as [(lat, lon), ...]
        ride_times: Corresponding timestamps (seconds from ride start)
        templates: Known segment GPS corridors (must be prepared with prepare_template)
        corridor_width_m: Max distance from template to count as "in corridor"
        min_coverage: Minimum fraction of template length that must be covered
        ride_elevations: Optional elevation array for uphill filtering

    Returns:
        List of TemplateMatch for each template that matched.
    """
    if not ride_latlng or not templates:
        return []

    n_ride = len(ride_latlng)
    if len(ride_times) != n_ride:
        raise ValueError(
            f"ride_latlng ({n_ride}) and ride_times ({len(ride_times)}) length mismatch"
        )

    # Precompute ride bounding box once
    r_min_lat, r_max_lat, r_min_lon, r_max_lon = _ride_bbox(ride_latlng)

    matches: List[TemplateMatch] = []

    for tmpl in templates:
        # --- Bounding box pre-filter ---
        if not _bboxes_overlap(
            r_min_lat, r_max_lat, r_min_lon, r_max_lon,
            tmpl.bbox_min_lat, tmpl.bbox_max_lat, tmpl.bbox_min_lon, tmpl.bbox_max_lon,
        ):
            continue

        if not tmpl.polyline or tmpl._total_length_m < 10.0:
            continue

        n_tmpl = len(tmpl.polyline)
        cumul = tmpl._cumulative_distances
        total_len = tmpl._total_length_m

        # --- Project each ride point onto the template ---
        # For each ride point, record (template_index, distance_to_template)
        in_corridor_mask = [False] * n_ride
        tmpl_indices = [0] * n_ride
        last_search = 0

        for i in range(n_ride):
            lat, lon = ride_latlng[i]
            # Quick lat/lon range check before expensive haversine
            if (
                lat < tmpl.bbox_min_lat
                or lat > tmpl.bbox_max_lat
                or lon < tmpl.bbox_min_lon
                or lon > tmpl.bbox_max_lon
            ):
                continue

            tidx, dist = _nearest_template_index(
                lat, lon, tmpl.polyline,
                search_start=last_search,
                search_window=_SEARCH_WINDOW,
            )
            # If the windowed search didn't find a close point, try a full search.
            # This handles cases where the ride GPS has large gaps (flat sections
            # between climbs) that cause last_search to fall behind.
            if dist > corridor_width_m:
                tidx, dist = _nearest_template_index(
                    lat, lon, tmpl.polyline,
                    search_start=0,
                    search_window=0,  # full search
                )
            tmpl_indices[i] = tidx
            if dist <= corridor_width_m:
                in_corridor_mask[i] = True
                last_search = tidx

        # --- Find contiguous in-corridor runs ---
        runs = _find_corridor_runs(in_corridor_mask, tmpl_indices, n_tmpl)
        if not runs:
            continue

        # --- Evaluate each run ---
        for run_start, run_end in runs:
            # Coverage: which template segments were covered?
            covered_template_indices = set()
            for i in range(run_start, run_end + 1):
                if in_corridor_mask[i]:
                    covered_template_indices.add(tmpl_indices[i])

            # Compute coverage as fraction of template length covered
            coverage = _compute_coverage(covered_template_indices, cumul, total_len)

            if coverage < min_coverage:
                continue

            # Direction check: are template indices generally increasing or decreasing?
            corridor_tidx = [
                tmpl_indices[i]
                for i in range(run_start, run_end + 1)
                if in_corridor_mask[i]
            ]
            direction = _determine_direction(corridor_tidx)

            # For "reverse" direction, the rider is going downhill on the climb
            # We only want uphill matches
            if direction == "reverse":
                continue

            # Temporal ordering: check that the matched points are in roughly
            # monotonic order on the template (not jumping around)
            if not _is_temporally_ordered(corridor_tidx, tolerance=0.25):
                continue

            # Elevation sanity check: rider's actual elevation gain should be
            # >= 50% of expected vert
            actual_vert = 0.0
            if ride_elevations is not None:
                actual_vert = _compute_actual_vert(
                    ride_elevations, run_start, run_end
                )
                if (
                    tmpl.expected_vert_m > 0
                    and actual_vert < 0.5 * tmpl.expected_vert_m
                ):
                    continue

            matches.append(
                TemplateMatch(
                    template_id=tmpl.template_id,
                    template_name=tmpl.name,
                    start_idx=run_start,
                    end_idx=run_end,
                    start_time_s=ride_times[run_start],
                    end_time_s=ride_times[run_end],
                    coverage=round(coverage, 3),
                    direction=direction,
                    actual_vert_m=round(actual_vert, 1),
                    expected_vert_m=tmpl.expected_vert_m,
                    expected_grade_pct=tmpl.expected_grade_pct,
                    in_corridor_count=sum(
                        1 for i in range(run_start, run_end + 1) if in_corridor_mask[i]
                    ),
                    total_template_points=n_tmpl,
                )
            )

    # Deduplicate: if multiple templates match the same time window, keep
    # the one with higher coverage
    matches = _dedup_overlapping_matches(matches)
    return matches


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_corridor_runs(
    in_corridor: List[bool],
    tmpl_indices: List[int],
    n_tmpl: int,
    max_gap: int = 15,
) -> List[Tuple[int, int]]:
    """
    Find contiguous (or nearly contiguous) runs of in-corridor ride points.

    Allows gaps of up to *max_gap* ride samples between corridor hits
    (GPS dropouts, brief detours).

    Returns list of (start_ride_idx, end_ride_idx).
    """
    runs: List[Tuple[int, int]] = []
    run_start: Optional[int] = None
    last_in: Optional[int] = None

    for i, is_in in enumerate(in_corridor):
        if is_in:
            if run_start is None:
                run_start = i
                last_in = i
            elif last_in is not None and i - last_in > max_gap:
                # Gap too large — end previous run, start new one
                runs.append((run_start, last_in))
                run_start = i
            last_in = i

    if run_start is not None and last_in is not None:
        runs.append((run_start, last_in))

    # Filter out very short runs (< 5 in-corridor points)
    return [
        (s, e)
        for s, e in runs
        if sum(1 for i in range(s, e + 1) if in_corridor[i]) >= 5
    ]


def _compute_coverage(
    covered_indices: set,
    cumulative_distances: List[float],
    total_length: float,
) -> float:
    """
    Compute what fraction of the template's length is covered.

    For each consecutive pair of template points where at least one is in
    the covered set, add that segment's length to the covered distance.
    """
    if total_length <= 0 or not covered_indices:
        return 0.0

    covered_dist = 0.0
    for i in range(len(cumulative_distances) - 1):
        if i in covered_indices or (i + 1) in covered_indices:
            seg_len = cumulative_distances[i + 1] - cumulative_distances[i]
            covered_dist += seg_len

    return covered_dist / total_length


def _determine_direction(corridor_tidx: List[int]) -> str:
    """
    Determine if the rider traversed the template forwards or in reverse.

    Compares indices at the start vs end of the matched run.
    """
    if len(corridor_tidx) < 3:
        return "forward"

    # Use first and last quartile medians for robustness
    q = max(1, len(corridor_tidx) // 4)
    first_q = sorted(corridor_tidx[:q])
    last_q = sorted(corridor_tidx[-q:])
    median_first = first_q[len(first_q) // 2]
    median_last = last_q[len(last_q) // 2]

    if median_last < median_first:
        return "reverse"
    return "forward"


def _is_temporally_ordered(corridor_tidx: List[int], tolerance: float = 0.25) -> bool:
    """
    Check that the sequence of template indices is roughly monotonic.

    Allows up to *tolerance* fraction of pairs to be out of order
    (GPS jitter, brief backtracking).
    """
    if len(corridor_tidx) < 3:
        return True

    pairs = len(corridor_tidx) - 1
    forward_count = sum(
        1 for i in range(pairs) if corridor_tidx[i + 1] >= corridor_tidx[i]
    )
    return forward_count / pairs >= (1.0 - tolerance)


def _compute_actual_vert(
    elevations: List[Optional[float]],
    start_idx: int,
    end_idx: int,
) -> float:
    """
    Compute net elevation gain over a ride section.

    Uses boundary-to-boundary (smoothed start to smoothed end) rather than
    cumulative ascent, since we want to compare with template's expected_vert_m
    which is also boundary-based.
    """
    # Find first and last valid elevations
    start_elev = None
    for i in range(start_idx, min(end_idx + 1, len(elevations))):
        if elevations[i] is not None:
            start_elev = elevations[i]
            break

    end_elev = None
    for i in range(min(end_idx, len(elevations) - 1), start_idx - 1, -1):
        if elevations[i] is not None:
            end_elev = elevations[i]
            break

    if start_elev is None or end_elev is None:
        return 0.0

    return max(0.0, end_elev - start_elev)


def _dedup_overlapping_matches(matches: List[TemplateMatch]) -> List[TemplateMatch]:
    """
    Remove overlapping template matches, keeping the one with higher coverage.

    Two matches overlap if their time ranges overlap by >= 50% of the shorter.
    """
    if len(matches) <= 1:
        return matches

    # Sort by coverage descending so we greedily keep the best
    matches.sort(key=lambda m: m.coverage, reverse=True)

    kept: List[TemplateMatch] = []
    for candidate in matches:
        overlaps = False
        for existing in kept:
            ovl = max(
                0,
                min(candidate.end_time_s, existing.end_time_s)
                - max(candidate.start_time_s, existing.start_time_s),
            )
            shorter = min(
                max(1, candidate.end_time_s - candidate.start_time_s),
                max(1, existing.end_time_s - existing.start_time_s),
            )
            if ovl / shorter >= 0.50:
                overlaps = True
                break
        if not overlaps:
            kept.append(candidate)

    # Re-sort by start time for consistent output
    kept.sort(key=lambda m: m.start_time_s)
    return kept
