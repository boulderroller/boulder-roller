from datetime import date

from app.services.riding_days import aggregate_riding_days


def _ride(day, duration_sec, status="completed"):
    return {
        "started_at": f"{day}T14:00:00+00:00",
        "duration_sec": 9999,
        "training_metrics": {"moving_s": duration_sec},
        "processing_status": status,
    }


def test_days_sum_moving_time_and_count_rides():
    rides = [
        _ride("2026-08-10", 3600),
        _ride("2026-08-10", 1800),
        _ride("2026-08-12", 2700),
    ]
    days = aggregate_riding_days(
        rides, start_date=date(2026, 8, 1), end_date=date(2026, 8, 31)
    )
    assert days == [
        {
            "date": "2026-08-10",
            "moving_s": 5400,
            "ride_count": 2,
            "distance_m": None,
            "elevation_gain_m": None,
        },
        {
            "date": "2026-08-12",
            "moving_s": 2700,
            "ride_count": 1,
            "distance_m": None,
            "elevation_gain_m": None,
        },
    ]


def test_failed_and_out_of_window_rides_are_excluded_even_when_scored():
    rides = [_ride("2026-08-10", 3600, status="failed"), _ride("2026-07-01", 3600)]
    days = aggregate_riding_days(
        rides, start_date=date(2026, 8, 1), end_date=date(2026, 8, 31)
    )
    assert days == []


def test_missing_moving_time_stays_absent():
    rides = [
        {
            "started_at": "2026-08-10T14:00:00+00:00",
            "duration_sec": None,
            "processing_status": "completed",
        }
    ]
    days = aggregate_riding_days(
        rides, start_date=date(2026, 8, 1), end_date=date(2026, 8, 31)
    )
    assert days == [
        {
            "date": "2026-08-10",
            "moving_s": None,
            "ride_count": 1,
            "distance_m": None,
            "elevation_gain_m": None,
        }
    ]
