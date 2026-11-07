from __future__ import annotations

from audit_bridge_preprocessing import summarize_activities


def test_summarize_activities_totals_metric_delta_and_bridge_reasons() -> None:
    summary = summarize_activities([
        {
            "bridge_off": {"matched": 2, "missed": 1, "extras": 1, "precision": 0.0, "recall": 0.0, "f1": 0.0},
            "bridge_on": {"matched": 3, "missed": 0, "extras": 1, "precision": 0.0, "recall": 0.0, "f1": 0.0},
            "bridge_summary": {
                "status_counts": {"accepted": 1, "skipped": 2},
                "reason_counts": {"interpolated": 1, "track_span_too_large": 2},
            },
        },
        {
            "bridge_off": {"matched": 1, "missed": 2, "extras": 0, "precision": 0.0, "recall": 0.0, "f1": 0.0},
            "bridge_on": {"matched": 1, "missed": 2, "extras": 1, "precision": 0.0, "recall": 0.0, "f1": 0.0},
            "bridge_summary": {
                "status_counts": {"accepted": 2},
                "reason_counts": {"interpolated": 2},
            },
        },
    ])

    assert summary["rides_scored"] == 2
    assert summary["bridge_off"]["matched"] == 3
    assert summary["bridge_on"]["matched"] == 4
    assert summary["delta"]["matched"] == 1
    assert summary["delta"]["missed"] == -1
    assert summary["delta"]["extras"] == 1
    assert summary["bridge_status_counts"] == {"accepted": 3, "skipped": 2}
    assert summary["bridge_reason_counts"] == {
        "interpolated": 3,
        "track_span_too_large": 2,
    }
