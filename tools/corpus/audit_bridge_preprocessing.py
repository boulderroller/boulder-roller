#!/usr/bin/env python3
"""Audit bridge preprocessing effects on holdout climb detection.

Runs each selected ride twice with the deployment frequency map:
once with bridge preprocessing disabled and once with bridge preprocessing
enabled. The output includes accepted/skipped bridge spans plus per-ride metric
deltas, so bridge corrections can be reviewed as signal edits instead of logs.
"""

from __future__ import annotations

import argparse
import copy
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from run_holdout_eval import (
    GOLDEN_DB,
    MIN_CLIMB_GRADE_PCT,
    MIN_CLIMB_VERT_M,
    Detection,
    Segment,
    compute_metrics,
    dedup_segments,
    load_frequency_map,
    match_detections_to_segments,
    run_detector,
    streams_to_tile_data,
)
from holdout_reference_quality import quarantine_repeated_segment_spam

REPO_ROOT = Path(__file__).parent.parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.road_enrichment import preprocess_bridge_elevations


def _load_activity_ids(
    conn: sqlite3.Connection,
    *,
    split: str,
    activity_ids: list[str],
    limit: int,
) -> list[tuple[str, str]]:
    if activity_ids:
        placeholders = ",".join("?" for _ in activity_ids)
        rows = conn.execute(
            f"""
            SELECT activity_id, name
            FROM rides
            WHERE activity_id IN ({placeholders})
            ORDER BY start_date ASC
            """,
            activity_ids,
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT DISTINCT r.activity_id, r.name
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
            """,
            (split, MIN_CLIMB_VERT_M, MIN_CLIMB_GRADE_PCT),
        ).fetchall()
    if limit > 0:
        rows = rows[:limit]
    return [(str(row[0]), row[1] or "") for row in rows]


def _load_activity_payload(
    conn: sqlite3.Connection,
    activity_id: str,
) -> tuple[list[Segment], dict[str, Any]]:
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
    return segments, streams


def _score_detection_set(
    segments: list[Segment],
    detections: list[Detection],
    time_array: list[int],
) -> dict[str, Any]:
    matched, missed, extras = match_detections_to_segments(segments, detections, time_array)
    precision, recall, f1 = compute_metrics(matched, missed, extras)
    return {
        "detections": len(detections),
        "matched": matched,
        "missed": missed,
        "extras": extras,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def _delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    keys = ("detections", "matched", "missed", "extras", "precision", "recall", "f1")
    return {
        key: round(after[key] - before[key], 4)
        for key in keys
    }


def _summarize_bridge_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = Counter(record["status"] for record in records)
    reason_counts = Counter(record["reason"] for record in records)
    suspicious = [
        record for record in records
        if record["reason"] in {"time_span_too_large", "track_span_too_large"}
    ]
    return {
        "total_records": len(records),
        "accepted": status_counts.get("accepted", 0),
        "skipped": status_counts.get("skipped", 0),
        "status_counts": dict(sorted(status_counts.items())),
        "reason_counts": dict(sorted(reason_counts.items())),
        "suspicious_skips": len(suspicious),
    }


def _run_bridge_enabled_detector(
    tile_samples: list[dict[str, Any]],
    frequency_map: dict[str, int] | None,
) -> tuple[list[Detection], list[dict[str, Any]]]:
    diagnostics: list[dict[str, Any]] = []
    samples = copy.deepcopy(tile_samples)
    preprocess_bridge_elevations(samples, diagnostics=diagnostics)
    detections = run_detector(samples, frequency_map=frequency_map, use_bridge_preprocessing=False)
    return detections, diagnostics


def audit_activity(
    conn: sqlite3.Connection,
    activity_id: str,
    name: str,
    frequency_map: dict[str, int] | None,
) -> dict[str, Any]:
    raw_segments, streams = _load_activity_payload(conn, activity_id)
    raw_segments = dedup_segments(raw_segments)
    segments, quarantined_groups = quarantine_repeated_segment_spam(raw_segments)
    if len(segments) < 3:
        raise ValueError(f"activity {activity_id} has fewer than 3 scored segments")

    time_array = streams.get("time", [])
    tile_samples, _ = streams_to_tile_data(streams)
    if not tile_samples:
        raise ValueError(f"activity {activity_id} produced no tile samples")

    bridge_off = run_detector(
        copy.deepcopy(tile_samples),
        frequency_map=frequency_map,
        use_bridge_preprocessing=False,
    )
    bridge_on, bridge_records = _run_bridge_enabled_detector(tile_samples, frequency_map)
    off_score = _score_detection_set(segments, bridge_off, time_array)
    on_score = _score_detection_set(segments, bridge_on, time_array)

    return {
        "activity_id": activity_id,
        "name": name,
        "segments": len(segments),
        "raw_segments": len(raw_segments),
        "quarantined_reference_segments": sum(group.count for group in quarantined_groups),
        "bridge_off": off_score,
        "bridge_on": on_score,
        "delta": _delta(off_score, on_score),
        "bridge_summary": _summarize_bridge_records(bridge_records),
        "bridge_records": bridge_records,
    }


def summarize_activities(activities: list[dict[str, Any]]) -> dict[str, Any]:
    total_off = Counter()
    total_on = Counter()
    for activity in activities:
        for key in ("matched", "missed", "extras"):
            total_off[key] += activity["bridge_off"][key]
            total_on[key] += activity["bridge_on"][key]

    off_p, off_r, off_f1 = compute_metrics(
        total_off["matched"],
        total_off["missed"],
        total_off["extras"],
    )
    on_p, on_r, on_f1 = compute_metrics(
        total_on["matched"],
        total_on["missed"],
        total_on["extras"],
    )
    bridge_reasons = Counter()
    bridge_statuses = Counter()
    for activity in activities:
        bridge_reasons.update(activity["bridge_summary"]["reason_counts"])
        bridge_statuses.update(activity["bridge_summary"]["status_counts"])

    bridge_off = {
        "matched": total_off["matched"],
        "missed": total_off["missed"],
        "extras": total_off["extras"],
        "precision": round(off_p, 4),
        "recall": round(off_r, 4),
        "f1": round(off_f1, 4),
    }
    bridge_on = {
        "matched": total_on["matched"],
        "missed": total_on["missed"],
        "extras": total_on["extras"],
        "precision": round(on_p, 4),
        "recall": round(on_r, 4),
        "f1": round(on_f1, 4),
    }
    return {
        "rides_scored": len(activities),
        "bridge_off": bridge_off,
        "bridge_on": bridge_on,
        "delta": _delta(
            {"detections": 0, **bridge_off},
            {"detections": 0, **bridge_on},
        ),
        "bridge_status_counts": dict(sorted(bridge_statuses.items())),
        "bridge_reason_counts": dict(sorted(bridge_reasons.items())),
    }


def _changed_activities(activities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    changed = [
        activity for activity in activities
        if any(activity["delta"][key] != 0 for key in ("matched", "missed", "extras"))
    ]
    return sorted(
        changed,
        key=lambda activity: (
            -(activity["delta"]["matched"] - activity["delta"]["missed"] - activity["delta"]["extras"]),
            activity["activity_id"],
        ),
    )


def _print_summary(summary: dict[str, Any], activities: list[dict[str, Any]], top: int) -> None:
    off = summary["bridge_off"]
    on = summary["bridge_on"]
    delta = summary["delta"]
    print(f"Rides scored: {summary['rides_scored']}")
    print(
        "Bridge off: "
        f"m={off['matched']} miss={off['missed']} x={off['extras']} "
        f"P={off['precision']:.4f} R={off['recall']:.4f} F1={off['f1']:.4f}"
    )
    print(
        "Bridge on:  "
        f"m={on['matched']} miss={on['missed']} x={on['extras']} "
        f"P={on['precision']:.4f} R={on['recall']:.4f} F1={on['f1']:.4f}"
    )
    print(
        "Delta:      "
        f"dm={delta['matched']:+d} dmiss={delta['missed']:+d} "
        f"dx={delta['extras']:+d} dF1={delta['f1']:+.4f}"
    )
    print(f"Bridge statuses: {summary['bridge_status_counts']}")
    print(f"Bridge reasons: {summary['bridge_reason_counts']}")

    changed = _changed_activities(activities)[:top]
    if changed:
        print()
        print(f"Changed rides (top {len(changed)}):")
        for activity in changed:
            d = activity["delta"]
            print(
                f"  {activity['activity_id']} dm={d['matched']:+d} "
                f"dmiss={d['missed']:+d} dx={d['extras']:+d} "
                f"dF1={d['f1']:+.4f} {activity['name']}"
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(GOLDEN_DB), help="Golden corpus DB path")
    parser.add_argument("--split", default="eval", help="ride_split value to audit")
    parser.add_argument("--activity-id", action="append", default=[], help="Specific activity ID to audit")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of rides")
    parser.add_argument("--output", type=Path, help="Write JSON audit artifact")
    parser.add_argument("--top", type=int, default=12, help="Changed rides to print")
    parser.add_argument("--quiet", action="store_true", help="Only write JSON output")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: database not found: {db_path}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(str(db_path))
    skipped_rides: list[dict[str, str]] = []
    try:
        frequency_map = load_frequency_map(db_path)
        rows = _load_activity_ids(
            conn,
            split=args.split,
            activity_ids=[str(activity_id) for activity_id in args.activity_id],
            limit=args.limit,
        )
        activities = []
        for activity_id, name in rows:
            try:
                activities.append(audit_activity(conn, activity_id, name, frequency_map))
            except (ValueError, json.JSONDecodeError) as exc:
                skipped_rides.append({"activity_id": activity_id, "reason": str(exc)})
    except sqlite3.Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        conn.close()

    summary = summarize_activities(activities)
    artifact = {
        "config": {
            "split": args.split,
            "activity_ids": args.activity_id,
            "limit": args.limit,
            "frequency_map_tiles": len(frequency_map) if frequency_map else 0,
        },
        "summary": summary,
        "skipped_rides": skipped_rides,
        "activities": activities,
    }
    if args.output:
        args.output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    if not args.quiet:
        _print_summary(summary, activities, args.top)
        if skipped_rides:
            print(f"Skipped rides: {len(skipped_rides)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
