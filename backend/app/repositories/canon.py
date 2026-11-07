"""Private service-role access to ratified climb-canon geometry."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Sequence
from uuid import UUID

from shapely import from_geojson, wkb, wkt
from shapely.geometry import LineString, MultiPolygon, Polygon, shape

from ..models.canon import CanonClimb
from ..services.canon_commitment import canonical_profile_hash_hex
from ..utils.postgrest_paging import PageCursor, order_by
from .base import BaseRepository


_QUERY_BATCH_SIZE = 500
# Requested window. The pinned client returns 999 rows for it; a PageCursor
# ends each read on a short page and bounds it (postgrest_paging).
_QUERY_PAGE_SIZE = 1000
_PROFILE_METRIC_TOLERANCE = 0.02
_CANON_COLUMNS = ",".join(
    (
        "id",
        "canon_id",
        "version",
        "status",
        "candidate_fingerprint",
        "display_name",
        "route_name",
        "direction",
        "centerline_geom",
        "corridor_geom",
        "gate_start_line",
        "gate_end_line",
        "canonical_profile",
        "length_m",
        "vert_m",
        "avg_gradient_pct",
        "compiler_version",
        "provenance",
        "odbl_source",
    )
)


class CanonRegistryError(RuntimeError):
    """Ratified registry state is malformed or internally ambiguous."""


class CanonRegistryChanged(CanonRegistryError):
    """The registry moved between reads; matching again reads a settled state."""


def _batches(values: Sequence[str]) -> Iterable[Sequence[str]]:
    for offset in range(0, len(values), _QUERY_BATCH_SIZE):
        yield values[offset : offset + _QUERY_BATCH_SIZE]


def _response_rows(response: Any, *, operation: str) -> List[Mapping[str, Any]]:
    rows = getattr(response, "data", None)
    if rows is None:
        raise CanonRegistryError(f"{operation} returned no data payload")
    if not isinstance(rows, list):
        raise CanonRegistryError(f"{operation} returned a non-list data payload")
    if not all(isinstance(row, Mapping) for row in rows):
        raise CanonRegistryError(f"{operation} returned a malformed row")
    return rows


def _parse_geometry(value: Any, *, field_name: str):
    try:
        if isinstance(value, Mapping):
            try:
                return from_geojson(json.dumps(dict(value)))
            except Exception:
                return shape(value)
        if isinstance(value, (bytes, bytearray, memoryview)):
            return wkb.loads(bytes(value))
        if not isinstance(value, str) or not value.strip():
            raise ValueError("missing geometry")
        encoded = value.strip()
        if encoded.startswith("{"):
            try:
                return from_geojson(encoded)
            except Exception:
                return shape(json.loads(encoded))
        if encoded.upper().startswith("SRID="):
            encoded = encoded.split(";", 1)[1]
        if re.fullmatch(r"[0-9a-fA-F]+", encoded) and len(encoded) % 2 == 0:
            return wkb.loads(bytes.fromhex(encoded))
        return wkt.loads(encoded)
    except Exception as exc:
        raise CanonRegistryError(f"invalid {field_name} geometry") from exc


def _line(value: Any, *, field_name: str) -> LineString:
    geometry = _parse_geometry(value, field_name=field_name)
    if not isinstance(geometry, LineString) or geometry.is_empty or not geometry.is_valid:
        raise CanonRegistryError(f"invalid {field_name} geometry")
    if len(geometry.coords) < 2:
        raise CanonRegistryError(f"invalid {field_name} geometry")
    return geometry


def _corridor(value: Any) -> MultiPolygon:
    geometry = _parse_geometry(value, field_name="corridor_geom")
    if isinstance(geometry, Polygon):
        geometry = MultiPolygon([geometry])
    if not isinstance(geometry, MultiPolygon) or geometry.is_empty or not geometry.is_valid:
        raise CanonRegistryError("invalid corridor_geom geometry")
    return geometry


def _number(value: Any, *, field_name: str, minimum: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise CanonRegistryError(f"invalid {field_name}") from exc
    if not math.isfinite(number) or number < minimum:
        raise CanonRegistryError(f"invalid {field_name}")
    return number


def _profile(value: Any) -> tuple:
    if not isinstance(value, list) or len(value) < 2:
        raise CanonRegistryError("invalid canonical profile")
    normalized: List[Dict[str, float]] = []
    previous_distance: Any = None
    for point in value:
        if not isinstance(point, Mapping):
            raise CanonRegistryError("invalid canonical profile")
        distance = _number(point.get("dist_m"), field_name="canonical profile distance")
        elevation = _number(
            point.get("elev_m"),
            field_name="canonical profile elevation",
            minimum=-1000.0,
        )
        if previous_distance is not None and distance < previous_distance:
            raise CanonRegistryError("canonical profile distances are not ordered")
        previous_distance = distance
        normalized.append({"dist_m": distance, "elev_m": elevation})
    if normalized[-1]["dist_m"] <= normalized[0]["dist_m"]:
        raise CanonRegistryError("canonical profile has no positive distance")
    return tuple(normalized)


def _profile_hash(provenance: Mapping[str, Any], profile: tuple) -> tuple:
    value = provenance.get("canonical_profile_hash")
    if not isinstance(value, Mapping):
        raise CanonRegistryError("missing canonical profile hash")
    algorithm = str(value.get("algorithm") or "")
    digest = str(value.get("value") or "").lower()
    if algorithm != "blake3_canonical_profile_v1" or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise CanonRegistryError("invalid canonical profile hash")
    if canonical_profile_hash_hex(profile) != digest:
        raise CanonRegistryError(
            "canonical profile hash does not match canonical profile"
        )
    return algorithm, digest


def _profile_metrics(profile: tuple) -> tuple:
    distance_m = float(profile[-1]["dist_m"] - profile[0]["dist_m"])
    vert_m = float(profile[-1]["elev_m"] - profile[0]["elev_m"])
    if distance_m <= 0 or vert_m < 0:
        raise CanonRegistryError("invalid ascending canonical profile metrics")
    avg_gradient_pct = (vert_m / distance_m) * 100.0
    return distance_m, vert_m, avg_gradient_pct


def _validate_profile_metric(
    stored: float,
    derived: float,
    *,
    field_name: str,
) -> None:
    if abs(stored - derived) > _PROFILE_METRIC_TOLERANCE:
        raise CanonRegistryError(
            f"{field_name} disagrees with canonical profile"
        )


def _snapshot_digest(
    *,
    row: Mapping[str, Any],
    centerline: LineString,
    corridor: MultiPolygon,
    gate_start: LineString,
    gate_end: LineString,
    profile: tuple,
    distance_m: float,
    vert_m: float,
    avg_gradient_pct: float,
    cells: Sequence[Mapping[str, Any]],
) -> str:
    payload = {
        "registry_id": str(row.get("id")),
        "canon_id": str(row.get("canon_id")),
        "version": int(row.get("version")),
        "candidate_fingerprint": str(row.get("candidate_fingerprint")),
        "centerline_wkb": centerline.wkb_hex,
        "corridor_wkb": corridor.wkb_hex,
        "gate_start_wkb": gate_start.wkb_hex,
        "gate_end_wkb": gate_end.wkb_hex,
        "canonical_profile": list(profile),
        "canonical_metrics": {
            "length_m": distance_m,
            "vert_m": vert_m,
            "avg_gradient_pct": avg_gradient_pct,
        },
        "compiler_version": str(row.get("compiler_version")),
        "profile_hash": row.get("provenance", {}).get("canonical_profile_hash"),
        "cells": sorted(
            (
                int(cell.get("h3_resolution", 0)),
                str(cell.get("tile_id") or ""),
                str(cell.get("coverage_role") or ""),
            )
            for cell in cells
        ),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class CanonRepository(BaseRepository):
    """Load the exact ratified rows touched by a ride's res-10 cells."""

    async def load_ratified_for_tiles(self, tile_ids: Sequence[str]) -> List[CanonClimb]:
        unique_tiles = sorted({str(tile_id) for tile_id in tile_ids if tile_id})
        if not unique_tiles:
            return []

        cell_rows = await self._load_cells_by_tiles(unique_tiles)

        cells_by_climb: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
        for cell in cell_rows:
            registry_id = str(cell.get("canon_climb_id") or "")
            tile_id = str(cell.get("tile_id") or "")
            if not registry_id or not tile_id or int(cell.get("h3_resolution", 0)) != 10:
                raise CanonRegistryError("malformed canon corridor-cell row")
            cells_by_climb[registry_id].append(cell)
        registry_ids = sorted(cells_by_climb)
        if not registry_ids:
            return []

        prefilter_canon_rows: List[Mapping[str, Any]] = []
        for batch in _batches(registry_ids):
            response = await self._run(
                lambda batch=batch: self._client.table("canon_climbs")
                .select("id,canon_id,status")
                .in_("status", ["ratified", "retired"])
                .in_("id", list(batch))
                .execute(),
                operation="canon_ratified_rows",
            )
            prefilter_canon_rows.extend(
                _response_rows(response, operation="ratified canon query")
            )

        # Publication can retire a prefetched row between these HTTP reads.
        # Its retained identity still locates the family's current geometry.
        # Rollback can remove a prefetched successor: retry, never silently
        # treat that lost lookup as an absence of climbs on this ride.
        missing_ids = sorted(set(registry_ids) - {str(row.get("id")) for row in prefilter_canon_rows})
        if missing_ids:
            # Candidate-owned cells are excluded by the status filter above.
            # Read only identity to distinguish them from a deleted revision.
            existing_ids = await self._load_existing_registry_ids(missing_ids)
            if set(missing_ids) - existing_ids:
                raise CanonRegistryChanged("registry changed during cell lookup; retry matching")
        canon_ids = sorted(
            {str(row.get("canon_id") or "") for row in prefilter_canon_rows}
        )
        if not prefilter_canon_rows:
            return []
        if "" in canon_ids:
            raise CanonRegistryError("ratified canon row is missing canon_id")
        canon_rows = await self._load_ratified_rows_by_canon_ids(canon_ids)
        active_counts: Dict[str, int] = defaultdict(int)
        for row in canon_rows:
            active_counts[str(row.get("canon_id") or "")] += 1
        if any(count > 1 for count in active_counts.values()):
            raise CanonRegistryError("multiple ratified versions for canon_id")
        if any(not active_counts.get(str(row.get("canon_id")))
               for row in prefilter_canon_rows if row.get("status") == "ratified"):
            raise CanonRegistryChanged("current registry row disappeared; retry matching")

        full_cell_rows = await self._load_cells_by_climb_ids(
            [str(row.get("id")) for row in canon_rows if row.get("id")]
        )
        full_cells_by_climb: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
        for cell in full_cell_rows:
            registry_id = str(cell.get("canon_climb_id") or "")
            if not registry_id:
                raise CanonRegistryError("malformed full canon corridor-cell row")
            full_cells_by_climb[registry_id].append(cell)

        climbs: List[CanonClimb] = []
        active_by_canon: Dict[UUID, UUID] = {}
        for row in canon_rows:
            climb = self._build_climb(
                row,
                full_cells_by_climb.get(str(row.get("id")), []),
            )
            previous_registry_id = active_by_canon.get(climb.canon_id)
            if previous_registry_id is not None and previous_registry_id != climb.registry_id:
                raise CanonRegistryError(
                    f"multiple ratified versions for canon_id {climb.canon_id}"
                )
            active_by_canon[climb.canon_id] = climb.registry_id
            climbs.append(climb)
        climbs.sort(key=lambda climb: (str(climb.canon_id), climb.version))
        return climbs

    async def _load_existing_registry_ids(self, registry_ids: Sequence[str]) -> set[str]:
        existing: set[str] = set()
        for batch in _batches(registry_ids):
            response = await self._run(
                lambda batch=batch: self._client.table("canon_climbs")
                .select("id")
                .in_("id", list(batch))
                .execute(),
                operation="canon_existing_registry_ids",
            )
            existing.update(str(row.get("id")) for row in
                            _response_rows(response, operation="registry identity query"))
        return existing

    async def _load_ratified_rows_by_canon_ids(
        self,
        canon_ids: Sequence[str],
    ) -> List[Mapping[str, Any]]:
        rows: List[Mapping[str, Any]] = []
        for batch in _batches(canon_ids):
            cursor = PageCursor(_QUERY_PAGE_SIZE)
            while True:
                def read_page(batch=batch, offset=cursor.offset):
                    # One chain keeps the ratified filter visible to
                    # scripts/check_geographic_reads.py.
                    ratified = (
                        self._client.table("canon_climbs")
                        .select(_CANON_COLUMNS)
                        .eq("status", "ratified")
                        .in_("canon_id", list(batch))
                    )
                    return (
                        order_by(ratified, "canon_id", "version")
                        .range(offset, offset + _QUERY_PAGE_SIZE - 1)
                        .execute()
                    )

                response = await self._run(read_page, operation="canon_active_versions")
                page = _response_rows(
                    response,
                    operation="active canon-version query",
                )
                rows.extend(page)
                if not cursor.advance(page):
                    break
        return rows

    async def _load_cells_by_tiles(
        self,
        tile_ids: Sequence[str],
    ) -> List[Mapping[str, Any]]:
        rows: List[Mapping[str, Any]] = []
        for batch in _batches(tile_ids):
            cursor = PageCursor(_QUERY_PAGE_SIZE)
            while True:
                response = await self._run(
                    lambda batch=batch, offset=cursor.offset: order_by(
                        self._client.table("canon_corridor_cells")
                        .select("canon_climb_id,h3_resolution,tile_id,coverage_role")
                        .eq("h3_resolution", 10)
                        .in_("tile_id", list(batch)),
                        "canon_climb_id",
                        "tile_id",
                        "coverage_role",
                    )
                    .range(offset, offset + _QUERY_PAGE_SIZE - 1)
                    .execute(),
                    operation="canon_prefilter_cells",
                )
                page = _response_rows(
                    response,
                    operation="canon corridor-cell prefilter query",
                )
                rows.extend(page)
                if not cursor.advance(page):
                    break
        return rows

    async def _load_cells_by_climb_ids(
        self,
        registry_ids: Sequence[str],
    ) -> List[Mapping[str, Any]]:
        unique_ids = sorted({registry_id for registry_id in registry_ids if registry_id})
        rows: List[Mapping[str, Any]] = []
        for batch in _batches(unique_ids):
            cursor = PageCursor(_QUERY_PAGE_SIZE)
            while True:
                response = await self._run(
                    lambda batch=batch, offset=cursor.offset: order_by(
                        self._client.table("canon_corridor_cells")
                        .select("canon_climb_id,h3_resolution,tile_id,coverage_role")
                        .eq("h3_resolution", 10)
                        .in_("canon_climb_id", list(batch)),
                        "canon_climb_id",
                        "tile_id",
                        "coverage_role",
                    )
                    .range(offset, offset + _QUERY_PAGE_SIZE - 1)
                    .execute(),
                    operation="canon_full_corridor_cells",
                )
                page = _response_rows(
                    response,
                    operation="full canon corridor-cell query",
                )
                rows.extend(page)
                if not cursor.advance(page):
                    break
        return rows

    @staticmethod
    def _build_climb(
        row: Mapping[str, Any],
        cells: Sequence[Mapping[str, Any]],
    ) -> CanonClimb:
        if row.get("status") != "ratified":
            raise CanonRegistryError("non-ratified row returned by canon query")
        if row.get("direction") not in (None, "ascending"):
            raise CanonRegistryError("unsupported canon direction")
        try:
            registry_id = UUID(str(row.get("id")))
            canon_id = UUID(str(row.get("canon_id")))
            version = int(row.get("version"))
        except (TypeError, ValueError, AttributeError) as exc:
            raise CanonRegistryError("invalid canon identity") from exc
        if version < 1:
            raise CanonRegistryError("invalid canon version")
        fingerprint = str(row.get("candidate_fingerprint") or "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            raise CanonRegistryError("invalid candidate fingerprint")
        display_name = str(row.get("display_name") or "").strip()
        if not display_name:
            raise CanonRegistryError("missing canon display name")
        route_name_raw = row.get("route_name")
        route_name = str(route_name_raw).strip() if route_name_raw else None
        centerline = _line(row.get("centerline_geom"), field_name="centerline_geom")
        corridor = _corridor(row.get("corridor_geom"))
        gate_start = _line(row.get("gate_start_line"), field_name="gate_start_line")
        gate_end = _line(row.get("gate_end_line"), field_name="gate_end_line")
        profile = _profile(row.get("canonical_profile"))
        provenance = row.get("provenance")
        if not isinstance(provenance, Mapping):
            raise CanonRegistryError("invalid canon provenance")
        hash_algorithm, profile_hash = _profile_hash(provenance, profile)
        profile_distance_m, profile_vert_m, profile_gradient_pct = _profile_metrics(
            profile
        )
        stored_distance_m = _number(
            row.get("length_m"),
            field_name="length_m",
            minimum=0.000001,
        )
        stored_vert_m = _number(row.get("vert_m"), field_name="vert_m")
        stored_gradient_pct = _number(
            row.get("avg_gradient_pct"),
            field_name="avg_gradient_pct",
        )
        _validate_profile_metric(
            stored_distance_m,
            profile_distance_m,
            field_name="length_m",
        )
        _validate_profile_metric(
            stored_vert_m,
            profile_vert_m,
            field_name="vert_m",
        )
        _validate_profile_metric(
            stored_gradient_pct,
            profile_gradient_pct,
            field_name="avg_gradient_pct",
        )
        compiler_version = str(row.get("compiler_version") or "").strip()
        if not compiler_version:
            raise CanonRegistryError("missing compiler version")
        odbl_source = str(row.get("odbl_source") or "").strip()
        if not odbl_source:
            raise CanonRegistryError("missing ODbL source")
        corridor_tiles = tuple(
            sorted({str(cell.get("tile_id")) for cell in cells if cell.get("tile_id")})
        )
        if not corridor_tiles:
            raise CanonRegistryError("ratified canon has no corridor cells")
        digest = _snapshot_digest(
            row=row,
            centerline=centerline,
            corridor=corridor,
            gate_start=gate_start,
            gate_end=gate_end,
            profile=profile,
            distance_m=profile_distance_m,
            vert_m=profile_vert_m,
            avg_gradient_pct=profile_gradient_pct,
            cells=cells,
        )
        return CanonClimb(
            registry_id=registry_id,
            canon_id=canon_id,
            version=version,
            display_name=display_name,
            route_name=route_name,
            centerline=centerline,
            corridor=corridor,
            gate_start=gate_start,
            gate_end=gate_end,
            canonical_profile=profile,
            length_m=profile_distance_m,
            vert_m=profile_vert_m,
            avg_gradient_pct=profile_gradient_pct,
            compiler_version=compiler_version,
            profile_hash_algorithm=hash_algorithm,
            profile_hash=profile_hash,
            odbl_source=odbl_source,
            corridor_tile_ids=corridor_tiles,
            candidate_fingerprint=fingerprint,
            registry_snapshot_digest=digest,
            provenance=dict(provenance),
        )
