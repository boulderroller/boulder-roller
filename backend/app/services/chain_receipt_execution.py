"""Shared confirmation semantics for receipt-backed chain executors."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from .protocol_ints import exact_i64
from .ride_chain_accounts import (
    ChainAccountMismatchError,
    ChainAccountUnavailableError,
    LegacyCompletionEvidenceError,
)


class PdaMismatchError(ValueError):
    """A submitted or existing account does not match the frozen plan PDA."""


@dataclass(frozen=True)
class ChainReceiptExecution:
    """Result of submitting a transaction or resolving its receipt PDA."""

    reference: str
    pda: str
    tx_signature: Optional[str]
    confirmed_at: Optional[str]

    @property
    def attested_at(self) -> Optional[str]:
        """Compatibility name used by the ride attestation projection."""
        return self.confirmed_at

    @classmethod
    def confirmed(cls, *, pda: str, reference: str) -> "ChainReceiptExecution":
        return cls(
            reference=reference,
            pda=pda,
            tx_signature=reference,
            confirmed_at=datetime.now(timezone.utc).isoformat(),
        )


def to_unix_seconds(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return exact_i64(int(value.timestamp()), field="ride timestamp")


def authoritative_chain_clock(value: int, *, field: str) -> str:
    if value <= 0:
        raise ChainAccountMismatchError(f"{field} lacks an immutable chain clock")
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


async def execution_from_reference(
    *,
    reference: Any,
    expected_pda: str,
    validate_existing: Callable[[], Awaitable[Optional[str]]],
    finalization_attempts: int,
    finalization_poll_seconds: float,
    require_authoritative_confirmed_at: bool = False,
) -> ChainReceiptExecution:
    reference_str = str(reference or "")
    if not reference_str:
        raise RuntimeError("chain submission returned no reference")
    existing = reference_str.startswith("exists:")
    if existing:
        existing_pda = reference_str.split("exists:", 1)[1]
        if existing_pda != expected_pda:
            raise PdaMismatchError(
                f"existing account {existing_pda} does not match expected PDA "
                f"{expected_pda}"
            )
    attempts = 1 if existing else max(1, finalization_attempts)
    authoritative_confirmed_at: Optional[str] = None
    for attempt in range(attempts):
        try:
            authoritative_confirmed_at = await validate_existing()
            break
        except LegacyCompletionEvidenceError:
            raise
        except ChainAccountMismatchError as exc:
            raise PdaMismatchError(str(exc)) from exc
        except ChainAccountUnavailableError:
            if attempt + 1 >= attempts:
                raise
            await asyncio.sleep(max(0.0, finalization_poll_seconds))
    if existing:
        if require_authoritative_confirmed_at and not authoritative_confirmed_at:
            raise ChainAccountUnavailableError(
                "validated existing receipt lacks an authoritative chain clock"
            )
        return ChainReceiptExecution(
            reference=reference_str,
            pda=expected_pda,
            tx_signature=None,
            confirmed_at=authoritative_confirmed_at,
        )
    return ChainReceiptExecution(
        reference=reference_str,
        pda=expected_pda,
        tx_signature=reference_str,
        confirmed_at=(
            authoritative_confirmed_at or datetime.now(timezone.utc).isoformat()
        ),
    )
