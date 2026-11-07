"""Derived Threshold evidence and promotion policy.

The rider-facing product calls this Threshold. Internal reward-FTP fields stay
for historical snapshot compatibility; no declared profile value enters this
module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from typing import Any, Literal, Mapping, Optional

from .reward_ftp import (
    MAX_REWARD_FTP_W,
    MIN_REWARD_FTP_W,
    NETWORK_DEFAULT_REWARD_FTP_SOURCE,
    RewardFtpSnapshot,
)
from .ride_effort_policy import RideEffortPolicy, build_ride_effort_policy


THRESHOLD_MODEL_VERSION = "threshold_cp_3_7_15_v1"
THRESHOLD_CANDIDATE_REVIEW_DISPOSITIONS = frozenset(
    {"invalid_fit_review", "below_bounds_review", "above_bounds_review"}
)
HELD_RIDE_ELIGIBILITY_WINDOW = timedelta(weeks=16)
THRESHOLD_PROVISIONAL_HOLD_POLICY = "threshold_provisional_hold_v1"


@dataclass(frozen=True)
class ThresholdPendingMonday:
    promotion_id: str
    watts: int
    effective_at: datetime


@dataclass(frozen=True)
class ThresholdTrainingDenominator:
    watts: int
    kind: Literal["network_placeholder", "sealed", "pending"]
    provisional: bool


@dataclass(frozen=True)
class ThresholdRiderProjection:
    state: Literal["establishing", "established"]
    current_w: Optional[int]
    established_at: Optional[datetime]
    last_raised_at: Optional[datetime]
    pending_monday: Optional[ThresholdPendingMonday]
    training_denominator: ThresholdTrainingDenominator
    sealing_in_progress: bool


def _projection_datetime(value: Any, *, field: str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO timestamp") from exc
    return _required_policy_datetime(value, field=field)


def _projection_watts(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    try:
        watts = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc
    if watts != value and not (
        isinstance(value, str) and str(watts) == value.strip()
    ):
        raise ValueError(f"{field} must be an exact integer")
    if not MIN_REWARD_FTP_W <= watts <= MAX_REWARD_FTP_W:
        raise ValueError(f"{field} is outside Threshold bounds")
    return watts


def project_threshold_training_tss(
    ride: Mapping[str, Any],
    *,
    threshold_w: int,
) -> Optional[float]:
    """Reproject a provenance-bound ride to the active training denominator."""
    watts = _projection_watts(threshold_w, field="training Threshold")
    if ride.get("threshold_training_kind") not in {"sealed", "pending"}:
        return None

    normalized = ride.get("normalized_power_raw_w")
    if normalized is None:
        normalized = ride.get("normalized_power_w")
    if normalized is not None:
        try:
            duration_s = float(ride.get("normalized_power_duration_s"))
            normalized_w = float(normalized)
        except (TypeError, ValueError):
            return None
        if not (
            math.isfinite(duration_s)
            and math.isfinite(normalized_w)
            and duration_s > 0
            and normalized_w > 0
        ):
            return None
        return round(
            duration_s * normalized_w * normalized_w / (watts * watts * 36),
            1,
        )

    try:
        stored_tss = float(ride.get("tss"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(stored_tss) or stored_tss < 0:
        return None
    return round(stored_tss, 1)


def parse_threshold_rider_projection(
    payload: Mapping[str, Any],
    *,
    as_of: Optional[datetime] = None,
) -> ThresholdRiderProjection:
    """Validate the private read model and preserve sealed truth at seal time."""
    if not isinstance(payload, Mapping):
        raise ValueError("Threshold authority returned no projection")
    now = _required_policy_datetime(
        as_of or datetime.now(timezone.utc), field="as_of"
    )
    state = payload.get("state")
    if state not in {"establishing", "established"}:
        raise ValueError("Threshold projection has an invalid state")

    sealing_raw = payload.get("sealing_in_progress", False)
    if not isinstance(sealing_raw, bool):
        raise ValueError("Threshold sealing state must be a boolean")
    sealing_in_progress = sealing_raw

    current_raw = payload.get("current_w")
    current_w = (
        None
        if current_raw is None
        else _projection_watts(current_raw, field="current Threshold")
    )
    established_at = (
        None
        if payload.get("established_at") is None
        else _projection_datetime(payload.get("established_at"), field="established_at")
    )
    last_raised_at = (
        None
        if payload.get("last_raised_at") is None
        else _projection_datetime(payload.get("last_raised_at"), field="last_raised_at")
    )

    pending_raw = payload.get("pending_monday")
    pending: Optional[ThresholdPendingMonday] = None
    suppress_expired_pending = False
    if pending_raw is not None:
        if not isinstance(pending_raw, Mapping):
            raise ValueError("pending Monday must be an object")
        parsed_pending = ThresholdPendingMonday(
            promotion_id=str(pending_raw.get("promotion_id") or ""),
            watts=_projection_watts(
                pending_raw.get("watts"), field="pending Threshold"
            ),
            effective_at=_projection_datetime(
                pending_raw.get("effective_at"), field="pending effective_at"
            ),
        )
        if not parsed_pending.promotion_id:
            raise ValueError("pending Monday lacks its promotion authority")
        if parsed_pending.effective_at <= now:
            # Old caches can cross the seal boundary. Keep the sealed Current
            # value, suppress the expired candidate, and poll for the seal.
            suppress_expired_pending = True
            sealing_in_progress = True
        else:
            pending = parsed_pending

    denominator_raw = payload.get("training_denominator")
    if not isinstance(denominator_raw, Mapping):
        raise ValueError("Threshold projection lacks its training denominator")
    denominator_kind = denominator_raw.get("kind")
    if denominator_kind not in {"network_placeholder", "sealed", "pending"}:
        raise ValueError("Threshold projection has an invalid denominator kind")
    denominator = ThresholdTrainingDenominator(
        watts=_projection_watts(
            denominator_raw.get("watts"), field="training watts"
        ),
        kind=denominator_kind,
        provisional=bool(denominator_raw.get("provisional")),
    )
    if suppress_expired_pending:
        if state != "established" or current_w is None:
            raise ValueError("expired pending Threshold lacks sealed authority")
        denominator = ThresholdTrainingDenominator(
            watts=current_w,
            kind="sealed",
            provisional=False,
        )

    if state == "establishing":
        if any(
            value is not None
            for value in (current_w, established_at, last_raised_at, pending)
        ):
            raise ValueError("Establishing cannot expose a Threshold value")
        if (
            denominator.kind != "network_placeholder"
            or denominator.watts != 200
            or not denominator.provisional
        ):
            raise ValueError(
                "Establishing requires the non-paying network placeholder"
            )
    else:
        if current_w is None or established_at is None:
            raise ValueError("Established Threshold lacks sealed authority")
        if established_at > now or (
            last_raised_at is not None and last_raised_at <= established_at
        ):
            raise ValueError("Established Threshold timestamps are inconsistent")
        if pending is None:
            if (
                denominator.kind != "sealed"
                or denominator.watts != current_w
                or denominator.provisional
            ):
                raise ValueError(
                    "Sealed denominator disagrees with Threshold authority"
                )
        else:
            if pending.watts <= current_w:
                raise ValueError("Pending Monday must raise the sealed Threshold")
            if (
                denominator.kind != "pending"
                or denominator.watts != pending.watts
                or not denominator.provisional
            ):
                raise ValueError(
                    "Pending denominator disagrees with scheduled promotion"
                )

    return ThresholdRiderProjection(
        state=state,
        current_w=current_w,
        established_at=established_at,
        last_raised_at=last_raised_at,
        pending_monday=pending,
        training_denominator=denominator,
        sealing_in_progress=sealing_in_progress,
    )


@dataclass(frozen=True)
class ThresholdSourceEvidence:
    recording_source: Optional[str]
    power_source_ids: tuple[str, ...]
    identity_complete: bool
    eligibility_reason: str

    @property
    def economic_eligible(self) -> bool:
        return self.eligibility_reason == "eligible"

    def as_ride_fields(self) -> dict[str, Any]:
        return {
            "threshold_recording_source": self.recording_source,
            "threshold_power_source_id": (
                self.power_source_ids[0]
                if self.economic_eligible and len(self.power_source_ids) == 1
                else None
            ),
            "threshold_source_identity_complete": self.identity_complete,
            "threshold_source_evidence": {
                "recording_source": self.recording_source,
                "power_source_ids": list(self.power_source_ids),
                "identity_complete": self.identity_complete,
                "eligibility_reason": self.eligibility_reason,
            },
        }


@dataclass(frozen=True)
class ThresholdEffortEvidence:
    best_180s_w: Optional[float]
    best_420s_w: Optional[float]
    best_900s_w: Optional[float]
    source: ThresholdSourceEvidence

    def rpc_payload(self, ride_id: Any) -> dict[str, Any]:
        return {
            "p_ride_id": str(ride_id),
            "p_best_180s_w": self.best_180s_w,
            "p_best_420s_w": self.best_420s_w,
            "p_best_900s_w": self.best_900s_w,
        }


@dataclass(frozen=True)
class HeldRideReleasePolicy:
    """Pure release decision for an upload-admitted provisional ride."""

    disposition: str
    reward_ftp_w: int
    reward_ftp_source: str
    reward_ftp_authority_id: Optional[str]
    reward_ftp_policy_version: str
    economic_tss: float
    exact_cal_base_units: int
    exact_tribute_budget_base_units: int
    review_reason: Optional[str] = None


def _validated_reward_ftp_snapshot(snapshot: RewardFtpSnapshot) -> RewardFtpSnapshot:
    if not isinstance(snapshot, RewardFtpSnapshot):
        raise ValueError("reward FTP snapshot is required")
    return RewardFtpSnapshot.from_row(
        {
            "reward_ftp_w": snapshot.ftp_w,
            "reward_ftp_source": snapshot.source,
            "reward_ftp_authority_id": snapshot.authority_id,
            "reward_ftp_policy_version": snapshot.policy_version,
        }
    )


def _required_policy_datetime(value: Any, *, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{field} must be a timezone-aware datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def requires_threshold_hold(snapshot: RewardFtpSnapshot) -> bool:
    """Return true only for the non-paying network display placeholder."""
    authority = _validated_reward_ftp_snapshot(snapshot)
    return authority.source == NETWORK_DEFAULT_REWARD_FTP_SOURCE


def project_threshold_hold_policy(
    policy: RideEffortPolicy,
    snapshot: RewardFtpSnapshot,
) -> RideEffortPolicy:
    """Keep provisional value estimated while exposing zero counted economics."""
    if not requires_threshold_hold(snapshot) or not policy.is_rewardable:
        return policy
    return RideEffortPolicy(
        effort_evidence_tier=policy.effort_evidence_tier,
        reward_policy=THRESHOLD_PROVISIONAL_HOLD_POLICY,
        estimated_cal=policy.estimated_cal,
        rewardable_cal=0,
        tributable_cal=0,
        estimated_cal_base_units=policy.estimated_cal_base_units,
        rewardable_cal_base_units=0,
        tributable_cal_base_units=0,
    )


def build_held_ride_release_policy(
    metrics: Any,
    *,
    admitted_at: datetime,
    established_at: datetime,
    established_threshold: RewardFtpSnapshot,
) -> HeldRideReleasePolicy:
    """Bind an eligible held ride to its first established Threshold."""
    admitted = _required_policy_datetime(admitted_at, field="admitted_at")
    established = _required_policy_datetime(established_at, field="established_at")
    threshold = _validated_reward_ftp_snapshot(established_threshold)
    if threshold.source != "derived_eftp" or threshold.authority_id is None:
        raise ValueError("release requires an established derived Threshold authority")

    shared = {
        "reward_ftp_w": threshold.ftp_w,
        "reward_ftp_source": threshold.source,
        "reward_ftp_authority_id": threshold.authority_id,
        "reward_ftp_policy_version": threshold.policy_version,
    }
    held_for = max(established - admitted, timedelta(0))
    if held_for > HELD_RIDE_ELIGIBILITY_WINDOW:
        return HeldRideReleasePolicy(
            disposition="lapsed",
            economic_tss=0.0,
            exact_cal_base_units=0,
            exact_tribute_budget_base_units=0,
            **shared,
        )

    effort = build_ride_effort_policy(metrics, now=admitted)
    try:
        economic_tss = float(
            metrics.get("tss") if isinstance(metrics, Mapping) else metrics.tss
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("authoritative release metrics require numeric TSS") from exc
    if not math.isfinite(economic_tss) or economic_tss < 0:
        raise ValueError("authoritative release metrics require finite nonnegative TSS")

    if effort.requires_economic_review:
        return HeldRideReleasePolicy(
            disposition="review",
            economic_tss=economic_tss,
            exact_cal_base_units=0,
            exact_tribute_budget_base_units=0,
            review_reason=effort.review_reason,
            **shared,
        )
    if not effort.is_rewardable:
        return HeldRideReleasePolicy(
            disposition="not_counted",
            economic_tss=economic_tss,
            exact_cal_base_units=0,
            exact_tribute_budget_base_units=0,
            review_reason=effort.review_reason,
            **shared,
        )

    exact_cal = effort.rewardable_cal_base_units
    return HeldRideReleasePolicy(
        disposition="release",
        economic_tss=economic_tss,
        exact_cal_base_units=exact_cal,
        # The release planner derives this from the frozen climb windows once
        # the rider's immutable Threshold is available.
        exact_tribute_budget_base_units=0,
        **shared,
    )


def threshold_source_evidence(parsed_ride: Any) -> ThresholdSourceEvidence:
    """Classify the strict structural source evidence attached by the GPX sidecar."""
    recording_source = getattr(parsed_ride, "threshold_recording_source", None)
    raw_ids = getattr(parsed_ride, "threshold_power_source_ids", ()) or ()
    source_ids = tuple(sorted({str(value) for value in raw_ids if value}))
    identity_complete = bool(
        getattr(parsed_ride, "threshold_source_identity_complete", False)
    )
    identity_error = getattr(parsed_ride, "threshold_source_identity_error", None)

    if recording_source != "br_ios":
        reason = "not_br_ios_recording"
    elif identity_error == "invalid_power_source_identity":
        reason = "invalid_power_source_identity"
    elif not source_ids or not identity_complete:
        reason = "missing_power_source_identity"
    elif len(source_ids) != 1:
        reason = "mixed_power_source_identity"
    else:
        reason = "eligible"
    return ThresholdSourceEvidence(
        recording_source=recording_source,
        power_source_ids=source_ids,
        identity_complete=identity_complete,
        eligibility_reason=reason,
    )


def threshold_effort_evidence(parsed_ride: Any) -> ThresholdEffortEvidence:
    """Read canonical mean-max anchors from the retained workout-parse activity."""
    native_activity = getattr(parsed_ride, "_native_activity", None)
    if native_activity is None:
        raise ValueError("Threshold anchors require the native workout_parse activity")

    from .workout_parse_adapter import _get_workout_parse

    workout_parse = _get_workout_parse()
    compute = getattr(workout_parse, "compute_threshold_power_anchors", None)
    if compute is None:
        raise RuntimeError(
            "workout_parse lacks the ratified 3/7/15-minute Threshold anchors"
        )
    raw = compute(native_activity)
    anchors = dict(raw or {})

    def optional_anchor(duration_s: int) -> Optional[float]:
        value = anchors.get(str(duration_s), anchors.get(duration_s))
        if value is None:
            return None
        numeric = float(value)
        return numeric if math.isfinite(numeric) and numeric >= 0 else None

    return ThresholdEffortEvidence(
        best_180s_w=optional_anchor(180),
        best_420s_w=optional_anchor(420),
        best_900s_w=optional_anchor(900),
        source=threshold_source_evidence(parsed_ride),
    )


def threshold_effort_evidence_or_empty(
    parsed_ride: Any,
) -> ThresholdEffortEvidence:
    """Abstain without consuming immutable evidence when anchors are unavailable."""
    source = threshold_source_evidence(parsed_ride)
    native_activity = getattr(parsed_ride, "_native_activity", None)
    if native_activity is None:
        return ThresholdEffortEvidence(None, None, None, source)

    from .workout_parse_adapter import _get_workout_parse

    compute = getattr(_get_workout_parse(), "compute_threshold_power_anchors", None)
    if not callable(compute):
        return ThresholdEffortEvidence(None, None, None, source)
    return threshold_effort_evidence(parsed_ride)


async def register_threshold_effort(
    repository: Any,
    *,
    ride_id: Any,
    evidence: ThresholdEffortEvidence,
) -> dict[str, Any]:
    """Persist one derived evidence row through the repository's private RPC."""
    if (
        evidence.best_180s_w is None
        and evidence.best_420s_w is None
        and evidence.best_900s_w is None
    ):
        return {"disposition": "not_recorded"}
    row = await repository.register_reward_threshold_effort(
        ride_id=ride_id,
        best_180s_w=evidence.best_180s_w,
        best_420s_w=evidence.best_420s_w,
        best_900s_w=evidence.best_900s_w,
    )
    if not isinstance(row, dict):
        raise ValueError("Threshold authority did not retain the ride evidence")
    return row


def threshold_candidate_review_reason(
    candidate: Mapping[str, Any],
) -> Optional[str]:
    """Map authority-review dispositions into the existing ride review gate."""
    disposition = str(candidate.get("disposition") or "")
    if disposition in THRESHOLD_CANDIDATE_REVIEW_DISPOSITIONS:
        return f"reward_threshold_{disposition}"
    return None
