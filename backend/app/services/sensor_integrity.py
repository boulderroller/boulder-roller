"""
Sensor Integrity Layer — per-activity quality scoring.

Implements memo item #8: "Treat data quality as a model input, not cleanup."
Scores each activity for GPS validity/continuity, elevation stability,
sampling regularity, and sensor coverage. The composite integrity score
feeds into abstention evaluation (ABSTENTION_POLICY.md) and is stored
as JSONB on the ride for audit.

Thresholds derived from corpus analysis (Feb 2026, 2,893 rides):
  - GPS coverage: 95.9% median, p5 = 87%
  - Elevation coverage: 97.5% median
  - Sampling: 0.94 Hz median, p5 = 0.19 Hz (GPX imports)
  - Power coverage: 81.6% median (device-dependent)
  - HR coverage: 33.2% median (many rides lack HR strap)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .sample_time import infer_sample_time_base, sample_time_seconds


@dataclass
class SensorIntegrityReport:
    """Per-activity sensor quality assessment."""

    # GPS quality
    gps_coverage: float = 0.0       # Fraction of samples with valid lat/lon (0.0-1.0)
    gps_jump_count: int = 0         # Teleportation events (>500m between consecutive samples)
    gps_max_jump_m: float = 0.0     # Largest single GPS jump in meters

    # Elevation quality
    elev_coverage: float = 0.0      # Fraction of samples with elevation_m
    elev_plausible: bool = True      # All values within [-500, 5500] range
    elev_max_m: float = 0.0         # Highest elevation in ride
    elev_min_m: float = 0.0         # Lowest elevation in ride

    # Sampling regularity
    sample_count: int = 0           # Total tile samples
    median_interval_s: float = 0.0  # Median gap between consecutive samples
    sampling_regularity: float = 0.0  # 0.0-1.0 (1.0 = perfectly regular)
    max_gap_s: int = 0              # Largest gap between consecutive samples
    gap_ratio: float = 0.0          # Fraction of total ride time in gaps >30s

    # Effort-sensor coverage. Power/HR absence does not make route geometry
    # invalid, but route-only effort is not reward-grade evidence.
    power_coverage: float = 0.0     # Fraction with power_w
    hr_coverage: float = 0.0        # Fraction with hr_bpm
    speed_coverage: float = 0.0     # Fraction with speed_mps

    # Aggregate
    integrity_score: float = 0.0    # Composite 0.0-1.0 score
    flags: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "gps_coverage": round(self.gps_coverage, 3),
            "gps_jump_count": self.gps_jump_count,
            "gps_max_jump_m": round(self.gps_max_jump_m, 1),
            "elev_coverage": round(self.elev_coverage, 3),
            "elev_plausible": self.elev_plausible,
            "elev_max_m": round(self.elev_max_m, 1),
            "elev_min_m": round(self.elev_min_m, 1),
            "sample_count": self.sample_count,
            "median_interval_s": round(self.median_interval_s, 2),
            "sampling_regularity": round(self.sampling_regularity, 3),
            "max_gap_s": self.max_gap_s,
            "gap_ratio": round(self.gap_ratio, 3),
            "power_coverage": round(self.power_coverage, 3),
            "hr_coverage": round(self.hr_coverage, 3),
            "speed_coverage": round(self.speed_coverage, 3),
            "integrity_score": round(self.integrity_score, 3),
            "flags": self.flags,
        }


# ---------------------------------------------------------------------------
# Thresholds (corpus-calibrated)
# ---------------------------------------------------------------------------

# GPS
GPS_COVERAGE_WARN = 0.80       # Below this → flag
GPS_COVERAGE_FAIL = 0.50       # Below this → abstain
GPS_JUMP_THRESHOLD_M = 500.0   # Single step > 500m = teleportation
GPS_JUMP_MAX_COUNT = 3         # More than 3 teleportations → flag

# Elevation
ELEV_COVERAGE_WARN = 0.90
ELEV_COVERAGE_FAIL = 0.50
ELEV_PLAUSIBLE_MAX = 5500.0    # Corpus max legit ~2500m; Everest = 8849m, 5500 generous
ELEV_PLAUSIBLE_MIN = -500.0    # Dead Sea = -430m, -500 generous

# Sampling
SAMPLE_MIN_COUNT = 10          # Need at least 10 samples to assess anything
SAMPLING_RATE_WARN = 0.2       # Below 0.2 Hz (5s interval) is degraded
GAP_THRESHOLD_S = 30           # Gaps longer than 30s counted toward gap_ratio
GAP_RATIO_WARN = 0.10          # >10% of ride in gaps
GAP_RATIO_FAIL = 0.30          # >30% of ride in gaps
MAX_GAP_WARN_S = 300           # Single gap > 5 minutes


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in meters between two GPS coordinates."""
    R = 6_371_000.0  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _is_valid_gps(lat: Optional[float], lon: Optional[float]) -> bool:
    """Reject null, Null Island (0,0), and FIT SDK sentinels."""
    if lat is None or lon is None:
        return False
    if lat == 0.0 and lon == 0.0:
        return False
    if abs(lat) > 90 or abs(lon) > 180:
        return False
    # FIT SDK sentinel: INT32_MIN/1e7 ≈ -214.748
    if lat < -90 or lon < -180:
        return False
    return True


def sample_has_valid_gps(sample: Dict[str, Any]) -> bool:
    """Honor lossless evidence validity before coordinate fallback checks."""
    if sample.get("gps_valid") is False:
        return False
    return _is_valid_gps(sample.get("lat"), sample.get("lon"))


def _median(values: List[float]) -> float:
    """Simple median without numpy dependency."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 0:
        return (s[mid - 1] + s[mid]) / 2.0
    return s[mid]


def compute_sensor_integrity(tile_samples: List[Dict]) -> SensorIntegrityReport:
    """
    Compute per-activity sensor integrity from tile samples.

    Args:
        tile_samples: List of dicts with keys t, tile_id, elevation_m,
            power_w, hr_bpm, speed_mps, lat, lon (all optional except t).

    Returns:
        SensorIntegrityReport with sub-scores and composite integrity score.
    """
    report = SensorIntegrityReport()
    n = len(tile_samples)
    report.sample_count = n

    if n < SAMPLE_MIN_COUNT:
        report.flags.append(f"SAMPLING:too_few_samples_{n}")
        report.integrity_score = 0.0
        return report

    # Sort by normalized seconds (should already be sorted, but defensive).
    # Production projections may carry either seconds-from-start or absolute
    # datetimes, and sparse rows can be missing t entirely.
    base_time = infer_sample_time_base(tile_samples)
    timed_samples: List[tuple[float, Dict[str, Any]]] = []
    untimed_samples: List[Dict[str, Any]] = []
    for sample in tile_samples:
        seconds = sample_time_seconds(sample.get("t"), base_time=base_time)
        if seconds is None:
            untimed_samples.append(sample)
        else:
            timed_samples.append((seconds, sample))

    timed_samples.sort(key=lambda item: item[0])
    samples = [sample for _, sample in timed_samples] + untimed_samples

    # -----------------------------------------------------------------
    # 1. GPS quality
    # -----------------------------------------------------------------
    gps_valid = 0
    gps_jumps = 0
    gps_max_jump = 0.0
    prev_lat, prev_lon = None, None

    for s in samples:
        lat = s.get("lat")
        lon = s.get("lon")
        if sample_has_valid_gps(s):
            gps_valid += 1
            if prev_lat is not None:
                dist = _haversine_m(prev_lat, prev_lon, lat, lon)
                if dist > GPS_JUMP_THRESHOLD_M:
                    gps_jumps += 1
                    gps_max_jump = max(gps_max_jump, dist)
            prev_lat, prev_lon = lat, lon

    report.gps_coverage = gps_valid / n
    report.gps_jump_count = gps_jumps
    report.gps_max_jump_m = gps_max_jump

    if report.gps_coverage < GPS_COVERAGE_FAIL:
        report.flags.append(f"GPS:coverage_fail_{report.gps_coverage:.0%}")
    elif report.gps_coverage < GPS_COVERAGE_WARN:
        report.flags.append(f"GPS:coverage_warn_{report.gps_coverage:.0%}")

    if gps_jumps > GPS_JUMP_MAX_COUNT:
        report.flags.append(f"GPS:teleportation_{gps_jumps}_jumps")
    elif gps_jumps > 0:
        report.flags.append(f"GPS:jump_{gps_max_jump:.0f}m")

    # -----------------------------------------------------------------
    # 2. Elevation quality
    # -----------------------------------------------------------------
    elev_valid = 0
    elev_values: List[float] = []

    for s in samples:
        e = s.get("elevation_m")
        if e is not None:
            elev_valid += 1
            elev_values.append(e)

    report.elev_coverage = elev_valid / n

    if elev_values:
        report.elev_max_m = max(elev_values)
        report.elev_min_m = min(elev_values)
        report.elev_plausible = (
            report.elev_min_m >= ELEV_PLAUSIBLE_MIN
            and report.elev_max_m <= ELEV_PLAUSIBLE_MAX
        )
    else:
        report.elev_plausible = True  # No data to disprove

    if report.elev_coverage < ELEV_COVERAGE_FAIL:
        report.flags.append(f"ELEV:coverage_fail_{report.elev_coverage:.0%}")
    elif report.elev_coverage < ELEV_COVERAGE_WARN:
        report.flags.append(f"ELEV:coverage_warn_{report.elev_coverage:.0%}")

    if not report.elev_plausible:
        report.flags.append(
            f"ELEV:implausible_range_{report.elev_min_m:.0f}_{report.elev_max_m:.0f}"
        )

    # -----------------------------------------------------------------
    # 3. Sampling regularity
    # -----------------------------------------------------------------
    intervals: List[float] = []
    gap_time = 0
    max_gap = 0

    sample_times = [seconds for seconds, _ in timed_samples]
    for i in range(1, len(sample_times)):
        dt = sample_times[i] - sample_times[i - 1]
        if dt > 0:
            intervals.append(dt)
            if dt > GAP_THRESHOLD_S:
                gap_time += dt
            max_gap = max(max_gap, dt)

    report.max_gap_s = max_gap

    if intervals:
        report.median_interval_s = _median(intervals)
        total_time = sample_times[-1] - sample_times[0]

        if total_time > 0:
            report.gap_ratio = gap_time / total_time
        else:
            report.gap_ratio = 0.0

        # Sampling regularity: 1.0 = all intervals identical.
        # Use coefficient of variation (CV): lower CV = more regular.
        # Map CV to [0, 1]: regularity = 1 / (1 + CV)
        if len(intervals) > 1:
            mean_dt = sum(intervals) / len(intervals)
            if mean_dt > 0:
                variance = sum((x - mean_dt) ** 2 for x in intervals) / len(intervals)
                cv = math.sqrt(variance) / mean_dt
                report.sampling_regularity = 1.0 / (1.0 + cv)
            else:
                report.sampling_regularity = 1.0
        else:
            report.sampling_regularity = 1.0

    # Sampling rate flags
    if report.median_interval_s > 0:
        sampling_hz = 1.0 / report.median_interval_s
        if sampling_hz < SAMPLING_RATE_WARN:
            report.flags.append(f"SAMPLING:sparse_{sampling_hz:.2f}Hz")

    if report.gap_ratio > GAP_RATIO_FAIL:
        report.flags.append(f"SAMPLING:gap_ratio_fail_{report.gap_ratio:.0%}")
    elif report.gap_ratio > GAP_RATIO_WARN:
        report.flags.append(f"SAMPLING:gap_ratio_warn_{report.gap_ratio:.0%}")

    if max_gap > MAX_GAP_WARN_S:
        report.flags.append(f"SAMPLING:max_gap_{max_gap}s")

    # -----------------------------------------------------------------
    # 4. Power / HR / Speed coverage (informational)
    # -----------------------------------------------------------------
    power_count = sum(1 for s in samples if s.get("power_w") is not None)
    hr_count = sum(1 for s in samples if s.get("hr_bpm") is not None)
    speed_count = sum(1 for s in samples if s.get("speed_mps") is not None)

    report.power_coverage = power_count / n
    report.hr_coverage = hr_count / n
    report.speed_coverage = speed_count / n

    # -----------------------------------------------------------------
    # 5. Composite integrity score (weighted average of sub-scores)
    # -----------------------------------------------------------------
    # Weights reflect importance to climb detection economics:
    #   GPS = 35%, Elevation = 30%, Sampling = 25%, Plausibility = 10%
    gps_score = report.gps_coverage
    if gps_jumps > GPS_JUMP_MAX_COUNT:
        gps_score *= 0.5  # Heavy penalty for systematic teleportation

    elev_score = report.elev_coverage
    if not report.elev_plausible:
        elev_score *= 0.3  # Corrupt barometric data is severe

    sampling_score = report.sampling_regularity
    if report.gap_ratio > GAP_RATIO_FAIL:
        sampling_score *= 0.5

    # Plausibility bonus: no flags at all = 1.0, flags reduce
    plausibility_score = 1.0
    severe_flags = [f for f in report.flags if "fail" in f or "implausible" in f or "teleportation" in f]
    if severe_flags:
        plausibility_score = max(0.0, 1.0 - 0.3 * len(severe_flags))

    report.integrity_score = (
        0.35 * gps_score
        + 0.30 * elev_score
        + 0.25 * sampling_score
        + 0.10 * plausibility_score
    )

    # Clamp to [0, 1]
    report.integrity_score = max(0.0, min(1.0, report.integrity_score))

    return report


def get_abstention_reasons_from_integrity(
    report: SensorIntegrityReport,
) -> List[str]:
    """
    Extract abstention-triggering reasons from a sensor integrity report.

    Only returns reasons that should block economic actions.
    Minor sampling warnings are excluded, but route-only effort is intentionally
    abstained: candidates may display, while reward-critical actions require
    power or heart-rate evidence.
    """
    reasons = []

    # GPS coverage below 50% → abstain
    if report.gps_coverage < GPS_COVERAGE_FAIL:
        reasons.append(f"SENSOR:gps_coverage_{report.gps_coverage:.0%}")

    # GPS teleportation events → abstain
    if report.gps_jump_count > GPS_JUMP_MAX_COUNT:
        reasons.append(f"SENSOR:gps_teleportation_{report.gps_jump_count}")

    # Elevation coverage below 50% → abstain
    if report.elev_coverage < ELEV_COVERAGE_FAIL:
        reasons.append(f"SENSOR:elev_coverage_{report.elev_coverage:.0%}")

    # Implausible elevation (corrupt barometric) → abstain
    if not report.elev_plausible:
        reasons.append(f"SENSOR:elev_implausible_{report.elev_min_m:.0f}_{report.elev_max_m:.0f}")

    # >30% of ride time in gaps → abstain
    if report.gap_ratio > GAP_RATIO_FAIL:
        reasons.append(f"SENSOR:gap_ratio_{report.gap_ratio:.0%}")

    # Too few samples for meaningful detection
    if report.sample_count < SAMPLE_MIN_COUNT:
        reasons.append(f"SENSOR:too_few_samples_{report.sample_count}")

    # Route-only effort can still produce useful climb candidates, but it must
    # not become automatic CAL/vault economy evidence.
    if report.power_coverage <= 0 and report.hr_coverage <= 0:
        reasons.append("EFFORT:route_estimate_only")

    # Composite score below hard threshold → abstain
    if report.integrity_score < 0.40:
        reasons.append(f"SENSOR:integrity_score_{report.integrity_score:.2f}")

    return reasons
