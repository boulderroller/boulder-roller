#!/usr/bin/env python3
"""
2nd Geography Validation: evaluate canonical_v2 climb detector across geographies.

The detector was tuned on SEPA (Philadelphia) rides. This script measures how
well it generalizes to LA/Malibu, Tucson, Vermont/NH, Virginia, and others.

CRITICAL: The H12 frequency map is disabled for non-SEPA geographies. That map
was built from SEPA detections and would be methodologically wrong to apply
elsewhere (every non-SEPA tile has zero frequency).

Usage:
    cd backend && source venv/bin/activate
    python3 ../tools/corpus/run_geo_eval.py

    # Verbose per-ride output
    python3 ../tools/corpus/run_geo_eval.py -v

    # Save full results to JSON
    python3 ../tools/corpus/run_geo_eval.py -o geo_eval_results.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).parent.parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.patterns.climb import detect_climbs_with_rust
from app.services.tile_service import TileService

GOLDEN_DB = Path(__file__).parent / "golden_corpus.db"
MIN_CLIMB_VERT_M = 25.0
MIN_CLIMB_GRADE_PCT = 2.0
MIN_DETECT_VERT_M = 20.0
OVERLAP_THRESHOLD = 0.30
MIN_RIDES_PER_GEO = 5

# Climb size buckets (by Strava segment elevation_diff)
SIZE_BUCKETS = [
    ("Small(25-50)",   25.0,  50.0),
    ("Med(50-100)",    50.0, 100.0),
    ("Large(100-250)", 100.0, 250.0),
    ("Major(250+)",    250.0, 99999.0),
]


# ---------------------------------------------------------------------------
# Data classes (same as run_full_comparison.py)
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


# ---------------------------------------------------------------------------
# Core helpers (self-contained — same logic as run_full_comparison.py)
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
    """Apply bridge elevation preprocessing to match production pipeline."""
    try:
        from app.services.road_enrichment import preprocess_bridge_elevations
        return preprocess_bridge_elevations(tile_samples)
    except Exception:
        return tile_samples


def run_detector(
    tile_samples: list,
    frequency_map: Optional[Dict[str, int]] = None,
    use_bridge_preprocessing: bool = False,
) -> List[Detection]:
    """Run canonical_v2 detector on tile_samples."""
    if use_bridge_preprocessing:
        tile_samples = _apply_bridge_preprocessing(tile_samples)

    kwargs = {
        "user_weight_kg": 75.0,
        "algorithm": "canonical_v2",
        "persistence_candidate_samples": tile_samples,
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
        )
        for c in climbs
        if c.vert_m >= MIN_DETECT_VERT_M
    ]


def match_detections_to_segments(
    segments: List[Segment],
    detections: List[Detection],
    time_array: List[int],
) -> Tuple[int, int, int, List[dict]]:
    """
    Match detections to segments.

    Returns (matched, missed, extras, per_segment_records).
    Each record includes the segment's elevation_diff for size-bucket analysis.
    """
    for seg in segments:
        seg.start_time_s = (
            time_array[seg.start_index] if seg.start_index < len(time_array) else 0
        )
        seg.end_time_s = (
            time_array[seg.end_index] if seg.end_index < len(time_array) else 0
        )

    used_detections = set()
    matched = 0
    records = []

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
            records.append({
                "result": "matched",
                "elevation_diff": seg.elevation_diff,
            })
        else:
            records.append({
                "result": "missed",
                "elevation_diff": seg.elevation_diff,
            })

    missed = len(segments) - matched
    extras = len(detections) - len(used_detections)
    return matched, missed, extras, records


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


def load_frequency_map(db_path: Path) -> Optional[Dict[str, int]]:
    """Load SEPA climb frequency map (only used for SEPA geography)."""
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


# ---------------------------------------------------------------------------
# Per-geography evaluation
# ---------------------------------------------------------------------------

@dataclass
class GeoResult:
    geography: str
    rides_scored: int = 0
    errors: int = 0
    total_matched: int = 0
    total_missed: int = 0
    total_extras: int = 0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    elapsed_s: float = 0.0
    # Per size bucket: {bucket_name: {"matched": int, "total": int}}
    bucket_stats: Dict[str, Dict[str, int]] = field(default_factory=dict)


def score_geography(
    conn: sqlite3.Connection,
    geography: str,
    frequency_map: Optional[Dict[str, int]],
    verbose: bool = False,
    force_no_freq: bool = False,
    use_bridge_preprocessing: bool = False,
) -> GeoResult:
    """Score all scorable rides for a given geography.

    Args:
        force_no_freq: If True, disable frequency map even for SEPA (for clean comparison)
        use_bridge_preprocessing: If True, run bridge elevation interpolation before detection
    """

    # For non-SEPA geographies, disable the frequency map
    # It was built from SEPA detections and would bias non-SEPA evaluation
    if force_no_freq:
        geo_freq_map = None
    else:
        geo_freq_map = frequency_map if geography == "SEPA" else None

    rows = conn.execute("""
        SELECT DISTINCT r.activity_id, r.name, r.elevation_gain_m
        FROM rides r
        JOIN strava_segment_efforts s ON r.activity_id = s.activity_id
        JOIN activity_streams a ON r.activity_id = a.activity_id
        WHERE r.geography = ?
              AND s.is_climb = 1
              AND s.elevation_diff >= ?
              AND s.average_grade >= ?
        GROUP BY r.activity_id
        HAVING COUNT(s.id) >= 3
        ORDER BY r.start_date ASC
    """, (geography, MIN_CLIMB_VERT_M, MIN_CLIMB_GRADE_PCT)).fetchall()

    result = GeoResult(geography=geography)
    # Initialize bucket stats
    for bname, _, _ in SIZE_BUCKETS:
        result.bucket_stats[bname] = {"matched": 0, "total": 0}

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

        segments = [
            Segment(
                segment_id=e[0], segment_name=e[1], start_index=e[2],
                end_index=e[3], elevation_diff=e[4], average_grade=e[5],
                distance_m=e[6] or 0,
            )
            for e in efforts
        ]
        segments = dedup_segments(segments)
        if len(segments) < 3:
            continue

        try:
            raw = json.loads(cached[0])
            streams = {s["type"]: s["data"] for s in raw}
            time_array = streams.get("time", [])

            tile_samples, _ = streams_to_tile_data(streams)
            if not tile_samples:
                continue

            detections = run_detector(tile_samples, geo_freq_map, use_bridge_preprocessing)
            m, mi, ex, seg_records = match_detections_to_segments(
                segments, detections, time_array
            )

            result.total_matched += m
            result.total_missed += mi
            result.total_extras += ex
            result.rides_scored += 1

            # Accumulate size bucket stats
            for rec in seg_records:
                elev_diff = rec["elevation_diff"]
                for bname, bmin, bmax in SIZE_BUCKETS:
                    if bmin <= elev_diff < bmax:
                        result.bucket_stats[bname]["total"] += 1
                        if rec["result"] == "matched":
                            result.bucket_stats[bname]["matched"] += 1
                        break

            if verbose:
                p, r, f1 = compute_metrics(m, mi, ex)
                label = (name or str(aid))[:40]
                print(f"    [{idx+1}/{len(rows)}] {label:40s}  "
                      f"segs={len(segments):2d}  det={len(detections):2d}  "
                      f"m={m} mi={mi} x={ex} F1={f1:.2f}")
            elif (idx + 1) % 25 == 0 or idx == len(rows) - 1:
                p_run, r_run, f1_run = compute_metrics(
                    result.total_matched, result.total_missed, result.total_extras
                )
                print(f"    [{idx+1}/{len(rows)}] scored={result.rides_scored}  "
                      f"m={result.total_matched} mi={result.total_missed} "
                      f"x={result.total_extras}  "
                      f"P={p_run:.3f} R={r_run:.3f} F1={f1_run:.3f}")

        except Exception as exc:
            result.errors += 1
            if result.errors <= 3:
                print(f"    [{idx+1}] {aid} ERROR: {exc}")

    result.elapsed_s = time.time() - t0
    result.precision, result.recall, result.f1 = compute_metrics(
        result.total_matched, result.total_missed, result.total_extras
    )
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="2nd Geography Validation: evaluate canonical_v2 across geographies"
    )
    parser.add_argument("--db", default=str(GOLDEN_DB), help="Golden corpus DB path")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print per-ride details")
    parser.add_argument("--output", "-o", type=str, default="",
                        help="Save full results to JSON file")
    args = parser.parse_args()

    db_path = Path(args.db)
    conn = sqlite3.connect(str(db_path))

    # -------------------------------------------------------------------
    # Discover available geographies with scorable rides + cached streams
    # -------------------------------------------------------------------
    geo_rows = conn.execute("""
        SELECT
            COALESCE(r.geography, 'Unknown') as geo,
            COUNT(DISTINCT r.activity_id) as scorable_cached
        FROM rides r
        JOIN strava_segment_efforts s ON r.activity_id = s.activity_id
        JOIN activity_streams a ON r.activity_id = a.activity_id
        WHERE s.is_climb = 1
              AND s.elevation_diff >= ?
              AND s.average_grade >= ?
        GROUP BY r.geography
        HAVING COUNT(DISTINCT r.activity_id) >= ?
        ORDER BY scorable_cached DESC
    """, (MIN_CLIMB_VERT_M, MIN_CLIMB_GRADE_PCT, MIN_RIDES_PER_GEO)).fetchall()

    geographies = [(g, c) for g, c in geo_rows if g and g not in ("Unknown", "Other")]
    if not geographies:
        print("ERROR: No geographies with >= {} scorable cached rides found.".format(
            MIN_RIDES_PER_GEO))
        sys.exit(1)

    print("=" * 90)
    print("2ND GEOGRAPHY VALIDATION")
    print("=" * 90)
    print(f"Algorithm: canonical_v2 on tile_samples (full resolution)")
    print(f"Filters: segment_elev >= {MIN_CLIMB_VERT_M}m, "
          f"grade >= {MIN_CLIMB_GRADE_PCT}%, "
          f"detect_vert >= {MIN_DETECT_VERT_M}m")
    print(f"Overlap threshold: {OVERLAP_THRESHOLD}")
    print(f"Bridge preprocessing: enabled (matches production pipeline)")
    print()

    print("Available geographies:")
    for geo, count in geographies:
        print(f"  {geo:<16s}  {count:>4d} scorable rides with cached streams")
    print()

    # -------------------------------------------------------------------
    # Load frequency map
    # -------------------------------------------------------------------
    frequency_map = load_frequency_map(db_path)
    if frequency_map:
        print(f"Loaded frequency map: {len(frequency_map)} tiles")
    else:
        print("No frequency map found — H12 heuristic neutral for all geographies")
    print()

    # -------------------------------------------------------------------
    # Score each geography (all WITHOUT frequency map for clean comparison)
    # -------------------------------------------------------------------
    results: List[GeoResult] = []

    for geo, count in geographies:
        print(f"--- {geo} ({count} candidate rides) ---")
        result = score_geography(
            conn, geo, frequency_map, verbose=args.verbose,
            force_no_freq=True, use_bridge_preprocessing=True,
        )
        results.append(result)
        print(f"  => {geo}: scored={result.rides_scored}  "
              f"M={result.total_matched} Mi={result.total_missed} X={result.total_extras}  "
              f"P={result.precision:.3f} R={result.recall:.3f} F1={result.f1:.3f}  "
              f"({result.elapsed_s:.0f}s)")
        if result.errors:
            print(f"     ({result.errors} errors)")
        print()

    # -------------------------------------------------------------------
    # Also run SEPA WITH frequency map to measure H12 impact
    # -------------------------------------------------------------------
    sepa_with_freq = None
    if frequency_map:
        print("--- SEPA (with frequency prior — measures H12 impact) ---")
        sepa_with_freq = score_geography(
            conn, "SEPA", frequency_map, verbose=False,
            force_no_freq=False, use_bridge_preprocessing=True,
        )
        print(f"  => SEPA (w/freq): scored={sepa_with_freq.rides_scored}  "
              f"P={sepa_with_freq.precision:.3f} R={sepa_with_freq.recall:.3f} "
              f"F1={sepa_with_freq.f1:.3f}")
        print()

    # -------------------------------------------------------------------
    # Find SEPA clean result for delta comparison
    # -------------------------------------------------------------------
    sepa_result = next((r for r in results if r.geography == "SEPA"), None)
    sepa_f1 = sepa_result.f1 if sepa_result else 0.777

    # -------------------------------------------------------------------
    # Summary table — all geographies on equal footing (no frequency prior)
    # -------------------------------------------------------------------
    print("=" * 90)
    print("GEOGRAPHY VALIDATION RESULTS (all without frequency prior — clean comparison)")
    print("=" * 90)
    print()

    header = (f"{'Geography':<16s} {'Rides':>5s} {'Match':>5s} {'Miss':>5s} "
              f"{'Extra':>5s}   {'P':>6s} {'R':>6s} {'F1':>6s}  {'vs SEPA':>8s}")
    print(header)
    print("-" * len(header))

    for r in sorted(results, key=lambda x: x.rides_scored, reverse=True):
        delta = r.f1 - sepa_f1
        delta_str = f"{delta:+.3f}" if r.geography != "SEPA" else "baseline"
        print(f"{r.geography:<16s} {r.rides_scored:>5d} {r.total_matched:>5d} "
              f"{r.total_missed:>5d} {r.total_extras:>5d}   "
              f"{r.precision:>6.3f} {r.recall:>6.3f} {r.f1:>6.3f}  {delta_str:>8s}")

    # Show H12 frequency prior impact on SEPA
    if sepa_with_freq and sepa_result:
        df1 = sepa_with_freq.f1 - sepa_result.f1
        print()
        print(f"H12 frequency prior impact on SEPA: F1 {df1:+.3f} "
              f"(w/freq={sepa_with_freq.f1:.3f}, w/o={sepa_result.f1:.3f})")

    # -------------------------------------------------------------------
    # Extras per ride
    # -------------------------------------------------------------------
    print()
    print("EXTRAS PER RIDE:")
    header2 = f"{'Geography':<16s} {'Rides':>5s} {'Extras':>6s} {'Avg/Ride':>9s}"
    print(header2)
    print("-" * len(header2))
    for r in sorted(results, key=lambda x: x.rides_scored, reverse=True):
        avg_extras = r.total_extras / r.rides_scored if r.rides_scored else 0
        print(f"{r.geography:<16s} {r.rides_scored:>5d} {r.total_extras:>6d} "
              f"{avg_extras:>9.1f}")

    # -------------------------------------------------------------------
    # Recall by climb size bucket
    # -------------------------------------------------------------------
    print()
    print("RECALL BY CLIMB SIZE:")
    bucket_names = [b[0] for b in SIZE_BUCKETS]
    header3 = f"{'Geography':<16s}  " + "  ".join(f"{bn:>14s}" for bn in bucket_names)
    print(header3)
    print("-" * len(header3))

    for r in sorted(results, key=lambda x: x.rides_scored, reverse=True):
        cells = []
        for bname in bucket_names:
            bs = r.bucket_stats.get(bname, {"matched": 0, "total": 0})
            total = bs["total"]
            matched = bs["matched"]
            if total > 0:
                recall = matched / total
                cells.append(f"{recall:.2f} ({matched}/{total})")
            else:
                cells.append(f"{'---':>14s}")
        row_str = f"{r.geography:<16s}  " + "  ".join(f"{c:>14s}" for c in cells)
        print(row_str)

    # -------------------------------------------------------------------
    # Pass/fail criteria
    # -------------------------------------------------------------------
    print()
    print("=" * 90)
    print("PASS CRITERIA CHECK")
    print("=" * 90)

    all_pass = True

    # Criterion 1: F1 within 0.10 of SEPA for geographies with >=20 rides
    print()
    print("1) F1 within 0.10 of SEPA for geographies with >=20 rides:")
    for r in results:
        if r.rides_scored >= 20:
            delta = abs(r.f1 - sepa_f1)
            ok = delta <= 0.10
            status = "PASS" if ok else "FAIL"
            if not ok:
                all_pass = False
            print(f"   {r.geography:<16s}  F1={r.f1:.3f}  delta={delta:.3f}  [{status}]")

    # Criterion 2: No geography with recall below 0.60
    print()
    print("2) No geography with recall below 0.60:")
    for r in results:
        ok = r.recall >= 0.60
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False
        print(f"   {r.geography:<16s}  R={r.recall:.3f}  [{status}]")

    # Criterion 3: Recall for Large+ climbs >= 0.70 everywhere
    print()
    print("3) Recall for Large+ climbs (>=100m) >= 0.70 everywhere:")
    for r in results:
        large_matched = 0
        large_total = 0
        for bname in ("Large(100-250)", "Major(250+)"):
            bs = r.bucket_stats.get(bname, {"matched": 0, "total": 0})
            large_matched += bs["matched"]
            large_total += bs["total"]
        if large_total > 0:
            large_recall = large_matched / large_total
            ok = large_recall >= 0.70
            status = "PASS" if ok else "FAIL"
            if not ok:
                all_pass = False
            print(f"   {r.geography:<16s}  Large+ R={large_recall:.3f} ({large_matched}/{large_total})  [{status}]")
        else:
            print(f"   {r.geography:<16s}  Large+ R=N/A (no large climbs)  [SKIP]")

    print()
    if all_pass:
        print("OVERALL: ALL CRITERIA PASSED")
    else:
        print("OVERALL: SOME CRITERIA FAILED")
    print("=" * 90)

    # -------------------------------------------------------------------
    # Save results to JSON
    # -------------------------------------------------------------------
    if args.output:
        output = {
            "reference": {
                "sepa_holdout_baseline": {"P": 0.759, "R": 0.796, "F1": 0.777, "rides": 131},
            },
            "config": {
                "algorithm": "canonical_v2",
                "min_climb_vert_m": MIN_CLIMB_VERT_M,
                "min_climb_grade_pct": MIN_CLIMB_GRADE_PCT,
                "min_detect_vert_m": MIN_DETECT_VERT_M,
                "overlap_threshold": OVERLAP_THRESHOLD,
                "frequency_map_policy": "SEPA only",
                "frequency_map_tiles": len(frequency_map) if frequency_map else 0,
            },
            "results": [],
        }
        for r in results:
            output["results"].append({
                "geography": r.geography,
                "rides_scored": r.rides_scored,
                "errors": r.errors,
                "total_matched": r.total_matched,
                "total_missed": r.total_missed,
                "total_extras": r.total_extras,
                "precision": round(r.precision, 4),
                "recall": round(r.recall, 4),
                "f1": round(r.f1, 4),
                "elapsed_s": round(r.elapsed_s, 1),
                "bucket_stats": r.bucket_stats,
                "f1_delta_vs_sepa": round(r.f1 - sepa_f1, 4),
            })
        Path(args.output).write_text(json.dumps(output, indent=2))
        print(f"\nFull results saved to {args.output}")

    conn.close()


if __name__ == "__main__":
    main()
