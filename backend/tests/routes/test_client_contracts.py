from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.dependencies import AuthenticatedUser
from app.client_contracts import (
    CLIENT_CONTRACT_VERSION,
    CLIENT_CONTRACT_MODELS,
    ClimbSummary,
    RecordBoard,
    RecordBoardEntry,
    RideAttestationStatus,
    RideClimbEarning,
    RideEffortEconomy,
    RideEarnings,
    RideInputQuality,
    RideProgression,
    RideStatusResponse,
    SettlementStatus,
    TruthSource,
    VaultEconomy,
    client_contract_json_schema,
)
from app.routes.climbs import build_climb_response
from app.routes.rides import (
    _build_ride_status_response,
    _fetch_ride_climb_earnings,
    get_ride,
    get_ride_status,
)


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "client_v1"


FIXTURE_MODELS = {
    "climb_summary.json": ClimbSummary,
    "record_board.json": RecordBoard,
    "ride_attestation_status.json": RideAttestationStatus,
    "ride_earnings.json": RideEarnings,
    "ride_status_response.json": RideStatusResponse,
    "settlement_status.json": SettlementStatus,
    "vault_economy.json": VaultEconomy,
}


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_threshold_hold_policy_is_a_valid_release_aware_client_state() -> None:
    held = RideEffortEconomy(
        effort_evidence_tier="power_verified",
        reward_policy="threshold_provisional_hold_v1",
        estimated_cal=84,
        rewardable_cal=0,
        tributable_cal=0,
        threshold_economy_state="held",
    )

    assert held.reward_policy == "threshold_provisional_hold_v1"
    assert held.threshold_economy_state == "held"


def test_finalized_completion_receipt_without_tx_is_still_onchain_truth() -> None:
    ride_id = str(uuid4())
    repo = MagicMock()
    table_data = {
        "vault_completions": [
            {
                "vault_signature": "sig-finalized",
                "wallet": "wallet-1",
                "activity_id": ride_id,
                "time_seconds": 412,
                "completed_at": "2026-07-13T13:00:00+00:00",
                "on_chain_tx": None,
                "cal_tribute": 104,
                "chain_confirmation_status": "confirmed",
                "completion_receipt_pda": "CompletionPda111",
                "completion_evidence_hash": "\\x" + "ab" * 32,
                "completion_evidence_version": 2,
                "chain_confirmed_at": "2026-07-13T13:01:00+00:00",
            }
        ],
        "indexed_vaults": [
            {
                "id": 142,
                "name": "Manayunk Wall",
                "signature_hex": "sig-finalized",
                "pda": "VaultPda111",
            }
        ],
        "indexed_leaderboards": [],
    }

    def table(name: str):
        query = MagicMock()
        query.select.return_value = query
        query.eq.return_value = query
        query.in_.return_value = query
        query.execute.return_value.data = table_data.get(name, [])
        return query

    repo.client.table.side_effect = table

    earnings = _fetch_ride_climb_earnings(
        repo,
        ride_id,
        {"wallet": "wallet-1"},
    )

    assert len(earnings) == 1
    assert earnings[0].truth_source == TruthSource.onchain
    assert earnings[0].tribute_truth_source == TruthSource.onchain
    assert earnings[0].completion_evidence_version == 2
    assert earnings[0].tribute_bound is True
    assert earnings[0].tx_signature is None


def test_climb_summary_mirrors_optional_vault_economy_for_rollout_compatibility():
    climb = ClimbSummary(
        id="climb-1",
        name="Hawk Hill",
        vault_economy=VaultEconomy(
            has_vault=True,
            vault_id=7,
            vault_signature="ab" * 32,
            total_staked="123",
            total_staked_base_units="123000000000",
            total_cal_staked="123",
            total_cal_staked_base_units="123000000000",
            total_completions=4,
        ),
    )

    assert climb.contract_version == CLIENT_CONTRACT_VERSION
    assert climb.truth_source == TruthSource.projected
    assert climb.vault_id == 7
    assert climb.has_vault is True
    assert climb.total_staked == "123"
    assert climb.total_staked_base_units == "123000000000"
    assert climb.vault_economy.vault_id == 7


def test_build_climb_response_exposes_canonical_vault_economy_and_flat_aliases():
    response = build_climb_response(
        {
            "id": "climb-1",
            "name": "Hawk Hill",
            "distance_m": 2500,
            "total_vert_m": 210,
            "signature_hex": "cd" * 32,
        },
        {
            "id": 9,
            "signature_hex": "cd" * 32,
            "total_staked": 5000,
            "total_completions": 12,
        },
    )

    dumped = response.model_dump()
    assert dumped["contract_version"] == CLIENT_CONTRACT_VERSION
    assert dumped["vault_economy"]["has_vault"] is True
    assert dumped["vault_economy"]["vault_id"] == 9
    assert dumped["vault_id"] == 9
    assert dumped["has_vault"] is True


def test_build_climb_response_uses_active_cal_not_deprecated_vault_slot():
    response = build_climb_response(
        {
            "id": "climb-exact",
            "name": "Exact Hill",
            "distance_m": 2500,
            "total_vert_m": 210,
            "signature_hex": "ef" * 32,
        },
        {
            "id": 10,
            "signature_hex": "ef" * 32,
            "total_staked": 999_000_000_000,
            "total_cal_staked_base_units": "1250000000001",
            "total_completions": 3,
        },
    )

    dumped = response.model_dump()
    assert dumped["vault_economy"]["total_staked"] == "1250.000000001"
    assert dumped["vault_economy"]["total_staked_base_units"] == "1250000000001"
    assert dumped["vault_economy"]["total_cal_staked"] == "1250.000000001"
    assert dumped["vault_economy"]["total_cal_staked_base_units"] == "1250000000001"
    assert dumped["total_staked"] == "1250.000000001"
    assert dumped["total_staked_base_units"] == "1250000000001"


def test_record_board_keeps_entries_canonical_and_leaderboard_compat_alias():
    board = RecordBoard(
        climb_id="climb-1",
        climb_name="Hawk Hill",
        vault_id=7,
        entries=[
            RecordBoardEntry(
                position=1,
                rank=1,
                tie_size=1,
                is_tied=False,
                wallet="Wallet111",
                best_time_seconds=321,
            ),
        ],
        kom_holder="Wallet111",
        kom_time_s=321,
    )

    assert board.truth_source == TruthSource.onchain
    assert board.segment_id == "climb-1"
    assert board.segment_name == "Hawk Hill"
    assert board.leaderboard[0].wallet == "Wallet111"


def test_settlement_status_mirrors_epoch_rollout_alias():
    status = SettlementStatus(
        settlement_week=14,
        finalized_at="2026-04-20T13:06:40+00:00",
        total_amount="42",
        total_amount_base_units="42000000000",
    )

    assert status.truth_source == TruthSource.onchain
    assert status.epoch == 14
    assert status.finalized_at == "2026-04-20T13:06:40+00:00"


def test_client_contract_schema_exports_all_canonical_models():
    schema = client_contract_json_schema()

    assert schema["contract_version"] == CLIENT_CONTRACT_VERSION
    assert set(schema["schemas"]) == set(CLIENT_CONTRACT_MODELS)
    for name in [
        "ClimbSummary",
        "VaultEconomy",
        "RideAttestationStatus",
        "RideStatusResponse",
        "RideEarnings",
        "RideClimbEarning",
        "RideProgression",
        "RideProcessingFailure",
        "RideInputQuality",
        "SettlementStatus",
        "RecordBoard",
        "LocalLegendStatus",
    ]:
        assert schema["schemas"][name]["type"] == "object"
        assert "properties" in schema["schemas"][name]

    ride_status_properties = schema["schemas"]["RideAttestationStatus"]["properties"]
    assert "attestation_status" in ride_status_properties
    assert "attestation_commitment_hex" in ride_status_properties
    assert "finalized_at" in ride_status_properties
    assert "import_source" in ride_status_properties
    assert "import_diagnostics" in ride_status_properties
    full_status_properties = schema["schemas"]["RideStatusResponse"]["properties"]
    assert "metrics" in full_status_properties
    assert "earnings" in full_status_properties
    assert "climb_earnings" in full_status_properties
    assert "progression" in full_status_properties
    assert "processing_stage" in full_status_properties
    assert "failure" in full_status_properties
    assert "input_quality" in full_status_properties


@pytest.mark.parametrize(("fixture_name", "model"), FIXTURE_MODELS.items())
def test_client_v1_golden_fixtures_validate_against_dtos(fixture_name, model):
    payload = load_fixture(fixture_name)

    dto = model.model_validate(payload)
    dumped = dto.model_dump(mode="json")

    assert dumped["contract_version"] == CLIENT_CONTRACT_VERSION
    assert dumped["truth_source"] in {"onchain", "attested", "projected", "compatibility"}


def test_record_board_accepts_pre_tie_metadata_client_v1_payload():
    payload = load_fixture("record_board.json")
    for key in ("entries", "leaderboard"):
        for entry in payload[key]:
            entry.pop("position")
            entry.pop("competition_rank")
            entry.pop("tie_size")
            entry.pop("is_tied")

    dto = RecordBoard.model_validate(payload)

    assert dto.entries[0].wallet == payload["entries"][0]["wallet"]
    assert dto.entries[0].position is None
    assert dto.entries[0].competition_rank is None
    assert dto.entries[0].tie_size is None
    assert dto.entries[0].is_tied is False


@pytest.mark.asyncio
async def test_completed_ride_status_route_matches_client_v1_attestation_and_earnings_contracts():
    ride_id = str(uuid4())
    finalized_at = "2026-04-20T13:05:00+00:00"
    repo = MagicMock()
    repo.get_ride = AsyncMock(
        return_value={
            "id": ride_id,
            "user_id": "user-1",
            "processing_status": "completed",
            "ride_hash_hex": "aa" * 32,
            "attestation_commitment_hex": "bb" * 32,
            "ride_parser_version": 1,
            "preliminary_ride_hash_hex": "aa" * 32,
            "preliminary_parser_version": 1,
            "canonical_match": True,
            "ride_attestation_pda": "RideAttestation111111111111111111111111111",
            "ride_attestation_tx_signature": "5" * 88,
            "ride_attested_at": "2026-04-20T13:04:00+00:00",
            "finalized_at": finalized_at,
            "import_source": "strava_stream_reconstructed_gpx",
            "import_source_id": "12345",
            "import_diagnostics": {
                "quality_tier": "degraded",
                "trackpoint_count": 820,
                "flags": ["STRAVA:max_gap_warn_45s"],
            },
            "sensor_integrity": {
                "gps_coverage": 0.98,
                "elev_coverage": 0.96,
                "sampling_regularity": 0.74,
                "max_gap_s": 45,
                "power_coverage": 0.0,
                "hr_coverage": 0.34,
                "speed_coverage": 0.99,
                "integrity_score": 0.76,
                "sample_count": 820,
                "flags": ["SAMPLING:gap_ratio_warn_12%"],
            },
            "cal_earned": 847,
            "effort_evidence_tier": "power_verified",
            "reward_policy": "rewardable",
            "estimated_cal": 78,
            "rewardable_cal": 78,
            "tributable_cal": 78,
            "dung_minted": 4200,
            "tx_signature": "6" * 88,
            "tss": 78.2,
            "threshold_training_w": 245,
            "threshold_training_kind": "sealed",
            "total_tss_after": 1200.5,
            "level_delta": 1,
            "level_after": 7,
            "kcals": 921,
            "distance_m": 48200,
            "elevation_gain_m": 970,
            "duration_sec": 7200,
            "avg_power_w": 231,
            "normalized_power_w": 278,
            "normalized_power_raw_w": 278.0,
            "normalized_power_duration_s": 7200,
            # Status TSS/progression is the frozen training load, never today's
            # Threshold repricing or a payment receipt.
            "training_metrics": {"engine_version": 2, "load": 81},
        }
    )
    table_data = {
        "vault_completions": [
            {
                "vault_signature": "sig-1",
                "wallet": "wallet-1",
                "activity_id": ride_id,
                "time_seconds": 412,
                "best_time_seconds": 412,
                "is_pr": True,
                "completed_at": "2026-04-20T13:03:00+00:00",
                "on_chain_tx": "climb-tx",
                "cal_tribute": 104,
                    "chain_confirmation_status": "confirmed",
                    "completion_receipt_pda": "CompletionPda111",
                    "completion_evidence_hash": "\\x" + "ab" * 32,
                    "completion_evidence_version": 2,
                    "chain_confirmed_at": "2026-04-20T13:04:00+00:00",
            }
        ],
        "indexed_vaults": [
            {
                "id": 142,
                "name": "Manayunk Wall",
                "signature_hex": "sig-1",
                "pda": "VaultPda111",
            }
        ],
        "indexed_leaderboards": [
            {
                "vault_id": 142,
                "entries": [
                    {"user": "wallet-2", "time_s": 430, "recorded_at": 1776600000},
                    {"user": "wallet-1", "time_s": 412, "recorded_at": 1776690180},
                ],
            }
        ],
    }

    def table(name: str):
        query = MagicMock()
        query.select.return_value = query
        query.eq.return_value = query
        query.in_.return_value = query
        query.execute.return_value.data = table_data.get(name, [])
        return query

    repo.client.table.side_effect = table
    repo.get_reward_threshold_rider_projection = AsyncMock(
        return_value={
            "state": "established",
            "current_w": 245,
            "established_at": "2026-08-17T12:00:00+00:00",
            "last_raised_at": None,
            "pending_monday": None,
            "training_denominator": {
                "watts": 245,
                "kind": "sealed",
                "provisional": False,
            },
        }
    )
    current_user = AuthenticatedUser(wallet="wallet-1", user_id="user-1", device_id="device-1")

    response = await get_ride_status(
        ride_id=ride_id,
        current_user=current_user,
        repo=repo,
    )

    status_response = RideStatusResponse.model_validate(response)
    attestation = RideAttestationStatus.model_validate(response)
    earnings = RideEarnings.model_validate(response["earnings"])
    effort_policy = RideEffortEconomy.model_validate(response["effort_policy"])
    climb_earning = RideClimbEarning.model_validate(response["climb_earnings"][0])
    progression = RideProgression.model_validate(response["progression"])
    assert status_response.contract_version == CLIENT_CONTRACT_VERSION
    assert status_response.metrics is not None
    assert status_response.metrics.distance_m == 48200
    assert status_response.has_gps is True
    assert attestation.contract_version == CLIENT_CONTRACT_VERSION
    assert attestation.truth_source == TruthSource.attested
    assert attestation.attestation_status == "attested"
    assert attestation.finalized_at == finalized_at
    assert attestation.import_source == "strava_stream_reconstructed_gpx"
    assert attestation.import_diagnostics["quality_tier"] == "degraded"
    assert status_response.processing_stage == "completed"
    assert status_response.can_retry_processing is False
    assert status_response.failure is None
    assert isinstance(status_response.input_quality, RideInputQuality)
    assert status_response.input_quality.status == "degraded"
    assert status_response.input_quality.sensor_data_state == "partial"
    assert status_response.input_quality.sample_count == 820
    assert status_response.input_quality.import_quality_tier == "degraded"
    assert "SAMPLING:gap_ratio_warn_12%" in status_response.input_quality.flags
    assert "STRAVA:max_gap_warn_45s" in status_response.input_quality.flags
    assert earnings.truth_source == TruthSource.onchain
    assert earnings.cal_earned == 847
    assert earnings.dung_earned == 4200
    assert earnings.finalized_at == finalized_at
    assert effort_policy.effort_evidence_tier == "power_verified"
    assert effort_policy.reward_policy == "rewardable"
    assert effort_policy.estimated_cal == 78
    assert effort_policy.rewardable_cal == 78
    assert effort_policy.tributable_cal == 78
    assert climb_earning.truth_source == TruthSource.onchain
    assert climb_earning.climb_name == "Manayunk Wall"
    assert climb_earning.vault_id == 142
    assert climb_earning.cal_tribute == 104
    assert climb_earning.tribute_truth_source == TruthSource.onchain
    assert climb_earning.completion_evidence_version == 2
    assert climb_earning.tribute_bound is True
    assert climb_earning.record_board_rank == 1
    assert climb_earning.is_new_kom is True
    assert progression.tss_delta == 81
    assert progression.total_tss_after is None
    assert progression.level_delta is None
    assert progression.level_after is None
    assert response["has_patterns"] is True
    assert response["has_leaderboards"] is True
    assert response["metrics"]["tss"] == 81


@pytest.mark.asyncio
async def test_processing_ride_status_skips_climb_earning_projection_reads():
    ride_id = str(uuid4())
    repo = MagicMock()
    repo.get_ride = AsyncMock(
        return_value={
            "id": ride_id,
            "user_id": "user-1",
            "processing_status": "processing",
            "raw_file_path": "rides/user-1/file.fit",
        }
    )
    current_user = AuthenticatedUser(wallet="wallet-1", user_id="user-1", device_id="device-1")

    response = await get_ride_status(
        ride_id=ride_id,
        current_user=current_user,
        repo=repo,
    )

    assert response["processing_stage"] == "processing"
    assert response["climb_earnings"] == []
    repo.client.table.assert_not_called()


@pytest.mark.asyncio
async def test_owner_status_withholds_legacy_progression_without_threshold_provenance():
    ride_id = str(uuid4())
    repo = MagicMock()
    repo.get_ride = AsyncMock(
        return_value={
            "id": ride_id,
            "user_id": "user-1",
            "processing_status": "processing",
            "tss": 88.4,
            "total_tss_after": 999.0,
            "level_delta": 2,
            "level_after": 9,
        }
    )
    current_user = AuthenticatedUser(wallet="wallet-1", user_id="user-1", device_id="device-1")

    response = await get_ride_status(
        ride_id=ride_id,
        current_user=current_user,
        repo=repo,
    )

    assert response["metrics"] is None
    assert response["progression"] is None
    repo.get_reward_threshold_rider_projection.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("persisted_cal", [0, 222])
async def test_public_threshold_hold_status_never_exposes_parent_or_release_cal(
    persisted_cal: int,
) -> None:
    ride_id = str(uuid4())
    repo = MagicMock()
    repo.get_ride = AsyncMock(
        return_value={
            "id": ride_id,
            "user_id": "owner-1",
            "visibility": "public",
            "processing_status": "completed",
            "reward_policy": "threshold_provisional_hold_v1",
            "cal_earned": persisted_cal,
            "tss": 52.25,
            "threshold_training_w": 245,
            "threshold_training_kind": "sealed",
        }
    )
    decision = MagicMock(is_owner=False, can_view=True)
    athletic_climb = RideClimbEarning(
        ride_id=ride_id,
        climb_id="61",
        climb_name="Release Wall",
        vault_id=61,
        vault_signature="sig-61",
        cal_tribute=15,
        tribute_truth_source=TruthSource.onchain,
        tribute_bound=True,
        completion_time_s=411,
        record_board_rank=2,
    )

    with patch(
        "app.routes.rides.check_ride_access",
        AsyncMock(return_value=decision),
    ), patch(
        "app.routes.rides._fetch_ride_climb_earnings",
        return_value=[athletic_climb],
    ):
        response = await get_ride_status(
            ride_id=ride_id,
            current_user=None,
            repo=repo,
        )

    assert "cal_earned" not in response
    assert "dung_minted" not in response
    assert "earnings" not in response
    assert response["effort_policy"] is None or "estimated_cal" not in response["effort_policy"]
    assert response["effort_policy"] is None or "rewardable_cal" not in response["effort_policy"]
    assert response["effort_policy"] is None or "tributable_cal" not in response["effort_policy"]
    assert response["metrics"]["tss"] is None
    assert response["climb_earnings"][0]["record_board_rank"] == 2
    assert "cal_tribute" not in response["climb_earnings"][0]
    assert response["climb_earnings"][0]["tribute_bound"] is False


@pytest.mark.asyncio
async def test_public_completed_status_omits_all_exact_ride_economy() -> None:
    ride_id = str(uuid4())
    repo = MagicMock()
    repo.get_ride = AsyncMock(
        return_value={
            "id": ride_id,
            "user_id": "owner-1",
            "visibility": "public",
            "processing_status": "completed",
            "reward_policy": "rewardable",
            "cal_earned": 222,
            "dung_minted": 44,
            "estimated_cal": 240,
            "rewardable_cal": 222,
            "tributable_cal": 22,
        }
    )
    decision = MagicMock(is_owner=False, can_view=True)
    athletic_climb = RideClimbEarning(
        ride_id=ride_id,
        climb_id="61",
        climb_name="Release Wall",
        vault_id=61,
        vault_signature="sig-61",
        cal_tribute=22,
        tribute_truth_source=TruthSource.onchain,
        tribute_bound=True,
        completion_time_s=411,
        record_board_rank=2,
    )

    with patch(
        "app.routes.rides.check_ride_access",
        AsyncMock(return_value=decision),
    ), patch(
        "app.routes.rides._fetch_ride_climb_earnings",
        return_value=[athletic_climb],
    ):
        response = await get_ride_status(
            ride_id=ride_id,
            current_user=None,
            repo=repo,
        )

    assert "cal_earned" not in response
    assert "dung_minted" not in response
    assert "earnings" not in response
    assert "estimated_cal" not in response["effort_policy"]
    assert "rewardable_cal" not in response["effort_policy"]
    assert "tributable_cal" not in response["effort_policy"]
    assert "cal_tribute" not in response["climb_earnings"][0]


@pytest.mark.asyncio
async def test_public_threshold_hold_ride_does_not_read_private_cal_itemization() -> None:
    ride_id = str(uuid4())
    repo = MagicMock()
    repo.get_ride = AsyncMock(
        return_value={
            "id": ride_id,
            "user_id": "owner-1",
            "visibility": "public",
            "processing_status": "completed",
            "reward_policy": "threshold_provisional_hold_v1",
            "cal_earned": 222,
        }
    )
    decision = MagicMock(is_owner=False, can_view=True)
    decision.to_client_dict.return_value = {}
    record = MagicMock()
    record.model_dump.return_value = {}

    with patch(
        "app.routes.rides.check_ride_access",
        AsyncMock(return_value=decision),
    ), patch(
        "app.routes.rides._serialized_ride_media",
        AsyncMock(return_value=[]),
    ), patch(
        "app.routes.rides._route_preview_points_for_record",
        AsyncMock(return_value=([], [])),
    ), patch(
        "app.routes.rides._to_ride_record",
        return_value=record,
    ), patch(
        "app.routes.rides._fetch_ride_cal_itemization",
    ) as fetch_itemization:
        response = await get_ride(
            ride_id=ride_id,
            current_user=None,
            repo=repo,
        )

    assert response["is_owner"] is False
    fetch_itemization.assert_not_called()


@pytest.mark.asyncio
async def test_owner_threshold_hold_status_keeps_climb_athletics_without_tribute() -> None:
    ride_id = str(uuid4())
    repo = MagicMock()
    repo.get_ride = AsyncMock(
        return_value={
            "id": ride_id,
            "user_id": "owner-1",
            "visibility": "public",
            "processing_status": "completed",
            "reward_policy": "threshold_provisional_hold_v1",
            "cal_earned": 0,
        }
    )
    repo.get_reward_threshold_ride_projections = AsyncMock(
        return_value={ride_id: {"state": "held"}}
    )
    decision = MagicMock(is_owner=True, can_view=True)
    athletic_climb = RideClimbEarning(
        ride_id=ride_id,
        climb_id="61",
        climb_name="Release Wall",
        vault_id=61,
        vault_signature="sig-61",
        cal_tribute=15,
        tribute_truth_source=TruthSource.onchain,
        tribute_bound=True,
        completion_time_s=411,
        record_board_rank=2,
    )

    with patch(
        "app.routes.rides.check_ride_access",
        AsyncMock(return_value=decision),
    ), patch(
        "app.routes.rides._fetch_ride_climb_earnings",
        return_value=[athletic_climb],
    ):
        response = await get_ride_status(
            ride_id=ride_id,
            current_user=AuthenticatedUser(
                wallet="owner-wallet",
                user_id="owner-1",
                device_id="owner-device",
            ),
            repo=repo,
        )

    assert response["cal_earned"] is None
    assert response["earnings"] is None
    assert response["effort_policy"]["threshold_economy_state"] == "held"
    assert response["climb_earnings"][0]["record_board_rank"] == 2
    assert response["climb_earnings"][0]["cal_tribute"] is None
    assert response["climb_earnings"][0]["tribute_bound"] is False


def test_failed_ride_status_contract_exposes_retryable_failure_and_invalid_quality():
    ride_id = str(uuid4())

    payload = _build_ride_status_response(
        ride_id,
        {
            "id": ride_id,
            "processing_status": "failed",
            "raw_file_path": "rides/user/ride.fit",
            "error_message": "Processing timed out. Please try re-uploading the file.",
            "sensor_integrity": {
                "integrity_score": 0.22,
                "sample_count": 6,
                "power_coverage": 0.0,
                "hr_coverage": 0.0,
                "speed_coverage": 0.0,
                "flags": ["SAMPLING:too_few_samples_6"],
            },
        },
    )
    response = RideStatusResponse.model_validate(payload)

    dumped = response.model_dump(mode="json")

    assert dumped["processing_stage"] == "failed"
    assert dumped["can_retry_processing"] is True
    assert dumped["failure"]["retryable"] is True
    assert dumped["failure"]["phase"] == "processing"
    assert dumped["input_quality"]["status"] == "invalid"
    assert dumped["input_quality"]["sensor_data_state"] == "absent"


def test_route_only_ride_status_contract_exposes_estimated_only_policy():
    ride_id = str(uuid4())

    payload = _build_ride_status_response(
        ride_id,
        {
            "id": ride_id,
            "processing_status": "under_review",
            "review_reason": "effort_source_route_estimate_only",
            "tss": 169.9,
            "cal_earned": 0,
            "effort_evidence_tier": "route_only",
            "reward_policy": "estimated_only",
            "estimated_cal": 169,
            "rewardable_cal": 0,
            "tributable_cal": 0,
        },
    )
    response = RideStatusResponse.model_validate(payload)

    assert response.processing_stage == "under_review"
    assert response.cal_earned is None
    assert response.earnings is None
    assert response.effort_policy is not None
    assert response.effort_policy.effort_evidence_tier == "route_only"
    assert response.effort_policy.reward_policy == "estimated_only"
    assert response.effort_policy.estimated_cal == 169
    assert response.effort_policy.rewardable_cal == 0
    assert response.effort_policy.tributable_cal == 0
