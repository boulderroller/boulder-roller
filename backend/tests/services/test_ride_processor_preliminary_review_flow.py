from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ride_processor import (
    AUTHORITATIVE_METRICS_VERSION,
    CAL_DECIMALS_MULTIPLIER,
    PRE_ECONOMY_REVIEW_REASON,
    ROUTE_ESTIMATE_ECONOMIC_REVIEW_REASON,
    RideProcessor,
)
from app.services.ride_attester import (
    MISSING_PRELIMINARY_ATTESTATION_REVIEW_REASON,
    OnchainRideIdentity,
    PreliminaryAttestationCheck,
    RideAttestationPreparation,
    evaluate_preliminary_attestation,
)
from app.services.ride_provenance_policy import (
    DUPLICATE_PROVIDER_ACTIVITY_REVIEW_REASON,
    MISSING_PROVIDER_ACTIVITY_REVIEW_REASON,
    PROVENANCE_TIER_FIRST_PARTY_RECORDED,
    PROVENANCE_TIER_MANUAL_FILE_UPLOAD,
    PROVENANCE_TIER_TRUSTED_PROVIDER_SYNC,
    build_ride_provenance_diagnostics,
)
from app.services.ride_economic_coordinator import RideEconomicOutcome
from app.services.reward_ftp import RewardFtpSnapshot
from app.services.reward_threshold import (
    ThresholdEffortEvidence,
    ThresholdSourceEvidence,
)


@pytest.mark.parametrize("tss", [64.1, "64.1", Decimal("64.1")])
def test_resume_preserves_decimal_cal_base_units(tss) -> None:
    from app.services.ride_processor import _frozen_ride_effort_policy

    policy = _frozen_ride_effort_policy({
        "economic_tss": tss,
        "effort_evidence_tier": "power_verified",
        "reward_policy": "rewardable",
        "estimated_cal": 64,
        "rewardable_cal": 64,
        "tributable_cal": 64,
    })
    assert policy is not None
    assert policy.estimated_cal_base_units == 64_100_000_000
    assert policy.rewardable_cal_base_units == 64_100_000_000
    assert policy.tributable_cal_base_units == 64_100_000_000


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ("legacy", "phase1"))
@pytest.mark.parametrize("ridden,total,tss", [(3600, 129600, 598.1), (738, 10001, 100.0)])
async def test_idle_padding_enters_review_without_changing_tss(phase: str, ridden: int, total: int, tss: float) -> None:
    ride_id = uuid4()
    started = datetime.now(timezone.utc) - timedelta(days=2)
    parsed = _parsed_ride(started, started + timedelta(seconds=total - 1), "idle.fit")
    parsed.records = [
        SimpleNamespace(
            timestamp=started + timedelta(seconds=second),
            power_w=250 if second < ridden else 0,
            speed_mps=8.0 if second < ridden else 0.0,
            cadence_rpm=85 if second < ridden else 0,
        )
        for second in range(total)
    ]
    metrics = _sensor_backed_metrics(tss=tss)
    metrics.duration_sec = total - 1
    metrics.moving_time_sec = metrics.normalized_power_duration_s = total
    metrics.power_sample_count = total
    ctx = _processor_context(
        ride_id=ride_id,
        ride_row={"id": str(ride_id)},
        preliminary_check=PreliminaryAttestationCheck(
            preliminary_ride_hash_hex=None, preliminary_parser_version=None,
            canonical_match=None, review_reason=None, requires_review=False,
        ),
        parsed_ride=parsed, metrics=metrics, identity=_identity(),
    )
    ctx.ride_repo.update_phase_status = AsyncMock()
    ctx.processor.analytics_service.calculate_threshold_ride_metrics = AsyncMock(
        return_value=(metrics, {})
    )
    method = ctx.processor.process_ride if phase == "legacy" else ctx.processor.process_phase1_core
    await method(
        ride_id=ride_id, user_id=uuid4(), file_data_b64="ZmFrZQ==",
        file_type="fit", file_bytes=b"fake",
    )
    if phase == "legacy":
        saved = ctx.ride_projection_store.update_ride_complete.await_args.kwargs
        assert saved["status"] == "under_review"
        policy = saved["effort_policy"]
        assert policy.rewardable_cal_base_units == policy.tributable_cal_base_units == 0
        ctx.ride_economic_coordinator.freeze_plan.assert_not_awaited()
        ctx.ride_economic_coordinator.execute.assert_not_awaited()
        ctx.ride_executor.credit_cal.assert_not_awaited()
    else:
        saved = ctx.ride_repo.update_phase_status.await_args.kwargs
        assert saved["tss"] == tss
        assert saved["economic_tss"] == tss
        assert saved["rewardable_cal"] == saved["tributable_cal"] == 0
        assert saved["reward_policy"] == "manual_review"
    assert saved["review_reason"] == "implausible_stationary_recording"
    admission_updates = ctx.ride_repo.update_ride_metadata.await_args_list[0].args[1]
    assert admission_updates["review_reason"] == "implausible_stationary_recording"
    evidence = admission_updates["import_diagnostics"]["idle_recording_evidence"]
    assert evidence["stationary_share_bps"] >= 9262
    assert evidence["review_share_bps"] == 9262
    assert evidence["policy_version"] == "stationary_recording_review_v2"
    if phase == "phase1":
        persisted = {"id": str(ride_id), "processing_status": "metrics_ready", **saved}
        ctx.ride_repo.get_ride_for_phase2 = AsyncMock(return_value=persisted)
        ctx.ride_repo.get_gps_track = AsyncMock(return_value=[])
        ctx.ride_projection_store.build_sensor_lookup = AsyncMock(return_value=None)
        enriched = await ctx.processor.process_phase2_enrichment(ride_id=ride_id, user_id=uuid4())
        assert ctx.ride_repo.update_phase_status.await_args.kwargs["processing_status"] == "under_review"
        assert enriched["cal_earned"] == 0
        ctx.ride_economic_coordinator.freeze_plan.assert_not_awaited()
        persisted.update(ctx.ride_repo.update_phase_status.await_args.kwargs)
        ctx.ride_repo.get_ride_for_phase3 = AsyncMock(return_value=persisted)
        ctx.ride_economic_repository.get_plan = AsyncMock(return_value=None)
        ctx.ride_projection_store.get_pattern_results_from_db = AsyncMock(return_value=None)
        ctx.processor._emit_ride_finalized_notification = AsyncMock()
        completed = await ctx.processor.process_phase3_rewards(ride_id=ride_id, user_id=uuid4())
        assert completed["status"] == "under_review"
        assert completed["cal_earned"] == 0
        ctx.ride_economic_coordinator.execute.assert_not_awaited()




@pytest.fixture(autouse=True)
def _effort_trim_seam(monkeypatch):
    from app.services.ride_effort_trim import epoch_ms
    monkeypatch.setattr("app.services.ride_processor.effort_spans_ms_rust", lambda ride: [(epoch_ms(ride.started_at), epoch_ms(ride.completed_at))])
    monkeypatch.setattr("app.repositories.ride_economic.RideEconomicRepository.get_effort_trim_basis", AsyncMock(return_value={"frozen": None, "covered_spans_ms": [], "covered_completion_windows": []}))


@pytest.fixture(autouse=True)
def _bind_network_default_reward_ftp(monkeypatch):
    monkeypatch.setattr(
        RideProcessor,
        "_bind_reward_ftp_snapshot",
        AsyncMock(return_value=RewardFtpSnapshot.network_default()),
    )


def _identity(ride_hash_hex: str = "ab" * 32) -> OnchainRideIdentity:
    ride_hash = bytes.fromhex(ride_hash_hex)
    return OnchainRideIdentity(
        ride_hash=ride_hash,
        attestation_commitment=ride_hash,
        parser_version=1,
        source_kind=1,
    )


def _sensor_backed_metrics(tss: float = 84.0) -> SimpleNamespace:
    return SimpleNamespace(
        duration_sec=300,
        moving_time_sec=300,
        metrics_version=AUTHORITATIVE_METRICS_VERSION,
        power_sample_count=300,
        power_sample_coverage_bps=10_000,
        heart_rate_sample_count=300,
        heart_rate_sample_coverage_bps=10_000,
        tss=tss,
        kcals=500.0,
        distance_m=12000.0,
        elevation_gain_m=300.0,
        avg_power_w=220.0,
        max_power_w=750.0,
        normalized_power_w=235.0,
        normalized_power_raw_w=235.0,
        normalized_power_duration_s=300,
        avg_hr_bpm=150.0,
        max_hr_bpm=180.0,
        avg_speed_mps=8.0,
        avg_cadence_rpm=88.0,
    )


def _parsed_ride(started_at: datetime, completed_at: datetime, file_name: str) -> SimpleNamespace:
    return SimpleNamespace(
        records=[SimpleNamespace(timestamp=started_at, lat=39.95, lon=-75.16)],
        gps_track=[],
        started_at=started_at,
        completed_at=completed_at,
        device_name="Test Head Unit",
        file_name=file_name,
    )


def _configure_empty_canon_evidence(projection_store: MagicMock) -> None:
    evidence = MagicMock()
    evidence.raw_samples.return_value = []
    evidence.record_points.return_value = []
    projection_store.build_canon_traversal_evidence.return_value = evidence
    projection_store.store_canon_traversal_evidence = AsyncMock()
    projection_store.load_canon_traversal_evidence = AsyncMock(return_value=None)


def _configure_establishing_threshold(ride_repo: MagicMock) -> None:
    ride_repo.get_reward_threshold_rider_projection = AsyncMock(
        return_value={
            "state": "establishing",
            "current_w": None,
            "established_at": None,
            "last_raised_at": None,
            "pending_monday": None,
            "training_denominator": {
                "watts": 200,
                "kind": "network_placeholder",
                "provisional": True,
            },
        }
    )


def _processor_context(
    *,
    ride_id,
    ride_row: dict,
    preliminary_check: PreliminaryAttestationCheck,
    parsed_ride: SimpleNamespace,
    metrics: SimpleNamespace,
    identity: OnchainRideIdentity,
) -> SimpleNamespace:
    ride_repo = MagicMock()
    _configure_establishing_threshold(ride_repo)
    ride_repo.update_ride_status = AsyncMock()
    ride_repo.get_ride = AsyncMock(return_value=ride_row)
    ride_repo.store_gps_points = AsyncMock()
    ride_repo.update_ride_metadata = AsyncMock()
    ride_repo.register_reward_threshold_effort = AsyncMock(
        return_value={"disposition": "display_only"}
    )

    user_repo = MagicMock()
    user_repo.get_user_wallet = AsyncMock(return_value="wallet-1")
    user_repo.get_user_stats = AsyncMock(return_value={"total_tss": 1000.0})

    ride_executor = MagicMock()
    ride_executor.record_ride_attestation = AsyncMock(
        return_value=SimpleNamespace(
            reference="ride-attestation-ref",
            pda="RideAttestation111111111111111111111111111111",
            tx_signature="ride-attestation-tx",
            attested_at="2026-05-10T12:05:00+00:00",
        )
    )
    ride_executor.credit_cal = AsyncMock(return_value="credit-cal-tx")
    ride_executor.record_climb_completion = AsyncMock()
    ride_economic_coordinator = MagicMock()
    ride_economic_coordinator.freeze_plan = AsyncMock(
        return_value={
            "ride_id": str(ride_id),
            "state": "planned",
            "steps": [],
            "plan_evidence_hash_hex": "34" * 32,
        }
    )
    ride_economic_coordinator.execute = AsyncMock(
        return_value=RideEconomicOutcome(
            status="complete",
            state="complete",
            durable_checkpoint=True,
            ride_attestation_pda="RideAttestation111111111111111111111111111111",
            ride_attestation_tx_signature="ride-attestation-tx",
            ride_attested_at="2026-05-10T12:05:00+00:00",
            cal_tx_signature="credit-cal-tx",
        )
    )

    ride_attester = MagicMock()
    ride_attester.calculate_metrics.return_value = _sensor_backed_metrics(tss=metrics.tss)
    ride_attester.prepare_ride.return_value = RideAttestationPreparation(
        onchain_identity=identity,
        preliminary_check=preliminary_check,
        parsed_ride=parsed_ride,
        metrics=metrics,
    )

    ride_projection_store = MagicMock()
    _configure_empty_canon_evidence(ride_projection_store)
    ride_projection_store.capture_profile_snapshot = AsyncMock()
    ride_projection_store.store_activity_streams = AsyncMock()
    ride_projection_store.gps_track_to_dicts = MagicMock(return_value=[])
    ride_projection_store.records_to_dicts = MagicMock(return_value=[])
    ride_projection_store.store_pattern_results = AsyncMock()
    ride_projection_store.update_ride_complete = AsyncMock()
    terminal_projector = MagicMock()
    terminal_projector.project = AsyncMock(
        return_value=SimpleNamespace(
            status="projected",
            durable_checkpoint=True,
            cal_earned=0,
            error=None,
        )
    )
    ride_economic_repository = MagicMock()
    ride_economic_repository.get_effort_trim_basis = AsyncMock(return_value={"frozen": None, "covered_spans_ms": [], "covered_completion_windows": []})
    ride_economic_repository.register_threshold_provisional_hold = AsyncMock(
        return_value={"hold_id": str(uuid4())}
    )

    with patch("app.services.ride_processor.get_supabase_client", return_value=MagicMock()):
        processor = RideProcessor(
            ride_repo=ride_repo,
            user_repo=user_repo,
            tile_repo=MagicMock(),
            token_repo=MagicMock(),
            pattern_repo=MagicMock(),
            achievement_repo=MagicMock(),
            vault_repo=MagicMock(),
            fitness_repo=MagicMock(),
            notification_repo=MagicMock(),
            ride_attester=ride_attester,
            ride_projection_store=ride_projection_store,
            ride_executor=ride_executor,
            ride_economic_repository=ride_economic_repository,
            ride_economic_coordinator=ride_economic_coordinator,
            ride_economic_terminal_projector=terminal_projector,
        )

    processor._publish_nats_event = AsyncMock()
    processor.achievement_detector.detect_achievements = AsyncMock(return_value=[])
    processor.analytics_service.update_daily_aggregates = AsyncMock()

    return SimpleNamespace(
        processor=processor,
        ride_repo=ride_repo,
        user_repo=user_repo,
        ride_executor=ride_executor,
        ride_economic_coordinator=ride_economic_coordinator,
        ride_attester=ride_attester,
        ride_projection_store=ride_projection_store,
        terminal_projector=terminal_projector,
        ride_economic_repository=ride_economic_repository,
        ride_id=ride_id,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("candidate_disposition", "expected_review_reason"),
    [
        ("pending_establishment", None),
        ("invalid_fit_review", "reward_threshold_invalid_fit_review"),
        ("below_bounds_review", "reward_threshold_below_bounds_review"),
        ("above_bounds_review", "reward_threshold_above_bounds_review"),
    ],
)
async def test_phase1_core_persists_canonical_identity_before_enrichment_or_rewards(
    candidate_disposition: str,
    expected_review_reason: str | None,
    monkeypatch,
) -> None:
    training = AsyncMock(side_effect=RuntimeError("training unavailable"))
    monkeypatch.setattr("app.services.training_metrics.TrainingMetricsService.score", training)
    ride_id = uuid4()
    user_id = uuid4()
    started_at = datetime.now(timezone.utc) - timedelta(hours=2)
    completed_at = started_at + timedelta(minutes=45)
    identity = _identity("ef" * 32)
    preliminary_check = PreliminaryAttestationCheck(
        preliminary_ride_hash_hex="ef" * 32,
        preliminary_parser_version=1,
        canonical_match=True,
        review_reason=None,
        requires_review=False,
    )
    metrics = _sensor_backed_metrics(tss=42.0)
    parsed_ride = _parsed_ride(started_at, completed_at, "phase1.fit")
    threshold_call_order: list[str] = []

    async def record_threshold_metadata(*args, **kwargs) -> None:
        threshold_call_order.append("source_metadata")

    async def record_threshold_candidate(*args, **kwargs) -> dict[str, str]:
        threshold_call_order.append("candidate")
        return {"disposition": candidate_disposition}

    ride_repo = MagicMock()
    ride_repo.update_ride_status = AsyncMock()
    ride_repo.update_ride_metadata = AsyncMock(side_effect=record_threshold_metadata)
    ride_repo.get_ride = AsyncMock(
        return_value={
            "id": str(ride_id),
            "preliminary_ride_hash_hex": "ef" * 32,
            "preliminary_parser_version": 1,
        }
    )
    ride_repo.store_gps_points = AsyncMock()
    ride_repo.update_phase_status = AsyncMock()
    ride_repo.register_reward_threshold_effort = AsyncMock(
        side_effect=record_threshold_candidate
    )
    ride_repo.get_reward_threshold_rider_projection = AsyncMock(
        return_value={
            "state": "establishing",
            "current_w": None,
            "established_at": None,
            "last_raised_at": None,
            "pending_monday": None,
            "training_denominator": {
                "watts": 200,
                "kind": "network_placeholder",
                "provisional": True,
            },
        }
    )

    user_repo = MagicMock()
    user_repo.get_user_wallet = AsyncMock(return_value="wallet-1")

    ride_attester = MagicMock()
    ride_attester.prepare_ride.return_value = RideAttestationPreparation(
        onchain_identity=identity,
        preliminary_check=preliminary_check,
        parsed_ride=parsed_ride,
        metrics=metrics,
    )
    ride_attester.calculate_metrics.return_value = _sensor_backed_metrics(tss=42.0)

    ride_projection_store = MagicMock()
    _configure_empty_canon_evidence(ride_projection_store)
    ride_projection_store.capture_profile_snapshot = AsyncMock()
    ride_projection_store.store_activity_streams = AsyncMock()
    ride_projection_store.gps_track_to_dicts = MagicMock(return_value=[])

    with patch("app.services.ride_processor.get_supabase_client", return_value=MagicMock()):
        processor = RideProcessor(
            ride_repo=ride_repo,
            user_repo=user_repo,
            tile_repo=MagicMock(),
            token_repo=MagicMock(),
            pattern_repo=MagicMock(),
            achievement_repo=MagicMock(),
            vault_repo=MagicMock(),
            fitness_repo=MagicMock(),
            notification_repo=MagicMock(),
            ride_attester=ride_attester,
            ride_projection_store=ride_projection_store,
        )
    processor._publish_nats_event = AsyncMock()
    capture_weather = AsyncMock()
    monkeypatch.setattr("app.services.ride_processor.capture_ride_weather", capture_weather)
    source_id = "11111111-1111-4111-8111-111111111111"
    threshold_evidence = ThresholdEffortEvidence(
        best_180s_w=350.0,
        best_420s_w=292.857,
        best_900s_w=270.0,
        source=ThresholdSourceEvidence(
            recording_source="br_ios",
            power_source_ids=(source_id,),
            identity_complete=True,
            eligibility_reason="eligible",
        )
    )

    with patch(
        "app.services.ride_processor.threshold_effort_evidence_or_empty",
        return_value=threshold_evidence,
    ):
        result = await processor.process_phase1_core(
            ride_id=ride_id,
            file_data_b64="ZmFrZQ==",
            file_type="fit",
            user_id=user_id,
            file_bytes=b"fake",
        )

    assert result["status"] == "metrics_ready"
    assert result["ride_hash_hex"] == "ef" * 32
    ride_attester.prepare_ride.assert_called_once()
    ride_repo.update_phase_status.assert_awaited_once()
    kwargs = ride_repo.update_phase_status.await_args.kwargs
    assert kwargs["phase"] == 1
    assert kwargs["ride_hash_hex"] == "ef" * 32
    assert kwargs["attestation_commitment_hex"] == "ef" * 32
    assert kwargs["ride_parser_version"] == 1
    assert kwargs["preliminary_ride_hash_hex"] == "ef" * 32
    assert kwargs["preliminary_parser_version"] == 1
    assert kwargs["canonical_match"] is True
    assert kwargs["review_reason"] == expected_review_reason
    if expected_review_reason is not None:
        assert kwargs["reward_policy"] == "manual_review"
        assert kwargs["rewardable_cal"] == 0
    assert kwargs["threshold_recording_source"] == "br_ios"
    assert kwargs["threshold_power_source_id"] == source_id
    assert kwargs["threshold_source_identity_complete"] is True
    assert threshold_call_order == ["source_metadata", "candidate"]
    # The production (phased) path records display weather, not just legacy.
    capture_weather.assert_awaited_once_with(ride_repo, ride_id, parsed_ride)
    training.assert_not_awaited()
    ride_repo.register_reward_threshold_effort.assert_awaited_once_with(
        ride_id=ride_id,
        best_180s_w=350.0,
        best_420s_w=292.857,
        best_900s_w=270.0,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("complete_policy", (True, False))
async def test_phase1_reprocess_uses_frozen_economic_snapshot_for_policy(
    complete_policy: bool,
) -> None:
    ride_id = uuid4()
    user_id = uuid4()
    started_at = datetime.now(timezone.utc) - timedelta(hours=2)
    completed_at = started_at + timedelta(minutes=45)
    ride_row = {
        "id": str(ride_id),
        "economic_tss": 84.0,
        "reward_ftp_w": 200,
        "reward_ftp_source": "network_default",
        "reward_ftp_authority_id": None,
        "reward_ftp_policy_version": "reward_ftp_policy_2026_08_24_threshold_v1",
        "threshold_source_evidence": {},
        "metrics_version": AUTHORITATIVE_METRICS_VERSION,
        "power_sample_count": 300,
        "power_sample_coverage_bps": 10_000,
        "moving_time_sec": 300,
        "normalized_power_w": 235.0,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "review_reason": None,
    }
    if complete_policy:
        ride_row.update(
            {
                "effort_evidence_tier": "power_verified",
                "reward_policy": "rewardable",
                "estimated_cal": 84,
                "rewardable_cal": 84,
                "tributable_cal": 84,
            }
        )
    context = _processor_context(
        ride_id=ride_id,
        ride_row=ride_row,
        preliminary_check=PreliminaryAttestationCheck(
            preliminary_ride_hash_hex="ac" * 32,
            preliminary_parser_version=1,
            canonical_match=True,
            review_reason=None,
            requires_review=False,
        ),
        parsed_ride=_parsed_ride(started_at, completed_at, "reprocess.fit"),
        metrics=_sensor_backed_metrics(tss=42.0),
        identity=_identity("ac" * 32),
    )
    # Reprocessing now sees a stationary recording; the existing admission wins.
    context.ride_attester.prepare_ride.return_value.parsed_ride.records = [
        SimpleNamespace(timestamp=started_at + timedelta(seconds=i),
                        speed_mps=0, power_w=0, cadence_rpm=0)
        for i in range(300)
    ]
    context.ride_repo.update_phase_status = AsyncMock()

    result = await context.processor.process_phase1_core(
        ride_id=ride_id,
        file_data_b64="ZmFrZQ==",
        file_type="fit",
        user_id=user_id,
        file_bytes=b"fake",
    )

    kwargs = context.ride_repo.update_phase_status.await_args.kwargs
    assert "economic_tss" not in kwargs
    assert "reward_ftp_w" not in kwargs
    assert "threshold_source_evidence" not in kwargs
    assert kwargs["estimated_cal"] == 84
    assert kwargs["rewardable_cal"] == 84
    assert kwargs["tributable_cal"] == 84
    assert result["economic_tss"] == 84.0
    assert result["effort_policy"]["rewardable_cal"] == 84


@pytest.mark.asyncio
async def test_legacy_reprocess_freezes_plan_from_stored_economics() -> None:
    ride_id = uuid4()
    user_id = uuid4()
    started_at = datetime.now(timezone.utc) - timedelta(hours=2)
    completed_at = started_at + timedelta(minutes=45)
    context = _processor_context(
        ride_id=ride_id,
        ride_row={
            "id": str(ride_id),
            "economic_tss": 84.0,
            "reward_ftp_w": 200,
            "reward_ftp_source": "network_default",
            "reward_ftp_authority_id": None,
            "reward_ftp_policy_version": "reward_ftp_policy_2026_08_24_threshold_v1",
            "threshold_source_evidence": {},
            "effort_evidence_tier": "power_verified",
            "reward_policy": "rewardable",
            "estimated_cal": 84,
            "rewardable_cal": 84,
            "tributable_cal": 84,
            "review_reason": None,
        },
        preliminary_check=PreliminaryAttestationCheck(
            preliminary_ride_hash_hex="ad" * 32,
            preliminary_parser_version=1,
            canonical_match=True,
            review_reason=None,
            requires_review=False,
        ),
        parsed_ride=_parsed_ride(started_at, completed_at, "legacy-reprocess.fit"),
        metrics=_sensor_backed_metrics(tss=42.0),
        identity=_identity("ad" * 32),
    )
    context.processor._bind_reward_ftp_snapshot = AsyncMock(return_value=RewardFtpSnapshot(
        ftp_w=200, source="derived_eftp", authority_id=str(uuid4()), policy_version="reward_ftp_policy_2026_08_24_threshold_v1"))
    context.terminal_projector.project = AsyncMock(
        return_value=SimpleNamespace(
            status="projected",
            durable_checkpoint=True,
            cal_earned=84,
            error=None,
        )
    )

    await context.processor.process_ride(
        ride_id=ride_id,
        file_data_b64="ZmFrZQ==",
        file_type="fit",
        user_id=user_id,
        file_bytes=b"fake",
    )

    frozen_draft = context.ride_economic_coordinator.freeze_plan.await_args.args[0]
    assert frozen_draft.total_tss == 84
    assert frozen_draft.exact_cal_base_units == 84 * CAL_DECIMALS_MULTIPLIER


@pytest.mark.asyncio
async def test_phase3_resumes_the_frozen_economic_plan() -> None:
    ride_id = uuid4()
    user_id = uuid4()
    completed_at = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=5)
    started_at = completed_at - timedelta(minutes=50)
    ride_hash_hex = "ba" * 32
    attestation_commitment_hex = "cd" * 32

    ride_repo = MagicMock()
    ride_repo.get_ride_for_phase3 = AsyncMock(
        return_value={
            "id": str(ride_id),
            "user_id": str(user_id),
            "processing_status": "enriched",
            "file_type": "tcx",
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "duration_sec": 3000,
            "distance_m": 9200.0,
            "elevation_gain_m": 422.0,
            "tss": 0.0,
            "kcals": 664.0,
            "avg_power_w": 232.0,
            "normalized_power_w": 232.0,
            "avg_hr_bpm": 151.0,
            "ride_hash_hex": ride_hash_hex,
            "attestation_commitment_hex": attestation_commitment_hex,
            "ride_parser_version": 7,
            "canonical_match": False,
            "review_reason": "mutable_policy_changed_after_freeze",
        }
    )
    ride_repo.update_phase_status = AsyncMock()

    user_repo = MagicMock()
    user_repo.get_user_wallet = AsyncMock(
        side_effect=RuntimeError("mutable wallet lookup must not run")
    )

    ride_executor = MagicMock()
    ride_economic_coordinator = MagicMock()
    ride_economic_coordinator.execute = AsyncMock(
        return_value=RideEconomicOutcome(
            status="complete",
            state="complete",
            durable_checkpoint=True,
            ride_attestation_pda="RideAttestation111111111111111111111111111111",
            ride_attestation_tx_signature="ride-attestation-tx",
            ride_attested_at="2026-06-12T22:00:00+00:00",
            cal_tx_signature="credit-cal-tx",
            completion_count=1,
        )
    )
    ride_economic_repository = MagicMock()
    ride_economic_repository.get_effort_trim_basis = AsyncMock(return_value={"frozen": None, "covered_spans_ms": [], "covered_completion_windows": []})
    ride_economic_repository.get_plan = AsyncMock(
        return_value={
            "wallet": "frozen-wallet-1",
            "exact_cal_base_units": 84 * CAL_DECIMALS_MULTIPLIER,
            "reward_policy": "rewardable",
            "review_reason": None,
            "state": "planned",
            "steps": [],
        }
    )
    terminal_projector = MagicMock()
    terminal_projector.project = AsyncMock(
        return_value=SimpleNamespace(
            status="projected",
            durable_checkpoint=True,
            cal_earned=84,
            error=None,
        )
    )

    ride_projection_store = MagicMock()
    _configure_empty_canon_evidence(ride_projection_store)
    ride_projection_store.get_pattern_results_from_db = AsyncMock(
        return_value=SimpleNamespace(climb_patterns=[SimpleNamespace()])
    )

    with patch("app.services.ride_processor.get_supabase_client", return_value=MagicMock()):
        processor = RideProcessor(
            ride_repo=ride_repo,
            user_repo=user_repo,
            tile_repo=MagicMock(),
            token_repo=MagicMock(),
            pattern_repo=MagicMock(),
            achievement_repo=MagicMock(),
            vault_repo=MagicMock(),
            fitness_repo=MagicMock(),
            notification_repo=MagicMock(),
            ride_projection_store=ride_projection_store,
            ride_executor=ride_executor,
            ride_economic_repository=ride_economic_repository,
            ride_economic_coordinator=ride_economic_coordinator,
            ride_economic_terminal_projector=terminal_projector,
        )
    processor._publish_nats_event = AsyncMock()
    processor._emit_ride_finalized_notification = AsyncMock()
    processor.achievement_detector.detect_achievements = AsyncMock(return_value=[])
    processor.analytics_service.update_daily_aggregates = AsyncMock()

    result = await processor.process_phase3_rewards(
        ride_id=ride_id,
        user_id=user_id,
    )

    assert result["status"] == "completed"
    assert result["cal_earned"] == 84
    ride_economic_coordinator.execute.assert_awaited_once_with(ride_id)
    terminal_projector.project.assert_awaited_once_with(ride_id)
    user_repo.get_user_wallet.assert_not_awaited()
    assert processor._publish_nats_event.await_args.args[1]["wallet"] == "frozen-wallet-1"
    assert result["economic_state"] == "complete"
    ride_repo.update_phase_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_phase3_propagates_failed_review_checkpoint_for_nats_nak() -> None:
    ride_id = uuid4()
    user_id = uuid4()
    completed_at = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=5)
    started_at = completed_at - timedelta(minutes=50)
    ride_repo = MagicMock()
    ride_repo.get_ride_for_phase3 = AsyncMock(
        return_value={
            "id": str(ride_id),
            "user_id": str(user_id),
            "processing_status": "enriched",
            "file_type": "fit",
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "duration_sec": 3000,
            "distance_m": 9200.0,
            "elevation_gain_m": 422.0,
            "tss": 84.0,
            "kcals": 664.0,
            "avg_power_w": 232.0,
            "normalized_power_w": 232.0,
            "avg_hr_bpm": 151.0,
            "canonical_match": True,
            "review_reason": None,
        }
    )
    ride_repo.update_phase_status = AsyncMock()
    user_repo = MagicMock()
    user_repo.get_user_wallet = AsyncMock(return_value="wallet-1")
    coordinator = MagicMock()
    coordinator.execute = AsyncMock(
        return_value=RideEconomicOutcome(
            status="under_review",
            state="planned",
            durable_checkpoint=False,
            error="pda mismatch; review checkpoint persistence failed",
        )
    )
    projection_store = MagicMock()
    _configure_empty_canon_evidence(projection_store)
    projection_store.get_pattern_results_from_db = AsyncMock(return_value=None)

    with patch("app.services.ride_processor.get_supabase_client", return_value=MagicMock()):
        processor = RideProcessor(
            ride_repo=ride_repo,
            user_repo=user_repo,
            tile_repo=MagicMock(),
            token_repo=MagicMock(),
            pattern_repo=MagicMock(),
            achievement_repo=MagicMock(),
            vault_repo=MagicMock(),
            fitness_repo=MagicMock(),
            notification_repo=MagicMock(),
            ride_projection_store=projection_store,
            ride_economic_coordinator=coordinator,
        )
    processor.ride_economic_repository = MagicMock()
    processor.ride_economic_repository.get_plan = AsyncMock(
        return_value={
            "wallet": "wallet-1",
            "exact_cal_base_units": 84 * CAL_DECIMALS_MULTIPLIER,
            "reward_policy": "rewardable",
            "review_reason": None,
            "state": "planned",
            "steps": [],
        }
    )
    processor._publish_nats_event = AsyncMock()
    processor.achievement_detector.detect_achievements = AsyncMock(return_value=[])
    processor.analytics_service.update_daily_aggregates = AsyncMock()

    result = await processor.process_phase3_rewards(ride_id=ride_id, user_id=user_id)

    assert result["status"] == "under_review"
    assert result["cal_earned"] == 0
    assert result["durable_checkpoint"] is False


@pytest.mark.asyncio
async def test_phase3_fails_closed_on_malformed_frozen_plan() -> None:
    ride_id = uuid4()
    user_id = uuid4()
    ride_repo = MagicMock()
    ride_repo.get_ride_for_phase3 = AsyncMock(
        return_value={
            "id": str(ride_id),
            "user_id": str(user_id),
            "processing_status": "enriched",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "duration_sec": 300,
            "distance_m": 1000,
            "elevation_gain_m": 100,
            "tss": 10,
            "kcals": 100,
        }
    )
    ride_repo.update_phase_status = AsyncMock()
    coordinator = MagicMock()
    coordinator.execute = AsyncMock()

    with patch("app.services.ride_processor.get_supabase_client", return_value=MagicMock()):
        processor = RideProcessor(
            ride_repo=ride_repo,
            user_repo=MagicMock(),
            tile_repo=MagicMock(),
            token_repo=MagicMock(),
            pattern_repo=MagicMock(),
            achievement_repo=MagicMock(),
            vault_repo=MagicMock(),
            fitness_repo=MagicMock(),
            notification_repo=MagicMock(),
            ride_projection_store=MagicMock(),
            ride_economic_coordinator=coordinator,
        )
    processor.ride_economic_repository = MagicMock()
    processor.ride_economic_repository.get_plan = AsyncMock(
        return_value={"state": "planned", "steps": []}
    )
    processor._emit_ride_failed_notification = AsyncMock()

    result = await processor.process_phase3_rewards(ride_id=ride_id, user_id=user_id)

    assert result["status"] == "phase3_failed"
    assert "wallet" in result["error"]
    coordinator.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_ride_skips_onchain_side_effects_when_preliminary_fit_hash_mismatches() -> None:
    ride_id = uuid4()
    user_id = uuid4()
    started_at = datetime(2026, 4, 17, 8, 0, tzinfo=timezone.utc)
    completed_at = started_at + timedelta(minutes=5)

    ride_repo = MagicMock()
    _configure_establishing_threshold(ride_repo)
    ride_repo.update_ride_status = AsyncMock()
    ride_repo.get_ride = AsyncMock(
        return_value={
            "id": str(ride_id),
            "preliminary_ride_hash_hex": "cd" * 32,
            "preliminary_parser_version": 1,
        }
    )
    ride_repo.store_gps_points = AsyncMock()
    ride_repo.update_ride_metadata = AsyncMock()
    ride_repo.register_reward_threshold_effort = AsyncMock(
        return_value={"disposition": "display_only"}
    )

    user_repo = MagicMock()
    user_repo.get_user_wallet = AsyncMock(return_value="wallet-1")
    user_repo.get_user_stats = AsyncMock(return_value={"total_tss": 1000.0})
    ride_executor = MagicMock()
    ride_executor.record_ride_attestation = AsyncMock()
    ride_executor.credit_cal = AsyncMock()
    ride_executor.record_climb_completion = AsyncMock()
    ride_attester = MagicMock()
    ride_projection_store = MagicMock()
    _configure_empty_canon_evidence(ride_projection_store)
    ride_projection_store.capture_profile_snapshot = AsyncMock()
    ride_projection_store.store_activity_streams = AsyncMock()
    ride_projection_store.gps_track_to_dicts = MagicMock(return_value=[])
    ride_projection_store.records_to_dicts = MagicMock(return_value=[])
    ride_projection_store.store_pattern_results = AsyncMock()
    ride_projection_store.update_ride_complete = AsyncMock()

    with patch("app.services.ride_processor.get_supabase_client", return_value=MagicMock()):
        processor = RideProcessor(
            ride_repo=ride_repo,
            user_repo=user_repo,
            tile_repo=MagicMock(),
            token_repo=MagicMock(),
            pattern_repo=MagicMock(),
            achievement_repo=MagicMock(),
            vault_repo=MagicMock(),
            fitness_repo=MagicMock(),
            notification_repo=MagicMock(),
            ride_attester=ride_attester,
            ride_projection_store=ride_projection_store,
            ride_executor=ride_executor,
        )

    processor._publish_nats_event = AsyncMock()
    processor.achievement_detector.detect_achievements = AsyncMock(return_value=[])
    processor.analytics_service.update_daily_aggregates = AsyncMock()

    parsed_ride = SimpleNamespace(
        records=[SimpleNamespace(timestamp=started_at, lat=39.95, lon=-75.16)],
        gps_track=[],
        started_at=started_at,
        completed_at=completed_at,
        device_name="Test Head Unit",
        file_name="ride.fit",
    )
    metrics = _sensor_backed_metrics()
    identity = OnchainRideIdentity(
        ride_hash=bytes.fromhex("ab" * 32),
        attestation_commitment=bytes.fromhex("ab" * 32),
        parser_version=1,
        source_kind=1,
    )
    ride_attester.prepare_ride.return_value = RideAttestationPreparation(
        onchain_identity=identity,
        preliminary_check=PreliminaryAttestationCheck(
            preliminary_ride_hash_hex="cd" * 32,
            preliminary_parser_version=1,
            canonical_match=False,
            review_reason="preliminary_hash_mismatch",
            requires_review=True,
        ),
        parsed_ride=parsed_ride,
        metrics=metrics,
    )
    ride_attester.calculate_metrics.return_value = SimpleNamespace(**vars(metrics))

    result = await processor.process_ride(
        ride_id=ride_id,
        file_data_b64="ZmFrZQ==",
        file_type="fit",
        user_id=user_id,
        file_bytes=b"fake",
    )

    assert result["status"] == "under_review"
    ride_attester.prepare_ride.assert_called_once()
    ride_executor.record_ride_attestation.assert_not_awaited()
    ride_executor.credit_cal.assert_not_awaited()
    ride_executor.record_climb_completion.assert_not_awaited()
    ride_projection_store.update_ride_complete.assert_awaited_once()
    kwargs = ride_projection_store.update_ride_complete.await_args.kwargs
    assert kwargs["status"] == "under_review"
    assert kwargs["canonical_match"] is False
    assert kwargs["review_reason"] == "preliminary_hash_mismatch"
    assert kwargs["cal_earned"] == 0
    assert kwargs["total_tss_after"] is None
    assert kwargs["level_delta"] is None
    assert kwargs["level_after"] is None
    user_repo.get_user_stats.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_ride_holds_manual_power_upload_until_threshold_exists() -> None:
    ride_id = uuid4()
    user_id = uuid4()
    started_at = datetime.now(timezone.utc) - timedelta(days=2)
    completed_at = started_at + timedelta(minutes=5)
    identity = _identity()
    ride_row = {
        "id": str(ride_id),
        "import_diagnostics": build_ride_provenance_diagnostics(
            preliminary_ride_hash=None,
            parser_version=None,
        ),
    }
    assert ride_row["import_diagnostics"]["provenance_tier"] == PROVENANCE_TIER_MANUAL_FILE_UPLOAD
    assert ride_row["import_diagnostics"]["preliminary_attestation_required"] is False

    preliminary_check = evaluate_preliminary_attestation(
        ride_row,
        identity,
        file_type="fit",
    )
    assert preliminary_check.requires_review is False
    assert preliminary_check.canonical_match is None

    metrics = _sensor_backed_metrics(tss=84.0)
    ctx = _processor_context(
        ride_id=ride_id,
        ride_row=ride_row,
        preliminary_check=preliminary_check,
        parsed_ride=_parsed_ride(started_at, completed_at, "manual-upload.fit"),
        metrics=metrics,
        identity=identity,
    )

    result = await ctx.processor.process_ride(
        ride_id=ride_id,
        file_data_b64="ZmFrZQ==",
        file_type="fit",
        user_id=user_id,
        file_bytes=b"fake",
    )

    assert result["status"] == "completed"
    assert result["cal_earned"] == 0
    assert result["reward_policy"] == "threshold_provisional_hold_v1"
    ctx.ride_attester.prepare_ride.assert_called_once()
    assert ctx.ride_attester.prepare_ride.call_args.kwargs["ride_row"] == ride_row
    ctx.ride_economic_coordinator.freeze_plan.assert_awaited_once()
    frozen_draft = ctx.ride_economic_coordinator.freeze_plan.await_args.args[0]
    assert frozen_draft.total_tss == 0
    assert frozen_draft.exact_cal_base_units == 0
    assert frozen_draft.threshold_hold_evidence is not None
    ctx.ride_economic_repository.register_threshold_provisional_hold.assert_not_awaited()
    ctx.ride_economic_coordinator.execute.assert_awaited_once_with(ride_id)
    ctx.terminal_projector.project.assert_awaited_once_with(ride_id)

    ctx.ride_projection_store.update_ride_complete.assert_awaited_once()
    kwargs = ctx.ride_projection_store.update_ride_complete.await_args.kwargs
    assert kwargs["status"] == "completed"
    assert kwargs["review_reason"] is None
    assert kwargs["canonical_match"] is None
    assert kwargs["preliminary_ride_hash_hex"] is None
    assert kwargs["preliminary_parser_version"] is None
    assert kwargs["cal_earned"] == 0
    effort_policy = kwargs["effort_policy"]
    assert effort_policy.effort_evidence_tier == "power_verified"
    assert effort_policy.reward_policy == "threshold_provisional_hold_v1"
    assert effort_policy.rewardable_cal == 0
    assert effort_policy.rewardable_cal_base_units == 0
    assert kwargs["total_tss_after"] == pytest.approx(1000.0)


@pytest.mark.asyncio
async def test_process_ride_executes_accepted_zero_cal_plan_without_climbs() -> None:
    ride_id = uuid4()
    user_id = uuid4()
    started_at = datetime.now(timezone.utc) - timedelta(days=2)
    completed_at = started_at + timedelta(minutes=5)
    identity = _identity()
    preliminary_check = PreliminaryAttestationCheck(
        preliminary_ride_hash_hex=None,
        preliminary_parser_version=None,
        canonical_match=None,
        review_reason=None,
        requires_review=False,
    )
    ctx = _processor_context(
        ride_id=ride_id,
        ride_row={"id": str(ride_id)},
        preliminary_check=preliminary_check,
        parsed_ride=_parsed_ride(started_at, completed_at, "zero-cal.fit"),
        metrics=_sensor_backed_metrics(tss=0.0),
        identity=identity,
    )

    result = await ctx.processor.process_ride(
        ride_id=ride_id,
        file_data_b64="ZmFrZQ==",
        file_type="fit",
        user_id=user_id,
        file_bytes=b"fake",
    )

    assert result["status"] == "completed"
    assert result["cal_earned"] == 0
    ctx.ride_economic_coordinator.freeze_plan.assert_awaited_once()
    draft = ctx.ride_economic_coordinator.freeze_plan.await_args.args[0]
    assert draft.reward_policy == "not_counted"
    assert draft.exact_cal_base_units == 0
    assert draft.completion_steps == []
    ctx.ride_economic_repository.register_threshold_provisional_hold.assert_not_awaited()
    ctx.ride_economic_coordinator.execute.assert_awaited_once_with(ride_id)
    ctx.terminal_projector.project.assert_awaited_once_with(ride_id)


@pytest.mark.asyncio
async def test_process_ride_missing_wallet_fails_closed_and_reports_zero_cal() -> None:
    ride_id = uuid4()
    user_id = uuid4()
    started_at = datetime.now(timezone.utc) - timedelta(days=2)
    completed_at = started_at + timedelta(minutes=5)
    ctx = _processor_context(
        ride_id=ride_id,
        ride_row={"id": str(ride_id)},
        preliminary_check=PreliminaryAttestationCheck(
            preliminary_ride_hash_hex=None,
            preliminary_parser_version=None,
            canonical_match=None,
            review_reason=None,
            requires_review=False,
        ),
        parsed_ride=_parsed_ride(started_at, completed_at, "missing-wallet.fit"),
        metrics=_sensor_backed_metrics(tss=84.0),
        identity=_identity(),
    )
    ctx.user_repo.get_user_wallet.return_value = None

    result = await ctx.processor.process_ride(
        ride_id=ride_id,
        file_data_b64="ZmFrZQ==",
        file_type="fit",
        user_id=user_id,
        file_bytes=b"fake",
    )

    assert result["status"] == "under_review"
    assert result["cal_earned"] == 0
    ctx.ride_economic_coordinator.freeze_plan.assert_not_awaited()
    ctx.ride_economic_coordinator.execute.assert_not_awaited()
    complete_call = next(
        call
        for call in ctx.processor._publish_nats_event.await_args_list
        if call.args[0] == "rides.events.completed"
    )
    assert complete_call.args[1]["cal_earned"] == 0
    update = ctx.ride_projection_store.update_ride_complete.await_args.kwargs
    assert update["status"] == "under_review"
    assert update["cal_earned"] == 0
    assert update["review_reason"] == "missing_wallet_for_economics"
    ctx.ride_attester.prepare_ride.assert_called_once()
    assert ctx.ride_attester.prepare_ride.call_args.kwargs["ride_row"] == {
        "id": str(ride_id)
    }
    ctx.terminal_projector.project.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_ride_blocks_first_party_missing_recorder_stamp_before_cal_credit() -> None:
    ride_id = uuid4()
    user_id = uuid4()
    started_at = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)
    completed_at = started_at + timedelta(minutes=5)
    identity = _identity()
    ride_row = {
        "id": str(ride_id),
        "import_diagnostics": build_ride_provenance_diagnostics(
            preliminary_ride_hash=None,
            parser_version=None,
            base={"provenance_tier": PROVENANCE_TIER_FIRST_PARTY_RECORDED},
        ),
    }
    assert ride_row["import_diagnostics"]["provenance_tier"] == PROVENANCE_TIER_FIRST_PARTY_RECORDED
    assert ride_row["import_diagnostics"]["preliminary_attestation_required"] is True
    assert ride_row["import_diagnostics"]["missing_preliminary_attestation"] is True

    preliminary_check = evaluate_preliminary_attestation(
        ride_row,
        identity,
        file_type="fit",
    )
    assert preliminary_check.requires_review is True
    assert preliminary_check.review_reason == MISSING_PRELIMINARY_ATTESTATION_REVIEW_REASON

    metrics = _sensor_backed_metrics(tss=84.0)
    ctx = _processor_context(
        ride_id=ride_id,
        ride_row=ride_row,
        preliminary_check=preliminary_check,
        parsed_ride=_parsed_ride(started_at, completed_at, "first-party-missing-stamp.fit"),
        metrics=metrics,
        identity=identity,
    )

    result = await ctx.processor.process_ride(
        ride_id=ride_id,
        file_data_b64="ZmFrZQ==",
        file_type="fit",
        user_id=user_id,
        file_bytes=b"fake",
    )

    assert result["status"] == "under_review"
    assert result["cal_earned"] == 0
    assert result["reward_policy"] == "manual_review"
    ctx.ride_executor.record_ride_attestation.assert_not_awaited()
    ctx.ride_executor.credit_cal.assert_not_awaited()
    ctx.ride_executor.record_climb_completion.assert_not_awaited()
    ctx.user_repo.get_user_stats.assert_not_awaited()

    ctx.ride_projection_store.update_ride_complete.assert_awaited_once()
    kwargs = ctx.ride_projection_store.update_ride_complete.await_args.kwargs
    assert kwargs["status"] == "under_review"
    assert kwargs["review_reason"] == MISSING_PRELIMINARY_ATTESTATION_REVIEW_REASON
    assert kwargs["canonical_match"] is False
    assert kwargs["cal_earned"] == 0
    effort_policy = kwargs["effort_policy"]
    assert effort_policy.effort_evidence_tier == "manual_review"
    assert effort_policy.reward_policy == "manual_review"
    assert effort_policy.rewardable_cal == 0
    assert kwargs["total_tss_after"] is None


@pytest.mark.asyncio
async def test_process_ride_holds_provider_power_upload_until_threshold_exists() -> None:
    ride_id = uuid4()
    user_id = uuid4()
    started_at = datetime.now(timezone.utc) - timedelta(days=2)
    completed_at = started_at + timedelta(minutes=5)
    identity = _identity()
    ride_row = {
        "id": str(ride_id),
        "import_source_id": "strava-activity-123",
        "import_diagnostics": build_ride_provenance_diagnostics(
            preliminary_ride_hash=None,
            parser_version=None,
            base={
                "import_source": "strava_stream_reconstructed_gpx",
                "source_activity_id": "strava-activity-123",
            },
        ),
    }
    assert ride_row["import_diagnostics"]["provenance_tier"] == PROVENANCE_TIER_TRUSTED_PROVIDER_SYNC
    assert ride_row["import_diagnostics"]["preliminary_attestation_required"] is False

    preliminary_check = evaluate_preliminary_attestation(
        ride_row,
        identity,
        file_type="gpx",
    )
    assert preliminary_check.requires_review is False
    assert preliminary_check.canonical_match is None

    metrics = _sensor_backed_metrics(tss=84.0)
    ctx = _processor_context(
        ride_id=ride_id,
        ride_row=ride_row,
        preliminary_check=preliminary_check,
        parsed_ride=_parsed_ride(started_at, completed_at, "strava-sync.gpx"),
        metrics=metrics,
        identity=identity,
    )

    result = await ctx.processor.process_ride(
        ride_id=ride_id,
        file_data_b64="ZmFrZQ==",
        file_type="gpx",
        user_id=user_id,
        file_bytes=b"fake",
    )

    assert result["status"] == "completed"
    assert result["cal_earned"] == 0
    assert result["reward_policy"] == "threshold_provisional_hold_v1"
    ctx.ride_economic_coordinator.freeze_plan.assert_awaited_once()
    frozen_draft = ctx.ride_economic_coordinator.freeze_plan.await_args.args[0]
    assert frozen_draft.total_tss == 0
    assert frozen_draft.exact_cal_base_units == 0
    assert frozen_draft.threshold_hold_evidence is not None
    ctx.ride_economic_repository.register_threshold_provisional_hold.assert_not_awaited()
    ctx.ride_economic_coordinator.execute.assert_awaited_once_with(ride_id)
    kwargs = ctx.ride_projection_store.update_ride_complete.await_args.kwargs
    assert kwargs["status"] == "completed"
    assert kwargs["review_reason"] is None
    assert kwargs["canonical_match"] is None
    assert kwargs["preliminary_ride_hash_hex"] is None
    assert kwargs["preliminary_parser_version"] is None
    assert kwargs["cal_earned"] == 0
    assert kwargs["effort_policy"].reward_policy == "threshold_provisional_hold_v1"


@pytest.mark.asyncio
async def test_process_ride_blocks_trusted_provider_sync_missing_activity_id() -> None:
    ride_id = uuid4()
    user_id = uuid4()
    started_at = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)
    completed_at = started_at + timedelta(minutes=5)
    identity = _identity()
    ride_row = {
        "id": str(ride_id),
        "import_diagnostics": build_ride_provenance_diagnostics(
            preliminary_ride_hash=None,
            parser_version=None,
            base={"import_source": "strava_stream_reconstructed_gpx"},
        ),
    }

    preliminary_check = evaluate_preliminary_attestation(
        ride_row,
        identity,
        file_type="gpx",
    )
    assert preliminary_check.requires_review is True
    assert preliminary_check.review_reason == MISSING_PROVIDER_ACTIVITY_REVIEW_REASON

    metrics = _sensor_backed_metrics(tss=84.0)
    ctx = _processor_context(
        ride_id=ride_id,
        ride_row=ride_row,
        preliminary_check=preliminary_check,
        parsed_ride=_parsed_ride(started_at, completed_at, "provider-missing-id.gpx"),
        metrics=metrics,
        identity=identity,
    )

    result = await ctx.processor.process_ride(
        ride_id=ride_id,
        file_data_b64="ZmFrZQ==",
        file_type="gpx",
        user_id=user_id,
        file_bytes=b"fake",
    )

    assert result["status"] == "under_review"
    assert result["cal_earned"] == 0
    ctx.ride_executor.record_ride_attestation.assert_not_awaited()
    ctx.ride_executor.credit_cal.assert_not_awaited()
    kwargs = ctx.ride_projection_store.update_ride_complete.await_args.kwargs
    assert kwargs["status"] == "under_review"
    assert kwargs["review_reason"] == MISSING_PROVIDER_ACTIVITY_REVIEW_REASON
    assert kwargs["canonical_match"] is False
    assert kwargs["cal_earned"] == 0
    assert kwargs["effort_policy"].reward_policy == "manual_review"


@pytest.mark.asyncio
async def test_process_ride_blocks_trusted_provider_duplicate_provenance() -> None:
    ride_id = uuid4()
    user_id = uuid4()
    started_at = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)
    completed_at = started_at + timedelta(minutes=5)
    identity = _identity()
    ride_row = {
        "id": str(ride_id),
        "import_source_id": "strava-activity-123",
        "import_diagnostics": build_ride_provenance_diagnostics(
            preliminary_ride_hash=None,
            parser_version=None,
            base={
                "import_source": "strava_stream_reconstructed_gpx",
                "source_activity_id": "strava-activity-123",
                "duplicate_provider_activity": True,
            },
        ),
    }

    preliminary_check = evaluate_preliminary_attestation(
        ride_row,
        identity,
        file_type="gpx",
    )
    assert preliminary_check.requires_review is True
    assert preliminary_check.review_reason == DUPLICATE_PROVIDER_ACTIVITY_REVIEW_REASON

    metrics = _sensor_backed_metrics(tss=84.0)
    ctx = _processor_context(
        ride_id=ride_id,
        ride_row=ride_row,
        preliminary_check=preliminary_check,
        parsed_ride=_parsed_ride(started_at, completed_at, "provider-duplicate.gpx"),
        metrics=metrics,
        identity=identity,
    )

    result = await ctx.processor.process_ride(
        ride_id=ride_id,
        file_data_b64="ZmFrZQ==",
        file_type="gpx",
        user_id=user_id,
        file_bytes=b"fake",
    )

    assert result["status"] == "under_review"
    assert result["cal_earned"] == 0
    ctx.ride_executor.record_ride_attestation.assert_not_awaited()
    ctx.ride_executor.credit_cal.assert_not_awaited()
    kwargs = ctx.ride_projection_store.update_ride_complete.await_args.kwargs
    assert kwargs["status"] == "under_review"
    assert kwargs["review_reason"] == DUPLICATE_PROVIDER_ACTIVITY_REVIEW_REASON
    assert kwargs["canonical_match"] is False
    assert kwargs["cal_earned"] == 0
    assert kwargs["effort_policy"].reward_policy == "manual_review"


@pytest.mark.asyncio
async def test_process_ride_keeps_attestation_failure_retryable() -> None:
    ride_id = uuid4()
    user_id = uuid4()
    completed_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    started_at = completed_at - timedelta(minutes=5)

    ride_repo = MagicMock()
    _configure_establishing_threshold(ride_repo)
    ride_repo.update_ride_status = AsyncMock()
    ride_repo.get_ride = AsyncMock(return_value={"id": str(ride_id)})
    ride_repo.store_gps_points = AsyncMock()
    ride_repo.update_ride_metadata = AsyncMock()
    ride_repo.register_reward_threshold_effort = AsyncMock(
        return_value={"disposition": "display_only"}
    )

    user_repo = MagicMock()
    user_repo.get_user_wallet = AsyncMock(return_value="wallet-1")
    user_repo.get_user_stats = AsyncMock(return_value={"total_tss": 1000.0})
    ride_executor = MagicMock()
    ride_executor.record_ride_attestation = AsyncMock(side_effect=RuntimeError("chain down"))
    ride_executor.credit_cal = AsyncMock()
    ride_economic_coordinator = MagicMock()
    ride_economic_coordinator.freeze_plan = AsyncMock(
        return_value={
            "ride_id": str(ride_id),
            "state": "planned",
            "steps": [],
            "plan_evidence_hash_hex": "34" * 32,
        }
    )
    ride_economic_coordinator.execute = AsyncMock(
        return_value=RideEconomicOutcome(
            status="recovery_pending",
            state="planned",
            durable_checkpoint=True,
            error="attestation: chain down",
        )
    )
    ride_attester = MagicMock()
    ride_projection_store = MagicMock()
    _configure_empty_canon_evidence(ride_projection_store)
    ride_projection_store.capture_profile_snapshot = AsyncMock()
    ride_projection_store.store_activity_streams = AsyncMock()
    ride_projection_store.gps_track_to_dicts = MagicMock(return_value=[])
    ride_projection_store.records_to_dicts = MagicMock(return_value=[])
    ride_projection_store.store_pattern_results = AsyncMock()
    ride_projection_store.update_ride_complete = AsyncMock()
    ride_economic_repository = MagicMock()
    ride_economic_repository.get_effort_trim_basis = AsyncMock(return_value={"frozen": None, "covered_spans_ms": [], "covered_completion_windows": []})
    ride_economic_repository.register_threshold_provisional_hold = AsyncMock(
        return_value={"hold_id": str(uuid4())}
    )

    with patch("app.services.ride_processor.get_supabase_client", return_value=MagicMock()):
        processor = RideProcessor(
            ride_repo=ride_repo,
            user_repo=user_repo,
            tile_repo=MagicMock(),
            token_repo=MagicMock(),
            pattern_repo=MagicMock(),
            achievement_repo=MagicMock(),
            vault_repo=MagicMock(),
            fitness_repo=MagicMock(),
            notification_repo=MagicMock(),
            ride_attester=ride_attester,
            ride_projection_store=ride_projection_store,
            ride_executor=ride_executor,
            ride_economic_repository=ride_economic_repository,
            ride_economic_coordinator=ride_economic_coordinator,
        )

    processor._publish_nats_event = AsyncMock()
    processor.achievement_detector.detect_achievements = AsyncMock(return_value=[])
    processor.analytics_service.update_daily_aggregates = AsyncMock()

    metrics = _sensor_backed_metrics()
    ride_attester.prepare_ride.return_value = RideAttestationPreparation(
        onchain_identity=OnchainRideIdentity(
            ride_hash=bytes.fromhex("ab" * 32),
            attestation_commitment=bytes.fromhex("ab" * 32),
            parser_version=1,
            source_kind=1,
        ),
        preliminary_check=PreliminaryAttestationCheck(
            preliminary_ride_hash_hex="ab" * 32,
            preliminary_parser_version=1,
            canonical_match=True,
            review_reason=None,
            requires_review=False,
        ),
        parsed_ride=SimpleNamespace(
            records=[SimpleNamespace(timestamp=started_at, lat=39.95, lon=-75.16)],
            gps_track=[],
            started_at=started_at,
            completed_at=completed_at,
            device_name="Test Head Unit",
            file_name="ride.fit",
        ),
        metrics=metrics,
    )
    ride_attester.calculate_metrics.return_value = SimpleNamespace(**vars(metrics))

    result = await processor.process_ride(
        ride_id=ride_id,
        file_data_b64="ZmFrZQ==",
        file_type="fit",
        user_id=user_id,
        file_bytes=b"fake",
    )

    assert result["status"] == "recovery_pending"
    assert result["durable_checkpoint"] is True
    ride_executor.credit_cal.assert_not_awaited()
    ride_projection_store.update_ride_complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_ride_abstains_route_only_effort_from_economics() -> None:
    ride_id = uuid4()
    user_id = uuid4()
    started_at = datetime.now(timezone.utc) - timedelta(days=2)
    completed_at = started_at + timedelta(hours=3)

    ride_repo = MagicMock()
    _configure_establishing_threshold(ride_repo)
    ride_repo.update_ride_status = AsyncMock()
    ride_repo.get_ride = AsyncMock(return_value={"id": str(ride_id)})
    ride_repo.store_gps_points = AsyncMock()
    ride_repo.update_ride_metadata = AsyncMock()
    ride_repo.register_reward_threshold_effort = AsyncMock(
        return_value={"disposition": "display_only"}
    )

    user_repo = MagicMock()
    user_repo.get_user_wallet = AsyncMock(return_value="wallet-1")
    user_repo.get_user_stats = AsyncMock(return_value={"total_tss": 1000.0})
    ride_executor = MagicMock()
    ride_executor.record_ride_attestation = AsyncMock()
    ride_executor.credit_cal = AsyncMock()
    ride_executor.record_climb_completion = AsyncMock()
    ride_attester = MagicMock()
    ride_projection_store = MagicMock()
    _configure_empty_canon_evidence(ride_projection_store)
    ride_projection_store.capture_profile_snapshot = AsyncMock()
    ride_projection_store.store_activity_streams = AsyncMock()
    ride_projection_store.gps_track_to_dicts = MagicMock(return_value=[])
    ride_projection_store.records_to_dicts = MagicMock(return_value=[])
    ride_projection_store.store_pattern_results = AsyncMock()
    ride_projection_store.update_ride_complete = AsyncMock()

    with patch("app.services.ride_processor.get_supabase_client", return_value=MagicMock()):
        processor = RideProcessor(
            ride_repo=ride_repo,
            user_repo=user_repo,
            tile_repo=MagicMock(),
            token_repo=MagicMock(),
            pattern_repo=MagicMock(),
            achievement_repo=MagicMock(),
            vault_repo=MagicMock(),
            fitness_repo=MagicMock(),
            notification_repo=MagicMock(),
            ride_attester=ride_attester,
            ride_projection_store=ride_projection_store,
            ride_executor=ride_executor,
        )

    processor._publish_nats_event = AsyncMock()
    processor.achievement_detector.detect_achievements = AsyncMock(return_value=[])
    processor.analytics_service.update_daily_aggregates = AsyncMock()

    parsed_ride = SimpleNamespace(
        records=[SimpleNamespace(timestamp=started_at, lat=39.95, lon=-75.16)],
        gps_track=[],
        started_at=started_at,
        completed_at=completed_at,
        device_name="Phone GPS",
        file_name="route-only.gpx",
    )
    metrics = SimpleNamespace(
        duration_sec=10800,
        tss=169.9,
        kcals=2304.0,
        distance_m=93212.1,
        elevation_gain_m=679.5,
        avg_power_w=None,
        max_power_w=None,
        normalized_power_w=None,
        avg_hr_bpm=None,
        max_hr_bpm=None,
        avg_speed_mps=8.63,
        avg_cadence_rpm=None,
    )
    identity = OnchainRideIdentity(
        ride_hash=bytes.fromhex("ab" * 32),
        attestation_commitment=bytes.fromhex("ab" * 32),
        parser_version=1,
        source_kind=2,
    )
    ride_attester.prepare_ride.return_value = RideAttestationPreparation(
        onchain_identity=identity,
        preliminary_check=PreliminaryAttestationCheck(
            preliminary_ride_hash_hex="ab" * 32,
            preliminary_parser_version=1,
            canonical_match=True,
            review_reason=None,
            requires_review=False,
        ),
        parsed_ride=parsed_ride,
        metrics=metrics,
    )
    ride_attester.calculate_metrics.return_value = SimpleNamespace(**vars(metrics))

    result = await processor.process_ride(
        ride_id=ride_id,
        file_data_b64="ZmFrZQ==",
        file_type="gpx",
        user_id=user_id,
        file_bytes=b"fake",
    )

    assert result["cal_earned"] == 0
    ride_executor.record_ride_attestation.assert_not_awaited()
    ride_executor.credit_cal.assert_not_awaited()
    ride_projection_store.update_ride_complete.assert_awaited_once()
    kwargs = ride_projection_store.update_ride_complete.await_args.kwargs
    assert kwargs["status"] == "under_review"
    assert kwargs["canonical_match"] is True
    assert kwargs["review_reason"] == ROUTE_ESTIMATE_ECONOMIC_REVIEW_REASON
    assert kwargs["cal_earned"] == 0
    effort_policy = kwargs["effort_policy"]
    assert effort_policy.effort_evidence_tier == "route_only"
    assert effort_policy.reward_policy == "estimated_only"
    assert effort_policy.estimated_cal == 169
    assert effort_policy.rewardable_cal == 0
    assert effort_policy.tributable_cal == 0
    assert kwargs["total_tss_after"] is None
    assert kwargs["level_delta"] is None
    assert kwargs["level_after"] is None
    user_repo.get_user_stats.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_ride_marks_pre_economy_activity_under_review_before_onchain_side_effects() -> None:
    ride_id = uuid4()
    user_id = uuid4()
    started_at = datetime(2015, 6, 26, 9, 0, tzinfo=timezone.utc)
    completed_at = started_at + timedelta(hours=3)

    ride_repo = MagicMock()
    _configure_establishing_threshold(ride_repo)
    ride_repo.update_ride_status = AsyncMock()
    ride_repo.get_ride = AsyncMock(return_value={"id": str(ride_id)})
    ride_repo.store_gps_points = AsyncMock()
    ride_repo.update_ride_metadata = AsyncMock()
    ride_repo.register_reward_threshold_effort = AsyncMock(
        return_value={"disposition": "display_only"}
    )

    user_repo = MagicMock()
    user_repo.get_user_wallet = AsyncMock(return_value="wallet-1")
    user_repo.get_user_stats = AsyncMock(return_value={"total_tss": 1000.0})
    ride_executor = MagicMock()
    ride_executor.record_ride_attestation = AsyncMock()
    ride_executor.credit_cal = AsyncMock()
    ride_executor.record_climb_completion = AsyncMock()
    ride_attester = MagicMock()
    ride_projection_store = MagicMock()
    _configure_empty_canon_evidence(ride_projection_store)
    ride_projection_store.capture_profile_snapshot = AsyncMock()
    ride_projection_store.store_activity_streams = AsyncMock()
    ride_projection_store.gps_track_to_dicts = MagicMock(return_value=[])
    ride_projection_store.records_to_dicts = MagicMock(return_value=[])
    ride_projection_store.store_pattern_results = AsyncMock()
    ride_projection_store.update_ride_complete = AsyncMock()

    with patch("app.services.ride_processor.get_supabase_client", return_value=MagicMock()):
        processor = RideProcessor(
            ride_repo=ride_repo,
            user_repo=user_repo,
            tile_repo=MagicMock(),
            token_repo=MagicMock(),
            pattern_repo=MagicMock(),
            achievement_repo=MagicMock(),
            vault_repo=MagicMock(),
            fitness_repo=MagicMock(),
            notification_repo=MagicMock(),
            ride_attester=ride_attester,
            ride_projection_store=ride_projection_store,
            ride_executor=ride_executor,
        )

    processor._publish_nats_event = AsyncMock()
    processor.achievement_detector.detect_achievements = AsyncMock(return_value=[])
    processor.analytics_service.update_daily_aggregates = AsyncMock()

    parsed_ride = SimpleNamespace(
        records=[SimpleNamespace(timestamp=started_at, lat=39.95, lon=-75.16)],
        gps_track=[],
        started_at=started_at,
        completed_at=completed_at,
        device_name="Old Head Unit",
        file_name="historical.fit",
    )
    metrics = SimpleNamespace(
        duration_sec=10800,
        tss=169.9,
        kcals=2304.0,
        distance_m=93212.1,
        elevation_gain_m=679.5,
        avg_power_w=220.0,
        max_power_w=750.0,
        normalized_power_w=235.0,
        avg_hr_bpm=150.0,
        max_hr_bpm=180.0,
        avg_speed_mps=8.63,
        avg_cadence_rpm=88.0,
    )
    identity = OnchainRideIdentity(
        ride_hash=bytes.fromhex("ab" * 32),
        attestation_commitment=bytes.fromhex("ab" * 32),
        parser_version=1,
        source_kind=1,
    )
    ride_attester.prepare_ride.return_value = RideAttestationPreparation(
        onchain_identity=identity,
        preliminary_check=PreliminaryAttestationCheck(
            preliminary_ride_hash_hex="ab" * 32,
            preliminary_parser_version=1,
            canonical_match=True,
            review_reason=None,
            requires_review=False,
        ),
        parsed_ride=parsed_ride,
        metrics=metrics,
    )
    ride_attester.calculate_metrics.return_value = SimpleNamespace(**vars(metrics))

    result = await processor.process_ride(
        ride_id=ride_id,
        file_data_b64="ZmFrZQ==",
        file_type="fit",
        user_id=user_id,
        file_bytes=b"fake",
    )

    assert result["cal_earned"] == 0
    ride_executor.record_ride_attestation.assert_not_awaited()
    ride_executor.credit_cal.assert_not_awaited()
    ride_executor.record_climb_completion.assert_not_awaited()
    ride_projection_store.update_ride_complete.assert_awaited_once()
    kwargs = ride_projection_store.update_ride_complete.await_args.kwargs
    assert kwargs["status"] == "under_review"
    assert kwargs["canonical_match"] is True
    assert kwargs["review_reason"] == PRE_ECONOMY_REVIEW_REASON
    assert kwargs["cal_earned"] == 0
    effort_policy = kwargs["effort_policy"]
    assert effort_policy.effort_evidence_tier == "manual_review"
    assert effort_policy.reward_policy == "manual_review"
    assert effort_policy.estimated_cal == 169
    assert effort_policy.rewardable_cal == 0
    assert effort_policy.tributable_cal == 0
    assert kwargs["total_tss_after"] is None
    assert kwargs["level_delta"] is None
    assert kwargs["level_after"] is None
    user_repo.get_user_stats.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ("legacy", "phase1"))
async def test_idle_review_survives_crash_after_tss_before_policy(phase):
    started = datetime.now(timezone.utc) - timedelta(hours=2)
    completed = started + timedelta(hours=1)
    ride_id = uuid4()
    metrics = _sensor_backed_metrics(tss=64.1)
    # Only the pre-snapshot metadata and TSS survived. No coupled CAL policy
    # columns were saved. On retry a different file/metrics view must not pay it.
    row = {
        "id": str(ride_id), **vars(metrics), "economic_tss": 64.1,
        "started_at": started.isoformat(), "completed_at": completed.isoformat(),
        "review_reason": "implausible_stationary_recording",
    }
    ctx = _processor_context(
        ride_id=ride_id, ride_row=row,
        preliminary_check=PreliminaryAttestationCheck(
            preliminary_ride_hash_hex=None, preliminary_parser_version=None,
            canonical_match=None, review_reason=None, requires_review=False,
        ),
        parsed_ride=_parsed_ride(started, completed, "retry.fit"),
        metrics=metrics, identity=_identity(),
    )
    ctx.ride_repo.update_phase_status = AsyncMock()
    method = ctx.processor.process_ride if phase == "legacy" else ctx.processor.process_phase1_core
    await method(ride_id=ride_id, user_id=uuid4(), file_data_b64="ZmFrZQ==", file_type="fit", file_bytes=b"fake")
    if phase == "legacy":
        saved = ctx.ride_projection_store.update_ride_complete.await_args.kwargs
        assert saved["status"] == "under_review"
        assert saved["effort_policy"].rewardable_cal_base_units == 0
        assert saved["effort_policy"].tributable_cal_base_units == 0
    else:
        saved = ctx.ride_repo.update_phase_status.await_args.kwargs
        assert saved["rewardable_cal"] == saved["tributable_cal"] == 0
        assert "economic_tss" not in saved
    assert saved["review_reason"] == "implausible_stationary_recording"
    ctx.ride_economic_coordinator.freeze_plan.assert_not_awaited()
    ctx.ride_economic_coordinator.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('file_type', ['fit', 'gpx'])
async def test_fully_covered_export_freezes_zero_without_losing_threshold_evidence(file_type, monkeypatch):
    def empty_metrics(parsed, keep, ftp):
        assert keep == []
        return None, []

    monkeypatch.setattr(
        "app.services.ride_effort_trim.calculate_paid_metrics_rust", empty_metrics
    )
    from app.services.subject_states import ride_subject_states
    ride_id, user_id = uuid4(), uuid4()
    start = datetime.now(timezone.utc) - timedelta(hours=2)
    row = {'id': str(ride_id)}
    ctx = _processor_context(
        ride_id=ride_id, ride_row=row,
        preliminary_check=PreliminaryAttestationCheck(None, None, True, None, False),
        parsed_ride=_parsed_ride(start, start+timedelta(minutes=5), f'second.{file_type}'),
        metrics=_sensor_backed_metrics(), identity=_identity('cd'*32),
    )
    order = []
    async def candidate(**kwargs):
        order.append('threshold')
        return {'disposition': 'pending_establishment'}
    async def admit(draft):
        order.append('admission')
        assert draft.effort_trim.paid_ms == []
        assert draft.total_tss == 0
        assert draft.exact_cal_base_units == 0
        return {'ride_id': str(ride_id), 'state': 'planned', 'steps': []}
    ctx.ride_repo.register_reward_threshold_effort.side_effect = candidate
    ctx.ride_economic_coordinator.freeze_plan.side_effect = admit
    from app.services.ride_effort_trim import epoch_ms
    ctx.ride_economic_repository.get_effort_trim_basis.return_value = {'frozen': None, 'covered_spans_ms': [[epoch_ms(start),epoch_ms(start+timedelta(minutes=5))]], 'covered_completion_windows': []}
    evidence = ThresholdEffortEvidence(
        best_180s_w=350, best_420s_w=293, best_900s_w=270,
        source=ThresholdSourceEvidence(recording_source='br_ios',
            power_source_ids=(str(uuid4()),), identity_complete=True,
            eligibility_reason='eligible'),
    )
    with patch('app.services.ride_processor.threshold_effort_evidence_or_empty', return_value=evidence):
        result = await ctx.processor.process_ride(
            ride_id=ride_id, file_data_b64='ZmFrZQ==', file_type=file_type,
            user_id=user_id, file_bytes=b'fake',
        )
    assert result['cal_earned'] == 0
    ctx.ride_economic_coordinator.execute.assert_awaited_once()
    saved = ctx.ride_projection_store.update_ride_complete.await_args.kwargs
    assert saved['review_reason'] is None
    assert saved['effort_policy'].reward_policy == 'not_counted'
    assert ride_subject_states(
        {
            **row,
            **saved["effort_policy"].as_ride_fields(),
            "covered_effort_seconds": 300,
            "paid_effort_seconds": 0,
        }
    )["cal"] == {"state": "not_counted", "reason": None}
    assert order == ['threshold', 'admission']


@pytest.mark.asyncio
async def test_power_free_gpx_keeps_route_estimate_review_reason():
    ride_id, user_id = uuid4(), uuid4()
    start = datetime.now(timezone.utc)-timedelta(hours=2)
    metrics = _sensor_backed_metrics()
    for key in ('power_sample_count', 'heart_rate_sample_count'):
        setattr(metrics, key, 0)
    for key in ('avg_power_w', 'max_power_w', 'normalized_power_w', 'normalized_power_raw_w', 'avg_hr_bpm'):
        setattr(metrics, key, None)
    ctx = _processor_context(ride_id=ride_id, ride_row={'id': str(ride_id)},
        preliminary_check=PreliminaryAttestationCheck(None, None, None, None, False),
        parsed_ride=_parsed_ride(start, start+timedelta(minutes=5), 'second.gpx'),
        metrics=metrics, identity=_identity())
    ctx.ride_attester.calculate_metrics.return_value = metrics
    result = await ctx.processor.process_ride(ride_id=ride_id, file_data_b64='ZmFrZQ==',
        file_type='gpx', user_id=user_id, file_bytes=b'fake')
    assert result['cal_earned'] == 0
    ctx.ride_economic_coordinator.freeze_plan.assert_not_awaited()
    ctx.ride_economic_coordinator.execute.assert_not_awaited()
    saved = ctx.ride_projection_store.update_ride_complete.await_args.kwargs
    assert saved['review_reason'] == 'effort_source_route_estimate_only'
    assert saved['effort_policy'].tributable_cal_base_units == 0
