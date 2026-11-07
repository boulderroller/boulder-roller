"""
Economic Ledger Service: Canonical append-only ledger for all value flows.

This service manages the economic_events table as the source of truth
for all economic activity.

Key features:
- Hash-chain integrity (SHA256 linking each event to its predecessor)
- Bi-temporal timestamps (valid_at vs recorded_at)
- Causality chains (caused_by_id linking related events)
- Multi-denomination support (CAL, DUNG, LP)
- Immutability enforced by DB triggers (UPDATE/DELETE blocked)

See: output/A5_VERIFICATION_DATA_PLATFORM_DESIGN.md, Section 3
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from supabase import Client

from ..utils.postgrest_paging import window

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class EconomicEvent:
    """A recorded economic event from the ledger."""
    id: int
    event_uuid: UUID
    event_type: str
    wallet: str
    counterparty: Optional[str]
    amount: Decimal
    denomination: str
    balance_after: Decimal
    caused_by_id: Optional[int]
    batch_id: Optional[UUID]
    pipeline_version_id: Optional[int]
    reference_type: Optional[str]
    reference_id: Optional[str]
    valid_at: datetime
    recorded_at: datetime
    reversal_of_id: Optional[int]
    is_reversed: bool
    evidence: Optional[Dict[str, Any]]
    prev_hash: Optional[str]
    event_hash: str
    hash_version: int = 1


# ---------------------------------------------------------------------------
# Hash chain computation
# ---------------------------------------------------------------------------

def compute_event_hash(
    wallet: str,
    event_type: str,
    denomination: str,
    amount: Decimal,
    balance_after: Decimal,
    valid_at: datetime,
    prev_hash: Optional[str],
) -> str:
    """
    Compute SHA256 hash for an economic event.

    The hash chain links each event to its predecessor for tamper detection.
    The canonical JSON representation uses sorted keys and string-encoded
    numerics for deterministic serialization.
    """
    canonical = json.dumps(
        {
            "wallet": wallet,
            "event_type": event_type,
            "denomination": denomination,
            "amount": str(amount),
            "balance_after": str(balance_after),
            "valid_at": valid_at.isoformat(),
            "prev_hash": prev_hash or "genesis",
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def canonical_ledger_decimal(value: Decimal) -> str:
    """Return the non-exponent decimal representation used by hash contract v2."""
    if isinstance(value, float):
        raise TypeError("ledger amounts must enter as Decimal, never float")
    decimal_value = value if isinstance(value, Decimal) else Decimal(value)
    if not decimal_value.is_finite():
        raise ValueError("ledger amounts must be finite")
    if decimal_value == 0:
        return "0"
    if abs(decimal_value.adjusted()) > 128:
        raise ValueError("ledger amount exceeds the 128-character exact-decimal limit")

    canonical = format(decimal_value, "f")
    if "." in canonical:
        canonical = canonical.rstrip("0").rstrip(".")
    if len(canonical) > 128:
        raise ValueError("ledger amount exceeds the 128-character exact-decimal limit")
    return canonical


def _canonical_ledger_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def compute_event_hash_v2(
    wallet: str,
    event_type: str,
    denomination: str,
    amount: Decimal,
    balance_after: Decimal,
    valid_at: datetime,
    prev_hash: Optional[str],
) -> str:
    """Compute the database-authoritative, scale-neutral ledger hash."""
    canonical = "\n".join(
        (
            "economic-event-v2",
            f"{len(wallet)}:{wallet}",
            f"{len(event_type)}:{event_type}",
            f"{len(denomination)}:{denomination}",
            canonical_ledger_decimal(amount),
            canonical_ledger_decimal(balance_after),
            _canonical_ledger_timestamp(valid_at),
            prev_hash or "genesis",
        )
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _parse_ledger_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _economic_event_from_row(data: Dict[str, Any]) -> EconomicEvent:
    batch_id = data.get("batch_id")
    return EconomicEvent(
        id=int(data["id"]),
        event_uuid=UUID(str(data["event_uuid"])),
        event_type=str(data["event_type"]),
        wallet=str(data["wallet"]),
        counterparty=data.get("counterparty"),
        amount=Decimal(str(data["amount"])),
        denomination=str(data["denomination"]),
        balance_after=Decimal(str(data["balance_after"])),
        caused_by_id=data.get("caused_by_id"),
        batch_id=UUID(str(batch_id)) if batch_id else None,
        pipeline_version_id=data.get("pipeline_version_id"),
        reference_type=data.get("reference_type"),
        reference_id=data.get("reference_id"),
        valid_at=_parse_ledger_datetime(data["valid_at"]),
        recorded_at=_parse_ledger_datetime(data["recorded_at"]),
        reversal_of_id=data.get("reversal_of_id"),
        is_reversed=bool(data.get("is_reversed", False)),
        evidence=data.get("evidence"),
        prev_hash=data.get("prev_hash"),
        event_hash=str(data["event_hash"]).strip(),
        hash_version=int(data.get("hash_version") or 1),
    )


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class EconomicLedgerService:
    """
    Service for recording and querying the canonical economic ledger.

    All writes go through record_event(), which:
    1. Sends exact canonical decimal text to the database append authority
    2. Serializes the wallet+denomination stream in PostgreSQL
    3. Computes the balance and v2 hash from the stored NUMERIC values
    4. Inserts the event in that same database transaction

    Key methods:
    - record_event: Append a new event to the ledger
    - get_balance: Get current wallet balance for a denomination
    - get_balance_at: Get historical wallet balance at a point in time
    - get_events: Query events for a wallet
    """

    def __init__(self, supabase: Client):
        self.supabase = supabase

    async def record_event(
        self,
        wallet: str,
        event_type: str,
        amount: Decimal,
        denomination: str = "CAL",
        valid_at: Optional[datetime] = None,
        caused_by_id: Optional[int] = None,
        batch_id: Optional[UUID] = None,
        pipeline_version_id: Optional[int] = None,
        reference_type: Optional[str] = None,
        reference_id: Optional[str] = None,
        counterparty: Optional[str] = None,
        reversal_of_id: Optional[int] = None,
        evidence: Optional[Dict[str, Any]] = None,
    ) -> EconomicEvent:
        """
        Append a new event to the economic ledger.

        This is the primary write path. PostgreSQL serializes the
        wallet/denomination stream, calculates the balance and v2 hash from
        exact NUMERIC values, and inserts the row in one transaction.

        Args:
            wallet: Affected wallet address
            event_type: Event taxonomy type (e.g., 'TSS_EARN', 'STAKE_DEPOSIT')
            amount: Change amount (positive=credit, negative=debit)
            denomination: Token denomination ('POINTS', 'CAL', 'DUNG', 'LP')
            valid_at: When the event happened in the real world (defaults to now)
            caused_by_id: ID of the parent event that caused this one
            batch_id: UUID grouping related events (e.g., epoch distribution)
            pipeline_version_id: FK to pipeline_versions for provenance
            reference_type: Source entity type ('activity', 'vault', 'epoch', etc.)
            reference_id: Source entity ID
            counterparty: Other party involved (e.g., vault signature)
            reversal_of_id: If this is a REVERSAL, the original event ID
            evidence: Additional context as JSONB

        Returns:
            The recorded EconomicEvent
        """
        if valid_at is None:
            valid_at = datetime.now(timezone.utc)

        # Ensure valid_at is timezone-aware
        if valid_at.tzinfo is None:
            valid_at = valid_at.replace(tzinfo=timezone.utc)
        if pipeline_version_id is None:
            raise ValueError("pipeline_version_id is required for new economic events")

        params = {
            "p_wallet": wallet,
            "p_event_type": event_type,
            "p_amount": canonical_ledger_decimal(amount),
            "p_denomination": denomination,
            "p_valid_at": valid_at.isoformat(),
            "p_pipeline_version_id": pipeline_version_id,
            "p_caused_by_id": caused_by_id,
            "p_batch_id": str(batch_id) if batch_id is not None else None,
            "p_reference_type": reference_type,
            "p_reference_id": reference_id,
            "p_counterparty": counterparty,
            "p_reversal_of_id": reversal_of_id,
            "p_evidence": evidence,
        }
        result = await asyncio.to_thread(
            lambda: self.supabase.rpc("append_economic_event", params).execute()
        )
        rows = result.data or []
        data = rows[0] if isinstance(rows, list) and rows else rows
        if not isinstance(data, dict):
            raise RuntimeError("append_economic_event returned no ledger row")
        event = _economic_event_from_row(data)

        logger.debug(
            "[EconomicLedger] Recorded event: id=%s type=%s wallet=%s "
            "amount=%s denom=%s balance_after=%s",
            event.id,
            event.event_type,
            "[redacted]",
            event.amount,
            event.denomination,
            event.balance_after,
        )

        return event

    async def get_balance(
        self,
        wallet: str,
        denomination: str = "CAL",
    ) -> Decimal:
        """
        Get current wallet balance for a denomination.

        Returns 0 if no events exist for this wallet+denomination.
        """
        result = await asyncio.to_thread(
            lambda: self.supabase.rpc(
                "wallet_balance_current",
                {"p_wallet": wallet, "p_denomination": denomination},
            ).execute()
        )
        return Decimal(str(result.data)) if result.data is not None else Decimal(0)

    async def get_balance_at(
        self,
        wallet: str,
        denomination: str,
        at: datetime,
    ) -> Decimal:
        """
        Get historical wallet balance at a specific point in time.

        Uses the wallet_balance_at() SQL function for efficient lookup.
        """
        # Ensure timezone-aware
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)

        result = await asyncio.to_thread(
            lambda: self.supabase.rpc(
                "wallet_balance_at",
                {
                    "p_wallet": wallet,
                    "p_denomination": denomination,
                    "p_at": at.isoformat(),
                },
            ).execute()
        )
        return Decimal(str(result.data)) if result.data is not None else Decimal(0)

    async def get_events(
        self,
        wallet: str,
        denomination: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        include_reversed: bool = False,
    ) -> List[EconomicEvent]:
        """
        Query economic events for a wallet.

        Args:
            wallet: Wallet address
            denomination: Filter by denomination (optional)
            event_type: Filter by event type (optional)
            limit: Max results
            offset: Pagination offset
            include_reversed: Whether to include reversed events

        Returns:
            List of EconomicEvent ordered by id DESC
        """
        query = (
            self.supabase.table("economic_events")
            .select("*")
            .eq("wallet", wallet)
        )

        if denomination:
            query = query.eq("denomination", denomination)
        if event_type:
            query = query.eq("event_type", event_type)
        if not include_reversed:
            query = query.eq("is_reversed", False)

        result = await asyncio.to_thread(
            lambda: window(query.order("id", desc=True), offset, limit).execute()
        )

        return [_economic_event_from_row(data) for data in (result.data or [])]

    async def verify_hash_chain(
        self,
        wallet: str,
        denomination: str = "CAL",
        limit: int = 1000,
    ) -> Dict[str, Any]:
        """
        Verify the hash chain integrity for a wallet+denomination.

        Walks through events in chronological order and recomputes each hash,
        checking it matches the stored hash.

        Returns:
            Dict with 'valid' (bool), 'events_checked' (int),
            'first_broken_id' (int or None), 'error' (str or None)
        """
        result = await asyncio.to_thread(
            lambda: self.supabase.table("economic_events")
            .select(
                "id, event_type, wallet, denomination, amount, balance_after, "
                "valid_at, prev_hash, event_hash, hash_version"
            )
            .eq("wallet", wallet)
            .eq("denomination", denomination)
            .order("id", desc=False)
            .limit(limit)
            .execute()
        )

        events = result.data or []
        if not events:
            return {"valid": True, "events_checked": 0, "first_broken_id": None, "error": None}

        for i, event in enumerate(events):
            expected_prev = events[i - 1]["event_hash"] if i > 0 else None

            # Check prev_hash linkage
            stored_prev = event.get("prev_hash")
            if stored_prev != expected_prev:
                return {
                    "valid": False,
                    "events_checked": i + 1,
                    "first_broken_id": event["id"],
                    "error": f"prev_hash mismatch at event {event['id']}: "
                             f"stored={stored_prev}, expected={expected_prev}",
                }

            # Recompute event hash
            valid_at_str = event["valid_at"]
            if isinstance(valid_at_str, str):
                valid_at = datetime.fromisoformat(valid_at_str.replace("Z", "+00:00"))
            else:
                valid_at = valid_at_str

            hash_version = int(event.get("hash_version") or 1)
            if hash_version == 1:
                recomputed = compute_event_hash(
                    wallet=event["wallet"],
                    event_type=event["event_type"],
                    denomination=event["denomination"],
                    amount=Decimal(str(event["amount"])),
                    balance_after=Decimal(str(event["balance_after"])),
                    valid_at=valid_at,
                    prev_hash=stored_prev,
                )
            elif hash_version == 2:
                recomputed = compute_event_hash_v2(
                    wallet=event["wallet"],
                    event_type=event["event_type"],
                    denomination=event["denomination"],
                    amount=Decimal(str(event["amount"])),
                    balance_after=Decimal(str(event["balance_after"])),
                    valid_at=valid_at,
                    prev_hash=stored_prev,
                )
            else:
                return {
                    "valid": False,
                    "events_checked": i + 1,
                    "first_broken_id": event["id"],
                    "error": f"unsupported hash_version {hash_version}",
                }

            if recomputed != event["event_hash"]:
                return {
                    "valid": False,
                    "events_checked": i + 1,
                    "first_broken_id": event["id"],
                    "error": f"event_hash mismatch at event {event['id']}: "
                             f"stored={event['event_hash']}, recomputed={recomputed}",
                }

        return {"valid": True, "events_checked": len(events), "first_broken_id": None, "error": None}


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_economic_ledger_service(supabase: Client) -> EconomicLedgerService:
    """Factory function for EconomicLedgerService."""
    return EconomicLedgerService(supabase)
