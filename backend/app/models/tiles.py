"""
Tile-based models for H3 hexagonal tile projection.

These models represent the database tables for storing ride data projected onto
H3 hexagonal tiles. This replaces the previous polyline segment approach with
a more flexible, privacy-preserving tile-based system.

H3 Resolution Guide:
- Resolution 10: ~15m hex edge, ~50m² area - high detail for urban areas
- Resolution 11: ~8m hex edge, ~25m² area - very high detail
- Resolution 9: ~30m hex edge, ~200m² area - lower detail, more privacy

For road cycling, we use resolution 10-11 to balance precision and privacy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import UUID


@dataclass
class ActivityTileSample:
    """
    Single tile sample from a ride activity.

    Represents a data point at a specific time during a ride, projected onto
    an H3 tile. Replaces the previous GPS point-to-segment matching approach.

    Table: activity_tile_samples
    """

    id: UUID
    activity_id: UUID  # Foreign key to rides.id
    t: int  # Elapsed time in seconds from ride start (rounded to integer)
    tile_id: str  # H3 hexagonal tile index (15-character string)

    # Optional sensor data at this sample point
    elevation_m: Optional[float] = None
    power_w: Optional[int] = None
    hr_bpm: Optional[int] = None  # Heart rate
    speed_mps: Optional[float] = None  # Speed in meters per second

    created_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "id": str(self.id),
            "activity_id": str(self.activity_id),
            "t": self.t,
            "tile_id": self.tile_id,
            "elevation_m": self.elevation_m,
            "power_w": self.power_w,
            "hr_bpm": self.hr_bpm,
            "speed_mps": self.speed_mps,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass
class WalletTileHistory:
    """
    Tracks which H3 tiles a wallet has visited.

    Used for:
    - Tile attestations (proving you've visited a location)
    - Privacy zones (tiles a user has visited can be private)
    - Territorial claims (gamification - who has visited the most tiles)
    - Anti-spoofing (tiles should be geographically connected over time)

    Table: wallet_tile_history
    """

    wallet: str  # Solana wallet address
    tile_id: str  # H3 hexagonal tile index
    first_visited_at: datetime  # When this wallet first visited this tile

    # Optional tracking fields
    visit_count: int = 1  # Number of times this tile was visited
    last_visited_at: Optional[datetime] = None

    # Primary key is (wallet, tile_id)

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "wallet": self.wallet,
            "tile_id": self.tile_id,
            "first_visited_at": self.first_visited_at.isoformat(),
            "visit_count": self.visit_count,
            "last_visited_at": self.last_visited_at.isoformat() if self.last_visited_at else None,
        }


# Type hints for Supabase table operations
ActivityTileSampleDict = dict  # Represents a row from activity_tile_samples table
WalletTileHistoryDict = dict  # Represents a row from wallet_tile_history table
