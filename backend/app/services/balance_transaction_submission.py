"""Confirmed submission boundary for Balance-backed wallet transactions."""

from __future__ import annotations

from dataclasses import dataclass

from .balance_transaction_coordinator import (
    BalanceOperationRecord,
    BalanceTransactionCoordinator,
)
from .tx_builder import (
    SubmittedTransactionExpired,
    SubmittedTransactionFailed,
    SubmittedTransactionPending,
    TxBuilder,
)


@dataclass(frozen=True)
class ConfirmedBalanceSubmission:
    signature: str
    operation: BalanceOperationRecord


class BalanceSubmissionError(RuntimeError):
    """Submission failed or remained ambiguous after updating durable state."""

    def __init__(self, operation: BalanceOperationRecord, message: str) -> None:
        self.operation = operation
        super().__init__(message)


class BalanceSubmissionFailed(BalanceSubmissionError):
    """The chain recorded a terminal transaction error."""


class BalanceSubmissionExpired(BalanceSubmissionError):
    """The prepared signature remained absent through blockhash expiry."""


class BalanceSubmissionPending(BalanceSubmissionError):
    """The deterministic signature still requires authoritative reconciliation."""


async def submit_confirmed_balance_transaction(
    *,
    builder: TxBuilder,
    coordinator: BalanceTransactionCoordinator,
    operation: BalanceOperationRecord,
    transaction_b64: str,
    last_valid_block_height: int,
) -> ConfirmedBalanceSubmission:
    """Submit once and permit projection only after authoritative confirmation."""
    try:
        signature = await builder.submit_signed_transaction(
            transaction_b64,
            last_valid_block_height=last_valid_block_height,
        )
    except SubmittedTransactionExpired as exc:
        submitted = coordinator.mark_submitted(operation, tx_signature=exc.signature)
        failed = coordinator.mark_failed(submitted, reason=str(exc), expired=True)
        raise BalanceSubmissionExpired(failed, str(exc)) from exc
    except SubmittedTransactionFailed as exc:
        submitted = coordinator.mark_submitted(operation, tx_signature=exc.signature)
        failed = coordinator.mark_failed(submitted, reason=str(exc))
        raise BalanceSubmissionFailed(failed, str(exc)) from exc
    except SubmittedTransactionPending as exc:
        submitted = coordinator.mark_submitted(operation, tx_signature=exc.signature)
        raise BalanceSubmissionPending(submitted, str(exc)) from exc

    submitted = coordinator.mark_submitted(operation, tx_signature=signature)
    confirmed = coordinator.mark_confirmed(submitted)
    return ConfirmedBalanceSubmission(signature=signature, operation=confirmed)
