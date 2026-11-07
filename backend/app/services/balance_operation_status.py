"""Read models for Boulder Roller Balance operation status."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .balance_transaction_coordinator import (
    BalanceConfirmationStatus,
    BalanceOperationRecord,
    BalanceProjectionStatus,
    BalanceRiderState,
    BalanceTransactionCoordinator,
)


class BalanceOperationReadState(str, Enum):
    """Stable reader/support state bucket."""

    PENDING = "pending"
    DELAYED = "delayed"
    RECORDED = "recorded"
    NEEDS_REVIEW = "needs_review"


@dataclass(frozen=True)
class BalanceRiderOperationStatus:
    """Rider-safe operation status without chain plumbing."""

    operation_id: str
    action_type: str
    asset: str
    amount: str
    reference_type: str | None
    reference_id: str | None
    rider_state: str | None
    read_state: str
    pending: bool
    delayed: bool
    needs_review: bool
    recorded: bool


@dataclass(frozen=True)
class BalanceSupportOperationStatus:
    """Support/admin operation status with technical context."""

    operation_id: str
    rider_account_id: str
    protocol_wallet: str
    action_type: str
    authority_model: str
    asset: str
    amount: str
    source: str
    destination: str
    reference_type: str | None
    reference_id: str | None
    idempotency_key: str
    prepared_message_hash: str | None
    fee_payer: str | None
    policy_or_delegate_id: str | None
    tx_signature: str | None
    confirmation_status: str
    projection_status: str
    retry_count: int
    failure_reason: str | None
    rider_state: str | None
    metadata: dict[str, str]


@dataclass(frozen=True)
class BalanceOperationStatus:
    """Combined operation read model."""

    rider: BalanceRiderOperationStatus
    support: BalanceSupportOperationStatus


def operation_status_from_record(record: BalanceOperationRecord) -> BalanceOperationStatus:
    """Convert a durable operation record into rider and support read models."""

    rider_state = record.rider_state or BalanceTransactionCoordinator.rider_state_for(record)
    read_state = _read_state_for(record, rider_state)
    rider = BalanceRiderOperationStatus(
        operation_id=record.operation_id,
        action_type=record.action_type,
        asset=record.asset,
        amount=record.amount,
        reference_type=record.reference_type,
        reference_id=record.reference_id,
        rider_state=rider_state,
        read_state=read_state.value,
        pending=read_state is BalanceOperationReadState.PENDING,
        delayed=read_state is BalanceOperationReadState.DELAYED,
        needs_review=read_state is BalanceOperationReadState.NEEDS_REVIEW,
        recorded=read_state is BalanceOperationReadState.RECORDED,
    )
    support = BalanceSupportOperationStatus(
        operation_id=record.operation_id,
        rider_account_id=record.rider_account_id,
        protocol_wallet=record.protocol_wallet,
        action_type=record.action_type,
        authority_model=record.authority_model,
        asset=record.asset,
        amount=record.amount,
        source=record.source,
        destination=record.destination,
        reference_type=record.reference_type,
        reference_id=record.reference_id,
        idempotency_key=record.idempotency_key,
        prepared_message_hash=record.prepared_message_hash,
        fee_payer=record.fee_payer,
        policy_or_delegate_id=record.policy_or_delegate_id,
        tx_signature=record.tx_signature,
        confirmation_status=record.confirmation_status,
        projection_status=record.projection_status,
        retry_count=record.retry_count,
        failure_reason=record.failure_reason,
        rider_state=rider_state,
        metadata=dict(record.metadata),
    )
    return BalanceOperationStatus(rider=rider, support=support)


def filter_operation_statuses(
    records: Iterable[BalanceOperationRecord],
    *,
    rider_account_id: str,
    reference_type: str | None = None,
    reference_id: str | None = None,
    action_type: str | None = None,
) -> tuple[BalanceOperationStatus, ...]:
    """Filter already-loaded records by rider/reference/action and project status."""

    statuses: list[BalanceOperationStatus] = []
    for record in records:
        if record.rider_account_id != rider_account_id:
            continue
        if reference_type is not None and record.reference_type != reference_type:
            continue
        if reference_id is not None and record.reference_id != reference_id:
            continue
        if action_type is not None and record.action_type != action_type:
            continue
        statuses.append(operation_status_from_record(record))
    return tuple(statuses)


def operation_record_from_row(row: dict[str, object]) -> BalanceOperationRecord:
    """Build an operation record from a balance_operations table row."""

    return BalanceOperationRecord(
        operation_id=str(row.get("operation_id") or ""),
        rider_account_id=str(row.get("rider_account_id") or ""),
        protocol_wallet=str(row.get("protocol_wallet") or ""),
        action_type=str(row.get("action_type") or ""),
        authority_model=str(row.get("authority_model") or ""),
        asset=str(row.get("asset") or ""),
        amount=str(row.get("amount") or ""),
        source=str(row.get("source") or ""),
        destination=str(row.get("destination") or ""),
        idempotency_key=str(row.get("idempotency_key") or ""),
        prepared_message_hash=_optional_str(row.get("prepared_message_hash")),
        fee_payer=_optional_str(row.get("fee_payer")),
        policy_or_delegate_id=_optional_str(row.get("policy_or_delegate_id")),
        tx_signature=_optional_str(row.get("tx_signature")),
        confirmation_status=str(
            row.get("confirmation_status") or BalanceConfirmationStatus.PREPARED.value
        ),
        projection_status=str(
            row.get("projection_status") or BalanceProjectionStatus.NOT_STARTED.value
        ),
        retry_count=int(row.get("retry_count") or 0),
        failure_reason=_optional_str(row.get("failure_reason")),
        reference_type=_optional_str(row.get("reference_type")),
        reference_id=_optional_str(row.get("reference_id")),
        rider_state=_optional_str(row.get("rider_state")),
        metadata=dict(row.get("metadata") or {}),
    )


class SupabaseBalanceOperationReader:
    """Supabase-backed reader for balance_operations."""

    def __init__(self, client) -> None:
        self._client = client

    def get(self, operation_id: str) -> BalanceOperationStatus | None:
        table = self._client.table("balance_operations")
        result = table.select("*").eq("operation_id", operation_id).limit(1).execute()
        rows = result.data or []
        if not rows:
            return None
        return operation_status_from_record(operation_record_from_row(rows[0]))

    def get_for_rider(
        self,
        operation_id: str,
        *,
        rider_account_id: str,
    ) -> BalanceOperationStatus | None:
        """Read one operation while applying rider ownership in the query."""

        result = (
            self._client.table("balance_operations")
            .select("*")
            .eq("operation_id", operation_id)
            .eq("rider_account_id", rider_account_id)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        if not rows:
            return None
        return operation_status_from_record(operation_record_from_row(rows[0]))

    def find_for_rider(
        self,
        rider_account_id: str,
        *,
        client_request_id: str,
        reference_type: str,
        reference_id: str,
        action_type: str,
    ) -> BalanceOperationStatus | None:
        """Find the newest owned operation for one stable client request."""

        result = (
            self._client.table("balance_operations")
            .select("*")
            .eq("rider_account_id", rider_account_id)
            .eq("reference_type", reference_type)
            .eq("reference_id", reference_id)
            .eq("action_type", action_type)
            .contains("metadata", {"client_request_id": client_request_id})
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        if not rows:
            return None
        return operation_status_from_record(operation_record_from_row(rows[0]))

    def list_for_rider(
        self,
        rider_account_id: str,
        *,
        reference_type: str | None = None,
        reference_id: str | None = None,
        action_type: str | None = None,
        limit: int = 25,
    ) -> tuple[BalanceOperationStatus, ...]:
        query = (
            self._client.table("balance_operations")
            .select("*")
            .eq("rider_account_id", rider_account_id)
        )
        if reference_type is not None:
            query = query.eq("reference_type", reference_type)
        if reference_id is not None:
            query = query.eq("reference_id", reference_id)
        if action_type is not None:
            query = query.eq("action_type", action_type)
        result = query.limit(limit).execute()
        return tuple(
            operation_status_from_record(operation_record_from_row(row))
            for row in (result.data or [])
        )


def _read_state_for(
    record: BalanceOperationRecord,
    rider_state: str | None,
) -> BalanceOperationReadState:
    confirmation = BalanceConfirmationStatus(record.confirmation_status)
    projection = BalanceProjectionStatus(record.projection_status)

    if confirmation in (BalanceConfirmationStatus.FAILED, BalanceConfirmationStatus.EXPIRED):
        return BalanceOperationReadState.NEEDS_REVIEW
    if projection is BalanceProjectionStatus.NEEDS_REVIEW:
        return BalanceOperationReadState.NEEDS_REVIEW
    if rider_state == BalanceRiderState.NEEDS_REVIEW.value:
        return BalanceOperationReadState.NEEDS_REVIEW
    if projection is BalanceProjectionStatus.RECORDED:
        return BalanceOperationReadState.RECORDED
    if projection is BalanceProjectionStatus.DELAYED:
        return BalanceOperationReadState.DELAYED
    if projection is BalanceProjectionStatus.PENDING:
        return BalanceOperationReadState.PENDING
    if confirmation in (BalanceConfirmationStatus.CONFIRMED, BalanceConfirmationStatus.FINALIZED):
        return BalanceOperationReadState.DELAYED
    return BalanceOperationReadState.PENDING


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
