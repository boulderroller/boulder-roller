from __future__ import annotations

from compare_candidate_generators import (
    classify_failure,
    expected_anchor_quality,
    expected_review_state,
    mode_score,
    scored_expected_rows,
)


class FakeClimb:
    def __init__(self, *, vert_m: float, start_time_offset_s: int):
        self.vert_m = vert_m
        self.start_time_offset_s = start_time_offset_s


def test_failure_taxonomy_distinguishes_negative_controls() -> None:
    assert (
        classify_failure(
            shown_count=0,
            expected_count=0,
            matched=0,
            extras=0,
            missed=0,
        )
        == "clean_negative_control"
    )
    assert (
        classify_failure(
            shown_count=2,
            expected_count=0,
            matched=0,
            extras=2,
            missed=0,
        )
        == "negative_control_false_positive"
    )


def test_failure_taxonomy_distinguishes_detector_failure_modes() -> None:
    assert (
        classify_failure(
            shown_count=1,
            expected_count=1,
            matched=1,
            extras=0,
            missed=0,
        )
        == "clean_pass"
    )
    assert (
        classify_failure(
            shown_count=0,
            expected_count=2,
            matched=0,
            extras=0,
            missed=2,
        )
        == "missing_all_expected"
    )
    assert (
        classify_failure(
            shown_count=1,
            expected_count=2,
            matched=1,
            extras=0,
            missed=1,
        )
        == "under_detecting"
    )
    assert (
        classify_failure(
            shown_count=3,
            expected_count=2,
            matched=2,
            extras=1,
            missed=0,
        )
        == "over_generating"
    )
    assert (
        classify_failure(
            shown_count=3,
            expected_count=2,
            matched=1,
            extras=2,
            missed=1,
        )
        == "mixed_boundary_drift"
    )


def test_anchor_quality_separates_strong_and_weak_annotations() -> None:
    assert expected_anchor_quality([]) == "negative_control"
    assert expected_anchor_quality([{"approx_start_s": 10}]) == "start_anchored"
    assert expected_anchor_quality([{"approx_vert_m": 80}]) == "vert_only"
    assert (
        expected_anchor_quality([{"approx_start_s": 10}, {"approx_vert_m": 80}])
        == "mixed_anchors"
    )


def test_pending_annotations_are_review_hints_not_scorecard_truth() -> None:
    expected_rows = [
        {"approx_start_s": 10, "approx_vert_m": 40},
        {
            "annotation_status": "pending_review",
            "approx_start_s": None,
            "approx_vert_m": 80,
        },
    ]

    assert scored_expected_rows(expected_rows) == [expected_rows[0]]
    assert expected_review_state(expected_rows) == "mixed_review"
    assert (
        expected_review_state(
            [
                {
                    "annotation_status": "pending_review",
                    "approx_start_s": None,
                    "approx_vert_m": 80,
                }
            ]
        )
        == "annotation_pending"
    )


def test_mode_score_does_not_penalize_against_only_pending_annotations() -> None:
    result = mode_score(
        [
            FakeClimb(vert_m=82, start_time_offset_s=1200),
            FakeClimb(vert_m=45, start_time_offset_s=2400),
        ],
        [
            {
                "annotation_status": "pending_review",
                "approx_start_s": None,
                "approx_vert_m": 80,
            }
        ],
    )

    assert result["shown"] == 2
    assert result["matched"] == 0
    assert result["extras"] == 0
    assert result["missed"] == 0
    assert result["pending_annotations"] == 1
    assert result["classification"] == "annotation_pending"
    assert result["review_state"] == "annotation_pending"


def test_mode_score_adds_taxonomy_and_anchor_quality() -> None:
    result = mode_score(
        [
            FakeClimb(vert_m=40, start_time_offset_s=100),
            FakeClimb(vert_m=35, start_time_offset_s=900),
        ],
        [{"approx_start_s": 110, "approx_vert_m": 40}],
    )

    assert result["matched"] == 1
    assert result["extras"] == 1
    assert result["missed"] == 0
    assert result["classification"] == "over_generating"
    assert result["anchor_quality"] == "start_anchored"
    assert result["review_state"] == "reviewed"
