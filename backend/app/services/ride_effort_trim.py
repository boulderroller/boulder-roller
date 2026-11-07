"""Permanent effort claims. All intervals are canonical half-open epoch ms."""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .workout_parse_adapter import calculate_paid_metrics_rust

VERSION = "ride_effort_trim_v1"


class PaidEffortEvidenceUnavailableError(ValueError):
    pass


class PaidEffortEvidenceMismatchError(ValueError):
    pass


class ClimbTributeExceedsPaidCalError(ValueError):
    pass


def normalize(spans):
    result = []
    for a, b in sorted(spans):
        if type(a) is not int or type(b) is not int or a >= b:
            raise ValueError("spans require increasing integer milliseconds")
        if result and a <= result[-1][1]:
            result[-1] = (result[-1][0], max(b, result[-1][1]))
        else:
            result.append((a, b))
    return result


def subtract(spans, covered):
    result = []
    for a, b in normalize(spans):
        for c, d in normalize(covered):
            if d <= a:
                continue
            if c >= b:
                break
            if c > a:
                result.append((a, c))
            a = max(a, d)
            if a >= b:
                break
        if a < b:
            result.append((a, b))
    return result


def intersect(left, right):
    return normalize(
        [
            (max(a, c), min(b, d))
            for a, b in left
            for c, d in right
            if max(a, c) < min(b, d)
        ]
    )


def total_seconds(spans):
    return sum(b - a for a, b in spans) // 1000


def encode(spans):
    return [list(s) for s in normalize(spans)]


def epoch_ms(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    delta = value - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return delta.days * 86400000 + delta.seconds * 1000 + delta.microseconds // 1000


def completion_window_ms(started_at, start_offset_s, end_offset_s):
    start = epoch_ms(started_at)
    return (start + start_offset_s * 1000, start + (end_offset_s + 1) * 1000)


@dataclass
class EffortTrim:
    effort_ms: list
    paid_ms: list
    covered_ms: list = field(default_factory=list)
    paid_metrics: Any = None
    frozen: bool = False
    covered_completion_windows: list = field(default_factory=list)
    version: str = VERSION

    def clear_claim(self):
        self.paid_ms = []
        # Empty claims have one representation, including on replay.
        self.paid_metrics = None

    def payload(self, *, include_metrics=True):
        result = {
            "version": self.version,
            "effort_spans_ms": encode(self.effort_ms),
            "paid_spans_ms": encode(self.paid_ms),
            "covered_spans_ms": encode(intersect(self.effort_ms, self.covered_ms)),
        }
        if include_metrics:
            m = self.paid_metrics
            result["paid_metrics"] = (
                None
                if m is None or not self.paid_ms
                else {
                    "tss": str(Decimal(str(m.tss))),
                    "normalized_power_duration_s": int(m.normalized_power_duration_s),
                    "power_sample_count": int(m.power_sample_count),
                    "power_sample_coverage_bps": int(m.power_sample_coverage_bps),
                    "moving_time_s": int(m.moving_time_sec),
                }
            )
        return result

    def projections(self):
        return {
            "effort_seconds": total_seconds(self.effort_ms),
            "covered_effort_seconds": total_seconds(
                intersect(self.effort_ms, self.covered_ms)
            ),
            "paid_effort_seconds": total_seconds(self.paid_ms),
        }


async def resolve_effort_trim(
    *,
    repository,
    ride_id,
    user_id,
    effort_ms,
    load_native_activity,
    reward_ftp_w,
    completion_spans_ms=None,
):
    basis = await repository.get_effort_trim_basis(
        ride_id=ride_id,
        user_id=user_id,
        completion_spans_ms=encode(completion_spans_ms or []),
    )
    effort = normalize(effort_ms)
    frozen = basis.get("frozen")
    covered = normalize(
        frozen["covered_spans_ms"] if frozen else basis["covered_spans_ms"]
    )
    if frozen and normalize(frozen["effort_spans_ms"]) != effort:
        raise PaidEffortEvidenceMismatchError("stored effort differs from frozen plan")
    candidate = (
        normalize(frozen["paid_spans_ms"]) if frozen else subtract(effort, covered)
    )
    trim = EffortTrim(
        effort,
        candidate,
        covered,
        frozen=bool(frozen),
        covered_completion_windows=basis["covered_completion_windows"],
    )
    if candidate == effort or (frozen and not candidate):
        return trim
    native = await load_native_activity()
    metrics, paid = calculate_paid_metrics_rust(native, candidate, reward_ftp_w)
    if frozen and normalize(paid) != candidate:
        raise PaidEffortEvidenceMismatchError(
            "frozen buckets differ from native activity"
        )
    trim.paid_metrics = metrics
    trim.paid_ms = normalize(paid)
    return trim
