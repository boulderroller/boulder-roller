#!/usr/bin/env python3
"""Run after migration 168 + matching API/native deployment; dry-run by default.

PYTHONPATH=backend python backend/scripts/backfill_training_metrics.py --user-id UUID
Add --apply to replay, --force to reverify the current version. --all is explicit.
--force-terminal explicitly retries permanent failures; payment fences still apply.
Never invokes reprocess, Threshold sealing, attestation or economic recovery.
"""

import argparse
import asyncio
import json
from datetime import datetime
from app.repositories.base import get_supabase_client
from app.repositories.ride import RideRepository
from app.services.file_storage import FileStorageService
from app.services.training_backfill import backfill_training
from app.services.training_metrics import ENGINE_VERSION
from app.services.training_eligibility import is_training_eligible
from app.services.workout_parse_adapter import parse_ride_file_bytes_rust


def payment_phases_finished(ride):
    """Match claim_training_replay; old phase-3 stamps do not finish a retry."""
    if not is_training_eligible(ride):
        return False
    attempt = ride.get("training_pay_attempts")
    if attempt:
        return (
            not attempt["active"]
            and all(
                attempt.get(field) == ride.get(field)
                for field in ("phase1_completed_at", "phase2_completed_at")
            )
            and (
                not attempt.get("phase3_completed_at")
                or (
                    ride.get("phase3_completed_at")
                    and datetime.fromisoformat(
                        ride["phase3_completed_at"].replace("Z", "+00:00")
                    )
                    >= datetime.fromisoformat(
                        attempt["phase3_completed_at"].replace("Z", "+00:00")
                    )
                )
            )
        )
    if ride["processing_status"] == "completed":
        return True
    if ride["processing_status"] != "under_review" or not ride.get(
        "phase3_completed_at"
    ):
        return False
    phase3 = datetime.fromisoformat(ride["phase3_completed_at"].replace("Z", "+00:00"))
    return all(
        phase3 >= datetime.fromisoformat(ride[field].replace("Z", "+00:00"))
        for field in ("phase1_completed_at", "phase2_completed_at")
        if ride.get(field)
    )


async def main(args):
    repo = RideRepository(get_supabase_client())
    storage = FileStorageService(repo.client)
    # Stable pagination first; updates cannot move rows across job pages.
    rides = []
    offset = 0
    while True:

        def query():
            q = repo.client.table("rides").select(
                "id,user_id,started_at,raw_file_path,file_type,training_metrics,training_error,"
                "processing_status,phase1_completed_at,phase2_completed_at,phase3_completed_at,"
                "training_pay_attempts(*),training_replay_state(error_class,terminal_engine_version)"
            )
            if args.user_id:
                q = q.eq("user_id", args.user_id)
            return (
                q.order("started_at")
                .order("id")
                .range(offset, offset + 499)
                .execute()
            )

        rows = (await repo._run(query)).data or []
        rides.extend(rows)
        if len(rows) < 500:
            break
        offset += 500

    async def parse(ride):
        raw = await storage.download_ride_file(ride["raw_file_path"])
        return await asyncio.to_thread(
            parse_ride_file_bytes_rust, raw, ride.get("file_type") or "auto"
        )

    ready = [ride for ride in rides if payment_phases_finished(ride)]
    result = await backfill_training(
        repo, ready, parse, apply=args.apply, force=args.force,
        force_terminal=args.force_terminal,
    )
    result["skipped"] += len(rides) - len(ready)
    print(
        json.dumps({"apply": args.apply, "engine_version": ENGINE_VERSION, **result}, sort_keys=True)
    )
    if result["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--user-id")
    group.add_argument("--all", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--force-terminal", action="store_true", help="Retry terminal failures; never bypass eligibility or payment fences")
    asyncio.run(main(p.parse_args()))
