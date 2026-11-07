#!/usr/bin/env python3
"""
Epoch Distribution Crank

Standalone CLI script for running settlement distributions via cron job.
FastAPI may run the background processor every 60 seconds; this cron path is a
safety net and uses the same database-backed processor lease as the background
loop and admin trigger.

Usage:
    # Single run (process any pending distributions)
    python scripts/epoch_crank.py

    # Check status without processing
    python scripts/epoch_crank.py --status

    # Force process all pending (skip epoch transition check)
    python scripts/epoch_crank.py --force

    # Dry run (show what would be processed)
    python scripts/epoch_crank.py --dry-run

Cron Setup (recommended):
    # Run every 15 minutes as safety net
    */15 * * * * cd /root/boulder-repo/backend && /root/boulder-repo/backend/venv/bin/python scripts/epoch_crank.py >> /var/log/epoch_crank.log 2>&1

    # Or for production, run every hour
    0 * * * * cd /root/boulder-repo/backend && /root/boulder-repo/backend/venv/bin/python scripts/epoch_crank.py >> /var/log/epoch_crank.log 2>&1

Environment:
    Requires SUPABASE_URL and SUPABASE_SERVICE_KEY environment variables.
    Load from .env file or set in cron environment.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

from app.supabase_client import create_backend_supabase_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def get_supabase_client():
    """Create Supabase client from environment."""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")

    if not url or not key:
        logger.error("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY")
        sys.exit(1)

    return create_backend_supabase_client(url, key)


async def get_status(supabase) -> dict:
    """Get current epoch state and pending distributions."""
    from app.services.epoch_processor import get_epoch_processor

    processor = get_epoch_processor(supabase)

    # Current epoch info
    settlement_clock = await processor._load_settlement_clock()
    current_epoch = settlement_clock.week_at(int(datetime.now(timezone.utc).timestamp()))
    stored_epoch = await processor.get_stored_epoch()

    # Durable state-machine jobs. Legacy epoch_distributions rows are imported
    # into reconciliation and are never executed directly.
    active_states = ["ready", "leased", "submitted", "reconciling", "retry_wait"]
    pending_resp = supabase.table("settlement_jobs") \
        .select("id, vault_signature, settlement_week, state, dung_to_mint") \
        .in_("state", active_states) \
        .order("created_at") \
        .execute()
    pending = pending_resp.data or []

    # Recently completed
    completed_resp = supabase.table("settlement_jobs") \
        .select("id, vault_signature, settlement_week, state, dung_to_mint, confirmed_at") \
        .eq("state", "confirmed") \
        .order("confirmed_at", desc=True) \
        .limit(10) \
        .execute()
    completed = completed_resp.data or []

    return {
        "current_epoch": current_epoch,
        "stored_epoch": stored_epoch,
        "epoch_needs_transition": current_epoch > stored_epoch,
        "is_points_period": False,
        "pending_distributions": len(pending),
        "pending_dung_total": sum(int(d.get("dung_to_mint", 0)) for d in pending),
        "pending_details": pending[:5],  # Show first 5
        "recent_completed": len(completed),
        "recent_details": completed[:5],
    }


async def run_crank(supabase, force: bool = False, dry_run: bool = False) -> dict:
    """Run the epoch crank."""
    from app.services.epoch_processor import get_epoch_processor

    processor = get_epoch_processor(supabase)

    results = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "transitioned": False,
        "distributions_processed": 0,
        "dry_run": dry_run,
    }

    if dry_run:
        status = await get_status(supabase)
        results["would_transition"] = status["epoch_needs_transition"]
        results["would_process"] = status["pending_distributions"]
        results["pending_dung"] = status["pending_dung_total"]
        logger.info(f"[DRY RUN] Would transition: {status['epoch_needs_transition']}")
        logger.info(f"[DRY RUN] Would process {status['pending_distributions']} distributions")
        return results

    transitioned, processed = await processor.process_settlement_cycle(force=force)
    results["distributions_processed"] = processed
    results["transitioned"] = transitioned

    if processed > 0:
        logger.info(f"[EpochCrank] Processed {processed} distributions")
    else:
        logger.info("[EpochCrank] No pending distributions to process")

    results["completed_at"] = datetime.now(timezone.utc).isoformat()
    return results


def print_status(status: dict):
    """Pretty print status."""
    print("\n=== EPOCH CRANK STATUS ===")
    print(f"Current Epoch:     {status['current_epoch']}")
    print(f"Stored Epoch:      {status['stored_epoch']}")
    print(f"Needs Transition:  {'YES' if status['epoch_needs_transition'] else 'No'}")
    print(f"Points Period:     {'Active' if status['is_points_period'] else 'Inactive'}")
    print(f"\nPending Distributions: {status['pending_distributions']}")
    print(f"Pending DUNG Total:    {status['pending_dung_total']}")

    if status["pending_details"]:
        print("\nPending (first 5):")
        for d in status["pending_details"]:
            print(f"  - Week {d['settlement_week']}: vault {d['vault_signature'][:16]}... ({d['dung_to_mint']} DUNG)")

    if status["recent_details"]:
        print(f"\nRecently Completed: {status['recent_completed']}")
        for d in status["recent_details"]:
            print(f"  - Week {d['settlement_week']}: vault {d['vault_signature'][:16]}... ({d['dung_to_mint']} DUNG)")

    print()


def print_results(results: dict):
    """Pretty print crank results."""
    print("\n=== EPOCH CRANK RESULTS ===")
    if results.get("dry_run"):
        print("[DRY RUN MODE]")
        print(f"Would Transition:  {'Yes' if results.get('would_transition') else 'No'}")
        print(f"Would Process:     {results.get('would_process', 0)} distributions")
        print(f"Pending DUNG:      {results.get('pending_dung', 0)}")
    else:
        print(f"Transitioned:      {'Yes' if results.get('transitioned') else 'No'}")
        print(f"Processed:         {results.get('distributions_processed', 0)} distributions")
        print(f"Started:           {results.get('started_at')}")
        print(f"Completed:         {results.get('completed_at')}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Run epoch distribution crank",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current status without processing",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force process all pending distributions (skip epoch transition check)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be processed without actually processing",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Minimal output (for cron)",
    )

    args = parser.parse_args()

    if args.quiet:
        logging.getLogger().setLevel(logging.WARNING)

    supabase = get_supabase_client()

    if args.status:
        status = asyncio.run(get_status(supabase))
        print_status(status)
    else:
        results = asyncio.run(run_crank(supabase, force=args.force, dry_run=args.dry_run))
        if not args.quiet:
            print_results(results)

        # Exit code based on results
        if results.get("distributions_processed", 0) > 0 or results.get("transitioned"):
            sys.exit(0)  # Success with work done
        else:
            sys.exit(0)  # Success with no work (normal)


if __name__ == "__main__":
    main()
