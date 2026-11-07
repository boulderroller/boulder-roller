from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from solders.keypair import Keypair

from app.solana_direct import derive_ride_attestation_pda

from app.services.ride_economic_coordinator import RideEconomicCoordinator
from app.services.ride_economic_coordinator import (
    CompletionStepDraft,
    RideEconomicPlanDraft,
)
from app.services.ride_effort_trim import EffortTrim, epoch_ms
from app.services.ride_attester import OnchainRideIdentity
from app.services.cal_tribute_policy import (
    CAL_TRIBUTE_POLICY_VERSION,
    calculate_segment_tss_base_units,
)
from app.services.ride_chain_accounts import LegacyCompletionEvidenceError
from app.services.ride_executor import (
    ChainReceiptExecution,
    PdaMismatchError,
    RideExecutor,
)


def _completion_hash(
    *,
    rider_wallet: str,
    ride_hash: bytes,
    vault_id: int,
    completion_time_s: int,
    cal_tribute: int,
) -> bytes:
    return hashlib.sha256(
        b"test-completion-v2"
        + rider_wallet.encode("utf-8")
        + ride_hash
        + f":{vault_id}:{completion_time_s}:{cal_tribute}".encode("ascii")
    ).digest()


class InMemoryRideEconomicRepository:
    def __init__(
        self,
        plan: dict,
        *,
        checkpoint_failure: bool = False,
        review_failure: bool = False,
    ) -> None:
        self.plan = deepcopy(plan)
        self.checkpoint_failure = checkpoint_failure
        self.review_failure = review_failure
        self.transitions: list[tuple[str, str]] = []
        self.projected_steps: list[int] = []
        self.retry_errors: list[str] = []
        self.frozen_payload: tuple[dict, list[dict]] | None = None
        self.threshold_hold_admissions: list[dict] = []

    async def freeze_plan(self, *, plan: dict, steps: list[dict]) -> dict:
        self.frozen_payload = (deepcopy(plan), deepcopy(steps))
        return {**deepcopy(plan), "state": "planned", "steps": deepcopy(steps)}

    async def record_threshold_provisional_hold_admission(self, **kwargs) -> dict:
        self.threshold_hold_admissions.append(deepcopy(kwargs))
        return deepcopy(kwargs)

    async def acquire_plan(
        self,
        *,
        ride_id: UUID,
        lease_owner: UUID,
        lease_seconds: int,
    ) -> dict | None:
        assert str(ride_id) == self.plan["ride_id"]
        if self.plan["state"] in {"complete", "review", "rejected"}:
            return None
        self.plan["lease_owner"] = str(lease_owner)
        return deepcopy(self.plan)

    async def get_plan(self, ride_id: UUID) -> dict | None:
        assert str(ride_id) == self.plan["ride_id"]
        return deepcopy(self.plan)

    async def advance_plan(
        self,
        *,
        ride_id: UUID,
        lease_owner: UUID,
        expected_state: str,
        next_state: str,
        fields: dict | None = None,
    ) -> dict:
        assert self.plan["state"] == expected_state
        assert self.plan["lease_owner"] == str(lease_owner)
        self.transitions.append((expected_state, next_state))
        self.plan["state"] = next_state
        self.plan.update(fields or {})
        return deepcopy(self.plan)

    async def confirm_completion_step(
        self,
        *,
        ride_id: UUID,
        lease_owner: UUID,
        step_index: int,
        expected_receipt_pda: str,
        tx_signature: str | None,
        confirmed_at: str,
    ) -> dict:
        step = self.plan["steps"][step_index]
        assert step["expected_receipt_pda"] == expected_receipt_pda
        step.update(
            {
                "state": "confirmed",
                "actual_tx_signature": tx_signature,
                "chain_confirmed_at": confirmed_at,
            }
        )
        return deepcopy(step)

    async def reconcile_completion_projection(
        self,
        *,
        ride_id: UUID,
        lease_owner: UUID,
        step_index: int,
    ) -> dict:
        self.projected_steps.append(step_index)
        return {"activity_id": str(ride_id), "step_index": step_index}

    async def mark_completion_projected(
        self,
        *,
        ride_id: UUID,
        lease_owner: UUID,
        step_index: int,
    ) -> dict:
        step = self.plan["steps"][step_index]
        step["state"] = "projected"
        return deepcopy(step)

    async def checkpoint_retry(
        self,
        *,
        ride_id: UUID,
        lease_owner: UUID,
        error: str,
        step_index: int | None,
        retry_delay_seconds: int,
    ) -> bool:
        if self.checkpoint_failure:
            raise RuntimeError("checkpoint database unavailable")
        self.retry_errors.append(error)
        self.plan["lease_owner"] = None
        return True

    async def mark_review(
        self,
        *,
        ride_id: UUID,
        lease_owner: UUID,
        reason: str,
        actor: str,
        conflict_evidence: dict,
    ) -> dict:
        if self.review_failure:
            raise RuntimeError("review database unavailable")
        self.plan.update(
            {
                "state": "review",
                "review_reason": reason,
                "review_actor": actor,
                "conflict_evidence": deepcopy(conflict_evidence),
                "review_version": int(self.plan.get("review_version") or 0) + 1,
            }
        )
        return deepcopy(self.plan)


class FaultInjectingRepository(InMemoryRideEconomicRepository):
    def __init__(self, plan: dict, *, failure_point: str) -> None:
        super().__init__(plan)
        self.failure_point = failure_point
        self.failure_injected = False
        self.projection_rows: set[int] = set()

    def _should_fail(self, point: str) -> bool:
        if self.failure_point == point and not self.failure_injected:
            self.failure_injected = True
            return True
        return False

    async def advance_plan(self, **kwargs) -> dict:
        transition = (kwargs["expected_state"], kwargs["next_state"])
        points = {
            ("planned", "attestation_confirmed"): "attestation_checkpoint",
            ("attestation_confirmed", "completions_confirmed"): (
                "completions_checkpoint"
            ),
            ("completions_confirmed", "cal_confirmed"): "cal_checkpoint",
            ("cal_confirmed", "projections_reconciled"): (
                "projections_checkpoint"
            ),
            ("projections_reconciled", "complete"): "complete_checkpoint",
        }
        if self._should_fail(points.get(transition, "")):
            raise RuntimeError(f"injected {points[transition]} failure")
        return await super().advance_plan(**kwargs)

    async def confirm_completion_step(self, **kwargs) -> dict:
        if self._should_fail("completion_checkpoint"):
            raise RuntimeError("injected completion checkpoint failure")
        return await super().confirm_completion_step(**kwargs)

    async def reconcile_completion_projection(self, **kwargs) -> dict:
        self.projection_rows.add(int(kwargs["step_index"]))
        return await super().reconcile_completion_projection(**kwargs)

    async def mark_completion_projected(self, **kwargs) -> dict:
        if self._should_fail("projection_checkpoint"):
            raise RuntimeError("injected projection checkpoint failure")
        return await super().mark_completion_projected(**kwargs)


class RecordingExecutor:
    def __init__(
        self,
        *,
        cal_failures: int = 0,
        completion_failures: int = 0,
    ) -> None:
        self.events: list[str] = []
        self.completion_calls: list[dict] = []
        self.cal_failures = cal_failures
        self.completion_failures = completion_failures
        self.created_attestations = 0
        self.created_cal_receipts = 0
        self.created_completion_receipts: set[int] = set()
        self._attestation_exists = False
        self._cal_receipt_exists = False

    def derive_attestation_pda(self, **kwargs) -> str:
        return f"attestation:{kwargs['ride_hash'].hex()}"

    def derive_cal_receipt_pda(self, **kwargs) -> str:
        return f"cal:{kwargs['ride_hash'].hex()}"

    def derive_completion_receipt_pda(self, **kwargs) -> str:
        return f"completion:{kwargs['ride_hash'].hex()}:{kwargs['vault_id']}"

    def build_completion_evidence_v2(self, **kwargs) -> bytes:
        return _completion_hash(**kwargs)

    async def record_ride_attestation(self, **kwargs) -> ChainReceiptExecution:
        self.events.append("attestation")
        if self._attestation_exists:
            return ChainReceiptExecution(
                reference=f"exists:{kwargs['expected_pda']}",
                pda=kwargs["expected_pda"],
                tx_signature=None,
                confirmed_at=None,
            )
        self._attestation_exists = True
        self.created_attestations += 1
        return ChainReceiptExecution.confirmed(
            pda=kwargs["expected_pda"],
            reference="attestation-tx",
        )

    async def record_climb_completion_receipt(self, **kwargs) -> ChainReceiptExecution:
        if kwargs.get("completion_evidence_version") != 2:
            raise LegacyCompletionEvidenceError(
                "frozen V1 completion evidence requires manual chain review"
            )
        self.events.append(f"completion:{kwargs['vault_id']}")
        self.completion_calls.append(
            {
                "vault_id": kwargs["vault_id"],
                "completion_time_s": kwargs["completion_time_s"],
                "cal_tribute": kwargs["cal_tribute"],
                "completion_evidence_hash": kwargs["completion_evidence_hash"],
                "expected_pda": kwargs["expected_pda"],
            }
        )
        if self.completion_failures:
            self.completion_failures -= 1
            raise RuntimeError("completion RPC unavailable")
        vault_id = int(kwargs["vault_id"])
        if vault_id in self.created_completion_receipts:
            return ChainReceiptExecution(
                reference=f"exists:{kwargs['expected_pda']}",
                pda=kwargs["expected_pda"],
                tx_signature=None,
                confirmed_at=None,
            )
        self.created_completion_receipts.add(vault_id)
        return ChainReceiptExecution.confirmed(
            pda=kwargs["expected_pda"],
            reference=f"completion-{kwargs['vault_id']}-tx",
        )

    async def credit_cal_receipt(self, **kwargs) -> ChainReceiptExecution:
        self.events.append("cal")
        if self.cal_failures:
            self.cal_failures -= 1
            raise RuntimeError("CAL RPC unavailable")
        if self._cal_receipt_exists:
            return ChainReceiptExecution(
                reference=f"exists:{kwargs['expected_pda']}",
                pda=kwargs["expected_pda"],
                tx_signature=None,
                confirmed_at=None,
            )
        self._cal_receipt_exists = True
        self.created_cal_receipts += 1
        return ChainReceiptExecution.confirmed(
            pda=kwargs["expected_pda"],
            reference="cal-tx",
        )


class MismatchedPdaExecutor(RecordingExecutor):
    async def record_ride_attestation(self, **kwargs) -> ChainReceiptExecution:
        raise PdaMismatchError("derived attestation does not match frozen plan")


class SettledAtExecutor(RecordingExecutor):
    async def record_ride_attestation(self, **kwargs) -> ChainReceiptExecution:
        self.events.append("attestation")
        self._attestation_exists = True
        self.created_attestations += 1
        return ChainReceiptExecution(
            reference="attestation-tx",
            pda=kwargs["expected_pda"],
            tx_signature="attestation-tx",
            confirmed_at="2026-07-13T13:05:00+00:00",
        )


def _plan(*, completion_count: int = 2) -> dict:
    ride_id = uuid4()
    completed_at = datetime(2026, 7, 13, 13, 0, tzinfo=timezone.utc).isoformat()
    steps = [
        {
            "step_index": index,
            "pattern_id": str(uuid4()),
            "vault_id": 100 + index,
            "vault_signature": f"vault-signature-{index}",
            "completion_time_s": 300 + index,
            "exact_tribute_base_units": 10 + index,
            "completion_evidence_version": 2,
            "completion_evidence_hash_hex": f"{index + 1:02x}" * 32,
            "expected_receipt_pda": f"completion-pda-{index}",
            "completed_at": completed_at,
            "state": "planned",
        }
        for index in range(completion_count)
    ]
    return {
        "ride_id": str(ride_id),
        "user_id": str(uuid4()),
        "wallet": "11111111111111111111111111111111",
        "ride_hash_hex": "ab" * 32,
        "attestation_commitment_hex": "cd" * 32,
        "parser_version": 7,
        "source_kind": 1,
        "started_at": "2026-07-13T12:00:00+00:00",
        "completed_at": completed_at,
        "total_tss": 84,
        "total_distance_m": 12000,
        "total_vert_m": 300,
        "exact_cal_base_units": 84_000_000_000,
        "climbs_crossed": completion_count,
        "expected_attestation_pda": "attestation-pda",
        "expected_cal_receipt_pda": "cal-pda",
        "reward_policy": "rewardable",
        "state": "planned",
        "lease_owner": None,
        "steps": steps,
    }


@pytest.mark.asyncio
async def test_threshold_hold_admission_uses_chain_settled_at() -> None:
    plan = _plan(completion_count=0)
    plan["reward_policy"] = "threshold_provisional_hold_v1"
    repository = InMemoryRideEconomicRepository(plan)
    coordinator = RideEconomicCoordinator(
        repository=repository,
        executor=SettledAtExecutor(),
    )

    outcome = await coordinator.execute(UUID(plan["ride_id"]))

    assert outcome.status == "complete"
    assert repository.threshold_hold_admissions == [
        {
            "ride_id": UUID(plan["ride_id"]),
            "admitted_at": "2026-07-13T13:05:00+00:00",
            "expected_attestation_pda": "attestation-pda",
        }
    ]


@pytest.mark.asyncio
async def test_freeze_preserves_exact_reconstructed_climb_plan() -> None:
    ride_id = uuid4()
    repository = InMemoryRideEconomicRepository(_plan(completion_count=0))
    executor = RecordingExecutor()
    coordinator = RideEconomicCoordinator(repository=repository, executor=executor)
    completed_at = datetime(2026, 7, 13, 13, 0, tzinfo=timezone.utc)
    identity = OnchainRideIdentity(
        ride_hash=bytes.fromhex("ab" * 32),
        attestation_commitment=bytes.fromhex("cd" * 32),
        parser_version=7,
        source_kind=1,
    )
    completion_steps = tuple(
        CompletionStepDraft(
            pattern_id=uuid4(),
            vault_id=100 + index,
            vault_signature=f"vault-{index}",
            completion_time_s=300 + index,
            completed_at=completed_at,
            exact_tribute_base_units=calculate_segment_tss_base_units(
                segment_np_duration_s=300 + index,
                segment_np_milliwatts=240_000,
                reward_ftp_w=200,
            ),
            intensity_bps=12000,
            completion_evidence_hash=_completion_hash(
                rider_wallet="wallet-1",
                ride_hash=identity.ride_hash,
                vault_id=100 + index,
                completion_time_s=300 + index,
                cal_tribute=calculate_segment_tss_base_units(
                    segment_np_duration_s=300 + index,
                    segment_np_milliwatts=240_000,
                    reward_ftp_w=200,
                ),
            ),
            completion_evidence_version=2,
            segment_start_offset_s=index * 400,
            segment_end_offset_s=index * 400 + 299 + index,
            segment_np_w=240,
            segment_np_milliwatts=240_000,
            segment_np_duration_s=300 + index,
            segment_power_sample_count=300 + index,
            segment_power_coverage_bps=10_000,
            tribute_weight=0,
        )
        for index in range(2)
    )

    frozen = await coordinator.freeze_plan(
        RideEconomicPlanDraft(
            effort_trim=EffortTrim([(epoch_ms(completed_at.replace(hour=12)), epoch_ms(completed_at)+1000)], [(epoch_ms(completed_at.replace(hour=12)), epoch_ms(completed_at)+1000)]),
            ride_id=ride_id,
            user_id=uuid4(),
            wallet="wallet-1",
            identity=identity,
            policy_version="test-policy",
            reward_policy="rewardable",
            tribute_policy_version=CAL_TRIBUTE_POLICY_VERSION,
            started_at=completed_at.replace(hour=12),
            completed_at=completed_at,
            total_tss=84,
            total_distance_m=12000,
            total_vert_m=300,
            exact_cal_base_units=230_000_000_000,
            climbs_crossed=2,
            completion_steps=completion_steps,
        )
    )

    assert frozen["climbs_crossed"] == 2
    expected_total = sum(step.exact_tribute_base_units for step in completion_steps)
    assert frozen["exact_cal_base_units"] == 230_000_000_000
    assert frozen["exact_tribute_budget_base_units"] == expected_total
    assert frozen["exact_tribute_base_units"] == expected_total
    assert len(frozen["steps"]) == 2
    assert [step["vault_id"] for step in frozen["steps"]] == [100, 101]
    assert all(step["expected_receipt_pda"] for step in frozen["steps"])


def _one_hz_step(
    *,
    identity: OnchainRideIdentity,
    completed_at: datetime,
    completion_time_s: int,
    segment_start_offset_s: int,
    segment_end_offset_s: int,
    segment_np_duration_s: int,
) -> CompletionStepDraft:
    tribute = calculate_segment_tss_base_units(
        segment_np_duration_s=segment_np_duration_s,
        segment_np_milliwatts=280_000,
        reward_ftp_w=200,
    )
    return CompletionStepDraft(
        pattern_id=uuid4(),
        vault_id=0,
        vault_signature="vault-0",
        completion_time_s=completion_time_s,
        completed_at=completed_at,
        exact_tribute_base_units=tribute,
        intensity_bps=14000,
        completion_evidence_hash=_completion_hash(
            rider_wallet="wallet-1",
            ride_hash=identity.ride_hash,
            vault_id=0,
            completion_time_s=completion_time_s,
            cal_tribute=tribute,
        ),
        completion_evidence_version=2,
        segment_start_offset_s=segment_start_offset_s,
        segment_end_offset_s=segment_end_offset_s,
        segment_np_w=280,
        segment_np_milliwatts=280_000,
        segment_np_duration_s=segment_np_duration_s,
        segment_power_sample_count=segment_np_duration_s,
        segment_power_coverage_bps=10_000,
        tribute_weight=0,
    )


def _one_hz_draft(step: CompletionStepDraft, identity: OnchainRideIdentity, completed_at: datetime) -> RideEconomicPlanDraft:
    return RideEconomicPlanDraft(
            effort_trim=EffortTrim([(epoch_ms(completed_at.replace(hour=12)), epoch_ms(completed_at)+1000)], [(epoch_ms(completed_at.replace(hour=12)), epoch_ms(completed_at)+1000)]),
        ride_id=uuid4(),
        user_id=uuid4(),
        wallet="wallet-1",
        identity=identity,
        policy_version="test-policy",
        reward_policy="rewardable",
        tribute_policy_version=CAL_TRIBUTE_POLICY_VERSION,
        started_at=completed_at.replace(hour=12),
        completed_at=completed_at,
        total_tss=27,
        total_distance_m=5434,
        total_vert_m=52,
        exact_cal_base_units=26_900_000_000,
        climbs_crossed=1,
        completion_steps=(step,),
    )


@pytest.mark.asyncio
async def test_freeze_accepts_fully_sampled_one_hz_climb_window() -> None:
    """A 1 Hz ride covers the whole inclusive window: completion_time + 1 samples.

    The frozen offsets are whole-second roundings of the gate crossings, so a
    183 s traversal yields 184 samples (or 183/185 by rounding). NP measured
    over every one of them must freeze; the old ``min(completion_time, window)``
    bound rejected every complete-power real ride on Shawmont Avenue.
    """
    repository = InMemoryRideEconomicRepository(_plan(completion_count=0))
    coordinator = RideEconomicCoordinator(repository=repository, executor=RecordingExecutor())
    completed_at = datetime(2026, 9, 9, 21, 46, tzinfo=timezone.utc)
    identity = OnchainRideIdentity(
        ride_hash=bytes.fromhex("0c" * 32),
        attestation_commitment=bytes.fromhex("cd" * 32),
        parser_version=5,
        source_kind=1,
    )

    for window_extra in (0, 1, 2):
        step = _one_hz_step(
            identity=identity,
            completed_at=completed_at,
            completion_time_s=183,
            segment_start_offset_s=406,
            segment_end_offset_s=406 + 182 + window_extra,
            segment_np_duration_s=183 + window_extra,
        )
        frozen = await coordinator.freeze_plan(_one_hz_draft(step, identity, completed_at))
        assert frozen["steps"][0]["segment_np_duration_s"] == 183 + window_extra

    with pytest.raises(ValueError, match="NP duration exceeds climb window"):
        await coordinator.freeze_plan(
            _one_hz_draft(
                _one_hz_step(
                    identity=identity,
                    completed_at=completed_at,
                    completion_time_s=183,
                    segment_start_offset_s=406,
                    segment_end_offset_s=589,
                    segment_np_duration_s=185,
                ),
                identity,
                completed_at,
            )
        )

    with pytest.raises(ValueError, match="segment window does not match completion time"):
        await coordinator.freeze_plan(
            _one_hz_draft(
                _one_hz_step(
                    identity=identity,
                    completed_at=completed_at,
                    completion_time_s=183,
                    segment_start_offset_s=406,
                    segment_end_offset_s=592,
                    segment_np_duration_s=183,
                ),
                identity,
                completed_at,
            )
        )


@pytest.mark.asyncio
async def test_freeze_rejects_fractional_base_units() -> None:
    repository = InMemoryRideEconomicRepository(_plan(completion_count=0))
    coordinator = RideEconomicCoordinator(
        repository=repository,
        executor=RecordingExecutor(),
    )
    completed_at = datetime(2026, 7, 13, 13, 0, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="exact_cal_base_units must be an integer"):
        await coordinator.freeze_plan(
            RideEconomicPlanDraft(
            effort_trim=EffortTrim([(epoch_ms(completed_at.replace(hour=12)), epoch_ms(completed_at)+1000)], [(epoch_ms(completed_at.replace(hour=12)), epoch_ms(completed_at)+1000)]),
                ride_id=uuid4(),
                user_id=uuid4(),
                wallet="wallet-1",
                identity=OnchainRideIdentity(
                    ride_hash=bytes.fromhex("ab" * 32),
                    attestation_commitment=bytes.fromhex("cd" * 32),
                    parser_version=7,
                    source_kind=1,
                ),
                policy_version="test-policy",
                reward_policy="rewardable",
                tribute_policy_version=CAL_TRIBUTE_POLICY_VERSION,
                started_at=completed_at.replace(hour=12),
                completed_at=completed_at,
                total_tss=84,
                total_distance_m=12000,
                total_vert_m=300,
                exact_cal_base_units=84.5,
                climbs_crossed=0,
                completion_steps=(),
            )
        )


@pytest.mark.asyncio
async def test_freeze_hash_ignores_reconstructed_pattern_uuid() -> None:
    repository = InMemoryRideEconomicRepository(_plan(completion_count=0))
    coordinator = RideEconomicCoordinator(
        repository=repository,
        executor=RecordingExecutor(),
    )
    completed_at = datetime(2026, 7, 13, 13, 0, tzinfo=timezone.utc)
    identity = OnchainRideIdentity(
        ride_hash=bytes.fromhex("ab" * 32),
        attestation_commitment=bytes.fromhex("cd" * 32),
        parser_version=7,
        source_kind=1,
    )

    def draft(pattern_id: UUID) -> RideEconomicPlanDraft:
        return RideEconomicPlanDraft(
            effort_trim=EffortTrim([(epoch_ms(completed_at.replace(hour=12)), epoch_ms(completed_at)+1000)], [(epoch_ms(completed_at.replace(hour=12)), epoch_ms(completed_at)+1000)]),
            ride_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            user_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
            wallet="wallet-1",
            identity=identity,
            policy_version="test-policy",
            reward_policy="rewardable",
            tribute_policy_version=CAL_TRIBUTE_POLICY_VERSION,
            started_at=completed_at.replace(hour=12),
            completed_at=completed_at,
            total_tss=84,
            total_distance_m=12000,
            total_vert_m=300,
            exact_cal_base_units=110_000_000_000,
            climbs_crossed=1,
            completion_steps=(
                CompletionStepDraft(
                    pattern_id=pattern_id,
                    vault_id=100,
                    vault_signature="vault-100",
                    completion_time_s=300,
                    completed_at=completed_at,
                    exact_tribute_base_units=12_000_000_000,
                    intensity_bps=12000,
                    completion_evidence_hash=_completion_hash(
                        rider_wallet="wallet-1",
                        ride_hash=identity.ride_hash,
                        vault_id=100,
                        completion_time_s=300,
                        cal_tribute=12_000_000_000,
                    ),
                    completion_evidence_version=2,
                    segment_start_offset_s=0,
                    segment_end_offset_s=299,
                    segment_np_w=240,
                    segment_np_milliwatts=240_000,
                    segment_np_duration_s=300,
                    segment_power_sample_count=300,
                    segment_power_coverage_bps=10_000,
                    tribute_weight=0,
                ),
            ),
        )

    await coordinator.freeze_plan(draft(uuid4()))
    first_hash = repository.frozen_payload[0]["plan_evidence_hash_hex"]
    first_pattern = repository.frozen_payload[1][0]["pattern_id"]
    await coordinator.freeze_plan(draft(uuid4()))
    second_hash = repository.frozen_payload[0]["plan_evidence_hash_hex"]
    second_pattern = repository.frozen_payload[1][0]["pattern_id"]

    assert first_pattern != second_pattern
    assert first_hash == second_hash


@pytest.mark.asyncio
async def test_attestation_precedes_all_completions_and_cal_is_last() -> None:
    plan = _plan(completion_count=2)
    repository = InMemoryRideEconomicRepository(plan)
    executor = RecordingExecutor()
    coordinator = RideEconomicCoordinator(repository=repository, executor=executor)

    outcome = await coordinator.execute(UUID(plan["ride_id"]))

    assert outcome.status == "complete"
    assert executor.events == ["attestation", "completion:100", "completion:101", "cal"]
    assert executor.completion_calls == [
        {
            "vault_id": 100,
            "completion_time_s": 300,
            "cal_tribute": 10,
            "completion_evidence_hash": bytes.fromhex("01" * 32),
            "expected_pda": "completion-pda-0",
        },
        {
            "vault_id": 101,
            "completion_time_s": 301,
            "cal_tribute": 11,
            "completion_evidence_hash": bytes.fromhex("02" * 32),
            "expected_pda": "completion-pda-1",
        },
    ]
    assert repository.transitions == [
        ("planned", "attestation_confirmed"),
        ("attestation_confirmed", "completions_confirmed"),
        ("completions_confirmed", "cal_confirmed"),
        ("cal_confirmed", "projections_reconciled"),
        ("projections_reconciled", "complete"),
    ]


@pytest.mark.asyncio
async def test_pending_v1_plan_enters_review_without_retrying_or_crediting_cal() -> None:
    plan = _plan(completion_count=1)
    plan["state"] = "attestation_confirmed"
    plan["steps"][0]["completion_evidence_version"] = 1
    repository = InMemoryRideEconomicRepository(plan)
    executor = RecordingExecutor()
    coordinator = RideEconomicCoordinator(repository=repository, executor=executor)

    outcome = await coordinator.execute(UUID(plan["ride_id"]))

    assert outcome.status == "under_review"
    assert outcome.state == "review"
    assert repository.retry_errors == []
    assert executor.events == []
    assert repository.plan["conflict_evidence"]["kind"] == (
        "legacy_completion_evidence"
    )


@pytest.mark.asyncio
async def test_cal_failure_replay_converges_without_duplicate_completion() -> None:
    plan = _plan(completion_count=1)
    repository = InMemoryRideEconomicRepository(plan)
    executor = RecordingExecutor(cal_failures=1)
    coordinator = RideEconomicCoordinator(repository=repository, executor=executor)

    first = await coordinator.execute(UUID(plan["ride_id"]))
    second = await coordinator.execute(UUID(plan["ride_id"]))

    assert first.status == "recovery_pending"
    assert first.durable_checkpoint is True
    assert second.status == "complete"
    assert executor.events.count("attestation") == 1
    assert executor.events.count("completion:100") == 1
    assert executor.events.count("cal") == 2
    assert repository.projected_steps == [0]


@pytest.mark.asyncio
async def test_completion_failure_stays_retryable_and_never_advances_to_cal() -> None:
    plan = _plan(completion_count=1)
    repository = InMemoryRideEconomicRepository(plan)
    executor = RecordingExecutor(completion_failures=1)
    coordinator = RideEconomicCoordinator(repository=repository, executor=executor)

    outcome = await coordinator.execute(UUID(plan["ride_id"]))

    assert outcome.status == "recovery_pending"
    assert outcome.durable_checkpoint is True
    assert repository.plan["state"] == "attestation_confirmed"
    assert executor.events == ["attestation", "completion:100"]
    assert "cal" not in executor.events


@pytest.mark.asyncio
async def test_checkpoint_persistence_failure_is_not_reported_as_durable() -> None:
    plan = _plan(completion_count=1)
    repository = InMemoryRideEconomicRepository(plan, checkpoint_failure=True)
    executor = RecordingExecutor(cal_failures=1)
    coordinator = RideEconomicCoordinator(repository=repository, executor=executor)

    outcome = await coordinator.execute(UUID(plan["ride_id"]))

    assert outcome.status == "recovery_pending"
    assert outcome.durable_checkpoint is False
    assert "checkpoint persistence failed" in str(outcome.error)


@pytest.mark.asyncio
async def test_pda_mismatch_moves_frozen_plan_to_durable_review() -> None:
    plan = _plan(completion_count=1)
    repository = InMemoryRideEconomicRepository(plan)
    coordinator = RideEconomicCoordinator(
        repository=repository,
        executor=MismatchedPdaExecutor(),
    )

    outcome = await coordinator.execute(UUID(plan["ride_id"]))

    assert outcome.status == "under_review"
    assert outcome.state == "review"
    assert outcome.durable_checkpoint is True
    assert repository.plan["state"] == "review"
    assert "pda_mismatch" in str(repository.plan["review_reason"])
    assert repository.plan["review_actor"] == "service:ride-economic-coordinator"
    assert repository.plan["conflict_evidence"]["operation"] == "attestation"
    assert repository.plan["conflict_evidence"]["version"] == 1


@pytest.mark.asyncio
async def test_review_persistence_failure_is_not_reported_as_durable() -> None:
    plan = _plan(completion_count=1)
    repository = InMemoryRideEconomicRepository(plan, review_failure=True)
    coordinator = RideEconomicCoordinator(
        repository=repository,
        executor=MismatchedPdaExecutor(),
    )

    outcome = await coordinator.execute(UUID(plan["ride_id"]))

    assert outcome.status == "under_review"
    assert outcome.durable_checkpoint is False
    assert repository.plan["state"] == "planned"
    assert repository.projected_steps == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "account_data",
    [
        b"wrong-discriminator" + bytes(205 - len("wrong-discriminator")),
        b"short-layout",
    ],
    ids=["wrong_anchor_discriminator", "wrong_anchor_layout_length"],
)
async def test_permanent_attestation_layout_conflict_enters_durable_review(
    account_data: bytes,
) -> None:
    plan = _plan(completion_count=0)
    program_id = Keypair().pubkey()
    rider = Keypair().pubkey()
    plan["wallet"] = str(rider)
    pda, _ = derive_ride_attestation_pda(
        rider, bytes.fromhex(plan["ride_hash_hex"]), program_id
    )
    plan["expected_attestation_pda"] = str(pda)
    repository = InMemoryRideEconomicRepository(plan)
    executor = RideExecutor(
        config_loader=lambda: SimpleNamespace(
            program_id=program_id, rpc_url="https://rpc.invalid"
        ),
        record_ride_fn=AsyncMock(return_value=f"exists:{pda}"),
        account_reader=AsyncMock(
            return_value=SimpleNamespace(owner=program_id, data=account_data)
        ),
    )
    coordinator = RideEconomicCoordinator(repository=repository, executor=executor)

    outcome = await coordinator.execute(UUID(plan["ride_id"]))

    assert outcome.status == "under_review"
    assert outcome.durable_checkpoint is True
    assert repository.plan["state"] == "review"
    assert "pda_mismatch" in str(repository.plan["review_reason"])


@pytest.mark.asyncio
async def test_confirmed_signature_without_finalized_account_cannot_advance_plan() -> None:
    plan = _plan(completion_count=0)
    program_id = Keypair().pubkey()
    rider = Keypair().pubkey()
    plan["wallet"] = str(rider)
    pda, _ = derive_ride_attestation_pda(
        rider, bytes.fromhex(plan["ride_hash_hex"]), program_id
    )
    plan["expected_attestation_pda"] = str(pda)
    repository = InMemoryRideEconomicRepository(plan)
    account_reader = AsyncMock(return_value=None)
    executor = RideExecutor(
        config_loader=lambda: SimpleNamespace(
            program_id=program_id, rpc_url="https://rpc.invalid"
        ),
        record_ride_fn=AsyncMock(return_value="confirmed-fork-signature"),
        account_reader=account_reader,
        finalization_attempts=2,
        finalization_poll_seconds=0,
    )
    coordinator = RideEconomicCoordinator(repository=repository, executor=executor)

    outcome = await coordinator.execute(UUID(plan["ride_id"]))

    assert outcome.status == "recovery_pending"
    assert outcome.durable_checkpoint is True
    assert repository.plan["state"] == "planned"
    assert repository.transitions == []
    assert account_reader.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_point",
    [
        "attestation_checkpoint",
        "completion_checkpoint",
        "completions_checkpoint",
        "cal_checkpoint",
        "projection_checkpoint",
        "projections_checkpoint",
        "complete_checkpoint",
    ],
)
async def test_replay_after_each_successful_step_creates_each_receipt_once(
    failure_point: str,
) -> None:
    plan = _plan(completion_count=1)
    repository = FaultInjectingRepository(plan, failure_point=failure_point)
    executor = RecordingExecutor()
    coordinator = RideEconomicCoordinator(repository=repository, executor=executor)

    first = await coordinator.execute(UUID(plan["ride_id"]))
    second = await coordinator.execute(UUID(plan["ride_id"]))

    assert first.status == "recovery_pending"
    assert first.durable_checkpoint is True
    assert second.status == "complete"
    assert repository.failure_injected is True
    assert executor.created_attestations == 1
    assert executor.created_completion_receipts == {100}
    assert executor.created_cal_receipts == 1
    assert repository.projection_rows == {0}


def _boundary_draft(
    *,
    identity: OnchainRideIdentity | None = None,
    total_tss: int = 84,
    total_distance_m: int = 12_000,
    total_vert_m: int = 300,
    exact_cal_base_units: int = 110_000_000_000,
    climbs_crossed: int = 1,
    vault_id: int = 100,
    completion_time_s: int = 300,
    exact_tribute_base_units: int | None = None,
) -> RideEconomicPlanDraft:
    completed_at = datetime(2026, 7, 13, 13, 0, tzinfo=timezone.utc)
    resolved_identity = identity or OnchainRideIdentity(
        ride_hash=bytes.fromhex("ab" * 32),
        attestation_commitment=bytes.fromhex("cd" * 32),
        parser_version=7,
        source_kind=1,
    )
    resolved_tribute = (
        calculate_segment_tss_base_units(
            segment_np_duration_s=min(completion_time_s, 2**32 - 1),
            segment_np_milliwatts=1_000,
            reward_ftp_w=200,
        )
        if exact_tribute_base_units is None
        else exact_tribute_base_units
    )
    return RideEconomicPlanDraft(
            effort_trim=EffortTrim([(epoch_ms(completed_at.replace(hour=12)), epoch_ms(completed_at)+1000)], [(epoch_ms(completed_at.replace(hour=12)), epoch_ms(completed_at)+1000)]),
        ride_id=uuid4(),
        user_id=uuid4(),
        wallet="wallet-1",
        identity=resolved_identity,
        policy_version="test-policy",
        reward_policy="rewardable",
        tribute_policy_version=CAL_TRIBUTE_POLICY_VERSION,
        started_at=completed_at.replace(hour=12),
        completed_at=completed_at,
        total_tss=total_tss,
        total_distance_m=total_distance_m,
        total_vert_m=total_vert_m,
        exact_cal_base_units=exact_cal_base_units,
        climbs_crossed=climbs_crossed,
        completion_steps=(
            CompletionStepDraft(
                pattern_id=uuid4(),
                vault_id=vault_id,
                vault_signature="vault-1",
                completion_time_s=completion_time_s,
                completed_at=completed_at,
                exact_tribute_base_units=resolved_tribute,
                intensity_bps=50,
                completion_evidence_hash=_completion_hash(
                    rider_wallet="wallet-1",
                    ride_hash=resolved_identity.ride_hash,
                    vault_id=vault_id,
                    completion_time_s=completion_time_s,
                    cal_tribute=resolved_tribute,
                ),
                completion_evidence_version=2,
                segment_start_offset_s=0,
                segment_end_offset_s=min(max(completion_time_s - 1, 0), 2**32 - 1),
                segment_np_w=1,
                segment_np_milliwatts=1_000,
                segment_np_duration_s=completion_time_s,
                segment_power_sample_count=30,
                segment_power_coverage_bps=10_000,
                tribute_weight=0,
            ),
        ),
    )


@pytest.mark.asyncio
async def test_frozen_plan_hash_commits_reward_ftp_snapshot() -> None:
    first_draft = replace(
        _boundary_draft(),
        reward_ftp_w=200,
        reward_ftp_source="network_default",
        reward_ftp_policy_version="reward_ftp_policy_2026_07_14",
    )
    second_tribute = calculate_segment_tss_base_units(
        segment_np_duration_s=first_draft.completion_steps[0].segment_np_duration_s,
        segment_np_milliwatts=1_000,
        reward_ftp_w=250,
    )
    second_step = replace(
        first_draft.completion_steps[0],
        exact_tribute_base_units=second_tribute,
        intensity_bps=40,
    )
    second_step = replace(
        second_step,
        completion_evidence_hash=_completion_hash(
            rider_wallet=first_draft.wallet,
            ride_hash=first_draft.identity.ride_hash,
            vault_id=second_step.vault_id,
            completion_time_s=second_step.completion_time_s,
            cal_tribute=second_tribute,
        ),
    )
    second_draft = replace(
        first_draft,
        reward_ftp_w=250,
        reward_ftp_source="operator_verified",
        reward_ftp_authority_id=str(uuid4()),
        completion_steps=(second_step,),
    )
    frozen_payloads = []

    for draft in (first_draft, second_draft):
        repository = InMemoryRideEconomicRepository(_plan(completion_count=0))
        coordinator = RideEconomicCoordinator(
            repository=repository,
            executor=RecordingExecutor(),
        )
        await coordinator.freeze_plan(draft)
        frozen_payloads.append(repository.frozen_payload[0])

    first, second = frozen_payloads
    assert first["reward_ftp_w"] == 200
    assert first["reward_ftp_source"] == "network_default"
    assert first["reward_ftp_policy_version"] == "reward_ftp_policy_2026_07_14"
    assert first["plan_evidence_hash_hex"] != second["plan_evidence_hash_hex"]


@pytest.mark.asyncio
async def test_protocol_integer_widths_accept_exact_unsigned_maxima() -> None:
    u32_max = 2**32 - 1
    u64_max = 2**64 - 1
    repository = InMemoryRideEconomicRepository(_plan(completion_count=0))
    coordinator = RideEconomicCoordinator(
        repository=repository,
        executor=RecordingExecutor(),
    )

    frozen = await coordinator.freeze_plan(
        _boundary_draft(
            identity=OnchainRideIdentity(
                ride_hash=bytes.fromhex("ab" * 32),
                attestation_commitment=bytes.fromhex("cd" * 32),
                parser_version=u32_max,
                source_kind=2**8 - 1,
            ),
            total_tss=u32_max,
            total_distance_m=u32_max,
            total_vert_m=u32_max,
            exact_cal_base_units=u64_max,
            climbs_crossed=2**16 - 1,
            vault_id=u64_max,
            completion_time_s=u32_max,
        )
    )

    assert frozen["exact_cal_base_units"] == u64_max
    assert frozen["steps"][0]["vault_id"] == u64_max
    assert frozen["exact_tribute_base_units"] == calculate_segment_tss_base_units(
        segment_np_duration_s=u32_max,
        segment_np_milliwatts=1_000,
        reward_ftp_w=200,
    )


@pytest.mark.asyncio
async def test_freeze_rejects_tribute_that_does_not_match_segment_tss() -> None:
    expected = calculate_segment_tss_base_units(
        segment_np_duration_s=300,
        segment_np_milliwatts=1_000,
        reward_ftp_w=200,
    )
    draft = _boundary_draft(
        exact_cal_base_units=100_000_000_000,
        exact_tribute_base_units=expected + 1,
    )
    repository = InMemoryRideEconomicRepository(_plan(completion_count=0))
    coordinator = RideEconomicCoordinator(
        repository=repository,
        executor=RecordingExecutor(),
    )

    with pytest.raises(ValueError, match="measured climb TSS"):
        await coordinator.freeze_plan(draft)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "draft"),
    [
        (
            "parser_version",
            _boundary_draft(
                identity=OnchainRideIdentity(
                    ride_hash=bytes.fromhex("ab" * 32),
                    attestation_commitment=bytes.fromhex("cd" * 32),
                    parser_version=2**32,
                    source_kind=1,
                )
            ),
        ),
        (
            "source_kind",
            _boundary_draft(
                identity=OnchainRideIdentity(
                    ride_hash=bytes.fromhex("ab" * 32),
                    attestation_commitment=bytes.fromhex("cd" * 32),
                    parser_version=1,
                    source_kind=2**8,
                )
            ),
        ),
        ("total_tss", _boundary_draft(total_tss=2**32)),
        ("total_distance_m", _boundary_draft(total_distance_m=2**32)),
        ("total_vert_m", _boundary_draft(total_vert_m=2**32)),
        ("exact_cal_base_units", _boundary_draft(exact_cal_base_units=2**64)),
        ("climbs_crossed", _boundary_draft(climbs_crossed=2**16)),
        ("vault_id", _boundary_draft(vault_id=2**64)),
        ("completion_time_s", _boundary_draft(completion_time_s=2**32)),
        (
            "exact_tribute_base_units",
            _boundary_draft(exact_tribute_base_units=2**64),
        ),
    ],
)
async def test_protocol_integer_widths_reject_max_plus_one(
    field: str,
    draft: RideEconomicPlanDraft,
) -> None:
    repository = InMemoryRideEconomicRepository(_plan(completion_count=0))
    coordinator = RideEconomicCoordinator(
        repository=repository,
        executor=RecordingExecutor(),
    )

    with pytest.raises(ValueError, match=field):
        await coordinator.freeze_plan(draft)
