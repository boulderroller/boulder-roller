from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg2
import pytest

from backend.tests.services.test_settlement_clock_postgres_runtime import (
    _connection,
    postgres_dsn,
)


MIGRATION = Path(__file__).parents[2] / "sql" / "120_exact_credited_settlement_flow.sql"


def _hash(byte: int) -> bytes:
    return bytes([byte]) * 32


def _timestamp(unix_seconds: int) -> datetime:
    return datetime.fromtimestamp(unix_seconds, tz=timezone.utc)


def _bootstrap(cursor: Any) -> None:
    cursor.execute(
        """
        DROP SCHEMA public CASCADE;
        CREATE SCHEMA public;

        CREATE TABLE public.indexed_vaults (
            id BIGINT PRIMARY KEY,
            signature_hex TEXT NOT NULL UNIQUE
        );

        CREATE TABLE public.indexed_events (
            vault_id BIGINT
        );

        CREATE TABLE public.vault_completions (
            id TEXT PRIMARY KEY,
            vault_signature TEXT NOT NULL,
            wallet TEXT NOT NULL,
            activity_id TEXT NOT NULL,
            completed_at TIMESTAMPTZ NOT NULL,
            settlement_week BIGINT NOT NULL,
            chain_confirmation_status TEXT NOT NULL,
            completion_evidence_hash BYTEA,
            on_chain_tx TEXT
        );

        CREATE TABLE public.indexed_epoch_distributions (
            tx_signature TEXT NOT NULL,
            event_index INTEGER NOT NULL,
            vault_id BIGINT NOT NULL,
            epoch BIGINT NOT NULL,
            block_time BIGINT,
            finalized_at TIMESTAMPTZ GENERATED ALWAYS AS (
                CASE WHEN block_time IS NOT NULL THEN to_timestamp(block_time) END
            ) STORED,
            PRIMARY KEY (tx_signature, event_index)
        );

        CREATE TABLE public.rides (
            id TEXT PRIMARY KEY,
            finalized_at TIMESTAMPTZ
        );

        CREATE TABLE public.epoch_distributions (
            id TEXT PRIMARY KEY,
            epoch BIGINT NOT NULL,
            vault_id BIGINT,
            vault_signature TEXT,
            finalized_at TIMESTAMPTZ
        );

        INSERT INTO public.indexed_vaults (id, signature_hex)
        VALUES (99, 'vault-preexisting');
        INSERT INTO public.rides (id, finalized_at)
        VALUES ('ride-preexisting', to_timestamp(777));
        INSERT INTO public.vault_completions (
            id, vault_signature, wallet, activity_id, completed_at,
            settlement_week, chain_confirmation_status,
            completion_evidence_hash, on_chain_tx
        ) VALUES (
            'preexisting-1', 'vault-preexisting', 'rider-1',
            'ride-preexisting', to_timestamp(100), 4,
            'confirmed', decode(repeat('63', 32), 'hex'), 'tx-preexisting'
        );
        """
    )


def _insert_flow(
    cursor: Any,
    *,
    suffix: str,
    vault_id: int,
    evidence_hash: bytes,
    credited_week: int,
    cal_tributed: int = 1000,
) -> None:
    cursor.execute(
        """
        INSERT INTO public.indexed_climb_completion_flows (
            tx_signature, event_index, vault_id, ride_attestation,
            completion_evidence_hash, credited_settlement_week, cal_tributed,
            slot, block_time
        ) VALUES (%s, 0, %s, %s, %s, %s, %s, 500, 900)
        """,
        (
            f"flow-{suffix}",
            vault_id,
            f"attestation-{suffix}",
            evidence_hash,
            credited_week,
            cal_tributed,
        ),
    )


def _ride_finalized_at(cursor: Any, ride_id: str) -> datetime | None:
    cursor.execute("SELECT finalized_at FROM public.rides WHERE id = %s", (ride_id,))
    return cursor.fetchone()[0]


def test_exact_credited_flow_drives_ride_finalization_in_any_trigger_order(
    postgres_dsn: str,
) -> None:
    migration = MIGRATION.read_text(encoding="utf-8")

    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _bootstrap(cursor)
            cursor.execute(migration)
            cursor.execute(
                """
                INSERT INTO public.indexed_events (vault_id)
                VALUES (18446744073709551615)
                RETURNING vault_id::TEXT
                """
            )
            assert cursor.fetchone()[0] == "18446744073709551615"
            assert _ride_finalized_at(cursor, "ride-preexisting") is None
            cursor.execute(
                """
                INSERT INTO public.indexed_vaults (id, signature_hex) VALUES
                    (1, 'vault-1'),
                    (2, 'vault-2');
                INSERT INTO public.rides (id) VALUES
                    ('ride-delayed'),
                    ('ride-same-week'),
                    ('ride-multi'),
                    ('ride-mixed'),
                    ('ride-zero'),
                    ('ride-historical'),
                    ('ride-completion-last');
                INSERT INTO public.vault_completions (
                    id, vault_signature, wallet, activity_id, completed_at,
                    settlement_week, chain_confirmation_status,
                    completion_evidence_hash, on_chain_tx
                ) VALUES
                    ('delayed-1', 'vault-1', 'rider-1', 'ride-delayed',
                        to_timestamp(100), 8, 'confirmed', %s, 'tx-delayed'),
                    ('same-1', 'vault-1', 'rider-1', 'ride-same-week',
                        to_timestamp(200), 10, 'confirmed', %s, 'tx-same'),
                    ('multi-1', 'vault-1', 'rider-1', 'ride-multi',
                        to_timestamp(300), 9, 'confirmed', %s, 'tx-multi-1'),
                    ('multi-2', 'vault-2', 'rider-1', 'ride-multi',
                        to_timestamp(300), 9, 'confirmed', %s, 'tx-multi-2'),
                    ('mixed-positive', 'vault-1', 'rider-1', 'ride-mixed',
                        to_timestamp(300), 9, 'confirmed', %s, 'tx-mixed-positive'),
                    ('mixed-zero', 'vault-2', 'rider-1', 'ride-mixed',
                        to_timestamp(300), 9, 'confirmed', %s, 'tx-mixed-zero'),
                    ('zero-only', 'vault-1', 'rider-1', 'ride-zero',
                        to_timestamp(300), 9, 'confirmed', %s, 'tx-zero-only'),
                    ('historical-1', 'vault-1', 'rider-1', 'ride-historical',
                        to_timestamp(100), 8, 'confirmed', %s, 'tx-historical');
                """,
                (
                    _hash(1),
                    _hash(2),
                    _hash(3),
                    _hash(4),
                    _hash(8),
                    _hash(9),
                    _hash(10),
                    _hash(5),
                ),
            )

            cursor.execute(
                """
                INSERT INTO public.indexed_epoch_distributions (
                    tx_signature, event_index, vault_id, epoch, block_time
                ) VALUES ('distribution-old', 0, 1, 8, 800)
                """
            )
            assert _ride_finalized_at(cursor, "ride-delayed") is None
            assert _ride_finalized_at(cursor, "ride-historical") is None

            _insert_flow(
                cursor,
                suffix="delayed",
                vault_id=1,
                evidence_hash=_hash(1),
                credited_week=10,
            )
            assert _ride_finalized_at(cursor, "ride-delayed") is None

            cursor.execute(
                """
                INSERT INTO public.indexed_epoch_distributions (
                    tx_signature, event_index, vault_id, epoch, block_time
                ) VALUES ('distribution-10', 0, 1, 10, 1000)
                """
            )
            assert _ride_finalized_at(cursor, "ride-delayed") == _timestamp(1000)

            _insert_flow(
                cursor,
                suffix="same",
                vault_id=1,
                evidence_hash=_hash(2),
                credited_week=10,
            )
            assert _ride_finalized_at(cursor, "ride-same-week") == _timestamp(1000)

            _insert_flow(
                cursor,
                suffix="multi-1",
                vault_id=1,
                evidence_hash=_hash(3),
                credited_week=10,
            )
            _insert_flow(
                cursor,
                suffix="multi-2",
                vault_id=2,
                evidence_hash=_hash(4),
                credited_week=11,
            )
            assert _ride_finalized_at(cursor, "ride-multi") is None
            cursor.execute(
                """
                INSERT INTO public.indexed_epoch_distributions (
                    tx_signature, event_index, vault_id, epoch, block_time
                ) VALUES ('distribution-11', 0, 2, 11, 1100)
                """
            )
            assert _ride_finalized_at(cursor, "ride-multi") == _timestamp(1100)

            _insert_flow(
                cursor,
                suffix="mixed-positive",
                vault_id=1,
                evidence_hash=_hash(8),
                credited_week=10,
            )
            _insert_flow(
                cursor,
                suffix="mixed-zero",
                vault_id=2,
                evidence_hash=_hash(9),
                credited_week=12,
                cal_tributed=0,
            )
            _insert_flow(
                cursor,
                suffix="zero-only",
                vault_id=1,
                evidence_hash=_hash(10),
                credited_week=12,
                cal_tributed=0,
            )
            assert _ride_finalized_at(cursor, "ride-mixed") == _timestamp(1000)
            assert _ride_finalized_at(cursor, "ride-zero") is None

            cursor.execute(
                """
                UPDATE public.vault_completions
                SET chain_confirmation_status = 'legacy_unverified'
                WHERE id = 'delayed-1'
                """
            )
            assert _ride_finalized_at(cursor, "ride-delayed") is None
            cursor.execute(
                """
                UPDATE public.vault_completions
                SET chain_confirmation_status = 'confirmed'
                WHERE id = 'delayed-1'
                """
            )
            assert _ride_finalized_at(cursor, "ride-delayed") == _timestamp(1000)

            cursor.execute(
                """
                UPDATE public.indexed_epoch_distributions
                SET epoch = 12
                WHERE tx_signature = 'distribution-10'
                """
            )
            assert _ride_finalized_at(cursor, "ride-delayed") is None
            assert _ride_finalized_at(cursor, "ride-same-week") is None
            assert _ride_finalized_at(cursor, "ride-multi") is None
            assert _ride_finalized_at(cursor, "ride-mixed") is None
            cursor.execute(
                """
                UPDATE public.indexed_epoch_distributions
                SET epoch = 10
                WHERE tx_signature = 'distribution-10'
                """
            )
            assert _ride_finalized_at(cursor, "ride-delayed") == _timestamp(1000)
            assert _ride_finalized_at(cursor, "ride-multi") == _timestamp(1100)
            assert _ride_finalized_at(cursor, "ride-mixed") == _timestamp(1000)

            cursor.execute(
                """
                DELETE FROM public.indexed_epoch_distributions
                WHERE tx_signature = 'distribution-10'
                """
            )
            assert _ride_finalized_at(cursor, "ride-delayed") is None
            assert _ride_finalized_at(cursor, "ride-mixed") is None
            cursor.execute(
                """
                INSERT INTO public.indexed_epoch_distributions (
                    tx_signature, event_index, vault_id, epoch, block_time
                ) VALUES ('distribution-10', 0, 1, 10, 1000)
                """
            )
            assert _ride_finalized_at(cursor, "ride-delayed") == _timestamp(1000)
            assert _ride_finalized_at(cursor, "ride-mixed") == _timestamp(1000)

            _insert_flow(
                cursor,
                suffix="wrong-vault",
                vault_id=2,
                evidence_hash=_hash(7),
                credited_week=11,
            )
            cursor.execute(
                """
                UPDATE public.vault_completions
                SET completion_evidence_hash = %s
                WHERE id = 'delayed-1'
                """,
                (_hash(7),),
            )
            assert _ride_finalized_at(cursor, "ride-delayed") is None
            cursor.execute(
                """
                UPDATE public.vault_completions
                SET completion_evidence_hash = %s
                WHERE id = 'delayed-1'
                """,
                (_hash(1),),
            )
            assert _ride_finalized_at(cursor, "ride-delayed") == _timestamp(1000)

            _insert_flow(
                cursor,
                suffix="completion-last",
                vault_id=1,
                evidence_hash=_hash(6),
                credited_week=10,
            )
            cursor.execute(
                """
                INSERT INTO public.vault_completions (
                    id, vault_signature, wallet, activity_id, completed_at,
                    settlement_week, chain_confirmation_status,
                    completion_evidence_hash, on_chain_tx
                ) VALUES (
                    'completion-last-1', 'vault-1', 'rider-1',
                    'ride-completion-last', to_timestamp(400), 7,
                    'confirmed', %s, 'tx-completion-last'
                )
                """,
                (_hash(6),),
            )
            assert _ride_finalized_at(cursor, "ride-completion-last") == _timestamp(1000)

            cursor.execute(
                """
                UPDATE public.indexed_epoch_distributions
                SET block_time = block_time
                WHERE tx_signature = 'distribution-10';
                UPDATE public.indexed_climb_completion_flows
                SET indexed_at = now()
                WHERE tx_signature = 'flow-delayed';
                """
            )
            assert _ride_finalized_at(cursor, "ride-delayed") == _timestamp(1000)
            assert _ride_finalized_at(cursor, "ride-historical") is None

            with pytest.raises(psycopg2.Error, match="immutable completion-flow evidence"):
                cursor.execute(
                    """
                    UPDATE public.indexed_climb_completion_flows
                    SET credited_settlement_week = 12
                    WHERE tx_signature = 'flow-delayed'
                    """
                )
