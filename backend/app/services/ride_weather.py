"""Display-only ride weather, captured once at processing time.

Effort-integrity co-signing was DROPPED (physics residual study wm0w):
weather here is a fact for the ride page, never an input to CAL. Fetches
are best-effort with a hard timeout; absence stays absence.
"""
from __future__ import annotations

from .privacy_logging import scrub_log_text
import logging
import math
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


async def capture_ride_weather(ride_repo: Any, ride_id: Any, parsed_ride: Any) -> None:
    """Store display-only weather at the ride's first fix; never a CAL input.

    Best-effort: a failure is logged and the ride carries no weather. Parsed
    fixes carry ``lat``/``lon``; fetch_ride_weather sends the provider only a
    0.1 degree grid and a 50 m elevation band.
    """
    weather: Optional[dict[str, Any]] = None
    try:
        first_fix = parsed_ride.gps_track[0] if parsed_ride.gps_track else None
        if first_fix is not None:
            weather = await fetch_ride_weather(
                latitude=float(first_fix.lat),
                longitude=float(first_fix.lon),
                started_at=parsed_ride.started_at,
                elevation=getattr(first_fix, "elevation_m", None),
            )
    except Exception as exc:
        logger.warning(
            "[RideWeather] model weather failed for ride %s: %s: %s",
            ride_id, type(exc).__name__, scrub_log_text(exc),
        )
    # The thermometer that was on the bike beats the reanalysis model
    # whenever the file carries it.
    device_temp = getattr(parsed_ride, "avg_temperature_c", None)
    if device_temp is not None:
        weather = {
            **(weather or {}),
            "weather_temp_c": round(float(device_temp), 1),
            "weather_source": "device",
        }
    elif weather:
        weather = {**weather, "weather_source": "model"}
    if not weather:
        return
    try:
        await ride_repo.update_ride_metadata(str(ride_id), weather)
    except Exception as exc:
        logger.warning(
            "[RideWeather] weather write failed for ride %s: %s: %s",
            ride_id, type(exc).__name__, scrub_log_text(exc),
        )


async def fetch_ride_weather(
    latitude: float,
    longitude: float,
    started_at: datetime,
    *,
    elevation: float | None = None,
) -> Optional[dict[str, Any]]:
    """Hourly regional temperature and wind at the start hour, or None.

    Quantize at this provider boundary, for both endpoints and every caller.
    A 0.1 degree grid (~11 km north/south) retains regional model weather
    without disclosing a house-level fix. Device temperature still takes
    precedence in the processor.
    """
    try:
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        day = started_at.date().isoformat()
        # The archive lags ~2 days; recent rides read the forecast API's
        # past_days window instead.
        age_days = (datetime.now(timezone.utc) - started_at).days
        if age_days >= 3:
            url = _ARCHIVE_URL
            params = {
                "latitude": f"{latitude:.1f}",
                "longitude": f"{longitude:.1f}",
                "start_date": day,
                "end_date": day,
                "hourly": "temperature_2m,wind_speed_10m,wind_direction_10m",
                "wind_speed_unit": "ms",
                "timezone": "UTC",
            }
        else:
            url = _FORECAST_URL
            params = {
                "latitude": f"{latitude:.1f}",
                "longitude": f"{longitude:.1f}",
                "past_days": 3,
                "forecast_days": 1,
                "hourly": "temperature_2m,wind_speed_10m,wind_direction_10m",
                "wind_speed_unit": "ms",
                "timezone": "UTC",
            }
        if elevation is not None and math.isfinite(elevation):
            params["elevation"] = float(round(elevation / 50) * 50)
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        hours = payload.get("hourly", {})
        times = hours.get("time") or []
        target = started_at.strftime("%Y-%m-%dT%H:00")
        if target not in times:
            return None
        index = times.index(target)

        def value(key: str) -> Optional[float]:
            series = hours.get(key) or []
            if index >= len(series):
                return None
            raw = series[index]
            return float(raw) if raw is not None else None

        temp = value("temperature_2m")
        wind = value("wind_speed_10m")
        direction = value("wind_direction_10m")
        if temp is None and wind is None:
            return None
        return {
            "weather_temp_c": temp,
            "weather_wind_mps": wind,
            "weather_wind_deg": int(direction) if direction is not None else None,
        }
    except Exception as exc:  # Best-effort by design: absence stays absence.
        logger.info('[RideWeather] capture skipped error=%s', scrub_log_text(exc))
        return None
