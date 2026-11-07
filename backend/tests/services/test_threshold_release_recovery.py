from __future__ import annotations

from types import SimpleNamespace

import pytest
from celery.exceptions import SoftTimeLimitExceeded

from app.services.threshold_release_recovery import ThresholdReleaseRecoveryLoop


class SequenceRunner:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    async def run_once(self):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.mark.asyncio
async def test_recovery_plans_then_executes_until_each_queue_is_idle() -> None:
    planner = SequenceRunner(
        [
            SimpleNamespace(status="planned"),
            SimpleNamespace(status="review"),
            SimpleNamespace(status="idle"),
        ]
    )
    coordinator = SequenceRunner(
        [
            SimpleNamespace(status="complete"),
            SimpleNamespace(status="recovery_pending"),
            SimpleNamespace(status="under_review"),
            SimpleNamespace(status="idle"),
        ]
    )
    recovery = ThresholdReleaseRecoveryLoop(
        planner=planner,
        coordinator=coordinator,
        batch_size=10,
    )

    outcome = await recovery.run_once()

    assert outcome == {
        "planned": 1,
        "planner_reviews": 1,
        "planner_errors": 0,
        "completed": 1,
        "recovery_pending": 1,
        "execution_reviews": 1,
        "execution_errors": 0,
    }
    assert planner.calls == 3
    assert coordinator.calls == 4


@pytest.mark.asyncio
async def test_recovery_isolates_one_item_failure_and_keeps_both_lanes_moving() -> None:
    planner = SequenceRunner(
        [RuntimeError("claim CAS lost"), SimpleNamespace(status="planned"), SimpleNamespace(status="idle")]
    )
    coordinator = SequenceRunner(
        [RuntimeError("receipt read unavailable"), SimpleNamespace(status="complete"), SimpleNamespace(status="idle")]
    )
    recovery = ThresholdReleaseRecoveryLoop(
        planner=planner,
        coordinator=coordinator,
        batch_size=10,
    )

    outcome = await recovery.run_once()

    assert outcome["planner_errors"] == 1
    assert outcome["execution_errors"] == 1
    assert outcome["planned"] == 1
    assert outcome["completed"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("lane", ["planner", "coordinator"])
async def test_recovery_never_swallows_soft_time_limit(lane: str) -> None:
    planner = SequenceRunner(
        [
            SoftTimeLimitExceeded(),
            SimpleNamespace(status="idle"),
        ]
        if lane == "planner"
        else [SimpleNamespace(status="idle")]
    )
    coordinator = SequenceRunner(
        [
            SoftTimeLimitExceeded(),
            SimpleNamespace(status="idle"),
        ]
        if lane == "coordinator"
        else [SimpleNamespace(status="idle")]
    )
    recovery = ThresholdReleaseRecoveryLoop(
        planner=planner,
        coordinator=coordinator,
        batch_size=10,
    )

    with pytest.raises(SoftTimeLimitExceeded):
        await recovery.run_once()

    if lane == "planner":
        assert planner.calls == 1
        assert coordinator.calls == 0
    else:
        assert planner.calls == 1
        assert coordinator.calls == 1
