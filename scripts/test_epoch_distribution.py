#!/usr/bin/env python3
"""
Test Epoch Distribution Flow

This script tests the epoch distribution system end-to-end on devnet.

Usage:
    # Check current epoch status
    python scripts/test_epoch_distribution.py status

    # Trigger epoch processing (requires admin auth)
    python scripts/test_epoch_distribution.py trigger --token YOUR_JWT

    # Full dry run - shows what would happen without executing
    python scripts/test_epoch_distribution.py dry-run

    # Create test data for demo
    python scripts/test_epoch_distribution.py setup-demo

Prerequisites:
    - Backend running locally or staging URL configured
    - Admin JWT token for trigger operations
    - SUPABASE_URL and SUPABASE_SERVICE_KEY for direct DB access
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

import httpx

# Add backend to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

API_BASE = os.getenv("API_BASE", "http://localhost:8000")
STAGING_API = "https://api.boulderroller.xyz"


def get_headers(token: Optional[str] = None) -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def check_status(api_base: str, token: Optional[str] = None) -> Dict[str, Any]:
    """Check epoch status via API."""
    async with httpx.AsyncClient() as client:
        # Try public epoch info first
        try:
            resp = await client.get(f"{api_base}/distributions/epoch/current")
            if resp.status_code == 200:
                public_data = resp.json()
                print("\n📊 Public Epoch Info:")
                print(f"   Current Epoch: {public_data.get('current_epoch')}")
                print(f"   Ends At: {public_data.get('ends_at')}")
        except Exception as e:
            print(f"   (Could not fetch public epoch info: {e})")

        # Try admin status if token provided
        if token:
            try:
                resp = await client.get(
                    f"{api_base}/admin/epoch/status",
                    headers=get_headers(token)
                )
                if resp.status_code == 200:
                    data = resp.json()
                    print("\n🔐 Admin Epoch Status:")
                    print(f"   Current Epoch: {data.get('current_epoch')}")
                    print(f"   Stored Epoch: {data.get('stored_epoch')}")
                    print(f"   Needs Transition: {data.get('epoch_needs_transition')}")
                    print(f"   Is Points Period: {data.get('is_points_period')}")
                    print(f"   Pending Distributions: {data.get('pending_distributions')}")
                    print(f"   Pending DUNG Total: {data.get('pending_dung_total')}")
                    print(f"   Recently Completed: {data.get('recently_completed')}")
                    return data
                else:
                    print(f"   Admin status failed: {resp.status_code} - {resp.text}")
            except Exception as e:
                print(f"   Admin status error: {e}")

        return {}


async def trigger_epoch(api_base: str, token: str) -> bool:
    """Trigger epoch processing via admin API."""
    print("\n⚡ Triggering epoch processing...")

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{api_base}/admin/epoch/process",
                headers=get_headers(token),
                timeout=60.0  # Long timeout for distribution processing
            )

            if resp.status_code == 200:
                data = resp.json()
                print("\n✅ Epoch processing completed:")
                print(f"   Transitioned: {data.get('transitioned')}")
                print(f"   Distributions Processed: {data.get('processed')}")
                return True
            else:
                print(f"\n❌ Failed: {resp.status_code}")
                print(f"   {resp.text}")
                return False

        except Exception as e:
            print(f"\n❌ Error: {e}")
            return False


async def dry_run_analysis() -> None:
    """Analyze what would happen in an epoch distribution (direct DB access)."""
    print("\n🔍 Dry Run Analysis")
    print("=" * 60)

    try:
        from app.supabase_client import create_backend_supabase_client
        from app.solana_direct import (
            DISTRIBUTION_CONFIG,
            VAULT_CAL_TO_DUNG_THRESHOLD,
            get_current_epoch,
            get_program_settlement_clock,
            load_default_config,
        )

        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_SERVICE_KEY"]
        db = create_backend_supabase_client(url, key)

        # Current epoch
        settlement_clock = await get_program_settlement_clock(load_default_config())
        current_epoch = get_current_epoch(settlement_clock)
        print(f"\n📅 Current Epoch: {current_epoch}")

        # Stored epoch
        epoch_state = db.from_("epoch_state").select("*").limit(1).execute()
        stored_epoch = epoch_state.data[0]["current_epoch"] if epoch_state.data else 0
        print(f"📦 Stored Epoch: {stored_epoch}")
        print(f"🔄 Transition Needed: {current_epoch > stored_epoch}")

        # Points period check
        config = db.from_("points_config").select("*").limit(1).execute()
        is_points_period = config.data[0].get("is_active", True) if config.data else True
        print(f"💰 Points Period Active: {is_points_period}")

        # Eligible vaults
        print("\n📊 Vault Analysis:")
        vaults = db.from_("indexed_vaults").select("id, name, cal_tribute_accumulated").execute()

        eligible_vaults = []
        for v in vaults.data or []:
            cal = Decimal(str(v.get("cal_tribute_accumulated", 0)))
            if cal >= VAULT_CAL_TO_DUNG_THRESHOLD:
                dung = int(cal // VAULT_CAL_TO_DUNG_THRESHOLD)
                eligible_vaults.append({
                    "id": v["id"],
                    "name": v.get("name", "Unknown"),
                    "cal": cal,
                    "dung": dung,
                })

        if eligible_vaults:
            print(f"\n   {len(eligible_vaults)} vaults eligible for distribution:")
            total_cal = Decimal(0)
            total_dung = 0
            for v in eligible_vaults[:10]:  # Show first 10
                print(f"   - Vault {v['id']} ({v['name'][:30]}): {v['cal']} CAL → {v['dung']} DUNG")
                total_cal += v["cal"]
                total_dung += v["dung"]
            if len(eligible_vaults) > 10:
                print(f"   ... and {len(eligible_vaults) - 10} more")

            print(f"\n   Total: {total_cal} CAL → {total_dung} DUNG")

            # Distribution breakdown for total
            leaderboard = int(total_dung * DISTRIBUTION_CONFIG["leaderboard_share_bps"] / 10000)
            stakers = int(total_dung * DISTRIBUTION_CONFIG["staker_share_bps"] / 10000)
            legend = int(total_dung * DISTRIBUTION_CONFIG["local_legend_share_bps"] / 10000)
            pol = int(total_dung * DISTRIBUTION_CONFIG["pol_share_bps"] / 10000)
            protocol = int(total_dung * DISTRIBUTION_CONFIG["protocol_fee_bps"] / 10000)

            print(f"\n   Distribution Breakdown:")
            print(f"   - Leaderboard (55%): {leaderboard} DUNG")
            print(f"   - Stakers (27%): {stakers} DUNG")
            print(f"   - Local Legend (3%): {legend} DUNG")
            print(f"   - POL (5%): {pol} DUNG")
            print(f"   - Protocol (10%): {protocol} DUNG")
        else:
            print("   No vaults eligible for distribution (need >= 1000 CAL)")

        # Pending distributions
        pending = db.from_("epoch_distributions").select("*").eq("status", "pending").execute()
        if pending.data:
            print(f"\n⏳ {len(pending.data)} pending distributions in queue")
        else:
            print("\n✅ No pending distributions")

    except ImportError as e:
        print(f"\n❌ Import error: {e}")
        print("   Make sure you're running from the project root with backend in PYTHONPATH")
    except KeyError as e:
        print(f"\n❌ Missing environment variable: {e}")
        print("   Set SUPABASE_URL and SUPABASE_SERVICE_KEY")
    except Exception as e:
        print(f"\n❌ Error: {e}")


async def setup_demo_data() -> None:
    """Create test vaults and stakes for demo purposes."""
    print("\n🎬 Setting Up Demo Data")
    print("=" * 60)

    try:
        from app.supabase_client import create_backend_supabase_client

        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_SERVICE_KEY"]
        db = create_backend_supabase_client(url, key)

        # Check for existing test vaults
        existing = db.from_("indexed_vaults").select("id").eq("name", "Demo Climb Alpha").execute()
        if existing.data:
            print("\n⚠️  Demo vaults already exist. Skipping creation.")
            print("   To reset, delete vaults with names starting with 'Demo'")
            return

        print("\n📝 This would create demo vaults on devnet.")
        print("   Implementation requires Solana keypair access.")
        print("\n   For now, use the admin UI or Anchor tests to create test vaults.")
        print("\n   Suggested test setup:")
        print("   1. Create 3 vaults with known signatures")
        print("   2. Add CAL tribute (>= 1000) to at least one")
        print("   3. Add stakes from test wallets")
        print("   4. Add leaderboard entries")
        print("   5. Trigger epoch distribution")

    except Exception as e:
        print(f"\n❌ Error: {e}")


def main():
    parser = argparse.ArgumentParser(description="Test epoch distribution system")
    parser.add_argument(
        "command",
        choices=["status", "trigger", "dry-run", "setup-demo"],
        help="Command to run"
    )
    parser.add_argument(
        "--token",
        help="Admin JWT token for authenticated endpoints"
    )
    parser.add_argument(
        "--api",
        default=API_BASE,
        help=f"API base URL (default: {API_BASE})"
    )
    parser.add_argument(
        "--staging",
        action="store_true",
        help="Use staging API instead of local"
    )

    args = parser.parse_args()

    api_base = STAGING_API if args.staging else args.api

    print(f"\n🎯 Boulder Rollers - Epoch Distribution Test")
    print(f"   API: {api_base}")
    print(f"   Time: {datetime.now(timezone.utc).isoformat()}")

    if args.command == "status":
        asyncio.run(check_status(api_base, args.token))

    elif args.command == "trigger":
        if not args.token:
            print("\n❌ --token required for trigger command")
            sys.exit(1)
        asyncio.run(check_status(api_base, args.token))
        asyncio.run(trigger_epoch(api_base, args.token))
        asyncio.run(check_status(api_base, args.token))

    elif args.command == "dry-run":
        asyncio.run(dry_run_analysis())

    elif args.command == "setup-demo":
        asyncio.run(setup_demo_data())

    print("\n✅ Done\n")


if __name__ == "__main__":
    main()
