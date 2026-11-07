from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.ride_processor import (
    AUTHORITATIVE_METRICS_VERSION,
    FUTURE_ACTIVITY_REVIEW_REASON,
    HEART_RATE_THRESHOLD_REVIEW_REASON,
    INSUFFICIENT_POWER_COVERAGE_REVIEW_REASON,
    INVALID_ACTIVITY_DURATION_REVIEW_REASON,
    NON_AUTHORITATIVE_METRICS_REVIEW_REASON,
    ROUTE_ESTIMATE_ECONOMIC_REVIEW_REASON,
    STALE_ACTIVITY_REVIEW_REASON,
    _calculate_cal_amounts,
    _calculate_economic_cal_amounts,
    _rider_level_for_total_tss,
    build_ride_effort_policy,
)


NOW = datetime.now(timezone.utc).replace(microsecond=0)
STARTED_AT = NOW - timedelta(hours=2)
COMPLETED_AT = NOW - timedelta(hours=1)


def test_cal_amounts_keep_display_units_separate_from_token_units():
    display_units, allocation_units = _calculate_cal_amounts(84.3)

    assert display_units == 84
    assert allocation_units == 84_300_000_000


def test_cal_amounts_preserve_exact_decimal_tss_base_units():
    assert _calculate_cal_amounts(64.1) == (64, 64_100_000_000)


def test_cal_amounts_zero_out_non_positive_tss():
    assert _calculate_cal_amounts(0) == (0, 0)
    assert _calculate_cal_amounts(-1) == (0, 0)


def test_economic_cal_amounts_abstain_route_only_tss():
    metrics = SimpleNamespace(
        tss=169.9,
        avg_power_w=None,
        normalized_power_w=None,
        avg_hr_bpm=None,
        started_at=STARTED_AT,
        completed_at=COMPLETED_AT,
        duration_sec=3600,
    )

    assert _calculate_economic_cal_amounts(metrics) == (
        0,
        0,
        ROUTE_ESTIMATE_ECONOMIC_REVIEW_REASON,
    )


def test_economic_cal_amounts_reject_hr_without_trusted_rider_threshold():
    metrics = {
        "tss": 84.3,
        "avg_power_w": None,
        "normalized_power_w": None,
        "avg_hr_bpm": 151,
        "metrics_version": AUTHORITATIVE_METRICS_VERSION,
        "heart_rate_sample_count": 3600,
        "heart_rate_sample_coverage_bps": 10_000,
        "started_at": STARTED_AT,
        "completed_at": COMPLETED_AT,
        "duration_sec": 3600,
    }

    assert _calculate_economic_cal_amounts(metrics) == (
        0,
        0,
        HEART_RATE_THRESHOLD_REVIEW_REASON,
    )


def test_route_only_policy_preserves_estimate_but_blocks_economics():
    policy = build_ride_effort_policy(
        SimpleNamespace(
            tss=169.9,
            avg_power_w=None,
            normalized_power_w=None,
            avg_hr_bpm=None,
            started_at=STARTED_AT,
            completed_at=COMPLETED_AT,
            duration_sec=3600,
        )
    )

    assert policy.effort_evidence_tier == "route_only"
    assert policy.reward_policy == "estimated_only"
    assert policy.estimated_cal == 169
    assert policy.rewardable_cal == 0
    assert policy.tributable_cal == 0
    assert policy.requires_economic_review is True
    assert policy.review_reason == ROUTE_ESTIMATE_ECONOMIC_REVIEW_REASON


def test_power_policy_is_rewardable_and_tributable():
    policy = build_ride_effort_policy(
        SimpleNamespace(
            tss=84.3,
            avg_power_w=201,
            normalized_power_w=222,
            avg_hr_bpm=None,
            metrics_version=AUTHORITATIVE_METRICS_VERSION,
            moving_time_sec=3600,
            power_sample_count=3600,
            power_sample_coverage_bps=10_000,
            started_at=STARTED_AT,
            completed_at=COMPLETED_AT,
            duration_sec=3600,
        )
    )

    assert policy.effort_evidence_tier == "power_verified"
    assert policy.reward_policy == "rewardable"
    assert policy.estimated_cal == 84
    assert policy.rewardable_cal == 84
    assert policy.tributable_cal == 84
    assert policy.rewardable_cal_base_units == 84_300_000_000
    assert policy.tributable_cal_base_units == 84_300_000_000


def test_legacy_power_estimate_is_visible_but_never_rewardable():
    policy = build_ride_effort_policy(
        SimpleNamespace(
            tss=84.3,
            avg_power_w=201,
            normalized_power_w=222,
            avg_hr_bpm=None,
            metrics_version="python_ride_metrics_v1",
            moving_time_sec=3600,
            power_sample_count=3600,
            power_sample_coverage_bps=10_000,
            started_at=STARTED_AT,
            completed_at=COMPLETED_AT,
            duration_sec=3600,
        )
    )

    assert policy.effort_evidence_tier == "sensor_supported"
    assert policy.reward_policy == "estimated_only"
    assert policy.estimated_cal == 84
    assert policy.rewardable_cal == 0
    assert policy.tributable_cal == 0
    assert policy.review_reason == NON_AUTHORITATIVE_METRICS_REVIEW_REASON


def test_sparse_power_is_not_reward_grade_even_with_positive_tss():
    policy = build_ride_effort_policy(
        SimpleNamespace(
            tss=84.3,
            avg_power_w=201,
            normalized_power_w=222,
            avg_hr_bpm=None,
            metrics_version=AUTHORITATIVE_METRICS_VERSION,
            moving_time_sec=3600,
            power_sample_count=12,
            power_sample_coverage_bps=120,
            started_at=STARTED_AT,
            completed_at=COMPLETED_AT,
            duration_sec=3600,
        )
    )

    assert policy.effort_evidence_tier == "sensor_supported"
    assert policy.reward_policy == "estimated_only"
    assert policy.rewardable_cal == 0
    assert policy.tributable_cal == 0
    assert policy.review_reason == INSUFFICIENT_POWER_COVERAGE_REVIEW_REASON


def test_manual_review_policy_blocks_economics_without_losing_estimate():
    policy = build_ride_effort_policy(
        {
            "tss": 84.3,
            "avg_power_w": 201,
            "normalized_power_w": 222,
            "avg_hr_bpm": None,
        },
        blocking_review_reason="preliminary_hash_mismatch",
    )

    assert policy.effort_evidence_tier == "manual_review"
    assert policy.reward_policy == "manual_review"
    assert policy.estimated_cal == 84
    assert policy.rewardable_cal == 0
    assert policy.tributable_cal == 0
    assert policy.review_reason == "preliminary_hash_mismatch"


def test_future_activity_policy_blocks_economics_without_losing_estimate():
    policy = build_ride_effort_policy(
        {
            "tss": 84.3,
            "avg_power_w": 201,
            "completed_at": NOW + timedelta(minutes=11),
            "started_at": NOW,
            "duration_sec": 660,
        },
        now=NOW,
    )

    assert policy.reward_policy == "manual_review"
    assert policy.rewardable_cal == 0
    assert policy.review_reason == FUTURE_ACTIVITY_REVIEW_REASON


def test_stale_activity_policy_blocks_automatic_economics():
    policy = build_ride_effort_policy(
        {
            "tss": 84.3,
            "avg_power_w": 201,
            "completed_at": NOW - timedelta(days=31),
            "started_at": NOW - timedelta(days=31, hours=1),
            "duration_sec": 3600,
        },
        now=NOW,
    )

    assert policy.reward_policy == "manual_review"
    assert policy.rewardable_cal == 0
    assert policy.review_reason == STALE_ACTIVITY_REVIEW_REASON


def test_impossible_duration_policy_blocks_automatic_economics():
    policy = build_ride_effort_policy(
        {
            "tss": 84.3,
            "avg_power_w": 201,
            "completed_at": COMPLETED_AT,
            "started_at": COMPLETED_AT,
            "duration_sec": 0,
        },
        now=NOW,
    )

    assert policy.reward_policy == "manual_review"
    assert policy.rewardable_cal == 0
    assert policy.review_reason == INVALID_ACTIVITY_DURATION_REVIEW_REASON


def test_rider_level_for_total_tss_uses_stable_200_tss_steps():
    assert _rider_level_for_total_tss(-50) == 1
    assert _rider_level_for_total_tss(0) == 1
    assert _rider_level_for_total_tss(199.99) == 1
    assert _rider_level_for_total_tss(200) == 2
    assert _rider_level_for_total_tss(1200.5) == 7
