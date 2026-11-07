from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.canon_traversal_evidence import (
    CANON_TRAVERSAL_EVIDENCE_VERSION,
    CanonTraversalEvidence,
    CanonTraversalEvidenceError,
)


class _TileService:
    def lat_lng_to_tile(self, lat: float, lon: float, resolution: int) -> str:
        assert resolution == 10
        return f"tile:{lat:.8f}:{lon:.8f}"


def _parsed_ride() -> SimpleNamespace:
    started_at = datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc)
    return SimpleNamespace(
        started_at=started_at,
        records=[
            SimpleNamespace(
                timestamp=started_at + timedelta(seconds=0.250125),
                lat=39.95000019,
                lon=-75.17000029,
                elevation_m=100.125,
                power_w=211,
                heart_rate_bpm=149,
                speed_mps=7.125,
            ),
            # A one-coordinate GPS record is malformed evidence, not a sensor-only
            # record. It must survive the handoff so D11 counts it outside.
            SimpleNamespace(
                timestamp=started_at + timedelta(seconds=0.500375),
                lat=None,
                lon=-75.16950017,
                elevation_m=101.0,
                power_w=215,
                heart_rate_bpm=150,
                speed_mps=7.2,
            ),
            SimpleNamespace(
                timestamp=started_at + timedelta(seconds=0.750625),
                lat=39.95050031,
                lon=-75.16900043,
                elevation_m=102.875,
                power_w=219,
                heart_rate_bpm=151,
                speed_mps=7.375,
            ),
            # Sensor-only records are not GPS samples and do not belong in the
            # D11 corridor denominator.
            SimpleNamespace(
                timestamp=started_at + timedelta(seconds=1),
                lat=None,
                lon=None,
                elevation_m=None,
                power_w=220,
                heart_rate_bpm=152,
                speed_mps=None,
            ),
        ],
    )


def test_jsonb_round_trip_preserves_subsecond_and_coordinate_evidence_exactly() -> None:
    ride_id = uuid4()
    evidence = CanonTraversalEvidence.build(
        ride_id=ride_id,
        ride_hash_hex="ab" * 32,
        ride_parser_version=7,
        parsed_ride=_parsed_ride(),
        tile_service=_TileService(),
    )

    # JSON encode/decode models the Supabase JSONB handoff between phase 1 and 2.
    restored = CanonTraversalEvidence.from_row(
        json.loads(json.dumps(evidence.to_row()))
    )

    assert restored.evidence_version == CANON_TRAVERSAL_EVIDENCE_VERSION
    assert len(restored.samples) == 3
    assert restored.samples == evidence.samples
    assert restored.samples[0]["t"] == 0.250125
    assert restored.samples[0]["lat"] == 39.95000019
    assert restored.samples[0]["lon"] == -75.17000029
    assert restored.samples[1]["t"] == 0.500375
    assert restored.samples[1]["lat"] is None
    assert restored.samples[1]["lon"] == -75.16950017
    assert restored.samples[1]["tile_id"] is None
    assert restored.samples[2]["t"] == 0.750625

    raw_samples = restored.raw_samples()
    record_points = restored.record_points(_parsed_ride().started_at)
    assert raw_samples == evidence.raw_samples()
    assert len(record_points) == 2
    assert record_points[0]["timestamp"] == datetime(
        2026, 7, 20, 10, 0, 0, 250125, tzinfo=timezone.utc
    )
    assert record_points[1]["timestamp"] == datetime(
        2026, 7, 20, 10, 0, 0, 750625, tzinfo=timezone.utc
    )
    assert record_points[1]["lat"] == 39.95050031
    # Numeric scalars are stored as canonical strings, so PostgreSQL JSONB
    # cannot rewrite exponent notation or signed zero beneath the digest.
    stored_sample = evidence.to_row()["samples"][0]
    assert stored_sample[1] == "0.250125"
    assert stored_sample[2] == "39.95000019"


def test_evidence_digest_fails_closed_after_sample_tampering() -> None:
    evidence = CanonTraversalEvidence.build(
        ride_id=uuid4(),
        ride_hash_hex="cd" * 32,
        ride_parser_version=8,
        parsed_ride=_parsed_ride(),
        tile_service=_TileService(),
    )
    row = json.loads(json.dumps(evidence.to_row()))
    row["samples"][0][1] = "1.250125"

    with pytest.raises(CanonTraversalEvidenceError, match="digest"):
        CanonTraversalEvidence.from_row(row)


def test_evidence_identity_and_sample_count_fail_closed() -> None:
    evidence = CanonTraversalEvidence.build(
        ride_id=uuid4(),
        ride_hash_hex="ef" * 32,
        ride_parser_version=9,
        parsed_ride=_parsed_ride(),
        tile_service=_TileService(),
    )
    bad_hash = evidence.to_row()
    bad_hash["ride_hash_hex"] = "not-a-hash"
    with pytest.raises(CanonTraversalEvidenceError, match="ride hash"):
        CanonTraversalEvidence.from_row(bad_hash)

    bad_count = evidence.to_row()
    bad_count["sample_count"] = 99
    with pytest.raises(CanonTraversalEvidenceError, match="sample count"):
        CanonTraversalEvidence.from_row(bad_count)
