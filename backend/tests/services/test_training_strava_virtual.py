import pytest
import workout_parse as wp

from app.services.strava_service import StravaService
from app.services.training_metrics import evidence_for
from backend.tests.services.test_strava_import_diagnostics import _streams


@pytest.mark.parametrize(
    "metadata",
    [
        {"type": "VirtualRide"},
        {"sport_type": "VirtualRide"},
        {"trainer": True},
        {"device_name": "Zwift"},
        {"device_name": "ROUVY"},
        {"device_name": "MyWhoosh"},
    ],
)
def test_strava_virtual_import_cannot_use_london_map_to_date_the_ride(metadata):
    service = StravaService.__new__(StravaService)
    streams = _streams()
    streams["latlng"]["data"] = [[51.5 + i * 0.0001, -0.1] for i in range(60)]
    outdoor = {
        "type": "Ride",
        "start_date": "2026-10-07T23:00:00Z",
        "name": "Synthetic",
    }
    before = wp.parse_file_bytes(
        service._streams_to_gpx(outdoor, streams).encode(), "gpx"
    )
    virtual = wp.parse_file_bytes(
        service._streams_to_gpx({**outdoor, **metadata}, streams).encode(), "gpx"
    )
    assert virtual.training_context["indoor_or_virtual"] is True
    assert evidence_for(virtual)["timezone"] is None
    assert evidence_for(before)["timezone"] == "Europe/London"
    assert wp.hash_canonical_ride(before) == wp.hash_canonical_ride(virtual)
    assert wp.compute_metrics(before, 250).tss == wp.compute_metrics(virtual, 250).tss
