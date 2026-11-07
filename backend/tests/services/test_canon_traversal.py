from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from shapely import from_wkt
from shapely.geometry import LineString, Point

from app.models.canon import CanonClimb
from app.services.canon_traversal import (
    BACKTRACK_JITTER_TOLERANCE_M,
    CanonTraversalEngine,
    _continuity_aware_progress,
    _normalize_samples,
)
from app.services.climb_economy_processor import ClimbEconomyProcessor


ACTIVITY_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
CANON_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
REGISTRY_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
TILE_ID = "8a2a1342b5a7fff"


def _canon() -> CanonClimb:
    return CanonClimb(
        registry_id=REGISTRY_ID,
        canon_id=CANON_ID,
        version=3,
        display_name="Test Hill: lower gate to upper gate",
        route_name="Test Hill",
        centerline=LineString([(-75.0, 40.0), (-75.0, 40.001)]),
        corridor=from_wkt(
            "MULTIPOLYGON (((-75.00025 39.9999, -74.99975 39.9999, "
            "-74.99975 40.0011, -75.00025 40.0011, -75.00025 39.9999)))"
        ),
        gate_start=LineString([(-75.0003, 40.0001), (-74.9997, 40.0001)]),
        gate_end=LineString([(-75.0003, 40.0009), (-74.9997, 40.0009)]),
        canonical_profile=(
            {"dist_m": 0.0, "elev_m": 10.0},
            {"dist_m": 50.0, "elev_m": 18.0},
            {"dist_m": 100.0, "elev_m": 30.0},
        ),
        length_m=100.0,
        vert_m=20.0,
        avg_gradient_pct=20.0,
        compiler_version="canon-compile-v0.2.3",
        profile_hash_algorithm="blake3_canonical_profile_v1",
        profile_hash="ab" * 32,
        odbl_source="OpenStreetMap contributors",
        corridor_tile_ids=(TILE_ID,),
    )


def _sample(t: float, progress: float, *, inside: bool = True, **extra) -> dict:
    sample = {
        "t": t,
        "lat": 40.0 + progress * 0.001,
        "lon": -75.0 if inside else -75.0005,
        "tile_id": TILE_ID,
        # Deliberately contradict the canon profile. Rider barometry must not
        # become the economic elevation authority.
        "elevation_m": 900.0 - progress * 400.0,
        "power_w": 280.0,
        "hr_bpm": 160,
    }
    sample.update(extra)
    return sample


def _evaluate(samples: list[dict]):
    return CanonTraversalEngine().evaluate(
        activity_id=ACTIVITY_ID,
        wallet="wallet-1",
        candidates=[_canon()],
        raw_samples=samples,
        user_weight_kg=70.0,
    )


def test_normalization_preserves_attested_parser_source_indices():
    normalized, _, _ = _normalize_samples(
        [
            _sample(0.0, 0.0, source_index=4),
            _sample(1.0, 0.1, source_index=9),
        ]
    )

    assert [sample.source_index for sample in normalized] == [4, 9]


def test_pattern_identity_binds_the_exact_registry_snapshot():
    samples = [
        _sample(0.0, 0.00),
        _sample(5.0, 0.20),
        _sample(10.0, 0.40),
        _sample(15.0, 0.60),
        _sample(20.0, 0.80),
        _sample(25.0, 1.00),
    ]
    first = replace(_canon(), registry_snapshot_digest="sha256:" + "11" * 32)
    second = replace(_canon(), registry_snapshot_digest="sha256:" + "22" * 32)
    engine = CanonTraversalEngine()

    first_result = engine.evaluate(
        activity_id=ACTIVITY_ID,
        wallet="wallet-1",
        candidates=[first],
        raw_samples=samples,
    )
    second_result = engine.evaluate(
        activity_id=ACTIVITY_ID,
        wallet="wallet-1",
        candidates=[second],
        raw_samples=samples,
    )

    assert first_result.climb_patterns[0].id != second_result.climb_patterns[0].id


def test_forward_traversal_interpolates_gates_dedupes_endpoint_and_uses_canon_metrics():
    samples = [
        _sample(0.0, 0.00),
        _sample(2.0, 0.10),  # exactly on start gate
        _sample(5.0, 0.20),  # adjacent segment also touches start gate
        _sample(10.0, 0.30),
        _sample(15.0, 0.40),
        _sample(20.0, 0.50),
        _sample(25.0, 0.60),
        _sample(30.0, 0.70),
        _sample(35.0, 1.00),  # finish crossing is 2/3 through this segment
    ]

    result = _evaluate(samples)

    assert result.rejections == {}
    assert len(result.climb_patterns) == 1
    climb = result.climb_patterns[0]
    assert climb.vert_m == 20.0
    assert climb.distance_m == 100.0
    assert climb.avg_gradient_pct == 20.0
    assert climb.avg_power_w == 280.0
    assert climb.w_per_kg == 4.0
    assert climb.avg_hr == 160
    assert climb.start_offset_s == 2
    assert climb.end_offset_s == 33
    assert climb.time_s == 31
    assert climb.start_lat == pytest.approx(40.0001)
    assert climb.end_lat == pytest.approx(40.0009)
    assert climb.road_name == "Test Hill"
    assert climb.detector_version == "canon_traversal_v1"
    assert climb.signature_hex is None
    assert climb.signature_v2_hex is None
    assert climb.economic_eligible is False
    assert climb.abstention_reasons == ["MATCH:canon_activation_required"]

    trace = climb.match_trace
    assert trace["canon_id"] == str(CANON_ID)
    assert trace["registry_id"] == str(REGISTRY_ID)
    assert trace["canon_version"] == 3
    assert trace["gate_crossings"]["start_time_s_raw"] == pytest.approx(2.0, abs=2e-5)
    assert trace["gate_crossings"]["finish_time_s_raw"] == pytest.approx(
        33.333333, abs=2e-5
    )
    assert trace["corridor_coverage"] == {
        "inside_count": 6,
        "intermediate_count": 6,
        "ratio": 1.0,
        "threshold": 0.8,
        "malformed_coordinate_count": 0,
    }
    assert trace["canonical_profile_hash"] == {
        "algorithm": "blake3_canonical_profile_v1",
        "value": "ab" * 32,
    }
    assert trace["odbl_source"] == "OpenStreetMap contributors"
    assert trace["pass_index"] == 1
    assert trace["pass_count"] == 1
    assert trace["best_for_canon"] is True
    assert climb.to_dict()["match_trace"] == trace


@pytest.mark.asyncio
async def test_real_canon_traversal_stays_pending_until_exact_finalized_binding() -> None:
    result = _evaluate(
        [
            _sample(0.0, 0.00),
            _sample(2.0, 0.10),
            _sample(5.0, 0.20),
            _sample(10.0, 0.30),
            _sample(15.0, 0.40),
            _sample(20.0, 0.50),
            _sample(25.0, 0.60),
            _sample(30.0, 0.70),
            _sample(35.0, 1.00),
        ]
    )
    climb = result.climb_patterns[0]
    assert climb.economic_eligible is False
    assert climb.abstention_reasons == ["MATCH:canon_activation_required"]
    vault_repo = MagicMock()
    vault_repo.find_canon_vault_binding = AsyncMock(
        return_value={
            "id": 42,
            "name": "Canonical Vault",
            "canon_climb_id": str(REGISTRY_ID),
            "canon_id": str(CANON_ID),
            "canon_version": 3,
            "canonical_profile_hash_hex": "ab" * 32,
                "canon_binding_status": "active",
                "canon_activation_status": "finalized",
                "expected_vault_activation_pda": "vault-activation-pda",
                "vault_activation_pda": "vault-activation-pda",
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
                "polyline_json": [],
        }
    )
    processor = ClimbEconomyProcessor(
        user_repo=MagicMock(),
        vault_repo=vault_repo,
        vault_service=MagicMock(),
        ride_executor=MagicMock(),
        projection_writer=MagicMock(),
    )

    await processor.match_climbs_to_vault(
        climb_patterns=[climb],
        tile_samples=[],
        user_id=uuid4(),
        user_wallet="wallet-1",
        ride_id=ACTIVITY_ID,
        completed_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
        ride_hash=None,
    )

    assert climb.economic_eligible is True
    assert climb.abstention_reasons == []
    assert climb.indexed_vault_id == 42


def test_reverse_and_partial_traversals_do_not_produce_a_climb():
    reverse = [
        _sample(0.0, 1.00),
        _sample(5.0, 0.80),
        _sample(10.0, 0.60),
        _sample(15.0, 0.40),
        _sample(20.0, 0.20),
        _sample(25.0, 0.00),
    ]
    partial = [
        _sample(0.0, 0.00),
        _sample(5.0, 0.20),
        _sample(10.0, 0.40),
        _sample(15.0, 0.60),
    ]

    reverse_result = _evaluate(reverse)
    partial_result = _evaluate(partial)

    assert reverse_result.climb_patterns == []
    assert reverse_result.rejections["reverse_direction"] >= 1
    assert partial_result.climb_patterns == []
    assert partial_result.rejections == {"partial_traversal": 1}


@pytest.mark.parametrize(
    ("inside_flags", "accepted"),
    [
        ([True, True, True, True, False], True),
        ([True, True, True, False, False], False),
    ],
)
def test_corridor_coverage_threshold_is_inclusive_at_eighty_percent(
    inside_flags: list[bool], accepted: bool
):
    samples = [_sample(0.0, 0.00), _sample(5.0, 0.10)]
    samples.extend(
        _sample(t, progress, inside=inside)
        for t, progress, inside in zip(
            [10.0, 15.0, 20.0, 25.0, 30.0],
            [0.30, 0.40, 0.50, 0.60, 0.70],
            inside_flags,
        )
    )
    samples.append(_sample(35.0, 1.00))

    result = _evaluate(samples)

    assert bool(result.climb_patterns) is accepted
    if accepted:
        assert result.climb_patterns[0].match_trace["corridor_coverage"]["ratio"] == 0.8
    else:
        assert result.rejections == {"corridor_coverage_below_threshold": 1}


def test_small_progress_jitter_is_tolerated_but_a_real_u_turn_is_rejected():
    jitter_progress_m = BACKTRACK_JITTER_TOLERANCE_M / 2.0
    jitter_progress = jitter_progress_m / 111.0
    accepted = [
        _sample(0.0, 0.00),
        _sample(5.0, 0.20),
        _sample(10.0, 0.35),
        _sample(15.0, 0.60),
        _sample(20.0, 0.60 - jitter_progress),
        _sample(25.0, 0.70),
        _sample(30.0, 0.80),
        _sample(35.0, 1.00),
    ]
    rejected = [
        _sample(0.0, 0.00),
        _sample(5.0, 0.20),
        _sample(10.0, 0.40),
        _sample(15.0, 0.70),
        _sample(20.0, 0.38),
        _sample(25.0, 0.50),
        _sample(30.0, 0.75),
        _sample(35.0, 1.00),
    ]

    accepted_result = _evaluate(accepted)
    rejected_result = _evaluate(rejected)

    assert len(accepted_result.climb_patterns) == 1
    monotonic = accepted_result.climb_patterns[0].match_trace["monotonic_progress"]
    assert monotonic["accepted"] is True
    assert monotonic["backtrack_tolerance_m"] == BACKTRACK_JITTER_TOLERANCE_M
    assert rejected_result.climb_patterns == []
    assert rejected_result.rejections == {"u_turn": 1}


def test_repeated_passes_are_separate_and_fastest_is_explicitly_selected():
    first_ascent = [
        _sample(0.0, 0.00),
        _sample(5.0, 0.20),
        _sample(10.0, 0.35),
        _sample(15.0, 0.50),
        _sample(20.0, 0.65),
        _sample(25.0, 0.75),
        _sample(35.0, 1.00),
    ]
    descent = [
        _sample(40.0, 0.75),
        _sample(45.0, 0.40),
        _sample(50.0, 0.00),
    ]
    faster_ascent = [
        _sample(55.0, 0.20),
        _sample(58.0, 0.35),
        _sample(61.0, 0.50),
        _sample(64.0, 0.65),
        _sample(67.0, 0.75),
        _sample(73.0, 1.00),
    ]

    result = _evaluate(first_ascent + descent + faster_ascent)

    assert len(result.climb_patterns) == 2
    first, second = result.climb_patterns
    assert first.start_offset_s < second.start_offset_s
    assert first.match_trace["pass_index"] == 1
    assert second.match_trace["pass_index"] == 2
    assert first.match_trace["pass_count"] == 2
    assert second.match_trace["pass_count"] == 2
    assert first.match_trace["best_for_canon"] is False
    assert second.match_trace["best_for_canon"] is True
    assert result.best_per_canon[str(CANON_ID)].id == second.id
    assert second.time_s < first.time_s


def test_exact_canon_coverage_does_not_span_a_ride_exit_and_reentry():
    result = _evaluate(
        [
            _sample(0.0, 0.50),
            _sample(1.0, 0.51),
            _sample(10.0, 0.52, inside=False),
            _sample(11.0, 0.53, inside=False),
            _sample(20.0, 0.54),
            _sample(21.0, 0.55),
        ]
    )

    assert result.covered_intervals == [(0.0, 1.0), (20.0, 21.0)]
    assert result.overlaps_canon_coverage(10.0, 11.0) is False


def test_malformed_timed_gps_points_count_outside_the_corridor_and_fail_closed():
    samples = [
        _sample(0.0, 0.00),
        _sample(5.0, 0.10),
        _sample(10.0, 0.30),
        {"t": 12.0, "lat": None, "lon": -75.0, "tile_id": TILE_ID},
        _sample(15.0, 0.40),
        {"t": 18.0, "lat": None, "lon": -75.0, "tile_id": TILE_ID},
        _sample(20.0, 0.50),
        _sample(25.0, 0.60),
        _sample(30.0, 0.70),
        _sample(35.0, 1.00),
    ]

    result = _evaluate(samples)

    assert result.climb_patterns == []
    assert result.rejections == {
        "corridor_coverage_below_threshold": 1,
        "malformed_sample": 2,
    }


def test_touching_and_riding_around_a_gate_endpoint_is_not_a_crossing():
    samples = [
        _sample(0.0, 0.00, lon=-75.0003),
        _sample(5.0, 0.10, lon=-75.0003),  # finite gate endpoint
        _sample(10.0, 0.00, lon=-75.00031),  # returns to the original side
        _sample(15.0, 0.20, lon=-75.00031),  # changes sides outside the finite line
        _sample(20.0, 0.30),
        _sample(25.0, 0.40),
        _sample(30.0, 0.50),
        _sample(35.0, 0.60),
        _sample(40.0, 0.70),
        _sample(45.0, 1.00),
    ]

    result = _evaluate(samples)

    assert result.climb_patterns == []
    assert result.rejections["gate_touch_without_crossing"] >= 1


def test_side_to_side_pass_through_exact_gate_endpoint_is_a_crossing():
    samples = [
        _sample(0.0, 0.00, lon=-75.0003),
        _sample(5.0, 0.10, lon=-75.0003),  # exact finite endpoint
        _sample(10.0, 0.20, lon=-75.0003),
        _sample(15.0, 0.30),
        _sample(20.0, 0.40),
        _sample(25.0, 0.50),
        _sample(30.0, 0.60),
        _sample(35.0, 0.70),
        _sample(40.0, 1.00),
    ]

    result = _evaluate(samples)

    assert len(result.climb_patterns) == 1
    assert (
        result.climb_patterns[0].match_trace["gate_crossings"]["start"][
            "direction_evidence"
        ]["endpoint_policy"]
        == "inclusive"
    )


def test_slow_exact_on_gate_pass_counts_when_progress_is_below_half_a_meter():
    progress_for_point_two_m = 0.20 / 111.0
    samples = [
        _sample(0.0, 0.10 - progress_for_point_two_m),
        _sample(1.0, 0.10),
        _sample(2.0, 0.10 + progress_for_point_two_m),
        _sample(10.0, 0.30),
        _sample(15.0, 0.40),
        _sample(20.0, 0.50),
        _sample(25.0, 0.60),
        _sample(30.0, 0.70),
        _sample(35.0, 1.00),
    ]

    result = _evaluate(samples)

    assert len(result.climb_patterns) == 1


def test_continuity_projection_follows_a_valid_close_hairpin_after_skipped_apex():
    centerline = LineString([(0, 0), (100, 0), (100, 6), (0, 6)])
    points = [
        Point(80, 0),
        Point(80, 6),
        Point(60, 6),
        Point(40, 6),
    ]

    assert _continuity_aware_progress(centerline, points) == pytest.approx(
        [80.0, 126.0, 146.0, 166.0]
    )


def test_equal_whole_second_repeats_are_both_marked_best_without_fractional_tiebreak():
    first = [
        _sample(0.0, 0.00),
        _sample(1.0, 0.10),
        _sample(5.0, 0.25),
        _sample(10.0, 0.40),
        _sample(15.0, 0.55),
        _sample(20.0, 0.70),
        _sample(25.0, 0.80),
        _sample(31.6, 0.90),
        _sample(32.0, 1.00),
    ]
    descent = [_sample(40.0, 0.70), _sample(45.0, 0.00)]
    second = [
        _sample(50.0, 0.10),
        _sample(55.0, 0.25),
        _sample(60.0, 0.40),
        _sample(65.0, 0.55),
        _sample(70.0, 0.70),
        _sample(75.0, 0.80),
        _sample(81.4, 0.90),
        _sample(82.0, 1.00),
    ]

    result = _evaluate(first + descent + second)

    assert [pattern.time_s for pattern in result.climb_patterns] == [31, 31]
    assert [
        pattern.match_trace["best_for_canon"]
        for pattern in result.climb_patterns
    ] == [True, True]
    assert [
        pattern.match_trace["best_representative"]
        for pattern in result.climb_patterns
    ] == [True, False]
    assert result.best_per_canon[str(CANON_ID)].id == result.climb_patterns[0].id


@pytest.mark.asyncio
async def test_service_runs_the_matcher_off_the_event_loop() -> None:
    import threading

    from app.services.canon_traversal import CanonTraversalService

    # Seconds of geometry per ride must not stall the API or the ack heartbeat.
    loop_thread = threading.get_ident()
    engine = CanonTraversalEngine()
    evaluate = engine.evaluate
    threads = []

    def recording_evaluate(**kwargs):
        threads.append(threading.get_ident())
        return evaluate(**kwargs)

    engine.evaluate = recording_evaluate
    repository = MagicMock()
    repository.load_ratified_for_tiles = AsyncMock(return_value=[_canon()])
    samples = [_sample(t, t / 35.0) for t in (0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0)]

    result = await CanonTraversalService(repository, engine).evaluate_ride(
        activity_id=ACTIVITY_ID, wallet="wallet-1", tile_samples=samples, raw_samples=samples,
    )

    assert threads and threads[0] != loop_thread
    assert len(result.climb_patterns) == 1
    repository.load_ratified_for_tiles.assert_awaited_once_with([TILE_ID])
