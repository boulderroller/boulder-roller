"""Synthetic geometry only; never load the private rider corpus in tests."""

import math
import json
from types import SimpleNamespace

import pytest
from shapely.geometry import LineString, Point

from gate_consistency import (
    boundary, changes, crossing_progress, endpoint_record, legacy_progress, metric, p95,
    private_safe_points, tolerance, write,
)


def crossing(before, after, u, x, y=0):
    return SimpleNamespace(
        before_progress_m=before,
        after_progress_m=after,
        interpolation_u=u,
        lon=x,
        lat=y,
    )


class Identity:
    def transform(self, x, y):
        return x, y


def test_endpoint_clipping_must_not_move_the_observed_crossing():
    """Two samplings of the same straight start have exactly the same position."""
    projected = SimpleNamespace(
        forward=Identity(), centerline=LineString([(0, 0), (100, 0)])
    )
    # Raw brackets [-20, 20] and [-60, 20] both cross x=0.
    # Finite-line projection clamps both negative endpoints to zero.
    first = crossing(0, 20, .5, 0)
    second = crossing(0, 20, .75, 0)
    assert math.isclose(crossing_progress(projected, first), 0, abs_tol=1e-9)
    assert math.isclose(crossing_progress(projected, second), 0, abs_tol=1e-9)


def test_finish_and_bend_are_projected_without_erasing_real_spread():
    projected = SimpleNamespace(
        forward=Identity(), centerline=LineString([(0, 0), (100, 0), (100, 100)])
    )
    assert crossing_progress(projected, crossing(180, 200, .5, 100, 100)) == 200
    # A curved/oblique gate can intersect positions with different real
    # along-track projections. The proposed metric must preserve that.
    assert crossing_progress(projected, crossing(90, 120, .5, 100, 20)) == 120
    assert crossing_progress(projected, crossing(90, 120, .5, 90, 0)) == 90


def effort(ride, climb, start, finish=100, start_s=0, finish_s=100):
    return {"ride": ride, "climb": climb, "start_s": start_s, "finish_s": finish_s,
            "start": {"direct": start}, "finish": {"direct": finish}}


def test_metric_keeps_every_repeat_and_requires_distinct_rides():
    observations = [effort("a", "eligible", 0), effort("a", "eligible", 0),
                    effort("b", "eligible", 30), effort("only", "ineligible", 999),
                    effort("only", "ineligible", -999)]
    score = metric(observations, "direct")
    assert score["n"] == 6 and score["eligible_groups"] == 2
    assert score["distinct_rides"] == 2
    assert score["p95_m"] == 30 and score["over_10m"] == 1
    assert metric([], "direct")["p95_m"] is None
    assert p95(range(1, 21)) == 19  # nearest rank, not interpolated quantile


def test_effort_matching_preserves_repeats_and_reports_losses():
    before = [effort("a", "c", 0), effort("a", "c", 0, start_s=200, finish_s=300)]
    after = [effort("a", "c", 0, start_s=10, finish_s=90),
             effort("b", "c", 0)]
    change = changes(before, after)
    assert (change["retained"], change["new"], change["lost"]) == (1, 1, 1)
    assert change["paired_elapsed_delta_s"]["median"] == -20


def synthetic_candidate():
    from app.models.canon import CanonClimb
    from uuid import UUID
    return CanonClimb(
        registry_id=UUID(int=1), canon_id=UUID(int=2), version=1,
        display_name="Synthetic hill", route_name=None,
        centerline=LineString([(-75, 40), (-75, 40.002)]),
        corridor=LineString([(-75, 40), (-75, 40.002)]).buffer(.0003),
        gate_start=LineString([(-75.0002, 40), (-74.9998, 40)]),
        gate_end=LineString([(-75.0002, 40.002), (-74.9998, 40.002)]),
        canonical_profile=({"dist_m": 0, "elev_m": 10},
                           {"dist_m": 222, "elev_m": 30}),
        length_m=222, vert_m=20, avg_gradient_pct=9,
        compiler_version="synthetic", profile_hash_algorithm="blake3_canonical_profile_v1",
        profile_hash="a" * 64, odbl_source="synthetic", corridor_tile_ids=())


def test_tolerance_preserves_anchor_orientation_span_identity_and_bounds():
    from app.services.canon_traversal import _project_candidate
    original = synthetic_candidate()
    revised = tolerance(original)
    a, b = _project_candidate(original), _project_candidate(revised)
    assert original.centerline.equals_exact(revised.centerline, 0)
    assert original.canonical_profile == revised.canonical_profile
    assert original.version == revised.version and original.length_m == revised.length_m
    for old, new in [(a.gate_start, b.gate_start), (a.gate_end, b.gate_end)]:
        assert old.centroid.distance(new.centroid) < 1e-6
        assert math.isclose(new.length, 80, abs_tol=1e-6)
        assert old.distance(new) < 1e-6
    with pytest.raises(ValueError):
        tolerance(original, gate_half_extent=41)
    with pytest.raises(ValueError):
        tolerance(original, corridor_half_width=36)


def test_boundary_trim_changes_version_and_retains_elevation_interval():
    original = synthetic_candidate()
    revised = boundary(original, 30, 30)
    assert revised.version == original.version + 1
    assert 59 < original.length_m - revised.length_m < 61
    assert revised.canonical_profile[0]["dist_m"] == 0
    assert 10 < revised.canonical_profile[0]["elev_m"] < 30
    assert revised.canonical_profile[-1]["elev_m"] < 30
    with pytest.raises(ValueError):
        boundary(original, 300, 0)


def test_repo_engine_crossing_reproduces_clipped_progress_artifact():
    from app.services.canon_traversal import (
        _gate_observations, _normalize_samples, _project_candidate,
    )
    p = _project_candidate(synthetic_candidate())
    samples, _, _ = _normalize_samples([
        {"t": 0, "lon": -75, "lat": 39.9998},
        {"t": 10, "lon": -75, "lat": 40.0002},
    ])
    observed = _gate_observations(
        gate_name="start", gate=p.gate_start, projected=p, samples=samples)
    assert len(observed) == 1 and observed[0].crosses_gate
    assert legacy_progress(observed[0]) > 10
    assert crossing_progress(p, observed[0]) < .001
    assert json.loads(json.dumps(endpoint_record(observed[0], p)))["clipped_bracket"] is True
    # Explicitly unchanged timestamp; the correction is spatial only.
    assert 4.99 < observed[0].time_s < 5.01


def test_render_excludes_points_beyond_60m_and_private_writes_in_repo(tmp_path):
    gate = LineString([(0, -25), (0, 25)])
    points = [Point(0, 0), Point(60, 0), Point(60.01, 0), Point(0, 86)]
    assert len(private_safe_points(points, gate)) == 2
    from gate_consistency import ROOT
    with pytest.raises(ValueError):
        write(ROOT / "must-not-write-private.json", {"ride": "secret"}, private=True)
    target = tmp_path / "cache.json"
    write(target, {"test": True}, private=True)
    assert target.stat().st_mode & 0o777 == 0o600
