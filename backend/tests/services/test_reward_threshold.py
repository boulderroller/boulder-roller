from __future__ import annotations

import pytest

import app.services.reward_threshold as reward_threshold
import app.services.reward_ftp as reward_ftp
import app.services.ride_processor as ride_processor
from app.services.reward_threshold import threshold_candidate_review_reason
from app.services.reward_ftp import RewardFtpSnapshot


def test_threshold_arithmetic_has_one_database_authority() -> None:
    assert reward_threshold.THRESHOLD_MODEL_VERSION == "threshold_cp_3_7_15_v1"
    assert not hasattr(reward_threshold, "derive_cp_candidate_w")
    assert not hasattr(reward_threshold, "promotion_decision")


def test_reprocessing_omits_frozen_threshold_and_reward_fields() -> None:
    assert hasattr(ride_processor, "_unfrozen_ride_economic_fields")
    existing = {
        "threshold_source_evidence": {},
        "reward_ftp_w": 245,
        "economic_tss": 0,
    }
    fields = ride_processor._unfrozen_ride_economic_fields(
        existing,
        threshold_source_fields={
            "threshold_source_evidence": {"eligibility_reason": "eligible"},
            "threshold_power_source_id": "new-meter",
        },
        economic_tss=88.0,
        reward_ftp_snapshot=RewardFtpSnapshot(
            ftp_w=300,
            source="derived_eftp",
            authority_id="11111111-1111-4111-8111-111111111111",
            policy_version="reward_ftp_policy_2026_08_24_threshold_v1",
        ),
    )

    assert fields == {}


def test_legacy_authority_sources_are_readable_but_not_advertised_writable() -> None:
    assert not hasattr(reward_ftp, "VERIFIED_REWARD_FTP_SOURCES")
    assert reward_ftp.POST_CUTOVER_WRITABLE_REWARD_FTP_SOURCES == frozenset(
        {"derived_eftp"}
    )
    assert reward_ftp.HISTORICAL_REWARD_FTP_SOURCES == frozenset(
        {"operator_verified", "trusted_provider", "verified_power_test"}
    )


@pytest.mark.parametrize(
    "disposition",
    ("invalid_fit_review", "below_bounds_review", "above_bounds_review"),
)
def test_every_invalid_candidate_holds_ride_economics_for_review(
    disposition: str,
) -> None:
    assert threshold_candidate_review_reason({"disposition": disposition}) == (
        f"reward_threshold_{disposition}"
    )


def test_historical_reward_ftp_policy_remains_readable_but_unknown_is_rejected() -> None:
    legacy = RewardFtpSnapshot.from_row(
        {
            "reward_ftp_w": 200,
            "reward_ftp_source": "network_default",
            "reward_ftp_authority_id": None,
            "reward_ftp_policy_version": "reward_ftp_policy_2026_07_14",
        }
    )
    derived = RewardFtpSnapshot.from_row(
        {
            "reward_ftp_w": 256,
            "reward_ftp_source": "derived_eftp",
            "reward_ftp_authority_id": "11111111-1111-4111-8111-111111111111",
            "reward_ftp_policy_version": "reward_ftp_policy_2026_08_24_threshold_v1",
        }
    )

    assert legacy.policy_version == "reward_ftp_policy_2026_07_14"
    assert derived.source == "derived_eftp"
    with pytest.raises(ValueError, match="unsupported reward FTP policy"):
        RewardFtpSnapshot.from_row(
            {
                "reward_ftp_w": 200,
                "reward_ftp_source": "network_default",
                "reward_ftp_authority_id": None,
                "reward_ftp_policy_version": "unknown",
            }
        )
