#!/usr/bin/env python3
"""
Run climb detection on ONLY the eval holdout set and score against ground truth.

This produces the honest out-of-sample P/R/F1 for the detector, free from
any tuning contamination. The train set was (implicitly) used for parameter
tuning; the eval set was never seen during development.

Prerequisites:
    Run create_holdout_split.py first to create the ride_split table.

Usage:
    cd backend && source venv/bin/activate
    python ../tools/corpus/run_holdout_eval.py

    # Also score the train set for comparison
    python ../tools/corpus/run_holdout_eval.py --also-train

    # Verbose per-ride output
    python ../tools/corpus/run_holdout_eval.py -v

    # Save results to JSON
    python ../tools/corpus/run_holdout_eval.py -o holdout_results.json
"""

from __future__ import annotations

import argparse
import copy
import json
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).parent.parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.patterns.climb import detect_climbs_with_rust
from app.services.tile_service import TileService

from holdout_reference_quality import (
    holdout_policy_classification,
    quarantine_repeated_segment_spam,
    quarantined_segment_count,
)

GOLDEN_DB = Path(__file__).parent / "golden_corpus.db"
MIN_CLIMB_VERT_M = 25.0
MIN_CLIMB_GRADE_PCT = 2.0
MIN_DETECT_VERT_M = 20.0
OVERLAP_THRESHOLD = 0.30


# ---------------------------------------------------------------------------
# Data classes (same as run_full_comparison.py for consistency)
# ---------------------------------------------------------------------------

@dataclass
class Segment:
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
class Detection:
    start_s: int
    end_s: int
    vert_m: float
    grade_pct: float
    distance_m: float
    mode: str
    economic_eligible: bool = True
    abstention_reasons: Tuple[str, ...] = ()


@dataclass
class MatchSummary:
    matched: int
    missed: int
    extras: int
    display_only_extras: int
    false_rewardable_extras: int


# ---------------------------------------------------------------------------
# Helpers (same logic as run_full_comparison.py — not imported to keep this
# script self-contained and immune to refactors of the comparison script)
# ---------------------------------------------------------------------------

def dedup_segments(segments: List[Segment]) -> List[Segment]:
    """Group overlapping segments, keep highest-elevation representative."""
    groups: List[List[Segment]] = []
    for seg in sorted(segments, key=lambda s: s.start_index):
        placed = False
        for group in groups:
            for existing in group:
                overlap = max(
                    0,
                    min(seg.end_index, existing.end_index) -
                    max(seg.start_index, existing.start_index),
                )
                shorter = min(
                    max(1, seg.end_index - seg.start_index),
                    max(1, existing.end_index - existing.start_index),
                )
                if overlap / shorter >= OVERLAP_THRESHOLD:
                    group.append(seg)
                    placed = True
                    break
            if placed:
                break
        if not placed:
            groups.append([seg])
    return [max(g, key=lambda s: s.elevation_diff) for g in groups]


def streams_to_tile_data(streams: Dict) -> Tuple[list, list]:
    """Convert Strava streams dict to tile_samples and tile_runs."""
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
        {
            "tile_id": s.tile_id, "t": int(s.t), "lat": s.lat, "lon": s.lon,
            "elevation_m": s.elevation_m, "power_w": s.power_w,
            "hr_bpm": s.hr_bpm, "speed_mps": s.speed_mps,
        }
        for s in ts.get_tile_sequence(points, resolution=10, start_time=0)
    ]
    tile_runs = ts.get_tile_run_sequence(points, resolution=10, start_time=0)
    return tile_samples, tile_runs or tile_samples


def _apply_bridge_preprocessing(tile_samples: list) -> list:
    """Apply bridge elevation preprocessing to match production pipeline.

    Production (pattern_engine.py) runs preprocess_bridge_elevations() before
    detection. Without this, eval metrics are slightly off-policy.
    """
    try:
        from app.services.road_enrichment import preprocess_bridge_elevations
        return preprocess_bridge_elevations(tile_samples)
    except Exception:
        return tile_samples  # Graceful fallback if import fails


def run_detector(
    tile_samples: list,
    frequency_map: Optional[Dict[str, int]] = None,
    use_bridge_preprocessing: bool = False,
    persistence_candidate_samples: Optional[list] = None,
    preserve_pre_bridge_persistence: bool = False,
) -> List[Detection]:
    """Run canonical_v2 detector on tile_samples.

    Args:
        tile_samples: GPS/elevation tile samples
        frequency_map: H12 frequency prior (None = disabled)
        use_bridge_preprocessing: If True, run bridge elevation interpolation
            before detection to match production pipeline behavior
        persistence_candidate_samples: Optional explicit samples for persistence
            candidate generation
        preserve_pre_bridge_persistence: If True, use the pre-bridge view for
            persistence proposals while scoring/confirmation uses bridge-processed
            samples. Experimental; not production default.
    """
    pre_bridge_samples = (
        copy.deepcopy(tile_samples)
        if (
            preserve_pre_bridge_persistence
            and use_bridge_preprocessing
            and persistence_candidate_samples is None
        )
        else None
    )

    if use_bridge_preprocessing:
        tile_samples = _apply_bridge_preprocessing(tile_samples)

    if persistence_candidate_samples is None:
        persistence_candidate_samples = pre_bridge_samples or tile_samples

    kwargs = {
        "user_weight_kg": 75.0,
        "algorithm": "canonical_v2",
        "persistence_candidate_samples": persistence_candidate_samples,
    }
    if frequency_map is not None:
        kwargs["frequency_map"] = frequency_map

    climbs = detect_climbs_with_rust(tile_samples, **kwargs)

    return [
        Detection(
            start_s=c.start_time_offset_s,
            end_s=c.end_time_offset_s,
            vert_m=c.vert_m,
            grade_pct=c.avg_gradient_pct or 0,
            distance_m=c.distance_m or 0,
            mode=getattr(c, "detector_mode", "") or "canonical_v2",
            economic_eligible=bool(getattr(c, "economic_eligible", True)),
            abstention_reasons=tuple(getattr(c, "abstention_reasons", None) or ()),
        )
        for c in climbs
        if c.vert_m >= MIN_DETECT_VERT_M
    ]


def match_detections_to_segments(
    segments: List[Segment],
    detections: List[Detection],
    time_array: List[int],
) -> MatchSummary:
    """Match detections to segments and classify unmatched extras by reward risk."""
    for seg in segments:
        seg.start_time_s = (
            time_array[seg.start_index] if seg.start_index < len(time_array) else 0
        )
        seg.end_time_s = (
            time_array[seg.end_index] if seg.end_index < len(time_array) else 0
        )

    used_detections = set()
    matched = 0

    for seg in segments:
        best_idx = None
        best_overlap = 0.0

        for idx, det in enumerate(detections):
            if idx in used_detections:
                continue
            ovl = max(
                0,
                min(seg.end_time_s, det.end_s) - max(seg.start_time_s, det.start_s),
            )
            shorter = min(
                max(1, seg.end_time_s - seg.start_time_s),
                max(1, det.end_s - det.start_s),
            )
            ratio = ovl / shorter
            if ratio >= OVERLAP_THRESHOLD and ratio > best_overlap:
                best_idx = idx
                best_overlap = ratio

        if best_idx is not None:
            used_detections.add(best_idx)
            matched += 1

    missed = len(segments) - matched
    unmatched = [
        det for idx, det in enumerate(detections)
        if idx not in used_detections
    ]
    display_only_extras = sum(1 for det in unmatched if not det.economic_eligible)
    false_rewardable_extras = sum(1 for det in unmatched if det.economic_eligible)
    return MatchSummary(
        matched=matched,
        missed=missed,
        extras=len(unmatched),
        display_only_extras=display_only_extras,
        false_rewardable_extras=false_rewardable_extras,
    )


def load_frequency_map(db_path: Path) -> Optional[Dict[str, int]]:
    """Load climb frequency map for H12 heuristic (same logic as run_full_comparison.py)."""
    # Try separate frequency DB first
    freq_db_path = db_path.parent / "golden_corpus_freq.db"
    if freq_db_path.exists():
        try:
            freq_conn = sqlite3.connect(str(freq_db_path), timeout=5)
            freq_rows = freq_conn.execute(
                "SELECT h3_tile, detection_count FROM climb_tile_frequency"
            ).fetchall()
            if freq_rows:
                freq_map = {r[0]: r[1] for r in freq_rows}
                freq_conn.close()
                return freq_map
            freq_conn.close()
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            pass

    # Fallback: try main DB
    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        freq_rows = conn.execute(
            "SELECT h3_tile, detection_count FROM climb_tile_frequency"
        ).fetchall()
        conn.close()
        if freq_rows:
            return {r[0]: r[1] for r in freq_rows}
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        pass

    return None


def compute_metrics(matched: int, missed: int, extras: int) -> Tuple[float, float, float]:
    """Compute precision, recall, F1."""
    total_expected = matched + missed
    total_detected = matched + extras
    precision = matched / total_detected if total_detected > 0 else 1.0
    recall = matched / total_expected if total_expected > 0 else 1.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    return precision, recall, f1


def classify_failure(matched: int, missed: int, extras: int) -> str:
    """Product-oriented failure bucket for detector tuning."""
    if missed == 0 and extras == 0:
        return "clean_pass"
    if matched == 0 and missed > 0 and extras == 0:
        return "missing_all_expected"
    if missed > 0 and extras > 0:
        return "mixed_boundary_drift"
    if missed > 0:
        return "under_detecting"
    if extras > 0:
        return "over_generating"
    return "unclassified"


def score_split(
    conn: sqlite3.Connection,
    split_name: str,
    frequency_map: Optional[Dict[str, int]],
    verbose: bool = False,
    use_bridge_preprocessing: bool = False,
    preserve_pre_bridge_persistence: bool = False,
    limit: int = 0,
) -> Dict:
    """
    Score all rides in a given split ('train' or 'eval').

    Returns dict with totals and per-ride results.
    """
    rows = conn.execute("""
        SELECT DISTINCT r.activity_id, r.name, r.elevation_gain_m
        FROM rides r
        JOIN ride_split rs ON r.activity_id = rs.activity_id
        JOIN strava_segment_efforts s ON r.activity_id = s.activity_id
        JOIN activity_streams a ON r.activity_id = a.activity_id
        WHERE rs.split = ?
              AND s.is_climb = 1
              AND s.elevation_diff >= ?
              AND s.average_grade >= ?
        GROUP BY r.activity_id
        HAVING COUNT(s.id) >= 3
        ORDER BY r.start_date ASC
    """, (split_name, MIN_CLIMB_VERT_M, MIN_CLIMB_GRADE_PCT)).fetchall()
    if limit > 0:
        rows = rows[:limit]

    total_matched = 0
    total_missed = 0
    total_extras = 0
    total_display_only_extras = 0
    total_false_rewardable_extras = 0
    raw_total_matched = 0
    raw_total_missed = 0
    raw_total_extras = 0
    raw_total_display_only_extras = 0
    raw_total_false_rewardable_extras = 0
    scored = 0
    raw_scored = 0
    errors = 0
    taxonomy: Dict[str, int] = defaultdict(int)
    raw_taxonomy: Dict[str, int] = defaultdict(int)
    quarantine_by_reason: Counter[str] = Counter()
    quarantine_examples: list[dict] = []
    total_quarantined_references = 0
    per_ride = []
    t0 = time.time()

    for idx, (aid, name, elev) in enumerate(rows):
        cached = conn.execute(
            "SELECT streams_json FROM activity_streams WHERE activity_id = ?", (aid,)
        ).fetchone()
        if not cached:
            continue

        efforts = conn.execute("""
            SELECT segment_id, segment_name, start_index, end_index,
                   elevation_diff, average_grade, distance_m
            FROM strava_segment_efforts
            WHERE activity_id = ? AND is_climb = 1
                  AND elevation_diff >= ? AND average_grade >= ?
            ORDER BY start_index
        """, (aid, MIN_CLIMB_VERT_M, MIN_CLIMB_GRADE_PCT)).fetchall()

        raw_segments = [
            Segment(
                segment_id=e[0], segment_name=e[1], start_index=e[2],
                end_index=e[3], elevation_diff=e[4], average_grade=e[5],
                distance_m=e[6] or 0,
            )
            for e in efforts
        ]
        raw_segments = dedup_segments(raw_segments)
        if len(raw_segments) < 3:
            continue

        segments, quarantined_groups = quarantine_repeated_segment_spam(raw_segments)
        if quarantined_groups:
            total_quarantined_references += quarantined_segment_count(quarantined_groups)
            for group in quarantined_groups:
                quarantine_by_reason[group.reason] += group.count
                if len(quarantine_examples) < 12:
                    quarantine_examples.append({
                        "activity_id": aid,
                        "ride_name": name,
                        "segment_id": group.segment_id,
                        "segment_name": group.segment_name,
                        "count": group.count,
                        "reason": group.reason,
                        "avg_elevation_diff": group.avg_elevation_diff,
                        "avg_average_grade": group.avg_average_grade,
                        "avg_distance_m": group.avg_distance_m,
                    })

        try:
            raw = json.loads(cached[0])
            streams = {s["type"]: s["data"] for s in raw}
            time_array = streams.get("time", [])

            tile_samples, _ = streams_to_tile_data(streams)
            if not tile_samples:
                continue

            detections = run_detector(
                tile_samples,
                frequency_map,
                use_bridge_preprocessing,
                preserve_pre_bridge_persistence=preserve_pre_bridge_persistence,
            )
            raw_match = match_detections_to_segments(
                raw_segments, detections, time_array
            )
            raw_total_matched += raw_match.matched
            raw_total_missed += raw_match.missed
            raw_total_extras += raw_match.extras
            raw_total_display_only_extras += raw_match.display_only_extras
            raw_total_false_rewardable_extras += raw_match.false_rewardable_extras
            raw_scored += 1
            policy_classification = holdout_policy_classification(aid)
            raw_classification = policy_classification or classify_failure(
                raw_match.matched, raw_match.missed, raw_match.extras
            )
            raw_taxonomy[raw_classification] += 1

            curated_scored = len(segments) >= 3
            if curated_scored:
                match = match_detections_to_segments(segments, detections, time_array)
                m = match.matched
                mi = match.missed
                ex = match.extras
                total_matched += match.matched
                total_missed += match.missed
                total_extras += match.extras
                total_display_only_extras += match.display_only_extras
                total_false_rewardable_extras += match.false_rewardable_extras
                scored += 1
                p, r, f1 = compute_metrics(m, mi, ex)
                classification = policy_classification or classify_failure(m, mi, ex)
                taxonomy[classification] += 1
            else:
                m = mi = ex = 0
                match = MatchSummary(0, 0, 0, 0, 0)
                p = r = f1 = None
                classification = "excluded_reference_spam"
                taxonomy[classification] += 1

            raw_p, raw_r, raw_f1 = compute_metrics(
                raw_match.matched, raw_match.missed, raw_match.extras
            )
            per_ride.append({
                "activity_id": aid,
                "name": name,
                "segments": len(segments),
                "raw_segments": len(raw_segments),
                "detections": len(detections),
                "matched": m,
                "missed": mi,
                "extras": ex,
                "display_only_extras": match.display_only_extras,
                "false_rewardable_extras": match.false_rewardable_extras,
                "precision": round(p, 3) if p is not None else None,
                "recall": round(r, 3) if r is not None else None,
                "f1": round(f1, 3) if f1 is not None else None,
                "classification": classification,
                "curated_scored": curated_scored,
                "raw_matched": raw_match.matched,
                "raw_missed": raw_match.missed,
                "raw_extras": raw_match.extras,
                "raw_display_only_extras": raw_match.display_only_extras,
                "raw_false_rewardable_extras": raw_match.false_rewardable_extras,
                "raw_precision": round(raw_p, 3),
                "raw_recall": round(raw_r, 3),
                "raw_f1": round(raw_f1, 3),
                "quarantined_reference_segments": quarantined_segment_count(quarantined_groups),
                "quarantine_reasons": [group.reason for group in quarantined_groups],
            })

            if verbose:
                label = (name or aid)[:40]
                f1_label = f"{f1:.2f}" if f1 is not None else "excluded"
                print(f"  [{idx+1}/{len(rows)}] {label:40s}  "
                      f"segs={len(segments):2d}/{len(raw_segments):2d}  "
                      f"det={len(detections):2d}  "
                      f"m={m} mi={mi} x={ex} "
                      f"(display={match.display_only_extras}, "
                      f"rewardable={match.false_rewardable_extras}) "
                      f"F1={f1_label} class={classification}")
            elif (idx + 1) % 50 == 0 or idx == len(rows) - 1:
                p_run, r_run, f1_run = compute_metrics(
                    total_matched, total_missed, total_extras
                )
                elapsed = time.time() - t0
                print(f"  [{idx+1}/{len(rows)}] scored={scored}/{raw_scored} curated/raw  "
                      f"m={total_matched} mi={total_missed} x={total_extras} "
                      f"(display={total_display_only_extras}, "
                      f"rewardable={total_false_rewardable_extras})  "
                      f"P={p_run:.3f} R={r_run:.3f} F1={f1_run:.3f}  ({elapsed:.0f}s)")

        except Exception as exc:
            errors += 1
            if errors <= 5:
                print(f"  [{idx+1}] {aid} ERROR: {exc}")

    elapsed = time.time() - t0
    precision, recall, f1 = compute_metrics(total_matched, total_missed, total_extras)
    raw_precision, raw_recall, raw_f1 = compute_metrics(
        raw_total_matched, raw_total_missed, raw_total_extras
    )

    return {
        "split": split_name,
        "rides_scored": scored,
        "raw_rides_scored": raw_scored,
        "excluded_rides": raw_scored - scored,
        "errors": errors,
        "total_matched": total_matched,
        "total_missed": total_missed,
        "total_extras": total_extras,
        "total_display_only_extras": total_display_only_extras,
        "total_false_rewardable_extras": total_false_rewardable_extras,
        "raw_total_matched": raw_total_matched,
        "raw_total_missed": raw_total_missed,
        "raw_total_extras": raw_total_extras,
        "raw_total_display_only_extras": raw_total_display_only_extras,
        "raw_total_false_rewardable_extras": raw_total_false_rewardable_extras,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "raw_precision": round(raw_precision, 4),
        "raw_recall": round(raw_recall, 4),
        "raw_f1": round(raw_f1, 4),
        "elapsed_s": round(elapsed, 1),
        "taxonomy": dict(sorted(taxonomy.items())),
        "raw_taxonomy": dict(sorted(raw_taxonomy.items())),
        "quarantined_reference_segments": total_quarantined_references,
        "quarantine_by_reason": dict(sorted(quarantine_by_reason.items())),
        "quarantine_examples": quarantine_examples,
        "per_ride": per_ride,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Score detector on holdout eval set (honest out-of-sample metrics)"
    )
    parser.add_argument("--db", default=str(GOLDEN_DB), help="Golden corpus DB path")
    parser.add_argument("--also-train", action="store_true",
                        help="Also score the train set for in-sample comparison")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print per-ride details")
    parser.add_argument("--output", "-o", type=str, default="",
                        help="Save full results to JSON file")
    parser.add_argument("--limit", type=int, default=0,
                        help="Score only the first N rides in each selected split for smoke runs")
    parser.add_argument(
        "--mode",
        choices=["scientific", "deployment", "both"],
        default="both",
        help=(
            "Score mode: "
            "'scientific' = H12 frequency map OFF (no leakage, clean baseline); "
            "'deployment' = full production pipeline (frequency map + bridge preprocessing); "
            "'both' = run both and show delta (default)"
        ),
    )
    parser.add_argument(
        "--preserve-pre-bridge-persistence",
        action="store_true",
        help=(
            "Experimental: generate persistence candidates from the pre-bridge "
            "elevation view while scoring on bridge-processed samples"
        ),
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    conn = sqlite3.connect(str(db_path))

    # Verify ride_split table exists
    table_check = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='ride_split'"
    ).fetchone()
    if not table_check:
        print("ERROR: ride_split table not found.")
        print("Run create_holdout_split.py first.")
        sys.exit(1)

    # Report split sizes
    split_counts = conn.execute(
        "SELECT split, COUNT(*) FROM ride_split GROUP BY split"
    ).fetchall()
    for split_name, count in split_counts:
        print(f"  {split_name}: {count} rides")
    print()

    # Load frequency map (for deployment mode)
    frequency_map = load_frequency_map(db_path)
    if frequency_map:
        print(f"Loaded frequency map: {len(frequency_map)} tiles")
    else:
        print("No frequency map found — H12 heuristic will be neutral in all modes")
    print()

    run_scientific = args.mode in ("scientific", "both")
    run_deployment = args.mode in ("deployment", "both")

    # --- Scientific mode: no frequency map, no bridge preprocessing ---
    scientific_result = None
    if run_scientific:
        print("=" * 80)
        print("SCIENTIFIC HOLDOUT (H12 OFF — no frequency prior, no bridge preprocessing)")
        print("=" * 80)
        scientific_result = score_split(
            conn, "eval", frequency_map=None,
            verbose=args.verbose,
            use_bridge_preprocessing=False,
            preserve_pre_bridge_persistence=args.preserve_pre_bridge_persistence,
            limit=args.limit,
        )
        print()

    # --- Deployment mode: full production pipeline ---
    deployment_result = None
    if run_deployment:
        print("=" * 80)
        print("DEPLOYMENT HOLDOUT (full production pipeline: H12 + bridge preprocessing)")
        print("=" * 80)
        deployment_result = score_split(
            conn, "eval", frequency_map=frequency_map,
            verbose=args.verbose,
            use_bridge_preprocessing=True,
            preserve_pre_bridge_persistence=args.preserve_pre_bridge_persistence,
            limit=args.limit,
        )
        print()

    # Optionally score train set (uses deployment settings for comparability)
    train_result = None
    if args.also_train:
        print("=" * 80)
        print("TRAIN SET (used for tuning — in-sample reference)")
        print("=" * 80)
        train_result = score_split(
            conn, "train", frequency_map=frequency_map,
            verbose=args.verbose,
            use_bridge_preprocessing=True,
            preserve_pre_bridge_persistence=args.preserve_pre_bridge_persistence,
            limit=args.limit,
        )
        print()

    # Summary
    print("=" * 80)
    print("HOLDOUT EVALUATION SUMMARY")
    print("=" * 80)
    print(f"Algorithm: canonical_v2 on tile_samples")
    print(f"Filters: segment_elev >= {MIN_CLIMB_VERT_M}m, "
          f"grade >= {MIN_CLIMB_GRADE_PCT}%, "
          f"detect_vert >= {MIN_DETECT_VERT_M}m")
    print(f"Overlap threshold: {OVERLAP_THRESHOLD}")
    print(f"Pre-bridge persistence seeds: {args.preserve_pre_bridge_persistence}")
    print()

    header = (
        f"{'Mode':<18s}  {'Rides':>6s}  {'Match':>6s}  {'Miss':>6s}  "
        f"{'Extra':>6s}  {'Xdisp':>6s}  {'Xrew':>6s}  "
        f"{'P':>7s}  {'R':>7s}  {'F1':>7s}"
    )
    print(header)
    print("-" * len(header))

    def _print_row(label, r):
        print(f"{label:<18s}  {r['rides_scored']:>6d}  {r['total_matched']:>6d}  "
              f"{r['total_missed']:>6d}  {r['total_extras']:>6d}  "
              f"{r['total_display_only_extras']:>6d}  "
              f"{r['total_false_rewardable_extras']:>6d}  "
              f"{r['precision']:>7.3f}  {r['recall']:>7.3f}  {r['f1']:>7.3f}")

    def _print_raw_row(label, r):
        print(f"{label:<18s}  {r['raw_rides_scored']:>6d}  {r['raw_total_matched']:>6d}  "
              f"{r['raw_total_missed']:>6d}  {r['raw_total_extras']:>6d}  "
              f"{r['raw_total_display_only_extras']:>6d}  "
              f"{r['raw_total_false_rewardable_extras']:>6d}  "
              f"{r['raw_precision']:>7.3f}  {r['raw_recall']:>7.3f}  {r['raw_f1']:>7.3f}")

    if scientific_result:
        _print_row("scientific", scientific_result)
        _print_raw_row("scientific raw", scientific_result)
    if deployment_result:
        _print_row("deployment", deployment_result)
        _print_raw_row("deployment raw", deployment_result)
    if train_result:
        _print_row("train", train_result)
        _print_raw_row("train raw", train_result)

    print()
    print("Failure taxonomy:")
    if scientific_result:
        print(f"  scientific: {scientific_result['taxonomy']}")
        print(f"  scientific raw: {scientific_result['raw_taxonomy']}")
    if deployment_result:
        print(f"  deployment: {deployment_result['taxonomy']}")
        print(f"  deployment raw: {deployment_result['raw_taxonomy']}")
    if train_result:
        print(f"  train: {train_result['taxonomy']}")
        print(f"  train raw: {train_result['raw_taxonomy']}")

    print()
    print("Reference curation:")
    for label, result in (
        ("scientific", scientific_result),
        ("deployment", deployment_result),
        ("train", train_result),
    ):
        if not result:
            continue
        print(
            f"  {label}: excluded_rides={result['excluded_rides']} "
            f"quarantined_refs={result['quarantined_reference_segments']} "
            f"by_reason={result['quarantine_by_reason']}"
        )
        for example in result["quarantine_examples"][:3]:
            print(
                f"    {example['activity_id']} {example['segment_name']} x{example['count']} "
                f"({example['reason']}, elev={example['avg_elevation_diff']}m, "
                f"grade={example['avg_average_grade']}%, dist={example['avg_distance_m']}m)"
            )

    # Show delta between modes if both were run
    if scientific_result and deployment_result:
        dp = deployment_result['precision'] - scientific_result['precision']
        dr = deployment_result['recall'] - scientific_result['recall']
        df1 = deployment_result['f1'] - scientific_result['f1']
        print(f"{'H12 delta':<14s}  {'':>6s}  {'':>6s}  {'':>6s}  {'':>6s}  "
              f"{dp:>+7.3f}  {dr:>+7.3f}  {df1:>+7.3f}")
        print()
        if abs(df1) < 0.005:
            print("H12 frequency prior has minimal impact (<0.5pp F1).")
            print("The leakage is academic — scientific and deployment metrics are equivalent.")
        elif df1 > 0:
            print(f"H12 frequency prior adds {df1:+.3f} F1. Scientific mode is the honest baseline.")
            print("Consider rebuilding frequency map from train-only data to eliminate leakage.")
        else:
            print(f"H12 frequency prior reduces F1 by {df1:.3f}. The prior may be hurting.")

    print()
    print("See docs/DETECTOR_PARAMS.md for canonical parameter values.")
    print("=" * 80)

    # Save results
    if args.output:
        output = {}
        if scientific_result:
            output["scientific"] = {k: v for k, v in scientific_result.items() if k != "per_ride"}
            output["scientific_per_ride"] = scientific_result["per_ride"]
        if deployment_result:
            output["deployment"] = {k: v for k, v in deployment_result.items() if k != "per_ride"}
            output["deployment_per_ride"] = deployment_result["per_ride"]
        if train_result:
            output["train"] = {k: v for k, v in train_result.items() if k != "per_ride"}
            output["train_per_ride"] = train_result["per_ride"]
        if scientific_result and deployment_result:
            output["h12_delta_f1"] = round(deployment_result["f1"] - scientific_result["f1"], 4)
        output["config"] = {
            "min_climb_vert_m": MIN_CLIMB_VERT_M,
            "min_climb_grade_pct": MIN_CLIMB_GRADE_PCT,
            "min_detect_vert_m": MIN_DETECT_VERT_M,
            "overlap_threshold": OVERLAP_THRESHOLD,
            "algorithm": "canonical_v2",
            "frequency_map_tiles": len(frequency_map) if frequency_map else 0,
            "mode": args.mode,
            "limit": args.limit,
            "preserve_pre_bridge_persistence": args.preserve_pre_bridge_persistence,
        }
        Path(args.output).write_text(json.dumps(output, indent=2))
        print(f"\nFull results saved to {args.output}")

    conn.close()


if __name__ == "__main__":
    main()
