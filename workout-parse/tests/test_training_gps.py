"""Generated GPX/TCX vectors matching iOS recording fields; no rider data."""

from datetime import datetime, timedelta, timezone
import math
import random

import pytest
import workout_parse as wp


def gps_activity(kind="gpx", cadence=False):
    rng = random.Random(7)
    origin = datetime(2026, 10, 8, 1, 0, tzinfo=timezone.utc)
    lat, distance = 40.0, 0.0
    points = []
    for second in range(1801):
        if second and not 900 < second <= 1020:
            distance += 7
            lat += math.degrees(7 / 6_371_000)
        stamp = (origin + timedelta(seconds=second)).isoformat()
        elevation = 30 + distance * 0.004 + rng.uniform(-0.6, 0.6)
        cad = 0 if second % 300 < 60 else 85  # coasting is still moving
        if kind == "gpx":
            sensors = f"<gpxtpx:cad>{cad}</gpxtpx:cad>" if cadence else ""
            points.append(
                f'<trkpt lat="{lat:.7f}" lon="-75.2"><ele>{elevation:.2f}</ele>'
                f"<time>{stamp}</time><extensions><gpxtpx:TrackPointExtension>"
                f"<gpxtpx:hr>150</gpxtpx:hr>{sensors}</gpxtpx:TrackPointExtension>"
                "<br:power>180</br:power></extensions></trkpt>"
            )
        else:
            points.append(
                f"<Trackpoint><Time>{stamp}</Time><Position><LatitudeDegrees>{lat:.7f}"
                "</LatitudeDegrees><LongitudeDegrees>-75.2</LongitudeDegrees></Position>"
                f"<AltitudeMeters>{elevation:.2f}</AltitudeMeters>"
                "<HeartRateBpm><Value>150</Value></HeartRateBpm>"
                "<Extensions><TPX><Watts>180</Watts></TPX></Extensions></Trackpoint>"
            )
    if kind == "gpx":
        xml = (
            '<gpx version="1.1" creator="Boulder Roller iOS" '
            'xmlns="http://www.topografix.com/GPX/1/1" '
            'xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1" '
            'xmlns:br="https://boulderroller.xyz/gpx/1"><trk><trkseg>'
            + "".join(points)
            + "</trkseg></trk></gpx>"
        )
    else:
        xml = (
            '<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">'
            '<Activities><Activity Sport="Biking"><Id>' + origin.isoformat() + "</Id>"
            '<Lap StartTime="'
            + origin.isoformat()
            + '"><Track>'
            + "".join(points)
            + "</Track></Lap></Activity></Activities></TrainingCenterDatabase>"
        )
    return wp.parse_bytes(xml.encode())


@pytest.mark.parametrize(
    "kind,cadence", [("gpx", False), ("gpx", True), ("tcx", False)]
)
def test_gps_motion_coasting_stops_distance_and_smoothed_elevation(kind, cadence):
    activity = gps_activity(kind, cadence)
    result = wp.compute_training_metrics(activity, 250, engine_version=2)
    assert result.distance_m == pytest.approx(11_760, abs=1)
    assert result.moving_s == 1680
    assert result.elapsed_s == 1800
    assert result.avg_speed_mps == pytest.approx(7, abs=0.001)
    assert result.elevation_gain_m == pytest.approx(47.04, abs=5)
    assert result.load is not None
    assert wp.compute_training_metrics(activity, 250).distance_m == (
        0 if kind == "tcx" else None
    )  # v1 replay


def test_gpx_selected_span_uses_its_own_gps_and_cannot_count_the_stop():
    result = wp.compute_training_metrics(
        gps_activity(), 250, engine_version=2, start_s=900, end_s=1020
    )
    assert result.distance_m == 0
    assert result.moving_s == 0
    assert result.avg_speed_mps is None
