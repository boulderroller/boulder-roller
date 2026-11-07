"""Road enrichment service for climb detection v3.

Queries road_features table (OSM data indexed by H3 tile) and enriches
persistence-detected climbs with road context for boundary placement,
bridge suppression, intersection splitting, and road name attribution.

Architecture: See docs/rfcs/CLIMB_DETECTION_V3_ARCHITECTURE.md Section 2.3

Key principle (user directive):
  "Road features are tiebreakers, not magnets."
  Don't drag a boundary to a road feature if the climb naturally
  flattens before it. Prefer tight boundaries over extended ones.
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

from ..repositories.base import get_supabase_client

logger = logging.getLogger(__name__)

# H3 resolution for tile indexing (matches project standard: resolution 10)
H3_RESOLUTION = 10

# Keep road-feature fetches below PostgREST's default row cap and make batch
# composition reproducible for offline detector comparisons.
ROAD_FEATURE_FETCH_BATCH_SIZE = 50

# Search window for intersection/road features near boundaries
# As fraction of the climb span from the canonical end
BOUNDARY_SEARCH_FRACTION = 0.25

# Absolute max search window in samples (~150m at cycling speed)
# Prevents snapping to distant intersections on long climbs
BOUNDARY_SEARCH_MAX_SAMPLES = 30

# Max distance in samples to snap boundary to a road feature without
# additional justification (gradient ambiguity, etc.)
SNAP_CLOSE_SAMPLES = 5

# Gradient thresholds for boundary decisions
GRADIENT_AMBIGUOUS_LO = 0.5   # Below this = definitely flat
GRADIENT_AMBIGUOUS_HI = 2.0   # Above this = definitely climbing
GRADIENT_FLAT_THRESHOLD = 1.5  # For intersection splitting

# Bridge suppression thresholds (OSM-based)
BRIDGE_PCT_THRESHOLD = 0.6
BRIDGE_MAX_VERT_M = 50.0
BRIDGE_MAX_TIME_S = 180
BRIDGE_PREPROCESS_ENDPOINT_MATCH_THRESHOLD_M = 50.0
BRIDGE_PREPROCESS_MAX_TIME_S = 180
BRIDGE_PREPROCESS_TRACK_DISTANCE_SLACK_M = 100.0
BRIDGE_PREPROCESS_TRACK_DISTANCE_RATIO = 3.0

# Post-detection FP suppression thresholds
NOISE_MIN_VERT_M = 10.0          # Sub-10m "climbs" are barometric noise
BRIDGE_HEURISTIC_RETURN_M = 5.0  # If elevation returns within this of start → bridge artifact
BRIDGE_HEURISTIC_MAX_TIME_S = 300  # Only check short climbs for bridge pattern

# Minimum vert for each half of a split climb
SPLIT_MIN_VERT_M = 15.0

# Samples past a road feature for "tight trim" (Step 3/4 last branch)
TRIM_PAST_FEATURE_SAMPLES = 3

# Gradient averaging window for split detection
SPLIT_GRADIENT_WINDOW = 30

# Haversine for proximity calculations
_R_EARTH_M = 6_371_000.0


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return _R_EARTH_M * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@dataclass
class RoadFeature:
    """A road feature from the road_features table."""
    tile_id: str
    feature_type: str  # intersection, bridge, tunnel, road_segment
    osm_id: int
    name: Optional[str]
    highway_class: Optional[str]
    lat: float
    lon: float
    road_names: List[str]
    degree: Optional[int]
    tags: Optional[dict]


@dataclass
class SplitCandidate:
    """A potential split point within a climb."""
    sample_idx: int
    intersection: RoadFeature
    gradient_at_split: float
    road_name_before: Optional[str]
    road_name_after: Optional[str]


@dataclass
class EnrichedClimb:
    """Enrichment metadata attached to a ClimbPattern after road analysis."""
    road_name: Optional[str] = None
    road_names_sequence: List[str] = field(default_factory=list)
    bridge_pct: float = 0.0
    is_bridge_artifact: bool = False
    suppressed: bool = False
    suppression_reason: Optional[str] = None
    split_candidates: List[SplitCandidate] = field(default_factory=list)
    refined_start: Optional[int] = None  # adjusted effort start index
    refined_end: Optional[int] = None    # adjusted effort end index
    start_boundary_source: str = "gradient"
    end_boundary_source: str = "gradient"
    start_intersection: Optional[dict] = None
    end_intersection: Optional[dict] = None
    nearby_features_start: List[dict] = field(default_factory=list)
    nearby_features_end: List[dict] = field(default_factory=list)


def fetch_road_features_for_tiles(tile_ids: Set[str]) -> List[RoadFeature]:
    """Batch-fetch road features for a set of H3 tiles from Supabase.

    Fetches all feature types (intersections, bridges, tunnels, road_segments)
    for the given tiles in a single query.
    """
    if not tile_ids:
        return []

    client = get_supabase_client()
    tile_list = sorted(tile_ids)

    # Supabase PostgREST has URL and row-count limits; batch conservatively.
    all_features = []

    for i in range(0, len(tile_list), ROAD_FEATURE_FETCH_BATCH_SIZE):
        batch = tile_list[i:i + ROAD_FEATURE_FETCH_BATCH_SIZE]
        response = (
            client.table("road_features")
            .select("tile_id, feature_type, osm_id, name, highway_class, lat, lon, road_names, degree, tags")
            .in_("tile_id", batch)
            .execute()
        )

        for row in response.data:
            all_features.append(RoadFeature(
                tile_id=row["tile_id"],
                feature_type=row["feature_type"],
                osm_id=row["osm_id"],
                name=row.get("name"),
                highway_class=row.get("highway_class"),
                lat=row["lat"],
                lon=row["lon"],
                road_names=row.get("road_names") or [],
                degree=row.get("degree"),
                tags=row.get("tags"),
            ))

    all_features.sort(
        key=lambda feature: (
            feature.tile_id,
            feature.feature_type,
            feature.osm_id,
            feature.name or "",
            feature.lat,
            feature.lon,
        )
    )
    logger.debug(f"Fetched {len(all_features)} road features for {len(tile_ids)} tiles")
    return all_features


def _features_by_type(features: List[RoadFeature]) -> Dict[str, List[RoadFeature]]:
    """Group features by type."""
    by_type: Dict[str, List[RoadFeature]] = {}
    for f in features:
        by_type.setdefault(f.feature_type, []).append(f)
    return by_type


def _features_by_tile(features: List[RoadFeature]) -> Dict[str, List[RoadFeature]]:
    """Group features by tile_id."""
    by_tile: Dict[str, List[RoadFeature]] = {}
    for f in features:
        by_tile.setdefault(f.tile_id, []).append(f)
    return by_tile


def _compute_gradient_at(smoothed: List[float], idx: int, window: int = 5) -> float:
    """Compute gradient percentage at a sample index over a window."""
    if idx < window or idx >= len(smoothed) - window:
        return 0.0
    elev_diff = smoothed[idx + window] - smoothed[idx - window]
    # Approximate distance: assume ~5m per sample at cycling speed
    dist_m = window * 2 * 5.0
    if dist_m == 0:
        return 0.0
    return (elev_diff / dist_m) * 100.0


def _find_sample_for_feature(
    feature: RoadFeature,
    tile_samples: List[Dict],
    start_idx: int,
    end_idx: int,
) -> Optional[int]:
    """Find the tile_sample index closest to a road feature's lat/lon.

    Searches within [start_idx, end_idx] range.
    """
    best_idx = None
    best_dist = float("inf")

    for i in range(start_idx, min(end_idx + 1, len(tile_samples))):
        s = tile_samples[i]
        lat = s.get("lat")
        lon = s.get("lon")
        if lat is None or lon is None:
            continue
        d = _haversine_m(feature.lat, feature.lon, lat, lon)
        if d < best_dist:
            best_dist = d
            best_idx = i

    # Only return if within 150m (H3 res-10 cell is ~66m edge, so feature
    # could be up to ~100m from the ride track)
    if best_dist < 150.0:
        return best_idx
    return None


def check_bridge_overlap(
    climb_tile_ids: List[str],
    features_by_type: Dict[str, List[RoadFeature]],
) -> float:
    """Compute fraction of climb tiles that overlap bridge features."""
    bridges = features_by_type.get("bridge", [])
    if not bridges:
        return 0.0

    bridge_tiles = {b.tile_id for b in bridges}
    climb_tiles = set(climb_tile_ids)
    overlap = climb_tiles & bridge_tiles

    if not climb_tiles:
        return 0.0
    return len(overlap) / len(climb_tiles)


def attribute_road_name(
    climb_tile_ids: List[str],
    features_by_tile: Dict[str, List[RoadFeature]],
) -> Tuple[Optional[str], List[str]]:
    """Attribute a road name to a climb based on road_segment features.

    Returns (primary_name, ordered_names_sequence).
    """
    name_counts: Dict[str, int] = {}
    name_sequence: List[str] = []
    last_name = None

    for tile_id in climb_tile_ids:
        tile_features = features_by_tile.get(tile_id, [])
        segments = [f for f in tile_features if f.feature_type == "road_segment" and f.name]

        if segments:
            # Pick highest highway class segment in this tile
            best = max(segments, key=lambda s: _highway_rank(s.highway_class))
            name_counts[best.name] = name_counts.get(best.name, 0) + 1
            if best.name != last_name:
                name_sequence.append(best.name)
                last_name = best.name

    if not name_counts:
        return None, []

    primary = max(name_counts, key=name_counts.get)
    return primary, name_sequence


def _highway_rank(highway_class: Optional[str]) -> int:
    """Rank highway classes by importance (higher = more important road)."""
    ranks = {
        "motorway": 10, "motorway_link": 9,
        "trunk": 8, "trunk_link": 7,
        "primary": 6, "primary_link": 5,
        "secondary": 4, "secondary_link": 3,
        "tertiary": 2, "tertiary_link": 1,
        "residential": 0, "unclassified": 0,
        "living_street": 0, "road": 0,
    }
    return ranks.get(highway_class or "", 0)


def find_nearby_intersections(
    tile_samples: List[Dict],
    start_idx: int,
    end_idx: int,
    features_by_type: Dict[str, List[RoadFeature]],
    min_degree: int = 2,
) -> List[Tuple[int, RoadFeature]]:
    """Find intersections near the ride track within a sample range.

    Returns list of (sample_idx, feature) sorted by sample_idx.
    Only includes intersections with degree >= min_degree.
    """
    intersections = features_by_type.get("intersection", [])
    if not intersections:
        return []

    results = []
    seen_osm_ids = set()

    for ix in intersections:
        if ix.degree is not None and ix.degree < min_degree:
            continue
        if ix.osm_id in seen_osm_ids:
            continue

        sample_idx = _find_sample_for_feature(ix, tile_samples, start_idx, end_idx)
        if sample_idx is not None:
            results.append((sample_idx, ix))
            seen_osm_ids.add(ix.osm_id)

    results.sort(key=lambda x: x[0])
    return results


def find_split_candidates(
    tile_samples: List[Dict],
    smoothed: List[float],
    climb_start: int,
    climb_end: int,
    features_by_type: Dict[str, List[RoadFeature]],
    features_by_tile: Dict[str, List[RoadFeature]],
) -> List[SplitCandidate]:
    """Find intersections in flat sections with road name changes — split candidates.

    RFC Section 2.3 Step 2:
    - Intersection in climb interior (middle 80%)
    - Gradient < 1.5% over ±30 samples
    - Different road name before and after
    - Each sub-climb has vert >= 15m
    - Intersection degree >= 3 (real junction, not a driveway)
    - Deduplicated: one candidate per road-name transition
    """
    span = climb_end - climb_start
    if span < 60:  # Too short to meaningfully split
        return []

    # Search interior (exclude first/last 10% of climb)
    interior_start = climb_start + max(10, span // 10)
    interior_end = climb_end - max(10, span // 10)

    # Require degree >= 3 to filter driveways and minor connections
    nearby = find_nearby_intersections(
        tile_samples, interior_start, interior_end,
        features_by_type, min_degree=3,
    )

    raw_candidates = []
    for sample_idx, intersection in nearby:
        # Check gradient is flat at intersection
        gradient = _compute_gradient_at(smoothed, sample_idx, window=min(SPLIT_GRADIENT_WINDOW, span // 4))
        if abs(gradient) > GRADIENT_FLAT_THRESHOLD:
            continue

        # Check road name change
        tiles_before = _get_tile_ids(tile_samples, climb_start, sample_idx)
        tiles_after = _get_tile_ids(tile_samples, sample_idx, climb_end)

        name_before = _dominant_road_name(tiles_before, features_by_tile)
        name_after = _dominant_road_name(tiles_after, features_by_tile)

        if name_before and name_after and name_before != name_after:
            # Check each half has enough vert
            vert_before = _compute_vert(smoothed, climb_start, sample_idx)
            vert_after = _compute_vert(smoothed, sample_idx, climb_end)

            if vert_before >= SPLIT_MIN_VERT_M and vert_after >= SPLIT_MIN_VERT_M:
                raw_candidates.append(SplitCandidate(
                    sample_idx=sample_idx,
                    intersection=intersection,
                    gradient_at_split=gradient,
                    road_name_before=name_before,
                    road_name_after=name_after,
                ))

    # Deduplicate: group candidates within 50 samples, keep the one with
    # the flattest gradient (closest to 0) per road-name transition
    if not raw_candidates:
        return []

    DEDUP_WINDOW = 50
    groups: List[List[SplitCandidate]] = []
    for sc in sorted(raw_candidates, key=lambda x: x.sample_idx):
        placed = False
        for group in groups:
            if (abs(sc.sample_idx - group[0].sample_idx) < DEDUP_WINDOW
                    and sc.road_name_before == group[0].road_name_before
                    and sc.road_name_after == group[0].road_name_after):
                group.append(sc)
                placed = True
                break
        if not placed:
            groups.append([sc])

    # Pick the best from each group (flattest gradient, highest degree)
    return [min(g, key=lambda x: abs(x.gradient_at_split)) for g in groups]


def _find_gradient_transition(
    smoothed: List[float],
    start_idx: int,
    end_idx: int,
    is_start: bool,
    threshold_pct: float = 2.0,
    sustain_samples: int = 8,
) -> Optional[int]:
    """Find where gradient transitions from flat to climbing (or vice versa).

    For start boundaries: walk forward from start_idx, find the first point
    where gradient exceeds threshold for `sustain_samples` consecutive samples.

    For end boundaries: walk backward from end_idx, find where gradient drops
    below threshold for `sustain_samples` consecutive samples.

    Returns the transition sample index, or None if not found.
    """
    if is_start:
        streak = 0
        for i in range(start_idx, end_idx):
            g = _compute_gradient_at(smoothed, i, window=3)
            if g > threshold_pct:
                streak += 1
                if streak >= sustain_samples:
                    return i - sustain_samples + 1  # start of the sustained gradient
            else:
                streak = 0
    else:
        streak = 0
        for i in range(end_idx, start_idx, -1):
            g = _compute_gradient_at(smoothed, i, window=3)
            if g > threshold_pct:
                streak += 1
                if streak >= sustain_samples:
                    return i + sustain_samples - 1  # end of sustained gradient
            else:
                streak = 0

    return None


def _aic_pick(gradient: List[float], center: int, window: int = 30) -> Optional[int]:
    """AIC picker from seismology — find exact statistical transition in gradient.

    Models the gradient signal as two segments with different variance.
    The AIC minimum marks where the signal's statistical properties change
    (flat noise → climbing signal). Achieves sub-sample precision in seismology.

    Args:
        gradient: gradient values (% per sample)
        center: approximate transition point (from onset backtracking)
        window: search radius around center (±window samples)

    Returns:
        Index of the exact transition, or None if no clear transition.
    """
    lo = max(1, center - window)
    hi = min(len(gradient) - 1, center + window)
    n = hi - lo
    if n < 10:
        return None

    segment = gradient[lo:hi]
    best_aic = float("inf")
    best_k = None

    for k in range(3, n - 3):  # need at least 3 samples each side
        seg1 = segment[:k]
        seg2 = segment[k:]

        # Variance of each segment (avoid log(0))
        var1 = sum((x - sum(seg1) / len(seg1)) ** 2 for x in seg1) / len(seg1)
        var2 = sum((x - sum(seg2) / len(seg2)) ** 2 for x in seg2) / len(seg2)

        if var1 <= 0 or var2 <= 0:
            continue

        aic = k * math.log(var1 + 1e-10) + (n - k) * math.log(var2 + 1e-10)
        if aic < best_aic:
            best_aic = aic
            best_k = k

    if best_k is None:
        return None

    return lo + best_k


def refine_boundary(
    tile_samples: List[Dict],
    smoothed: List[float],
    gradient_walk_idx: int,
    canonical_bound: int,
    search_end: int,
    features_by_type: Dict[str, List[RoadFeature]],
    is_start: bool,
) -> Tuple[int, str, Optional[dict]]:
    """Refine a boundary using onset backtracking + AIC + intersection snap.

    Three-step approach inspired by audio onset detection and seismology:
    1. Onset (from Rust): gradient energy minimum in approach zone
    2. AIC: exact statistical transition near onset point
    3. Intersection snap: if an intersection is within ±10 samples, use it

    "Road features are tiebreakers, not magnets."

    Returns (refined_idx, boundary_source, intersection_info).
    """
    # Step 1: The gradient_walk_idx is already the onset-anchored position
    # (caller passes onset_start_idx when available)
    anchor = gradient_walk_idx

    # NOTE: AIC refinement was tried (seismology technique) but cycling gradient
    # SNR is too low — AIC finds noise transitions instead of real climb onsets.
    # The onset backtracking from Rust is sufficient.
    source = "onset"

    # Step 3: Intersection snap — look for a road feature near the AIC point
    search_lo = max(anchor - SNAP_CLOSE_SAMPLES * 2, 0)
    search_hi = min(anchor + SNAP_CLOSE_SAMPLES * 2, len(tile_samples) - 1)

    nearby = find_nearby_intersections(
        tile_samples, search_lo, search_hi, features_by_type, min_degree=2,
    )

    if nearby:
        best_idx, best_feature = min(nearby, key=lambda x: abs(x[0] - anchor))
        dist = abs(best_idx - anchor)

        if dist <= SNAP_CLOSE_SAMPLES * 2:
            return best_idx, "intersection", {
                "osm_id": best_feature.osm_id,
                "name": best_feature.name,
                "degree": best_feature.degree,
                "lat": best_feature.lat,
                "lon": best_feature.lon,
            }

    # No nearby intersection — use AIC/onset point
    return anchor, source, None


def _compute_vert(smoothed: List[float], start: int, end: int) -> float:
    """Compute vertical gain in a range (sum of positive deltas)."""
    gain = 0.0
    for i in range(start + 1, min(end + 1, len(smoothed))):
        delta = smoothed[i] - smoothed[i - 1]
        if delta > 0:
            gain += delta
    return gain


def _get_tile_ids(tile_samples: List[Dict], start: int, end: int) -> List[str]:
    """Extract tile_ids from a sample range.

    Tries tile_id field first. If missing (common when samples were built
    with deduplicated H3 strings), computes from lat/lon using h3 library.
    """
    tiles = []
    for i in range(start, min(end + 1, len(tile_samples))):
        tid = tile_samples[i].get("tile_id")
        if tid:
            tiles.append(tid)
        else:
            # Fall back to computing from lat/lon
            lat = tile_samples[i].get("lat")
            lon = tile_samples[i].get("lon")
            if lat is not None and lon is not None:
                try:
                    import h3
                    tid = h3.latlng_to_cell(lat, lon, H3_RESOLUTION)
                    tiles.append(tid)
                except Exception:
                    pass
    return tiles


def _dominant_road_name(
    tile_ids: List[str],
    features_by_tile: Dict[str, List[RoadFeature]],
) -> Optional[str]:
    """Find the most common road name for a set of tiles."""
    counts: Dict[str, int] = {}
    for tid in tile_ids:
        for f in features_by_tile.get(tid, []):
            if f.feature_type == "road_segment" and f.name:
                counts[f.name] = counts.get(f.name, 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)


def enrich_climb(
    climb,
    tile_samples: List[Dict],
    smoothed: List[float],
    road_features: List[RoadFeature],
) -> EnrichedClimb:
    """Enrich a single climb with road context.

    Implements the full decision logic from RFC Section 2.3:
    1. Bridge suppression
    2. Intersection splitting candidates
    3. Start boundary refinement
    4. End boundary refinement + summit seeking
    5. Road name attribution
    6. Boundary source tracking

    Args:
        climb: ClimbPattern with tile_ids, start/end offsets, vert_m, time_s
        tile_samples: Full ride tile samples
        smoothed: Smoothed elevation profile (same indexing as tile_samples)
        road_features: Pre-fetched road features for this ride's tiles

    Returns:
        EnrichedClimb with all enrichment metadata
    """
    enriched = EnrichedClimb()

    # Resolve sample indices — ClimbV2 (Rust) has effort_start_idx/effort_end_idx,
    # ClimbPattern (Python) has start_time_offset_s/end_time_offset_s
    climb_start = getattr(climb, "effort_start_idx", None)
    climb_end = getattr(climb, "effort_end_idx", None)

    if climb_start is None or climb_end is None:
        start_offset = getattr(climb, "start_time_offset_s", 0) or 0
        end_offset = getattr(climb, "end_time_offset_s", 0) or 0
        climb_start = _time_to_sample_idx(tile_samples, start_offset)
        climb_end = _time_to_sample_idx(tile_samples, end_offset)

    # Get tile_ids — prefer climb's own list, fall back to building from indices
    climb_tile_ids = getattr(climb, "tile_ids", None) or []
    if not climb_tile_ids and climb_start is not None and climb_end is not None:
        climb_tile_ids = _get_tile_ids(tile_samples, climb_start, climb_end)

    climb_tiles_set = set(climb_tile_ids)

    # Filter features to those relevant to this climb
    climb_features = [f for f in road_features if f.tile_id in climb_tiles_set]
    by_type = _features_by_type(climb_features)
    by_tile = _features_by_tile(climb_features)

    if climb_start is None or climb_end is None:
        logger.warning("Could not map climb time offsets to sample indices")
        return enriched

    span = climb_end - climb_start
    if span <= 0:
        return enriched

    vert_m = getattr(climb, "vert_m", 0) or 0
    time_s = getattr(climb, "time_s", 0) or 0

    # STEP 0A: Noise suppression — sub-10m "climbs" are barometric noise
    if vert_m < NOISE_MIN_VERT_M:
        enriched.suppressed = True
        enriched.suppression_reason = f"NOISE:vert_{vert_m:.0f}m<{NOISE_MIN_VERT_M:.0f}m"
        return enriched

    # NOTE: Elevation-based bridge heuristic was tried and removed — it can't
    # distinguish real hills from bridges (both go up then down on loop rides).
    # West Walnut Lane Bridge is missing bridge=yes tag in OSM (data gap).
    # Bridge suppression relies solely on OSM bridge tags for now.

    # STEP 1: Bridge suppression (OSM-based)
    enriched.bridge_pct = check_bridge_overlap(climb_tile_ids, by_type)
    if (enriched.bridge_pct > BRIDGE_PCT_THRESHOLD
            and vert_m < BRIDGE_MAX_VERT_M
            and time_s < BRIDGE_MAX_TIME_S):
        enriched.is_bridge_artifact = True
        enriched.suppressed = True
        enriched.suppression_reason = "INFRA:bridge_overlap"
        logger.info(
            f"Bridge suppression: bridge_pct={enriched.bridge_pct:.2f}, "
            f"vert={vert_m:.0f}m, time={time_s}s"
        )
        return enriched

    # STEP 2: Intersection splitting candidates
    enriched.split_candidates = find_split_candidates(
        tile_samples, smoothed, climb_start, climb_end, by_type, by_tile,
    )
    if enriched.split_candidates:
        logger.info(
            f"Found {len(enriched.split_candidates)} split candidates: "
            + ", ".join(
                f"{sc.road_name_before}→{sc.road_name_after} at idx {sc.sample_idx}"
                for sc in enriched.split_candidates
            )
        )

    # STEP 3: Start boundary refinement
    # Use onset index (gradient energy minimum) as anchor if available
    onset_start = getattr(climb, "onset_start_idx", None)
    if onset_start is not None:
        # Onset provides the flattest point in the approach zone — search near it
        start_anchor = onset_start
    else:
        start_anchor = climb_start

    search_window = min(int(BOUNDARY_SEARCH_FRACTION * span), BOUNDARY_SEARCH_MAX_SAMPLES)
    search_hi_start = start_anchor + search_window
    enriched.refined_start, enriched.start_boundary_source, enriched.start_intersection = \
        refine_boundary(
            tile_samples, smoothed,
            gradient_walk_idx=start_anchor,
            canonical_bound=climb_start,
            search_end=search_hi_start,
            features_by_type=by_type,
            is_start=True,
        )

    # STEP 4: End boundary refinement
    onset_end = getattr(climb, "onset_end_idx", None)
    end_anchor = onset_end if onset_end is not None else climb_end

    search_lo_end = end_anchor - search_window
    enriched.refined_end, enriched.end_boundary_source, enriched.end_intersection = \
        refine_boundary(
            tile_samples, smoothed,
            gradient_walk_idx=end_anchor,
            canonical_bound=climb_end,
            search_end=search_lo_end,
            features_by_type=by_type,
            is_start=False,
        )

    # Summit seeking for end boundary
    if climb_end < len(smoothed):
        # Check if there's a higher point between current end and canonical end
        search_end = min(climb_end + int(0.1 * span), len(smoothed) - 1)
        if search_end > enriched.refined_end:
            summit_idx = enriched.refined_end
            summit_elev = smoothed[enriched.refined_end] if enriched.refined_end < len(smoothed) else 0
            for i in range(enriched.refined_end, search_end + 1):
                if i < len(smoothed) and smoothed[i] > summit_elev:
                    summit_elev = smoothed[i]
                    summit_idx = i
            if summit_idx > enriched.refined_end:
                enriched.refined_end = summit_idx
                enriched.end_boundary_source = "summit"

    # STEP 5: Road name attribution
    enriched.road_name, enriched.road_names_sequence = attribute_road_name(
        climb_tile_ids, by_tile,
    )

    return enriched


def enrich_climbs(
    climbs: list,
    tile_samples: List[Dict],
    smoothed: Optional[List[float]] = None,
) -> List[EnrichedClimb]:
    """Batch enrichment for all climbs in a ride.

    Fetches road features once for all tiles in the ride, then enriches
    each climb individually.

    Args:
        climbs: List of ClimbPattern objects from persistence detector
        tile_samples: Full ride tile samples
        smoothed: Optional pre-computed smoothed elevation. If None,
                  computes SMA(5) from tile_samples elevation_m.

    Returns:
        List of EnrichedClimb, one per input climb (same order).
    """
    if not climbs or not tile_samples:
        return [EnrichedClimb() for _ in climbs]

    # Compute smoothed elevation if not provided
    if smoothed is None:
        smoothed = _smooth_elevation(tile_samples)

    # Collect all tile_ids across all climbs
    # If climb has effort indices but no tile_ids, build from tile_samples
    all_tiles: Set[str] = set()
    for climb in climbs:
        tiles = getattr(climb, "tile_ids", None) or []
        if not tiles:
            start_idx = getattr(climb, "effort_start_idx", None)
            end_idx = getattr(climb, "effort_end_idx", None)
            if start_idx is not None and end_idx is not None:
                tiles = _get_tile_ids(tile_samples, start_idx, end_idx)
        all_tiles.update(tiles)

    # Single batch fetch
    road_features = fetch_road_features_for_tiles(all_tiles)
    logger.info(f"Fetched {len(road_features)} road features for {len(all_tiles)} tiles across {len(climbs)} climbs")

    # Enrich each climb
    results = []
    for climb in climbs:
        enriched = enrich_climb(climb, tile_samples, smoothed, road_features)
        results.append(enriched)

    # Log summary
    suppressed = sum(1 for e in results if e.suppressed)
    with_splits = sum(1 for e in results if e.split_candidates)
    with_names = sum(1 for e in results if e.road_name)
    refined_starts = sum(1 for e in results if e.start_boundary_source != "gradient")
    refined_ends = sum(1 for e in results if e.end_boundary_source != "gradient")

    logger.info(
        f"Road enrichment: {len(climbs)} climbs → "
        f"{suppressed} suppressed, {with_splits} with splits, "
        f"{with_names} named, {refined_starts} start refined, {refined_ends} end refined"
    )

    return results


def _smooth_elevation(tile_samples: List[Dict], window: int = 5) -> List[float]:
    """SMA smoothing of elevation profile."""
    elevs = [s.get("elevation_m", 0.0) or 0.0 for s in tile_samples]
    if len(elevs) < window:
        return elevs

    smoothed = []
    half = window // 2
    for i in range(len(elevs)):
        lo = max(0, i - half)
        hi = min(len(elevs), i + half + 1)
        smoothed.append(sum(elevs[lo:hi]) / (hi - lo))
    return smoothed


def _bridge_feature_length_m(feature: RoadFeature) -> Optional[float]:
    tags = feature.tags or {}
    raw_length = tags.get("bridge_length_m")
    if raw_length is not None:
        try:
            length = float(raw_length)
            if length > 0:
                return length
        except (TypeError, ValueError):
            pass

    try:
        return _haversine_m(
            float(tags["bridge_start_lat"]),
            float(tags["bridge_start_lon"]),
            float(tags["bridge_end_lat"]),
            float(tags["bridge_end_lon"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _track_distance_between_samples(tile_samples: List[Dict], start_idx: int, end_idx: int) -> Optional[float]:
    distance_m = 0.0
    for idx in range(start_idx + 1, end_idx + 1):
        prev = tile_samples[idx - 1]
        curr = tile_samples[idx]
        prev_lat = prev.get("lat")
        prev_lon = prev.get("lon")
        curr_lat = curr.get("lat")
        curr_lon = curr.get("lon")
        if None in (prev_lat, prev_lon, curr_lat, curr_lon):
            return None
        distance_m += _haversine_m(prev_lat, prev_lon, curr_lat, curr_lon)
    return distance_m


def _append_bridge_preprocess_diagnostic(
    diagnostics: Optional[List[Dict]],
    feature: RoadFeature,
    *,
    status: str,
    reason: str,
    best_start_idx: Optional[int] = None,
    best_end_idx: Optional[int] = None,
    best_start_dist_m: Optional[float] = None,
    best_end_dist_m: Optional[float] = None,
    entry_idx: Optional[int] = None,
    exit_idx: Optional[int] = None,
    span_samples: Optional[int] = None,
    time_span_s: Optional[float] = None,
    track_distance_m: Optional[float] = None,
    bridge_length_m: Optional[float] = None,
    entry_elev_m: Optional[float] = None,
    exit_elev_m: Optional[float] = None,
) -> None:
    if diagnostics is None:
        return

    diagnostics.append({
        "status": status,
        "reason": reason,
        "bridge_name": feature.name,
        "osm_id": feature.osm_id,
        "tile_id": feature.tile_id,
        "bridge_length_m": round(bridge_length_m, 2) if bridge_length_m is not None else None,
        "best_start_idx": best_start_idx,
        "best_end_idx": best_end_idx,
        "best_start_dist_m": round(best_start_dist_m, 2) if best_start_dist_m is not None else None,
        "best_end_dist_m": round(best_end_dist_m, 2) if best_end_dist_m is not None else None,
        "entry_idx": entry_idx,
        "exit_idx": exit_idx,
        "span_samples": span_samples,
        "time_span_s": round(time_span_s, 2) if time_span_s is not None else None,
        "track_distance_m": round(track_distance_m, 2) if track_distance_m is not None else None,
        "entry_elev_m": round(entry_elev_m, 2) if entry_elev_m is not None else None,
        "exit_elev_m": round(exit_elev_m, 2) if exit_elev_m is not None else None,
    })


def preprocess_bridge_elevations(
    tile_samples: List[Dict],
    bridge_features: Optional[List[RoadFeature]] = None,
    diagnostics: Optional[List[Dict]] = None,
) -> List[Dict]:
    """Interpolate elevation across bridge spans to prevent false climbs.

    For each bridge, find samples that are geographically on the bridge
    (within 50m of the bridge way endpoints). Replace their elevation with
    linear interpolation between the entry and exit elevation.

    This prevents the barometric altimeter from creating false elevation
    peaks when crossing bridges high above rivers/roads below.

    Modifies tile_samples IN PLACE and returns the same list.

    Args:
        tile_samples: List of sample dicts with 't', 'elevation_m', 'lat', 'lon'.
        bridge_features: Pre-fetched bridge RoadFeatures. If None, fetches from
            Supabase based on the tiles in tile_samples.
        diagnostics: Optional list populated with accepted/skipped bridge spans.

    Returns:
        The same tile_samples list (modified in place).
    """
    if not tile_samples:
        return tile_samples

    # Fetch bridge features if not provided
    if bridge_features is None:
        try:
            import h3
        except ImportError:
            logger.warning("h3 not available for bridge preprocessing")
            return tile_samples

        # Collect unique tile IDs from samples
        tile_ids: Set[str] = set()
        for s in tile_samples:
            tid = s.get("tile_id")
            if tid:
                tile_ids.add(tid)
            else:
                lat = s.get("lat")
                lon = s.get("lon")
                if lat is not None and lon is not None:
                    try:
                        tile_ids.add(h3.latlng_to_cell(lat, lon, H3_RESOLUTION))
                    except Exception:
                        pass

        if not tile_ids:
            return tile_samples

        all_features = fetch_road_features_for_tiles(tile_ids)
        bridge_features = [f for f in all_features if f.feature_type == "bridge"]

    if not bridge_features:
        return tile_samples

    # Deduplicate bridges by osm_id (same bridge appears in multiple tiles)
    seen_osm_ids: Set[int] = set()
    unique_bridges: List[RoadFeature] = []
    for bf in bridge_features:
        if bf.osm_id not in seen_osm_ids:
            seen_osm_ids.add(bf.osm_id)
            unique_bridges.append(bf)

    # Only process bridges that have endpoint geometry in tags
    bridges_with_geometry = []
    for bf in unique_bridges:
        tags = bf.tags or {}
        if all(k in tags for k in ("bridge_start_lat", "bridge_start_lon",
                                     "bridge_end_lat", "bridge_end_lon")):
            bridges_with_geometry.append(bf)

    if not bridges_with_geometry:
        logger.debug(
            f"Bridge preprocessing: {len(unique_bridges)} bridges found but "
            f"none have endpoint geometry in tags"
        )
        return tile_samples

    # Max span to interpolate (prevents interpolating across very long bridges
    # that might contain real elevation change)
    MAX_SPAN_SAMPLES = 500

    interpolated_count = 0

    for bf in bridges_with_geometry:
        tags = bf.tags
        bridge_length_m = _bridge_feature_length_m(bf)
        b_start_lat = float(tags["bridge_start_lat"])
        b_start_lon = float(tags["bridge_start_lon"])
        b_end_lat = float(tags["bridge_end_lat"])
        b_end_lon = float(tags["bridge_end_lon"])

        # Find the sample closest to bridge start
        best_start_idx = None
        best_start_dist = float("inf")
        # Find the sample closest to bridge end
        best_end_idx = None
        best_end_dist = float("inf")

        for i, s in enumerate(tile_samples):
            lat = s.get("lat")
            lon = s.get("lon")
            if lat is None or lon is None:
                continue

            d_start = _haversine_m(lat, lon, b_start_lat, b_start_lon)
            if d_start < best_start_dist:
                best_start_dist = d_start
                best_start_idx = i

            d_end = _haversine_m(lat, lon, b_end_lat, b_end_lon)
            if d_end < best_end_dist:
                best_end_dist = d_end
                best_end_idx = i

        # Validate: both endpoints found within threshold
        if best_start_idx is None or best_end_idx is None:
            _append_bridge_preprocess_diagnostic(
                diagnostics,
                bf,
                status="skipped",
                reason="endpoint_missing",
                best_start_idx=best_start_idx,
                best_end_idx=best_end_idx,
                bridge_length_m=bridge_length_m,
            )
            continue
        if (
            best_start_dist > BRIDGE_PREPROCESS_ENDPOINT_MATCH_THRESHOLD_M
            or best_end_dist > BRIDGE_PREPROCESS_ENDPOINT_MATCH_THRESHOLD_M
        ):
            _append_bridge_preprocess_diagnostic(
                diagnostics,
                bf,
                status="skipped",
                reason="endpoint_too_far",
                best_start_idx=best_start_idx,
                best_end_idx=best_end_idx,
                best_start_dist_m=best_start_dist,
                best_end_dist_m=best_end_dist,
                bridge_length_m=bridge_length_m,
            )
            continue

        # Ensure entry_idx < exit_idx (rider might cross bridge in either direction)
        entry_idx = min(best_start_idx, best_end_idx)
        exit_idx = max(best_start_idx, best_end_idx)

        # Skip if span is too large or zero
        span = exit_idx - entry_idx
        if span <= 1 or span > MAX_SPAN_SAMPLES:
            _append_bridge_preprocess_diagnostic(
                diagnostics,
                bf,
                status="skipped",
                reason="sample_span_out_of_range",
                best_start_idx=best_start_idx,
                best_end_idx=best_end_idx,
                best_start_dist_m=best_start_dist,
                best_end_dist_m=best_end_dist,
                entry_idx=entry_idx,
                exit_idx=exit_idx,
                span_samples=span,
                bridge_length_m=bridge_length_m,
            )
            continue

        entry_t = tile_samples[entry_idx].get("t")
        exit_t = tile_samples[exit_idx].get("t")
        time_span_s = None
        if entry_t is not None and exit_t is not None:
            time_span_s = abs(float(exit_t) - float(entry_t))
            if time_span_s > BRIDGE_PREPROCESS_MAX_TIME_S:
                _append_bridge_preprocess_diagnostic(
                    diagnostics,
                    bf,
                    status="skipped",
                    reason="time_span_too_large",
                    best_start_idx=best_start_idx,
                    best_end_idx=best_end_idx,
                    best_start_dist_m=best_start_dist,
                    best_end_dist_m=best_end_dist,
                    entry_idx=entry_idx,
                    exit_idx=exit_idx,
                    span_samples=span,
                    time_span_s=time_span_s,
                    bridge_length_m=bridge_length_m,
                )
                continue

        track_distance_m = _track_distance_between_samples(tile_samples, entry_idx, exit_idx)
        if bridge_length_m is not None and track_distance_m is not None:
            max_track_distance_m = max(
                bridge_length_m + BRIDGE_PREPROCESS_TRACK_DISTANCE_SLACK_M,
                bridge_length_m * BRIDGE_PREPROCESS_TRACK_DISTANCE_RATIO,
            )
            if track_distance_m > max_track_distance_m:
                _append_bridge_preprocess_diagnostic(
                    diagnostics,
                    bf,
                    status="skipped",
                    reason="track_span_too_large",
                    best_start_idx=best_start_idx,
                    best_end_idx=best_end_idx,
                    best_start_dist_m=best_start_dist,
                    best_end_dist_m=best_end_dist,
                    entry_idx=entry_idx,
                    exit_idx=exit_idx,
                    span_samples=span,
                    time_span_s=time_span_s,
                    track_distance_m=track_distance_m,
                    bridge_length_m=bridge_length_m,
                )
                continue

        # Get entry and exit elevations
        entry_elev = tile_samples[entry_idx].get("elevation_m")
        exit_elev = tile_samples[exit_idx].get("elevation_m")
        if entry_elev is None or exit_elev is None:
            _append_bridge_preprocess_diagnostic(
                diagnostics,
                bf,
                status="skipped",
                reason="missing_elevation",
                best_start_idx=best_start_idx,
                best_end_idx=best_end_idx,
                best_start_dist_m=best_start_dist,
                best_end_dist_m=best_end_dist,
                entry_idx=entry_idx,
                exit_idx=exit_idx,
                span_samples=span,
                time_span_s=time_span_s,
                track_distance_m=track_distance_m,
                bridge_length_m=bridge_length_m,
            )
            continue

        _append_bridge_preprocess_diagnostic(
            diagnostics,
            bf,
            status="accepted",
            reason="interpolated",
            best_start_idx=best_start_idx,
            best_end_idx=best_end_idx,
            best_start_dist_m=best_start_dist,
            best_end_dist_m=best_end_dist,
            entry_idx=entry_idx,
            exit_idx=exit_idx,
            span_samples=span,
            time_span_s=time_span_s,
            track_distance_m=track_distance_m,
            bridge_length_m=bridge_length_m,
            entry_elev_m=entry_elev,
            exit_elev_m=exit_elev,
        )

        # Linear interpolation across the bridge span
        for j in range(entry_idx, exit_idx + 1):
            frac = (j - entry_idx) / span
            interpolated_elev = entry_elev + frac * (exit_elev - entry_elev)

            # Store original elevation for debugging
            if "orig_elevation_m" not in tile_samples[j]:
                tile_samples[j]["orig_elevation_m"] = tile_samples[j].get("elevation_m")

            tile_samples[j]["elevation_m"] = interpolated_elev

        interpolated_count += 1
        bridge_name = bf.name or f"OSM:{bf.osm_id}"
        bridge_length = tags.get("bridge_length_m", "?")
        logger.info(
            f"[BridgePreprocess] Interpolated bridge '{bridge_name}' "
            f"(osm_id={bf.osm_id}, length={bridge_length}m): "
            f"samples [{entry_idx}..{exit_idx}] ({span} samples), "
            f"elev {entry_elev:.1f}m -> {exit_elev:.1f}m"
        )

    if interpolated_count > 0:
        logger.info(
            f"[BridgePreprocess] Interpolated {interpolated_count} bridge(s) "
            f"out of {len(bridges_with_geometry)} with geometry"
        )
    else:
        logger.debug(
            f"[BridgePreprocess] No bridges matched ride track "
            f"({len(bridges_with_geometry)} bridges with geometry checked)"
        )

    return tile_samples


def _parse_sample_datetime(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _datetime_delta_seconds(value: datetime, base_time: datetime) -> float:
    if value.tzinfo is None and base_time.tzinfo is not None:
        value = value.replace(tzinfo=base_time.tzinfo)
    elif value.tzinfo is not None and base_time.tzinfo is None:
        base_time = base_time.replace(tzinfo=value.tzinfo)
    return (value - base_time).total_seconds()


def _seconds_value(value) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, timedelta):
        return value.total_seconds()
    return None


def _sample_time_as_seconds(value, *, base_time) -> Optional[float]:
    seconds = _seconds_value(value)
    if seconds is not None:
        return seconds
    parsed_value = _parse_sample_datetime(value)
    parsed_base = _parse_sample_datetime(base_time)
    if parsed_value is not None and parsed_base is not None:
        return _datetime_delta_seconds(parsed_value, parsed_base)
    return None


def _target_time_as_seconds(time_offset_s, *, base_time) -> Optional[float]:
    offset_seconds = _seconds_value(time_offset_s)
    if offset_seconds is not None:
        base_seconds = _seconds_value(base_time)
        if base_seconds is not None:
            return base_seconds + offset_seconds
        return offset_seconds

    parsed_value = _parse_sample_datetime(time_offset_s)
    parsed_base = _parse_sample_datetime(base_time)
    if parsed_value is not None and parsed_base is not None:
        return _datetime_delta_seconds(parsed_value, parsed_base)
    return None


def _time_to_sample_idx(tile_samples: List[Dict], time_offset_s) -> Optional[int]:
    """Map a time offset (seconds from activity start) to the nearest sample index."""
    if not tile_samples:
        return None

    # Get the base time from the first sample
    base_t = tile_samples[0].get("t")
    if base_t is None:
        # Fall back to index-based mapping if no timestamps
        # Assume ~1 sample per second
        try:
            return min(int(time_offset_s), len(tile_samples) - 1)
        except (TypeError, ValueError):
            return None

    target_t = _target_time_as_seconds(time_offset_s, base_time=base_t)
    if target_t is None:
        return None
    best_idx = 0
    best_diff = float("inf")

    for i, s in enumerate(tile_samples):
        t = s.get("t")
        if t is None:
            continue
        sample_t = _sample_time_as_seconds(t, base_time=base_t)
        if sample_t is None:
            continue
        diff = abs(sample_t - target_t)
        if diff < best_diff:
            best_diff = diff
            best_idx = i

    return best_idx
