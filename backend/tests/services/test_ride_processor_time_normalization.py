from datetime import datetime, timezone

from app.services.ride_processor import _coerce_phase2_timestamp


def test_coerce_phase2_timestamp_accepts_iso_datetime_and_epoch_seconds():
    iso_value = "2026-06-12T21:18:00Z"
    epoch_value = datetime(2026, 6, 12, 21, 18, tzinfo=timezone.utc).timestamp()

    iso_timestamp = _coerce_phase2_timestamp(iso_value)
    epoch_timestamp = _coerce_phase2_timestamp(epoch_value)

    assert iso_timestamp == datetime(2026, 6, 12, 21, 18, tzinfo=timezone.utc)
    assert epoch_timestamp == datetime(2026, 6, 12, 21, 18, tzinfo=timezone.utc)
    assert _coerce_phase2_timestamp("not-a-date") is None


def test_coerce_phase2_timestamp_treats_compact_track_numbers_as_elapsed() -> None:
    base = datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc)

    assert _coerce_phase2_timestamp(0.625, base_time=base) == datetime(
        2026, 7, 20, 10, 0, 0, 625000, tzinfo=timezone.utc
    )
