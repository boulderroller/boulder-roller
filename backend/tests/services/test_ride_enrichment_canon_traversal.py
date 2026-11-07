from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.patterns import ClimbPattern
from app.services.canon_traversal import CanonTraversalEvaluation
from app.services.pattern_engine import PatternResults, VaultCompletion
from app.services.ride_enrichment_service import RideEnrichmentService
from app.services.sensor_integrity import SensorIntegrityReport


def _climb(*, start: int, end: int, road: str, detector_version: str) -> ClimbPattern:
    return ClimbPattern(
        id=uuid4(),
        activity_id=uuid4(),
        wallet="wallet-1",
        arena_id=None,
        vert_m=40.0,
        time_s=end - start,
        start_offset_s=start,
        end_offset_s=end,
        road_name=road,
        tile_ids=[f"tile-{road}"],
        detector_version=detector_version,
        match_trace={"canon_id": "canon-1"} if detector_version == "canon_traversal_v1" else None,
    )


class _PatternEngine:
    def __init__(self, results):
        self.results = results
        self.kwargs = None

    async def detect_patterns(self, **kwargs):
        self.kwargs = kwargs
        return self.results


class _CanonService:
    def __init__(self, evaluation):
        self.evaluation = evaluation
        self.kwargs = None

    async def evaluate_ride(self, **kwargs):
        self.kwargs = kwargs
        return self.evaluation


class _AttributionService:
    def __init__(self):
        self.calls = []

    async def get_climb_attribution(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "road_name": "Detector attribution",
            "road_grade": 5.0,
            "coverage_pct": 90.0,
            "attribution_summary": "Detector attribution",
        }


def _service(pattern_results, canon_evaluation):
    async def get_user_wallet(_user_id):
        return "wallet-1"

    async def get_wallet_tile_history(_wallet):
        return set()

    attribution = _AttributionService()
    canon = _CanonService(canon_evaluation)
    return (
        RideEnrichmentService(
            user_repo=SimpleNamespace(get_user_wallet=get_user_wallet),
            tile_repo=SimpleNamespace(get_wallet_tile_history=get_wallet_tile_history),
            pattern_engine=_PatternEngine(pattern_results),
            tile_attribution_service=attribution,
            climb_economy_processor=SimpleNamespace(),
            ride_projection_store=SimpleNamespace(),
            canon_traversal_service=canon,
        ),
        attribution,
        canon,
    )


@pytest.mark.asyncio
async def test_canon_traversal_replaces_overlapping_detector_but_preserves_off_canon_discovery():
    ride_id = uuid4()
    overlapping = _climb(start=20, end=40, road="overlap", detector_version="persistence")
    off_canon = _climb(start=150, end=200, road="offcanon", detector_version="persistence")
    canonical = _climb(start=15, end=50, road="Canon Hill", detector_version="canon_traversal_v1")
    canonical.activity_id = ride_id
    results = PatternResults(
        activity_id=ride_id,
        wallet="wallet-1",
        climb_patterns=[overlapping, off_canon],
        vault_completions=[
            VaultCompletion(
                vault_id=1,
                vault_name="stale-overlap",
                climb_pattern_id=overlapping.id,
                similarity=0.99,
                completion_time_s=overlapping.time_s,
            ),
            VaultCompletion(
                vault_id=2,
                vault_name="off-canon",
                climb_pattern_id=off_canon.id,
                similarity=0.99,
                completion_time_s=off_canon.time_s,
            ),
        ],
    )
    evaluation = CanonTraversalEvaluation(
        climb_patterns=[canonical],
        covered_intervals=[(10.0, 100.0)],
        considered_tile_ids={"canon-tile"},
    )
    service, attribution, canon = _service(results, evaluation)

    enriched = await service.detect_and_store_patterns(
        ride_id=ride_id,
        user_id=uuid4(),
        tile_samples=[{"t": 0.0, "tile_id": "canon-tile"}],
        raw_climb_samples=[
            {"t": 0.25, "lat": 40.0, "lon": -75.0, "tile_id": "canon-tile"},
            {"t": 1.75, "lat": 40.001, "lon": -75.0, "tile_id": "canon-tile"},
        ],
        user_weight_kg=72.0,
    )

    assert [climb.id for climb in enriched.climb_patterns] == [canonical.id, off_canon.id]
    assert canonical.road_name == "Canon Hill"
    assert attribution.calls == [{"tile_ids": off_canon.tile_ids, "vert_m": off_canon.vert_m}]
    assert enriched.vault_completions == []
    assert canon.kwargs["tile_samples"][0]["tile_id"] == "canon-tile"
    assert [sample["t"] for sample in canon.kwargs["raw_samples"]] == [0.25, 1.75]
    assert [sample["t"] for sample in service.pattern_engine.kwargs["raw_climb_samples"]] == [0, 1]
    assert all(
        isinstance(sample["t"], int)
        for sample in service.pattern_engine.kwargs["raw_climb_samples"]
    )
    assert all(
        isinstance(sample["power_w"], int)
        for sample in service.pattern_engine.kwargs["raw_climb_samples"]
        if sample.get("power_w") is not None
    )
    assert canon.kwargs["user_weight_kg"] == 72.0


@pytest.mark.asyncio
async def test_rejected_canon_window_still_suppresses_detector_identity_in_canon_geography():
    ride_id = uuid4()
    partial_detector = _climb(
        start=20,
        end=40,
        road="partial",
        detector_version="momentum",
    )
    off_canon = _climb(start=120, end=150, road="offcanon", detector_version="momentum")
    results = PatternResults(
        activity_id=ride_id,
        wallet="wallet-1",
        climb_patterns=[partial_detector, off_canon],
    )
    evaluation = CanonTraversalEvaluation(
        climb_patterns=[],
        covered_intervals=[(10.0, 80.0)],
        rejections={"partial_traversal": 1},
    )
    service, _, _ = _service(results, evaluation)

    enriched = await service.detect_and_store_patterns(
        ride_id=ride_id,
        user_id=uuid4(),
        tile_samples=[{"t": 0.0, "tile_id": "canon-tile"}],
        raw_climb_samples=[
            {"t": 0.0, "lat": 40.0, "lon": -75.0, "tile_id": "canon-tile"},
            {"t": 1.0, "lat": 40.001, "lon": -75.0, "tile_id": "canon-tile"},
        ],
    )

    assert [climb.id for climb in enriched.climb_patterns] == [off_canon.id]


@pytest.mark.asyncio
async def test_accepted_canon_traversal_inherits_sensor_abstention() -> None:
    ride_id = uuid4()
    canonical = _climb(
        start=0,
        end=60,
        road="Canon Hill",
        detector_version="canon_traversal_v1",
    )
    canonical.activity_id = ride_id
    canonical.abstention_reasons = ["MATCH:canon_activation_required"]
    canonical.economic_eligible = False
    results = PatternResults(
        activity_id=ride_id,
        wallet="wallet-1",
        sensor_integrity=SensorIntegrityReport(
            gps_coverage=0.0,
            elev_coverage=1.0,
            sample_count=60,
            power_coverage=1.0,
            integrity_score=0.35,
        ),
    )
    evaluation = CanonTraversalEvaluation(
        climb_patterns=[canonical],
        covered_intervals=[(0.0, 60.0)],
    )
    service, _, _ = _service(results, evaluation)

    enriched = await service.detect_and_store_patterns(
        ride_id=ride_id,
        user_id=uuid4(),
        tile_samples=[
            {"t": 0.0, "tile_id": "canon-tile", "elevation_m": 100.0},
            {"t": 60.0, "tile_id": "canon-tile", "elevation_m": 140.0},
        ],
        raw_climb_samples=[
            {"t": 0.0, "lat": None, "lon": None, "elevation_m": 100.0},
            {"t": 60.0, "lat": None, "lon": None, "elevation_m": 140.0},
        ],
    )

    assert enriched.climb_patterns == [canonical]
    assert canonical.economic_eligible is False
    assert "MATCH:canon_activation_required" in canonical.abstention_reasons
    assert "SENSOR:gps_coverage_0%" in canonical.abstention_reasons


@pytest.mark.asyncio
async def test_lossless_activity_integrity_counts_invalid_gps_outside_canon_window() -> None:
    ride_id = uuid4()
    canonical = _climb(
        start=10,
        end=14,
        road="Canon Hill",
        detector_version="canon_traversal_v1",
    )
    canonical.activity_id = ride_id
    canonical.abstention_reasons = ["MATCH:canon_activation_required"]
    canonical.economic_eligible = False
    results = PatternResults(activity_id=ride_id, wallet="wallet-1")
    evaluation = CanonTraversalEvaluation(
        climb_patterns=[canonical],
        covered_intervals=[(10.0, 14.0)],
    )
    service, _, _ = _service(results, evaluation)
    invalid = [
        {
            "t": float(index),
            "lat": None,
            "lon": None,
            "tile_id": "canon-tile",
            "elevation_m": 100.0,
            "power_w": 200.0,
        }
        for index in range(7)
    ]
    valid = [
        {
            "t": float(index),
            "lat": 40.0 + index / 100_000,
            "lon": -75.0,
            "tile_id": "canon-tile",
            "elevation_m": 100.0 + index,
            "power_w": 200.0,
        }
        for index in range(10, 15)
    ]

    enriched = await service.detect_and_store_patterns(
        ride_id=ride_id,
        user_id=uuid4(),
        tile_samples=valid,
        raw_climb_samples=invalid + valid,
    )

    assert enriched.sensor_integrity.sample_count == 12
    assert enriched.sensor_integrity.gps_coverage == pytest.approx(5 / 12)
    assert "SENSOR:gps_coverage_42%" in canonical.abstention_reasons


@pytest.mark.asyncio
async def test_lossless_activity_integrity_honors_explicit_invalid_untimed_gps() -> None:
    ride_id = uuid4()
    canonical = _climb(
        start=10,
        end=14,
        road="Canon Hill",
        detector_version="canon_traversal_v1",
    )
    canonical.activity_id = ride_id
    canonical.abstention_reasons = ["MATCH:canon_activation_required"]
    canonical.economic_eligible = False
    results = PatternResults(activity_id=ride_id, wallet="wallet-1")
    evaluation = CanonTraversalEvaluation(
        climb_patterns=[canonical],
        covered_intervals=[(10.0, 14.0)],
    )
    service, _, _ = _service(results, evaluation)
    untimed_invalid = [
        {
            "t": None,
            "lat": 39.9 + index / 100_000,
            "lon": -75.0,
            "tile_id": None,
            "elevation_m": 100.0,
            "power_w": 200.0,
            "gps_valid": False,
        }
        for index in range(7)
    ]
    timed_valid = [
        {
            "t": float(index),
            "lat": 40.0 + index / 100_000,
            "lon": -75.0,
            "tile_id": "canon-tile",
            "elevation_m": 100.0 + index,
            "power_w": 200.0,
            "gps_valid": True,
        }
        for index in range(10, 15)
    ]

    enriched = await service.detect_and_store_patterns(
        ride_id=ride_id,
        user_id=uuid4(),
        tile_samples=timed_valid,
        raw_climb_samples=untimed_invalid + timed_valid,
    )

    assert enriched.sensor_integrity.sample_count == 12
    assert enriched.sensor_integrity.gps_coverage == pytest.approx(5 / 12)
    assert "SENSOR:gps_coverage_42%" in canonical.abstention_reasons


class _UnreadableCanonService:
    def __init__(self, error):
        self.error = error

    async def evaluate_ride(self, **_kwargs):
        raise self.error


async def _detect_with_unreadable_canon(error):
    service, _attribution, _canon = _service(
        PatternResults(activity_id=uuid4(), wallet="wallet-1"), CanonTraversalEvaluation()
    )
    service.canon_traversal_service = _UnreadableCanonService(error)
    return await service.detect_and_store_patterns(
        ride_id=uuid4(),
        user_id=uuid4(),
        tile_samples=[{"t": 0.0, "tile_id": "canon-tile"}],
        raw_climb_samples=[{"t": 0.25, "lat": 40.0, "lon": -75.0, "tile_id": "canon-tile"}],
    )


@pytest.mark.asyncio
async def test_registry_change_mid_read_stays_retryable():
    from app.repositories.canon import CanonRegistryChanged

    moved = CanonRegistryChanged("registry changed during cell lookup; retry matching")
    with pytest.raises(CanonRegistryChanged) as raised:
        await _detect_with_unreadable_canon(moved)
    assert raised.value is moved


@pytest.mark.asyncio
async def test_registry_defect_surfaces_as_blocked_matching():
    from app.repositories.canon import CanonRegistryError
    from app.services.ride_enrichment_service import CanonMatchingBlocked

    # A defect never degrades to "no climbs on this ride"; it stops the ride.
    defect = CanonRegistryError("ratified canon has no corridor cells")
    with pytest.raises(CanonMatchingBlocked, match="ratified canon has no corridor cells") as raised:
        await _detect_with_unreadable_canon(defect)
    assert raised.value.__cause__ is defect
