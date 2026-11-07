from __future__ import annotations

from dataclasses import dataclass

from holdout_reference_quality import (
    holdout_policy_classification,
    quarantine_repeated_segment_spam,
)


@dataclass
class SegmentFixture:
    segment_id: int
    segment_name: str
    elevation_diff: float
    average_grade: float
    distance_m: float


def make_segments(
    count: int,
    *,
    segment_id: int,
    segment_name: str,
    elevation_diff: float,
    average_grade: float,
    distance_m: float,
) -> list[SegmentFixture]:
    return [
        SegmentFixture(
            segment_id=segment_id,
            segment_name=segment_name,
            elevation_diff=elevation_diff,
            average_grade=average_grade,
            distance_m=distance_m,
        )
        for _ in range(count)
    ]


def test_quarantines_dtown_mountain_repeated_weak_label_spam() -> None:
    segments = make_segments(
        29,
        segment_id=12_345,
        segment_name="Dtown Mountain",
        elevation_diff=28.0,
        average_grade=2.3,
        distance_m=1230.0,
    )

    curated, groups = quarantine_repeated_segment_spam(segments)

    assert curated == []
    assert len(groups) == 1
    assert groups[0].segment_name == "Dtown Mountain"
    assert groups[0].count == 29
    assert groups[0].reason == "repeated_weak_segment_label"


def test_quarantines_county_road_635_repeated_steep_template_label() -> None:
    segments = make_segments(
        18,
        segment_id=63_500,
        segment_name="County Road 635 Climb",
        elevation_diff=122.6,
        average_grade=16.9,
        distance_m=727.0,
    )

    curated, groups = quarantine_repeated_segment_spam(segments)

    assert curated == []
    assert len(groups) == 1
    assert groups[0].segment_name == "County Road 635 Climb"
    assert groups[0].count == 18
    assert groups[0].reason == "repeated_steep_template_label"


def test_keeps_smaller_repeat_sets_for_product_policy_review() -> None:
    segments = make_segments(
        8,
        segment_id=99,
        segment_name="Urban Hill Repeat",
        elevation_diff=32.0,
        average_grade=3.4,
        distance_m=940.0,
    )

    curated, groups = quarantine_repeated_segment_spam(segments)

    assert curated == segments
    assert groups == []


def test_keeps_non_spam_reference_segments_when_one_group_is_quarantined() -> None:
    spam = make_segments(
        16,
        segment_id=63_500,
        segment_name="County Road 635 Climb",
        elevation_diff=122.6,
        average_grade=16.9,
        distance_m=727.0,
    )
    trusted = [
        SegmentFixture(
            segment_id=7,
            segment_name="Real climb",
            elevation_diff=90.0,
            average_grade=6.0,
            distance_m=1500.0,
        )
    ]

    curated, groups = quarantine_repeated_segment_spam([*spam, *trusted])

    assert curated == trusted
    assert [group.reason for group in groups] == ["repeated_steep_template_label"]


def test_marks_wissahickon_as_policy_review_case() -> None:
    assert holdout_policy_classification("3523251381") == "urban_repeat_policy_review"
    assert holdout_policy_classification("709103855") is None
