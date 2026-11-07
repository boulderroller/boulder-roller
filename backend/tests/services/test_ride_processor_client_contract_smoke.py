from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.client_contracts import RideStatusResponse
from app.dependencies import AuthenticatedUser
from app.routes.rides import _build_ride_status_response, upload_init
from app.schemas import UploadInitRequest
from app.services.ride_attester import (
    OnchainRideIdentity,
    PreliminaryAttestationCheck,
    RideAttestationPreparation,
)
from app.services.ride_processor import (
    AUTHORITATIVE_METRICS_VERSION,
    RideProcessor,
)
from app.services.ride_economic_coordinator import RideEconomicOutcome
from app.services.ride_privacy import RidePrivacyPolicy


REPO_ROOT = Path(__file__).resolve().parents[3]
VECTOR_PATH = REPO_ROOT / "tests/fixtures/canonical_ride_v4_vectors.json"


class _PatternResults:
    def __init__(self, ride_id: UUID, wallet: str) -> None:
        self.activity_id = ride_id
        self.wallet = wallet
        self.climb_patterns = [
            SimpleNamespace(signature_hex="ab" * 32, vert_m=97.0)
        ]
        self.sensor_integrity = None
        self.vault_allocations = []

    @property
    def total_patterns(self) -> int:
        return len(self.climb_patterns)

    def summary(self) -> str:
        return "97m climbed"


def _reference_vector() -> tuple[bytes, str, int, str]:
    vectors = json.loads(VECTOR_PATH.read_text())
    reference = vectors["vectors"]["reference_gpx_file"]
    source_path = REPO_ROOT / reference["source_path"]
    return (
        source_path.read_bytes(),
        reference["ride_hash"],
        int(vectors["parser_version"]),
        str(reference["file_type"]),
    )


@pytest.mark.asyncio
async def test_deterministic_ride_fixture_flows_to_client_v1_status_contract(monkeypatch) -> None:
    """Gate the backend spine that turns ride evidence into protocol status.

    The Rust/mobile parser symmetry gates prove the fixture hash itself. This
    smoke proves the backend does not drop or mutate that truth at the seams:
    upload init -> Attester handoff -> Executor inputs -> projection
    persistence -> public ``client.v1`` status DTO.
    """

    fixture_bytes, ride_hash_hex, parser_version, file_type = _reference_vector()
    file_hash_hex = hashlib.sha256(fixture_bytes).hexdigest()
    user_id = uuid4()
    wallet = "wallet-1"

    ride_repo = MagicMock()
    ride_repo.find_ride_by_hash = AsyncMock(return_value=None)
    ride_repo.resolve_ride_privacy_policy = AsyncMock(
        return_value=RidePrivacyPolicy(
            visibility="public",
            map_visibility="hide_start_end",
            map_hide_start_m=200,
            map_hide_end_m=200,
        )
    )
    ride_repo.create_ride = AsyncMock()
    ride_repo.update_ride_status = AsyncMock()
    ride_repo.store_gps_points = AsyncMock()
    ride_repo.update_ride_metadata = AsyncMock()
    ride_repo.register_reward_threshold_effort = AsyncMock(
        return_value={"disposition": "display_only"}
    )
    ride_repo.get_reward_threshold_rider_projection = AsyncMock(
        return_value={
            "state": "establishing",
            "current_w": None,
            "established_at": None,
            "last_raised_at": None,
            "pending_monday": None,
            "training_denominator": {
                "watts": 200,
                "kind": "network_placeholder",
                "provisional": True,
            },
        }
    )
    ride_repo.bind_reward_ftp_snapshot = AsyncMock(
        return_value={
            "reward_ftp_w": 200,
            "reward_ftp_source": "network_default",
            "reward_ftp_authority_id": None,
            "reward_ftp_policy_version": "reward_ftp_policy_2026_07_14",
        }
    )

    storage = MagicMock()
    storage.create_signed_upload_url = AsyncMock(
        return_value={"signed_url": "https://example.test/upload"}
    )

    current_user = AuthenticatedUser(
        wallet=wallet,
        user_id=str(user_id),
        device_id="device-1",
    )

    with patch("app.routes.rides.create_file_storage_service", return_value=storage):
        upload_response = await upload_init(
            http_request=MagicMock(),
            init_request=UploadInitRequest(
                file_type=file_type,
                file_hash=file_hash_hex,
                file_size=len(fixture_bytes),
                preliminary_ride_hash=ride_hash_hex,
                parser_version=parser_version,
            ),
            force=False,
            current_user=current_user,
            ride_repo=ride_repo,
        )

    ride_repo.create_ride.assert_awaited_once()
    upload_kwargs = ride_repo.create_ride.await_args.kwargs
    assert upload_kwargs["file_hash"] == file_hash_hex
    assert upload_kwargs["preliminary_ride_hash_hex"] == ride_hash_hex
    assert upload_kwargs["preliminary_parser_version"] == parser_version

    ride_id = UUID(upload_response.upload_id)
    upload_row = {
        "id": str(ride_id),
        "user_id": str(user_id),
        "file_hash": file_hash_hex,
        "file_type": file_type,
        "preliminary_ride_hash_hex": ride_hash_hex,
        "preliminary_parser_version": parser_version,
        "raw_file_path": upload_kwargs["raw_file_path"],
    }
    ride_repo.get_ride = AsyncMock(return_value=upload_row)

    completed_at = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=15)
    started_at = completed_at - timedelta(minutes=45)
    parsed_ride = SimpleNamespace(
        records=[SimpleNamespace(timestamp=started_at, lat=40.123456, lon=-105.123456)],
        gps_track=[SimpleNamespace(timestamp=started_at, lat=40.123456, lon=-105.123456)],
        started_at=started_at,
        completed_at=completed_at,
        device_name="Fixture Head Unit",
        file_name="canonical_v1_reference.gpx",
    )
    metrics = SimpleNamespace(
        duration_sec=2700,
        moving_time_sec=2700,
        metrics_version=AUTHORITATIVE_METRICS_VERSION,
        power_sample_count=2700,
        power_sample_coverage_bps=10_000,
        heart_rate_sample_count=2700,
        heart_rate_sample_coverage_bps=10_000,
        tss=84.7,
        kcals=512.0,
        distance_m=12345.6,
        elevation_gain_m=321.0,
        avg_power_w=218.0,
        max_power_w=701.0,
        normalized_power_w=234.0,
        normalized_power_raw_w=234.125,
        normalized_power_duration_s=2700,
        avg_hr_bpm=151.0,
        max_hr_bpm=181.0,
        avg_speed_mps=4.6,
        avg_cadence_rpm=86.0,
    )
    identity = OnchainRideIdentity(
        ride_hash=bytes.fromhex(ride_hash_hex),
        attestation_commitment=bytes.fromhex(ride_hash_hex),
        parser_version=parser_version,
        source_kind=2,
    )

    ride_attester = MagicMock()
    ride_attester.prepare_ride.return_value = RideAttestationPreparation(
        onchain_identity=identity,
        preliminary_check=PreliminaryAttestationCheck(
            preliminary_ride_hash_hex=ride_hash_hex,
            preliminary_parser_version=parser_version,
            canonical_match=True,
            review_reason=None,
            requires_review=False,
        ),
        parsed_ride=parsed_ride,
        metrics=metrics,
    )
    ride_attester.calculate_metrics.return_value = SimpleNamespace(**vars(metrics))

    ride_projection_store = MagicMock()
    ride_projection_store.capture_profile_snapshot = AsyncMock()
    ride_projection_store.store_activity_streams = AsyncMock()
    ride_projection_store.gps_track_to_dicts = MagicMock(
        return_value=[{"lat": 40.123456, "lon": -105.123456, "timestamp": started_at.isoformat()}]
    )
    ride_projection_store.records_to_dicts = MagicMock(
        return_value=[{"lat": 40.123456, "lon": -105.123456, "timestamp": started_at}]
    )
    ride_projection_store.process_tile_projection = AsyncMock(
        return_value=(1, 1, [{"tile_id": "892681b6c8fffff"}])
    )
    canon_evidence = MagicMock()
    canon_evidence.raw_samples.return_value = [
        {
            "source_index": 0,
            "tile_id": "892681b6c8fffff",
            "t": 0.375,
            "lat": 40.123456,
            "lon": -105.123456,
            "elevation_m": 1600.5,
            "power_w": 218,
            "hr_bpm": 151,
            "speed_mps": 4.6,
            "gps_valid": True,
        }
    ]
    canon_evidence.record_points.return_value = [
        {"lat": 40.123456, "lon": -105.123456, "timestamp": started_at}
    ]
    ride_projection_store.build_canon_traversal_evidence.return_value = canon_evidence
    ride_projection_store.store_canon_traversal_evidence = AsyncMock()
    ride_projection_store.store_pattern_results = AsyncMock()
    ride_projection_store.update_ride_complete = AsyncMock()

    user_repo = MagicMock()
    user_repo.get_user_wallet = AsyncMock(return_value=wallet)
    user_repo.get_user_stats = AsyncMock(return_value={"total_tss": 1115.8})

    ride_executor = MagicMock()
    ride_executor.record_ride_attestation = AsyncMock(
        return_value=SimpleNamespace(
            reference="ride-attestation-ref",
            pda="RideAttestation111111111111111111111111111111",
            tx_signature="ride-attestation-tx",
            attested_at=(completed_at + timedelta(seconds=30)).isoformat(),
        )
    )
    ride_executor.credit_cal = AsyncMock(return_value="credit-cal-tx")
    ride_executor.record_climb_completion = AsyncMock()

    climb_economy_processor = MagicMock()
    climb_economy_processor.build_completion_plan = AsyncMock(
        return_value=(
            [],
            [{"vault_id": 142, "vault_signature": "ab" * 32, "cal_tribute": 5}],
        )
    )
    ride_economic_coordinator = MagicMock()
    ride_economic_coordinator.freeze_plan = AsyncMock(
        return_value={
            "ride_id": str(ride_id),
            "state": "planned",
            "steps": [],
            "plan_evidence_hash_hex": "ef" * 32,
        }
    )
    from app.services.ride_effort_trim import epoch_ms
    monkeypatch.setattr("app.services.ride_processor.effort_spans_ms_rust", lambda parsed: [(epoch_ms(parsed.started_at),epoch_ms(parsed.completed_at))])
    weather_requests = []

    async def fake_weather(**kwargs):
        weather_requests.append(kwargs)
        return {"weather_temp_c": 12.5, "weather_wind_mps": 3.0, "weather_wind_deg": 180}

    monkeypatch.setattr("app.services.ride_weather.fetch_ride_weather", fake_weather)
    ride_economic_repository = MagicMock()
    ride_economic_repository.get_effort_trim_basis = AsyncMock(return_value={"frozen":None,"covered_spans_ms":[],"covered_completion_windows":[]})
    ride_economic_repository.register_threshold_provisional_hold = AsyncMock()
    ride_economic_coordinator.execute = AsyncMock(
        return_value=RideEconomicOutcome(
            status="complete",
            state="complete",
            durable_checkpoint=True,
            ride_attestation_pda="RideAttestation111111111111111111111111111111",
            ride_attestation_tx_signature="ride-attestation-tx",
            ride_attested_at=(completed_at + timedelta(seconds=30)).isoformat(),
            cal_tx_signature=None,
        )
    )
    ride_economic_terminal_projector = MagicMock()
    ride_economic_terminal_projector.project = AsyncMock(
        return_value=SimpleNamespace(
            status="projected",
            durable_checkpoint=True,
            cal_earned=0,
            error=None,
        )
    )

    ride_enrichment_service = MagicMock()
    ride_enrichment_service.detect_and_store_patterns = AsyncMock(
        return_value=_PatternResults(ride_id, wallet)
    )

    tile_service = MagicMock()
    tile_service.get_tile_sequence = MagicMock(
        return_value=[
            SimpleNamespace(
                tile_id="892681b6c8fffff",
                t=0.375,
                lat=40.123456,
                lon=-105.123456,
                elevation_m=1600.5,
                power_w=218,
                hr_bpm=151,
                speed_mps=4.6,
            )
        ]
    )

    with patch("app.services.ride_processor.get_supabase_client", return_value=MagicMock()):
        processor = RideProcessor(
            ride_repo=ride_repo,
            user_repo=user_repo,
            tile_repo=MagicMock(),
            token_repo=MagicMock(),
            pattern_repo=MagicMock(),
            achievement_repo=MagicMock(),
            vault_repo=MagicMock(),
            fitness_repo=MagicMock(),
            notification_repo=MagicMock(),
            tile_service=tile_service,
            vault_service=MagicMock(),
            ride_attester=ride_attester,
            ride_projection_store=ride_projection_store,
            climb_economy_processor=climb_economy_processor,
            ride_enrichment_service=ride_enrichment_service,
            ride_executor=ride_executor,
            ride_economic_coordinator=ride_economic_coordinator,
            ride_economic_repository=ride_economic_repository,
            ride_economic_terminal_projector=ride_economic_terminal_projector,
        )
    processor._publish_nats_event = AsyncMock()
    processor.achievement_detector.detect_achievements = AsyncMock(return_value=[])
    processor.analytics_service.update_daily_aggregates = AsyncMock()

    result = await processor.process_ride(
        ride_id=ride_id,
        file_data_b64=base64.b64encode(fixture_bytes).decode("ascii"),
        file_type=file_type,
        user_id=user_id,
        user_weight_kg=75.0,
        file_bytes=fixture_bytes,
    )

    assert result["status"] == "completed"
    # Parsed fixes carry lat/lon; the provider quantizes them (ride_weather).
    assert weather_requests == [{"latitude": 40.123456, "longitude": -105.123456,
                                 "started_at": started_at, "elevation": None}]
    ride_repo.update_ride_metadata.assert_any_await(str(ride_id), {
        "weather_temp_c": 12.5, "weather_wind_mps": 3.0, "weather_wind_deg": 180,
        "weather_source": "model",
    })
    economic_status_call = next(
        call
        for call in ride_repo.update_ride_status.await_args_list
        if "economic_tss" in call.kwargs
    )
    assert economic_status_call.kwargs["normalized_power_raw_w"] == 234.125
    assert economic_status_call.kwargs["normalized_power_duration_s"] == 2700
    ride_attester.prepare_ride.assert_called_once()
    prepare_kwargs = ride_attester.prepare_ride.call_args.kwargs
    assert prepare_kwargs["file_bytes"] == fixture_bytes
    assert prepare_kwargs["file_type"] == file_type
    assert prepare_kwargs["ride_row"] == upload_row

    ride_economic_coordinator.freeze_plan.assert_awaited_once()
    ride_economic_terminal_projector.project.assert_awaited_once_with(ride_id)
    frozen_draft = ride_economic_coordinator.freeze_plan.await_args.args[0]
    assert frozen_draft.wallet == wallet
    assert frozen_draft.identity.ride_hash.hex() == ride_hash_hex
    assert frozen_draft.completed_at == completed_at
    assert frozen_draft.total_tss == 0
    assert frozen_draft.exact_cal_base_units == 0
    assert frozen_draft.reward_policy == "threshold_provisional_hold_v1"

    climb_economy_processor.build_completion_plan.assert_awaited_once()
    plan_kwargs = climb_economy_processor.build_completion_plan.await_args.kwargs
    assert plan_kwargs["completed_at"] == completed_at
    assert plan_kwargs["raw_climb_samples"][0]["t"] == 0
    assert isinstance(plan_kwargs["raw_climb_samples"][0]["t"], int)
    assert isinstance(plan_kwargs["raw_climb_samples"][0]["power_w"], int)
    # Measurement retains the ride budget; the held parent above pays zero.
    assert plan_kwargs["exact_ride_cal_base_units"] == 84_700_000_000
    ride_economic_coordinator.execute.assert_awaited_once_with(ride_id)
    ride_executor.record_ride_attestation.assert_not_awaited()
    ride_executor.credit_cal.assert_not_awaited()

    ride_projection_store.update_ride_complete.assert_awaited_once()
    enrichment_kwargs = (
        ride_enrichment_service.detect_and_store_patterns.await_args.kwargs
    )
    assert enrichment_kwargs["raw_climb_samples"][0]["t"] == 0.375
    ride_projection_store.store_canon_traversal_evidence.assert_awaited_once_with(
        canon_evidence
    )
    complete_kwargs = ride_projection_store.update_ride_complete.await_args.kwargs
    assert complete_kwargs["status"] == "completed"
    assert complete_kwargs["ride_hash_hex"] == ride_hash_hex
    assert complete_kwargs["attestation_commitment_hex"] == ride_hash_hex
    assert complete_kwargs["ride_parser_version"] == parser_version
    assert complete_kwargs["preliminary_ride_hash_hex"] == ride_hash_hex
    assert complete_kwargs["preliminary_parser_version"] == parser_version
    assert complete_kwargs["canonical_match"] is True
    assert complete_kwargs["review_reason"] is None
    assert complete_kwargs["ride_attestation_pda"] == "RideAttestation111111111111111111111111111111"
    assert complete_kwargs["ride_attestation_tx_signature"] == "ride-attestation-tx"
    assert complete_kwargs["tx_signature"] == "ride-attestation-tx"
    assert complete_kwargs["cal_earned"] == 0
    assert complete_kwargs["total_tss_after"] == pytest.approx(1115.8)
    assert complete_kwargs["level_delta"] == 0
    assert complete_kwargs["level_after"] == 6

    status_row = {
        "id": str(ride_id),
        "processing_status": complete_kwargs["status"],
        "ride_hash_hex": complete_kwargs["ride_hash_hex"],
        "attestation_commitment_hex": complete_kwargs["attestation_commitment_hex"],
        "ride_parser_version": complete_kwargs["ride_parser_version"],
        "preliminary_ride_hash_hex": complete_kwargs["preliminary_ride_hash_hex"],
        "preliminary_parser_version": complete_kwargs["preliminary_parser_version"],
        "canonical_match": complete_kwargs["canonical_match"],
        "review_reason": complete_kwargs["review_reason"],
        "ride_attestation_pda": complete_kwargs["ride_attestation_pda"],
        "ride_attestation_tx_signature": complete_kwargs["ride_attestation_tx_signature"],
        "ride_attested_at": complete_kwargs["ride_attested_at"],
        "tss": complete_kwargs["metrics"].tss,
        "kcals": metrics.kcals,
        "distance_m": metrics.distance_m,
        "elevation_gain_m": metrics.elevation_gain_m,
        "duration_sec": metrics.duration_sec,
        "avg_power_w": metrics.avg_power_w,
        "normalized_power_w": metrics.normalized_power_w,
        "cal_earned": complete_kwargs["cal_earned"],
        "dung_minted": complete_kwargs["dung_minted"],
        "tx_signature": complete_kwargs["tx_signature"],
        "total_tss_after": complete_kwargs["total_tss_after"],
        "level_delta": complete_kwargs["level_delta"],
        "level_after": complete_kwargs["level_after"],
        "finalized_at": None,
    }
    status_payload = _build_ride_status_response(
        str(ride_id),
        status_row,
        climb_earnings=[],
    )
    status_contract = RideStatusResponse.model_validate(status_payload)

    assert status_contract.contract_version == "client.v1"
    assert status_contract.truth_source == "attested"
    assert status_contract.attestation_status == "attested"
    assert status_contract.ride_hash_hex == ride_hash_hex
    assert status_contract.parser_version == parser_version
    assert status_contract.earnings is not None
    assert status_contract.earnings.truth_source == "onchain"
    assert status_contract.earnings.cal_earned == 0
    assert status_contract.progression is not None
    assert status_contract.progression.truth_source == "projected"
    assert status_contract.progression.tss_delta is None
    assert status_contract.progression.total_tss_after == pytest.approx(1115.8)
    assert status_contract.progression.level_delta == 0
    assert status_contract.progression.level_after == 6
    assert status_contract.climb_earnings == []
