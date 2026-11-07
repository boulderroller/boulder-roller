"""Local-date evidence from synthetic file bytes, never from a virtual map."""

import importlib.util
from datetime import datetime, date
from pathlib import Path

import pytest
import workout_parse as wp

from app.services.training_metrics import evidence_for, compute
from app.services.riding_days import aggregate_training_weeks

spec = importlib.util.spec_from_file_location(
    "training_context_vectors",
    Path(__file__).resolve().parents[3]
    / "workout-parse/tests/test_training_context.py",
)
vectors = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vectors)


@pytest.mark.parametrize(
    "kwargs,zone,offset",
    [
        (
            {"sub_sport": 58, "offset": -14400, "position": (-11.6359, 166.9726)},
            None,
            -14400,
        ),
        ({"offset": 19800}, None, 19800),
        ({}, "America/New_York", None),
        ({"sub_sport": 6}, None, None),
        ({"trainer": True}, None, None),
        ({"manufacturer": 260}, None, None),
        ({"position": (-11.6359, 166.9726)}, None, None),
        ({"position": (-10.8, 165.82)}, None, None),
        ({"position": (-21.7, 166.2)}, None, None),
    ],
)
def test_file_date_evidence_precedence(kwargs, zone, offset):
    activity = wp.parse_bytes(vectors.fit_context(**kwargs))
    evidence = evidence_for(activity)
    assert evidence["timezone"] == zone
    assert evidence.get("utc_offset_s") == offset


def test_philadelphia_evening_zwift_stays_on_riders_day():
    activity = wp.parse_bytes(
        vectors.fit_context(sub_sport=58, offset=-14400, position=(-11.6359, 166.9726))
    )
    evidence = evidence_for(activity)
    inputs = {
        "started_at": "2026-10-07T23:00:00Z",
        **evidence,
        "timezone_basis": "device",
    }
    result = compute(activity, inputs)
    assert result["local_date"] == "2026-10-07"
    assert result["utc_offset_s"] == -14400
    assert result["timezone"] is None
    # A configured rider zone takes precedence, even over a different device clock.
    inputs["settings"] = {"timezone": "Asia/Tokyo"}
    assert compute(activity, inputs)["local_date"] == "2026-10-08"


def test_undated_ride_only_marks_weeks_it_could_have_occurred_in():
    rides = [
        {"processing_status": "completed", "started_at": "2026-10-05T01:00:00Z", "training_metrics": {"local_date": None}}
    ]
    result = aggregate_training_weeks(rides, end_date=date(2026, 10, 8), weeks=12)
    assert all(not r["partial"] and r["distance_m"] == 0 for r in result[:-2])
    assert all(r["partial"] and r["distance_m"] is None for r in result[-2:])
