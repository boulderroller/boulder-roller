#!/usr/bin/env python3
"""
Temporal split evaluation: detector + template matching on full-resolution data.

Uses 691 GPS templates from 2012-2021 history (segment_templates_temporal).
Evaluates on 65 rides from 2022+ against Strava segment ground truth.

Reports:
- Detector-only P/R/F1 (canonical_v2 on tile_samples)
- Detector + templates combined P/R/F1

Usage:
    python tools/corpus/run_temporal_eval.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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

GOLDEN_DB = Path(__file__).parent / "golden_corpus.db"
MIN_CLIMB_VERT_M = 25.0
MIN_CLIMB_GRADE_PCT = 2.0
MIN_DETECT_VERT_M = 20.0
OVERLAP_THRESHOLD = 0.30


# ---------------------------------------------------------------------------
# Data classes (mirrored from run_full_comparison.py)
# ---------------------------------------------------------------------------

class Segment:
    __slots__ = ("segment_id", "segment_name", "start_index", "end_index",
                 "elevation_diff", "average_grade", "distance_m",
                 "start_time_s", "end_time_s")

    def __init__(self, segment_id, segment_name, start_index, end_index,
                 elevation_diff, average_grade, distance_m):
        self.segment_id = segment_id
        self.segment_name = segment_name
        self.start_index = start_index
        self.end_index = end_index
        self.elevation_diff = elevation_diff
        self.average_grade = average_grade
        self.distance_m = distance_m
        self.start_time_s = 0
        self.end_time_s = 0


class Detection:
    __slots__ = ("start_s", "end_s", "vert_m", "grade_pct", "distance_m", "mode")

    def __init__(self, start_s, end_s, vert_m, grade_pct, distance_m, mode):
        self.start_s = start_s
        self.end_s = end_s
        self.vert_m = vert_m
        self.grade_pct = grade_pct
        self.distance_m = distance_m
        self.mode = mode


# ---------------------------------------------------------------------------
# Helpers (from run_full_comparison.py)
# ---------------------------------------------------------------------------

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


def run_detector(tile_samples: list, frequency_map: Optional[Dict[str, int]]) -> List[Detection]:
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


def run_template_matching(
    streams: Dict,
    templates: List[SegmentTemplate],
) -> List[Detection]:
    latlng_raw = streams.get("latlng", [])
    time_array = streams.get("time", [])
    altitude = streams.get("altitude", [])

    if not latlng_raw or not time_array:
        return []

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
            distance_m=0.0,
            mode="template_match",
        )
        for m in matches
        if m.actual_vert_m >= MIN_DETECT_VERT_M or m.expected_vert_m >= MIN_DETECT_VERT_M
    ]


def merge_detections(
    detector_dets: List[Detection],
    template_dets: List[Detection],
) -> List[Detection]:
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


def match_detections_to_segments(
    segments: List[Segment],
    detections: List[Detection],
    time_array: List[int],
) -> Tuple[int, int, int]:
    """Match detections to segments. Returns (matched, missed, extras)."""
    for seg in segments:
        seg.start_time_s = time_array[seg.start_index] if seg.start_index < len(time_array) else 0
        seg.end_time_s = time_array[seg.end_index] if seg.end_index < len(time_array) else 0

    used_detections = set()
    matched = 0
    missed = 0

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
            used_detections.add(best_idx)
            matched += 1
        else:
            missed += 1

    extras = len(detections) - len(used_detections)
    return matched, missed, extras


def load_temporal_templates(conn: sqlite3.Connection) -> List[SegmentTemplate]:
    """Load templates from the segment_templates_temporal table."""
    rows = conn.execute("""
        SELECT segment_id, segment_name, expected_vert_m, expected_grade_pct,
               polyline_json
        FROM segment_templates_temporal
    """).fetchall()

    templates = []
    for r in rows:
        try:
            polyline = json.loads(r[4])
            polyline = [(p[0], p[1]) for p in polyline]
        except (json.JSONDecodeError, IndexError, TypeError):
            continue
        tmpl = SegmentTemplate(
            template_id=r[0],
            name=r[1],
            polyline=polyline,
            expected_vert_m=r[2] or 0.0,
            expected_grade_pct=r[3] or 0.0,
            expected_distance_m=0.0,
        )
        prepare_template(tmpl)
        templates.append(tmpl)
    return templates


def load_frequency_map(db_path: Path) -> Optional[Dict[str, int]]:
    """Load climb frequency map for H12 heuristic."""
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
        if freq_rows:
            return {r[0]: r[1] for r in freq_rows}
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        pass

    return None


def main():
    conn = sqlite3.connect(str(GOLDEN_DB))

    # Load temporal templates
    templates = load_temporal_templates(conn)
    print(f"Loaded {len(templates)} temporal templates (2012-2021 history)")

    # Load frequency map
    frequency_map = load_frequency_map(GOLDEN_DB)
    if frequency_map:
        print(f"Loaded frequency map: {len(frequency_map)} tiles")
    else:
        print("No frequency map found — H12 heuristic will be neutral")

    # Get eval rides (2022+)
    eval_rows = conn.execute("""
        SELECT DISTINCT r.activity_id, r.name, r.elevation_gain_m
        FROM rides r
        JOIN strava_segment_efforts s ON r.activity_id = s.activity_id
        JOIN activity_streams a ON r.activity_id = a.activity_id
        WHERE r.start_date >= '2022-01-01'
              AND s.is_climb = 1 AND s.elevation_diff >= ? AND s.average_grade >= ?
        GROUP BY r.activity_id
        HAVING COUNT(s.id) >= 3
        ORDER BY r.start_date ASC
    """, (MIN_CLIMB_VERT_M, MIN_CLIMB_GRADE_PCT)).fetchall()

    print(f"Eval rides (2022+): {len(eval_rows)}")
    print(f"Filters: segment_elev >= {MIN_CLIMB_VERT_M}m, grade >= {MIN_CLIMB_GRADE_PCT}%, detect_vert >= {MIN_DETECT_VERT_M}m")
    print()

    # Accumulators: detector only
    det_matched = 0
    det_missed = 0
    det_extras = 0

    # Accumulators: detector + templates
    comb_matched = 0
    comb_missed = 0
    comb_extras = 0

    scored = 0
    errors = 0
    t0 = time.time()

    for idx, (aid, name, elev) in enumerate(eval_rows):
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
            Segment(segment_id=e[0], segment_name=e[1], start_index=e[2],
                    end_index=e[3], elevation_diff=e[4], average_grade=e[5],
                    distance_m=e[6] or 0)
            for e in efforts
        ]
        segments = dedup_segments(segments)
        if len(segments) < 3:
            continue

        try:
            raw = json.loads(cached[0])
            streams = {s["type"]: s["data"] for s in raw}
            time_array = streams.get("time", [])

            tile_samples, tile_runs = streams_to_tile_data(streams)
            if not tile_samples:
                continue

            # Detector only (on tile_samples — full resolution)
            detector_dets = run_detector(tile_samples, frequency_map)

            # Make fresh segments for each scoring pass (start/end times get set)
            segments_det = [
                Segment(s.segment_id, s.segment_name, s.start_index, s.end_index,
                        s.elevation_diff, s.average_grade, s.distance_m)
                for s in segments
            ]
            m, mi, ex = match_detections_to_segments(segments_det, detector_dets, time_array)
            det_matched += m
            det_missed += mi
            det_extras += ex

            # Template matching
            template_dets = run_template_matching(streams, templates)

            # Combined: merge detector + template detections
            combined_dets = merge_detections(detector_dets, template_dets)

            segments_comb = [
                Segment(s.segment_id, s.segment_name, s.start_index, s.end_index,
                        s.elevation_diff, s.average_grade, s.distance_m)
                for s in segments
            ]
            m2, mi2, ex2 = match_detections_to_segments(segments_comb, combined_dets, time_array)
            comb_matched += m2
            comb_missed += mi2
            comb_extras += ex2

            scored += 1

            if (idx + 1) % 10 == 0 or idx == len(eval_rows) - 1:
                # Detector-only running stats
                te_d = det_matched + det_missed
                td_d = det_matched + det_extras
                p_d = det_matched / td_d if td_d else 1
                r_d = det_matched / te_d if te_d else 1
                f1_d = 2 * p_d * r_d / (p_d + r_d) if (p_d + r_d) else 0

                # Combined running stats
                te_c = comb_matched + comb_missed
                td_c = comb_matched + comb_extras
                p_c = comb_matched / td_c if td_c else 1
                r_c = comb_matched / te_c if te_c else 1
                f1_c = 2 * p_c * r_c / (p_c + r_c) if (p_c + r_c) else 0

                elapsed = time.time() - t0
                print(f"  [{idx+1}/{len(eval_rows)}] scored={scored} "
                      f"det: m={det_matched} mi={det_missed} x={det_extras} P={p_d:.3f} R={r_d:.3f} F1={f1_d:.3f} | "
                      f"comb: m={comb_matched} mi={comb_missed} x={comb_extras} P={p_c:.3f} R={r_c:.3f} F1={f1_c:.3f} "
                      f"({elapsed:.0f}s)")

        except Exception as exc:
            errors += 1
            if errors <= 5:
                print(f"  [{idx+1}] {aid} ERROR: {exc}")

    elapsed = time.time() - t0

    # Final stats
    print()
    print("=" * 80)
    print("TEMPORAL SPLIT EVALUATION — FULL RESOLUTION (tile_samples)")
    print("=" * 80)
    print(f"Eval rides scored: {scored} (errors: {errors})")
    print(f"Templates: {len(templates)} (from 2012-2021 history)")
    print(f"Frequency map: {'yes' if frequency_map else 'no'} ({len(frequency_map) if frequency_map else 0} tiles)")
    print(f"Time: {elapsed:.1f}s")
    print()

    # Detector only
    te_d = det_matched + det_missed
    td_d = det_matched + det_extras
    p_d = det_matched / td_d if td_d else 1
    r_d = det_matched / te_d if te_d else 1
    f1_d = 2 * p_d * r_d / (p_d + r_d) if (p_d + r_d) else 0
    print(f"DETECTOR ONLY (canonical_v2, tile_samples):")
    print(f"  Matched: {det_matched}  Missed: {det_missed}  Extras: {det_extras}")
    print(f"  Precision: {p_d:.1%}  Recall: {r_d:.1%}  F1: {f1_d:.3f}")
    print()

    # Combined
    te_c = comb_matched + comb_missed
    td_c = comb_matched + comb_extras
    p_c = comb_matched / td_c if td_c else 1
    r_c = comb_matched / te_c if te_c else 1
    f1_c = 2 * p_c * r_c / (p_c + r_c) if (p_c + r_c) else 0
    print(f"DETECTOR + TEMPLATES (canonical_v2 + 691 temporal templates):")
    print(f"  Matched: {comb_matched}  Missed: {comb_missed}  Extras: {comb_extras}")
    print(f"  Precision: {p_c:.1%}  Recall: {r_c:.1%}  F1: {f1_c:.3f}")
    print()

    # Template-only contribution
    template_recoveries = comb_matched - det_matched
    template_extra_noise = comb_extras - det_extras
    print(f"TEMPLATE CONTRIBUTION:")
    print(f"  Recoveries (misses → matches): {template_recoveries}")
    print(f"  Additional extras (noise): {template_extra_noise}")
    print()

    # Comparison with tile_runs baselines
    print("=" * 80)
    print("COMPARISON WITH tile_runs BASELINES")
    print("=" * 80)
    print(f"{'Metric':<45s} {'tile_runs':>10s} {'tile_samples':>12s} {'Delta':>10s}")
    print("-" * 80)

    tile_runs_det_p = 0.805
    tile_runs_det_r = 0.713
    tile_runs_det_f1 = 0.756

    print(f"{'Full corpus detector P':<45s} {tile_runs_det_p:>10.1%} {'(see step 2)':>12s} {'':>10s}")
    print(f"{'Full corpus detector R':<45s} {tile_runs_det_r:>10.1%} {'(see step 2)':>12s} {'':>10s}")
    print(f"{'Full corpus detector F1':<45s} {tile_runs_det_f1:>10.3f} {'(see step 2)':>12s} {'':>10s}")
    print()

    tile_runs_eval_p = 0.773
    tile_runs_eval_r = 0.874
    tile_runs_eval_f1 = 0.821

    print(f"{'Temporal det+tmpl P':<45s} {tile_runs_eval_p:>10.1%} {p_c:>12.1%} {p_c - tile_runs_eval_p:>+10.1%}")
    print(f"{'Temporal det+tmpl R':<45s} {tile_runs_eval_r:>10.1%} {r_c:>12.1%} {r_c - tile_runs_eval_r:>+10.1%}")
    print(f"{'Temporal det+tmpl F1':<45s} {tile_runs_eval_f1:>10.3f} {f1_c:>12.3f} {f1_c - tile_runs_eval_f1:>+10.3f}")
    print()

    print(f"{'Temporal det-only P':<45s} {'':>10s} {p_d:>12.1%}")
    print(f"{'Temporal det-only R':<45s} {'':>10s} {r_d:>12.1%}")
    print(f"{'Temporal det-only F1':<45s} {'':>10s} {f1_d:>12.3f}")
    print("=" * 80)


if __name__ == "__main__":
    main()
