"""
Pattern models for the tile-based attestation architecture.

These models represent detected effort patterns from ride activities.
Patterns are detected automatically and CAL is tributed to vaults crossed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID


class PatternType(str, Enum):
    """Types of patterns that can be detected."""
    CLIMB = "CLIMB"
    STEADY = "STEADY"
    EXPLORATION = "EXPLORATION"


@dataclass
class ClimbPattern:
    """
    A detected climb effort within an Arena.

    Represents sustained vertical gain with minimal drops,
    detected from elevation data in tile samples.

    Table: patterns_climb
    """
    id: UUID
    activity_id: UUID
    wallet: str
    arena_id: Optional[UUID]  # NULL for World Arena

    # Core metrics
    vert_m: float  # Total vertical gain in meters
    time_s: int    # Duration in seconds

    # Optional power/HR metrics
    avg_power_w: Optional[float] = None
    w_per_kg: Optional[float] = None
    avg_hr: Optional[int] = None

    # Time offsets within the activity
    start_offset_s: int = 0
    end_offset_s: int = 0

    # Road attribution (from OSM tile features)
    road_name: Optional[str] = None  # Primary road name (e.g., "Manayunk Wall")
    road_grade: Optional[float] = None  # Road grade from OSM data
    road_coverage_pct: Optional[float] = None  # % of climb on primary road
    attribution_summary: Optional[str] = None  # e.g., "85% on Manayunk Wall (8.5% grade)"

    # Tile sequence for reattribution
    tile_ids: Optional[list] = None  # H3 tile IDs for this climb segment

    # Computed metrics from climb detection
    distance_m: Optional[float] = None  # Horizontal distance in meters
    avg_gradient_pct: Optional[float] = None  # Average gradient percentage
    signature_hex: Optional[str] = None  # 64-byte v1 signature for vault matching
    signature_v2_hex: Optional[str] = None  # 64-byte DCT v2 signature

    # GPS coordinates at effort start/end (for GPS-gated vault matching)
    start_lat: Optional[float] = None
    start_lon: Optional[float] = None
    end_lat: Optional[float] = None
    end_lon: Optional[float] = None

    # Significance scoring (from GPD terrain bootstrap)
    persistence_m: Optional[float] = None  # Topological persistence in meters
    significance_g: Optional[float] = None  # Conservative GPD score 0-1
    significance_percentile: Optional[float] = None  # Local percentile (0-100)
    significance_return_period: Optional[float] = None  # 1-in-N climbs
    significance_confidence_tier: Optional[int] = None  # 0-3
    significance_bootstrapped: Optional[bool] = None  # True = DEM-fitted cell
    significance_cell_h3: Optional[str] = None  # H3 cell used for scoring

    # Vault match fields (populated by vault matching in ride_processor)
    vault_climb_id: Optional[str] = None  # UUID of matched canonical OSM climb
    vault_climb_name: Optional[str] = None  # Name of matched climb (e.g., "Manayunk Wall")
    vault_climb_slug: Optional[str] = None  # URL-friendly slug
    vault_match_similarity: Optional[float] = None  # Similarity score (0.0-1.0)
    is_strong_match: Optional[bool] = None  # True if above vault's threshold
    indexed_vault_id: Optional[int] = None  # ID of matched on-chain vault
    indexed_vault_name: Optional[str] = None  # Name of matched on-chain vault

    # Abstention and decision trace (per TRUTH_CONTRACT_V1 / ABSTENTION_POLICY)
    economic_eligible: bool = True  # False = abstained from economic actions
    abstention_reasons: Optional[list] = None  # e.g. ["MATCH:probable_without_gps"]
    match_trace: Optional[dict] = None  # Machine-readable match evidence (JSONB)
    detector_version: Optional[str] = None  # "persistence", "momentum"

    created_at: Optional[datetime] = None

    @property
    def pattern_type(self) -> PatternType:
        return PatternType.CLIMB

    @property
    def vam(self) -> Optional[float]:
        """Velocità Ascensionale Media (VAM) - meters/hour of climbing."""
        if self.time_s > 0:
            return (self.vert_m / self.time_s) * 3600
        return None

    # Aliases for compatibility with services/patterns/climb.py ClimbPattern
    @property
    def start_time_offset_s(self) -> int:
        """Alias for start_offset_s (compatibility with detector ClimbPattern)."""
        return self.start_offset_s

    @property
    def end_time_offset_s(self) -> int:
        """Alias for end_offset_s (compatibility with detector ClimbPattern)."""
        return self.end_offset_s

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "activity_id": str(self.activity_id),
            "wallet": self.wallet,
            "arena_id": str(self.arena_id) if self.arena_id else None,
            "pattern_type": self.pattern_type.value,
            "vert_m": self.vert_m,
            "time_s": self.time_s,
            "avg_power_w": self.avg_power_w,
            "w_per_kg": self.w_per_kg,
            "avg_hr": self.avg_hr,
            "vam": self.vam,
            "start_offset_s": self.start_offset_s,
            "end_offset_s": self.end_offset_s,
            "road_name": self.road_name,
            "road_grade": self.road_grade,
            "road_coverage_pct": self.road_coverage_pct,
            "attribution_summary": self.attribution_summary,
            "tile_ids": self.tile_ids,
            "distance_m": self.distance_m,
            "avg_gradient_pct": self.avg_gradient_pct,
            "signature_hex": self.signature_hex,
            "signature_v2_hex": self.signature_v2_hex,
            "start_lat": self.start_lat,
            "start_lon": self.start_lon,
            "end_lat": self.end_lat,
            "end_lon": self.end_lon,
            "persistence_m": self.persistence_m,
            "significance_g": self.significance_g,
            "significance_percentile": self.significance_percentile,
            "significance_return_period": self.significance_return_period,
            "significance_confidence_tier": self.significance_confidence_tier,
            "significance_bootstrapped": self.significance_bootstrapped,
            "significance_cell_h3": self.significance_cell_h3,
            "vault_climb_id": self.vault_climb_id,
            "vault_climb_name": self.vault_climb_name,
            "vault_climb_slug": self.vault_climb_slug,
            "vault_match_similarity": self.vault_match_similarity,
            "is_strong_match": self.is_strong_match,
            "indexed_vault_id": self.indexed_vault_id,
            "indexed_vault_name": self.indexed_vault_name,
            "economic_eligible": self.economic_eligible,
            "abstention_reasons": self.abstention_reasons,
            "match_trace": self.match_trace,
            "detector_version": self.detector_version,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass
class SteadyPattern:
    """
    A detected steady aerobic effort.

    Represents sustained effort in Z2-Z3 intensity band
    with low variability, detected from power or HR data.

    Table: patterns_steady
    """
    id: UUID
    activity_id: UUID
    wallet: str

    # Core metrics
    duration_s: int  # Duration in seconds

    # Power metrics
    avg_power_w: Optional[float] = None
    np_power_w: Optional[float] = None  # Normalized power

    # HR metrics
    avg_hr: Optional[int] = None

    # Intensity metrics
    intensity_index: Optional[float] = None  # Relative to FTP (0.0-1.0+)
    variability_index: Optional[float] = None  # VI = NP/AP

    # Time offsets within the activity
    start_offset_s: int = 0
    end_offset_s: int = 0

    created_at: Optional[datetime] = None

    @property
    def pattern_type(self) -> PatternType:
        return PatternType.STEADY

    @property
    def tss_estimate(self) -> Optional[float]:
        """Estimated Training Stress Score for this effort."""
        if self.intensity_index and self.duration_s:
            # TSS = (duration_s * IF^2) / 3600 * 100
            return (self.duration_s * (self.intensity_index ** 2)) / 36
        return None

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "activity_id": str(self.activity_id),
            "wallet": self.wallet,
            "pattern_type": self.pattern_type.value,
            "duration_s": self.duration_s,
            "avg_power_w": self.avg_power_w,
            "np_power_w": self.np_power_w,
            "avg_hr": self.avg_hr,
            "intensity_index": self.intensity_index,
            "variability_index": self.variability_index,
            "tss_estimate": self.tss_estimate,
            "start_offset_s": self.start_offset_s,
            "end_offset_s": self.end_offset_s,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass
class ExplorationPattern:
    """
    A detected exploration effort.

    Represents riding in new/unusual areas, detected by
    comparing activity tiles to historical tile visits.

    Table: patterns_exploration
    """
    id: UUID
    activity_id: UUID
    wallet: str

    # Core metrics
    new_tiles_wallet: int  # Tiles new to this wallet
    new_tiles_global: Optional[int] = None  # Tiles new to entire system

    # Optional metrics
    total_tiles: int = 0  # Total unique tiles in activity
    night_minutes: Optional[int] = None  # Minutes riding in "night" hours

    # Time offsets (usually full activity)
    start_offset_s: int = 0
    end_offset_s: int = 0

    created_at: Optional[datetime] = None

    @property
    def pattern_type(self) -> PatternType:
        return PatternType.EXPLORATION

    @property
    def exploration_ratio(self) -> float:
        """Ratio of new tiles to total tiles."""
        if self.total_tiles > 0:
            return self.new_tiles_wallet / self.total_tiles
        return 0.0

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "activity_id": str(self.activity_id),
            "wallet": self.wallet,
            "pattern_type": self.pattern_type.value,
            "new_tiles_wallet": self.new_tiles_wallet,
            "new_tiles_global": self.new_tiles_global,
            "total_tiles": self.total_tiles,
            "exploration_ratio": self.exploration_ratio,
            "night_minutes": self.night_minutes,
            "start_offset_s": self.start_offset_s,
            "end_offset_s": self.end_offset_s,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# Type aliases for database operations
PatternDict = dict
ClimbPatternDict = dict
SteadyPatternDict = dict
ExplorationPatternDict = dict
