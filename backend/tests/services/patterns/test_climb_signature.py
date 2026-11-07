from datetime import datetime, timedelta, timezone
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.patterns.climb_signature import (
    ClimbSignatureGenerator,
    ClimbSignatureV2,
    InvalidRewardGradeQuery,
    RewardGradeMatcherUnavailable,
    match_reward_grade_v2,
)


V2_SIGNATURE_HEX = (
    "0208012901ef0258000000000000000062030000800000008000000000008000"
    "80008000000080008000800000008000e9105ad1a189212e4aaad7873984334a"
)


def _with_h3(signature_hex: str, h3_anchor: int) -> str:
    payload = bytearray.fromhex(signature_hex)
    payload[8:16] = h3_anchor.to_bytes(8, "big")
    return payload.hex()


def test_generate_from_climb_pattern_accepts_datetime_samples() -> None:
    base = datetime(2026, 6, 12, 18, 0, tzinfo=timezone.utc)
    samples = [
        {
            "t": base + timedelta(seconds=offset),
            "elevation_m": elevation,
            "lat": 40.0 + idx * 0.0001,
            "lon": -75.0,
        }
        for idx, (offset, elevation) in enumerate(
            (
                (0, 100.0),
                (10, 104.0),
                (20, 111.0),
                (30, 118.0),
            )
        )
    ]

    signature = ClimbSignatureGenerator().generate_from_climb_pattern(
        samples,
        start_time=0,
        end_time=30,
    )

    assert signature is not None
    assert signature.duration_s == 30
    assert signature.vert_m > 0


def test_v2_signature_decodes_distance_in_meters() -> None:
    signature = ClimbSignatureV2.from_hex(V2_SIGNATURE_HEX)

    assert signature is not None
    assert signature.distance_m == 4_950


def test_reward_grade_match_requires_oriented_start_and_end_proximity() -> None:
    signature_hex = _with_h3(V2_SIGNATURE_HEX, 0x8A2A1072B59FFFF)
    matcher = SimpleNamespace(
        match_signatures_v2=lambda *_args: {
            "result": "match",
            "confidence": 1.0,
            "dct_distance": 0.0,
        }
    )

    with patch.dict(sys.modules, {"workout_parse": matcher}):
        equal = match_reward_grade_v2(
            query_signature_v2_hex=signature_hex,
            candidate_signature_v2_hex=signature_hex,
            query_start=(39.9500, -75.1600),
            query_end=(39.9550, -75.1600),
            candidate_start=(39.9500, -75.1600),
            candidate_end=(39.9550, -75.1600),
        )
        reversed_trace = match_reward_grade_v2(
            query_signature_v2_hex=signature_hex,
            candidate_signature_v2_hex=signature_hex,
            query_start=(39.9550, -75.1600),
            query_end=(39.9500, -75.1600),
            candidate_start=(39.9500, -75.1600),
            candidate_end=(39.9550, -75.1600),
        )
        late_trace = match_reward_grade_v2(
            query_signature_v2_hex=signature_hex,
            candidate_signature_v2_hex=signature_hex,
            query_start=(39.9520, -75.1600),
            query_end=(39.9550, -75.1600),
            candidate_start=(39.9500, -75.1600),
            candidate_end=(39.9550, -75.1600),
        )

    assert equal is not None
    assert equal.result == "match"
    assert equal.start_distance_m == pytest.approx(0.0)
    assert equal.end_distance_m == pytest.approx(0.0)
    assert reversed_trace is None
    assert late_trace is None


def test_reward_grade_match_requires_complete_geographic_evidence() -> None:
    signature_hex = _with_h3(V2_SIGNATURE_HEX, 0x8A2A1072B59FFFF)
    matcher = SimpleNamespace(
        match_signatures_v2=lambda *_args: {
            "result": "match",
            "confidence": 1.0,
            "dct_distance": 0.0,
        }
    )

    with patch.dict(sys.modules, {"workout_parse": matcher}):
        with pytest.raises(ValueError, match="query end"):
            match_reward_grade_v2(
                query_signature_v2_hex=signature_hex,
                candidate_signature_v2_hex=signature_hex,
                query_start=(39.9500, -75.1600),
                query_end=(None, -75.1600),
                candidate_start=(39.9500, -75.1600),
                candidate_end=(39.9550, -75.1600),
            )


def test_reward_grade_match_rejects_null_island_gps_sentinel() -> None:
    matcher = SimpleNamespace(
        match_signatures_v2=lambda *_args: {
            "result": "match",
            "confidence": 1.0,
            "dct_distance": 0.0,
        }
    )

    with patch.dict(sys.modules, {"workout_parse": matcher}):
        with pytest.raises(InvalidRewardGradeQuery, match="query start.*GPS"):
            match_reward_grade_v2(
                query_signature_v2_hex=V2_SIGNATURE_HEX,
                candidate_signature_v2_hex=V2_SIGNATURE_HEX,
                query_start=(0.0, 0.0),
                query_end=(0.005, 0.0),
                candidate_start=(0.0, 0.0),
                candidate_end=(0.005, 0.0),
            )


def test_reward_grade_matcher_unavailable_fails_loud() -> None:
    signature_hex = _with_h3(V2_SIGNATURE_HEX, 0x8A2A1072B59FFFF)

    with patch.dict(sys.modules, {"workout_parse": None}):
        with pytest.raises(RewardGradeMatcherUnavailable, match="workout_parse"):
            match_reward_grade_v2(
                query_signature_v2_hex=signature_hex,
                candidate_signature_v2_hex=signature_hex,
                query_start=(39.9500, -75.1600),
                query_end=(39.9550, -75.1600),
                candidate_start=(39.9500, -75.1600),
                candidate_end=(39.9550, -75.1600),
            )


def test_corrupt_reward_grade_query_is_not_misclassified_as_candidate() -> None:
    def reject_query(*_args):
        raise ValueError("Invalid v2 signature hex (a)")

    matcher = SimpleNamespace(match_signatures_v2=reject_query)
    with patch.dict(sys.modules, {"workout_parse": matcher}):
        with pytest.raises(InvalidRewardGradeQuery, match="query.*checksum"):
            match_reward_grade_v2(
                query_signature_v2_hex=V2_SIGNATURE_HEX,
                candidate_signature_v2_hex=V2_SIGNATURE_HEX,
                query_start=(39.9500, -75.1600),
                query_end=(39.9550, -75.1600),
                candidate_start=(39.9500, -75.1600),
                candidate_end=(39.9550, -75.1600),
            )


def test_corrupt_reward_grade_query_fails_before_endpoint_rejection() -> None:
    def reject_query(*_args):
        raise ValueError("Invalid v2 signature hex (a)")

    matcher = SimpleNamespace(match_signatures_v2=reject_query)
    with patch.dict(sys.modules, {"workout_parse": matcher}):
        with pytest.raises(InvalidRewardGradeQuery, match="query.*checksum"):
            match_reward_grade_v2(
                query_signature_v2_hex=V2_SIGNATURE_HEX,
                candidate_signature_v2_hex=V2_SIGNATURE_HEX,
                query_start=(39.9500, -75.1600),
                query_end=(39.9550, -75.1600),
                candidate_start=(32.2200, -110.9700),
                candidate_end=(32.2250, -110.9700),
            )
