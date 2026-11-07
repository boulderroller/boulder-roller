#!/usr/bin/env python3
"""Evaluate an opt-in interval-DP selector over traced canonical_v2 candidates.

This is an experiment harness only. Production canonical_v2 selection stays
unchanged; the selector can only replace an already-selected cluster winner with
another acceptable candidate from that same selected cluster. It never promotes
a candidate from an unselected cluster or creates a ride-only known-climb match.
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

from run_holdout_eval import (  # noqa: E402
    GOLDEN_DB,
    OVERLAP_THRESHOLD,
    Detection,
    classify_failure,
    compute_metrics,
    load_frequency_map,
)
from trace_detector_pipeline import trace_activity  # noqa: E402

QKJM_OPPORTUNITY_ACTIVITY_IDS = ("2243288124", "2526937019", "5773006459")


def _round(value: Any, digits: int = 4) -> Any:
    if value is None:
        return None
    return round(float(value), digits)


def _overlap_ratio(start_a: int, end_a: int, start_b: int, end_b: int) -> float:
    overlap = max(0, min(end_a, end_b) - max(start_a, start_b))
    shorter = min(max(1, end_a - start_a), max(1, end_b - start_b))
    return overlap / shorter


def _candidate_duration(candidate: dict[str, Any]) -> int:
    return max(1, int(candidate["end_s"]) - int(candidate["start_s"]))


def _score_margin(candidate: dict[str, Any]) -> float:
    value = candidate.get("score_margin")
    if value is not None:
        return float(value)
    return float(candidate.get("score") or 0.0) - float(candidate.get("threshold") or 0.0)


def _candidate_weight(candidate: dict[str, Any]) -> float:
    """Runtime-only replacement score for the opt-in DP experiment.

    The production chooser already supplies the acceptance gate. This experiment
    probes whether, within an accepted cluster, a longer accepted interval gives
    better boundary coverage than the highest raw score alone.
    """

    score = float(candidate.get("score") or 0.0)
    score_margin = _score_margin(candidate)
    vert_m = float(candidate.get("vert_m") or 0.0)
    # Make boundary coverage the experimental variable. Score still breaks
    # near-ties, but accepted longer intervals can beat shorter high-score
    # cluster winners, which is exactly what qkjm's replacement traces probe.
    return _candidate_duration(candidate) + (0.20 * vert_m) + (0.05 * score) + (0.05 * score_margin)


def _detection_from_candidate(candidate: dict[str, Any]) -> Detection:
    return Detection(
        start_s=int(candidate["start_s"]),
        end_s=int(candidate["end_s"]),
        vert_m=float(candidate.get("vert_m") or 0.0),
        grade_pct=float(candidate.get("grade_pct") or 0.0),
        distance_m=float(candidate.get("distance_m") or 0.0),
        mode=f"canonical_v2:{candidate.get('source') or 'selector'}",
    )


def _detection_from_selected(row: dict[str, Any]) -> Detection:
    return Detection(
        start_s=int(row["start_s"]),
        end_s=int(row["end_s"]),
        vert_m=float(row.get("vert_m") or 0.0),
        grade_pct=float(row.get("grade_pct") or 0.0),
        distance_m=float(row.get("distance_m") or 0.0),
        mode=row.get("detector_mode") or "canonical_v2",
    )


def _candidate_key(candidate: dict[str, Any]) -> str:
    return str(candidate["candidate_key"])


def _is_replacement_candidate(candidate: dict[str, Any]) -> bool:
    return (
        candidate.get("selectable") is True
        and candidate.get("decision") in {"selected", "acceptable_not_selected"}
        and _score_margin(candidate) >= 0.0
        and candidate.get("cluster_index") is not None
    )


def _selected_cluster_candidates(mode: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    selected_cluster_keys = {
        cluster["selected_key"]
        for cluster in mode.get("clusters", [])
        if cluster.get("accepted") and cluster.get("selected_key")
    }
    clusters: dict[int, list[dict[str, Any]]] = {}
    for candidate in mode.get("candidates", []):
        cluster_index = candidate.get("cluster_index")
        if cluster_index is None or not _is_replacement_candidate(candidate):
            continue
        cluster_selected = any(
            _candidate_key(cluster_candidate) in selected_cluster_keys
            for cluster_candidate in mode.get("candidates", [])
            if cluster_candidate.get("cluster_index") == cluster_index
        )
        if not cluster_selected:
            continue
        clusters.setdefault(int(cluster_index), []).append(candidate)
    return clusters


def _weighted_interval_schedule(options: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select non-overlapping options by weighted interval scheduling."""

    if not options:
        return []
    sorted_options = sorted(
        options,
        key=lambda option: (
            int(option["candidate"]["end_s"]),
            int(option["candidate"]["start_s"]),
            option["cluster_index"],
        ),
    )
    ends = [int(option["candidate"]["end_s"]) for option in sorted_options]
    previous: list[int] = []
    for idx, option in enumerate(sorted_options):
        start = int(option["candidate"]["start_s"])
        lo = 0
        hi = idx
        while lo < hi:
            mid = (lo + hi) // 2
            if ends[mid] <= start:
                lo = mid + 1
            else:
                hi = mid
        previous.append(lo - 1)

    dp = [0.0] * (len(sorted_options) + 1)
    keep = [False] * len(sorted_options)
    for idx, option in enumerate(sorted_options, start=1):
        include = float(option["weight"]) + dp[previous[idx - 1] + 1]
        exclude = dp[idx - 1]
        if include > exclude:
            dp[idx] = include
            keep[idx - 1] = True
        else:
            dp[idx] = exclude

    selected: list[dict[str, Any]] = []
    idx = len(sorted_options) - 1
    while idx >= 0:
        if keep[idx] and float(sorted_options[idx]["weight"]) + dp[previous[idx] + 1] >= dp[idx]:
            selected.append(sorted_options[idx])
            idx = previous[idx]
        else:
            idx -= 1
    return list(reversed(selected))


def select_replacements(mode: dict[str, Any]) -> tuple[list[Detection], list[dict[str, Any]]]:
    """Apply the constrained selector to one traced mode."""

    baseline_by_key = {
        _candidate_key(candidate): candidate
        for candidate in mode.get("candidates", [])
        if candidate.get("selected")
    }
    cluster_candidates = _selected_cluster_candidates(mode)
    options: list[dict[str, Any]] = []
    for cluster_index, candidates in cluster_candidates.items():
        selected = next((candidate for candidate in candidates if candidate.get("selected")), None)
        if selected is None:
            continue
        best = max(candidates, key=_candidate_weight)
        options.append(
            {
                "cluster_index": cluster_index,
                "selected_key": _candidate_key(selected),
                "candidate": best,
                "weight": _candidate_weight(best),
            }
        )

    scheduled = _weighted_interval_schedule(options)
    replacement_by_selected_key: dict[str, dict[str, Any]] = {}
    replacements: list[dict[str, Any]] = []
    for option in scheduled:
        candidate = option["candidate"]
        selected_key = option["selected_key"]
        selected = baseline_by_key.get(selected_key)
        if selected is None or _candidate_key(candidate) == selected_key:
            continue
        replacement_by_selected_key[selected_key] = candidate
        replacements.append(
            {
                "cluster_index": option["cluster_index"],
                "selected_key": selected_key,
                "replacement_key": _candidate_key(candidate),
                "selected_source": selected.get("source"),
                "replacement_source": candidate.get("source"),
                "selected_window": [selected.get("start_s"), selected.get("end_s")],
                "replacement_window": [candidate.get("start_s"), candidate.get("end_s")],
                "selected_score": selected.get("score"),
                "replacement_score": candidate.get("score"),
                "selected_weight": _round(_candidate_weight(selected)),
                "replacement_weight": _round(_candidate_weight(candidate)),
                "candidate_overlap": _round(
                    _overlap_ratio(
                        int(selected["start_s"]),
                        int(selected["end_s"]),
                        int(candidate["start_s"]),
                        int(candidate["end_s"]),
                    )
                ),
            }
        )

    detections: list[Detection] = []
    for selected in mode.get("selected", []):
        selected_key = f"{str(selected.get('detector_mode') or '').replace('canonical_v2:', '')}:{selected['start_s']}-{selected['end_s']}"
        replacement = replacement_by_selected_key.get(selected_key)
        detections.append(
            _detection_from_candidate(replacement)
            if replacement is not None
            else _detection_from_selected(selected)
        )
    return sorted(detections, key=lambda detection: detection.start_s), replacements


def _score_records(records: list[dict[str, Any]]) -> dict[str, Any]:
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


def _delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    return {
        "matched": int(after["matched"]) - int(before["matched"]),
        "missed": int(after["missed"]) - int(before["missed"]),
        "extras": int(after["extras"]) - int(before["extras"]),
        "precision": _round(after["precision"] - before["precision"]),
        "recall": _round(after["recall"] - before["recall"]),
        "f1": _round(after["f1"] - before["f1"]),
    }


def _aggregate(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    matched = sum(row[key]["matched"] for row in rows)
    missed = sum(row[key]["missed"] for row in rows)
    extras = sum(row[key]["extras"] for row in rows)
    precision, recall, f1 = compute_metrics(matched, missed, extras)
    taxonomy = Counter(row[key]["classification"] for row in rows)
    return {
        "rides_scored": len(rows),
        "matched": matched,
        "missed": missed,
        "extras": extras,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "taxonomy": dict(sorted(taxonomy.items())),
    }


def _activity_ids_from_holdout(
    holdout_json: Path,
    *,
    classification: str | None,
    qkjm_only: bool,
    limit: int,
) -> list[str]:
    data = json.loads(holdout_json.read_text())
    rows = list(data.get("deployment_per_ride") or data.get("scientific_per_ride") or [])
    if classification:
        rows = [row for row in rows if row.get("classification") == classification]
    if qkjm_only:
        allowed = set(QKJM_OPPORTUNITY_ACTIVITY_IDS)
        rows = [row for row in rows if str(row.get("activity_id")) in allowed]
    rows.sort(key=lambda row: str(row.get("activity_id")))
    if limit > 0:
        rows = rows[:limit]
    return [str(row["activity_id"]) for row in rows]


def _record_classification(summary: dict[str, Any], activity_id: str) -> str:
    return holdout_policy_classification(activity_id) or classify_failure(
        int(summary["matched"]),
        int(summary["missed"]),
        int(summary["extras"]),
    )


def holdout_policy_classification(activity_id: str) -> str | None:
    from holdout_reference_quality import holdout_policy_classification as classify

    return classify(activity_id)


def evaluate_activity(
    conn: sqlite3.Connection,
    activity_id: str,
    frequency_map: dict[str, int] | None,
    *,
    bridge_mode: str,
    preserve_pre_bridge_persistence: bool,
) -> dict[str, Any]:
    trace = trace_activity(
        conn,
        activity_id,
        frequency_map,
        bridge_mode=bridge_mode,
        preserve_pre_bridge_persistence=preserve_pre_bridge_persistence,
    )
    if bridge_mode == "on":
        mode_name = "bridge_on"
    elif bridge_mode == "off":
        mode_name = "bridge_off"
    else:
        raise ValueError("selector eval expects a single bridge mode")

    mode = trace["modes"][mode_name]
    selector_detections, replacements = select_replacements(mode)
    selector_records = _records_for_selector_from_trace(mode, selector_detections)
    baseline = dict(mode["match_summary"])
    selected = _score_records(selector_records)
    baseline["classification"] = _record_classification(baseline, activity_id)
    selected["classification"] = _record_classification(selected, activity_id)
    return {
        "activity_id": activity_id,
        "segments": trace.get("segments"),
        "baseline": baseline,
        "selector": selected,
        "delta": _delta(baseline, selected),
        "replacements": replacements,
        "replacement_count": len(replacements),
        "matches_production_selection": mode.get("matches_production_selection"),
        "selector_records": selector_records,
    }


def _records_for_selector_from_trace(
    mode: dict[str, Any],
    selector_detections: list[Detection],
) -> list[dict[str, Any]]:
    """Score replacements using reference rows already embedded in the trace.

    trace_detector_pipeline does not currently expose Segment objects, but its
    baseline match records contain the scored reference windows. Rebuilding from
    those rows keeps this experiment local and avoids changing trace defaults.
    """

    reference_rows = [
        row
        for row in mode.get("match_records", [])
        if row["result_type"] in {"matched", "missed"}
    ]
    used_detections: set[int] = set()
    records: list[dict[str, Any]] = []
    for ref in reference_rows:
        best_idx = None
        best_overlap = 0.0
        for idx, det in enumerate(selector_detections):
            if idx in used_detections:
                continue
            ratio = _overlap_ratio(
                int(ref["seg_start_s"]),
                int(ref["seg_end_s"]),
                det.start_s,
                det.end_s,
            )
            if ratio >= OVERLAP_THRESHOLD and ratio > best_overlap:
                best_idx = idx
                best_overlap = ratio

        segment_fields = {
            key: ref.get(key)
            for key in (
                "segment_id",
                "segment_name",
                "seg_start_s",
                "seg_end_s",
                "seg_elev_diff",
                "seg_avg_grade",
                "seg_distance_m",
            )
        }
        if best_idx is None:
            records.append({"result_type": "missed", **segment_fields})
            continue

        det = selector_detections[best_idx]
        used_detections.add(best_idx)
        records.append(
            {
                "result_type": "matched",
                **segment_fields,
                "det_start_s": det.start_s,
                "det_end_s": det.end_s,
                "det_vert_m": round(det.vert_m, 2),
                "det_grade_pct": round(det.grade_pct, 2),
                "det_distance_m": round(det.distance_m, 1),
                "det_mode": det.mode,
                "overlap_ratio": round(best_overlap, 3),
                "boundary_start_diff_s": det.start_s - int(ref["seg_start_s"]),
                "boundary_end_diff_s": det.end_s - int(ref["seg_end_s"]),
            }
        )

    for idx, det in enumerate(selector_detections):
        if idx in used_detections:
            continue
        records.append(
            {
                "result_type": "extra",
                "det_start_s": det.start_s,
                "det_end_s": det.end_s,
                "det_vert_m": round(det.vert_m, 2),
                "det_grade_pct": round(det.grade_pct, 2),
                "det_distance_m": round(det.distance_m, 1),
                "det_mode": det.mode,
            }
        )
    return sorted(
        records,
        key=lambda row: (
            row.get("seg_start_s")
            if row.get("seg_start_s") is not None
            else row.get("det_start_s", 0)
        ),
    )


def write_markdown_report(report: dict[str, Any], path: Path) -> None:
    baseline = report["aggregate"]["baseline"]
    selector = report["aggregate"]["selector"]
    delta = report["aggregate"]["delta"]
    lines = [
        "# Interval-DP Selector Experiment for 5i5p.1",
        "",
        "Scope: opt-in corpus experiment only. Production `canonical_v2` remains unchanged.",
        "",
        "## Selector Constraint",
        "",
        "- Only accepted `canonical_v2` clusters are considered.",
        "- The selector may replace the selected cluster winner with an `acceptable_not_selected` candidate from the same cluster.",
        "- It never promotes candidates from unselected clusters and never adds a known-climb candidate without ride-only detector evidence.",
        "",
        "## Command",
        "",
        "```bash",
        report["reproduction_command"],
        "```",
        "",
        "## Aggregate Delta",
        "",
        f"- Rides scored: {baseline['rides_scored']}",
        f"- Baseline matched/missed/extras: {baseline['matched']} / {baseline['missed']} / {baseline['extras']}",
        f"- Selector matched/missed/extras: {selector['matched']} / {selector['missed']} / {selector['extras']}",
        f"- Delta matched/missed/extras: {delta['matched']:+d} / {delta['missed']:+d} / {delta['extras']:+d}",
        f"- Baseline P/R/F1: {baseline['precision']} / {baseline['recall']} / {baseline['f1']}",
        f"- Selector P/R/F1: {selector['precision']} / {selector['recall']} / {selector['f1']}",
        f"- Delta P/R/F1: {delta['precision']:+.4f} / {delta['recall']:+.4f} / {delta['f1']:+.4f}",
        f"- Replacements applied: {report['aggregate']['replacement_count']}",
        "",
        "## Per-Ride Changes",
        "",
        "| Activity | Replacements | Baseline m/miss/x | Selector m/miss/x | Delta m/miss/x | Delta F1 |",
        "| --- | ---: | --- | --- | --- | ---: |",
    ]
    for row in report["activities"]:
        if row["replacement_count"] == 0 and row["delta"]["f1"] == 0:
            continue
        lines.append(
            f"| {row['activity_id']} | {row['replacement_count']} | "
            f"{row['baseline']['matched']}/{row['baseline']['missed']}/{row['baseline']['extras']} | "
            f"{row['selector']['matched']}/{row['selector']['missed']}/{row['selector']['extras']} | "
            f"{row['delta']['matched']:+d}/{row['delta']['missed']:+d}/{row['delta']['extras']:+d} | "
            f"{row['delta']['f1']:+.4f} |"
        )
    lines.extend([
        "",
        "## Recommendation",
        "",
        report["recommendation"],
        "",
    ])
    path.write_text("\n".join(lines))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(GOLDEN_DB), help="Golden corpus DB path")
    parser.add_argument("--activity-id", action="append", default=[], help="Activity ID to evaluate")
    parser.add_argument("--holdout-json", type=Path, help="Use activity IDs from a holdout JSON")
    parser.add_argument(
        "--classification",
        default=None,
        help="Optional holdout classification filter, e.g. mixed_boundary_drift",
    )
    parser.add_argument(
        "--qkjm-only",
        action="store_true",
        help="Restrict holdout JSON rows to qkjm's three replacement activity IDs",
    )
    parser.add_argument("--limit", type=int, default=0, help="Limit selected activities")
    parser.add_argument(
        "--bridge-mode",
        choices=["on", "off"],
        default="on",
        help="Deployment-compatible selector eval uses bridge on",
    )
    parser.add_argument(
        "--preserve-pre-bridge-persistence",
        action="store_true",
        help="Pass through trace_detector_pipeline experimental mode",
    )
    parser.add_argument("--output", type=Path, required=True, help="Write JSON report")
    parser.add_argument("--markdown-output", type=Path, help="Write Markdown report")
    parser.add_argument("--verbose-logs", action="store_true", help="Keep INFO logs visible")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.verbose_logs:
        logging.getLogger().setLevel(logging.WARNING)

    activity_ids = [str(activity_id) for activity_id in args.activity_id]
    if args.holdout_json:
        activity_ids.extend(
            _activity_ids_from_holdout(
                args.holdout_json,
                classification=args.classification,
                qkjm_only=args.qkjm_only,
                limit=args.limit,
            )
        )
    if args.limit > 0 and not args.holdout_json:
        activity_ids = activity_ids[: args.limit]
    activity_ids = list(dict.fromkeys(activity_ids))
    if not activity_ids:
        print("ERROR: provide --activity-id or --holdout-json", file=sys.stderr)
        return 2

    db_path = Path(args.db)
    conn = sqlite3.connect(str(db_path))
    try:
        frequency_map = load_frequency_map(db_path) if args.bridge_mode == "on" else None
        activities = [
            evaluate_activity(
                conn,
                activity_id,
                frequency_map,
                bridge_mode=args.bridge_mode,
                preserve_pre_bridge_persistence=args.preserve_pre_bridge_persistence,
            )
            for activity_id in activity_ids
        ]
    finally:
        conn.close()

    baseline = _aggregate(activities, "baseline")
    selector = _aggregate(activities, "selector")
    aggregate_delta = _delta(baseline, selector)
    replacement_count = sum(row["replacement_count"] for row in activities)
    recommendation = (
        "Keep the selector opt-in only. It should not replace production canonical_v2 "
        "unless the full holdout shows positive F1 with no false-rewardable regression."
    )
    if aggregate_delta["f1"] <= 0:
        recommendation = (
            "Revert/do not promote. The constrained selector did not improve F1 on this eval slice."
        )

    report = {
        "config": {
            "db": str(db_path),
            "activity_ids": activity_ids,
            "holdout_json": str(args.holdout_json) if args.holdout_json else None,
            "classification": args.classification,
            "qkjm_only": args.qkjm_only,
            "bridge_mode": args.bridge_mode,
            "preserve_pre_bridge_persistence": args.preserve_pre_bridge_persistence,
            "frequency_map_tiles": len(frequency_map) if frequency_map else 0,
            "overlap_threshold": OVERLAP_THRESHOLD,
        },
        "aggregate": {
            "baseline": baseline,
            "selector": selector,
            "delta": aggregate_delta,
            "replacement_count": replacement_count,
        },
        "activities": activities,
        "recommendation": recommendation,
        "reproduction_command": "python3 " + " ".join(sys.argv),
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if args.markdown_output:
        write_markdown_report(report, args.markdown_output)

    print(
        "rides={rides} replacements={replacements} "
        "baseline={bm}/{bmi}/{bx} selector={sm}/{smi}/{sx} delta_f1={df1:+.4f}".format(
            rides=baseline["rides_scored"],
            replacements=replacement_count,
            bm=baseline["matched"],
            bmi=baseline["missed"],
            bx=baseline["extras"],
            sm=selector["matched"],
            smi=selector["missed"],
            sx=selector["extras"],
            df1=aggregate_delta["f1"],
        )
    )
    print(f"wrote JSON: {args.output}")
    if args.markdown_output:
        print(f"wrote Markdown: {args.markdown_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
