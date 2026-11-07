from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("workout_parse")

from app.services.workout_parse_adapter import (  # noqa: E402
    calculate_metrics_rust,
    parse_ride_file_bytes_rust,
)


START = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)


def _samples() -> list[tuple[datetime, int]]:
    samples: list[tuple[datetime, int]] = []
    for second in list(range(60)) + list(range(360, 420)):
        power = 0 if second % 5 == 0 else 200
        samples.append((START + timedelta(seconds=second), power))
    return samples


def _gpx_bytes() -> bytes:
    points = []
    for index, (timestamp, power) in enumerate(_samples()):
        points.append(
            f'<trkpt lat="{39.95 + index * 0.00001}" lon="{-75.16 + index * 0.00001}">'
            f"<ele>{10 + index * 0.1}</ele><time>{timestamp.isoformat()}</time>"
            "<extensions><gpxtpx:TrackPointExtension>"
            "<gpxtpx:hr>150</gpxtpx:hr><gpxtpx:cad>88</gpxtpx:cad>"
            f"</gpxtpx:TrackPointExtension><br:power>{power}</br:power></extensions>"
            "</trkpt>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1" '
        'xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1" '
        'xmlns:br="https://boulderroller.xyz/xmlschemas/ride/v1">'
        f"<trk><trkseg>{''.join(points)}</trkseg></trk></gpx>"
    ).encode()


def _tcx_bytes() -> bytes:
    points = []
    for index, (timestamp, power) in enumerate(_samples()):
        points.append(
            "<Trackpoint>"
            f"<Time>{timestamp.isoformat()}</Time><Position>"
            f"<LatitudeDegrees>{39.95 + index * 0.00001}</LatitudeDegrees>"
            f"<LongitudeDegrees>{-75.16 + index * 0.00001}</LongitudeDegrees>"
            "</Position>"
            f"<AltitudeMeters>{10 + index * 0.1}</AltitudeMeters>"
            "<HeartRateBpm><Value>150</Value></HeartRateBpm><Cadence>88</Cadence>"
            f"<Extensions><ns3:TPX><ns3:Watts>{power}</ns3:Watts>"
            "</ns3:TPX></Extensions></Trackpoint>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<TrainingCenterDatabase '
        'xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2" '
        'xmlns:ns3="http://www.garmin.com/xmlschemas/ActivityExtension/v2">'
        f'<Activities><Activity Sport="Biking"><Lap StartTime="{START.isoformat()}">'
        f"<Track>{''.join(points)}</Track></Lap></Activity></Activities>"
        "</TrainingCenterDatabase>"
    ).encode()


def test_cross_format_metrics_preserve_zero_power_and_exclude_pause_time() -> None:
    metrics_by_format = {}
    for file_type, payload in (("gpx", _gpx_bytes()), ("tcx", _tcx_bytes())):
        parsed = parse_ride_file_bytes_rust(payload, file_type)
        metrics_by_format[file_type] = calculate_metrics_rust(
            parsed,
            user_ftp_w=200,
        )

    gpx = metrics_by_format["gpx"]
    tcx = metrics_by_format["tcx"]

    assert gpx.metrics_version == "workout_parse_metrics_v1"
    assert gpx.duration_sec == 419
    assert gpx.moving_time_sec == 120
    assert gpx.power_sample_count == 120
    assert gpx.power_sample_coverage_bps == 10_000
    assert gpx.avg_power_w == 160
    assert gpx.normalized_power_w == 160
    assert gpx.tss == pytest.approx(2.1, abs=0.1)

    comparable_fields = (
        "duration_sec",
        "moving_time_sec",
        "avg_power_w",
        "normalized_power_w",
        "tss",
        "power_sample_count",
        "power_sample_coverage_bps",
    )
    assert {field: getattr(gpx, field) for field in comparable_fields} == {
        field: getattr(tcx, field) for field in comparable_fields
    }
