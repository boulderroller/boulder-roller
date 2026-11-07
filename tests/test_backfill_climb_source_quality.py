import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "tools" / "backfill_climb_source_quality.py"
SPEC = importlib.util.spec_from_file_location("backfill_climb_source_quality", SCRIPT_PATH)
script = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(script)


def test_existing_trace_preserves_json_object_fields():
    assert script.existing_trace({"detector": "legacy"}) == {"detector": "legacy"}
    assert script.existing_trace('{"detector":"legacy"}') == {"detector": "legacy"}
    assert script.existing_trace(None) == {}
    assert script.existing_trace("[]") == {}


def test_summarize_quality_counts_demotions_and_reasons():
    rows = [
        {
            "quality": {
                "economic_eligible": True,
                "sample_count": 3,
                "abstention_reasons": [],
            }
        },
        {
            "quality": {
                "economic_eligible": False,
                "sample_count": 0,
                "abstention_reasons": ["CLIMB_SENSOR:no_samples_in_window"],
            }
        },
    ]

    assert script.summarize_quality(rows) == {
        "rows_scanned": 2,
        "eligible_after": 1,
        "demoted_after": 1,
        "missing_samples": 1,
        "reasons": {"CLIMB_SENSOR:no_samples_in_window": 1},
    }


def test_climb_from_row_uses_offsets_when_time_missing():
    climb = script.climb_from_row(
        {
            "start_offset_s": 10,
            "end_offset_s": 70,
            "vert_m": 30,
            "time_s": None,
            "distance_m": None,
            "avg_gradient_pct": 5.0,
        }
    )

    assert climb.start_time_offset_s == 10
    assert climb.end_time_offset_s == 70
    assert climb.time_s == 60
    assert climb.distance_m == 0.0
    assert climb.avg_gradient_pct == 5.0
