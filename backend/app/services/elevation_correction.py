"""Truth-preserving DEM correction for the rider-facing elevation projection.

Feature: boulderroller-v2-odmi6.2.1 — server-side corrected climbing totals and
relief profile for rides, sampled from a repository-controlled export of the
canon pipeline's local USGS 3DEP tiles (CANON_BUILD_DECISIONS.md D6 source; no
remote or paid elevation provider).

The attested source file, canonical hash, detector samples, and economic
inputs remain untouched. This module returns a separate, versioned read-model
result; callers persist it in projection-only columns and must render an
unavailable result as missing rather than as zero.

PERSISTENCE CONTRACT: callers use the separate ``elevation_correction_*`` /
``elevation_corrected_gain_m`` ride columns and never overwrite
``rides.elevation_gain_m`` — that existing field is raw device truth and feeds
the frozen economic plan and achievements.
"""

from __future__ import annotations

import gzip
import json
import logging
import math
import mmap
import os
import struct
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Protocol, Sequence

logger = logging.getLogger(__name__)

ELEVATION_CORRECTION_VERSION = "dem_grid_bilinear_match8m_median3_hysteresis2m_v3"
DEFAULT_MINIMUM_COVERAGE_BPS = 9_800
MAP_MATCH_MINIMUM_PROGRESS_M = 8.0
GAIN_HYSTERESIS_M = 2.0
# A coordinate discontinuity larger than this between consecutive points is a
# recording gap (pause/transport), not terrain: reset gain accumulation instead
# of manufacturing ascent across the jump. Explicit segment flags also reset.
SEGMENT_RESET_DISTANCE_M = 500.0

GRID_FORMAT = "br_dem_grid_v1"
GRID_BASENAME = "delaware_valley_1as_v1"
_GRID_NODATA = -32768

# Delta-encoded profile storage version (rides.elevation_correction_profile).
PROFILE_STORAGE_VERSION = 1


@dataclass(frozen=True)
class RouteElevationPoint:
    latitude: float
    longitude: float
    raw_elevation_m: Optional[float]
    starts_new_segment: bool = False


@dataclass(frozen=True)
class ElevationCorrectionResult:
    status: str  # "corrected" | "unavailable"
    source_version: str
    correction_version: str
    coverage_bps: int
    elevation_gain_m: Optional[float]
    corrected_elevations_m: tuple[Optional[float], ...]
    reason: Optional[str] = None

    def as_ride_fields(self) -> dict[str, Any]:
        """Projection-only ride column values (never elevation_gain_m)."""
        fields: dict[str, Any] = {
            "elevation_correction_status": self.status,
            "elevation_correction_source": self.source_version,
            "elevation_correction_version": self.correction_version,
            "elevation_correction_coverage_bps": self.coverage_bps,
            "elevation_correction_reason": self.reason,
            "elevation_corrected_gain_m": (
                round(self.elevation_gain_m, 1)
                if self.elevation_gain_m is not None
                else None
            ),
            "elevation_correction_profile": None,
        }
        if self.status == "corrected":
            fields["elevation_correction_profile"] = encode_correction_profile(
                self.corrected_elevations_m
            )
        return fields


class DEMIndex(Protocol):
    source_version: str

    def elevation_at(self, latitude: float, longitude: float) -> Optional[float]:
        ...


class GridDEMIndex:
    """Bilinear sampler over a br_dem_grid_v1 int16 cell-center grid.

    The binary is memory-mapped so the API process only pages in the terrain
    it actually touches. Any nodata or out-of-coverage neighbor fails closed
    to ``None`` — absence is never estimated.
    """

    def __init__(self, meta: dict[str, Any], buffer: Any) -> None:
        if meta.get("format") != GRID_FORMAT:
            raise ValueError(f"unexpected DEM grid format {meta.get('format')!r}")
        self.source_version = str(meta["source_version"])
        self.rows = int(meta["rows"])
        self.cols = int(meta["cols"])
        self.min_lat = float(meta["min_lat"])
        self.max_lat = float(meta["max_lat"])
        self.min_lon = float(meta["min_lon"])
        self.max_lon = float(meta["max_lon"])
        self.step_deg = float(meta["step_deg"])
        self.nodata = int(meta.get("nodata", _GRID_NODATA))
        expected = self.rows * self.cols * 2
        if len(buffer) != expected:
            raise ValueError(
                f"DEM grid size mismatch: expected {expected} bytes, got {len(buffer)}"
            )
        self._buffer = buffer

    def _cell(self, row: int, col: int) -> Optional[float]:
        offset = (row * self.cols + col) * 2
        (value,) = struct.unpack_from("<h", self._buffer, offset)
        if value == self.nodata:
            return None
        return value / 10.0  # decimeters -> meters

    def elevation_at(self, latitude: float, longitude: float) -> Optional[float]:
        if not _valid_coordinate(latitude, longitude):
            return None
        # Fractional index into cell centers: center of cell (0,0) sits half a
        # step inside the bbox from the northwest corner.
        row_f = (self.max_lat - latitude) / self.step_deg - 0.5
        col_f = (longitude - self.min_lon) / self.step_deg - 0.5
        r0 = math.floor(row_f)
        c0 = math.floor(col_f)
        if r0 < 0 or c0 < 0 or r0 + 1 >= self.rows or c0 + 1 >= self.cols:
            return None
        q00 = self._cell(r0, c0)
        q01 = self._cell(r0, c0 + 1)
        q10 = self._cell(r0 + 1, c0)
        q11 = self._cell(r0 + 1, c0 + 1)
        if q00 is None or q01 is None or q10 is None or q11 is None:
            return None
        wr = row_f - r0
        wc = col_f - c0
        return (
            q00 * (1 - wr) * (1 - wc)
            + q01 * (1 - wr) * wc
            + q10 * wr * (1 - wc)
            + q11 * wr * wc
        )


_grid_lock = threading.Lock()
_grid_cache: Optional[GridDEMIndex] = None
_grid_load_attempted = False


def _grid_dir_candidates() -> list[Path]:
    candidates = []
    env_dir = os.environ.get("DEM_GRID_DIR")
    if env_dir:
        candidates.append(Path(env_dir))
    candidates.append(Path("/app/resources/dem"))
    repository_root = Path(__file__).resolve().parents[3]
    candidates.append(repository_root / "data/dem")
    return candidates


def load_dem_grid() -> Optional[GridDEMIndex]:
    """Load the deploy-asset DEM grid, or ``None`` when absent.

    Missing data is a truthful state (correction abstains with
    ``dem_grid_missing``); it must never crash ride processing.
    """

    global _grid_cache, _grid_load_attempted
    with _grid_lock:
        if _grid_cache is not None or _grid_load_attempted:
            return _grid_cache
        _grid_load_attempted = True
        for directory in _grid_dir_candidates():
            meta_path = directory / f"{GRID_BASENAME}.meta.json"
            if not meta_path.exists():
                continue
            try:
                meta = json.loads(meta_path.read_text())
                bin_path = directory / f"{GRID_BASENAME}.bin"
                gz_path = directory / f"{GRID_BASENAME}.bin.gz"
                if not bin_path.exists() and gz_path.exists():
                    bin_path = _decompress_grid(gz_path, meta)
                if not bin_path.exists():
                    continue
                with open(bin_path, "rb") as handle:
                    buffer = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)
                _grid_cache = GridDEMIndex(meta, buffer)
                logger.info(
                    "[ElevationCorrection] DEM grid loaded: %s (%dx%d) from %s",
                    _grid_cache.source_version,
                    _grid_cache.rows,
                    _grid_cache.cols,
                    directory,
                )
                return _grid_cache
            except Exception:
                logger.exception(
                    "[ElevationCorrection] failed to load DEM grid from %s", directory
                )
        logger.warning(
            "[ElevationCorrection] no DEM grid found; corrections will abstain"
        )
        return None


def _decompress_grid(gz_path: Path, meta: dict[str, Any]) -> Path:
    """Inflate a gz-only grid once per host into a cache path and reuse it."""
    target = Path(tempfile.gettempdir()) / f"{GRID_BASENAME}.{meta.get('bin_sha256', 'x')[:16]}.bin"
    if target.exists() and target.stat().st_size == int(meta.get("bin_bytes", -1)):
        return target
    tmp = target.with_suffix(".tmp")
    with gzip.open(gz_path, "rb") as src, open(tmp, "wb") as dst:
        while chunk := src.read(1 << 20):
            dst.write(chunk)
    os.replace(tmp, target)
    return target


def reset_grid_cache_for_tests() -> None:
    global _grid_cache, _grid_load_attempted
    with _grid_lock:
        _grid_cache = None
        _grid_load_attempted = False


def route_points_from_gps_dicts(
    points: Sequence[dict[str, Any]],
) -> tuple[RouteElevationPoint, ...]:
    """Adapt stored/processing GPS dicts to correction inputs.

    Accepts both the processing-time shape (``latitude``/``longitude``/
    ``elevation``) and the stored polyline decode shape (``elevation_m``).
    Recording gaps beyond ``SEGMENT_RESET_DISTANCE_M`` become segment starts
    so pauses and transport never fabricate ascent.
    """

    adapted: list[RouteElevationPoint] = []
    previous: Optional[tuple[float, float]] = None
    for point in points:
        latitude = point.get("latitude", point.get("lat"))
        longitude = point.get("longitude", point.get("lon"))
        if latitude is None or longitude is None:
            continue
        latitude = float(latitude)
        longitude = float(longitude)
        raw = _finite_or_none(
            point.get("elevation_m", point.get("elevation"))
        )
        starts_new_segment = bool(point.get("starts_new_segment"))
        if (
            not starts_new_segment
            and previous is not None
            and _valid_coordinate(latitude, longitude)
            and _valid_coordinate(*previous)
            and _haversine_m(previous[0], previous[1], latitude, longitude)
            > SEGMENT_RESET_DISTANCE_M
        ):
            starts_new_segment = True
        adapted.append(
            RouteElevationPoint(
                latitude=latitude,
                longitude=longitude,
                raw_elevation_m=raw,
                starts_new_segment=starts_new_segment,
            )
        )
        previous = (latitude, longitude)
    return tuple(adapted)


def correct_route_elevation(
    route: Sequence[RouteElevationPoint],
    dem: Optional[DEMIndex],
    *,
    minimum_coverage_bps: int = DEFAULT_MINIMUM_COVERAGE_BPS,
) -> ElevationCorrectionResult:
    if not 0 <= minimum_coverage_bps <= 10_000:
        raise ValueError("minimum_coverage_bps must be between 0 and 10000")
    if dem is None:
        return ElevationCorrectionResult(
            status="unavailable",
            source_version="none",
            correction_version=ELEVATION_CORRECTION_VERSION,
            coverage_bps=0,
            elevation_gain_m=None,
            corrected_elevations_m=tuple(None for _ in route),
            reason="dem_grid_missing",
        )
    if not route:
        return ElevationCorrectionResult(
            status="unavailable",
            source_version=dem.source_version,
            correction_version=ELEVATION_CORRECTION_VERSION,
            coverage_bps=0,
            elevation_gain_m=None,
            corrected_elevations_m=(),
            reason="missing_route",
        )

    matches = _map_match_with_stationary_hysteresis(route, dem)
    matched_count = sum(value is not None for value in matches)
    coverage_bps = matched_count * 10_000 // len(route)

    if coverage_bps < minimum_coverage_bps:
        # Never ship a partial corrected profile: clients would sum it into a
        # fabricated total. Unavailable means no corrected values at all.
        return ElevationCorrectionResult(
            status="unavailable",
            source_version=dem.source_version,
            correction_version=ELEVATION_CORRECTION_VERSION,
            coverage_bps=coverage_bps,
            elevation_gain_m=None,
            corrected_elevations_m=tuple(None for _ in route),
            reason="insufficient_dem_coverage",
        )

    segment_starts = [point.starts_new_segment for point in route]
    smoothed = _median_smooth_without_crossing_missing(matches, segment_starts)
    gain = _gain_with_hysteresis(smoothed, segment_starts)
    return ElevationCorrectionResult(
        status="corrected",
        source_version=dem.source_version,
        correction_version=ELEVATION_CORRECTION_VERSION,
        coverage_bps=coverage_bps,
        elevation_gain_m=round(gain, 1),
        corrected_elevations_m=tuple(
            round(value, 1) if value is not None else None for value in smoothed
        ),
    )


def encode_correction_profile(
    elevations_m: Sequence[Optional[float]],
) -> dict[str, Any]:
    """Delta-encode corrected elevations (decimeters) aligned to gps_track."""

    deltas: list[int] = []
    missing_ranges: list[list[int]] = []
    previous = 0
    run_start: Optional[int] = None
    for index, value in enumerate(elevations_m):
        if value is None:
            if run_start is None:
                run_start = index
            deltas.append(0)
            continue
        if run_start is not None:
            missing_ranges.append([run_start, index - 1])
            run_start = None
        decimeters = int(round(value * 10))
        deltas.append(decimeters - previous)
        previous = decimeters
    if run_start is not None:
        missing_ranges.append([run_start, len(list(elevations_m)) - 1])
    return {
        "v": PROFILE_STORAGE_VERSION,
        "count": len(deltas),
        "elevations_dm": deltas,
        "missing_ranges": missing_ranges,
    }


def decode_correction_profile(profile: Any) -> list[Optional[float]]:
    """Decode the stored profile back to per-point meters (None = missing)."""

    if not isinstance(profile, dict):
        return []
    if profile.get("v") != PROFILE_STORAGE_VERSION:
        return []
    deltas = profile.get("elevations_dm")
    if not isinstance(deltas, list):
        return []
    missing: set[int] = set()
    for entry in profile.get("missing_ranges") or []:
        if (
            isinstance(entry, (list, tuple))
            and len(entry) == 2
            and all(isinstance(edge, int) for edge in entry)
        ):
            start, end = entry
            missing.update(range(max(start, 0), min(end, len(deltas) - 1) + 1))
    values: list[Optional[float]] = []
    total = 0
    for index, delta in enumerate(deltas):
        if index in missing:
            values.append(None)
            continue
        if not isinstance(delta, int):
            return []
        total += delta
        values.append(total / 10.0)
    return values


def _map_match_with_stationary_hysteresis(
    route: Sequence[RouteElevationPoint],
    dem: DEMIndex,
) -> list[Optional[float]]:
    """Anchor DEM lookups until the rider makes real horizontal progress.

    Stationary GPS jitter (a few meters) must not walk across DEM cells and
    accumulate phantom ascent; the anchor releases after 8 m of progress.
    """

    matches: list[Optional[float]] = []
    anchor: Optional[RouteElevationPoint] = None
    anchor_elevation: Optional[float] = None
    for point in route:
        if point.starts_new_segment:
            anchor = None
            anchor_elevation = None
        if not _valid_coordinate(point.latitude, point.longitude):
            matches.append(None)
            anchor = None
            anchor_elevation = None
            continue
        if anchor is not None and anchor_elevation is not None:
            progress = _haversine_m(
                anchor.latitude,
                anchor.longitude,
                point.latitude,
                point.longitude,
            )
            if progress < MAP_MATCH_MINIMUM_PROGRESS_M:
                matches.append(anchor_elevation)
                continue
        elevation = dem.elevation_at(point.latitude, point.longitude)
        matches.append(elevation)
        if elevation is None:
            anchor = None
            anchor_elevation = None
        else:
            anchor = point
            anchor_elevation = elevation
    return matches


def _median_smooth_without_crossing_missing(
    elevations: Sequence[Optional[float]],
    segment_starts: Sequence[bool],
) -> list[Optional[float]]:
    result = list(elevations)
    for index in range(1, len(elevations) - 1):
        if segment_starts[index] or segment_starts[index + 1]:
            continue
        window = elevations[index - 1 : index + 2]
        if any(value is None for value in window):
            continue
        result[index] = sorted(float(value) for value in window if value is not None)[1]
    return result


def _gain_with_hysteresis(
    elevations: Iterable[Optional[float]],
    segment_starts: Sequence[bool],
) -> float:
    gain = 0.0
    baseline: Optional[float] = None
    peak: Optional[float] = None

    def commit_ascent() -> float:
        if baseline is None or peak is None:
            return 0.0
        ascent = peak - baseline
        return ascent if ascent >= GAIN_HYSTERESIS_M else 0.0

    for index, elevation in enumerate(elevations):
        if index > 0 and segment_starts[index]:
            gain += commit_ascent()
            baseline = None
            peak = None
        if elevation is None:
            gain += commit_ascent()
            baseline = None
            peak = None
            continue
        if baseline is None or peak is None:
            baseline = elevation
            peak = elevation
            continue
        if elevation >= peak:
            peak = elevation
            continue
        if peak - elevation >= GAIN_HYSTERESIS_M:
            gain += commit_ascent()
            baseline = elevation
            peak = elevation
        elif elevation < baseline:
            baseline = elevation
    return gain + commit_ascent()


def _valid_coordinate(latitude: float, longitude: float) -> bool:
    return (
        math.isfinite(latitude)
        and math.isfinite(longitude)
        and -90 <= latitude <= 90
        and -180 <= longitude <= 180
    )


def _finite_or_none(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_m = 6_371_008.8
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = lat2_rad - lat1_rad
    delta_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    )
    return radius_m * 2 * math.atan2(math.sqrt(a), math.sqrt(max(0, 1 - a)))
