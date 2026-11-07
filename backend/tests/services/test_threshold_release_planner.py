from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from uuid import UUID

import pytest

from app.services.ride_economic_plan import CompletionStepDraft
from app.services.threshold_release_planner import (
    ThresholdReleasePlanner,
    build_threshold_hold_evidence,
)


LEASE_OWNER = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
RIDE_ID = "11111111-1111-4111-8111-111111111111"
USER_ID = "22222222-2222-4222-8222-222222222222"
AUTHORITY_ID = "33333333-3333-4333-8333-333333333333"
WALLET = "11111111111111111111111111111111"


def _hold_evidence() -> dict:
    metrics = {
        "normalized_power_raw_w": 200.0,
        "normalized_power_duration_s": 3600,
        "normalized_power_w": 200,
        "avg_power_w": 190,
        "avg_hr_bpm": None,
        "metrics_version": "workout_parse_metrics_v1",
        "moving_time_sec": 3600,
        "duration_sec": 3600,
        "power_sample_count": 3600,
        "power_sample_coverage_bps": 10_000,
        "heart_rate_sample_count": 0,
        "heart_rate_sample_coverage_bps": 0,
        "started_at": datetime(2026, 8, 24, 15, 0, tzinfo=timezone.utc),
        "completed_at": datetime(2026, 8, 24, 16, 0, tzinfo=timezone.utc),
    }
    steps = [
        CompletionStepDraft(
            pattern_id=UUID("44444444-4444-4444-8444-444444444444"),
            vault_id=0,  # the VaultCounter starts at 0; Vault 0 is a real vault
            vault_signature="07" * 32,
            completion_time_s=420,
            completed_at=datetime(2026, 8, 24, 16, 0, tzinfo=timezone.utc),
            exact_tribute_base_units=0,
            intensity_bps=0,
            completion_evidence_hash=b"\x00" * 32,
            completion_evidence_version=2,
            segment_start_offset_s=60,
            segment_end_offset_s=480,
            segment_np_w=250,
            segment_np_milliwatts=250_000,
            segment_np_duration_s=420,
            segment_power_sample_count=420,
            segment_power_coverage_bps=10_000,
            tribute_weight=0,
            climb_distance_m=1_200,
            climb_vert_m=90,
        ),
        CompletionStepDraft(
            pattern_id=UUID("55555555-5555-4555-8555-555555555555"),
            vault_id=9,
            vault_signature="09" * 32,
            completion_time_s=900,
            completed_at=datetime(2026, 8, 24, 16, 0, tzinfo=timezone.utc),
            exact_tribute_base_units=0,
            intensity_bps=0,
            completion_evidence_hash=b"\x00" * 32,
            completion_evidence_version=2,
            segment_start_offset_s=600,
            segment_end_offset_s=1_500,
            segment_np_w=200,
            segment_np_milliwatts=200_000,
            segment_np_duration_s=900,
            segment_power_sample_count=900,
            segment_power_coverage_bps=10_000,
            tribute_weight=0,
            climb_distance_m=2_400,
            climb_vert_m=180,
        ),
    ]
    return build_threshold_hold_evidence(metrics=metrics, completion_steps=steps)


def _claim(*, late_upload: bool = False) -> dict:
    admitted_at = "2026-08-24T16:00:00+00:00"
    established_at = (
        "2026-08-17T12:00:00+00:00"
        if late_upload
        else "2026-10-19T12:00:00+00:00"
    )
    return {
        "batch_item_id": "66666666-6666-4666-8666-666666666666",
        "ride_id": RIDE_ID,
        "user_id": USER_ID,
        "wallet": WALLET,
        "ride_hash_hex": "12" * 32,
        "admitted_at": admitted_at,
        "established_at": established_at,
        "reward_ftp_authority_id": AUTHORITY_ID,
        "reward_ftp_authority_evidence_hash_hex": "23" * 32,
        "reward_ftp_w": 250,
        "reward_ftp_source": "derived_eftp",
        "reward_ftp_policy_version": "reward_ftp_policy_2026_08_24_threshold_v1",
        "planner_lease_owner": str(LEASE_OWNER),
        "hold_evidence": _hold_evidence(),
    }


class RecordingRepository:
    def __init__(self, claim: dict | None) -> None:
        self.claim = deepcopy(claim)
        self.frozen: tuple[dict, list[dict]] | None = None
        self.terminal: dict | None = None

    async def claim_due_threshold_release_item(self, **kwargs):
        return deepcopy(self.claim)

    async def freeze_threshold_release_snapshot(self, *, snapshot, steps, lease_owner):
        assert lease_owner == LEASE_OWNER
        self.frozen = (deepcopy(snapshot), deepcopy(steps))
        return {"snapshot_id": "77777777-7777-4777-8777-777777777777"}

    async def mark_threshold_release_item_terminal(self, **kwargs):
        self.terminal = deepcopy(kwargs)
        return kwargs


class FailingFreezeRepository(RecordingRepository):
    async def freeze_threshold_release_snapshot(self, *, snapshot, steps, lease_owner):
        raise RuntimeError("database temporarily unavailable")


class DeterministicExecutor:
    def derive_held_ride_release_pda(self, *, rider_wallet, ride_hash):
        assert rider_wallet == WALLET
        assert len(ride_hash) == 32
        return "release-pda"

    def derive_cal_receipt_pda(self, *, rider_wallet, ride_hash):
        return "cal-pda"

    def derive_completion_receipt_pda(self, *, rider_wallet, ride_hash, vault_id):
        return f"completion-{vault_id}"

    def build_released_completion_evidence_v3(
        self,
        *,
        rider_wallet,
        ride_hash,
        vault_id,
        completion_time_s,
        cal_tribute,
        expected_release_authority_pda,
    ):
        assert expected_release_authority_pda == "release-pda"
        return bytes([vault_id]) + cal_tribute.to_bytes(8, "little") + b"\x00" * 23


@pytest.mark.asyncio
@pytest.mark.parametrize("late_upload", [False, True])
async def test_planner_freezes_threshold_specific_child_and_v3_receipts(
    monkeypatch, late_upload: bool
) -> None:
    repository = RecordingRepository(_claim(late_upload=late_upload))
    executor = DeterministicExecutor()
    calls: list[tuple[float, int, int]] = []

    def fake_tss(*, normalized_power_raw_w, normalized_power_duration_s, threshold_w):
        calls.append(
            (normalized_power_raw_w, normalized_power_duration_s, threshold_w)
        )
        return 64.0

    monkeypatch.setattr(
        "app.services.threshold_release_planner.calculate_threshold_release_tss",
        fake_tss,
    )
    planner = ThresholdReleasePlanner(
        repository=repository,
        executor=executor,
        lease_owner_factory=lambda: LEASE_OWNER,
    )

    outcome = await planner.run_once()

    assert outcome.status == "planned"
    assert calls == [(200.0, 3600, 250)]
    assert repository.frozen is not None
    snapshot, steps = repository.frozen
    assert snapshot["reward_ftp_authority_id"] == AUTHORITY_ID
    assert snapshot["reward_ftp_w"] == 250
    assert snapshot["economic_tss"] == 64.0
    assert snapshot["total_tss"] == 64
    assert snapshot["exact_cal_base_units"] == 64_000_000_000
    assert snapshot["exact_tribute_budget_base_units"] == 27_666_666_666
    assert snapshot["expected_release_authority_pda"] == "release-pda"
    assert snapshot["expected_cal_receipt_pda"] == "cal-pda"
    assert sum(step["exact_tribute_base_units"] for step in steps) == 27_666_666_666
    assert [step["completion_evidence_version"] for step in steps] == [3, 3]
    assert [step["expected_receipt_pda"] for step in steps] == [
        "completion-0",
        "completion-9",
    ]
    assert "release_plan_evidence_hash_hex" not in snapshot


@pytest.mark.asyncio
async def test_release_evidence_and_hash_do_not_depend_on_planner_lease_owner(
    monkeypatch,
) -> None:
    first_claim = _claim()
    second_claim = {**_claim(), "planner_lease_owner": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"}
    monkeypatch.setattr(
        "app.services.threshold_release_planner.calculate_threshold_release_tss",
        lambda **_kwargs: 64.0,
    )
    planner = ThresholdReleasePlanner(
        repository=RecordingRepository(None),
        executor=DeterministicExecutor(),
    )

    first_snapshot, first_steps = planner._build_snapshot(first_claim)
    second_snapshot, second_steps = planner._build_snapshot(second_claim)

    assert first_snapshot == second_snapshot
    assert first_steps == second_steps
    assert "planner_lease_owner" not in first_snapshot
    assert "planner_lease_owner" not in json.dumps(first_snapshot)


@pytest.mark.asyncio
async def test_planner_is_idle_without_a_claim() -> None:
    planner = ThresholdReleasePlanner(
        repository=RecordingRepository(None),
        executor=DeterministicExecutor(),
        lease_owner_factory=lambda: LEASE_OWNER,
    )

    outcome = await planner.run_once()

    assert outcome.status == "idle"
    assert outcome.durable_checkpoint is True


@pytest.mark.asyncio
async def test_planner_freezes_json_serializable_snapshot_without_cycles(
    monkeypatch,
) -> None:
    repository = RecordingRepository(_claim())
    monkeypatch.setattr(
        "app.services.threshold_release_planner.calculate_threshold_release_tss",
        lambda **_kwargs: 64.1,
    )
    planner = ThresholdReleasePlanner(
        repository=repository,
        executor=DeterministicExecutor(),
        lease_owner_factory=lambda: LEASE_OWNER,
    )

    outcome = await planner.run_once()

    assert outcome.status == "planned"
    assert repository.frozen is not None
    snapshot, _steps = repository.frozen
    assert snapshot["economic_tss"] == 64.1
    assert snapshot["exact_cal_base_units"] == 64_100_000_000
    assert json.loads(json.dumps(snapshot))["snapshot_evidence"]["plan"][
        "economic_tss"
    ] == 64.1


@pytest.mark.asyncio
async def test_planner_does_not_turn_transient_snapshot_failure_into_review(
    monkeypatch,
) -> None:
    repository = FailingFreezeRepository(_claim())
    monkeypatch.setattr(
        "app.services.threshold_release_planner.calculate_threshold_release_tss",
        lambda **_kwargs: 64.0,
    )
    planner = ThresholdReleasePlanner(
        repository=repository,
        executor=DeterministicExecutor(),
        lease_owner_factory=lambda: LEASE_OWNER,
    )

    with pytest.raises(RuntimeError, match="temporarily unavailable"):
        await planner.run_once()

    assert repository.terminal is None


@pytest.mark.asyncio
async def test_planner_routes_invalid_frozen_evidence_to_durable_review() -> None:
    claim = _claim()
    claim.pop("hold_evidence")
    repository = RecordingRepository(claim)
    planner = ThresholdReleasePlanner(
        repository=repository,
        executor=DeterministicExecutor(),
        lease_owner_factory=lambda: LEASE_OWNER,
    )

    outcome = await planner.run_once()

    assert outcome.status == "review"
    assert outcome.durable_checkpoint is True
    assert repository.terminal is not None
    assert repository.terminal["disposition"] == "review"
    assert repository.terminal["reason"] == "release claim lacks frozen hold evidence"


@pytest.mark.asyncio
async def test_preexisting_padded_hold_releases_its_admission_frozen_metrics(monkeypatch):
    wp = pytest.importorskip("workout_parse")
    claim = _claim()
    frozen = claim["hold_evidence"]["metrics"]
    measured = wp.compute_segment_power_metrics(
        [i * 1000 for i in range(129600)], [250] * 3600 + [0] * 126000
    )
    frozen.update({
        "normalized_power_raw_w": measured.normalized_power_raw_w,
        "normalized_power_duration_s": 129600,
        "normalized_power_w": measured.normalized_power_w,
        "moving_time_sec": 129600,
        "duration_sec": 129599,
        "power_sample_count": 129600,
    })
    original = deepcopy(claim["hold_evidence"])

    def must_not_reclassify(*args, **kwargs):
        raise AssertionError("release must use admission evidence, not today's idle policy")

    monkeypatch.setattr("app.services.ride_idle_evidence.assess_idle_recording", must_not_reclassify)
    monkeypatch.setattr("app.services.ride_processor.assess_idle_recording", must_not_reclassify)
    repository = RecordingRepository(claim)
    outcome = await ThresholdReleasePlanner(
        repository=repository, executor=DeterministicExecutor(), lease_owner_factory=lambda: LEASE_OWNER
    ).run_once()
    assert outcome.status == "planned"
    snapshot, steps = repository.frozen
    assert snapshot["economic_tss"] == 598.1
    assert snapshot["exact_cal_base_units"] == 598_100_000_000
    assert claim["hold_evidence"] == original
    assert frozen["metrics_version"] == "workout_parse_metrics_v1"
    assert [step["segment_np_duration_s"] for step in steps] == [420, 900]


@pytest.mark.asyncio
async def test_planner_routes_implausible_authority_to_review_without_freezing(
    monkeypatch,
):
    from app.repositories.ride_economic import ThresholdReleaseAuthorityConflictError

    class GatedRepository(RecordingRepository):
        async def freeze_threshold_release_snapshot(self, **kwargs):
            raise ThresholdReleaseAuthorityConflictError(
                code="BRR07", operation="freeze", message="Threshold fit requires review"
            )

    repository = GatedRepository(_claim())
    monkeypatch.setattr(
        "app.services.threshold_release_planner.calculate_threshold_release_tss",
        lambda **kwargs: 64.0,
    )
    planner = ThresholdReleasePlanner(
        repository=repository,
        executor=DeterministicExecutor(),
        lease_owner_factory=lambda: LEASE_OWNER,
    )
    outcome = await planner.run_once()
    assert outcome.status == "review"
    assert repository.frozen is None
    assert repository.terminal["disposition"] == "review"
