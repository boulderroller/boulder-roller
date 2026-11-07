from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.services.balance_transaction_coordinator import (
    BalanceConfirmationStatus,
    BalanceOperationIntent,
    BalanceTransactionCoordinator,
    InMemoryBalanceOperationLog,
)
from app.services.balance_transaction_submission import (
    BalanceSubmissionExpired,
    BalanceSubmissionFailed,
    BalanceSubmissionPending,
    submit_confirmed_balance_transaction,
)
from app.services.boulder_balance_authority import AuthorityModel
from app.services.tx_builder import (
    SubmittedTransactionExpired,
    SubmittedTransactionFailed,
    SubmittedTransactionPending,
)


def _prepared_operation():
    log = InMemoryBalanceOperationLog()
    coordinator = BalanceTransactionCoordinator(sink=log)
    operation = coordinator.prepare_operation(
        BalanceOperationIntent(
            action_type="deposit_cal",
            rider_account_id="rider-1",
            protocol_wallet="wallet-1",
            authority_model=AuthorityModel.WALLET_BOUNDARY,
            asset="CAL",
            amount="250000000000",
            source="wallet-1",
            destination="vault:42:cal_escrow",
            idempotency_key="deposit:request-1",
            prepared_message_hash="message-hash-1",
            step_up_satisfied=True,
        )
    )
    return coordinator, log, operation


@pytest.mark.asyncio
async def test_confirmed_submission_is_durable_before_projection() -> None:
    coordinator, log, operation = _prepared_operation()
    builder = AsyncMock()
    builder.submit_signed_transaction.return_value = "signature-1"

    result = await submit_confirmed_balance_transaction(
        builder=builder,
        coordinator=coordinator,
        operation=operation,
        transaction_b64="signed-bytes",
        last_valid_block_height=123,
    )

    assert result.signature == "signature-1"
    assert result.operation.confirmation_status == BalanceConfirmationStatus.CONFIRMED.value
    assert log.get(operation.operation_id) == result.operation
    builder.submit_signed_transaction.assert_awaited_once_with(
        "signed-bytes",
        last_valid_block_height=123,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("builder_error", "service_error", "expected_status"),
    [
        (
            SubmittedTransactionFailed("signature-1", "chain rejected"),
            BalanceSubmissionFailed,
            BalanceConfirmationStatus.FAILED.value,
        ),
        (
            SubmittedTransactionExpired("signature-1", "blockhash expired"),
            BalanceSubmissionExpired,
            BalanceConfirmationStatus.EXPIRED.value,
        ),
        (
            SubmittedTransactionPending("signature-1", "RPC unavailable"),
            BalanceSubmissionPending,
            BalanceConfirmationStatus.SUBMITTED.value,
        ),
    ],
)
async def test_submission_outcome_preserves_authoritative_lifecycle_state(
    builder_error,
    service_error,
    expected_status,
) -> None:
    coordinator, log, operation = _prepared_operation()
    builder = AsyncMock()
    builder.submit_signed_transaction.side_effect = builder_error

    with pytest.raises(service_error) as exc_info:
        await submit_confirmed_balance_transaction(
            builder=builder,
            coordinator=coordinator,
            operation=operation,
            transaction_b64="signed-bytes",
            last_valid_block_height=123,
        )

    recorded = log.get(operation.operation_id)
    assert recorded == exc_info.value.operation
    assert recorded.confirmation_status == expected_status
    assert recorded.tx_signature == "signature-1"
