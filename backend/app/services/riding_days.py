"""Stored engine facts grouped by their frozen rider-local calendar day."""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

from app.services.fitness_analytics import training_date
from app.services.training_eligibility import COUNTED_STATUSES, is_training_eligible

FIELDS = ("moving_s", "distance_m", "elevation_gain_m")


def has_local_date(ride):
    metrics = ride.get("training_metrics") or {}
    return "local_date" not in metrics or metrics["local_date"] is not None


def undated_count(rides, start_date, end_date):
    # Without a zone, an instant can fall on either adjacent calendar date.
    # Count this uncertainty; never assign it to a fabricated local day.
    return sum(
        is_training_eligible(r)
        and not has_local_date(r)
        and start_date - timedelta(days=1)
        <= training_date(r)
        <= end_date + timedelta(days=1)
        for r in rides
    )


def aggregate_riding_days(
    rides: list[dict[str, Any]],
    *,
    start_date: date,
    end_date: date,
    timezone_name: str | None = None,
) -> list[dict[str, Any]]:
    totals = {}
    for ride in rides:
        if not has_local_date(ride):
            continue
        if not is_training_eligible(ride):
            continue
        ride_date = training_date(ride)
        if not start_date <= ride_date <= end_date:
            continue
        entry = totals.setdefault(
            ride_date, {**dict.fromkeys(FIELDS, 0.0), "ride_count": 0}
        )
        entry["ride_count"] += 1
        metrics = ride.get("training_metrics") or {}
        for field in FIELDS:
            value = metrics.get(field)
            if value is None:
                entry[field] = None
                continue
            value = float(value)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"invalid stored {field}")
            if entry[field] is not None:
                entry[field] += value
    return [
        {
            "date": day.isoformat(),
            **entry,
            "moving_s": (
                round(entry["moving_s"]) if entry["moving_s"] is not None else None
            ),
        }
        for day, entry in sorted(totals.items())
    ]


def aggregate_training_weeks(rides, *, end_date, weeks=12):
    monday = end_date - timedelta(days=end_date.weekday())
    start_date = monday - timedelta(weeks=weeks - 1)
    daily = aggregate_riding_days(rides, start_date=start_date, end_date=end_date)
    result = []
    for offset in reversed(range(weeks)):
        start = monday - timedelta(weeks=offset)
        unknown = undated_count(rides, start, min(start + timedelta(days=6), end_date))
        selected = [
            r
            for r in daily
            if start.isoformat() <= r["date"] < (start + timedelta(days=7)).isoformat()
        ]
        row = {"week_start": start.isoformat(), "partial": bool(unknown)}
        for output, field in [
            ("distance_m", "distance_m"),
            ("duration_s", "moving_s"),
            ("climb_m", "elevation_gain_m"),
        ]:
            values = [r[field] for r in selected]
            unavailable = bool(unknown) or any(v is None for v in values)
            row[output] = None if unavailable else sum(values)
            row["partial"] = row["partial"] or unavailable
        result.append(row)
    return result
