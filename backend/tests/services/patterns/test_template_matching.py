"""Tests for GPS template matching (Path H)."""

import json
import math
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import pytest

from app.services.patterns.template_matching import (
    SegmentTemplate,
    TemplateMatch,
    _compute_actual_vert,
    _compute_coverage,
    _determine_direction,
    _find_corridor_runs,
    _haversine_m,
    _is_temporally_ordered,
    match_ride_against_templates,
    prepare_template,
)
from app.services.pattern_engine import PatternEngine, UserProfile
from app.services.vault_indexer import IndexedVault, VaultSignatureCache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_template(
    template_id: int = 1,
    name: str = "Test Climb",
    polyline: Optional[List[Tuple[float, float]]] = None,
    expected_vert_m: float = 100.0,
    expected_grade_pct: float = 5.0,
) -> SegmentTemplate:
    """Build a prepared SegmentTemplate for testing."""
    if polyline is None:
        # Default: a 500m climb heading roughly north
        polyline = [
            (40.0000, -75.5000),
            (40.0005, -75.5000),
            (40.0010, -75.5000),
            (40.0015, -75.5000),
            (40.0020, -75.5000),
            (40.0025, -75.5000),
            (40.0030, -75.5000),
            (40.0035, -75.5000),
            (40.0040, -75.5000),
            (40.0045, -75.5000),
        ]
    tmpl = SegmentTemplate(
        template_id=template_id,
        name=name,
        polyline=polyline,
        expected_vert_m=expected_vert_m,
        expected_grade_pct=expected_grade_pct,
    )
    prepare_template(tmpl)
    return tmpl


def ride_along_template(
    polyline: List[Tuple[float, float]],
    start_time: int = 0,
    time_step: int = 5,
    lateral_offset_m: float = 0.0,
    elevation_start: float = 100.0,
    elevation_gain: float = 100.0,
) -> Tuple[List[Tuple[float, float]], List[int], List[float]]:
    """
    Generate a ride GPS track that follows a template polyline.

    Returns (latlng, times, elevations).
    """
    n = len(polyline)
    latlng = []
    times = []
    elevations = []

    for i, (lat, lon) in enumerate(polyline):
        # Add small lateral offset (in longitude, approx)
        offset_deg = lateral_offset_m / 111320.0  # rough m->deg at equator
        latlng.append((lat, lon + offset_deg))
        times.append(start_time + i * time_step)
        elevations.append(elevation_start + (elevation_gain * i / max(1, n - 1)))

    return latlng, times, elevations


# ---------------------------------------------------------------------------
# Unit tests: haversine
# ---------------------------------------------------------------------------


class TestHaversine:
    def test_same_point(self):
        assert _haversine_m(40.0, -75.0, 40.0, -75.0) == pytest.approx(0.0, abs=0.01)

    def test_known_distance(self):
        # ~111 km per degree of latitude
        d = _haversine_m(40.0, -75.0, 41.0, -75.0)
        assert 110_000 < d < 112_000

    def test_short_distance(self):
        # ~55m for 0.0005 degrees latitude at 40N
        d = _haversine_m(40.0000, -75.0, 40.0005, -75.0)
        assert 50 < d < 60


# ---------------------------------------------------------------------------
# Unit tests: prepare_template
# ---------------------------------------------------------------------------


class TestPrepareTemplate:
    def test_bounding_box(self):
        tmpl = make_template()
        assert tmpl.bbox_min_lat < 40.0000
        assert tmpl.bbox_max_lat > 40.0045
        assert tmpl.bbox_min_lon < -75.5000
        assert tmpl.bbox_max_lon > -75.5000

    def test_cumulative_distances(self):
        tmpl = make_template()
        assert len(tmpl._cumulative_distances) == len(tmpl.polyline)
        assert tmpl._cumulative_distances[0] == 0.0
        assert tmpl._total_length_m > 0

    def test_total_length(self):
        tmpl = make_template()
        # 10 points separated by 0.0005 deg lat ~ 55m each = ~495m total
        assert 400 < tmpl._total_length_m < 600


# ---------------------------------------------------------------------------
# Unit tests: corridor helpers
# ---------------------------------------------------------------------------


class TestFindCorridorRuns:
    def test_single_run(self):
        mask = [False, True, True, True, True, True, False]
        tidx = [0, 0, 1, 2, 3, 4, 0]
        runs = _find_corridor_runs(mask, tidx, 5)
        assert len(runs) == 1
        assert runs[0] == (1, 5)

    def test_gap_too_large(self):
        mask = [True] * 5 + [False] * 20 + [True] * 5
        tidx = list(range(30))
        runs = _find_corridor_runs(mask, tidx, 30, max_gap=15)
        assert len(runs) == 2

    def test_too_few_points(self):
        mask = [True, True, True, False, False]
        tidx = [0, 1, 2, 0, 0]
        runs = _find_corridor_runs(mask, tidx, 3)
        # 3 in-corridor points < 5 minimum
        assert len(runs) == 0


class TestComputeCoverage:
    def test_full_coverage(self):
        cumul = [0.0, 100.0, 200.0, 300.0, 400.0]
        covered = {0, 1, 2, 3, 4}
        cov = _compute_coverage(covered, cumul, 400.0)
        assert cov == pytest.approx(1.0, abs=0.01)

    def test_partial_coverage(self):
        cumul = [0.0, 100.0, 200.0, 300.0, 400.0]
        covered = {0, 1}  # covers segments 0->1 and 1->2
        cov = _compute_coverage(covered, cumul, 400.0)
        assert 0.4 < cov < 0.6


class TestDetermineDirection:
    def test_forward(self):
        assert _determine_direction([0, 2, 4, 6, 8]) == "forward"

    def test_reverse(self):
        assert _determine_direction([8, 6, 4, 2, 0]) == "reverse"


class TestTemporalOrdering:
    def test_ordered(self):
        assert _is_temporally_ordered([0, 1, 2, 3, 4, 5]) is True

    def test_disordered(self):
        assert _is_temporally_ordered([5, 4, 3, 2, 1, 0]) is False

    def test_mostly_ordered(self):
        # One out-of-order pair out of 9 (< 25% tolerance)
        assert _is_temporally_ordered([0, 1, 2, 3, 2, 5, 6, 7, 8, 9]) is True


class TestComputeActualVert:
    def test_ascending(self):
        elevs = [100.0, 110.0, 120.0, 130.0, 140.0]
        assert _compute_actual_vert(elevs, 0, 4) == pytest.approx(40.0)

    def test_descending(self):
        elevs = [140.0, 130.0, 120.0, 110.0, 100.0]
        assert _compute_actual_vert(elevs, 0, 4) == pytest.approx(0.0)

    def test_with_nones(self):
        elevs = [None, 100.0, None, 120.0, None]
        assert _compute_actual_vert(elevs, 0, 4) == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# Integration tests: full matching
# ---------------------------------------------------------------------------


class TestMatchRideAgainstTemplates:
    def test_ride_along_template_matches(self):
        """A ride that follows the template closely should match."""
        tmpl = make_template()
        latlng, times, elevs = ride_along_template(
            tmpl.polyline,
            lateral_offset_m=10.0,
            elevation_gain=100.0,
        )
        matches = match_ride_against_templates(
            latlng, times, [tmpl],
            corridor_width_m=50.0,
            min_coverage=0.60,
            ride_elevations=elevs,
        )
        assert len(matches) == 1
        assert matches[0].template_id == tmpl.template_id
        assert matches[0].coverage >= 0.60
        assert matches[0].direction == "forward"

    def test_ride_too_far_away_no_match(self):
        """A ride 200m away from the template should not match."""
        tmpl = make_template()
        latlng, times, elevs = ride_along_template(
            tmpl.polyline,
            lateral_offset_m=200.0,
            elevation_gain=100.0,
        )
        matches = match_ride_against_templates(
            latlng, times, [tmpl],
            corridor_width_m=50.0,
            min_coverage=0.60,
            ride_elevations=elevs,
        )
        assert len(matches) == 0

    def test_ride_in_reverse_no_match(self):
        """A ride going downhill on the segment should not match (direction filter)."""
        tmpl = make_template()
        # Reverse the polyline so we traverse it backwards
        reversed_poly = list(reversed(tmpl.polyline))
        latlng, times, elevs = ride_along_template(
            reversed_poly,
            lateral_offset_m=5.0,
            elevation_gain=100.0,
        )
        matches = match_ride_against_templates(
            latlng, times, [tmpl],
            corridor_width_m=50.0,
            min_coverage=0.60,
            ride_elevations=elevs,
        )
        # The rider traverses the template in reverse order -> should be filtered
        assert len(matches) == 0

    def test_insufficient_elevation_no_match(self):
        """A ride through the corridor with insufficient elevation gain should not match."""
        tmpl = make_template(expected_vert_m=100.0)
        latlng, times, elevs = ride_along_template(
            tmpl.polyline,
            lateral_offset_m=5.0,
            elevation_gain=10.0,  # Only 10m vs 100m expected
        )
        matches = match_ride_against_templates(
            latlng, times, [tmpl],
            corridor_width_m=50.0,
            min_coverage=0.60,
            ride_elevations=elevs,
        )
        assert len(matches) == 0

    def test_bbox_prefilter_skips_distant(self):
        """Templates far from the ride should be skipped by bounding box."""
        tmpl = make_template(
            polyline=[
                (50.0000, -1.0000),  # London area — far from SEPA
                (50.0005, -1.0000),
                (50.0010, -1.0000),
                (50.0015, -1.0000),
                (50.0020, -1.0000),
                (50.0025, -1.0000),
                (50.0030, -1.0000),
                (50.0035, -1.0000),
                (50.0040, -1.0000),
                (50.0045, -1.0000),
            ]
        )
        # Ride in SEPA
        ride_poly = [
            (40.0000, -75.5000),
            (40.0005, -75.5000),
            (40.0010, -75.5000),
            (40.0015, -75.5000),
            (40.0020, -75.5000),
            (40.0025, -75.5000),
            (40.0030, -75.5000),
            (40.0035, -75.5000),
            (40.0040, -75.5000),
            (40.0045, -75.5000),
        ]
        latlng, times, elevs = ride_along_template(
            ride_poly, elevation_gain=100.0,
        )
        matches = match_ride_against_templates(
            latlng, times, [tmpl],
            corridor_width_m=50.0,
            min_coverage=0.60,
            ride_elevations=elevs,
        )
        assert len(matches) == 0

    def test_partial_coverage_below_threshold(self):
        """A ride that only covers 30% of the template should not match."""
        tmpl = make_template()
        # Only ride through the first 3 of 10 template points (30%)
        partial_poly = tmpl.polyline[:3]
        latlng, times, elevs = ride_along_template(
            partial_poly,
            lateral_offset_m=5.0,
            elevation_gain=30.0,
        )
        matches = match_ride_against_templates(
            latlng, times, [tmpl],
            corridor_width_m=50.0,
            min_coverage=0.60,
            ride_elevations=elevs,
        )
        assert len(matches) == 0

    def test_empty_inputs(self):
        """Empty ride or templates should return empty list."""
        tmpl = make_template()
        assert match_ride_against_templates([], [], [tmpl]) == []
        assert match_ride_against_templates([(40.0, -75.0)], [0], []) == []

    def test_no_elevation_data_still_matches(self):
        """Without elevation data, the elevation check is skipped."""
        tmpl = make_template(expected_vert_m=0.0)  # No expected vert -> skip elev check
        latlng, times, _elevs = ride_along_template(
            tmpl.polyline,
            lateral_offset_m=5.0,
        )
        matches = match_ride_against_templates(
            latlng, times, [tmpl],
            corridor_width_m=50.0,
            min_coverage=0.60,
            ride_elevations=None,
        )
        assert len(matches) == 1

    def test_multiple_templates_both_match(self):
        """Two non-overlapping templates that both match."""
        tmpl1 = make_template(
            template_id=1,
            name="Climb A",
            polyline=[
                (40.0000, -75.5000),
                (40.0005, -75.5000),
                (40.0010, -75.5000),
                (40.0015, -75.5000),
                (40.0020, -75.5000),
                (40.0025, -75.5000),
                (40.0030, -75.5000),
                (40.0035, -75.5000),
                (40.0040, -75.5000),
                (40.0045, -75.5000),
            ],
            expected_vert_m=50.0,
        )
        tmpl2 = make_template(
            template_id=2,
            name="Climb B",
            polyline=[
                (40.0100, -75.5000),
                (40.0105, -75.5000),
                (40.0110, -75.5000),
                (40.0115, -75.5000),
                (40.0120, -75.5000),
                (40.0125, -75.5000),
                (40.0130, -75.5000),
                (40.0135, -75.5000),
                (40.0140, -75.5000),
                (40.0145, -75.5000),
            ],
            expected_vert_m=50.0,
        )

        # Ride that goes through both
        combined_poly = tmpl1.polyline + tmpl2.polyline
        latlng, times, elevs = ride_along_template(
            combined_poly,
            lateral_offset_m=5.0,
            elevation_gain=120.0,
        )

        matches = match_ride_against_templates(
            latlng, times, [tmpl1, tmpl2],
            corridor_width_m=50.0,
            min_coverage=0.60,
            ride_elevations=elevs,
        )
        assert len(matches) == 2
        ids = {m.template_id for m in matches}
        assert ids == {1, 2}


class TestTemplateMatchRewardSafety:
    """Template/profile evidence must not create rewardable climbs by itself."""

    def _vault_cache_with_template(self, tmpl: SegmentTemplate) -> VaultSignatureCache:
        cache = VaultSignatureCache()
        cache._loaded = True
        cache._vaults = {
            tmpl.template_id: IndexedVault(
                id=tmpl.template_id,
                signature_hex="ab" * 32,
                signature_hash_hex="cd" * 32,
                minter="vault-minter",
                name=tmpl.name,
                vert_m=tmpl.expected_vert_m,
                distance_m=int(tmpl._total_length_m or 500),
                avg_gradient_pct=tmpl.expected_grade_pct,
                total_completions=0,
                total_staked=0,
                kom_holder=None,
                kom_time_s=0,
                created_at=datetime.now(timezone.utc),
                pda="vault-pda",
                signature_v2_hex="ef" * 64,
                polyline_json=json.dumps([[lat, lon] for lat, lon in tmpl.polyline]),
            )
        }
        return cache

    def test_template_only_known_climb_is_display_only(self):
        tmpl = make_template(template_id=42, name="Known Vault Climb")
        latlng, times, elevs = ride_along_template(
            tmpl.polyline,
            lateral_offset_m=5.0,
            elevation_gain=100.0,
        )
        samples = [
            {
                "t": t,
                "tile_id": f"tile_{i}",
                "lat": lat,
                "lon": lon,
                "elevation_m": elevs[i],
            }
            for i, ((lat, lon), t) in enumerate(zip(latlng, times))
        ]
        engine = PatternEngine(
            vault_cache=self._vault_cache_with_template(tmpl),
            use_rust_detector=False,
        )

        patterns = engine._run_template_matching(
            tile_samples=samples,
            raw_climb_samples=samples,
            existing_patterns=[],
            user_profile=UserProfile(wallet="wallet", weight_kg=75.0),
            activity_id=uuid.uuid4(),
            sensor_integrity=None,
        )

        assert len(patterns) == 1
        pattern = patterns[0]
        assert pattern.detector_version == "template_match:canonical_v2"
        assert pattern.indexed_vault_id == tmpl.template_id
        assert pattern.indexed_vault_name == tmpl.name
        assert pattern.vault_climb_name == tmpl.name
        assert pattern.economic_eligible is False
        assert "SOURCE:identity_only_no_ride_candidate" in (pattern.abstention_reasons or [])

    def test_template_identity_reason_survives_clean_generic_abstention_checks(self):
        engine = PatternEngine(use_rust_detector=False)

        # Build the dataclass through the production template path above instead
        # of hand-rolling model defaults; this specifically guards the previous
        # bug where significance_confidence_tier=None left template-only output
        # economically eligible.
        tmpl = make_template(template_id=43, name="Clean Template Climb")
        latlng, times, elevs = ride_along_template(tmpl.polyline, elevation_gain=100.0)
        samples = [
            {
                "t": t,
                "tile_id": f"tile_{i}",
                "lat": lat,
                "lon": lon,
                "elevation_m": elevs[i],
            }
            for i, ((lat, lon), t) in enumerate(zip(latlng, times))
        ]
        engine.vault_cache = self._vault_cache_with_template(tmpl)

        produced = engine._run_template_matching(
            tile_samples=samples,
            raw_climb_samples=samples,
            existing_patterns=[],
            user_profile=UserProfile(wallet="wallet", weight_kg=75.0),
            activity_id=uuid.uuid4(),
            sensor_integrity=None,
        )

        assert len(produced) == 1
        assert produced[0].significance_confidence_tier is None
        assert produced[0].signature_v2_hex is not None
        assert produced[0].economic_eligible is False
