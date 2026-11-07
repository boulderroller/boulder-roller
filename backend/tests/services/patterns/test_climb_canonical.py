import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.services.patterns.climb import (
    ClimbCandidate,
    ClimbPattern,
    RideQualityProfile,
    _choose_canonical_v2_climbs,
    _bridge_neutral_match_confirms_raw_persistence,
    _h2_power_confirmation_bonus,
    _h9_roller_filter_bonus,
    _h10_isolation_bonus,
    _h12_frequency_prior_bonus,
    _partition_raw_persistence_candidates,
    _convert_rust_climbs_to_patterns,
    _run_rust_detector,
    _score_terrain_result,
    _score_climb_candidate,
    detect_climbs_with_rust,
)
from app.services.patterns.climb_profile import RideClimbProfile, build_ride_climb_profile


def make_climb(
    start_s: int,
    end_s: int,
    *,
    vert_m: float,
    gradient_pct: float,
    distance_m: float = 1200.0,
) -> ClimbPattern:
    return ClimbPattern(
        vert_m=vert_m,
        time_s=end_s - start_s,
        start_time_offset_s=start_s,
        end_time_offset_s=end_s,
        avg_gradient_pct=gradient_pct,
        distance_m=distance_m,
    )


def make_quality_profile(
    *,
    source_class: str = "native_dense",
    integrity_score: float = 0.95,
    sparse_sampling: bool = False,
    degraded_gps: bool = False,
    degraded_elevation: bool = False,
) -> RideQualityProfile:
    return RideQualityProfile(
        source_class=source_class,
        integrity_score=integrity_score,
        gps_coverage=0.98,
        elev_coverage=0.99,
        median_interval_s=1.0 if not sparse_sampling else 6.0,
        sampling_regularity=0.98,
        gap_ratio=0.0 if not sparse_sampling else 0.18,
        gps_jump_count=0 if not degraded_gps else 2,
        sparse_sampling=sparse_sampling,
        degraded_gps=degraded_gps,
        degraded_elevation=degraded_elevation,
        flags=[],
    )


class TestCanonicalClimbSelection:
    def test_momentum_conversion_preserves_exact_reward_grade_evidence(self):
        rust_climb = type(
            "RustClimb",
            (),
            {
                "vert_m": 60.0,
                "time_s": 300,
                "avg_power_w": 240.0,
                "w_per_kg": 3.2,
                "avg_hr": 155,
                "start_time_offset_s": 100,
                "end_time_offset_s": 400,
                "arena_id": None,
                "tile_ids": ["tile-a"],
                "avg_gradient_pct": 6.0,
                "distance_m": 1000.0,
                "signature_hex": "ab" * 64,
                "signature_v2_hex": "cd" * 64,
                "start_lat": 39.9500,
                "start_lon": -75.1600,
                "end_lat": 39.9550,
                "end_lon": -75.1600,
            },
        )()

        climbs = _convert_rust_climbs_to_patterns(
            [rust_climb],
            sample_source=[{"t": 0, "elevation_m": 100.0}],
            algorithm="momentum",
            user_weight_kg=75.0,
        )

        assert climbs[0].signature_v2_hex == "cd" * 64
        assert climbs[0].start_lat == 39.9500
        assert climbs[0].start_lon == -75.1600
        assert climbs[0].end_lat == 39.9550
        assert climbs[0].end_lon == -75.1600

    def test_persistence_indices_use_rust_filtered_sorted_sample_space(self):
        samples = [
            {"t": 30, "elevation_m": 130.0, "marker": "third"},
            {"t": 10, "elevation_m": 110.0, "marker": "first-equal"},
            {"t": 20, "elevation_m": None, "marker": "missing-elevation"},
            {"t": 15, "elevation_m": True, "marker": "boolean-elevation"},
            {"t": 10, "elevation_m": 111.0, "marker": "second-equal"},
            {"t": 40, "elevation_m": 140.0, "marker": "fourth"},
            {
                "t": 2**63,
                "elevation_m": 150.0,
                "marker": "out-of-i64-range",
            },
        ]

        rust_result = [
            type(
                "RustClimb",
                (),
                {
                    "vert_m": 20.0,
                    "time_s": 20,
                    "avg_power_w": None,
                    "avg_hr": None,
                    "effort_start_idx": 1,
                    "effort_end_idx": 2,
                    "tile_ids": [],
                    "avg_gradient_pct": 5.0,
                    "distance_m": 400.0,
                    "signature_v1_hex": None,
                    "signature_v2_hex": None,
                    "start_lat": None,
                    "start_lon": None,
                    "end_lat": None,
                    "end_lon": None,
                    "persistence": 20.0,
                },
            )()
        ]

        class FakeWorkoutParse:
            received_samples = None

            def detect_climbs_persistence(self, *, tile_samples, user_weight_kg):
                self.received_samples = tile_samples
                return rust_result

        workout_parse = FakeWorkoutParse()
        climbs = _run_rust_detector(
            workout_parse,
            tile_samples=samples,
            persistence_candidate_samples=None,
            terrain="auto",
            config_overrides=None,
            arena_tiles=None,
            user_weight_kg=None,
            algorithm="persistence",
            generate_signatures=True,
        )

        assert [sample["marker"] for sample in workout_parse.received_samples] == [
            "first-equal",
            "second-equal",
            "third",
            "fourth",
        ]
        assert climbs[0].start_time_offset_s == 10
        assert climbs[0].end_time_offset_s == 30

    def test_score_terrain_result_penalizes_low_grade_drags(self):
        clean_efforts = [
            make_climb(1320, 1500, vert_m=58.0, gradient_pct=6.8, distance_m=900.0),
            make_climb(3905, 4200, vert_m=46.0, gradient_pct=4.6, distance_m=1160.0),
        ]
        low_grade_noise = clean_efforts + [
            make_climb(1200, 4320, vert_m=72.0, gradient_pct=1.4, distance_m=5200.0),
            make_climb(4500, 5850, vert_m=24.0, gradient_pct=1.3, distance_m=2400.0),
        ]

        assert _score_terrain_result(clean_efforts) > _score_terrain_result(low_grade_noise)

    def test_score_terrain_result_rewards_compact_real_set(self):
        sparse_set = [make_climb(1600, 2050, vert_m=22.0, gradient_pct=2.1, distance_m=1450.0)]
        compact_real_set = [
            make_climb(1320, 1500, vert_m=58.0, gradient_pct=6.8, distance_m=900.0),
            make_climb(3905, 4200, vert_m=46.0, gradient_pct=4.6, distance_m=1160.0),
        ]

        assert _score_terrain_result(compact_real_set) > _score_terrain_result(sparse_set)

    def test_detect_climbs_with_rust_canonical_sweeps_and_selects(self):
        samples = [{"t": i * 10, "elevation_m": 100.0 + i} for i in range(500)]
        terrain_results = {
            "auto": [
                make_climb(1300, 1510, vert_m=54.0, gradient_pct=6.1, distance_m=930.0),
                make_climb(3300, 3600, vert_m=18.0, gradient_pct=1.5, distance_m=1500.0),
            ],
            "urban_hills": [
                make_climb(1325, 1495, vert_m=57.0, gradient_pct=7.0, distance_m=880.0)
            ],
            "hilly": [
                make_climb(1320, 1500, vert_m=58.0, gradient_pct=6.8, distance_m=900.0),
                make_climb(3905, 4200, vert_m=46.0, gradient_pct=4.6, distance_m=1160.0),
            ],
        }

        with patch("app.services.patterns.climb._get_workout_parse", return_value=object()):
            with patch(
                "app.services.patterns.climb._run_rust_detector",
                side_effect=lambda *_args, **kwargs: terrain_results[kwargs["terrain"]],
            ):
                climbs = detect_climbs_with_rust(samples, algorithm="canonical")

        assert len(climbs) == 2
        assert climbs[0].start_time_offset_s == 1320
        assert climbs[1].start_time_offset_s == 3905

    def test_detect_climbs_with_rust_persistence_prefers_raw_candidate_samples(self):
        tile_runs = [{"t": 120, "tile_id": "tile-a", "elevation_m": 100.0}]
        raw_tile_samples = [{"t": 45, "tile_id": "tile-a", "elevation_m": 95.0}]
        persistence_result = [
            type(
                "RustClimb",
                (),
                {
                    "vert_m": 42.0,
                    "time_s": 180,
                    "avg_power_w": None,
                    "avg_hr": None,
                    "effort_start_idx": 0,
                    "effort_end_idx": 0,
                    "tile_ids": ["tile-a"],
                    "avg_gradient_pct": 6.0,
                    "distance_m": 700.0,
                    "signature_v1_hex": None,
                    "signature_v2_hex": None,
                    "start_lat": None,
                    "start_lon": None,
                    "end_lat": None,
                    "end_lon": None,
                    "persistence": 42.0,
                },
            )()
        ]

        with patch("app.services.patterns.climb._get_workout_parse", return_value=object()):
            with patch(
                "app.services.patterns.climb._run_rust_detector",
                return_value=[
                    make_climb(45, 225, vert_m=42.0, gradient_pct=6.0, distance_m=700.0)
                ],
            ) as run_detector:
                climbs = detect_climbs_with_rust(
                    tile_runs,
                    persistence_candidate_samples=raw_tile_samples,
                    algorithm="persistence",
                )

        assert len(climbs) == 1
        assert climbs[0].start_time_offset_s == 45
        run_detector.assert_called_once()
        assert (
            run_detector.call_args.kwargs["persistence_candidate_samples"] == raw_tile_samples
        )

    def test_detect_climbs_with_rust_persistence_normalizes_datetime_sample_offsets(self):
        base = datetime(2026, 6, 12, 18, 0, tzinfo=timezone.utc)
        tile_runs = [
            {
                "t": base + timedelta(seconds=offset),
                "tile_id": "tile-a",
                "elevation_m": 100.0 + idx,
                "lat": 39.0,
                "lon": -75.0,
            }
            for idx, offset in enumerate((0, 45, 225))
        ]
        persistence_result = [
            type(
                "RustClimb",
                (),
                {
                    "vert_m": 42.0,
                    "time_s": 180,
                    "avg_power_w": None,
                    "avg_hr": None,
                    "effort_start_idx": 1,
                    "effort_end_idx": 2,
                    "tile_ids": ["tile-a"],
                    "avg_gradient_pct": 6.0,
                    "distance_m": 700.0,
                    "signature_v1_hex": None,
                    "signature_v2_hex": None,
                    "start_lat": None,
                    "start_lon": None,
                    "end_lat": None,
                    "end_lon": None,
                    "persistence": 42.0,
                },
            )()
        ]

        class FakeWorkoutParse:
            def detect_climbs_persistence(self, **_kwargs):
                return persistence_result

        with patch("app.services.patterns.climb._get_workout_parse", return_value=FakeWorkoutParse()):
            climbs = detect_climbs_with_rust(tile_runs, algorithm="persistence")

        assert len(climbs) == 1
        assert climbs[0].start_time_offset_s == 45
        assert climbs[0].end_time_offset_s == 225

    def test_detect_climbs_with_rust_canonical_v2_normalizes_datetime_offsets_across_detectors(self):
        base = datetime(2026, 6, 12, 18, 0, tzinfo=timezone.utc)
        samples = [
            {
                "t": base + timedelta(seconds=i * 10),
                "tile_id": "tile-a",
                "elevation_m": 100.0 + (i * 1.6),
                "lat": 39.0 + (i * 0.00001),
                "lon": -75.0,
                "power_w": 240,
            }
            for i in range(80)
        ]

        class FakeTerrainResult:
            def to_dict(self):
                return {
                    "class": "hilly",
                    "confidence": 0.9,
                    "metrics": {"total_gain_m": 126.0},
                }

        class FakeWorkoutParse:
            def classify_terrain(self, tile_samples):
                assert isinstance(tile_samples[0]["t"], (int, float))
                return FakeTerrainResult()

            def detect_climbs_adaptive(self, **_kwargs):
                return [
                    type(
                        "RustMomentumClimb",
                        (),
                        {
                            "vert_m": 72.0,
                            "time_s": 240,
                            "avg_power_w": 250.0,
                            "w_per_kg": 3.6,
                            "avg_hr": 158,
                            "start_time_offset_s": base + timedelta(seconds=100),
                            "end_time_offset_s": base + timedelta(seconds=340),
                            "arena_id": None,
                            "tile_ids": ["tile-a"],
                            "avg_gradient_pct": 7.2,
                            "distance_m": 1000.0,
                            "signature_hex": None,
                        },
                    )()
                ]

            def detect_climbs_persistence(self, **_kwargs):
                return [
                    type(
                        "RustPersistenceClimb",
                        (),
                        {
                            "vert_m": 74.0,
                            "time_s": 240,
                            "avg_power_w": None,
                            "avg_hr": None,
                            "effort_start_idx": 10,
                            "effort_end_idx": 34,
                            "tile_ids": ["tile-a"],
                            "avg_gradient_pct": 7.4,
                            "distance_m": 1000.0,
                            "signature_v1_hex": None,
                            "signature_v2_hex": None,
                            "start_lat": None,
                            "start_lon": None,
                            "end_lat": None,
                            "end_lon": None,
                            "persistence": 74.0,
                        },
                    )()
                ]

        with patch("app.services.patterns.climb._get_workout_parse", return_value=FakeWorkoutParse()):
            climbs = detect_climbs_with_rust(samples, algorithm="canonical_v2")

        assert len(climbs) == 1
        assert isinstance(climbs[0].start_time_offset_s, int)
        assert isinstance(climbs[0].end_time_offset_s, int)
        assert climbs[0].start_time_offset_s == 100
        assert climbs[0].end_time_offset_s == 340
        assert climbs[0].route_profile is not None

    def test_detect_climbs_with_rust_canonical_v2_prefers_corroborated_best_candidate(self):
        samples = [{"t": i * 10, "elevation_m": 100.0 + i, "lat": 39.0, "lon": -75.0} for i in range(500)]
        momentum_auto = [make_climb(1320, 1500, vert_m=42.0, gradient_pct=4.5, distance_m=930.0)]
        momentum_hilly = [make_climb(1310, 1490, vert_m=45.0, gradient_pct=4.9, distance_m=910.0)]
        persistence = [make_climb(1180, 1520, vert_m=76.0, gradient_pct=6.8, distance_m=1110.0)]
        persistence[0].persistence = 72.0

        with patch("app.services.patterns.climb._get_workout_parse", return_value=object()):
            with patch(
                "app.services.patterns.climb._run_canonical_momentum_sweep",
                return_value=(
                    {"auto": momentum_auto, "hilly": momentum_hilly},
                    "hilly",
                    momentum_hilly,
                ),
            ):
                with patch(
                    "app.services.patterns.climb._run_rust_detector",
                    return_value=persistence,
                ):
                    with patch(
                        "app.services.patterns.climb.RideQualityProfile.from_tile_samples",
                        return_value=make_quality_profile(),
                    ):
                        climbs = detect_climbs_with_rust(samples, algorithm="canonical_v2")

        assert len(climbs) == 1
        assert climbs[0].start_time_offset_s == 1180
        assert climbs[0].detector_mode == "canonical_v2:persistence"
        assert climbs[0].proposal_sources == ["momentum:auto", "momentum:hilly", "persistence"]
        assert climbs[0].confidence is not None
        assert climbs[0].route_profile is not None

    def test_detect_climbs_with_rust_canonical_v2_confirms_raw_persistence_candidate_samples(self):
        corrected_samples = [
            {"t": i * 10, "elevation_m": 100.0 + i, "lat": 39.0, "lon": -75.0}
            for i in range(20)
        ]
        raw_candidate_samples = [
            {"t": i * 10, "elevation_m": 95.0 + i, "lat": 39.0, "lon": -75.0}
            for i in range(20)
        ]

        with patch("app.services.patterns.climb._get_workout_parse", return_value=object()):
            with patch(
                "app.services.patterns.climb._run_canonical_momentum_sweep",
                return_value=({}, None, []),
            ):
                with patch(
                    "app.services.patterns.climb._run_rust_detector",
                    return_value=[],
                ) as run_detector:
                    detect_climbs_with_rust(
                        corrected_samples,
                        persistence_candidate_samples=raw_candidate_samples,
                        algorithm="canonical_v2",
                    )

        assert run_detector.call_count == 2
        assert (
            run_detector.call_args_list[0].kwargs["persistence_candidate_samples"]
            == raw_candidate_samples
        )
        assert run_detector.call_args_list[1].kwargs["persistence_candidate_samples"] is None

    def test_detect_climbs_with_rust_canonical_v2_penalizes_sparse_marginal_single_source(self):
        samples = [{"t": i * 20, "elevation_m": 100.0 + i, "lat": 39.0, "lon": -75.0} for i in range(500)]
        momentum_auto = [make_climb(1320, 1530, vert_m=55.0, gradient_pct=6.0, distance_m=920.0)]
        persistence = [make_climb(1380, 1470, vert_m=22.0, gradient_pct=2.2, distance_m=420.0)]
        persistence[0].persistence = 12.0

        with patch("app.services.patterns.climb._get_workout_parse", return_value=object()):
            with patch(
                "app.services.patterns.climb._run_canonical_momentum_sweep",
                return_value=({"auto": momentum_auto}, "auto", momentum_auto),
            ):
                with patch(
                    "app.services.patterns.climb._run_rust_detector",
                    return_value=persistence,
                ):
                    with patch(
                        "app.services.patterns.climb.RideQualityProfile.from_tile_samples",
                        return_value=make_quality_profile(
                            source_class="sparse_reconstructed",
                            integrity_score=0.58,
                            sparse_sampling=True,
                            degraded_elevation=True,
                        ),
                    ):
                        climbs = detect_climbs_with_rust(samples, algorithm="canonical_v2")

        assert len(climbs) == 1
        assert climbs[0].start_time_offset_s == 1320
        assert climbs[0].detector_mode == "canonical_v2:momentum:auto"
        assert climbs[0].route_profile is not None

    def test_canonical_v2_suppresses_sparse_low_gradient_sub_60m_clutter(self):
        ride_quality = make_quality_profile(
            source_class="sparse_reconstructed",
            integrity_score=0.85,
            sparse_sampling=True,
        )
        ride_profile = RideClimbProfile(points=[], total_distance_m=9000.0)

        small_low_grade = make_climb(
            1000,
            1300,
            vert_m=55.0,
            gradient_pct=1.7,
            distance_m=3200.0,
        )
        small_low_grade.persistence = 48.0
        small_low_grade_momentum = make_climb(
            1010,
            1290,
            vert_m=52.0,
            gradient_pct=1.6,
            distance_m=3100.0,
        )

        longer_shoulder = make_climb(
            2200,
            2650,
            vert_m=62.0,
            gradient_pct=1.8,
            distance_m=3400.0,
        )
        longer_shoulder.persistence = 60.0
        longer_shoulder_momentum = make_climb(
            2210,
            2640,
            vert_m=61.0,
            gradient_pct=1.8,
            distance_m=3350.0,
        )

        selected = _choose_canonical_v2_climbs(
            ride_quality=ride_quality,
            ride_profile=ride_profile,
            momentum_results={
                "auto": [small_low_grade_momentum, longer_shoulder_momentum],
            },
            persistence_climbs=[small_low_grade, longer_shoulder],
        )

        assert len(selected) == 1
        assert selected[0].start_time_offset_s == 2200
        assert selected[0].vert_m == 62.0
        assert "sparse_low_gradient_suppression" not in (
            selected[0].confidence_reasons or []
        )

    def test_canonical_v2_applies_momentum_urban_micro_climb_display_floor(self):
        ride_quality = make_quality_profile()
        ride_profile = RideClimbProfile(points=[], total_distance_m=9000.0)
        urban_micro = make_climb(
            1000,
            1090,
            vert_m=28.0,
            gradient_pct=6.2,
            distance_m=452.0,
        )

        selected = _choose_canonical_v2_climbs(
            ride_quality=ride_quality,
            ride_profile=ride_profile,
            momentum_results={"urban_hills": [urban_micro]},
            persistence_climbs=[],
        )

        assert selected == []

        persistence_micro = make_climb(
            995,
            1100,
            vert_m=30.0,
            gradient_pct=5.9,
            distance_m=508.0,
        )
        persistence_micro.persistence = 29.0

        corroborated = _choose_canonical_v2_climbs(
            ride_quality=ride_quality,
            ride_profile=ride_profile,
            momentum_results={"urban_hills": [urban_micro]},
            persistence_climbs=[persistence_micro],
        )

        assert len(corroborated) == 1
        assert "persistence" in (corroborated[0].detector_mode or "")
        assert set(corroborated[0].proposal_sources or []) == {
            "momentum:urban_hills",
            "persistence",
        }

    def test_canonical_v2_blocks_unconfirmed_raw_persistence_seed(self):
        ride_quality = make_quality_profile()
        ride_profile = RideClimbProfile(points=[], total_distance_m=9000.0)
        weak_momentum = make_climb(
            600, 720, vert_m=12.0, gradient_pct=2.0, distance_m=600.0
        )
        raw_persistence = make_climb(
            580, 740, vert_m=55.0, gradient_pct=5.5, distance_m=1000.0
        )
        raw_persistence.persistence = 50.0

        selected = _choose_canonical_v2_climbs(
            ride_quality=ride_quality,
            ride_profile=ride_profile,
            momentum_results={"auto": [weak_momentum]},
            persistence_climbs=[raw_persistence],
            persistence_confirmation_climbs=[],
        )

        assert selected == []

    def test_canonical_v2_allows_raw_persistence_seed_with_bridge_neutral_match(self):
        ride_quality = make_quality_profile()
        ride_profile = RideClimbProfile(points=[], total_distance_m=9000.0)
        weak_momentum = make_climb(
            600, 720, vert_m=12.0, gradient_pct=2.0, distance_m=600.0
        )
        raw_persistence = make_climb(
            580, 740, vert_m=55.0, gradient_pct=5.5, distance_m=1000.0
        )
        raw_persistence.persistence = 50.0
        bridge_neutral_match = make_climb(
            590, 735, vert_m=44.0, gradient_pct=4.8, distance_m=920.0
        )
        bridge_neutral_match.persistence = 35.0

        selected = _choose_canonical_v2_climbs(
            ride_quality=ride_quality,
            ride_profile=ride_profile,
            momentum_results={"auto": [weak_momentum]},
            persistence_climbs=[raw_persistence],
            persistence_confirmation_climbs=[bridge_neutral_match],
        )

        assert len(selected) == 1
        assert selected[0].detector_mode == "canonical_v2:persistence"
        assert "bridge_neutral_persistence_match" in (
            selected[0].confidence_reasons or []
        )

    def test_raw_persistence_bridge_match_requires_corrected_climb_shape(self):
        ride_quality = make_quality_profile()
        ride_profile = RideClimbProfile(points=[], total_distance_m=9000.0)
        raw_candidate = ClimbCandidate(
            climb=make_climb(
                6952, 7024, vert_m=35.7, gradient_pct=6.2, distance_m=572.0
            ),
            source="persistence",
            family="persistence",
            ride_quality=ride_quality,
        )
        short_bridge_match = make_climb(
            6952, 7024, vert_m=35.7, gradient_pct=6.2, distance_m=572.0
        )
        low_grade_bridge_match = make_climb(
            5681, 6037, vert_m=52.5, gradient_pct=2.02, distance_m=2603.0
        )
        better_bridge_match_for_low_grade_candidate = make_climb(
            5681, 6037, vert_m=58.0, gradient_pct=2.6, distance_m=2230.0
        )
        confirmed_bridge_match = make_climb(
            6476, 6770, vert_m=50.9, gradient_pct=2.7, distance_m=1991.0
        )

        assert not _bridge_neutral_match_confirms_raw_persistence(
            raw_candidate,
            short_bridge_match,
            ride_profile,
        )

        raw_candidate.climb = make_climb(
            5681, 6037, vert_m=52.6, gradient_pct=2.02, distance_m=2603.0
        )
        assert not _bridge_neutral_match_confirms_raw_persistence(
            raw_candidate,
            low_grade_bridge_match,
            ride_profile,
        )
        assert not _bridge_neutral_match_confirms_raw_persistence(
            raw_candidate,
            better_bridge_match_for_low_grade_candidate,
            ride_profile,
        )

        raw_candidate.climb = make_climb(
            6476, 6770, vert_m=50.9, gradient_pct=2.7, distance_m=1991.0
        )
        assert _bridge_neutral_match_confirms_raw_persistence(
            raw_candidate,
            confirmed_bridge_match,
            ride_profile,
        )

    def test_canonical_v2_blocks_short_raw_persistence_seed_despite_bridge_match(self):
        ride_quality = make_quality_profile()
        ride_profile = RideClimbProfile(points=[], total_distance_m=9000.0)
        raw_persistence = make_climb(
            6952, 7024, vert_m=35.7, gradient_pct=6.2, distance_m=572.0
        )
        raw_persistence.persistence = 35.0
        bridge_neutral_match = make_climb(
            6952, 7024, vert_m=35.7, gradient_pct=6.2, distance_m=572.0
        )
        bridge_neutral_match.persistence = 35.0

        selected = _choose_canonical_v2_climbs(
            ride_quality=ride_quality,
            ride_profile=ride_profile,
            momentum_results={},
            persistence_climbs=[raw_persistence],
            persistence_confirmation_climbs=[bridge_neutral_match],
        )

        assert selected == []

    def test_canonical_v2_allows_raw_persistence_seed_with_corrected_profile_support(self):
        ride_quality = make_quality_profile()
        ride_profile = build_ride_climb_profile(
            [
                {"t": 540, "elevation_m": 100.0, "speed_mps": 5.0},
                {"t": 580, "elevation_m": 100.0, "speed_mps": 5.0},
                {"t": 640, "elevation_m": 121.0, "speed_mps": 5.0},
                {"t": 700, "elevation_m": 144.0, "speed_mps": 5.0},
                {"t": 740, "elevation_m": 155.0, "speed_mps": 5.0},
                {"t": 780, "elevation_m": 155.0, "speed_mps": 5.0},
            ]
        )
        weak_momentum = make_climb(
            600, 720, vert_m=12.0, gradient_pct=2.0, distance_m=600.0
        )
        raw_persistence = make_climb(
            580, 740, vert_m=55.0, gradient_pct=5.5, distance_m=1000.0
        )
        raw_persistence.persistence = 50.0

        selected = _choose_canonical_v2_climbs(
            ride_quality=ride_quality,
            ride_profile=ride_profile,
            momentum_results={"auto": [weak_momentum]},
            persistence_climbs=[raw_persistence],
            persistence_confirmation_climbs=[],
        )

        assert len(selected) == 1
        assert selected[0].detector_mode == "canonical_v2:persistence"
        assert "bridge_neutral_profile_support" in (
            selected[0].confidence_reasons or []
        )

    def test_canonical_v2_uses_unconfirmed_raw_persistence_as_weak_momentum_support(self):
        ride_quality = make_quality_profile()
        ride_profile = build_ride_climb_profile(
            [
                {"t": 80, "elevation_m": 100.0, "speed_mps": 6.5},
                {"t": 100, "elevation_m": 100.0, "speed_mps": 6.5},
                {"t": 180, "elevation_m": 118.0, "speed_mps": 6.5},
                {"t": 260, "elevation_m": 140.0, "speed_mps": 6.5},
                {"t": 340, "elevation_m": 145.0, "speed_mps": 6.5},
            ]
        )
        marginal_momentum = make_climb(
            100, 320, vert_m=35.0, gradient_pct=2.9, distance_m=1207.0
        )
        raw_persistence = make_climb(
            95, 335, vert_m=45.0, gradient_pct=2.0, distance_m=2250.0
        )
        raw_persistence.persistence = 45.0

        without_raw_support = _choose_canonical_v2_climbs(
            ride_quality=ride_quality,
            ride_profile=ride_profile,
            momentum_results={"auto": [marginal_momentum]},
            persistence_climbs=[],
            persistence_confirmation_climbs=[],
        )
        selected = _choose_canonical_v2_climbs(
            ride_quality=ride_quality,
            ride_profile=ride_profile,
            momentum_results={"auto": [marginal_momentum]},
            persistence_climbs=[raw_persistence],
            persistence_confirmation_climbs=[],
        )

        assert without_raw_support == []
        assert len(selected) == 1
        assert selected[0].detector_mode == "canonical_v2:momentum:auto"
        assert "weak_raw_persistence_support" in (
            selected[0].confidence_reasons or []
        )
        assert "raw_persistence_unconfirmed" not in (
            selected[0].confidence_reasons or []
        )

        raw_candidate = ClimbCandidate(
            climb=raw_persistence,
            source="persistence",
            family="persistence",
            ride_quality=ride_quality,
        )
        confirmed, weak_support = _partition_raw_persistence_candidates(
            [raw_candidate],
            persistence_confirmation_climbs=[],
            ride_profile=ride_profile,
        )
        assert confirmed == []
        assert weak_support == [raw_candidate]
        assert raw_candidate.selectable is False
        assert "support_only_raw_persistence" in raw_candidate.reasons

    def test_score_climb_candidate_applies_tiny_momentum_consensus_epsilon(self):
        ride_quality = make_quality_profile(
            integrity_score=0.90,
            sparse_sampling=True,
        )
        tile_samples = [
            {"t": 0, "elevation_m": 100.0},
            {"t": 20, "elevation_m": 100.0},
            {"t": 40, "elevation_m": 100.0},
            {"t": 60, "elevation_m": 100.0},
            {"t": 80, "elevation_m": 100.0},
            {"t": 800, "elevation_m": 140.0},
            {"t": 820, "elevation_m": 140.0},
            {"t": 840, "elevation_m": 140.0},
            {"t": 860, "elevation_m": 140.0},
            {"t": 880, "elevation_m": 140.0},
        ]
        marginal = ClimbCandidate(
            climb=make_climb(
                100,
                384,
                vert_m=40.5,
                gradient_pct=2.5,
                distance_m=1620.0,
            ),
            source="momentum:rolling",
            family="momentum",
            ride_quality=ride_quality,
            tile_samples=tile_samples,
        )
        marginal.corroborating_sources = ["momentum:rolling_review"]

        score, reasons = _score_climb_candidate(marginal)

        assert "momentum_consensus_epsilon" in reasons
        assert score >= marginal.acceptance_threshold

        unsupported = ClimbCandidate(
            climb=make_climb(
                100,
                384,
                vert_m=40.5,
                gradient_pct=2.5,
                distance_m=1620.0,
            ),
            source="momentum:rolling",
            family="momentum",
            ride_quality=ride_quality,
            tile_samples=tile_samples,
        )

        unsupported_score, unsupported_reasons = _score_climb_candidate(
            unsupported
        )
        assert "momentum_consensus_epsilon" not in unsupported_reasons
        assert unsupported_score < unsupported.acceptance_threshold

    def test_canonical_v2_allows_steep_isolated_urban_micro_climb(self):
        ride_quality = make_quality_profile(
            source_class="sparse_reconstructed",
            integrity_score=0.70,
            sparse_sampling=True,
        )
        ride_profile = RideClimbProfile(points=[], total_distance_m=9000.0)
        steep_micro = make_climb(
            1000,
            1090,
            vert_m=22.0,
            gradient_pct=7.8,
            distance_m=282.0,
        )
        tile_samples = [
            {"t": 940, "elevation_m": 10.0},
            {"t": 960, "elevation_m": 10.2},
            {"t": 980, "elevation_m": 10.1},
            {"t": 1000, "elevation_m": 10.1},
            {"t": 1005, "elevation_m": 11.5},
            {"t": 1010, "elevation_m": 13.0},
            {"t": 1015, "elevation_m": 14.3},
            {"t": 1105, "elevation_m": 32.0},
            {"t": 1125, "elevation_m": 32.3},
            {"t": 1145, "elevation_m": 32.1},
        ]

        selected = _choose_canonical_v2_climbs(
            ride_quality=ride_quality,
            ride_profile=ride_profile,
            momentum_results={"urban_hills": [steep_micro]},
            persistence_climbs=[],
            tile_samples=tile_samples,
        )

        assert len(selected) == 1
        assert selected[0].detector_mode == "canonical_v2:momentum:urban_hills"
        assert "steep_isolated_urban_micro" in (selected[0].confidence_reasons or [])
        assert "micro_urban_below_display_floor" not in (
            selected[0].confidence_reasons or []
        )

    def test_canonical_v2_blocks_short_steep_isolated_urban_micro_climb(self):
        ride_quality = make_quality_profile(
            source_class="sparse_reconstructed",
            integrity_score=0.82,
            sparse_sampling=True,
        )
        ride_profile = RideClimbProfile(points=[], total_distance_m=9000.0)
        too_short_micro = make_climb(
            4782,
            4878,
            vert_m=20.33,
            gradient_pct=10.13,
            distance_m=200.7,
        )
        tile_samples = [
            {"t": 4725, "elevation_m": 10.0},
            {"t": 4745, "elevation_m": 10.1},
            {"t": 4765, "elevation_m": 10.0},
            {"t": 4782, "elevation_m": 10.0},
            {"t": 4787, "elevation_m": 12.0},
            {"t": 4792, "elevation_m": 14.0},
            {"t": 4797, "elevation_m": 16.0},
            {"t": 4885, "elevation_m": 30.0},
            {"t": 4905, "elevation_m": 30.2},
            {"t": 4925, "elevation_m": 30.1},
        ]

        selected = _choose_canonical_v2_climbs(
            ride_quality=ride_quality,
            ride_profile=ride_profile,
            momentum_results={"urban_hills": [too_short_micro]},
            persistence_climbs=[],
            tile_samples=tile_samples,
        )

        assert selected == []

    def test_canonical_v2_uses_acceptable_cluster_candidate_when_top_is_disqualified(self):
        ride_quality = make_quality_profile()
        ride_profile = RideClimbProfile(points=[], total_distance_m=9000.0)
        below_floor_urban = make_climb(
            4627,
            4971,
            vert_m=31.0,
            gradient_pct=7.9,
            distance_m=394.0,
        )
        acceptable_rolling = make_climb(
            4666,
            4971,
            vert_m=29.8,
            gradient_pct=7.8,
            distance_m=383.0,
        )

        selected = _choose_canonical_v2_climbs(
            ride_quality=ride_quality,
            ride_profile=ride_profile,
            momentum_results={
                "urban_hills": [below_floor_urban],
                "rolling": [acceptable_rolling],
            },
            persistence_climbs=[],
        )

        assert len(selected) == 1
        assert selected[0].start_time_offset_s == 4666
        assert selected[0].detector_mode == "canonical_v2:momentum:rolling"
        assert selected[0].proposal_sources == ["momentum:rolling", "momentum:urban_hills"]

    def test_detect_climbs_with_rust_canonical_v2_prefers_stronger_earlier_persistence_override(self):
        samples = [{"t": i * 10, "elevation_m": 100.0 + i, "lat": 39.0, "lon": -75.0} for i in range(500)]
        momentum_auto = [make_climb(1150, 1450, vert_m=210.0, gradient_pct=6.5, distance_m=3200.0)]
        persistence = [make_climb(980, 1440, vert_m=305.0, gradient_pct=6.0, distance_m=3600.0)]
        persistence[0].persistence = 58.0

        with patch("app.services.patterns.climb._get_workout_parse", return_value=object()):
            with patch(
                "app.services.patterns.climb._run_canonical_momentum_sweep",
                return_value=({"auto": momentum_auto}, "auto", momentum_auto),
            ):
                with patch(
                    "app.services.patterns.climb._run_rust_detector",
                    return_value=persistence,
                ):
                    with patch(
                        "app.services.patterns.climb.RideQualityProfile.from_tile_samples",
                        return_value=make_quality_profile(),
                    ):
                        climbs = detect_climbs_with_rust(samples, algorithm="canonical_v2")

        assert len(climbs) == 1
        assert climbs[0].start_time_offset_s == 980
        assert climbs[0].detector_mode == "canonical_v2:persistence"
        assert climbs[0].route_profile is not None

    def test_detect_climbs_with_rust_canonical_v2_frag_discount_for_corroborated_highvert(self):
        """Corroborated high-vert climbs (>=100m) get fragmentation discount, allowing
        long low-gradient mountain approaches to pass the acceptance threshold."""
        samples = [{"t": i * 10, "elevation_m": 700.0 + i * 0.2, "lat": 32.0, "lon": -111.0} for i in range(2000)]
        # Long mountain approach: 275m vert, 1.9% grade, 14.5km — would get frag=4.5 normally
        momentum_auto = [make_climb(4839, 6401, vert_m=275.0, gradient_pct=1.9, distance_m=14588.0)]
        persistence = [make_climb(4874, 6368, vert_m=272.0, gradient_pct=2.0, distance_m=13912.0)]
        persistence[0].persistence = 271.5

        with patch("app.services.patterns.climb._get_workout_parse", return_value=object()):
            with patch(
                "app.services.patterns.climb._run_canonical_momentum_sweep",
                return_value=({"auto": momentum_auto}, "auto", momentum_auto),
            ):
                with patch(
                    "app.services.patterns.climb._run_rust_detector",
                    return_value=persistence,
                ):
                    with patch(
                        "app.services.patterns.climb.RideQualityProfile.from_tile_samples",
                        return_value=make_quality_profile(
                            sparse_sampling=True,
                            integrity_score=0.74,
                        ),
                    ):
                        climbs = detect_climbs_with_rust(samples, algorithm="canonical_v2")

        assert len(climbs) == 1
        assert climbs[0].vert_m >= 270.0
        assert "corroborated_highvert_frag_discount" in (climbs[0].confidence_reasons or [])

    def test_persistence_candidate_not_consumed_by_rejected_momentum_baseline(self):
        """A persistence candidate overlapping a rejected momentum baseline should
        still be evaluated in the standalone persistence rescue path.

        This is the 'consumed-persistence' bug: if a momentum baseline is rejected
        (score < threshold), the persistence candidates that overlapped it were
        already marked as used and never got a second chance.

        Scenario: the best-terrain baseline is a weak 12m/2% climb that gets rejected.
        The persistence candidate (55m/5.5%) overlaps it. Two other terrains also
        have weak overlapping climbs that corroborate the persistence candidate.
        Without the fix, the persistence candidate is consumed by used_persistence
        and never evaluated standalone.
        """
        ride_quality = make_quality_profile()
        ride_profile = RideClimbProfile(points=[], total_distance_m=5000.0)

        # Weak momentum baseline: very low vert, below-threshold gradient.
        # This cluster (baseline + overlapping persistence) will score below
        # acceptance because the momentum baseline is too weak on its own,
        # and the persistence candidate — while strong — won't fire the
        # _should_prefer_persistence_override path (starts_earlier < 90s).
        weak_momentum = make_climb(
            600, 720, vert_m=12.0, gradient_pct=2.0, distance_m=600.0
        )

        # Strong persistence candidate overlapping the weak baseline.
        strong_persistence = make_climb(
            580, 740, vert_m=55.0, gradient_pct=5.5, distance_m=1000.0
        )
        strong_persistence.persistence = 50.0

        # Both "auto" and "hilly" have only the weak climb — so "auto" wins
        # (higher source prior) and uses it as the baseline. Both terrains
        # corroborate the persistence candidate (satisfying >=2 terrain gate).
        momentum_results = {
            "auto": [weak_momentum],
            "hilly": [
                make_climb(610, 710, vert_m=11.0, gradient_pct=1.9, distance_m=550.0)
            ],
        }

        selected = _choose_canonical_v2_climbs(
            ride_quality=ride_quality,
            ride_profile=ride_profile,
            momentum_results=momentum_results,
            persistence_climbs=[strong_persistence],
        )

        # The persistence candidate should be rescued, not silently discarded.
        assert len(selected) == 1, (
            f"Expected 1 climb (rescued persistence), got {len(selected)}"
        )
        assert selected[0].vert_m == 55.0
        assert selected[0].detector_mode == "canonical_v2:persistence"
        assert "persistence" in selected[0].proposal_sources


    def test_multi_terrain_merge_recovers_non_winning_terrain_climb(self):
        """A climb appearing only in a non-winning terrain (e.g. 'rolling') should
        still be evaluated and accepted.

        This is the Shawmont-Minerva scenario: the climb appears in 'rolling' but not
        in 'auto' (which wins the ride). Before multi-terrain merge, this climb was
        discarded because only the winning terrain's candidates were used as baselines.
        """
        ride_quality = make_quality_profile()
        ride_profile = RideClimbProfile(points=[], total_distance_m=8000.0)

        # Climb A: appears in both auto and hilly (overlapping boundaries)
        climb_a_auto = make_climb(1320, 1500, vert_m=58.0, gradient_pct=6.8, distance_m=900.0)
        climb_a_hilly = make_climb(1310, 1490, vert_m=56.0, gradient_pct=6.5, distance_m=880.0)

        # Climb B: appears ONLY in rolling terrain (Shawmont scenario)
        climb_b_rolling = make_climb(3905, 4200, vert_m=46.0, gradient_pct=4.6, distance_m=1160.0)

        momentum_results = {
            "auto": [climb_a_auto],
            "hilly": [climb_a_hilly],
            "rolling": [
                make_climb(1325, 1495, vert_m=55.0, gradient_pct=6.3, distance_m=890.0),
                climb_b_rolling,
            ],
        }

        selected = _choose_canonical_v2_climbs(
            ride_quality=ride_quality,
            ride_profile=ride_profile,
            momentum_results=momentum_results,
            persistence_climbs=[],
        )

        # Both climbs should be accepted — climb B should NOT be discarded
        assert len(selected) == 2, (
            f"Expected 2 climbs (multi-terrain merge), got {len(selected)}: "
            f"{[(c.start_time_offset_s, c.vert_m) for c in selected]}"
        )
        # Climb A at ~1320
        assert selected[0].start_time_offset_s in (1310, 1320, 1325)
        # Climb B at 3905 — the recovered non-winning-terrain climb
        assert selected[1].start_time_offset_s == 3905
        assert selected[1].vert_m == 46.0

    def test_multi_terrain_merge_deduplicates_same_physical_climb(self):
        """The same physical climb detected by multiple terrains should produce
        exactly one output, not N duplicates."""
        ride_quality = make_quality_profile()
        ride_profile = RideClimbProfile(points=[], total_distance_m=5000.0)

        momentum_results = {
            "auto": [make_climb(1320, 1500, vert_m=58.0, gradient_pct=6.8, distance_m=900.0)],
            "hilly": [make_climb(1310, 1490, vert_m=56.0, gradient_pct=6.5, distance_m=880.0)],
            "rolling": [make_climb(1325, 1495, vert_m=55.0, gradient_pct=6.3, distance_m=890.0)],
        }

        selected = _choose_canonical_v2_climbs(
            ride_quality=ride_quality,
            ride_profile=ride_profile,
            momentum_results=momentum_results,
            persistence_climbs=[],
        )

        # One physical climb = one output
        assert len(selected) == 1
        # All three terrains should be in proposal_sources
        assert "momentum:auto" in selected[0].proposal_sources
        assert "momentum:hilly" in selected[0].proposal_sources
        assert "momentum:rolling" in selected[0].proposal_sources


class TestCanonicalV2Fallback:
    """Tests for canonical_v2 fallback behavior when chooser rejects all candidates."""

    def _run_with_chooser_returning_empty(self, env_override=None):
        """Helper: run canonical_v2 with chooser mocked to return empty list."""
        samples = [
            {"t": i * 10, "elevation_m": 100.0 + i, "lat": 39.0, "lon": -75.0}
            for i in range(500)
        ]
        momentum_auto = [make_climb(1320, 1500, vert_m=42.0, gradient_pct=4.5, distance_m=930.0)]

        with patch("app.services.patterns.climb._get_workout_parse", return_value=object()):
            with patch(
                "app.services.patterns.climb._run_canonical_momentum_sweep",
                return_value=({"auto": momentum_auto}, "auto", momentum_auto),
            ):
                with patch(
                    "app.services.patterns.climb._run_rust_detector",
                    return_value=[],
                ):
                    with patch(
                        "app.services.patterns.climb.RideQualityProfile.from_tile_samples",
                        return_value=make_quality_profile(),
                    ):
                        with patch(
                            "app.services.patterns.climb._choose_canonical_v2_climbs",
                            return_value=[],
                        ):
                            if env_override:
                                with patch.dict(os.environ, env_override):
                                    return detect_climbs_with_rust(samples, algorithm="canonical_v2")
                            return detect_climbs_with_rust(samples, algorithm="canonical_v2")

    def test_chooser_rejection_returns_empty_by_default(self):
        """When chooser rejects all candidates, default behavior returns empty list."""
        climbs = self._run_with_chooser_returning_empty()
        assert climbs == []

    def test_chooser_rejection_returns_momentum_with_fallback_enabled(self):
        """When CANONICAL_V2_FALLBACK_ENABLED=true, rejected climbs return with low confidence."""
        climbs = self._run_with_chooser_returning_empty(
            env_override={"CANONICAL_V2_FALLBACK_ENABLED": "true"}
        )
        assert len(climbs) == 1
        assert climbs[0].detector_mode == "canonical_v2:fallback"
        assert climbs[0].confidence == 0.1

    def test_chooser_rejection_fallback_disabled_explicitly(self):
        """Explicitly setting CANONICAL_V2_FALLBACK_ENABLED=false returns empty."""
        climbs = self._run_with_chooser_returning_empty(
            env_override={"CANONICAL_V2_FALLBACK_ENABLED": "false"}
        )
        assert climbs == []


class TestH9RollerFilter:
    """Tests for _h9_roller_filter_bonus — roller rejection heuristic.

    Duration cutoff: 90s (recalibrated from 60s via full-resolution sweep).
    Gray zone: 90-180s.  Over 180s: no penalty.
    """

    def test_sub_90s_very_steep_no_penalty(self):
        """Very steep punch climb (<90s, >=12% gradient) is allowed."""
        climb = make_climb(100, 145, vert_m=30.0, gradient_pct=15.0, distance_m=200.0)
        assert _h9_roller_filter_bonus(climb) == 0.0

    def test_sub_90s_steep_mild_penalty(self):
        """Short steep effort (<90s, 8-12% gradient) gets mild penalty."""
        climb = make_climb(100, 180, vert_m=20.0, gradient_pct=9.0, distance_m=220.0)
        assert _h9_roller_filter_bonus(climb) == -0.5

    def test_sub_90s_low_gradient_full_penalty(self):
        """Short low-gradient bump (<90s, <8% gradient) is a roller."""
        climb = make_climb(100, 170, vert_m=12.0, gradient_pct=4.0, distance_m=300.0)
        assert _h9_roller_filter_bonus(climb) == -2.0

    def test_over_180s_no_penalty(self):
        """Any climb over 180s gets no roller penalty regardless of gradient."""
        climb = make_climb(100, 300, vert_m=25.0, gradient_pct=2.5, distance_m=1000.0)
        assert _h9_roller_filter_bonus(climb) == 0.0

    def test_gray_zone_steep_no_penalty(self):
        """90-180s climb with gradient >=6% is not a roller."""
        climb = make_climb(100, 250, vert_m=45.0, gradient_pct=7.0, distance_m=650.0)
        assert _h9_roller_filter_bonus(climb) == 0.0

    def test_gray_zone_moderate_mild_penalty(self):
        """90-180s climb with 4-6% gradient gets mild penalty."""
        climb = make_climb(100, 250, vert_m=30.0, gradient_pct=4.5, distance_m=670.0)
        assert _h9_roller_filter_bonus(climb) == -0.5

    def test_gray_zone_low_gradient_roller(self):
        """90-180s climb with <4% gradient is a roller."""
        climb = make_climb(100, 250, vert_m=20.0, gradient_pct=2.5, distance_m=800.0)
        assert _h9_roller_filter_bonus(climb) == -1.5

    def test_manayunk_wall_not_penalized(self):
        """Manayunk Wall (17% gradient, ~90 seconds, ~59m vert) must NOT be penalized.

        At exactly 90s, this falls in the gray zone where >=6% gradient gives 0.0.
        """
        climb = make_climb(100, 190, vert_m=59.0, gradient_pct=17.0, distance_m=350.0)
        assert _h9_roller_filter_bonus(climb) == 0.0

    def test_boundary_90s_steep(self):
        """Exactly 90s with steep gradient — in gray zone, no penalty."""
        climb = make_climb(100, 190, vert_m=35.0, gradient_pct=8.0, distance_m=440.0)
        assert _h9_roller_filter_bonus(climb) == 0.0

    def test_boundary_180s(self):
        """Exactly 180s — no penalty regardless of gradient."""
        climb = make_climb(100, 280, vert_m=18.0, gradient_pct=2.0, distance_m=900.0)
        assert _h9_roller_filter_bonus(climb) == 0.0

    def test_none_gradient_treated_as_zero(self):
        """Missing gradient data is treated as 0%, triggering full roller penalty."""
        climb = make_climb(100, 130, vert_m=8.0, gradient_pct=0.0, distance_m=200.0)
        climb.avg_gradient_pct = None
        assert _h9_roller_filter_bonus(climb) == -2.0


class TestH2PowerConfirmation:
    """Tests for _h2_power_confirmation_bonus — power confirmation heuristic."""

    def test_no_climb_power_returns_neutral(self):
        """Climb without power data gets 0.0 bonus."""
        climb = make_climb(100, 400, vert_m=60.0, gradient_pct=6.0)
        climb.avg_power_w = None
        assert _h2_power_confirmation_bonus(climb, 200.0) == 0.0

    def test_no_ride_power_returns_neutral(self):
        """Ride without power data gets 0.0 bonus."""
        climb = make_climb(100, 400, vert_m=60.0, gradient_pct=6.0)
        climb.avg_power_w = 250.0
        assert _h2_power_confirmation_bonus(climb, None) == 0.0

    def test_zero_ride_power_returns_neutral(self):
        """Zero ride average power gets 0.0 bonus (avoid division by zero)."""
        climb = make_climb(100, 400, vert_m=60.0, gradient_pct=6.0)
        climb.avg_power_w = 250.0
        assert _h2_power_confirmation_bonus(climb, 0.0) == 0.0

    def test_strong_confirmation(self):
        """Power 50%+ above ride average = strong confirmation (+1.5)."""
        climb = make_climb(100, 400, vert_m=60.0, gradient_pct=6.0)
        climb.avg_power_w = 320.0  # 320/200 = 1.6
        assert _h2_power_confirmation_bonus(climb, 200.0) == 1.5

    def test_good_confirmation(self):
        """Power 30-50% above ride average = good confirmation (+1.0)."""
        climb = make_climb(100, 400, vert_m=60.0, gradient_pct=6.0)
        climb.avg_power_w = 270.0  # 270/200 = 1.35
        assert _h2_power_confirmation_bonus(climb, 200.0) == 1.0

    def test_mild_confirmation(self):
        """Power 15-30% above ride average = mild confirmation (+0.5)."""
        climb = make_climb(100, 400, vert_m=60.0, gradient_pct=6.0)
        climb.avg_power_w = 240.0  # 240/200 = 1.2
        assert _h2_power_confirmation_bonus(climb, 200.0) == 0.5

    def test_neutral_zone(self):
        """Power within 90-115% of ride average = neutral (0.0)."""
        climb = make_climb(100, 400, vert_m=60.0, gradient_pct=6.0)
        climb.avg_power_w = 200.0  # 200/200 = 1.0
        assert _h2_power_confirmation_bonus(climb, 200.0) == 0.0

    def test_below_average_suspicious(self):
        """Power 70-90% of ride average = suspicious (-0.5)."""
        climb = make_climb(100, 400, vert_m=60.0, gradient_pct=6.0)
        climb.avg_power_w = 160.0  # 160/200 = 0.8
        assert _h2_power_confirmation_bonus(climb, 200.0) == -0.5

    def test_coasting_penalty(self):
        """Power <70% of ride average = likely coasting (-1.0)."""
        climb = make_climb(100, 400, vert_m=60.0, gradient_pct=6.0)
        climb.avg_power_w = 120.0  # 120/200 = 0.6
        assert _h2_power_confirmation_bonus(climb, 200.0) == -1.0

    def test_boundary_150_pct(self):
        """Exactly 1.50 ratio = strong confirmation."""
        climb = make_climb(100, 400, vert_m=60.0, gradient_pct=6.0)
        climb.avg_power_w = 300.0  # 300/200 = 1.5
        assert _h2_power_confirmation_bonus(climb, 200.0) == 1.5

    def test_boundary_90_pct(self):
        """Exactly 0.90 ratio = neutral."""
        climb = make_climb(100, 400, vert_m=60.0, gradient_pct=6.0)
        climb.avg_power_w = 180.0  # 180/200 = 0.9
        assert _h2_power_confirmation_bonus(climb, 200.0) == 0.0

    def test_boundary_70_pct(self):
        """Exactly 0.70 ratio = suspicious (not coasting)."""
        climb = make_climb(100, 400, vert_m=60.0, gradient_pct=6.0)
        climb.avg_power_w = 140.0  # 140/200 = 0.7
        assert _h2_power_confirmation_bonus(climb, 200.0) == -0.5


class TestH10Isolation:
    """Tests for _h10_isolation_bonus — topographic isolation heuristic."""

    def _make_flat_then_climb_samples(self, climb_start_s=200, climb_end_s=500):
        """Flat terrain -> sharp climb -> flat terrain."""
        samples = []
        for t in range(climb_start_s - 70, climb_start_s):
            samples.append({"t": t, "elevation_m": 100.0})
        duration = climb_end_s - climb_start_s
        for i, t in enumerate(range(climb_start_s, climb_end_s)):
            samples.append({"t": t, "elevation_m": 100.0 + (60.0 * i / max(1, duration - 1))})
        for t in range(climb_end_s, climb_end_s + 70):
            samples.append({"t": t, "elevation_m": 160.0})
        return samples

    def _make_embedded_climb_samples(self, climb_start_s=200, climb_end_s=500):
        """Already climbing before and after the detected climb."""
        samples = []
        for t in range(climb_start_s - 70, climb_start_s):
            offset = t - (climb_start_s - 70)
            samples.append({"t": t, "elevation_m": 80.0 + offset * 0.25})
        duration = climb_end_s - climb_start_s
        for i, t in enumerate(range(climb_start_s, climb_end_s)):
            samples.append({"t": t, "elevation_m": 100.0 + (60.0 * i / max(1, duration - 1))})
        for t in range(climb_end_s, climb_end_s + 70):
            offset = t - climb_end_s
            samples.append({"t": t, "elevation_m": 160.0 + offset * 0.25})
        return samples

    def test_no_tile_samples_returns_zero(self):
        climb = make_climb(200, 500, vert_m=60.0, gradient_pct=6.0)
        assert _h10_isolation_bonus(climb, None) == 0.0

    def test_flat_before_flat_after_high_bonus(self):
        climb = make_climb(200, 500, vert_m=60.0, gradient_pct=6.0)
        samples = self._make_flat_then_climb_samples()
        bonus = _h10_isolation_bonus(climb, samples)
        assert bonus >= 1.5

    def test_datetime_samples_match_numeric_isolation_bonus(self):
        climb = make_climb(200, 500, vert_m=60.0, gradient_pct=6.0)
        samples = [
            {"t": t, "elevation_m": 100.0}
            for t in range(0, 130)
        ] + self._make_flat_then_climb_samples()
        base_time = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)
        datetime_samples = [
            {**sample, "t": base_time + timedelta(seconds=sample["t"])}
            for sample in samples
        ]

        assert _h10_isolation_bonus(climb, datetime_samples) == _h10_isolation_bonus(
            climb,
            samples,
        )

    def test_embedded_small_climb_gets_penalty(self):
        """Small climb (25m) embedded in terrain gets full penalty."""
        small_climb = make_climb(200, 500, vert_m=25.0, gradient_pct=3.0, distance_m=800.0)
        samples = self._make_embedded_climb_samples()
        bonus = _h10_isolation_bonus(small_climb, samples)
        assert bonus <= -1.0

    def test_embedded_large_climb_mild_penalty(self):
        """Large climb (60m) embedded in terrain gets reduced penalty."""
        large_climb = make_climb(200, 500, vert_m=60.0, gradient_pct=6.0)
        samples = self._make_embedded_climb_samples()
        bonus = _h10_isolation_bonus(large_climb, samples)
        assert bonus > -0.5  # Much milder for big climbs
        assert bonus < 0.0   # Still slightly negative

    def test_steep_onset_from_flat_gives_max_bonus(self):
        climb = make_climb(200, 260, vert_m=30.0, gradient_pct=10.0, distance_m=300.0)
        samples = []
        for t in range(140, 200):
            samples.append({"t": t, "elevation_m": 100.0})
        for t in range(200, 245):
            samples.append({"t": t, "elevation_m": 100.0 + (t - 200) * 0.67})
        for t in range(245, 261):
            samples.append({"t": t, "elevation_m": 130.0 + (t - 245) * 0.33})
        for t in range(261, 330):
            samples.append({"t": t, "elevation_m": 135.0})
        bonus = _h10_isolation_bonus(climb, samples)
        assert bonus == 2.0  # Flat pre + flat post + steep onset = capped at 2.0

    def test_clamped_to_range(self):
        climb = make_climb(200, 500, vert_m=25.0, gradient_pct=3.0, distance_m=800.0)
        samples = self._make_embedded_climb_samples()
        bonus = _h10_isolation_bonus(climb, samples)
        assert bonus >= -1.5
        assert bonus <= 2.0


class TestH12FrequencyPrior:
    """Tests for _h12_frequency_prior_bonus — historical detection frequency heuristic."""

    def _make_climb_with_gps(self, start_lat: float, start_lon: float) -> ClimbPattern:
        climb = make_climb(100, 400, vert_m=60.0, gradient_pct=6.0)
        climb.start_lat = start_lat
        climb.start_lon = start_lon
        return climb

    def test_no_frequency_map_returns_zero(self):
        """No frequency map = neutral."""
        climb = self._make_climb_with_gps(39.97, -75.20)
        assert _h12_frequency_prior_bonus(climb, None) == 0.0

    def test_empty_frequency_map_returns_zero(self):
        """Empty frequency map = neutral."""
        climb = self._make_climb_with_gps(39.97, -75.20)
        assert _h12_frequency_prior_bonus(climb, {}) == 0.0

    def test_no_gps_returns_zero(self):
        """Climb without GPS coordinates = neutral."""
        climb = make_climb(100, 400, vert_m=60.0, gradient_pct=6.0)
        climb.start_lat = None
        climb.start_lon = None
        freq_map = {"some_tile": 50}
        assert _h12_frequency_prior_bonus(climb, freq_map) == 0.0

    def test_unknown_tile_returns_zero(self):
        """Tile not in frequency map = neutral."""
        climb = self._make_climb_with_gps(39.97, -75.20)
        freq_map = {"different_tile": 50}
        assert _h12_frequency_prior_bonus(climb, freq_map) == 0.0

    def test_well_established_location(self):
        """20+ detections = well-established (+1.0, capped per audit H12-decay)."""
        climb = self._make_climb_with_gps(39.97, -75.20)
        import h3
        tile = h3.latlng_to_cell(39.97, -75.20, 8)
        freq_map = {tile: 25}
        assert _h12_frequency_prior_bonus(climb, freq_map) == 1.0

    def test_established_location(self):
        """10-19 detections = established (+0.75)."""
        climb = self._make_climb_with_gps(39.97, -75.20)
        import h3
        tile = h3.latlng_to_cell(39.97, -75.20, 8)
        freq_map = {tile: 15}
        assert _h12_frequency_prior_bonus(climb, freq_map) == 0.75

    def test_growing_confidence(self):
        """5-9 detections = growing confidence (+0.5)."""
        climb = self._make_climb_with_gps(39.97, -75.20)
        import h3
        tile = h3.latlng_to_cell(39.97, -75.20, 8)
        freq_map = {tile: 7}
        assert _h12_frequency_prior_bonus(climb, freq_map) == 0.5

    def test_second_detection(self):
        """2-4 detections = mild bonus (+0.25)."""
        climb = self._make_climb_with_gps(39.97, -75.20)
        import h3
        tile = h3.latlng_to_cell(39.97, -75.20, 8)
        freq_map = {tile: 3}
        assert _h12_frequency_prior_bonus(climb, freq_map) == 0.25

    def test_single_detection_neutral(self):
        """1 detection = neutral (0.0)."""
        climb = self._make_climb_with_gps(39.97, -75.20)
        import h3
        tile = h3.latlng_to_cell(39.97, -75.20, 8)
        freq_map = {tile: 1}
        assert _h12_frequency_prior_bonus(climb, freq_map) == 0.0

    def test_boundary_20(self):
        """Exactly 20 = well-established."""
        climb = self._make_climb_with_gps(39.97, -75.20)
        import h3
        tile = h3.latlng_to_cell(39.97, -75.20, 8)
        freq_map = {tile: 20}
        assert _h12_frequency_prior_bonus(climb, freq_map) == 1.0

    def test_boundary_10(self):
        """Exactly 10 = established."""
        climb = self._make_climb_with_gps(39.97, -75.20)
        import h3
        tile = h3.latlng_to_cell(39.97, -75.20, 8)
        freq_map = {tile: 10}
        assert _h12_frequency_prior_bonus(climb, freq_map) == 0.75

    def test_boundary_5(self):
        """Exactly 5 = growing confidence."""
        climb = self._make_climb_with_gps(39.97, -75.20)
        import h3
        tile = h3.latlng_to_cell(39.97, -75.20, 8)
        freq_map = {tile: 5}
        assert _h12_frequency_prior_bonus(climb, freq_map) == 0.5

    def test_boundary_2(self):
        """Exactly 2 = second detection."""
        climb = self._make_climb_with_gps(39.97, -75.20)
        import h3
        tile = h3.latlng_to_cell(39.97, -75.20, 8)
        freq_map = {tile: 2}
        assert _h12_frequency_prior_bonus(climb, freq_map) == 0.25

    def test_frequency_prior_ignored_for_single_source_candidate(self):
        """H12 is historical corroboration, not a standalone acceptance signal."""
        import h3

        climb = make_climb(
            100,
            700,
            vert_m=30.0,
            gradient_pct=3.0,
            distance_m=1000.0,
        )
        climb.start_lat = 39.97
        climb.start_lon = -75.20
        freq_map = {h3.latlng_to_cell(39.97, -75.20, 8): 25}
        candidate = ClimbCandidate(
            climb=climb,
            source="momentum:auto",
            family="momentum",
            ride_quality=make_quality_profile(),
            frequency_map=freq_map,
        )

        total, reasons = _score_climb_candidate(candidate)

        assert "h12_frequency:+1.0" not in reasons
        assert total < candidate.acceptance_threshold

    def test_frequency_prior_applies_after_cross_family_corroboration(self):
        """H12 can still boost candidates already corroborated by another family."""
        import h3

        climb = make_climb(
            100,
            700,
            vert_m=30.0,
            gradient_pct=3.0,
            distance_m=1000.0,
        )
        climb.start_lat = 39.97
        climb.start_lon = -75.20
        freq_map = {h3.latlng_to_cell(39.97, -75.20, 8): 25}
        candidate = ClimbCandidate(
            climb=climb,
            source="momentum:auto",
            family="momentum",
            ride_quality=make_quality_profile(),
            corroborating_families=["persistence"],
            frequency_map=freq_map,
        )

        total, reasons = _score_climb_candidate(candidate)

        assert "h12_frequency:+1.0" in reasons
        assert total >= candidate.acceptance_threshold
