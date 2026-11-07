#!/usr/bin/env python3
"""
Analyze WHY canonical_v2's chooser drops climbs that persistence finds.

For each missed Strava segment:
1. Load cached streams for the ride
2. Re-run canonical_v2 detection with full scoring instrumentation
3. Trace each persistence proposal through the scoring pipeline
4. Report the exact score breakdown and rejection reason

Output: per-climb scoring breakdown + aggregate categorization of 610 misses.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).parent.parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.patterns.climb import (
    ClimbCandidate,
    ClimbPattern,
    RideQualityProfile,
    _build_climb_candidates,
    _candidate_family,
    _candidate_fragmentation_penalty,
    _candidate_quality_penalty,
    _candidate_source_prior,
    _candidates_corroborate,
    _choose_canonical_v2_climbs,
    _climb_strength_score,
    _climb_vam,
    _run_canonical_momentum_sweep,
    _score_climb_candidate,
    classify_terrain,
    detect_climbs_with_rust,
    CANONICAL_V2_MIN_SCORE,
    CANONICAL_V2_SINGLE_SOURCE_PENALTY,
)
from app.services.patterns.climb_profile import build_ride_climb_profile
from app.services.tile_service import TileService

GOLDEN_DB = Path(__file__).parent / "golden_corpus.db"
MIN_CLIMB_VERT_M = 25.0
MIN_CLIMB_GRADE_PCT = 2.0
MIN_DETECT_VERT_M = 20.0
OVERLAP_THRESHOLD = 0.35


@dataclass
class SegmentInfo:
    segment_id: int
    segment_name: str
    start_index: int
    end_index: int
    elevation_diff: float
    average_grade: float
    distance_m: float
    start_time_s: int = 0
    end_time_s: int = 0


@dataclass
class ScoreBreakdown:
    """Full scoring breakdown for a rejected persistence candidate."""
    activity_id: int
    segment_name: str
    seg_elev_diff: float
    seg_avg_grade: float
    # Climb candidate metrics
    climb_vert_m: float
    climb_time_s: int
    climb_gradient: float
    climb_distance_m: float
    climb_vam: float
    climb_persistence: Optional[float]
    # Score components
    strength: float
    source_prior: float
    corroboration_bonus: float
    fragmentation_penalty: float
    quality_penalty: float
    total_score: float
    # Threshold components
    base_threshold: float
    single_source_penalty: float
    sparse_threshold_add: float
    degraded_threshold_add: float
    acceptance_threshold: float
    # Computed
    score_deficit: float  # how far below threshold
    # Classification
    had_momentum_corroboration: bool
    corroborating_families: List[str]
    # Quality
    ride_sparse: bool
    ride_degraded_elev: bool
    ride_degraded_gps: bool
    integrity_score: float
    source_class: str
    # Fragmentation sub-rules triggered
    frag_rules: List[str]
    # Primary rejection reason
    primary_reason: str


def streams_to_tile_data(streams: Dict) -> Tuple[list, list]:
    """Convert cached Strava streams into tile_samples and tile_runs."""
    points = []
    for i, t in enumerate(streams.get("time", [])):
        point = {"timestamp": float(t)}
        if "altitude" in streams and i < len(streams["altitude"]):
            point["elevation_m"] = streams["altitude"][i]
        if "latlng" in streams and i < len(streams["latlng"]):
            point["lat"] = streams["latlng"][i][0]
            point["lon"] = streams["latlng"][i][1]
        if "watts" in streams and i < len(streams["watts"]):
            pw = streams["watts"][i]
            if pw and 0 < pw < 5000:
                point["power_w"] = pw
        if "heartrate" in streams and i < len(streams["heartrate"]):
            hr = streams["heartrate"][i]
            if hr and 0 < hr < 255:
                point["hr_bpm"] = hr
        points.append(point)

    if not points:
        return [], []

    ts = TileService()
    tile_samples = [
        {"tile_id": s.tile_id, "t": int(s.t), "lat": s.lat, "lon": s.lon,
         "elevation_m": s.elevation_m, "power_w": s.power_w,
         "hr_bpm": s.hr_bpm, "speed_mps": s.speed_mps}
        for s in ts.get_tile_sequence(points, resolution=10, start_time=0)
    ]
    tile_runs = ts.get_tile_run_sequence(points, resolution=10, start_time=0)
    return tile_samples, tile_runs or tile_samples


def _overlap_ratio(a_start, a_end, b_start, b_end) -> float:
    overlap = max(0, min(a_end, b_end) - max(a_start, b_start))
    shorter = min(max(1, a_end - a_start), max(1, b_end - b_start))
    return overlap / shorter


def _get_frag_rules(climb: ClimbPattern) -> List[str]:
    """Identify which fragmentation sub-rules fire for a given climb."""
    gradient = climb.avg_gradient_pct or 0.0
    distance = climb.distance_m or 0.0
    rules = []

    if climb.vert_m < 28.0 and gradient < 4.0:
        rules.append(f"low_vert_low_grade(v={climb.vert_m:.0f}<28,g={gradient:.1f}<4)")
    if climb.time_s < 90 and gradient < 6.0:
        rules.append(f"short_time_low_grade(t={climb.time_s}<90,g={gradient:.1f}<6)")
    if distance > 3500.0 and gradient < 2.0:
        rules.append(f"long_shallow(d={distance:.0f}>3500,g={gradient:.1f}<2)")
    if gradient < 2.5 and climb.time_s >= 600:
        rules.append(f"very_shallow_long(g={gradient:.1f}<2.5,t={climb.time_s}>=600)")
    elif gradient < 3.0 and climb.time_s >= 300:
        rules.append(f"shallow_medium(g={gradient:.1f}<3.0,t={climb.time_s}>=300)")
    if climb.vert_m >= 200.0 and gradient < 2.5:
        rules.append(f"high_vert_shallow(v={climb.vert_m:.0f}>=200,g={gradient:.1f}<2.5)")
    if distance < 500.0 and climb.vert_m < 25.0:
        rules.append(f"tiny(d={distance:.0f}<500,v={climb.vert_m:.0f}<25)")

    return rules


def _classify_rejection(bd: ScoreBreakdown) -> str:
    """Classify the primary rejection reason for a missed climb."""
    deficit = bd.score_deficit

    # Check if it's a near miss (below by less than 1.0)
    is_near = deficit < 1.0

    # Dominant factor analysis
    # The deficit = acceptance_threshold - total_score
    # total_score = strength + source_prior + corroboration - frag - quality
    # threshold = base + single_source + sparse + degraded

    reasons = []

    # Single source penalty is the most common threshold inflator
    if bd.single_source_penalty > 0 and not bd.had_momentum_corroboration:
        reasons.append("no_corroboration")

    if bd.fragmentation_penalty > 0:
        reasons.append("fragmentation")

    if bd.quality_penalty > 0.5:
        reasons.append("quality_penalty")

    if bd.strength <= 1.0:
        reasons.append("weak_strength")

    if bd.sparse_threshold_add > 0:
        reasons.append("sparse_threshold")

    if bd.degraded_threshold_add > 0:
        reasons.append("degraded_threshold")

    # Determine which is the DOMINANT factor
    # Compare what each contributes to the deficit
    contributions = {}
    if bd.single_source_penalty > 0:
        contributions["no_corroboration"] = bd.single_source_penalty
    if bd.fragmentation_penalty > 0:
        contributions["fragmentation"] = bd.fragmentation_penalty
    if bd.quality_penalty > 0:
        contributions["quality_penalty"] = bd.quality_penalty
    if bd.sparse_threshold_add > 0:
        contributions["sparse_threshold"] = bd.sparse_threshold_add
    if bd.degraded_threshold_add > 0:
        contributions["degraded_threshold"] = bd.degraded_threshold_add
    # Low strength is the absence of positive score
    max_possible_strength = 9.0  # 3 + 3 + 3
    contributions["low_strength"] = max(0, 3.0 - bd.strength)

    # Sort by contribution
    sorted_contribs = sorted(contributions.items(), key=lambda x: x[1], reverse=True)

    primary = sorted_contribs[0][0] if sorted_contribs else "unknown"

    if is_near:
        primary = f"near_miss:{primary}"

    return primary


def score_persistence_proposals_for_ride(
    activity_id: int,
    streams: Dict,
    segments: List[SegmentInfo],
    tile_samples: list,
    tile_runs: list,
) -> List[ScoreBreakdown]:
    """
    Run canonical_v2's internal pipeline and trace exactly why each
    persistence proposal was accepted or rejected. Then match rejected
    proposals against missed Strava segments.
    """
    import workout_parse as wp

    # Build quality + terrain just like canonical_v2 does
    ride_quality = RideQualityProfile.from_tile_samples(tile_samples)
    terrain_info = classify_terrain(tile_samples)
    ride_profile = build_ride_climb_profile(
        tile_samples,
        terrain_class=terrain_info.get("class") if terrain_info else None,
        terrain_confidence=terrain_info.get("confidence") if terrain_info else None,
    )

    # Run momentum sweep
    terrain_results, best_terrain, momentum_selected = _run_canonical_momentum_sweep(
        wp,
        tile_samples=tile_samples,
        config_overrides=None,
        arena_tiles=None,
        user_weight_kg=75.0,
        generate_signatures=True,
    )

    # Run persistence
    persistence_climbs = detect_climbs_with_rust(
        tile_samples,
        persistence_candidate_samples=tile_samples,
        user_weight_kg=75.0,
        algorithm="persistence",
    )

    # Run canonical_v2 (to know what it actually accepted)
    canonical_v2_output = _choose_canonical_v2_climbs(
        ride_quality=ride_quality,
        ride_profile=ride_profile,
        momentum_results=terrain_results,
        persistence_climbs=persistence_climbs,
    )

    # Build accepted time ranges
    accepted_ranges = [(c.start_time_offset_s, c.end_time_offset_s) for c in canonical_v2_output]

    # Now we replicate the chooser's scoring for ALL persistence proposals
    # to get the full breakdown for the REJECTED ones
    if not terrain_results:
        return []

    # Pick the best terrain set (same logic as chooser)
    from app.services.patterns.climb import _score_canonical_v2_momentum_set
    best_terrain_name = max(
        terrain_results,
        key=lambda tn: _score_canonical_v2_momentum_set(
            terrain_results[tn],
            persistence_climbs=persistence_climbs,
            ride_quality=ride_quality,
        ),
    )
    baseline_climbs = terrain_results[best_terrain_name]
    baseline_candidates = _build_climb_candidates(
        baseline_climbs, source=f"momentum:{best_terrain_name}", ride_quality=ride_quality,
    )
    persistence_candidates = _build_climb_candidates(
        persistence_climbs, source="persistence", ride_quality=ride_quality,
    )

    # Replicate the chooser's corroboration logic
    used_persistence = set()
    all_scored: List[Tuple[ClimbCandidate, bool, str]] = []  # (candidate, accepted, path)

    for baseline in baseline_candidates:
        overlapping_persistence = [
            (idx, candidate)
            for idx, candidate in enumerate(persistence_candidates)
            if _candidates_corroborate(baseline.climb, candidate.climb)
        ]
        used_persistence.update(idx for idx, _ in overlapping_persistence)

        baseline.corroborating_sources = [c.source for _, c in overlapping_persistence]
        baseline.corroborating_families = sorted({_candidate_family(s) for s in baseline.corroborating_sources})
        baseline.total_score, baseline.reasons = _score_climb_candidate(baseline)
        best_candidate = baseline

        for idx, candidate in overlapping_persistence:
            candidate.corroborating_sources = [baseline.source]
            candidate.corroborating_families = [baseline.family]
            candidate.total_score, candidate.reasons = _score_climb_candidate(candidate)

        accepted = best_candidate.total_score >= best_candidate.acceptance_threshold
        all_scored.append((baseline, accepted, "baseline_loop"))

        # Also score the overlapping persistence candidates individually
        for idx, candidate in overlapping_persistence:
            all_scored.append((candidate, accepted, "corroborate_loop"))

    # Persistence-only candidates (no momentum overlap)
    for idx, candidate in enumerate(persistence_candidates):
        if idx in used_persistence:
            continue

        # This is the persistence-only path
        corroborating_terrains = sorted(
            tn for tn, climbs in terrain_results.items()
            if any(_candidates_corroborate(candidate.climb, c) for c in climbs)
        )
        if len(corroborating_terrains) >= 2:
            candidate.corroborating_sources = [f"momentum:{t}" for t in corroborating_terrains]
            candidate.corroborating_families = ["momentum"]
        else:
            candidate.corroborating_sources = []
            candidate.corroborating_families = []

        candidate.total_score, candidate.reasons = _score_climb_candidate(candidate)
        # Extra +1.0 penalty for persistence-only path
        effective_threshold = candidate.acceptance_threshold
        if len(corroborating_terrains) < 2:
            # Chooser line 2138: `if len(corroborating_terrains) < 2: continue`
            all_scored.append((candidate, False, "persistence_only_no_terrain_support"))
        else:
            # Chooser line 2144: threshold + 1.0
            accepted = candidate.total_score >= candidate.acceptance_threshold + 1.0
            all_scored.append((candidate, accepted, "persistence_multi_terrain"))

    # Now match rejected persistence proposals against missed Strava segments
    time_array = streams.get("time", [])
    for seg in segments:
        seg.start_time_s = time_array[seg.start_index] if seg.start_index < len(time_array) else 0
        seg.end_time_s = time_array[seg.end_index] if seg.end_index < len(time_array) else 0

    # Find which segments the canonical_v2 MISSED
    missed_segments = []
    for seg in segments:
        matched_any = False
        for a_start, a_end in accepted_ranges:
            if _overlap_ratio(a_start, a_end, seg.start_time_s, seg.end_time_s) >= OVERLAP_THRESHOLD:
                matched_any = True
                break
        if not matched_any:
            missed_segments.append(seg)

    # For each missed segment, find the best-matching persistence proposal
    breakdowns = []
    for seg in missed_segments:
        # Find persistence proposals that overlap this segment
        best_match = None
        best_overlap = 0.0
        for candidate, accepted, path in all_scored:
            if accepted:
                continue
            if candidate.family != "persistence":
                continue
            ovl = _overlap_ratio(
                candidate.climb.start_time_offset_s,
                candidate.climb.end_time_offset_s,
                seg.start_time_s, seg.end_time_s,
            )
            if ovl >= 0.25 and ovl > best_overlap:  # slightly looser than 0.35 to catch more
                best_match = candidate
                best_overlap = ovl
                best_path = path

        if best_match is None:
            # No persistence proposal matched this segment at all
            # This means persistence didn't even detect it, or the overlap is too low
            continue

        c = best_match
        climb = c.climb

        strength = _climb_strength_score(climb)
        source_prior = _candidate_source_prior(c.source, climb)
        corr_bonus = 0.0
        if c.corroborating_families:
            corr_bonus = 1.5 * len(c.corroborating_families)
        elif c.corroborating_sources:
            corr_bonus = 0.5

        frag = _candidate_fragmentation_penalty(climb)
        # Apply discount if applicable
        if c.corroborating_families and climb.vert_m >= 100.0 and frag > 0:
            frag *= 0.3
        quality = _candidate_quality_penalty(climb, ride_quality)

        total = strength + source_prior + corr_bonus - frag - quality

        base_threshold = CANONICAL_V2_MIN_SCORE
        single_source_pen = 0.0
        if not c.corroborating_families:
            single_source_pen = CANONICAL_V2_SINGLE_SOURCE_PENALTY

        sparse_add = 0.5 if ride_quality.sparse_sampling else 0.0
        degraded_add = 0.25 if (ride_quality.degraded_elevation and climb.vert_m < 35.0) else 0.0

        threshold = base_threshold + single_source_pen + sparse_add + degraded_add

        # For persistence-only path, the effective threshold is +1.0
        if best_path == "persistence_multi_terrain":
            threshold += 1.0

        frag_rules = _get_frag_rules(climb)

        bd = ScoreBreakdown(
            activity_id=activity_id,
            segment_name=seg.segment_name,
            seg_elev_diff=seg.elevation_diff,
            seg_avg_grade=seg.average_grade,
            climb_vert_m=climb.vert_m,
            climb_time_s=climb.time_s,
            climb_gradient=climb.avg_gradient_pct or 0.0,
            climb_distance_m=climb.distance_m or 0.0,
            climb_vam=_climb_vam(climb),
            climb_persistence=climb.persistence,
            strength=strength,
            source_prior=source_prior,
            corroboration_bonus=corr_bonus,
            fragmentation_penalty=frag,
            quality_penalty=quality,
            total_score=total,
            base_threshold=base_threshold,
            single_source_penalty=single_source_pen,
            sparse_threshold_add=sparse_add,
            degraded_threshold_add=degraded_add,
            acceptance_threshold=threshold,
            score_deficit=threshold - total,
            had_momentum_corroboration=len(c.corroborating_families) > 0,
            corroborating_families=c.corroborating_families,
            ride_sparse=ride_quality.sparse_sampling,
            ride_degraded_elev=ride_quality.degraded_elevation,
            ride_degraded_gps=ride_quality.degraded_gps,
            integrity_score=ride_quality.integrity_score,
            source_class=ride_quality.source_class,
            frag_rules=frag_rules,
            primary_reason=_classify_rejection(ScoreBreakdown(
                activity_id=activity_id,
                segment_name=seg.segment_name,
                seg_elev_diff=seg.elevation_diff,
                seg_avg_grade=seg.average_grade,
                climb_vert_m=climb.vert_m,
                climb_time_s=climb.time_s,
                climb_gradient=climb.avg_gradient_pct or 0.0,
                climb_distance_m=climb.distance_m or 0.0,
                climb_vam=_climb_vam(climb),
                climb_persistence=climb.persistence,
                strength=strength,
                source_prior=source_prior,
                corroboration_bonus=corr_bonus,
                fragmentation_penalty=frag,
                quality_penalty=quality,
                total_score=total,
                base_threshold=base_threshold,
                single_source_penalty=single_source_pen,
                sparse_threshold_add=sparse_add,
                degraded_threshold_add=degraded_add,
                acceptance_threshold=threshold,
                score_deficit=threshold - total,
                had_momentum_corroboration=len(c.corroborating_families) > 0,
                corroborating_families=c.corroborating_families,
                ride_sparse=ride_quality.sparse_sampling,
                ride_degraded_elev=ride_quality.degraded_elevation,
                ride_degraded_gps=ride_quality.degraded_gps,
                integrity_score=ride_quality.integrity_score,
                source_class=ride_quality.source_class,
                frag_rules=frag_rules,
                primary_reason="",  # Will be set
            )),
        )
        breakdowns.append(bd)

    return breakdowns


def main():
    conn = sqlite3.connect(str(GOLDEN_DB))

    # Get recent canonical_v2 and persistence run IDs
    cv2_run = conn.execute(
        "SELECT run_id FROM detection_runs WHERE algorithm='canonical_v2' ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    pers_run = conn.execute(
        "SELECT run_id FROM detection_runs WHERE algorithm='persistence' ORDER BY created_at DESC LIMIT 1"
    ).fetchone()

    if not cv2_run or not pers_run:
        print("ERROR: Need detection_runs for both canonical_v2 and persistence.")
        print("Run: python tools/corpus/run_full_comparison.py --algorithms all")
        sys.exit(1)

    cv2_run_id = cv2_run[0]
    pers_run_id = pers_run[0]

    print(f"canonical_v2 run: {cv2_run_id}")
    print(f"persistence run:  {pers_run_id}")

    # Find segments missed by canonical_v2 but matched by persistence
    # These are the 610 climbs we need to investigate
    missed_by_cv2 = conn.execute("""
        SELECT cv2.activity_id, cv2.segment_id, cv2.segment_name,
               cv2.seg_elev_diff, cv2.seg_avg_grade, cv2.seg_distance_m,
               cv2.seg_start_s, cv2.seg_end_s
        FROM detection_results cv2
        WHERE cv2.run_id = ? AND cv2.result_type = 'missed'
        AND EXISTS (
            SELECT 1 FROM detection_results p
            WHERE p.run_id = ? AND p.result_type = 'matched'
            AND p.activity_id = cv2.activity_id
            AND p.segment_id = cv2.segment_id
        )
        ORDER BY cv2.seg_elev_diff DESC
    """, (cv2_run_id, pers_run_id)).fetchall()

    print(f"\nSegments missed by canonical_v2 but matched by persistence: {len(missed_by_cv2)}")

    # Show segment frequency (most-missed segments)
    seg_counts = Counter()
    for row in missed_by_cv2:
        seg_counts[row[2]] += 1

    print(f"\nTop 30 most-missed segment names:")
    for name, count in seg_counts.most_common(30):
        print(f"  {count:3d}x  {name}")

    # Get unique activity IDs from the misses
    miss_by_activity = defaultdict(list)
    for row in missed_by_cv2:
        aid, seg_id, seg_name, elev, grade, dist, start_s, end_s = row
        miss_by_activity[aid].append(SegmentInfo(
            segment_id=seg_id, segment_name=seg_name,
            start_index=0, end_index=0,
            elevation_diff=elev, average_grade=grade,
            distance_m=dist or 0,
            start_time_s=start_s or 0, end_time_s=end_s or 0,
        ))

    print(f"\nDistinct rides with missed climbs: {len(miss_by_activity)}")

    # Process rides
    all_breakdowns: List[ScoreBreakdown] = []
    errors = 0
    skipped = 0
    processed = 0
    max_rides = 0  # 0 = all

    for ride_idx, (activity_id, missed_segs) in enumerate(sorted(miss_by_activity.items())):
        if max_rides > 0 and ride_idx >= max_rides:
            break

        # Load cached streams
        cached = conn.execute(
            "SELECT streams_json FROM activity_streams WHERE activity_id = ?", (activity_id,)
        ).fetchone()
        if not cached:
            skipped += 1
            continue

        # Load ALL segments for this ride (need them for the full comparison)
        all_efforts = conn.execute("""
            SELECT segment_id, segment_name, start_index, end_index,
                   elevation_diff, average_grade, distance_m
            FROM strava_segment_efforts
            WHERE activity_id = ? AND is_climb = 1
                  AND elevation_diff >= ? AND average_grade >= ?
            ORDER BY start_index
        """, (activity_id, MIN_CLIMB_VERT_M, MIN_CLIMB_GRADE_PCT)).fetchall()

        all_segments = [
            SegmentInfo(
                segment_id=e[0], segment_name=e[1],
                start_index=e[2], end_index=e[3],
                elevation_diff=e[4], average_grade=e[5],
                distance_m=e[6] or 0,
            )
            for e in all_efforts
        ]

        try:
            raw = json.loads(cached[0])
            streams = {s["type"]: s["data"] for s in raw}

            tile_samples, tile_runs = streams_to_tile_data(streams)
            if not tile_samples:
                skipped += 1
                continue

            breakdowns = score_persistence_proposals_for_ride(
                activity_id=activity_id,
                streams=streams,
                segments=all_segments,
                tile_samples=tile_samples,
                tile_runs=tile_runs,
            )
            all_breakdowns.extend(breakdowns)
            processed += 1

            if (processed) % 25 == 0:
                print(f"  [{processed}/{len(miss_by_activity)}] analyzed, {len(all_breakdowns)} breakdowns so far")

        except Exception as exc:
            errors += 1
            if errors <= 5:
                import traceback
                print(f"  ERROR on activity {activity_id}: {exc}")
                traceback.print_exc()

    print(f"\nProcessed {processed} rides, skipped {skipped}, errors {errors}")
    print(f"Total scored breakdowns: {len(all_breakdowns)}")

    if not all_breakdowns:
        print("No breakdowns to analyze. Exiting.")
        return

    # =========================================================================
    # SECTION 1: Detailed breakdown for most-repeated missed segments
    # =========================================================================
    print("\n" + "=" * 100)
    print("SECTION 1: Detailed score breakdowns for top missed segments")
    print("=" * 100)

    # Group breakdowns by segment name
    by_segment = defaultdict(list)
    for bd in all_breakdowns:
        by_segment[bd.segment_name].append(bd)

    # Show top 15 most-repeated
    for seg_name, bds in sorted(by_segment.items(), key=lambda x: -len(x[1]))[:15]:
        print(f"\n{'─' * 90}")
        print(f"SEGMENT: {seg_name} ({len(bds)} misses)")
        print(f"  Strava elev: {bds[0].seg_elev_diff:.0f}m, grade: {bds[0].seg_avg_grade:.1f}%")
        print(f"{'─' * 90}")

        # Show first 3 instances in detail
        for i, bd in enumerate(bds[:3]):
            print(f"\n  Instance {i+1} (activity {bd.activity_id}):")
            print(f"    Persistence proposal: vert={bd.climb_vert_m:.0f}m, time={bd.climb_time_s}s, "
                  f"grade={bd.climb_gradient:.1f}%, dist={bd.climb_distance_m:.0f}m, "
                  f"VAM={bd.climb_vam:.0f}, persistence={bd.climb_persistence}")
            print(f"    ┌─── Score components ───")
            print(f"    │  strength:        {bd.strength:+.2f}")
            print(f"    │  source_prior:    {bd.source_prior:+.2f}  (persistence base=0.15, +0.35 if pers>=25)")
            print(f"    │  corroboration:   {bd.corroboration_bonus:+.2f}  (families={bd.corroborating_families})")
            print(f"    │  fragmentation:   {bd.fragmentation_penalty:-.2f}  {bd.frag_rules}")
            print(f"    │  quality:         {bd.quality_penalty:-.2f}  (integrity={bd.integrity_score:.2f}, "
                  f"sparse={bd.ride_sparse}, degraded_elev={bd.ride_degraded_elev})")
            print(f"    │  ─────────────────────")
            print(f"    │  TOTAL SCORE:     {bd.total_score:+.2f}")
            print(f"    ├─── Threshold ───")
            print(f"    │  base:            {bd.base_threshold:.2f}")
            print(f"    │  single_source:   {bd.single_source_penalty:+.2f}")
            print(f"    │  sparse:          {bd.sparse_threshold_add:+.2f}")
            print(f"    │  degraded:        {bd.degraded_threshold_add:+.2f}")
            print(f"    │  ─────────────────────")
            print(f"    │  THRESHOLD:       {bd.acceptance_threshold:.2f}")
            print(f"    └─── Deficit: {bd.score_deficit:+.2f}  →  {bd.primary_reason}")

        # Summary stats across all instances
        if len(bds) > 3:
            deficits = [b.score_deficit for b in bds]
            reasons = Counter(b.primary_reason for b in bds)
            print(f"\n  Summary across {len(bds)} instances:")
            print(f"    Median deficit: {sorted(deficits)[len(deficits)//2]:.2f}")
            print(f"    Min deficit: {min(deficits):.2f}, Max: {max(deficits):.2f}")
            print(f"    Reasons: {dict(reasons)}")

    # =========================================================================
    # SECTION 2: Aggregate categorization
    # =========================================================================
    print("\n" + "=" * 100)
    print("SECTION 2: Aggregate categorization of all missed climbs")
    print("=" * 100)

    reason_counts = Counter()
    for bd in all_breakdowns:
        reason_counts[bd.primary_reason] += 1

    total = len(all_breakdowns)
    print(f"\nTotal breakdowns analyzed: {total}")
    print(f"\nRejection reason distribution:")
    for reason, count in reason_counts.most_common():
        pct = 100.0 * count / total
        print(f"  {count:4d}  ({pct:5.1f}%)  {reason}")

    # =========================================================================
    # SECTION 3: Component analysis
    # =========================================================================
    print("\n" + "=" * 100)
    print("SECTION 3: Component-level analysis")
    print("=" * 100)

    # Score deficit distribution
    deficits = sorted(bd.score_deficit for bd in all_breakdowns)
    print(f"\nScore deficit distribution (threshold - total_score):")
    print(f"  Min:    {deficits[0]:.2f}")
    print(f"  p10:    {deficits[len(deficits)//10]:.2f}")
    print(f"  p25:    {deficits[len(deficits)//4]:.2f}")
    print(f"  Median: {deficits[len(deficits)//2]:.2f}")
    print(f"  p75:    {deficits[3*len(deficits)//4]:.2f}")
    print(f"  p90:    {deficits[9*len(deficits)//10]:.2f}")
    print(f"  Max:    {deficits[-1]:.2f}")
    near_misses = sum(1 for d in deficits if d < 1.0)
    print(f"  Near misses (deficit < 1.0): {near_misses} ({100*near_misses/total:.1f}%)")

    # Corroboration analysis
    with_corr = sum(1 for bd in all_breakdowns if bd.had_momentum_corroboration)
    without_corr = total - with_corr
    print(f"\nCorroboration:")
    print(f"  With momentum corroboration: {with_corr} ({100*with_corr/total:.1f}%)")
    print(f"  Without (single-source):     {without_corr} ({100*without_corr/total:.1f}%)")

    # Fragmentation analysis
    with_frag = sum(1 for bd in all_breakdowns if bd.fragmentation_penalty > 0)
    print(f"\nFragmentation penalty applied: {with_frag} ({100*with_frag/total:.1f}%)")
    frag_rule_counts = Counter()
    for bd in all_breakdowns:
        for rule in bd.frag_rules:
            frag_rule_counts[rule.split("(")[0]] += 1
    for rule, count in frag_rule_counts.most_common():
        print(f"  {count:4d}  {rule}")

    # Quality analysis
    with_quality = sum(1 for bd in all_breakdowns if bd.quality_penalty > 0.5)
    sparse = sum(1 for bd in all_breakdowns if bd.ride_sparse)
    degraded_e = sum(1 for bd in all_breakdowns if bd.ride_degraded_elev)
    degraded_g = sum(1 for bd in all_breakdowns if bd.ride_degraded_gps)
    print(f"\nQuality:")
    print(f"  Quality penalty > 0.5: {with_quality} ({100*with_quality/total:.1f}%)")
    print(f"  Sparse sampling rides: {sparse} ({100*sparse/total:.1f}%)")
    print(f"  Degraded elevation:    {degraded_e} ({100*degraded_e/total:.1f}%)")
    print(f"  Degraded GPS:          {degraded_g} ({100*degraded_g/total:.1f}%)")

    # Strength distribution
    print(f"\nStrength score distribution:")
    strengths = sorted(bd.strength for bd in all_breakdowns)
    for s_val in [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]:
        count = sum(1 for s in strengths if s_val <= s < s_val + 1)
        if count > 0:
            print(f"  [{s_val}, {s_val+1}): {count:4d} ({100*count/total:.1f}%)")

    # Segment characteristics
    print(f"\nMissed segment characteristics:")
    elevs = sorted(bd.seg_elev_diff for bd in all_breakdowns)
    grades = sorted(bd.seg_avg_grade for bd in all_breakdowns)
    print(f"  Segment elev diff — median: {elevs[len(elevs)//2]:.0f}m, "
          f"min: {elevs[0]:.0f}m, max: {elevs[-1]:.0f}m")
    print(f"  Segment avg grade — median: {grades[len(grades)//2]:.1f}%, "
          f"min: {grades[0]:.1f}%, max: {grades[-1]:.1f}%")

    # =========================================================================
    # SECTION 4: Recommendations
    # =========================================================================
    print("\n" + "=" * 100)
    print("SECTION 4: Scoring rule analysis and recommendations")
    print("=" * 100)

    # Simulate: what if single_source_penalty = 0.0?
    recovered_no_single = sum(
        1 for bd in all_breakdowns
        if bd.total_score >= (bd.acceptance_threshold - bd.single_source_penalty)
    )
    print(f"\nIF single_source_penalty removed (0.75 → 0.0):")
    print(f"  Would recover: {recovered_no_single}/{total} ({100*recovered_no_single/total:.1f}%)")

    # Simulate: what if single_source_penalty = 0.25?
    recovered_lower_single = sum(
        1 for bd in all_breakdowns
        if bd.total_score >= (bd.acceptance_threshold - bd.single_source_penalty + 0.25)
    )
    print(f"\nIF single_source_penalty reduced (0.75 → 0.25):")
    print(f"  Would recover: {recovered_lower_single}/{total} ({100*recovered_lower_single/total:.1f}%)")

    # Simulate: what if fragmentation penalty halved?
    recovered_half_frag = sum(
        1 for bd in all_breakdowns
        if (bd.total_score + bd.fragmentation_penalty * 0.5) >= bd.acceptance_threshold
    )
    print(f"\nIF fragmentation penalty halved:")
    print(f"  Would recover: {recovered_half_frag}/{total} ({100*recovered_half_frag/total:.1f}%)")

    # Simulate: what if persistence source_prior boosted?
    recovered_pers_prior = sum(
        1 for bd in all_breakdowns
        if (bd.total_score + 0.5) >= bd.acceptance_threshold  # +0.5 to prior
    )
    print(f"\nIF persistence source_prior boosted by +0.50:")
    print(f"  Would recover: {recovered_pers_prior}/{total} ({100*recovered_pers_prior/total:.1f}%)")

    # Simulate: what if MIN_SCORE lowered to 1.75?
    recovered_lower_min = sum(
        1 for bd in all_breakdowns
        if bd.total_score >= (bd.acceptance_threshold - 0.5)  # -0.5 from base
    )
    print(f"\nIF CANONICAL_V2_MIN_SCORE lowered (2.25 → 1.75):")
    print(f"  Would recover: {recovered_lower_min}/{total} ({100*recovered_lower_min/total:.1f}%)")

    # Combined: lower single_source + boost persistence prior
    recovered_combined = sum(
        1 for bd in all_breakdowns
        if (bd.total_score + 0.50) >= (bd.acceptance_threshold - bd.single_source_penalty + 0.25)
    )
    print(f"\nIF combined (single_source 0.75→0.25 AND persistence prior +0.50):")
    print(f"  Would recover: {recovered_combined}/{total} ({100*recovered_combined/total:.1f}%)")

    conn.close()


if __name__ == "__main__":
    main()
