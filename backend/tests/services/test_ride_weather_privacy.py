from datetime import datetime, timedelta, timezone
import json
import logging

import httpx
import pytest

from app.services import ride_weather


@pytest.mark.asyncio
@pytest.mark.parametrize("age_days", [0, 30])
@pytest.mark.parametrize("failure", [False, True])
async def test_weather_only_sends_coarse_grid_and_never_logs_coordinates(monkeypatch, caplog, age_days, failure):
    started = datetime.now(timezone.utc) - timedelta(days=age_days)
    calls = []

    def handler(request):
        calls.append(request)
        if failure:
            # Even a provider exception echoing private input must not reach logs.
            raise RuntimeError("latitude=40.123456&longitude=-79.987654 rider@example.test")
        return httpx.Response(200, json={"hourly": {
            "time": [started.strftime("%Y-%m-%dT%H:00")],
            "temperature_2m": [18.5], "wind_speed_10m": [3.2], "wind_direction_10m": [270],
        }})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(ride_weather.httpx, "AsyncClient", lambda **kwargs: client)
    caplog.set_level(logging.INFO)
    result = await ride_weather.fetch_ride_weather(40.123456, -79.987654, started)
    assert calls[0].url.params["latitude"] == "40.1"
    assert calls[0].url.params["longitude"] == "-80.0"
    if age_days >= 3:
        assert calls[0].url.params["start_date"] == started.date().isoformat()
    assert result == (None if failure else {
        "weather_temp_c": 18.5, "weather_wind_mps": 3.2, "weather_wind_deg": 270,
    })
    evidence = json.dumps([str(call.url) for call in calls]) + caplog.text
    for private in ("40.1234", "79.9877", "40.123456", "79.987654", "rider@example.test"):
        assert private not in evidence


@pytest.mark.asyncio
async def test_weather_keeps_start_elevation_with_recorded_archive_response(monkeypatch):
    from pathlib import Path
    recorded = json.loads((Path(__file__).parents[1] / "fixtures/weather/open_meteo_2025_07_01.json").read_text())
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=recorded)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(ride_weather.httpx, "AsyncClient", lambda **kwargs: client)
    result = await ride_weather.fetch_ride_weather(40.123456, -79.987654,
        datetime(2025, 7, 1, 13, 12, tzinfo=timezone.utc), elevation=374.123456)
    assert requests[0].url.params["elevation"] == "350.0"
    assert requests[0].url.params["latitude"] == "40.1"
    assert recorded["elevation"] == 350
    assert recorded["hourly_units"]["wind_speed_10m"] == "m/s"
    assert result == {"weather_temp_c": 24.0, "weather_wind_mps": 4.25, "weather_wind_deg": 238}


def _metadata_writes():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    return SimpleNamespace(update_ride_metadata=AsyncMock())


@pytest.mark.asyncio
@pytest.mark.parametrize("point_module", ["app.services.ride_parser", "app.services.workout_parse_adapter"])
async def test_capture_sends_the_first_fix_coarsely_and_stores_model_weather(monkeypatch, point_module):
    import importlib
    from types import SimpleNamespace
    from uuid import uuid4

    module = importlib.import_module(point_module)
    point = getattr(module, "GpsPoint", None) or module.GpsPointCompat
    started = datetime(2025, 7, 1, 13, 12, tzinfo=timezone.utc)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"hourly": {
            "time": ["2025-07-01T13:00"], "temperature_2m": [24.0],
            "wind_speed_10m": [4.25], "wind_direction_10m": [238],
        }})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(ride_weather.httpx, "AsyncClient", lambda **kwargs: client)
    ride = SimpleNamespace(started_at=started, gps_track=[
        point(lat=40.123456, lon=-79.987654, elevation_m=374.123456, timestamp=started),
    ])
    repo, ride_id = _metadata_writes(), uuid4()

    await ride_weather.capture_ride_weather(repo, ride_id, ride)

    params = requests[0].url.params
    assert (params["latitude"], params["longitude"], params["elevation"]) == ("40.1", "-80.0", "350.0")
    repo.update_ride_metadata.assert_awaited_once_with(str(ride_id), {
        "weather_temp_c": 24.0, "weather_wind_mps": 4.25, "weather_wind_deg": 238,
        "weather_source": "model",
    })


@pytest.mark.asyncio
async def test_capture_prefers_the_device_thermometer(monkeypatch):
    from types import SimpleNamespace
    from uuid import uuid4

    async def model(**_kwargs):
        return {"weather_temp_c": 24.0, "weather_wind_mps": 4.25, "weather_wind_deg": 238}

    monkeypatch.setattr(ride_weather, "fetch_ride_weather", model)
    ride = SimpleNamespace(started_at=datetime.now(timezone.utc), avg_temperature_c=21.04,
                           gps_track=[SimpleNamespace(lat=40.0, lon=-75.0, elevation_m=None)])
    repo, ride_id = _metadata_writes(), uuid4()

    await ride_weather.capture_ride_weather(repo, ride_id, ride)

    repo.update_ride_metadata.assert_awaited_once_with(str(ride_id), {
        "weather_temp_c": 21.0, "weather_wind_mps": 4.25, "weather_wind_deg": 238,
        "weather_source": "device",
    })


@pytest.mark.asyncio
async def test_capture_logs_a_weather_failure_without_coordinates(caplog):
    from types import SimpleNamespace
    from uuid import uuid4

    # A fix that cannot be read must leave a trace, never a silent gap.
    ride = SimpleNamespace(started_at=datetime.now(timezone.utc),
                           gps_track=[SimpleNamespace(latitude=40.123456, longitude=-79.987654)])
    repo = _metadata_writes()
    caplog.set_level(logging.WARNING)

    await ride_weather.capture_ride_weather(repo, uuid4(), ride)

    repo.update_ride_metadata.assert_not_awaited()
    assert "[RideWeather] model weather failed" in caplog.text and "AttributeError" in caplog.text
    assert "40.1234" not in caplog.text and "79.9876" not in caplog.text
