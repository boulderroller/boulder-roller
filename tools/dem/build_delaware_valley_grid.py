#!/usr/bin/env python3
"""Export the Delaware Valley ride-correction DEM grid from local 3DEP tiles.

Feature: boulderroller-v2-odmi6.2.1 (server-side DEM-corrected ride elevation).
This is an OFFLINE generator, not a runtime dependency. It consumes the same
locally downloaded USGS 3DEP 1/3 arc-second GeoTIFFs the canon compiler's
profile exporter uses (CANON_BUILD_DECISIONS.md D6) and emits a compact
1 arc-second cell-center grid the backend samples at ride-processing time.

The emitted asset is deliberately NOT committed to git (tens of MB). It is a
deploy asset placed on the API host and bind-mounted into the container at
/app/resources/dem (see docker-compose.yml). Regenerate with this script on a
machine that holds the source tiles; provenance and digests land in meta.json
next to the binary so the runtime loader can verify what it is reading.

Data license: USGS 3DEP is public domain (U.S. Geological Survey). The source
tile names and acquisition dates are recorded in the output metadata.

Example invocation (paths from the July 2026 canon compile):

    python tools/dem/build_delaware_valley_grid.py \
        --dem .../workout-parse/data/dem/USGS_13_n40w076_20250507.tif \
        --dem .../workout-parse/data/dem/USGS_13_n41w076_20221115.tif \
        --validate-profiles workout-parse/resources/philly_ratified_boundary_3dep_profiles_v1.json \
        --output-dir data/dem

Requires numpy + tifffile + imagecodecs (LZW), e.g. in a throwaway venv.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import tifffile

GRID_FORMAT = "br_dem_grid_v1"
SOURCE_VERSION = "usgs_3dep_13as_dv_1as_grid_v1"
NODATA_OUT = -32768
SOURCE_NODATA = -999999.0
STEP_DEG = 1.0 / 3600.0  # 1 arc-second target cells


@dataclass
class SourceTile:
    path: Path
    data: np.ndarray  # float32, row 0 = north
    lon_center0: float  # longitude of pixel (0,0) CENTER
    lat_center0: float  # latitude of pixel (0,0) CENTER
    scale_deg: float
    raster_type: str  # "pixel_is_area" | "pixel_is_point"
    lat_min: float
    lat_max: float


def _geokey(directory: tuple, key_id: int) -> int | None:
    # GeoKeyDirectory: header of 4 shorts then N entries of 4 shorts each.
    entries = directory[4:]
    for i in range(0, len(entries) - 3, 4):
        if entries[i] == key_id and entries[i + 1] == 0:
            return int(entries[i + 3])
    return None


def load_tile(path: Path) -> SourceTile:
    with tifffile.TiffFile(str(path)) as tf:
        page = tf.pages[0]
        tags = page.tags
        scale = tags["ModelPixelScaleTag"].value
        tiepoint = tags["ModelTiepointTag"].value
        geokeys = tags["GeoKeyDirectoryTag"].value
        raster_type_code = _geokey(tuple(geokeys), 1025)
        if raster_type_code == 2:
            raster_type = "pixel_is_point"
        elif raster_type_code in (1, None):
            # Missing registration defaults to PixelIsArea, matching the canon
            # exporter's documented behavior (CANON_BUILD_DECISIONS.md).
            raster_type = "pixel_is_area"
        else:
            raise SystemExit(f"{path}: malformed GTRasterTypeGeoKey {raster_type_code}")
        if abs(scale[0] - scale[1]) > 1e-12:
            raise SystemExit(f"{path}: anisotropic pixel scale unsupported")
        if tuple(tiepoint[:3]) != (0.0, 0.0, 0.0):
            raise SystemExit(f"{path}: unexpected raster tiepoint {tiepoint[:3]}")
        data = page.asarray()
    scale_deg = float(scale[0])
    lon0, lat0 = float(tiepoint[3]), float(tiepoint[4])
    if raster_type == "pixel_is_area":
        # Tiepoint references the outer corner of pixel (0,0); shift to center.
        lon_center0 = lon0 + scale_deg / 2.0
        lat_center0 = lat0 - scale_deg / 2.0
    else:
        lon_center0 = lon0
        lat_center0 = lat0
    rows = data.shape[0]
    lat_min = lat_center0 - (rows - 1) * scale_deg
    return SourceTile(
        path=path,
        data=data,
        lon_center0=lon_center0,
        lat_center0=lat_center0,
        scale_deg=scale_deg,
        raster_type=raster_type,
        lat_min=lat_min,
        lat_max=lat_center0,
    )


def bilinear_rows(tile: SourceTile, lat_centers: np.ndarray, lon_centers: np.ndarray) -> np.ndarray:
    """Sample a lat×lon block of target cell centers from one source tile."""
    row_f = (tile.lat_center0 - lat_centers) / tile.scale_deg
    col_f = (lon_centers - tile.lon_center0) / tile.scale_deg
    r0 = np.floor(row_f).astype(np.int64)
    c0 = np.floor(col_f).astype(np.int64)
    max_r = tile.data.shape[0] - 2
    max_c = tile.data.shape[1] - 2
    out_of_bounds_r = (r0 < 0) | (r0 > max_r)
    out_of_bounds_c = (c0 < 0) | (c0 > max_c)
    r0c = np.clip(r0, 0, max_r)
    c0c = np.clip(c0, 0, max_c)
    wr = (row_f - r0c)[:, None]
    wc = (col_f - c0c)[None, :]
    q00 = tile.data[np.ix_(r0c, c0c)].astype(np.float64)
    q01 = tile.data[np.ix_(r0c, c0c + 1)].astype(np.float64)
    q10 = tile.data[np.ix_(r0c + 1, c0c)].astype(np.float64)
    q11 = tile.data[np.ix_(r0c + 1, c0c + 1)].astype(np.float64)
    nod = (
        (q00 == SOURCE_NODATA)
        | (q01 == SOURCE_NODATA)
        | (q10 == SOURCE_NODATA)
        | (q11 == SOURCE_NODATA)
        | out_of_bounds_r[:, None]
        | out_of_bounds_c[None, :]
    )
    value = (
        q00 * (1 - wr) * (1 - wc)
        + q01 * (1 - wr) * wc
        + q10 * wr * (1 - wc)
        + q11 * wr * wc
    )
    value[nod] = np.nan
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dem", action="append", required=True, type=Path)
    parser.add_argument("--min-lat", type=float, default=39.5)
    parser.add_argument("--max-lat", type=float, default=40.6)
    parser.add_argument("--min-lon", type=float, default=-76.0)
    parser.add_argument("--max-lon", type=float, default=-75.0)
    parser.add_argument("--output-dir", type=Path, default=Path("data/dem"))
    parser.add_argument("--validate-profiles", type=Path, default=None)
    args = parser.parse_args()

    tiles = [load_tile(p) for p in args.dem]
    for tile in tiles:
        print(
            f"loaded {tile.path.name}: scale={tile.scale_deg:.9f} deg, "
            f"{tile.raster_type}, lat centers {tile.lat_min:.6f}..{tile.lat_max:.6f}"
        )

    rows = int(round((args.max_lat - args.min_lat) / STEP_DEG))
    cols = int(round((args.max_lon - args.min_lon) / STEP_DEG))
    lat_centers = args.max_lat - (np.arange(rows) + 0.5) * STEP_DEG
    lon_centers = args.min_lon + (np.arange(cols) + 0.5) * STEP_DEG

    grid = np.full((rows, cols), np.nan, dtype=np.float64)
    for tile in tiles:
        # A row belongs to this tile if the tile's core degree cell contains
        # it; the 6-pixel collar guarantees bilinear neighbors near edges.
        usable = (
            (lat_centers <= tile.lat_max - tile.scale_deg)
            & (lat_centers >= tile.lat_min + tile.scale_deg)
        )
        pending = usable & np.isnan(grid[:, 0]) if cols else usable
        row_idx = np.nonzero(usable)[0]
        if row_idx.size == 0:
            continue
        sampled = bilinear_rows(tile, lat_centers[row_idx], lon_centers)
        current = grid[row_idx, :]
        take = np.isnan(current)
        current[take] = sampled[take]
        grid[row_idx, :] = current
        del pending

    finite = np.isfinite(grid)
    print(
        f"grid {rows}x{cols}: {finite.sum()} finite cells "
        f"({finite.mean() * 100:.2f}%), elev {np.nanmin(grid):.1f}..{np.nanmax(grid):.1f} m"
    )

    decimeters = np.where(finite, np.rint(grid * 10.0), NODATA_OUT)
    if decimeters[finite].max() > 32767 or decimeters[finite].min() <= NODATA_OUT:
        raise SystemExit("elevation exceeds int16 decimeter range")
    packed = decimeters.astype("<i2")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    bin_path = args.output_dir / "delaware_valley_1as_v1.bin"
    packed.tofile(bin_path)
    sha256 = hashlib.sha256(bin_path.read_bytes()).hexdigest()
    gz_path = bin_path.with_suffix(".bin.gz")
    with open(bin_path, "rb") as src, gzip.open(gz_path, "wb", compresslevel=9) as dst:
        while chunk := src.read(1 << 20):
            dst.write(chunk)

    validation = None
    if args.validate_profiles and args.validate_profiles.exists():
        payload = json.loads(args.validate_profiles.read_text())
        diffs = []
        skipped = 0
        for road in payload.get("roads", ()):
            for point in road.get("points", ()):
                lat, lon, ref = float(point["lat"]), float(point["lon"]), float(point["elev_m"])
                i = int((args.max_lat - lat) / STEP_DEG)
                j = int((lon - args.min_lon) / STEP_DEG)
                if not (0 <= i < rows and 0 <= j < cols) or not finite[i, j]:
                    skipped += 1
                    continue
                diffs.append(grid[i, j] - ref)
        diffs_arr = np.array(diffs)
        validation = {
            "reference": str(args.validate_profiles),
            "points_compared": int(diffs_arr.size),
            "points_skipped": int(skipped),
            "rmse_m": float(np.sqrt(np.mean(diffs_arr**2))) if diffs_arr.size else None,
            "mean_abs_m": float(np.mean(np.abs(diffs_arr))) if diffs_arr.size else None,
            "max_abs_m": float(np.max(np.abs(diffs_arr))) if diffs_arr.size else None,
        }
        print("validation vs canon profile bundle:", json.dumps(validation, indent=2))

    meta = {
        "format": GRID_FORMAT,
        "source_version": SOURCE_VERSION,
        "dem_source": "USGS 3DEP 1/3 arc-second GeoTIFF (public domain), local canon-compiler tiles",
        "source_tiles": [
            {
                "name": tile.path.name,
                "bytes": tile.path.stat().st_size,
                "raster_type": tile.raster_type,
                "pixel_scale_deg": tile.scale_deg,
            }
            for tile in tiles
        ],
        "method": "bilinear resample of 1/3as source at 1as target cell centers; any nodata/out-of-bounds neighbor fails closed",
        "registration": "cell centers; row 0 north; row-major; little-endian int16 decimeters",
        "nodata": NODATA_OUT,
        "units": "decimeters",
        "step_deg": STEP_DEG,
        "rows": rows,
        "cols": cols,
        "min_lat": args.min_lat,
        "max_lat": args.max_lat,
        "min_lon": args.min_lon,
        "max_lon": args.max_lon,
        "bin_sha256": sha256,
        "bin_bytes": bin_path.stat().st_size,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "tools/dem/build_delaware_valley_grid.py",
        "validation": validation,
    }
    meta_path = args.output_dir / "delaware_valley_1as_v1.meta.json"
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"wrote {bin_path} ({bin_path.stat().st_size / 1e6:.1f} MB)")
    print(f"wrote {gz_path} ({gz_path.stat().st_size / 1e6:.1f} MB)")
    print(f"wrote {meta_path}")


if __name__ == "__main__":
    sys.exit(main())
