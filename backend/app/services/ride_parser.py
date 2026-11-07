"""
Ride file parsing - extracts raw data from .fit and .gpx files.

Strava-style: server is source of truth for all parsing.
"""
from __future__ import annotations

import base64
import io
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Union

import fitparse
import gpxpy


class FileType(str, Enum):
    FIT = "fit"
    GPX = "gpx"
    TCX = "tcx"  # future


@dataclass
class GpsPoint:
    """Single GPS trackpoint."""
    lat: float
    lon: float
    elevation_m: Optional[float] = None
    timestamp: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "lat": self.lat,
            "lon": self.lon,
            "elevation_m": self.elevation_m,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


@dataclass
class DataRecord:
    """Single data sample from the ride."""
    timestamp: datetime
    lat: Optional[float] = None
    lon: Optional[float] = None
    elevation_m: Optional[float] = None
    power_w: Optional[int] = None
    heart_rate_bpm: Optional[int] = None
    cadence_rpm: Optional[int] = None
    speed_mps: Optional[float] = None
    distance_m: Optional[float] = None
    temperature_c: Optional[float] = None


@dataclass
class ParsedRide:
    """Result of parsing a ride file."""
    started_at: datetime
    completed_at: datetime
    records: list[DataRecord] = field(default_factory=list)
    gps_track: list[GpsPoint] = field(default_factory=list)

    # Metadata from file
    device_name: Optional[str] = None
    device_serial: Optional[str] = None
    sport: str = "cycling"
    file_name: Optional[str] = None

    def gps_track_as_dicts(self) -> list[dict]:
        """Convert GPS track to JSON-serializable format."""
        return [p.to_dict() for p in self.gps_track]


def parse_ride_file(file_data_b64: str, file_type: Union[FileType, str]) -> ParsedRide:
    """
    Parse a base64-encoded ride file.

    Args:
        file_data_b64: Base64-encoded file contents
        file_type: "fit" or "gpx"

    Returns:
        ParsedRide with extracted records and GPS track

    Raises:
        ValueError: If file is invalid or unparseable
    """
    # Normalize file_type to enum
    if isinstance(file_type, str):
        file_type = FileType(file_type.lower())

    try:
        raw_bytes = base64.b64decode(file_data_b64)
    except Exception as e:
        raise ValueError(f"Invalid base64 encoding: {e}")

    if file_type == FileType.FIT:
        return _parse_fit(raw_bytes)
    elif file_type == FileType.GPX:
        return _parse_gpx(raw_bytes)
    else:
        raise ValueError(f"Unsupported file type: {file_type}")


def _parse_fit(raw_bytes: bytes) -> ParsedRide:
    """Parse a .fit file (Garmin, Wahoo, etc.)."""
    try:
        fit = fitparse.FitFile(io.BytesIO(raw_bytes))
    except Exception as e:
        raise ValueError(f"Invalid FIT file: {e}")

    records: list[DataRecord] = []
    gps_track: list[GpsPoint] = []
    device_name: Optional[str] = None
    sport = "cycling"

    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    for record in fit.get_messages():
        msg_name = record.name

        # Extract device info
        if msg_name == "file_id":
            for fld in record.fields:
                if fld.name == "manufacturer":
                    device_name = str(fld.value)

        # Extract sport type
        if msg_name == "sport":
            for fld in record.fields:
                if fld.name == "sport":
                    sport = str(fld.value).lower()

        # Extract data records
        if msg_name == "record":
            data = {f.name: f.value for f in record.fields}

            ts = data.get("timestamp")
            if not ts:
                continue

            # Track start/end times
            if started_at is None or ts < started_at:
                started_at = ts
            if completed_at is None or ts > completed_at:
                completed_at = ts

            # Convert semicircles to degrees (FIT format)
            lat = _semicircles_to_degrees(data.get("position_lat"))
            lon = _semicircles_to_degrees(data.get("position_long"))

            rec = DataRecord(
                timestamp=ts,
                lat=lat,
                lon=lon,
                elevation_m=data.get("altitude") or data.get("enhanced_altitude"),
                power_w=data.get("power"),
                heart_rate_bpm=data.get("heart_rate"),
                cadence_rpm=data.get("cadence"),
                speed_mps=data.get("enhanced_speed") or data.get("speed"),
                distance_m=data.get("distance"),
                temperature_c=data.get("temperature"),
            )
            records.append(rec)

            # Build GPS track
            if lat is not None and lon is not None:
                gps_track.append(GpsPoint(
                    lat=lat,
                    lon=lon,
                    elevation_m=rec.elevation_m,
                    timestamp=ts,
                ))

    if not records:
        raise ValueError("No data records found in FIT file")

    # Ensure timezone-aware
    if started_at and started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    if completed_at and completed_at.tzinfo is None:
        completed_at = completed_at.replace(tzinfo=timezone.utc)

    return ParsedRide(
        started_at=started_at or datetime.now(timezone.utc),
        completed_at=completed_at or datetime.now(timezone.utc),
        records=records,
        gps_track=gps_track,
        device_name=device_name,
        sport=sport,
    )


def _parse_gpx(raw_bytes: bytes) -> ParsedRide:
    """Parse a .gpx file (generic GPS exchange format)."""
    try:
        gpx = gpxpy.parse(raw_bytes.decode("utf-8"))
    except Exception as e:
        raise ValueError(f"Invalid GPX file: {e}")

    records: list[DataRecord] = []
    gps_track: list[GpsPoint] = []

    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                ts = point.time
                if ts is None:
                    continue

                # Ensure timezone-aware
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)

                if started_at is None or ts < started_at:
                    started_at = ts
                if completed_at is None or ts > completed_at:
                    completed_at = ts

                # GPX extensions may contain HR, power, cadence
                hr = _gpx_extension(point, "hr") or _gpx_extension(point, "heartrate")
                power = _gpx_extension(point, "power")
                cadence = _gpx_extension(point, "cad") or _gpx_extension(point, "cadence")

                rec = DataRecord(
                    timestamp=ts,
                    lat=point.latitude,
                    lon=point.longitude,
                    elevation_m=point.elevation,
                    heart_rate_bpm=int(hr) if hr else None,
                    power_w=int(power) if power else None,
                    cadence_rpm=int(cadence) if cadence else None,
                )
                records.append(rec)

                gps_track.append(GpsPoint(
                    lat=point.latitude,
                    lon=point.longitude,
                    elevation_m=point.elevation,
                    timestamp=ts,
                ))

    if not records:
        raise ValueError("No trackpoints found in GPX file")

    return ParsedRide(
        started_at=started_at or datetime.now(timezone.utc),
        completed_at=completed_at or datetime.now(timezone.utc),
        records=records,
        gps_track=gps_track,
        sport="cycling",
    )


def _semicircles_to_degrees(value: Optional[int]) -> Optional[float]:
    """Convert FIT semicircles to decimal degrees."""
    if value is None:
        return None
    return value * (180.0 / 2**31)


def _gpx_extension(point, name: str) -> Optional[str]:
    """Extract a value from GPX extensions."""
    for ext in point.extensions:
        # Handle namespaced tags like {ns}hr
        tag = ext.tag.split("}")[-1].lower()
        if tag == name.lower():
            return ext.text
        # Check children
        for child in ext:
            child_tag = child.tag.split("}")[-1].lower()
            if child_tag == name.lower():
                return child.text
    return None
