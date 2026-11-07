"""
TileService: H3 hexagonal tile projection for GPS coordinates.

This service handles converting GPS coordinates to H3 hexagonal tile indices,
enabling privacy-preserving location attestation and ride verification.

H3 is Uber's Hexagonal Hierarchical Spatial Index system, providing consistent
global coverage with hexagonal cells at multiple resolutions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

import h3

_HIGHWAY_RANK = {
    "motorway": 10,
    "motorway_link": 9,
    "trunk": 8,
    "trunk_link": 7,
    "primary": 6,
    "primary_link": 5,
    "secondary": 4,
    "secondary_link": 3,
    "tertiary": 2,
    "tertiary_link": 1,
}


def _highway_rank(highway_class: Optional[str]) -> int:
    return _HIGHWAY_RANK.get(highway_class or "", 0)


def _is_optional_attribution_schema_error(exc: Exception) -> bool:
    text = str(exc).lower()
    missing_schema = (
        "does not exist" in text
        or "could not find the function" in text
        or "schema cache" in text
        or "column" in text
        or "relation" in text
        or "function" in text
    )
    optional_surface = any(
        name in text
        for name in ("get_tile_attribution", "tile_features", "road_features", "feature_type")
    )
    return missing_schema and optional_surface


@dataclass
class TileSample:
    """A single tile sample with associated sensor data."""

    tile_id: str  # H3 index
    t: float  # Elapsed time in seconds
    lat: float  # Original latitude (for reference)
    lon: float  # Original longitude (for reference)
    elevation_m: Optional[float] = None
    power_w: Optional[int] = None
    hr_bpm: Optional[int] = None
    speed_mps: Optional[float] = None


class TileService:
    """
    Service for converting GPS coordinates to H3 hexagonal tiles.

    H3 Resolution Reference:
    - Res 8: ~461m edge, ~0.74 km² - Neighborhood level
    - Res 9: ~174m edge, ~0.10 km² - City block level
    - Res 10: ~66m edge, ~0.015 km² - Street segment level (DEFAULT for cycling)
    - Res 11: ~25m edge, ~0.002 km² - Building level (high precision)
    - Res 12: ~9m edge, ~0.0003 km² - Very high precision

    For road cycling, we default to resolution 10 (~50-100m hexagons) which provides
    good precision for route tracking while preserving some location privacy.
    """

    # Resolution constants for different use cases
    RESOLUTION_NEIGHBORHOOD = 8  # ~500m hexagons - for area-based rewards
    RESOLUTION_BLOCK = 9  # ~200m hexagons - for general location
    RESOLUTION_STREET = 10  # ~50m hexagons - DEFAULT for road cycling
    RESOLUTION_BUILDING = 11  # ~25m hexagons - high precision tracking
    RESOLUTION_PRECISE = 12  # ~10m hexagons - very high precision

    # Default resolution for ride tracking
    DEFAULT_RESOLUTION = RESOLUTION_STREET

    def lat_lng_to_tile(
        self,
        lat: float,
        lon: float,
        resolution: int = DEFAULT_RESOLUTION,
    ) -> str:
        """
        Convert latitude/longitude to H3 hexagonal tile index.

        Args:
            lat: Latitude in degrees
            lon: Longitude in degrees
            resolution: H3 resolution level (8-12, default 10)

        Returns:
            H3 tile index as a 15-character hexadecimal string

        Example:
            >>> service = TileService()
            >>> tile_id = service.lat_lng_to_tile(40.7128, -74.0060)
            >>> print(tile_id)
            '8a2a1072b59ffff'
        """
        if not (-90 <= lat <= 90):
            raise ValueError(f"Invalid latitude: {lat}. Must be between -90 and 90.")
        if not (-180 <= lon <= 180):
            raise ValueError(f"Invalid longitude: {lon}. Must be between -180 and 180.")
        if not (0 <= resolution <= 15):
            raise ValueError(f"Invalid resolution: {resolution}. Must be between 0 and 15.")

        return h3.latlng_to_cell(lat, lon, resolution)

    def tile_to_lat_lng(self, tile_id: str) -> tuple[float, float]:
        """
        Convert H3 tile index back to latitude/longitude (center point).

        Args:
            tile_id: H3 tile index

        Returns:
            Tuple of (latitude, longitude) for the tile's center point

        Example:
            >>> service = TileService()
            >>> lat, lon = service.tile_to_lat_lng('8a2a1072b59ffff')
            >>> print(f"{lat:.6f}, {lon:.6f}")
        """
        lat, lon = h3.cell_to_latlng(tile_id)
        return lat, lon

    def get_tile_boundary(self, tile_id: str) -> List[tuple[float, float]]:
        """
        Get the hexagonal boundary coordinates for a tile.

        Args:
            tile_id: H3 tile index

        Returns:
            List of (lat, lon) tuples forming the hexagon boundary

        Example:
            >>> service = TileService()
            >>> boundary = service.get_tile_boundary('8a2a1072b59ffff')
            >>> # Returns 6 or 7 coordinate pairs forming hexagon vertices
        """
        boundary = h3.cell_to_boundary(tile_id)
        return [(lat, lon) for lat, lon in boundary]

    def get_tile_sequence(
        self,
        gps_points: List[Dict],
        resolution: int = DEFAULT_RESOLUTION,
        start_time: Optional[float] = None,
    ) -> List[TileSample]:
        """
        Convert a GPS track to a sequence of tile samples.

        Args:
            gps_points: List of GPS points, each with keys:
                - lat: float
                - lon: float
                - timestamp: datetime or float (optional)
                - elevation_m: float (optional)
                - power_w: int (optional)
                - hr_bpm: int (optional)
                - speed_mps: float (optional)
            resolution: H3 resolution level (default 10)
            start_time: Starting timestamp for calculating elapsed time (optional)

        Returns:
            List of TileSample objects with tile_id and sensor data

        Example:
            >>> gps_track = [
            ...     {"lat": 40.7128, "lon": -74.0060, "timestamp": 1234567890.0,
            ...      "elevation_m": 10.5, "power_w": 250},
            ...     {"lat": 40.7129, "lon": -74.0061, "timestamp": 1234567891.0,
            ...      "elevation_m": 11.2, "power_w": 255},
            ... ]
            >>> tiles = service.get_tile_sequence(gps_track)
        """
        if not gps_points:
            return []

        tile_samples: List[TileSample] = []

        # Normalize start_time to a float (epoch seconds)
        if start_time is not None:
            start_time = start_time.timestamp() if hasattr(start_time, "timestamp") else float(start_time)
        elif gps_points[0].get("timestamp"):
            first_ts = gps_points[0]["timestamp"]
            start_time = first_ts.timestamp() if hasattr(first_ts, "timestamp") else float(first_ts)

        for i, point in enumerate(gps_points):
            lat = point.get("lat") or point.get("latitude")
            lon = point.get("lon") or point.get("longitude")

            if lat is None or lon is None:
                continue

            # Calculate elapsed time
            t = 0.0
            if start_time is not None and point.get("timestamp"):
                ts = point["timestamp"]
                current_ts = ts.timestamp() if hasattr(ts, "timestamp") else float(ts)
                t = current_ts - start_time
            else:
                # Fallback: use index as time if no timestamps
                t = float(i)

            # Skip malformed coordinates instead of aborting the whole sequence.
            try:
                tile_id = self.lat_lng_to_tile(lat, lon, resolution)
            except Exception:
                continue

            # Extract optional sensor data
            tile_sample = TileSample(
                tile_id=tile_id,
                t=t,
                lat=lat,
                lon=lon,
                elevation_m=point.get("elevation_m", point.get("elevation")),
                power_w=point.get("power_w", point.get("power")),
                hr_bpm=point.get("hr_bpm") or point.get("heart_rate_bpm") or point.get("heart_rate"),
                speed_mps=point.get("speed_mps", point.get("speed")),
            )

            tile_samples.append(tile_sample)

        return tile_samples

    @staticmethod
    def _to_unix_seconds(value: Any) -> Optional[float]:
        if value is None:
            return None
        if hasattr(value, "timestamp"):
            try:
                return float(value.timestamp())
            except Exception:
                return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def get_tile_run_sequence(
        self,
        points: List[Dict],
        resolution: int = DEFAULT_RESOLUTION,
        start_time: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """
        Convert point samples to contiguous "tile runs" (one sample per stay in a tile).

        Each output sample represents a contiguous time period spent in the same H3 tile,
        with sensor values aggregated across all points in that period.

        Output dicts are compatible with PatternEngine + store_activity_tile_samples:
        {
            "tile_id": str,
            "t": int,                 # seconds since ride start (segment start)
            "lat": float,
            "lon": float,
            "elevation_m": Optional[float],
            "power_w": Optional[int], # avg over segment
            "hr_bpm": Optional[int],  # avg over segment
            "speed_mps": Optional[float], # avg over segment
            # plus debug fields: t_end, duration_s, elevation_min_m, elevation_max_m, samples
        }
        """
        if not points:
            return []

        start_time_s = self._to_unix_seconds(start_time)

        # Extract and sort by timestamp to ensure correct ordering.
        rows: list[dict[str, Any]] = []
        for i, point in enumerate(points):
            lat = point.get("lat") or point.get("latitude")
            lon = point.get("lon") or point.get("longitude")
            ts = point.get("timestamp")
            ts_s = self._to_unix_seconds(ts)

            if lat is None or lon is None or ts_s is None:
                continue

            rows.append(
                {
                    "i": i,
                    "ts_s": ts_s,
                    "lat": float(lat),
                    "lon": float(lon),
                    "elevation_m": point.get("elevation_m", point.get("elevation")),
                    "power_w": point.get("power_w", point.get("power")),
                    "hr_bpm": point.get("hr_bpm")
                    or point.get("heart_rate_bpm")
                    or point.get("heart_rate"),
                    "speed_mps": point.get("speed_mps", point.get("speed")),
                }
            )

        if not rows:
            return []

        rows.sort(key=lambda r: (r["ts_s"], r["i"]))

        if start_time_s is None:
            start_time_s = rows[0]["ts_s"]

        tile_runs: list[Dict[str, Any]] = []

        current_tile_id: Optional[str] = None
        run_start_t: int = 0
        run_end_t: int = 0
        run_lat: float = 0.0
        run_lon: float = 0.0

        elev_first: Optional[float] = None
        elev_min: Optional[float] = None
        elev_max: Optional[float] = None

        power_sum = 0.0
        power_count = 0
        hr_sum = 0.0
        hr_count = 0
        speed_sum = 0.0
        speed_count = 0
        sample_count = 0

        def _finish_run() -> None:
            nonlocal current_tile_id
            nonlocal run_start_t, run_end_t, run_lat, run_lon
            nonlocal elev_first, elev_min, elev_max
            nonlocal power_sum, power_count, hr_sum, hr_count, speed_sum, speed_count, sample_count

            if current_tile_id is None:
                return

            tile_runs.append(
                {
                    "tile_id": current_tile_id,
                    "t": run_start_t,
                    "lat": run_lat,
                    "lon": run_lon,
                    "elevation_m": elev_first,
                    "power_w": int(round(power_sum / power_count)) if power_count > 0 else None,
                    "hr_bpm": int(round(hr_sum / hr_count)) if hr_count > 0 else None,
                    "speed_mps": (speed_sum / speed_count) if speed_count > 0 else None,
                    "t_end": run_end_t,
                    "duration_s": max(0, run_end_t - run_start_t),
                    "elevation_min_m": elev_min,
                    "elevation_max_m": elev_max,
                    "samples": sample_count,
                }
            )

            current_tile_id = None
            elev_first = None
            elev_min = None
            elev_max = None
            power_sum = 0.0
            power_count = 0
            hr_sum = 0.0
            hr_count = 0
            speed_sum = 0.0
            speed_count = 0
            sample_count = 0

        for row in rows:
            t = int(max(0.0, row["ts_s"] - start_time_s))
            lat = row["lat"]
            lon = row["lon"]

            try:
                tile_id = self.lat_lng_to_tile(lat, lon, resolution)
            except Exception:
                continue

            if current_tile_id is None:
                current_tile_id = tile_id
                run_start_t = t
                run_end_t = t
                run_lat = lat
                run_lon = lon
            elif tile_id != current_tile_id:
                _finish_run()
                current_tile_id = tile_id
                run_start_t = t
                run_end_t = t
                run_lat = lat
                run_lon = lon
            else:
                run_end_t = t

            sample_count += 1

            elev = row.get("elevation_m")
            if elev is not None:
                try:
                    elev_f = float(elev)
                except (TypeError, ValueError):
                    elev_f = None
                if elev_f is not None:
                    if elev_first is None:
                        elev_first = elev_f
                    elev_min = elev_f if elev_min is None else min(elev_min, elev_f)
                    elev_max = elev_f if elev_max is None else max(elev_max, elev_f)

            pwr = row.get("power_w")
            if pwr is not None:
                try:
                    power_sum += float(pwr)
                    power_count += 1
                except (TypeError, ValueError):
                    pass

            hr = row.get("hr_bpm")
            if hr is not None:
                try:
                    hr_val = float(hr)
                except (TypeError, ValueError):
                    hr_val = None
                if hr_val is not None and hr_val > 0:
                    hr_sum += hr_val
                    hr_count += 1

            spd = row.get("speed_mps")
            if spd is not None:
                try:
                    spd_val = float(spd)
                except (TypeError, ValueError):
                    spd_val = None
                if spd_val is not None and spd_val > 0:
                    speed_sum += spd_val
                    speed_count += 1

        _finish_run()

        return tile_runs

    def get_neighboring_tiles(self, tile_id: str, k: int = 1) -> List[str]:
        """
        Get the k-ring of neighboring tiles around a given tile.

        Args:
            tile_id: Center H3 tile index
            k: Ring distance (1 = immediate neighbors, 2 = second ring, etc.)

        Returns:
            List of H3 tile indices in the k-ring (includes center tile)

        Example:
            >>> service = TileService()
            >>> neighbors = service.get_neighboring_tiles('8a2a1072b59ffff', k=1)
            >>> # Returns 7 tiles: the center + 6 immediate neighbors
        """
        return list(h3.grid_disk(tile_id, k))

    def get_resolution(self, tile_id: str) -> int:
        """
        Get the resolution level of an H3 tile.

        Args:
            tile_id: H3 tile index

        Returns:
            Resolution level (0-15)
        """
        return h3.get_resolution(tile_id)

    def deduplicate_tiles(
        self,
        tile_samples: List[TileSample],
        keep_first: bool = True,
    ) -> List[TileSample]:
        """
        Remove consecutive duplicate tiles from a sequence.

        When a rider stays in the same tile for multiple samples, we may want to
        keep only one sample per tile to reduce storage and improve privacy.

        Args:
            tile_samples: List of TileSample objects
            keep_first: If True, keep first occurrence; if False, keep last

        Returns:
            Deduplicated list of TileSample objects

        Example:
            >>> samples = [
            ...     TileSample('tile1', 0, 40.0, -74.0),
            ...     TileSample('tile1', 1, 40.0, -74.0),  # duplicate
            ...     TileSample('tile2', 2, 40.1, -74.1),
            ... ]
            >>> deduped = service.deduplicate_tiles(samples)
            >>> len(deduped)  # 2 (removed middle duplicate)
        """
        if not tile_samples:
            return []

        result: List[TileSample] = []
        prev_tile_id = None

        for sample in tile_samples:
            if sample.tile_id != prev_tile_id:
                result.append(sample)
                prev_tile_id = sample.tile_id
            elif not keep_first:
                # Replace with latest sample in this tile
                result[-1] = sample

        return result

    def get_unique_tiles(self, tile_samples: List[TileSample]) -> List[str]:
        """
        Get a list of unique tile IDs from a sequence.

        Args:
            tile_samples: List of TileSample objects

        Returns:
            List of unique H3 tile indices in order of first appearance

        Example:
            >>> unique = service.get_unique_tiles(tile_samples)
            >>> # Returns deduplicated list of tile IDs
        """
        seen = set()
        unique_tiles = []

        for sample in tile_samples:
            if sample.tile_id not in seen:
                seen.add(sample.tile_id)
                unique_tiles.append(sample.tile_id)

        return unique_tiles

    async def project_gps_to_tiles(
        self,
        gps_track: List[Dict],
        resolution: int = DEFAULT_RESOLUTION,
    ) -> List[Dict]:
        """
        Project GPS track to H3 tiles (async wrapper for ride processor).

        This method converts a GPS track to tile samples and returns them
        as dictionaries ready for database insertion.

        Args:
            gps_track: List of GPS points with lat, lon, timestamp, etc.
            resolution: H3 resolution level (default 10)

        Returns:
            List of dictionaries with tile_id and sensor data
        """
        # Get tile sequence using the sync method
        tile_samples = self.get_tile_sequence(gps_track, resolution)

        # Deduplicate consecutive tiles
        deduped = self.deduplicate_tiles(tile_samples)

        # Convert to dictionaries for database storage
        return [
            {
                "tile_id": sample.tile_id,
                "t": int(sample.t),
                "lat": sample.lat,
                "lon": sample.lon,
                "elevation_m": sample.elevation_m,
                "power_w": sample.power_w,
                "hr_bpm": sample.hr_bpm,
                "speed_mps": sample.speed_mps,
            }
            for sample in deduped
        ]

    async def project_points_to_tile_runs(
        self,
        points: List[Dict],
        resolution: int = DEFAULT_RESOLUTION,
        start_time: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """
        Project point samples to contiguous tile runs (async wrapper).

        Unlike project_gps_to_tiles(), this aggregates consecutive points that fall
        in the same tile into a single sample with averaged sensor values.
        """
        return self.get_tile_run_sequence(points=points, resolution=resolution, start_time=start_time)


@dataclass
class RoadAttribution:
    """Attribution of tiles to a named road feature."""

    road_name: str
    road_class: str
    grade: Optional[float]  # Average grade percentage
    tile_count: int  # Number of tiles matching this road
    coverage_pct: float  # Percentage of input tiles on this road


@dataclass
class TileAttributionResult:
    """Result of attributing a set of tiles to road features."""

    total_tiles: int
    matched_tiles: int
    coverage_pct: float  # Overall percentage of tiles with road attribution
    roads: List[RoadAttribution]  # Roads sorted by coverage (descending)

    @property
    def primary_road(self) -> Optional[RoadAttribution]:
        """Get the road with highest coverage, if any."""
        return self.roads[0] if self.roads else None

    def summary(self) -> str:
        """Generate a human-readable attribution summary."""
        if not self.roads:
            return "No road attribution available"

        parts = []
        for road in self.roads[:3]:  # Top 3 roads
            if road.grade:
                parts.append(f"{road.coverage_pct:.0f}% on {road.road_name} ({road.grade:.1f}% grade)")
            else:
                parts.append(f"{road.coverage_pct:.0f}% on {road.road_name}")

        return ", ".join(parts)


class TileAttributionService:
    """
    Service for attributing H3 tiles to named road features.

    Uses preprocessed OSM data to identify which roads a ride traversed,
    enabling attribution like "Your climb was 85% on Manayunk Wall".

    This service queries the tile_features and road_features tables populated
    by the OSM preprocessing pipeline.
    """

    def __init__(self, supabase_client):
        """
        Initialize with a Supabase client.

        Args:
            supabase_client: Initialized Supabase client
        """
        self.client = supabase_client

    def _empty_result(self, total_tiles: int) -> TileAttributionResult:
        return TileAttributionResult(
            total_tiles=total_tiles,
            matched_tiles=0,
            coverage_pct=0.0,
            roads=[],
        )

    def _build_current_attribution(
        self,
        rows: List[Dict[str, Any]],
        total_tiles: int,
        min_coverage_pct: float,
    ) -> TileAttributionResult:
        best_by_tile: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            name = row.get("name")
            tile_id = row.get("tile_id")
            if not name or not tile_id:
                continue

            current = best_by_tile.get(tile_id)
            if current is None or _highway_rank(row.get("highway_class")) > _highway_rank(
                current.get("highway_class")
            ):
                best_by_tile[tile_id] = row

        grouped: Dict[str, Dict[str, Any]] = {}
        for row in best_by_tile.values():
            road_class = row.get("highway_class") or "Unknown"
            road_name = row["name"]
            current = grouped.setdefault(
                road_name,
                {"road_class": road_class, "tile_count": 0},
            )
            current["tile_count"] += 1
            if _highway_rank(road_class) > _highway_rank(current["road_class"]):
                current["road_class"] = road_class

        roads: List[RoadAttribution] = []
        for road_name, data in grouped.items():
            tile_count = data["tile_count"]
            coverage = (tile_count / total_tiles * 100.0) if total_tiles else 0.0
            if coverage >= min_coverage_pct:
                roads.append(
                    RoadAttribution(
                        road_name=road_name,
                        road_class=data["road_class"],
                        grade=None,
                        tile_count=tile_count,
                        coverage_pct=coverage,
                    )
                )

        roads.sort(key=lambda road: road.coverage_pct, reverse=True)
        matched_tiles = sum(road.tile_count for road in roads)
        coverage_pct = (matched_tiles / total_tiles * 100.0) if total_tiles else 0.0
        return TileAttributionResult(
            total_tiles=total_tiles,
            matched_tiles=matched_tiles,
            coverage_pct=min(100.0, coverage_pct),
            roads=roads,
        )

    def _attribute_tiles_from_current_schema(
        self,
        unique_tiles: List[str],
        min_coverage_pct: float,
    ) -> TileAttributionResult:
        response = (
            self.client.table("road_features")
            .select("tile_id, feature_type, name, highway_class")
            .in_("tile_id", unique_tiles)
            .eq("feature_type", "road_segment")
            .execute()
        )
        return self._build_current_attribution(
            rows=getattr(response, "data", None) or [],
            total_tiles=len(unique_tiles),
            min_coverage_pct=min_coverage_pct,
        )

    def _attribute_tiles_from_legacy_rpc(
        self,
        unique_tiles: List[str],
        min_coverage_pct: float,
    ) -> TileAttributionResult:
        response = self.client.rpc("get_tile_attribution", {"tile_ids": unique_tiles}).execute()

        roads = []
        for row in response.data or []:
            coverage = row.get("coverage_pct", 0)
            if coverage >= min_coverage_pct:
                roads.append(
                    RoadAttribution(
                        road_name=row["road_name"],
                        road_class=row.get("road_class", "Unknown"),
                        grade=row.get("grade"),
                        tile_count=row.get("tile_count", 0),
                        coverage_pct=coverage,
                    )
                )

        overall_coverage = sum(r.coverage_pct for r in roads)
        matched_tiles = int(len(unique_tiles) * overall_coverage / 100) if overall_coverage else 0
        return TileAttributionResult(
            total_tiles=len(unique_tiles),
            matched_tiles=matched_tiles,
            coverage_pct=min(100.0, overall_coverage),
            roads=roads,
        )

    async def attribute_tiles(
        self,
        tile_ids: List[str],
        min_coverage_pct: float = 5.0,
    ) -> TileAttributionResult:
        """
        Attribute a set of tiles to road features.

        Args:
            tile_ids: List of H3 tile indices
            min_coverage_pct: Minimum coverage percentage to include a road (default 5%)

        Returns:
            TileAttributionResult with road attributions sorted by coverage

        Example:
            >>> result = await service.attribute_tiles(ride_tiles)
            >>> print(result.summary())
            "85% on Manayunk Wall (8.5% grade), 10% on Ridge Avenue"
        """
        if not tile_ids:
            return TileAttributionResult(
                total_tiles=0,
                matched_tiles=0,
                coverage_pct=0.0,
                roads=[],
            )

        unique_tiles = list(set(tile_ids))
        total_tiles = len(unique_tiles)

        # Prefer the current road_features schema. The old tile_features RPC is
        # retained only as a rollout fallback for databases that still have it.
        try:
            return self._attribute_tiles_from_current_schema(unique_tiles, min_coverage_pct)
        except Exception as exc:
            if _is_optional_attribution_schema_error(exc):
                logger.debug("Current road attribution schema unavailable: %s", exc)
            else:
                logger.warning("Current road attribution failed, trying legacy RPC: %s", exc)

        try:
            return self._attribute_tiles_from_legacy_rpc(unique_tiles, min_coverage_pct)
        except Exception as exc:
            if _is_optional_attribution_schema_error(exc):
                logger.debug("Optional legacy tile attribution schema unavailable: %s", exc)
            else:
                logger.warning("Tile attribution failed: %s", exc)
            return self._empty_result(total_tiles)

    async def get_climb_attribution(
        self,
        tile_ids: List[str],
        vert_m: float,
    ) -> Dict[str, Any]:
        """
        Get attribution specifically for a climb pattern.

        Args:
            tile_ids: List of H3 tile indices for the climb
            vert_m: Total vertical gain in meters

        Returns:
            Dictionary with climb-specific attribution:
            {
                "road_name": str or None,
                "road_grade": float or None,
                "coverage_pct": float,
                "attribution_summary": str,
            }
        """
        result = await self.attribute_tiles(tile_ids, min_coverage_pct=10.0)

        primary = result.primary_road
        return {
            "road_name": primary.road_name if primary else None,
            "road_grade": primary.grade if primary else None,
            "coverage_pct": primary.coverage_pct if primary else 0.0,
            "attribution_summary": result.summary(),
        }
