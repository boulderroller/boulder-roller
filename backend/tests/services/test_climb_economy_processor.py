from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from solders.pubkey import Pubkey

from app.solana_direct import (
    _derive_vault_pda,
    derive_ride_attestation_pda,
)
from app.services.climb_economy_processor import (
    ClimbEconomyProcessor,
    VaultCompletionChainError,
    is_vault_live_for_completion,
)
from app.services import ride_economic_plan_builder
from app.services.workout_parse_adapter import SegmentPowerMetricsCompat
from app.services.vault_completion_evidence import (
    build_climb_completion_evidence_v2,
)


PROGRAM_ID = Pubkey.new_unique()
V2_SIGNATURE_HEX = (
    "0208012901ef0258000000000000000062030000800000008000000000008000"
    "80008000000080008000800000008000e9105ad1a189212e4aaad7873984334a"
)
AUTHORITATIVE_ACTIVATION = {
    "activation_status": "active",
    "chain_activation_active": True,
    "chain_activation_seed_generation": 2,
    "canon_binding_status": "active",
    "canon_activation_status": "finalized",
    "canon_climb_id": "11111111-1111-1111-1111-111111111111",
    "canon_id": "22222222-2222-2222-2222-222222222222",
    "canon_version": 1,
    "canonical_profile_hash_hex": "ab" * 32,
    "chain_slot": 900,
    "expected_vault_activation_pda": "vault-activation-pda",
    "canon_activation_chain_slot": 900,
    "vault_activation_pda": "vault-activation-pda",
    "vault_activation_is_active": True,
    "vault_activation_seed_generation": 2,
    "vault_activation_seed_completions_written": 0,
    "vault_activation_leaderboard_seeded": True,
    "vault_activation_matched_users": 0,
    "vault_activation_matched_completions": 0,
    "vault_activation_created_at": 100,
    "vault_activation_activated_at": 100,
    "vault_activation_last_seed_at": 100,
    "vault_activation_seed_cutoff_at": 100,
    "vault_activation_evidence_hash": "cd" * 32,
    "constructor_evidence_verified": True,
    "constructor_evidence_hash": "cd" * 32,
    "vault_activation_chain_slot": 900,
}


def _canon_match_trace() -> dict:
    return {
        "registry_id": AUTHORITATIVE_ACTIVATION["canon_climb_id"],
        "canon_id": AUTHORITATIVE_ACTIVATION["canon_id"],
        "canon_version": AUTHORITATIVE_ACTIVATION["canon_version"],
        "profile_hash": AUTHORITATIVE_ACTIVATION["canonical_profile_hash_hex"],
    }


def _canonical_vault(**overrides) -> dict:
    value = {
        "id": 42,
        "name": "Test Wall",
        **AUTHORITATIVE_ACTIVATION,
    }
    value.update(overrides)
    return value


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("constructor_evidence_verified", False),
        ("constructor_evidence_hash", "ef" * 32),
        ("vault_activation_pda", "wrong-pda"),
        ("vault_activation_is_active", False),
        ("vault_activation_seed_generation", 3),
        ("vault_activation_seed_completions_written", 1),
        ("vault_activation_leaderboard_seeded", False),
        ("vault_activation_matched_users", 1),
        ("vault_activation_matched_completions", 1),
        ("vault_activation_activated_at", 101),
        ("vault_activation_evidence_hash", "0" * 64),
    ],
)
def test_completion_authority_rejects_nonconstructor_activation_evidence(
    field: str,
    value: object,
) -> None:
    assert is_vault_live_for_completion(_canonical_vault(**{field: value})) is False


def test_completion_authority_survives_later_vault_and_activation_observation_slots() -> None:
    assert is_vault_live_for_completion(
        _canonical_vault(chain_slot=950, vault_activation_chain_slot=975)
    ) is True


@pytest.mark.asyncio
async def test_exact_repository_binding_builds_one_completion_without_generic_refetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ride_economic_plan_builder,
        "calculate_segment_power_metrics_rust",
        lambda *_args, **_kwargs: SegmentPowerMetricsCompat(
            normalized_power_w=240,
            normalized_power_milliwatts=240_000,
            normalized_power_duration_s=60,
            power_sample_count=60,
            power_sample_coverage_bps=10_000,
            moving_time_s=60,
            metrics_version="workout_parse_metrics_v1",
        ),
    )
    exact_binding = _canonical_vault(
        signature_hex="ab" * 64,
        signature_hash_hex="cd" * 32,
    )
    vault_repo = MagicMock()
    vault_repo.find_canon_vault_binding = AsyncMock(return_value=exact_binding)
    vault_repo.get_vault_by_id = AsyncMock(
        return_value={
            "id": 42,
            "signature_hex": "ab" * 64,
            "chain_activation_active": True,
            "chain_activation_seed_generation": 2,
        }
    )
    vault_repo.validate_climb_time = AsyncMock(return_value={"is_valid": True})
    ride_executor = MagicMock()
    ride_executor.build_completion_evidence_v2.return_value = b"e" * 32
    processor = ClimbEconomyProcessor(
        user_repo=MagicMock(),
        vault_repo=vault_repo,
        vault_service=MagicMock(),
        ride_executor=ride_executor,
        projection_writer=MagicMock(),
    )
    climb = SimpleNamespace(
        id=uuid4(),
        match_trace=_canon_match_trace(),
        economic_eligible=False,
        abstention_reasons=["MATCH:canon_activation_required"],
        detector_version="canon_traversal_v1",
        time_s=60,
        distance_m=600,
        vert_m=60,
        start_offset_s=0,
        end_offset_s=59,
        start_time_offset_s=0,
        end_time_offset_s=59,
        start_lat=None,
        start_lon=None,
        end_lat=None,
        end_lon=None,
    )

    steps, allocations = await processor.build_completion_plan(
        climb_patterns=[climb],
        tile_samples=[],
        raw_climb_samples=[],
        user_id=uuid4(),
        user_wallet="wallet-1",
        ride_id=uuid4(),
        ride_hash=b"r" * 32,
        completed_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
        exact_ride_cal_base_units=10_000_000_000,
        total_ride_duration_s=60,
        reward_ftp_w=200,
    )

    assert len(steps) == 1
    assert len(allocations) == 1
    assert steps[0].vault_id == 42
    assert steps[0].vault_signature == "ab" * 64
    vault_repo.find_canon_vault_binding.assert_awaited_once()
    vault_repo.get_vault_by_id.assert_not_awaited()


@pytest.mark.asyncio
async def test_exact_binding_cannot_clear_nonactivation_sensor_abstention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ride_economic_plan_builder,
        "calculate_segment_power_metrics_rust",
        lambda *_args, **_kwargs: SegmentPowerMetricsCompat(
            normalized_power_w=240,
            normalized_power_milliwatts=240_000,
            normalized_power_duration_s=60,
            power_sample_count=60,
            power_sample_coverage_bps=10_000,
            moving_time_s=60,
            metrics_version="workout_parse_metrics_v1",
        ),
    )
    exact_binding = _canonical_vault(
        signature_hex="ab" * 64,
        signature_hash_hex="cd" * 32,
    )
    vault_repo = MagicMock()
    vault_repo.find_canon_vault_binding = AsyncMock(return_value=exact_binding)
    vault_repo.validate_climb_time = AsyncMock(return_value={"is_valid": True})
    processor = ClimbEconomyProcessor(
        user_repo=MagicMock(),
        vault_repo=vault_repo,
        vault_service=MagicMock(),
        ride_executor=MagicMock(),
        projection_writer=MagicMock(),
    )
    climb = SimpleNamespace(
        id=uuid4(),
        match_trace=_canon_match_trace(),
        economic_eligible=False,
        abstention_reasons=[
            "MATCH:canon_activation_required",
            "SENSOR:gps_coverage_0%",
        ],
        detector_version="canon_traversal_v1",
        time_s=60,
        distance_m=600,
        vert_m=60,
        start_offset_s=0,
        end_offset_s=59,
        start_time_offset_s=0,
        end_time_offset_s=59,
        start_lat=None,
        start_lon=None,
        end_lat=None,
        end_lon=None,
    )

    steps, allocations = await processor.build_completion_plan(
        climb_patterns=[climb],
        tile_samples=[],
        raw_climb_samples=[],
        user_id=uuid4(),
        user_wallet="wallet-1",
        ride_id=uuid4(),
        ride_hash=b"r" * 32,
        completed_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
        exact_ride_cal_base_units=1_000,
        total_ride_duration_s=60,
        reward_ftp_w=200,
    )

    assert steps == []
    assert allocations == []
    assert climb.economic_eligible is False
    assert climb.abstention_reasons == ["SENSOR:gps_coverage_0%"]
    vault_repo.validate_climb_time.assert_not_awaited()


def _reward_grade_climb(**overrides):
    values = {
        "signature_hex": "ab" * 32,
        "signature_v2_hex": V2_SIGNATURE_HEX,
        "economic_eligible": True,
        "vert_m": 120.0,
        "distance_m": 1_500.0,
        "time_s": 480,
        "avg_gradient_pct": 8.0,
        "start_offset_s": None,
        "end_offset_s": None,
        "start_lat": 39.9500,
        "start_lon": -75.1600,
        "end_lat": 39.9550,
        "end_lon": -75.1600,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _completion_hash(**kwargs) -> bytes:
    rider = Pubkey.from_string(kwargs["rider_wallet"])
    attestation, _ = derive_ride_attestation_pda(
        rider, kwargs["ride_hash"], PROGRAM_ID
    )
    vault, _ = _derive_vault_pda(kwargs["vault_id"], PROGRAM_ID)
    return build_climb_completion_evidence_v2(
        ride_attestation=attestation,
        vault=vault,
        completion_time_s=kwargs["completion_time_s"],
        cal_tribute=kwargs["cal_tribute"],
    )


@pytest.mark.asyncio
async def test_completion_plan_uses_one_frozen_wallet_snapshot_for_all_evidence(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        ride_economic_plan_builder,
        "calculate_segment_power_metrics_rust",
        lambda *_args, **_kwargs: SegmentPowerMetricsCompat(
            normalized_power_w=240,
            normalized_power_milliwatts=240_000,
            normalized_power_duration_s=300,
            power_sample_count=300,
            power_sample_coverage_bps=10_000,
            moving_time_s=300,
            metrics_version="workout_parse_metrics_v1",
        ),
    )
    frozen_wallet = str(Pubkey.new_unique())
    later_wallet = str(Pubkey.new_unique())
    user_repo = MagicMock()
    user_repo.get_user_wallet = AsyncMock(return_value=later_wallet)
    signature_hashes = {
        41: bytes.fromhex("41" * 32),
        42: bytes.fromhex("42" * 32),
    }
    vault_repo = MagicMock()
    vault_repo.get_vault_by_id = AsyncMock(
        side_effect=lambda vault_id: {
            "id": vault_id,
            "signature_hex": f"vault-{vault_id}",
            "signature_hash_hex": signature_hashes[vault_id].hex(),
            **AUTHORITATIVE_ACTIVATION,
        }
    )
    vault_repo.validate_climb_time = AsyncMock(return_value={"is_valid": True})
    ride_executor = MagicMock()
    ride_executor.build_completion_evidence_v2.side_effect = _completion_hash
    processor = ClimbEconomyProcessor(
        user_repo=user_repo,
        vault_repo=vault_repo,
        vault_service=MagicMock(),
        ride_executor=ride_executor,
        projection_writer=MagicMock(),
    )
    processor.match_climbs_to_vault = AsyncMock(return_value=(0, []))
    ride_id = uuid4()
    completed_at = datetime(2026, 7, 13, 13, 0, tzinfo=timezone.utc)
    ride_hash = bytes.fromhex("ab" * 32)
    climbs = [
        SimpleNamespace(
            id=uuid4(),
            indexed_vault_id=vault_id,
            canon_vault_binding={
                "id": vault_id,
                "signature_hex": f"vault-{vault_id}",
                "signature_hash_hex": signature_hashes[vault_id].hex(),
                **AUTHORITATIVE_ACTIVATION,
            },
            economic_eligible=True,
            time_s=300 + index,
            avg_gradient_pct=8.0,
            distance_m=1200,
            vert_m=120,
            start_time_offset_s=index * 400,
            end_time_offset_s=index * 400 + 299 + index,
        )
        for index, vault_id in enumerate((41, 42))
    ]

    steps, _ = await processor.build_completion_plan(
        climb_patterns=climbs,
        tile_samples=[],
        raw_climb_samples=[],
        user_id=uuid4(),
        user_wallet=frozen_wallet,
        ride_id=ride_id,
        ride_hash=ride_hash,
        completed_at=completed_at,
        exact_ride_cal_base_units=50_000_000_000,
        total_ride_duration_s=1_000,
        reward_ftp_w=200,
    )

    expected = [
        _completion_hash(
            rider_wallet=frozen_wallet,
            ride_hash=ride_hash,
            vault_id=climb.indexed_vault_id,
            completion_time_s=climb.time_s,
            cal_tribute=12_000_000_000,
        )
        for index, climb in enumerate(climbs)
    ]
    later_wallet_hashes = [
        _completion_hash(
            rider_wallet=later_wallet,
            ride_hash=ride_hash,
            vault_id=climb.indexed_vault_id,
            completion_time_s=climb.time_s,
            cal_tribute=12_000_000_000,
        )
        for index, climb in enumerate(climbs)
    ]

    assert [step.completion_evidence_hash for step in steps] == expected
    assert [step.completion_evidence_hash for step in steps] != later_wallet_hashes
    assert (
        processor.match_climbs_to_vault.await_args.kwargs["user_wallet"]
        == frozen_wallet
    )
    user_repo.get_user_wallet.assert_not_awaited()


@pytest.mark.asyncio
async def test_completion_plan_conserves_ride_cal_across_multiple_steep_climbs(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        ride_economic_plan_builder,
        "calculate_segment_power_metrics_rust",
        lambda *_args, **_kwargs: SegmentPowerMetricsCompat(
            normalized_power_w=240,
            normalized_power_milliwatts=240_000,
            normalized_power_duration_s=500,
            power_sample_count=500,
            power_sample_coverage_bps=10_000,
            moving_time_s=500,
            metrics_version="workout_parse_metrics_v1",
        ),
    )
    vault_repo = MagicMock()
    vault_repo.get_vault_by_id = AsyncMock(
        side_effect=lambda vault_id: {
            "id": vault_id,
            "signature_hex": f"vault-{vault_id}",
            "signature_hash_hex": f"{vault_id:02x}" * 32,
            **AUTHORITATIVE_ACTIVATION,
        }
    )
    vault_repo.validate_climb_time = AsyncMock(return_value={"is_valid": True})
    ride_executor = MagicMock()
    ride_executor.build_completion_evidence_v2.side_effect = _completion_hash
    processor = ClimbEconomyProcessor(
        user_repo=MagicMock(),
        vault_repo=vault_repo,
        vault_service=MagicMock(),
        ride_executor=ride_executor,
        projection_writer=MagicMock(),
    )
    processor.match_climbs_to_vault = AsyncMock(return_value=(0, []))
    climbs = [
        SimpleNamespace(
            id=UUID(f"00000000-0000-0000-0000-{vault_id:012d}"),
            indexed_vault_id=vault_id,
            canon_vault_binding={
                "id": vault_id,
                "signature_hex": f"vault-{vault_id}",
                "signature_hash_hex": f"{vault_id:02x}" * 32,
                **AUTHORITATIVE_ACTIVATION,
            },
            economic_eligible=True,
            time_s=500,
            avg_gradient_pct=10.0,
            distance_m=1_000,
            vert_m=100,
        )
        for index, vault_id in enumerate((41, 42))
    ]
    for index, climb in enumerate(climbs):
        climb.start_time_offset_s = index * 500
        climb.end_time_offset_s = index * 500 + 499

    ride_hash = bytes.fromhex("cd" * 32)
    wallet = str(Pubkey.new_unique())
    steps, allocations = await processor.build_completion_plan(
        climb_patterns=climbs,
        tile_samples=[],
        raw_climb_samples=[],
        user_id=uuid4(),
        user_wallet=wallet,
        ride_id=uuid4(),
        ride_hash=ride_hash,
        completed_at=datetime(2026, 7, 13, 13, 0, tzinfo=timezone.utc),
        exact_ride_cal_base_units=100_000_000_000,
        total_ride_duration_s=1_000,
        reward_ftp_w=200,
    )

    expected_tributes = [20_000_000_000, 20_000_000_000]
    assert [step.exact_tribute_base_units for step in steps] == expected_tributes
    assert [allocation["cal_tribute"] for allocation in allocations] == expected_tributes
    assert sum(expected_tributes) == 40_000_000_000
    assert [step.completion_evidence_hash for step in steps] == [
        _completion_hash(
            rider_wallet=wallet,
            ride_hash=ride_hash,
            vault_id=step.vault_id,
            completion_time_s=step.completion_time_s,
            cal_tribute=tribute,
        )
        for step, tribute in zip(steps, expected_tributes)
    ]


@pytest.mark.asyncio
async def test_ineligible_climbs_do_not_record_vault_economics():
    user_repo = MagicMock()
    user_repo.get_user_wallet = AsyncMock(return_value="wallet-1")
    vault_repo = MagicMock()
    vault_service = MagicMock()
    vault_service.match_climb_pattern = AsyncMock()
    ride_executor = MagicMock()
    projection_writer = MagicMock()
    processor = ClimbEconomyProcessor(
        user_repo=user_repo,
        vault_repo=vault_repo,
        vault_service=vault_service,
        ride_executor=ride_executor,
        projection_writer=projection_writer,
    )
    climb = SimpleNamespace(
        signature_hex="ab" * 32,
        economic_eligible=False,
        abstention_reasons=["EFFORT:route_estimate_only"],
    )

    distributed, allocations = await processor.match_climbs_to_vault(
        climb_patterns=[climb],
        tile_samples=[],
        user_id=uuid4(),
        ride_id=uuid4(),
        completed_at=MagicMock(),
        cal_earned=100,
        total_ride_duration_s=600,
        ride_hash=b"1" * 32,
    )

    assert distributed == 0
    assert allocations == []
    vault_service.match_climb_pattern.assert_not_awaited()


@pytest.mark.asyncio
async def test_canon_traversal_uses_only_exact_active_registry_binding():
    registry_id = uuid4()
    canon_id = uuid4()
    profile_hash = "ab" * 32
    vault_repo = MagicMock()
    vault_repo.find_canon_vault_binding = AsyncMock(
        return_value={
            "id": 42,
            "name": "Canonical Vault",
            "canon_climb_id": str(registry_id),
            "canon_id": str(canon_id),
            "canon_version": 3,
            "canonical_profile_hash_hex": profile_hash,
            **AUTHORITATIVE_ACTIVATION,
        }
    )
    vault_repo.find_reward_grade_vault_matches = AsyncMock()
    processor = ClimbEconomyProcessor(
        user_repo=MagicMock(),
        vault_repo=vault_repo,
        vault_service=MagicMock(),
        ride_executor=MagicMock(),
        projection_writer=MagicMock(),
    )
    climb = SimpleNamespace(
        economic_eligible=True,
        match_trace={
            "registry_id": str(registry_id),
            "canon_id": str(canon_id),
            "canon_version": 3,
            "profile_hash": profile_hash,
        },
        vert_m=100,
    )

    distributed, allocations = await processor.match_climbs_to_vault(
        climb_patterns=[climb],
        tile_samples=[],
        user_id=uuid4(),
        user_wallet="wallet-1",
        ride_id=uuid4(),
        completed_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
        ride_hash=None,
    )

    assert (distributed, allocations) == (0, [])
    assert climb.indexed_vault_id == 42
    vault_repo.find_canon_vault_binding.assert_awaited_once_with(
        registry_id=registry_id,
        canon_id=canon_id,
        canon_version=3,
        profile_hash_hex=profile_hash,
    )
    vault_repo.find_reward_grade_vault_matches.assert_not_awaited()


@pytest.mark.asyncio
async def test_detector_pattern_is_discovery_only_and_always_abstains_economically():
    vault_repo = MagicMock()
    vault_repo.find_canon_vault_binding = AsyncMock()
    vault_repo.find_reward_grade_vault_matches = AsyncMock(
        return_value=[{"id": 42, "name": "Legacy Detector Vault"}]
    )
    processor = ClimbEconomyProcessor(
        user_repo=MagicMock(),
        vault_repo=vault_repo,
        vault_service=MagicMock(),
        ride_executor=MagicMock(),
        projection_writer=MagicMock(),
    )
    climb = _reward_grade_climb()

    distributed, allocations = await processor.match_climbs_to_vault(
        climb_patterns=[climb],
        tile_samples=[],
        user_id=uuid4(),
        user_wallet="wallet-1",
        ride_id=uuid4(),
        completed_at=datetime(2026, 7, 21, tzinfo=timezone.utc),
        ride_hash=None,
    )

    assert (distributed, allocations) == (0, [])
    assert climb.economic_eligible is False
    assert "MATCH:canon_traversal_required" in climb.abstention_reasons
    vault_repo.find_canon_vault_binding.assert_not_awaited()
    vault_repo.find_reward_grade_vault_matches.assert_not_awaited()


@pytest.mark.asyncio
async def test_reward_economics_never_fall_back_to_legacy_signature_matching():
    user_repo = MagicMock()
    user_repo.get_user_wallet = AsyncMock(return_value="wallet-1")
    vault_repo = MagicMock()
    vault_repo.find_canon_vault_binding = AsyncMock()
    vault_repo.find_reward_grade_vault_matches = AsyncMock(return_value=[])
    vault_repo.get_vault_by_signature_hash = AsyncMock(
        return_value={"id": 99, "name": "Wrong City", **AUTHORITATIVE_ACTIVATION}
    )
    vault_repo.find_vaults_by_signature_similarity = AsyncMock(
        return_value=[{"id": 99, "name": "Wrong City", "_similarity": 1.0}]
    )
    vault_service = MagicMock()
    vault_service.match_climb_pattern = AsyncMock(return_value=[])
    processor = ClimbEconomyProcessor(
        user_repo=user_repo,
        vault_repo=vault_repo,
        vault_service=vault_service,
        ride_executor=MagicMock(),
        projection_writer=MagicMock(),
    )

    climb = _reward_grade_climb()
    distributed, allocations = await processor.match_climbs_to_vault(
        climb_patterns=[climb],
        tile_samples=[],
        user_id=uuid4(),
        ride_id=uuid4(),
        completed_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        cal_earned=100,
        total_ride_duration_s=600,
        ride_hash=b"1" * 32,
    )

    assert distributed == 0
    assert allocations == []
    assert "MATCH:canon_traversal_required" in climb.abstention_reasons
    vault_repo.find_canon_vault_binding.assert_not_awaited()
    vault_repo.find_reward_grade_vault_matches.assert_not_awaited()
    vault_repo.get_vault_by_signature_hash.assert_not_awaited()
    vault_repo.find_vaults_by_signature_similarity.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_exact_canon_binding_abstains_without_tribute():
    user_repo = MagicMock()
    user_repo.get_user_wallet = AsyncMock(return_value="wallet-1")
    vault_repo = MagicMock()
    vault_repo.find_canon_vault_binding = AsyncMock(return_value=None)
    vault_repo.find_reward_grade_vault_matches = AsyncMock()
    vault_service = MagicMock()
    vault_service.match_climb_pattern = AsyncMock(return_value=[])
    processor = ClimbEconomyProcessor(
        user_repo=user_repo,
        vault_repo=vault_repo,
        vault_service=vault_service,
        ride_executor=MagicMock(),
        projection_writer=MagicMock(),
    )
    climb = _reward_grade_climb(match_trace=_canon_match_trace())

    distributed, allocations = await processor.match_climbs_to_vault(
        climb_patterns=[climb],
        tile_samples=[],
        user_id=uuid4(),
        ride_id=uuid4(),
        completed_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        cal_earned=100,
        total_ride_duration_s=600,
        ride_hash=None,
        strict=True,
    )

    assert distributed == 0
    assert allocations == []
    assert climb.economic_eligible is False
    assert "MATCH:canon_activation_required" in climb.abstention_reasons
    vault_repo.find_canon_vault_binding.assert_awaited_once()
    vault_repo.find_reward_grade_vault_matches.assert_not_awaited()


@pytest.mark.asyncio
async def test_discovery_match_failure_cannot_block_exact_canon_binding():
    user_repo = MagicMock()
    user_repo.get_user_wallet = AsyncMock(return_value="wallet-1")
    vault_repo = MagicMock()
    vault_repo.find_canon_vault_binding = AsyncMock(return_value=_canonical_vault())
    vault_repo.find_reward_grade_vault_matches = AsyncMock()
    vault_service = MagicMock()
    vault_service.match_climb_pattern = AsyncMock(
        side_effect=RuntimeError("discovery index unavailable")
    )
    processor = ClimbEconomyProcessor(
        user_repo=user_repo,
        vault_repo=vault_repo,
        vault_service=vault_service,
        ride_executor=MagicMock(),
        projection_writer=MagicMock(),
    )

    distributed, allocations = await processor.match_climbs_to_vault(
        climb_patterns=[_reward_grade_climb(match_trace=_canon_match_trace())],
        tile_samples=[],
        user_id=uuid4(),
        ride_id=uuid4(),
        completed_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        ride_hash=None,
        strict=True,
    )

    assert distributed == 0
    assert allocations == []
    vault_repo.find_canon_vault_binding.assert_awaited_once()
    vault_repo.find_reward_grade_vault_matches.assert_not_awaited()
    vault_service.match_climb_pattern.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_canon_trace_abstains_before_legacy_matching():
    user_repo = MagicMock()
    user_repo.get_user_wallet = AsyncMock(return_value="wallet-1")
    vault_repo = MagicMock()
    vault_repo.find_reward_grade_vault_matches = AsyncMock()
    vault_repo.get_vault_by_signature_hash = AsyncMock(
        return_value={"id": 42, "name": "Legacy Match", **AUTHORITATIVE_ACTIVATION}
    )
    vault_service = MagicMock()
    vault_service.match_climb_pattern = AsyncMock(return_value=[])
    processor = ClimbEconomyProcessor(
        user_repo=user_repo,
        vault_repo=vault_repo,
        vault_service=vault_service,
        ride_executor=MagicMock(),
        projection_writer=MagicMock(),
    )
    climb = _reward_grade_climb(signature_v2_hex=None, end_lat=None)

    distributed, allocations = await processor.match_climbs_to_vault(
        climb_patterns=[climb],
        tile_samples=[],
        user_id=uuid4(),
        ride_id=uuid4(),
        completed_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        cal_earned=100,
        total_ride_duration_s=600,
        ride_hash=b"1" * 32,
    )

    assert distributed == 0
    assert allocations == []
    assert climb.economic_eligible is False
    assert "MATCH:canon_traversal_required" in climb.abstention_reasons
    vault_repo.find_reward_grade_vault_matches.assert_not_awaited()
    vault_repo.get_vault_by_signature_hash.assert_not_awaited()


@pytest.mark.asyncio
async def test_geographic_query_cannot_override_exact_canon_binding():
    user_repo = MagicMock()
    user_repo.get_user_wallet = AsyncMock(return_value="wallet-1")
    vault_repo = MagicMock()
    vault_repo.find_canon_vault_binding = AsyncMock(return_value=_canonical_vault())
    vault_repo.find_reward_grade_vault_matches = AsyncMock()
    vault_service = MagicMock()
    vault_service.match_climb_pattern = AsyncMock(return_value=[])
    processor = ClimbEconomyProcessor(
        user_repo=user_repo,
        vault_repo=vault_repo,
        vault_service=vault_service,
        ride_executor=MagicMock(),
        projection_writer=MagicMock(),
    )
    climb = _reward_grade_climb(
        start_lat=0.0,
        start_lon=0.0,
        match_trace=_canon_match_trace(),
    )

    distributed, allocations = await processor.match_climbs_to_vault(
        climb_patterns=[climb],
        tile_samples=[],
        user_id=uuid4(),
        ride_id=uuid4(),
        completed_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
        cal_earned=100,
        total_ride_duration_s=600,
        ride_hash=None,
        strict=True,
    )

    assert distributed == 0
    assert allocations == []
    assert climb.economic_eligible is True
    assert climb.indexed_vault_id == 42
    vault_repo.find_canon_vault_binding.assert_awaited_once()
    vault_repo.find_reward_grade_vault_matches.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_ride_hash_enriches_vault_match_without_reward_side_effects():
    user_repo = MagicMock()
    user_repo.get_user_wallet = AsyncMock(return_value="wallet-1")
    vault_repo = MagicMock()
    vault_repo.find_canon_vault_binding = AsyncMock(
        return_value=_canonical_vault(
            start_lat=39.95,
            start_lon=-75.16,
            end_lat=39.955,
            end_lon=-75.16,
            polyline_json=[[39.95, -75.16]],
        )
    )
    vault_repo.record_completion = AsyncMock()
    vault_service = MagicMock()
    vault_service.match_climb_pattern = AsyncMock(return_value=[])
    ride_executor = MagicMock()
    ride_executor.record_climb_completion = AsyncMock()
    projection_writer = MagicMock()
    processor = ClimbEconomyProcessor(
        user_repo=user_repo,
        vault_repo=vault_repo,
        vault_service=vault_service,
        ride_executor=ride_executor,
        projection_writer=projection_writer,
    )
    climb = _reward_grade_climb(match_trace=_canon_match_trace())

    distributed, allocations = await processor.match_climbs_to_vault(
        climb_patterns=[climb],
        tile_samples=[],
        user_id=uuid4(),
        ride_id=uuid4(),
        completed_at=MagicMock(),
        cal_earned=100,
        total_ride_duration_s=600,
        ride_hash=None,
    )

    assert distributed == 0
    assert allocations == []
    assert climb.indexed_vault_id == 42
    assert climb.indexed_vault_name == "Test Wall"
    vault_repo.record_completion.assert_not_awaited()
    ride_executor.record_climb_completion.assert_not_awaited()
    projection_writer.mirror_completion_tx.assert_not_called()
    projection_writer.mirror_completion_tx_error.assert_not_called()


@pytest.mark.asyncio
async def test_direct_completion_path_cannot_bypass_frozen_plan_validation():
    user_repo = MagicMock()
    user_repo.get_user_wallet = AsyncMock(
        return_value="11111111111111111111111111111111"
    )
    vault_repo = MagicMock()
    vault_repo.find_canon_vault_binding = AsyncMock(
        return_value=_canonical_vault(
            start_lat=39.95,
            start_lon=-75.16,
            end_lat=39.955,
            end_lon=-75.16,
            polyline_json=[[39.95, -75.16]],
        )
    )
    vault_repo.record_completion = AsyncMock(
        return_value={
            "validated": False,
            "validation_notes": "Time 12s is impossibly fast (min: 95s)",
        }
    )
    vault_service = MagicMock()
    vault_service.match_climb_pattern = AsyncMock(return_value=[])
    ride_executor = MagicMock()
    ride_executor.record_climb_completion = AsyncMock(return_value="tx-sig")
    projection_writer = MagicMock()
    processor = ClimbEconomyProcessor(
        user_repo=user_repo,
        vault_repo=vault_repo,
        vault_service=vault_service,
        ride_executor=ride_executor,
        projection_writer=projection_writer,
    )
    climb = _reward_grade_climb(time_s=12, match_trace=_canon_match_trace())

    with pytest.raises(VaultCompletionChainError, match="freeze and execute"):
        await processor.match_climbs_to_vault(
            climb_patterns=[climb],
            tile_samples=[],
            user_id=uuid4(),
            ride_id=uuid4(),
            completed_at=datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc),
            cal_earned=100,
            total_ride_duration_s=600,
            ride_hash=b"1" * 32,
        )

    ride_executor.record_climb_completion.assert_not_awaited()
    projection_writer.mirror_completion_tx.assert_not_called()
    projection_writer.mirror_completion_tx_error.assert_not_called()


@pytest.mark.asyncio
async def test_per_climb_chain_failure_is_not_swallowed() -> None:
    user_repo = MagicMock()
    user_repo.get_user_wallet = AsyncMock(
        return_value="11111111111111111111111111111111"
    )
    vault_repo = MagicMock()
    vault_repo.find_canon_vault_binding = AsyncMock(
        return_value=_canonical_vault(
            start_lat=39.95,
            start_lon=-75.16,
            end_lat=39.955,
            end_lon=-75.16,
            polyline_json=[[39.95, -75.16]],
        )
    )
    vault_repo.record_completion = AsyncMock(return_value={"validated": True})
    vault_service = MagicMock()
    vault_service.match_climb_pattern = AsyncMock(return_value=[])
    ride_executor = MagicMock()
    ride_executor.record_climb_completion = AsyncMock(
        side_effect=RuntimeError("rpc unavailable")
    )
    projection_writer = MagicMock()
    processor = ClimbEconomyProcessor(
        user_repo=user_repo,
        vault_repo=vault_repo,
        vault_service=vault_service,
        ride_executor=ride_executor,
        projection_writer=projection_writer,
    )
    climb = _reward_grade_climb(match_trace=_canon_match_trace())

    with pytest.raises(VaultCompletionChainError, match="freeze and execute"):
        await processor.match_climbs_to_vault(
            climb_patterns=[climb],
            tile_samples=[],
            user_id=uuid4(),
            ride_id=uuid4(),
            completed_at=datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc),
            cal_earned=100,
            total_ride_duration_s=600,
            ride_hash=b"1" * 32,
        )
    ride_executor.record_climb_completion.assert_not_awaited()


@pytest.mark.asyncio
async def test_project_vault_enrichment_accepts_datetime_tile_sample_times():
    user_repo = MagicMock()
    user_repo.get_user_wallet = AsyncMock(return_value="wallet-1")
    vault_repo = MagicMock()
    vault_repo.find_canon_vault_binding = AsyncMock(
        return_value=_canonical_vault(
            start_lat=40.0,
            start_lon=-105.0,
            end_lat=40.004,
            end_lon=-105.004,
            polyline_json=None,
        )
    )
    vault_service = MagicMock()
    vault_service.match_climb_pattern = AsyncMock(return_value=[])
    ride_executor = MagicMock()
    ride_executor.record_climb_completion = AsyncMock()
    projection_writer = MagicMock()
    processor = ClimbEconomyProcessor(
        user_repo=user_repo,
        vault_repo=vault_repo,
        vault_service=vault_service,
        ride_executor=ride_executor,
        projection_writer=projection_writer,
    )
    climb = _reward_grade_climb(
        indexed_vault_id=42,
        vault_match_similarity=0.96,
        start_offset_s=10,
        end_offset_s=50,
        start_lat=40.0,
        start_lon=-105.0,
        end_lat=40.004,
        end_lon=-105.004,
        match_trace=_canon_match_trace(),
    )
    base_time = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)
    tile_samples = [
        {
            "t": base_time + timedelta(seconds=offset),
            "lat": 40.0 + offset / 10000,
            "lon": -105.0 - offset / 10000,
        }
        for offset in range(0, 60, 10)
    ]

    distributed, allocations = await processor.match_climbs_to_vault(
        climb_patterns=[climb],
        tile_samples=tile_samples,
        user_id=uuid4(),
        ride_id=uuid4(),
        completed_at=base_time,
        cal_earned=100,
        total_ride_duration_s=600,
        ride_hash=None,
    )

    assert distributed == 0
    assert allocations == []
    projection_writer.backfill_vault_polyline.assert_called_once()
    _, kwargs = projection_writer.backfill_vault_polyline.call_args
    assert kwargs["vault_id"] == 42
    assert kwargs["polyline_data"] == [
        [40.001, -105.001],
        [40.002, -105.002],
        [40.003, -105.003],
        [40.004, -105.004],
        [40.005, -105.005],
    ]
