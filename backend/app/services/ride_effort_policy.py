"""Ride effort and economy policy.

This module keeps estimated effort separate from reward-grade value. GPS-only
rides can still produce route and climb discovery truth, but only rides with
reward-grade effort evidence can mint/credit/tribute CAL automatically.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Optional


from .ride_effort_trim import total_seconds

# Ride metadata stores whole-token display values, while on-chain crediting
# uses SPL base units for the CAL mint.
CAL_DECIMALS_MULTIPLIER = 1_000_000_000

AUTHORITATIVE_METRICS_VERSION = "workout_parse_metrics_v1"
RIDE_EFFORT_POLICY_VERSION = "ride_effort_policy_2026_07_14_ftp_v1"
MIN_POWER_SAMPLE_COUNT = 30
MIN_POWER_SAMPLE_COVERAGE_BPS = 5_000
MIN_POWER_MOVING_TIME_SECONDS = 30

EFFORT_EVIDENCE_MANUAL_REVIEW = "manual_review"
EFFORT_EVIDENCE_POWER_VERIFIED = "power_verified"
EFFORT_EVIDENCE_ROUTE_ONLY = "route_only"
EFFORT_EVIDENCE_SENSOR_SUPPORTED = "sensor_supported"

REWARD_POLICY_ESTIMATED_ONLY = "estimated_only"
REWARD_POLICY_MANUAL_REVIEW = "manual_review"
REWARD_POLICY_NOT_COUNTED = "not_counted"
REWARD_POLICY_REWARDABLE = "rewardable"

# Tim copy slots S1 and S2. Empty slots render nothing.
PARTLY_COUNTED_COPY = ""
ALREADY_COUNTED_COPY = ""

ROUTE_ESTIMATE_ECONOMIC_REVIEW_REASON = "effort_source_route_estimate_only"
NON_AUTHORITATIVE_METRICS_REVIEW_REASON = "non_authoritative_effort_metrics"
INSUFFICIENT_POWER_COVERAGE_REVIEW_REASON = "insufficient_power_sensor_coverage"
HEART_RATE_THRESHOLD_REVIEW_REASON = "heart_rate_effort_requires_trusted_threshold"
PRE_ECONOMY_REVIEW_REASON = "activity_before_economy_start"
FUTURE_ACTIVITY_REVIEW_REASON = "activity_completed_in_future"
STALE_ACTIVITY_REVIEW_REASON = "activity_too_old_for_automatic_economics"
INVALID_ACTIVITY_DURATION_REVIEW_REASON = "invalid_activity_duration"
MISSING_ACTIVITY_TIMESTAMP_REVIEW_REASON = "missing_activity_timestamp"
ECONOMY_START_UNIX_SECONDS = 1_704_020_400
ECONOMY_START_AT = datetime.fromtimestamp(ECONOMY_START_UNIX_SECONDS, tz=timezone.utc)
MAX_ACTIVITY_CLOCK_SKEW_SECONDS = 10 * 60
MAX_ACTIVITY_AGE_SECONDS = 30 * 24 * 60 * 60
MAX_ACTIVITY_DURATION_SECONDS = 36 * 60 * 60


def _source_value(source: Any, name: str) -> Any:
    return source.get(name) if isinstance(source, dict) else getattr(source, name, None)


def _calculate_cal_amounts(tss: float) -> tuple[int, int]:
    """Return (display_units, base_units) derived from TSS."""
    if tss <= 0:
        return 0, 0
    display_units = int(tss)
    # TSS is persisted as a decimal authority. Converting through the binary
    # float product can undercount an otherwise exact tenth (for example,
    # 64.1) by one base unit and then conflict with the NUMERIC SQL freeze.
    base_units = int(Decimal(str(tss)) * CAL_DECIMALS_MULTIPLIER)
    return display_units, base_units


def _metric_value(source: Any, name: str) -> Optional[float]:
    value = _source_value(source, name)
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def _numeric_value(source: Any, name: str) -> Optional[float]:
    value = _source_value(source, name)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _has_power_sensor(metrics: Any) -> bool:
    sample_count = _numeric_value(metrics, "power_sample_count") or 0
    return sample_count > 0 or any(
        _numeric_value(metrics, name) is not None
        for name in ("avg_power_w", "max_power_w", "normalized_power_w")
    )


def _has_heart_rate_backed_effort(metrics: Any) -> bool:
    sample_count = _numeric_value(metrics, "heart_rate_sample_count") or 0
    return sample_count > 0 or _metric_value(metrics, "avg_hr_bpm") is not None


def _has_sensor_backed_effort(metrics: Any) -> bool:
    """Return true when TSS came from an effort sensor, not route shape alone."""
    return _has_power_sensor(metrics) or _has_heart_rate_backed_effort(metrics)


def _has_reward_grade_power(metrics: Any) -> bool:
    return (
        _source_value(metrics, "metrics_version") == AUTHORITATIVE_METRICS_VERSION
        and (_numeric_value(metrics, "power_sample_count") or 0)
        >= MIN_POWER_SAMPLE_COUNT
        and (_numeric_value(metrics, "power_sample_coverage_bps") or 0)
        >= MIN_POWER_SAMPLE_COVERAGE_BPS
        and (_numeric_value(metrics, "moving_time_sec") or 0)
        >= MIN_POWER_MOVING_TIME_SECONDS
        and _metric_value(metrics, "normalized_power_w") is not None
    )


def classify_effort_evidence_tier(metrics: Any) -> str:
    """Classify the best available effort evidence for a ride."""
    if _has_reward_grade_power(metrics):
        return EFFORT_EVIDENCE_POWER_VERIFIED
    if _has_sensor_backed_effort(metrics):
        return EFFORT_EVIDENCE_SENSOR_SUPPORTED
    return EFFORT_EVIDENCE_ROUTE_ONLY


def _economic_review_reason_for_metrics(metrics: Any) -> Optional[str]:
    tss = _metric_value(metrics, "tss")

    if _has_power_sensor(metrics):
        if _source_value(metrics, "metrics_version") != AUTHORITATIVE_METRICS_VERSION:
            return NON_AUTHORITATIVE_METRICS_REVIEW_REASON
        if not _has_reward_grade_power(metrics):
            normalized_power = _numeric_value(metrics, "normalized_power_w")
            if normalized_power == 0 and tss is None:
                return None
            return INSUFFICIENT_POWER_COVERAGE_REVIEW_REASON
        return None

    if _has_heart_rate_backed_effort(metrics):
        return HEART_RATE_THRESHOLD_REVIEW_REASON

    if tss is not None:
        return ROUTE_ESTIMATE_ECONOMIC_REVIEW_REASON
    return None


def _datetime_from_value(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        if value <= 0:
            return None
        seconds = value / 1000 if value > 10_000_000_000 else value
        try:
            dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _completed_at_from_source(metrics: Any, completed_at: Any = None) -> Optional[datetime]:
    if completed_at is not None:
        return _datetime_from_value(completed_at)
    for name in ("completed_at", "completedAt", "ended_at", "endedAt"):
        parsed = _datetime_from_value(_source_value(metrics, name))
        if parsed is not None:
            return parsed
    return None


def _started_at_from_source(metrics: Any, started_at: Any = None) -> Optional[datetime]:
    if started_at is not None:
        return _datetime_from_value(started_at)
    for name in ("started_at", "startedAt", "start_time", "startTime"):
        parsed = _datetime_from_value(_source_value(metrics, name))
        if parsed is not None:
            return parsed
    return None


def _duration_seconds_from_source(metrics: Any) -> Optional[float]:
    for name in ("duration_sec", "duration_s", "durationSec", "durationS"):
        value = _source_value(metrics, name)
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        return parsed
    return None


def is_pre_economy_activity(completed_at: Any) -> bool:
    """Return true when an activity completed before live economics existed."""
    parsed = _datetime_from_value(completed_at)
    return parsed is not None and parsed < ECONOMY_START_AT


def _activity_time_review_reason(
    metrics: Any,
    *,
    completed_at: Any = None,
    started_at: Any = None,
    now: Any = None,
) -> Optional[str]:
    completed = _completed_at_from_source(metrics, completed_at)
    if completed is None:
        return MISSING_ACTIVITY_TIMESTAMP_REVIEW_REASON
    if completed < ECONOMY_START_AT:
        return PRE_ECONOMY_REVIEW_REASON

    current_time = _datetime_from_value(now) or datetime.now(timezone.utc)
    if completed > current_time + timedelta(seconds=MAX_ACTIVITY_CLOCK_SKEW_SECONDS):
        return FUTURE_ACTIVITY_REVIEW_REASON
    if completed < current_time - timedelta(seconds=MAX_ACTIVITY_AGE_SECONDS):
        return STALE_ACTIVITY_REVIEW_REASON

    started = _started_at_from_source(metrics, started_at)
    if started is not None:
        duration_s = (completed - started).total_seconds()
        if duration_s <= 0 or duration_s > MAX_ACTIVITY_DURATION_SECONDS:
            return INVALID_ACTIVITY_DURATION_REVIEW_REASON

    metric_duration_s = _duration_seconds_from_source(metrics)
    if (
        metric_duration_s is not None
        and (metric_duration_s <= 0 or metric_duration_s > MAX_ACTIVITY_DURATION_SECONDS)
    ):
        return INVALID_ACTIVITY_DURATION_REVIEW_REASON

    return None


@dataclass(frozen=True)
class RideEffortPolicy:
    """Computed ride-level policy for estimated, rewardable, and tributable CAL."""

    effort_evidence_tier: str
    reward_policy: str
    estimated_cal: int
    rewardable_cal: int
    tributable_cal: int
    estimated_cal_base_units: int = 0
    rewardable_cal_base_units: int = 0
    tributable_cal_base_units: int = 0
    review_reason: Optional[str] = None

    @property
    def requires_economic_review(self) -> bool:
        return self.reward_policy in {
            REWARD_POLICY_ESTIMATED_ONLY,
            REWARD_POLICY_MANUAL_REVIEW,
        }

    @property
    def is_rewardable(self) -> bool:
        return self.rewardable_cal > 0 and self.rewardable_cal_base_units > 0

    @property
    def is_tributable(self) -> bool:
        return self.tributable_cal > 0 and self.tributable_cal_base_units > 0

    def as_ride_fields(self) -> Dict[str, Any]:
        """Fields persisted on rides so clients and later phases stop guessing."""
        return {
            "effort_evidence_tier": self.effort_evidence_tier,
            "reward_policy": self.reward_policy,
            "estimated_cal": self.estimated_cal,
            "rewardable_cal": self.rewardable_cal,
            "tributable_cal": self.tributable_cal,
        }


def build_ride_effort_policy(
    metrics: Any,
    *,
    blocking_review_reason: Optional[str] = None,
    completed_at: Any = None,
    started_at: Any = None,
    now: Any = None,
) -> RideEffortPolicy:
    """Build one policy object from ride metrics plus any blocking review reason."""
    estimated_cal, estimated_cal_base_units = _calculate_cal_amounts(
        float(_metric_value(metrics, "tss") or 0)
    )

    if blocking_review_reason:
        return RideEffortPolicy(
            effort_evidence_tier=EFFORT_EVIDENCE_MANUAL_REVIEW,
            reward_policy=REWARD_POLICY_MANUAL_REVIEW,
            estimated_cal=estimated_cal,
            rewardable_cal=0,
            tributable_cal=0,
            estimated_cal_base_units=estimated_cal_base_units,
            review_reason=blocking_review_reason,
        )

    time_review_reason = _activity_time_review_reason(
        metrics,
        completed_at=completed_at,
        started_at=started_at,
        now=now,
    )
    if time_review_reason:
        return RideEffortPolicy(
            effort_evidence_tier=EFFORT_EVIDENCE_MANUAL_REVIEW,
            reward_policy=REWARD_POLICY_MANUAL_REVIEW,
            estimated_cal=estimated_cal,
            rewardable_cal=0,
            tributable_cal=0,
            estimated_cal_base_units=estimated_cal_base_units,
            review_reason=time_review_reason,
        )

    effort_review_reason = _economic_review_reason_for_metrics(metrics)
    effort_evidence_tier = classify_effort_evidence_tier(metrics)
    if effort_review_reason:
        return RideEffortPolicy(
            effort_evidence_tier=effort_evidence_tier,
            reward_policy=REWARD_POLICY_ESTIMATED_ONLY,
            estimated_cal=estimated_cal,
            rewardable_cal=0,
            tributable_cal=0,
            estimated_cal_base_units=estimated_cal_base_units,
            review_reason=effort_review_reason,
        )

    if estimated_cal <= 0:
        return RideEffortPolicy(
            effort_evidence_tier=effort_evidence_tier,
            reward_policy=REWARD_POLICY_NOT_COUNTED,
            estimated_cal=0,
            rewardable_cal=0,
            tributable_cal=0,
            estimated_cal_base_units=0,
        )

    return RideEffortPolicy(
        effort_evidence_tier=effort_evidence_tier,
        reward_policy=REWARD_POLICY_REWARDABLE,
        estimated_cal=estimated_cal,
        rewardable_cal=estimated_cal,
        tributable_cal=estimated_cal,
        estimated_cal_base_units=estimated_cal_base_units,
        rewardable_cal_base_units=estimated_cal_base_units,
        tributable_cal_base_units=estimated_cal_base_units,
    )


def _calculate_economic_cal_amounts(metrics: Any) -> tuple[int, int, Optional[str]]:
    """Backward-compatible tuple for older tests/callers.

    Returns (rewardable_display_cal, rewardable_base_units, review_reason).
    New code should prefer ``build_ride_effort_policy``.
    """
    policy = build_ride_effort_policy(metrics)
    return policy.rewardable_cal, policy.rewardable_cal_base_units, policy.review_reason


def build_paid_effort_policy(file_policy, trim, *, started_at, completed_at):
    if not file_policy.is_rewardable:
        trim.clear_claim()
        return file_policy
    if trim.paid_ms == trim.effort_ms:
        return file_policy
    metrics = trim.paid_metrics
    if (
        not trim.paid_ms
        or total_seconds(trim.paid_ms) < 30
        or metrics is None
        or metrics.power_sample_count < 30
    ):
        trim.clear_claim()
        return replace(
            file_policy,
            reward_policy=REWARD_POLICY_NOT_COUNTED,
            review_reason=None,
            estimated_cal=0,
            estimated_cal_base_units=0,
            rewardable_cal=0,
            rewardable_cal_base_units=0,
            tributable_cal=0,
            tributable_cal_base_units=0,
        )
    if trim.frozen:
        display, exact = _calculate_cal_amounts(metrics.tss)
        return replace(
            file_policy,
            estimated_cal=display,
            estimated_cal_base_units=exact,
            rewardable_cal=display,
            rewardable_cal_base_units=exact,
            tributable_cal=display,
            tributable_cal_base_units=exact,
        )
    paid = build_ride_effort_policy(
        metrics, started_at=started_at, completed_at=completed_at
    )
    if not paid.is_rewardable:
        trim.clear_claim()
    return paid
