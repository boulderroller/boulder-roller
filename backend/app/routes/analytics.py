from datetime import datetime, timedelta, timezone as utc_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, Field, model_validator, ValidationError
from typing import Optional, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..dependencies import (
    AuthenticatedUser,
    get_current_user,
    get_fitness_repository,
    get_ride_repository,
)
from ..repositories import FitnessRepository, RideRepository
from ..services.fitness_analytics import (
    FitnessAnalyticsService,
    training_date,
    has_dated_load,
)
from ..services.power_curve import THRESHOLD_ANCHORS_S
from ..services.training_eligibility import is_training_eligible
from ..services.riding_days import (
    aggregate_riding_days,
    aggregate_training_weeks,
    undated_count,
)
from ..middleware.rate_limiter import rate_limit

router = APIRouter()


async def get_analytics_service(
    fitness_repo: FitnessRepository = Depends(get_fitness_repository),
    ride_repo: RideRepository = Depends(get_ride_repository),
) -> FitnessAnalyticsService:
    return FitnessAnalyticsService(fitness_repo, ride_repo)


def _zone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise HTTPException(422, "invalid rider timezone") from exc
    return value


async def _rider_clock(repo, user_id, rides, client_zone=None):
    if isinstance(client_zone, str):
        _zone(client_zone)
    settings = await repo.training_settings(user_id)
    if settings.get("timezone"):
        zone = settings["timezone"]
        return zone, (
            "inferred" if settings.get("timezone_source") == "inferred" else "rider"
        )
    if isinstance(client_zone, str):
        return client_zone, "client"
    # A frozen geographic zone is the final owner-local fallback. Device
    # offsets and virtual map positions must not impersonate an outdoor zone.
    for ride in sorted(rides, key=lambda r: r["started_at"], reverse=True):
        if not is_training_eligible(ride):
            continue
        metrics = ride.get("training_metrics") or {}
        if (
            metrics.get("local_date")
            and metrics.get("timezone")
            and metrics.get("timezone_basis") == "start_position"
        ):
            return metrics["timezone"], "outdoor_ride"
    return "UTC", "utc_fallback"


async def _training_snapshot(repo, user_id, days, timezone_name=None):
    rides = await repo.list_threshold_training_rides(user_id)
    zone, basis = await _rider_clock(repo, user_id, rides, timezone_name)
    target = datetime.now(ZoneInfo(zone)).date()
    rides = [r for r in rides if is_training_eligible(r) and training_date(r, zone) <= target]
    scored = [r for r in rides if has_dated_load(r)]
    latest = await repo.current_training_threshold(user_id)
    metadata = {
        "threshold_state": (
            "estimated"
            if latest and latest.get("estimate")
            else "established" if latest else "establishing"
        ),
        "threshold_training_state": None,
        "threshold_version": "training.v2",
        "training_available": bool(scored),
        "training_threshold": latest,
    }
    snapshot = FitnessAnalyticsService.threshold_training_snapshot(
        rides,
        threshold_w=0,
        threshold=metadata,
        start_date=target - timedelta(days=days - 1),
        target_date=target,
        timezone_name=zone,
    )
    snapshot["clock"] = {"basis": basis, "fallback": basis == "utc_fallback"}
    return snapshot, metadata


@router.get("/fitness")
@rate_limit(category="analytics")
async def get_fitness_metrics(
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    analytics: FitnessAnalyticsService = Depends(get_analytics_service),
    ride_repo: RideRepository = Depends(get_ride_repository),
    timezone: Optional[str] = Query(None),
):
    try:
        snapshot, metadata = await _training_snapshot(
            ride_repo, current_user.user_id, 28, timezone
        )
        result = snapshot["fitness_metrics"]
        if not metadata["training_available"]:
            result = {**result, "ctl": None, "atl": None, "tsb": None, "form": None}
        return {
            **result,
            "estimate": snapshot["estimate"],
            "basis": snapshot["basis"],
            "clock": snapshot["clock"],
            "as_of": snapshot["as_of"],
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, {"code": "training_analytics_unavailable"}) from exc


@router.get("/training-load")
@rate_limit(category="analytics")
async def get_training_load(
    request: Request,
    days: int = Query(28, ge=1, le=365),
    current_user: AuthenticatedUser = Depends(get_current_user),
    ride_repo: RideRepository = Depends(get_ride_repository),
    timezone: Optional[str] = Query(None),
):
    try:
        snapshot, metadata = await _training_snapshot(
            ride_repo, current_user.user_id, days, timezone
        )
        return {
            **snapshot["training_load"],
            "snapshot": snapshot,
            "estimate": snapshot["estimate"],
            "basis": snapshot["basis"],
            **metadata,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, {"code": "training_analytics_unavailable"}) from exc


@router.get("/power-curve")
@rate_limit(category="analytics")
async def get_power_curve(
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    ride_repo: RideRepository = Depends(get_ride_repository),
):
    # Aggregate stored native curves. No stream read or second curve algorithm.
    rides = await ride_repo.list_threshold_training_rides(current_user.user_id)
    curves = [
        (r.get("training_metrics") or {})
        for r in rides
        if is_training_eligible(r) and r.get("training_metrics") is not None
        and datetime.fromisoformat(r["started_at"].replace("Z", "+00:00"))
        <= datetime.now(utc_timezone.utc)
    ]
    best = {}
    sampled = 0
    for metrics in curves:
        if metrics.get("power_curve_w"):
            sampled += 1
        for seconds, watts in zip(
            metrics.get("power_curve_s", []), metrics.get("power_curve_w") or []
        ):
            if watts is not None:
                best[seconds] = max(watts, best.get(seconds, 0))
    durations = sorted(
        {s for metrics in curves for s in metrics.get("power_curve_s", [])}
    )

    threshold = await ride_repo.current_training_threshold(current_user.user_id)
    return {
        "contractVersion": "power_curve.v1",
        "durationsS": durations,
        "bestW": [best.get(s) for s in durations],
        "sampledRides": sampled,
        "rideCount": len(curves),
        "available": bool(best),
        "threshold": {
            "sealedW": (
                threshold["value"] if threshold and not threshold["estimate"] else None
            ),
            "candidateW": None,
            "estimate": threshold,
            "anchorsW": {str(s): best.get(s) for s in THRESHOLD_ANCHORS_S},
        },
    }


class TrainingSettings(BaseModel):
    timezone: str | None = None
    threshold_hr_bpm: int | None = Field(default=None, gt=60, lt=255)
    resting_hr_bpm: int | None = Field(default=None, ge=20, le=120)
    max_hr_bpm: int | None = Field(default=None, gt=60, lt=255)
    sex: str | None = None
    hr_zone_tops_bpm: list[int] | None = None

    @model_validator(mode="after")
    def valid(self):
        if self.timezone:
            _zone(self.timezone)
        if self.sex not in (None, "female", "male"):
            raise ValueError("invalid sex")
        if self.hr_zone_tops_bpm is not None and (
            not self.hr_zone_tops_bpm
            or any(v < 20 or v >= 255 for v in self.hr_zone_tops_bpm)
            or any(
                a >= b for a, b in zip(self.hr_zone_tops_bpm, self.hr_zone_tops_bpm[1:])
            )
        ):
            raise ValueError("invalid HR zone tops")
        if (
            self.max_hr_bpm
            and self.threshold_hr_bpm
            and self.threshold_hr_bpm > self.max_hr_bpm
        ):
            raise ValueError("threshold HR exceeds max HR")
        if self.resting_hr_bpm and any(
            v and v <= self.resting_hr_bpm
            for v in (self.threshold_hr_bpm, self.max_hr_bpm)
        ):
            raise ValueError("resting HR must be below exercise HR")
        return self


@router.get("/settings")
async def get_training_settings(
    current_user: AuthenticatedUser = Depends(get_current_user),
    ride_repo: RideRepository = Depends(get_ride_repository),
):
    return await ride_repo.training_settings(current_user.user_id)


class TrainingTimezone(BaseModel):
    timezone: str


@router.post("/timezone")
@rate_limit(category="analytics")
async def initialize_training_timezone(
    request: Request,
    preference: TrainingTimezone,
    current_user: AuthenticatedUser = Depends(get_current_user),
    ride_repo: RideRepository = Depends(get_ride_repository),
):
    _zone(preference.timezone)
    return await ride_repo.initialize_training_timezone(
        current_user.user_id, preference.timezone
    )


@router.put("/settings")
@rate_limit(category="analytics")
async def set_training_settings(
    request: Request,
    settings: TrainingSettings,
    current_user: AuthenticatedUser = Depends(get_current_user),
    ride_repo: RideRepository = Depends(get_ride_repository),
):
    # Settings are effective forward from receipt; existing scored rides keep their snapshot.
    previous = await ride_repo.training_settings(current_user.user_id)
    patch = settings.model_dump(exclude_unset=True)
    merged = {
        key: value for key, value in {**previous, **patch}.items() if value is not None
    }
    try:
        TrainingSettings.model_validate(merged)
    except ValidationError as exc:
        raise HTTPException(422, "invalid training settings") from exc
    return await ride_repo.append_training_settings(current_user.user_id, patch)


@router.get("/riding-days")
@rate_limit(category="analytics")
async def get_riding_days(
    request: Request,
    days: int = Query(182, ge=7, le=371),
    timezone: Optional[str] = Query(None),
    current_user: AuthenticatedUser = Depends(get_current_user),
    ride_repo: RideRepository = Depends(get_ride_repository),
):
    """Moving time + ride count per day for the consistency heatmap.

    Not Threshold-bound: riding time exists for every ride, so the rhythm
    view never blanks while a Threshold is establishing.
    """
    if isinstance(timezone, str):
        _zone(timezone)
    try:
        rides = await ride_repo.list_threshold_training_rides(current_user.user_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "riding_days_unavailable"},
        ) from exc
    zone, basis = await _rider_clock(ride_repo, current_user.user_id, rides, timezone)
    end_date = datetime.now(ZoneInfo(zone)).date()
    start_date = end_date - timedelta(days=days - 1)
    result = {
        "contractVersion": "riding_days.v1",
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "clock": {"basis": basis, "fallback": basis == "utc_fallback"},
        "undated_count": undated_count(rides, start_date, end_date),
        "days": aggregate_riding_days(
            rides, start_date=start_date, end_date=end_date, timezone_name=timezone
        ),
    }
    return result


@router.get("/weeks")
@rate_limit(category="analytics")
async def get_training_weeks(
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    ride_repo: RideRepository = Depends(get_ride_repository),
    timezone: Optional[str] = Query(None),
):
    rides = await ride_repo.list_threshold_training_rides(current_user.user_id)
    zone, basis = await _rider_clock(ride_repo, current_user.user_id, rides, timezone)
    today = datetime.now(ZoneInfo(zone)).date()
    return [
        dict(row, clock={"basis": basis, "fallback": basis == "utc_fallback"})
        for row in aggregate_training_weeks(rides, end_date=today)
    ]
