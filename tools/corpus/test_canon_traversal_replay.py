from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import canon_traversal_replay as replay_module

from canon_traversal_replay import (
    InputIntegrityError,
    ObservedPass,
    apply_disagreement_audit,
    boundary_repeat_metrics,
    build_boundary_input_manifest,
    build_cutover_scorecard,
    classify_disagreement,
    classify_detector_only_interval,
    detector_gate_span_decisions,
    full_corpus_audit_completeness,
    load_corridor_equivalence,
    load_cross_rider_evidence,
    maximum_interval_matching,
    resolve_launch_canon_candidates,
    map_reference_templates,
    RatifiedCandidate,
    reference_contains_observed,
    run_pinned_offline_detector,
    select_boundary_ratifications,
    sha256_file,
    verify_runtime_dependencies,
)


def _candidate(fingerprint: str, *, ratified: bool) -> dict:
    provenance = {}
    if ratified:
        provenance["ratified_boundary"] = {
            "decision_id": f"decision-{fingerprint}",
        }
    return {
        "candidate_fingerprint": fingerprint * 64,
        "provenance": provenance,
    }


def test_sha256_file_reads_the_exact_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"canon-replay-input")

    assert sha256_file(artifact) == hashlib.sha256(
        b"canon-replay-input"
    ).hexdigest()


def test_cross_rider_v2_requires_pre_outcome_manifest_hashes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = Path(__file__).with_name("canon_cross_rider_evidence_2026-07-21.json")
    evidence = json.loads(source.read_text())
    artifact = tmp_path / "cross-rider.json"
    artifact.write_text(json.dumps(evidence))
    monkeypatch.setattr(
        replay_module,
        "EXPECTED_CROSS_RIDER_EVIDENCE_SHA256",
        sha256_file(artifact),
    )

    assert load_cross_rider_evidence(artifact)["model"].endswith("_v2")

    evidence["source_manifest"]["eligible_pair_manifest_sha256"] = "z" * 64
    artifact.write_text(json.dumps(evidence))
    monkeypatch.setattr(
        replay_module,
        "EXPECTED_CROSS_RIDER_EVIDENCE_SHA256",
        sha256_file(artifact),
    )
    with pytest.raises(InputIntegrityError, match="source manifest digests"):
        load_cross_rider_evidence(artifact)


def test_cross_rider_evidence_is_bound_to_exact_postgis_wkb_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = Path(__file__).with_name("canon_cross_rider_evidence_2026-07-21.json")
    evidence = json.loads(source.read_text())
    evidence["source_manifest"]["scored_attempt_outcomes_sha256"] = "a" * 64
    evidence["source_manifest"]["scored_pair_outcomes_sha256"] = "b" * 64
    evidence["source_manifest"]["authoritative_wkb_manifest_sha256"] = "f" * 64
    artifact = tmp_path / "cross-rider-wrong-wkb.json"
    artifact.write_text(json.dumps(evidence))
    monkeypatch.setattr(
        replay_module,
        "EXPECTED_CROSS_RIDER_EVIDENCE_SHA256",
        sha256_file(artifact),
    )

    with pytest.raises(InputIntegrityError, match="PostGIS WKB manifest"):
        load_cross_rider_evidence(artifact)


def test_pinned_corridor_equivalence_and_runtime_dependencies() -> None:
    evidence = Path(__file__).with_name(
        "canon_corridor_equivalence_2026-07-21.json"
    )

    assert load_corridor_equivalence(evidence)["candidate_count"] == 57
    assert verify_runtime_dependencies()["native_parser_sha256"] == (
        replay_module.EXPECTED_NATIVE_PARSER_SHA256
    )


def test_selects_only_explicit_boundary_ratifications() -> None:
    report = {
        "compiler_version": "canon-compile-v0.2.5",
        "ratified_boundaries": {
            "mode": "applied",
            "applied_decisions": 2,
            "retained_decisions": 2,
        },
        "candidates": [
            _candidate("a", ratified=True),
            _candidate("b", ratified=False),
            _candidate("c", ratified=True),
        ],
    }

    selected = select_boundary_ratifications(report)

    assert [item["candidate_fingerprint"] for item in selected] == [
        "a" * 64,
        "c" * 64,
    ]


def test_ratified_selection_fails_on_report_count_drift() -> None:
    report = {
        "compiler_version": "canon-compile-v0.2.5",
        "ratified_boundaries": {
            "mode": "applied",
            "applied_decisions": 2,
            "retained_decisions": 2,
        },
        "candidates": [_candidate("a", ratified=True)],
    }

    with pytest.raises(InputIntegrityError, match="retained ratification count"):
        select_boundary_ratifications(report)


@pytest.mark.parametrize(
    ("detector", "traversal", "reference", "classification"),
    [
        (True, True, True, "agreement"),
        (True, False, True, "canon_gap_or_evidence_rejection"),
        (False, True, True, "detector_error"),
        (False, False, True, "both_missed_reference"),
        (True, False, False, "detector_only_off_canon"),
        (False, True, False, "traversal_only_unlabelled"),
    ],
)
def test_disagreement_taxonomy_never_forces_a_false_binary(
    detector: bool,
    traversal: bool,
    reference: bool,
    classification: str,
) -> None:
    assert classify_disagreement(
        detector_match=detector,
        traversal_match=traversal,
        independent_reference=reference,
    ) == classification


def test_scorecard_passes_only_when_every_cutover_gate_has_evidence() -> None:
    scorecard = build_cutover_scorecard(
        corpus_integrity_ok=True,
        replay_errors=0,
        reference_passes=100,
        reference_h3_hits=100,
        traversal_matches=96,
        boundary_eligible_climb_gate_groups=4,
        boundary_eligible_distinct_rides=8,
        repeat_boundary_endpoints=30,
        boundary_p95_error_m=9.9,
        boundary_strict_max_error_m=19.9,
        boundary_candidate_manifest_sha256="a" * 64,
        boundary_observation_manifest_sha256="b" * 64,
        boundary_input_manifest_sha256="c" * 64,
        boundary_metric_ratified=True,
        timing_metrics={
            "eligible_climb_gate_groups": 2, "eligible_distinct_rides": 3,
            "comparisons": 24, "_p95_error_s_raw": 1.5,
            "frozen_input": {"input_manifest_sha256": "d" * 64},
        },
        cross_rider_pairs=8,
        cross_rider_agreements=8,
        cross_rider_supported_candidates=2,
        unclassified_disagreements=0,
    )

    assert scorecard["overall_pass"] is True
    assert scorecard["gates"]["recall"]["value"] == 0.96
    assert scorecard["gates"]["boundary_agreement"]["pass"] is True
    assert scorecard["gates"]["cross_rider_agreement"]["measured"] is True


@pytest.mark.parametrize(
    "overrides,failed_gate",
    [
        ({"traversal_matches": 94}, "recall"),
        ({"reference_h3_hits": 99}, "reference_h3_coverage"),
        ({"boundary_p95_error_m": 10.01}, "boundary_agreement"),
        ({"boundary_eligible_climb_gate_groups": 0}, "boundary_agreement"),
        ({"boundary_eligible_distinct_rides": 1}, "boundary_agreement"),
        ({"repeat_boundary_endpoints": 0}, "boundary_agreement"),
        ({"boundary_strict_max_error_m": None}, "boundary_agreement"),
        ({"boundary_input_manifest_sha256": None}, "boundary_agreement"),
        ({"boundary_metric_ratified": False}, "boundary_agreement"),
        ({"cross_rider_pairs": 0, "cross_rider_agreements": 0}, "cross_rider_agreement"),
        ({"cross_rider_pairs": 1, "cross_rider_agreements": 0}, "cross_rider_agreement"),
        ({"replay_errors": 1}, "replay_integrity"),
        ({"unclassified_disagreements": 1}, "disagreement_classification"),
        ({"unresolved_prior_approvals": 1}, "offline_canon_authority"),
    ],
)
def test_scorecard_fails_closed(overrides: dict, failed_gate: str) -> None:
    kwargs = {
        "corpus_integrity_ok": True,
        "replay_errors": 0,
        "reference_passes": 100,
        "reference_h3_hits": 100,
        "traversal_matches": 96,
        "boundary_eligible_climb_gate_groups": 4,
        "boundary_eligible_distinct_rides": 8,
        "repeat_boundary_endpoints": 30,
        "boundary_p95_error_m": 9.9,
        "boundary_strict_max_error_m": 19.9,
        "boundary_candidate_manifest_sha256": "a" * 64,
        "boundary_observation_manifest_sha256": "b" * 64,
        "boundary_input_manifest_sha256": "c" * 64,
        "boundary_metric_ratified": True,
        "cross_rider_pairs": 8,
        "cross_rider_agreements": 8,
        "cross_rider_supported_candidates": 2,
        "unclassified_disagreements": 0,
    }
    kwargs.update(overrides)

    scorecard = build_cutover_scorecard(**kwargs)

    assert scorecard["overall_pass"] is False
    assert scorecard["gates"][failed_gate]["pass"] is False


def test_scorecard_is_stable_json() -> None:
    scorecard = build_cutover_scorecard(
        corpus_integrity_ok=True,
        replay_errors=0,
        reference_passes=13,
        reference_h3_hits=13,
        traversal_matches=12,
        boundary_eligible_climb_gate_groups=2,
        boundary_eligible_distinct_rides=3,
        repeat_boundary_endpoints=26,
        boundary_p95_error_m=14.93,
        boundary_strict_max_error_m=22.0,
        boundary_candidate_manifest_sha256="a" * 64,
        boundary_observation_manifest_sha256="b" * 64,
        boundary_input_manifest_sha256="c" * 64,
        boundary_metric_ratified=False,
        cross_rider_pairs=0,
        cross_rider_agreements=0,
        cross_rider_supported_candidates=0,
        unclassified_disagreements=0,
    )

    encoded = json.dumps(scorecard, sort_keys=True, separators=(",", ":"))
    assert "activity_id" not in encoded
    assert "latitude" not in encoded
    assert "longitude" not in encoded
    assert scorecard["overall_pass"] is False


def test_reference_interval_allows_subsecond_gate_interpolation() -> None:
    assert reference_contains_observed(3096.0, 3210.0, 3095.56, 3209.53)
    assert not reference_contains_observed(3096.0, 3210.0, 3094.99, 3209.53)


def test_boundary_repeat_metric_uses_strict_max_repeat_median_deviation() -> None:
    # Explicit legacy fixture: supplied progress differs from the GPS coordinates.
    from types import SimpleNamespace

    from pyproj import Transformer
    from shapely.geometry import LineString

    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32618", always_xy=True)
    candidate = RatifiedCandidate(
        "decision-a",
        "a" * 64,
        "A",
        SimpleNamespace(
            gate_start=LineString([(-75.0, 39.9999), (-75.0, 40.0001)]),
            gate_end=LineString([(-74.999, 39.9999), (-74.999, 40.0001)]),
        ),
        None,
        None,
        transformer,
    )
    observed = [
        ObservedPass(
            activity_id=str(index),
            candidate_fingerprint=candidate.fingerprint,
            decision_id=candidate.decision_id,
            start_s=0.0,
            end_s=10.0,
            start_lat=40.0,
            start_lon=-75.0,
            finish_lat=40.0,
            finish_lon=-74.999,
            start_progress_m=start_progress,
            finish_progress_m=finish_progress,
        )
        for index, (start_progress, finish_progress) in enumerate(
            [(0.0, 100.0), (5.0, 105.0), (30.0, 110.0)],
            start=1,
        )
    ]

    source_hashes = {
        "corpus_sha256": "1" * 64,
        "canon_report_sha256": "2" * 64,
        "review_labels_sha256": "3" * 64,
    }
    metrics = boundary_repeat_metrics(
        observed,
        [candidate],
        source_hashes=source_hashes,
        legacy_clipped_projection=True,
    )

    assert metrics["repeat_endpoints"] == 6
    assert metrics["max_error_m"] == 25.0
    assert metrics["p95_error_m"] == 25.0
    assert metrics["max_gate_intersection_residual_m"] == pytest.approx(0.0)
    assert metrics["eligible_climb_gate_groups"] == 2
    assert metrics["eligible_distinct_rides"] == 3
    assert metrics["frozen_input"]["candidate_count"] == 1
    assert metrics["frozen_input"]["observation_count"] == 3
    assert metrics["frozen_input"]["source_sha256"] == source_hashes


def test_boundary_input_manifest_is_pre_outcome_stable_and_privacy_bounded() -> None:
    from types import SimpleNamespace

    candidate = RatifiedCandidate(
        "decision-a",
        "a" * 64,
        "A",
        SimpleNamespace(),
        None,
        None,
        None,
    )
    observed = [
        ObservedPass(
            activity_id="raw-private-activity-id",
            candidate_fingerprint=candidate.fingerprint,
            decision_id=candidate.decision_id,
            start_s=1.0,
            end_s=2.0,
            start_lat=40.0,
            start_lon=-75.0,
            finish_lat=40.001,
            finish_lon=-75.001,
            start_progress_m=3.0,
            finish_progress_m=4.0,
        )
    ]
    source_hashes = {
        "corpus_sha256": "1" * 64,
        "canon_report_sha256": "2" * 64,
        "review_labels_sha256": "3" * 64,
    }

    first = build_boundary_input_manifest(
        observed,
        [candidate],
        source_hashes=source_hashes,
    )
    second = build_boundary_input_manifest(
        observed,
        [candidate],
        source_hashes=source_hashes,
    )

    assert first == second
    assert first["candidate_count"] == 1
    assert first["observation_count"] == 1
    assert first["scored_observation_count"] == 1
    assert first["scored_observation_manifest_sha256"] == first[
        "observation_manifest_sha256"
    ]
    assert first["distinct_activity_count"] == 1
    assert first["metric_progress_encoding"] == "python_float_hex_exact_binary64_v1"
    assert "raw-private-activity-id" not in json.dumps(first, sort_keys=True)

    changed = [
        ObservedPass(
            **{
                **observed[0].__dict__,
                "finish_progress_m": 4.0000001,
            }
        )
    ]
    changed_manifest = build_boundary_input_manifest(
        changed,
        [candidate],
        source_hashes=source_hashes,
    )
    assert changed_manifest["candidate_manifest_sha256"] == first[
        "candidate_manifest_sha256"
    ]
    assert changed_manifest["observation_manifest_sha256"] != first[
        "observation_manifest_sha256"
    ]
    assert changed_manifest["input_manifest_sha256"] != first[
        "input_manifest_sha256"
    ]

    non_finite = [
        ObservedPass(
            **{
                **observed[0].__dict__,
                "finish_progress_m": float("nan"),
            }
        )
    ]
    with pytest.raises(InputIntegrityError, match="non-finite"):
        build_boundary_input_manifest(
            non_finite,
            [candidate],
            source_hashes=source_hashes,
        )


def test_boundary_metric_scores_every_repeat_crossing_order_independently() -> None:
    # Preserve the historical all-crossing aggregation as well as the new path.
    from types import SimpleNamespace

    from pyproj import Transformer
    from shapely.geometry import LineString

    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32618", always_xy=True)
    candidate = RatifiedCandidate(
        "decision-a",
        "a" * 64,
        "A",
        SimpleNamespace(
            gate_start=LineString([(-75.0, 39.9999), (-75.0, 40.0001)]),
            gate_end=LineString([(-74.999, 39.9999), (-74.999, 40.0001)]),
        ),
        None,
        None,
        transformer,
    )

    def observation(
        activity_id: str,
        start_s: float,
        start_progress_m: float,
        finish_progress_m: float,
    ) -> ObservedPass:
        return ObservedPass(
            activity_id=activity_id,
            candidate_fingerprint=candidate.fingerprint,
            decision_id=candidate.decision_id,
            start_s=start_s,
            end_s=start_s + 10.0,
            start_lat=40.0,
            start_lon=-75.0,
            finish_lat=40.0,
            finish_lon=-74.999,
            start_progress_m=start_progress_m,
            finish_progress_m=finish_progress_m,
        )

    observed = [
        observation("ride-1", 10.0, 0.0, 100.0),
        observation("ride-1", 20.0, 100.0, 200.0),
        observation("ride-2", 11.0, 5.0, 105.0),
        observation("ride-3", 12.0, 10.0, 110.0),
    ]
    source_hashes = {
        "corpus_sha256": "1" * 64,
        "canon_report_sha256": "2" * 64,
        "review_labels_sha256": "3" * 64,
    }

    forward = boundary_repeat_metrics(
        observed,
        [candidate],
        source_hashes=source_hashes,
        legacy_clipped_projection=True,
    )
    reversed_result = boundary_repeat_metrics(
        list(reversed(observed)),
        [candidate],
        source_hashes=source_hashes,
        legacy_clipped_projection=True,
    )

    assert forward == reversed_result
    assert forward["frozen_input"]["observation_count"] == 4
    assert forward["frozen_input"]["scored_observation_count"] == 4
    assert forward["repeat_endpoints"] == 8
    assert all(group["rides"] == 3 for group in forward["groups"])
    assert all(group["observations"] == 4 for group in forward["groups"])


def test_boundary_threshold_compares_raw_p95_before_display_rounding() -> None:
    from types import SimpleNamespace

    from pyproj import Transformer
    from shapely.geometry import LineString

    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32618", always_xy=True)
    candidate = RatifiedCandidate(
        "decision-a",
        "a" * 64,
        "A",
        SimpleNamespace(
            gate_start=LineString([(-75.0, 39.9999), (-75.0, 40.0001)]),
            gate_end=LineString([(-74.999, 39.9999), (-74.999, 40.0001)]),
        ),
        None,
        None,
        transformer,
    )
    source_hashes = {
        "corpus_sha256": "1" * 64,
        "canon_report_sha256": "2" * 64,
        "review_labels_sha256": "3" * 64,
    }

    def metrics_for(raw_deviation_m: float) -> dict:
        observed = [
            ObservedPass(
                activity_id=f"ride-{index}",
                candidate_fingerprint=candidate.fingerprint,
                decision_id=candidate.decision_id,
                start_s=float(index),
                end_s=float(index + 10),
                start_lat=40.0,
                start_lon=-75.0,
                finish_lat=40.0,
                finish_lon=-74.999,
                start_progress_m=0.0 if index == 1 else raw_deviation_m * 2.0,
                finish_progress_m=(
                    100.0 if index == 1 else 100.0 + raw_deviation_m * 2.0
                ),
            )
            for index in (1, 2)
        ]
        return boundary_repeat_metrics(
            observed,
            [candidate],
            source_hashes=source_hashes,
            legacy_clipped_projection=True,
        )

    def score(metrics: dict) -> dict:
        frozen = metrics["frozen_input"]
        return build_cutover_scorecard(
            corpus_integrity_ok=True,
            replay_errors=0,
            reference_passes=100,
            reference_h3_hits=100,
            traversal_matches=100,
            boundary_eligible_climb_gate_groups=metrics[
                "eligible_climb_gate_groups"
            ],
            boundary_eligible_distinct_rides=metrics["eligible_distinct_rides"],
            repeat_boundary_endpoints=metrics["repeat_endpoints"],
            boundary_p95_error_m=metrics["_p95_error_m_raw"],
            boundary_strict_max_error_m=metrics["_max_error_m_raw"],
            boundary_candidate_manifest_sha256=frozen[
                "candidate_manifest_sha256"
            ],
            boundary_observation_manifest_sha256=frozen[
                "observation_manifest_sha256"
            ],
            boundary_input_manifest_sha256=frozen["input_manifest_sha256"],
            boundary_metric_ratified=True,
            cross_rider_pairs=1,
            cross_rider_agreements=1,
            cross_rider_supported_candidates=1,
            unclassified_disagreements=0,
        )

    exact = metrics_for(10.0)
    just_over = metrics_for(10.0004)
    assert exact["p95_error_m"] == just_over["p95_error_m"] == 10.0
    assert score(exact)["gates"]["boundary_agreement"]["pass"] is True
    assert score(just_over)["gates"]["boundary_agreement"]["pass"] is False


def test_interval_matching_avoids_greedy_repeat_stranding() -> None:
    matches = maximum_interval_matching(
        [(0.0, 100.0), (60.0, 100.0)],
        [(60.0, 100.0), (0.0, 40.0)],
    )

    assert matches == {0: 1, 1: 0}


def test_one_detector_cannot_match_two_repeat_traversals() -> None:
    matches = maximum_interval_matching(
        [(0.0, 100.0), (90.0, 190.0)],
        [(80.0, 110.0)],
    )

    assert len(matches) == 1
    assert set(matches.values()) == {0}


def test_detector_gate_span_requires_both_exact_gates() -> None:
    from shapely.geometry import LineString

    candidate = RatifiedCandidate(
        "decision-a",
        "a" * 64,
        "A",
        type(
            "Runtime",
            (),
            {
                "gate_start": LineString([(0.0, -1.0), (0.0, 1.0)]),
                "gate_end": LineString([(2.0, -1.0), (2.0, 1.0)]),
            },
        )(),
        None,
        None,
        None,
    )
    samples = [
        {"t": 0.0, "lat": 0.0, "lon": -1.0},
        {"t": 1.0, "lat": 0.0, "lon": 0.0},
        {"t": 2.0, "lat": 0.0, "lon": 2.0},
        {"t": 3.0, "lat": 0.0, "lon": 3.0},
    ]

    assert detector_gate_span_decisions(samples, [candidate], 0.0, 3.0) == [
        "decision-a"
    ]
    assert detector_gate_span_decisions(samples, [candidate], 2.1, 3.0) == []
    assert detector_gate_span_decisions(
        list(reversed(samples)), [candidate], 0.0, 3.0
    ) == []


def test_audited_gap_overrides_missing_current_gate_span() -> None:
    outcome = classify_detector_only_interval(
        activity_ordinal=7,
        start_s=100.0,
        end_s=200.0,
        gate_span_decision_ids=[],
        audited_reference_gaps={
            7: [
                {
                    "start_s": 90.0,
                    "end_s": 210.0,
                    "decision_id": "decision-a",
                    "reason": "gate_span_partial",
                }
            ]
        },
    )

    assert outcome == {
        "classification": "canon_gap",
        "disagreement_kind": "detector_found_audited_reference_gap",
        "decision_id": "decision-a",
        "canon_gap_reason": "gate_span_partial",
    }


def test_exact_full_corpus_audit_resolves_corridor_gap() -> None:
    outcome = classify_detector_only_interval(
        activity_ordinal=22,
        start_s=53.0,
        end_s=209.0,
        gate_span_decision_ids=["canon-a99efed4c22a1a3f"],
        audited_reference_gaps={},
    )

    assert outcome == {
        "classification": "canon_gap",
        "disagreement_kind": "audited_full_corpus_corridor_gap",
        "decision_id": "canon-a99efed4c22a1a3f",
        "canon_gap_reason": "corridor_gps_tolerance",
        "detector_error_reason": "",
        "_full_audit_key": (22, "canon-a99efed4c22a1a3f", 53.0, 209.0),
    }


def test_exact_full_corpus_audit_resolves_detector_false_positive() -> None:
    outcome = classify_detector_only_interval(
        activity_ordinal=748,
        start_s=1008.0,
        end_s=1336.0,
        gate_span_decision_ids=["canon-a99efed4c22a1a3f"],
        audited_reference_gaps={},
    )

    assert outcome == {
        "classification": "detector_error",
        "disagreement_kind": "audited_detector_false_positive",
        "decision_id": "canon-a99efed4c22a1a3f",
        "canon_gap_reason": "",
        "detector_error_reason": "u_turn_false_positive",
        "_full_audit_key": (748, "canon-a99efed4c22a1a3f", 1008.0, 1336.0),
    }


def test_nearby_full_corpus_interval_remains_unresolved() -> None:
    outcome = classify_detector_only_interval(
        activity_ordinal=22,
        start_s=53.01,
        end_s=209.0,
        gate_span_decision_ids=["canon-a99efed4c22a1a3f"],
        audited_reference_gaps={},
    )

    assert outcome == {
        "classification": "canon_gap_or_evidence_rejection",
        "disagreement_kind": "detector_spanned_canon_gates_without_traversal",
        "decision_id": "",
        "canon_gap_reason": "",
    }


def test_full_corpus_audit_rejects_an_extra_gate_span_decision() -> None:
    outcome = classify_detector_only_interval(
        activity_ordinal=22,
        start_s=53.0,
        end_s=209.0,
        gate_span_decision_ids=[
            "canon-a99efed4c22a1a3f",
            "canon-unexpected-extra-decision",
        ],
        audited_reference_gaps={},
    )

    assert outcome == {
        "classification": "canon_gap_or_evidence_rejection",
        "disagreement_kind": "full_corpus_audit_context_mismatch",
        "decision_id": "",
        "canon_gap_reason": "",
    }


def test_missing_full_corpus_audit_fails_completeness_without_identity_leak() -> None:
    observed = {
        key: 1 for key in replay_module.AUDITED_FULL_CORPUS_DISAGREEMENTS
    }
    observed.pop(next(iter(observed)))

    completeness = full_corpus_audit_completeness(observed)

    assert completeness == {
        "expected": 8,
        "observed": 7,
        "missing": 1,
        "duplicates": 0,
        "unexpected": 0,
    }
    assert "activity" not in completeness


@pytest.mark.parametrize(
    ("activity_ordinal", "start_s", "end_s"),
    [
        (145, 4217.0, 4478.0),
        (183, 3742.0, 4058.0),
    ],
)
def test_hagys_partial_traversal_detector_false_positives_are_exactly_audited(
    activity_ordinal: int,
    start_s: float,
    end_s: float,
) -> None:
    outcome = classify_detector_only_interval(
        activity_ordinal=activity_ordinal,
        start_s=start_s,
        end_s=end_s,
        gate_span_decision_ids=["canon-4698d2a41a0d7f8f"],
        audited_reference_gaps={},
    )

    assert outcome == {
        "classification": "detector_error",
        "disagreement_kind": "audited_detector_false_positive",
        "decision_id": "canon-4698d2a41a0d7f8f",
        "canon_gap_reason": "",
        "detector_error_reason": "partial_traversal_false_positive",
        "_full_audit_key": (
            activity_ordinal,
            "canon-4698d2a41a0d7f8f",
            start_s,
            end_s,
        ),
    }


def test_final_v025_full_corpus_audit_registry_is_exactly_four_gaps_and_four_errors() -> None:
    expected = {
        (22, "canon-a99efed4c22a1a3f", 53.0, 209.0),
        (22, "canon-45cce7f975578a7d", 2080.0, 2332.0),
        (67, "canon-27921d9d554b85bd", 6802.0, 7045.0),
        (145, "canon-4698d2a41a0d7f8f", 4217.0, 4478.0),
        (183, "canon-4698d2a41a0d7f8f", 3742.0, 4058.0),
        (200, "canon-a99efed4c22a1a3f", 977.0, 1203.0),
        (748, "canon-a99efed4c22a1a3f", 1008.0, 1336.0),
        (749, "canon-b670dc809f8e643b", 1818.0, 2175.0),
    }
    assert set(replay_module.AUDITED_FULL_CORPUS_DISAGREEMENTS) == expected
    classifications = {
        key: value["classification"]
        for key, value in replay_module.AUDITED_FULL_CORPUS_DISAGREEMENTS.items()
    }
    assert list(classifications.values()).count("canon_gap") == 4
    assert list(classifications.values()).count("detector_error") == 4


def test_duplicate_full_corpus_audit_fails_exactly_once_completeness() -> None:
    observed = {
        key: 1 for key in replay_module.AUDITED_FULL_CORPUS_DISAGREEMENTS
    }
    duplicated = next(iter(observed))
    observed[duplicated] = 2

    assert full_corpus_audit_completeness(observed) == {
        "expected": 8,
        "observed": 7,
        "missing": 0,
        "duplicates": 1,
        "unexpected": 0,
    }


def test_pinned_detector_uses_tileservice_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import run_holdout_eval

    adapted = [{"adapter": "tile-service", "speed_mps": 7.5}]
    seen = {}

    def fake_adapter(streams: dict):
        seen["streams"] = streams
        return adapted, []

    def fake_detector(samples: list, **kwargs):
        seen["samples"] = samples
        seen["kwargs"] = kwargs
        return ["detected"]

    monkeypatch.setattr(run_holdout_eval, "streams_to_tile_data", fake_adapter)
    monkeypatch.setattr(run_holdout_eval, "run_detector", fake_detector)

    result = run_pinned_offline_detector({"time": [0], "latlng": [[0.0, 0.0]]})

    assert result == ["detected"]
    assert seen["samples"] is adapted
    assert seen["kwargs"] == {
        "frequency_map": None,
        "use_bridge_preprocessing": False,
    }


def test_disagreement_audit_fails_closed_on_a_new_reference_miss() -> None:
    rows, unresolved = apply_disagreement_audit(
        [
            {
                "_activity_ordinal": 160,
                "decision_id": "canon-f900cfb8fdb96b47",
                "_reference_start_s": 2700.0,
                "_reference_end_s": 2800.0,
                "traversal_match": False,
                "classification": "canon_gap_or_evidence_rejection",
            }
        ]
    )

    assert rows[0]["classification"] == "unclassified_reference_miss"
    assert unresolved > 0


def test_final_v025_reference_gap_audit_is_exactly_the_four_observed_misses() -> None:
    expected = {
        (200, "canon-f900cfb8fdb96b47", 2764.0, 2870.0),
        (272, "canon-cad891a15fe27cfc", 1883.0, 2080.0),
        (556, "canon-a5328e90bebaec92", 7237.0, 7413.0),
        (1105, "canon-f900cfb8fdb96b47", 4982.0, 5106.0),
    }
    assert set(replay_module.AUDITED_CANON_GAPS) == expected
    rows = [
        {
            "_activity_ordinal": ordinal,
            "decision_id": decision_id,
            "_reference_start_s": start_s,
            "_reference_end_s": end_s,
            "traversal_match": False,
            "classification": "canon_gap_or_evidence_rejection",
        }
        for ordinal, decision_id, start_s, end_s in sorted(expected)
    ]

    resolved, unresolved = apply_disagreement_audit(rows)

    assert unresolved == 0
    assert {row["classification"] for row in resolved} == {"canon_gap"}


def test_launch_reconstruction_is_44_plus_15_plus_2_with_four_exact_overlaps() -> None:
    candidates = []
    labels = []
    for index in range(44):
        source = f"{index + 1:064x}"
        current = f"{index + 101:064x}"
        provenance = {}
        if index < 4:
            provenance = {
                "ratified_boundary": {"decision_id": f"boundary-overlap-{index}"}
            }
        candidates.append(
            {
                "candidate_fingerprint": current,
                "legacy_candidate_fingerprints": [source],
                "provenance": provenance,
            }
        )
        labels.append(
            {
                "candidate_id": f"approved-{index}",
                "candidate_fingerprint": source,
                "decision": "approve",
                "display_name": f"Approved {index}",
            }
        )
    for index in range(11):
        fingerprint = f"{index + 501:064x}"
        candidates.append(
            {
                "candidate_fingerprint": fingerprint,
                "legacy_candidate_fingerprints": [f"{index + 601:064x}"],
                "provenance": {
                    "ratified_boundary": {"decision_id": f"boundary-{index}"}
                },
            }
        )
    parker_source = "a" * 64
    candidates.append(
        {
            "candidate_fingerprint": "b" * 64,
            "legacy_candidate_fingerprints": [parker_source],
            "display_name": "Parker Avenue",
            "provenance": {},
        }
    )
    labels.append(
        {
            "candidate_id": "parker",
            "candidate_fingerprint": parker_source,
            "decision": "needs_work",
            "display_name": "Parker Avenue",
        }
    )
    candidates.append(
        {
            "candidate_fingerprint": (
                "ef2c9a235a7b5b4b365d323e4c7d3f73e309390a850d694044a356e24094b45b"
            ),
            "legacy_candidate_fingerprints": ["c" * 64],
            "display_name": "Hagys Ford Road North / Hagys Ford Road",
            "provenance": {},
        }
    )
    labels.append(
        {
            "candidate_id": "hagys",
            "candidate_fingerprint": "d" * 64,
            "decision": "needs_work",
            "display_name": "Hagys Ford Road North / Hagys Ford Road",
        }
    )
    report = {
        "ratified_boundaries": {
            "mode": "applied",
            "applied_decisions": 15,
            "retained_decisions": 15,
        },
        "candidates": candidates,
    }

    selected, audit = resolve_launch_canon_candidates(report, {"labels": labels})

    assert len(selected) == 57
    assert audit["carried_approve_labels"] == 44
    assert audit["boundary_ratifications"] == 15
    assert len(audit["locked_validated_carries"]) == 2
    assert audit["pending_approve_labels"] == []


def test_ambiguous_template_mapping_is_excluded(monkeypatch: pytest.MonkeyPatch) -> None:
    class Connection:
        @staticmethod
        def execute(_query: str):
            class Cursor:
                @staticmethod
                def fetchall():
                    return [(7, "ambiguous", "[[40.0, -75.0], [40.1, -75.1]]")]

            return Cursor()

    candidates = [
        RatifiedCandidate("a", "a" * 64, "A", None, None, None, None),
        RatifiedCandidate("b", "b" * 64, "B", None, None, None, None),
    ]
    monkeypatch.setattr(
        replay_module,
        "_template_maps_candidate",
        lambda _points, _candidate: 1.0,
    )

    mapped, taxonomy = map_reference_templates(Connection(), candidates)

    assert mapped == []
    assert taxonomy["ambiguous_multi_canon_template"] == 1
