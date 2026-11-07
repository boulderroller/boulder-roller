"""Durable execution order for receipt-backed held-ride economics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any, Callable, Optional
from uuid import UUID, uuid4

from celery.exceptions import SoftTimeLimitExceeded

from ..repositories.ride_economic import (
    RideEconomicRepository,
    ThresholdReleaseAuthorityConflictError,
)
from .chain_receipt_execution import PdaMismatchError
from .ride_chain_accounts import ChainAccountMismatchError
from .threshold_release_executor import ThresholdReleaseExecutor


logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ThresholdReleaseOutcome:
    status: str
    state: str
    durable_checkpoint: bool
    snapshot_id: Optional[str] = None
    error: Optional[str] = None


class ThresholdReleaseCoordinator:
    """Converge one frozen release: authority, CAL, completions, projection."""

    def __init__(
        self,
        *,
        repository: RideEconomicRepository,
        executor: ThresholdReleaseExecutor,
        training_projector: Any = None,
        lease_seconds: int = 300,
        retry_delay_seconds: int = 30,
        lease_owner_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self.repository = repository
        self.executor = executor
        self.training_projector = training_projector
        self.lease_seconds = max(1, int(lease_seconds))
        self.retry_delay_seconds = max(1, int(retry_delay_seconds))
        self._lease_owner_factory = lease_owner_factory

    async def run_once(self) -> ThresholdReleaseOutcome:
        lease_owner = self._lease_owner_factory()
        plan = await self.repository.claim_due_release_execution(
            lease_owner=lease_owner,
            lease_seconds=self.lease_seconds,
        )
        if plan is None:
            return ThresholdReleaseOutcome(
                status="idle",
                state="missing",
                durable_checkpoint=True,
            )
        return await self._execute(plan=plan, lease_owner=lease_owner)

    async def _execute(
        self,
        *,
        plan: dict[str, Any],
        lease_owner: UUID,
    ) -> ThresholdReleaseOutcome:
        snapshot_id = UUID(str(plan["snapshot_id"]))
        state = str(plan["state"])
        ride_hash = bytes.fromhex(str(plan["ride_hash_hex"]))

        if state == "planned":
            try:
                execution = await self.executor.authorize_held_ride_release_receipt(
                    rider_wallet=str(plan["wallet"]),
                    ride_hash=ride_hash,
                    reward_ftp_authority_id=UUID(
                        str(plan["reward_ftp_authority_id"])
                    ),
                    reward_ftp_authority_evidence_hash=bytes.fromhex(
                        str(plan["reward_ftp_authority_evidence_hash_hex"])
                    ),
                    reward_ftp_policy_version=str(
                        plan["reward_ftp_policy_version"]
                    ),
                    reward_ftp_w=int(plan["reward_ftp_w"]),
                    admitted_at=datetime.fromisoformat(str(plan["admitted_at"])),
                    established_at=datetime.fromisoformat(
                        str(plan["established_at"])
                    ),
                    total_tss=int(plan["total_tss"]),
                    exact_cal_base_units=int(plan["exact_cal_base_units"]),
                    exact_tribute_budget_base_units=int(
                        plan["exact_tribute_budget_base_units"]
                    ),
                    release_plan_evidence_hash=bytes.fromhex(
                        str(plan["release_plan_evidence_hash_hex"])
                    ),
                    expected_pda=str(plan["expected_release_authority_pda"]),
                )
                if not execution.confirmed_at:
                    raise RuntimeError(
                        "release authority validation lacks an authoritative chain clock"
                    )
                plan = await self.repository.advance_release_execution(
                    snapshot_id=snapshot_id,
                    lease_owner=lease_owner,
                    expected_state="planned",
                    next_state="release_authority_confirmed",
                    fields={
                        "release_authority_tx_signature": execution.tx_signature,
                        "release_authority_confirmed_at": execution.confirmed_at,
                    },
                )
                state = "release_authority_confirmed"
            except (PdaMismatchError, ChainAccountMismatchError, ValueError) as exc:
                return await self._review(
                    snapshot_id=snapshot_id,
                    lease_owner=lease_owner,
                    error=f"release_authority: {exc}",
                    conflict_evidence={
                        "version": 1,
                        "kind": "release_authority_mismatch",
                        "message": str(exc),
                        "observed_at": _now_iso(),
                    },
                )
            except SoftTimeLimitExceeded:
                raise
            except Exception as exc:
                return await self._retry(
                    snapshot_id=snapshot_id,
                    lease_owner=lease_owner,
                    state=state,
                    error=f"release_authority: {exc}",
                )

        if state == "release_authority_confirmed":
            try:
                execution = await self.executor.credit_released_cal_receipt(
                    rider_wallet=str(plan["wallet"]),
                    ride_hash=ride_hash,
                    amount=int(plan["exact_cal_base_units"]),
                    expected_release_authority_pda=str(
                        plan["expected_release_authority_pda"]
                    ),
                    expected_pda=str(plan["expected_cal_receipt_pda"]),
                )
                if not execution.confirmed_at:
                    raise RuntimeError(
                        "released CAL validation lacks an authoritative chain clock"
                    )
                plan = await self.repository.advance_release_execution(
                    snapshot_id=snapshot_id,
                    lease_owner=lease_owner,
                    expected_state="release_authority_confirmed",
                    next_state="cal_confirmed",
                    fields={
                        "cal_tx_signature": execution.tx_signature,
                        "cal_confirmed_at": execution.confirmed_at,
                    },
                )
                state = "cal_confirmed"
            except (PdaMismatchError, ChainAccountMismatchError, ValueError) as exc:
                return await self._review(
                    snapshot_id=snapshot_id,
                    lease_owner=lease_owner,
                    error=f"release_cal: {exc}",
                    conflict_evidence={
                        "version": 1,
                        "kind": "release_cal_mismatch",
                        "message": str(exc),
                        "observed_at": _now_iso(),
                    },
                )
            except SoftTimeLimitExceeded:
                raise
            except Exception as exc:
                return await self._retry(
                    snapshot_id=snapshot_id,
                    lease_owner=lease_owner,
                    state=state,
                    error=f"release_cal: {exc}",
                )

        if state == "cal_confirmed":
            for step in sorted(
                plan.get("steps") or [], key=lambda row: int(row["step_index"])
            ):
                if step.get("state") in {"confirmed", "projected"}:
                    continue
                step_index = int(step["step_index"])
                try:
                    execution = (
                        await self.executor.record_released_climb_completion_receipt(
                            rider_wallet=str(plan["wallet"]),
                            ride_hash=ride_hash,
                            vault_id=int(step["vault_id"]),
                            completion_time_s=int(step["completion_time_s"]),
                            cal_tribute=int(step["exact_tribute_base_units"]),
                            completion_evidence_version=int(
                                step["completion_evidence_version"]
                            ),
                            completion_evidence_hash=bytes.fromhex(
                                str(step["completion_evidence_hash_hex"])
                            ),
                            expected_release_authority_pda=str(
                                plan["expected_release_authority_pda"]
                            ),
                            expected_pda=str(step["expected_receipt_pda"]),
                        )
                    )
                    if not execution.confirmed_at:
                        raise RuntimeError(
                            "released completion validation lacks an authoritative chain clock"
                        )
                    confirmed = await self.repository.confirm_release_step(
                        snapshot_id=snapshot_id,
                        lease_owner=lease_owner,
                        step_index=step_index,
                        expected_receipt_pda=str(step["expected_receipt_pda"]),
                        tx_signature=execution.tx_signature,
                        confirmed_at=execution.confirmed_at,
                    )
                    step.update(confirmed)
                except (PdaMismatchError, ChainAccountMismatchError, ValueError) as exc:
                    return await self._review(
                        snapshot_id=snapshot_id,
                        lease_owner=lease_owner,
                        error=f"release_completion[{step_index}]: {exc}",
                        conflict_evidence={
                            "version": 1,
                            "kind": "release_completion_mismatch",
                            "step_index": step_index,
                            "message": str(exc),
                            "observed_at": _now_iso(),
                        },
                    )
                except SoftTimeLimitExceeded:
                    raise
                except Exception as exc:
                    return await self._retry(
                        snapshot_id=snapshot_id,
                        lease_owner=lease_owner,
                        state=state,
                        error=f"release_completion[{step_index}]: {exc}",
                        step_index=step_index,
                    )
            try:
                plan = await self.repository.advance_release_execution(
                    snapshot_id=snapshot_id,
                    lease_owner=lease_owner,
                    expected_state="cal_confirmed",
                    next_state="completions_confirmed",
                )
                state = "completions_confirmed"
            except SoftTimeLimitExceeded:
                raise
            except Exception as exc:
                return await self._retry(
                    snapshot_id=snapshot_id,
                    lease_owner=lease_owner,
                    state=state,
                    error=f"release_completion_checkpoint: {exc}",
                )

        if state == "completions_confirmed":
            for step in sorted(
                plan.get("steps") or [], key=lambda row: int(row["step_index"])
            ):
                if step.get("state") == "projected":
                    continue
                step_index = int(step["step_index"])
                try:
                    await self.repository.reconcile_release_completion(
                        snapshot_id=snapshot_id,
                        lease_owner=lease_owner,
                        step_index=step_index,
                    )
                    projected = await self.repository.mark_release_step_projected(
                        snapshot_id=snapshot_id,
                        lease_owner=lease_owner,
                        step_index=step_index,
                    )
                    step.update(projected)
                except ThresholdReleaseAuthorityConflictError as exc:
                    return await self._indexed_conflict_review(
                        snapshot_id=snapshot_id,
                        lease_owner=lease_owner,
                        phase="reconcile",
                        error=exc,
                        step_index=step_index,
                    )
                except SoftTimeLimitExceeded:
                    raise
                except Exception as exc:
                    return await self._retry(
                        snapshot_id=snapshot_id,
                        lease_owner=lease_owner,
                        state=state,
                        error=f"release_projection[{step_index}]: {exc}",
                        step_index=step_index,
                    )
            try:
                plan = await self.repository.advance_release_execution(
                    snapshot_id=snapshot_id,
                    lease_owner=lease_owner,
                    expected_state="completions_confirmed",
                    next_state="projections_reconciled",
                )
                state = "projections_reconciled"
            except SoftTimeLimitExceeded:
                raise
            except Exception as exc:
                return await self._retry(
                    snapshot_id=snapshot_id,
                    lease_owner=lease_owner,
                    state=state,
                    error=f"release_projection_checkpoint: {exc}",
                )

        if state == "projections_reconciled":
            try:
                plan = await self.repository.advance_release_execution(
                    snapshot_id=snapshot_id,
                    lease_owner=lease_owner,
                    expected_state="projections_reconciled",
                    next_state="complete",
                )
                state = "complete"
            except ThresholdReleaseAuthorityConflictError as exc:
                return await self._indexed_conflict_review(
                    snapshot_id=snapshot_id,
                    lease_owner=lease_owner,
                    phase="complete",
                    error=exc,
                )
            except SoftTimeLimitExceeded:
                raise
            except Exception as exc:
                return await self._retry(
                    snapshot_id=snapshot_id,
                    lease_owner=lease_owner,
                    state=state,
                    error=f"release_complete: {exc}",
                )

        project_terminal = getattr(
            self.repository, "project_threshold_release_terminal", None
        )
        terminal_projection = None
        if state == "complete" and callable(project_terminal):
            try:
                terminal_projection = await project_terminal(snapshot_id=snapshot_id)
            except ThresholdReleaseAuthorityConflictError as exc:
                return await self._indexed_conflict_review(
                    snapshot_id=snapshot_id,
                    lease_owner=lease_owner,
                    phase="terminal",
                    error=exc,
                )
            except SoftTimeLimitExceeded:
                raise
            except Exception as exc:
                return await self._retry(
                    snapshot_id=snapshot_id,
                    lease_owner=lease_owner,
                    state=state,
                    error=f"release_terminal_projection: {exc}",
                )

        if (
            state == "complete"
            and terminal_projection is not None
            and self.training_projector is not None
        ):
            try:
                await self.training_projector.project(terminal_projection)
                mark_projected = getattr(
                    self.repository, "mark_threshold_training_projected", None
                )
                if not callable(mark_projected) or not await mark_projected(
                    snapshot_id=snapshot_id
                ):
                    raise RuntimeError(
                        "Threshold release training projection was not durably marked"
                    )
            except SoftTimeLimitExceeded:
                raise
            except Exception as exc:
                durable = False
                checkpoint = getattr(
                    self.repository, "checkpoint_threshold_training_retry", None
                )
                if callable(checkpoint):
                    try:
                        durable = bool(
                            await checkpoint(
                                snapshot_id=snapshot_id,
                                error=str(exc),
                                retry_delay_seconds=self.retry_delay_seconds,
                            )
                        )
                    except SoftTimeLimitExceeded:
                        raise
                    except Exception:
                        logger.exception(
                            "Threshold training retry checkpoint failed for %s",
                            snapshot_id,
                        )
                return ThresholdReleaseOutcome(
                    status="recovery_pending",
                    state=state,
                    durable_checkpoint=durable,
                    snapshot_id=str(snapshot_id),
                    error=f"release_training_projection: {exc}",
                )

        return ThresholdReleaseOutcome(
            status="complete" if state == "complete" else "recovery_pending",
            state=state,
            durable_checkpoint=True,
            snapshot_id=str(snapshot_id),
        )

    async def _indexed_conflict_review(
        self,
        *,
        snapshot_id: UUID,
        lease_owner: UUID,
        phase: str,
        error: ThresholdReleaseAuthorityConflictError,
        step_index: Optional[int] = None,
    ) -> ThresholdReleaseOutcome:
        evidence: dict[str, Any] = {
            "version": 1,
            "kind": "indexed_threshold_release_authority_conflict",
            "phase": phase,
            "sqlstate": error.code,
            "operation": error.operation,
            "message": str(error),
            "observed_at": _now_iso(),
        }
        if step_index is not None:
            evidence["step_index"] = step_index
        return await self._review(
            snapshot_id=snapshot_id,
            lease_owner=lease_owner,
            error=f"{phase}: {error}",
            conflict_evidence=evidence,
        )

    async def _retry(
        self,
        *,
        snapshot_id: UUID,
        lease_owner: UUID,
        state: str,
        error: str,
        step_index: Optional[int] = None,
    ) -> ThresholdReleaseOutcome:
        durable = False
        checkpoint_error = error
        try:
            durable = await self.repository.checkpoint_release_retry(
                snapshot_id=snapshot_id,
                lease_owner=lease_owner,
                error=error,
                step_index=step_index,
                retry_delay_seconds=self.retry_delay_seconds,
            )
        except SoftTimeLimitExceeded:
            raise
        except Exception as exc:
            checkpoint_error = f"{error}; checkpoint persistence failed: {exc}"
            logger.exception(
                "Threshold release retry checkpoint failed for %s", snapshot_id
            )
        return ThresholdReleaseOutcome(
            status="recovery_pending",
            state=state,
            durable_checkpoint=durable,
            snapshot_id=str(snapshot_id),
            error=checkpoint_error,
        )

    async def _review(
        self,
        *,
        snapshot_id: UUID,
        lease_owner: UUID,
        error: str,
        conflict_evidence: dict[str, Any],
    ) -> ThresholdReleaseOutcome:
        durable = False
        review_error = error
        try:
            await self.repository.mark_threshold_release_review(
                snapshot_id=snapshot_id,
                lease_owner=lease_owner,
                reason=error,
                conflict_evidence=conflict_evidence,
            )
            durable = True
        except SoftTimeLimitExceeded:
            raise
        except Exception as exc:
            review_error = f"{error}; review persistence failed: {exc}"
            logger.exception(
                "Threshold release review checkpoint failed for %s", snapshot_id
            )
        return ThresholdReleaseOutcome(
            status="under_review",
            state="review" if durable else "planned",
            durable_checkpoint=durable,
            snapshot_id=str(snapshot_id),
            error=review_error,
        )
