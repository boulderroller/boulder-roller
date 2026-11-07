#!/usr/bin/env python3
"""Mine mixed_boundary_drift traces for boundary-selector evidence.

This is an evidence harness only. It reuses canonical_v2 trace output and looks
for cases where an accepted-but-unselected candidate could replace a selected
extra detection while matching a missed reference segment.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

SCRIPT_DIR = Path(__file__).parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from run_holdout_eval import GOLDEN_DB, OVERLAP_THRESHOLD, load_frequency_map
from trace_detector_pipeline import trace_activity

SAFE_DECISIONS = {"acceptable_not_selected"}
EXTRA_DETECTION_OVERLAP = 0.90


def _round(value: Any, digits: int = 3) -> Any:
    if value is None:
        return None
    return round(float(value), digits)


def _overlap_ratio(start_a: int, end_a: int, start_b: int, end_b: int) -> float:
    overlap = max(0, min(end_a, end_b) - max(start_a, start_b))
    shorter = min(max(1, end_a - start_a), max(1, end_b - start_b))
    return overlap / shorter


def _activity_sort_key(row: dict[str, Any], sort_mode: str) -> tuple[Any, ...]:
    if sort_mode == "impact":
        return (
            -int(row.get("missed", 0) or 0),
            -int(row.get("extras", 0) or 0),
            -int(row.get("segments", 0) or 0),
            str(row.get("activity_id")),
        )
    return (str(row.get("activity_id")),)


def load_mixed_boundary_rows(
    holdout_json: Path,
    *,
    limit: int,
    sort_mode: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data = json.loads(holdout_json.read_text())
    rows = [
        row
        for row in data.get("deployment_per_ride", [])
        if row.get("classification") == "mixed_boundary_drift"
    ]
    rows.sort(key=lambda row: _activity_sort_key(row, sort_mode))
    if limit > 0:
        rows = rows[:limit]
    return data, rows


def _compact_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_key": candidate.get("candidate_key"),
        "cluster_index": candidate.get("cluster_index"),
        "source": candidate.get("source"),
        "family": candidate.get("family"),
        "decision": candidate.get("decision"),
        "score": candidate.get("score"),
        "threshold": candidate.get("threshold"),
        "score_margin": candidate.get("score_margin"),
        "start_s": candidate.get("start_s"),
        "end_s": candidate.get("end_s"),
        "vert_m": candidate.get("vert_m"),
        "grade_pct": candidate.get("grade_pct"),
        "distance_m": candidate.get("distance_m"),
        "reasons": list(candidate.get("reasons") or [])[:8],
        "corroborating_sources": list(candidate.get("corroborating_sources") or []),
    }


def _extra_for_selected_candidate(
    selected: dict[str, Any],
    extras: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, float]:
    best_extra: dict[str, Any] | None = None
    best_overlap = 0.0
    for extra in extras:
        overlap = _overlap_ratio(
            int(selected["start_s"]),
            int(selected["end_s"]),
            int(extra["det_start_s"]),
            int(extra["det_end_s"]),
        )
        if overlap > best_overlap:
            best_overlap = overlap
            best_extra = extra
    if best_overlap < EXTRA_DETECTION_OVERLAP:
        return None, best_overlap
    return best_extra, best_overlap


def _candidate_matches_segment(
    candidate: dict[str, Any],
    segment: dict[str, Any],
) -> float:
    return _overlap_ratio(
        int(candidate["start_s"]),
        int(candidate["end_s"]),
        int(segment["seg_start_s"]),
        int(segment["seg_end_s"]),
    )


def _candidate_pair_overlap(
    left: dict[str, Any],
    right: dict[str, Any],
) -> float:
    return _overlap_ratio(
        int(left["start_s"]),
        int(left["end_s"]),
        int(right["start_s"]),
        int(right["end_s"]),
    )


def _is_runtime_safe_alternative(candidate: dict[str, Any]) -> bool:
    return (
        not candidate.get("selected")
        and candidate.get("selectable") is True
        and candidate.get("decision") in SAFE_DECISIONS
        and float(candidate.get("score_margin") or -999.0) >= 0.0
    )


def mine_mode(
    activity_row: dict[str, Any],
    mode_name: str,
    mode: dict[str, Any],
) -> dict[str, Any]:
    candidates = list(mode.get("candidates") or [])
    selected_candidates = [candidate for candidate in candidates if candidate.get("selected")]
    missed_records = [
        record for record in mode.get("match_records", []) if record.get("result_type") == "missed"
    ]
    extra_records = [
        record for record in mode.get("match_records", []) if record.get("result_type") == "extra"
    ]

    opportunities: list[dict[str, Any]] = []
    near_counts: Counter[str] = Counter()
    for missed in missed_records:
        safe_alternatives = [
            candidate
            for candidate in candidates
            if _is_runtime_safe_alternative(candidate)
            and _candidate_matches_segment(candidate, missed) >= OVERLAP_THRESHOLD
        ]
        safe_alternatives.sort(
            key=lambda candidate: (
                _candidate_matches_segment(candidate, missed),
                float(candidate.get("score_margin") or -999.0),
            ),
            reverse=True,
        )

        if not safe_alternatives:
            near_counts["missed_without_safe_alternative"] += 1
            continue

        found_replacement = False
        for alternative in safe_alternatives:
            same_cluster = [
                candidate
                for candidate in selected_candidates
                if alternative.get("cluster_index") is not None
                and candidate.get("cluster_index") == alternative.get("cluster_index")
            ]
            overlapping_selected = [
                candidate
                for candidate in selected_candidates
                if candidate not in same_cluster
                and _candidate_pair_overlap(candidate, alternative) >= OVERLAP_THRESHOLD
            ]
            paired_selected = [
                candidate
                for candidate in [*same_cluster, *overlapping_selected]
                if _candidate_pair_overlap(candidate, alternative) >= OVERLAP_THRESHOLD
            ]

            for selected in paired_selected:
                pair_overlap = _candidate_pair_overlap(alternative, selected)
                selected_extra, selected_extra_overlap = _extra_for_selected_candidate(
                    selected,
                    extra_records,
                )
                if selected_extra is None:
                    near_counts["safe_alternative_would_trade_existing_match"] += 1
                    continue

                selected_segment_overlap = _candidate_matches_segment(selected, missed)
                if selected_segment_overlap >= OVERLAP_THRESHOLD:
                    near_counts["selected_extra_already_segment_overlap"] += 1
                    continue

                opportunity = {
                    "activity_id": str(activity_row.get("activity_id")),
                    "activity_name": activity_row.get("name"),
                    "mode": mode_name,
                    "segment": {
                        "segment_id": missed.get("segment_id"),
                        "segment_name": missed.get("segment_name"),
                        "seg_start_s": missed.get("seg_start_s"),
                        "seg_end_s": missed.get("seg_end_s"),
                        "seg_elev_diff": missed.get("seg_elev_diff"),
                        "seg_avg_grade": missed.get("seg_avg_grade"),
                        "seg_distance_m": missed.get("seg_distance_m"),
                    },
                    "alternative_candidate": _compact_candidate(alternative),
                    "selected_extra_candidate": _compact_candidate(selected),
                    "selected_extra_detection": {
                        "det_start_s": selected_extra.get("det_start_s"),
                        "det_end_s": selected_extra.get("det_end_s"),
                        "det_vert_m": selected_extra.get("det_vert_m"),
                        "det_grade_pct": selected_extra.get("det_grade_pct"),
                        "det_distance_m": selected_extra.get("det_distance_m"),
                        "det_mode": selected_extra.get("det_mode"),
                    },
                    "overlaps": {
                        "alternative_to_segment": _round(_candidate_matches_segment(alternative, missed)),
                        "selected_to_segment": _round(selected_segment_overlap),
                        "alternative_to_selected": _round(pair_overlap),
                        "selected_to_extra_detection": _round(selected_extra_overlap),
                    },
                    "expected_local_delta": {
                        "matched": 1,
                        "missed": -1,
                        "extras": -1,
                    },
                }
                opportunities.append(opportunity)
                found_replacement = True
                break
            if found_replacement:
                break

        if not found_replacement:
            near_counts["safe_alternative_without_extra_replacement"] += 1

    diagnosis_counts = Counter(
        row.get("diagnosis")
        for row in mode.get("diagnostics", [])
        if row.get("result_type") == "missed"
    )
    candidate_decisions = Counter(candidate.get("decision") for candidate in candidates)
    return {
        "summary": dict(mode.get("match_summary") or {}),
        "candidate_decisions": dict(sorted(candidate_decisions.items())),
        "missed_diagnoses": dict(sorted(diagnosis_counts.items())),
        "near_counts": dict(sorted(near_counts.items())),
        "opportunities": opportunities,
    }


def mine_activity(
    conn: sqlite3.Connection,
    frequency_map: dict[str, int] | None,
    activity_row: dict[str, Any],
    *,
    bridge_mode: str,
    preserve_pre_bridge_persistence: bool,
) -> dict[str, Any]:
    trace = trace_activity(
        conn,
        str(activity_row["activity_id"]),
        frequency_map,
        bridge_mode=bridge_mode,
        preserve_pre_bridge_persistence=preserve_pre_bridge_persistence,
    )
    modes = {
        mode_name: mine_mode(activity_row, mode_name, mode)
        for mode_name, mode in trace.get("modes", {}).items()
    }
    return {
        "activity_id": str(activity_row.get("activity_id")),
        "activity_name": activity_row.get("name"),
        "holdout_row": {
            "segments": activity_row.get("segments"),
            "detections": activity_row.get("detections"),
            "matched": activity_row.get("matched"),
            "missed": activity_row.get("missed"),
            "extras": activity_row.get("extras"),
            "f1": activity_row.get("f1"),
            "classification": activity_row.get("classification"),
        },
        "trace_summary": {
            "segments": trace.get("segments"),
            "raw_segments": trace.get("raw_segments"),
            "quarantined_reference_segments": trace.get("quarantined_reference_segments"),
            "stream_summary": trace.get("stream_summary"),
        },
        "modes": modes,
    }


def _aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    all_opportunities = [
        opportunity
        for result in results
        for mode in result.get("modes", {}).values()
        for opportunity in mode.get("opportunities", [])
    ]
    activity_ids_with_opportunities = sorted(
        {str(opportunity["activity_id"]) for opportunity in all_opportunities}
    )
    missed_diagnoses: Counter[str] = Counter()
    near_counts: Counter[str] = Counter()
    for result in results:
        for mode in result.get("modes", {}).values():
            missed_diagnoses.update(mode.get("missed_diagnoses") or {})
            near_counts.update(mode.get("near_counts") or {})
    return {
        "activities_traced": len(results),
        "runtime_safe_opportunities": len(all_opportunities),
        "activities_with_opportunities": activity_ids_with_opportunities,
        "missed_diagnoses": dict(sorted(missed_diagnoses.items())),
        "near_counts": dict(sorted(near_counts.items())),
    }


def _holdout_summary(holdout_data: dict[str, Any]) -> dict[str, Any]:
    deployment = holdout_data.get("deployment") or {}
    if deployment:
        return {
            "rides_scored": deployment.get("rides_scored"),
            "matched": deployment.get("total_matched"),
            "missed": deployment.get("total_missed"),
            "extras": deployment.get("total_extras"),
            "precision": deployment.get("precision"),
            "recall": deployment.get("recall"),
            "f1": deployment.get("f1"),
            "taxonomy": deployment.get("taxonomy"),
        }

    rows = holdout_data.get("deployment_per_ride") or []
    taxonomy = Counter(row.get("classification") for row in rows)
    matched = sum(int(row.get("matched", 0) or 0) for row in rows)
    missed = sum(int(row.get("missed", 0) or 0) for row in rows)
    extras = sum(int(row.get("extras", 0) or 0) for row in rows)
    return {
        "rides_scored": len(rows),
        "matched": matched,
        "missed": missed,
        "extras": extras,
        "taxonomy": dict(sorted(taxonomy.items())),
    }


def _markdown_table_row(opportunity: dict[str, Any]) -> str:
    alt = opportunity["alternative_candidate"]
    selected = opportunity["selected_extra_candidate"]
    segment = opportunity["segment"]
    overlaps = opportunity["overlaps"]
    return (
        f"| {opportunity['activity_id']} | {segment['segment_id']} "
        f"{segment['segment_name']} | {segment['seg_start_s']}-{segment['seg_end_s']} | "
        f"{selected['source']} {selected['start_s']}-{selected['end_s']} "
        f"score {selected['score']} | {alt['source']} {alt['start_s']}-{alt['end_s']} "
        f"score {alt['score']} | {overlaps['selected_to_segment']} -> "
        f"{overlaps['alternative_to_segment']} | {overlaps['alternative_to_selected']} |"
    )


def write_markdown_report(report: dict[str, Any], markdown_output: Path) -> None:
    aggregate = report["aggregate"]
    holdout = report["holdout_summary"]
    opportunities = [
        opportunity
        for result in report["activities"]
        for mode in result.get("modes", {}).values()
        for opportunity in mode.get("opportunities", [])
    ]
    ready = aggregate["runtime_safe_opportunities"] >= 3
    lines = [
        "# Boundary-Drift Trace Mining for qkjm",
        "",
        "Scope: evidence gathering only. This does not tune canonical_v2 and does not start interval-DP.",
        "",
        "## Commands",
        "",
        "```bash",
        report["reproduction_command"],
        "```",
        "",
        "## Holdout Baseline",
        "",
        f"- Rides scored: {holdout.get('rides_scored')}",
        f"- Matched / missed / extras: {holdout.get('matched')} / {holdout.get('missed')} / {holdout.get('extras')}",
        f"- Precision / recall / F1: {holdout.get('precision')} / {holdout.get('recall')} / {holdout.get('f1')}",
        f"- Taxonomy: `{json.dumps(holdout.get('taxonomy'), sort_keys=True)}`",
        "",
        "## Trace Mining Result",
        "",
        f"- Mixed boundary-drift rides selected for tracing: {report['config']['mixed_boundary_rows_selected']}",
        f"- Activities successfully traced: {aggregate['activities_traced']}",
        f"- Runtime-safe replacement opportunities found: {aggregate['runtime_safe_opportunities']}",
        f"- Activities with opportunities: {', '.join(aggregate['activities_with_opportunities']) or 'none'}",
        f"- Missed-segment diagnoses: `{json.dumps(aggregate['missed_diagnoses'], sort_keys=True)}`",
        f"- Non-opportunity counts: `{json.dumps(aggregate['near_counts'], sort_keys=True)}`",
        "",
        "A runtime-safe opportunity here means an `acceptable_not_selected` candidate meets the normal "
        f"{OVERLAP_THRESHOLD:.2f} reference-overlap threshold for a missed segment and can replace a "
        "selected extra detection in the same or overlapping candidate cluster.",
        "",
        "## Concrete Pairs",
        "",
    ]
    if opportunities:
        lines.extend([
            "| Activity | Segment | Reference window | Selected extra | Alternative candidate | Segment overlap | Pair overlap |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ])
        lines.extend(_markdown_table_row(opportunity) for opportunity in opportunities[:20])
        if len(opportunities) > 20:
            lines.append(f"| ... | ... | ... | ... | ... | ... | {len(opportunities) - 20} more in JSON |")
    else:
        lines.append("No runtime-safe replacement pairs were found in this mining run.")

    lines.extend([
        "",
        "## Recommendation",
        "",
    ])
    if ready:
        lines.extend([
            "qkjm has enough concrete traces to close as evidence-gathering complete.",
            "",
            "Recommendation for `boulderroller-v2-5i5p.1`: start it as a constrained selector experiment. "
            "The first implementation should only consider replacement choices inside an existing selected "
            "cluster and must keep the invariant: no ride-only climb candidate means no known-climb reward.",
        ])
    else:
        lines.extend([
            "qkjm should remain open. This run did not find enough replacement pairs to justify starting "
            "`boulderroller-v2-5i5p.1` yet.",
            "",
            "Recommendation: mine more mixed rides or broaden the diagnostic definition before selector work.",
        ])

    lines.append("")
    markdown_output.write_text("\n".join(lines))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(GOLDEN_DB), help="Golden corpus DB path")
    parser.add_argument(
        "--holdout-json",
        required=True,
        type=Path,
        help="JSON output from run_holdout_eval.py --mode deployment",
    )
    parser.add_argument("--output", type=Path, required=True, help="Write JSON mining artifact")
    parser.add_argument("--markdown-output", type=Path, help="Write concise Markdown evidence report")
    parser.add_argument(
        "--bridge-mode",
        choices=["on", "off", "both"],
        default="on",
        help="Trace mode to inspect; deployment evidence should use bridge on",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit mixed_boundary_drift rides traced; 0 means all",
    )
    parser.add_argument(
        "--sort",
        choices=["activity", "impact"],
        default="impact",
        help="Order mixed rides before applying --limit",
    )
    parser.add_argument(
        "--preserve-pre-bridge-persistence",
        action="store_true",
        help="Pass through trace_detector_pipeline experimental mode",
    )
    parser.add_argument(
        "--verbose-logs",
        action="store_true",
        help="Keep bridge/HTTP INFO logs visible",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.verbose_logs:
        logging.getLogger().setLevel(logging.WARNING)
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: database not found: {db_path}", file=sys.stderr)
        return 2
    if not args.holdout_json.exists():
        print(f"ERROR: holdout JSON not found: {args.holdout_json}", file=sys.stderr)
        return 2

    holdout_data, activity_rows = load_mixed_boundary_rows(
        args.holdout_json,
        limit=args.limit,
        sort_mode=args.sort,
    )

    conn = sqlite3.connect(str(db_path))
    try:
        frequency_map = load_frequency_map(db_path)
        results = [
            mine_activity(
                conn,
                frequency_map,
                row,
                bridge_mode=args.bridge_mode,
                preserve_pre_bridge_persistence=args.preserve_pre_bridge_persistence,
            )
            for row in activity_rows
        ]
    finally:
        conn.close()

    report = {
        "config": {
            "db": str(db_path),
            "holdout_json": str(args.holdout_json),
            "bridge_mode": args.bridge_mode,
            "limit": args.limit,
            "sort": args.sort,
            "preserve_pre_bridge_persistence": args.preserve_pre_bridge_persistence,
            "mixed_boundary_rows_available": sum(
                1
                for row in holdout_data.get("deployment_per_ride", [])
                if row.get("classification") == "mixed_boundary_drift"
            ),
            "mixed_boundary_rows_selected": len(activity_rows),
            "frequency_map_tiles": len(frequency_map) if frequency_map else 0,
        },
        "holdout_summary": _holdout_summary(holdout_data),
        "aggregate": _aggregate(results),
        "activities": results,
        "reproduction_command": "python3 " + " ".join(sys.argv),
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if args.markdown_output:
        write_markdown_report(report, args.markdown_output)

    aggregate = report["aggregate"]
    print(
        "traced={activities_traced} opportunities={runtime_safe_opportunities} "
        "activities_with_opportunities={activities_with_opportunities}".format(**aggregate)
    )
    print(f"wrote JSON: {args.output}")
    if args.markdown_output:
        print(f"wrote Markdown: {args.markdown_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
