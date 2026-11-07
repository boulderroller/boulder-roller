from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID

import pytest
from celery.exceptions import SoftTimeLimitExceeded

from app.services.chain_receipt_execution import (
    ChainReceiptExecution,
    PdaMismatchError,
)
from app.repositories.ride_economic import ThresholdReleaseAuthorityConflictError
from app.services.threshold_release_coordinator import ThresholdReleaseCoordinator


LEASE_OWNER = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
SNAPSHOT_ID = "11111111-1111-4111-8111-111111111111"


def _plan() -> dict:
    return {
        "snapshot_id": SNAPSHOT_ID,
        "state": "planned",
        "wallet": "11111111111111111111111111111111",
        "ride_hash_hex": "12" * 32,
        "reward_ftp_authority_id": "22222222-2222-4222-8222-222222222222",
        "reward_ftp_authority_evidence_hash_hex": "23" * 32,
        "reward_ftp_policy_version": "reward_ftp_policy_2026_08_24_threshold_v1",
        "reward_ftp_w": 250,
        "admitted_at": "2026-08-24T16:00:00+00:00",
        "established_at": "2026-10-19T12:00:00+00:00",
        "economic_tss": 64.0,
        "total_tss": 64,
        "exact_cal_base_units": 64_000_000_000,
        "exact_tribute_budget_base_units": 6_400_000_000,
        "release_plan_evidence_hash_hex": "34" * 32,
        "expected_release_authority_pda": "release-pda",
        "expected_cal_receipt_pda": "cal-pda",
        "steps": [
            {
                "step_index": 0,
                "state": "planned",
                "vault_id": 7,
                "completion_time_s": 420,
                "exact_tribute_base_units": 4_000_000_000,
                "completion_evidence_hash_hex": "45" * 32,
                "completion_evidence_version": 3,
                "expected_receipt_pda": "completion-7",
            },
            {
                "step_index": 1,
                "state": "planned",
                "vault_id": 9,
                "completion_time_s": 900,
                "exact_tribute_base_units": 2_400_000_000,
                "completion_evidence_hash_hex": "56" * 32,
                "completion_evidence_version": 3,
                "expected_receipt_pda": "completion-9",
            },
        ],
    }


class RecordingRepository:
    def __init__(self, plan: dict | None = None) -> None:
        self.plan = deepcopy(plan) if plan is not None else None
        self.calls: list[tuple] = []

    async def claim_due_release_execution(self, **kwargs):
        self.calls.append(("claim", kwargs))
        return deepcopy(self.plan)

    async def advance_release_execution(
        self, *, expected_state: str, next_state: str, fields=None, **kwargs
    ):
        assert self.plan is not None
        assert self.plan["state"] == expected_state
        self.calls.append(("advance", expected_state, next_state, fields or {}))
        self.plan["state"] = next_state
        self.plan.update(fields or {})
        return deepcopy(self.plan)

    async def confirm_release_step(self, *, step_index: int, **kwargs):
        assert self.plan is not None
        self.calls.append(("confirm_step", step_index, kwargs))
        self.plan["steps"][step_index]["state"] = "confirmed"
        return deepcopy(self.plan["steps"][step_index])

    async def reconcile_release_completion(self, *, step_index: int, **kwargs):
        self.calls.append(("reconcile_step", step_index, kwargs))
        return {"step_index": step_index, "reconciled": True}

    async def mark_release_step_projected(self, *, step_index: int, **kwargs):
        assert self.plan is not None
        self.calls.append(("project_step", step_index, kwargs))
        self.plan["steps"][step_index]["state"] = "projected"
        return deepcopy(self.plan["steps"][step_index])

    async def checkpoint_release_retry(self, **kwargs):
        self.calls.append(("retry", kwargs))
        return True

    async def mark_threshold_release_review(self, **kwargs):
        self.calls.append(("review", kwargs))
        assert self.plan is not None
        self.plan["state"] = "review"
        return deepcopy(self.plan)


class TransientTerminalProjectionRepository(RecordingRepository):
    def __init__(self, plan: dict) -> None:
        super().__init__(plan)
        self.projection_attempts = 0

    async def project_threshold_release_terminal(self, **kwargs):
        self.projection_attempts += 1
        self.calls.append(("terminal_projection", kwargs))
        if self.projection_attempts == 1:
            raise RuntimeError("temporary projection failure")
        return {"terminal_projected_at": "2026-10-19T12:00:00+00:00"}


class TrainingProjectionRepository(RecordingRepository):
    def __init__(self, plan: dict) -> None:
        super().__init__(plan)
        self.training_projected = False

    async def project_threshold_release_terminal(self, **kwargs):
        self.calls.append(("terminal_projection", kwargs))
        assert self.plan is not None
        return {
            **deepcopy(self.plan),
            "ride_id": "33333333-3333-4333-8333-333333333333",
            "user_id": "44444444-4444-4444-8444-444444444444",
            "terminal_projected_at": "2026-10-19T12:00:00+00:00",
        }

    async def checkpoint_threshold_training_retry(self, **kwargs):
        self.calls.append(("training_retry", kwargs))
        return True

    async def mark_threshold_training_projected(self, **kwargs):
        self.calls.append(("training_projected", kwargs))
        self.training_projected = True
        return True


class FailsOnceTrainingProjector:
    def __init__(self) -> None:
        self.calls = 0

    async def project(self, release: dict) -> None:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("injected analytics failure")


class IndexedAuthorityConflictRepository(RecordingRepository):
    def __init__(self, plan: dict, *, failure_point: str) -> None:
        super().__init__(plan)
        self.failure_point = failure_point

    @staticmethod
    def _conflict(operation: str, code: str) -> ThresholdReleaseAuthorityConflictError:
        return ThresholdReleaseAuthorityConflictError(
            code=code,
            operation=operation,
            message=f"{operation} found immutable indexed authority conflict",
        )

    async def advance_release_execution(self, **kwargs):
        if (
            self.failure_point == "complete"
            and kwargs["next_state"] == "complete"
        ):
            raise self._conflict("advance_reward_threshold_release_execution", "BRR01")
        return await super().advance_release_execution(**kwargs)

    async def reconcile_release_completion(self, *, step_index: int, **kwargs):
        if self.failure_point == "reconcile":
            raise self._conflict(
                "reconcile_confirmed_reward_threshold_release_completion",
                "BRR03",
            )
        return await super().reconcile_release_completion(
            step_index=step_index, **kwargs
        )

    async def project_threshold_release_terminal(self, **kwargs):
        self.calls.append(("terminal_projection", kwargs))
        if self.failure_point == "terminal":
            raise self._conflict(
                "project_reward_threshold_release_terminal", "BRR02"
            )
        return {"terminal_projected_at": "2026-10-19T12:00:00+00:00"}


class PostChainCheckpointFailureRepository(RecordingRepository):
    def __init__(self, plan: dict, *, failure_point: str) -> None:
        super().__init__(plan)
        self.failure_point = failure_point
        self.failed = False

    def _fail_once(self, point: str) -> bool:
        if not self.failed and self.failure_point == point:
            self.failed = True
            return True
        return False

    async def advance_release_execution(self, **kwargs):
        transition = (kwargs["expected_state"], kwargs["next_state"])
        point = {
            ("planned", "release_authority_confirmed"): "authority",
            ("release_authority_confirmed", "cal_confirmed"): "cal",
        }.get(transition)
        if point and self._fail_once(point):
            raise RuntimeError(f"injected {point} checkpoint failure")
        return await super().advance_release_execution(**kwargs)

    async def confirm_release_step(self, *, step_index: int, **kwargs):
        if step_index == 0 and self._fail_once("completion"):
            raise RuntimeError("injected completion checkpoint failure")
        return await super().confirm_release_step(step_index=step_index, **kwargs)


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def authorize_held_ride_release_receipt(self, **kwargs):
        self.calls.append(("authorize", kwargs))
        return ChainReceiptExecution.confirmed(
            pda="release-pda", reference="release-signature"
        )

    async def record_released_climb_completion_receipt(self, **kwargs):
        self.calls.append(("completion", kwargs["vault_id"], kwargs))
        return ChainReceiptExecution.confirmed(
            pda=kwargs["expected_pda"],
            reference=f"completion-{kwargs['vault_id']}-signature",
        )

    async def credit_released_cal_receipt(self, **kwargs):
        self.calls.append(("cal", kwargs))
        return ChainReceiptExecution.confirmed(
            pda="cal-pda", reference="cal-signature"
        )


class SoftLimitExecutor(RecordingExecutor):
    async def authorize_held_ride_release_receipt(self, **kwargs):
        raise SoftTimeLimitExceeded()


class ExistingPdaOnRetryExecutor(RecordingExecutor):
    def __init__(self) -> None:
        super().__init__()
        self.seen: set[str] = set()

    def _execution(self, pda: str, signature: str) -> ChainReceiptExecution:
        if pda in self.seen:
            return ChainReceiptExecution(
                reference=f"exists:{pda}",
                pda=pda,
                tx_signature=None,
                confirmed_at="2026-10-19T12:00:00+00:00",
            )
        self.seen.add(pda)
        return ChainReceiptExecution.confirmed(pda=pda, reference=signature)

    async def authorize_held_ride_release_receipt(self, **kwargs):
        self.calls.append(("authorize", kwargs))
        return self._execution("release-pda", "release-signature")

    async def record_released_climb_completion_receipt(self, **kwargs):
        self.calls.append(("completion", kwargs["vault_id"], kwargs))
        return self._execution(
            kwargs["expected_pda"],
            f"completion-{kwargs['vault_id']}-signature",
        )

    async def credit_released_cal_receipt(self, **kwargs):
        self.calls.append(("cal", kwargs))
        return self._execution("cal-pda", "cal-signature")


class MissingClockExistingPdaExecutor(ExistingPdaOnRetryExecutor):
    def _execution(self, pda: str, signature: str) -> ChainReceiptExecution:
        if pda in self.seen:
            return ChainReceiptExecution(
                reference=f"exists:{pda}",
                pda=pda,
                tx_signature=None,
                confirmed_at=None,
            )
        return super()._execution(pda, signature)


@pytest.mark.asyncio
async def test_child_authority_then_cal_once_then_all_tribute() -> None:
    repository = RecordingRepository(_plan())
    executor = RecordingExecutor()
    coordinator = ThresholdReleaseCoordinator(
        repository=repository,
        executor=executor,
        lease_owner_factory=lambda: LEASE_OWNER,
    )

    outcome = await coordinator.run_once()

    assert outcome.status == "complete"
    assert outcome.state == "complete"
    assert [call[:2] for call in executor.calls] == [
        ("authorize", executor.calls[0][1]),
        ("cal", executor.calls[1][1]),
        ("completion", 7),
        ("completion", 9),
    ]
    assert executor.calls[0][1]["expected_pda"] == "release-pda"
    assert executor.calls[1][1]["amount"] == 64_000_000_000
    assert sum(
        call[2]["cal_tribute"]
        for call in executor.calls
        if call[0] == "completion"
    ) == 6_400_000_000
    assert all(
        call[2]["completion_evidence_version"] == 3
        for call in executor.calls
        if call[0] == "completion"
    )


@pytest.mark.asyncio
async def test_no_claim_performs_no_chain_work() -> None:
    repository = RecordingRepository(None)
    executor = RecordingExecutor()
    coordinator = ThresholdReleaseCoordinator(
        repository=repository,
        executor=executor,
        lease_owner_factory=lambda: LEASE_OWNER,
    )

    outcome = await coordinator.run_once()

    assert outcome.status == "idle"
    assert executor.calls == []


@pytest.mark.asyncio
async def test_soft_time_limit_bypasses_retry_checkpoint() -> None:
    repository = RecordingRepository(_plan())
    coordinator = ThresholdReleaseCoordinator(
        repository=repository,
        executor=SoftLimitExecutor(),
        lease_owner_factory=lambda: LEASE_OWNER,
    )

    with pytest.raises(SoftTimeLimitExceeded):
        await coordinator.run_once()

    assert [call[0] for call in repository.calls] == ["claim"]


class FailingExecutor(RecordingExecutor):
    async def record_released_climb_completion_receipt(self, **kwargs):
        if kwargs["vault_id"] == 9:
            raise RuntimeError("temporary completion failure")
        return await super().record_released_climb_completion_receipt(**kwargs)


class MismatchedAuthorityExecutor(RecordingExecutor):
    async def authorize_held_ride_release_receipt(self, **kwargs):
        raise PdaMismatchError("existing child authority does not match the plan")


@pytest.mark.asyncio
async def test_failure_after_one_receipt_retries_without_reminting_cal() -> None:
    repository = RecordingRepository(_plan())
    executor = FailingExecutor()
    coordinator = ThresholdReleaseCoordinator(
        repository=repository,
        executor=executor,
        lease_owner_factory=lambda: LEASE_OWNER,
        retry_delay_seconds=3,
    )

    outcome = await coordinator.run_once()

    assert outcome.status == "recovery_pending"
    assert outcome.durable_checkpoint is True
    assert [call[0] for call in executor.calls] == [
        "authorize",
        "cal",
        "completion",
    ]
    assert any(call[0] == "retry" for call in repository.calls)
    assert sum(call[0] == "cal" for call in executor.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_point", ["authority", "completion", "cal"])
async def test_existing_child_pda_recovers_after_sql_checkpoint_failure(
    failure_point: str,
) -> None:
    repository = PostChainCheckpointFailureRepository(
        _plan(), failure_point=failure_point
    )
    executor = ExistingPdaOnRetryExecutor()
    coordinator = ThresholdReleaseCoordinator(
        repository=repository,
        executor=executor,
        lease_owner_factory=lambda: LEASE_OWNER,
    )

    first = await coordinator.run_once()
    second = await coordinator.run_once()

    assert first.status == "recovery_pending"
    assert first.durable_checkpoint is True
    assert second.status == "complete"
    assert any(call[0] == "retry" for call in repository.calls)
    if failure_point == "authority":
        fields = next(
            call[3]
            for call in repository.calls
            if call[:3] == (
                "advance",
                "planned",
                "release_authority_confirmed",
            )
        )
        assert fields["release_authority_tx_signature"] is None
        assert fields["release_authority_confirmed_at"]


@pytest.mark.asyncio
async def test_existing_child_pda_without_chain_clock_cannot_checkpoint() -> None:
    repository = PostChainCheckpointFailureRepository(
        _plan(), failure_point="authority"
    )
    coordinator = ThresholdReleaseCoordinator(
        repository=repository,
        executor=MissingClockExistingPdaExecutor(),
        lease_owner_factory=lambda: LEASE_OWNER,
    )

    first = await coordinator.run_once()
    second = await coordinator.run_once()

    assert first.status == "recovery_pending"
    assert second.status == "recovery_pending"
    assert repository.plan is not None
    assert repository.plan["state"] == "planned"


@pytest.mark.asyncio
async def test_permanent_child_mismatch_enters_review_instead_of_retrying() -> None:
    repository = RecordingRepository(_plan())
    coordinator = ThresholdReleaseCoordinator(
        repository=repository,
        executor=MismatchedAuthorityExecutor(),
        lease_owner_factory=lambda: LEASE_OWNER,
    )

    outcome = await coordinator.run_once()

    assert outcome.status == "under_review"
    assert outcome.state == "review"
    assert outcome.durable_checkpoint is True
    assert any(call[0] == "review" for call in repository.calls)
    assert not any(call[0] == "retry" for call in repository.calls)


@pytest.mark.asyncio
async def test_operator_reentry_resumes_after_cal_and_preserves_confirmed_step() -> None:
    plan = _plan()
    plan["state"] = "cal_confirmed"
    plan["cal_confirmed_at"] = "2026-10-19T12:01:00+00:00"
    plan["steps"][0]["state"] = "confirmed"
    repository = RecordingRepository(plan)
    executor = RecordingExecutor()
    coordinator = ThresholdReleaseCoordinator(
        repository=repository,
        executor=executor,
        lease_owner_factory=lambda: LEASE_OWNER,
    )

    outcome = await coordinator.run_once()

    assert outcome.status == "complete"
    assert [call[:2] for call in executor.calls] == [("completion", 9)]
    assert not any(call[0] == "cal" for call in executor.calls)
    assert not any(
        call[0] == "confirm_step" and call[1] == 0
        for call in repository.calls
    )


@pytest.mark.asyncio
async def test_chain_complete_release_retries_transient_terminal_projection() -> None:
    plan = _plan()
    plan["state"] = "complete"
    plan["steps"] = [
        {**step, "state": "projected"} for step in plan["steps"]
    ]
    repository = TransientTerminalProjectionRepository(plan)
    coordinator = ThresholdReleaseCoordinator(
        repository=repository,
        executor=RecordingExecutor(),
        lease_owner_factory=lambda: LEASE_OWNER,
    )

    first = await coordinator.run_once()
    second = await coordinator.run_once()

    assert first.status == "recovery_pending"
    assert first.state == "complete"
    assert first.durable_checkpoint is True
    assert second.status == "complete"
    assert repository.projection_attempts == 2
    assert any(call[0] == "retry" for call in repository.calls)


@pytest.mark.asyncio
async def test_completed_release_remains_claimable_until_training_projection_succeeds() -> None:
    plan = _plan()
    plan["state"] = "complete"
    plan["steps"] = [{**step, "state": "projected"} for step in plan["steps"]]
    repository = TrainingProjectionRepository(plan)
    projector = FailsOnceTrainingProjector()
    coordinator = ThresholdReleaseCoordinator(
        repository=repository,
        executor=RecordingExecutor(),
        training_projector=projector,
        lease_owner_factory=lambda: LEASE_OWNER,
    )

    first = await coordinator.run_once()
    second = await coordinator.run_once()

    assert first.status == "recovery_pending"
    assert first.durable_checkpoint is True
    assert second.status == "complete"
    assert projector.calls == 2
    assert repository.training_projected is True
    assert any(call[0] == "training_retry" for call in repository.calls)
    assert any(call[0] == "training_projected" for call in repository.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_point", ["complete", "terminal"])
async def test_zero_step_indexed_authority_conflict_enters_review(
    failure_point: str,
) -> None:
    plan = _plan()
    plan["steps"] = []
    plan["state"] = (
        "projections_reconciled" if failure_point == "complete" else "complete"
    )
    repository = IndexedAuthorityConflictRepository(
        plan, failure_point=failure_point
    )
    coordinator = ThresholdReleaseCoordinator(
        repository=repository,
        executor=RecordingExecutor(),
        lease_owner_factory=lambda: LEASE_OWNER,
    )

    outcome = await coordinator.run_once()

    assert outcome.status == "under_review"
    assert outcome.state == "review"
    assert outcome.durable_checkpoint is True
    review_call = next(call for call in repository.calls if call[0] == "review")
    assert review_call[1]["conflict_evidence"]["phase"] == failure_point
    assert not any(call[0] == "retry" for call in repository.calls)


@pytest.mark.asyncio
async def test_multi_step_indexed_completion_conflict_enters_review() -> None:
    plan = _plan()
    plan["state"] = "completions_confirmed"
    plan["steps"] = [
        {**step, "state": "confirmed"} for step in plan["steps"]
    ]
    repository = IndexedAuthorityConflictRepository(
        plan, failure_point="reconcile"
    )
    coordinator = ThresholdReleaseCoordinator(
        repository=repository,
        executor=RecordingExecutor(),
        lease_owner_factory=lambda: LEASE_OWNER,
    )

    outcome = await coordinator.run_once()

    assert outcome.status == "under_review"
    assert outcome.state == "review"
    assert outcome.durable_checkpoint is True
    review_call = next(call for call in repository.calls if call[0] == "review")
    assert review_call[1]["conflict_evidence"]["phase"] == "reconcile"
    assert review_call[1]["conflict_evidence"]["step_index"] == 0
    assert not any(call[0] == "retry" for call in repository.calls)


def test_fixture_timestamps_are_utc_and_release_after_establishment() -> None:
    plan = _plan()
    admitted = datetime.fromisoformat(plan["admitted_at"])
    established = datetime.fromisoformat(plan["established_at"])
    assert admitted.tzinfo == timezone.utc
    assert established > admitted
