#!/usr/bin/env python3
"""Explain holdout scoring for one or more activities.

This is the single-ride drilldown companion to run_holdout_eval.py. It uses the
same corpus filters and detector path, but returns segment-level records so a
changed aggregate result can be inspected without re-running the whole holdout.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterable

from run_holdout_eval import (
    GOLDEN_DB,
    MIN_CLIMB_GRADE_PCT,
    MIN_CLIMB_VERT_M,
    OVERLAP_THRESHOLD,
    Detection,
    Segment,
    classify_failure,
    compute_metrics,
    dedup_segments,
    load_frequency_map,
    run_detector,
    streams_to_tile_data,
)
from holdout_reference_quality import (
    holdout_policy_classification,
    quarantine_repeated_segment_spam,
    quarantined_segment_count,
)


def _overlap_ratio(seg: Segment, det: Detection) -> float:
    overlap = max(0, min(seg.end_time_s, det.end_s) - max(seg.start_time_s, det.start_s))
    shorter = min(
        max(1, seg.end_time_s - seg.start_time_s),
        max(1, det.end_s - det.start_s),
    )
    return overlap / shorter


def _segment_record(seg: Segment) -> dict[str, Any]:
    return {
        "segment_id": seg.segment_id,
        "segment_name": seg.segment_name,
        "seg_start_s": seg.start_time_s,
        "seg_end_s": seg.end_time_s,
        "seg_elev_diff": round(seg.elevation_diff, 2),
        "seg_avg_grade": round(seg.average_grade, 2),
        "seg_distance_m": round(seg.distance_m, 1),
    }


def _detection_record(det: Detection) -> dict[str, Any]:
    return {
        "det_start_s": det.start_s,
        "det_end_s": det.end_s,
        "det_vert_m": round(det.vert_m, 2),
        "det_grade_pct": round(det.grade_pct, 2),
        "det_distance_m": round(det.distance_m, 1),
        "det_mode": det.mode,
    }


def detailed_match_records(
    segments: list[Segment],
    detections: list[Detection],
    time_array: list[int],
) -> list[dict[str, Any]]:
    """Match detections to references and keep row-level evidence."""
    for seg in segments:
        seg.start_time_s = time_array[seg.start_index] if seg.start_index < len(time_array) else 0
        seg.end_time_s = time_array[seg.end_index] if seg.end_index < len(time_array) else 0

    records: list[dict[str, Any]] = []
    used_detections: set[int] = set()

    for seg in segments:
        best_idx = None
        best_overlap = 0.0
        for idx, det in enumerate(detections):
            if idx in used_detections:
                continue
            ratio = _overlap_ratio(seg, det)
            if ratio >= OVERLAP_THRESHOLD and ratio > best_overlap:
                best_idx = idx
                best_overlap = ratio

        if best_idx is None:
            records.append({"result_type": "missed", **_segment_record(seg)})
            continue

        det = detections[best_idx]
        used_detections.add(best_idx)
        records.append({
            "result_type": "matched",
            **_segment_record(seg),
            **_detection_record(det),
            "overlap_ratio": round(best_overlap, 3),
            "boundary_start_diff_s": det.start_s - seg.start_time_s,
            "boundary_end_diff_s": det.end_s - seg.end_time_s,
        })

    for idx, det in enumerate(detections):
        if idx not in used_detections:
            records.append({"result_type": "extra", **_detection_record(det)})

    return sorted(
        records,
        key=lambda row: (
            row.get("seg_start_s")
            if row.get("seg_start_s") is not None
            else row.get("det_start_s", 0)
        ),
    )


def _load_activity_rows(conn: sqlite3.Connection, activity_id: str) -> tuple[dict[str, Any], list[Segment], dict[str, Any]]:
    ride_row = conn.execute(
        """
        SELECT activity_id, name, start_date, distance_m, elevation_gain_m
        FROM rides
        WHERE activity_id = ?
        """,
        (activity_id,),
    ).fetchone()
    if not ride_row:
        raise ValueError(f"activity {activity_id} not found in rides")

    stream_row = conn.execute(
        "SELECT streams_json FROM activity_streams WHERE activity_id = ?",
        (activity_id,),
    ).fetchone()
    if not stream_row:
        raise ValueError(f"activity {activity_id} has no cached streams")

    effort_rows = conn.execute(
        """
        SELECT segment_id, segment_name, start_index, end_index,
               elevation_diff, average_grade, distance_m
        FROM strava_segment_efforts
        WHERE activity_id = ? AND is_climb = 1
              AND elevation_diff >= ? AND average_grade >= ?
        ORDER BY start_index
        """,
        (activity_id, MIN_CLIMB_VERT_M, MIN_CLIMB_GRADE_PCT),
    ).fetchall()

    segments = [
        Segment(
            segment_id=row[0],
            segment_name=row[1],
            start_index=row[2],
            end_index=row[3],
            elevation_diff=row[4],
            average_grade=row[5],
            distance_m=row[6] or 0,
        )
        for row in effort_rows
    ]
    raw_streams = json.loads(stream_row[0])
    streams = {stream["type"]: stream["data"] for stream in raw_streams}
    ride = {
        "activity_id": str(ride_row[0]),
        "name": ride_row[1],
        "start_date": ride_row[2],
        "distance_m": ride_row[3],
        "elevation_gain_m": ride_row[4],
    }
    return ride, segments, streams


def explain_activity(
    conn: sqlite3.Connection,
    activity_id: str,
    *,
    mode: str,
    frequency_map: dict[str, int] | None,
) -> dict[str, Any]:
    ride, raw_segments, streams = _load_activity_rows(conn, activity_id)
    raw_segments = dedup_segments(raw_segments)
    segments, quarantined_groups = quarantine_repeated_segment_spam(raw_segments)

    time_array = streams.get("time", [])
    tile_samples, _ = streams_to_tile_data(streams)
    if not tile_samples:
        raise ValueError(f"activity {activity_id} produced no tile samples")

    deployment = mode == "deployment"
    detections = run_detector(
        tile_samples,
        frequency_map=frequency_map if deployment else None,
        use_bridge_preprocessing=deployment,
    )
    records = detailed_match_records(segments, detections, time_array)

    matched = sum(1 for row in records if row["result_type"] == "matched")
    missed = sum(1 for row in records if row["result_type"] == "missed")
    extras = sum(1 for row in records if row["result_type"] == "extra")
    precision, recall, f1 = compute_metrics(matched, missed, extras)
    policy_classification = holdout_policy_classification(activity_id)
    classification = policy_classification or classify_failure(matched, missed, extras)

    return {
        "mode": mode,
        "ride": ride,
        "summary": {
            "segments": len(segments),
            "raw_segments": len(raw_segments),
            "detections": len(detections),
            "matched": matched,
            "missed": missed,
            "extras": extras,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "classification": classification,
            "quarantined_reference_segments": quarantined_segment_count(quarantined_groups),
            "quarantine_reasons": [group.reason for group in quarantined_groups],
        },
        "records": records,
    }


def _print_activity(result: dict[str, Any]) -> None:
    ride = result["ride"]
    summary = result["summary"]
    print(
        f"{ride['activity_id']} {ride.get('name') or ''}: "
        f"m={summary['matched']} miss={summary['missed']} x={summary['extras']} "
        f"P={summary['precision']:.3f} R={summary['recall']:.3f} F1={summary['f1']:.3f} "
        f"class={summary['classification']}"
    )
    for row in result["records"]:
        if row["result_type"] == "matched":
            print(
                f"  matched  seg={row['segment_id']} {row['segment_name']} "
                f"seg={row['seg_start_s']}-{row['seg_end_s']} "
                f"det={row['det_start_s']}-{row['det_end_s']} "
                f"overlap={row['overlap_ratio']:.3f} "
                f"d_start={row['boundary_start_diff_s']:+d}s "
                f"d_end={row['boundary_end_diff_s']:+d}s"
            )
        elif row["result_type"] == "missed":
            print(
                f"  missed   seg={row['segment_id']} {row['segment_name']} "
                f"seg={row['seg_start_s']}-{row['seg_end_s']} "
                f"vert={row['seg_elev_diff']}m grade={row['seg_avg_grade']}%"
            )
        else:
            print(
                f"  extra    det={row['det_start_s']}-{row['det_end_s']} "
                f"vert={row['det_vert_m']}m grade={row['det_grade_pct']}% "
                f"mode={row['det_mode']}"
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("activity_id", nargs="+", help="Strava activity ID(s) in golden_corpus.db")
    parser.add_argument("--db", default=str(GOLDEN_DB), help="Golden corpus DB path")
    parser.add_argument(
        "--mode",
        choices=["deployment", "scientific"],
        default="deployment",
        help="deployment uses H12 + bridge preprocessing; scientific disables both",
    )
    parser.add_argument("--output", type=Path, help="Write JSON artifact to this path")
    parser.add_argument("--quiet", action="store_true", help="Only write JSON output")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: database not found: {db_path}", file=sys.stderr)
        return 2

    try:
        conn = sqlite3.connect(str(db_path))
        frequency_map = load_frequency_map(db_path)
        results = [
            explain_activity(conn, activity_id, mode=args.mode, frequency_map=frequency_map)
            for activity_id in args.activity_id
        ]
    except (sqlite3.Error, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        if "conn" in locals():
            conn.close()

    artifact = {"mode": args.mode, "activities": results}
    if args.output:
        args.output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    if not args.quiet:
        for result in results:
            _print_activity(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
