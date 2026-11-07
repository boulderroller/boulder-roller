"""
Adapter layer for workout-parse Rust module.

Provides compatibility with existing ride_parser.py / ride_metrics.py interfaces,
allowing gradual migration without breaking changes.

Usage:
    # Feature flag in environment
    USE_RUST_PARSER=true

    # Or use directly
    from .workout_parse_adapter import parse_ride_file_rust, calculate_metrics_rust
"""

from __future__ import annotations

import base64
from collections import defaultdict, deque
import logging
import math
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, List, Mapping, Optional, Sequence, Tuple

import numpy as np
from defusedxml import ElementTree as SafeElementTree

logger = logging.getLogger(__name__)

BR_GPX_NAMESPACE = "https://boulderroller.xyz/gpx/v1"

# Feature flag
USE_RUST_PARSER = os.getenv("USE_RUST_PARSER", "false").lower() == "true"

# Lazy import to avoid errors if module not built
_wp = None


def _finite_float_or_none(value) -> Optional[float]:
    """Convert Rust float sentinels like NaN into Python missing values."""
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _get_workout_parse():
    """Lazy import workout_parse module."""
    global _wp
    if _wp is None:
        try:
            import workout_parse as wp
            _wp = wp
        except ImportError as e:
            logger.warning(f"workout_parse not available: {e}")
            raise
    return _wp


@dataclass
class DataRecordCompat:
    """Compatible with existing ride_parser.DataRecord."""
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
    # BR GPX sidecar evidence. This does not participate in canonical ride
    # hashing; it binds powered samples to the paired meter selected by iOS.
    power_source_id: Optional[str] = None


@dataclass
class GpsPointCompat:
    """Compatible with existing ride_parser.GpsPoint."""
    lat: float
    lon: float
    elevation_m: Optional[float] = None
    timestamp: Optional[datetime] = None
    raw_elevation_m: Optional[float] = None
    relative_barometer_m: Optional[float] = None
    elevation_source: Optional[str] = None
    elevation_confidence: Optional[str] = None
    elevation_provenance_available: bool = False
    starts_new_segment: bool = False

    def to_dict(self) -> dict:
        return {
            "lat": self.lat,
            "lon": self.lon,
            "elevation_m": self.elevation_m,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "raw_elevation_m": self.raw_elevation_m,
            "relative_barometer_m": self.relative_barometer_m,
            "elevation_source": self.elevation_source,
            "elevation_confidence": self.elevation_confidence,
            "elevation_provenance_available": self.elevation_provenance_available,
            "starts_new_segment": self.starts_new_segment,
        }


@dataclass
class ParsedRideCompat:
    """Compatible with existing ride_parser.ParsedRide."""
    started_at: datetime
    completed_at: datetime
    records: List[DataRecordCompat]
    gps_track: List[GpsPointCompat]
    device_name: Optional[str] = None
    device_serial: Optional[str] = None
    sport: str = "cycling"
    file_name: Optional[str] = None
    # Device testimony held outside canonicalization (FIT evidence pass,
    # 2026-08-18): provenance rows, Session claims, explicit pause spans,
    # and on-bike ambient temperature. Absent for GPX/TCX and older files.
    device_provenance: List[dict] = field(default_factory=list)
    device_summary: Optional[dict] = None
    timer_pause_count: int = 0
    event_moving_time_s: Optional[int] = None
    avg_temperature_c: Optional[float] = None
    laps: List[dict] = field(default_factory=list)
    power_balance: Optional[dict] = None
    gps_accuracy_stats: Optional[dict] = None
    threshold_recording_source: Optional[str] = None
    threshold_power_source_ids: tuple[str, ...] = ()
    threshold_source_identity_complete: bool = False
    threshold_source_identity_error: Optional[str] = None
    _native_activity: object = field(default=None, repr=False, compare=False)

    def gps_track_as_dicts(self) -> list[dict]:
        return [p.to_dict() for p in self.gps_track]


@dataclass
class RideMetricsCompat:
    """Compatible with existing ride_metrics.RideMetrics."""
    duration_sec: int
    distance_m: float
    elevation_gain_m: float
    tss: float
    kcals: float
    avg_power_w: Optional[float] = None
    avg_hr_bpm: Optional[float] = None
    avg_speed_mps: Optional[float] = None
    avg_cadence_rpm: Optional[float] = None
    max_power_w: Optional[int] = None
    max_hr_bpm: Optional[int] = None
    max_speed_mps: Optional[float] = None
    normalized_power_w: Optional[float] = None
    normalized_power_raw_w: Optional[float] = None
    normalized_power_duration_s: int = 0
    moving_time_sec: int = 0
    metrics_version: str = ""
    power_sample_count: int = 0
    power_sample_coverage_bps: int = 0
    heart_rate_sample_count: int = 0
    heart_rate_sample_coverage_bps: int = 0


@dataclass(frozen=True)
class SegmentPowerMetricsCompat:
    """Canonical power evidence for one frozen climb interval."""

    normalized_power_w: Optional[int]
    normalized_power_milliwatts: Optional[int]
    normalized_power_duration_s: int
    power_sample_count: int
    power_sample_coverage_bps: int
    moving_time_s: int
    metrics_version: str


def parse_ride_file_bytes_rust(file_bytes: bytes, file_type: str) -> ParsedRideCompat:
    """
    Parse a ride file from raw bytes using the Rust parser.

    Preferred entry point — skips the base64 encode/decode round-trip.
    Falls back to parse_bytes if parse_file_bytes is not available.
    """
    wp = _get_workout_parse()

    # Use parse_file_bytes (with type hint) if available, else fall back to parse_bytes
    if hasattr(wp, "parse_file_bytes"):
        activity = wp.parse_file_bytes(file_bytes, file_type or "auto")
    else:
        activity = wp.parse_bytes(file_bytes)

    parsed_ride = _activity_to_parsed_ride(activity, wp)
    _attach_device_evidence(parsed_ride, activity)
    return apply_gpx_elevation_provenance(parsed_ride, file_bytes)


def parse_ride_file_rust(file_data_b64: str, file_type: str) -> ParsedRideCompat:
    """
    Parse a ride file using the Rust parser.

    Drop-in replacement for ride_parser.parse_ride_file().
    """
    wp = _get_workout_parse()

    # Decode base64
    raw_bytes = base64.b64decode(file_data_b64)

    # Parse with Rust
    activity = wp.parse_bytes(raw_bytes)

    parsed_ride = _activity_to_parsed_ride(activity, wp)
    return apply_gpx_elevation_provenance(parsed_ride, raw_bytes)


def apply_gpx_elevation_provenance(
    parsed_ride: ParsedRideCompat,
    file_bytes: bytes,
) -> ParsedRideCompat:
    """Attach BR GPX elevation evidence to the projection-only compat track.

    The native workout-parse Activity remains unchanged so canonicalization,
    detector inputs, and economic metrics retain their frozen source behavior.
    A plain ``<ele>`` is device elevation, not automatically "raw GPS". If the
    BR provenance contract is absent, raw fields remain nil and availability is
    explicitly false.
    """
    parsed_sidecar = _parse_br_gpx_elevation_provenance(file_bytes)
    if parsed_sidecar is None:
        return parsed_ride
    entries, creator = parsed_sidecar
    parsed_ride.threshold_recording_source = (
        "br_ios" if creator == "Boulder Roller iOS" else None
    )
    coordinate_entries: dict[tuple[float, float], deque[int]] = defaultdict(deque)
    exact_entries: dict[
        tuple[float, float, datetime], deque[int]
    ] = defaultdict(deque)
    segment_start_prefix = [0]
    for entry_index, entry in enumerate(entries):
        coordinate_key = (
            round(float(entry["latitude"]), 6),
            round(float(entry["longitude"]), 6),
        )
        coordinate_entries[coordinate_key].append(entry_index)
        entry_time = entry.get("timestamp")
        if entry_time is not None:
            exact_entries[(*coordinate_key, entry_time)].append(entry_index)
        segment_start_prefix.append(
            segment_start_prefix[-1] + int(entry["starts_new_segment"])
        )

    matched_entries: list[tuple[GpsPointCompat, dict[str, Any], bool]] = []
    entry_cursor = 0
    for point in parsed_ride.gps_track:
        coordinate_key = (
            round(float(point.lat), 6),
            round(float(point.lon), 6),
        )
        point_time = point.timestamp
        if point_time is not None:
            point_time = (
                point_time.replace(tzinfo=timezone.utc)
                if point_time.tzinfo is None
                else point_time.astimezone(timezone.utc)
            )
        chosen_index: Optional[int] = None
        if point_time is not None:
            exact_matches = exact_entries.get((*coordinate_key, point_time))
            while exact_matches and exact_matches[0] < entry_cursor:
                exact_matches.popleft()
            if exact_matches:
                chosen_index = exact_matches[0]
        coordinate_matches = coordinate_entries.get(coordinate_key)
        while coordinate_matches and coordinate_matches[0] < entry_cursor:
            coordinate_matches.popleft()
        if chosen_index is None and coordinate_matches and len(coordinate_matches) == 1:
            chosen_index = coordinate_matches[0]
        if chosen_index is None:
            continue
        starts_new_segment = (
            segment_start_prefix[chosen_index + 1]
            > segment_start_prefix[entry_cursor]
        )
        matched_entries.append(
            (point, entries[chosen_index], starts_new_segment)
        )
        entry_cursor = chosen_index + 1

    for point, entry, starts_new_segment in matched_entries:
        point.starts_new_segment = starts_new_segment
        source = entry.get("elevation_source")
        confidence = entry.get("elevation_confidence")
        raw_elevation = entry.get("raw_elevation_m")
        available = (
            source in {"barometer_fused", "gps"}
            and confidence in {"high", "medium"}
            and raw_elevation is not None
        )
        point.elevation_provenance_available = available
        if available:
            point.raw_elevation_m = raw_elevation
            point.relative_barometer_m = entry.get("relative_barometer_m")
            point.elevation_source = source
            point.elevation_confidence = confidence

    identity_complete = (
        len(parsed_ride.records)
        == len(parsed_ride.gps_track)
        == len(entries)
        == len(matched_entries)
    )
    identity_error: Optional[str] = (
        None if identity_complete else "record_alignment_mismatch"
    )
    if identity_complete:
        for record, entry in zip(parsed_ride.records, entries):
            entry_time = entry.get("timestamp")
            entry_power = entry.get("power_w")
            if (
                entry.get("threshold_value_invalid") is True
                or entry_time is None
                or record.timestamp.astimezone(timezone.utc) != entry_time
                or record.power_w != entry_power
            ):
                identity_complete = False
                identity_error = "record_alignment_mismatch"
                break
    else:
        identity_error = "record_alignment_mismatch"

    current_power_source_id: Optional[str] = None
    source_ids: set[str] = set()
    if identity_complete:
        assignments: list[Optional[str]] = []
        for record, entry in zip(parsed_ride.records, entries):
            marker = entry.get("power_source_marker")
            if marker is not None:
                try:
                    current_power_source_id = str(uuid.UUID(marker))
                    source_ids.add(current_power_source_id)
                except (AttributeError, TypeError, ValueError):
                    current_power_source_id = None
                    identity_complete = False
                    identity_error = "invalid_power_source_identity"
                    break
            assignments.append(current_power_source_id)
            if record.power_w is not None and current_power_source_id is None:
                identity_complete = False
        if identity_complete:
            for record, source_id in zip(parsed_ride.records, assignments):
                if record.power_w is not None:
                    record.power_source_id = source_id

    parsed_ride.threshold_power_source_ids = tuple(sorted(source_ids))
    parsed_ride.threshold_source_identity_complete = identity_complete
    parsed_ride.threshold_source_identity_error = identity_error
    return parsed_ride


def _parse_br_gpx_elevation_provenance(
    file_bytes: bytes,
) -> Optional[tuple[list[dict[str, Any]], Optional[str]]]:
    try:
        root = SafeElementTree.fromstring(file_bytes)
    except Exception:
        return None
    if _xml_local_name(root.tag) != "gpx":
        return None

    segments = [
        element for element in root.iter()
        if _xml_local_name(element.tag) == "trkseg"
    ]
    grouped_points = [
        [
            element for element in segment.iter()
            if _xml_local_name(element.tag) == "trkpt"
        ]
        for segment in segments
    ]
    if not grouped_points:
        grouped_points = [[
            element for element in root.iter()
            if _xml_local_name(element.tag) == "trkpt"
        ]]

    entries: list[dict[str, Any]] = []
    for segment_points in grouped_points:
        for point_index, element in enumerate(segment_points):
            entry = _gpx_provenance_entry(
                element,
                starts_new_segment=point_index == 0,
            )
            if entry is None:
                return None
            entries.append(entry)
    return entries, root.attrib.get("creator")


def _gpx_provenance_entry(
    element: Any,
    *,
    starts_new_segment: bool,
) -> Optional[dict[str, Any]]:
    latitude = _finite_float_or_none(element.attrib.get("lat"))
    longitude = _finite_float_or_none(element.attrib.get("lon"))
    if latitude is None or longitude is None:
        return None
    values: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "starts_new_segment": starts_new_segment,
    }
    for child in element.iter():
        local_name = _xml_local_name(child.tag)
        text = (child.text or "").strip()
        namespace = _xml_namespace(child.tag)
        if local_name == "time":
            try:
                parsed_time = datetime.fromisoformat(text.replace("Z", "+00:00"))
                values["timestamp"] = (
                    parsed_time.replace(tzinfo=timezone.utc)
                    if parsed_time.tzinfo is None
                    else parsed_time.astimezone(timezone.utc)
                )
            except (TypeError, ValueError):
                values["threshold_value_invalid"] = True
                values.pop("timestamp", None)
        elif local_name == "power" and namespace == BR_GPX_NAMESPACE:
            power = _finite_float_or_none(text)
            if power is not None and power >= 0 and power.is_integer():
                values["power_w"] = int(power)
            else:
                values["threshold_value_invalid"] = True
        if local_name == "elevation-source":
            values["elevation_source"] = text
        elif local_name == "elevation-confidence":
            values["elevation_confidence"] = text
        elif local_name == "raw-gps-altitude-m":
            values["raw_elevation_m"] = _finite_float_or_none(text)
        elif local_name == "relative-barometer-m":
            values["relative_barometer_m"] = _finite_float_or_none(text)
        elif local_name == "power-source" and namespace == BR_GPX_NAMESPACE:
            values["power_source_marker"] = text
    return values


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xml_namespace(tag: str) -> Optional[str]:
    if not tag.startswith("{") or "}" not in tag:
        return None
    return tag[1:].split("}", 1)[0]


def compute_ride_identity_bytes_rust(
    file_bytes: bytes,
    file_type: str,
    parser_version: Optional[int] = None,
) -> Tuple[bytes, int]:
    """
    Compute the canonical ride hash bytes and parser version for attestation identity.

    This uses the same workout-parse canonicalization contract as the validation tests.
    """
    wp = _get_workout_parse()

    resolved_parser_version = (
        int(getattr(wp, "CURRENT_PARSER_VERSION"))
        if parser_version is None
        else int(parser_version)
    )

    if hasattr(wp, "parse_file_bytes"):
        # Parsing itself is versioned: replaying V1 source bytes preserves its
        # legacy detector, QName, XML-state, and elevation interpretation
        # before canonicalization.
        activity = wp.parse_file_bytes(
            file_bytes,
            file_type or "auto",
            parser_version=resolved_parser_version,
        )
    else:
        if parser_version is not None:
            raise RuntimeError("workout_parse lacks version-aware source parsing")
        activity = wp.parse_bytes(file_bytes)

    ride_hash_hex = wp.hash_canonical_ride(
        activity,
        parser_version=resolved_parser_version,
    )
    return bytes.fromhex(ride_hash_hex), resolved_parser_version


def _attach_device_evidence(parsed_ride: ParsedRideCompat, activity) -> None:
    """Copy the parser's device testimony onto the compat ride. Defensive
    getattr so an older binding shape degrades to absence, never error."""
    try:
        devices = getattr(activity, "devices", None) or []
        parsed_ride.device_provenance = [dict(d) for d in devices]
    except Exception:
        parsed_ride.device_provenance = []
    try:
        summary = getattr(activity, "device_summary", None)
        parsed_ride.device_summary = dict(summary) if summary else None
    except Exception:
        parsed_ride.device_summary = None
    try:
        pauses = getattr(activity, "timer_pauses", None) or []
        parsed_ride.timer_pause_count = len(pauses)
        parsed_ride.event_moving_time_s = getattr(activity, "event_moving_time_s", None)
    except Exception:
        parsed_ride.timer_pause_count = 0
        parsed_ride.event_moving_time_s = None
    try:
        laps = getattr(activity, "laps", None) or []
        parsed_ride.laps = [dict(lap) for lap in laps]
    except Exception:
        parsed_ride.laps = []
    try:
        raw_balance = getattr(activity, "lr_balance_raw", None)
        if raw_balance is not None:
            values = np.asarray(raw_balance)
            flagged = values[values != 255]
            if len(flagged) >= 10:
                # FIT: bit7 marks the value as the RIGHT-side contribution.
                right = np.where(flagged >= 128, flagged - 128, flagged).astype(float)
                right = right[(right >= 0) & (right <= 100)]
                if len(right) >= 10:
                    right_pct = float(np.mean(right))
                    parsed_ride.power_balance = {
                        "left_pct": round(100.0 - right_pct, 1),
                        "right_pct": round(right_pct, 1),
                        "sample_count": int(len(right)),
                    }
    except Exception:
        parsed_ride.power_balance = None
    try:
        accuracy = getattr(activity, "gps_accuracy_m", None)
        if accuracy is not None:
            values = np.asarray(accuracy, dtype=float)
            finite = values[np.isfinite(values)]
            if len(finite) > 0:
                parsed_ride.gps_accuracy_stats = {
                    "p50_m": round(float(np.percentile(finite, 50)), 1),
                    "p95_m": round(float(np.percentile(finite, 95)), 1),
                    "over_50m_share_bps": int(
                        round(float(np.mean(finite > 50.0)) * 10000)
                    ),
                    "sample_count": int(len(finite)),
                }
    except Exception:
        parsed_ride.gps_accuracy_stats = None
    try:
        temps = getattr(activity, "temperature_c", None)
        if temps is not None:
            values = [t for t in np.asarray(temps).tolist() if t is not None and np.isfinite(t)]
            if values:
                parsed_ride.avg_temperature_c = float(sum(values) / len(values))
    except Exception:
        parsed_ride.avg_temperature_c = None


def _activity_to_parsed_ride(activity, wp) -> ParsedRideCompat:
    """Convert a Rust ParsedActivity to the Python-compatible ParsedRideCompat."""
    records = []
    gps_track = []

    time_ms = np.asarray(activity.time_ms)
    n = len(time_ms)

    # Get optional arrays
    lat_e7 = np.asarray(activity.lat_e7) if activity.lat_e7 is not None else None
    lon_e7 = np.asarray(activity.lon_e7) if activity.lon_e7 is not None else None
    elev_m = np.asarray(activity.elevation_m) if getattr(activity, "elevation_m", None) is not None else None
    pwr_w = np.asarray(activity.pwr_w) if activity.pwr_w is not None else None
    hr_bpm = np.asarray(activity.hr_bpm) if activity.hr_bpm is not None else None
    cadence = np.asarray(activity.cadence_rpm) if activity.cadence_rpm is not None else None
    speed = np.asarray(activity.speed_mps) if activity.speed_mps is not None else None
    dist = np.asarray(activity.dist_m) if activity.dist_m is not None else None
    # V1 motion arrays collapse missing values to zero for canonical hashing.
    # The non-canonical sidecar distinguishes recorded stops from sensor absence.
    motion_presence = getattr(activity, "motion_sample_presence", ())
    if speed is None:
        motion_speed = np.asarray(getattr(activity, "motion_speed_mps", ()))
        if len(motion_speed) == n:
            speed = motion_speed


    for i in range(n):
        ts = datetime.fromtimestamp(time_ms[i] / 1000, tz=timezone.utc)

        # GPS
        lat = None
        lon = None
        ele = None
        if lat_e7 is not None and lat_e7[i] != wp.MISSING_I32:
            lat = lat_e7[i] / 1e7
        if lon_e7 is not None and lon_e7[i] != wp.MISSING_I32:
            lon = lon_e7[i] / 1e7
        if (lat is not None or lon is not None) and elev_m is not None:
            ele = _finite_float_or_none(elev_m[i])

        # Power
        power = None
        if pwr_w is not None and pwr_w[i] != wp.MISSING_U16:
            power = int(pwr_w[i])

        # HR
        hr = None
        if hr_bpm is not None and hr_bpm[i] != wp.MISSING_U8:
            hr = int(hr_bpm[i])

        # Cadence
        cad = None
        if cadence is not None and cadence[i] != wp.MISSING_U8:
            cad = int(cadence[i])

        # Speed
        spd = None
        presence = motion_presence[i] if i < len(motion_presence) else 0
        if speed is not None:
            observed_speed = _finite_float_or_none(speed[i])
            if observed_speed is not None and (
                observed_speed > 0 or (observed_speed == 0 and presence & 1)
            ):
                spd = observed_speed

        # Distance
        d = None
        if dist is not None:
            observed_distance = _finite_float_or_none(dist[i])
            if observed_distance is not None and (
                observed_distance > 0 or (observed_distance == 0 and presence & 2)
            ):
                d = observed_distance

        record = DataRecordCompat(
            timestamp=ts,
            lat=lat,
            lon=lon,
            elevation_m=ele,
            power_w=power,
            heart_rate_bpm=hr,
            cadence_rpm=cad,
            speed_mps=spd,
            distance_m=d,
        )
        records.append(record)

        if lat is not None and lon is not None:
            gps_track.append(GpsPointCompat(lat=lat, lon=lon, elevation_m=ele, timestamp=ts))

    # Timestamps
    started_at = datetime.fromtimestamp(activity.started_at_ms / 1000, tz=timezone.utc)
    completed_at = datetime.fromtimestamp(time_ms[-1] / 1000, tz=timezone.utc) if n > 0 else started_at

    return ParsedRideCompat(
        started_at=started_at,
        completed_at=completed_at,
        records=records,
        gps_track=gps_track,
        device_name=activity.device_name,
        sport=activity.sport,
        _native_activity=activity,
    )


def calculate_metrics_rust(
    parsed_ride: ParsedRideCompat,
    user_weight_kg: float = 75.0,
    user_ftp_w: Optional[float] = None,
) -> RideMetricsCompat:
    """
    Calculate authoritative metrics on the exact Rust activity that was parsed.

    Reconstructing arrays here previously created a second NP/TSS formula. The
    native activity is retained explicitly so reward-bearing math has one path.
    """
    wp = _get_workout_parse()
    ftp = int(user_ftp_w) if user_ftp_w else 200
    native_activity = parsed_ride._native_activity
    if native_activity is None:
        raise ValueError("authoritative metrics require the native workout_parse activity")

    computed = wp.compute_metrics(native_activity, ftp)

    return _metrics_compat(computed, wp)


def effort_spans_ms_rust(parsed_ride):
    return [tuple(span) for span in _get_workout_parse().effort_spans_ms(parsed_ride._native_activity)]


def calculate_paid_metrics_rust(parsed_ride, keep_ms, ftp):
    wp = _get_workout_parse()
    computed, spans = wp.compute_metrics_in_spans(parsed_ride._native_activity, int(ftp), keep_ms)
    return _metrics_compat(computed, wp), [tuple(span) for span in spans]


def _metrics_compat(computed, wp):
    def rounded_optional(value, digits: int = 0):
        numeric = _finite_float_or_none(value)
        return round(numeric, digits) if numeric is not None else None

    return RideMetricsCompat(
        duration_sec=int(computed.duration_s),
        moving_time_sec=int(computed.moving_time_s),
        distance_m=round(float(computed.distance_m), 1),
        elevation_gain_m=round(float(computed.elevation_gain_m), 1),
        tss=round(float(computed.tss or 0.0), 1),
        kcals=round(float(computed.kcals or 0.0), 0),
        avg_power_w=rounded_optional(computed.avg_power_w),
        avg_hr_bpm=rounded_optional(computed.avg_hr_bpm),
        avg_speed_mps=rounded_optional(computed.avg_speed_mps, 2),
        avg_cadence_rpm=rounded_optional(computed.avg_cadence_rpm),
        max_power_w=(
            int(computed.max_power_w) if computed.max_power_w is not None else None
        ),
        max_hr_bpm=(
            int(computed.max_hr_bpm) if computed.max_hr_bpm is not None else None
        ),
        max_speed_mps=rounded_optional(computed.max_speed_mps, 2),
        normalized_power_w=rounded_optional(computed.normalized_power_w),
        normalized_power_raw_w=_finite_float_or_none(
            getattr(computed, "normalized_power_raw_w", None)
        ),
        normalized_power_duration_s=int(
            getattr(computed, "normalized_power_duration_s", 0)
        ),
        metrics_version=str(wp.METRICS_VERSION),
        power_sample_count=int(computed.power_sample_count),
        power_sample_coverage_bps=int(computed.power_sample_coverage_bps),
        heart_rate_sample_count=int(computed.heart_rate_sample_count),
        heart_rate_sample_coverage_bps=int(computed.heart_rate_sample_coverage_bps),
    )


def calculate_threshold_release_tss(
    *,
    normalized_power_raw_w: float,
    normalized_power_duration_s: int,
    threshold_w: int,
) -> float:
    """Recompute held-ride TSS through workout-parse's canonical scalar."""
    if isinstance(normalized_power_duration_s, bool) or not isinstance(
        normalized_power_duration_s, int
    ):
        raise ValueError("normalized_power_duration_s must be an exact integer")
    if isinstance(threshold_w, bool) or not isinstance(threshold_w, int):
        raise ValueError("threshold_w must be an exact integer")
    try:
        normalized_power = float(normalized_power_raw_w)
    except (TypeError, ValueError) as exc:
        raise ValueError("normalized_power_raw_w must be numeric") from exc
    if (
        normalized_power_duration_s <= 0
        or threshold_w <= 0
        or not math.isfinite(normalized_power)
        or normalized_power <= 0
    ):
        raise ValueError("frozen release power inputs must be positive")

    workout_parse = _get_workout_parse()
    calculate = getattr(workout_parse, "calculate_tss_from_power", None)
    if calculate is None:
        raise RuntimeError(
            "workout_parse lacks the authoritative held-ride TSS scalar"
        )
    tss = float(
        calculate(
            normalized_power_duration_s,
            normalized_power,
            threshold_w,
        )
    )
    if not math.isfinite(tss) or tss < 0:
        raise ValueError("workout_parse returned invalid held-ride TSS")
    return round(tss, 1)


def calculate_segment_power_metrics_rust(
    samples: Sequence[Mapping[str, Any]],
    *,
    start_offset_s: int,
    end_offset_s: int,
    keep_ms_relative=None,
) -> SegmentPowerMetricsCompat:
    """Compute canonical power metrics for an inclusive climb interval."""
    if isinstance(start_offset_s, bool) or not isinstance(start_offset_s, int):
        raise ValueError("start_offset_s must be an exact integer")
    if isinstance(end_offset_s, bool) or not isinstance(end_offset_s, int):
        raise ValueError("end_offset_s must be an exact integer")
    if start_offset_s < 0 or end_offset_s < start_offset_s:
        raise ValueError("segment offsets must define a non-negative interval")

    time_ms: list[int] = []
    power_w: list[Optional[int]] = []
    previous_t: Optional[int] = None
    for sample in samples:
        sample_t = sample.get("t")
        if isinstance(sample_t, bool) or not isinstance(sample_t, int):
            raise ValueError("segment sample time must be an exact integer")
        if previous_t is not None and sample_t < previous_t:
            raise ValueError("segment sample times must be monotonic")
        previous_t = sample_t
        if sample_t < start_offset_s or sample_t > end_offset_s:
            continue

        sample_power = sample.get("power_w")
        if sample_power is not None:
            if isinstance(sample_power, bool) or not isinstance(sample_power, int):
                raise ValueError("segment power must be an exact integer or missing")
            if sample_power < 0 or sample_power > 65_535:
                raise ValueError("segment power must fit u16")
        time_ms.append(sample_t * 1_000)
        power_w.append(sample_power)

    workout_parse = _get_workout_parse()
    function_name = (
        "compute_segment_power_metrics"
        if keep_ms_relative is None
        else "compute_segment_power_metrics_in_spans"
    )
    compute = getattr(workout_parse, function_name, None)
    if compute is None:
        raise RuntimeError(
            "workout_parse lacks canonical climb-window power metrics"
        )
    computed = (
        compute(time_ms, power_w)
        if keep_ms_relative is None
        else compute(time_ms, power_w, keep_ms_relative)
    )
    normalized_power_raw_w = _finite_float_or_none(
        getattr(computed, "normalized_power_raw_w", None)
    )
    return SegmentPowerMetricsCompat(
        normalized_power_w=(
            int(computed.normalized_power_w)
            if computed.normalized_power_w is not None
            else None
        ),
        normalized_power_milliwatts=(
            math.floor(normalized_power_raw_w * 1_000 + 0.5)
            if normalized_power_raw_w is not None
            else None
        ),
        normalized_power_duration_s=int(
            getattr(computed, "normalized_power_duration_s", 0)
        ),
        power_sample_count=int(computed.power_sample_count),
        power_sample_coverage_bps=int(computed.power_sample_coverage_bps),
        moving_time_s=int(computed.moving_time_s),
        metrics_version=str(workout_parse.METRICS_VERSION),
    )
