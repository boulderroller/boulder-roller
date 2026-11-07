#!/usr/bin/env python3
"""Audit or repair indexed vault geographic v2 reward identities."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

from app.supabase_client import create_backend_supabase_client

from app.services.vault_reward_identity import (
    VaultRewardIdentityError,
    reconcile_vault_reward_identities,
)


def _client_from_environment():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv(
        "SUPABASE_SERVICE_ROLE_KEY"
    )
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and a Supabase service-role key are required"
        )
    return create_backend_supabase_client(url, key)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve every legacy vault key to one global geographic v2 identity. "
            "The default is a read-only dry run."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist verified identities; omitted means dry-run only",
    )
    parser.add_argument("--vault-id", type=int, help="Process one indexed vault")
    parser.add_argument("--limit", type=int, help="Bound the number of vaults scanned")
    args = parser.parse_args()

    try:
        report = reconcile_vault_reward_identities(
            client=_client_from_environment(),
            apply=args.apply,
            vault_id=args.vault_id,
            limit=args.limit,
        )
    except (RuntimeError, VaultRewardIdentityError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2))
        return 2

    payload = {
        "status": "resolved" if not report.failures else "unresolved",
        "mode": "apply" if args.apply else "dry-run",
        **asdict(report),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 1 if report.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
