from __future__ import annotations

from eval_interval_dp_selector import _score_records, select_replacements


def _candidate(
    key: str,
    *,
    cluster_index: int,
    selected: bool,
    decision: str,
    start_s: int,
    end_s: int,
    score: float,
) -> dict:
    source = key.split(":", 1)[0]
    if key.startswith("momentum:"):
        source = ":".join(key.split(":")[:2])
    return {
        "candidate_key": key,
        "cluster_index": cluster_index,
        "source": source,
        "family": "momentum" if source.startswith("momentum") else "persistence",
        "selected": selected,
        "decision": decision,
        "selectable": True,
        "score": score,
        "threshold": 4.0,
        "score_margin": score - 4.0,
        "start_s": start_s,
        "end_s": end_s,
        "vert_m": 42.0,
        "grade_pct": 5.0,
        "distance_m": 900.0,
    }


def test_select_replacements_only_uses_accepted_selected_clusters() -> None:
    mode = {
        "clusters": [
            {
                "cluster_index": 0,
                "accepted": True,
                "selected_key": "persistence:100-200",
            },
            {
                "cluster_index": 1,
                "accepted": False,
                "selected_key": None,
            },
        ],
        "candidates": [
            _candidate(
                "persistence:100-200",
                cluster_index=0,
                selected=True,
                decision="selected",
                start_s=100,
                end_s=200,
                score=7.0,
            ),
            _candidate(
                "momentum:rolling:90-260",
                cluster_index=0,
                selected=False,
                decision="acceptable_not_selected",
                start_s=90,
                end_s=260,
                score=6.8,
            ),
            _candidate(
                "momentum:rolling:500-700",
                cluster_index=1,
                selected=False,
                decision="acceptable_not_selected",
                start_s=500,
                end_s=700,
                score=9.0,
            ),
        ],
        "selected": [
            {
                "start_s": 100,
                "end_s": 200,
                "vert_m": 42.0,
                "grade_pct": 5.0,
                "distance_m": 900.0,
                "detector_mode": "canonical_v2:persistence",
            }
        ],
    }

    detections, replacements = select_replacements(mode)

    assert [(det.start_s, det.end_s) for det in detections] == [(90, 260)]
    assert len(replacements) == 1
    assert replacements[0]["selected_key"] == "persistence:100-200"
    assert replacements[0]["replacement_key"] == "momentum:rolling:90-260"


def test_score_records_uses_holdout_metric_shape() -> None:
    summary = _score_records(
        [
            {"result_type": "matched"},
            {"result_type": "missed"},
            {"result_type": "extra"},
        ]
    )

    assert summary == {
        "matched": 1,
        "missed": 1,
        "extras": 1,
        "precision": 0.5,
        "recall": 0.5,
        "f1": 0.5,
    }
