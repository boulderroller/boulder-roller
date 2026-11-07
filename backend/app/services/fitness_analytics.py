"""
Training analytics: CTL/ATL/TSB calculations and daily aggregation helpers.
"""

from __future__ import annotations

from copy import copy
import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Callable, List, Optional

from ..repositories import FitnessRepository, RideRepository
from .training_eligibility import is_training_eligible
from .reward_threshold import (
    parse_threshold_rider_projection,
)


def has_dated_load(ride):
    metrics = ride.get("training_metrics") or {}
    return is_training_eligible(ride) and metrics.get("load") is not None and not (
        "local_date" in metrics and metrics["local_date"] is None
    )


class FitnessAnalyticsService:
    """Calculate and persist fitness metrics (CTL/ATL/TSB)."""

    CTL_TIME_CONSTANT = 42  # days
    ATL_TIME_CONSTANT = 7  # days

    def __init__(self, fitness_repo: FitnessRepository, ride_repo: RideRepository):
        self.fitness_repo = fitness_repo
        self.ride_repo = ride_repo

    async def calculate_threshold_ride_metrics(
        self,
        *,
        user_id: str,
        parsed_ride: Any,
        user_weight_kg: float,
        initial_metrics: Any,
        metrics_calculator: Callable[..., Any],
    ) -> tuple[Any, dict[str, Any]]:
        """Retained legacy write path; training reads use the frozen native projection."""
        raw = await self.ride_repo.get_reward_threshold_rider_projection(user_id)
        projection = parse_threshold_rider_projection(raw)
        denominator = projection.training_denominator
        if projection.state == "establishing":
            # The network placeholder can support Threshold-independent facts,
            # but its TSS never persists or surfaces.
            training_metrics = copy(initial_metrics)
            training_metrics.tss = None
            return training_metrics, {
                "threshold_training_w": None,
                "threshold_training_kind": None,
                "threshold_training_authority_id": None,
                "threshold_training_promotion_id": None,
            }

        metrics = metrics_calculator(
            parsed_ride=parsed_ride,
            user_weight_kg=user_weight_kg,
            user_ftp_w=denominator.watts,
        )
        denominator_raw = raw.get("training_denominator") or {}
        return metrics, {
            "threshold_training_w": denominator.watts,
            "threshold_training_kind": denominator.kind,
            "threshold_training_authority_id": denominator_raw.get("authority_id"),
            "threshold_training_promotion_id": denominator_raw.get("promotion_id"),
        }

    async def calculate_fitness_metrics(
        self, user_id: str, target_date: Optional[date] = None
    ) -> dict:
        """
        Calculate CTL, ATL, TSB for a user on a given date using exponentially weighted averages.
        """
        target_date = target_date or date.today()

        yesterday = target_date - timedelta(days=1)
        prev_metrics = (
            await self.fitness_repo.get_fitness_metrics(user_id, yesterday) or {}
        )

        prev_ctl = float(prev_metrics.get("ctl") or 0)
        prev_atl = float(prev_metrics.get("atl") or 0)

        daily_load = await self.fitness_repo.get_daily_training_load(
            user_id, target_date
        )
        today_tss = float(daily_load.get("total_tss") or 0) if daily_load else 0.0

        ctl_decay = 1 - math.exp(-1 / self.CTL_TIME_CONSTANT)
        atl_decay = 1 - math.exp(-1 / self.ATL_TIME_CONSTANT)

        new_ctl = prev_ctl + (today_tss - prev_ctl) * ctl_decay
        new_atl = prev_atl + (today_tss - prev_atl) * atl_decay
        new_tsb = new_ctl - new_atl

        week_ago = target_date - timedelta(days=7)
        week_ago_metrics = (
            await self.fitness_repo.get_fitness_metrics(user_id, week_ago) or {}
        )
        week_ago_ctl = float(week_ago_metrics.get("ctl") or 0)
        ramp_rate = new_ctl - week_ago_ctl

        return {
            "date": target_date.isoformat(),
            "ctl": round(new_ctl, 1),
            "atl": round(new_atl, 1),
            "tsb": round(new_ctl) - round(new_atl),
            "ramp_rate": round(ramp_rate, 1),
            "form": self._get_form_status(new_tsb),
        }

    @staticmethod
    def _get_form_status(tsb: float) -> str:
        """Interpret TSB into a form descriptor."""
        if tsb > 20:
            return "Transition"
        if tsb > 5:
            return "Fresh"
        if tsb > -10:
            return "Grey zone"
        if tsb > -30:
            return "Optimal"
        return "High risk"

    @staticmethod
    def threshold_daily_loads(
        rides: list[dict[str, Any]],
        *,
        threshold_w: int,
        start_date: date,
        end_date: date,
        timezone_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Sum frozen per-ride scores; never apply today's Threshold to history."""
        totals: dict[date, float] = {}
        estimates: dict[date, bool] = {}
        for ride in rides:
            if not has_dated_load(ride):
                continue
            ride_date = training_date(ride, timezone_name)
            if not start_date <= ride_date <= end_date:
                continue
            tss = (ride.get("training_metrics") or {}).get("load")
            if tss is None:
                continue
            totals[ride_date] = totals.get(ride_date, 0.0) + tss
            estimates[ride_date] = estimates.get(ride_date, False) or bool(
                ride["training_metrics"].get("load_estimate")
            )
        return [
            {
                "date": ride_date.isoformat(),
                "total_tss": round(total_tss, 1),
                "estimate": estimates[ride_date],
                "basis": "stored_ride_loads",
            }
            for ride_date, total_tss in sorted(totals.items())
        ]

    @classmethod
    def calculate_threshold_fitness_metrics(
        cls,
        rides: list[dict[str, Any]],
        *,
        threshold_w: int,
        target_date: Optional[date] = None,
        timezone_name: str | None = None,
    ) -> dict[str, Any]:
        """Exponential model over stored ride-day loads, with zero-load rest days."""
        target = target_date or date.today()
        first_date = cls._threshold_history_start(rides, target, timezone_name)
        daily = cls.threshold_daily_loads(
            rides,
            threshold_w=threshold_w,
            start_date=first_date,
            end_date=target,
            timezone_name=timezone_name,
        )
        loads = {
            date.fromisoformat(str(row["date"])): float(row["total_tss"])
            for row in daily
        }

        ctl = 0.0
        atl = 0.0
        ctl_by_date: dict[date, float] = {}
        ctl_decay = 1 - math.exp(-1 / cls.CTL_TIME_CONSTANT)
        atl_decay = 1 - math.exp(-1 / cls.ATL_TIME_CONSTANT)
        current = first_date
        while current <= target:
            day_tss = loads.get(current, 0.0)
            ctl += (day_tss - ctl) * ctl_decay
            atl += (day_tss - atl) * atl_decay
            ctl_by_date[current] = ctl
            current += timedelta(days=1)

        tsb = ctl - atl
        ramp_rate = ctl - ctl_by_date.get(target - timedelta(days=7), 0.0)
        return {
            "date": target.isoformat(),
            "ctl": round(ctl),
            "atl": round(atl),
            "tsb": round(ctl) - round(atl),
            "ramp_rate": round(ramp_rate, 1),
            "form": cls._get_form_status(round(ctl) - round(atl)),
        }

    @staticmethod
    def _threshold_history_start(
        rides: list[dict[str, Any]], target: date, timezone_name=None
    ) -> date:
        return min(
            (
                training_date(ride, timezone_name)
                for ride in rides
                if has_dated_load(ride) and training_date(ride, timezone_name) <= target
            ),
            default=target,
        )

    @classmethod
    def threshold_training_snapshot(
        cls,
        rides: list[dict[str, Any]],
        *,
        threshold_w: int,
        threshold: dict[str, Any],
        start_date: date,
        target_date: date,
        timezone_name: str | None = None,
        utc_offset_s: int | None = None,
    ) -> dict[str, Any]:
        """Bind FFF and the visible daily loads to one ride list and one date.

        ``rides`` must be the rider's full history through ``target_date``;
        the model starts at the first Threshold-eligible ride.
        """
        rides = [ride for ride in rides if is_training_eligible(ride)]
        history_start = cls._threshold_history_start(rides, target_date, timezone_name)
        history = cls.threshold_daily_loads(
            rides,
            threshold_w=threshold_w,
            start_date=history_start,
            end_date=target_date,
            timezone_name=timezone_name,
        )
        window = [row for row in history if row["date"] >= start_date.isoformat()]
        total_tss = sum(float(row["total_tss"]) for row in window)
        observed = sum(
            1
            for ride in rides
            if training_date(ride, timezone_name) <= target_date
            and has_dated_load(ride)
        )
        unavailable = [
            str(ride.get("id"))
            for ride in rides
            if training_date(ride, timezone_name) <= target_date
            and not has_dated_load(ride)
            and (
                ride.get("training_metrics") is not None
                or (ride.get("training_replay_state") or {}).get("error_class")
                or ("raw_file_path" in ride and not ride["raw_file_path"])
            )
        ]
        in_flight = sorted(
            str(ride.get("id"))
            for ride in rides
            if not has_dated_load(ride)
            and str(ride.get("id")) not in unavailable
            and training_date(ride, timezone_name) <= target_date
        )
        history_days = (target_date - history_start).days + 1
        revision = hashlib.sha256(
            json.dumps(
                {
                    "threshold_version": threshold["threshold_version"],
                    "as_of": target_date.isoformat(),
                    "history": history,
                    "timezone": timezone_name,
                    "utc_offset_s": utc_offset_s,
                    "scores": [
                        (r.get("id"), r.get("training_metrics"))
                        for r in sorted(rides, key=lambda r: str(r.get("id")))
                    ],
                    "in_flight": in_flight,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()[:16]
        fitness = cls.calculate_threshold_fitness_metrics(
            rides,
            threshold_w=threshold_w,
            target_date=target_date,
            timezone_name=timezone_name,
        )
        measured_fitness = cls.calculate_threshold_fitness_metrics(
            [
                r
                for r in rides
                if not (r.get("training_metrics") or {}).get("load_estimate")
            ],
            threshold_w=threshold_w,
            target_date=target_date,
            timezone_name=timezone_name,
        )
        # Preserve per-ride provenance forever. A snapshot marker describes
        # estimates that affect its visible window or displayed model precision.
        estimate = any(row["estimate"] for row in window) or fitness != measured_fitness
        return {
            "revision": revision,
            "as_of": datetime.combine(
                target_date,
                datetime.max.time(),
                tzinfo=(
                    ZoneInfo(timezone_name)
                    if timezone_name
                    else timezone(timedelta(seconds=utc_offset_s or 0))
                ),
            ).isoformat(),
            "estimate": estimate,
            "basis": "stored_ride_loads",
            "timezone": timezone_name,
            "utc_offset_s": utc_offset_s,
            "initialization": (
                "initialized"
                if observed and history_days >= cls.CTL_TIME_CONSTANT
                else "initializing"
            ),
            "coverage": {
                "completeness": "partial" if in_flight or unavailable else "complete",
                "population": (
                    f"{observed:,} / {observed + len(in_flight) + len(unavailable):,} rides"
                    if in_flight or unavailable
                    else f"{observed:,} {'ride' if observed == 1 else 'rides'}"
                ),
                "observed_count": observed,
                "expected_count": observed + len(in_flight) + len(unavailable),
                "pending_count": len(in_flight),
                "unavailable_count": len(unavailable),
            },
            "fitness_metrics": {
                **fitness,
                **threshold,
            },
            "training_load": {
                "daily_loads": window,
                "total_tss": total_tss,
                "avg_daily_tss": total_tss
                / max((target_date - start_date).days + 1, 1),
                **threshold,
            },
        }

    async def update_daily_aggregates(self, user_id: str, ride_date: date) -> None:
        """Recalculate daily aggregates and fitness forward from a ride date."""
        rides = await self.ride_repo.get_user_rides_for_date(user_id, ride_date)

        total_tss = sum(float(r.get("tss") or 0) for r in rides)
        total_duration = sum(int(r.get("duration_sec") or 0) for r in rides)
        total_distance = sum(float(r.get("distance_m") or 0) for r in rides)

        await self.fitness_repo.upsert_daily_training_load(
            user_id=user_id,
            load_date=ride_date,
            total_tss=total_tss,
            ride_count=len(rides),
            total_duration_sec=total_duration,
            total_distance_m=total_distance,
        )

        await self._recalculate_fitness_forward(user_id, ride_date)

    async def _recalculate_fitness_forward(self, user_id: str, from_date: date) -> None:
        """Recompute fitness metrics from a given date through today.

        Performance optimization: Cap recalculation to max 90 days.
        Old rides have negligible impact on current CTL/ATL due to exponential decay.
        """
        today = date.today()
        max_lookback = today - timedelta(days=90)

        # Don't recalculate ancient history - exponential decay makes it irrelevant
        start_date = max(from_date, max_lookback)
        current = start_date

        while current <= today:
            metrics = await self.calculate_fitness_metrics(user_id, current)
            await self.fitness_repo.upsert_fitness_metrics(
                user_id=user_id,
                metrics_date=current,
                ctl=metrics["ctl"],
                atl=metrics["atl"],
                tsb=metrics["tsb"],
                ramp_rate=metrics.get("ramp_rate"),
            )
            current += timedelta(days=1)


def normalize_to_date(value: Any, timezone_name: str | None = None) -> date:
    """Strict date parsing. A bad event date can never masquerade as today."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("invalid training date") from exc
    if not isinstance(value, datetime):
        raise ValueError("training date is required")
    if timezone_name:
        value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
        value = value.astimezone(ZoneInfo(timezone_name))
    return value.date()


def training_date(ride: dict, timezone_name: str | None = None) -> date:
    stored = (ride.get("training_metrics") or {}).get("local_date")
    if stored:
        return normalize_to_date(stored)
    # Legacy/unscored dates support coverage only. A scored ride with unknown
    # local_date is omitted from day loads until genuine zone evidence exists.
    return normalize_to_date(
        ride.get("started_at"), (ride.get("training_metrics") or {}).get("timezone")
    )
