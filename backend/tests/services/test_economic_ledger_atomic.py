from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest

from backend.app.services.economic_ledger import (
    EconomicLedgerService,
    canonical_ledger_decimal,
    compute_event_hash_v2,
)


class _RpcCall:
    def __init__(self, data: list[dict[str, object]]) -> None:
        self._data = data

    def execute(self) -> SimpleNamespace:
        return SimpleNamespace(data=self._data)


class _Supabase:
    def __init__(self, row: dict[str, object]) -> None:
        self.row = row
        self.calls: list[tuple[str, dict[str, object]]] = []

    def rpc(self, name: str, params: dict[str, object]) -> _RpcCall:
        self.calls.append((name, params))
        return _RpcCall([self.row])

    def table(self, _name: str) -> None:
        raise AssertionError("ledger writes must not use direct table inserts")


class _Query:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def select(self, *_args: object) -> "_Query":
        return self

    def eq(self, *_args: object) -> "_Query":
        return self

    def order(self, *_args: object, **_kwargs: object) -> "_Query":
        return self

    def limit(self, *_args: object) -> "_Query":
        return self

    def execute(self) -> SimpleNamespace:
        return SimpleNamespace(data=self.rows)


class _ReadSupabase:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def table(self, name: str) -> _Query:
        assert name == "economic_events"
        return _Query(self.rows)


def _row() -> dict[str, object]:
    return {
        "id": 9,
        "event_uuid": "a1d9a360-551d-4078-8447-12d1c82ea522",
        "event_type": "TSS_EARN",
        "wallet": "wallet-exact",
        "counterparty": None,
        "amount": "9007199254740993.000000001",
        "denomination": "CAL",
        "balance_after": "9007199254740993.000000001",
        "caused_by_id": None,
        "batch_id": None,
        "pipeline_version_id": 7,
        "reference_type": "ride",
        "reference_id": "ride-1",
        "valid_at": "2026-07-14T16:30:00.123456+00:00",
        "recorded_at": "2026-07-14T16:30:01.000000+00:00",
        "reversal_of_id": None,
        "is_reversed": False,
        "evidence": {"source": "test"},
        "prev_hash": None,
        "event_hash": "f" * 64,
        "hash_version": 2,
    }


def test_record_event_sends_exact_decimal_text_to_atomic_rpc() -> None:
    supabase = _Supabase(_row())
    service = EconomicLedgerService(supabase)  # type: ignore[arg-type]
    valid_at = datetime(2026, 7, 14, 16, 30, 0, 123456, tzinfo=timezone.utc)

    event = asyncio.run(
        service.record_event(
            wallet="wallet-exact",
            event_type="TSS_EARN",
            amount=Decimal("9007199254740993.000000001"),
            denomination="CAL",
            valid_at=valid_at,
            pipeline_version_id=7,
            reference_type="ride",
            reference_id="ride-1",
            evidence={"source": "test"},
        )
    )

    assert supabase.calls == [
        (
            "append_economic_event",
            {
                "p_wallet": "wallet-exact",
                "p_event_type": "TSS_EARN",
                "p_amount": "9007199254740993.000000001",
                "p_denomination": "CAL",
                "p_valid_at": "2026-07-14T16:30:00.123456+00:00",
                "p_pipeline_version_id": 7,
                "p_caused_by_id": None,
                "p_batch_id": None,
                "p_reference_type": "ride",
                "p_reference_id": "ride-1",
                "p_counterparty": None,
                "p_reversal_of_id": None,
                "p_evidence": {"source": "test"},
            },
        )
    ]
    assert event.event_uuid == UUID("a1d9a360-551d-4078-8447-12d1c82ea522")
    assert event.amount == Decimal("9007199254740993.000000001")
    assert event.balance_after == Decimal("9007199254740993.000000001")
    assert event.hash_version == 2


def test_v2_hash_canonicalizes_scale_and_negative_zero() -> None:
    valid_at = datetime(2026, 7, 14, 16, 30, 0, 123456, tzinfo=timezone.utc)
    first = compute_event_hash_v2(
        wallet="wallet-exact",
        event_type="TSS_EARN",
        denomination="CAL",
        amount=Decimal("1.2300"),
        balance_after=Decimal("1.230000"),
        valid_at=valid_at,
        prev_hash=None,
    )
    second = compute_event_hash_v2(
        wallet="wallet-exact",
        event_type="TSS_EARN",
        denomination="CAL",
        amount=Decimal("1.23"),
        balance_after=Decimal("1.23"),
        valid_at=valid_at,
        prev_hash=None,
    )

    assert first == second
    assert canonical_ledger_decimal(Decimal("-0.000")) == "0"
    assert canonical_ledger_decimal(Decimal("0.000000001")) == "0.000000001"
    with pytest.raises(ValueError, match="finite"):
        canonical_ledger_decimal(Decimal("NaN"))
    with pytest.raises(TypeError, match="never float"):
        canonical_ledger_decimal(1.25)  # type: ignore[arg-type]


def test_hash_chain_verifier_dispatches_v2_contract() -> None:
    valid_at = datetime(2026, 7, 14, 16, 30, 0, 123456, tzinfo=timezone.utc)
    event_hash = compute_event_hash_v2(
        wallet="wallet-exact",
        event_type="TSS_EARN",
        denomination="CAL",
        amount=Decimal("1.2300"),
        balance_after=Decimal("1.230000"),
        valid_at=valid_at,
        prev_hash=None,
    )
    service = EconomicLedgerService(  # type: ignore[arg-type]
        _ReadSupabase(
            [
                {
                    "id": 1,
                    "event_type": "TSS_EARN",
                    "wallet": "wallet-exact",
                    "denomination": "CAL",
                    "amount": "1.2300",
                    "balance_after": "1.230000",
                    "valid_at": valid_at.isoformat(),
                    "prev_hash": None,
                    "event_hash": event_hash,
                    "hash_version": 2,
                }
            ]
        )
    )

    assert asyncio.run(service.verify_hash_chain("wallet-exact")) == {
        "valid": True,
        "events_checked": 1,
        "first_broken_id": None,
        "error": None,
    }
