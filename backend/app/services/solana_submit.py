"""Unified Solana transaction submission framework.

Replaces the duplicated fire-and-forget pattern across ~20 send_* functions
in solana_direct.py with a single submit_and_confirm() that provides:

1. Priority fees (compute budget instructions on every transaction)
2. Retry with blockhash expiry detection + exponential backoff
3. Transaction lifecycle tracking in tx_lifecycle table
4. Configurable commitment levels (confirmed/finalized)
5. Structured result objects

Usage:
    from app.services.solana_submit import submit_and_confirm, TxResult

    # Build your instruction(s) as before
    ix = make_record_proof_ix(...)

    result = await submit_and_confirm(
        instructions=[ix],
        signers=[config.payer],
        fee_payer=config.payer.pubkey(),
        tx_type="record_proof",
        reference_type="ride",
        reference_id=ride_id,
        wallet=user_wallet,
    )

    if result.success:
        print(f"Confirmed: {result.signature} at slot {result.slot}")
    else:
        print(f"Failed: {result.error}")
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterator, Optional, Protocol, Sequence

from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed, Finalized
from solders.address_lookup_table_account import AddressLookupTableAccount
from solders.commitment_config import CommitmentLevel
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.rpc.config import RpcContextConfig
from solders.rpc.requests import IsBlockhashValid
from solders.rpc.responses import IsBlockhashValidResp
from solders.transaction import Transaction, VersionedTransaction

from ..metrics import SOLANA_RPC_CALLS, SOLANA_RPC_ERRORS, SOLANA_RPC_LATENCY
from ..solana_env import solana_rpc_url

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Default priority fee in micro-lamports per compute unit.
# 50,000 micro-lamports = 0.05 lamports per CU.
# At 200K CU that's ~10,000 lamports = 0.00001 SOL per tx.
DEFAULT_PRIORITY_FEE_MICRO_LAMPORTS = 50_000

# Default compute unit limit. Most BoulderRollers instructions use <200K CU.
DEFAULT_COMPUTE_UNITS = 200_000

# Solana 1.18 clamps a transaction's requested compute budget at 1.4M CU.
# Reject larger values so lifecycle evidence cannot claim a limit the runtime
# did not apply.
MAX_TRANSACTION_COMPUTE_UNITS = 1_400_000
MICRO_LAMPORTS_PER_LAMPORT = 1_000_000

# Solana's IPv6 MTU-derived serialized transaction ceiling.
PACKET_DATA_SIZE = 1_232

# Maximum number of retries on blockhash expiry
DEFAULT_MAX_RETRIES = 3

# Backoff schedule in seconds (index = retry number)
BACKOFF_SCHEDULE = [2.0, 4.0, 8.0, 16.0, 32.0]

# Confirmation polling interval. 2.0s keeps tx confirmation cheap on Helius
# (most txs confirm in 1-2s anyway); dropping below that just burns RPC credits
# polling getSignatureStatuses.
CONFIRM_POLL_INTERVAL_S = 2.0

# Maximum time to wait for confirmation before treating as timeout
CONFIRM_TIMEOUT_S = 60.0

_CONFIRMATION_RANK = {
    "processed": 0,
    "confirmed": 1,
    "finalized": 2,
}

SubmittedCallback = Callable[[str], Awaitable[None]]


class TransactionEvidenceGuard(Protocol):
    """Optional process-local rehearsal evidence hook; production defaults off."""

    def record_prepared_transaction(
        self,
        transaction: object,
        lookup_tables: Sequence[AddressLookupTableAccount],
        metadata: dict[str, Any],
    ) -> None: ...

    def record_finalized_transaction(
        self,
        signature: str,
        slot: Optional[int],
        status: str,
        metadata: dict[str, Any],
    ) -> None: ...

    def record_terminal_transaction(
        self,
        signature: str,
        status: str,
        metadata: dict[str, Any],
    ) -> None: ...


_TRANSACTION_EVIDENCE_GUARD: contextvars.ContextVar[
    Optional[TransactionEvidenceGuard]
] = contextvars.ContextVar("transaction_evidence_guard", default=None)


@contextlib.contextmanager
def transaction_evidence_guard(
    guard: TransactionEvidenceGuard,
) -> Iterator[None]:
    """Install a scoped fail-closed guard for every unified submission."""
    token = _TRANSACTION_EVIDENCE_GUARD.set(guard)
    try:
        yield
    finally:
        _TRANSACTION_EVIDENCE_GUARD.reset(token)


def activate_transaction_evidence_guard(guard: TransactionEvidenceGuard) -> None:
    """Install a guard for a standalone process-scoped rehearsal command."""
    _TRANSACTION_EVIDENCE_GUARD.set(guard)


def guard_prepared_transaction(
    transaction: object,
    lookup_tables: Optional[Sequence[AddressLookupTableAccount]],
    metadata: dict[str, Any],
) -> None:
    guard = _TRANSACTION_EVIDENCE_GUARD.get()
    if guard is not None:
        guard.record_prepared_transaction(
            transaction,
            tuple(lookup_tables or ()),
            dict(metadata),
        )


def guard_finalized_transaction(
    signature: str,
    slot: Optional[int],
    status: str,
    metadata: dict[str, Any],
) -> None:
    guard = _TRANSACTION_EVIDENCE_GUARD.get()
    if guard is not None:
        guard.record_finalized_transaction(
            signature,
            slot,
            status,
            dict(metadata),
        )


def guard_terminal_transaction(
    signature: str,
    status: str,
    metadata: dict[str, Any],
) -> None:
    """Persist a definitive failed/expired rehearsal attempt, if guarded."""
    guard = _TRANSACTION_EVIDENCE_GUARD.get()
    if guard is not None:
        guard.record_terminal_transaction(
            signature,
            status,
            dict(metadata),
        )


def transaction_evidence_guard_active() -> bool:
    """Return whether the isolated rehearsal lifecycle authority is active."""
    return _TRANSACTION_EVIDENCE_GUARD.get() is not None


class TransactionPacketSizeError(ValueError):
    """A signed transaction cannot fit in one Solana packet."""


async def is_blockhash_valid_compat(
    client: AsyncClient,
    blockhash,
    *,
    commitment=Confirmed,
):
    """Call isBlockhashValid with solana-py versions that omit the helper."""
    public_helper = getattr(client, "is_blockhash_valid", None)
    if callable(public_helper):
        return await public_helper(blockhash, commitment=commitment)

    commitment_level = {
        "processed": CommitmentLevel.Processed,
        "confirmed": CommitmentLevel.Confirmed,
        "finalized": CommitmentLevel.Finalized,
    }.get(str(commitment))
    if commitment_level is None:
        raise ValueError(f"unsupported Solana commitment: {commitment}")

    provider = getattr(client, "_provider", None)
    if provider is None:
        raise AttributeError("Solana RPC client has no request provider")
    request = IsBlockhashValid(
        blockhash,
        RpcContextConfig(commitment=commitment_level),
    )
    return await provider.make_request(request, IsBlockhashValidResp)


def _get_priority_fee() -> int:
    """Read priority fee from env or return default."""
    env_val = os.getenv("SOLANA_PRIORITY_FEE_MICRO_LAMPORTS")
    if env_val is not None:
        try:
            return int(env_val)
        except ValueError:
            logger.warning(
                "Invalid SOLANA_PRIORITY_FEE_MICRO_LAMPORTS=%r, using default %d",
                env_val,
                DEFAULT_PRIORITY_FEE_MICRO_LAMPORTS,
            )
    return DEFAULT_PRIORITY_FEE_MICRO_LAMPORTS


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class TxResult:
    """Outcome of a submit_and_confirm() call."""

    success: bool
    signature: Optional[str] = None
    status: str = "unknown"       # matches tx_lifecycle.status values
    slot: Optional[int] = None
    error: Optional[str] = None
    retry_count: int = 0
    lifecycle_id: Optional[int] = None  # tx_lifecycle.id if tracking enabled

    @property
    def failed(self) -> bool:
        return not self.success


# ---------------------------------------------------------------------------
# Lifecycle tracking (Supabase)
# ---------------------------------------------------------------------------

async def _create_lifecycle_row(
    tx_type: str,
    reference_type: Optional[str],
    reference_id: Optional[str],
    wallet: Optional[str],
    max_retries: int,
    priority_fee_lamports: int,
    compute_units: int,
    instructions_summary: Optional[list[dict]] = None,
) -> Optional[int]:
    """Insert a pending row into tx_lifecycle. Returns the row id, or None on failure."""
    try:
        from ..repositories.base import get_supabase_client
        client = get_supabase_client()

        row = {
            "tx_type": tx_type,
            "status": "pending",
            "priority_fee_lamports": priority_fee_lamports,
            "compute_units": compute_units,
            "max_retries": max_retries,
            "reference_type": reference_type,
            "reference_id": reference_id,
            "wallet": wallet,
        }
        if instructions_summary:
            row["instructions"] = instructions_summary

        result = await asyncio.to_thread(
            lambda: client.table("tx_lifecycle").insert(row).execute()
        )
        if result.data and len(result.data) > 0:
            return result.data[0]["id"]
        return None
    except Exception:
        # Lifecycle tracking is best-effort; never block submission
        logger.warning("Failed to create tx_lifecycle row", exc_info=True)
        return None


async def _update_lifecycle(
    lifecycle_id: Optional[int],
    **fields,
) -> None:
    """Update a tx_lifecycle row. Best-effort, never raises."""
    if lifecycle_id is None:
        return
    try:
        from ..repositories.base import get_supabase_client
        client = get_supabase_client()
        await asyncio.to_thread(
            lambda: client.table("tx_lifecycle")
            .update(fields)
            .eq("id", lifecycle_id)
            .execute()
        )
    except Exception:
        logger.warning("Failed to update tx_lifecycle id=%s", lifecycle_id, exc_info=True)


# ---------------------------------------------------------------------------
# Instruction helpers
# ---------------------------------------------------------------------------

def _prepend_compute_budget(
    instructions: list[Instruction],
    priority_fee_micro_lamports: int,
    compute_units: int,
) -> list[Instruction]:
    """Prepend SetComputeUnitLimit and SetComputeUnitPrice to instruction list."""
    budget_ixs: list[Instruction] = []

    if compute_units > 0:
        budget_ixs.append(set_compute_unit_limit(compute_units))

    if priority_fee_micro_lamports > 0:
        budget_ixs.append(set_compute_unit_price(priority_fee_micro_lamports))

    return budget_ixs + list(instructions)


def _summarize_instructions(instructions: list[Instruction]) -> list[dict]:
    """Create a JSON-safe summary of instructions for debugging."""
    summaries = []
    for ix in instructions:
        summaries.append({
            "program_id": str(ix.program_id),
            "accounts_count": len(ix.accounts),
            "data_len": len(ix.data),
        })
    return summaries


def _build_signed_transaction(
    *,
    instructions: list[Instruction],
    fee_payer: Pubkey,
    signers: list[Keypair],
    blockhash,
    address_lookup_table_accounts: Optional[
        list[AddressLookupTableAccount]
    ] = None,
):
    """Build a legacy or v0 transaction and enforce the wire-size ceiling."""
    if address_lookup_table_accounts:
        message = MessageV0.try_compile(
            fee_payer,
            instructions,
            address_lookup_table_accounts,
            blockhash,
        )
        transaction = VersionedTransaction(message, signers)
    else:
        transaction = Transaction.new_signed_with_payer(
            instructions,
            fee_payer,
            signers,
            blockhash,
        )

    serialized_size = len(bytes(transaction))
    if serialized_size > PACKET_DATA_SIZE:
        raise TransactionPacketSizeError(
            f"transaction serializes to {serialized_size:,} bytes; "
            f"Solana packet limit is {PACKET_DATA_SIZE:,} bytes"
        )
    return transaction


# ---------------------------------------------------------------------------
# Core submission logic
# ---------------------------------------------------------------------------

async def submit_and_confirm(
    instructions: list[Instruction],
    signers: list[Keypair],
    fee_payer: Pubkey,
    tx_type: str,
    reference_type: Optional[str] = None,
    reference_id: Optional[str] = None,
    wallet: Optional[str] = None,
    commitment: str = "confirmed",
    max_retries: int = DEFAULT_MAX_RETRIES,
    priority_fee_micro_lamports: Optional[int] = None,
    compute_units: Optional[int] = None,
    rpc_url: Optional[str] = None,
    skip_lifecycle: bool = False,
    on_prepared: Optional[SubmittedCallback] = None,
    on_submitted: Optional[SubmittedCallback] = None,
    address_lookup_table_accounts: Optional[
        list[AddressLookupTableAccount]
    ] = None,
) -> TxResult:
    """Submit a Solana transaction with priority fees, retries, and lifecycle tracking.

    This is the single entry point for ALL backend-initiated Solana transactions.
    It replaces the duplicated pattern of:
        blockhash = await client.get_latest_blockhash()
        tx = Transaction.new_signed_with_payer(...)
        resp = await client.send_raw_transaction(bytes(tx))
        await client.confirm_transaction(...)

    Args:
        instructions: The application instructions (compute budget is prepended automatically).
        signers: Keypairs that must sign the transaction (first is typically the payer).
        fee_payer: The public key of the fee payer.
        tx_type: Classification for lifecycle tracking (e.g. 'record_proof', 'vault_create').
        reference_type: Optional entity type for correlation (e.g. 'ride', 'vault').
        reference_id: Optional entity ID for correlation.
        wallet: Optional user wallet address for correlation.
        commitment: Desired commitment level ('confirmed' or 'finalized').
        max_retries: Maximum number of retry attempts on blockhash expiry.
        priority_fee_micro_lamports: Override the default priority fee. Pass 0 to disable.
        compute_units: Override the default compute unit limit. Pass 0 to disable.
        rpc_url: Override the default RPC URL.
        skip_lifecycle: If True, skip tx_lifecycle table writes (useful for tests).
        on_prepared: Optional durable callback for the locally signed
            transaction signature, invoked before any send attempt.
        on_submitted: Optional durable callback invoked immediately after RPC
            acceptance and before lifecycle tracking or confirmation polling.
        address_lookup_table_accounts: Optional active lookup tables used to
            compile a v0 transaction. Empty input keeps the legacy encoding.

    Returns:
        TxResult with success/failure, signature, slot, and error details.
    """
    if _TRANSACTION_EVIDENCE_GUARD.get() is not None:
        # The isolated rehearsal artifact is its durable lifecycle authority.
        # Never let that command fall through to production Supabase tracking.
        skip_lifecycle = True
    effective_rpc = rpc_url or solana_rpc_url()
    effective_fee = (
        priority_fee_micro_lamports
        if priority_fee_micro_lamports is not None
        else _get_priority_fee()
    )
    effective_cu = (
        compute_units if compute_units is not None else DEFAULT_COMPUTE_UNITS
    )
    if (
        isinstance(effective_cu, bool)
        or not isinstance(effective_cu, int)
        or not 0 <= effective_cu <= MAX_TRANSACTION_COMPUTE_UNITS
    ):
        raise ValueError(
            "compute unit limit must be between 0 and "
            f"{MAX_TRANSACTION_COMPUTE_UNITS}"
        )
    if (
        isinstance(effective_fee, bool)
        or not isinstance(effective_fee, int)
        or effective_fee < 0
    ):
        raise ValueError("priority fee must be a nonnegative integer")
    if effective_cu == 0 and effective_fee > 0:
        raise ValueError("priority fee requires an explicit positive compute unit limit")
    commitment_obj = Finalized if commitment == "finalized" else Confirmed

    # Prepend compute budget instructions
    full_instructions = _prepend_compute_budget(instructions, effective_fee, effective_cu)

    # Summarize for lifecycle tracking
    ix_summary = _summarize_instructions(instructions)

    # Convert priority fee to total lamports for the lifecycle row, rounding up
    # as the runtime does: (micro-lamports per CU * CU) / 1_000_000.
    total_priority_fee_micro_lamports = effective_fee * effective_cu
    total_priority_lamports = (
        (
            total_priority_fee_micro_lamports
            + MICRO_LAMPORTS_PER_LAMPORT
            - 1
        )
        // MICRO_LAMPORTS_PER_LAMPORT
        if total_priority_fee_micro_lamports > 0
        else 0
    )

    # Create lifecycle row
    lifecycle_id: Optional[int] = None
    if not skip_lifecycle:
        lifecycle_id = await _create_lifecycle_row(
            tx_type=tx_type,
            reference_type=reference_type,
            reference_id=reference_id,
            wallet=wallet,
            max_retries=max_retries,
            priority_fee_lamports=total_priority_lamports,
            compute_units=effective_cu,
            instructions_summary=ix_summary,
        )

    SOLANA_RPC_CALLS.labels(method=tx_type).inc()
    start = time.perf_counter()
    last_error: Optional[str] = None

    try:
        for attempt in range(max_retries + 1):
            try:
                result = await _submit_attempt(
                    rpc_url=effective_rpc,
                    instructions=full_instructions,
                    signers=signers,
                    fee_payer=fee_payer,
                    commitment_obj=commitment_obj,
                    commitment_str=commitment,
                    lifecycle_id=lifecycle_id,
                    tx_type=tx_type,
                    attempt=attempt,
                    on_prepared=on_prepared,
                    on_submitted=on_submitted,
                    address_lookup_table_accounts=address_lookup_table_accounts,
                )
                # Success
                result.retry_count = attempt
                result.lifecycle_id = lifecycle_id
                return result

            except _PreparedSignaturePersistenceError as exc:
                SOLANA_RPC_ERRORS.labels(method=tx_type).inc()
                return TxResult(
                    success=False,
                    signature=exc.signature,
                    status="prepared_persistence_failed",
                    error=str(exc),
                    retry_count=attempt,
                    lifecycle_id=lifecycle_id,
                )

            except _PreparedTransactionAmbiguous as exc:
                if not skip_lifecycle:
                    await _update_lifecycle(
                        lifecycle_id,
                        status="submitted",
                        signature=exc.signature,
                        error_message=str(exc),
                    )
                return TxResult(
                    success=False,
                    signature=exc.signature,
                    status="prepared_ambiguous",
                    error=str(exc),
                    retry_count=attempt,
                    lifecycle_id=lifecycle_id,
                )

            except _AcceptedSignaturePersistenceError as exc:
                SOLANA_RPC_ERRORS.labels(method=tx_type).inc()
                logger.error(
                    "[%s] RPC accepted %s but durable signature callback failed: %s",
                    tx_type,
                    exc.signature,
                    exc,
                )
                if not skip_lifecycle:
                    await _update_lifecycle(
                        lifecycle_id,
                        status="submitted",
                        signature=exc.signature,
                        error_message=str(exc),
                    )
                return TxResult(
                    success=False,
                    signature=exc.signature,
                    status="accepted_ambiguous",
                    error=str(exc),
                    retry_count=attempt,
                    lifecycle_id=lifecycle_id,
                )

            except _AcceptedTransactionPending as exc:
                # Once an accepted signature has been durably handed off, this
                # call must not create a replacement transaction. The owner
                # reconciles that exact signature and finalized chain state.
                if not skip_lifecycle:
                    await _update_lifecycle(
                        lifecycle_id,
                        status="submitted",
                        signature=exc.signature,
                        error_message=str(exc),
                    )
                return TxResult(
                    success=False,
                    signature=exc.signature,
                    status="submitted",
                    error=str(exc),
                    retry_count=attempt,
                    lifecycle_id=lifecycle_id,
                )

            except _BlockhashExpiredError as exc:
                last_error = f"Blockhash expired on attempt {attempt + 1}"
                logger.warning(
                    "[%s] Blockhash expired (attempt %d/%d), retrying...",
                    tx_type,
                    attempt + 1,
                    max_retries + 1,
                )

                if not skip_lifecycle:
                    await _update_lifecycle(
                        lifecycle_id,
                        status="expired",
                        retry_count=attempt + 1,
                        error_message=last_error,
                    )

                if attempt < max_retries:
                    backoff = BACKOFF_SCHEDULE[min(attempt, len(BACKOFF_SCHEDULE) - 1)]
                    await asyncio.sleep(backoff)
                    continue

                # All retries exhausted
                SOLANA_RPC_ERRORS.labels(method=tx_type).inc()
                if not skip_lifecycle:
                    await _update_lifecycle(
                        lifecycle_id,
                        status="failed",
                        failed_at="now()",
                        error_message=f"Blockhash expired after {max_retries + 1} attempts",
                    )
                return TxResult(
                    success=False,
                    status="expired",
                    error=f"Blockhash expired after {max_retries + 1} attempts",
                    retry_count=attempt + 1,
                    lifecycle_id=lifecycle_id,
                )

            except _TxSubmissionError as exc:
                SOLANA_RPC_ERRORS.labels(method=tx_type).inc()
                last_error = str(exc)
                logger.error("[%s] Transaction failed: %s", tx_type, exc)

                if not skip_lifecycle:
                    await _update_lifecycle(
                        lifecycle_id,
                        status="failed",
                        failed_at="now()",
                        error_message=last_error,
                        retry_count=attempt,
                    )
                return TxResult(
                    success=False,
                    status="failed",
                    error=last_error,
                    retry_count=attempt,
                    lifecycle_id=lifecycle_id,
                )

        # Should not reach here, but just in case
        return TxResult(
            success=False,
            status="failed",
            error=last_error or "Unknown error after retries",
            lifecycle_id=lifecycle_id,
        )

    finally:
        SOLANA_RPC_LATENCY.labels(method=tx_type).observe(time.perf_counter() - start)


# ---------------------------------------------------------------------------
# Internal exceptions
# ---------------------------------------------------------------------------

class _BlockhashExpiredError(Exception):
    """Raised when a blockhash has expired before confirmation."""
    pass


class _TxSubmissionError(Exception):
    """Raised when a transaction fails for a non-retryable reason."""
    pass


class BlockhashExpiredError(_BlockhashExpiredError):
    """A signature stayed absent through its last valid block height."""


class TransactionExecutionError(_TxSubmissionError):
    """The chain recorded a terminal execution error for the signature."""


class TransactionConfirmationTimeout(_TxSubmissionError):
    """Confirmation remained ambiguous through the local polling deadline."""


class _AcceptedSignaturePersistenceError(Exception):
    """RPC accepted a signature but its required durable callback failed."""

    def __init__(self, signature: str, error: Exception) -> None:
        self.signature = signature
        super().__init__(f"accepted signature persistence failed: {error}")


class _PreparedSignaturePersistenceError(Exception):
    """A signed transaction could not be durably fenced before send."""

    def __init__(self, signature: str, error: Exception) -> None:
        self.signature = signature
        super().__init__(f"prepared signature persistence failed: {error}")


class _PreparedTransactionAmbiguous(Exception):
    """A send response was lost after the signed signature was persisted."""

    def __init__(self, signature: str, error: Exception) -> None:
        self.signature = signature
        super().__init__(f"prepared transaction send is ambiguous: {error}")


class _AcceptedTransactionPending(Exception):
    """An accepted, durably recorded signature still needs reconciliation."""

    def __init__(self, signature: str, error: Exception) -> None:
        self.signature = signature
        super().__init__(f"accepted transaction requires reconciliation: {error}")


# ---------------------------------------------------------------------------
# Confirmation helpers
# ---------------------------------------------------------------------------

def _confirmation_status_name(status_obj) -> str:
    """Return a lower-case confirmation status name across solana-py shapes."""
    raw_status = getattr(status_obj, "confirmation_status", None)
    if raw_status is None:
        return ""
    raw_value = getattr(raw_status, "value", raw_status)
    normalized = str(raw_value).lower()
    for status in ("finalized", "confirmed", "processed"):
        if status in normalized:
            return status
    return normalized


def _status_satisfies_commitment(status_obj, commitment_str: str) -> bool:
    status = _confirmation_status_name(status_obj)
    if not status:
        # Older RPC response shapes can omit confirmation_status once present.
        return commitment_str != "finalized"
    required = _CONFIRMATION_RANK.get(commitment_str, _CONFIRMATION_RANK["confirmed"])
    current = _CONFIRMATION_RANK.get(status, -1)
    return current >= required


def _is_retryable_confirmation_error(error_msg: str) -> bool:
    lowered = error_msg.lower()
    return any(
        pattern in lowered
        for pattern in (
            "429",
            "too many requests",
            "rate limit",
            "bad gateway",
            "gateway",
            "timeout",
            "temporarily unavailable",
            "connection",
        )
    )


async def _confirm_signature_with_retry(
    client: AsyncClient,
    signature,
    commitment_obj,
    commitment_str: str,
    last_valid_block_height: int,
    tx_type: str,
    recent_blockhash=None,
):
    """Poll signature status after submission.

    Once the transaction is submitted, transient RPC read failures must not turn
    a potentially valid transaction into a recorded protocol failure. Public
    devnet/Helius can rate-limit or return gateway errors while the transaction
    is already landing, so confirmation reads retry until finality, expiry, or
    timeout.
    """
    deadline = time.monotonic() + CONFIRM_TIMEOUT_S
    last_error: Optional[str] = None
    force_history = False

    while True:
        search_history = force_history or time.monotonic() >= deadline
        try:
            statuses = await client.get_signature_statuses(
                [signature],
                search_transaction_history=search_history,
            )
            status_obj = statuses.value[0] if statuses.value else None
            if status_obj is not None:
                if hasattr(status_obj, "err") and status_obj.err is not None:
                    raise TransactionExecutionError(
                        f"Transaction error: {status_obj.err}"
                    )
                if _status_satisfies_commitment(status_obj, commitment_str):
                    return status_obj

            block_height = await client.get_block_height(commitment=commitment_obj)
            blockhash_expired = block_height.value > last_valid_block_height
            if not blockhash_expired and recent_blockhash is not None:
                blockhash_valid = await is_blockhash_valid_compat(
                    client,
                    recent_blockhash,
                    commitment=commitment_obj,
                )
                blockhash_expired = not bool(blockhash_valid.value)

            if blockhash_expired and status_obj is None:
                history = await client.get_signature_statuses(
                    [signature],
                    search_transaction_history=True,
                )
                history_status = history.value[0] if history.value else None
                if history_status is None:
                    expiry_reason = (
                        f"block height {block_height.value} exceeded "
                        f"{last_valid_block_height}"
                        if block_height.value > last_valid_block_height
                        else "recent blockhash is no longer valid"
                    )
                    raise BlockhashExpiredError(
                        "transaction expired without an authoritative signature status: "
                        f"{expiry_reason}"
                    )
                if (
                    hasattr(history_status, "err")
                    and history_status.err is not None
                ):
                    raise TransactionExecutionError(
                        f"Transaction error: {history_status.err}"
                    )
                if _status_satisfies_commitment(history_status, commitment_str):
                    return history_status
                force_history = True

        except (_BlockhashExpiredError, _TxSubmissionError):
            raise
        except Exception as exc:
            last_error = str(exc)
            if _is_retryable_confirmation_error(last_error):
                logger.warning(
                    "[%s] Confirmation poll retry after RPC error: %s",
                    tx_type,
                    last_error,
                )
            else:
                logger.warning(
                    "[%s] Confirmation poll retry after unexpected RPC error",
                    tx_type,
                    exc_info=True,
                )

        if time.monotonic() >= deadline:
            raise TransactionConfirmationTimeout(
                "confirm_transaction timed out"
                + (f" after RPC error: {last_error}" if last_error else "")
            )

        await asyncio.sleep(CONFIRM_POLL_INTERVAL_S)


async def confirm_signature_with_retry(
    client: AsyncClient,
    signature,
    commitment_obj,
    commitment_str: str,
    last_valid_block_height: int,
    tx_type: str,
    recent_blockhash=None,
):
    """Public confirmation authority shared by server- and wallet-signed flows."""
    return await _confirm_signature_with_retry(
        client=client,
        signature=signature,
        commitment_obj=commitment_obj,
        commitment_str=commitment_str,
        last_valid_block_height=last_valid_block_height,
        tx_type=tx_type,
        recent_blockhash=recent_blockhash,
    )


# ---------------------------------------------------------------------------
# Single attempt logic
# ---------------------------------------------------------------------------

async def _submit_attempt(
    rpc_url: str,
    instructions: list[Instruction],
    signers: list[Keypair],
    fee_payer: Pubkey,
    commitment_obj,
    commitment_str: str,
    lifecycle_id: Optional[int],
    tx_type: str,
    attempt: int,
    on_prepared: Optional[SubmittedCallback] = None,
    on_submitted: Optional[SubmittedCallback] = None,
    address_lookup_table_accounts: Optional[
        list[AddressLookupTableAccount]
    ] = None,
) -> TxResult:
    """Execute a single submission attempt. Raises on blockhash expiry or hard failure."""

    async with AsyncClient(rpc_url, commitment=commitment_obj) as client:
        # 1. Get fresh blockhash
        latest = await client.get_latest_blockhash()
        blockhash = latest.value.blockhash
        last_valid_block_height = latest.value.last_valid_block_height

        # 2. Build and sign transaction
        tx = _build_signed_transaction(
            instructions=instructions,
            fee_payer=fee_payer,
            signers=signers,
            blockhash=blockhash,
            address_lookup_table_accounts=address_lookup_table_accounts,
        )
        evidence_metadata = {
            "tx_type": tx_type,
            "attempt": attempt,
            "commitment": commitment_str,
            "recent_blockhash": str(blockhash),
            "last_valid_block_height": int(last_valid_block_height),
        }
        guard_prepared_transaction(
            tx,
            address_lookup_table_accounts,
            evidence_metadata,
        )

        prepared_signature = str(tx.signatures[0])
        if on_prepared is not None:
            try:
                await on_prepared(prepared_signature)
            except Exception as exc:
                raise _PreparedSignaturePersistenceError(
                    prepared_signature,
                    exc,
                ) from exc

        # 3. Update lifecycle with blockhash
        if lifecycle_id is not None:
            await _update_lifecycle(
                lifecycle_id,
                blockhash=str(blockhash),
                last_valid_block_height=last_valid_block_height,
            )

        # 4. Submit
        try:
            resp = await client.send_raw_transaction(bytes(tx))
            signature = resp.value
            sig_str = str(signature)
        except Exception as exc:
            if on_prepared is not None:
                raise _PreparedTransactionAmbiguous(prepared_signature, exc) from exc
            error_msg = str(exc)
            # Check for blockhash-related errors in the RPC response
            if "blockhash not found" in error_msg.lower() or "block height exceeded" in error_msg.lower():
                guard_terminal_transaction(
                    prepared_signature,
                    "expired",
                    {**evidence_metadata, "error": error_msg},
                )
                raise _BlockhashExpiredError(error_msg)
            if transaction_evidence_guard_active():
                # A lost send response is not proof that the signature failed.
                # The durable prepared row must be reconciled on explicit resume.
                raise _PreparedTransactionAmbiguous(prepared_signature, exc) from exc
            raise _TxSubmissionError(f"send_raw_transaction failed: {error_msg}")

        if on_prepared is not None and sig_str != prepared_signature:
            raise _PreparedTransactionAmbiguous(
                prepared_signature,
                RuntimeError(f"RPC returned mismatched signature {sig_str}"),
            )

        logger.info(
            "[%s] Submitted tx %s (attempt %d, blockhash=%s)",
            tx_type,
            sig_str,
            attempt + 1,
            str(blockhash)[:16],
        )

        # This callback is the settlement durability boundary. It deliberately
        # precedes best-effort tx_lifecycle writes and potentially long finality
        # polling so lease ownership cannot be lost with an unknown signature.
        if on_submitted is not None:
            try:
                await on_submitted(sig_str)
            except Exception as exc:
                raise _AcceptedSignaturePersistenceError(sig_str, exc) from exc

        # 5. Update lifecycle to submitted
        if lifecycle_id is not None:
            await _update_lifecycle(
                lifecycle_id,
                status="submitted",
                signature=sig_str,
                submitted_at="now()",
            )

        # 6. Poll for confirmation with block height expiry check
        try:
            status_obj = await _confirm_signature_with_retry(
                client=client,
                signature=signature,
                commitment_obj=commitment_obj,
                commitment_str=commitment_str,
                last_valid_block_height=last_valid_block_height,
                tx_type=tx_type,
            )
        except TransactionExecutionError as exc:
            guard_terminal_transaction(
                sig_str,
                "failed",
                {**evidence_metadata, "error": str(exc)},
            )
            raise
        except BlockhashExpiredError as exc:
            guard_terminal_transaction(
                sig_str,
                "expired",
                {**evidence_metadata, "error": str(exc)},
            )
            raise
        except TransactionConfirmationTimeout as exc:
            if on_submitted is not None or transaction_evidence_guard_active():
                raise _AcceptedTransactionPending(sig_str, exc) from exc
            raise
        except Exception as exc:
            if on_submitted is not None or transaction_evidence_guard_active():
                raise _AcceptedTransactionPending(sig_str, exc) from exc
            error_msg = str(exc)
            if "block height exceeded" in error_msg.lower() or "expired" in error_msg.lower():
                guard_terminal_transaction(
                    sig_str,
                    "expired",
                    {**evidence_metadata, "error": error_msg},
                )
                raise _BlockhashExpiredError(error_msg)
            raise _TxSubmissionError(f"confirm_transaction failed: {error_msg}")

        # 7. Parse confirmation result
        if status_obj is not None:
            # Extract slot if available
            slot = None
            if hasattr(status_obj, 'slot'):
                slot = status_obj.slot

            # Determine final status from commitment
            final_status = commitment_str  # 'confirmed' or 'finalized'
            ts_field = f"{final_status}_at"

            if lifecycle_id is not None:
                update_fields = {
                    "status": final_status,
                    ts_field: "now()",
                    "retry_count": attempt,
                }
                if slot is not None:
                    update_fields["slot"] = slot
                await _update_lifecycle(lifecycle_id, **update_fields)

            guard_finalized_transaction(
                sig_str,
                int(slot) if slot is not None else None,
                final_status,
                evidence_metadata,
            )

            return TxResult(
                success=True,
                signature=sig_str,
                status=final_status,
                slot=slot,
            )

        # Confirmation returned but no status info — treat as confirmed
        if lifecycle_id is not None:
            await _update_lifecycle(
                lifecycle_id,
                status=commitment_str,
                confirmed_at="now()",
                retry_count=attempt,
                signature=sig_str,
            )

        guard_finalized_transaction(
            sig_str,
            None,
            commitment_str,
            evidence_metadata,
        )

        return TxResult(
            success=True,
            signature=sig_str,
            status=commitment_str,
        )
