from __future__ import annotations

from diff_holdout_runs import HoldoutRun, compare_runs, resolve_mode


def make_run(mode: str, per_ride: list[dict]) -> HoldoutRun:
    matched = sum(row["matched"] for row in per_ride)
    missed = sum(row["missed"] for row in per_ride)
    extras = sum(row["extras"] for row in per_ride)
    precision = matched / (matched + extras)
    recall = matched / (matched + missed)
    f1 = 2 * precision * recall / (precision + recall)
    return HoldoutRun(
        mode=mode,
        summary={
            "total_matched": matched,
            "total_missed": missed,
            "total_extras": extras,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        },
        per_ride=per_ride,
    )


def test_resolve_mode_prefers_deployment_when_available() -> None:
    base = {"deployment": {}, "deployment_per_ride": [], "scientific": {}, "scientific_per_ride": []}
    new = {"deployment": {}, "deployment_per_ride": []}

    assert resolve_mode(base, new, "auto") == "deployment"


def test_compare_runs_reports_summary_and_ride_deltas() -> None:
    base = make_run(
        "deployment",
        [
            {
                "activity_id": "1",
                "name": "worse",
                "matched": 3,
                "missed": 0,
                "extras": 0,
                "detections": 3,
                "precision": 1.0,
                "recall": 1.0,
                "f1": 1.0,
                "classification": "clean_pass",
            },
            {
                "activity_id": "2",
                "name": "better",
                "matched": 2,
                "missed": 1,
                "extras": 1,
                "detections": 3,
                "precision": 0.667,
                "recall": 0.667,
                "f1": 0.667,
                "classification": "mixed_boundary_drift",
            },
        ],
    )
    new = make_run(
        "deployment",
        [
            {
                "activity_id": "1",
                "name": "worse",
                "matched": 2,
                "missed": 1,
                "extras": 1,
                "detections": 3,
                "precision": 0.667,
                "recall": 0.667,
                "f1": 0.667,
                "classification": "mixed_boundary_drift",
            },
            {
                "activity_id": "2",
                "name": "better",
                "matched": 3,
                "missed": 0,
                "extras": 0,
                "detections": 3,
                "precision": 1.0,
                "recall": 1.0,
                "f1": 1.0,
                "classification": "clean_pass",
            },
        ],
    )

    comparison = compare_runs(base, new)

    assert comparison["summary_delta"]["total_matched"] == 0
    assert comparison["summary_delta"]["total_missed"] == 0
    assert comparison["summary_delta"]["total_extras"] == 0
    assert comparison["changed_rides"] == 2
    assert comparison["improved_rides"] == 1
    assert comparison["regressed_rides"] == 1
    assert [row["activity_id"] for row in comparison["ride_changes"]] == ["1", "2"]
    assert comparison["ride_changes"][0]["deltas"]["missed"] == 1
    assert comparison["ride_changes"][1]["deltas"]["extras"] == -1
