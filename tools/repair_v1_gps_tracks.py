#!/usr/bin/env python3
"""Repair persisted v1 GPS tracks that encoded missing elevation as 0m.

Default mode is a dry-run. Use --apply to write the repaired v2 gps_track and
replace climb rows from the raw-file reparse.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.repositories import PatternRepository, get_supabase_client  # noqa: E402
from app.services.file_storage import create_file_storage_service  # noqa: E402
from app.services.gps_track_repair import (  # noqa: E402
    analyze_v1_elevation_sentinel,
    pattern_quality_kwargs,
    reparse_raw_ride_projection,
    summarize_climb,
)


def _pattern_kwargs(
    *,
    activity_id: UUID,
    wallet: str,
    climb: Any,
    detector_version: str,
    source_samples: List[Dict[str, Any]],
) -> Dict[str, Any]:
    payload = {
        "pattern_id": uuid4(),
        "activity_id": activity_id,
        "wallet": wallet,
        "vert_m": climb.vert_m,
        "time_s": climb.time_s,
        "start_offset_s": climb.start_time_offset_s,
        "end_offset_s": climb.end_time_offset_s,
        "avg_power_w": getattr(climb, "avg_power_w", None),
        "w_per_kg": getattr(climb, "w_per_kg", None),
        "avg_hr": getattr(climb, "avg_hr", None),
        "tile_ids": climb.tile_ids,
        "distance_m": climb.distance_m,
        "avg_gradient_pct": climb.avg_gradient_pct,
        "signature_hex": climb.signature_hex,
        "signature_v2_hex": getattr(climb, "signature_v2_hex", None),
        "persistence_m": getattr(climb, "persistence", None),
        "start_lat": getattr(climb, "start_lat", None),
        "start_lon": getattr(climb, "start_lon", None),
        "end_lat": getattr(climb, "end_lat", None),
        "end_lon": getattr(climb, "end_lon", None),
        "detector_version": detector_version,
    }
    payload.update(
        pattern_quality_kwargs(
            climb,
            source_samples,
            context=f"v1_gps_repair:{detector_version}",
        )
    )
    return payload


def _fetch_ride_rows(
    client: Any,
    *,
    ride_id: Optional[str],
    min_elevation_gain_m: float,
    scan_limit: int,
) -> List[Dict[str, Any]]:
    select_cols = "id,file_type,raw_file_path,gps_track,elevation_gain_m,user_id"
    if ride_id:
        result = client.table("rides").select(select_cols).eq("id", ride_id).limit(1).execute()
        return result.data or []

    result = (
        client.table("rides")
        .select(select_cols)
        .gte("elevation_gain_m", min_elevation_gain_m)
        .eq("processing_status", "completed")
        .order("uploaded_at")
        .limit(scan_limit)
        .execute()
    )
    return [
        row
        for row in (result.data or [])
        if row.get("raw_file_path") and isinstance(row.get("gps_track"), dict)
    ]


def _fetch_existing_climbs(client: Any, ride_id: str) -> List[Dict[str, Any]]:
    result = (
        client.table("patterns_climb")
        .select(
            "id,wallet,vert_m,time_s,distance_m,avg_gradient_pct,"
            "start_offset_s,end_offset_s,detector_version,persistence_m"
        )
        .eq("activity_id", ride_id)
        .execute()
    )
    return result.data or []


def _resolve_wallet(client: Any, ride_id: str, user_id: Optional[str]) -> Optional[str]:
    existing = _fetch_existing_climbs(client, ride_id)
    wallet = next((row.get("wallet") for row in existing if row.get("wallet")), None)
    if wallet or not user_id:
        return wallet
    result = client.table("users").select("wallet").eq("id", user_id).limit(1).execute()
    rows = result.data or []
    return rows[0].get("wallet") if rows else None


async def _repair_row(client: Any, row: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    ride_id = str(row["id"])
    analysis = analyze_v1_elevation_sentinel(
        row.get("gps_track"),
        min_zero_prefix=args.min_zero_prefix,
        min_jump_m=args.min_jump_m,
    )
    result: Dict[str, Any] = {
        "ride_id": ride_id,
        "elevation_gain_m": row.get("elevation_gain_m"),
        "analysis": analysis.to_dict(),
        "action": "skipped",
    }

    if not analysis.suspicious and not args.force:
        result["skip_reason"] = analysis.reason
        return result

    existing_climbs = _fetch_existing_climbs(client, ride_id)
    result["old_climbs"] = [
        {
            "id": climb.get("id"),
            "vert_m": climb.get("vert_m"),
            "distance_m": climb.get("distance_m"),
            "avg_gradient_pct": climb.get("avg_gradient_pct"),
            "start_s": climb.get("start_offset_s"),
            "end_s": climb.get("end_offset_s"),
        }
        for climb in existing_climbs
    ]

    raw_file_path = row.get("raw_file_path")
    if not raw_file_path:
        result["skip_reason"] = "missing_raw_file_path"
        return result

    file_bytes = await create_file_storage_service(client).download_ride_file(raw_file_path)
    projection = reparse_raw_ride_projection(
        file_bytes,
        row.get("file_type") or "fit",
        detector_algorithm=args.detector_algorithm,
    )
    result["projection"] = projection.summary

    if not projection.climbs and not args.allow_empty_climbs:
        result["skip_reason"] = "reparse_found_no_climbs"
        return result

    if not args.apply:
        result["action"] = "would_apply"
        return result

    wallet = _resolve_wallet(client, ride_id, row.get("user_id"))
    if not wallet:
        result["skip_reason"] = "could_not_resolve_wallet"
        return result

    client.table("rides").update({"gps_track": projection.encoded_gps_track}).eq("id", ride_id).execute()
    client.table("patterns_climb").delete().eq("activity_id", ride_id).execute()

    repo = PatternRepository(client)
    inserted = 0
    for climb in projection.climbs:
        await repo.store_climb_pattern(
            **_pattern_kwargs(
                activity_id=UUID(ride_id),
                wallet=wallet,
                climb=climb,
                detector_version=args.detector_algorithm,
                source_samples=projection.tile_runs,
            )
        )
        inserted += 1

    result["action"] = "applied"
    result["inserted_climbs"] = inserted
    result["new_climbs"] = [summarize_climb(climb) for climb in projection.climbs]
    return result


async def _main_async(args: argparse.Namespace) -> int:
    client = get_supabase_client()
    rows = _fetch_ride_rows(
        client,
        ride_id=args.ride_id,
        min_elevation_gain_m=args.min_elevation_gain_m,
        scan_limit=args.scan_limit,
    )
    results = []
    skipped_by_reason: Dict[str, int] = {}
    for row in rows:
        result = await _repair_row(client, row, args)
        if result["action"] == "skipped":
            reason = str(result.get("skip_reason") or "skipped")
            skipped_by_reason[reason] = skipped_by_reason.get(reason, 0) + 1
            if args.all_results:
                results.append(result)
        else:
            results.append(result)

    print(json.dumps({
        "apply": args.apply,
        "scanned": len(rows),
        "returned": len(results),
        "skipped_by_reason": skipped_by_reason,
        "results": results,
    }, indent=2, default=str))
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ride-id", help="Repair a specific ride ID instead of scanning")
    parser.add_argument("--scan-limit", type=int, default=250)
    parser.add_argument("--min-elevation-gain-m", type=float, default=50.0)
    parser.add_argument("--min-zero-prefix", type=int, default=5)
    parser.add_argument("--min-jump-m", type=float, default=50.0)
    parser.add_argument("--detector-algorithm", default="canonical_v2")
    parser.add_argument("--force", action="store_true", help="Reparse even when the v1 sentinel detector is not suspicious")
    parser.add_argument("--allow-empty-climbs", action="store_true", help="Allow apply to replace climb rows with zero rows")
    parser.add_argument("--all-results", action="store_true", help="Include skipped rides in output")
    parser.add_argument("--apply", action="store_true", help="Write repaired gps_track and replacement climb rows")
    return parser.parse_args()


def main() -> int:
    return asyncio.run(_main_async(_parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
