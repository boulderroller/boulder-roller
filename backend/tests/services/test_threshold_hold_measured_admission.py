"""Local admission/release composition with real parser and economic builders.

Only external climb matching, time validation, and persistence are replaced.
No database, provider, or chain transaction is performed by these tests.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from solders.pubkey import Pubkey

from app.services.climb_economy_processor import ClimbEconomyProcessor
from app.services.reward_ftp import REWARD_FTP_POLICY_VERSION, RewardFtpSnapshot
from app.services.ride_attester import OnchainRideIdentity
from app.services.ride_economic_coordinator import RideEconomicCoordinator
from app.services.ride_effort_policy import build_ride_effort_policy
from app.services.ride_executor import RideExecutor
from app.services.ride_processor import RideProcessor
from app.services.threshold_release_executor import ThresholdReleaseExecutor
from app.services.threshold_release_planner import (
    THRESHOLD_PROVISIONAL_HOLD_POLICY,
    ThresholdReleasePlanner,
)


RIDE_ID = UUID("11111111-1111-4111-8111-111111111111")
USER_ID = UUID("22222222-2222-4222-8222-222222222222")
PATTERN_ID = UUID("33333333-3333-4333-8333-333333333333")
AUTHORITY_ID = "44444444-4444-4444-8444-444444444444"
STARTED_AT = datetime(2026, 8, 24, 15, 0, tzinfo=timezone.utc)
COMPLETED_AT = datetime(2026, 8, 24, 16, 0, tzinfo=timezone.utc)
WALLET = "11111111111111111111111111111111"


def _config() -> SimpleNamespace:
    return SimpleNamespace(program_id=Pubkey.from_bytes(b"\x77" * 32))


def _established_threshold() -> RewardFtpSnapshot:
    return RewardFtpSnapshot(
        ftp_w=250,
        source="derived_eftp",
        policy_version=REWARD_FTP_POLICY_VERSION,
        authority_id=AUTHORITY_ID,
    )


def _climb() -> SimpleNamespace:
    return SimpleNamespace(
        id=PATTERN_ID,
        indexed_vault_id=7,
        economic_eligible=True,
        time_s=300,
        distance_m=1200,
        vert_m=90,
        start_time_offset_s=60,
        end_time_offset_s=359,
        canon_vault_binding={
            "id": 7,
            "signature_hex": "07" * 32,
            "canon_binding_status": "active",
            "canon_activation_status": "finalized",
            "canon_climb_id": str(PATTERN_ID),
            "canon_id": str(USER_ID),
            "canon_version": 1,
            "canonical_profile_hash_hex": "ab" * 32,
            "expected_vault_activation_pda": "local-vault-activation",
            "vault_activation_pda": "local-vault-activation",
            "constructor_evidence_verified": True,
            "constructor_evidence_hash": "cd" * 32,
            "vault_activation_is_active": True,
            "vault_activation_seed_generation": 2,
            "vault_activation_seed_completions_written": 0,
            "vault_activation_leaderboard_seeded": True,
            "vault_activation_matched_users": 0,
            "vault_activation_matched_completions": 0,
            "vault_activation_created_at": 100,
            "vault_activation_activated_at": 100,
            "vault_activation_last_seed_at": 100,
            "vault_activation_seed_cutoff_at": 100,
            "vault_activation_evidence_hash": "cd" * 32,
        },
    )


def _processor() -> tuple[RideProcessor, SimpleNamespace]:
    repository = SimpleNamespace(
        get_effort_trim_basis=AsyncMock(return_value={"frozen":None,"covered_spans_ms":[],"covered_completion_windows":[]}),
        freeze_plan=AsyncMock(side_effect=lambda **payload: deepcopy(payload))
    )
    executor = RideExecutor(config_loader=_config)
    climbs = object.__new__(ClimbEconomyProcessor)
    climbs.match_climbs_to_vault = AsyncMock(return_value=(0, []))
    climbs.vault_repo = SimpleNamespace(
        validate_climb_time=AsyncMock(return_value={"is_valid": True})
    )
    climbs.ride_executor = executor
    processor = object.__new__(RideProcessor)
    processor.ride_economic_repository = repository
    processor.climb_economy_processor = climbs
    processor.ride_economic_coordinator = RideEconomicCoordinator(
        repository=repository, executor=executor
    )
    return processor, repository


async def _admit(
    processor: RideProcessor,
    *,
    threshold: RewardFtpSnapshot,
    ride_tss: float | None = None,
) -> tuple[dict, list, SimpleNamespace]:
    metrics = SimpleNamespace(
        tss=(100.0 if threshold.ftp_w == 200 else 64.0)
        if ride_tss is None else ride_tss,
        normalized_power_w=200,
        normalized_power_raw_w=200.0,
        normalized_power_duration_s=3600,
        avg_power_w=200,
        avg_hr_bpm=None,
        metrics_version="workout_parse_metrics_v1",
        moving_time_sec=3600,
        duration_sec=3600,
        power_sample_count=3600,
        power_sample_coverage_bps=10_000,
        heart_rate_sample_count=0,
        heart_rate_sample_coverage_bps=0,
    )
    patterns = SimpleNamespace(climb_patterns=[_climb()], vault_allocations=[])
    frozen, allocations, _, _ = await processor._freeze_ride_economic_plan(
        effort_spans_ms=[(int(STARTED_AT.timestamp()*1000),int(COMPLETED_AT.timestamp()*1000))],
        load_native_activity=AsyncMock(side_effect=AssertionError("untrimmed reload")),
        ride_id=RIDE_ID,
        user_id=USER_ID,
        user_wallet=WALLET,
        identity=OnchainRideIdentity(
            ride_hash=b"\x12" * 32,
            attestation_commitment=b"\x23" * 32,
            parser_version=5,
            source_kind=1,
        ),
        effort_policy=build_ride_effort_policy(
            metrics, started_at=STARTED_AT, completed_at=COMPLETED_AT,
            now=COMPLETED_AT,
        ),
        economic_metrics=metrics,
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
        total_tss=int(metrics.tss),
        total_distance_m=40_000,
        total_vert_m=500,
        total_ride_duration_s=3600,
        reward_ftp_snapshot=threshold,
        pattern_results=patterns,
        tile_samples=[],
        raw_climb_samples=[{"t": t, "power_w": 200} for t in range(3600)],
    )
    return frozen, allocations, patterns


@pytest.mark.asyncio
async def test_powered_climb_is_held_without_payment_then_repriced_at_release() -> None:
    processor, repository = _processor()
    frozen, allocations, patterns = await _admit(
        processor, threshold=RewardFtpSnapshot.network_default(),
    )

    repository.freeze_plan.assert_awaited_once()
    assert allocations == patterns.vault_allocations == []
    assert frozen["steps"] == []
    parent = frozen["plan"]
    assert parent["reward_policy"] == THRESHOLD_PROVISIONAL_HOLD_POLICY
    assert parent["total_tss"] == parent["exact_cal_base_units"] == 0
    assert parent["exact_tribute_budget_base_units"] == 0
    assert parent["exact_tribute_base_units"] == 0
    assert parent["reward_ftp_w"] == 200
    evidence = frozen["threshold_hold"]["hold_evidence"]
    assert evidence["metrics"]["normalized_power_raw_w"] == 200.0
    segment = evidence["completion_steps"][0]
    assert segment["segment_np_milliwatts"] == 200_000
    assert segment["segment_np_duration_s"] == 300
    assert segment["segment_power_sample_count"] == 300
    assert segment["segment_power_coverage_bps"] == 10_000
    assert segment["segment_start_offset_s"] == 60
    assert segment["segment_end_offset_s"] == 359
    assert not {"exact_tribute_base_units", "intensity_bps",
                "completion_evidence_hash_hex"}.intersection(segment)
    assert not {"tss", "exact_cal_base_units"}.intersection(evidence["metrics"])

    original = deepcopy(frozen)
    claim = {
        "batch_item_id": "55555555-5555-4555-8555-555555555555",
        "ride_id": str(RIDE_ID), "user_id": str(USER_ID), "wallet": WALLET,
        "ride_hash_hex": "12" * 32,
        "admitted_at": COMPLETED_AT.isoformat(),
        "established_at": "2026-08-31T12:00:00+00:00",
        "reward_ftp_authority_id": AUTHORITY_ID,
        "reward_ftp_authority_evidence_hash_hex": "34" * 32,
        "reward_ftp_w": 250, "reward_ftp_source": "derived_eftp",
        "reward_ftp_policy_version": REWARD_FTP_POLICY_VERSION,
        "hold_evidence": evidence,
    }
    planner = ThresholdReleasePlanner(
        repository=repository, executor=ThresholdReleaseExecutor(config_loader=_config)
    )
    release, steps = planner._build_snapshot(claim)
    assert release["exact_cal_base_units"] == 64_000_000_000
    assert release["exact_tribute_budget_base_units"] == 5_333_333_333
    assert steps[0]["exact_tribute_base_units"] == 5_333_333_333
    assert steps[0]["completion_evidence_version"] == 3
    assert frozen == original

    # Release must independently enforce its ceiling against retained evidence.
    inconsistent_claim = deepcopy(claim)
    inconsistent_segment = inconsistent_claim["hold_evidence"]["completion_steps"][0]
    inconsistent_segment["segment_np_w"] = 1_000
    inconsistent_segment["segment_np_milliwatts"] = 1_000_000
    with pytest.raises(ValueError, match="measured climb TSS exceeds full attested CAL"):
        planner._build_snapshot(inconsistent_claim)


@pytest.mark.asyncio
async def test_established_powered_climb_keeps_ordinary_payment() -> None:
    processor, repository = _processor()
    frozen, allocations, patterns = await _admit(
        processor, threshold=_established_threshold()
    )
    repository.freeze_plan.assert_awaited_once()
    assert "threshold_hold" not in frozen
    assert frozen["plan"]["exact_cal_base_units"] == 64_000_000_000
    assert frozen["plan"]["exact_tribute_base_units"] == 5_333_333_333
    assert frozen["steps"][0]["completion_evidence_version"] == 2
    assert allocations == patterns.vault_allocations
    assert allocations[0]["cal_tribute"] == 5_333_333_333


@pytest.mark.asyncio
@pytest.mark.parametrize("held", [False, True])
async def test_admission_rejects_climb_above_its_measured_ride_budget(held: bool) -> None:
    processor, repository = _processor()
    with pytest.raises(ValueError, match="measured climb TSS exceeds full attested CAL"):
        await _admit(
            processor,
            threshold=RewardFtpSnapshot.network_default() if held else _established_threshold(),
            ride_tss=1.0,
        )
    repository.freeze_plan.assert_not_awaited()
