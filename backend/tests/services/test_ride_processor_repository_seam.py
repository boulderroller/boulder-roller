from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.models.patterns import ClimbPattern
from app.repositories.ride import RideRepository
from app.services.canon_traversal import CanonTraversalEvaluation, CanonTraversalService
from app.services.pattern_engine import PatternResults
from app.services.ride_economic_coordinator import (
    CompletionStepDraft,
    RideEconomicOutcome,
)
from app.services.ride_processor import AUTHORITATIVE_METRICS_VERSION, RideProcessor


class _ShapeAwareRideQuery:
    def __init__(self, rows: dict[str, dict]) -> None:
        self.rows = rows
        self._selected: list[str] | None = None
        self._update: dict | None = None
        self._filters: list[tuple[str, object]] = []
        self._limit: int | None = None

    def select(self, columns: str):
        self._selected = [column.strip() for column in columns.split(",")]
        return self

    def update(self, payload: dict):
        self._update = dict(payload)
        return self

    def eq(self, column: str, value: object):
        self._filters.append((column, value))
        return self

    def limit(self, value: int):
        self._limit = value
        return self

    def execute(self):
        matching = [
            row
            for row in self.rows.values()
            if all(str(row.get(column)) == str(value) for column, value in self._filters)
        ]
        if self._update is not None:
            for row in matching:
                row.update(self._update)
        if self._limit is not None:
            matching = matching[: self._limit]
        if self._selected is not None:
            matching = [
                {column: row.get(column) for column in self._selected}
                for row in matching
            ]
        return SimpleNamespace(data=matching)


class _ShapeAwareRideClient:
    def __init__(self, rows: dict[str, dict]) -> None:
        self.rows = rows

    def table(self, name: str):
        assert name == "rides"
        return _ShapeAwareRideQuery(self.rows)


def _phase1_row(*, ride_id, user_id, tss: float) -> dict:
    completed_at = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=2)
    started_at = completed_at - timedelta(minutes=30)
    return {
        "id": str(ride_id),
        "user_id": str(user_id),
        "file_type": "fit",
        "processing_status": "processing",
        "tss": tss,
        "economic_tss": tss,
        "reward_ftp_w": 200,
        "reward_ftp_source": "network_default",
        "reward_ftp_authority_id": None,
        "reward_ftp_policy_version": "reward_ftp_policy_2026_07_14",
        "kcals": 500.0,
        "distance_m": 12_000.0,
        "elevation_gain_m": 300.0,
        "duration_sec": 1_800,
        "moving_time_sec": 1_800,
        "metrics_version": AUTHORITATIVE_METRICS_VERSION,
        "power_sample_count": 1_800,
        "power_sample_coverage_bps": 10_000,
        "heart_rate_sample_count": 1_800,
        "heart_rate_sample_coverage_bps": 10_000,
        "avg_power_w": 220.0,
        "normalized_power_w": 235.0,
        "normalized_power_raw_w": 235.125,
        "normalized_power_duration_s": 1_800,
        "avg_hr_bpm": 150.0,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "raw_file_path": "rides/test.fit",
        "effort_spans_ms": [[int(started_at.timestamp()*1000), int(completed_at.timestamp()*1000)]],
    }


async def _persist_phase1_identity(repo: RideRepository, ride_id) -> None:
    await repo.update_phase_status(
        ride_id=ride_id,
        phase=1,
        success=True,
        ride_hash_hex="ab" * 32,
        attestation_commitment_hex="cd" * 32,
        ride_parser_version=7,
        canonical_match=True,
        review_reason=None,
    )


def _processor(
    *,
    repo: RideRepository,
    projection_store: MagicMock,
    coordinator: MagicMock,
    enrichment_service: MagicMock | None = None,
    climb_economy_processor: MagicMock | None = None,
) -> RideProcessor:
    user_repo = MagicMock()
    user_repo.get_user_wallet = AsyncMock(return_value="wallet-1")
    terminal_projector = MagicMock()
    terminal_projector.project = AsyncMock(
        return_value=SimpleNamespace(
            status="projected",
            durable_checkpoint=True,
            cal_earned=0,
            error=None,
        )
    )
    with patch("app.services.ride_processor.get_supabase_client", return_value=MagicMock()):
        processor = RideProcessor(
            ride_repo=repo,
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
            ride_economic_terminal_projector=terminal_projector,
            ride_enrichment_service=enrichment_service,
            climb_economy_processor=climb_economy_processor,
        )
    processor.ride_economic_repository.get_effort_trim_basis = AsyncMock(return_value={"frozen": None, "covered_spans_ms": [], "covered_completion_windows": []})
    processor._publish_nats_event = AsyncMock()
    return processor


def test_canon_traversal_is_wired_into_default_production_enrichment() -> None:
    processor = _processor(
        repo=MagicMock(),
        projection_store=MagicMock(),
        coordinator=MagicMock(),
    )

    assert isinstance(processor.canon_traversal_service, CanonTraversalService)
    assert (
        processor.ride_enrichment_service.canon_traversal_service
        is processor.canon_traversal_service
    )


@pytest.mark.asyncio
async def test_real_phase1_projection_supplies_phase2_canonical_identity() -> None:
    ride_id = uuid4()
    user_id = uuid4()
    rows = {str(ride_id): _phase1_row(ride_id=ride_id, user_id=user_id, tss=84.0)}
    repo = RideRepository(_ShapeAwareRideClient(rows))
    repo._run = AsyncMock(side_effect=lambda func, operation="supabase": func())
    repo.get_gps_track = AsyncMock(return_value=[])
    await _persist_phase1_identity(repo, ride_id)

    projection_store = MagicMock()
    projection_store.build_sensor_lookup = AsyncMock(return_value=None)
    projection_store.load_canon_traversal_evidence = AsyncMock(return_value=None)
    projection_store.store_pattern_results = AsyncMock()
    coordinator = MagicMock()
    coordinator.freeze_plan = AsyncMock(
        return_value={
            "ride_id": str(ride_id),
            "state": "planned",
            "steps": [],
            "plan_evidence_hash_hex": "ef" * 32,
        }
    )
    processor = _processor(
        repo=repo,
        projection_store=projection_store,
        coordinator=coordinator,
    )
    processor.ride_economic_repository.register_threshold_provisional_hold = AsyncMock()

    result = await processor.process_phase2_enrichment(ride_id=ride_id, user_id=user_id)

    assert result["status"] == "enriched"
    coordinator.freeze_plan.assert_awaited_once()
    draft = coordinator.freeze_plan.await_args.args[0]
    assert draft.identity.ride_hash == bytes.fromhex("ab" * 32)
    assert draft.identity.attestation_commitment == bytes.fromhex("cd" * 32)
    assert draft.identity.parser_version == 7
    hold = draft.threshold_hold_evidence
    assert hold is not None
    hold_metrics = hold["metrics"]
    assert hold_metrics["normalized_power_raw_w"] == 235.125
    assert hold_metrics["normalized_power_duration_s"] == 1_800
    assert hold_metrics["avg_power_w"] == 220.0
    assert hold_metrics["power_sample_count"] == 1_800
    assert hold_metrics["power_sample_coverage_bps"] == 10_000
    assert hold_metrics["metrics_version"] == AUTHORITATIVE_METRICS_VERSION
    processor.ride_economic_repository.register_threshold_provisional_hold.assert_not_awaited()


@pytest.mark.asyncio
async def test_phase1_normalizes_absent_release_power_pair_to_null() -> None:
    ride_id = uuid4()
    user_id = uuid4()
    row = _phase1_row(ride_id=ride_id, user_id=user_id, tss=0.0)
    rows = {str(ride_id): row}
    repo = RideRepository(_ShapeAwareRideClient(rows))
    repo._run = AsyncMock(side_effect=lambda func, operation="supabase": func())

    await repo.update_phase_status(
        ride_id=ride_id,
        phase=1,
        success=True,
        normalized_power_raw_w=None,
        normalized_power_duration_s=0,
    )

    assert row["normalized_power_raw_w"] is None
    assert row["normalized_power_duration_s"] is None


@pytest.mark.asyncio
async def test_phased_zero_cal_ride_freezes_without_claiming_climb_steps() -> None:
    ride_id = uuid4()
    user_id = uuid4()
    row = _phase1_row(ride_id=ride_id, user_id=user_id, tss=0.0)
    rows = {str(ride_id): row}
    repo = RideRepository(_ShapeAwareRideClient(rows))
    repo._run = AsyncMock(side_effect=lambda func, operation="supabase": func())
    repo.get_gps_track = AsyncMock(
        return_value=[
            {
                "timestamp": row["started_at"],
                "latitude": 39.95,
                "longitude": -75.16,
                "elevation_m": 100.0,
            }
        ]
    )
    await _persist_phase1_identity(repo, ride_id)

    projection_store = MagicMock()
    projection_store.build_sensor_lookup = AsyncMock(return_value=None)
    canon_evidence = MagicMock()
    canon_evidence.raw_samples.return_value = [
        {
            "source_index": 0,
            "tile_id": "tile-1",
            "t": 0.625,
            "lat": 39.95,
            "lon": -75.16,
            "elevation_m": 100.0,
            "power_w": 220.0,
            "hr_bpm": 150.0,
            "speed_mps": 8.0,
            "gps_valid": True,
        }
    ]
    canon_evidence.record_points.return_value = [
        {
            "timestamp": datetime.fromisoformat(row["started_at"])
            + timedelta(seconds=0.625),
            "lat": 39.95,
            "lon": -75.16,
            "elevation_m": 100.0,
            "power_w": 220.0,
            "hr_bpm": 150.0,
            "speed_mps": 8.0,
        }
    ]
    projection_store.load_canon_traversal_evidence = AsyncMock(
        return_value=canon_evidence
    )
    projection_store.process_tile_projection = AsyncMock(
        return_value=(1, 1, [{"tile_id": "tile-1", "t": 0}])
    )
    projection_store.store_pattern_results = AsyncMock()
    canon_pattern = ClimbPattern(
        id=uuid4(),
        activity_id=ride_id,
        wallet="wallet-1",
        arena_id=None,
        vert_m=40.0,
        time_s=123,
        start_offset_s=1,
        end_offset_s=124,
        tile_ids=["tile-1"],
        economic_eligible=False,
        abstention_reasons=["MATCH:canon_activation_required"],
        match_trace={"canon_id": str(uuid4())},
        detector_version="canon_traversal_v1",
    )
    detector_results = PatternResults(
        activity_id=ride_id,
        wallet="wallet-1",
    )
    climb_processor = MagicMock()
    climb_processor.build_completion_plan = AsyncMock(
        return_value=(
            [
                CompletionStepDraft(
                    pattern_id=canon_pattern.id,
                    vault_id=9,
                    vault_signature="vault-9",
                    completion_time_s=123,
                    completed_at=datetime.fromisoformat(row["completed_at"]),
                    exact_tribute_base_units=0,
                    intensity_bps=10_000,
                    completion_evidence_hash=bytes.fromhex("ef" * 32),
                    completion_evidence_version=2,
                )
            ],
            [{"vault_id": 9, "vault_signature": "vault-9", "cal_tribute": 0}],
        )
    )
    coordinator = MagicMock()
    coordinator.freeze_plan = AsyncMock(
        return_value={"ride_id": str(ride_id), "state": "planned", "steps": [{}]}
    )
    coordinator.execute = AsyncMock(
        return_value=RideEconomicOutcome(
            status="complete",
            state="complete",
            durable_checkpoint=True,
            ride_attestation_pda="attestation-pda",
            completion_count=1,
        )
    )
    processor = _processor(
        repo=repo,
        projection_store=projection_store,
        coordinator=coordinator,
        climb_economy_processor=climb_processor,
    )
    processor.tile_repo.get_wallet_tile_history = AsyncMock(return_value=set())
    processor.ride_enrichment_service.pattern_engine = SimpleNamespace(
        detect_patterns=AsyncMock(return_value=detector_results)
    )
    processor.canon_traversal_service.evaluate_ride = AsyncMock(
        return_value=CanonTraversalEvaluation(
            climb_patterns=[canon_pattern],
            covered_intervals=[(1.0, 124.0)],
            considered_tile_ids={"tile-1"},
        )
    )
    processor.tile_service = MagicMock()
    processor.tile_service.get_tile_sequence.return_value = [
        SimpleNamespace(
            tile_id="tile-1",
            t=0.625,
            lat=39.95,
            lon=-75.16,
            elevation_m=100.0,
            power_w=220.0,
            hr_bpm=150.0,
            speed_mps=8.0,
        )
    ]
    processor.ride_economic_repository = MagicMock()
    processor.ride_economic_repository.get_effort_trim_basis = AsyncMock(return_value={"frozen": None, "covered_spans_ms": [], "covered_completion_windows": []})
    processor.ride_economic_repository.get_plan = AsyncMock(
        return_value={
            "wallet": "wallet-1",
            "exact_cal_base_units": 0,
            "reward_policy": "rewardable",
            "review_reason": None,
            "state": "planned",
            "steps": [],
        }
    )
    projection_store.get_pattern_results_from_db = AsyncMock(return_value=detector_results)
    processor.achievement_detector.detect_achievements = AsyncMock(return_value=[])
    processor.analytics_service.update_daily_aggregates = AsyncMock()
    processor._emit_ride_finalized_notification = AsyncMock()

    result = await processor.process_phase2_enrichment(ride_id=ride_id, user_id=user_id)

    assert result["status"] == "enriched"
    assert (
        processor.canon_traversal_service.evaluate_ride.await_args.kwargs[
            "raw_samples"
        ][0]["t"]
        == 0.625
    )
    assert (
        processor.ride_enrichment_service.canon_traversal_service
        is processor.canon_traversal_service
    )
    repo.get_gps_track.assert_not_awaited()
    coordinator.freeze_plan.assert_awaited_once()
    draft = coordinator.freeze_plan.await_args.args[0]
    assert draft.exact_cal_base_units == 0
    assert draft.completion_steps == []
    assert draft.effort_trim.paid_ms == []
    climb_processor.build_completion_plan.assert_not_awaited()

    phase3 = await processor.process_phase3_rewards(ride_id=ride_id, user_id=user_id)
    assert phase3["status"] == "completed"
    assert phase3["cal_earned"] == 0
    coordinator.execute.assert_awaited_once_with(ride_id)
    processor.ride_economic_terminal_projector.project.assert_awaited_once_with(
        ride_id
    )


@pytest.mark.asyncio
async def test_phase2_stale_coverage_exhausts_three_attempts():
    from app.repositories.ride_economic import StaleEffortCoverageError
    ride_id, user_id = uuid4(), uuid4()
    rows = {str(ride_id): _phase1_row(ride_id=ride_id, user_id=user_id, tss=84)}
    repo = RideRepository(_ShapeAwareRideClient(rows))
    repo._run = AsyncMock(side_effect=lambda func, operation='supabase': func())
    repo.get_gps_track = AsyncMock(return_value=[])
    await _persist_phase1_identity(repo, ride_id)
    store = MagicMock()
    store.build_sensor_lookup = AsyncMock(return_value=None)
    store.load_canon_traversal_evidence = AsyncMock(return_value=None)
    store.store_pattern_results = AsyncMock()
    coordinator = MagicMock()
    coordinator.freeze_plan = AsyncMock(side_effect=StaleEffortCoverageError('stale_effort_coverage'))
    coordinator.execute = AsyncMock()
    processor = _processor(repo=repo, projection_store=store, coordinator=coordinator)
    result = await processor.process_phase2_enrichment(ride_id=ride_id, user_id=user_id)
    assert result['status'] == 'phase2_failed'
    assert coordinator.freeze_plan.await_count == 3
    assert processor.ride_economic_repository.get_effort_trim_basis.await_count == 3
    coordinator.execute.assert_not_awaited()

@pytest.mark.asyncio
async def test_phase2_missing_raw_file_routes_needed_trim_to_review():
    ride_id,user_id=uuid4(),uuid4()
    row=_phase1_row(ride_id=ride_id,user_id=user_id,tss=84)
    row['raw_file_path']=None
    rows={str(ride_id):row}
    repo=RideRepository(_ShapeAwareRideClient(rows))
    repo._run=AsyncMock(side_effect=lambda func,operation='supabase':func())
    repo.get_gps_track=AsyncMock(return_value=[])
    await _persist_phase1_identity(repo,ride_id)
    store=MagicMock();store.build_sensor_lookup=AsyncMock(return_value=None)
    store.load_canon_traversal_evidence=AsyncMock(return_value=None)
    store.store_pattern_results=AsyncMock()
    coordinator=MagicMock();coordinator.freeze_plan=AsyncMock()
    processor=_processor(repo=repo,projection_store=store,coordinator=coordinator)
    start,end=row['effort_spans_ms'][0]
    processor.ride_economic_repository.get_effort_trim_basis.return_value={'frozen':None,'covered_spans_ms':[(start,start+1000)],'covered_completion_windows':[]}
    await processor.process_phase2_enrichment(ride_id=ride_id,user_id=user_id)
    assert row['processing_status']=='under_review'
    assert row['review_reason']=='paid_effort_evidence_unavailable'
    assert row['cal_earned']==0
    coordinator.freeze_plan.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("registry_defect", [True, False])
async def test_phase2_fails_the_ride_only_when_the_canon_registry_is_unreadable(registry_defect):
    from app.services.ride_enrichment_service import CanonMatchingBlocked

    ride_id, user_id = uuid4(), uuid4()
    row = _phase1_row(ride_id=ride_id, user_id=user_id, tss=84)
    repo = RideRepository(_ShapeAwareRideClient({str(ride_id): row}))
    repo._run = AsyncMock(side_effect=lambda func, operation="supabase": func())
    repo.get_gps_track = AsyncMock(return_value=[
        {"latitude": 40.0, "longitude": -75.0, "timestamp": row["started_at"]},
    ])
    await _persist_phase1_identity(repo, ride_id)
    store = MagicMock()
    store.build_sensor_lookup = AsyncMock(return_value=None)
    store.load_canon_traversal_evidence = AsyncMock(return_value=None)
    store.process_tile_projection = AsyncMock(return_value=(1, 1, [{"tile_id": "tile-a", "t": 0}]))
    store.store_pattern_results = AsyncMock()
    coordinator = MagicMock()
    coordinator.freeze_plan = AsyncMock()
    enrichment = MagicMock()
    enrichment.detect_and_store_patterns = AsyncMock(side_effect=(
        CanonMatchingBlocked("canon registry defect: ratified canon has no corridor cells")
        if registry_defect else RuntimeError("canon registry read timed out")
    ))
    processor = _processor(repo=repo, projection_store=store, coordinator=coordinator,
                           enrichment_service=enrichment)

    result = await processor.process_phase2_enrichment(ride_id=ride_id, user_id=user_id)

    enrichment.detect_and_store_patterns.assert_awaited_once()
    coordinator.freeze_plan.assert_not_awaited()
    assert result["status"] == "phase2_failed"
    assert row["phase2_error"].startswith("detect_and_store_patterns: ")
    # A defect recurs on every redelivery: the ride fails visibly instead.
    assert result["retryable"] is (not registry_defect)
    assert row["processing_status"] == ("failed" if registry_defect else "metrics_ready")
