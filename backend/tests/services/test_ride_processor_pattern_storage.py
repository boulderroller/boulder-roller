from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock, Mock, call

import pytest

from app.services.pattern_engine import PatternResults
from app.services.ride_enrichment_service import RideEnrichmentService
from app.services.ride_projection_store import RideProjectionStore


def _fake_climb(activity_id, wallet: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        activity_id=activity_id,
        wallet=wallet,
        vert_m=109.8,
        time_s=3130,
        start_offset_s=0,
        end_offset_s=3130,
        arena_id=None,
        avg_power_w=None,
        w_per_kg=None,
        avg_hr=None,
        road_name="Bryn Mawr Avenue",
        road_grade=None,
        road_coverage_pct=None,
        attribution_summary=None,
        tile_ids=["abc"],
        distance_m=20472.0,
        avg_gradient_pct=0.5,
        signature_hex="sig-v1",
        signature_v2_hex="sig-v2",
        persistence_m=None,
        significance_g=None,
        significance_percentile=None,
        significance_return_period=None,
        significance_confidence_tier=None,
        significance_bootstrapped=None,
        significance_cell_h3=None,
        start_lat=None,
        start_lon=None,
        end_lat=None,
        end_lon=None,
        economic_eligible=True,
        abstention_reasons=[],
        match_trace=None,
        detector_version="test",
    )


@pytest.mark.asyncio
async def test_store_pattern_results_rewrites_activity_patterns_before_insert():
    activity_id = uuid4()
    clear_patterns = AsyncMock()
    store_climb = AsyncMock()
    pattern_repo = SimpleNamespace(
        clear_patterns_for_activity=clear_patterns,
        store_climb_pattern=store_climb,
        store_steady_pattern=AsyncMock(),
        store_exploration_pattern=AsyncMock(),
    )
    call_order = Mock()
    call_order.attach_mock(clear_patterns, "clear_patterns_for_activity")
    call_order.attach_mock(store_climb, "store_climb_pattern")
    projection_store = RideProjectionStore(
        ride_repo=SimpleNamespace(),
        tile_repo=SimpleNamespace(),
        pattern_repo=pattern_repo,
        user_repo=SimpleNamespace(),
        client=SimpleNamespace(),
        tile_service=SimpleNamespace(),
    )

    results = PatternResults(
        activity_id=activity_id,
        wallet="wallet-1",
        climb_patterns=[_fake_climb(activity_id, "wallet-1")],
    )

    await projection_store.store_pattern_results(results)

    pattern_repo.clear_patterns_for_activity.assert_awaited_once_with(activity_id)
    pattern_repo.store_climb_pattern.assert_awaited_once()
    assert call_order.mock_calls[:2] == [
        call.clear_patterns_for_activity(activity_id),
        call.store_climb_pattern(
            pattern_id=results.climb_patterns[0].id,
            activity_id=activity_id,
            wallet="wallet-1",
            vert_m=109.8,
            time_s=3130,
            start_offset_s=0,
            end_offset_s=3130,
            arena_id=None,
            avg_power_w=None,
            w_per_kg=None,
            avg_hr=None,
            road_name="Bryn Mawr Avenue",
            road_grade=None,
            road_coverage_pct=None,
            attribution_summary=None,
            tile_ids=["abc"],
            distance_m=20472.0,
            avg_gradient_pct=0.5,
            signature_hex="sig-v1",
            signature_v2_hex="sig-v2",
            persistence_m=None,
            significance_g=None,
            significance_percentile=None,
            significance_return_period=None,
            significance_confidence_tier=None,
            significance_bootstrapped=None,
            significance_cell_h3=None,
            start_lat=None,
            start_lon=None,
            end_lat=None,
            end_lon=None,
            economic_eligible=True,
            abstention_reasons=[],
            match_trace=None,
            detector_version="test",
        ),
    ]


@pytest.mark.asyncio
async def test_reconstructed_pattern_results_preserve_climbs_crossed():
    activity_id = uuid4()
    pattern_repo = SimpleNamespace(
        get_patterns_for_activity=AsyncMock(
            return_value={
                "climb_patterns": [
                    {
                        "id": str(uuid4()),
                        "activity_id": str(activity_id),
                        "wallet": "wallet-1",
                        "arena_id": None,
                        "vert_m": 109.8,
                        "time_s": 3130,
                        "start_offset_s": 0,
                        "end_offset_s": 3130,
                        "signature_hex": "ab" * 32,
                        "economic_eligible": True,
                    }
                ],
                "steady_pattern": None,
                "exploration_pattern": None,
            }
        )
    )
    ride_repo = SimpleNamespace(
        get_ride=AsyncMock(return_value={"user_id": str(uuid4())})
    )
    user_repo = SimpleNamespace(get_user_wallet=AsyncMock(return_value="wallet-1"))
    projection_store = RideProjectionStore(
        ride_repo=ride_repo,
        tile_repo=SimpleNamespace(),
        pattern_repo=pattern_repo,
        user_repo=user_repo,
        client=SimpleNamespace(),
        tile_service=SimpleNamespace(),
    )

    reconstructed = await projection_store.get_pattern_results_from_db(activity_id)

    assert reconstructed is not None
    assert len(reconstructed.climb_patterns) == 1
    assert reconstructed.climb_patterns[0].signature_hex == "ab" * 32


@pytest.mark.asyncio
async def test_store_pattern_results_preserves_canon_traversal_evidence_unchanged():
    activity_id = uuid4()
    store_climb = AsyncMock()
    projection_store = RideProjectionStore(
        ride_repo=SimpleNamespace(),
        tile_repo=SimpleNamespace(),
        pattern_repo=SimpleNamespace(
            clear_patterns_for_activity=AsyncMock(),
            store_climb_pattern=store_climb,
            store_steady_pattern=AsyncMock(),
            store_exploration_pattern=AsyncMock(),
        ),
        user_repo=SimpleNamespace(),
        client=SimpleNamespace(),
        tile_service=SimpleNamespace(),
    )
    climb = _fake_climb(activity_id, "wallet-1")
    climb.start_offset_s = 12
    climb.end_offset_s = 73
    climb.time_s = 61
    climb.vert_m = 82.4
    climb.distance_m = 701.2
    climb.avg_gradient_pct = 11.75
    climb.start_lat = 40.01
    climb.start_lon = -75.21
    climb.end_lat = 40.02
    climb.end_lon = -75.20
    climb.signature_hex = None
    climb.signature_v2_hex = None
    climb.economic_eligible = False
    climb.abstention_reasons = ["MATCH:canon_activation_required"]
    climb.detector_version = "canon_traversal_v1"
    climb.match_trace = {
        "trace_version": "canon_traversal_trace_v1",
        "canon_id": "22222222-2222-4222-8222-222222222222",
        "canon_version": 3,
        "gate_crossings": {
            "start_time_s_raw": 12.25,
            "finish_time_s_raw": 73.10,
        },
    }

    await projection_store.store_pattern_results(
        PatternResults(
            activity_id=activity_id,
            wallet="wallet-1",
            climb_patterns=[climb],
        )
    )

    stored = store_climb.await_args.kwargs
    assert stored["time_s"] == 61
    assert stored["start_offset_s"] == 12
    assert stored["end_offset_s"] == 73
    assert stored["vert_m"] == 82.4
    assert stored["distance_m"] == 701.2
    assert stored["avg_gradient_pct"] == 11.75
    assert stored["start_lat"] == 40.01
    assert stored["start_lon"] == -75.21
    assert stored["end_lat"] == 40.02
    assert stored["end_lon"] == -75.20
    assert stored["signature_hex"] is None
    assert stored["signature_v2_hex"] is None
    assert stored["economic_eligible"] is False
    assert stored["abstention_reasons"] == ["MATCH:canon_activation_required"]
    assert stored["match_trace"] == climb.match_trace
    assert stored["detector_version"] == "canon_traversal_v1"


@pytest.mark.asyncio
async def test_review_path_stores_retained_detector_climbs_as_discovery_only():
    activity_id = uuid4()
    store_climb = AsyncMock()
    projection_store = RideProjectionStore(
        ride_repo=SimpleNamespace(),
        tile_repo=SimpleNamespace(),
        pattern_repo=SimpleNamespace(
            clear_patterns_for_activity=AsyncMock(),
            store_climb_pattern=store_climb,
            store_steady_pattern=AsyncMock(),
            store_exploration_pattern=AsyncMock(),
        ),
        user_repo=SimpleNamespace(),
        client=SimpleNamespace(),
        tile_service=SimpleNamespace(),
    )
    detector = _fake_climb(activity_id, "wallet-1")
    detector.start_offset_s = 0
    detector.end_offset_s = 10
    detector.economic_eligible = True
    detector.abstention_reasons = []
    detector.detector_version = "climb_detector_v2"
    detector.match_trace = {
        "registry_id": str(uuid4()),
        "canon_id": str(uuid4()),
        "canon_version": 2,
        "detector_similarity": 0.97,
    }
    canonical = _fake_climb(activity_id, "wallet-1")
    canonical.start_offset_s = 20
    canonical.end_offset_s = 30
    canonical.detector_version = "canon_traversal_v1"
    canonical.economic_eligible = False
    canonical.abstention_reasons = ["MATCH:canon_activation_required"]
    canonical.match_trace = {
        "registry_id": str(uuid4()),
        "canon_id": str(uuid4()),
        "canon_version": 2,
        "profile_hash": "ab" * 32,
    }
    canonical_trace = canonical.match_trace.copy()
    results = PatternResults(
        activity_id=activity_id,
        wallet="wallet-1",
        climb_patterns=[detector],
        vault_completions=[SimpleNamespace(climb_pattern_id=detector.id)],
    )
    evaluation = SimpleNamespace(
        climb_patterns=[canonical],
        overlaps_canon_coverage=lambda _start, _end: False,
    )

    # Under-review rides skip economic-plan freezing but still persist this
    # reconciled result through RideProjectionStore.
    RideEnrichmentService._reconcile_canon_traversals(results, evaluation)
    await projection_store.store_pattern_results(results)

    assert detector.economic_eligible is False
    assert "MATCH:canon_traversal_required" in detector.abstention_reasons
    assert detector.match_trace["authority"] == "discovery_only"
    assert not {
        "registry_id",
        "canon_id",
        "canon_version",
    }.issubset(detector.match_trace)
    assert canonical.abstention_reasons == ["MATCH:canon_activation_required"]
    assert canonical.match_trace == canonical_trace
    assert results.vault_completions == []

    stored_by_detector = {
        call.kwargs["detector_version"]: call.kwargs
        for call in store_climb.await_args_list
    }
    assert stored_by_detector["climb_detector_v2"]["economic_eligible"] is False
    assert "MATCH:canon_traversal_required" in stored_by_detector[
        "climb_detector_v2"
    ]["abstention_reasons"]
    assert stored_by_detector["climb_detector_v2"]["match_trace"][
        "authority"
    ] == "discovery_only"
    assert stored_by_detector["canon_traversal_v1"]["match_trace"] == canonical_trace
