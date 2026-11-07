"""One durable state machine for all ride economic consequences."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional
from uuid import UUID, uuid4

from ..repositories.ride_economic import RideEconomicRepository
from .ride_attester import OnchainRideIdentity
from .ride_chain_accounts import LegacyCompletionEvidenceError
from .ride_executor import PdaMismatchError, RideExecutor
from .ride_economic_plan import (
    CompletionStepDraft,
    RideEconomicPlanDraft,
    freeze_ride_economic_plan,
)

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class _RideEconomicReviewConflict(RuntimeError):
    def __init__(
        self,
        *,
        operation: str,
        expected_pda: str,
        error: Exception,
        step_index: Optional[int] = None,
        kind: str = "pda_mismatch",
    ) -> None:
        self.kind = kind
        self.evidence: Dict[str, Any] = {
            "version": 1,
            "kind": kind,
            "operation": operation,
            "expected_pda": expected_pda,
            "message": str(error),
            "observed_at": _now_iso(),
        }
        if step_index is not None:
            self.evidence["step_index"] = step_index
        super().__init__(str(error))


@dataclass(frozen=True)
class RideEconomicOutcome:
    status: str
    state: str
    durable_checkpoint: bool
    error: Optional[str] = None
    ride_attestation_pda: Optional[str] = None
    ride_attestation_tx_signature: Optional[str] = None
    ride_attested_at: Optional[str] = None
    cal_tx_signature: Optional[str] = None
    completion_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RideEconomicCoordinator:
    """Freeze, lease, execute, and reconcile one ride economic plan."""

    def __init__(
        self,
        *,
        repository: RideEconomicRepository,
        executor: RideExecutor,
        lease_seconds: int = 300,
        retry_delay_seconds: int = 30,
        lease_owner_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self.repository = repository
        self.executor = executor
        self.lease_seconds = lease_seconds
        self.retry_delay_seconds = retry_delay_seconds
        self._lease_owner_factory = lease_owner_factory

    async def freeze_plan(self, draft: RideEconomicPlanDraft) -> Dict[str, Any]:
        """Persist the immutable plan and exact receipt identities once."""
        return await freeze_ride_economic_plan(
            repository=self.repository, executor=self.executor, draft=draft
        )

    async def execute(self, ride_id: UUID) -> RideEconomicOutcome:
        """Converge a frozen plan while holding its database lease."""
        lease_owner = self._lease_owner_factory()
        plan = await self.repository.acquire_plan(
            ride_id=ride_id,
            lease_owner=lease_owner,
            lease_seconds=self.lease_seconds,
        )
        if plan is None:
            existing = await self.repository.get_plan(ride_id)
            if existing and existing.get("state") == "complete":
                return self._outcome(existing, status="complete", durable=True)
            if existing and existing.get("state") == "review":
                return self._outcome(
                    existing,
                    status="under_review",
                    durable=True,
                    error=existing.get("review_reason"),
                )
            return RideEconomicOutcome(
                status="recovery_pending",
                state=str((existing or {}).get("state") or "missing"),
                durable_checkpoint=existing is not None,
                error="economic plan is missing or currently leased",
            )

        try:
            return await self._execute_leased(
                ride_id=ride_id,
                lease_owner=lease_owner,
                plan=plan,
            )
        except _RideEconomicReviewConflict as exc:
            return await self._review(
                ride_id=ride_id,
                lease_owner=lease_owner,
                plan=plan,
                reason=f"{exc.kind}: {exc}",
                conflict_evidence=exc.evidence,
            )
        except PdaMismatchError as exc:
            return await self._review(
                ride_id=ride_id,
                lease_owner=lease_owner,
                plan=plan,
                reason=f"pda_mismatch: {exc}",
                conflict_evidence={
                    "version": 1,
                    "kind": "pda_mismatch",
                    "operation": "unknown",
                    "message": str(exc),
                    "observed_at": _now_iso(),
                },
            )

    async def _execute_leased(
        self,
        *,
        ride_id: UUID,
        lease_owner: UUID,
        plan: Dict[str, Any],
    ) -> RideEconomicOutcome:
        state = str(plan["state"])
        ride_hash = bytes.fromhex(str(plan["ride_hash_hex"]))
        identity = OnchainRideIdentity(
            ride_hash=ride_hash,
            attestation_commitment=bytes.fromhex(
                str(plan["attestation_commitment_hex"])
            ),
            parser_version=int(plan["parser_version"]),
            source_kind=int(plan["source_kind"]),
        )

        if state == "planned":
            try:
                execution = await self.executor.record_ride_attestation(
                    rider_wallet=str(plan["wallet"]),
                    identity=identity,
                    completed_at=datetime.fromisoformat(str(plan["completed_at"])),
                    started_at=datetime.fromisoformat(str(plan["started_at"])),
                    total_tss=int(plan["total_tss"]),
                    total_distance_m=int(plan["total_distance_m"]),
                    total_vert_m=int(plan["total_vert_m"]),
                    cal_earned=int(plan["exact_cal_base_units"]),
                    climbs_crossed=int(plan["climbs_crossed"]),
                    expected_pda=str(plan["expected_attestation_pda"]),
                )
                confirmed_at = execution.confirmed_at or _now_iso()
                plan = await self.repository.advance_plan(
                    ride_id=ride_id,
                    lease_owner=lease_owner,
                    expected_state="planned",
                    next_state="attestation_confirmed",
                    fields={
                        "attestation_actual_tx_signature": execution.tx_signature,
                        "attestation_confirmed_at": confirmed_at,
                    },
                )
                state = "attestation_confirmed"
            except PdaMismatchError as exc:
                raise _RideEconomicReviewConflict(
                    operation="attestation",
                    expected_pda=str(plan["expected_attestation_pda"]),
                    error=exc,
                ) from exc
            except Exception as exc:
                return await self._retry(
                    ride_id=ride_id,
                    lease_owner=lease_owner,
                    plan=plan,
                    error=f"attestation: {exc}",
                )

        if state == "attestation_confirmed":
            if plan.get("reward_policy") == "threshold_provisional_hold_v1":
                try:
                    admitted_at = str(plan.get("attestation_confirmed_at") or "")
                    if not admitted_at:
                        raise ValueError(
                            "Threshold hold parent lacks its chain admission clock"
                        )
                    await self.repository.record_threshold_provisional_hold_admission(
                        ride_id=ride_id,
                        admitted_at=admitted_at,
                        expected_attestation_pda=str(
                            plan["expected_attestation_pda"]
                        ),
                    )
                except Exception as exc:
                    return await self._retry(
                        ride_id=ride_id,
                        lease_owner=lease_owner,
                        plan=plan,
                        error=f"Threshold hold admission: {exc}",
                    )
            for step in sorted(plan.get("steps") or [], key=lambda row: row["step_index"]):
                if step.get("state") in {"confirmed", "projected"}:
                    continue
                step_index = int(step["step_index"])
                try:
                    execution = await self.executor.record_climb_completion_receipt(
                        rider_wallet=str(plan["wallet"]),
                        ride_hash=ride_hash,
                        vault_id=int(step["vault_id"]),
                        completion_time_s=int(step["completion_time_s"]),
                        cal_tribute=int(step["exact_tribute_base_units"]),
                        completion_evidence_version=int(
                            step.get("completion_evidence_version") or 1
                        ),
                        completion_evidence_hash=bytes.fromhex(
                            str(step["completion_evidence_hash_hex"])
                        ),
                        expected_pda=str(step["expected_receipt_pda"]),
                    )
                    confirmed = await self.repository.confirm_completion_step(
                        ride_id=ride_id,
                        lease_owner=lease_owner,
                        step_index=step_index,
                        expected_receipt_pda=str(step["expected_receipt_pda"]),
                        tx_signature=execution.tx_signature,
                        confirmed_at=execution.confirmed_at or _now_iso(),
                    )
                    step.update(confirmed)
                except LegacyCompletionEvidenceError as exc:
                    raise _RideEconomicReviewConflict(
                        operation="completion",
                        expected_pda=str(step["expected_receipt_pda"]),
                        error=exc,
                        step_index=step_index,
                        kind="legacy_completion_evidence",
                    ) from exc
                except PdaMismatchError as exc:
                    raise _RideEconomicReviewConflict(
                        operation="completion",
                        expected_pda=str(step["expected_receipt_pda"]),
                        error=exc,
                        step_index=step_index,
                    ) from exc
                except Exception as exc:
                    return await self._retry(
                        ride_id=ride_id,
                        lease_owner=lease_owner,
                        plan=plan,
                        error=f"completion[{step_index}]: {exc}",
                        step_index=step_index,
                    )
            try:
                plan = await self.repository.advance_plan(
                    ride_id=ride_id,
                    lease_owner=lease_owner,
                    expected_state="attestation_confirmed",
                    next_state="completions_confirmed",
                )
                state = "completions_confirmed"
            except Exception as exc:
                return await self._retry(
                    ride_id=ride_id,
                    lease_owner=lease_owner,
                    plan=plan,
                    error=f"completion checkpoint: {exc}",
                )

        if state == "completions_confirmed":
            try:
                cal_amount = int(plan["exact_cal_base_units"])
                if cal_amount > 0:
                    execution = await self.executor.credit_cal_receipt(
                        rider_wallet=str(plan["wallet"]),
                        ride_hash=ride_hash,
                        amount=cal_amount,
                        expected_pda=str(plan["expected_cal_receipt_pda"]),
                    )
                    tx_signature = execution.tx_signature
                    confirmed_at = execution.confirmed_at or _now_iso()
                else:
                    tx_signature = None
                    confirmed_at = _now_iso()
                plan = await self.repository.advance_plan(
                    ride_id=ride_id,
                    lease_owner=lease_owner,
                    expected_state="completions_confirmed",
                    next_state="cal_confirmed",
                    fields={
                        "cal_actual_tx_signature": tx_signature,
                        "cal_confirmed_at": confirmed_at,
                    },
                )
                state = "cal_confirmed"
            except PdaMismatchError as exc:
                raise _RideEconomicReviewConflict(
                    operation="cal",
                    expected_pda=str(plan["expected_cal_receipt_pda"]),
                    error=exc,
                ) from exc
            except Exception as exc:
                return await self._retry(
                    ride_id=ride_id,
                    lease_owner=lease_owner,
                    plan=plan,
                    error=f"cal: {exc}",
                )

        if state == "cal_confirmed":
            for step in sorted(plan.get("steps") or [], key=lambda row: row["step_index"]):
                if step.get("state") == "projected":
                    continue
                step_index = int(step["step_index"])
                try:
                    await self.repository.reconcile_completion_projection(
                        ride_id=ride_id,
                        lease_owner=lease_owner,
                        step_index=step_index,
                    )
                    projected = await self.repository.mark_completion_projected(
                        ride_id=ride_id,
                        lease_owner=lease_owner,
                        step_index=step_index,
                    )
                    step.update(projected)
                except Exception as exc:
                    return await self._retry(
                        ride_id=ride_id,
                        lease_owner=lease_owner,
                        plan=plan,
                        error=f"projection[{step_index}]: {exc}",
                        step_index=step_index,
                    )
            try:
                plan = await self.repository.advance_plan(
                    ride_id=ride_id,
                    lease_owner=lease_owner,
                    expected_state="cal_confirmed",
                    next_state="projections_reconciled",
                )
                state = "projections_reconciled"
            except Exception as exc:
                return await self._retry(
                    ride_id=ride_id,
                    lease_owner=lease_owner,
                    plan=plan,
                    error=f"projection checkpoint: {exc}",
                )

        if state == "projections_reconciled":
            try:
                plan = await self.repository.advance_plan(
                    ride_id=ride_id,
                    lease_owner=lease_owner,
                    expected_state="projections_reconciled",
                    next_state="complete",
                )
            except Exception as exc:
                return await self._retry(
                    ride_id=ride_id,
                    lease_owner=lease_owner,
                    plan=plan,
                    error=f"complete checkpoint: {exc}",
                )

        return self._outcome(plan, status="complete", durable=True)

    async def _retry(
        self,
        *,
        ride_id: UUID,
        lease_owner: UUID,
        plan: Dict[str, Any],
        error: str,
        step_index: Optional[int] = None,
    ) -> RideEconomicOutcome:
        durable = False
        checkpoint_error = error
        try:
            durable = await self.repository.checkpoint_retry(
                ride_id=ride_id,
                lease_owner=lease_owner,
                error=error,
                step_index=step_index,
                retry_delay_seconds=self.retry_delay_seconds,
            )
        except Exception as exc:
            checkpoint_error = f"{error}; checkpoint persistence failed: {exc}"
            logger.exception("Ride economic retry checkpoint failed for %s", ride_id)
        return self._outcome(
            plan,
            status="recovery_pending",
            durable=durable,
            error=checkpoint_error,
        )

    async def _review(
        self,
        *,
        ride_id: UUID,
        lease_owner: UUID,
        plan: Dict[str, Any],
        reason: str,
        conflict_evidence: Dict[str, Any],
    ) -> RideEconomicOutcome:
        durable = False
        review_plan = plan
        try:
            review_plan = await self.repository.mark_review(
                ride_id=ride_id,
                lease_owner=lease_owner,
                reason=reason,
                actor="service:ride-economic-coordinator",
                conflict_evidence=conflict_evidence,
            )
            durable = True
        except Exception:
            logger.exception("Ride economic review checkpoint failed for %s", ride_id)
        return self._outcome(
            review_plan,
            status="under_review",
            durable=durable,
            error=reason,
        )

    def _outcome(
        self,
        plan: Dict[str, Any],
        *,
        status: str,
        durable: bool,
        error: Optional[str] = None,
    ) -> RideEconomicOutcome:
        steps = plan.get("steps") or []
        return RideEconomicOutcome(
            status=status,
            state=str(plan.get("state") or "missing"),
            durable_checkpoint=durable,
            error=error,
            ride_attestation_pda=plan.get("expected_attestation_pda"),
            ride_attestation_tx_signature=plan.get(
                "attestation_actual_tx_signature"
            ),
            ride_attested_at=plan.get("attestation_confirmed_at"),
            cal_tx_signature=plan.get("cal_actual_tx_signature"),
            completion_count=sum(
                1 for step in steps if step.get("state") in {"confirmed", "projected"}
            ),
        )
