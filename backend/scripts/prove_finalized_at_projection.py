#!/usr/bin/env python3
"""Prove finalized_at settlement projection semantics against Postgres.

This is a non-destructive v1 compatibility smoke gate for BACKEND_TRUTHS §3.3.
Current versioned-clock behavior is proved by
tests/services/test_settlement_clock_postgres_runtime.py against migration 119.

The proof runs inside a transaction-scoped scratch schema:
  1. Create minimal tables required by migration 089.
  2. Install backend/sql/089_finalized_at_settlement_projection.sql.
  3. Insert synthetic chain-completion and distribution projection rows.
  4. Assert finalized_at is generated from block_time and propagated by DB
     triggers to epoch_distributions and rides.
  5. Roll back the whole transaction.

No production rows are inserted, updated, or deleted.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from pathlib import Path
from typing import Optional

import asyncpg


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = REPO_ROOT / "backend" / "sql" / "089_finalized_at_settlement_projection.sql"
LEGACY_SETTLEMENT_WEEK_ANCHOR = 1_704_020_400
SETTLEMENT_WEEK_SECONDS = 604_800


class RollbackProof(Exception):
    """Raised intentionally so the proof transaction always rolls back."""


def _load_backend_env() -> None:
    """Load backend/.env enough for DATABASE_URL without printing secrets."""
    env_path = REPO_ROOT / "backend" / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _settlement_week(completed_at_epoch: int) -> int:
    return (
        completed_at_epoch - LEGACY_SETTLEMENT_WEEK_ANCHOR
    ) // SETTLEMENT_WEEK_SECONDS


def _read_migration() -> str:
    if not MIGRATION_PATH.exists():
        raise FileNotFoundError(f"Missing migration: {MIGRATION_PATH}")
    return MIGRATION_PATH.read_text(encoding="utf-8")


async def _create_minimal_schema(conn: asyncpg.Connection, schema: str) -> None:
    await conn.execute(f'CREATE SCHEMA "{schema}"')
    await conn.execute(f'SET LOCAL search_path = "{schema}", public')
    await conn.execute(
        """
        CREATE TABLE rides (
            id UUID PRIMARY KEY,
            finalized_at TIMESTAMPTZ NULL
        );

        CREATE TABLE indexed_vaults (
            id BIGINT PRIMARY KEY,
            signature_hex TEXT NOT NULL
        );

        CREATE TABLE vault_completions (
            vault_signature TEXT NOT NULL,
            activity_id TEXT NOT NULL,
            completed_at TIMESTAMPTZ NOT NULL,
            on_chain_tx TEXT,
            on_chain_tx_error TEXT
        );

        CREATE TABLE epoch_distributions (
            id UUID PRIMARY KEY,
            epoch INTEGER NOT NULL,
            vault_signature TEXT NOT NULL,
            vault_id BIGINT,
            finalized_at TIMESTAMPTZ NULL
        );

        CREATE TABLE indexed_epoch_distributions (
            tx_signature TEXT NOT NULL,
            event_index INTEGER NOT NULL,
            vault_id BIGINT NOT NULL,
            epoch BIGINT NOT NULL,
            block_time BIGINT,
            PRIMARY KEY (tx_signature, event_index)
        );
        """
    )


async def _assert_finalized_epoch(
    conn: asyncpg.Connection,
    *,
    vault_id: int,
    epoch: int,
    block_time: int,
) -> None:
    row = await conn.fetchrow(
        """
        SELECT
            EXTRACT(EPOCH FROM finalized_at)::BIGINT AS finalized_epoch
        FROM indexed_epoch_distributions
        WHERE vault_id = $1 AND epoch = $2
        """,
        vault_id,
        epoch,
    )
    assert row, f"missing indexed_epoch_distributions row for vault={vault_id}"
    assert row["finalized_epoch"] == block_time, (
        "indexed_epoch_distributions.finalized_at must be GENERATED from "
        f"block_time={block_time}, got epoch={row['finalized_epoch']}"
    )


async def _assert_ride_finalized(
    conn: asyncpg.Connection,
    *,
    ride_id: uuid.UUID,
    expected_block_time: Optional[int],
) -> None:
    row = await conn.fetchrow(
        "SELECT EXTRACT(EPOCH FROM finalized_at)::BIGINT AS finalized_epoch "
        "FROM rides WHERE id = $1",
        ride_id,
    )
    assert row, f"missing ride row {ride_id}"
    assert row["finalized_epoch"] == expected_block_time, (
        f"rides.finalized_at drift for ride={ride_id}: "
        f"expected epoch {expected_block_time}, got {row['finalized_epoch']}"
    )


async def _assert_legacy_distribution_finalized(
    conn: asyncpg.Connection,
    *,
    vault_id: int,
    epoch: int,
    expected_block_time: int,
) -> None:
    row = await conn.fetchrow(
        """
        SELECT EXTRACT(EPOCH FROM finalized_at)::BIGINT AS finalized_epoch
        FROM epoch_distributions
        WHERE vault_id = $1 AND epoch = $2
        """,
        vault_id,
        epoch,
    )
    assert row, f"missing epoch_distributions row for vault={vault_id}"
    assert row["finalized_epoch"] == expected_block_time, (
        "epoch_distributions.finalized_at must mirror chain-derived "
        f"block_time={expected_block_time}, got {row['finalized_epoch']}"
    )


async def _insert_vault(conn: asyncpg.Connection, vault_id: int) -> str:
    signature = f"{vault_id:0128x}"[-128:]
    await conn.execute(
        "INSERT INTO indexed_vaults (id, signature_hex) VALUES ($1, $2)",
        vault_id,
        signature,
    )
    return signature


async def _insert_ride_completion(
    conn: asyncpg.Connection,
    *,
    ride_id: uuid.UUID,
    vault_signature: str,
    completed_at_epoch: int,
    tx: str,
) -> None:
    await conn.execute("INSERT INTO rides (id) VALUES ($1)", ride_id)
    await conn.execute(
        """
        INSERT INTO vault_completions (
            vault_signature,
            activity_id,
            completed_at,
            on_chain_tx
        ) VALUES ($1, $2, to_timestamp($3), $4)
        """,
        vault_signature,
        str(ride_id),
        completed_at_epoch,
        tx,
    )


async def _insert_distribution_projection(
    conn: asyncpg.Connection,
    *,
    vault_id: int,
    vault_signature: str,
    epoch: int,
    block_time: int,
    event_index: int,
) -> None:
    await conn.execute(
        """
        INSERT INTO epoch_distributions (
            id,
            epoch,
            vault_signature,
            vault_id
        ) VALUES ($1, $2, $3, $4)
        """,
        uuid.uuid4(),
        epoch,
        vault_signature,
        vault_id,
    )
    await conn.execute(
        """
        INSERT INTO indexed_epoch_distributions (
            tx_signature,
            event_index,
            vault_id,
            epoch,
            block_time
        ) VALUES ($1, $2, $3, $4, $5)
        """,
        f"proof_tx_{vault_id}_{event_index}",
        event_index,
        vault_id,
        epoch,
        block_time,
    )


async def run(database_url: str) -> None:
    schema = "br_finalized_at_proof_" + uuid.uuid4().hex[:12]
    conn = await asyncpg.connect(database_url)
    try:
        async with conn.transaction():
            await conn.execute("SET LOCAL statement_timeout = '20s'")
            await _create_minimal_schema(conn, schema)
            await conn.execute(_read_migration())

            completed_at_epoch = 1_776_000_000
            settlement_week = _settlement_week(completed_at_epoch)
            block_time_1 = 1_776_604_800
            block_time_2 = 1_776_605_400

            # Case 1: completion exists first; distribution event finalizes it.
            ride_a = uuid.uuid4()
            sig_101 = await _insert_vault(conn, 101)
            await _insert_ride_completion(
                conn,
                ride_id=ride_a,
                vault_signature=sig_101,
                completed_at_epoch=completed_at_epoch,
                tx="proof_completion_a",
            )
            await _insert_distribution_projection(
                conn,
                vault_id=101,
                vault_signature=sig_101,
                epoch=settlement_week,
                block_time=block_time_1,
                event_index=1,
            )
            await _assert_finalized_epoch(
                conn,
                vault_id=101,
                epoch=settlement_week,
                block_time=block_time_1,
            )
            await _assert_legacy_distribution_finalized(
                conn,
                vault_id=101,
                epoch=settlement_week,
                expected_block_time=block_time_1,
            )
            await _assert_ride_finalized(
                conn,
                ride_id=ride_a,
                expected_block_time=block_time_1,
            )

            # Case 2: distribution exists first; later completion backfills.
            ride_b = uuid.uuid4()
            sig_202 = await _insert_vault(conn, 202)
            await _insert_distribution_projection(
                conn,
                vault_id=202,
                vault_signature=sig_202,
                epoch=settlement_week,
                block_time=block_time_2,
                event_index=2,
            )
            await _insert_ride_completion(
                conn,
                ride_id=ride_b,
                vault_signature=sig_202,
                completed_at_epoch=completed_at_epoch,
                tx="proof_completion_b",
            )
            await _assert_ride_finalized(
                conn,
                ride_id=ride_b,
                expected_block_time=block_time_2,
            )

            # Case 3: multi-vault ride locks only after all completions settle.
            ride_c = uuid.uuid4()
            sig_303 = await _insert_vault(conn, 303)
            sig_404 = await _insert_vault(conn, 404)
            await conn.execute("INSERT INTO rides (id) VALUES ($1)", ride_c)
            await conn.execute(
                """
                INSERT INTO vault_completions (
                    vault_signature,
                    activity_id,
                    completed_at,
                    on_chain_tx
                ) VALUES
                    ($1, $2, to_timestamp($3), 'proof_completion_c1'),
                    ($4, $2, to_timestamp($3), 'proof_completion_c2')
                """,
                sig_303,
                str(ride_c),
                completed_at_epoch,
                sig_404,
            )
            await _insert_distribution_projection(
                conn,
                vault_id=303,
                vault_signature=sig_303,
                epoch=settlement_week,
                block_time=block_time_1,
                event_index=3,
            )
            await _assert_ride_finalized(
                conn,
                ride_id=ride_c,
                expected_block_time=None,
            )
            await _insert_distribution_projection(
                conn,
                vault_id=404,
                vault_signature=sig_404,
                epoch=settlement_week,
                block_time=block_time_2,
                event_index=4,
            )
            await _assert_ride_finalized(
                conn,
                ride_id=ride_c,
                expected_block_time=block_time_2,
            )

            raise RollbackProof
    except RollbackProof:
        pass
    finally:
        await conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the finalized_at settlement projection proof."
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Postgres URL. Defaults to DATABASE_URL or backend/.env.",
    )
    return parser.parse_args()


def main() -> int:
    _load_backend_env()
    args = parse_args()
    database_url = args.database_url or os.getenv("DATABASE_URL")
    if not database_url:
        print(
            "DATABASE_URL is not set. Provide --database-url or backend/.env.",
            file=sys.stderr,
        )
        return 2

    asyncio.run(run(database_url))
    print(
        "PASS finalized_at proof: generated block_time column, completion-first "
        "trigger, distribution-first trigger, and multi-vault all-settled rule."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
