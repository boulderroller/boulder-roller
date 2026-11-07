#!/usr/bin/env python3
"""
Run full climb detection comparison across the golden corpus.

For each scorable ride:
1. Load cached streams from golden_corpus.db
2. Run detector(s) on the ride data
3. Match detections against deduped Strava segment efforts
4. Store every match, miss, and extra with full detail

Results stored in detection_runs + detection_results tables for
offline querying, categorization, and visual inspection.

Usage:
    python tools/corpus/run_full_comparison.py                    # All rides, canonical_v2 only
    python tools/corpus/run_full_comparison.py --algorithms all   # All three detectors
    python tools/corpus/run_full_comparison.py --limit 50         # First 50 rides
    python tools/corpus/run_full_comparison.py --algorithms canonical_v2+templates  # Detector + GPS template matching
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from uuid import uuid4

REPO_ROOT = Path(__file__).parent.parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.patterns.climb import detect_climbs_with_rust
from app.services.patterns.template_matching import (
    SegmentTemplate,
    TemplateMatch,
    match_ride_against_templates,
    prepare_template,
)
from app.services.tile_service import TileService

from holdout_reference_quality import (
    quarantine_repeated_segment_spam,
    quarantined_segment_count,
)

GOLDEN_DB = Path(__file__).parent / "golden_corpus.db"
MIN_CLIMB_VERT_M = 25.0
MIN_CLIMB_GRADE_PCT = 2.0
MIN_DETECT_VERT_M = 20.0
OVERLAP_THRESHOLD = 0.30


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


def dedup_segments(segments: List[Segment]) -> List[Segment]:
    groups: List[List[Segment]] = []
    for seg in sorted(segments, key=lambda s: s.start_index):
        placed = False
        for group in groups:
            for existing in group:
                overlap = max(0, min(seg.end_index, existing.end_index) - max(seg.start_index, existing.start_index))
                shorter = min(max(1, seg.end_index - seg.start_index), max(1, existing.end_index - existing.start_index))
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


def run_detector(algo: str, tile_runs: list, tile_samples: list,
                 frequency_map: Optional[Dict[str, int]] = None) -> List[Detection]:
    kwargs = {"user_weight_kg": 75.0}
    if algo == "canonical_v2":
        kwargs["algorithm"] = "canonical_v2"
        kwargs["persistence_candidate_samples"] = tile_samples
        if frequency_map is not None:
            kwargs["frequency_map"] = frequency_map
    elif algo == "persistence":
        kwargs["algorithm"] = "persistence"
        kwargs["persistence_candidate_samples"] = tile_samples
    elif algo == "momentum_auto":
        kwargs["algorithm"] = "momentum"
        kwargs["terrain"] = "auto"
    elif algo == "canonical":
        kwargs["algorithm"] = "canonical"
    else:
        kwargs["algorithm"] = algo

    # Use tile_samples (1:1 with raw) instead of tile_runs (7x coarser)
    # for better gradient resolution on short climbs
    climbs = detect_climbs_with_rust(tile_samples, **kwargs)

    return [
        Detection(
            start_s=c.start_time_offset_s,
            end_s=c.end_time_offset_s,
            vert_m=c.vert_m,
            grade_pct=c.avg_gradient_pct or 0,
            distance_m=c.distance_m or 0,
            mode=getattr(c, "detector_mode", "") or algo,
        )
        for c in climbs
        if c.vert_m >= MIN_DETECT_VERT_M
    ]


def load_segment_templates(conn: sqlite3.Connection) -> List[SegmentTemplate]:
    """Load prepared segment templates from golden_corpus.db."""
    rows = conn.execute("""
        SELECT segment_id, segment_name, expected_vert_m, expected_grade_pct,
               expected_distance_m, polyline_json
        FROM segment_templates
    """).fetchall()

    templates = []
    for r in rows:
        try:
            polyline = json.loads(r[5])
            polyline = [(p[0], p[1]) for p in polyline]
        except (json.JSONDecodeError, IndexError, TypeError):
            continue
        tmpl = SegmentTemplate(
            template_id=r[0],
            name=r[1],
            polyline=polyline,
            expected_vert_m=r[2] or 0.0,
            expected_grade_pct=r[3] or 0.0,
            expected_distance_m=r[4] or 0.0,
        )
        prepare_template(tmpl)
        templates.append(tmpl)
    return templates


def run_template_matching(
    streams: Dict,
    templates: List[SegmentTemplate],
) -> List[Detection]:
    """
    Run GPS template matching against the ride streams.

    Returns a list of Detection objects compatible with the standard
    match_and_record() pipeline.
    """
    latlng_raw = streams.get("latlng", [])
    time_array = streams.get("time", [])
    altitude = streams.get("altitude", [])

    if not latlng_raw or not time_array:
        return []

    # Build ride_latlng, ride_times, ride_elevations — filtering invalid GPS
    ride_latlng: List[Tuple[float, float]] = []
    ride_times: List[int] = []
    ride_elevations: List[Optional[float]] = []

    for i in range(len(latlng_raw)):
        ll = latlng_raw[i] if i < len(latlng_raw) else None
        if not ll or len(ll) < 2:
            continue
        lat, lon = ll[0], ll[1]
        if lat == 0.0 and lon == 0.0:
            continue
        if abs(lat) > 90 or abs(lon) > 180:
            continue
        ride_latlng.append((lat, lon))
        ride_times.append(time_array[i] if i < len(time_array) else 0)
        ride_elevations.append(altitude[i] if i < len(altitude) else None)

    if len(ride_latlng) < 10:
        return []

    matches = match_ride_against_templates(
        ride_latlng=ride_latlng,
        ride_times=ride_times,
        templates=templates,
        corridor_width_m=50.0,
        min_coverage=0.60,
        ride_elevations=ride_elevations,
    )

    return [
        Detection(
            start_s=m.start_time_s,
            end_s=m.end_time_s,
            vert_m=m.actual_vert_m if m.actual_vert_m > 0 else m.expected_vert_m,
            grade_pct=m.expected_grade_pct,
            distance_m=0.0,  # Not directly available from template match
            mode="template_match",
        )
        for m in matches
        if m.actual_vert_m >= MIN_DETECT_VERT_M or m.expected_vert_m >= MIN_DETECT_VERT_M
    ]


def merge_detections(
    detector_dets: List[Detection],
    template_dets: List[Detection],
) -> List[Detection]:
    """
    Merge detector detections with template-matched detections.

    If a template match overlaps an existing detector detection (by time),
    keep the detector's version. Template matches only add truly new detections
    that the detector missed.
    """
    merged = list(detector_dets)
    for tmpl_det in template_dets:
        overlaps_existing = False
        for existing in detector_dets:
            ovl = max(0, min(tmpl_det.end_s, existing.end_s) - max(tmpl_det.start_s, existing.start_s))
            shorter = min(
                max(1, tmpl_det.end_s - tmpl_det.start_s),
                max(1, existing.end_s - existing.start_s),
            )
            if ovl / shorter >= OVERLAP_THRESHOLD:
                overlaps_existing = True
                break
        if not overlaps_existing:
            merged.append(tmpl_det)
    return sorted(merged, key=lambda d: d.start_s)


def match_and_record(
    segments: List[Segment],
    detections: List[Detection],
    time_array: List[int],
) -> List[dict]:
    """Match detections to segments, return detailed records."""
    # Convert segment indices to times
    for seg in segments:
        seg.start_time_s = time_array[seg.start_index] if seg.start_index < len(time_array) else 0
        seg.end_time_s = time_array[seg.end_index] if seg.end_index < len(time_array) else 0

    records = []
    used_detections = set()

    # For each segment, find best matching detection
    for seg in segments:
        best_idx = None
        best_overlap = 0.0

        for idx, det in enumerate(detections):
            if idx in used_detections:
                continue
            ovl = max(0, min(seg.end_time_s, det.end_s) - max(seg.start_time_s, det.start_s))
            shorter = min(max(1, seg.end_time_s - seg.start_time_s), max(1, det.end_s - det.start_s))
            ratio = ovl / shorter
            if ratio >= OVERLAP_THRESHOLD and ratio > best_overlap:
                best_idx = idx
                best_overlap = ratio

        if best_idx is not None:
            det = detections[best_idx]
            used_detections.add(best_idx)
            records.append({
                "result_type": "matched",
                "segment_id": seg.segment_id,
                "segment_name": seg.segment_name,
                "seg_start_s": seg.start_time_s,
                "seg_end_s": seg.end_time_s,
                "seg_elev_diff": seg.elevation_diff,
                "seg_avg_grade": seg.average_grade,
                "seg_distance_m": seg.distance_m,
                "det_start_s": det.start_s,
                "det_end_s": det.end_s,
                "det_vert_m": det.vert_m,
                "det_grade_pct": det.grade_pct,
                "det_distance_m": det.distance_m,
                "det_mode": det.mode,
                "overlap_ratio": round(best_overlap, 3),
                "boundary_start_diff_s": det.start_s - seg.start_time_s,
                "boundary_end_diff_s": det.end_s - seg.end_time_s,
            })
        else:
            records.append({
                "result_type": "missed",
                "segment_id": seg.segment_id,
                "segment_name": seg.segment_name,
                "seg_start_s": seg.start_time_s,
                "seg_end_s": seg.end_time_s,
                "seg_elev_diff": seg.elevation_diff,
                "seg_avg_grade": seg.average_grade,
                "seg_distance_m": seg.distance_m,
            })

    # Record extras (detections with no segment match)
    for idx, det in enumerate(detections):
        if idx not in used_detections:
            records.append({
                "result_type": "extra",
                "det_start_s": det.start_s,
                "det_end_s": det.end_s,
                "det_vert_m": det.vert_m,
                "det_grade_pct": det.grade_pct,
                "det_distance_m": det.distance_m,
                "det_mode": det.mode,
            })

    return records


def main():
    parser = argparse.ArgumentParser(description="Run full comparison across golden corpus")
    parser.add_argument("--db", default=str(GOLDEN_DB))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--algorithms", type=str, default="canonical_v2",
                        help="Comma-separated: canonical_v2,momentum_auto,persistence,"
                             "canonical_v2+templates,all")
    args = parser.parse_args()

    algos = args.algorithms.split(",")
    if "all" in algos:
        algos = ["canonical_v2", "momentum_auto", "persistence"]

    conn = sqlite3.connect(args.db)

    # Load segment templates if any algorithm uses +templates
    segment_templates: Optional[List[SegmentTemplate]] = None
    for algo in algos:
        if "+templates" in algo:
            segment_templates = load_segment_templates(conn)
            print(f"Loaded {len(segment_templates)} segment templates for GPS template matching")
            if not segment_templates:
                print("  WARNING: No templates found. Run build_segment_templates.py first.")
            break

    # Load climb frequency map for H12 Bayesian prior (if table exists)
    frequency_map: Optional[Dict[str, int]] = None
    try:
        freq_rows = conn.execute(
            "SELECT h3_tile, detection_count FROM climb_tile_frequency"
        ).fetchall()
        if freq_rows:
            frequency_map = {r[0]: r[1] for r in freq_rows}
            print(f"Loaded climb frequency map: {len(frequency_map)} tiles")
    except sqlite3.OperationalError:
        pass  # Table doesn't exist yet
    # Fallback: try separate frequency DB (useful when main DB is locked)
    if frequency_map is None:
        freq_db_path = Path(args.db).parent / "golden_corpus_freq.db"
        if freq_db_path.exists():
            try:
                freq_conn = sqlite3.connect(str(freq_db_path), timeout=5)
                freq_rows = freq_conn.execute(
                    "SELECT h3_tile, detection_count FROM climb_tile_frequency"
                ).fetchall()
                if freq_rows:
                    frequency_map = {r[0]: r[1] for r in freq_rows}
                    print(f"Loaded climb frequency map from {freq_db_path.name}: {len(frequency_map)} tiles")
                freq_conn.close()
            except (sqlite3.OperationalError, sqlite3.DatabaseError):
                pass
    if frequency_map is None:
        print("No climb frequency map found — H12 heuristic will be neutral")

    # Get scorable rides with cached streams
    rows = conn.execute("""
        SELECT DISTINCT r.activity_id, r.name, r.elevation_gain_m
        FROM rides r
        JOIN strava_segment_efforts s ON r.activity_id = s.activity_id
        JOIN activity_streams a ON r.activity_id = a.activity_id
        WHERE s.is_climb = 1 AND s.elevation_diff >= ? AND s.average_grade >= ?
        GROUP BY r.activity_id
        HAVING COUNT(s.id) >= 3
        ORDER BY r.start_date ASC
    """, (MIN_CLIMB_VERT_M, MIN_CLIMB_GRADE_PCT)).fetchall()

    if args.limit > 0:
        rows = rows[:args.limit]

    print(f"Scoring {len(rows)} rides with algorithms: {algos}")
    print(f"Filters: segment_elev >= {MIN_CLIMB_VERT_M}m, grade >= {MIN_CLIMB_GRADE_PCT}%, detect_vert >= {MIN_DETECT_VERT_M}m\n")

    for algo in algos:
        run_id = f"{algo}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:6]}"
        print(f"=== {algo} (run_id: {run_id}) ===")

        total_matched = 0
        total_missed = 0
        total_extras = 0
        scored = 0
        errors = 0
        total_quarantined_references = 0
        quarantine_by_reason: Counter[str] = Counter()
        all_records = []

        for idx, (aid, name, elev) in enumerate(rows):
            # Load cached streams
            cached = conn.execute(
                "SELECT streams_json FROM activity_streams WHERE activity_id = ?", (aid,)
            ).fetchone()
            if not cached:
                continue

            # Load segments
            efforts = conn.execute("""
                SELECT segment_id, segment_name, start_index, end_index,
                       elevation_diff, average_grade, distance_m
                FROM strava_segment_efforts
                WHERE activity_id = ? AND is_climb = 1
                      AND elevation_diff >= ? AND average_grade >= ?
                ORDER BY start_index
            """, (aid, MIN_CLIMB_VERT_M, MIN_CLIMB_GRADE_PCT)).fetchall()

            segments = [
                Segment(segment_id=e[0], segment_name=e[1], start_index=e[2],
                        end_index=e[3], elevation_diff=e[4], average_grade=e[5],
                        distance_m=e[6] or 0)
                for e in efforts
            ]
            segments = dedup_segments(segments)
            if len(segments) < 3:
                continue
            segments, quarantined_groups = quarantine_repeated_segment_spam(segments)
            if quarantined_groups:
                total_quarantined_references += quarantined_segment_count(quarantined_groups)
                for group in quarantined_groups:
                    quarantine_by_reason[group.reason] += group.count
            if len(segments) < 3:
                continue

            try:
                raw = json.loads(cached[0])
                streams = {s["type"]: s["data"] for s in raw}
                time_array = streams.get("time", [])

                tile_samples, tile_runs = streams_to_tile_data(streams)
                if not tile_samples:
                    continue

                # Determine the base detector algorithm and whether to merge templates
                if "+templates" in algo:
                    base_algo = algo.replace("+templates", "")
                    use_templates = True
                else:
                    base_algo = algo
                    use_templates = False

                detections = run_detector(base_algo, tile_runs, tile_samples,
                                         frequency_map=frequency_map)

                # Merge GPS template matches if enabled
                if use_templates and segment_templates:
                    template_dets = run_template_matching(streams, segment_templates)
                    detections = merge_detections(detections, template_dets)

                records = match_and_record(segments, detections, time_array)

                matched = sum(1 for r in records if r["result_type"] == "matched")
                missed = sum(1 for r in records if r["result_type"] == "missed")
                extras = sum(1 for r in records if r["result_type"] == "extra")

                total_matched += matched
                total_missed += missed
                total_extras += extras
                scored += 1

                # Tag records with activity_id and run_id
                for r in records:
                    r["run_id"] = run_id
                    r["activity_id"] = aid
                all_records.extend(records)

                if (idx + 1) % 50 == 0 or idx == len(rows) - 1:
                    te = total_matched + total_missed
                    td = total_matched + total_extras
                    p = total_matched / td if td else 1
                    r_val = total_matched / te if te else 1
                    f1 = 2 * p * r_val / (p + r_val) if (p + r_val) else 0
                    print(f"  [{idx+1}/{len(rows)}] scored={scored} "
                          f"matched={total_matched} missed={total_missed} extras={total_extras} "
                          f"P={p:.3f} R={r_val:.3f} F1={f1:.3f}")

            except Exception as exc:
                errors += 1
                if errors <= 5:
                    print(f"  [{idx+1}] {aid} ERROR: {exc}")

        # Store run summary
        te = total_matched + total_missed
        td = total_matched + total_extras
        precision = total_matched / td if td else 1
        recall = total_matched / te if te else 1
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0

        conn.execute("""
            INSERT OR REPLACE INTO detection_runs
            (run_id, algorithm, min_detect_vert, min_seg_elev, min_seg_grade,
             rides_scored, total_matched, total_missed, total_extras,
             precision, recall, f1, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (run_id, algo, MIN_DETECT_VERT_M, MIN_CLIMB_VERT_M, MIN_CLIMB_GRADE_PCT,
              scored, total_matched, total_missed, total_extras,
              round(precision, 4), round(recall, 4), round(f1, 4),
              datetime.now(timezone.utc).isoformat()))

        # Store detailed results
        for r in all_records:
            conn.execute("""
                INSERT INTO detection_results
                (run_id, activity_id, result_type,
                 segment_id, segment_name, seg_start_s, seg_end_s,
                 seg_elev_diff, seg_avg_grade, seg_distance_m,
                 det_start_s, det_end_s, det_vert_m, det_grade_pct,
                 det_distance_m, det_mode, overlap_ratio,
                 boundary_start_diff_s, boundary_end_diff_s)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                r.get("run_id"), r.get("activity_id"), r["result_type"],
                r.get("segment_id"), r.get("segment_name"),
                r.get("seg_start_s"), r.get("seg_end_s"),
                r.get("seg_elev_diff"), r.get("seg_avg_grade"), r.get("seg_distance_m"),
                r.get("det_start_s"), r.get("det_end_s"),
                r.get("det_vert_m"), r.get("det_grade_pct"),
                r.get("det_distance_m"), r.get("det_mode"),
                r.get("overlap_ratio"),
                r.get("boundary_start_diff_s"), r.get("boundary_end_diff_s"),
            ))

        conn.commit()

        print(f"\n  FINAL: {algo}")
        print(f"    Rides scored: {scored} (errors: {errors})")
        print(f"    Matched: {total_matched}  Missed: {total_missed}  Extras: {total_extras}")
        print(f"    Precision: {precision:.3f}  Recall: {recall:.3f}  F1: {f1:.3f}")
        print(f"    Quarantined refs: {total_quarantined_references}  {dict(quarantine_by_reason)}")
        print(f"    Run ID: {run_id}")
        print()

    # Print comparison if multiple algorithms
    if len(algos) > 1:
        print("=" * 80)
        print("COMPARISON")
        print("=" * 80)
        for row in conn.execute(
            "SELECT algorithm, rides_scored, total_matched, total_missed, total_extras, precision, recall, f1 "
            "FROM detection_runs ORDER BY created_at DESC LIMIT ?", (len(algos),)
        ).fetchall():
            print(f"  {row[0]:20s}  scored={row[1]:3d}  m={row[2]:4d}  miss={row[3]:4d}  "
                  f"x={row[4]:4d}  P={row[5]:.3f}  R={row[6]:.3f}  F1={row[7]:.3f}")


if __name__ == "__main__":
    main()
