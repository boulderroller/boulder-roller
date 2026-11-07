from datetime import datetime, timedelta, timezone

from app.services.sample_time import normalize_sample_times_to_seconds


def test_normalize_sample_times_to_seconds_handles_datetime_and_numeric_values():
    base_time = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)
    samples = [
        {"t": base_time + timedelta(seconds=20), "value": "late"},
        {"t": 5, "value": "numeric"},
        {"value": "untimed"},
        {"t": base_time + timedelta(seconds=10), "value": "middle"},
    ]

    normalized = normalize_sample_times_to_seconds(samples, base_time=base_time, sort=True)

    assert [sample["value"] for sample in normalized] == ["numeric", "middle", "late"]
    assert [sample["t"] for sample in normalized] == [5.0, 10.0, 20.0]
