from __future__ import annotations

from datetime import datetime, timezone

from app.services.strava_service import (
    STRAVA_STREAM_RECONSTRUCTED_GPX_SOURCE,
    StravaService,
)
from app.services.ride_provenance_policy import (
    ECONOMIC_GUARDRAIL_TRUSTED_PROVIDER,
    ECONOMIC_POLICY_AUTOMATIC_ELIGIBLE,
    PROVENANCE_TIER_TRUSTED_PROVIDER_SYNC,
)


def _streams(point_count: int = 60) -> dict:
    return {
        "time": {"data": list(range(point_count))},
        "latlng": {
            "data": [
                [40.0 + (idx * 0.0001), -75.0 - (idx * 0.0001)]
                for idx in range(point_count)
            ]
        },
        "altitude": {"data": [100.0 + idx for idx in range(point_count)]},
        "watts": {"data": [220 for _ in range(point_count)]},
        "heartrate": {"data": [150 for _ in range(point_count)]},
        "cadence": {"data": [88 for _ in range(point_count)]},
    }


def test_strava_stream_diagnostics_marks_dense_reconstruction_high_quality():
    diagnostics = StravaService.assess_stream_reconstruction_fidelity(
        activity_id=12345,
        streams=_streams(60),
    )

    assert diagnostics.import_source == STRAVA_STREAM_RECONSTRUCTED_GPX_SOURCE
    assert diagnostics.source_activity_id == "12345"
    assert diagnostics.quality_tier == "high"
    assert diagnostics.trackpoint_count == 60
    assert diagnostics.median_interval_s == 1.0
    assert diagnostics.max_gap_s == 1
    assert diagnostics.altitude_coverage == 1.0
    assert diagnostics.flags == []

    payload = diagnostics.to_dict()
    assert payload["ingest_source"] == STRAVA_STREAM_RECONSTRUCTED_GPX_SOURCE
    assert payload["provenance_tier"] == PROVENANCE_TIER_TRUSTED_PROVIDER_SYNC
    assert payload["provenance_economic_policy"] == ECONOMIC_POLICY_AUTOMATIC_ELIGIBLE
    assert payload["economic_guardrail_profile"] == ECONOMIC_GUARDRAIL_TRUSTED_PROVIDER
    assert payload["preliminary_attestation_required"] is False


def test_strava_stream_diagnostics_flags_sparse_missing_altitude_reconstruction():
    streams = _streams(12)
    streams["time"]["data"] = [0, 1, 2, 3, 4, 5, 65, 125, 185, 245, 305, 365]
    streams["altitude"]["data"] = []

    diagnostics = StravaService.assess_stream_reconstruction_fidelity(
        activity_id=67890,
        streams=streams,
    )

    assert diagnostics.quality_tier == "low"
    assert diagnostics.trackpoint_count == 12
    assert diagnostics.gap_count_over_30s == 6
    assert "STRAVA:missing_altitude_stream" in diagnostics.flags
    assert "STRAVA:max_gap_warn_60s" in diagnostics.flags


def test_strava_reconstructed_gpx_embeds_import_provenance_metadata():
    service = StravaService.__new__(StravaService)
    activity = {
        "name": "Tom & Jerry <Hill>",
        "start_date": datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc).isoformat(),
    }
    streams = _streams(3)
    diagnostics = StravaService.assess_stream_reconstruction_fidelity(
        activity_id=999,
        streams=streams,
    )

    gpx = service._streams_to_gpx(activity, streams, diagnostics)

    assert "<import_source>strava_stream_reconstructed_gpx</import_source>" in gpx
    assert "<source_activity_id>999</source_activity_id>" in gpx
    assert "<quality_tier>unusable</quality_tier>" in gpx
    assert "<name>Tom &amp; Jerry &lt;Hill&gt;</name>" in gpx


def test_strava_reconstructed_gpx_preserves_zero_sensor_samples():
    service = StravaService.__new__(StravaService)
    activity = {
        "name": "Zero Samples",
        "start_date": datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc).isoformat(),
    }
    streams = _streams(3)
    streams["watts"]["data"] = [220, 0, 240]
    streams["heartrate"]["data"] = [150, 0, 152]
    streams["cadence"]["data"] = [88, 0, 90]
    diagnostics = StravaService.assess_stream_reconstruction_fidelity(
        activity_id=1000,
        streams=streams,
    )

    gpx = service._streams_to_gpx(activity, streams, diagnostics)

    assert "<power>0</power>" in gpx
    assert "<hr>0</hr>" in gpx
    assert "<cad>0</cad>" in gpx
