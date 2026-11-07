#!/usr/bin/env python3
"""Deterministic, privacy-bounded scoring for the D11 corpus replay gate.

This module deliberately separates three things that are easy to conflate:

* compiler candidates are not ratified canon;
* detector output is comparison evidence, not traversal ground truth;
* an empty denominator is not a passing metric.

The command-line runner at the bottom verifies the pinned corpus and compiler
artifacts, selects only candidates carrying explicit ratified-boundary
provenance, replays the independently mappable reference slice, and emits a
stable aggregate scorecard. Raw GPS and rider identifiers never enter output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence
from uuid import NAMESPACE_URL, UUID, uuid5


EXPECTED_CORPUS_SHA256 = (
    "64b15790bed2628b3e7e8371657b408ec5e96305db84bfe050507b14860b98ee"
)
EXPECTED_CANON_SHA256 = (
    "de67892dc600affd97e0a5158f3a369ca29777b214ecce41be0e47060736bf0e"
)
EXPECTED_LABELS_SHA256 = (
    "77fbdcc691de9d82124f3d848035f103e5433c6ef2bbe3d8bd64782041c4fdd9"
)
EXPECTED_RIDE_COUNT = 1_416
EXPECTED_BOUNDARY_RATIFICATION_COUNT = 15
EXPECTED_LAUNCH_CANON_COUNT = 57
EXPECTED_POSTGIS_CORRIDOR_WKB_MANIFEST_SHA256 = (
    "d5c1d27838d7a1ff59676c123da7b9860ce4e9700477e536684797b0b03ad8ac"
)
EXPECTED_CROSS_RIDER_EVIDENCE_SHA256 = (
    "5aa53b2e4e5e556be318cb421bcec91d9197c3d19a47857a6e59b35cb5eee6c2"
)
EXPECTED_CORRIDOR_EQUIVALENCE_SHA256 = (
    "4cc2c64b4d46f67fbfa6b6f1ef523c3d29ad5d80b8c529f95711b8cc25cc39df"
)
EXPECTED_NATIVE_PARSER_SHA256 = (
    "9f2915020fe49af36880f09a132da81d92910d85824a9329b6b7eb65f7f1e31d"
)
EXPECTED_DETECTOR_IMPLEMENTATION_SHA256 = (
    "0221ef17d8ebcb589cc5d29749c7aaa131502203e89fc9af08567d7a38160830"
)
EXPECTED_DETECTOR_ADAPTER_SHA256 = (
    "346ec7f8ed753977cfed30e79d052593deff5379dbd8e7cc8f94b74f59a674f0"
)
EXPECTED_TRAVERSAL_ENGINE_SHA256 = (
    "869b69c26f86d7d2229cd14b5d048e5dc24a5ca53113f18de4fbdd819ef05106"
)
RECALL_THRESHOLD = 0.95
BOUNDARY_THRESHOLD_M = 10.0
TIMING_THRESHOLD_S = 2.0
TIMING_THINNING_STRIDE = 8
TIMING_DENSE_MAX_GAP_S = 1.5
CROSS_RIDER_AGREEMENT_THRESHOLD = 1.0
REFERENCE_OVERLAP_THRESHOLD = 0.30
REFERENCE_TIME_TOLERANCE_S = 1.0
BOUNDARY_OBSERVATION_SCORING_RULE = (
    "all_accepted_crossings_stable_sorted_distinct_rides_only_for_group_eligibility_v1"
)

# Privacy-safe, manually audited corpus disagreements. Keys are the one-based
# corpus ordinal, launch decision, and exact independent reference interval.
# This avoids embedding raw or dictionary-linkable ride identifiers and keeps
# one audited miss from laundering a different miss on the same ride.
AUDITED_CANON_GAPS = {
    (200, "canon-f900cfb8fdb96b47", 2764.0, 2870.0): "gate_span_partial",
    (272, "canon-cad891a15fe27cfc", 1883.0, 2080.0): "corridor_gps_tolerance",
    (556, "canon-a5328e90bebaec92", 7237.0, 7413.0): "gate_span_partial",
    (1105, "canon-f900cfb8fdb96b47", 4982.0, 5106.0): "gate_span_partial",
}

# Full-corpus detector-only rows audited after the first complete replay. Keys
# pin the corpus ordinal, launch decision, and detector interval. Four traces
# stay within 28-49 m of the canonical centerline and are map/GPS corridor
# gaps; the remaining traces are detector false positives rejected by D11's
# U-turn or partial-traversal rules.
AUDITED_FULL_CORPUS_DISAGREEMENTS = {
    (22, "canon-a99efed4c22a1a3f", 53.0, 209.0): {
        "classification": "canon_gap",
        "reason": "corridor_gps_tolerance",
        "gate_span_decision_ids": ("canon-a99efed4c22a1a3f",),
    },
    (22, "canon-45cce7f975578a7d", 2080.0, 2332.0): {
        "classification": "canon_gap",
        "reason": "corridor_gps_tolerance",
        "gate_span_decision_ids": ("canon-45cce7f975578a7d",),
    },
    (67, "canon-27921d9d554b85bd", 6802.0, 7045.0): {
        "classification": "canon_gap",
        "reason": "corridor_gps_tolerance",
        "gate_span_decision_ids": ("canon-27921d9d554b85bd",),
    },
    # Both Hagys windows cross the start gate in reverse, skip the first half,
    # and join downstream: 50.68% and 51.02% corridor coverage versus the 80%
    # D11 minimum. The accepted control crosses start/finish forward with 100%.
    (145, "canon-4698d2a41a0d7f8f", 4217.0, 4478.0): {
        "classification": "detector_error",
        "reason": "partial_traversal_false_positive",
        "gate_span_decision_ids": ("canon-4698d2a41a0d7f8f",),
    },
    (183, "canon-4698d2a41a0d7f8f", 3742.0, 4058.0): {
        "classification": "detector_error",
        "reason": "partial_traversal_false_positive",
        "gate_span_decision_ids": ("canon-4698d2a41a0d7f8f",),
    },
    (200, "canon-a99efed4c22a1a3f", 977.0, 1203.0): {
        "classification": "canon_gap",
        "reason": "corridor_gps_tolerance",
        "gate_span_decision_ids": ("canon-a99efed4c22a1a3f",),
    },
    (748, "canon-a99efed4c22a1a3f", 1008.0, 1336.0): {
        "classification": "detector_error",
        "reason": "u_turn_false_positive",
        "gate_span_decision_ids": ("canon-a99efed4c22a1a3f",),
    },
    (749, "canon-b670dc809f8e643b", 1818.0, 2175.0): {
        "classification": "detector_error",
        "reason": "partial_traversal_false_positive",
        "gate_span_decision_ids": ("canon-b670dc809f8e643b",),
    },
}


class InputIntegrityError(RuntimeError):
    """A pinned replay input does not match the audited source."""


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def select_boundary_ratifications(report: Mapping[str, Any]) -> list[dict]:
    """Return compiler candidates with explicit boundary-ratification provenance.

    The compiler report contains thousands of possible climbs. A name match or
    a high worthiness score is never enough to promote one into this replay.
    """

    metadata = report.get("ratified_boundaries") or {}
    if metadata.get("mode") != "applied":
        raise InputIntegrityError("canon report is not an applied ratification run")
    retained = int(metadata.get("retained_decisions") or 0)
    applied = int(metadata.get("applied_decisions") or 0)
    selected = [
        dict(candidate)
        for candidate in report.get("candidates") or []
        if isinstance(candidate.get("provenance"), Mapping)
        and isinstance(candidate["provenance"].get("ratified_boundary"), Mapping)
    ]
    selected.sort(key=lambda item: str(item.get("candidate_fingerprint") or ""))
    if not selected or len(selected) != retained or retained != applied:
        raise InputIntegrityError(
            "retained ratification count does not match explicit candidate provenance"
        )
    fingerprints = [str(item.get("candidate_fingerprint") or "") for item in selected]
    if len(set(fingerprints)) != len(fingerprints) or any(
        len(fingerprint) != 64 for fingerprint in fingerprints
    ):
        raise InputIntegrityError("ratified candidate fingerprints are not unique SHA-256-sized values")
    return selected


_LOCKED_VALIDATED_CARRIES = {
    # Parker / Umbria has exact legacy lineage in the current report.
    "Parker Avenue": None,
    # The v0.1 fingerprint was not retained, but the July 18 decision explicitly
    # preserved this unchanged geometry; pinning the current fingerprint avoids
    # a name-only guess.
    "Hagys Ford Road North / Hagys Ford Road": (
        "ef2c9a235a7b5b4b365d323e4c7d3f73e309390a850d694044a356e24094b45b"
    ),
}


def resolve_launch_canon_candidates(
    report: Mapping[str, Any],
    review_document: Mapping[str, Any],
) -> tuple[list[dict], dict[str, Any]]:
    """Reconstruct the reviewed launch set through exact fingerprint lineage.

    The applied report marks fifteen corrected boundaries, while the earlier
    Tim-reviewed fixture contains the rest of the launch set. Forty-four
    approvals carry through exact legacy fingerprints, including the four
    restored legacy boundaries, so none remain pending. Parker and Hagys are
    included only because the locked July 18 decision explicitly validates
    those unchanged boundaries.
    """

    candidates = [dict(item) for item in report.get("candidates") or []]
    lineage_owners: dict[str, list[dict]] = defaultdict(list)
    for candidate in candidates:
        fingerprints = [
            str(candidate.get("candidate_fingerprint") or ""),
            *[
                str(value)
                for value in candidate.get("legacy_candidate_fingerprints") or []
            ],
        ]
        for fingerprint in fingerprints:
            if fingerprint:
                lineage_owners[fingerprint].append(candidate)

    selected: dict[str, dict] = {}
    pending_approvals: list[dict[str, str]] = []
    carried_approvals = 0
    labels = list(review_document.get("labels") or [])
    for label in labels:
        if label.get("decision") != "approve":
            continue
        fingerprint = str(label.get("candidate_fingerprint") or "")
        owners = lineage_owners.get(fingerprint, [])
        if len(owners) == 1:
            candidate = dict(owners[0])
            candidate["_launch_decision_id"] = str(
                label.get("candidate_id") or f"review-{fingerprint[:16]}"
            )
            candidate["_launch_authority"] = "tim_review_approve_exact_lineage"
            selected[str(candidate["candidate_fingerprint"])] = candidate
            carried_approvals += 1
        else:
            pending_approvals.append(
                {
                    "display_name": str(label.get("display_name") or ""),
                    "source_fingerprint": fingerprint,
                    "lineage_owner_count": str(len(owners)),
                }
            )

    boundary_candidates = select_boundary_ratifications(report)
    for candidate in boundary_candidates:
        candidate = dict(candidate)
        candidate["_launch_decision_id"] = str(
            candidate["provenance"]["ratified_boundary"]["decision_id"]
        )
        candidate["_launch_authority"] = "ratified_boundary_registry"
        selected[str(candidate["candidate_fingerprint"])] = candidate

    validated_carries: list[str] = []
    for display_name, pinned_fingerprint in _LOCKED_VALIDATED_CARRIES.items():
        source_labels = [
            label
            for label in labels
            if label.get("decision") == "needs_work"
            and label.get("display_name") == display_name
        ]
        if len(source_labels) != 1:
            raise InputIntegrityError(
                f"locked validated carry {display_name!r} has no unique review label"
            )
        if pinned_fingerprint is None:
            owners = lineage_owners.get(
                str(source_labels[0].get("candidate_fingerprint") or ""), []
            )
            if len(owners) != 1:
                raise InputIntegrityError(
                    f"locked validated carry {display_name!r} has ambiguous lineage"
                )
            candidate = owners[0]
        else:
            matches = [
                candidate
                for candidate in candidates
                if candidate.get("candidate_fingerprint") == pinned_fingerprint
            ]
            if len(matches) != 1 or matches[0].get("display_name") != display_name:
                raise InputIntegrityError(
                    f"locked validated carry {display_name!r} fingerprint drifted"
                )
            candidate = matches[0]
        candidate = dict(candidate)
        candidate["_launch_decision_id"] = str(
            source_labels[0].get("candidate_id")
            or f"validated-{candidate['candidate_fingerprint'][:16]}"
        )
        candidate["_launch_authority"] = "locked_july_18_validated_boundary"
        selected[str(candidate["candidate_fingerprint"])] = candidate
        validated_carries.append(display_name)

    ordered = [selected[fingerprint] for fingerprint in sorted(selected)]
    audit = {
        "carried_approve_labels": carried_approvals,
        "boundary_ratifications": len(boundary_candidates),
        "locked_validated_carries": sorted(validated_carries),
        "pending_approve_labels": sorted(
            pending_approvals,
            key=lambda item: (item["display_name"], item["source_fingerprint"]),
        ),
        "resolved_candidates": len(ordered),
    }
    if len(ordered) != EXPECTED_LAUNCH_CANON_COUNT:
        raise InputIntegrityError(
            f"resolved launch canon count drifted: expected {EXPECTED_LAUNCH_CANON_COUNT}, got {len(ordered)}"
        )
    return ordered, audit


def classify_disagreement(
    *,
    detector_match: bool,
    traversal_match: bool,
    independent_reference: bool,
) -> str:
    """Classify without hiding traversal defects inside a forced binary."""

    if independent_reference:
        if detector_match and traversal_match:
            return "agreement"
        if detector_match and not traversal_match:
            return "canon_gap_or_evidence_rejection"
        if traversal_match and not detector_match:
            return "detector_error"
        return "both_missed_reference"
    if detector_match and traversal_match:
        return "unlabelled_agreement"
    if detector_match:
        return "detector_only_off_canon"
    if traversal_match:
        return "traversal_only_unlabelled"
    return "no_output"


def build_cutover_scorecard(
    *,
    corpus_integrity_ok: bool,
    replay_errors: int,
    reference_passes: int,
    reference_h3_hits: int,
    traversal_matches: int,
    boundary_eligible_climb_gate_groups: int,
    boundary_eligible_distinct_rides: int,
    repeat_boundary_endpoints: int,
    boundary_p95_error_m: Optional[float],
    boundary_strict_max_error_m: Optional[float],
    boundary_candidate_manifest_sha256: Optional[str],
    boundary_observation_manifest_sha256: Optional[str],
    boundary_input_manifest_sha256: Optional[str],
    boundary_metric_ratified: bool,
    cross_rider_pairs: int,
    cross_rider_agreements: int,
    cross_rider_supported_candidates: int,
    unclassified_disagreements: int,
    offline_snapshot_integrity_ok: bool = True,
    unresolved_prior_approvals: int = 0,
    timing_metrics: Optional[Mapping[str, Any]] = None,
    legacy_clipped_projection: bool = False,
) -> dict[str, Any]:
    """Build the cutover gates; every missing denominator fails closed."""

    recall_measured = reference_passes > 0
    recall = traversal_matches / reference_passes if recall_measured else None
    replay_pass = bool(corpus_integrity_ok and replay_errors == 0)
    reference_h3_pass = bool(
        reference_passes > 0 and reference_h3_hits == reference_passes
    )
    recall_pass = bool(recall_measured and recall is not None and recall >= RECALL_THRESHOLD)
    boundary_manifests = {
        "candidate_manifest_sha256": boundary_candidate_manifest_sha256,
        "observation_manifest_sha256": boundary_observation_manifest_sha256,
        "input_manifest_sha256": boundary_input_manifest_sha256,
    }
    boundary_measured = bool(
        boundary_eligible_climb_gate_groups > 0
        and boundary_eligible_distinct_rides >= 2
        and repeat_boundary_endpoints > 0
        and boundary_p95_error_m is not None
        and boundary_strict_max_error_m is not None
        and all(_is_sha256(value) for value in boundary_manifests.values())
    )
    boundary_pass = bool(
        boundary_measured
        and boundary_metric_ratified
        and not legacy_clipped_projection
        and float(boundary_p95_error_m) <= BOUNDARY_THRESHOLD_M
    )
    timing = dict(timing_metrics or {})
    timing_p95 = timing.get("_p95_error_s_raw")
    timing_measured = bool(
        timing.get("eligible_climb_gate_groups", 0) > 0
        and timing.get("eligible_distinct_rides", 0) >= 2
        and timing.get("comparisons", 0) > 0
        and timing_p95 is not None and math.isfinite(float(timing_p95))
        and _is_sha256(timing.get("frozen_input", {}).get("input_manifest_sha256"))
    )
    cross_rider_measured = cross_rider_pairs > 0
    cross_rider_value = (
        cross_rider_agreements / cross_rider_pairs if cross_rider_measured else None
    )
    cross_rider_pass = bool(
        cross_rider_measured
        and cross_rider_value is not None
        and cross_rider_value >= CROSS_RIDER_AGREEMENT_THRESHOLD
        and cross_rider_supported_candidates > 0
    )
    classification_pass = unclassified_disagreements == 0
    gates = {
        "offline_canon_authority": {
            "pass": bool(
                offline_snapshot_integrity_ok and unresolved_prior_approvals == 0
            ),
            "pinned_reviewed_snapshot": bool(offline_snapshot_integrity_ok),
            "unresolved_prior_approvals": int(unresolved_prior_approvals),
        },
        "replay_integrity": {
            "pass": replay_pass,
            "corpus_integrity_ok": bool(corpus_integrity_ok),
            "errors": int(replay_errors),
        },
        "reference_h3_coverage": {
            "pass": reference_h3_pass,
            "hits": int(reference_h3_hits),
            "reference_passes": int(reference_passes),
            "value": (
                round(reference_h3_hits / reference_passes, 6)
                if reference_passes > 0
                else None
            ),
        },
        "recall": {
            "pass": recall_pass,
            "measured": recall_measured,
            "value": round(recall, 6) if recall is not None else None,
            "matches": int(traversal_matches),
            "reference_passes": int(reference_passes),
            "threshold": RECALL_THRESHOLD,
        },
        "boundary_agreement": {
            "pass": boundary_pass,
            "measured": boundary_measured,
            "metric_ratified": bool(boundary_metric_ratified),
            "legacy_historical_reproduction_only": bool(legacy_clipped_projection),
            "eligible_climb_gate_groups": int(boundary_eligible_climb_gate_groups),
            "eligible_distinct_rides": int(boundary_eligible_distinct_rides),
            "repeat_endpoints": int(repeat_boundary_endpoints),
            "p95_error_m": (
                round(float(boundary_p95_error_m), 3)
                if boundary_p95_error_m is not None
                else None
            ),
            "strict_max_error_m": (
                round(float(boundary_strict_max_error_m), 3)
                if boundary_strict_max_error_m is not None
                else None
            ),
            "threshold_m": BOUNDARY_THRESHOLD_M,
            "aggregation": "pooled_endpoint_p95_repeat_median",
            "frozen_input_manifests": boundary_manifests,
        },
        "timing_agreement": {
            **{key: value for key, value in timing.items() if not key.startswith("_")},
            "pass": bool(timing_measured and float(timing_p95) <= TIMING_THRESHOLD_S
                         and timing.get("missing_probe_crossings", 0) == 0),
            "measured": timing_measured,
            "p95_error_s": round(float(timing_p95), 6) if timing_p95 is not None else None,
            "threshold_s": TIMING_THRESHOLD_S,
            "stride": TIMING_THINNING_STRIDE,
        },
        "cross_rider_agreement": {
            "pass": cross_rider_pass,
            "measured": cross_rider_measured,
            "value": round(cross_rider_value, 6) if cross_rider_value is not None else None,
            "agreements": int(cross_rider_agreements),
            "pairs": int(cross_rider_pairs),
            "supported_candidates": int(cross_rider_supported_candidates),
            "threshold": CROSS_RIDER_AGREEMENT_THRESHOLD,
        },
        "disagreement_classification": {
            "pass": classification_pass,
            "unclassified": int(unclassified_disagreements),
        },
    }
    return {
        "model": "canon_traversal_cutover_scorecard_v3",
        "overall_pass": all(gate["pass"] for gate in gates.values()),
        "gates": gates,
    }


@dataclass(frozen=True)
class RatifiedCandidate:
    decision_id: str
    fingerprint: str
    display_name: str
    runtime: Any
    exact_corridor: Any
    projected_centerline: Any
    project_forward: Any


@dataclass(frozen=True)
class ReferenceTemplate:
    segment_id: int
    segment_name: str
    candidate_fingerprint: str
    decision_id: str
    corridor_coverage: float


@dataclass(frozen=True)
class ExpectedPass:
    activity_id: str
    segment_id: int
    candidate_fingerprint: str
    decision_id: str
    start_s: float
    end_s: float


@dataclass(frozen=True)
class ObservedPass:
    activity_id: str
    candidate_fingerprint: str
    decision_id: str
    start_s: float
    end_s: float
    start_lat: float
    start_lon: float
    finish_lat: float
    finish_lon: float
    start_progress_m: float
    finish_progress_m: float
    start_timing: Optional[Mapping[str, Any]] = None
    finish_timing: Optional[Mapping[str, Any]] = None


def crossing_progress_m(
    candidate: RatifiedCandidate, lon: float, lat: float,
    payload: Mapping[str, Any], *, legacy_clipped_projection: bool = False,
) -> float:
    """D13 projects the intersection itself; legacy is historical replay only."""
    from shapely.geometry import Point

    if legacy_clipped_projection:
        evidence = payload["direction_evidence"]
        before = float(evidence["before"]["along_track_m"])
        after = float(evidence["after"]["along_track_m"])
        return before + float(payload["interpolation_u"]) * (after - before)
    return float(candidate.projected_centerline.project(
        Point(*candidate.project_forward.transform(lon, lat))))


def timing_thinning_probe(
    raw_samples: Sequence[Mapping[str, Any]], candidate: RatifiedCandidate,
    gate_name: str, payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare one dense crossing with all eight sampling phases.

    Select brackets by sample position, before examining any error. Guard every
    original interval spanning the original and retained brackets, not merely
    their total duration. Pauses/recording edges are counted, never scored as
    zero. Lost/ambiguous crossings remain failed offsets in the p95 population.
    """
    from app.services.canon_traversal import _gate_observations, _normalize_samples, _project_candidate

    samples, _, _ = _normalize_samples(raw_samples)
    positions = {s.source_index: i for i, s in enumerate(samples)}
    bracket = payload["bracketing_samples"]
    left = positions[bracket["start"]["source_index"]]
    right = positions[bracket["end"]["source_index"]]
    gap = samples[right].t_s - samples[left].t_s
    result: dict[str, Any] = {"bracket_gap_s": gap,
                             "dense": 0 < gap <= TIMING_DENSE_MAX_GAP_S,
                             "offsets": []}
    if not result["dense"]:
        return result
    projected = None
    stride = TIMING_THINNING_STRIDE
    for offset in range(stride):
        # Match the reviewed experiment's +/-three-stride neighbourhood. A
        # phase with multiple forward crossings is ambiguous, never cherry-pick
        # the crossing whose time happens to agree best.
        indices = [j for j in range(max(0, left - 3 * stride),
                                   min(len(samples), left + 3 * stride + 2))
                   if j % stride == offset]
        lower = [j for j in indices if j <= left]
        upper = [j for j in indices if j >= right]
        item: dict[str, Any] = {"offset": offset}
        result["offsets"].append(item)
        if not lower or not upper:
            item["status"] = "recording_edge"
            continue
        if projected is None:
            projected = _project_candidate(candidate.runtime)
        crossings = [x for x in _gate_observations(
            gate_name=gate_name,
            gate=projected.gate_start if gate_name == "start" else projected.gate_end,
            projected=projected, samples=[samples[j] for j in indices])
            if x.crosses_gate and x.direction > 0]
        lo, hi = lower[-1], upper[0]
        if len(crossings) == 1:
            lo = min(left, positions[crossings[0].segment_start_source_index])
            hi = max(right, positions[crossings[0].segment_end_source_index])
        window = samples[lo:hi + 1]
        if any(not 0 < b.t_s - a.t_s <= TIMING_DENSE_MAX_GAP_S
               or b.source_index != a.source_index + 1
               for a, b in zip(window, window[1:])):
            item["status"] = "recording_pause"
            continue
        if len(crossings) != 1:
            item["status"] = "no_unique_forward_crossing"
        else:
            item.update(status="measured",
                        error_s=float(crossings[0].time_s - payload["time_s_raw"]))
    return result


def observed_pass_from_pattern(
    activity_id: str, candidate: RatifiedCandidate, pattern: Any,
    raw_samples: Sequence[Mapping[str, Any]], *, legacy_clipped_projection: bool = False,
) -> ObservedPass:
    """Shared production/reference and full-corpus scorecard observation path."""
    crossing = pattern.match_trace["gate_crossings"]
    return ObservedPass(
        activity_id=activity_id, candidate_fingerprint=candidate.fingerprint,
        decision_id=candidate.decision_id,
        start_s=float(crossing["start_time_s_raw"]),
        end_s=float(crossing["finish_time_s_raw"]),
        start_lat=float(pattern.start_lat), start_lon=float(pattern.start_lon),
        finish_lat=float(pattern.end_lat), finish_lon=float(pattern.end_lon),
        start_progress_m=crossing_progress_m(candidate, pattern.start_lon, pattern.start_lat,
                                             crossing["start"], legacy_clipped_projection=legacy_clipped_projection),
        finish_progress_m=crossing_progress_m(candidate, pattern.end_lon, pattern.end_lat,
                                              crossing["finish"], legacy_clipped_projection=legacy_clipped_projection),
        start_timing=timing_thinning_probe(raw_samples, candidate, "start", crossing["start"]),
        finish_timing=timing_thinning_probe(raw_samples, candidate, "finish", crossing["finish"]),
    )


def _verify_hash(path: Path, expected: str, label: str) -> str:
    actual = sha256_file(path)
    if actual != expected:
        raise InputIntegrityError(
            f"{label} SHA-256 mismatch: expected {expected}, got {actual}"
        )
    return actual


def _open_corpus_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    integrity = connection.execute("PRAGMA integrity_check").fetchone()
    if not integrity or integrity[0] != "ok":
        connection.close()
        raise InputIntegrityError(f"corpus SQLite integrity failed: {integrity!r}")
    rides = int(connection.execute("SELECT COUNT(*) FROM rides").fetchone()[0])
    streams = int(
        connection.execute("SELECT COUNT(*) FROM activity_streams").fetchone()[0]
    )
    joined = int(
        connection.execute(
            "SELECT COUNT(*) FROM rides JOIN activity_streams USING(activity_id)"
        ).fetchone()[0]
    )
    if (rides, streams, joined) != (
        EXPECTED_RIDE_COUNT,
        EXPECTED_RIDE_COUNT,
        EXPECTED_RIDE_COUNT,
    ):
        connection.close()
        raise InputIntegrityError(
            f"corpus ride/stream counts drifted: rides={rides}, streams={streams}, joined={joined}"
        )
    return connection


def load_cross_rider_evidence(path: Path) -> dict[str, Any]:
    _verify_hash(
        path,
        EXPECTED_CROSS_RIDER_EVIDENCE_SHA256,
        "cross-rider evidence",
    )
    document = json.loads(path.read_text())
    if document.get("model") != "canon_cross_rider_evidence_v2":
        raise InputIntegrityError("unsupported cross-rider evidence model")
    if document.get("canon_report_sha256") != EXPECTED_CANON_SHA256:
        raise InputIntegrityError("cross-rider evidence targets a different canon report")
    metric = document.get("same_canon_cross_rider_agreement") or {}
    pairs = int(metric.get("pairs") or 0)
    agreements = int(metric.get("agreements") or 0)
    if pairs < 0 or agreements < 0 or agreements > pairs:
        raise InputIntegrityError("cross-rider evidence has an invalid agreement denominator")
    expected_value = agreements / pairs if pairs else None
    if metric.get("value") != expected_value:
        raise InputIntegrityError("cross-rider evidence value does not match its numerator")
    if int(metric.get("supported_candidates") or 0) <= 0 and pairs > 0:
        raise InputIntegrityError("cross-rider evidence has pairs without candidate support")
    source_manifest = document.get("source_manifest") or {}
    required_manifest_hashes = {
        "candidate_corridor_manifest_sha256",
        "authoritative_wkb_manifest_sha256",
        "all_objects_sha256",
        "corridor_hit_objects_sha256",
        "eligible_objects_multiset_sha256",
        "eligible_unique_objects_sha256",
        "accepted_objects_multiset_sha256",
        "accepted_unique_objects_sha256",
        "eligible_attempts_sha256",
        "scored_attempt_outcomes_sha256",
        "eligible_unique_sources_sha256",
        "eligible_pair_manifest_sha256",
        "scored_pair_outcomes_sha256",
    }
    if any(not _is_sha256(source_manifest.get(key)) for key in required_manifest_hashes):
        raise InputIntegrityError("cross-rider evidence is missing source manifest digests")
    if (
        source_manifest.get("authoritative_wkb_manifest_sha256")
        != EXPECTED_POSTGIS_CORRIDOR_WKB_MANIFEST_SHA256
    ):
        raise InputIntegrityError(
            "cross-rider evidence targets a different authoritative PostGIS WKB manifest"
        )
    if int((document.get("geographic_census") or {}).get("launch_candidates") or 0) != EXPECTED_LAUNCH_CANON_COUNT:
        raise InputIntegrityError("cross-rider evidence does not cover the launch snapshot")
    runtime = document.get("replay_runtime") or {}
    if runtime.get("native_parser_sha256") != EXPECTED_NATIVE_PARSER_SHA256:
        raise InputIntegrityError("cross-rider evidence used a different native parser")
    if runtime.get("traversal_engine_sha256") != EXPECTED_TRAVERSAL_ENGINE_SHA256:
        raise InputIntegrityError("cross-rider evidence used a different traversal engine")
    dogfood = document.get("dogfood_negative_control") or {}
    if int(dogfood.get("accepted_passes") or 0) != 0:
        raise InputIntegrityError("dogfood negative control unexpectedly contains a canon pass")
    return document


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    if len(text) != 64:
        return False
    try:
        int(text, 16)
    except ValueError:
        return False
    return text == text.lower()


def load_corridor_equivalence(path: Path) -> dict[str, Any]:
    _verify_hash(
        path,
        EXPECTED_CORRIDOR_EQUIVALENCE_SHA256,
        "corridor equivalence evidence",
    )
    document = json.loads(path.read_text())
    if document.get("model") != "canon_corridor_equivalence_v1":
        raise InputIntegrityError("unsupported corridor equivalence model")
    if document.get("canon_report_sha256") != EXPECTED_CANON_SHA256:
        raise InputIntegrityError("corridor evidence targets a different canon report")
    if int(document.get("candidate_count") or 0) != EXPECTED_LAUNCH_CANON_COUNT:
        raise InputIntegrityError("corridor evidence has the wrong candidate count")
    manifest = document.get("authoritative_wkb_manifest") or {}
    if manifest.get("sha256") != EXPECTED_POSTGIS_CORRIDOR_WKB_MANIFEST_SHA256:
        raise InputIntegrityError("authoritative PostGIS WKB manifest drifted")
    sensitivity = document.get("reference_sensitivity") or {}
    required = {
        "templates": 11,
        "expected_passes": 98,
        "local_matches": 94,
        "authoritative_matches": 94,
        "observed_patterns_each": 96,
    }
    if any(int(sensitivity.get(key) or 0) != value for key, value in required.items()):
        raise InputIntegrityError("corridor reference-sensitivity evidence drifted")
    if not all(
        bool(sensitivity.get(key))
        for key in (
            "mapped_identically",
            "match_vector_identical",
            "timestamps_identical",
            "rejection_taxonomy_identical",
        )
    ):
        raise InputIntegrityError("corridor classification equivalence is incomplete")
    return document


def verify_runtime_dependencies() -> dict[str, str]:
    """Pin native and Python detector/traversal implementations fail-closed."""

    import workout_parse
    from app.services.patterns import climb as climb_module

    package_dir = Path(workout_parse.__file__).resolve().parent
    native_modules = sorted(package_dir.glob("workout_parse*.so"))
    if len(native_modules) != 1 or climb_module._get_workout_parse() is None:
        raise InputIntegrityError("native workout_parse detector runtime is unavailable")
    repo_root = Path(__file__).resolve().parents[2]
    paths = {
        "native_parser_sha256": native_modules[0],
        "detector_implementation_sha256": repo_root
        / "backend/app/services/patterns/climb.py",
        "detector_adapter_sha256": Path(__file__).with_name("run_holdout_eval.py"),
        "traversal_engine_sha256": repo_root
        / "backend/app/services/canon_traversal.py",
    }
    expected = {
        "native_parser_sha256": EXPECTED_NATIVE_PARSER_SHA256,
        "detector_implementation_sha256": EXPECTED_DETECTOR_IMPLEMENTATION_SHA256,
        "detector_adapter_sha256": EXPECTED_DETECTOR_ADAPTER_SHA256,
        "traversal_engine_sha256": EXPECTED_TRAVERSAL_ENGINE_SHA256,
    }
    observed = {key: sha256_file(path) for key, path in paths.items()}
    for key, digest in expected.items():
        if observed[key] != digest:
            raise InputIntegrityError(
                f"runtime dependency {key} drifted: expected {digest}, got {observed[key]}"
            )
    return observed


def _exact_metric_corridor(centerline: Any, half_width_m: float) -> tuple[Any, Any, Any]:
    from pyproj import CRS, Transformer
    from shapely.geometry import MultiPolygon, Polygon
    from shapely.ops import transform

    midpoint = centerline.interpolate(0.5, normalized=True)
    local_crs = CRS.from_proj4(
        "+proj=aeqd "
        f"+lat_0={midpoint.y:.12f} +lon_0={midpoint.x:.12f} "
        "+datum=WGS84 +units=m +no_defs"
    )
    forward = Transformer.from_crs("EPSG:4326", local_crs, always_xy=True)
    inverse = Transformer.from_crs(local_crs, "EPSG:4326", always_xy=True)
    projected_centerline = transform(forward.transform, centerline)
    corridor = transform(
        inverse.transform,
        projected_centerline.buffer(float(half_width_m)),
    )
    if isinstance(corridor, Polygon):
        corridor = MultiPolygon([corridor])
    return corridor, projected_centerline, forward


def load_ratified_runtime_candidates(
    selected: Sequence[Mapping[str, Any]],
) -> list[RatifiedCandidate]:
    from shapely import wkt

    backend_dir = Path(__file__).resolve().parents[2] / "backend"
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    from app.models.canon import CanonClimb

    fingerprint_digest = hashlib.sha256(
        "\n".join(item["candidate_fingerprint"] for item in selected).encode("ascii")
    ).hexdigest()
    result: list[RatifiedCandidate] = []
    for item in selected:
        fingerprint = str(item["candidate_fingerprint"])
        decision_id = str(item.get("_launch_decision_id") or "")
        if not decision_id:
            raise InputIntegrityError(
                f"launch candidate {fingerprint} has no decision authority"
            )
        profile_hash = item["provenance"]["canonical_profile_hash"]
        centerline = wkt.loads(item["centerline_wkt"])
        corridor, projected_centerline, forward = _exact_metric_corridor(
            centerline,
            float(item["corridor_half_width_m"]),
        )
        runtime = CanonClimb(
            registry_id=uuid5(NAMESPACE_URL, f"boulderroller:offline-registry:{fingerprint}"),
            canon_id=uuid5(NAMESPACE_URL, f"boulderroller:offline-canon:{fingerprint}"),
            version=1,
            display_name=item["display_name"],
            route_name=item.get("route_name"),
            centerline=centerline,
            corridor=corridor,
            gate_start=wkt.loads(item["gate_start_wkt"]),
            gate_end=wkt.loads(item["gate_end_wkt"]),
            canonical_profile=tuple(item["canonical_profile"]),
            length_m=float(item["length_m"]),
            vert_m=float(item["vert_m"]),
            avg_gradient_pct=float(item["avg_gradient_pct"]),
            compiler_version=item["compiler_version"],
            profile_hash_algorithm=profile_hash["algorithm"],
            profile_hash=profile_hash["value"],
            odbl_source=item["odbl_source"],
            corridor_tile_ids=tuple(
                str(cell["tile_id"]) for cell in item.get("corridor_cells") or []
            ),
            candidate_fingerprint=fingerprint,
            registry_snapshot_digest=fingerprint_digest,
            provenance=item["provenance"],
        )
        result.append(
            RatifiedCandidate(
                decision_id=decision_id,
                fingerprint=fingerprint,
                display_name=str(item["display_name"]),
                runtime=runtime,
                exact_corridor=corridor,
                projected_centerline=projected_centerline,
                project_forward=forward,
            )
        )
    return result


def _intersection_along(line: Any, gate: Any) -> list[float]:
    from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPoint, Point

    intersection = line.intersection(gate)
    points: list[Any] = []
    if intersection.is_empty:
        return []
    if isinstance(intersection, Point):
        points = [intersection]
    elif isinstance(intersection, MultiPoint):
        points = list(intersection.geoms)
    elif isinstance(intersection, (LineString, MultiLineString)):
        geoms = [intersection] if isinstance(intersection, LineString) else list(intersection.geoms)
        for geometry in geoms:
            points.extend([geometry.boundary.geoms[0], geometry.boundary.geoms[-1]])
    elif isinstance(intersection, GeometryCollection):
        for geometry in intersection.geoms:
            if isinstance(geometry, Point):
                points.append(geometry)
    return sorted(float(line.project(point)) for point in points)


def _template_maps_candidate(points: Sequence[Sequence[float]], candidate: RatifiedCandidate) -> Optional[float]:
    from shapely.geometry import LineString, Point

    if len(points) < 3:
        return None
    coordinates = []
    for raw_point in points:
        if not isinstance(raw_point, Sequence) or len(raw_point) < 2:
            return None
        lat = float(raw_point[0])
        lon = float(raw_point[1])
        if not math.isfinite(lat) or not math.isfinite(lon):
            return None
        coordinates.append((lon, lat))
    line = LineString(coordinates)
    starts = _intersection_along(line, candidate.runtime.gate_start)
    finishes = _intersection_along(line, candidate.runtime.gate_end)
    ordered_pairs = [
        (start, finish)
        for start in starts
        for finish in finishes
        if finish > start
    ]
    if not ordered_pairs:
        return None
    start_along, finish_along = min(ordered_pairs, key=lambda pair: (pair[0], pair[1]))
    cumulative = [0.0]
    for previous, current in zip(coordinates, coordinates[1:]):
        cumulative.append(
            cumulative[-1]
            + math.hypot(current[0] - previous[0], current[1] - previous[1])
        )
    between = [
        (lon, lat)
        for (lon, lat), along in zip(coordinates, cumulative)
        if start_along <= along <= finish_along
    ]
    if len(between) < 3:
        return None
    coverage = sum(
        candidate.exact_corridor.covers(Point(lon, lat))
        for lon, lat in between
    ) / len(between)
    if coverage < 0.80:
        return None
    projected_points = []
    for lon, lat in between:
        x, y = candidate.project_forward.transform(lon, lat)
        projected_points.append(Point(x, y))
    progress = [candidate.projected_centerline.project(point) for point in projected_points]
    running_max = progress[0]
    maximum_backtrack = 0.0
    for value in progress[1:]:
        maximum_backtrack = max(maximum_backtrack, running_max - value)
        running_max = max(running_max, value)
    if maximum_backtrack > 12.0:
        return None
    return coverage


def map_reference_templates(
    connection: sqlite3.Connection,
    candidates: Sequence[RatifiedCandidate],
) -> tuple[list[ReferenceTemplate], dict[str, int]]:
    """Map only unique, complete, pre-D11 segment templates to canon."""

    mapped: list[ReferenceTemplate] = []
    counters: Counter[str] = Counter()
    rows = connection.execute(
        "SELECT segment_id, segment_name, polyline_json FROM segment_templates ORDER BY segment_id"
    ).fetchall()
    for segment_id, name, polyline_json in rows:
        try:
            points = json.loads(polyline_json)
        except (TypeError, json.JSONDecodeError):
            counters["invalid_template"] += 1
            continue
        matches = []
        for candidate in candidates:
            coverage = _template_maps_candidate(points, candidate)
            if coverage is not None:
                matches.append((candidate, coverage))
        if len(matches) == 1:
            candidate, coverage = matches[0]
            mapped.append(
                ReferenceTemplate(
                    segment_id=int(segment_id),
                    segment_name=str(name or ""),
                    candidate_fingerprint=candidate.fingerprint,
                    decision_id=candidate.decision_id,
                    corridor_coverage=float(coverage),
                )
            )
            counters["unique_complete_template"] += 1
            counters["complete_template_canon_mappings"] += 1
        elif len(matches) > 1:
            counters["ambiguous_multi_canon_template"] += 1
        else:
            counters["not_complete"] += 1
    return mapped, dict(sorted(counters.items()))


def _streams_for_activity(connection: sqlite3.Connection, activity_id: str) -> dict[str, list]:
    row = connection.execute(
        "SELECT streams_json FROM activity_streams WHERE activity_id = ?",
        (activity_id,),
    ).fetchone()
    if not row:
        raise InputIntegrityError(f"missing stream for reference activity {activity_id}")
    raw = json.loads(row[0])
    return {str(stream["type"]): list(stream["data"]) for stream in raw}


def load_expected_passes(
    connection: sqlite3.Connection,
    templates: Sequence[ReferenceTemplate],
) -> list[ExpectedPass]:
    by_segment = {template.segment_id: template for template in templates}
    if not by_segment:
        return []
    placeholders = ",".join("?" for _ in by_segment)
    rows = connection.execute(
        f"""
        SELECT activity_id, segment_id, start_index, end_index
        FROM strava_segment_efforts
        WHERE segment_id IN ({placeholders})
        ORDER BY activity_id, start_index, end_index, segment_id
        """,
        tuple(sorted(by_segment)),
    ).fetchall()
    stream_cache: dict[str, dict[str, list]] = {}
    expected: list[ExpectedPass] = []
    seen: set[tuple[str, str, int, int]] = set()
    for activity_id, segment_id, start_index, end_index in rows:
        activity = str(activity_id)
        streams = stream_cache.setdefault(
            activity,
            _streams_for_activity(connection, activity),
        )
        times = streams.get("time") or []
        start_index = int(start_index)
        end_index = int(end_index)
        if start_index < 0 or end_index <= start_index or end_index >= len(times):
            raise InputIntegrityError(
                f"invalid reference interval for activity {activity}, segment {segment_id}"
            )
        template = by_segment[int(segment_id)]
        key = (activity, template.candidate_fingerprint, start_index, end_index)
        if key in seen:
            continue
        seen.add(key)
        expected.append(
            ExpectedPass(
                activity_id=activity,
                segment_id=int(segment_id),
                candidate_fingerprint=template.candidate_fingerprint,
                decision_id=template.decision_id,
                start_s=float(times[start_index]),
                end_s=float(times[end_index]),
            )
        )
    clustered: list[ExpectedPass] = []
    grouped: dict[tuple[str, str], list[ExpectedPass]] = defaultdict(list)
    for reference in expected:
        grouped[(reference.activity_id, reference.candidate_fingerprint)].append(reference)
    for _, group in sorted(grouped.items()):
        ordered_group = sorted(
            group,
            key=lambda item: (item.start_s, item.end_s, item.segment_id),
        )
        remaining = set(range(len(ordered_group)))
        clusters: list[list[ExpectedPass]] = []
        while remaining:
            seed = min(remaining)
            remaining.remove(seed)
            component = {seed}
            frontier = [seed]
            while frontier:
                current = frontier.pop()
                current_reference = ordered_group[current]
                neighbours = [
                    index
                    for index in sorted(remaining)
                    if _interval_overlap_ratio(
                        current_reference.start_s,
                        current_reference.end_s,
                        ordered_group[index].start_s,
                        ordered_group[index].end_s,
                    )
                    >= REFERENCE_OVERLAP_THRESHOLD
                ]
                for index in neighbours:
                    remaining.remove(index)
                    component.add(index)
                    frontier.append(index)
            clusters.append([ordered_group[index] for index in sorted(component)])
        for cluster in clusters:
            # All independently mapped labels in a cluster contain the same
            # canon pass. The tightest interval avoids counting overlapping
            # Strava labels as separate expected traversals.
            clustered.append(
                min(
                    cluster,
                    key=lambda item: (item.end_s - item.start_s, item.segment_id),
                )
            )
    return sorted(
        clustered,
        key=lambda item: (
            int(item.activity_id),
            item.start_s,
            item.end_s,
            item.candidate_fingerprint,
        ),
    )


def _tile_samples(streams: Mapping[str, Sequence[Any]]) -> list[dict[str, Any]]:
    import h3

    times = streams.get("time") or []
    coordinates = streams.get("latlng") or []
    count = min(len(times), len(coordinates))
    altitude = streams.get("altitude") or []
    watts = streams.get("watts") or []
    heartrate = streams.get("heartrate") or []
    samples: list[dict[str, Any]] = []
    for index in range(count):
        lat, lon = coordinates[index]
        sample: dict[str, Any] = {
            "source_index": index,
            "t": float(times[index]),
            "lat": float(lat),
            "lon": float(lon),
            "tile_id": h3.latlng_to_cell(float(lat), float(lon), 10),
        }
        if index < len(altitude):
            sample["elevation_m"] = altitude[index]
        if index < len(watts):
            sample["power_w"] = watts[index]
        if index < len(heartrate):
            sample["hr_bpm"] = heartrate[index]
        samples.append(sample)
    return samples


def run_pinned_offline_detector(
    streams: Mapping[str, Sequence[Any]],
) -> list[Any]:
    """Run the deterministic detector view through its canonical adapter.

    D11 intentionally consumes lossless raw samples. The legacy detector does
    not: its contract includes TileService normalization and derived speed.
    Keeping that adapter here prevents a superficially similar raw-sample call
    from changing detector output.
    """

    from run_holdout_eval import run_detector, streams_to_tile_data

    detector_samples, _ = streams_to_tile_data(dict(streams))
    return run_detector(
        detector_samples,
        frequency_map=None,
        use_bridge_preprocessing=False,
    )


def _interval_overlap_ratio(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    overlap = max(0.0, min(a_end, b_end) - max(a_start, b_start))
    shorter = min(max(1.0, a_end - a_start), max(1.0, b_end - b_start))
    return overlap / shorter


def _maximum_bipartite_matching(
    adjacency: Mapping[int, Sequence[int]],
    left_order: Sequence[int],
) -> dict[int, int]:
    """Deterministic augmenting-path matching over pre-ranked adjacency."""

    matched_right: dict[int, int] = {}

    def augment(left_index: int, visited_right: set[int]) -> bool:
        for right_index in adjacency[left_index]:
            if right_index in visited_right:
                continue
            visited_right.add(right_index)
            owner = matched_right.get(right_index)
            if owner is None or augment(owner, visited_right):
                matched_right[right_index] = left_index
                return True
        return False

    for left_index in left_order:
        augment(left_index, set())
    return {
        left_index: right_index
        for right_index, left_index in sorted(matched_right.items())
    }


def maximum_interval_matching(
    left: Sequence[tuple[float, float]],
    right: Sequence[tuple[float, float]],
    *,
    threshold: float = REFERENCE_OVERLAP_THRESHOLD,
) -> dict[int, int]:
    """Return a deterministic maximum-cardinality interval matching.

    A greedy best-overlap pass can strand a repeat that has only one possible
    partner. The augmenting-path matcher keeps every detector/traversal output
    one-to-one while maximizing the number of comparable efforts. Stable
    adjacency ordering makes the emitted scorecard reproducible.
    """

    adjacency: dict[int, list[int]] = {}
    for left_index, (left_start, left_end) in enumerate(left):
        candidates = []
        for right_index, (right_start, right_end) in enumerate(right):
            overlap = _interval_overlap_ratio(
                left_start,
                left_end,
                right_start,
                right_end,
            )
            if overlap < threshold:
                continue
            boundary_delta = abs(left_start - right_start) + abs(left_end - right_end)
            candidates.append((right_index, overlap, boundary_delta))
        adjacency[left_index] = [
            right_index
            for right_index, _, _ in sorted(
                candidates,
                key=lambda item: (-item[1], item[2], item[0]),
            )
        ]
    left_order = sorted(
        range(len(left)),
        key=lambda index: (
            len(adjacency[index]),
            left[index][0],
            left[index][1],
            index,
        ),
    )
    return _maximum_bipartite_matching(adjacency, left_order)


def detector_gate_span_decisions(
    samples: Sequence[Mapping[str, Any]],
    candidates: Sequence[RatifiedCandidate],
    start_s: float,
    end_s: float,
) -> list[str]:
    """Return launch decisions whose exact gates a detection spans in order.

    Detector times are whole seconds while gate intersections are fractional,
    so the slice includes the same one-sample tolerance used by the independent
    reference comparison. H3 or corridor proximity alone is deliberately not
    enough to turn an off-canon discovery into a canon disagreement.
    """

    from shapely.geometry import LineString, Point

    low, high = sorted((float(start_s), float(end_s)))
    timed_coordinates = [
        (float(sample["t"]), float(sample["lon"]), float(sample["lat"]))
        for sample in samples
        if low - REFERENCE_TIME_TOLERANCE_S
        <= float(sample["t"])
        <= high + REFERENCE_TIME_TOLERANCE_S
        and math.isfinite(float(sample["lat"]))
        and math.isfinite(float(sample["lon"]))
    ]
    if len(timed_coordinates) < 2:
        return []

    def intersection_positions(segment: Any, gate: Any) -> list[float]:
        intersection = segment.intersection(gate)
        if intersection.is_empty:
            return []
        if intersection.geom_type == "Point":
            return [float(segment.project(intersection))]
        if hasattr(intersection, "geoms"):
            positions = []
            for geometry in intersection.geoms:
                if geometry.geom_type == "Point":
                    positions.append(float(segment.project(geometry)))
                elif hasattr(geometry, "coords"):
                    positions.extend(
                        float(segment.project(Point(coordinate)))
                        for coordinate in geometry.coords
                    )
            return sorted(positions)
        if hasattr(intersection, "coords"):
            return sorted(
                float(segment.project(Point(coordinate)))
                for coordinate in intersection.coords
            )
        return []

    matched = []
    for candidate in candidates:
        saw_start = False
        for before, after in zip(timed_coordinates, timed_coordinates[1:]):
            segment = LineString([(before[1], before[2]), (after[1], after[2])])
            if segment.length == 0:
                continue
            start_positions = intersection_positions(
                segment, candidate.runtime.gate_start
            )
            finish_positions = intersection_positions(
                segment, candidate.runtime.gate_end
            )
            if saw_start and finish_positions:
                matched.append(candidate.decision_id)
                break
            if start_positions and finish_positions:
                if any(
                    start_position <= finish_position
                    for start_position in start_positions
                    for finish_position in finish_positions
                ):
                    matched.append(candidate.decision_id)
                    break
            if start_positions:
                saw_start = True
    return sorted(set(matched))


def classify_detector_only_interval(
    *,
    activity_ordinal: int,
    start_s: float,
    end_s: float,
    gate_span_decision_ids: Sequence[str],
    audited_reference_gaps: Mapping[int, Sequence[Mapping[str, Any]]],
) -> Optional[dict[str, Any]]:
    """Classify one unmatched detector interval, with reference truth first."""

    matching_gaps = []
    for gap in audited_reference_gaps.get(activity_ordinal, []):
        overlap = _interval_overlap_ratio(
            float(start_s),
            float(end_s),
            float(gap["start_s"]),
            float(gap["end_s"]),
        )
        if overlap >= REFERENCE_OVERLAP_THRESHOLD:
            matching_gaps.append((overlap, gap))
    if matching_gaps:
        _, gap = min(
            matching_gaps,
            key=lambda item: (
                -item[0],
                str(item[1].get("decision_id") or ""),
            ),
        )
        return {
            "classification": "canon_gap",
            "disagreement_kind": "detector_found_audited_reference_gap",
            "decision_id": str(gap.get("decision_id") or ""),
            "canon_gap_reason": str(gap.get("reason") or ""),
        }
    full_audit_matches = []
    for decision_id in sorted(set(gate_span_decision_ids)):
        audit_key = (
            int(activity_ordinal),
            decision_id,
            float(start_s),
            float(end_s),
        )
        audit = AUDITED_FULL_CORPUS_DISAGREEMENTS.get(audit_key)
        if audit:
            full_audit_matches.append((audit_key, audit))
    normalized_gate_span_decisions = tuple(
        sorted(set(gate_span_decision_ids))
    )
    if len(full_audit_matches) == 1 and normalized_gate_span_decisions == tuple(
        full_audit_matches[0][1]["gate_span_decision_ids"]
    ):
        audit_key, audit = full_audit_matches[0]
        classification = str(audit["classification"])
        reason = str(audit["reason"])
        return {
            "classification": classification,
            "disagreement_kind": (
                "audited_full_corpus_corridor_gap"
                if classification == "canon_gap"
                else "audited_detector_false_positive"
            ),
            "decision_id": str(audit_key[1]),
            "canon_gap_reason": reason if classification == "canon_gap" else "",
            "detector_error_reason": (
                reason if classification == "detector_error" else ""
            ),
            "_full_audit_key": audit_key,
        }
    if full_audit_matches:
        return {
            "classification": "canon_gap_or_evidence_rejection",
            "disagreement_kind": "full_corpus_audit_context_mismatch",
            "decision_id": "",
            "canon_gap_reason": "",
        }
    if not gate_span_decision_ids:
        return None
    return {
        "classification": "canon_gap_or_evidence_rejection",
        "disagreement_kind": "detector_spanned_canon_gates_without_traversal",
        "decision_id": "",
        "canon_gap_reason": "",
    }


def full_corpus_audit_completeness(
    observed_audits: Mapping[tuple[int, str, float, float], int],
) -> dict[str, int]:
    """Require every pinned audit exactly once without disclosing identities."""

    expected = set(AUDITED_FULL_CORPUS_DISAGREEMENTS)
    missing = sum(
        max(1 - int(observed_audits.get(key, 0)), 0) for key in expected
    )
    duplicates = sum(
        max(int(observed_audits.get(key, 0)) - 1, 0) for key in expected
    )
    unexpected = sum(
        int(count)
        for key, count in observed_audits.items()
        if key not in expected
    )
    return {
        "expected": len(expected),
        "observed": sum(
            1 for key in expected if int(observed_audits.get(key, 0)) == 1
        ),
        "missing": missing,
        "duplicates": duplicates,
        "unexpected": unexpected,
    }


def reference_contains_observed(
    reference_start_s: float,
    reference_end_s: float,
    observed_start_s: float,
    observed_end_s: float,
) -> bool:
    """Allow one sample of interpolation around Strava integer indices."""

    return bool(
        reference_start_s - REFERENCE_TIME_TOLERANCE_S
        <= observed_start_s
        <= observed_end_s
        <= reference_end_s + REFERENCE_TIME_TOLERANCE_S
    )


def replay_reference_slice(
    connection: sqlite3.Connection,
    candidates: Sequence[RatifiedCandidate],
    expected: Sequence[ExpectedPass],
    *,
    corpus_path: Path,
    legacy_clipped_projection: bool = False,
) -> tuple[list[dict[str, Any]], list[ObservedPass], Counter[str], int]:
    """Replay every independently labelled activity through D11 and detector."""

    backend_dir = Path(__file__).resolve().parents[2] / "backend"
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    from app.services.canon_traversal import CanonTraversalEngine

    candidate_by_fingerprint = {candidate.fingerprint: candidate for candidate in candidates}
    expected_by_activity: dict[str, list[ExpectedPass]] = defaultdict(list)
    for reference in expected:
        expected_by_activity[reference.activity_id].append(reference)
    engine = CanonTraversalEngine()
    activity_ordinals = {
        str(row[0]): index
        for index, row in enumerate(
            connection.execute(
                "SELECT activity_id FROM activity_streams "
                "ORDER BY CAST(activity_id AS INTEGER)"
            ).fetchall(),
            start=1,
        )
    }
    rows: list[dict[str, Any]] = []
    accepted: list[ObservedPass] = []
    taxonomy: Counter[str] = Counter()
    errors = 0
    for activity_id in sorted(expected_by_activity, key=lambda value: int(value)):
        references = expected_by_activity[activity_id]
        streams = _streams_for_activity(connection, activity_id)
        samples = _tile_samples(streams)
        activity_tile_ids = {str(sample["tile_id"]) for sample in samples}
        relevant = [
            candidate_by_fingerprint[fingerprint]
            for fingerprint in sorted(
                {reference.candidate_fingerprint for reference in references}
            )
            if activity_tile_ids.intersection(
                candidate_by_fingerprint[fingerprint].runtime.corridor_tile_ids
            )
        ]
        try:
            evaluation = engine.evaluate(
                activity_id=uuid5(NAMESPACE_URL, f"strava-corpus:{activity_id}"),
                wallet="offline-corpus-replay",
                candidates=[candidate.runtime for candidate in relevant],
                raw_samples=samples,
                user_weight_kg=75.0,
            )
            detector = run_pinned_offline_detector(streams)
        except Exception:
            errors += 1
            continue
        observed_by_fingerprint: dict[str, list[ObservedPass]] = defaultdict(list)
        for pattern in evaluation.climb_patterns:
            trace = pattern.match_trace
            fingerprint = str(trace.get("candidate_fingerprint") or "")
            candidate = candidate_by_fingerprint[fingerprint]
            observed = observed_pass_from_pattern(
                activity_id, candidate, pattern, samples,
                legacy_clipped_projection=legacy_clipped_projection)
            observed_by_fingerprint[fingerprint].append(observed)
            accepted.append(observed)
        used_observed: set[tuple[str, float, float]] = set()
        used_detector: set[int] = set()
        for reference in references:
            traversal_match: Optional[ObservedPass] = None
            for observed in observed_by_fingerprint.get(reference.candidate_fingerprint, []):
                key = (observed.candidate_fingerprint, observed.start_s, observed.end_s)
                if key in used_observed:
                    continue
                if reference_contains_observed(
                    reference.start_s,
                    reference.end_s,
                    observed.start_s,
                    observed.end_s,
                ):
                    traversal_match = observed
                    used_observed.add(key)
                    break
            detector_match = False
            for detector_index, detection in enumerate(detector):
                if detector_index in used_detector:
                    continue
                if _interval_overlap_ratio(
                    reference.start_s,
                    reference.end_s,
                    float(detection.start_s),
                    float(detection.end_s),
                ) >= REFERENCE_OVERLAP_THRESHOLD:
                    detector_match = True
                    used_detector.add(detector_index)
                    break
            classification = classify_disagreement(
                detector_match=detector_match,
                traversal_match=traversal_match is not None,
                independent_reference=True,
            )
            taxonomy[classification] += 1
            rows.append(
                {
                    "_activity_ordinal": activity_ordinals[activity_id],
                    "decision_id": reference.decision_id,
                    "segment_id": reference.segment_id,
                    "detector_match": detector_match,
                    "traversal_match": traversal_match is not None,
                    "classification": classification,
                    "h3_candidate_hit": bool(
                        activity_tile_ids.intersection(
                            candidate_by_fingerprint[
                                reference.candidate_fingerprint
                            ].runtime.corridor_tile_ids
                        )
                    ),
                    "_reference_start_s": reference.start_s,
                    "_reference_end_s": reference.end_s,
                }
            )
    return rows, accepted, taxonomy, errors


def apply_disagreement_audit(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Resolve audited traversal misses; leave any new miss fail-closed."""

    resolved: list[dict[str, Any]] = []
    unresolved = 0
    observed_audits: set[tuple[int, str, float, float]] = set()
    for source in rows:
        row = dict(source)
        if not bool(row.get("traversal_match")):
            audit_key = (
                int(row.get("_activity_ordinal") or 0),
                str(row.get("decision_id") or ""),
                float(row.get("_reference_start_s") or 0.0),
                float(row.get("_reference_end_s") or 0.0),
            )
            reason = AUDITED_CANON_GAPS.get(audit_key)
            if reason:
                row["classification"] = "canon_gap"
                row["canon_gap_reason"] = reason
                observed_audits.add(audit_key)
            else:
                row["classification"] = "unclassified_reference_miss"
                unresolved += 1
        resolved.append(row)
    missing_expected_audits = set(AUDITED_CANON_GAPS) - observed_audits
    if missing_expected_audits:
        unresolved += len(missing_expected_audits)
    return resolved, unresolved


def scan_full_corpus(
    connection: sqlite3.Connection,
    candidates: Sequence[RatifiedCandidate],
    *,
    audited_reference_gaps: Optional[
        Mapping[int, Sequence[Mapping[str, Any]]]
    ] = None,
) -> dict[str, Any]:
    """Replay and compare D11 with the pinned detector on all 1,416 rides.

    D11 accepted passes become traversal ground truth in canon-covered
    geography. An independently labelled reference miss can override that
    policy as a canon gap. Otherwise, traversal-only output is a detector
    error and detector-only output that spans both exact canon gates is a canon
    gap/evidence-rejection candidate. Output outside exact canon gate spans
    remains discovery evidence and is not a cutover disagreement.
    """

    backend_dir = Path(__file__).resolve().parents[2] / "backend"
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    from app.services.canon_traversal import CanonTraversalEngine
    from shapely.geometry import LineString

    audited_reference_gaps = audited_reference_gaps or {}
    tile_to_candidates: dict[str, list[RatifiedCandidate]] = defaultdict(list)
    for candidate in candidates:
        for tile_id in candidate.runtime.corridor_tile_ids:
            tile_to_candidates[tile_id].append(candidate)
    launch_bounds = (
        min(candidate.runtime.centerline.bounds[0] for candidate in candidates),
        min(candidate.runtime.centerline.bounds[1] for candidate in candidates),
        max(candidate.runtime.centerline.bounds[2] for candidate in candidates),
        max(candidate.runtime.centerline.bounds[3] for candidate in candidates),
    )
    philadelphia_region_padding_deg = 0.05
    philadelphia_region_bbox = (
        launch_bounds[0] - philadelphia_region_padding_deg,
        launch_bounds[1] - philadelphia_region_padding_deg,
        launch_bounds[2] + philadelphia_region_padding_deg,
        launch_bounds[3] + philadelphia_region_padding_deg,
    )

    rows = connection.execute(
        "SELECT activity_id, streams_json FROM activity_streams ORDER BY CAST(activity_id AS INTEGER)"
    ).fetchall()
    engine = CanonTraversalEngine()
    taxonomy: Counter[str] = Counter()
    comparison_taxonomy: Counter[str] = Counter()
    rejections: Counter[str] = Counter()
    per_candidate: Counter[str] = Counter()
    disagreement_rows: list[dict[str, Any]] = []
    observed_full_audits: Counter[tuple[int, str, float, float]] = Counter()
    scanned = 0
    detector_rides_scanned = 0
    detector_detections = 0
    philadelphia_region_rides = 0
    candidate_hit_rides = 0
    both_gate_intersection_rides = 0
    prefiltered_incomplete_candidates = 0
    traversal_rides = 0
    traversal_passes = 0
    errors = 0

    for activity_id, streams_json in rows:
        scanned += 1
        activity = str(activity_id)
        try:
            raw_streams = json.loads(streams_json)
            streams = {
                str(stream["type"]): list(stream["data"])
                for stream in raw_streams
            }
            samples = _tile_samples(streams)
            if any(
                philadelphia_region_bbox[1]
                <= float(sample["lat"])
                <= philadelphia_region_bbox[3]
                and philadelphia_region_bbox[0]
                <= float(sample["lon"])
                <= philadelphia_region_bbox[2]
                for sample in samples
            ):
                philadelphia_region_rides += 1
            detector = run_pinned_offline_detector(streams)
            detector_rides_scanned += 1
            detector_detections += len(detector)

            relevant: dict[str, RatifiedCandidate] = {}
            for sample in samples:
                for candidate in tile_to_candidates.get(str(sample["tile_id"]), []):
                    relevant[candidate.fingerprint] = candidate
            if not relevant:
                taxonomy["no_canon_h3_coverage"] += 1
                comparison_taxonomy["detector_only_off_canon"] += len(detector)
                continue

            candidate_hit_rides += 1
            finite_coordinates = [
                (float(sample["lon"]), float(sample["lat"]))
                for sample in samples
                if math.isfinite(float(sample["lat"]))
                and math.isfinite(float(sample["lon"]))
            ]
            complete_relevant: dict[str, RatifiedCandidate] = {}
            if len(finite_coordinates) >= 2:
                ride_line = LineString(finite_coordinates)
                complete_relevant = {
                    fingerprint: candidate
                    for fingerprint, candidate in relevant.items()
                    if ride_line.intersects(candidate.runtime.gate_start)
                    and ride_line.intersects(candidate.runtime.gate_end)
                }
                if complete_relevant:
                    both_gate_intersection_rides += 1
                else:
                    taxonomy["canon_h3_without_both_gate_intersections"] += 1
            else:
                taxonomy["insufficient_coordinate_geometry"] += 1

            h3_candidates = [
                relevant[key] for key in sorted(relevant)
            ]
            evaluation_candidates = [
                complete_relevant[key] for key in sorted(complete_relevant)
            ]
            prefiltered_count = len(h3_candidates) - len(evaluation_candidates)
            prefiltered_incomplete_candidates += prefiltered_count
            taxonomy["prefiltered_without_both_gate_intersections"] += prefiltered_count

            patterns: list[Any] = []
            if evaluation_candidates:
                evaluation = engine.evaluate(
                    activity_id=uuid5(NAMESPACE_URL, f"strava-corpus:{activity}"),
                    wallet="offline-full-corpus-replay",
                    candidates=[
                        candidate.runtime for candidate in evaluation_candidates
                    ],
                    raw_samples=samples,
                    user_weight_kg=75.0,
                )
                rejections.update(evaluation.rejections)
                patterns = list(evaluation.climb_patterns)
            if patterns:
                traversal_rides += 1
            traversal_passes += len(patterns)
            for pattern in patterns:
                fingerprint = str(pattern.match_trace.get("candidate_fingerprint") or "")
                per_candidate[fingerprint] += 1
            taxonomy["accepted_traversal_pass"] += len(patterns)
            if not patterns:
                taxonomy["canon_coverage_without_accepted_pass"] += 1

            traversal_intervals = [
                (
                    float(pattern.match_trace["gate_crossings"]["start_time_s_raw"]),
                    float(pattern.match_trace["gate_crossings"]["finish_time_s_raw"]),
                )
                for pattern in patterns
            ]
            detector_intervals = [
                (float(item.start_s), float(item.end_s)) for item in detector
            ]
            matches = maximum_interval_matching(
                traversal_intervals,
                detector_intervals,
            )
            matched_detector = set(matches.values())
            comparison_taxonomy["agreement"] += len(matches)

            candidate_by_fingerprint = {
                candidate.fingerprint: candidate
                for candidate in evaluation_candidates
            }
            for traversal_index, pattern in enumerate(patterns):
                if traversal_index in matches:
                    continue
                fingerprint = str(
                    pattern.match_trace.get("candidate_fingerprint") or ""
                )
                candidate = candidate_by_fingerprint[fingerprint]
                comparison_taxonomy["detector_error"] += 1
                disagreement_rows.append(
                    {
                        "_activity_ordinal": scanned,
                        "classification": "detector_error",
                        "disagreement_kind": "detector_missed_traversal",
                        "decision_id": candidate.decision_id,
                        "detector_match": False,
                        "traversal_match": True,
                    }
                )

            for detector_index, detection in enumerate(detector):
                if detector_index in matched_detector:
                    continue
                gate_span_decisions = detector_gate_span_decisions(
                    samples,
                    h3_candidates,
                    float(detection.start_s),
                    float(detection.end_s),
                )
                outcome = classify_detector_only_interval(
                    activity_ordinal=scanned,
                    start_s=float(detection.start_s),
                    end_s=float(detection.end_s),
                    gate_span_decision_ids=gate_span_decisions,
                    audited_reference_gaps=audited_reference_gaps,
                )
                if outcome is None:
                    comparison_taxonomy["detector_only_off_canon"] += 1
                    continue
                classification = str(outcome["classification"])
                disagreement_kind = str(outcome["disagreement_kind"])
                decision_id = str(outcome.get("decision_id") or "")
                canon_gap_reason = str(outcome.get("canon_gap_reason") or "")
                detector_error_reason = str(
                    outcome.get("detector_error_reason") or ""
                )
                full_audit_key = outcome.get("_full_audit_key")
                if full_audit_key is not None:
                    observed_full_audits[tuple(full_audit_key)] += 1
                comparison_taxonomy[classification] += 1
                row = {
                    "_activity_ordinal": scanned,
                    "classification": classification,
                    "disagreement_kind": disagreement_kind,
                    "detector_match": True,
                    "traversal_match": False,
                    "detector_economic_eligible": bool(
                        getattr(detection, "economic_eligible", True)
                    ),
                    "gate_span_decision_ids": gate_span_decisions,
                }
                if decision_id:
                    row["decision_id"] = decision_id
                if canon_gap_reason:
                    row["canon_gap_reason"] = canon_gap_reason
                if detector_error_reason:
                    row["detector_error_reason"] = detector_error_reason
                disagreement_rows.append(row)
        except Exception as exc:
            errors += 1
            taxonomy[f"replay_error:{type(exc).__name__}"] += 1
        if scanned % 200 == 0:
            print(
                f"full-corpus progress {scanned}/{len(rows)} "
                f"candidate_hits={candidate_hit_rides} both_gates={both_gate_intersection_rides} "
                f"passes={traversal_passes} detections={detector_detections} errors={errors}",
                file=sys.stderr,
                flush=True,
            )

    per_candidate_rows = []
    by_fingerprint = {candidate.fingerprint: candidate for candidate in candidates}
    for fingerprint, count in sorted(
        per_candidate.items(),
        key=lambda item: (by_fingerprint[item[0]].decision_id, item[0]),
    ):
        candidate = by_fingerprint[fingerprint]
        per_candidate_rows.append(
            {
                "decision_id": candidate.decision_id,
                "display_name": candidate.display_name,
                "passes": int(count),
            }
        )
    full_audit_completeness = full_corpus_audit_completeness(
        observed_full_audits
    )
    return {
        "rides_total": len(rows),
        "rides_scanned": scanned,
        "detector_rides_scanned": detector_rides_scanned,
        "detector_detections": detector_detections,
        "philadelphia_coverage": {
            "region_model": "launch_centerline_bounds_plus_0.05_degrees",
            "bbox_lon_lat": [round(value, 7) for value in philadelphia_region_bbox],
            "rides_entering_region": philadelphia_region_rides,
            "rides_total": len(rows),
            "value": round(philadelphia_region_rides / len(rows), 6),
        },
        "candidate_h3_hit_rides": candidate_hit_rides,
        "both_gate_intersection_rides": both_gate_intersection_rides,
        "prefiltered_incomplete_candidate_instances": prefiltered_incomplete_candidates,
        "traversal_rides": traversal_rides,
        "traversal_passes": traversal_passes,
        "detector_comparison_scope": "all_1416_rides",
        "detector_mode": "canonical_v2_scientific_offline_no_frequency_or_bridge_inputs",
        "classification_policy": (
            "D11 accepted traversal is ground truth; traversal-only is "
            "detector_error; detector-only spanning both exact canon gates is "
            "canon_gap_or_evidence_rejection unless independent reference "
            "evidence resolves it as canon_gap"
        ),
        "rejection_scope": (
            "D11 rejection taxonomy covers only candidates whose full ride "
            "LineString intersects both exact gates; zero/one-gate H3 candidates "
            "are counted by the safe prefilter instead"
        ),
        "unclassified_disagreements": int(
            comparison_taxonomy["canon_gap_or_evidence_rejection"]
            + full_audit_completeness["missing"]
            + full_audit_completeness["duplicates"]
            + full_audit_completeness["unexpected"]
        ),
        "full_corpus_audit_completeness": full_audit_completeness,
        "errors": errors,
        "taxonomy": dict(sorted(taxonomy.items())),
        "comparison_taxonomy": dict(sorted(comparison_taxonomy.items())),
        "rejections": dict(sorted(rejections.items())),
        "per_candidate": per_candidate_rows,
        "disagreements": [
            {
                key: value
                for key, value in item.items()
                if not key.startswith("_")
            }
            for item in sorted(
                disagreement_rows,
                key=lambda item: (
                    item["classification"],
                    int(item["_activity_ordinal"]),
                    str(item.get("decision_id") or ""),
                ),
            )
        ],
    }


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6_371_008.8 * math.asin(min(1.0, math.sqrt(value)))


def _lines_sha256(lines: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for line in lines:
        digest.update(line.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _boundary_observation_stable_key(item: ObservedPass) -> tuple[Any, ...]:
    return (
        item.decision_id,
        item.candidate_fingerprint,
        item.activity_id,
        float(item.start_s),
        float(item.end_s),
        float(item.start_progress_m),
        float(item.finish_progress_m),
        float(item.start_lat),
        float(item.start_lon),
        float(item.finish_lat),
        float(item.finish_lon),
    )


def _stable_boundary_observations(
    observed: Sequence[ObservedPass],
) -> list[ObservedPass]:
    """Order every accepted crossing without thinning the frozen observations."""

    return sorted(observed, key=_boundary_observation_stable_key)


def _boundary_observation_manifest_row(item: ObservedPass) -> tuple[str, str]:
    numeric_values = (
        item.start_s,
        item.end_s,
        item.start_progress_m,
        item.finish_progress_m,
        item.start_lat,
        item.start_lon,
        item.finish_lat,
        item.finish_lon,
    )
    if not all(math.isfinite(float(value)) for value in numeric_values):
        raise InputIntegrityError("boundary observation contains a non-finite value")
    activity_token = hashlib.sha256(
        b"canon-boundary-activity-v1\0" + item.activity_id.encode("utf-8")
    ).hexdigest()
    return activity_token, "\t".join(
        (
            activity_token,
            item.decision_id,
            item.candidate_fingerprint,
            f"{item.start_s:.6f}",
            f"{item.end_s:.6f}",
            float(item.start_progress_m).hex(),
            float(item.finish_progress_m).hex(),
            f"{item.start_lat:.9f}",
            f"{item.start_lon:.9f}",
            f"{item.finish_lat:.9f}",
            f"{item.finish_lon:.9f}",
            json.dumps([item.start_timing, item.finish_timing], sort_keys=True,
                       separators=(",", ":"), allow_nan=False),
        )
    )


def _freeze_boundary_inputs(
    observed: Sequence[ObservedPass],
    candidates: Sequence[RatifiedCandidate],
    *,
    source_hashes: Mapping[str, str],
) -> tuple[dict[str, Any], list[ObservedPass]]:
    """Build the D13 input manifest and stable all-crossing score input."""

    scored_observed = _stable_boundary_observations(observed)
    manifest = _build_boundary_input_manifest(
        observed,
        candidates,
        scored_observed,
        source_hashes=source_hashes,
    )
    return manifest, scored_observed


def _build_boundary_input_manifest(
    observed: Sequence[ObservedPass],
    candidates: Sequence[RatifiedCandidate],
    scored_observed: Sequence[ObservedPass],
    *,
    source_hashes: Mapping[str, str],
) -> dict[str, Any]:
    """Freeze D13 inputs before calculating any boundary outcome.

    Activity identifiers are domain-separated and hashed before they enter the
    observation manifest. Only aggregate counts and digests are emitted.
    """

    required_source_hashes = {
        "corpus_sha256",
        "canon_report_sha256",
        "review_labels_sha256",
    }
    if set(source_hashes) != required_source_hashes or any(
        not _is_sha256(source_hashes[key]) for key in required_source_hashes
    ):
        raise InputIntegrityError(
            "boundary input manifest requires exact corpus, canon, and review SHA-256 values"
        )

    candidate_rows = sorted(
        f"{candidate.decision_id}\t{candidate.fingerprint}" for candidate in candidates
    )
    candidate_decisions = [candidate.decision_id for candidate in candidates]
    candidate_fingerprints = [candidate.fingerprint for candidate in candidates]
    if (
        len(candidate_rows) != len(set(candidate_rows))
        or len(candidate_decisions) != len(set(candidate_decisions))
        or len(candidate_fingerprints) != len(set(candidate_fingerprints))
    ):
        raise InputIntegrityError("boundary candidate manifest contains duplicates")
    candidate_keys = {
        (candidate.decision_id, candidate.fingerprint) for candidate in candidates
    }

    observation_rows: list[str] = []
    activity_tokens: set[str] = set()
    candidate_observation_pairs: set[tuple[str, str]] = set()
    for item in observed:
        candidate_key = (item.decision_id, item.candidate_fingerprint)
        if candidate_key not in candidate_keys:
            raise InputIntegrityError(
                "boundary observation references a candidate outside the frozen manifest"
            )
        activity_token, observation_row = _boundary_observation_manifest_row(item)
        activity_tokens.add(activity_token)
        candidate_observation_pairs.add((item.candidate_fingerprint, activity_token))
        observation_rows.append(observation_row)
    observation_rows.sort()
    scored_observation_rows = sorted(
        _boundary_observation_manifest_row(item)[1] for item in scored_observed
    )
    if scored_observation_rows != observation_rows:
        raise InputIntegrityError(
            "boundary scoring input must retain every frozen observation exactly once"
        )

    components: dict[str, Any] = {
        "source_sha256": dict(sorted(source_hashes.items())),
        "candidate_count": len(candidate_rows),
        "candidate_manifest_sha256": _lines_sha256(candidate_rows),
        "observation_count": len(observation_rows),
        "observation_manifest_sha256": _lines_sha256(observation_rows),
        "distinct_activity_count": len(activity_tokens),
        "candidate_activity_pair_count": len(candidate_observation_pairs),
        "observation_scoring_rule": BOUNDARY_OBSERVATION_SCORING_RULE,
        "metric_progress_encoding": "python_float_hex_exact_binary64_v1",
        "scored_observation_count": len(scored_observation_rows),
        "scored_observation_manifest_sha256": _lines_sha256(scored_observation_rows),
    }
    canonical_components = json.dumps(
        components,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "model": "canon_boundary_input_manifest_v2",
        **components,
        "input_manifest_sha256": hashlib.sha256(canonical_components).hexdigest(),
    }


def build_boundary_input_manifest(
    observed: Sequence[ObservedPass],
    candidates: Sequence[RatifiedCandidate],
    *,
    source_hashes: Mapping[str, str],
) -> dict[str, Any]:
    """Public manifest builder with the ratified selection rule fixed in code."""

    return _build_boundary_input_manifest(
        observed,
        candidates,
        _stable_boundary_observations(observed),
        source_hashes=source_hashes,
    )


def boundary_repeat_metrics(
    observed: Sequence[ObservedPass],
    candidates: Sequence[RatifiedCandidate],
    *,
    source_hashes: Mapping[str, str],
    legacy_clipped_projection: bool = False,
) -> dict[str, Any]:
    from shapely.geometry import Point
    from shapely.ops import transform

    candidate_by_fingerprint = {
        candidate.fingerprint: candidate for candidate in candidates
    }
    # Re-project here as well: external replay callers may still supply the old
    # bracket-progress fields. A default score must never silently use them.
    if not legacy_clipped_projection:
        observed = [replace(item,
            start_progress_m=crossing_progress_m(candidate_by_fingerprint[item.candidate_fingerprint],
                                                 item.start_lon, item.start_lat, {}),
            finish_progress_m=crossing_progress_m(candidate_by_fingerprint[item.candidate_fingerprint],
                                                  item.finish_lon, item.finish_lat, {}))
                    for item in observed]
    frozen_input, scored_observed = _freeze_boundary_inputs(
        observed,
        candidates,
        source_hashes=source_hashes,
    )
    projected_gates: dict[tuple[str, str], Any] = {}
    for candidate in candidates:
        projected_gates[(candidate.fingerprint, "start")] = transform(
            candidate.project_forward.transform,
            candidate.runtime.gate_start,
        )
        projected_gates[(candidate.fingerprint, "finish")] = transform(
            candidate.project_forward.transform,
            candidate.runtime.gate_end,
        )
    groups: dict[
        tuple[str, str],
        list[tuple[str, float, tuple[float, float], float]],
    ] = defaultdict(list)
    for item in scored_observed:
        candidate = candidate_by_fingerprint[item.candidate_fingerprint]
        start_xy = candidate.project_forward.transform(item.start_lon, item.start_lat)
        finish_xy = candidate.project_forward.transform(item.finish_lon, item.finish_lat)
        groups[(item.decision_id, "start")].append(
            (
                item.activity_id,
                item.start_progress_m,
                (item.start_lat, item.start_lon),
                float(
                    Point(*start_xy).distance(
                        projected_gates[(item.candidate_fingerprint, "start")]
                    )
                ),
            )
        )
        groups[(item.decision_id, "finish")].append(
            (
                item.activity_id,
                item.finish_progress_m,
                (item.finish_lat, item.finish_lon),
                float(
                    Point(*finish_xy).distance(
                        projected_gates[(item.candidate_fingerprint, "finish")]
                    )
                ),
            )
        )
    errors: list[float] = []
    eligible_ride_ids: set[str] = set()
    gate_intersection_residuals: list[float] = []
    lateral_scatter: list[float] = []
    group_summaries = []
    for key, values in sorted(groups.items()):
        distinct_ride_ids = {activity_id for activity_id, *_ in values}
        if len(distinct_ride_ids) < 2:
            continue
        eligible_ride_ids.update(distinct_ride_ids)
        ordered = sorted(
            (
                (activity_id, (progress_m, point, gate_residual_m))
                for activity_id, progress_m, point, gate_residual_m in values
            ),
            key=lambda item: (
                item[0],
                item[1][0],
                item[1][1][0],
                item[1][1][1],
                item[1][2],
            ),
        )
        center_progress = statistics.median(item[1][0] for item in ordered)
        bracket_deviations = [abs(item[1][0] - center_progress) for item in ordered]
        _, medoid = min(
            ordered,
            key=lambda item: (
                sum(
                    _haversine_m(item[1][1], other[1][1])
                    for other in ordered
                ),
                hashlib.sha256(item[0].encode("ascii")).hexdigest(),
            ),
        )
        lateral = [_haversine_m(item[1][1], medoid[1]) for item in ordered]
        gate_errors = [item[1][2] for item in ordered]
        errors.extend(bracket_deviations)
        gate_intersection_residuals.extend(gate_errors)
        lateral_scatter.extend(lateral)
        group_summaries.append(
            {
                "decision_id": key[0],
                "gate": key[1],
                "rides": len(distinct_ride_ids),
                "observations": len(ordered),
                "p95_error_m": round(_nearest_rank_p95(bracket_deviations), 3),
                "over_10m": sum(value > BOUNDARY_THRESHOLD_M for value in bracket_deviations),
                "max_error_m": round(max(bracket_deviations), 3),
                "max_gate_intersection_residual_m": round(max(gate_errors), 6),
                "max_lateral_scatter_m": round(max(lateral), 3),
            }
        )
    sorted_errors = sorted(errors)
    if sorted_errors:
        index = max(0, math.ceil(0.95 * len(sorted_errors)) - 1)
        p95 = sorted_errors[index]
        maximum = sorted_errors[-1]
    else:
        p95 = maximum = None
    return {
        "frozen_input": frozen_input,
        "eligible_climb_gate_groups": len(group_summaries),
        "eligible_distinct_rides": len(eligible_ride_ids),
        "repeat_endpoints": len(errors),
        "_p95_error_m_raw": p95,
        "_max_error_m_raw": maximum,
        "p95_error_m": round(p95, 3) if p95 is not None else None,
        "max_error_m": round(maximum, 3) if maximum is not None else None,
        "max_lateral_scatter_m": (
            round(max(lateral_scatter), 3) if lateral_scatter else None
        ),
        "max_gate_intersection_residual_m": (
            round(max(gate_intersection_residuals), 6)
            if gate_intersection_residuals
            else None
        ),
        "error_axis": ("legacy_clipped_sample_projection" if legacy_clipped_projection
                       else "observed_crossing_projected_canonical_progress"),
        "aggregation": "pooled_endpoint_p95_repeat_median",
        "observation_scoring_rule": BOUNDARY_OBSERVATION_SCORING_RULE,
        "diagnostic_note": (
            "Cutover uses pooled p95 along-track repeat-median deviation. The "
            "strict maximum, lateral scatter, and gate-intersection residual are "
            "diagnostics only and do not replace the ratified p95 gate."
        ),
        "groups": group_summaries,
    }


def _nearest_rank_p95(values: Sequence[float]) -> Optional[float]:
    return sorted(values)[math.ceil(.95 * len(values)) - 1] if values else None


def _timing_p95(values: Sequence[float], failed_offsets: int) -> Optional[float]:
    """A missing crossing ranks as +infinity, never disappearing from the pool.

    None means no denominator or an unbounded p95; JSON never contains Infinity.
    This is exactly the pooled <=2 s bar, not an additional zero-loss gate.
    """
    count = len(values) + failed_offsets
    rank = math.ceil(.95 * count) - 1
    return sorted(values)[rank] if count and rank < len(values) else None


def timing_agreement_metrics(
    observed: Sequence[ObservedPass], candidates: Sequence[RatifiedCandidate], *,
    source_hashes: Mapping[str, str],
) -> dict[str, Any]:
    """All crossing/offset errors, with the same two-distinct-ride eligibility."""
    frozen, ordered = _freeze_boundary_inputs(observed, candidates, source_hashes=source_hashes)
    grouped: dict[tuple[str, str], list[tuple[str, Optional[Mapping[str, Any]]]]] = defaultdict(list)
    for item in ordered:
        grouped[(item.decision_id, "start")].append((item.activity_id, item.start_timing))
        grouped[(item.decision_id, "finish")].append((item.activity_id, item.finish_timing))
    pool: list[float] = []
    eligible_rides: set[str] = set()
    totals: Counter[str] = Counter()
    summaries = []
    for candidate in sorted(candidates, key=lambda c: c.decision_id):
        for gate in ("start", "finish"):
            values = grouped[(candidate.decision_id, gate)]
            rides = {ride for ride, _ in values}
            eligible = len(rides) >= 2
            errors: list[float] = []
            counts: Counter[str] = Counter()
            compared, over_1s, paused = set(), set(), set()
            for ride, probe in values:
                if probe is None:
                    counts["missing_probe_crossings"] += 1
                    continue
                if not probe["dense"]:
                    counts["non_1s_crossings"] += 1
                    continue
                counts["dense_crossings"] += 1
                offsets = probe["offsets"]
                if sorted(p["offset"] for p in offsets) != list(range(TIMING_THINNING_STRIDE)):
                    raise InputIntegrityError("timing probe must retain every offset exactly once")
                for point in offsets:
                    status = point["status"]
                    if status == "measured":
                        value = abs(float(point["error_s"]))
                        if not math.isfinite(value):
                            raise InputIntegrityError("non-finite timing error")
                        errors.append(value)
                        compared.add(ride)
                        if value > 1:
                            over_1s.add(ride)
                    elif status == "recording_pause":
                        counts["pause_guarded_offsets"] += 1
                        paused.add(ride)
                    elif status == "recording_edge":
                        counts["edge_guarded_offsets"] += 1
                    elif status == "no_unique_forward_crossing":
                        counts["unmeasurable_offsets"] += 1
                    else:
                        raise InputIntegrityError(f"unknown timing probe status: {status}")
            failures = counts["unmeasurable_offsets"]
            row = {"decision_id": candidate.decision_id, "display_name": candidate.display_name,
                   "gate": gate, "eligible": eligible, "rides": len(rides),
                   "crossings": len(values), "compared_rides": len(compared),
                   "rides_over_1s": len(over_1s), "rides_with_pause_guard": len(paused),
                   "comparisons": len(errors) + failures, "measured_offsets": len(errors),
                   "median_error_s": statistics.median(errors) if errors else None,
                   "p95_error_s": _timing_p95(errors, failures),
                   "p95_measured_only_s": _nearest_rank_p95(errors),
                   "p95_unbounded": bool(failures and _timing_p95(errors, failures) is None),
                   "max_error_s": max(errors) if errors and not failures else None,
                   "max_measured_error_s": max(errors) if errors else None,
                   **{key: counts[key] for key in (
                       "dense_crossings", "non_1s_crossings", "missing_probe_crossings",
                       "pause_guarded_offsets", "edge_guarded_offsets", "unmeasurable_offsets")}}
            summaries.append(row)
            if eligible:
                pool.extend(errors)
                eligible_rides.update(compared)
                totals.update(counts)
    failures = totals["unmeasurable_offsets"]
    raw_p95 = _timing_p95(pool, failures)
    return {"frozen_input": frozen,
            "eligible_climb_gate_groups": sum(g["eligible"] for g in summaries),
            "eligible_distinct_rides": len(eligible_rides),
            "comparisons": len(pool) + failures, "measured_offsets": len(pool),
            "_p95_error_s_raw": raw_p95, "p95_error_s": raw_p95,
            "p95_measured_only_s": _nearest_rank_p95(pool),
            "p95_unbounded": bool(failures and raw_p95 is None),
            "median_error_s": statistics.median(pool) if pool else None,
            "max_error_s": max(pool) if pool and not failures else None,
            "max_measured_error_s": max(pool) if pool else None,
            **{key: totals[key] for key in (
                "dense_crossings", "non_1s_crossings", "missing_probe_crossings",
                "pause_guarded_offsets", "edge_guarded_offsets", "unmeasurable_offsets")},
            "dense_max_interval_s": TIMING_DENSE_MAX_GAP_S,
            "aggregation": "pooled_absolute_crossing_time_change_all_eight_offsets",
            "failed_offset_rank": "positive_infinity_in_p95_population",
            "median_population": "measured_offsets_only",
            "pause_guard": "every_original_interval_spanning_original_and_thinned_brackets_0_lt_dt_le_1.5s_and_consecutive_source_indices",
            "groups": summaries}


def gate_geometry_metrics(candidates: Sequence[RatifiedCandidate]) -> list[dict[str, Any]]:
    """Scan every gate, including gates without rides; diagnostic, not a new bar.

    Sample the entire arm at <=0.25 m spacing. Flag >1 m of projection excursion
    from its centre anchor; the D13 10 m p95 threshold remains unchanged.
    """
    from shapely.ops import transform

    rows = []
    for candidate in sorted(candidates, key=lambda c: c.decision_id):
        line = candidate.projected_centerline
        for name, source in (("start", candidate.runtime.gate_start),
                             ("finish", candidate.runtime.gate_end)):
            gate = transform(candidate.project_forward.transform, source)
            anchor = float(line.project(gate.interpolate(.5, normalized=True)))
            steps = max(1, math.ceil(gate.length / .25))
            values = [float(line.project(gate.interpolate(i / steps, normalized=True)))
                      for i in range(steps + 1)]
            excursion = max(abs(v - anchor) for v in values)
            rows.append({"decision_id": candidate.decision_id, "display_name": candidate.display_name,
                         "gate": name, "gate_length_m": float(gate.length),
                         "anchor_progress_m": anchor,
                         "arm_progress_min_m": min(values), "arm_progress_max_m": max(values),
                         "max_arm_excursion_m": excursion, "geometry_flag": excursion > 1,
                         "scan_spacing_m": float(gate.length / steps)})
    return rows


def run_scorecard(
    corpus_path: Path,
    canon_path: Path,
    review_labels_path: Path,
    cross_rider_evidence_path: Path,
    corridor_equivalence_path: Path,
    *, legacy_clipped_projection: bool = False,
) -> dict[str, Any]:
    corpus_hash = _verify_hash(corpus_path, EXPECTED_CORPUS_SHA256, "golden corpus")
    canon_hash = _verify_hash(canon_path, EXPECTED_CANON_SHA256, "canon report")
    labels_hash = _verify_hash(
        review_labels_path, EXPECTED_LABELS_SHA256, "canon review labels"
    )
    report = json.loads(canon_path.read_text())
    review_document = json.loads(review_labels_path.read_text())
    cross_rider_hash = sha256_file(cross_rider_evidence_path)
    cross_rider_evidence = load_cross_rider_evidence(cross_rider_evidence_path)
    corridor_equivalence = load_corridor_equivalence(corridor_equivalence_path)
    corridor_equivalence_hash = sha256_file(corridor_equivalence_path)
    runtime_dependencies = verify_runtime_dependencies()
    cross_rider_metric = cross_rider_evidence["same_canon_cross_rider_agreement"]
    selected, registry_audit = resolve_launch_canon_candidates(report, review_document)
    candidates = load_ratified_runtime_candidates(selected)
    connection = _open_corpus_read_only(corpus_path)
    try:
        templates, mapping_taxonomy = map_reference_templates(connection, candidates)
        expected = load_expected_passes(connection, templates)
        comparisons, observed, _raw_taxonomy, errors = replay_reference_slice(
            connection,
            candidates,
            expected,
            corpus_path=corpus_path,
            legacy_clipped_projection=legacy_clipped_projection,
        )
        comparisons, unclassified_reference = apply_disagreement_audit(comparisons)
        audited_reference_gaps: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for comparison in comparisons:
            if comparison.get("classification") != "canon_gap":
                continue
            audited_reference_gaps[int(comparison["_activity_ordinal"])].append(
                {
                    "start_s": float(comparison["_reference_start_s"]),
                    "end_s": float(comparison["_reference_end_s"]),
                    "decision_id": str(comparison["decision_id"]),
                    "reason": str(comparison.get("canon_gap_reason") or ""),
                }
            )
        full_replay = scan_full_corpus(
            connection,
            candidates,
            audited_reference_gaps=audited_reference_gaps,
        )
    finally:
        connection.close()
    boundaries = boundary_repeat_metrics(
        observed,
        candidates,
        source_hashes={
            "corpus_sha256": corpus_hash,
            "canon_report_sha256": canon_hash,
            "review_labels_sha256": labels_hash,
        },
        legacy_clipped_projection=legacy_clipped_projection,
    )
    timing = timing_agreement_metrics(observed, candidates,
                                      source_hashes=boundaries["frozen_input"]["source_sha256"])
    unclassified_disagreements = unclassified_reference + int(
        full_replay["unclassified_disagreements"]
    )
    taxonomy: Counter[str] = Counter(
        str(item["classification"]) for item in comparisons
    )
    traversal_matches = sum(1 for item in comparisons if item["traversal_match"])
    reference_h3_hits = sum(1 for item in comparisons if item["h3_candidate_hit"])
    scorecard = build_cutover_scorecard(
        corpus_integrity_ok=True,
        replay_errors=errors + int(full_replay["errors"]),
        reference_passes=len(expected),
        reference_h3_hits=reference_h3_hits,
        traversal_matches=traversal_matches,
        boundary_eligible_climb_gate_groups=int(
            boundaries["eligible_climb_gate_groups"]
        ),
        boundary_eligible_distinct_rides=int(boundaries["eligible_distinct_rides"]),
        repeat_boundary_endpoints=int(boundaries["repeat_endpoints"]),
        boundary_p95_error_m=boundaries["_p95_error_m_raw"],
        boundary_strict_max_error_m=boundaries["_max_error_m_raw"],
        boundary_candidate_manifest_sha256=boundaries["frozen_input"][
            "candidate_manifest_sha256"
        ],
        boundary_observation_manifest_sha256=boundaries["frozen_input"][
            "observation_manifest_sha256"
        ],
        boundary_input_manifest_sha256=boundaries["frozen_input"][
            "input_manifest_sha256"
        ],
        boundary_metric_ratified=True,
        timing_metrics=timing,
        legacy_clipped_projection=legacy_clipped_projection,
        cross_rider_pairs=int(cross_rider_metric["pairs"]),
        cross_rider_agreements=int(cross_rider_metric["agreements"]),
        cross_rider_supported_candidates=int(
            cross_rider_metric["supported_candidates"]
        ),
        unclassified_disagreements=unclassified_disagreements,
        offline_snapshot_integrity_ok=True,
        unresolved_prior_approvals=len(registry_audit["pending_approve_labels"]),
    )
    scorecard.update(
        {
            "inputs": {
                "corpus_sha256": corpus_hash,
                "canon_report_sha256": canon_hash,
                "review_labels_sha256": labels_hash,
                "cross_rider_evidence_sha256": cross_rider_hash,
                "corridor_equivalence_sha256": corridor_equivalence_hash,
                "runtime_dependencies": runtime_dependencies,
                "corpus_rides": EXPECTED_RIDE_COUNT,
                "launch_candidates_reconstructed": len(candidates),
                "ratified_decision_ids": sorted(candidate.decision_id for candidate in candidates),
                "boundary_candidate_manifest_sha256": boundaries["frozen_input"][
                    "candidate_manifest_sha256"
                ],
                "boundary_observation_manifest_sha256": boundaries["frozen_input"][
                    "observation_manifest_sha256"
                ],
                "boundary_input_manifest_sha256": boundaries["frozen_input"][
                    "input_manifest_sha256"
                ],
            },
            "corridor_equivalence": corridor_equivalence,
            "registry_reconstruction": registry_audit,
            "cross_rider_evidence": cross_rider_evidence,
            "reference": {
                "source": "pre_d11_strava_segment_templates_unique_full_gate_mapping",
                "mapped_templates": len(templates),
                "mapped_candidate_count": len(
                    {template.candidate_fingerprint for template in templates}
                ),
                "mapping_taxonomy": mapping_taxonomy,
                "expected_passes": len(expected),
                "h3_candidate_hits": reference_h3_hits,
                "template_ids": sorted(template.segment_id for template in templates),
                "mappings": [
                    {
                        "segment_id": template.segment_id,
                        "segment_name": template.segment_name,
                        "decision_id": template.decision_id,
                        "corridor_coverage": round(template.corridor_coverage, 6),
                    }
                    for template in sorted(
                        templates,
                        key=lambda item: (item.segment_id, item.decision_id),
                    )
                ],
            },
            "comparison": {
                "detector_mode": "canonical_v2_scientific_offline_no_frequency_or_bridge_inputs",
                "taxonomy": dict(sorted(taxonomy.items())),
                "rows": sorted(
                    [
                        {
                            key: value
                            for key, value in row.items()
                            if not key.startswith("_")
                        }
                        for row in comparisons
                    ],
                    key=lambda row: (
                        row["decision_id"],
                        row["segment_id"],
                        row["classification"],
                        bool(row["detector_match"]),
                        bool(row["traversal_match"]),
                    ),
                ),
            },
            "full_corpus_replay": full_replay,
            "boundary_detail": {
                key: value
                for key, value in boundaries.items()
                if not key.startswith("_")
            },
            "gate_geometry_scan": gate_geometry_metrics(candidates),
            "limitations": [
                "The golden corpus contains one rider; cross-rider agreement comes from a separate privacy-bounded 177-upload replay manifest.",
                "The pinned applied v0.2.5 report and 57 explicitly reviewed current candidates are sufficient authority for offline geometry replay; live runtime-registry readiness is a separate 4crx.11 check.",
                "Only independently unique full-gate template mappings enter recall; unmapped compiler candidates are not labels.",
                "The ratified boundary contract gates pooled p95 along-track repeat-median deviation at 10 m; strict maximum, lateral scatter, and gate-intersection residual remain diagnostics.",
                "D13 projects the crossing itself and measures gate geometry, not physical GPS accuracy. Timing agreement independently gates all eight thinning offsets at pooled p95 <=2 s with recording-pause guards.",
                "The compiler corridor preview is ignored; local AEQD reconstruction is checked against same-manifest PostGIS geography for all 57 launch candidates.",
            ],
        }
    )
    return scorecard


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="Pinned golden corpus SQLite DB")
    parser.add_argument("--canon-report", type=Path, required=True, help="Applied v0.2.5 compiler report")
    parser.add_argument(
        "--review-labels",
        type=Path,
        default=Path(__file__).resolve().parents[2]
        / "backend/tests/fixtures/canon_review_labels_2026-07-05.json",
        help="Pinned Tim review fixture",
    )
    parser.add_argument(
        "--cross-rider-evidence",
        type=Path,
        default=Path(__file__).with_name("canon_cross_rider_evidence_2026-07-21.json"),
        help="Privacy-bounded aggregate from the multi-rider raw-upload replay",
    )
    parser.add_argument(
        "--corridor-equivalence",
        type=Path,
        default=Path(__file__).with_name(
            "canon_corridor_equivalence_2026-07-21.json"
        ),
        help="Pinned PostGIS-versus-local corridor equivalence evidence",
    )
    parser.add_argument("--output", type=Path, help="Write stable privacy-bounded JSON")
    parser.add_argument("--legacy-clipped-projection", action="store_true",
                        help="Historical reproduction only; cannot pass the current boundary cutover bar")
    args = parser.parse_args(argv)
    try:
        scorecard = run_scorecard(
            args.db.resolve(),
            args.canon_report.resolve(),
            args.review_labels.resolve(),
            args.cross_rider_evidence.resolve(),
            args.corridor_equivalence.resolve(),
            legacy_clipped_projection=args.legacy_clipped_projection,
        )
    except (InputIntegrityError, OSError, ValueError, sqlite3.DatabaseError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    encoded = json.dumps(scorecard, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded)
    else:
        print(encoded, end="")
    return 0 if scorecard["overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
