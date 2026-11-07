from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services.reward_ftp import RewardFtpSnapshot
from app.services.reward_threshold import (
    HELD_RIDE_ELIGIBILITY_WINDOW,
    build_held_ride_release_policy,
    requires_threshold_hold,
)
from app.services.ride_effort_policy import (
    STALE_ACTIVITY_REVIEW_REASON,
    build_ride_effort_policy,
)


ADMITTED_AT = datetime(2026, 8, 24, 16, 0, tzinfo=timezone.utc)


def _derived_threshold(ftp_w: int = 250) -> RewardFtpSnapshot:
    return RewardFtpSnapshot(
        ftp_w=ftp_w,
        source="derived_eftp",
        authority_id="11111111-1111-4111-8111-111111111111",
        policy_version="reward_ftp_policy_2026_08_24_threshold_v1",
    )


def _reward_grade_metrics(*, completed_at: datetime, tss: float = 64.0) -> SimpleNamespace:
    return SimpleNamespace(
        tss=tss,
        avg_power_w=200,
        normalized_power_w=200,
        avg_hr_bpm=None,
        metrics_version="workout_parse_metrics_v1",
        moving_time_sec=3600,
        power_sample_count=3600,
        power_sample_coverage_bps=10_000,
        started_at=completed_at - timedelta(hours=1),
        completed_at=completed_at,
        duration_sec=3600,
    )


def test_hold_is_selected_by_authority_source_not_the_numeric_200w_value() -> None:
    assert requires_threshold_hold(RewardFtpSnapshot.network_default()) is True
    assert requires_threshold_hold(_derived_threshold(ftp_w=200)) is False


def test_release_recomputes_exact_cal_before_climb_tribute_is_planned() -> None:
    # The ride was admitted at upload inside the ordinary 30-day guard. At
    # establishment its original completion is older than 30 days, which must
    # not cause the already-admitted held ride to be rejected a second time.
    completed_at = ADMITTED_AT - timedelta(days=29)
    policy = build_held_ride_release_policy(
        _reward_grade_metrics(completed_at=completed_at),
        admitted_at=ADMITTED_AT,
        established_at=ADMITTED_AT + timedelta(weeks=8),
        established_threshold=_derived_threshold(),
    )

    assert policy.disposition == "release"
    assert policy.reward_ftp_w == 250
    assert policy.reward_ftp_source == "derived_eftp"
    assert policy.reward_ftp_authority_id == "11111111-1111-4111-8111-111111111111"
    assert policy.economic_tss == 64.0
    assert policy.exact_cal_base_units == 64_000_000_000
    assert policy.exact_tribute_budget_base_units == 0


def test_sixteen_week_establishment_edge_is_inclusive_then_lapses() -> None:
    metrics = _reward_grade_metrics(completed_at=ADMITTED_AT)

    exact_edge = build_held_ride_release_policy(
        metrics,
        admitted_at=ADMITTED_AT,
        established_at=ADMITTED_AT + HELD_RIDE_ELIGIBILITY_WINDOW,
        established_threshold=_derived_threshold(),
    )
    after_edge = build_held_ride_release_policy(
        metrics,
        admitted_at=ADMITTED_AT,
        established_at=(
            ADMITTED_AT
            + HELD_RIDE_ELIGIBILITY_WINDOW
            + timedelta(microseconds=1)
        ),
        established_threshold=_derived_threshold(),
    )

    assert HELD_RIDE_ELIGIBILITY_WINDOW == timedelta(weeks=16)
    assert exact_edge.disposition == "release"
    assert exact_edge.exact_cal_base_units == 64_000_000_000
    assert after_edge.disposition == "lapsed"
    assert after_edge.exact_cal_base_units == 0
    assert after_edge.exact_tribute_budget_base_units == 0


def test_release_requires_real_authority_and_accepts_forward_only_late_upload() -> None:
    metrics = _reward_grade_metrics(completed_at=ADMITTED_AT)

    with pytest.raises(ValueError, match="established"):
        build_held_ride_release_policy(
            metrics,
            admitted_at=ADMITTED_AT,
            established_at=ADMITTED_AT + timedelta(weeks=1),
            established_threshold=RewardFtpSnapshot.network_default(),
        )
    late_upload = build_held_ride_release_policy(
        metrics,
        admitted_at=ADMITTED_AT,
        established_at=ADMITTED_AT - timedelta(weeks=1),
        established_threshold=_derived_threshold(),
    )
    assert late_upload.disposition == "release"
    assert late_upload.exact_cal_base_units == 64_000_000_000


def test_ordinary_thirty_day_upload_guard_is_unchanged() -> None:
    exact_edge = build_ride_effort_policy(
        _reward_grade_metrics(completed_at=ADMITTED_AT - timedelta(days=30)),
        now=ADMITTED_AT,
    )
    stale = build_ride_effort_policy(
        _reward_grade_metrics(
            completed_at=ADMITTED_AT - timedelta(days=30, microseconds=1)
        ),
        now=ADMITTED_AT,
    )

    assert exact_edge.reward_policy == "rewardable"
    assert exact_edge.rewardable_cal_base_units == 64_000_000_000
    assert stale.reward_policy == "manual_review"
    assert stale.rewardable_cal_base_units == 0
    assert stale.review_reason == STALE_ACTIVITY_REVIEW_REASON
