from __future__ import annotations

from trace_detector_pipeline import _summarize_elevation_delta, diagnose_match_records


def test_summarize_elevation_delta_groups_changed_ranges() -> None:
    before = [
        {"t": 0, "elevation_m": 10.0},
        {"t": 5, "elevation_m": 11.0},
        {"t": 10, "elevation_m": 12.0},
        {"t": 15, "elevation_m": 13.0},
        {"t": 20, "elevation_m": 14.0},
    ]
    after = [
        {"t": 0, "elevation_m": 10.0},
        {"t": 5, "elevation_m": 10.5},
        {"t": 10, "elevation_m": 12.5},
        {"t": 15, "elevation_m": 13.0},
        {"t": 20, "elevation_m": 15.25},
    ]

    summary = _summarize_elevation_delta(before, after)

    assert summary["changed_samples"] == 3
    assert summary["total_abs_delta_m"] == 2.25
    assert summary["max_abs_delta_m"] == 1.25
    assert summary["changed_ranges"] == [
        {
            "start_idx": 1,
            "end_idx": 2,
            "start_s": 5,
            "end_s": 10,
            "samples": 2,
            "min_delta_m": -0.5,
            "max_delta_m": 0.5,
            "max_abs_delta_m": 0.5,
        },
        {
            "start_idx": 4,
            "end_idx": 4,
            "start_s": 20,
            "end_s": 20,
            "samples": 1,
            "min_delta_m": 1.25,
            "max_delta_m": 1.25,
            "max_abs_delta_m": 1.25,
        },
    ]


def test_diagnose_match_records_buckets_missed_segments_by_candidate_stage() -> None:
    records = [
        {
            "result_type": "missed",
            "segment_id": 1,
            "segment_name": "Rejected Climb",
            "seg_start_s": 100,
            "seg_end_s": 200,
        },
        {
            "result_type": "missed",
            "segment_id": 2,
            "segment_name": "Absent Climb",
            "seg_start_s": 400,
            "seg_end_s": 500,
        },
        {
            "result_type": "extra",
            "det_start_s": 700,
            "det_end_s": 760,
            "det_mode": "canonical_v2:momentum:rolling",
        },
    ]
    candidates = [
        {
            "candidate_key": "momentum:rolling:105-190",
            "source": "momentum:rolling",
            "family": "momentum",
            "selected": False,
            "decision": "rejected",
            "start_s": 105,
            "end_s": 190,
            "score_margin": -0.75,
        }
    ]

    diagnostics = diagnose_match_records(records, candidates)

    assert diagnostics[0]["diagnosis"] == "candidate_generated_rejected"
    assert diagnostics[0]["best_candidates"][0]["overlap_ratio"] == 1.0
    assert diagnostics[1]["diagnosis"] == "no_candidate_generated"
    assert diagnostics[2]["diagnosis"] == "selected_extra"
