from __future__ import annotations

from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.services.ride_economic_recovery import RideEconomicRecoveryLoop
from app.services.ride_economic_terminal_projector import (
    RideEconomicTerminalProjector,
)


def _complete_plan() -> dict:
    ride_id = uuid4()
    return {
        "ride_id": str(ride_id),
        "user_id": str(uuid4()),
        "wallet": "11111111111111111111111111111111",
        "state": "complete",
        "exact_cal_base_units": 84_000_000_000,
        "attestation_actual_tx_signature": None,
        "attestation_confirmed_at": "2026-07-13T13:00:00+00:00",
        "cal_actual_tx_signature": "cal-signature",
        "terminal_projected_at": None,
        "steps": [
            {
                "step_index": 0,
                "vault_id": 9,
                "vault_signature": "vault-signature",
                "completion_time_s": 321,
                "exact_tribute_base_units": 11_000_000_000,
                "state": "projected",
            }
        ],
    }


class TerminalRepository:
    def __init__(self, plan: dict) -> None:
        self.plan = deepcopy(plan)
        self.mark_calls = 0
        self.retry_calls = 0

    async def get_plan(self, ride_id: UUID) -> dict:
        assert str(ride_id) == self.plan["ride_id"]
        return deepcopy(self.plan)

    async def mark_terminal_projected(self, *, ride_id: UUID) -> bool:
        self.mark_calls += 1
        self.plan["terminal_projected_at"] = "2026-07-13T13:01:00+00:00"
        return True

    async def checkpoint_terminal_projection(self, **kwargs) -> bool:
        self.retry_calls += 1
        return True

    async def list_recoverable_plans(self, *, limit: int) -> list[dict]:
        if self.plan.get("terminal_projected_at"):
            return []
        return [{"ride_id": self.plan["ride_id"], "state": "complete"}]


@pytest.mark.asyncio
async def test_complete_plan_projects_frozen_identity_and_notifications_once() -> None:
    plan = _complete_plan()
    economics = TerminalRepository(plan)
    ride_repo = MagicMock()
    ride_repo.get_ride = AsyncMock(return_value={"id": plan["ride_id"]})
    ride_repo.update_phase_status = AsyncMock()
    notifications = MagicMock()
    notifications.create_event_notification = AsyncMock(return_value="notification-id")
    projector = RideEconomicTerminalProjector(
        economic_repository=economics,
        ride_repository=ride_repo,
        notification_repository=notifications,
    )

    first = await projector.project(UUID(plan["ride_id"]))
    second = await projector.project(UUID(plan["ride_id"]))

    assert first.status == "projected"
    assert second.status == "already_projected"
    ride_repo.update_phase_status.assert_awaited_once()
    fields = ride_repo.update_phase_status.await_args.kwargs
    assert fields["processing_status"] == "completed"
    assert fields["cal_earned"] == 84
    assert fields["ride_attestation_pda"] is None
    assert fields["ride_attestation_tx_signature"] is None
    assert fields["tx_signature"] == "cal-signature"
    assert fields["error_message"] is None
    assert notifications.create_event_notification.await_count == 2
    assert economics.mark_calls == 1


@pytest.mark.asyncio
async def test_crash_after_chain_complete_recovery_projects_terminal_ride_once() -> None:
    plan = _complete_plan()
    economics = TerminalRepository(plan)
    ride_repo = MagicMock()
    ride_repo.get_ride = AsyncMock(return_value={"id": plan["ride_id"]})
    ride_repo.update_phase_status = AsyncMock()
    notifications = MagicMock()
    notifications.create_event_notification = AsyncMock(return_value="notification-id")
    projector = RideEconomicTerminalProjector(
        economic_repository=economics,
        ride_repository=ride_repo,
        notification_repository=notifications,
    )
    coordinator = MagicMock()
    coordinator.execute = AsyncMock(
        return_value=MagicMock(status="complete", durable_checkpoint=True)
    )
    recovery = RideEconomicRecoveryLoop(
        repository=economics,
        coordinator_factory=lambda: coordinator,
        terminal_projector_factory=lambda: projector,
    )

    assert await recovery.run_once() == 1
    assert await recovery.run_once() == 0

    coordinator.execute.assert_awaited_once_with(UUID(plan["ride_id"]))
    ride_repo.update_phase_status.assert_awaited_once()
    assert economics.mark_calls == 1
    assert notifications.create_event_notification.await_count == 2


@pytest.mark.asyncio
async def test_deleted_product_ride_does_not_strand_complete_frozen_plan() -> None:
    plan = _complete_plan()
    economics = TerminalRepository(plan)
    ride_repo = MagicMock()
    ride_repo.get_ride = AsyncMock(return_value=None)
    ride_repo.update_phase_status = AsyncMock()
    notifications = MagicMock()
    notifications.create_event_notification = AsyncMock()
    projector = RideEconomicTerminalProjector(
        economic_repository=economics,
        ride_repository=ride_repo,
        notification_repository=notifications,
    )

    outcome = await projector.project(UUID(plan["ride_id"]))

    assert outcome.status == "source_deleted"
    assert economics.mark_calls == 1
    ride_repo.update_phase_status.assert_not_awaited()
    notifications.create_event_notification.assert_not_awaited()
