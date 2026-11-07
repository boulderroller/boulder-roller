#!/usr/bin/env python3
"""Compare two run_holdout_eval.py JSON outputs.

This is intentionally lightweight: it works from saved JSON artifacts, so a
failed detector prototype can be diffed after the code has been reverted.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


SUMMARY_FIELDS = (
    "total_matched",
    "total_missed",
    "total_extras",
    "precision",
    "recall",
    "f1",
)
PER_RIDE_FIELDS = ("matched", "missed", "extras", "detections", "precision", "recall", "f1")
MODE_CANDIDATES = ("deployment", "scientific", "eval", "train")


@dataclass(frozen=True)
class HoldoutRun:
    mode: str
    summary: dict[str, Any]
    per_ride: list[dict[str, Any]]


def _load_json(path: Path) -> dict[str, Any]:
    with path.open() as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _available_modes(data: dict[str, Any]) -> list[str]:
    return [
        key
        for key, value in data.items()
        if isinstance(value, dict)
        and isinstance(data.get(f"{key}_per_ride"), list)
    ]


def resolve_mode(base_data: dict[str, Any], new_data: dict[str, Any], requested: str) -> str:
    base_modes = set(_available_modes(base_data))
    new_modes = set(_available_modes(new_data))
    common = base_modes & new_modes

    if requested != "auto":
        if requested not in common:
            raise ValueError(
                f"mode {requested!r} is not present in both runs; common modes: {sorted(common)}"
            )
        return requested

    for mode in MODE_CANDIDATES:
        if mode in common:
            return mode

    if not common:
        raise ValueError("no comparable run mode found in both JSON files")
    return sorted(common)[0]


def load_run(path: Path, mode: str) -> HoldoutRun:
    data = _load_json(path)
    if mode not in data or f"{mode}_per_ride" not in data:
        raise ValueError(f"{path} does not contain mode {mode!r}")
    summary = data[mode]
    per_ride = data[f"{mode}_per_ride"]
    if not isinstance(summary, dict) or not isinstance(per_ride, list):
        raise ValueError(f"{path} has an invalid {mode!r} holdout shape")
    return HoldoutRun(mode=mode, summary=summary, per_ride=per_ride)


def _number(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _activity_key(row: dict[str, Any]) -> str:
    return str(row.get("activity_id", ""))


def _quality_delta(base: dict[str, Any], new: dict[str, Any]) -> float:
    """Positive is better, negative is worse.

    Per-ride F1 in the source JSON is rounded, so count movement is used as a
    deterministic tie-breaker.
    """
    f1_delta = _number(new.get("f1")) - _number(base.get("f1"))
    count_delta = (
        (_number(new.get("matched")) - _number(base.get("matched")))
        - (_number(new.get("missed")) - _number(base.get("missed")))
        - (_number(new.get("extras")) - _number(base.get("extras")))
    )
    return (f1_delta * 1000.0) + count_delta


def _classify_change(base: dict[str, Any], new: dict[str, Any]) -> str:
    score = _quality_delta(base, new)
    if score > 0.0001:
        return "improved"
    if score < -0.0001:
        return "regressed"
    return "changed_neutral"


def compare_runs(base: HoldoutRun, new: HoldoutRun) -> dict[str, Any]:
    base_by_id = {_activity_key(row): row for row in base.per_ride if _activity_key(row)}
    new_by_id = {_activity_key(row): row for row in new.per_ride if _activity_key(row)}

    summary_delta = {
        field: round(_number(new.summary.get(field)) - _number(base.summary.get(field)), 4)
        for field in SUMMARY_FIELDS
    }

    ride_changes: list[dict[str, Any]] = []
    for activity_id in sorted(set(base_by_id) | set(new_by_id)):
        base_row = base_by_id.get(activity_id)
        new_row = new_by_id.get(activity_id)
        if base_row is None:
            ride_changes.append({
                "activity_id": activity_id,
                "name": new_row.get("name") if new_row else "",
                "change_type": "added_ride",
            })
            continue
        if new_row is None:
            ride_changes.append({
                "activity_id": activity_id,
                "name": base_row.get("name"),
                "change_type": "removed_ride",
            })
            continue

        deltas = {
            field: round(_number(new_row.get(field)) - _number(base_row.get(field)), 4)
            for field in PER_RIDE_FIELDS
        }
        changed = any(delta != 0 for delta in deltas.values())
        base_class = base_row.get("classification")
        new_class = new_row.get("classification")
        if base_class != new_class:
            changed = True
        if not changed:
            continue

        ride_changes.append({
            "activity_id": activity_id,
            "name": new_row.get("name") or base_row.get("name"),
            "change_type": _classify_change(base_row, new_row),
            "quality_delta": round(_quality_delta(base_row, new_row), 4),
            "deltas": deltas,
            "base": {field: base_row.get(field) for field in PER_RIDE_FIELDS},
            "new": {field: new_row.get(field) for field in PER_RIDE_FIELDS},
            "classification": {
                "base": base_class,
                "new": new_class,
            },
        })

    ride_changes.sort(key=lambda row: (row.get("quality_delta", 0.0), row["activity_id"]))

    return {
        "mode": base.mode,
        "summary_delta": summary_delta,
        "base_summary": {field: base.summary.get(field) for field in SUMMARY_FIELDS},
        "new_summary": {field: new.summary.get(field) for field in SUMMARY_FIELDS},
        "changed_rides": len(ride_changes),
        "improved_rides": sum(1 for row in ride_changes if row["change_type"] == "improved"),
        "regressed_rides": sum(1 for row in ride_changes if row["change_type"] == "regressed"),
        "neutral_changed_rides": sum(
            1 for row in ride_changes if row["change_type"] == "changed_neutral"
        ),
        "ride_changes": ride_changes,
    }


def _format_metric(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _print_summary(comparison: dict[str, Any], top: int) -> None:
    mode = comparison["mode"]
    print(f"Mode: {mode}")
    print()
    print("Summary")
    for field in SUMMARY_FIELDS:
        base = _format_metric(comparison["base_summary"].get(field))
        new = _format_metric(comparison["new_summary"].get(field))
        delta = comparison["summary_delta"].get(field)
        sign = "+" if isinstance(delta, (int, float)) and delta > 0 else ""
        print(f"  {field:14s} {base:>8s} -> {new:>8s}  ({sign}{_format_metric(delta)})")

    print()
    print(
        "Changed rides: "
        f"{comparison['changed_rides']} "
        f"({comparison['improved_rides']} improved, "
        f"{comparison['regressed_rides']} regressed, "
        f"{comparison['neutral_changed_rides']} neutral)"
    )

    changes = comparison["ride_changes"]
    if not changes:
        return

    regressions = [row for row in changes if row["change_type"] == "regressed"]
    if regressions:
        print()
        print(f"Top regressions ({min(top, len(regressions))})")
        for row in regressions[:top]:
            _print_ride_change(row)

    improvements = [row for row in reversed(changes) if row["change_type"] == "improved"]
    if improvements:
        print()
        print(f"Top improvements ({min(top, len(improvements))})")
        for row in improvements[:top]:
            _print_ride_change(row)


def _print_ride_change(row: dict[str, Any]) -> None:
    deltas = row.get("deltas", {})
    name = row.get("name") or "(unnamed)"
    print(
        f"  {row['activity_id']}  {row['change_type']:9s}  "
        f"dm={deltas.get('matched', 0):+g} "
        f"dmiss={deltas.get('missed', 0):+g} "
        f"dextra={deltas.get('extras', 0):+g} "
        f"df1={deltas.get('f1', 0):+g}  {name}"
    )


def _write_json(path: Path, comparison: dict[str, Any]) -> None:
    path.write_text(json.dumps(comparison, indent=2, sort_keys=True) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", type=Path, help="Baseline run_holdout_eval.py JSON output")
    parser.add_argument("new", type=Path, help="New/prototype run_holdout_eval.py JSON output")
    parser.add_argument(
        "--mode",
        default="auto",
        help="Run mode to compare: deployment, scientific, eval, train, or auto",
    )
    parser.add_argument("--top", type=int, default=10, help="Number of rides to print per bucket")
    parser.add_argument("--json-output", type=Path, help="Write full comparison JSON to this path")
    parser.add_argument("--quiet", action="store_true", help="Only write JSON output")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        base_data = _load_json(args.base)
        new_data = _load_json(args.new)
        mode = resolve_mode(base_data, new_data, args.mode)
        comparison = compare_runs(
            HoldoutRun(mode, base_data[mode], base_data[f"{mode}_per_ride"]),
            HoldoutRun(mode, new_data[mode], new_data[f"{mode}_per_ride"]),
        )
    except (OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json_output:
        _write_json(args.json_output, comparison)
    if not args.quiet:
        _print_summary(comparison, args.top)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
