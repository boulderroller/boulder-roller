"""Boulder Roller Balance transaction coordinator contract.

The coordinator sits above concrete Solana builders/submission code. It checks
which authority model is allowed for a rider action, creates a stable operation
record, and keeps confirmation state separate from app projection state.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Mapping, Protocol

from .boulder_balance_authority import (
    AuthorityModel,
    BalanceAuthorityPolicy,
    BoundaryStepUp,
    NORMAL_BALANCE_ACTIONS,
    policy_for_action,
)
from .balance_authority_execution import (
    plan_balance_authority_execution,
)
from .balance_lifecycle import (
    RiderBalanceStatus,
    balance_authority_active_for_status,
    no_prompt_lifecycle_blockers,
)

logger = logging.getLogger(__name__)


class BalanceOperationError(ValueError):
    """Raised when an operation intent violates the Balance authority model."""


class BalanceActionBudgetExceeded(BalanceOperationError):
    """Raised when sponsored Balance action budgets are exhausted."""

    def __init__(
        self,
        *,
        action_type: str,
        scope: str,
        limit: int,
        used: int,
        rider_message: str,
        retry_after_seconds: int,
    ) -> None:
        super().__init__(
            f"{action_type}: {scope} daily Balance action budget exceeded "
            f"({used}/{limit})"
        )
        self.action_type = action_type
        self.scope = scope
        self.limit = limit
        self.used = used
        self.rider_message = rider_message
        self.retry_after_seconds = retry_after_seconds


DEFAULT_RIDER_DAILY_ACTION_BUDGETS: Mapping[str, int] = {
    "collect_dung": 12,
    "deposit_cal": 8,
    "withdraw_cal": 8,
    "create_vault": 3,
    "pay_usdc": 8,
}
DEFAULT_GLOBAL_DAILY_ACTION_BUDGET = 500
_FALSE_ENV_VALUES = {"0", "false", "no", "off"}


class BalanceConfirmationStatus(str, Enum):
    """Chain-facing operation state."""

    PREPARED = "prepared"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    FINALIZED = "finalized"
    FAILED = "failed"
    EXPIRED = "expired"


class BalanceProjectionStatus(str, Enum):
    """App/indexer-facing operation state."""

    NOT_STARTED = "not_started"
    PENDING = "pending"
    RECORDED = "recorded"
    DELAYED = "delayed"
    NEEDS_REVIEW = "needs_review"


class BalanceRiderState(str, Enum):
    """Rider-facing state language for primary Balance surfaces."""

    COUNTED = "Counted"
    COLLECTABLE = "Collectable"
    COLLECTED = "Collected"
    PENDING = "Pending"
    DELAYED = "Delayed"
    NEEDS_REVIEW = "Needs review"


FINAL_RIDER_STATE_BY_ACTION = {
    "collect_dung": BalanceRiderState.COLLECTED,
}


@dataclass(frozen=True)
class BalanceOperationIntent:
    """Input checked before a route builds or submits a Balance operation."""

    action_type: str
    rider_account_id: str
    protocol_wallet: str
    authority_model: AuthorityModel
    asset: str
    amount: str
    source: str
    destination: str
    reference_type: str | None = None
    reference_id: str | None = None
    idempotency_key: str | None = None
    prepared_message_hash: str | None = None
    fee_payer: str | None = None
    policy_or_delegate_id: str | None = None
    tx_signature: str | None = None
    program_config_checked: bool = True
    revocation_checked: bool = True
    step_up_satisfied: bool = False
    balance_authority_active: bool = True
    policy_or_delegate_active: bool = True
    boulder_constraints_checked: bool = True
    balance_lifecycle_status: RiderBalanceStatus = RiderBalanceStatus.ACTIVE
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class BalanceOperationRecord:
    """Durable operation ledger shape for support, retries, and admin review."""

    operation_id: str
    rider_account_id: str
    protocol_wallet: str
    action_type: str
    authority_model: str
    asset: str
    amount: str
    source: str
    destination: str
    idempotency_key: str
    prepared_message_hash: str | None
    fee_payer: str | None
    policy_or_delegate_id: str | None
    tx_signature: str | None
    confirmation_status: str
    projection_status: str
    retry_count: int
    failure_reason: str | None
    reference_type: str | None
    reference_id: str | None
    rider_state: str | None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def to_row(self) -> dict[str, object]:
        """JSON-safe row shape for persistence adapters."""

        return {
            "operation_id": self.operation_id,
            "rider_account_id": self.rider_account_id,
            "protocol_wallet": self.protocol_wallet,
            "action_type": self.action_type,
            "authority_model": self.authority_model,
            "asset": self.asset,
            "amount": self.amount,
            "source": self.source,
            "destination": self.destination,
            "idempotency_key": self.idempotency_key,
            "prepared_message_hash": self.prepared_message_hash,
            "fee_payer": self.fee_payer,
            "policy_or_delegate_id": self.policy_or_delegate_id,
            "tx_signature": self.tx_signature,
            "confirmation_status": self.confirmation_status,
            "projection_status": self.projection_status,
            "retry_count": self.retry_count,
            "failure_reason": self.failure_reason,
            "reference_type": self.reference_type,
            "reference_id": self.reference_id,
            "rider_state": self.rider_state,
            "metadata": dict(self.metadata),
        }


class BalanceOperationSink(Protocol):
    """Persistence boundary for operation records."""

    def insert(self, record: BalanceOperationRecord) -> None:
        ...

    def update(self, record: BalanceOperationRecord) -> None:
        ...


class BalanceActionBudgetStore(Protocol):
    """Read-side budget boundary for sponsored Balance action attempts."""

    def count_rider_actions(
        self,
        *,
        rider_account_id: str,
        action_type: str,
        window_start: datetime,
        window_end: datetime,
    ) -> int:
        ...

    def count_global_actions(
        self,
        *,
        window_start: datetime,
        window_end: datetime,
        action_types: tuple[str, ...] | None = None,
    ) -> int:
        ...


@dataclass(frozen=True)
class BalanceActionBudgetPolicy:
    """Configurable daily budgets for sponsored Balance operations."""

    enabled: bool = True
    rider_daily_budgets: Mapping[str, int] = field(
        default_factory=lambda: dict(DEFAULT_RIDER_DAILY_ACTION_BUDGETS)
    )
    global_daily_budget: int | None = DEFAULT_GLOBAL_DAILY_ACTION_BUDGET

    @classmethod
    def from_env(cls) -> "BalanceActionBudgetPolicy":
        """Load budget limits from environment variables.

        Action-specific variables use the form
        BALANCE_RIDER_DAILY_<ACTION>_BUDGET, for example
        BALANCE_RIDER_DAILY_COLLECT_DUNG_BUDGET.
        """

        enabled = _env_bool("BALANCE_ACTION_BUDGETS_ENABLED", default=True)
        default_rider_budget = _env_int("BALANCE_RIDER_DAILY_ACTION_BUDGET", default=None)
        rider_daily_budgets = {
            action: _env_int(
                f"BALANCE_RIDER_DAILY_{action.upper()}_BUDGET",
                default=default_rider_budget
                if default_rider_budget is not None
                else DEFAULT_RIDER_DAILY_ACTION_BUDGETS[action],
            )
            for action in NORMAL_BALANCE_ACTIONS
        }
        return cls(
            enabled=enabled,
            rider_daily_budgets=rider_daily_budgets,
            global_daily_budget=_env_int(
                "BALANCE_GLOBAL_DAILY_ACTION_BUDGET",
                default=DEFAULT_GLOBAL_DAILY_ACTION_BUDGET,
            ),
        )

    def rider_limit_for(self, action_type: str) -> int | None:
        return self.rider_daily_budgets.get(action_type)


class InMemoryBalanceOperationLog:
    """Small test/dev sink with the same contract as a durable adapter."""

    def __init__(self) -> None:
        self.records: dict[str, BalanceOperationRecord] = {}
        self.created_at: dict[str, datetime] = {}

    def insert(self, record: BalanceOperationRecord) -> None:
        if record.operation_id in self.records:
            raise BalanceOperationError(f"Duplicate Balance operation: {record.operation_id}")
        self.records[record.operation_id] = record
        self.created_at[record.operation_id] = datetime.now(timezone.utc)

    def update(self, record: BalanceOperationRecord) -> None:
        if record.operation_id not in self.records:
            raise BalanceOperationError(f"Unknown Balance operation: {record.operation_id}")
        self.records[record.operation_id] = record

    def get(self, operation_id: str) -> BalanceOperationRecord | None:
        return self.records.get(operation_id)

    def count_rider_actions(
        self,
        *,
        rider_account_id: str,
        action_type: str,
        window_start: datetime,
        window_end: datetime,
    ) -> int:
        return sum(
            1
            for record in self.records.values()
            if record.rider_account_id == rider_account_id
            and record.action_type == action_type
            and _within_window(self.created_at.get(record.operation_id), window_start, window_end)
        )

    def count_global_actions(
        self,
        *,
        window_start: datetime,
        window_end: datetime,
        action_types: tuple[str, ...] | None = None,
    ) -> int:
        return sum(
            1
            for record in self.records.values()
            if (action_types is None or record.action_type in action_types)
            and _within_window(self.created_at.get(record.operation_id), window_start, window_end)
        )


class SupabaseBalanceOperationSink:
    """Supabase-backed sink for the balance_operations ledger."""

    def __init__(self, client) -> None:
        self._client = client

    def insert(self, record: BalanceOperationRecord) -> None:
        self._write(record, method="insert", strict=True)

    def update(self, record: BalanceOperationRecord) -> None:
        self._write(record, method="upsert", strict=False)

    def count_rider_actions(
        self,
        *,
        rider_account_id: str,
        action_type: str,
        window_start: datetime,
        window_end: datetime,
    ) -> int:
        return self._count_actions(
            rider_account_id=rider_account_id,
            action_type=action_type,
            window_start=window_start,
            window_end=window_end,
        )

    def count_global_actions(
        self,
        *,
        window_start: datetime,
        window_end: datetime,
        action_types: tuple[str, ...] | None = None,
    ) -> int:
        return self._count_actions(
            rider_account_id=None,
            action_type=None,
            action_types=action_types,
            window_start=window_start,
            window_end=window_end,
        )

    def _count_actions(
        self,
        *,
        rider_account_id: str | None,
        action_type: str | None,
        action_types: tuple[str, ...] | None = None,
        window_start: datetime,
        window_end: datetime,
    ) -> int:
        try:
            query = (
                self._client.table("balance_operations")
                .select("operation_id", count="exact")
                .gte("created_at", window_start.isoformat())
                .lt("created_at", window_end.isoformat())
            )
            if rider_account_id is not None:
                query = query.eq("rider_account_id", rider_account_id)
            if action_type is not None:
                query = query.eq("action_type", action_type)
            elif action_types:
                query = query.in_("action_type", list(action_types))
            response = query.execute()
        except Exception as exc:
            logger.warning("[BalanceCoordinator] Failed to read action budgets: %s", exc)
            raise BalanceOperationError("Balance action budget check failed") from exc
        return int(getattr(response, "count", 0) or 0)

    def _write(
        self,
        record: BalanceOperationRecord,
        *,
        method: str,
        strict: bool,
    ) -> None:
        try:
            table = self._client.table("balance_operations")
            writer = getattr(table, method)
            writer(record.to_row()).execute()
        except Exception as exc:
            logger.warning(
                "[BalanceCoordinator] Failed to persist operation %s action=%s: %s",
                record.operation_id,
                record.action_type,
                exc,
            )
            if strict:
                raise BalanceOperationError(
                    f"Failed to persist Balance operation {record.operation_id}"
                ) from exc


class BalanceTransactionCoordinator:
    """Validate and record Balance operations before Solana execution."""

    def __init__(
        self,
        sink: BalanceOperationSink | None = None,
        *,
        budget_store: BalanceActionBudgetStore | None = None,
        budget_policy: BalanceActionBudgetPolicy | None = None,
        clock=None,
    ) -> None:
        self.sink = sink
        self.budget_store = budget_store
        self.budget_policy = budget_policy or BalanceActionBudgetPolicy.from_env()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def prepared_message_hash(message_bytes: bytes) -> str:
        return hashlib.sha256(message_bytes).hexdigest()

    def prepare_operation(self, intent: BalanceOperationIntent) -> BalanceOperationRecord:
        policy = policy_for_action(intent.action_type)
        self._validate_intent(intent, policy)
        self._enforce_action_budget(intent, policy)

        idempotency_key = intent.idempotency_key or self._derive_idempotency_key(intent)
        operation_id = self._derive_operation_id(idempotency_key)
        record = BalanceOperationRecord(
            operation_id=operation_id,
            rider_account_id=intent.rider_account_id,
            protocol_wallet=intent.protocol_wallet,
            action_type=intent.action_type,
            authority_model=intent.authority_model.value,
            asset=intent.asset,
            amount=intent.amount,
            source=intent.source,
            destination=intent.destination,
            idempotency_key=idempotency_key,
            prepared_message_hash=intent.prepared_message_hash,
            fee_payer=intent.fee_payer,
            policy_or_delegate_id=intent.policy_or_delegate_id,
            tx_signature=intent.tx_signature,
            confirmation_status=BalanceConfirmationStatus.PREPARED.value,
            projection_status=BalanceProjectionStatus.NOT_STARTED.value,
            retry_count=0,
            failure_reason=None,
            reference_type=intent.reference_type,
            reference_id=intent.reference_id,
            rider_state=BalanceRiderState.PENDING.value,
            metadata=dict(intent.metadata),
        )
        self._insert(record)
        return record

    def mark_submitted(self, record: BalanceOperationRecord, tx_signature: str) -> BalanceOperationRecord:
        return self._update(
            replace(
                record,
                tx_signature=tx_signature,
                confirmation_status=BalanceConfirmationStatus.SUBMITTED.value,
                rider_state=BalanceRiderState.PENDING.value,
            )
        )

    def mark_confirmed(
        self,
        record: BalanceOperationRecord,
        *,
        finalized: bool = False,
    ) -> BalanceOperationRecord:
        status = BalanceConfirmationStatus.FINALIZED if finalized else BalanceConfirmationStatus.CONFIRMED
        return self._update(
            replace(
                record,
                confirmation_status=status.value,
                rider_state=self.rider_state_for(
                    replace(record, confirmation_status=status.value)
                ),
            )
        )

    def mark_projection(
        self,
        record: BalanceOperationRecord,
        projection_status: BalanceProjectionStatus,
    ) -> BalanceOperationRecord:
        updated = replace(record, projection_status=projection_status.value)
        return self._update(replace(updated, rider_state=self.rider_state_for(updated)))

    def mark_projection_recorded(self, record: BalanceOperationRecord) -> BalanceOperationRecord:
        confirmed = self.mark_confirmed(record)
        return self.mark_projection(confirmed, BalanceProjectionStatus.RECORDED)

    def mark_projection_delayed(
        self,
        record: BalanceOperationRecord,
        *,
        failure_reason: str | None = None,
    ) -> BalanceOperationRecord:
        updated = replace(
            record,
            projection_status=BalanceProjectionStatus.DELAYED.value,
            failure_reason=failure_reason,
        )
        return self._update(replace(updated, rider_state=self.rider_state_for(updated)))

    def mark_retry(self, record: BalanceOperationRecord) -> BalanceOperationRecord:
        return self._update(replace(record, retry_count=record.retry_count + 1))

    def mark_failed(
        self,
        record: BalanceOperationRecord,
        *,
        reason: str,
        expired: bool = False,
    ) -> BalanceOperationRecord:
        confirmation = BalanceConfirmationStatus.EXPIRED if expired else BalanceConfirmationStatus.FAILED
        return self._update(
            replace(
                record,
                confirmation_status=confirmation.value,
                projection_status=BalanceProjectionStatus.NEEDS_REVIEW.value,
                failure_reason=reason,
                rider_state=BalanceRiderState.NEEDS_REVIEW.value,
            )
        )

    @staticmethod
    def rider_state_for(record: BalanceOperationRecord) -> str | None:
        confirmation = BalanceConfirmationStatus(record.confirmation_status)
        projection = BalanceProjectionStatus(record.projection_status)

        if confirmation in (BalanceConfirmationStatus.FAILED, BalanceConfirmationStatus.EXPIRED):
            return BalanceRiderState.NEEDS_REVIEW.value
        if projection is BalanceProjectionStatus.NEEDS_REVIEW:
            return BalanceRiderState.NEEDS_REVIEW.value
        if projection is BalanceProjectionStatus.DELAYED:
            return BalanceRiderState.DELAYED.value
        if projection is BalanceProjectionStatus.PENDING:
            return BalanceRiderState.PENDING.value
        if confirmation in (BalanceConfirmationStatus.PREPARED, BalanceConfirmationStatus.SUBMITTED):
            return BalanceRiderState.PENDING.value
        if projection is BalanceProjectionStatus.NOT_STARTED:
            return BalanceRiderState.DELAYED.value
        if projection is BalanceProjectionStatus.RECORDED:
            final_state = FINAL_RIDER_STATE_BY_ACTION.get(record.action_type)
            return final_state.value if final_state else None
        return BalanceRiderState.NEEDS_REVIEW.value

    @staticmethod
    def _derive_operation_id(idempotency_key: str) -> str:
        digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        return f"br-op-{digest[:24]}"

    @staticmethod
    def _derive_idempotency_key(intent: BalanceOperationIntent) -> str:
        parts = (
            intent.action_type,
            intent.rider_account_id,
            intent.protocol_wallet,
            intent.authority_model.value,
            intent.asset,
            intent.amount,
            intent.source,
            intent.destination,
            intent.reference_type or "",
            intent.reference_id or "",
        )
        digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
        return f"br:{intent.action_type}:{digest}"

    def _insert(self, record: BalanceOperationRecord) -> None:
        if self.sink is not None:
            self.sink.insert(record)

    def _update(self, record: BalanceOperationRecord) -> BalanceOperationRecord:
        if self.sink is not None:
            self.sink.update(record)
        return record

    def _enforce_action_budget(
        self,
        intent: BalanceOperationIntent,
        policy: BalanceAuthorityPolicy,
    ) -> None:
        if self.budget_store is None or not self.budget_policy.enabled:
            return

        budgeted_actions = tuple(self.budget_policy.rider_daily_budgets.keys())
        if intent.action_type not in budgeted_actions:
            return

        now = _coerce_utc(self._clock())
        window_start, window_end = _daily_utc_window(now)
        retry_after_seconds = max(1, int((window_end - now).total_seconds()))

        rider_limit = self.budget_policy.rider_limit_for(intent.action_type)
        if rider_limit is not None:
            rider_count = self.budget_store.count_rider_actions(
                rider_account_id=intent.rider_account_id,
                action_type=intent.action_type,
                window_start=window_start,
                window_end=window_end,
            )
            if rider_count >= rider_limit:
                raise BalanceActionBudgetExceeded(
                    action_type=intent.action_type,
                    scope="rider",
                    limit=rider_limit,
                    used=rider_count,
                    rider_message=f"Today's {policy.rider_label} limit is reached. Try again tomorrow.",
                    retry_after_seconds=retry_after_seconds,
                )

        global_limit = self.budget_policy.global_daily_budget
        if global_limit is not None:
            global_count = self.budget_store.count_global_actions(
                window_start=window_start,
                window_end=window_end,
                action_types=budgeted_actions,
            )
            if global_count >= global_limit:
                raise BalanceActionBudgetExceeded(
                    action_type=intent.action_type,
                    scope="global",
                    limit=global_limit,
                    used=global_count,
                    rider_message="Today's Balance action limit is reached. Try again tomorrow.",
                    retry_after_seconds=retry_after_seconds,
                )

    @staticmethod
    def _validate_intent(intent: BalanceOperationIntent, policy: BalanceAuthorityPolicy) -> None:
        if intent.authority_model not in policy.authority_models:
            raise BalanceOperationError(
                f"{intent.action_type}: authority model {intent.authority_model.value} is not allowed"
            )
        if not intent.asset:
            raise BalanceOperationError(f"{intent.action_type}: missing asset")
        if not intent.amount:
            raise BalanceOperationError(f"{intent.action_type}: missing amount")
        if not intent.source:
            raise BalanceOperationError(f"{intent.action_type}: missing source")
        if not intent.destination:
            raise BalanceOperationError(f"{intent.action_type}: missing destination")

        intent_assets = _split_assets(intent.asset)
        unsupported_assets = [asset for asset in intent_assets if asset not in policy.assets]
        if unsupported_assets:
            raise BalanceOperationError(
                f"{intent.action_type}: unsupported asset(s): {', '.join(unsupported_assets)}"
            )

        if policy.requires_program_config and not intent.program_config_checked:
            raise BalanceOperationError(f"{intent.action_type}: ProgramConfig check is required")
        if policy.requires_revocation_check and not intent.revocation_checked:
            raise BalanceOperationError(f"{intent.action_type}: revocation check is required")

        if intent.authority_model in (
            AuthorityModel.RIDER_SESSION,
            AuthorityModel.PRIVY_POLICY_SIGNER,
            AuthorityModel.SPL_DELEGATE,
        ):
            if not intent.policy_or_delegate_id:
                raise BalanceOperationError(
                    f"{intent.action_type}: policy_or_delegate_id is required for "
                    f"{intent.authority_model.value}"
                )

        if intent.authority_model is AuthorityModel.WALLET_BOUNDARY and not intent.step_up_satisfied:
            raise BalanceOperationError(
                f"{intent.action_type}: wallet-boundary execution requires step-up "
                f"({BoundaryStepUp.WALLET_CONFIRMATION.value} or stronger)"
            )

        try:
            lifecycle_blockers = no_prompt_lifecycle_blockers(intent.balance_lifecycle_status)
        except ValueError as exc:
            raise BalanceOperationError(f"{intent.action_type}: {exc}") from exc

        if lifecycle_blockers and intent.authority_model is not AuthorityModel.WALLET_BOUNDARY:
            raise BalanceOperationError(
                f"{intent.action_type}: account security rejected "
                f"({', '.join(blocker.value for blocker in lifecycle_blockers)})"
            )

        execution_plan = plan_balance_authority_execution(
            action_type=intent.action_type,
            authority_model=intent.authority_model,
            policy_or_delegate_id=intent.policy_or_delegate_id,
            balance_authority_active=(
                intent.balance_authority_active
                and balance_authority_active_for_status(intent.balance_lifecycle_status)
            ),
            policy_or_delegate_active=intent.policy_or_delegate_active,
            boulder_constraints_checked=intent.boulder_constraints_checked,
            step_up_satisfied=intent.step_up_satisfied,
        )
        if not execution_plan.allowed:
            raise BalanceOperationError(
                f"{intent.action_type}: authority execution rejected "
                f"({', '.join(failure.value for failure in execution_plan.failures)})"
            )


def _split_assets(asset: str) -> tuple[str, ...]:
    normalized = asset.replace("+", ",")
    return tuple(part.strip() for part in normalized.split(",") if part.strip())


def _coerce_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _daily_utc_window(now: datetime) -> tuple[datetime, datetime]:
    start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def _within_window(
    created_at: datetime | None,
    window_start: datetime,
    window_end: datetime,
) -> bool:
    if created_at is None:
        return False
    created_at = _coerce_utc(created_at)
    return window_start <= created_at < window_end


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in _FALSE_ENV_VALUES


def _env_int(name: str, *, default: int | None) -> int | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid integer for %s=%r; using %r", name, raw, default)
        return default


def prepared_message_hash(transaction_b64: str) -> str:
    """Hash serialized prepared transaction bytes from the route builder."""

    return BalanceTransactionCoordinator.prepared_message_hash(base64.b64decode(transaction_b64))
