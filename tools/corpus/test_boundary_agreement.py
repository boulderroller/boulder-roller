"""Synthetic tests for the founder's 20 October boundary and timing bars."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from shapely.geometry import LineString

import canon_traversal_replay as cr


class Identity:
    def transform(self, x, y):
        return x, y


def candidate(line=None):
    line = line if line is not None else LineString([(0, 0), (100, 0)])
    runtime = SimpleNamespace(
        gate_start=LineString([(0, 25), (0, -25)]),
        gate_end=LineString([(100, 25), (100, -25)]),
        corridor_tile_ids=("tile",),
    )
    return cr.RatifiedCandidate("hill", "a" * 64, "Synthetic hill", runtime,
                                None, line, Identity())


def test_reference_replay_projects_crossing_not_clipped_samples(monkeypatch):
    from app.services import canon_traversal

    c = candidate()
    def payload(u):
        return {"interpolation_u": u, "time_s_raw": u,
                "bracketing_samples": {"start": {"source_index": 0, "t_s": 0},
                                       "end": {"source_index": 1, "t_s": 1}},
                "direction_evidence": {"before": {"along_track_m": 0},
                                       "after": {"along_track_m": 20}}}

    class Engine:
        def evaluate(self, **kwargs):
            p = payload(kwargs["raw_samples"][0]["u"])
            return SimpleNamespace(climb_patterns=[SimpleNamespace(
                start_lat=0, start_lon=0, end_lat=0, end_lon=100,
                match_trace={"candidate_fingerprint": c.fingerprint,
                             "gate_crossings": {"start": p, "finish": p,
                                                "start_time_s_raw": 0,
                                                "finish_time_s_raw": 10}})])

    monkeypatch.setattr(canon_traversal, "CanonTraversalEngine", Engine)
    monkeypatch.setattr(cr, "run_pinned_offline_detector", lambda streams: [])
    monkeypatch.setattr(cr, "_streams_for_activity", lambda con, aid: float(aid))
    monkeypatch.setattr(cr, "_tile_samples", lambda value: [
        {"t": i, "lat": 0, "lon": i * 20 - 20, "tile_id": "tile",
         "source_index": i, "u": {1: .5, 2: .75, 3: .95}[value]}
        for i in range(2)])
    con = SimpleNamespace(execute=lambda sql: SimpleNamespace(
        fetchall=lambda: [("1",), ("2",), ("3",)]))
    refs = [cr.ExpectedPass(str(i), i, c.fingerprint, c.decision_id, 0, 10)
            for i in (1, 2, 3)]
    _, observations, _, errors = cr.replay_reference_slice(
        con, [c], refs, corpus_path=None)
    assert errors == 0
    assert [o.start_progress_m for o in observations] == [0, 0, 0]
    assert [o.finish_progress_m for o in observations] == [100, 100, 100]
    _, historical, _, _ = cr.replay_reference_slice(
        con, [c], refs, corpus_path=None, legacy_clipped_projection=True)
    assert [o.start_progress_m for o in historical] == [10, 15, 19]
    assert [(o.start_s, o.end_s) for o in observations] == [
        (o.start_s, o.end_s) for o in historical]


HASHES = {"corpus_sha256": "1" * 64, "canon_report_sha256": "2" * 64,
          "review_labels_sha256": "3" * 64}


def observation(ride, c, start=0, finish=100, **kwargs):
    return cr.ObservedPass(ride, c.fingerprint, c.decision_id, 0, 100,
                           0, 0, 0, 100, start, finish, **kwargs)


def test_bend_remains_a_failure_and_geometry_scan_includes_unridden_gates():
    c = candidate(LineString([(0, 0), (5, 0), (5, 100)]))
    starts = [cr.crossing_progress_m(c, 0, y, {}) for y in (0, 20)]
    assert starts == [0, 25]
    result = cr.boundary_repeat_metrics(
        [replace(observation(str(i), c, start=s, finish=105), start_lat=y,
                 finish_lon=5, finish_lat=100) for i, (s, y) in enumerate(zip(starts, (0, 20)))],
        [c], source_hashes=HASHES)
    assert result["_p95_error_m_raw"] == 12.5
    assert next(g for g in result["groups"] if g["gate"] == "start")["p95_error_m"] == 12.5
    # Default scoring reprojects even an older caller's stale progress fields.
    repeated = [replace(observation("a", c), finish_lon=5, finish_lat=100),
                replace(observation("a", c), finish_lon=5, finish_lat=100),
                replace(observation("b", c), start_lat=20, finish_lon=5, finish_lat=100)]
    weighted = cr.boundary_repeat_metrics(repeated, [c], source_hashes=HASHES)
    assert weighted["repeat_endpoints"] == 6
    assert weighted["_p95_error_m_raw"] == 25
    assert weighted == cr.boundary_repeat_metrics(list(reversed(repeated)), [c], source_hashes=HASHES)
    assert cr.boundary_repeat_metrics(repeated[:2], [c], source_hashes=HASHES)["repeat_endpoints"] == 0
    scan = cr.gate_geometry_metrics([c])
    assert len(scan) == 2
    assert next(g for g in scan if g["gate"] == "start")["geometry_flag"] is True


def dense_fixture(pause=False):
    from test_gate_consistency import synthetic_candidate
    from app.services.canon_traversal import _gate_observations, _normalize_samples, _project_candidate
    runtime = synthetic_candidate()
    projected = _project_candidate(runtime)
    c = cr.RatifiedCandidate("hill", "a" * 64, "Synthetic hill", runtime,
                             runtime.corridor, projected.centerline, projected.forward)
    raw = [{"source_index": i, "t": i + (60 if pause and i >= 22 else 0),
            "lon": -75, "lat": 40 + (i - 20.5) * (.000025 if i < 21 else .00005)}
           for i in range(45)]
    samples, _, _ = _normalize_samples(raw)
    crossing = _gate_observations(gate_name="start", gate=projected.gate_start,
                                  projected=projected, samples=samples)[0]
    return c, raw, crossing


def test_timing_all_eight_offsets_and_pause_guard():
    c, raw, crossing = dense_fixture()
    probe = cr.timing_thinning_probe(raw, c, "start", crossing.to_trace())
    assert probe["dense"] is True
    assert [p["offset"] for p in probe["offsets"]] == list(range(8))
    assert all(p["status"] == "measured" for p in probe["offsets"])
    assert max(abs(p["error_s"]) for p in probe["offsets"]) > 1
    c, raw, crossing = dense_fixture(pause=True)
    paused = cr.timing_thinning_probe(raw, c, "start", crossing.to_trace())
    assert sum(p["status"] == "recording_pause" for p in paused["offsets"]) == 7
    assert sum(p["status"] == "measured" for p in paused["offsets"]) == 1
    assert all("error_s" not in p for p in paused["offsets"] if p["status"] != "measured")
    c, raw, crossing = dense_fixture()
    # Dense samples hit the gate; thinning loses it when nearby samples detour.
    detour = [{**s, "lon": s["lon"] + (.01 if i not in (20, 21) else 0)}
              for i, s in enumerate(raw)]
    lost = cr.timing_thinning_probe(detour, c, "start", crossing.to_trace())
    assert any(p["status"] == "no_unique_forward_crossing" for p in lost["offsets"])


def probe(error):
    return {"dense": True, "bracket_gap_s": 1,
            "offsets": [{"offset": i, "status": "measured", "error_s": error}
                        for i in range(8)]}


def test_timing_reports_each_gate_keeps_repeats_and_fails_closed():
    c = candidate()
    observations = [observation(ride, c, start_timing=probe(error), finish_timing=probe(0))
                    for ride, error in [("a", 0), ("a", 3), ("b", 0)]]
    timing = cr.timing_agreement_metrics(observations, [c], source_hashes=HASHES)
    assert timing["comparisons"] == 48
    assert timing["eligible_climb_gate_groups"] == 2
    assert timing["_p95_error_s_raw"] == 3
    by_gate = {g["gate"]: g for g in timing["groups"]}
    assert by_gate["start"]["p95_error_s"] == 3
    assert by_gate["finish"]["p95_error_s"] == 0
    assert by_gate["start"]["rides_over_1s"] == 1
    assert timing == cr.timing_agreement_metrics(list(reversed(observations)), [c], source_hashes=HASHES)
    only_one_ride = cr.timing_agreement_metrics(observations[:2], [c], source_hashes=HASHES)
    assert only_one_ride["comparisons"] == 0
    assert only_one_ride["_p95_error_s_raw"] is None
    assert "activity_id" not in str(timing) and "source_index" not in str(timing)

    def cutover(value, **overrides):
        kwargs = dict(corpus_integrity_ok=True, replay_errors=0,
                      reference_passes=100, reference_h3_hits=100, traversal_matches=100,
                      boundary_eligible_climb_gate_groups=2, boundary_eligible_distinct_rides=2,
                      repeat_boundary_endpoints=6, boundary_p95_error_m=.03,
                      boundary_strict_max_error_m=19,
                      boundary_candidate_manifest_sha256="a" * 64,
                      boundary_observation_manifest_sha256="b" * 64,
                      boundary_input_manifest_sha256="c" * 64, boundary_metric_ratified=True,
                      cross_rider_pairs=2, cross_rider_agreements=2, cross_rider_supported_candidates=1,
                      unclassified_disagreements=0, timing_metrics=value)
        kwargs.update(overrides)
        return cr.build_cutover_scorecard(**kwargs)

    assert cutover(timing)["overall_pass"] is False
    exact = {**timing, "_p95_error_s_raw": 2.0}
    assert cutover(exact)["overall_pass"] is True
    assert cutover({**exact, "_p95_error_s_raw": 2.0004})["gates"]["timing_agreement"]["pass"] is False
    assert cutover({**exact, "missing_probe_crossings": 1})["overall_pass"] is False
    assert cutover(None)["gates"]["timing_agreement"]["measured"] is False
    assert cutover(only_one_ride)["gates"]["timing_agreement"]["pass"] is False
    assert cutover(exact, legacy_clipped_projection=True)["gates"]["boundary_agreement"]["pass"] is False
    changed = [replace(observations[0], start_timing=probe(1)), *observations[1:]]
    new_hash = cr.timing_agreement_metrics(changed, [c], source_hashes=HASHES)["frozen_input"]["input_manifest_sha256"]
    assert new_hash != timing["frozen_input"]["input_manifest_sha256"]

    # A failed offset ranks beyond every finite error, keeping the founder's
    # pooled p95 rule: 1/32 failures fits in its tail, 2/32 makes p95 unbounded.
    clean = [observation(ride, c, start_timing=probe(1), finish_timing=probe(0))
             for ride in ("a", "b")]
    for failures in (1, 2):
        failed_probe = probe(1)
        for i in range(failures):
            failed_probe["offsets"][i] = {"offset": i, "status": "no_unique_forward_crossing"}
        failed = [replace(clean[0], start_timing=failed_probe), clean[1]]
        measured = cr.timing_agreement_metrics(failed, [c], source_hashes=HASHES)
        assert measured["comparisons"] == 32
        assert measured["measured_offsets"] == 32 - failures
        assert measured["_p95_error_s_raw"] == (1 if failures == 1 else None)
        assert cutover(measured)["overall_pass"] is (failures == 1)
