from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from app.services.balance_operation_status import (
    BalanceOperationReadState,
    SupabaseBalanceOperationReader,
    filter_operation_statuses,
    operation_record_from_row,
    operation_status_from_record,
)
from app.services.balance_transaction_coordinator import (
    BalanceConfirmationStatus,
    BalanceOperationRecord,
    BalanceProjectionStatus,
    BalanceRiderState,
)


def _record(
    *,
    operation_id: str = "br-op-123",
    rider_account_id: str = "rider-123",
    action_type: str = "deposit_cal",
    confirmation_status: BalanceConfirmationStatus = BalanceConfirmationStatus.PREPARED,
    projection_status: BalanceProjectionStatus = BalanceProjectionStatus.NOT_STARTED,
    rider_state: str | None = None,
    retry_count: int = 0,
    failure_reason: str | None = None,
    reference_type: str | None = "vault",
    reference_id: str | None = "42",
) -> BalanceOperationRecord:
    return BalanceOperationRecord(
        operation_id=operation_id,
        rider_account_id=rider_account_id,
        protocol_wallet="Wallet111111111111111111111111111111111",
        action_type=action_type,
        authority_model="app_balance",
        asset="CAL",
        amount="250000000000",
        source="RiderBalance CAL token PDA",
        destination="vault:42:cal_escrow",
        idempotency_key=f"br:{action_type}:{operation_id}",
        prepared_message_hash="msg-hash-123",
        fee_payer="BoulderRollerFeePayer111111111111111",
        policy_or_delegate_id="policy-123",
        tx_signature="tx-123",
        confirmation_status=confirmation_status.value,
        projection_status=projection_status.value,
        retry_count=retry_count,
        failure_reason=failure_reason,
        reference_type=reference_type,
        reference_id=reference_id,
        rider_state=rider_state,
        metadata={"surface": "vault"},
    )


def test_prepared_and_submitted_operations_read_as_pending() -> None:
    prepared = operation_status_from_record(_record())
    submitted = operation_status_from_record(
        _record(confirmation_status=BalanceConfirmationStatus.SUBMITTED)
    )

    assert prepared.rider.read_state == BalanceOperationReadState.PENDING.value
    assert prepared.rider.rider_state == BalanceRiderState.PENDING.value
    assert prepared.rider.pending
    assert submitted.rider.read_state == BalanceOperationReadState.PENDING.value
    assert submitted.rider.rider_state == BalanceRiderState.PENDING.value
    assert submitted.rider.pending


def test_confirmed_without_projection_reads_as_delayed_not_recorded() -> None:
    status = operation_status_from_record(
        _record(confirmation_status=BalanceConfirmationStatus.CONFIRMED)
    )

    assert status.rider.read_state == BalanceOperationReadState.DELAYED.value
    assert status.rider.rider_state == BalanceRiderState.DELAYED.value
    assert status.rider.delayed
    assert not status.rider.recorded
    assert status.support.confirmation_status == BalanceConfirmationStatus.CONFIRMED.value
    assert status.support.projection_status == BalanceProjectionStatus.NOT_STARTED.value


def test_recorded_collect_dung_is_collected_and_support_context_is_preserved() -> None:
    record = _record(
        action_type="collect_dung",
        confirmation_status=BalanceConfirmationStatus.FINALIZED,
        projection_status=BalanceProjectionStatus.RECORDED,
    )

    status = operation_status_from_record(record)

    assert status.rider.read_state == BalanceOperationReadState.RECORDED.value
    assert status.rider.rider_state == BalanceRiderState.COLLECTED.value
    assert status.rider.recorded
    assert status.support.operation_id == "br-op-123"
    assert status.support.action_type == "collect_dung"
    assert status.support.authority_model == "app_balance"
    assert status.support.tx_signature == "tx-123"
    assert status.support.policy_or_delegate_id == "policy-123"
    assert status.support.retry_count == 0
    assert status.support.failure_reason is None
    assert status.support.metadata == {"surface": "vault"}


def test_confirmed_pending_projection_remains_pending_for_the_rider() -> None:
    record = _record(
        action_type="create_vault",
        confirmation_status=BalanceConfirmationStatus.CONFIRMED,
        projection_status=BalanceProjectionStatus.PENDING,
    )

    status = operation_status_from_record(record)

    assert status.rider.read_state == BalanceOperationReadState.PENDING.value
    assert status.rider.rider_state == BalanceRiderState.PENDING.value


def test_rider_status_omits_support_only_operation_fields() -> None:
    status = operation_status_from_record(
        _record(
            action_type="withdraw_to_wallet",
            confirmation_status=BalanceConfirmationStatus.SUBMITTED,
            projection_status=BalanceProjectionStatus.PENDING,
        )
    )

    rider_fields = set(status.rider.__dataclass_fields__)

    assert "protocol_wallet" not in rider_fields
    assert "source" not in rider_fields
    assert "destination" not in rider_fields
    assert "idempotency_key" not in rider_fields
    assert "prepared_message_hash" not in rider_fields
    assert "fee_payer" not in rider_fields
    assert "policy_or_delegate_id" not in rider_fields
    assert "tx_signature" not in rider_fields
    assert "metadata" not in rider_fields


def test_recorded_status_preserves_counted_and_collectable_rider_states() -> None:
    counted = operation_status_from_record(
        _record(
            operation_id="br-op-counted",
            confirmation_status=BalanceConfirmationStatus.FINALIZED,
            projection_status=BalanceProjectionStatus.RECORDED,
            rider_state=BalanceRiderState.COUNTED.value,
        )
    )
    collectable = operation_status_from_record(
        _record(
            operation_id="br-op-collectable",
            confirmation_status=BalanceConfirmationStatus.FINALIZED,
            projection_status=BalanceProjectionStatus.RECORDED,
            rider_state=BalanceRiderState.COLLECTABLE.value,
        )
    )

    assert counted.rider.read_state == BalanceOperationReadState.RECORDED.value
    assert counted.rider.rider_state == BalanceRiderState.COUNTED.value
    assert collectable.rider.read_state == BalanceOperationReadState.RECORDED.value
    assert collectable.rider.rider_state == BalanceRiderState.COLLECTABLE.value


def test_failed_expired_and_projection_review_read_as_needs_review() -> None:
    failed = operation_status_from_record(
        _record(
            confirmation_status=BalanceConfirmationStatus.FAILED,
            projection_status=BalanceProjectionStatus.NEEDS_REVIEW,
            retry_count=2,
            failure_reason="submit failed",
        )
    )
    expired = operation_status_from_record(
        _record(
            operation_id="br-op-expired",
            confirmation_status=BalanceConfirmationStatus.EXPIRED,
            retry_count=1,
            failure_reason="blockhash expired",
        )
    )
    projection_review = operation_status_from_record(
        _record(
            operation_id="br-op-review",
            confirmation_status=BalanceConfirmationStatus.CONFIRMED,
            projection_status=BalanceProjectionStatus.NEEDS_REVIEW,
            failure_reason="indexer mismatch",
        )
    )

    assert failed.rider.read_state == BalanceOperationReadState.NEEDS_REVIEW.value
    assert failed.rider.rider_state == BalanceRiderState.NEEDS_REVIEW.value
    assert failed.rider.needs_review
    assert failed.support.retry_count == 2
    assert failed.support.failure_reason == "submit failed"
    assert expired.rider.read_state == BalanceOperationReadState.NEEDS_REVIEW.value
    assert expired.support.failure_reason == "blockhash expired"
    assert projection_review.rider.read_state == BalanceOperationReadState.NEEDS_REVIEW.value
    assert projection_review.support.projection_status == BalanceProjectionStatus.NEEDS_REVIEW.value


def test_filter_operation_statuses_by_rider_reference_and_action() -> None:
    target = _record(operation_id="br-op-target", action_type="collect_dung")
    wrong_rider = _record(operation_id="br-op-rider", rider_account_id="rider-456")
    wrong_reference = _record(operation_id="br-op-reference", reference_id="99")
    wrong_action = _record(operation_id="br-op-action", action_type="withdraw_cal")

    statuses = filter_operation_statuses(
        (target, wrong_rider, wrong_reference, wrong_action),
        rider_account_id="rider-123",
        reference_type="vault",
        reference_id="42",
        action_type="collect_dung",
    )

    assert len(statuses) == 1
    assert statuses[0].rider.operation_id == "br-op-target"
    assert statuses[0].rider.action_type == "collect_dung"


def test_operation_record_from_row_round_trips_support_fields() -> None:
    source = _record(
        action_type="withdraw_cal",
        confirmation_status=BalanceConfirmationStatus.CONFIRMED,
        projection_status=BalanceProjectionStatus.DELAYED,
        retry_count=3,
        failure_reason="projection lag",
    )
    row = source.to_row()

    record = operation_record_from_row(row)
    status = operation_status_from_record(record)

    assert record == source
    assert status.rider.read_state == BalanceOperationReadState.DELAYED.value
    assert status.rider.rider_state == BalanceRiderState.DELAYED.value
    assert status.support.action_type == "withdraw_cal"
    assert status.support.retry_count == 3
    assert status.support.failure_reason == "projection lag"
    assert status.support.policy_or_delegate_id == "policy-123"


def test_supabase_reader_get_and_list_for_rider_build_status_models() -> None:
    rows = [
        replace(
            _record(operation_id="br-op-one", action_type="collect_dung"),
            confirmation_status=BalanceConfirmationStatus.FINALIZED.value,
            projection_status=BalanceProjectionStatus.RECORDED.value,
        ).to_row(),
        _record(
            operation_id="br-op-two",
            action_type="withdraw_cal",
            confirmation_status=BalanceConfirmationStatus.CONFIRMED,
        ).to_row(),
        _record(operation_id="br-op-other-rider", rider_account_id="rider-456").to_row(),
    ]
    client = _FakeSupabaseClient(rows)
    reader = SupabaseBalanceOperationReader(client)

    one = reader.get("br-op-one")
    listed = reader.list_for_rider(
        "rider-123",
        reference_type="vault",
        reference_id="42",
        action_type="withdraw_cal",
        limit=10,
    )

    assert one is not None
    assert one.rider.operation_id == "br-op-one"
    assert one.rider.read_state == BalanceOperationReadState.RECORDED.value
    assert one.rider.rider_state == BalanceRiderState.COLLECTED.value
    assert len(listed) == 1
    assert listed[0].rider.operation_id == "br-op-two"
    assert listed[0].rider.read_state == BalanceOperationReadState.DELAYED.value
    assert client.table_names == ["balance_operations", "balance_operations"]
    assert client.queries[1].filters == [
        ("rider_account_id", "rider-123"),
        ("reference_type", "vault"),
        ("reference_id", "42"),
        ("action_type", "withdraw_cal"),
    ]
    assert client.queries[1].limit_count == 10


class _FakeSupabaseClient:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows
        self.table_names: list[str] = []
        self.queries: list[_FakeSupabaseQuery] = []

    def table(self, table_name: str) -> "_FakeSupabaseQuery":
        self.table_names.append(table_name)
        query = _FakeSupabaseQuery(self._rows)
        self.queries.append(query)
        return query


class _FakeSupabaseQuery:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows
        self.filters: list[tuple[str, object]] = []
        self.limit_count: int | None = None

    def select(self, _columns: str) -> "_FakeSupabaseQuery":
        return self

    def eq(self, field: str, value: object) -> "_FakeSupabaseQuery":
        self.filters.append((field, value))
        return self

    def limit(self, count: int) -> "_FakeSupabaseQuery":
        self.limit_count = count
        return self

    def execute(self) -> SimpleNamespace:
        rows = [
            row
            for row in self._rows
            if all(row.get(field) == value for field, value in self.filters)
        ]
        if self.limit_count is not None:
            rows = rows[: self.limit_count]
        return SimpleNamespace(data=rows)
