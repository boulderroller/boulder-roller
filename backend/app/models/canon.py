"""Immutable runtime view of a ratified climb-canon row."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Tuple
from uuid import UUID

from shapely.geometry import LineString, MultiPolygon


@dataclass(frozen=True)
class CanonClimb:
    """Geometry and profile authority consumed by the D11 traversal engine."""

    registry_id: UUID
    canon_id: UUID
    version: int
    display_name: str
    route_name: Optional[str]
    centerline: LineString
    corridor: MultiPolygon
    gate_start: LineString
    gate_end: LineString
    canonical_profile: Tuple[Mapping[str, float], ...]
    length_m: float
    vert_m: float
    avg_gradient_pct: float
    compiler_version: str
    profile_hash_algorithm: str
    profile_hash: str
    odbl_source: str
    corridor_tile_ids: Tuple[str, ...]
    candidate_fingerprint: str = ""
    registry_snapshot_digest: str = ""
    provenance: Mapping[str, Any] = field(default_factory=dict)
