"""Recording plausibility only: never remove samples or change NP/TSS.

Coggan defines TSS from intensity and duration:
https://www.trainingpeaks.com/learn/articles/normalized-power-intensity-factor-training-stress/
TrainingPeaks gives TSS = duration * (NP / FTP)^2 * 100:
https://www.trainingpeaks.com/learn/articles/estimating-training-stress-score-tss/
WKO distinguishes recording duration (auto-pause off includes stops) from
moving duration; this does not establish a universal importer algorithm:
https://help.trainingpeaks.com/hc/en-us/articles/223730607

These sources support retaining recorded zeros, outdoors and indoors. The
parameters below are evidence-review policy, NOT TSS parameters.
Changing them requires Tim's ratification and a new evidence-policy version;
already frozen ride policies and held-release NP/duration remain untouched.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Any, Sequence

IDLE_EVIDENCE_VERSION = "stationary_recording_review_v2"
IDLE_REVIEW_REASON = "implausible_stationary_recording"
# Conservative near-zero speed, below WKO's 2 mph moving-duration boundary.
# Local real-stream calibration and sensitivity are recorded in the owning PR.
STATIONARY_MAX_SPEED_MPS = 0.5
STATIONARY_MIN_SPAN_S = 30
MAX_RECORDED_GAP_S = 30  # Same sample-gap boundary as metrics v1; not changed.
# Tim ratified 2026-09-24 (Bead 8906g.5, PR #50): 92.62% keeps all
# 1,416 cached real rides below review, with a >=0.50 percentage-point margin
# above their 92.110228% maximum, while tightening the draft 95% gate.
# Retain <=0.5 m/s and spans >30s. Tighten toward 75% once review has a
# resolver; that follow-up is recorded on the same Bead, not active policy.
# v2 identifies this threshold; prior admission decisions remain frozen.
STATIONARY_REVIEW_SHARE_BPS = 9_262


@dataclass(frozen=True)
class IdleRecordingEvidence:
    recorded_duration_s: float
    stationary_duration_s: float
    stationary_share_bps: int
    review_reason: str | None
    policy_version: str = IDLE_EVIDENCE_VERSION
    stationary_max_speed_mps: float = STATIONARY_MAX_SPEED_MPS
    stationary_min_span_s: int = STATIONARY_MIN_SPAN_S
    max_recorded_gap_s: int = MAX_RECORDED_GAP_S
    review_share_bps: int = STATIONARY_REVIEW_SHARE_BPS

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _number(record: Any, key: str) -> float | None:
    value = getattr(record, key, None)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and value >= 0 else None


def _gps_speed(previous: Any, current: Any, dt: float) -> float | None:
    coordinates = [
        getattr(r, k, None) for r in (previous, current) for k in ("lat", "lon")
    ]
    if any(
        isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
        for v in coordinates
    ):
        return None
    lat1, lon1, lat2, lon2 = coordinates
    if not (
        -90 <= lat1 <= 90
        and -90 <= lat2 <= 90
        and -180 <= lon1 <= 180
        and -180 <= lon2 <= 180
    ):
        return None
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((phi2 - phi1) / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 6_371_000 * 2 * math.asin(math.sqrt(min(1.0, a))) / dt


def _stationary_interval(previous: Any, current: Any, dt: float) -> bool:
    # Positive effort vetoes still GPS/zero trainer speed. Missing is not zero.
    for record in (previous, current):
        if any((_number(record, key) or 0) > 0 for key in ("power_w", "cadence_rpm")):
            return False
    # Any affirmative movement vetoes stationarity, including when another
    # sensor is stuck at zero. Never prefer a flat speed/distance over GPS motion.
    stationary_signal = False
    speeds = [_number(r, "speed_mps") for r in (previous, current)]
    if any(speed is not None and speed > STATIONARY_MAX_SPEED_MPS for speed in speeds):
        return False
    if all(speed is not None for speed in speeds):
        stationary_signal = True
    distances = [_number(r, "distance_m") for r in (previous, current)]
    if all(distance is not None for distance in distances):
        delta = distances[1] - distances[0]
        if delta / dt > STATIONARY_MAX_SPEED_MPS:
            return False
        if delta >= 0:  # A reset alone is not stationary evidence.
            stationary_signal = True
    gps_speed = _gps_speed(previous, current, dt)
    if gps_speed is not None:
        if gps_speed > STATIONARY_MAX_SPEED_MPS:
            return False
        stationary_signal = True
    if stationary_signal:
        return True
    # No motion channel: cadence AND explicit zero power support trainer rest.
    # Power-only zeros cannot distinguish rest from coasting; leave unknown.
    return all(
        _number(r, "cadence_rpm") == 0 and _number(r, "power_w") == 0
        for r in (previous, current)
    )


def assess_idle_recording(
    records: Sequence[Any], *, keep_ms=None
) -> IdleRecordingEvidence:
    """Time-weighted share of >30s stationary spans within recorded intervals.

    Gaps >30s are excluded from numerator and denominator. Unknown movement
    stays in the denominator but never becomes affirmative stationary evidence.
    No gap interpolation, sample removal, or TSS recomputation occurs here.
    """
    from .ride_effort_trim import epoch_ms, intersect

    total_us = stationary_us = run_us = 0
    last_end = None
    for previous, current in zip(records, records[1:]):
        dt_us = (current.timestamp - previous.timestamp) // timedelta(microseconds=1)
        if not 0 < dt_us <= MAX_RECORDED_GAP_S * 1_000_000:
            if run_us > STATIONARY_MIN_SPAN_S * 1_000_000:
                stationary_us += run_us
            run_us = 0
            last_end = None
            continue
        if keep_ms is None:
            pieces = [(0, dt_us)]
        else:
            pieces = [
                (a * 1000, b * 1000)
                for a, b in intersect(
                    [(epoch_ms(previous.timestamp), epoch_ms(current.timestamp))],
                    keep_ms,
                )
            ]
        stationary = _stationary_interval(previous, current, dt_us / 1_000_000)
        for a, b in pieces:
            if keep_ms is not None and a != last_end:
                if run_us > STATIONARY_MIN_SPAN_S * 1_000_000:
                    stationary_us += run_us
                run_us = 0
            total_us += b - a
            if stationary:
                run_us += b - a
            else:
                if run_us > STATIONARY_MIN_SPAN_S * 1_000_000:
                    stationary_us += run_us
                run_us = 0
            last_end = b
    if run_us > STATIONARY_MIN_SPAN_S * 1_000_000:
        stationary_us += run_us
    share_bps = stationary_us * 10_000 // total_us if total_us else 0
    return IdleRecordingEvidence(
        recorded_duration_s=total_us / 1_000_000,
        stationary_duration_s=stationary_us / 1_000_000,
        stationary_share_bps=share_bps,
        review_reason=(
            IDLE_REVIEW_REASON if share_bps >= STATIONARY_REVIEW_SHARE_BPS else None
        ),
    )
