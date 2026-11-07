"""Versioned training projection. This module never writes economic fields.

The native v1/v2 entry points remain replayable. Version 3 respects frozen HR
zone tops, uses unsmoothed HR, and prefers positive device calorie estimates
over the work-based estimate at 24% efficiency.
"""

from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo
from .training_eligibility import is_training_eligible

ENGINE_VERSION = 3


@lru_cache(maxsize=1)
def _timezone_finder():
    from timezonefinder import TimezoneFinder

    return TimezoneFinder()


def ride_timezone(activity):
    """Last-resort outdoor geography; virtual/trainer positions are not clocks."""
    context = activity.training_context
    if context["indoor_or_virtual"] or context["utc_offset_s"] is not None:
        return None
    lat, lon = activity.lat_e7, activity.lon_e7
    if lat is None or lon is None:
        return None
    for a, b in zip(lat, lon):
        a, b = float(a) / 1e7, float(b) / 1e7
        if -90 <= a <= 90 and -180 <= b <= 180:
            # Synthetic offshore worlds can survive exports without FIT flags.
            # These small map envelopes only veto geography; they never assert
            # a rider location. Real-city maps require the file's indoor flags.
            if any(
                south <= a <= north and west <= b <= east
                for south, north, west, east in VIRTUAL_MAP_BOUNDS
            ):
                return None
            return _timezone_finder().timezone_at(lat=a, lng=b)
    return None


# Offshore map bounds (data only, no rider files):
# https://github.com/andipaetzold/zwift-data/blob/107dbeeee720df09797e97cd37f5464e56ef7bbe/src/worlds.ts
VIRTUAL_MAP_BOUNDS = (
    (-11.74087, -11.62597, 166.87747, 167.03255),  # Watopia
    (-10.85234, -10.73746, 165.76591, 165.88222),  # Makuri
    (-21.7564, -21.64155, 166.1384, 166.26125),  # France
    (-10.4038, -10.3657, 165.7824, 165.8207),  # Crit City
)


METRIC_FIELDS = (
    "engine_version",
    "elapsed_s",
    "recording_s",
    "moving_s",
    "np_w",
    "load",
    "load_basis",
    "intensity_pct",
    "avg_power_w",
    "work_j",
    "variability_index",
    "efficiency_factor",
    "distance_m",
    "elevation_gain_m",
    "avg_hr_bpm",
    "max_hr_bpm",
    "avg_cadence_rpm",
    "max_cadence_rpm",
    "avg_speed_mps",
    "max_speed_mps",
    "max_power_w",
    "calories_kcal",
    "calories_estimate",
    "calories_basis",
    "decoupling_pct",
    "power_zone_s",
    "hr_zone_s",
    "power_zone_tops_w",
    "hr_zone_tops_bpm",
    "power_curve_s",
    "power_curve_w",
)


def measure(value, basis: str, estimate: bool = False) -> dict | None:
    return (
        None
        if value is None
        else {"value": value, "estimate": estimate, "basis": basis}
    )


def physiology(inputs: dict) -> dict:
    settings = inputs.get("settings") or {}
    resting = measure(
        settings.get("resting_hr_bpm", 60),
        "rider" if settings.get("resting_hr_bpm") else "intervals_default_60",
        not bool(settings.get("resting_hr_bpm")),
    )
    max_hr = measure(settings.get("max_hr_bpm"), "rider")
    if max_hr is None and settings.get("hr_zone_tops_bpm"):
        max_hr = measure(
            settings["hr_zone_tops_bpm"][-1], "last_configured_hr_zone", True
        )
    # There is no universal numeric ICU max-HR default. Retained observed peak
    # is explicitly an estimate; a ride without HR cannot invent one.
    if max_hr is None:
        max_hr = measure(inputs.get("observed_max_hr_bpm"), "observed_peak_hr", True)
    lthr = measure(settings.get("threshold_hr_bpm"), "rider")
    if lthr is None and inputs.get("best_20m_hr_bpm"):
        lthr = measure(
            int(inputs["best_20m_hr_bpm"] * 0.95 + 0.5), "95_percent_best_20m_hr", True
        )
    if lthr is None and max_hr:
        lthr = measure(int(max_hr["value"] * 0.9 + 0.5), "90_percent_max_hr", True)
    if max_hr and max_hr["value"] <= resting["value"]:
        max_hr = None
    if lthr and (
        lthr["value"] <= resting["value"]
        or (max_hr and lthr["value"] > max_hr["value"])
    ):
        lthr = None
    return {
        "resting_hr": resting,
        "max_hr": max_hr,
        "threshold_hr": lthr,
        "hrss_k": 1.67 if settings.get("sex") == "female" else 1.92,
    }


def evidence_for(activity) -> dict:
    import workout_parse as wp

    result = wp.compute_training_metrics(activity, 0, engine_version=ENGINE_VERSION)
    curve = dict(zip(result.power_curve_s, result.power_curve_w or []))
    return {
        "engine_version": ENGINE_VERSION,
        "timezone": ride_timezone(activity),
        "utc_offset_s": activity.training_context["utc_offset_s"],
        **{f"best_{s}s_w": curve.get(s) for s in (180, 420, 900)},
        "best_20m_hr_bpm": result.best_20m_hr_bpm,
        "max_hr_bpm": result.max_hr_bpm,
    }


def compute(activity, inputs: dict, *, start_s=None, end_s=None) -> dict:
    import workout_parse as wp

    hr = physiology(inputs)
    value = lambda key: (hr[key] or {}).get("value")
    threshold = inputs.get("threshold")
    raw = wp.compute_training_metrics(
        activity,
        (threshold or {}).get("value", 0),
        engine_version=ENGINE_VERSION,
        start_s=start_s,
        end_s=end_s,
        lthr_bpm=value("threshold_hr"),
        resting_hr_bpm=value("resting_hr"),
        max_hr_bpm=value("max_hr"),
        hrss_k=hr["hrss_k"],
        hr_zones_bpm=(inputs.get("settings") or {}).get("hr_zone_tops_bpm"),
    )
    result = {name: getattr(raw, name) for name in METRIC_FIELDS}
    tops = raw.power_zone_tops_w
    result["power_zone_ranges_w"] = (
        [
            [0 if i == 0 else tops[i - 1] + 1, tops[i] if i < 6 else None]
            for i in range(7)
        ]
        if tops
        else None
    )
    times = (raw.power_zone_s or [])[:7]
    result["power_zone_total_s"] = sum(times) if times else None
    result["power_zone_pct"] = (
        [t * 100 / sum(times) for t in times] if sum(times) else None
    )
    result["threshold"] = threshold
    result["physiology"] = hr
    result["load_estimate"] = (
        raw.load_basis == "hrss"
        or bool((threshold or {}).get("estimate"))
        or inputs.get("history_complete") is False
    )
    result["load_state"] = "scored" if raw.load is not None else "unavailable"
    result["history_complete"] = inputs.get("history_complete", True)
    result["estimates"] = {
        "threshold": threshold,
        "threshold_hr": hr["threshold_hr"],
        "load": measure(
            raw.load, raw.load_basis or "unavailable", result["load_estimate"]
        ),
        "calories": measure(
            raw.calories_kcal,
            raw.calories_basis,
            raw.calories_estimate,
        ),
    }
    tz = inputs.get("timezone")
    offset = inputs.get("utc_offset_s")
    settings = inputs.get("settings") or {}
    if not tz and (offset is None or settings.get("timezone_source") != "inferred"):
        tz = settings.get("timezone")
    result["timezone"] = tz
    result["utc_offset_s"] = offset if not tz else None
    result["timezone_basis"] = inputs.get("timezone_basis")
    started = datetime.fromisoformat(str(inputs["started_at"]).replace("Z", "+00:00"))
    clock = (
        ZoneInfo(tz)
        if tz
        else timezone(timedelta(seconds=offset)) if offset is not None else None
    )
    result["local_date"] = inputs.get("local_date") or (
        started.astimezone(clock).date().isoformat() if clock else None
    )
    return result


class TrainingMetricsService:
    def __init__(self, repo):
        self.repo = repo

    async def score(self, *, ride_id: str, user_id: str, parsed_ride) -> dict:
        activity = getattr(parsed_ride, "_native_activity", None)
        if activity is None:
            raise ValueError("training requires retained native activity")
        evidence = await asyncio.to_thread(evidence_for, activity)
        inputs = await self.repo.bind_training_inputs(
            ride_id, user_id, parsed_ride.started_at, evidence
        )
        metrics = await asyncio.to_thread(compute, activity, inputs)
        from .climb_read_metrics import retained_climb_reads

        patterns = await self.repo.training_climb_patterns(ride_id)
        metrics["climbs"] = await asyncio.to_thread(
            retained_climb_reads, activity, patterns
        )
        from .climb_effort_metrics import build_effort_rows

        try:
            efforts = await asyncio.to_thread(build_effort_rows, activity, patterns, inputs)
            if efforts:
                await self.repo.store_climb_efforts(ride_id, user_id, inputs, efforts)
        except Exception:
            logging.getLogger(__name__).exception("Climb effort projection failed for ride %s", ride_id)
        return await self.repo.store_training_metrics(
            ride_id, user_id, inputs, metrics, evidence
        )


def project_training(ride: dict, *, owner: bool) -> dict:
    """No physiology or derived private training payload leaves the owner view."""
    result = dict(ride)
    metrics = result.pop("training_metrics", None)
    result.pop("training_inputs", None)
    result.pop("training_evidence", None)
    result.pop("training_error", None)
    result.pop("training_replay_state", None)
    if not owner:
        result.pop("max_hr_bpm", None)
    result["tss"] = None
    result["threshold_training_state"] = None
    for name in ("total_tss_after", "level_delta", "level_after"):
        result[name] = None
    if metrics and is_training_eligible(ride):
        metrics = dict(metrics)
        for column, key in [
            ("duration_sec", "elapsed_s"),
            ("moving_time_sec", "moving_s"),
            ("kcals", "calories_kcal"),
            ("distance_m", "distance_m"),
            ("elevation_gain_m", "elevation_gain_m"),
            ("avg_power_w", "avg_power_w"),
            ("max_power_w", "max_power_w"),
            ("normalized_power_w", "np_w"),
            ("avg_hr_bpm", "avg_hr_bpm"),
            ("avg_speed_mps", "avg_speed_mps"),
            ("avg_cadence_rpm", "avg_cadence_rpm"),
        ]:
            if metrics.get(key) is not None:
                result[column] = metrics[key]
            elif result.get(column) is not None:
                metrics[key] = result[column]
        # Common ride facts retain the same engine and calorie provenance for
        # every authorized viewer; Threshold, load and physiology stay private.
        public_fields = (
            "engine_version",
            "elapsed_s",
            "recording_s",
            "moving_s",
            "distance_m",
            "elevation_gain_m",
            "avg_power_w",
            "np_w",
            "avg_hr_bpm",
            "avg_cadence_rpm",
            "avg_speed_mps",
            "work_j",
            "calories_kcal",
            "calories_estimate",
        )
        result["training_metrics"] = (
            metrics
            if owner
            else {
                **{key: metrics.get(key) for key in public_fields},
                "estimates": {
                    "calories": (metrics.get("estimates") or {}).get("calories")
                },
            }
        )
        result["tss"] = metrics.get("load") if owner else None
    return result
