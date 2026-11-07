from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services import ride_attester
from app.services.ride_attester import RideAttester
from app.services.ride_effort_policy import build_ride_effort_policy


def _parsed_ride() -> SimpleNamespace:
    started_at = datetime(2026, 4, 17, 8, 0, tzinfo=timezone.utc)
    completed_at = started_at + timedelta(minutes=5)
    return SimpleNamespace(
        records=[
            SimpleNamespace(timestamp=started_at),
            SimpleNamespace(timestamp=completed_at),
        ],
        gps_track=[],
        started_at=started_at,
        completed_at=completed_at,
    )


def test_prepare_ride_binds_identity_preliminary_check_parse_and_metrics() -> None:
    attester = RideAttester()
    parsed = _parsed_ride()
    metrics = SimpleNamespace(duration_sec=300, tss=84.0)

    with patch.object(
        ride_attester,
        "compute_ride_identity_bytes",
        return_value=(bytes.fromhex("ab" * 32), 1),
    ):
        with patch.object(ride_attester, "parse_ride_file_bytes", return_value=parsed):
            with patch.object(ride_attester, "calculate_metrics", return_value=metrics):
                prepared = attester.prepare_ride(
                    file_data_b64="ZmFrZQ==",
                    file_type="fit",
                    file_bytes=b"fake",
                    ride_row={
                        "preliminary_ride_hash_hex": "ab" * 32,
                        "preliminary_parser_version": 1,
                    },
                    user_weight_kg=75.0,
                    user_ftp_w=200,
                )

    assert prepared.onchain_identity.ride_hash == bytes.fromhex("ab" * 32)
    assert prepared.onchain_identity.parser_version == 1
    assert prepared.preliminary_check.requires_review is False
    assert prepared.preliminary_check.canonical_match is True
    assert prepared.parsed_ride is parsed
    assert prepared.metrics is metrics


def test_prepare_ride_rejects_empty_records_before_execution() -> None:
    attester = RideAttester()
    parsed = SimpleNamespace(records=[], gps_track=[])

    with patch.object(
        ride_attester,
        "compute_ride_identity_bytes",
        return_value=(bytes.fromhex("ab" * 32), 1),
    ):
        with patch.object(ride_attester, "parse_ride_file_bytes", return_value=parsed):
            with pytest.raises(ValueError, match="No valid records"):
                attester.prepare_ride(
                    file_data_b64="ZmFrZQ==",
                    file_type="fit",
                    file_bytes=b"fake",
                    ride_row={},
                    user_weight_kg=75.0,
                    user_ftp_w=200,
                )


def test_calculate_metrics_uses_authoritative_workout_parse_engine() -> None:
    attester = RideAttester()
    parsed = SimpleNamespace(_native_activity=object(), records=[])
    expected = SimpleNamespace(metrics_version="workout_parse_metrics_v1", tss=84.0)

    with patch.object(
        ride_attester,
        "calculate_metrics_rust",
        return_value=expected,
    ) as calculate_metrics_rust:
        actual = attester.calculate_metrics(
            parsed_ride=parsed,
            user_weight_kg=75.0,
            user_ftp_w=245,
        )

    assert actual is expected
    calculate_metrics_rust.assert_called_once_with(
        parsed,
        user_weight_kg=75.0,
        user_ftp_w=245,
    )


def test_prepare_ride_separates_display_ftp_from_reward_ftp() -> None:
    attester = RideAttester()
    parsed = _parsed_ride()

    def metrics_for_ftp(*, user_ftp_w: int, **_kwargs):
        return SimpleNamespace(duration_sec=300, tss=40_000 / user_ftp_w)

    with patch.object(
        ride_attester,
        "compute_ride_identity_bytes",
        return_value=(bytes.fromhex("ab" * 32), 3),
    ):
        with patch.object(ride_attester, "parse_ride_file_bytes", return_value=parsed):
            with patch.object(
                ride_attester,
                "calculate_metrics",
                side_effect=metrics_for_ftp,
            ):
                prepared = attester.prepare_ride(
                    file_data_b64="ZmFrZQ==",
                    file_type="fit",
                    file_bytes=b"fake",
                    ride_row={},
                    user_weight_kg=75.0,
                    user_ftp_w=100,
                    reward_ftp_w=200,
                )

    assert prepared.metrics.tss == 400
    assert prepared.economic_metrics.tss == 200
    assert prepared.reward_ftp_w == 200


def test_profile_ftp_edits_cannot_change_rewardable_cal() -> None:
    attester = RideAttester()
    parsed = _parsed_ride()

    def metrics_for_ftp(*, user_ftp_w: int, **_kwargs):
        return SimpleNamespace(
            duration_sec=300,
            moving_time_sec=300,
            metrics_version="workout_parse_metrics_v1",
            power_sample_count=300,
            power_sample_coverage_bps=10_000,
            normalized_power_w=200,
            tss=40_000 / user_ftp_w,
        )

    prepared = []
    with patch.object(
        ride_attester,
        "compute_ride_identity_bytes",
        return_value=(bytes.fromhex("ab" * 32), 3),
    ), patch.object(
        ride_attester, "parse_ride_file_bytes", return_value=parsed
    ), patch.object(
        ride_attester, "calculate_metrics", side_effect=metrics_for_ftp
    ):
        for profile_ftp_w in (50, 500):
            prepared.append(
                attester.prepare_ride(
                    file_data_b64="ZmFrZQ==",
                    file_type="fit",
                    file_bytes=b"fake",
                    ride_row={},
                    user_weight_kg=75.0,
                    user_ftp_w=profile_ftp_w,
                    reward_ftp_w=200,
                )
            )

    first, second = prepared
    assert first.metrics.tss == 800
    assert second.metrics.tss == 80
    assert first.economic_metrics.tss == second.economic_metrics.tss == 200
    policies = [
        build_ride_effort_policy(
            item.economic_metrics,
            started_at=parsed.started_at,
            completed_at=parsed.completed_at,
            now=parsed.completed_at + timedelta(hours=1),
        )
        for item in prepared
    ]
    assert [policy.rewardable_cal for policy in policies] == [200, 200]
