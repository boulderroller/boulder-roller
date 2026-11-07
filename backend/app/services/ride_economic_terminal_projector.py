"""Idempotent rider-surface projection from a complete frozen economic plan."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID

from ..repositories.notification import NotificationRepository
from ..repositories.ride import RideRepository
from ..repositories.ride_economic import RideEconomicRepository
from .protocol_ints import U64_MAX, exact_uint
from .ride_effort_policy import CAL_DECIMALS_MULTIPLIER

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RideEconomicTerminalProjectionOutcome:
    status: str
    durable_checkpoint: bool
    cal_earned: int = 0
    error: Optional[str] = None


class RideEconomicTerminalProjector:
    """Project only immutable complete-plan facts into mutable product rows."""

    def __init__(
        self,
        *,
        economic_repository: RideEconomicRepository,
        ride_repository: RideRepository,
        notification_repository: NotificationRepository,
        retry_delay_seconds: int = 30,
    ) -> None:
        self.economic_repository = economic_repository
        self.ride_repository = ride_repository
        self.notification_repository = notification_repository
        self.retry_delay_seconds = retry_delay_seconds

    async def project(self, ride_id: UUID) -> RideEconomicTerminalProjectionOutcome:
        plan: dict[str, Any] | None = None
        try:
            plan = await self.economic_repository.get_plan(ride_id)
            if not plan or plan.get("state") != "complete":
                raise RuntimeError("terminal projection requires a complete frozen plan")
            cal_earned = self._display_cal(plan)
            if plan.get("terminal_projected_at"):
                return RideEconomicTerminalProjectionOutcome(
                    status="already_projected",
                    durable_checkpoint=True,
                    cal_earned=cal_earned,
                )

            ride = await self.ride_repository.get_ride(str(ride_id))
            if ride is None:
                await self._mark_projected(ride_id)
                return RideEconomicTerminalProjectionOutcome(
                    status="source_deleted",
                    durable_checkpoint=True,
                    cal_earned=cal_earned,
                )

            await self._project_ride(plan=plan, ride_id=ride_id, cal_earned=cal_earned)
            await self._emit_notifications(plan=plan, ride_id=ride_id, cal_earned=cal_earned)
            await self._mark_projected(ride_id)
            return RideEconomicTerminalProjectionOutcome(
                status="projected",
                durable_checkpoint=True,
                cal_earned=cal_earned,
            )
        except Exception as exc:
            durable = False
            error = f"terminal projection: {exc}"
            try:
                durable = await self.economic_repository.checkpoint_terminal_projection(
                    ride_id=ride_id,
                    error=error,
                    retry_delay_seconds=self.retry_delay_seconds,
                )
            except Exception as checkpoint_exc:
                error = f"{error}; checkpoint persistence failed: {checkpoint_exc}"
                logger.exception("Terminal projection checkpoint failed for %s", ride_id)
            return RideEconomicTerminalProjectionOutcome(
                status="recovery_pending",
                durable_checkpoint=durable,
                cal_earned=self._display_cal(plan) if plan else 0,
                error=error,
            )

    @staticmethod
    def _display_cal(plan: Optional[dict[str, Any]]) -> int:
        units = exact_uint(
            (plan or {}).get("exact_cal_base_units", 0),
            field="exact_cal_base_units",
            maximum=U64_MAX,
        )
        return units // CAL_DECIMALS_MULTIPLIER

    async def _mark_projected(self, ride_id: UUID) -> None:
        if not await self.economic_repository.mark_terminal_projected(ride_id=ride_id):
            raise RuntimeError("terminal projection checkpoint CAS failed")

    async def _project_ride(
        self,
        *,
        plan: dict[str, Any],
        ride_id: UUID,
        cal_earned: int,
    ) -> None:
        tx_signature = plan.get("cal_actual_tx_signature") or plan.get(
            "attestation_actual_tx_signature"
        )
        await self.ride_repository.update_phase_status(
            ride_id=ride_id,
            phase=3,
            success=True,
            error_message=None,
            processing_status="completed",
            review_reason=None,
            cal_earned=cal_earned,
            dung_minted=0,
            tx_signature=tx_signature,
            ride_attestation_pda=plan.get("expected_attestation_pda"),
            ride_attestation_tx_signature=plan.get(
                "attestation_actual_tx_signature"
            ),
            ride_attested_at=plan.get("attestation_confirmed_at"),
        )

    async def _emit_notifications(
        self,
        *,
        plan: dict[str, Any],
        ride_id: UUID,
        cal_earned: int,
    ) -> None:
        user_id = str(plan["user_id"])
        wallet = str(plan["wallet"])
        for step in plan.get("steps") or []:
            vault_signature = step.get("vault_signature")
            if not vault_signature:
                continue
            evidence_version = int(step.get("completion_evidence_version") or 1)
            tribute_bound = evidence_version == 2
            await self._notify(
                user_id=user_id,
                wallet=wallet,
                notification_type="record_rank_moved",
                title="Record Board updated",
                message="Your climb completion was recorded.",
                target_type="record_board",
                target_id=str(step.get("vault_id") or vault_signature),
                metadata={
                    "ride_id": str(ride_id),
                    "vault_id": step.get("vault_id"),
                    "vault_signature": vault_signature,
                    "cal_tribute": (
                        int(step["exact_tribute_base_units"])
                        if tribute_bound
                        else None
                    ),
                    "completion_evidence_version": evidence_version,
                    "tribute_bound": tribute_bound,
                    "time_in_vault_s": int(step["completion_time_s"]),
                },
                dedupe_key=f"record_rank_moved:{ride_id}:{vault_signature}",
            )
        tx_signature = plan.get("cal_actual_tx_signature") or plan.get(
            "attestation_actual_tx_signature"
        )
        await self._notify(
            user_id=user_id,
            wallet=wallet,
            notification_type="ride_finalized",
            title="Ride finalized",
            message="Your ride is finalized and ready to review.",
            target_type="ride",
            target_id=str(ride_id),
            metadata={
                "ride_id": str(ride_id),
                "cal_earned": cal_earned,
                "dung_minted": 0,
                "tx_signature": tx_signature,
            },
            dedupe_key=f"ride_finalized:{ride_id}",
        )

    async def _notify(self, **payload: Any) -> None:
        try:
            await self.notification_repository.create_event_notification(**payload)
        except Exception as exc:
            message = str(exc).lower()
            if "duplicate key" in message or "23505" in message:
                return
            raise
