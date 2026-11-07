"""Reference-label curation helpers for Strava holdout scoring.

The Strava holdout set is useful regression pressure, but repeated stale
segment-effort labels can dominate aggregate misses. These helpers quarantine
obvious duplicate-label spam before it becomes detector-tuning signal while
leaving raw metrics available for audit.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple, TypeVar

REPEATED_SEGMENT_SPAM_MIN_COUNT = 12
GEOMETRY_ELEV_TOLERANCE_M = 1.0
GEOMETRY_GRADE_TOLERANCE_PCT = 0.25
GEOMETRY_DISTANCE_TOLERANCE_M = 15.0

WEAK_REPEAT_MAX_ELEV_M = 35.0
WEAK_REPEAT_MAX_GRADE_PCT = 3.0

STEEP_REPEAT_MIN_ELEV_M = 80.0
STEEP_REPEAT_MIN_GRADE_PCT = 12.0
STEEP_REPEAT_MAX_DISTANCE_M = 1000.0

POLICY_REVIEW_ACTIVITY_CLASSIFICATIONS = {
    "3523251381": "urban_repeat_policy_review",
}

T = TypeVar("T")


@dataclass(frozen=True)
class QuarantinedSegmentGroup:
    segment_id: int
    segment_name: str
    count: int
    reason: str
    avg_elevation_diff: float
    avg_average_grade: float
    avg_distance_m: float


def _normalise_name(value: object) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"\s+", " ", text)


def segment_reference_key(segment: object) -> Tuple[int, str]:
    """Stable key for repeated Strava segment-effort labels."""
    return (
        int(getattr(segment, "segment_id", 0) or 0),
        _normalise_name(getattr(segment, "segment_name", "")),
    )


def _spread(values: Iterable[float]) -> float:
    vals = list(values)
    if not vals:
        return 0.0
    return max(vals) - min(vals)


def _avg(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _geometry_is_tightly_repeated(segments: Sequence[object]) -> bool:
    elevations = [float(getattr(s, "elevation_diff", 0.0) or 0.0) for s in segments]
    grades = [float(getattr(s, "average_grade", 0.0) or 0.0) for s in segments]
    distances = [float(getattr(s, "distance_m", 0.0) or 0.0) for s in segments]
    return (
        _spread(elevations) <= GEOMETRY_ELEV_TOLERANCE_M
        and _spread(grades) <= GEOMETRY_GRADE_TOLERANCE_PCT
        and _spread(distances) <= GEOMETRY_DISTANCE_TOLERANCE_M
    )


def _spam_reason(segments: Sequence[object]) -> str | None:
    if len(segments) < REPEATED_SEGMENT_SPAM_MIN_COUNT:
        return None
    if not _geometry_is_tightly_repeated(segments):
        return None

    elevations = [float(getattr(s, "elevation_diff", 0.0) or 0.0) for s in segments]
    grades = [float(getattr(s, "average_grade", 0.0) or 0.0) for s in segments]
    distances = [float(getattr(s, "distance_m", 0.0) or 0.0) for s in segments]
    avg_elev = _avg(elevations)
    avg_grade = _avg(grades)
    avg_distance = _avg(distances)

    if avg_elev <= WEAK_REPEAT_MAX_ELEV_M and avg_grade <= WEAK_REPEAT_MAX_GRADE_PCT:
        return "repeated_weak_segment_label"
    if (
        avg_elev >= STEEP_REPEAT_MIN_ELEV_M
        and avg_grade >= STEEP_REPEAT_MIN_GRADE_PCT
        and avg_distance <= STEEP_REPEAT_MAX_DISTANCE_M
    ):
        return "repeated_steep_template_label"
    return None


def quarantine_repeated_segment_spam(
    segments: Sequence[T],
) -> Tuple[List[T], List[QuarantinedSegmentGroup]]:
    """Remove obvious repeated segment-effort spam from curated references.

    This intentionally targets narrow defect signatures:
    - many repeats of the exact same Strava segment on one ride;
    - tightly repeated segment geometry;
    - either weak near-threshold labels or short implausibly steep templates.
    """
    grouped: dict[Tuple[int, str], list[T]] = defaultdict(list)
    for segment in segments:
        grouped[segment_reference_key(segment)].append(segment)

    quarantined_keys: set[Tuple[int, str]] = set()
    quarantined_groups: list[QuarantinedSegmentGroup] = []

    for key, group in grouped.items():
        reason = _spam_reason(group)
        if not reason:
            continue

        elevations = [float(getattr(s, "elevation_diff", 0.0) or 0.0) for s in group]
        grades = [float(getattr(s, "average_grade", 0.0) or 0.0) for s in group]
        distances = [float(getattr(s, "distance_m", 0.0) or 0.0) for s in group]
        representative = group[0]
        quarantined_keys.add(key)
        quarantined_groups.append(
            QuarantinedSegmentGroup(
                segment_id=int(getattr(representative, "segment_id", 0) or 0),
                segment_name=str(getattr(representative, "segment_name", "") or ""),
                count=len(group),
                reason=reason,
                avg_elevation_diff=round(_avg(elevations), 1),
                avg_average_grade=round(_avg(grades), 1),
                avg_distance_m=round(_avg(distances), 1),
            )
        )

    curated = [
        segment
        for segment in segments
        if segment_reference_key(segment) not in quarantined_keys
    ]
    return curated, quarantined_groups


def quarantined_segment_count(groups: Sequence[QuarantinedSegmentGroup]) -> int:
    return sum(group.count for group in groups)


def holdout_policy_classification(activity_id: object) -> str | None:
    """Known holdout rides that need policy taxonomy rather than threshold tuning."""
    return POLICY_REVIEW_ACTIVITY_CLASSIFICATIONS.get(str(activity_id))
