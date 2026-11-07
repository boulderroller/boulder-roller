#!/usr/bin/env python3
"""
Score climb detection against Strava segment ground truth.

For each ride in the golden corpus:
1. Fetch activity streams from Strava API
2. Run canonical_v2 (and optionally other detectors) on the streams
3. Compare detected climbs against Strava segment efforts
4. Produce per-ride and aggregate scoring

Matching logic:
  A detected climb "matches" a Strava segment if their time ranges overlap
  by >= 40% of the shorter segment's duration. Each Strava segment can match
  at most one detected climb, and vice versa (greedy best-match).

Metrics:
  - matched: Strava segments our detector found
  - missed: Strava segments our detector missed
  - extras: detected climbs with no Strava segment match
  - precision: matched / (matched + extras)
  - recall: matched / (matched + missed)
  - f1: harmonic mean of precision and recall

Usage:
    export SUPABASE_URL=...
    export SUPABASE_SERVICE_KEY=...
    export STRAVA_CLIENT_ID=...
    export STRAVA_CLIENT_SECRET=...

    # Score a small batch (fetches streams on demand)
    python tools/corpus/score_golden_corpus.py --limit 20

    # Score all rides with cached streams
    python tools/corpus/score_golden_corpus.py --resume

    # Score specific rides
    python tools/corpus/score_golden_corpus.py --activity-ids 17679127204,17736068811
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import httpx
except ImportError:
    print("httpx required: pip install httpx")
    sys.exit(1)

REPO_ROOT = Path(__file__).parent.parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.patterns.climb import detect_climbs_with_rust
from app.services.tile_service import TileService

GOLDEN_DB = Path(__file__).parent / "golden_corpus.db"
MIN_CLIMB_VERT_M = 25.0   # Minimum vert to consider a Strava segment a "climb"
MIN_CLIMB_GRADE_PCT = 2.0  # Minimum average grade to consider a segment a real climb
MIN_DETECT_VERT_M = 20.0  # Minimum vert to consider a detected climb "shown"
OVERLAP_THRESHOLD = 0.30  # Minimum overlap ratio for a match
REQUEST_DELAY_S = 1.5


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"Missing required environment variable: {name}", file=sys.stderr)
        sys.exit(2)
    return value


def get_strava_token() -> str:
    """Get a fresh Strava access token."""
    supabase_url = require_env("SUPABASE_URL")
    supabase_key = require_env("SUPABASE_SERVICE_KEY")
    strava_client_id = require_env("STRAVA_CLIENT_ID")
    strava_client_secret = require_env("STRAVA_CLIENT_SECRET")

    supabase_headers = {"apikey": supabase_key}
    if not supabase_key.startswith("sb_secret_"):
        supabase_headers["Authorization"] = f"Bearer {supabase_key}"
    resp = httpx.get(
        f"{supabase_url}/rest/v1/strava_connections",
        params={"is_active": "eq.true", "select": "refresh_token"},
        headers=supabase_headers,
        timeout=10,
    )
    token_resp = httpx.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": strava_client_id,
            "client_secret": strava_client_secret,
            "grant_type": "refresh_token",
            "refresh_token": resp.json()[0]["refresh_token"],
        },
        timeout=10,
    )
    return token_resp.json()["access_token"]


def fetch_streams(activity_id: int, access_token: str) -> Optional[Dict]:
    """Fetch activity streams from Strava."""
    resp = httpx.get(
        f"https://www.strava.com/api/v3/activities/{activity_id}/streams",
        headers={"Authorization": f"Bearer {access_token}"},
        params={
            "keys": "time,latlng,altitude,watts,heartrate,cadence",
            "key_type": "time",
        },
        timeout=30,
    )
    if resp.status_code == 429:
        return None
    if resp.status_code != 200:
        return None
    return {s["type"]: s["data"] for s in resp.json()}


def streams_to_tile_data(streams: Dict) -> Tuple[list, list]:
    """Convert Strava streams to tile samples and tile runs."""
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
            "tile_id": s.tile_id,
            "t": int(s.t),
            "lat": s.lat,
            "lon": s.lon,
            "elevation_m": s.elevation_m,
            "power_w": s.power_w,
            "hr_bpm": s.hr_bpm,
            "speed_mps": s.speed_mps,
        }
        for s in ts.get_tile_sequence(points, resolution=10, start_time=0)
    ]
    tile_runs = ts.get_tile_run_sequence(points, resolution=10, start_time=0)
    return tile_samples, tile_runs or tile_samples


@dataclass
class SegmentEffort:
    """A Strava segment effort (ground truth)."""
    segment_id: int
    segment_name: str
    start_index: int
    end_index: int
    elevation_diff: float
    average_grade: float
    climb_category: int
    elapsed_time_s: int
    distance_m: float

    @property
    def approx_start_s(self) -> int:
        return self.start_index

    @property
    def approx_end_s(self) -> int:
        return self.end_index


@dataclass
class DetectedClimb:
    """A climb detected by our engine."""
    start_s: int
    end_s: int
    vert_m: float
    grade_pct: float
    distance_m: float
    detector_mode: str


def overlap_ratio(a_start: int, a_end: int, b_start: int, b_end: int) -> float:
    """Overlap as fraction of the shorter segment's duration."""
    overlap = max(0, min(a_end, b_end) - max(a_start, b_start))
    shorter = min(max(1, a_end - a_start), max(1, b_end - b_start))
    return overlap / shorter


def dedup_segments(segments: List[SegmentEffort]) -> List[SegmentEffort]:
    """Group overlapping segments, keep the one with highest elevation from each group."""
    groups: List[List[SegmentEffort]] = []
    for seg in sorted(segments, key=lambda s: s.start_index):
        placed = False
        for group in groups:
            for existing in group:
                overlap = max(0, min(seg.end_index, existing.end_index) - max(seg.start_index, existing.start_index))
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


def match_climbs_to_segments(
    detected: List[DetectedClimb],
    segments: List[SegmentEffort],
    streams: Dict,
) -> Tuple[int, int, int, List[dict]]:
    """
    Match detected climbs against Strava segment efforts.

    Strava segments use start_index/end_index (sample indices), while our
    detector uses time offsets. We use the streams time array to convert.

    Segments are deduplicated first — overlapping segments covering the same
    hill are grouped and only the highest-elevation representative is kept.

    Returns: (matched, missed, extras, match_details)
    """
    segments = dedup_segments(segments)
    time_array = streams.get("time", [])

    # Convert segment indices to time offsets
    seg_times = []
    for seg in segments:
        start_t = time_array[seg.start_index] if seg.start_index < len(time_array) else 0
        end_t = time_array[seg.end_index] if seg.end_index < len(time_array) else 0
        seg_times.append((start_t, end_t, seg))

    # Greedy matching: for each segment, find best overlapping detection
    used_detections = set()
    matched = 0
    match_details = []

    for start_t, end_t, seg in seg_times:
        best_idx = None
        best_overlap = 0.0

        for idx, det in enumerate(detected):
            if idx in used_detections:
                continue
            ovl = overlap_ratio(start_t, end_t, det.start_s, det.end_s)
            if ovl >= OVERLAP_THRESHOLD and ovl > best_overlap:
                best_idx = idx
                best_overlap = ovl

        if best_idx is not None:
            matched += 1
            used_detections.add(best_idx)
            det = detected[best_idx]
            match_details.append({
                "segment": seg.segment_name,
                "seg_elev": seg.elevation_diff,
                "seg_grade": seg.average_grade,
                "seg_time": f"{start_t}-{end_t}",
                "det_time": f"{det.start_s}-{det.end_s}",
                "det_vert": det.vert_m,
                "det_grade": det.grade_pct,
                "overlap": round(best_overlap, 2),
                "status": "matched",
            })
        else:
            match_details.append({
                "segment": seg.segment_name,
                "seg_elev": seg.elevation_diff,
                "seg_grade": seg.average_grade,
                "seg_time": f"{start_t}-{end_t}",
                "status": "missed",
            })

    extras = len(detected) - len(used_detections)
    missed = len(segments) - matched

    # Add extra detections to details
    for idx, det in enumerate(detected):
        if idx not in used_detections:
            match_details.append({
                "det_time": f"{det.start_s}-{det.end_s}",
                "det_vert": det.vert_m,
                "det_grade": det.grade_pct,
                "det_mode": det.detector_mode,
                "status": "extra",
            })

    return matched, missed, extras, match_details


def score_ride(
    activity_id: str,
    conn: sqlite3.Connection,
    access_token: str,
    algorithms: List[str],
) -> Optional[Dict]:
    """Score a single ride across all algorithms."""
    # Get Strava segment efforts for this ride
    efforts = conn.execute(
        """SELECT segment_id, segment_name, start_index, end_index,
                  elevation_diff, average_grade, climb_category,
                  elapsed_time_s, distance_m
           FROM strava_segment_efforts
           WHERE activity_id = ? AND is_climb = 1
                 AND elevation_diff >= ? AND average_grade >= ?""",
        (activity_id, MIN_CLIMB_VERT_M, MIN_CLIMB_GRADE_PCT),
    ).fetchall()

    if not efforts:
        return None

    segments = [
        SegmentEffort(
            segment_id=e[0], segment_name=e[1], start_index=e[2], end_index=e[3],
            elevation_diff=e[4], average_grade=e[5], climb_category=e[6],
            elapsed_time_s=e[7] or 0, distance_m=e[8] or 0,
        )
        for e in efforts
    ]

    # Try cached streams first, then fetch from API
    cached = conn.execute(
        "SELECT streams_json FROM activity_streams WHERE activity_id = ?",
        (activity_id,),
    ).fetchone()
    if cached:
        raw = json.loads(cached[0])
        streams = {s["type"]: s["data"] for s in raw}
    else:
        streams = fetch_streams(int(activity_id), access_token)
        if streams is None:
            return None

    tile_samples, tile_runs = streams_to_tile_data(streams)
    if not tile_samples:
        return None

    results = {"activity_id": activity_id, "strava_climb_segments": len(segments)}

    for algo in algorithms:
        try:
            kwargs = {"user_weight_kg": 75.0}
            if algo == "canonical_v2":
                kwargs["algorithm"] = "canonical_v2"
                kwargs["persistence_candidate_samples"] = tile_samples
            elif algo == "persistence":
                kwargs["algorithm"] = "persistence"
                kwargs["persistence_candidate_samples"] = tile_samples
            elif algo.startswith("momentum"):
                kwargs["algorithm"] = "momentum"
                kwargs["terrain"] = algo.split("_", 1)[1] if "_" in algo else "auto"
            else:
                kwargs["algorithm"] = algo

            climbs = detect_climbs_with_rust(tile_runs, **kwargs)

            detected = [
                DetectedClimb(
                    start_s=c.start_time_offset_s,
                    end_s=c.end_time_offset_s,
                    vert_m=c.vert_m,
                    grade_pct=c.avg_gradient_pct or 0,
                    distance_m=c.distance_m or 0,
                    detector_mode=getattr(c, "detector_mode", "") or algo,
                )
                for c in climbs
                if c.vert_m >= MIN_DETECT_VERT_M
            ]

            matched, missed, extras, details = match_climbs_to_segments(
                detected, segments, streams,
            )

            precision = matched / (matched + extras) if (matched + extras) > 0 else 1.0
            recall = matched / (matched + missed) if (matched + missed) > 0 else 1.0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

            results[algo] = {
                "shown": len(detected),
                "matched": matched,
                "missed": missed,
                "extras": extras,
                "precision": round(precision, 3),
                "recall": round(recall, 3),
                "f1": round(f1, 3),
            }
        except Exception as exc:
            results[algo] = {"error": str(exc)}

    return results


def main():
    parser = argparse.ArgumentParser(description="Score detector against Strava segments")
    parser.add_argument("--db", default=str(GOLDEN_DB), help="Golden corpus DB path")
    parser.add_argument("--limit", type=int, default=0, help="Max rides to score")
    parser.add_argument("--min-segments", type=int, default=3, help="Min climb segments per ride")
    parser.add_argument("--min-elev", type=float, default=MIN_CLIMB_VERT_M, help="Min segment elevation (m)")
    parser.add_argument("--min-grade", type=float, default=MIN_CLIMB_GRADE_PCT, help="Min segment avg grade (%)")
    parser.add_argument("--activity-ids", type=str, default="", help="Comma-separated activity IDs")
    parser.add_argument("--algorithms", type=str,
                        default="canonical_v2,momentum_auto,persistence",
                        help="Comma-separated algorithms to test")
    parser.add_argument("--output", "-o", type=str, default="", help="Save results JSON")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    algorithms = [a.strip() for a in args.algorithms.split(",")]

    print("Refreshing Strava token...")
    access_token = get_strava_token()

    # Select rides to score
    if args.activity_ids:
        activity_ids = [a.strip() for a in args.activity_ids.split(",")]
    else:
        rows = conn.execute(
            """SELECT r.activity_id, r.name, r.elevation_gain_m, COUNT(s.id) as seg_count
               FROM rides r
               JOIN strava_segment_efforts s ON r.activity_id = s.activity_id AND s.is_climb = 1
               WHERE s.elevation_diff >= ? AND s.average_grade >= ?
               GROUP BY r.activity_id
               HAVING seg_count >= ?
               ORDER BY r.elevation_gain_m DESC""",
            (args.min_elev, args.min_grade, args.min_segments),
        ).fetchall()
        activity_ids = [r[0] for r in rows]
        print(f"Rides with >= {args.min_segments} climb segments: {len(activity_ids)}")

    if args.limit > 0:
        activity_ids = activity_ids[:args.limit]

    print(f"Scoring {len(activity_ids)} rides with algorithms: {algorithms}")
    print(f"Stream fetches needed: {len(activity_ids)} (est. {len(activity_ids) * REQUEST_DELAY_S / 60:.0f} min)\n")

    # Aggregate totals
    totals = {algo: {"shown": 0, "matched": 0, "missed": 0, "extras": 0} for algo in algorithms}
    all_results = []
    scored = 0
    skipped = 0
    rate_count = 0
    rate_window_start = time.time()

    for idx, aid in enumerate(activity_ids):
        # Rate limiting
        elapsed = time.time() - rate_window_start
        if elapsed >= 900:
            rate_count = 0
            rate_window_start = time.time()
        if rate_count >= 95:
            wait = 900 - elapsed + 5
            print(f"  Rate limit. Waiting {wait:.0f}s...")
            time.sleep(wait)
            rate_count = 0
            rate_window_start = time.time()

        ride_name = conn.execute(
            "SELECT name FROM rides WHERE activity_id = ?", (aid,)
        ).fetchone()
        ride_label = (ride_name[0] or aid)[:35] if ride_name else aid

        result = score_ride(aid, conn, access_token, algorithms)
        rate_count += 1

        if result is None:
            skipped += 1
            if args.verbose:
                print(f"  [{idx+1}/{len(activity_ids)}] {ride_label:35s}  (skipped)")
            time.sleep(REQUEST_DELAY_S)
            continue

        scored += 1
        all_results.append(result)

        # Accumulate totals
        line_parts = [f"  [{idx+1}/{len(activity_ids)}] {ride_label:35s}  segs={result['strava_climb_segments']:2d}"]
        for algo in algorithms:
            r = result.get(algo, {})
            if "error" in r:
                line_parts.append(f"  {algo}:ERR")
                continue
            for key in totals[algo]:
                totals[algo][key] += r.get(key, 0)
            line_parts.append(
                f"  {algo}: m={r['matched']}/{r['matched']+r['missed']} "
                f"x={r['extras']} f1={r['f1']:.2f}"
            )

        print("".join(line_parts))
        time.sleep(REQUEST_DELAY_S)

    # Print summary
    print(f"\n{'='*80}")
    print(f"GOLDEN CORPUS SCORING SUMMARY")
    print(f"{'='*80}")
    print(f"Rides scored: {scored}  (skipped: {skipped})")
    print()

    for algo in algorithms:
        t = totals[algo]
        total_expected = t["matched"] + t["missed"]
        total_detected = t["matched"] + t["extras"]
        precision = t["matched"] / total_detected if total_detected > 0 else 1.0
        recall = t["matched"] / total_expected if total_expected > 0 else 1.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        print(f"  {algo:20s}  matched={t['matched']:4d}  missed={t['missed']:4d}  "
              f"extras={t['extras']:4d}  precision={precision:.3f}  recall={recall:.3f}  F1={f1:.3f}")

    print(f"{'='*80}")

    if args.output:
        output = {
            "scored_rides": scored,
            "skipped": skipped,
            "algorithms": {
                algo: {
                    **totals[algo],
                    "precision": round(
                        totals[algo]["matched"] / max(1, totals[algo]["matched"] + totals[algo]["extras"]), 3
                    ),
                    "recall": round(
                        totals[algo]["matched"] / max(1, totals[algo]["matched"] + totals[algo]["missed"]), 3
                    ),
                }
                for algo in algorithms
            },
            "per_ride": all_results,
        }
        Path(args.output).write_text(json.dumps(output, indent=2))
        print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
