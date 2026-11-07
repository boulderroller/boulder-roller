#!/usr/bin/env python3
"""Backfill source-quality traces on legacy climb rows.

The script is intentionally conservative: it only targets rows currently
eligible for economics that lack match_trace.source_quality. It evaluates the
existing persisted climb window against the ride GPS/tile samples and may demote
rows whose source coverage or shape fails current guardrails; it never promotes
already-abstained rows.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional

import psycopg2
from psycopg2.extras import Json

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.gps_track_repair import evaluate_climb_source_quality  # noqa: E402
from app.services.tile_service import TileService  # noqa: E402
from app.utils.polyline import decode_gps_track  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=None, help="Postgres DATABASE_URL")
    parser.add_argument("--activity-id", default=None, help="Limit to one ride UUID")
    parser.add_argument("--limit", type=int, default=0, help="Maximum climb rows to scan")
    parser.add_argument("--apply", action="store_true", help="Write updates")
    return parser.parse_args()


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key, value.strip().strip("\"'"))


def database_url(args: argparse.Namespace) -> str:
    if args.database_url:
        return args.database_url
    load_dotenv(ROOT / "backend" / ".env")
    value = os.getenv("DATABASE_URL")
    if not value:
        raise SystemExit("DATABASE_URL is required via --database-url or backend/.env")
    return value


def fetch_candidate_rows(conn, *, activity_id: Optional[str], limit: int) -> List[Dict[str, Any]]:
    params: list[Any] = []
    filters = [
        "coalesce(pc.economic_eligible, true) = true",
        "(pc.match_trace is null or not (pc.match_trace ? 'source_quality'))",
    ]
    if activity_id:
        filters.append("pc.activity_id = %s")
        params.append(activity_id)

    query = f"""
        select
            pc.id,
            pc.activity_id,
            pc.vert_m,
            pc.time_s,
            pc.distance_m,
            pc.avg_gradient_pct,
            pc.start_offset_s,
            pc.end_offset_s,
            pc.match_trace,
            r.gps_track
        from patterns_climb pc
        left join rides r on r.id = pc.activity_id
        where {' and '.join(filters)}
        order by pc.activity_id, pc.start_offset_s nulls last, pc.id
    """
    if limit > 0:
        query += " limit %s"
        params.append(limit)

    with conn.cursor() as cur:
        cur.execute(query, params)
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def tile_runs_for_gps(gps_track: Any, cache_key: str, cache: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    if cache_key in cache:
        return cache[cache_key]
    if not gps_track:
        cache[cache_key] = []
        return cache[cache_key]
    try:
        points = decode_gps_track(gps_track)
        cache[cache_key] = TileService().get_tile_run_sequence(
            points=points,
            resolution=10,
            start_time=None,
        ) or []
    except Exception:
        cache[cache_key] = []
    return cache[cache_key]


def climb_from_row(row: Dict[str, Any]) -> SimpleNamespace:
    start_s = int(row.get("start_offset_s") or 0)
    end_s = int(row.get("end_offset_s") or start_s)
    time_s = int(row.get("time_s") or max(0, end_s - start_s))
    return SimpleNamespace(
        start_time_offset_s=start_s,
        end_time_offset_s=end_s,
        vert_m=float(row.get("vert_m") or 0.0),
        time_s=time_s,
        distance_m=float(row.get("distance_m") or 0.0),
        avg_gradient_pct=row.get("avg_gradient_pct"),
    )


def existing_trace(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def update_row(conn, row_id: str, quality: Dict[str, Any], trace: Dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            update patterns_climb
            set
                economic_eligible = %s,
                abstention_reasons = %s,
                match_trace = %s::jsonb
            where id = %s
            """,
            (
                bool(quality["economic_eligible"]),
                quality["abstention_reasons"] or None,
                Json(trace),
                row_id,
            ),
        )


def summarize_quality(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    summary = {
        "rows_scanned": 0,
        "eligible_after": 0,
        "demoted_after": 0,
        "missing_samples": 0,
        "reasons": defaultdict(int),
    }
    for row in rows:
        quality = row["quality"]
        summary["rows_scanned"] += 1
        if quality["economic_eligible"]:
            summary["eligible_after"] += 1
        else:
            summary["demoted_after"] += 1
        if quality["sample_count"] == 0:
            summary["missing_samples"] += 1
        for reason in quality["abstention_reasons"]:
            summary["reasons"][reason] += 1
    summary["reasons"] = dict(sorted(summary["reasons"].items()))
    return summary


def main() -> int:
    args = parse_args()
    conn = psycopg2.connect(database_url(args))
    conn.autocommit = False
    tile_cache: Dict[str, List[Dict[str, Any]]] = {}
    reviewed_rows: list[dict[str, Any]] = []

    try:
        rows = fetch_candidate_rows(
            conn,
            activity_id=args.activity_id,
            limit=args.limit,
        )
        for row in rows:
            activity_id = str(row["activity_id"])
            samples = tile_runs_for_gps(row.get("gps_track"), activity_id, tile_cache)
            quality = evaluate_climb_source_quality(
                climb_from_row(row),
                samples,
                context="legacy_source_quality_backfill",
            )
            trace = existing_trace(row.get("match_trace"))
            trace["source_quality"] = quality
            reviewed_rows.append(
                {
                    "id": str(row["id"]),
                    "activity_id": activity_id,
                    "quality": quality,
                    "trace": trace,
                }
            )
            if args.apply:
                update_row(conn, str(row["id"]), quality, trace)

        summary = summarize_quality(reviewed_rows)
        summary["activities_scanned"] = len({row["activity_id"] for row in reviewed_rows})
        summary["mode"] = "apply" if args.apply else "dry-run"
        print(json.dumps(summary, indent=2, sort_keys=True))
        if args.apply:
            conn.commit()
        else:
            conn.rollback()
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
