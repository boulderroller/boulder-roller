"""
Ride metrics calculation - TSS, kcals, elevation gain, etc.

All formulas centralized here for consistency across clients.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .ride_parser import DataRecord


@dataclass
class RideMetrics:
    """Computed metrics for a ride."""
    duration_sec: int
    distance_m: float
    elevation_gain_m: float

    # Effort metrics
    tss: float  # Training Stress Score
    kcals: float  # Calories burned

    # Averages (None if no data)
    avg_power_w: Optional[float] = None
    avg_hr_bpm: Optional[float] = None
    avg_speed_mps: Optional[float] = None
    avg_cadence_rpm: Optional[float] = None

    # Peaks
    max_power_w: Optional[int] = None
    max_hr_bpm: Optional[int] = None
    max_speed_mps: Optional[float] = None

    # Normalized power (for TSS calculation)
    normalized_power_w: Optional[float] = None
    moving_time_sec: int = 0
    metrics_version: str = "python_ride_metrics_v1"
    power_sample_count: int = 0
    power_sample_coverage_bps: int = 0
    heart_rate_sample_count: int = 0
    heart_rate_sample_coverage_bps: int = 0


# Default FTP for users without a known value
DEFAULT_FTP_W = 200

# Metabolic constants
KCAL_PER_KJ = 0.239  # 1 kJ = 0.239 kcal
CYCLING_EFFICIENCY = 0.25  # ~25% mechanical efficiency


def calculate_metrics(
    records: list[DataRecord],
    user_weight_kg: float = 75.0,
    user_ftp_w: Optional[float] = None,
) -> RideMetrics:
    """
    Calculate all ride metrics from parsed records.

    TSS Calculation:
    - With power: TSS = (duration_sec * NP * IF) / (FTP * 3600) * 100
    - Without power: Estimate from HR or duration/distance

    Kcal Calculation:
    - With power: Work (kJ) / efficiency
    - Without power: MET-based estimate from duration
    """
    if not records:
        return RideMetrics(
            duration_sec=0,
            distance_m=0,
            elevation_gain_m=0,
            tss=0,
            kcals=0,
            metrics_version="python_ride_metrics_v1",
        )

    ftp = user_ftp_w or DEFAULT_FTP_W

    # Duration
    duration_sec = int((records[-1].timestamp - records[0].timestamp).total_seconds())
    duration_sec = max(duration_sec, 1)  # Avoid division by zero

    # Distance (from GPS or accumulated distance field)
    distance_m = _calculate_distance(records)

    # Elevation gain
    elevation_gain_m = _calculate_elevation_gain(records)

    # Power metrics
    recorded_power_values = [r.power_w for r in records if r.power_w is not None]
    power_values = [power for power in recorded_power_values if power > 0]
    has_power = len(power_values) > 10  # Need meaningful power data

    avg_power_w: Optional[float] = None
    normalized_power_w: Optional[float] = None
    max_power_w: Optional[int] = None

    if has_power:
        avg_power_w = sum(power_values) / len(power_values)
        max_power_w = max(power_values)
        normalized_power_w = _calculate_normalized_power(records)

    # HR metrics
    hr_values = [r.heart_rate_bpm for r in records if r.heart_rate_bpm is not None and r.heart_rate_bpm > 0]
    avg_hr_bpm = sum(hr_values) / len(hr_values) if hr_values else None
    max_hr_bpm = max(hr_values) if hr_values else None

    # Speed metrics
    speed_values = [r.speed_mps for r in records if r.speed_mps is not None and r.speed_mps > 0]
    avg_speed_mps = sum(speed_values) / len(speed_values) if speed_values else None
    max_speed_mps = max(speed_values) if speed_values else None

    # If no speed from device, calculate from distance/time
    if avg_speed_mps is None and distance_m > 0 and duration_sec > 0:
        avg_speed_mps = distance_m / duration_sec

    # Cadence
    cadence_values = [r.cadence_rpm for r in records if r.cadence_rpm is not None and r.cadence_rpm > 0]
    avg_cadence_rpm = sum(cadence_values) / len(cadence_values) if cadence_values else None

    # TSS calculation
    if has_power and normalized_power_w:
        tss = _calculate_tss_from_power(
            duration_sec=duration_sec,
            normalized_power=normalized_power_w,
            ftp=ftp,
        )
    elif avg_hr_bpm:
        tss = _estimate_tss_from_hr(
            duration_sec=duration_sec,
            avg_hr=avg_hr_bpm,
            max_hr=max_hr_bpm or 190,
        )
    else:
        tss = _estimate_tss_from_duration(
            duration_sec=duration_sec,
            distance_m=distance_m,
            elevation_gain_m=elevation_gain_m,
        )

    # Kcal calculation
    if has_power and avg_power_w:
        # Work = avg_power * time (in joules), convert to kcal
        work_kj = (avg_power_w * duration_sec) / 1000
        kcals = work_kj / CYCLING_EFFICIENCY * KCAL_PER_KJ
    else:
        # MET-based estimate: cycling ~8 METs moderate, ~12 METs vigorous
        met = 8.0
        if distance_m > 0:
            met += (elevation_gain_m / distance_m) * 100
        met = min(met, 14.0)  # Cap at very vigorous
        hours = duration_sec / 3600
        kcals = met * user_weight_kg * hours

    return RideMetrics(
        duration_sec=duration_sec,
        distance_m=round(distance_m, 1),
        elevation_gain_m=round(elevation_gain_m, 1),
        tss=round(tss, 1),
        kcals=round(kcals, 0),
        avg_power_w=round(avg_power_w, 0) if avg_power_w else None,
        avg_hr_bpm=round(avg_hr_bpm, 0) if avg_hr_bpm else None,
        avg_speed_mps=round(avg_speed_mps, 2) if avg_speed_mps else None,
        avg_cadence_rpm=round(avg_cadence_rpm, 0) if avg_cadence_rpm else None,
        max_power_w=max_power_w,
        max_hr_bpm=max_hr_bpm,
        max_speed_mps=round(max_speed_mps, 2) if max_speed_mps else None,
        normalized_power_w=round(normalized_power_w, 0) if normalized_power_w else None,
        moving_time_sec=duration_sec,
        metrics_version="python_ride_metrics_v1",
        power_sample_count=len(recorded_power_values),
        power_sample_coverage_bps=(len(recorded_power_values) * 10_000 // len(records)),
        heart_rate_sample_count=len(hr_values),
        heart_rate_sample_coverage_bps=(len(hr_values) * 10_000 // len(records)),
    )


def _calculate_distance(records: list[DataRecord]) -> float:
    """Calculate total distance in meters."""
    # First try accumulated distance from device
    distances = [r.distance_m for r in records if r.distance_m is not None]
    if distances:
        return max(distances)

    # Fall back to GPS calculation
    total = 0.0
    prev_lat, prev_lon = None, None

    for r in records:
        if r.lat is not None and r.lon is not None:
            if prev_lat is not None:
                total += _haversine(prev_lat, prev_lon, r.lat, r.lon)
            prev_lat, prev_lon = r.lat, r.lon

    return total


def _calculate_elevation_gain(records: list[DataRecord]) -> float:
    """Calculate total elevation gain in meters (only positive changes)."""
    elevations = [r.elevation_m for r in records if r.elevation_m is not None]
    if len(elevations) < 2:
        return 0.0

    # Smooth with SMA(21) to reduce barometric noise and match Strava-like gain
    smoothed = _smooth_elevations(elevations, window=21)

    gain = 0.0
    for i in range(1, len(smoothed)):
        delta = smoothed[i] - smoothed[i - 1]
        if delta > 0:
            gain += delta

    return gain


def _smooth_elevations(values: list[float], window: int = 5) -> list[float]:
    """Simple moving average smoothing."""
    if len(values) < window:
        return values

    result = []
    for i in range(len(values)):
        start = max(0, i - window // 2)
        end = min(len(values), i + window // 2 + 1)
        result.append(sum(values[start:end]) / (end - start))

    return result


def _calculate_normalized_power(records: list[DataRecord], window_sec: int = 30) -> Optional[float]:
    """
    Calculate Normalized Power (NP) using 30-second rolling average.

    NP = 4th root of (average of (30s rolling avg power)^4)

    Optimized O(n) implementation using sliding window.
    """
    power_values = [(r.timestamp.timestamp(), r.power_w) for r in records if r.power_w is not None]
    if len(power_values) < window_sec:
        return None

    # O(n) sliding window approach
    rolling_avgs = []
    window_sum = 0.0
    window_start_idx = 0

    for i, (ts, power) in enumerate(power_values):
        window_sum += power

        # Remove elements that are outside the 30-second window
        window_start_time = ts - window_sec
        while window_start_idx < i and power_values[window_start_idx][0] < window_start_time:
            window_sum -= power_values[window_start_idx][1]
            window_start_idx += 1

        window_count = i - window_start_idx + 1
        if window_count > 0:
            rolling_avgs.append(window_sum / window_count)

    if not rolling_avgs:
        return None

    # NP = 4th root of mean of 4th powers
    fourth_powers_sum = sum(p ** 4 for p in rolling_avgs)
    return (fourth_powers_sum / len(rolling_avgs)) ** 0.25


def _calculate_tss_from_power(duration_sec: int, normalized_power: float, ftp: float) -> float:
    """
    TSS = (duration_sec * NP * IF) / (FTP * 3600) * 100
    where IF (Intensity Factor) = NP / FTP
    """
    if ftp <= 0:
        return 0

    intensity_factor = normalized_power / ftp
    tss = (duration_sec * normalized_power * intensity_factor) / (ftp * 3600) * 100
    return tss


def _estimate_tss_from_hr(duration_sec: int, avg_hr: float, max_hr: float) -> float:
    """
    Estimate TSS from heart rate when power isn't available.

    Uses TRIMP-like approach scaled to TSS.
    """
    if max_hr <= 0:
        return 0

    hr_ratio = avg_hr / max_hr
    hours = duration_sec / 3600

    # Rough TSS estimate: ~50 TSS/hour at moderate intensity
    base_tss_per_hour = 50
    intensity_multiplier = (hr_ratio - 0.5) * 4  # 0.5 HR ratio = 0x, 0.75 = 1x, 1.0 = 2x
    intensity_multiplier = max(0.5, min(intensity_multiplier, 2.0))

    return hours * base_tss_per_hour * intensity_multiplier


def _estimate_tss_from_duration(duration_sec: int, distance_m: float, elevation_gain_m: float) -> float:
    """
    Rough TSS estimate when no power or HR data.

    Based on typical cycling: ~40-60 TSS/hour moderate effort.
    """
    hours = duration_sec / 3600

    # Base rate
    base_tss = 45 * hours

    # Adjust for climbing (more elevation = harder)
    if distance_m > 0:
        gradient_factor = 1 + (elevation_gain_m / distance_m) * 10
        gradient_factor = min(gradient_factor, 1.5)
        base_tss *= gradient_factor

    return base_tss


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two GPS points in meters."""
    R = 6371000  # Earth radius in meters

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c
