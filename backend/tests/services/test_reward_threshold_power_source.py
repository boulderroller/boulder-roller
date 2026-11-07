from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.reward_threshold import (
    threshold_effort_evidence,
    threshold_effort_evidence_or_empty,
    threshold_source_evidence,
)
from app.services.workout_parse_adapter import (
    DataRecordCompat,
    GpsPointCompat,
    ParsedRideCompat,
    apply_gpx_elevation_provenance,
    parse_ride_file_bytes_rust,
)


SOURCE_A = "11111111-1111-4111-8111-111111111111"
SOURCE_B = "22222222-2222-4222-8222-222222222222"


def _parsed(point_count: int) -> ParsedRideCompat:
    started_at = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)
    records = [
        DataRecordCompat(
            timestamp=started_at + timedelta(seconds=index),
            lat=40.0 + index / 10_000,
            lon=-75.0,
            power_w=250 + index,
        )
        for index in range(point_count)
    ]
    return ParsedRideCompat(
        started_at=started_at,
        completed_at=records[-1].timestamp,
        records=records,
        gps_track=[
            GpsPointCompat(
                lat=record.lat,
                lon=record.lon,
                timestamp=record.timestamp,
            )
            for record in records
        ],
    )


def _gpx(*source_ids: str | None, creator: str = "Boulder Roller iOS") -> bytes:
    points = []
    for index, source_id in enumerate(source_ids):
        source = (
            f"<br:power-source>{source_id}</br:power-source>"
            if source_id is not None
            else ""
        )
        points.append(
            f"""
            <trkpt lat="{40.0 + index / 10_000:.4f}" lon="-75.0000">
              <time>2026-08-24T12:00:0{index}Z</time>
              <extensions><br:power>{250 + index}</br:power>{source}</extensions>
            </trkpt>
            """
        )
    return (
        f"""<?xml version="1.0"?>
        <gpx creator="{creator}" xmlns="http://www.topografix.com/GPX/1/1"
             xmlns:br="https://boulderroller.xyz/gpx/v1">
          <trk><trkseg>{''.join(points)}</trkseg></trk>
        </gpx>"""
    ).encode()


def _gpx_with_wrong_source_namespace() -> bytes:
    return _gpx(SOURCE_A, None).replace(
        b'xmlns:br="https://boulderroller.xyz/gpx/v1"',
        b'xmlns:br="https://example.invalid/not-br"',
    )


def test_br_ios_power_source_is_carried_across_compressed_markers() -> None:
    parsed = apply_gpx_elevation_provenance(
        _parsed(3),
        _gpx(SOURCE_A, None, None),
    )

    assert [record.power_source_id for record in parsed.records] == [
        SOURCE_A,
        SOURCE_A,
        SOURCE_A,
    ]
    evidence = threshold_source_evidence(parsed)
    assert evidence.recording_source == "br_ios"
    assert evidence.power_source_ids == (SOURCE_A,)
    assert evidence.identity_complete is True
    assert evidence.economic_eligible is True


def test_missing_malformed_or_mixed_source_abstains_without_rejecting_ride() -> None:
    missing = apply_gpx_elevation_provenance(_parsed(2), _gpx(None, None))
    malformed = apply_gpx_elevation_provenance(
        _parsed(2), _gpx("not-a-uuid", None)
    )
    mixed = apply_gpx_elevation_provenance(
        _parsed(3), _gpx(SOURCE_A, SOURCE_B, None)
    )

    assert threshold_source_evidence(missing).eligibility_reason == (
        "missing_power_source_identity"
    )
    assert threshold_source_evidence(malformed).eligibility_reason == (
        "invalid_power_source_identity"
    )
    assert threshold_source_evidence(mixed).eligibility_reason == (
        "mixed_power_source_identity"
    )
    assert len(missing.records) == len(malformed.records) == 2
    assert len(mixed.records) == 3


def test_non_br_gpx_can_inform_display_but_not_economic_candidate() -> None:
    parsed = apply_gpx_elevation_provenance(
        _parsed(2),
        _gpx(SOURCE_A, None, creator="Strava GPX export"),
    )

    evidence = threshold_source_evidence(parsed)
    assert evidence.recording_source is None
    assert evidence.economic_eligible is False
    assert evidence.eligibility_reason == "not_br_ios_recording"
    assert evidence.as_ride_fields()["threshold_power_source_id"] is None


def test_wrong_namespace_or_record_mismatch_abstains() -> None:
    wrong_namespace = apply_gpx_elevation_provenance(
        _parsed(2), _gpx_with_wrong_source_namespace()
    )
    mismatch_ride = _parsed(2)
    mismatch_ride.records[1].power_w = 999
    mismatched = apply_gpx_elevation_provenance(
        mismatch_ride, _gpx(SOURCE_A, None)
    )

    assert threshold_source_evidence(wrong_namespace).eligibility_reason == (
        "missing_power_source_identity"
    )
    assert mismatched.threshold_source_identity_error == "record_alignment_mismatch"
    assert threshold_source_evidence(mismatched).economic_eligible is False


def test_native_parser_exposes_pause_aware_threshold_anchors_to_backend() -> None:
    started = datetime(2026, 8, 24, 8, tzinfo=timezone.utc)
    points = []
    for index in range(900):
        marker = (
            f"<br:power-source>{SOURCE_A}</br:power-source>"
            if index == 0
            else ""
        )
        timestamp = (started + timedelta(seconds=index)).isoformat().replace(
            "+00:00", "Z"
        )
        points.append(
            f'<trkpt lat="40.0000" lon="-75.0000"><time>{timestamp}</time>'
            f'<extensions><br:power>300</br:power>{marker}</extensions></trkpt>'
        )
    gpx = (
        '<?xml version="1.0"?><gpx creator="Boulder Roller iOS" '
        'xmlns="http://www.topografix.com/GPX/1/1" '
        'xmlns:br="https://boulderroller.xyz/gpx/v1"><trk><trkseg>'
        + "".join(points)
        + "</trkseg></trk></gpx>"
    ).encode()

    evidence = threshold_effort_evidence(
        parse_ride_file_bytes_rust(gpx, "gpx")
    )

    assert evidence.best_180s_w == 300.0
    assert evidence.best_420s_w == 300.0
    assert evidence.best_900s_w == 300.0
    assert evidence.source.economic_eligible is True


def test_missing_threshold_anchor_capability_abstains_without_failing_ingest(
    monkeypatch,
) -> None:
    parsed = apply_gpx_elevation_provenance(
        _parsed(2),
        _gpx(SOURCE_A, None),
    )
    parsed._native_activity = object()
    monkeypatch.setattr(
        "app.services.workout_parse_adapter._get_workout_parse",
        lambda: object(),
    )

    evidence = threshold_effort_evidence_or_empty(parsed)

    assert (evidence.best_180s_w, evidence.best_420s_w, evidence.best_900s_w) == (
        None,
        None,
        None,
    )
    assert evidence.source.economic_eligible is True


@pytest.mark.parametrize(
    ("old", "new"),
    (
        (b"2026-08-24T12:00:01Z", b"not-a-time"),
        (b"<br:power>251</br:power>", b"<br:power>251.5</br:power>"),
    ),
)
def test_bad_threshold_value_keeps_valid_elevation_provenance_but_abstains(
    old: bytes,
    new: bytes,
) -> None:
    gpx = _gpx(SOURCE_A, None).replace(old, new).replace(
        b"<extensions>",
        (
            b"<extensions><elevation-source>barometer_fused</elevation-source>"
            b"<elevation-confidence>high</elevation-confidence>"
            b"<raw-gps-altitude-m>321.5</raw-gps-altitude-m>"
            b"<relative-barometer-m>4.25</relative-barometer-m>"
        ),
    )

    parsed = apply_gpx_elevation_provenance(_parsed(2), gpx)

    assert all(point.elevation_provenance_available for point in parsed.gps_track)
    assert all(point.raw_elevation_m == 321.5 for point in parsed.gps_track)
    assert parsed.threshold_source_identity_complete is False
    assert parsed.threshold_source_identity_error == "record_alignment_mismatch"
    assert threshold_source_evidence(parsed).economic_eligible is False


def test_native_parser_drop_keeps_elevation_on_remaining_coordinate() -> None:
    gpx = _gpx(SOURCE_A, None).replace(
        b"2026-08-24T12:00:00Z",
        b"not-a-time",
    ).replace(
        b"<extensions>",
        (
            b"<extensions><elevation-source>barometer_fused</elevation-source>"
            b"<elevation-confidence>high</elevation-confidence>"
            b"<raw-gps-altitude-m>321.5</raw-gps-altitude-m>"
            b"<relative-barometer-m>4.25</relative-barometer-m>"
        ),
    )

    parsed = parse_ride_file_bytes_rust(gpx, "gpx")

    assert len(parsed.gps_track) == 1
    assert parsed.gps_track[0].lat == pytest.approx(40.0001)
    assert parsed.gps_track[0].elevation_provenance_available is True
    assert parsed.gps_track[0].raw_elevation_m == 321.5
    assert parsed.gps_track[0].starts_new_segment is True
    assert parsed.threshold_source_identity_complete is False
    assert parsed.threshold_source_identity_error == "record_alignment_mismatch"


@pytest.mark.parametrize(
    "power_xml",
    (
        b"<br:power>250.5</br:power>",
        b"<br:power>250.5</br:power><br:power>250</br:power>",
        b"<br:power>250</br:power><br:power>-1</br:power>",
    ),
)
def test_native_parser_never_masks_an_invalid_threshold_value(
    power_xml: bytes,
) -> None:
    gpx = _gpx(SOURCE_A, None).replace(
        b"<br:power>250</br:power>",
        power_xml,
    ).replace(
        b"<extensions>",
        (
            b"<extensions><elevation-source>barometer_fused</elevation-source>"
            b"<elevation-confidence>high</elevation-confidence>"
            b"<raw-gps-altitude-m>321.5</raw-gps-altitude-m>"
        ),
    )

    parsed = parse_ride_file_bytes_rust(gpx, "gpx")

    assert any(point.elevation_provenance_available for point in parsed.gps_track)
    assert parsed.threshold_source_identity_complete is False
    assert parsed.threshold_source_identity_error == "record_alignment_mismatch"
    assert threshold_source_evidence(parsed).economic_eligible is False
