#!/usr/bin/env python3
"""Explicit, read-side canonical-effort backfill; never run by migrations.

PYTHONPATH=backend python backend/scripts/backfill_climb_efforts.py --user-id UUID
Dry-run by default. --apply requires migration 175 and the matching native module.
Uses frozen training inputs; missing inputs/original files are unavailable.
--apply downloads retained originals and incurs storage egress. It verifies
their versioned canonical hash and retained D11 evidence before any write.
Never reprocesses a ride, changes Threshold, submits transactions or touches pay.
"""

import argparse
import asyncio
import json
import logging
from types import SimpleNamespace

logger = logging.getLogger(__name__)


async def backfill(repo, rides, parse, *, apply=False):
    from app.services.climb_effort_metrics import build_effort_rows
    from app.services.training_eligibility import is_training_eligible

    counts = dict(eligible=0, scored=0, unavailable=0, skipped=0, failed=0)
    for ride in rides:
        if not is_training_eligible(ride):
            counts["skipped"] += 1
            continue
        if not ride.get("training_inputs") or not ride.get("raw_file_path"):
            counts["unavailable"] += 1
            logger.warning("Effort backfill unavailable for ride %s: missing retained inputs/original", ride.get("id"))
            continue
        counts["eligible"] += 1
        if not apply:
            continue
        try:
            parsed = await parse(ride)
            if (parsed.ride_parser_version != ride.get("ride_parser_version")
                    or parsed.ride_hash_hex != ride.get("ride_hash_hex")):
                raise ValueError("re-parsed original identity mismatch")
            from app.services.canon_traversal_evidence import CanonTraversalEvidence
            evidence = await repo.get_canon_traversal_evidence(
                ride_id=ride["id"], ride_hash_hex=parsed.ride_hash_hex,
                ride_parser_version=parsed.ride_parser_version, evidence_version="canon_traversal_evidence_v1")
            verified = CanonTraversalEvidence.from_row(evidence)
            if (str(verified.ride_id) != str(ride["id"]) or verified.ride_hash_hex != parsed.ride_hash_hex
                    or verified.ride_parser_version != parsed.ride_parser_version):
                raise ValueError("canonical pattern evidence identity mismatch")
            patterns = await repo.training_climb_patterns(ride["id"])
            efforts = await asyncio.to_thread(
                build_effort_rows, parsed._native_activity, patterns, ride["training_inputs"]
            )
            if efforts:
                await repo.store_climb_efforts(
                    ride["id"], ride["user_id"], ride["training_inputs"], efforts
                )
            counts["scored"] += len(efforts)
        except Exception:
            logger.exception("Effort backfill failed for ride %s", ride.get("id"))
            counts["failed"] += 1  # no rider measurements or raw files in logs
    return counts


async def main(args):
    from app.repositories.base import get_supabase_client
    from app.repositories.ride import RideRepository
    from app.services.file_storage import FileStorageService
    import workout_parse as wp

    repo = RideRepository(get_supabase_client())
    storage = FileStorageService(repo.client)
    counts = dict(eligible=0, scored=0, unavailable=0, skipped=0, failed=0)
    offset = 0

    async def parse(ride):
        data = await storage.download_ride_file(ride["raw_file_path"])
        def checked_parse():
            version = ride["ride_parser_version"]
            if not isinstance(version, int) or not ride.get("ride_hash_hex"):
                raise ValueError("missing retained parser identity")
            activity = wp.parse_file_bytes(data, ride["file_type"] or "auto", parser_version=version)
            return SimpleNamespace(_native_activity=activity, ride_parser_version=version,
                                   ride_hash_hex=wp.hash_canonical_ride(activity, parser_version=version))
        return await asyncio.to_thread(checked_parse)

    while True:
        def query():
            q = repo.client.table("rides").select(
                "id,user_id,training_inputs,raw_file_path,file_type,processing_status,ride_hash_hex,ride_parser_version"
            )
            if args.user_id:
                q = q.eq("user_id", str(args.user_id))
            return q.order("id").range(offset, offset + 499).execute()
        rides = (await repo._run(query)).data or []
        batch = await backfill(repo, rides, parse, apply=args.apply)
        for key in counts:
            counts[key] += batch[key]
        if len(rides) < 500:
            break
        offset += 500
    print(json.dumps({"apply": args.apply, **counts}, sort_keys=True))
    if counts["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    from uuid import UUID

    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--user-id", type=UUID)
    scope.add_argument("--all", action="store_true")
    parser.add_argument("--apply", action="store_true")
    asyncio.run(main(parser.parse_args()))
