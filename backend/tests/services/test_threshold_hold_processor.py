from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.services.ride_attester import OnchainRideIdentity
from app.services.ride_effort_policy import RideEffortPolicy
from app.services.ride_processor import RideProcessor
from app.services.reward_ftp import RewardFtpSnapshot
from app.services.threshold_release_planner import THRESHOLD_PROVISIONAL_HOLD_POLICY


RIDE_ID = UUID("11111111-1111-4111-8111-111111111111")
USER_ID = UUID("22222222-2222-4222-8222-222222222222")
STARTED_AT = datetime(2026, 8, 24, 15, 0, tzinfo=timezone.utc)
COMPLETED_AT = datetime(2026, 8, 24, 16, 0, tzinfo=timezone.utc)


def _metrics() -> SimpleNamespace:
    return SimpleNamespace(
        tss=100.0,
        normalized_power_w=200,
        normalized_power_raw_w=200.0,
        normalized_power_duration_s=3600,
        avg_power_w=190,
        avg_hr_bpm=None,
        metrics_version="workout_parse_metrics_v1",
        moving_time_sec=3600,
        duration_sec=3600,
        power_sample_count=3600,
        power_sample_coverage_bps=10_000,
        heart_rate_sample_count=0,
        heart_rate_sample_coverage_bps=0,
    )


def _effort_policy() -> RideEffortPolicy:
    return RideEffortPolicy(
        effort_evidence_tier="power_verified",
        reward_policy="rewardable",
        estimated_cal=100,
        rewardable_cal=100,
        tributable_cal=100,
        estimated_cal_base_units=100_000_000_000,
        rewardable_cal_base_units=100_000_000_000,
        tributable_cal_base_units=100_000_000_000,
    )


@pytest.mark.asyncio
async def test_network_default_freezes_zero_parent_and_durable_hold() -> None:
    processor = object.__new__(RideProcessor)
    processor.ride_economic_repository = SimpleNamespace(get_effort_trim_basis=AsyncMock(return_value={"frozen":None,"covered_spans_ms":[],"covered_completion_windows":[]}))
    candidate_step = SimpleNamespace(
        pattern_id=UUID("33333333-3333-4333-8333-333333333333"),
        vault_id=7,
        vault_signature="07" * 32,
        completion_time_s=420,
        completed_at=COMPLETED_AT,
        exact_tribute_base_units=10_000_000_000,
        intensity_bps=12_500,
        completion_evidence_hash=b"\x55" * 32,
        completion_evidence_version=2,
        segment_start_offset_s=60,
        segment_end_offset_s=480,
        segment_np_w=250,
        segment_np_milliwatts=250_000,
        segment_np_duration_s=420,
        segment_power_sample_count=420,
        segment_power_coverage_bps=10_000,
        segment_power_metrics_version="workout_parse_metrics_v1",
        tribute_weight=0,
        climb_distance_m=1200,
        climb_vert_m=90,
    )
    processor.climb_economy_processor = SimpleNamespace(
        build_completion_plan=AsyncMock(
            return_value=([candidate_step], [{"vault_id": 7, "cal_tribute": 0}])
        )
    )
    frozen = {
        "plan_evidence_hash_hex": "34" * 32,
        "state": "planned",
    }
    processor.ride_economic_coordinator = SimpleNamespace(
        freeze_plan=AsyncMock(return_value=frozen)
    )
    pattern_results = SimpleNamespace(climb_patterns=[object()], vault_allocations=[])

    result, allocations, _, _ = await processor._freeze_ride_economic_plan(
        effort_spans_ms=[(int(STARTED_AT.timestamp()*1000),int(COMPLETED_AT.timestamp()*1000))],
        load_native_activity=AsyncMock(side_effect=AssertionError("untrimmed reload")),
        ride_id=RIDE_ID,
        user_id=USER_ID,
        user_wallet="11111111111111111111111111111111",
        identity=OnchainRideIdentity(
            ride_hash=b"\x12" * 32,
            attestation_commitment=b"\x23" * 32,
            parser_version=5,
            source_kind=1,
        ),
        effort_policy=_effort_policy(),
        economic_metrics=_metrics(),
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
        total_tss=100,
        total_distance_m=40_000,
        total_vert_m=500,
        total_ride_duration_s=3600,
        reward_ftp_snapshot=RewardFtpSnapshot.network_default(),
        pattern_results=pattern_results,
        tile_samples=[],
        raw_climb_samples=[],
    )

    assert result == frozen
    assert allocations == []
    draft = processor.ride_economic_coordinator.freeze_plan.await_args.args[0]
    assert draft.reward_policy == THRESHOLD_PROVISIONAL_HOLD_POLICY
    assert draft.total_tss == 0
    assert draft.exact_cal_base_units == 0
    assert draft.completion_steps == []
    hold_evidence = draft.threshold_hold_evidence
    assert hold_evidence is not None
    assert hold_evidence["metrics"]["normalized_power_raw_w"] == 200.0
    serialized = str(hold_evidence)
    assert "exact_cal_base_units" not in serialized
    assert "intensity_bps" not in serialized


@pytest.mark.asyncio
async def test_invalid_hold_evidence_fails_before_zero_parent_is_frozen(monkeypatch) -> None:
    processor = object.__new__(RideProcessor)
    processor.ride_economic_repository = SimpleNamespace(get_effort_trim_basis=AsyncMock(return_value={"frozen":None,"covered_spans_ms":[],"covered_completion_windows":[]}))
    processor.climb_economy_processor = SimpleNamespace(
        build_completion_plan=AsyncMock(return_value=([], []))
    )
    processor.ride_economic_coordinator = SimpleNamespace(
        freeze_plan=AsyncMock(return_value={"state": "planned"})
    )
    processor.ride_economic_repository = SimpleNamespace(
        get_effort_trim_basis=AsyncMock(return_value={"frozen":None,"covered_spans_ms":[],"covered_completion_windows":[]}),
        register_threshold_provisional_hold=AsyncMock()
    )
    monkeypatch.setattr(
        "app.services.ride_processor.build_threshold_hold_evidence",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("raw NP absent")),
    )

    with pytest.raises(ValueError, match="raw NP absent"):
        await processor._freeze_ride_economic_plan(
        effort_spans_ms=[(int(STARTED_AT.timestamp()*1000),int(COMPLETED_AT.timestamp()*1000))],
        load_native_activity=AsyncMock(side_effect=AssertionError("untrimmed reload")),
            ride_id=RIDE_ID,
            user_id=USER_ID,
            user_wallet="11111111111111111111111111111111",
            identity=OnchainRideIdentity(
                ride_hash=b"\x12" * 32,
                attestation_commitment=b"\x23" * 32,
                parser_version=5,
                source_kind=1,
            ),
            effort_policy=_effort_policy(),
            economic_metrics=_metrics(),
            started_at=STARTED_AT,
            completed_at=COMPLETED_AT,
            total_tss=100,
            total_distance_m=40_000,
            total_vert_m=500,
            total_ride_duration_s=3600,
            reward_ftp_snapshot=RewardFtpSnapshot.network_default(),
            pattern_results=SimpleNamespace(climb_patterns=[], vault_allocations=[]),
            tile_samples=[],
            raw_climb_samples=[],
        )

    processor.ride_economic_coordinator.freeze_plan.assert_not_awaited()
