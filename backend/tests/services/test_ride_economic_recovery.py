from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.ride_economic_recovery import RideEconomicRecoveryLoop


@pytest.mark.asyncio
async def test_recovery_loop_resumes_each_due_plan_directly_from_frozen_plan() -> None:
    plans = [
        {"ride_id": str(uuid4()), "user_id": str(uuid4())},
        {"ride_id": str(uuid4()), "user_id": str(uuid4())},
    ]
    repository = MagicMock()
    repository.list_recoverable_plans = AsyncMock(return_value=plans)
    coordinator = MagicMock()
    coordinator.execute = AsyncMock(return_value=MagicMock(status="complete"))
    recovery = RideEconomicRecoveryLoop(
        repository=repository,
        coordinator_factory=lambda: coordinator,
        batch_size=10,
    )

    resumed = await recovery.run_once()

    assert resumed == 2
    repository.list_recoverable_plans.assert_awaited_once_with(limit=10)
    assert coordinator.execute.await_count == 2
    for plan, call in zip(plans, coordinator.execute.await_args_list):
        assert str(call.args[0]) == plan["ride_id"]


@pytest.mark.asyncio
async def test_recovery_loop_continues_after_one_plan_fails() -> None:
    plans = [
        {"ride_id": str(uuid4()), "user_id": str(uuid4())},
        {"ride_id": str(uuid4()), "user_id": str(uuid4())},
    ]
    repository = MagicMock()
    repository.list_recoverable_plans = AsyncMock(return_value=plans)
    coordinator = MagicMock()
    coordinator.execute = AsyncMock(
        side_effect=[RuntimeError("temporary failure"), MagicMock(status="complete")]
    )
    recovery = RideEconomicRecoveryLoop(
        repository=repository,
        coordinator_factory=lambda: coordinator,
    )

    resumed = await recovery.run_once()

    assert resumed == 1
    assert coordinator.execute.await_count == 2


@pytest.mark.asyncio
async def test_recovery_ignores_mutated_ride_policy_and_owns_frozen_plan() -> None:
    ride_id = uuid4()
    repository = MagicMock()
    repository.list_recoverable_plans = AsyncMock(
        return_value=[
            {
                "ride_id": str(ride_id),
                "user_id": str(uuid4()),
                "exact_cal_base_units": 84_000_000_000,
                "reward_policy": "rewardable",
            }
        ]
    )
    coordinator = MagicMock()
    coordinator.execute = AsyncMock(return_value=MagicMock(status="complete"))
    mutable_phase3_processor = MagicMock()
    mutable_phase3_processor.process_phase3_rewards = AsyncMock(
        side_effect=AssertionError("recovery must not recompute ride policy")
    )
    recovery = RideEconomicRecoveryLoop(
        repository=repository,
        coordinator_factory=lambda: coordinator,
    )

    resumed = await recovery.run_once()

    assert resumed == 1
    coordinator.execute.assert_awaited_once_with(ride_id)
    mutable_phase3_processor.process_phase3_rewards.assert_not_awaited()
