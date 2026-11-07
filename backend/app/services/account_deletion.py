"""Fail-closed account-deletion lifecycle primitives.

The durable database row is the authority for progress.  This module keeps the
destructive worker small and testable: it refuses to touch storage or invoke
the atomic anonymization boundary until the client has acknowledged local
recordings and every server-side value authority has been checked again.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Awaitable, Callable, Mapping, Protocol, Sequence

from ..account_deletion_contract import (
    VAULT_STAKE_ACTIVE_FIELDS,
    VAULT_STAKE_CLAIM_FIELDS,
)


class DeletionBlockerCode(str, Enum):
    BALANCE_REMAINS = "balance_remains"
    STAKE_REMAINS = "stake_remains"
    CLAIM_REMAINS = "claim_remains"
    UNUPLOADED_RIDES_UNACKNOWLEDGED = "unuploaded_rides_unacknowledged"
    POLICY_REVIEW_REQUIRED = "policy_review_required"
    PREFLIGHT_UNAVAILABLE = "preflight_unavailable"


class DeletionExecutionStatus(str, Enum):
    BLOCKED = "blocked"
    FAILED_RETRYABLE = "failed_retryable"
    NEEDS_SUPPORT = "needs_support"
    COMPLETED = "completed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class DeletionAssetBalance:
    asset: str
    amount_base_units: int
    source: str

    def __post_init__(self) -> None:
        if self.amount_base_units < 0:
            raise ValueError("Deletion balance observations cannot be negative")


@dataclass(frozen=True)
class AccountDeletionValueSnapshot:
    balances: tuple[DeletionAssetBalance, ...]
    active_stakes: int
    pending_claims: int
    unresolved_provenance: int
    unavailable_sources: tuple[str, ...]
    database_blockers: tuple[AccountDeletionBlocker, ...] = ()
    destructive_boundary_available: bool = False

    def __post_init__(self) -> None:
        if min(self.active_stakes, self.pending_claims, self.unresolved_provenance) < 0:
            raise ValueError("Deletion preflight counts cannot be negative")


@dataclass(frozen=True)
class AccountDeletionBlocker:
    code: DeletionBlockerCode
    category: str
    asset: str | None = None
    amount_base_units: int | None = None
    count: int | None = None
    source: str | None = None
    action: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = {
            key: value.value if isinstance(value, Enum) else value
            for key, value in {
                "code": self.code,
                "category": self.category,
                "asset": self.asset,
                "amount_base_units": self.amount_base_units,
                "count": self.count,
                "source": self.source,
                "action": self.action,
            }.items()
            if value is not None
        }
        if self.amount_base_units is not None:
            payload["amount_base_units"] = str(self.amount_base_units)
        return payload


@dataclass(frozen=True)
class AccountDeletionPreflight:
    allowed: bool
    available: bool
    blockers: tuple[AccountDeletionBlocker, ...]
    checked_at: datetime
    destructive_boundary_available: bool = False


@dataclass(frozen=True)
class AccountDeletionRequest:
    request_id: str
    user_id: str
    wallet: str
    status: str
    unuploaded_rides_acknowledged: bool
    storage_paths: tuple[str, ...]
    lease_token: str


@dataclass(frozen=True)
class AccountDeletionExecutionResult:
    request_id: str
    status: DeletionExecutionStatus
    blockers: tuple[AccountDeletionBlocker, ...] = ()
    failure_code: str | None = None


class AccountDeletionRepositoryProtocol(Protocol):
    async def claim_for_processing(self, request_id: str) -> AccountDeletionRequest | None: ...

    async def mark_blocked(
        self,
        request: AccountDeletionRequest,
        blockers: Sequence[AccountDeletionBlocker],
    ) -> Mapping[str, Any]: ...

    async def mark_failed(
        self,
        request: AccountDeletionRequest,
        *,
        failure_code: str,
    ) -> Mapping[str, Any]: ...

    async def mark_needs_support(
        self,
        request: AccountDeletionRequest,
        blockers: Sequence[AccountDeletionBlocker],
    ) -> Mapping[str, Any]: ...

    async def renew_lease(self, request: AccountDeletionRequest) -> None: ...

    async def authorize_storage_deletion(
        self,
        request: AccountDeletionRequest,
        *,
        preflight_snapshot: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...

    async def record_storage_receipt(
        self,
        request: AccountDeletionRequest,
        *,
        path: str,
        outcome: str,
    ) -> None: ...

    async def mark_storage_removed(
        self,
        request: AccountDeletionRequest,
        *,
        preflight_snapshot: Mapping[str, Any],
    ) -> None: ...

    async def finalize_anonymization(
        self,
        request: AccountDeletionRequest,
    ) -> Mapping[str, Any]: ...


class AccountDeletionPreflightReaderProtocol(Protocol):
    async def read(self, *, user_id: str, wallet: str) -> AccountDeletionValueSnapshot: ...


class AccountDeletionStorageProtocol(Protocol):
    async def delete_ride_file(self, path: str) -> bool: ...

    async def file_exists_strict(self, path: str) -> bool: ...


def hash_account_deletion_status_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def account_deletion_status_token_matches(token: str, expected_hash: str) -> bool:
    if not token or not expected_hash:
        return False
    return hmac.compare_digest(
        hash_account_deletion_status_token(token),
        str(expected_hash).strip().lower(),
    )


def _decimal(value: Any, *, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid deletion authority amount for {field}") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"Invalid deletion authority amount for {field}")
    return parsed


def _positive_count(rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> int:
    count = 0
    for row in rows:
        if any(_decimal(row.get(field), field=field) > 0 for field in fields):
            count += 1
    return count


def _operation_is_unfinished(row: Mapping[str, Any]) -> bool:
    confirmation = str(row.get("confirmation_status") or "")
    projection = str(row.get("projection_status") or "")
    if confirmation in {"failed", "expired"}:
        return False
    return confirmation != "finalized" or projection != "recorded"


def _balance_observation(
    *,
    asset: str,
    amount: Any,
    source: str,
) -> DeletionAssetBalance | None:
    parsed = _decimal(amount, field=f"{source}.{asset}")
    if parsed <= 0:
        return None
    # Legacy rows are NUMERIC while chain reads are exact integers.  Any
    # positive fractional legacy amount is still a blocker and must never be
    # rounded down to the zero/safe state.
    amount_base_units = max(1, int(parsed))
    return DeletionAssetBalance(
        asset=asset,
        amount_base_units=amount_base_units,
        source=source,
    )


class AccountDeletionAuthorityReader:
    """Combine database and chain authorities into one fail-closed snapshot."""

    _LIVE_SOURCE_STATES = {"live", "not_initialized"}

    def __init__(
        self,
        *,
        repository: Any,
        balance_snapshot_loader: Callable[[str], Awaitable[Any]],
        balance_dung_loader: Callable[[str], Awaitable[Any]],
        stake_loader: Callable[[str], Awaitable[Sequence[Mapping[str, Any]]]],
    ) -> None:
        self._repository = repository
        self._balance_snapshot_loader = balance_snapshot_loader
        self._balance_dung_loader = balance_dung_loader
        self._stake_loader = stake_loader

    async def read(self, *, user_id: str, wallet: str) -> AccountDeletionValueSnapshot:
        results = await asyncio.gather(
            self._repository.get_deletion_database_blockers(user_id, wallet),
            self._balance_snapshot_loader(wallet),
            self._balance_dung_loader(wallet),
            self._stake_loader(wallet),
            return_exceptions=True,
        )
        db_blocker_rows, balance_snapshot, balance_dung, vault_stakes = results
        unavailable: list[str] = []
        balances: list[DeletionAssetBalance] = []
        active_stakes = 0
        pending_claims = 0
        unresolved_provenance = 0
        database_blockers: list[AccountDeletionBlocker] = []

        if isinstance(db_blocker_rows, BaseException):
            unavailable.append("database")
        else:
            try:
                if not isinstance(db_blocker_rows, Sequence):
                    raise TypeError("Database blocker authority is not a sequence")
                for raw in db_blocker_rows:
                    if not isinstance(raw, Mapping):
                        raise TypeError("Database blocker is not an object")
                    amount_value = raw.get("amount_base_units")
                    amount = None
                    if amount_value is not None:
                        amount_text = str(amount_value)
                        if not amount_text.isdigit():
                            raise ValueError("Database atomic amount is not an integer string")
                        amount = int(amount_text)
                    count_value = raw.get("count")
                    count = int(count_value) if count_value is not None else None
                    database_blockers.append(
                        AccountDeletionBlocker(
                            code=DeletionBlockerCode(str(raw["code"])),
                            category=str(raw["category"]),
                            asset=str(raw["asset"]) if raw.get("asset") is not None else None,
                            amount_base_units=amount,
                            count=count,
                            source=str(raw["source"]) if raw.get("source") is not None else None,
                            action=str(raw["action"]) if raw.get("action") is not None else None,
                        )
                    )
            except (KeyError, TypeError, ValueError):
                unavailable.append("database")

        if isinstance(balance_snapshot, BaseException):
            unavailable.append("rider_balance")
        else:
            try:
                header_status = str(balance_snapshot.header.source_status)
                cal_status = str(balance_snapshot.cal.status)
                usdc_status = str(balance_snapshot.usdc.status)
                if not {header_status, cal_status, usdc_status}.issubset(
                    self._LIVE_SOURCE_STATES
                ):
                    raise ValueError("RiderBalance source is not authoritative")
                for source, asset in (
                    (balance_snapshot.cal, "CAL"),
                    (balance_snapshot.usdc, "USDC"),
                ):
                    observation = _balance_observation(
                        asset=asset,
                        amount=source.amount_base_units,
                        source="boulder_roller_balance",
                    )
                    if observation:
                        balances.append(observation)
            except (AttributeError, TypeError, ValueError):
                unavailable.append("rider_balance")

        if isinstance(balance_dung, BaseException):
            unavailable.append("balance_dung")
        else:
            try:
                if str(balance_dung.status) not in self._LIVE_SOURCE_STATES:
                    raise ValueError("Balance DUNG source is not authoritative")
                observation = _balance_observation(
                    asset="DUNG",
                    amount=balance_dung.amount_base_units,
                    source="boulder_roller_balance",
                )
                if observation:
                    balances.append(observation)
            except (AttributeError, TypeError, ValueError):
                unavailable.append("balance_dung")

        if isinstance(vault_stakes, BaseException):
            unavailable.append("vault_stakes")
        else:
            try:
                active_stakes += _positive_count(
                    vault_stakes,
                    VAULT_STAKE_ACTIVE_FIELDS,
                )
                pending_claims += _positive_count(
                    vault_stakes,
                    VAULT_STAKE_CLAIM_FIELDS,
                )
                # The existence of a wallet-keyed on-chain stake account is a
                # provenance edge even after its balances reach zero.
                unresolved_provenance += len(vault_stakes)
            except (TypeError, ValueError):
                unavailable.append("vault_stakes")

        return AccountDeletionValueSnapshot(
            balances=tuple(balances),
            active_stakes=active_stakes,
            pending_claims=pending_claims,
            unresolved_provenance=unresolved_provenance,
            unavailable_sources=tuple(sorted(set(unavailable))),
            database_blockers=tuple(database_blockers),
            # Tim has not ratified an on-chain closure/tombstone primitive.
            # This is intentionally hard false: there is no environment bypass
            # for a destructive policy boundary.
            destructive_boundary_available=False,
        )


def evaluate_account_deletion_preflight(
    snapshot: AccountDeletionValueSnapshot,
) -> AccountDeletionPreflight:
    """Turn exact authority observations into one fail-closed decision."""
    checked_at = datetime.now(timezone.utc)
    if snapshot.unavailable_sources:
        return AccountDeletionPreflight(
            allowed=False,
            available=False,
            blockers=(
                AccountDeletionBlocker(
                    code=DeletionBlockerCode.PREFLIGHT_UNAVAILABLE,
                    category="availability",
                    count=len(snapshot.unavailable_sources),
                    source=",".join(sorted(set(snapshot.unavailable_sources))),
                    action="retry",
                ),
            ),
            checked_at=checked_at,
            destructive_boundary_available=snapshot.destructive_boundary_available,
        )

    blockers: list[AccountDeletionBlocker] = list(snapshot.database_blockers)
    for balance in snapshot.balances:
        if balance.amount_base_units <= 0:
            continue
        blockers.append(
            AccountDeletionBlocker(
                code=DeletionBlockerCode.BALANCE_REMAINS,
                category="balance",
                asset=balance.asset,
                amount_base_units=balance.amount_base_units,
                source=balance.source,
                action="open_balance",
            )
        )
    if snapshot.active_stakes:
        blockers.append(
            AccountDeletionBlocker(
                code=DeletionBlockerCode.STAKE_REMAINS,
                category="stake",
                count=snapshot.active_stakes,
                action="open_balance",
            )
        )
    if snapshot.pending_claims:
        blockers.append(
            AccountDeletionBlocker(
                code=DeletionBlockerCode.CLAIM_REMAINS,
                category="claim",
                count=snapshot.pending_claims,
                action="open_balance",
            )
        )
    if snapshot.unresolved_provenance:
        blockers.append(
            AccountDeletionBlocker(
                code=DeletionBlockerCode.POLICY_REVIEW_REQUIRED,
                category="policy",
                count=snapshot.unresolved_provenance,
                action="contact_support",
            )
        )
    if not snapshot.destructive_boundary_available:
        blockers.append(
            AccountDeletionBlocker(
                code=DeletionBlockerCode.POLICY_REVIEW_REQUIRED,
                category="policy",
                count=1,
                source="on_chain_deletion_boundary",
                action="contact_support",
            )
        )

    return AccountDeletionPreflight(
        allowed=not blockers,
        available=True,
        blockers=tuple(blockers),
        checked_at=checked_at,
        destructive_boundary_available=snapshot.destructive_boundary_available,
    )


def account_deletion_preflight_snapshot(
    preflight: AccountDeletionPreflight,
) -> dict[str, Any]:
    return {
        "contract_version": "account-deletion.v1",
        "allowed": preflight.allowed,
        "available": preflight.available,
        "destructive_boundary_available": preflight.destructive_boundary_available,
        "blockers": [blocker.as_dict() for blocker in preflight.blockers],
        "checked_at": preflight.checked_at.isoformat(),
    }


def _account_deletion_blockers_from_row(
    row: Mapping[str, Any],
) -> tuple[AccountDeletionBlocker, ...]:
    raw_blockers = row.get("blockers") or []
    if not isinstance(raw_blockers, list):
        raise ValueError("Account deletion authorization returned malformed blockers")
    blockers: list[AccountDeletionBlocker] = []
    for raw in raw_blockers:
        if not isinstance(raw, Mapping):
            raise ValueError("Account deletion authorization returned malformed blockers")
        amount_value = raw.get("amount_base_units")
        blockers.append(
            AccountDeletionBlocker(
                code=DeletionBlockerCode(str(raw["code"])),
                category=str(raw["category"]),
                asset=str(raw["asset"]) if raw.get("asset") is not None else None,
                amount_base_units=(
                    int(str(amount_value)) if amount_value is not None else None
                ),
                count=int(raw["count"]) if raw.get("count") is not None else None,
                source=str(raw["source"]) if raw.get("source") is not None else None,
                action=str(raw["action"]) if raw.get("action") is not None else None,
            )
        )
    return tuple(blockers)


async def execute_account_deletion(
    request_id: str,
    *,
    repository: AccountDeletionRepositoryProtocol,
    preflight_reader: AccountDeletionPreflightReaderProtocol,
    storage: AccountDeletionStorageProtocol,
    monotonic: Callable[[], float] = time.monotonic,
    lease_renewal_interval_seconds: float = 120.0,
) -> AccountDeletionExecutionResult:
    """Execute one leased request without reporting success prematurely."""
    request = await repository.claim_for_processing(request_id)
    if request is None:
        return AccountDeletionExecutionResult(
            request_id=request_id,
            status=DeletionExecutionStatus.SKIPPED,
        )
    last_lease_renewed_at = monotonic()

    async def renew_lease_if_due() -> None:
        nonlocal last_lease_renewed_at
        now = monotonic()
        if now - last_lease_renewed_at < lease_renewal_interval_seconds:
            return
        await repository.renew_lease(request)
        last_lease_renewed_at = now

    if not request.unuploaded_rides_acknowledged:
        blockers = (
            AccountDeletionBlocker(
                code=DeletionBlockerCode.UNUPLOADED_RIDES_UNACKNOWLEDGED,
                category="recording",
                action="review_recordings",
            ),
        )
        await repository.mark_blocked(request, blockers)
        return AccountDeletionExecutionResult(
            request_id=request_id,
            status=DeletionExecutionStatus.BLOCKED,
            blockers=blockers,
        )

    try:
        snapshot = await preflight_reader.read(
            user_id=request.user_id,
            wallet=request.wallet,
        )
        preflight = evaluate_account_deletion_preflight(snapshot)
    except Exception:
        await repository.mark_failed(request, failure_code="preflight_unavailable")
        return AccountDeletionExecutionResult(
            request_id=request_id,
            status=DeletionExecutionStatus.FAILED_RETRYABLE,
            failure_code="preflight_unavailable",
        )

    if not preflight.available:
        await repository.mark_failed(request, failure_code="preflight_unavailable")
        return AccountDeletionExecutionResult(
            request_id=request_id,
            status=DeletionExecutionStatus.FAILED_RETRYABLE,
            blockers=preflight.blockers,
            failure_code="preflight_unavailable",
        )

    if not preflight.allowed:
        if any(
            blocker.code is DeletionBlockerCode.POLICY_REVIEW_REQUIRED
            for blocker in preflight.blockers
        ):
            await repository.mark_needs_support(request, preflight.blockers)
            return AccountDeletionExecutionResult(
                request_id=request_id,
                status=DeletionExecutionStatus.NEEDS_SUPPORT,
                blockers=preflight.blockers,
            )
        await repository.mark_blocked(request, preflight.blockers)
        return AccountDeletionExecutionResult(
            request_id=request_id,
            status=DeletionExecutionStatus.BLOCKED,
            blockers=preflight.blockers,
        )

    try:
        await renew_lease_if_due()
        final_snapshot = await preflight_reader.read(
            user_id=request.user_id,
            wallet=request.wallet,
        )
        final_preflight = evaluate_account_deletion_preflight(final_snapshot)
    except Exception:
        await repository.mark_failed(request, failure_code="preflight_unavailable")
        return AccountDeletionExecutionResult(
            request_id=request_id,
            status=DeletionExecutionStatus.FAILED_RETRYABLE,
            failure_code="preflight_unavailable",
        )

    if not final_preflight.available:
        await repository.mark_failed(request, failure_code="preflight_unavailable")
        return AccountDeletionExecutionResult(
            request_id=request_id,
            status=DeletionExecutionStatus.FAILED_RETRYABLE,
            blockers=final_preflight.blockers,
            failure_code="preflight_unavailable",
        )
    if not final_preflight.allowed:
        if any(
            blocker.code is DeletionBlockerCode.POLICY_REVIEW_REQUIRED
            for blocker in final_preflight.blockers
        ):
            await repository.mark_needs_support(request, final_preflight.blockers)
            return AccountDeletionExecutionResult(
                request_id=request_id,
                status=DeletionExecutionStatus.NEEDS_SUPPORT,
                blockers=final_preflight.blockers,
            )
        await repository.mark_blocked(request, final_preflight.blockers)
        return AccountDeletionExecutionResult(
            request_id=request_id,
            status=DeletionExecutionStatus.BLOCKED,
            blockers=final_preflight.blockers,
        )

    try:
        await renew_lease_if_due()
        authorized_row = await repository.authorize_storage_deletion(
            request,
            preflight_snapshot=account_deletion_preflight_snapshot(final_preflight),
        )
        authorized_status = str(authorized_row.get("status") or "")
        if authorized_status in {"blocked", "needs_support"}:
            blockers = _account_deletion_blockers_from_row(authorized_row)
            return AccountDeletionExecutionResult(
                request_id=request_id,
                status=(
                    DeletionExecutionStatus.BLOCKED
                    if authorized_status == "blocked"
                    else DeletionExecutionStatus.NEEDS_SUPPORT
                ),
                blockers=blockers,
            )
        if (
            authorized_status != "processing"
            or not authorized_row.get("storage_authorized_at")
        ):
            raise RuntimeError("Database did not authorize account deletion storage")

        for path in dict.fromkeys(path for path in request.storage_paths if path):
            await renew_lease_if_due()
            await storage.delete_ride_file(path)
            if await storage.file_exists_strict(path):
                raise RuntimeError("Deletion storage object still exists")
            await repository.record_storage_receipt(
                request,
                path=path,
                outcome="confirmed_absent",
            )

        await renew_lease_if_due()
        await repository.mark_storage_removed(
            request,
            preflight_snapshot=account_deletion_preflight_snapshot(final_preflight),
        )
        await renew_lease_if_due()
        row = await repository.finalize_anonymization(request)
    except Exception:
        try:
            await repository.mark_failed(request, failure_code="deletion_failed")
        except Exception:
            # A stale worker must not overwrite the authoritative state written
            # by the current lease owner.
            pass
        return AccountDeletionExecutionResult(
            request_id=request_id,
            status=DeletionExecutionStatus.FAILED_RETRYABLE,
            failure_code="deletion_failed",
        )

    final_status = str(row.get("status") or "")
    if final_status == "completed" and row.get("completion_verified_at"):
        return AccountDeletionExecutionResult(
            request_id=request_id,
            status=DeletionExecutionStatus.COMPLETED,
        )
    if final_status == "needs_support":
        return AccountDeletionExecutionResult(
            request_id=request_id,
            status=DeletionExecutionStatus.NEEDS_SUPPORT,
        )
    if final_status == "blocked":
        return AccountDeletionExecutionResult(
            request_id=request_id,
            status=DeletionExecutionStatus.BLOCKED,
        )
    return AccountDeletionExecutionResult(
        request_id=request_id,
        status=DeletionExecutionStatus.FAILED_RETRYABLE,
        failure_code="completion_unverified",
    )
