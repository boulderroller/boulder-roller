"""Durable ride-economic plan, lease, and confirmed-receipt persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Protocol
from uuid import UUID

from .base import BaseRepository


class ConfirmedCompletionCandidateProvider(Protocol):
    """Read boundary consumed by Local Legend and settlement orchestration."""

    async def list_confirmed_local_legend_candidates(
        self,
        *,
        vault_id: int,
        completed_from: datetime,
        completed_before: datetime,
    ) -> List[Dict[str, Any]]:
        """Return complete wallet aggregates for one exact legend term."""

    async def list_confirmed_completion_candidates(
        self,
        *,
        vault_id: Optional[int] = None,
        completed_from: Optional[datetime] = None,
        completed_before: Optional[datetime] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """Return only completions backed by a confirmed chain receipt."""


class ConfirmedCompletionCandidateUnavailable(RuntimeError):
    """The authoritative candidate source could not be read."""


class StaleEffortCoverageError(RuntimeError):
    """Coverage changed while this plan was being priced; re-read and recompute."""


class ThresholdReleaseAuthorityConflictError(RuntimeError):
    """Release authority requires review, including an implausible Threshold fit."""

    def __init__(self, *, code: str, operation: str, message: str) -> None:
        self.code = code
        self.operation = operation
        super().__init__(f"{operation}: {message}")


_THRESHOLD_RELEASE_CONFLICT_CODES = frozenset(
    {"BRR01", "BRR02", "BRR03", "BRR04", "BRR05", "BRR06", "BRR07"}
)


def is_authoritative_completion(row: Dict[str, Any]) -> bool:
    """Return whether a projection carries authoritative chain confirmation."""
    if row.get("chain_confirmation_status") != "confirmed":
        return False
    tx_signature = str(row.get("on_chain_tx") or "")
    if tx_signature.startswith("exists:"):
        return False
    return bool(
        row.get("completion_receipt_pda")
        and row.get("completion_evidence_hash")
        and row.get("chain_confirmed_at")
    )


def is_authoritative_tribute(row: Dict[str, Any]) -> bool:
    """Return whether the receipt binds the exact projected tribute amount."""
    return (
        is_authoritative_completion(row)
        and int(row.get("completion_evidence_version") or 0) in {2, 3}
        and row.get("cal_tribute") is not None
    )


def _rpc_payload(response: Any) -> Any:
    data = getattr(response, "data", None)
    if isinstance(data, list):
        return data[0] if data else None
    return data


class RideEconomicRepository(BaseRepository):
    """Persistence adapter for the ride-economic state machine."""

    async def _run(
        self,
        func: Callable[[], Any],
        operation: str = "supabase",
    ) -> Any:
        try:
            return await super()._run(func, operation=operation)
        except Exception as exc:
            code = str(getattr(exc, "code", "") or "")
            if code == "BRR08":
                raise StaleEffortCoverageError("stale_effort_coverage") from exc
            if code in _THRESHOLD_RELEASE_CONFLICT_CODES:
                raise ThresholdReleaseAuthorityConflictError(
                    code=code,
                    operation=operation,
                    message=str(exc),
                ) from exc
            raise

    async def register_threshold_provisional_hold(
        self,
        *,
        hold: Dict[str, Any],
    ) -> Dict[str, Any]:
        response = await self._run(
            lambda: self._client.rpc(
                "register_reward_threshold_provisional_hold",
                {"p_hold": hold},
            ).execute(),
            operation="register_reward_threshold_provisional_hold",
        )
        payload = _rpc_payload(response)
        if not isinstance(payload, dict):
            raise RuntimeError("Threshold provisional hold was not persisted")
        return payload

    async def record_threshold_provisional_hold_admission(
        self,
        *,
        ride_id: UUID,
        admitted_at: str,
        expected_attestation_pda: str,
    ) -> Dict[str, Any]:
        response = await self._run(
            lambda: self._client.rpc(
                "record_reward_threshold_provisional_hold_admission",
                {
                    "p_ride_id": str(ride_id),
                    "p_admitted_at": admitted_at,
                    "p_ride_attestation_pda": expected_attestation_pda,
                },
            ).execute(),
            operation="record_reward_threshold_provisional_hold_admission",
        )
        payload = _rpc_payload(response)
        if not isinstance(payload, dict):
            raise RuntimeError("Threshold hold admission was not persisted")
        return payload

    async def claim_due_threshold_release_item(
        self,
        *,
        lease_owner: UUID,
        lease_seconds: int,
    ) -> Optional[Dict[str, Any]]:
        response = await self._run(
            lambda: self._client.rpc(
                "claim_due_reward_threshold_release_item",
                {
                    "p_lease_owner": str(lease_owner),
                    "p_lease_seconds": int(lease_seconds),
                },
            ).execute(),
            operation="claim_due_reward_threshold_release_item",
        )
        payload = _rpc_payload(response)
        return payload if isinstance(payload, dict) else None

    async def freeze_threshold_release_snapshot(
        self,
        *,
        snapshot: Dict[str, Any],
        steps: List[Dict[str, Any]],
        lease_owner: UUID,
    ) -> Dict[str, Any]:
        response = await self._run(
            lambda: self._client.rpc(
                "freeze_reward_threshold_release_snapshot",
                {
                    "p_snapshot": snapshot,
                    "p_steps": steps,
                    "p_planner_lease_owner": str(lease_owner),
                },
            ).execute(),
            operation="freeze_reward_threshold_release_snapshot",
        )
        payload = _rpc_payload(response)
        if not isinstance(payload, dict):
            raise RuntimeError("Threshold release snapshot was not frozen")
        return payload

    async def mark_threshold_release_item_terminal(
        self,
        *,
        batch_item_id: UUID,
        lease_owner: UUID,
        disposition: str,
        reason: str,
        evidence: Dict[str, Any],
    ) -> Dict[str, Any]:
        response = await self._run(
            lambda: self._client.rpc(
                "mark_reward_threshold_release_item_terminal",
                {
                    "p_batch_item_id": str(batch_item_id),
                    "p_lease_owner": str(lease_owner),
                    "p_disposition": disposition,
                    "p_reason": reason[:2000],
                    "p_evidence": evidence,
                },
            ).execute(),
            operation="mark_reward_threshold_release_item_terminal",
        )
        payload = _rpc_payload(response)
        if not isinstance(payload, dict):
            raise RuntimeError("Threshold release item terminal CAS failed")
        return payload

    async def claim_due_release_execution(
        self,
        *,
        lease_owner: UUID,
        lease_seconds: int,
    ) -> Optional[Dict[str, Any]]:
        response = await self._run(
            lambda: self._client.rpc(
                "claim_due_reward_threshold_release_execution",
                {
                    "p_lease_owner": str(lease_owner),
                    "p_lease_seconds": int(lease_seconds),
                },
            ).execute(),
            operation="claim_due_reward_threshold_release_execution",
        )
        payload = _rpc_payload(response)
        return payload if isinstance(payload, dict) else None

    async def advance_release_execution(
        self,
        *,
        snapshot_id: UUID,
        lease_owner: UUID,
        expected_state: str,
        next_state: str,
        fields: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        response = await self._run(
            lambda: self._client.rpc(
                "advance_reward_threshold_release_execution",
                {
                    "p_snapshot_id": str(snapshot_id),
                    "p_lease_owner": str(lease_owner),
                    "p_expected_state": expected_state,
                    "p_next_state": next_state,
                    "p_fields": fields or {},
                },
            ).execute(),
            operation="advance_reward_threshold_release_execution",
        )
        payload = _rpc_payload(response)
        if not isinstance(payload, dict):
            raise RuntimeError(
                f"Threshold release CAS failed: {expected_state} -> {next_state}"
            )
        return payload

    async def confirm_release_step(
        self,
        *,
        snapshot_id: UUID,
        lease_owner: UUID,
        step_index: int,
        expected_receipt_pda: str,
        tx_signature: Optional[str],
        confirmed_at: str,
    ) -> Dict[str, Any]:
        response = await self._run(
            lambda: self._client.rpc(
                "confirm_reward_threshold_release_step",
                {
                    "p_snapshot_id": str(snapshot_id),
                    "p_lease_owner": str(lease_owner),
                    "p_step_index": int(step_index),
                    "p_expected_receipt_pda": expected_receipt_pda,
                    "p_tx_signature": tx_signature,
                    "p_confirmed_at": confirmed_at,
                },
            ).execute(),
            operation="confirm_reward_threshold_release_step",
        )
        payload = _rpc_payload(response)
        if not isinstance(payload, dict):
            raise RuntimeError(f"Threshold release step {step_index} was not confirmed")
        return payload

    async def reconcile_release_completion(
        self,
        *,
        snapshot_id: UUID,
        lease_owner: UUID,
        step_index: int,
    ) -> Dict[str, Any]:
        response = await self._run(
            lambda: self._client.rpc(
                "reconcile_confirmed_reward_threshold_release_completion",
                {
                    "p_snapshot_id": str(snapshot_id),
                    "p_lease_owner": str(lease_owner),
                    "p_step_index": int(step_index),
                },
            ).execute(),
            operation="reconcile_confirmed_reward_threshold_release_completion",
        )
        payload = _rpc_payload(response)
        if not isinstance(payload, dict):
            raise RuntimeError(f"Threshold release step {step_index} was not reconciled")
        return payload

    async def mark_release_step_projected(
        self,
        *,
        snapshot_id: UUID,
        lease_owner: UUID,
        step_index: int,
    ) -> Dict[str, Any]:
        response = await self._run(
            lambda: self._client.rpc(
                "mark_reward_threshold_release_step_projected",
                {
                    "p_snapshot_id": str(snapshot_id),
                    "p_lease_owner": str(lease_owner),
                    "p_step_index": int(step_index),
                },
            ).execute(),
            operation="mark_reward_threshold_release_step_projected",
        )
        payload = _rpc_payload(response)
        if not isinstance(payload, dict):
            raise RuntimeError(
                f"Threshold release step {step_index} projection was not checkpointed"
            )
        return payload

    async def checkpoint_release_retry(
        self,
        *,
        snapshot_id: UUID,
        lease_owner: UUID,
        error: str,
        step_index: Optional[int],
        retry_delay_seconds: int,
    ) -> bool:
        response = await self._run(
            lambda: self._client.rpc(
                "checkpoint_reward_threshold_release_retry",
                {
                    "p_snapshot_id": str(snapshot_id),
                    "p_lease_owner": str(lease_owner),
                    "p_error": error[:2000],
                    "p_step_index": step_index,
                    "p_retry_delay_seconds": int(retry_delay_seconds),
                },
            ).execute(),
            operation="checkpoint_reward_threshold_release_retry",
        )
        return bool(_rpc_payload(response))

    async def mark_threshold_release_review(
        self,
        *,
        snapshot_id: UUID,
        lease_owner: UUID,
        reason: str,
        conflict_evidence: Dict[str, Any],
    ) -> Dict[str, Any]:
        response = await self._run(
            lambda: self._client.rpc(
                "mark_reward_threshold_release_review",
                {
                    "p_snapshot_id": str(snapshot_id),
                    "p_lease_owner": str(lease_owner),
                    "p_reason": reason[:2000],
                    "p_conflict_evidence": conflict_evidence,
                },
            ).execute(),
            operation="mark_reward_threshold_release_review",
        )
        payload = _rpc_payload(response)
        if not isinstance(payload, dict):
            raise RuntimeError("Threshold release review CAS failed")
        return payload

    async def project_threshold_release_terminal(
        self,
        *,
        snapshot_id: UUID,
    ) -> Dict[str, Any]:
        response = await self._run(
            lambda: self._client.rpc(
                "project_reward_threshold_release_terminal",
                {"p_snapshot_id": str(snapshot_id)},
            ).execute(),
            operation="project_reward_threshold_release_terminal",
        )
        payload = _rpc_payload(response)
        if not isinstance(payload, dict):
            raise RuntimeError("Threshold release terminal projection failed")
        return payload

    async def checkpoint_threshold_training_retry(
        self,
        *,
        snapshot_id: UUID,
        error: str,
        retry_delay_seconds: int,
    ) -> bool:
        response = await self._run(
            lambda: self._client.rpc(
                "checkpoint_reward_threshold_training_retry",
                {
                    "p_snapshot_id": str(snapshot_id),
                    "p_error": error[:2000],
                    "p_retry_delay_seconds": int(retry_delay_seconds),
                },
            ).execute(),
            operation="checkpoint_reward_threshold_training_retry",
        )
        return bool(_rpc_payload(response))

    async def mark_threshold_training_projected(
        self,
        *,
        snapshot_id: UUID,
    ) -> bool:
        response = await self._run(
            lambda: self._client.rpc(
                "mark_reward_threshold_training_projected",
                {"p_snapshot_id": str(snapshot_id)},
            ).execute(),
            operation="mark_reward_threshold_training_projected",
        )
        return bool(_rpc_payload(response))

    async def get_effort_trim_basis(
        self,
        *,
        ride_id: UUID,
        user_id: UUID,
        completion_spans_ms: Optional[List[List[int]]] = None,
    ) -> Dict[str, Any]:
        response = await self._run(
            lambda: self._client.rpc(
                "get_ride_effort_trim_basis",
                {
                    "p_ride_id": str(ride_id),
                    "p_user_id": str(user_id),
                    "p_completion_spans_ms": completion_spans_ms or [],
                },
            ).execute(),
            operation="get_ride_effort_trim_basis",
        )
        payload = _rpc_payload(response)
        if not isinstance(payload, dict):
            raise RuntimeError("get_ride_effort_trim_basis returned no basis")
        return payload

    async def freeze_plan(
        self,
        *,
        plan: Dict[str, Any],
        steps: List[Dict[str, Any]],
        threshold_hold: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"p_plan": plan, "p_steps": steps}
        if threshold_hold is not None:
            params["p_threshold_hold"] = threshold_hold
        response = await self._run(
            lambda: self._client.rpc(
                "freeze_ride_economic_plan",
                params,
            ).execute(),
            operation="freeze_ride_economic_plan",
        )
        payload = _rpc_payload(response)
        if not isinstance(payload, dict):
            raise RuntimeError("freeze_ride_economic_plan returned no plan")
        return payload

    async def get_plan(self, ride_id: UUID) -> Optional[Dict[str, Any]]:
        response = await self._run(
            lambda: self._client.rpc(
                "get_ride_economic_plan",
                {"p_ride_id": str(ride_id)},
            ).execute(),
            operation="get_ride_economic_plan",
        )
        payload = _rpc_payload(response)
        return payload if isinstance(payload, dict) else None

    async def acquire_plan(
        self,
        *,
        ride_id: UUID,
        lease_owner: UUID,
        lease_seconds: int,
    ) -> Optional[Dict[str, Any]]:
        response = await self._run(
            lambda: self._client.rpc(
                "acquire_ride_economic_plan",
                {
                    "p_ride_id": str(ride_id),
                    "p_lease_owner": str(lease_owner),
                    "p_lease_seconds": int(lease_seconds),
                },
            ).execute(),
            operation="acquire_ride_economic_plan",
        )
        payload = _rpc_payload(response)
        return payload if isinstance(payload, dict) else None

    async def advance_plan(
        self,
        *,
        ride_id: UUID,
        lease_owner: UUID,
        expected_state: str,
        next_state: str,
        fields: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        response = await self._run(
            lambda: self._client.rpc(
                "advance_ride_economic_plan",
                {
                    "p_ride_id": str(ride_id),
                    "p_lease_owner": str(lease_owner),
                    "p_expected_state": expected_state,
                    "p_next_state": next_state,
                    "p_fields": fields or {},
                },
            ).execute(),
            operation="advance_ride_economic_plan",
        )
        payload = _rpc_payload(response)
        if not isinstance(payload, dict):
            raise RuntimeError(
                f"ride economic CAS failed: {expected_state} -> {next_state}"
            )
        return payload

    async def confirm_completion_step(
        self,
        *,
        ride_id: UUID,
        lease_owner: UUID,
        step_index: int,
        expected_receipt_pda: str,
        tx_signature: Optional[str],
        confirmed_at: str,
    ) -> Dict[str, Any]:
        response = await self._run(
            lambda: self._client.rpc(
                "confirm_ride_economic_completion",
                {
                    "p_ride_id": str(ride_id),
                    "p_lease_owner": str(lease_owner),
                    "p_step_index": int(step_index),
                    "p_expected_receipt_pda": expected_receipt_pda,
                    "p_tx_signature": tx_signature,
                    "p_confirmed_at": confirmed_at,
                },
            ).execute(),
            operation="confirm_ride_economic_completion",
        )
        payload = _rpc_payload(response)
        if not isinstance(payload, dict):
            raise RuntimeError(f"completion checkpoint failed for step {step_index}")
        return payload

    async def reconcile_completion_projection(
        self,
        *,
        ride_id: UUID,
        lease_owner: UUID,
        step_index: int,
    ) -> Dict[str, Any]:
        response = await self._run(
            lambda: self._client.rpc(
                "reconcile_confirmed_vault_completion",
                {
                    "p_ride_id": str(ride_id),
                    "p_lease_owner": str(lease_owner),
                    "p_step_index": int(step_index),
                },
            ).execute(),
            operation="reconcile_confirmed_vault_completion",
        )
        payload = _rpc_payload(response)
        if not isinstance(payload, dict):
            raise RuntimeError(f"completion projection failed for step {step_index}")
        return payload

    async def mark_completion_projected(
        self,
        *,
        ride_id: UUID,
        lease_owner: UUID,
        step_index: int,
    ) -> Dict[str, Any]:
        response = await self._run(
            lambda: self._client.rpc(
                "mark_ride_economic_completion_projected",
                {
                    "p_ride_id": str(ride_id),
                    "p_lease_owner": str(lease_owner),
                    "p_step_index": int(step_index),
                },
            ).execute(),
            operation="mark_ride_economic_completion_projected",
        )
        payload = _rpc_payload(response)
        if not isinstance(payload, dict):
            raise RuntimeError(f"completion projection CAS failed for step {step_index}")
        return payload

    async def checkpoint_retry(
        self,
        *,
        ride_id: UUID,
        lease_owner: UUID,
        error: str,
        step_index: Optional[int],
        retry_delay_seconds: int,
    ) -> bool:
        response = await self._run(
            lambda: self._client.rpc(
                "checkpoint_ride_economic_retry",
                {
                    "p_ride_id": str(ride_id),
                    "p_lease_owner": str(lease_owner),
                    "p_error": error[:2000],
                    "p_step_index": step_index,
                    "p_retry_delay_seconds": int(retry_delay_seconds),
                },
            ).execute(),
            operation="checkpoint_ride_economic_retry",
        )
        return bool(_rpc_payload(response))

    async def mark_review(
        self,
        *,
        ride_id: UUID,
        lease_owner: UUID,
        reason: str,
        actor: str,
        conflict_evidence: Dict[str, Any],
    ) -> Dict[str, Any]:
        response = await self._run(
            lambda: self._client.rpc(
                "mark_ride_economic_review",
                {
                    "p_ride_id": str(ride_id),
                    "p_lease_owner": str(lease_owner),
                    "p_reason": reason[:2000],
                    "p_actor": actor[:200],
                    "p_conflict_evidence": conflict_evidence,
                },
            ).execute(),
            operation="mark_ride_economic_review",
        )
        payload = _rpc_payload(response)
        if not isinstance(payload, dict):
            raise RuntimeError("ride economic review checkpoint CAS failed")
        return payload

    async def get_review(self, ride_id: UUID) -> Optional[Dict[str, Any]]:
        response = await self._run(
            lambda: self._client.rpc(
                "get_ride_economic_review",
                {"p_ride_id": str(ride_id)},
            ).execute(),
            operation="get_ride_economic_review",
        )
        payload = _rpc_payload(response)
        return payload if isinstance(payload, dict) else None

    async def resolve_review(
        self,
        *,
        ride_id: UUID,
        expected_review_version: int,
        request_id: UUID,
        actor_id: UUID,
        outcome: str,
        selected_checkpoint: Optional[str],
        reason: str,
        chain_evidence: Dict[str, Any],
        liability_disposition: Optional[str],
        effects_disposition: Optional[str],
    ) -> Dict[str, Any]:
        """Persist an application-verified snapshot and one fenced decision.

        This low-level adapter is intentionally called by
        RideEconomicReviewResolutionService, never from raw admin request data.
        """
        response = await self._run(
            lambda: self._client.rpc(
                "resolve_ride_economic_review",
                {
                    "p_ride_id": str(ride_id),
                    "p_expected_review_version": int(expected_review_version),
                    "p_request_id": str(request_id),
                    "p_actor_id": str(actor_id),
                    "p_outcome": outcome,
                    "p_selected_checkpoint": selected_checkpoint,
                    "p_reason": reason[:2000],
                    "p_chain_evidence": chain_evidence,
                    "p_liability_disposition": liability_disposition,
                    "p_effects_disposition": effects_disposition,
                },
            ).execute(),
            operation="resolve_ride_economic_review",
        )
        payload = _rpc_payload(response)
        if not isinstance(payload, dict):
            raise RuntimeError("ride economic review resolution CAS failed")
        return payload

    async def mark_terminal_projected(self, *, ride_id: UUID) -> bool:
        response = await self._run(
            lambda: self._client.rpc(
                "mark_ride_economic_terminal_projected",
                {"p_ride_id": str(ride_id)},
            ).execute(),
            operation="mark_ride_economic_terminal_projected",
        )
        return bool(_rpc_payload(response))

    async def checkpoint_terminal_projection(
        self,
        *,
        ride_id: UUID,
        error: str,
        retry_delay_seconds: int,
    ) -> bool:
        response = await self._run(
            lambda: self._client.rpc(
                "checkpoint_ride_economic_terminal_projection",
                {
                    "p_ride_id": str(ride_id),
                    "p_error": error[:2000],
                    "p_retry_delay_seconds": int(retry_delay_seconds),
                },
            ).execute(),
            operation="checkpoint_ride_economic_terminal_projection",
        )
        return bool(_rpc_payload(response))

    async def list_recoverable_plans(self, *, limit: int = 25) -> List[Dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 100))
        response = await self._run(
            lambda: self._client.table("ride_economic_plans")
            .select(
                "ride_id,user_id,state,next_attempt_at,attempts,"
                "terminal_projection_attempts,terminal_projected_at"
            )
            .not_.in_("state", ["complete", "review", "rejected"])
            .lte("next_attempt_at", datetime.now(timezone.utc).isoformat())
            .order("next_attempt_at")
            .limit(bounded_limit)
            .execute(),
            operation="list_recoverable_ride_economic_plans",
        )
        rows = list(getattr(response, "data", None) or [])
        remaining = bounded_limit - len(rows)
        if remaining <= 0:
            return rows
        terminal_response = await self._run(
            lambda: self._client.table("ride_economic_plans")
            .select(
                "ride_id,user_id,state,next_attempt_at,attempts,"
                "terminal_projection_attempts,terminal_projected_at"
            )
            .eq("state", "complete")
            .is_("terminal_projected_at", "null")
            .lte("next_attempt_at", datetime.now(timezone.utc).isoformat())
            .order("next_attempt_at")
            .limit(remaining)
            .execute(),
            operation="list_unprojected_complete_ride_economic_plans",
        )
        rows.extend(list(getattr(terminal_response, "data", None) or []))
        return rows

    async def list_confirmed_completion_candidates(
        self,
        *,
        vault_id: Optional[int] = None,
        completed_from: Optional[datetime] = None,
        completed_before: Optional[datetime] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        def execute() -> Any:
            query = self._client.table("confirmed_vault_completion_candidates").select(
                "*"
            )
            if vault_id is not None:
                query = query.eq("vault_id", int(vault_id))
            if completed_from is not None:
                query = query.gte("completed_at", completed_from.isoformat())
            if completed_before is not None:
                query = query.lt("completed_at", completed_before.isoformat())
            return query.order("completed_at").limit(max(1, min(limit, 5000))).execute()

        response = await self._run(
            execute,
            operation="list_confirmed_completion_candidates",
        )
        return [
            dict(row)
            for row in (getattr(response, "data", None) or [])
            if is_authoritative_completion(dict(row))
        ]

    async def list_confirmed_local_legend_candidates(
        self,
        *,
        vault_id: int,
        completed_from: datetime,
        completed_before: datetime,
    ) -> List[Dict[str, Any]]:
        """Read one untruncated server-side aggregate for a legend term."""
        response = await self._run(
            lambda: self._client.rpc(
                "get_confirmed_local_legend_candidates",
                {
                    "p_vault_id": int(vault_id),
                    "p_completed_from": completed_from.isoformat(),
                    "p_completed_before": completed_before.isoformat(),
                },
            ).execute(),
            operation="get_confirmed_local_legend_candidates",
        )
        payload = getattr(response, "data", None)
        if (
            isinstance(payload, list)
            and len(payload) == 1
            and isinstance(payload[0], dict)
            and "authoritative" in payload[0]
        ):
            payload = payload[0]
        if not isinstance(payload, dict) or payload.get("authoritative") is not True:
            raise RuntimeError("Local Legend candidate aggregate is not authoritative")

        candidates = payload.get("candidates")
        receipt_count = payload.get("confirmed_receipt_count")
        wallet_count = payload.get("wallet_count")
        if not isinstance(candidates, list):
            raise RuntimeError("Local Legend candidate aggregate is malformed")
        if (
            isinstance(receipt_count, bool)
            or not isinstance(receipt_count, int)
            or receipt_count < 0
            or isinstance(wallet_count, bool)
            or not isinstance(wallet_count, int)
            or wallet_count < 0
        ):
            raise RuntimeError("Local Legend candidate aggregate counts are malformed")

        rows: List[Dict[str, Any]] = []
        seen_wallets = set()
        counted_receipts = 0
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise RuntimeError("Local Legend candidate row is malformed")
            wallet = candidate.get("wallet")
            completion_count = candidate.get("completion_count")
            if (
                not isinstance(wallet, str)
                or not wallet
                or wallet in seen_wallets
                or isinstance(completion_count, bool)
                or not isinstance(completion_count, int)
                or completion_count <= 0
                or candidate.get("first_completed_at") is None
            ):
                raise RuntimeError("Local Legend candidate row is malformed")
            seen_wallets.add(wallet)
            counted_receipts += completion_count
            rows.append(dict(candidate))

        if wallet_count != len(rows) or receipt_count != counted_receipts:
            raise RuntimeError("Local Legend candidate aggregate is incomplete")
        return rows
