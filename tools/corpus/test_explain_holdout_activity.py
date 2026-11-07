from __future__ import annotations

from explain_holdout_activity import detailed_match_records
from run_holdout_eval import Detection, Segment


def make_segment(segment_id: int, start_index: int, end_index: int) -> Segment:
    return Segment(
        segment_id=segment_id,
        segment_name=f"segment {segment_id}",
        start_index=start_index,
        end_index=end_index,
        elevation_diff=40.0,
        average_grade=5.0,
        distance_m=800.0,
    )


def test_detailed_match_records_keeps_match_miss_extra_and_boundaries() -> None:
    time_array = [0, 10, 20, 30, 40, 50, 60]
    segments = [
        make_segment(1, 1, 3),
        make_segment(2, 4, 6),
    ]
    detections = [
        Detection(
            start_s=12,
            end_s=32,
            vert_m=42.0,
            grade_pct=5.2,
            distance_m=810.0,
            mode="canonical_v2:momentum",
        ),
        Detection(
            start_s=70,
            end_s=90,
            vert_m=25.0,
            grade_pct=3.0,
            distance_m=700.0,
            mode="canonical_v2:persistence",
        ),
    ]

    records = detailed_match_records(segments, detections, time_array)

    assert [record["result_type"] for record in records] == ["matched", "missed", "extra"]
    assert records[0]["segment_id"] == 1
    assert records[0]["overlap_ratio"] == 0.9
    assert records[0]["boundary_start_diff_s"] == 2
    assert records[0]["boundary_end_diff_s"] == 2
    assert records[1]["segment_id"] == 2
    assert records[2]["det_mode"] == "canonical_v2:persistence"
