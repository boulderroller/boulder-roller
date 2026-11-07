from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.pattern_engine import PatternEngine, PatternResults, UserProfile
from app.models.patterns import ClimbPattern
from app.services.ride_enrichment_service import RideEnrichmentService


class RecordingPatternEngine:
    def __init__(self) -> None:
        self.tile_samples = None
        self.raw_climb_samples = None

    async def detect_patterns(
        self,
        *,
        activity_id,
        tile_samples,
        raw_climb_samples,
        user_profile,
        wallet_tile_history,
        ride_start_time,
    ):
        self.tile_samples = tile_samples
        self.raw_climb_samples = raw_climb_samples
        return PatternResults(activity_id=activity_id, wallet=user_profile.wallet)


class DetectorPatternEngine(RecordingPatternEngine):
    async def detect_patterns(self, **kwargs):
        results = await super().detect_patterns(**kwargs)
        detector = SimpleNamespace(
            id=uuid4(),
            start_offset_s=0,
            end_offset_s=60,
            vert_m=50.0,
            detector_version="climb_detector_v2",
            economic_eligible=True,
            abstention_reasons=[],
            match_trace={
                "registry_id": str(uuid4()),
                "canon_id": str(uuid4()),
                "canon_version": 2,
                "economic_action": {
                    "type": "vault_completion",
                    "is_new_kom": True,
                },
            },
            tile_ids=[],
            persistence_m=None,
        )
        results.climb_patterns = [detector]
        results.vault_completions = [
            SimpleNamespace(
                climb_pattern_id=detector.id,
                vault_name="legacy detector Vault",
            )
        ]
        return results


@pytest.mark.asyncio
async def test_ride_enrichment_normalizes_tile_and_raw_sample_times_before_detection():
    async def get_user_wallet(_):
        return "wallet-1"

    async def get_wallet_tile_history(_):
        return []

    started_at = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)
    ride_id = uuid4()
    user_id = uuid4()
    pattern_engine = RecordingPatternEngine()
    service = RideEnrichmentService(
        user_repo=SimpleNamespace(get_user_wallet=get_user_wallet),
        tile_repo=SimpleNamespace(get_wallet_tile_history=get_wallet_tile_history),
        pattern_engine=pattern_engine,
        tile_attribution_service=SimpleNamespace(),
        climb_economy_processor=SimpleNamespace(),
        ride_projection_store=SimpleNamespace(),
    )

    tile_samples = [
        {"t": started_at + timedelta(seconds=20), "tile_id": "late"},
        {"t": 5, "tile_id": "numeric"},
        {"tile_id": "untimed"},
        {"t": started_at + timedelta(seconds=10), "tile_id": "middle"},
    ]
    raw_samples = [
        {
            "t": started_at + timedelta(seconds=15),
            "tile_id": "raw-late",
            "lat": 39.95,
            "lon": -75.16,
        },
        {
            "t": 0,
            "tile_id": "raw-start",
            "lat": 39.94,
            "lon": -75.17,
        },
    ]

    await service.detect_and_store_patterns(
        ride_id=ride_id,
        user_id=user_id,
        tile_samples=tile_samples,
        raw_climb_samples=raw_samples,
        ride_start_time=started_at,
        apply_vault_economics=False,
    )

    assert [sample["tile_id"] for sample in pattern_engine.tile_samples] == [
        "numeric",
        "middle",
        "late",
    ]
    assert [sample["t"] for sample in pattern_engine.tile_samples] == [5.0, 10.0, 20.0]
    assert [sample["tile_id"] for sample in pattern_engine.raw_climb_samples] == [
        "raw-start",
        "raw-late",
    ]
    assert [sample["t"] for sample in pattern_engine.raw_climb_samples] == [0.0, 15.0]
    assert all(
        isinstance(sample["t"], int)
        for sample in pattern_engine.raw_climb_samples
    )


@pytest.mark.asyncio
async def test_ride_enrichment_rejects_direct_economic_side_effects():
    async def get_user_wallet(_):
        return "wallet-1"

    async def get_wallet_tile_history(_):
        return []

    service = RideEnrichmentService(
        user_repo=SimpleNamespace(get_user_wallet=get_user_wallet),
        tile_repo=SimpleNamespace(get_wallet_tile_history=get_wallet_tile_history),
        pattern_engine=RecordingPatternEngine(),
        tile_attribution_service=SimpleNamespace(),
        climb_economy_processor=SimpleNamespace(),
        ride_projection_store=SimpleNamespace(),
    )

    with pytest.raises(RuntimeError, match="freeze a ride economic plan"):
        await service.detect_and_store_patterns(
            ride_id=uuid4(),
            user_id=uuid4(),
            tile_samples=[],
            apply_vault_economics=True,
        )


@pytest.mark.asyncio
async def test_detector_is_discovery_only_without_raw_canon_evidence():
    async def get_user_wallet(_):
        return "wallet-1"

    async def get_wallet_tile_history(_):
        return []

    service = RideEnrichmentService(
        user_repo=SimpleNamespace(get_user_wallet=get_user_wallet),
        tile_repo=SimpleNamespace(get_wallet_tile_history=get_wallet_tile_history),
        pattern_engine=DetectorPatternEngine(),
        tile_attribution_service=SimpleNamespace(),
        climb_economy_processor=SimpleNamespace(),
        ride_projection_store=SimpleNamespace(),
    )

    results = await service.detect_and_store_patterns(
        ride_id=uuid4(),
        user_id=uuid4(),
        tile_samples=[],
        raw_climb_samples=None,
        apply_vault_economics=False,
        canon_traversal_authoritative=False,
    )

    detector = results.climb_patterns[0]
    assert detector.economic_eligible is False
    assert "MATCH:canon_traversal_required" in detector.abstention_reasons
    assert detector.match_trace["authority"] == "discovery_only"
    assert not {"registry_id", "canon_id", "canon_version"}.issubset(
        detector.match_trace
    )
    assert detector.match_trace["economic_action"] is None
    assert results.vault_completions == []


def test_abstention_gap_check_accepts_datetime_and_numeric_climb_samples():
    started_at = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)
    engine = PatternEngine(use_rust_detector=False)
    pattern = ClimbPattern(
        id=uuid4(),
        activity_id=uuid4(),
        wallet="wallet-1",
        arena_id=None,
        vert_m=40,
        time_s=120,
        start_offset_s=0,
        end_offset_s=120,
        signature_v2_hex="aa" * 32,
        significance_confidence_tier=1,
    )
    samples = [
        {"t": started_at, "lat": 40.0, "elevation_m": 1600.0},
        {"t": 0, "lat": 40.0, "elevation_m": 1600.0},
        {"t": started_at + timedelta(seconds=10), "lat": 40.0, "elevation_m": 1602.0},
        {"t": started_at + timedelta(seconds=20), "lat": 40.0, "elevation_m": 1604.0},
    ]

    engine._evaluate_abstention(pattern, samples)

    assert pattern.economic_eligible is True
    assert not any(
        reason.startswith("CLIMB_SENSOR:time_gap")
        for reason in (pattern.abstention_reasons or [])
    )


@pytest.mark.asyncio
async def test_pattern_engine_scores_integrity_from_dense_raw_samples(monkeypatch):
    engine = PatternEngine(use_rust_detector=False)

    async def no_climbs(**_kwargs):
        return []

    monkeypatch.setattr(engine, "_detect_climb_patterns", no_climbs)
    monkeypatch.setattr(engine, "_run_template_matching", lambda **_kwargs: [])
    monkeypatch.setattr(engine, "_detect_steady_pattern", lambda **_kwargs: None)
    monkeypatch.setattr(engine, "_detect_exploration_pattern", lambda **_kwargs: None)

    started_at = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)
    tile_samples = [
        {"t": 0, "tile_id": "start", "lat": 40.0, "lon": -105.0},
        {"t": 600, "tile_id": "later", "lat": 40.01, "lon": -105.01},
    ]
    raw_samples = [
        {
            "t": offset,
            "tile_id": f"raw-{offset}",
            "lat": 40.0 + offset / 100000,
            "lon": -105.0 - offset / 100000,
            "elevation_m": 1600.0 + offset / 10,
            "hr_bpm": 145,
        }
        for offset in range(0, 60, 5)
    ]

    results = await engine.detect_patterns(
        activity_id=uuid4(),
        tile_samples=tile_samples,
        raw_climb_samples=raw_samples,
        user_profile=UserProfile(wallet="wallet-1", weight_kg=75, ftp_w=200),
        wallet_tile_history=set(),
        ride_start_time=started_at,
    )

    assert results.sensor_integrity is not None
    assert results.sensor_integrity.sample_count == len(raw_samples)
    assert results.sensor_integrity.elev_coverage == 1.0
    assert results.sensor_integrity.hr_coverage == 1.0
    assert results.sensor_integrity.gap_ratio == 0.0
    assert not any(
        flag.startswith("SAMPLING:gap_ratio")
        for flag in results.sensor_integrity.flags
    )
