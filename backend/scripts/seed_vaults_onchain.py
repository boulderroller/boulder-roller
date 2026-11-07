#!/usr/bin/env python3
"""Retired generation-1 vault seeding entrypoint.

The former script copied mutable database projections into permanent on-chain
completion and leaderboard state, then activated the vault with generation 1.
That path is not reward-authoritative and must not be revived. V4-B deployment
uses a fresh program and a canonical climb seeder; a future historical import
would require the separately ratified sealed generation-2 manifest contract.
"""

from __future__ import annotations

import asyncio


async def seed_and_activate_vault(
    db_client,
    config,
    vault_row: dict,
    dry_run: bool = False,
    force_reseed: bool = False,
):
    """Reject every invocation of the retired generation-1 writer."""
    raise RuntimeError(
        "legacy generation-1 vault seeding is disabled: use the canonical "
        "V4-B climb seeder or a ratified generation-2 manifest path"
    )


async def main() -> None:
    raise RuntimeError(
        "legacy generation-1 vault seeding is disabled: use the canonical "
        "V4-B climb seeder or a ratified generation-2 manifest path"
    )


if __name__ == "__main__":
    asyncio.run(main())
