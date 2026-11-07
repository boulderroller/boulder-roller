#!/usr/bin/env python3
"""
Generate interactive HTML ride reviews showing climb detection vs ground truth.

For each ride, produces a self-contained HTML file with:
  1. Leaflet map: GPS track + color-coded ground truth and detection overlays
  2. Elevation profile chart: full ride elevation with segment highlighting
  3. Results table: all segments and detections with match status
  4. Navigation: prev/next ride links, algorithm selector

Usage:
    # Generate review for a specific ride
    python tools/corpus/generate_ride_review.py --activity-id 17679127204

    # Generate reviews for top 20 rides by segment count
    python tools/corpus/generate_ride_review.py --top 20

    # Generate for rides with most misses (most interesting to review)
    python tools/corpus/generate_ride_review.py --most-missed 20

    # Use a specific detection run
    python tools/corpus/generate_ride_review.py --run-id canonical_v2_20260320_123456_abc123

    # Generate all scorable rides
    python tools/corpus/generate_ride_review.py --all
"""

from __future__ import annotations

import argparse
import html
import json
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

GOLDEN_DB = Path(__file__).parent / "golden_corpus.db"
REVIEWS_DIR = Path(__file__).parent / "reviews"

MIN_CLIMB_VERT_M = 25.0
MIN_CLIMB_GRADE_PCT = 2.0
OVERLAP_THRESHOLD = 0.35


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

@dataclass
class RideInfo:
    activity_id: str
    name: str
    start_date: str
    distance_m: float
    elevation_gain_m: float


@dataclass
class SegmentEffort:
    segment_name: str
    start_index: int
    end_index: int
    elevation_diff: float
    average_grade: float
    distance_m: float
    climb_category: int
    elapsed_time_s: int
    # Computed from time array
    start_time_s: int = 0
    end_time_s: int = 0


@dataclass
class DetectionResult:
    result_type: str  # matched, missed, extra
    # Segment fields (for matched/missed)
    segment_name: Optional[str] = None
    seg_start_s: Optional[int] = None
    seg_end_s: Optional[int] = None
    seg_elev_diff: Optional[float] = None
    seg_avg_grade: Optional[float] = None
    seg_distance_m: Optional[float] = None
    # Detection fields (for matched/extra)
    det_start_s: Optional[int] = None
    det_end_s: Optional[int] = None
    det_vert_m: Optional[float] = None
    det_grade_pct: Optional[float] = None
    det_distance_m: Optional[float] = None
    det_mode: Optional[str] = None
    overlap_ratio: Optional[float] = None
    boundary_start_diff_s: Optional[int] = None
    boundary_end_diff_s: Optional[int] = None


def load_ride_info(conn: sqlite3.Connection, activity_id: str) -> Optional[RideInfo]:
    row = conn.execute(
        "SELECT activity_id, name, start_date, distance_m, elevation_gain_m "
        "FROM rides WHERE activity_id = ?",
        (activity_id,),
    ).fetchone()
    if not row:
        return None
    return RideInfo(
        activity_id=row[0],
        name=row[1] or "Untitled",
        start_date=row[2] or "",
        distance_m=row[3] or 0,
        elevation_gain_m=row[4] or 0,
    )


def load_streams(conn: sqlite3.Connection, activity_id: str) -> Optional[Dict]:
    row = conn.execute(
        "SELECT streams_json FROM activity_streams WHERE activity_id = ?",
        (activity_id,),
    ).fetchone()
    if not row:
        return None
    raw = json.loads(row[0])
    return {s["type"]: s["data"] for s in raw}


def load_segments(conn: sqlite3.Connection, activity_id: str) -> List[SegmentEffort]:
    rows = conn.execute(
        """SELECT segment_name, start_index, end_index, elevation_diff,
                  average_grade, distance_m, climb_category, elapsed_time_s
           FROM strava_segment_efforts
           WHERE activity_id = ? AND is_climb = 1
                 AND elevation_diff >= ? AND average_grade >= ?
           ORDER BY start_index""",
        (activity_id, MIN_CLIMB_VERT_M, MIN_CLIMB_GRADE_PCT),
    ).fetchall()
    return [
        SegmentEffort(
            segment_name=r[0] or "Unnamed",
            start_index=r[1] or 0,
            end_index=r[2] or 0,
            elevation_diff=r[3] or 0,
            average_grade=r[4] or 0,
            distance_m=r[5] or 0,
            climb_category=r[6] or 0,
            elapsed_time_s=r[7] or 0,
        )
        for r in rows
    ]


def dedup_segments(segments: List[SegmentEffort]) -> List[SegmentEffort]:
    """Group overlapping segments, keep highest-elevation from each group."""
    groups: List[List[SegmentEffort]] = []
    for seg in sorted(segments, key=lambda s: s.start_index):
        placed = False
        for group in groups:
            for existing in group:
                overlap = max(
                    0,
                    min(seg.end_index, existing.end_index)
                    - max(seg.start_index, existing.start_index),
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


def get_latest_run_id(conn: sqlite3.Connection, algorithm: str = "canonical_v2") -> Optional[str]:
    """Get the most recent detection run for the given algorithm."""
    row = conn.execute(
        "SELECT run_id FROM detection_runs WHERE algorithm = ? ORDER BY created_at DESC LIMIT 1",
        (algorithm,),
    ).fetchone()
    return row[0] if row else None


def get_available_runs(conn: sqlite3.Connection) -> List[Tuple[str, str]]:
    """Get all available run_ids with their algorithms."""
    rows = conn.execute(
        "SELECT run_id, algorithm FROM detection_runs ORDER BY created_at DESC"
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def load_detection_results(
    conn: sqlite3.Connection, activity_id: str, run_id: str
) -> List[DetectionResult]:
    rows = conn.execute(
        """SELECT result_type, segment_name,
                  seg_start_s, seg_end_s, seg_elev_diff, seg_avg_grade, seg_distance_m,
                  det_start_s, det_end_s, det_vert_m, det_grade_pct, det_distance_m,
                  det_mode, overlap_ratio, boundary_start_diff_s, boundary_end_diff_s
           FROM detection_results
           WHERE activity_id = ? AND run_id = ?
           ORDER BY COALESCE(seg_start_s, det_start_s)""",
        (activity_id, run_id),
    ).fetchall()
    return [
        DetectionResult(
            result_type=r[0],
            segment_name=r[1],
            seg_start_s=r[2],
            seg_end_s=r[3],
            seg_elev_diff=r[4],
            seg_avg_grade=r[5],
            seg_distance_m=r[6],
            det_start_s=r[7],
            det_end_s=r[8],
            det_vert_m=r[9],
            det_grade_pct=r[10],
            det_distance_m=r[11],
            det_mode=r[12],
            overlap_ratio=r[13],
            boundary_start_diff_s=r[14],
            boundary_end_diff_s=r[15],
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Stream data processing
# ---------------------------------------------------------------------------


def extract_track_points(streams: Dict) -> List[Tuple[float, float]]:
    """Extract (lat, lon) pairs from streams."""
    latlng = streams.get("latlng", [])
    return [(pt[0], pt[1]) for pt in latlng if pt and len(pt) >= 2]


def extract_elevation_profile(streams: Dict) -> Tuple[List[int], List[float]]:
    """Extract (time[], elevation[]) from streams."""
    times = streams.get("time", [])
    altitudes = streams.get("altitude", [])
    if not times or not altitudes:
        return [], []
    n = min(len(times), len(altitudes))
    return times[:n], altitudes[:n]


def time_to_index(time_array: List[int], t: int) -> int:
    """Find the index in time_array closest to time t."""
    if not time_array:
        return 0
    best_idx = 0
    best_diff = abs(time_array[0] - t)
    for i, tv in enumerate(time_array):
        diff = abs(tv - t)
        if diff < best_diff:
            best_diff = diff
            best_idx = i
    return best_idx


def segment_latlng_slice(
    streams: Dict, start_idx: int, end_idx: int
) -> List[Tuple[float, float]]:
    """Get GPS points for a segment by sample index range."""
    latlng = streams.get("latlng", [])
    end_idx = min(end_idx, len(latlng) - 1)
    start_idx = max(0, start_idx)
    return [(pt[0], pt[1]) for pt in latlng[start_idx : end_idx + 1] if pt and len(pt) >= 2]


def time_range_to_latlng(
    streams: Dict, start_s: int, end_s: int
) -> List[Tuple[float, float]]:
    """Get GPS points for a time range."""
    times = streams.get("time", [])
    latlng = streams.get("latlng", [])
    if not times or not latlng:
        return []
    n = min(len(times), len(latlng))
    pts = []
    for i in range(n):
        if times[i] >= start_s and times[i] <= end_s:
            pt = latlng[i]
            if pt and len(pt) >= 2:
                pts.append((pt[0], pt[1]))
    return pts


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

def esc(s: str) -> str:
    """HTML-escape a string."""
    return html.escape(str(s))


def format_time(seconds: Optional[int]) -> str:
    """Format seconds as mm:ss or h:mm:ss."""
    if seconds is None:
        return "-"
    s = int(seconds)
    if s < 3600:
        return f"{s // 60}:{s % 60:02d}"
    return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def generate_ride_html(
    ride: RideInfo,
    streams: Dict,
    segments: List[SegmentEffort],
    results: List[DetectionResult],
    run_id: str,
    available_runs: List[Tuple[str, str]],
    prev_activity_id: Optional[str],
    next_activity_id: Optional[str],
    all_activity_ids: List[str],
) -> str:
    """Generate the full HTML for a single ride review."""

    time_array = streams.get("time", [])
    latlng = streams.get("latlng", [])
    altitudes = streams.get("altitude", [])

    # Convert segment indices to time offsets
    for seg in segments:
        seg.start_time_s = time_array[seg.start_index] if seg.start_index < len(time_array) else 0
        seg.end_time_s = time_array[seg.end_index] if seg.end_index < len(time_array) else 0

    # Build track points for map
    track_points = extract_track_points(streams)
    track_json = json.dumps(track_points)

    # Build elevation profile data
    elev_times, elev_values = extract_elevation_profile(streams)
    elev_times_json = json.dumps(elev_times)
    elev_values_json = json.dumps(elev_values)

    # Classify results
    matched_segs = [r for r in results if r.result_type == "matched"]
    missed_segs = [r for r in results if r.result_type == "missed"]
    extra_dets = [r for r in results if r.result_type == "extra"]

    total_expected = len(matched_segs) + len(missed_segs)
    total_detected = len(matched_segs) + len(extra_dets)
    precision = len(matched_segs) / total_detected if total_detected > 0 else 1.0
    recall = len(matched_segs) / total_expected if total_expected > 0 else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    # Build map overlay data for segments
    # Green = matched ground truth, Red = missed ground truth
    seg_overlays = []
    for r in results:
        if r.result_type in ("matched", "missed"):
            # Use detection results' seg_start_s/seg_end_s to find indices
            start_idx = time_to_index(time_array, r.seg_start_s) if r.seg_start_s is not None else 0
            end_idx = time_to_index(time_array, r.seg_end_s) if r.seg_end_s is not None else 0
            pts = segment_latlng_slice(streams, start_idx, end_idx)
            color = "#22c55e" if r.result_type == "matched" else "#ef4444"
            label = r.segment_name or "Reference Segment"
            seg_overlays.append({
                "points": pts,
                "color": color,
                "name": label,
                "type": "Reference Segment",
                "status": r.result_type,
                "elev": r.seg_elev_diff,
                "grade": r.seg_avg_grade,
                "time_range": f"{format_time(r.seg_start_s)} - {format_time(r.seg_end_s)}",
                "start_s": r.seg_start_s,
                "end_s": r.seg_end_s,
            })

    # Blue = matched detection, Orange = extra detection
    det_overlays = []
    for r in results:
        if r.result_type == "matched":
            pts = time_range_to_latlng(streams, r.det_start_s, r.det_end_s)
            det_overlays.append({
                "points": pts,
                "color": "#3b82f6",
                "name": "Detection (" + (r.det_mode or "unknown") + ")",
                "type": "Detection",
                "status": "matched",
                "vert": r.det_vert_m,
                "grade": r.det_grade_pct,
                "time_range": f"{format_time(r.det_start_s)} - {format_time(r.det_end_s)}",
                "overlap": r.overlap_ratio,
                "start_s": r.det_start_s,
                "end_s": r.det_end_s,
            })
        elif r.result_type == "extra":
            pts = time_range_to_latlng(streams, r.det_start_s, r.det_end_s)
            det_overlays.append({
                "points": pts,
                "color": "#f97316",
                "name": "Extra Detection (" + (r.det_mode or "unknown") + ")",
                "type": "Detection",
                "status": "extra",
                "vert": r.det_vert_m,
                "grade": r.det_grade_pct,
                "time_range": f"{format_time(r.det_start_s)} - {format_time(r.det_end_s)}",
                "start_s": r.det_start_s,
                "end_s": r.det_end_s,
            })

    seg_overlays_json = json.dumps(seg_overlays)
    det_overlays_json = json.dumps(det_overlays)

    # Build elevation profile highlight regions (time ranges for coloring)
    elev_highlights = []
    for r in results:
        if r.result_type == "matched":
            elev_highlights.append({
                "start_s": r.seg_start_s, "end_s": r.seg_end_s,
                "color": "rgba(34, 197, 94, 0.2)", "border": "#22c55e",
                "label": r.segment_name or "Ref",
            })
            elev_highlights.append({
                "start_s": r.det_start_s, "end_s": r.det_end_s,
                "color": "rgba(59, 130, 246, 0.2)", "border": "#3b82f6",
                "label": "Det",
            })
        elif r.result_type == "missed":
            elev_highlights.append({
                "start_s": r.seg_start_s, "end_s": r.seg_end_s,
                "color": "rgba(239, 68, 68, 0.2)", "border": "#ef4444",
                "label": r.segment_name or "Ref (missed)",
            })
        elif r.result_type == "extra":
            elev_highlights.append({
                "start_s": r.det_start_s, "end_s": r.det_end_s,
                "color": "rgba(249, 115, 22, 0.2)", "border": "#f97316",
                "label": "Extra det",
            })

    elev_highlights_json = json.dumps(elev_highlights)

    # Navigation links
    prev_link = f'<a href="{prev_activity_id}.html">&larr; Previous</a>' if prev_activity_id else '<span class="disabled">&larr; Previous</span>'
    next_link = f'<a href="{next_activity_id}.html">Next &rarr;</a>' if next_activity_id else '<span class="disabled">Next &rarr;</span>'

    # Algorithm selector options
    run_options = ""
    for rid, algo in available_runs:
        selected = ' selected' if rid == run_id else ''
        run_options += f'<option value="{esc(rid)}"{selected}>{esc(algo)} ({esc(rid[:20])}...)</option>\n'

    # Results table rows
    table_rows = ""

    # Reference segments (matched + missed)
    for r in results:
        if r.result_type == "matched":
            status_badge = '<span class="badge badge-match">Matched</span>'
            overlap_str = f"{r.overlap_ratio:.0%}" if r.overlap_ratio else "-"
            boundary_str = ""
            if r.boundary_start_diff_s is not None:
                boundary_str = f"start: {r.boundary_start_diff_s:+d}s, end: {r.boundary_end_diff_s:+d}s"
            table_rows += f"""<tr class="row-matched">
                <td>Reference</td>
                <td>{esc(r.segment_name or '-')}</td>
                <td>{r.seg_elev_diff:.0f}m</td>
                <td>{r.seg_avg_grade:.1f}%</td>
                <td>{format_time(r.seg_start_s)} - {format_time(r.seg_end_s)}</td>
                <td>{status_badge}</td>
                <td>{overlap_str}</td>
                <td>{esc(boundary_str)}</td>
            </tr>\n"""
            # Corresponding detection row
            table_rows += f"""<tr class="row-detection-matched">
                <td>Detection</td>
                <td>{esc(r.det_mode or '-')}</td>
                <td>{r.det_vert_m:.0f}m</td>
                <td>{r.det_grade_pct:.1f}%</td>
                <td>{format_time(r.det_start_s)} - {format_time(r.det_end_s)}</td>
                <td>{status_badge}</td>
                <td>{overlap_str}</td>
                <td>{esc(boundary_str)}</td>
            </tr>\n"""
        elif r.result_type == "missed":
            status_badge = '<span class="badge badge-miss">Missed</span>'
            table_rows += f"""<tr class="row-missed">
                <td>Reference</td>
                <td>{esc(r.segment_name or '-')}</td>
                <td>{r.seg_elev_diff:.0f}m</td>
                <td>{r.seg_avg_grade:.1f}%</td>
                <td>{format_time(r.seg_start_s)} - {format_time(r.seg_end_s)}</td>
                <td>{status_badge}</td>
                <td>-</td>
                <td>-</td>
            </tr>\n"""

    # Extra detections
    for r in results:
        if r.result_type == "extra":
            status_badge = '<span class="badge badge-extra">Extra</span>'
            table_rows += f"""<tr class="row-extra">
                <td>Detection</td>
                <td>{esc(r.det_mode or '-')}</td>
                <td>{r.det_vert_m:.0f}m</td>
                <td>{r.det_grade_pct:.1f}%</td>
                <td>{format_time(r.det_start_s)} - {format_time(r.det_end_s)}</td>
                <td>{status_badge}</td>
                <td>-</td>
                <td>-</td>
            </tr>\n"""

    # F1 color
    if f1 >= 0.8:
        f1_class = "f1-good"
    elif f1 >= 0.5:
        f1_class = "f1-ok"
    else:
        f1_class = "f1-bad"

    ride_date = ride.start_date[:10] if ride.start_date else "Unknown"
    ride_dist_km = ride.distance_m / 1000 if ride.distance_m else 0

    # All data injected into JS is JSON-serialized (safe against injection).
    # All text content displayed in HTML is escaped via esc().
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Ride Review: {esc(ride.name)} ({ride.activity_id})</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.0.1/dist/chartjs-plugin-annotation.min.js"></script>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        background: #0f172a; color: #e2e8f0;
        line-height: 1.5;
    }}
    .container {{ max-width: 1400px; margin: 0 auto; padding: 16px; }}

    /* Header */
    .header {{
        display: flex; justify-content: space-between; align-items: center;
        padding: 12px 0; border-bottom: 1px solid #334155; margin-bottom: 16px;
    }}
    .header h1 {{ font-size: 1.25rem; font-weight: 600; color: #f8fafc; }}
    .header .meta {{ font-size: 0.85rem; color: #94a3b8; }}
    .nav {{ display: flex; gap: 16px; align-items: center; }}
    .nav a {{ color: #60a5fa; text-decoration: none; font-size: 0.9rem; }}
    .nav a:hover {{ text-decoration: underline; }}
    .nav .disabled {{ color: #475569; font-size: 0.9rem; }}

    /* Summary bar */
    .summary {{
        display: flex; gap: 24px; padding: 12px 16px;
        background: #1e293b; border-radius: 8px; margin-bottom: 16px;
        flex-wrap: wrap; align-items: center;
    }}
    .stat {{ text-align: center; }}
    .stat .value {{ font-size: 1.4rem; font-weight: 700; color: #f8fafc; }}
    .stat .label {{ font-size: 0.75rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; }}
    .f1-good .value {{ color: #22c55e; }}
    .f1-ok .value {{ color: #eab308; }}
    .f1-bad .value {{ color: #ef4444; }}

    /* Algorithm selector */
    .algo-select {{
        margin-left: auto; display: flex; align-items: center; gap: 8px;
    }}
    .algo-select label {{ font-size: 0.8rem; color: #94a3b8; }}
    .algo-select select {{
        background: #334155; color: #e2e8f0; border: 1px solid #475569;
        border-radius: 4px; padding: 4px 8px; font-size: 0.8rem;
    }}

    /* Map */
    #map {{ width: 100%; height: 450px; border-radius: 8px; margin-bottom: 16px; }}

    /* Legend */
    .legend {{
        display: flex; gap: 16px; padding: 8px 16px;
        background: #1e293b; border-radius: 8px; margin-bottom: 16px;
        flex-wrap: wrap; font-size: 0.8rem;
    }}
    .legend-item {{ display: flex; align-items: center; gap: 6px; }}
    .legend-swatch {{
        width: 24px; height: 4px; border-radius: 2px; display: inline-block;
    }}

    /* Chart */
    .chart-container {{
        background: #1e293b; border-radius: 8px; padding: 16px;
        margin-bottom: 16px; height: 280px; position: relative;
    }}

    /* Table */
    .results-table {{
        width: 100%; border-collapse: collapse; font-size: 0.82rem;
        background: #1e293b; border-radius: 8px; overflow: hidden;
    }}
    .results-table th {{
        background: #334155; padding: 8px 12px; text-align: left;
        font-weight: 600; color: #cbd5e1; font-size: 0.75rem;
        text-transform: uppercase; letter-spacing: 0.05em;
    }}
    .results-table td {{ padding: 6px 12px; border-top: 1px solid #1e293b; }}
    .row-matched td {{ background: rgba(34, 197, 94, 0.05); }}
    .row-detection-matched td {{ background: rgba(59, 130, 246, 0.05); }}
    .row-missed td {{ background: rgba(239, 68, 68, 0.08); }}
    .row-extra td {{ background: rgba(249, 115, 22, 0.08); }}

    /* Badges */
    .badge {{
        display: inline-block; padding: 2px 8px; border-radius: 4px;
        font-size: 0.72rem; font-weight: 600; text-transform: uppercase;
    }}
    .badge-match {{ background: #166534; color: #bbf7d0; }}
    .badge-miss {{ background: #991b1b; color: #fecaca; }}
    .badge-extra {{ background: #9a3412; color: #fed7aa; }}

    /* Footer */
    .footer {{
        text-align: center; padding: 16px 0; margin-top: 16px;
        border-top: 1px solid #334155; font-size: 0.75rem; color: #64748b;
    }}

    /* Index link */
    .index-link {{ margin-bottom: 8px; }}
    .index-link a {{ color: #60a5fa; text-decoration: none; font-size: 0.85rem; }}
    .index-link a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<div class="container">
    <div class="index-link"><a href="index.html">&larr; Back to Index</a></div>

    <div class="header">
        <div>
            <h1>{esc(ride.name)}</h1>
            <div class="meta">{esc(ride_date)} &middot; {ride_dist_km:.1f} km &middot; {ride.elevation_gain_m:.0f}m gain &middot; ID: {ride.activity_id}</div>
        </div>
        <div class="nav">
            {prev_link}
            {next_link}
        </div>
    </div>

    <div class="summary">
        <div class="stat">
            <div class="value">{len(matched_segs)}</div>
            <div class="label">Matched</div>
        </div>
        <div class="stat">
            <div class="value">{len(missed_segs)}</div>
            <div class="label">Missed</div>
        </div>
        <div class="stat">
            <div class="value">{len(extra_dets)}</div>
            <div class="label">Extra</div>
        </div>
        <div class="stat">
            <div class="value">{precision:.0%}</div>
            <div class="label">Precision</div>
        </div>
        <div class="stat">
            <div class="value">{recall:.0%}</div>
            <div class="label">Recall</div>
        </div>
        <div class="stat {f1_class}">
            <div class="value">{f1:.2f}</div>
            <div class="label">F1</div>
        </div>
        <div class="algo-select">
            <label>Run:</label>
            <select id="runSelector" onchange="switchRun(this.value)">
                {run_options}
            </select>
        </div>
    </div>

    <div class="legend">
        <div class="legend-item"><span class="legend-swatch" style="background:#94a3b8"></span> GPS Track</div>
        <div class="legend-item"><span class="legend-swatch" style="background:#22c55e"></span> Reference (matched)</div>
        <div class="legend-item"><span class="legend-swatch" style="background:#ef4444"></span> Reference (missed)</div>
        <div class="legend-item"><span class="legend-swatch" style="background:#3b82f6"></span> Detection (matched)</div>
        <div class="legend-item"><span class="legend-swatch" style="background:#f97316"></span> Detection (extra)</div>
    </div>

    <div id="map"></div>

    <div class="chart-container">
        <canvas id="elevChart"></canvas>
    </div>

    <table class="results-table">
        <thead>
            <tr>
                <th>Type</th>
                <th>Name / Mode</th>
                <th>Elevation</th>
                <th>Grade</th>
                <th>Time Range</th>
                <th>Status</th>
                <th>Overlap</th>
                <th>Boundary Diff</th>
            </tr>
        </thead>
        <tbody>
            {table_rows}
        </tbody>
    </table>

    <div class="footer">
        Climb Detection Review &middot; Generated from detection run: {esc(run_id)}
    </div>
</div>

<script>
// All data below is JSON-serialized from trusted DB content.
// No user-supplied strings are injected without escaping.
(function() {{
    // ---- MAP ----
    var trackPoints = {track_json};
    var segOverlays = {seg_overlays_json};
    var detOverlays = {det_overlays_json};

    var mapEl = document.getElementById('map');
    if (trackPoints.length === 0) {{
        mapEl.textContent = 'No GPS data available';
        mapEl.style.cssText = 'padding:40px;text-align:center;color:#94a3b8';
    }} else {{
        var map = L.map('map');
        L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
            attribution: '&copy; CARTO',
            maxZoom: 19,
        }}).addTo(map);

        // Full track
        var trackLine = L.polyline(trackPoints, {{color: '#94a3b8', weight: 2, opacity: 0.6}}).addTo(map);
        map.fitBounds(trackLine.getBounds().pad(0.05));

        // Segment overlays (ground truth)
        segOverlays.forEach(function(seg) {{
            if (seg.points.length < 2) return;
            var line = L.polyline(seg.points, {{color: seg.color, weight: 5, opacity: 0.85}}).addTo(map);
            var statusLabel = seg.status === 'matched' ? 'Matched' : 'Missed';
            line.bindPopup(
                '<b>' + seg.name + '</b><br>' +
                'Type: ' + seg.type + '<br>' +
                'Status: <b>' + statusLabel + '</b><br>' +
                'Elevation: ' + (seg.elev ? seg.elev.toFixed(0) + 'm' : '-') + '<br>' +
                'Grade: ' + (seg.grade ? seg.grade.toFixed(1) + '%' : '-') + '<br>' +
                'Time: ' + seg.time_range
            );
            // Start marker
            var startPt = seg.points[0];
            L.circleMarker(startPt, {{radius: 5, color: seg.color, fillColor: seg.color, fillOpacity: 1}})
                .bindPopup('Start: ' + seg.name)
                .addTo(map);
        }});

        // Detection overlays
        detOverlays.forEach(function(det) {{
            if (det.points.length < 2) return;
            var line = L.polyline(det.points, {{color: det.color, weight: 5, opacity: 0.85, dashArray: '8 4'}}).addTo(map);
            var statusLabel = det.status === 'matched' ? 'Matched' : 'Extra';
            var popupText = '<b>' + det.name + '</b><br>' +
                'Status: <b>' + statusLabel + '</b><br>' +
                'Vert: ' + (det.vert ? det.vert.toFixed(0) + 'm' : '-') + '<br>' +
                'Grade: ' + (det.grade ? det.grade.toFixed(1) + '%' : '-') + '<br>' +
                'Time: ' + det.time_range;
            if (det.overlap) popupText += '<br>Overlap: ' + (det.overlap * 100).toFixed(0) + '%';
            line.bindPopup(popupText);
            var startPt = det.points[0];
            L.circleMarker(startPt, {{radius: 4, color: det.color, fillColor: det.color, fillOpacity: 1, weight: 1}})
                .bindPopup('Det start: ' + det.name)
                .addTo(map);
        }});
    }}

    // ---- ELEVATION PROFILE ----
    var elevTimes = {elev_times_json};
    var elevValues = {elev_values_json};
    var elevHighlights = {elev_highlights_json};

    if (elevTimes.length === 0) return;

    // Build annotation boxes for highlighted regions
    var annotations = {{}};
    elevHighlights.forEach(function(h, i) {{
        annotations['box' + i] = {{
            type: 'box',
            xMin: h.start_s,
            xMax: h.end_s,
            backgroundColor: h.color,
            borderColor: h.border,
            borderWidth: 1,
            label: {{
                display: true,
                content: h.label,
                position: 'start',
                color: '#e2e8f0',
                font: {{ size: 9, weight: 'normal' }},
                padding: 2,
            }}
        }};
    }});

    var ctx = document.getElementById('elevChart').getContext('2d');
    new Chart(ctx, {{
        type: 'line',
        data: {{
            labels: elevTimes,
            datasets: [{{
                label: 'Elevation (m)',
                data: elevValues,
                borderColor: '#94a3b8',
                borderWidth: 1.5,
                pointRadius: 0,
                fill: true,
                backgroundColor: 'rgba(148, 163, 184, 0.08)',
                tension: 0.1,
            }}]
        }},
        options: {{
            responsive: true,
            maintainAspectRatio: false,
            interaction: {{ mode: 'nearest', axis: 'x', intersect: false }},
            plugins: {{
                legend: {{ display: false }},
                annotation: {{ annotations: annotations }},
                tooltip: {{
                    callbacks: {{
                        title: function(items) {{
                            var s = items[0].parsed.x;
                            var m = Math.floor(s / 60);
                            var sec = s % 60;
                            return m + ':' + (sec < 10 ? '0' : '') + sec;
                        }},
                        label: function(item) {{
                            return item.parsed.y.toFixed(1) + ' m';
                        }}
                    }}
                }}
            }},
            scales: {{
                x: {{
                    type: 'linear',
                    title: {{ display: true, text: 'Time (seconds)', color: '#94a3b8' }},
                    ticks: {{
                        color: '#64748b',
                        callback: function(value) {{
                            var m = Math.floor(value / 60);
                            return m + 'min';
                        }},
                        maxTicksLimit: 20,
                    }},
                    grid: {{ color: 'rgba(100, 116, 139, 0.15)' }},
                }},
                y: {{
                    title: {{ display: true, text: 'Elevation (m)', color: '#94a3b8' }},
                    ticks: {{ color: '#64748b' }},
                    grid: {{ color: 'rgba(100, 116, 139, 0.15)' }},
                }}
            }}
        }}
    }});
}})();

function switchRun(runId) {{
    // Static files -- show regeneration note via DOM API (no raw HTML injection)
    var note = document.createElement('div');
    note.style.cssText = 'position:fixed;top:0;left:0;right:0;padding:8px;background:#1d4ed8;color:white;text-align:center;font-size:0.85rem;z-index:9999';
    note.textContent = 'To view run "' + runId + '", regenerate with: --run-id ' + runId;
    document.body.prepend(note);
}}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Index page generation
# ---------------------------------------------------------------------------

def generate_index_html(
    rides_data: List[dict],
    run_id: str,
) -> str:
    """Generate index.html linking to all ride reviews."""

    rows_html = ""
    for rd in rides_data:
        f1 = rd.get("f1", 0)
        if f1 >= 0.8:
            f1_class = "f1-good"
        elif f1 >= 0.5:
            f1_class = "f1-ok"
        else:
            f1_class = "f1-bad"

        rows_html += f"""<tr>
            <td><a href="{rd['activity_id']}.html">{esc(rd['name'])}</a></td>
            <td>{esc(rd['date'])}</td>
            <td>{rd['segments']}</td>
            <td>{rd['matched']}</td>
            <td>{rd['missed']}</td>
            <td>{rd['extras']}</td>
            <td>{rd['precision']:.0%}</td>
            <td>{rd['recall']:.0%}</td>
            <td class="{f1_class}">{rd['f1']:.2f}</td>
        </tr>\n"""

    total_matched = sum(r["matched"] for r in rides_data)
    total_missed = sum(r["missed"] for r in rides_data)
    total_extras = sum(r["extras"] for r in rides_data)
    total_expected = total_matched + total_missed
    total_detected = total_matched + total_extras
    agg_precision = total_matched / total_detected if total_detected > 0 else 1.0
    agg_recall = total_matched / total_expected if total_expected > 0 else 1.0
    agg_f1 = 2 * agg_precision * agg_recall / (agg_precision + agg_recall) if (agg_precision + agg_recall) > 0 else 0.0

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Climb Detection Review Index</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        background: #0f172a; color: #e2e8f0; line-height: 1.5;
    }}
    .container {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
    h1 {{ font-size: 1.4rem; margin-bottom: 8px; }}
    .subtitle {{ color: #94a3b8; font-size: 0.85rem; margin-bottom: 20px; }}
    .agg-summary {{
        display: flex; gap: 24px; padding: 12px 16px;
        background: #1e293b; border-radius: 8px; margin-bottom: 20px;
        flex-wrap: wrap;
    }}
    .stat {{ text-align: center; }}
    .stat .value {{ font-size: 1.3rem; font-weight: 700; color: #f8fafc; }}
    .stat .label {{ font-size: 0.72rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; }}
    table {{
        width: 100%; border-collapse: collapse; font-size: 0.85rem;
        background: #1e293b; border-radius: 8px; overflow: hidden;
    }}
    th {{
        background: #334155; padding: 8px 12px; text-align: left;
        font-weight: 600; color: #cbd5e1; font-size: 0.75rem;
        text-transform: uppercase; letter-spacing: 0.05em;
        cursor: pointer; user-select: none;
    }}
    th:hover {{ background: #475569; }}
    td {{ padding: 6px 12px; border-top: 1px solid #0f172a; }}
    td a {{ color: #60a5fa; text-decoration: none; }}
    td a:hover {{ text-decoration: underline; }}
    .f1-good {{ color: #22c55e; font-weight: 700; }}
    .f1-ok {{ color: #eab308; font-weight: 700; }}
    .f1-bad {{ color: #ef4444; font-weight: 700; }}
    .footer {{
        text-align: center; padding: 16px 0; margin-top: 16px;
        border-top: 1px solid #334155; font-size: 0.75rem; color: #64748b;
    }}
</style>
</head>
<body>
<div class="container">
    <h1>Climb Detection Review</h1>
    <div class="subtitle">Run: {esc(run_id)} &middot; {len(rides_data)} rides</div>

    <div class="agg-summary">
        <div class="stat"><div class="value">{len(rides_data)}</div><div class="label">Rides</div></div>
        <div class="stat"><div class="value">{total_matched}</div><div class="label">Matched</div></div>
        <div class="stat"><div class="value">{total_missed}</div><div class="label">Missed</div></div>
        <div class="stat"><div class="value">{total_extras}</div><div class="label">Extra</div></div>
        <div class="stat"><div class="value">{agg_precision:.0%}</div><div class="label">Precision</div></div>
        <div class="stat"><div class="value">{agg_recall:.0%}</div><div class="label">Recall</div></div>
        <div class="stat"><div class="value">{agg_f1:.2f}</div><div class="label">F1</div></div>
    </div>

    <table id="ridesTable">
        <thead>
            <tr>
                <th onclick="sortTable(0)">Ride</th>
                <th onclick="sortTable(1)">Date</th>
                <th onclick="sortTable(2)">Segments</th>
                <th onclick="sortTable(3)">Matched</th>
                <th onclick="sortTable(4)">Missed</th>
                <th onclick="sortTable(5)">Extra</th>
                <th onclick="sortTable(6)">Precision</th>
                <th onclick="sortTable(7)">Recall</th>
                <th onclick="sortTable(8)">F1</th>
            </tr>
        </thead>
        <tbody>
            {rows_html}
        </tbody>
    </table>

    <div class="footer">Climb Detection Review Index</div>
</div>

<script>
var sortDir = {{}};
function sortTable(col) {{
    var table = document.getElementById('ridesTable');
    var tbody = table.querySelector('tbody');
    var rows = Array.from(tbody.querySelectorAll('tr'));
    var dir = sortDir[col] = !(sortDir[col] || false);
    rows.sort(function(a, b) {{
        var av = a.cells[col].textContent.trim();
        var bv = b.cells[col].textContent.trim();
        var an = parseFloat(av.replace('%', ''));
        var bn = parseFloat(bv.replace('%', ''));
        if (!isNaN(an) && !isNaN(bn)) {{
            return dir ? an - bn : bn - an;
        }}
        return dir ? av.localeCompare(bv) : bv.localeCompare(av);
    }});
    rows.forEach(function(row) {{ tbody.appendChild(row); }});
}}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def select_rides(
    conn: sqlite3.Connection,
    activity_id: Optional[str] = None,
    top: int = 0,
    most_missed: int = 0,
    run_id: Optional[str] = None,
    all_rides: bool = False,
) -> List[str]:
    """Select which rides to generate reviews for."""

    if activity_id:
        return [activity_id]

    if most_missed and run_id:
        # Rides with the most missed segments for the given run
        rows = conn.execute(
            """SELECT activity_id, COUNT(*) as miss_count
               FROM detection_results
               WHERE run_id = ? AND result_type = 'missed'
               GROUP BY activity_id
               ORDER BY miss_count DESC
               LIMIT ?""",
            (run_id, most_missed),
        ).fetchall()
        return [r[0] for r in rows]

    if top:
        # Rides with most reference segments
        rows = conn.execute(
            """SELECT r.activity_id, COUNT(s.id) as seg_count
               FROM rides r
               JOIN strava_segment_efforts s ON r.activity_id = s.activity_id
               JOIN activity_streams a ON r.activity_id = a.activity_id
               WHERE s.is_climb = 1 AND s.elevation_diff >= ? AND s.average_grade >= ?
               GROUP BY r.activity_id
               ORDER BY seg_count DESC
               LIMIT ?""",
            (MIN_CLIMB_VERT_M, MIN_CLIMB_GRADE_PCT, top),
        ).fetchall()
        return [r[0] for r in rows]

    if all_rides:
        # All rides with cached streams and detection results
        if run_id:
            rows = conn.execute(
                """SELECT DISTINCT d.activity_id
                   FROM detection_results d
                   JOIN activity_streams a ON d.activity_id = a.activity_id
                   WHERE d.run_id = ?
                   ORDER BY d.activity_id""",
                (run_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT DISTINCT r.activity_id
                   FROM rides r
                   JOIN activity_streams a ON r.activity_id = a.activity_id
                   JOIN strava_segment_efforts s ON r.activity_id = s.activity_id
                   WHERE s.is_climb = 1 AND s.elevation_diff >= ? AND s.average_grade >= ?
                   GROUP BY r.activity_id
                   HAVING COUNT(s.id) >= 3
                   ORDER BY r.start_date""",
                (MIN_CLIMB_VERT_M, MIN_CLIMB_GRADE_PCT),
            ).fetchall()
        return [r[0] for r in rows]

    # Default: top 20
    return select_rides(conn, top=20)


def main():
    parser = argparse.ArgumentParser(
        description="Generate HTML ride review overlays for climb detection evaluation"
    )
    parser.add_argument("--db", default=str(GOLDEN_DB), help="Path to golden corpus DB")
    parser.add_argument("--output-dir", default=str(REVIEWS_DIR), help="Output directory for HTML files")
    parser.add_argument("--activity-id", type=str, default=None, help="Generate for a specific ride")
    parser.add_argument("--top", type=int, default=0, help="Generate for top N rides by segment count")
    parser.add_argument("--most-missed", type=int, default=0, help="Generate for N rides with most misses")
    parser.add_argument("--all", action="store_true", help="Generate for all scorable rides")
    parser.add_argument("--run-id", type=str, default=None, help="Use a specific detection run ID")
    parser.add_argument("--algorithm", type=str, default="canonical_v2", help="Algorithm to use (default: canonical_v2)")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))

    # Resolve run_id
    run_id = args.run_id
    if not run_id:
        run_id = get_latest_run_id(conn, args.algorithm)
        if not run_id:
            print(f"ERROR: No detection runs found for algorithm '{args.algorithm}'.", file=sys.stderr)
            print("Run `python tools/corpus/run_full_comparison.py` first.", file=sys.stderr)
            sys.exit(1)
        print(f"Using latest run: {run_id}")

    available_runs = get_available_runs(conn)

    # Select rides
    activity_ids = select_rides(
        conn,
        activity_id=args.activity_id,
        top=args.top,
        most_missed=args.most_missed if args.most_missed else 0,
        run_id=run_id,
        all_rides=args.all,
    )

    if not activity_ids:
        print("No rides selected. Check your filters and database content.")
        sys.exit(1)

    print(f"Generating reviews for {len(activity_ids)} rides...")

    # Create output directory
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Generate individual ride HTMLs
    rides_data = []
    generated = 0
    skipped = 0

    for idx, aid in enumerate(activity_ids):
        ride = load_ride_info(conn, aid)
        if not ride:
            print(f"  [{idx+1}/{len(activity_ids)}] {aid} -- no ride info (skipped)")
            skipped += 1
            continue

        streams = load_streams(conn, aid)
        if not streams:
            print(f"  [{idx+1}/{len(activity_ids)}] {aid} -- no cached streams (skipped)")
            skipped += 1
            continue

        # Load ground truth segments
        segments = load_segments(conn, aid)
        segments = dedup_segments(segments)

        # Load detection results
        results = load_detection_results(conn, aid, run_id)

        # If no results from detection_results table, we can still show the ride
        # with just the reference segments (all shown as "no detection data")

        # Navigation
        prev_id = activity_ids[idx - 1] if idx > 0 else None
        next_id = activity_ids[idx + 1] if idx < len(activity_ids) - 1 else None

        # Generate HTML
        html_content = generate_ride_html(
            ride=ride,
            streams=streams,
            segments=segments,
            results=results,
            run_id=run_id,
            available_runs=available_runs,
            prev_activity_id=prev_id,
            next_activity_id=next_id,
            all_activity_ids=activity_ids,
        )

        out_file = out_dir / f"{aid}.html"
        out_file.write_text(html_content)

        # Collect stats for index
        matched = sum(1 for r in results if r.result_type == "matched")
        missed = sum(1 for r in results if r.result_type == "missed")
        extras = sum(1 for r in results if r.result_type == "extra")
        total_exp = matched + missed
        total_det = matched + extras
        p = matched / total_det if total_det > 0 else 1.0
        r_val = matched / total_exp if total_exp > 0 else 1.0
        f1 = 2 * p * r_val / (p + r_val) if (p + r_val) > 0 else 0.0

        rides_data.append({
            "activity_id": aid,
            "name": ride.name,
            "date": (ride.start_date[:10] if ride.start_date else ""),
            "segments": len(segments),
            "matched": matched,
            "missed": missed,
            "extras": extras,
            "precision": p,
            "recall": r_val,
            "f1": f1,
        })

        generated += 1
        ride_label = (ride.name or aid)[:40]
        print(f"  [{idx+1}/{len(activity_ids)}] {ride_label:40s}  m={matched} miss={missed} x={extras} F1={f1:.2f}")

    # Generate index.html
    # Sort index by F1 ascending (worst first -- most interesting to review)
    rides_data.sort(key=lambda r: r["f1"])
    index_html = generate_index_html(rides_data, run_id)
    (out_dir / "index.html").write_text(index_html)

    print(f"\nGenerated: {generated} rides ({skipped} skipped)")
    print(f"Output: {out_dir}/")
    print(f"Index:  {out_dir}/index.html")


if __name__ == "__main__":
    main()
