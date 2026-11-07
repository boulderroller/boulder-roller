#!/usr/bin/env python3
"""Trace canonical_v2 detector signal stages for holdout rides.

This is a diagnostic harness, not a detector variant. It records what the
production-style pipeline saw at each stage: stream quality, bridge
preprocessing edits, generated candidates, canonical_v2 cluster scoring,
selected detections, and match outcomes against the golden corpus reference.
"""

from __future__ import annotations

import argparse
import copy
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from audit_bridge_preprocessing import _load_activity_payload
from explain_holdout_activity import detailed_match_records
from holdout_reference_quality import quarantine_repeated_segment_spam
from run_holdout_eval import (
    GOLDEN_DB,
    Detection,
    Segment,
    compute_metrics,
    dedup_segments,
    load_frequency_map,
    streams_to_tile_data,
)

REPO_ROOT = Path(__file__).parent.parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.patterns.climb import (
    ClimbCandidate,
    ClimbPattern,
    CANONICAL_MOMENTUM_TERRAINS,
    RideQualityProfile,
    _build_climb_candidates,
    _candidate_confidence,
    _candidates_corroborate,
    _choose_canonical_v2_climbs,
    _cluster_canonical_v2_candidates,
    _get_workout_parse,
    _attach_weak_raw_persistence_support,
    _partition_raw_persistence_candidates,
    _run_canonical_momentum_sweep,
    _run_rust_detector,
    _score_candidate_with_canonical_context,
    _should_prefer_persistence_override,
    _uses_separate_persistence_candidate_samples,
    classify_terrain,
)
from app.services.patterns.climb_profile import build_ride_climb_profile
from app.services.road_enrichment import preprocess_bridge_elevations

OVERLAP_FOR_CANDIDATE_DIAGNOSIS = 0.25


def _round(value: Any, digits: int = 3) -> Any:
    if value is None:
        return None
    return round(float(value), digits)


def _overlap_ratio(start_a: int, end_a: int, start_b: int, end_b: int) -> float:
    overlap = max(0, min(end_a, end_b) - max(start_a, start_b))
    shorter = min(max(1, end_a - start_a), max(1, end_b - start_b))
    return overlap / shorter


def _climb_record(climb: ClimbPattern) -> dict[str, Any]:
    return {
        "start_s": int(climb.start_time_offset_s),
        "end_s": int(climb.end_time_offset_s),
        "time_s": int(climb.time_s),
        "vert_m": _round(climb.vert_m, 2),
        "grade_pct": _round(climb.avg_gradient_pct, 2),
        "distance_m": _round(climb.distance_m, 1),
        "persistence_m": _round(getattr(climb, "persistence", None), 2),
        "detector_mode": getattr(climb, "detector_mode", None),
    }


def _candidate_record(
    candidate: ClimbCandidate,
    *,
    cluster_index: int | None,
    selected: bool,
    decision: str,
) -> dict[str, Any]:
    return {
        "candidate_key": _candidate_key(candidate),
        "cluster_index": cluster_index,
        "source": candidate.source,
        "family": candidate.family,
        "selected": selected,
        "decision": decision,
        "score": _round(candidate.total_score, 3),
        "threshold": _round(candidate.acceptance_threshold, 3),
        "score_margin": _round(candidate.total_score - candidate.acceptance_threshold, 3),
        "reasons": list(candidate.reasons),
        "corroborating_sources": list(candidate.corroborating_sources),
        "corroborating_families": list(candidate.corroborating_families),
        "weak_raw_persistence_support_count": candidate.weak_raw_persistence_support_count,
        "selectable": candidate.selectable,
        **_climb_record(candidate.climb),
    }


def _candidate_key(candidate: ClimbCandidate) -> str:
    climb = candidate.climb
    return f"{candidate.source}:{climb.start_time_offset_s}-{climb.end_time_offset_s}"


def _detections_from_climbs(climbs: list[ClimbPattern]) -> list[Detection]:
    return [
        Detection(
            start_s=int(climb.start_time_offset_s),
            end_s=int(climb.end_time_offset_s),
            vert_m=float(climb.vert_m),
            grade_pct=float(climb.avg_gradient_pct or 0.0),
            distance_m=float(climb.distance_m or 0.0),
            mode=getattr(climb, "detector_mode", "") or "canonical_v2",
        )
        for climb in climbs
        if climb.vert_m >= 20.0
    ]


def _stream_summary(streams: dict[str, Any], tile_samples: list[dict[str, Any]]) -> dict[str, Any]:
    times = streams.get("time", [])
    intervals = [
        int(times[idx]) - int(times[idx - 1])
        for idx in range(1, len(times))
        if int(times[idx]) >= int(times[idx - 1])
    ]
    interval_counts = Counter(intervals)
    return {
        "raw_points": len(times),
        "tile_samples": len(tile_samples),
        "latlng_points": len(streams.get("latlng", [])),
        "altitude_points": len(streams.get("altitude", [])),
        "power_points": len(streams.get("watts", [])),
        "heartrate_points": len(streams.get("heartrate", [])),
        "median_interval_s": sorted(intervals)[len(intervals) // 2] if intervals else None,
        "max_interval_s": max(intervals) if intervals else None,
        "interval_counts_top": [
            {"seconds": seconds, "count": count}
            for seconds, count in interval_counts.most_common(8)
        ],
    }


def _summarize_elevation_delta(
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
) -> dict[str, Any]:
    changed: list[tuple[int, float]] = []
    for idx, (old, new) in enumerate(zip(before, after)):
        old_elev = old.get("elevation_m")
        new_elev = new.get("elevation_m")
        if old_elev is None or new_elev is None:
            continue
        delta = float(new_elev) - float(old_elev)
        if abs(delta) > 1e-9:
            changed.append((idx, delta))

    ranges: list[dict[str, Any]] = []
    if changed:
        start_idx = prev_idx = changed[0][0]
        deltas = [changed[0][1]]
        for idx, delta in changed[1:]:
            if idx == prev_idx + 1:
                prev_idx = idx
                deltas.append(delta)
                continue
            ranges.append(_delta_range_record(before, start_idx, prev_idx, deltas))
            start_idx = prev_idx = idx
            deltas = [delta]
        ranges.append(_delta_range_record(before, start_idx, prev_idx, deltas))

    return {
        "changed_samples": len(changed),
        "total_abs_delta_m": _round(sum(abs(delta) for _, delta in changed), 3),
        "max_abs_delta_m": _round(max((abs(delta) for _, delta in changed), default=0.0), 3),
        "changed_ranges": ranges,
    }


def _delta_range_record(
    samples: list[dict[str, Any]],
    start_idx: int,
    end_idx: int,
    deltas: list[float],
) -> dict[str, Any]:
    return {
        "start_idx": start_idx,
        "end_idx": end_idx,
        "start_s": samples[start_idx].get("t"),
        "end_s": samples[end_idx].get("t"),
        "samples": end_idx - start_idx + 1,
        "min_delta_m": _round(min(deltas), 3),
        "max_delta_m": _round(max(deltas), 3),
        "max_abs_delta_m": _round(max(abs(delta) for delta in deltas), 3),
    }


def trace_canonical_v2(
    tile_samples: list[dict[str, Any]],
    *,
    frequency_map: dict[str, int] | None,
    persistence_candidate_samples: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[ClimbPattern]]:
    wp = _get_workout_parse()
    if wp is None:
        raise RuntimeError("workout_parse is not available; canonical_v2 tracing requires Rust detector bindings")

    ride_quality = RideQualityProfile.from_tile_samples(tile_samples)
    terrain_info = classify_terrain(tile_samples) or {}
    ride_total_gain_m = terrain_info.get("metrics", {}).get("total_gain_m")
    ride_profile = build_ride_climb_profile(
        tile_samples,
        terrain_class=terrain_info.get("class"),
        terrain_confidence=terrain_info.get("confidence"),
    )
    power_samples = [
        sample.get("power_w")
        for sample in tile_samples
        if sample.get("power_w") is not None and sample.get("power_w") > 0
    ]
    ride_avg_power_w = sum(power_samples) / len(power_samples) if power_samples else None

    persistence_samples = (
        persistence_candidate_samples
        if persistence_candidate_samples is not None
        else tile_samples
    )
    momentum_results, best_terrain, momentum_selected = _run_canonical_momentum_sweep(
        wp,
        tile_samples=tile_samples,
        config_overrides=None,
        arena_tiles=None,
        user_weight_kg=75.0,
        generate_signatures=False,
    )
    persistence_climbs = _run_rust_detector(
        wp,
        tile_samples=tile_samples,
        persistence_candidate_samples=persistence_samples,
        terrain="auto",
        config_overrides=None,
        arena_tiles=None,
        user_weight_kg=75.0,
        algorithm="persistence",
        generate_signatures=False,
    )
    persistence_confirmation_climbs: list[ClimbPattern] | None = None
    if _uses_separate_persistence_candidate_samples(
        tile_samples,
        persistence_candidate_samples,
    ):
        persistence_confirmation_climbs = _run_rust_detector(
            wp,
            tile_samples=tile_samples,
            persistence_candidate_samples=None,
            terrain="auto",
            config_overrides=None,
            arena_tiles=None,
            user_weight_kg=75.0,
            algorithm="persistence",
            generate_signatures=False,
        )

    all_candidates: list[ClimbCandidate] = []
    for terrain_name in CANONICAL_MOMENTUM_TERRAINS:
        all_candidates.extend(
            _build_climb_candidates(
                momentum_results.get(terrain_name, []),
                source=f"momentum:{terrain_name}",
                ride_quality=ride_quality,
                terrain_class=terrain_info.get("class"),
                ride_total_gain_m=ride_total_gain_m,
                ride_avg_power_w=ride_avg_power_w,
                tile_samples=tile_samples,
                frequency_map=frequency_map,
            )
        )
    persistence_candidates = _build_climb_candidates(
        persistence_climbs,
        source="persistence",
        ride_quality=ride_quality,
        terrain_class=terrain_info.get("class"),
        ride_total_gain_m=ride_total_gain_m,
        ride_avg_power_w=ride_avg_power_w,
        tile_samples=tile_samples,
        frequency_map=frequency_map,
    )
    weak_persistence_support_candidates: list[ClimbCandidate] = []
    if persistence_confirmation_climbs is not None:
        persistence_candidates, weak_persistence_support_candidates = (
            _partition_raw_persistence_candidates(
                persistence_candidates,
                persistence_confirmation_climbs=persistence_confirmation_climbs,
                ride_profile=ride_profile,
            )
        )
        _attach_weak_raw_persistence_support(
            all_candidates,
            weak_persistence_support_candidates,
        )
    all_candidates.extend(persistence_candidates)

    clusters = _cluster_canonical_v2_candidates(all_candidates)
    selected: list[ClimbPattern] = []
    used_persistence_ids: set[int] = set()
    candidate_records: list[dict[str, Any]] = []
    cluster_records: list[dict[str, Any]] = []

    for cluster_index, cluster in enumerate(clusters):
        cluster_sources = {candidate.source for candidate in cluster}
        cluster_families = {candidate.family for candidate in cluster}
        best_candidate: ClimbCandidate | None = None
        for candidate in cluster:
            candidate.corroborating_sources = sorted(cluster_sources - {candidate.source})
            candidate.corroborating_families = sorted(cluster_families - {candidate.family})
            _score_candidate_with_canonical_context(
                candidate,
                ride_profile=ride_profile,
                persistence_confirmation_climbs=persistence_confirmation_climbs,
            )
            if not candidate.selectable:
                continue
            if best_candidate is None or candidate.total_score > best_candidate.total_score:
                best_candidate = candidate

        if best_candidate is None:
            continue

        raw_best_key = _candidate_key(best_candidate)
        for candidate in cluster:
            if (
                candidate.selectable
                and candidate.family == "persistence"
                and candidate.total_score >= candidate.acceptance_threshold
                and best_candidate.family == "momentum"
            ):
                if _should_prefer_persistence_override(best_candidate, candidate):
                    best_candidate = candidate

        override_best_key = _candidate_key(best_candidate)
        acceptable_candidates = [
            candidate
            for candidate in cluster
            if candidate.selectable
            and candidate.total_score >= candidate.acceptance_threshold
        ]
        fallback_used = False
        if best_candidate.total_score < best_candidate.acceptance_threshold and acceptable_candidates:
            best_candidate = max(acceptable_candidates, key=lambda candidate: candidate.total_score)
            fallback_used = True

        for candidate in cluster:
            if candidate.selectable and candidate.family == "persistence":
                used_persistence_ids.add(id(candidate))

        accepted = best_candidate.total_score >= best_candidate.acceptance_threshold
        selected_key = _candidate_key(best_candidate) if accepted else None
        if not accepted:
            for candidate in cluster:
                if candidate.selectable and candidate.family == "persistence":
                    used_persistence_ids.discard(id(candidate))

        for candidate in cluster:
            is_selected = accepted and _candidate_key(candidate) == selected_key
            decision = "selected" if is_selected else "rejected"
            if not candidate.selectable:
                decision = "support_only"
            elif not is_selected and candidate.total_score >= candidate.acceptance_threshold:
                decision = "acceptable_not_selected"
            candidate_records.append(
                _candidate_record(
                    candidate,
                    cluster_index=cluster_index,
                    selected=is_selected,
                    decision=decision,
                )
            )

        if accepted:
            chosen = best_candidate.climb
            chosen.detector_mode = f"canonical_v2:{best_candidate.source}"
            chosen.proposal_sources = sorted(cluster_sources)
            chosen.confidence = _candidate_confidence(best_candidate)
            chosen.confidence_reasons = sorted(set(best_candidate.reasons))
            selected.append(chosen)

        cluster_records.append({
            "cluster_index": cluster_index,
            "sources": sorted(cluster_sources),
            "families": sorted(cluster_families),
            "raw_best_key": raw_best_key,
            "override_best_key": override_best_key,
            "selected_key": selected_key,
            "fallback_to_acceptable_candidate": fallback_used,
            "accepted": accepted,
            "candidate_count": len(cluster),
        })

    rescue_records: list[dict[str, Any]] = []
    for candidate in persistence_candidates:
        if id(candidate) in used_persistence_ids:
            continue
        if any(_candidates_corroborate(candidate.climb, selected_climb) for selected_climb in selected):
            continue
        corroborating_terrains = sorted(
            terrain_name
            for terrain_name, climbs in momentum_results.items()
            if any(_candidates_corroborate(candidate.climb, climb) for climb in climbs)
        )
        if len(corroborating_terrains) < 1:
            candidate.corroborating_sources = []
            candidate.corroborating_families = []
            _score_candidate_with_canonical_context(
                candidate,
                ride_profile=ride_profile,
                persistence_confirmation_climbs=persistence_confirmation_climbs,
            )
            rescue_records.append(_candidate_record(
                candidate,
                cluster_index=None,
                selected=False,
                decision="rescue_rejected_no_momentum_support",
            ))
            continue

        candidate.corroborating_sources = [f"momentum:{terrain}" for terrain in corroborating_terrains]
        candidate.corroborating_families = ["momentum"]
        _score_candidate_with_canonical_context(
            candidate,
            ride_profile=ride_profile,
            persistence_confirmation_climbs=persistence_confirmation_climbs,
        )
        accepted = candidate.total_score >= candidate.acceptance_threshold + 0.5
        if accepted:
            chosen = candidate.climb
            chosen.detector_mode = "canonical_v2:persistence"
            chosen.proposal_sources = sorted(["persistence", *candidate.corroborating_sources])
            chosen.confidence = _candidate_confidence(candidate)
            chosen.confidence_reasons = sorted(set(candidate.reasons))
            selected.append(chosen)
        rescue_records.append(_candidate_record(
            candidate,
            cluster_index=None,
            selected=accepted,
            decision="rescue_selected" if accepted else "rescue_rejected_below_threshold",
        ))

    production_selected = _choose_canonical_v2_climbs(
        ride_quality=ride_quality,
        ride_profile=ride_profile,
        momentum_results=momentum_results,
        persistence_climbs=persistence_climbs,
        terrain_class=terrain_info.get("class"),
        ride_total_gain_m=ride_total_gain_m,
        ride_avg_power_w=ride_avg_power_w,
        tile_samples=tile_samples,
        frequency_map=frequency_map,
        persistence_confirmation_climbs=persistence_confirmation_climbs,
    )

    selected = sorted(selected, key=lambda climb: climb.start_time_offset_s)
    production_keys = [_climb_record(climb) for climb in production_selected]
    traced_keys = [_climb_record(climb) for climb in selected]

    trace = {
        "ride_quality": ride_quality.to_dict(),
        "terrain": terrain_info,
        "ride_avg_power_w": _round(ride_avg_power_w, 1),
        "candidate_views": {
            "confirmation_samples": len(tile_samples),
            "persistence_candidate_samples": len(persistence_samples),
            "persistence_candidate_view": (
                "separate_pre_bridge"
                if persistence_samples is not tile_samples
                else "confirmation"
            ),
            "persistence_confirmation_count": (
                len(persistence_confirmation_climbs)
                if persistence_confirmation_climbs is not None
                else None
            ),
            "weak_raw_persistence_support_count": len(
                weak_persistence_support_candidates
            ),
            "weak_raw_persistence_support": [
                _candidate_record(
                    candidate,
                    cluster_index=None,
                    selected=False,
                    decision="support_only_raw",
                )
                for candidate in weak_persistence_support_candidates
            ],
        },
        "momentum_best_terrain": best_terrain,
        "momentum_selected_count": len(momentum_selected),
        "candidate_counts": {
            **{f"momentum:{terrain}": len(momentum_results.get(terrain, [])) for terrain in CANONICAL_MOMENTUM_TERRAINS},
            "persistence": len(persistence_climbs),
            "clusters": len(clusters),
        },
        "clusters": cluster_records,
        "candidates": candidate_records + rescue_records,
        "selected": traced_keys,
        "matches_production_selection": traced_keys == production_keys,
    }
    return trace, selected


def diagnose_match_records(
    match_records: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for record in match_records:
        if record["result_type"] == "missed":
            overlapping = [
                {
                    **candidate,
                    "overlap_ratio": _round(_overlap_ratio(
                        int(record["seg_start_s"]),
                        int(record["seg_end_s"]),
                        int(candidate["start_s"]),
                        int(candidate["end_s"]),
                    ), 3),
                }
                for candidate in candidates
                if _overlap_ratio(
                    int(record["seg_start_s"]),
                    int(record["seg_end_s"]),
                    int(candidate["start_s"]),
                    int(candidate["end_s"]),
                ) >= OVERLAP_FOR_CANDIDATE_DIAGNOSIS
            ]
            overlapping.sort(
                key=lambda candidate: (
                    candidate["selected"],
                    candidate["overlap_ratio"],
                    candidate.get("score_margin") or -999,
                ),
                reverse=True,
            )
            if not overlapping:
                diagnosis = "no_candidate_generated"
            elif any(candidate["selected"] for candidate in overlapping):
                diagnosis = "boundary_overlap_below_match_threshold"
            elif overlapping[0].get("score_margin", -999) < 0:
                diagnosis = "candidate_generated_rejected"
            elif overlapping[0]["decision"] == "acceptable_not_selected":
                diagnosis = "candidate_acceptable_not_selected"
            else:
                diagnosis = "candidate_generated_unselected"

            diagnostics.append({
                "result_type": "missed",
                "segment_id": record.get("segment_id"),
                "segment_name": record.get("segment_name"),
                "seg_start_s": record.get("seg_start_s"),
                "seg_end_s": record.get("seg_end_s"),
                "diagnosis": diagnosis,
                "best_candidates": overlapping[:5],
            })
        elif record["result_type"] == "extra":
            diagnostics.append({
                "result_type": "extra",
                "det_start_s": record.get("det_start_s"),
                "det_end_s": record.get("det_end_s"),
                "det_mode": record.get("det_mode"),
                "diagnosis": "selected_extra",
            })
    return diagnostics


def _score_match_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    matched = sum(1 for row in records if row["result_type"] == "matched")
    missed = sum(1 for row in records if row["result_type"] == "missed")
    extras = sum(1 for row in records if row["result_type"] == "extra")
    precision, recall, f1 = compute_metrics(matched, missed, extras)
    return {
        "matched": matched,
        "missed": missed,
        "extras": extras,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def _trace_mode(
    tile_samples: list[dict[str, Any]],
    segments: list[Segment],
    time_array: list[int],
    frequency_map: dict[str, int] | None,
    *,
    bridge_enabled: bool,
    preserve_pre_bridge_persistence: bool,
) -> dict[str, Any]:
    before = copy.deepcopy(tile_samples)
    samples = copy.deepcopy(tile_samples)
    bridge_records: list[dict[str, Any]] = []
    if bridge_enabled:
        preprocess_bridge_elevations(samples, diagnostics=bridge_records)

    persistence_samples = before if preserve_pre_bridge_persistence and bridge_enabled else samples
    trace, selected_climbs = trace_canonical_v2(
        samples,
        frequency_map=frequency_map,
        persistence_candidate_samples=persistence_samples,
    )
    detections = _detections_from_climbs(selected_climbs)
    records = detailed_match_records(copy.deepcopy(segments), detections, time_array)
    trace["match_summary"] = _score_match_records(records)
    trace["match_records"] = records
    trace["diagnostics"] = diagnose_match_records(records, trace["candidates"])
    trace["bridge_preprocessing"] = {
        "enabled": bridge_enabled,
        "records": bridge_records,
        "elevation_delta": _summarize_elevation_delta(before, samples),
    }
    return trace


def trace_activity(
    conn: sqlite3.Connection,
    activity_id: str,
    frequency_map: dict[str, int] | None,
    *,
    bridge_mode: str,
    preserve_pre_bridge_persistence: bool,
) -> dict[str, Any]:
    raw_segments, streams = _load_activity_payload(conn, activity_id)
    raw_segments = dedup_segments(raw_segments)
    segments, quarantined_groups = quarantine_repeated_segment_spam(raw_segments)
    time_array = streams.get("time", [])
    tile_samples, _tile_runs = streams_to_tile_data(streams)
    if not tile_samples:
        raise ValueError(f"activity {activity_id} produced no tile samples")

    modes: dict[str, Any] = {}
    if bridge_mode in {"off", "both"}:
        modes["bridge_off"] = _trace_mode(
            tile_samples,
            segments,
            time_array,
            frequency_map,
            bridge_enabled=False,
            preserve_pre_bridge_persistence=preserve_pre_bridge_persistence,
        )
    if bridge_mode in {"on", "both"}:
        modes["bridge_on"] = _trace_mode(
            tile_samples,
            segments,
            time_array,
            frequency_map,
            bridge_enabled=True,
            preserve_pre_bridge_persistence=preserve_pre_bridge_persistence,
        )

    return {
        "activity_id": str(activity_id),
        "segments": len(segments),
        "raw_segments": len(raw_segments),
        "quarantined_reference_segments": sum(group.count for group in quarantined_groups),
        "stream_summary": _stream_summary(streams, tile_samples),
        "modes": modes,
    }


def _print_activity_summary(activity: dict[str, Any]) -> None:
    print(
        f"{activity['activity_id']}: segments={activity['segments']} "
        f"raw={activity['raw_segments']} tile_samples={activity['stream_summary']['tile_samples']}"
    )
    for mode_name, mode in activity["modes"].items():
        summary = mode["match_summary"]
        counts = mode["candidate_counts"]
        diag_counts = Counter(row["diagnosis"] for row in mode["diagnostics"])
        print(
            f"  {mode_name}: m={summary['matched']} miss={summary['missed']} "
            f"x={summary['extras']} F1={summary['f1']:.4f} "
            f"candidates={sum(count for key, count in counts.items() if key != 'clusters')} "
            f"clusters={counts['clusters']} diagnostics={dict(sorted(diag_counts.items()))}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("activity_id", nargs="+", help="Strava activity ID(s) in golden_corpus.db")
    parser.add_argument("--db", default=str(GOLDEN_DB), help="Golden corpus DB path")
    parser.add_argument(
        "--bridge-mode",
        choices=["off", "on", "both"],
        default="both",
        help="Trace bridge preprocessing disabled, enabled, or both",
    )
    parser.add_argument("--output", type=Path, help="Write JSON trace artifact")
    parser.add_argument("--quiet", action="store_true", help="Only write JSON output")
    parser.add_argument(
        "--preserve-pre-bridge-persistence",
        action="store_true",
        help=(
            "Experimental: generate persistence candidates from the pre-bridge "
            "view while scoring on bridge-processed samples"
        ),
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: database not found: {db_path}", file=sys.stderr)
        return 2

    try:
        conn = sqlite3.connect(str(db_path))
        frequency_map = load_frequency_map(db_path)
        activities = [
            trace_activity(
                conn,
                str(activity_id),
                frequency_map,
                bridge_mode=args.bridge_mode,
                preserve_pre_bridge_persistence=args.preserve_pre_bridge_persistence,
            )
            for activity_id in args.activity_id
        ]
    except (RuntimeError, sqlite3.Error, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        if "conn" in locals():
            conn.close()

    artifact = {
        "config": {
            "activity_ids": [str(activity_id) for activity_id in args.activity_id],
            "bridge_mode": args.bridge_mode,
            "frequency_map_tiles": len(frequency_map) if frequency_map else 0,
            "preserve_pre_bridge_persistence": args.preserve_pre_bridge_persistence,
        },
        "activities": activities,
    }
    if args.output:
        args.output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    if not args.quiet:
        for activity in activities:
            _print_activity_summary(activity)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
