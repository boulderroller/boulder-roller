"""
Climb Vault Service

Manages canonical climbs and matches user rides against them.

The vault contains verified climbs derived from OSM data (not user-generated segments).
Matching is route-agnostic: any path that produces a similar elevation signature counts.

Flow:
1. User ride → Detect climbs → Generate signature
2. Geographic filter: find vault climbs near user's tiles
3. Signature similarity: compare against candidates
4. Match found → Create attestation record for on-chain proof
"""

from __future__ import annotations

import logging

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple
from uuid import UUID

from app.services.patterns.climb import ClimbPattern
from app.services.patterns.climb_signature import ClimbSignature, ClimbSignatureGenerator
from app.services.sample_time import infer_sample_time_base, sample_in_time_window
from app.utils.postgrest_paging import order_by

logger = logging.getLogger(__name__)


@dataclass
class VaultClimb:
    """A canonical climb from the vault."""
    id: UUID
    name: str
    slug: Optional[str]
    region: Optional[str]
    country_code: Optional[str]

    # Bounds
    bounds_min_lat: float
    bounds_max_lat: float
    bounds_min_lon: float
    bounds_max_lon: float

    # Tile sequence (canonical route representation)
    h3_tile_ids: Optional[List[str]] = None

    # Elevation profile
    total_vert_m: float = 0
    avg_gradient_pct: float = 0
    distance_m: float = 0
    base_elevation_m: Optional[float] = None
    peak_elevation_m: Optional[float] = None

    # Signature
    signature_hex: str = ""
    signature_tolerance: float = 0.55

    # Classification
    uci_category: Optional[str] = None
    difficulty_score: Optional[float] = None

    @property
    def signature(self) -> ClimbSignature:
        """Parse signature from hex string."""
        sig_bytes = bytes.fromhex(self.signature_hex)
        # Decode metrics from signature bytes
        import struct
        vert = struct.unpack('>f', sig_bytes[32:36])[0]
        grad = struct.unpack('>f', sig_bytes[36:40])[0]
        dist = struct.unpack('>f', sig_bytes[40:44])[0]
        dur = struct.unpack('>I', sig_bytes[44:48])[0]
        return ClimbSignature(
            signature=sig_bytes,
            vert_m=vert,
            avg_gradient_pct=grad,
            distance_m=dist,
            duration_s=dur,
        )



@dataclass
class VaultMatch:
    """Result of matching a user climb against the vault."""
    vault_climb: VaultClimb
    similarity: float
    user_signature_hex: str

    @property
    def is_strong_match(self) -> bool:
        """Check if similarity exceeds the vault climb's threshold."""
        return self.similarity >= self.vault_climb.signature_tolerance


@dataclass
class ClimbAttestation:
    """Record of a matched climb ready for on-chain proof."""
    id: Optional[UUID]
    user_id: UUID
    ride_id: UUID
    vault_climb_id: UUID

    # Match quality
    signature_similarity: float

    # Performance
    vert_m: float
    time_s: int
    vam: Optional[float]
    avg_power_w: Optional[float]

    # Signatures
    user_signature_hex: str

    # Tiles
    tile_ids: List[str]

    # Timestamps
    climb_started_at: datetime
    climb_completed_at: datetime

    # On-chain status
    attestation_status: str = "pending"
    solana_tx_signature: Optional[str] = None


class ClimbVaultService:
    """
    Service for managing the climb vault and matching user rides.
    """

    def __init__(self, supabase_client):
        """
        Initialize with a Supabase client.

        Args:
            supabase_client: Initialized Supabase client
        """
        self.client = supabase_client
        self._signature_gen = ClimbSignatureGenerator()

    # =========================================================================
    # VAULT QUERIES (using Supabase client)
    # =========================================================================

    async def get_vault_climb(self, climb_id: UUID) -> Optional[VaultClimb]:
        """Get a single vault climb by ID."""
        response = self.client.from_("climb_vault") \
            .select("*") \
            .eq("id", str(climb_id)) \
            .eq("active", True) \
            .execute()

        if not response.data:
            return None
        return self._row_to_vault_climb(response.data[0])

    async def find_climbs_in_bounds(
        self,
        min_lat: float,
        max_lat: float,
        min_lon: float,
        max_lon: float,
        limit: int = 50,
    ) -> List[VaultClimb]:
        """
        Find vault climbs whose bounds overlap with the given area.

        Used as first-pass filter before signature matching.
        """
        logger.info(f"[VaultQuery] Searching for vault climbs overlapping: lat={min_lat:.4f}-{max_lat:.4f}, lon={min_lon:.4f}-{max_lon:.4f}")

        # Supabase query for bounds overlap
        # Vault climb overlaps if: vault.max_lat >= user.min_lat AND vault.min_lat <= user.max_lat
        # AND vault.max_lon >= user.min_lon AND vault.min_lon <= user.max_lon
        query = self.client.from_("climb_vault") \
            .select("*") \
            .eq("active", True) \
            .gte("bounds_max_lat", min_lat) \
            .lte("bounds_min_lat", max_lat) \
            .gte("bounds_max_lon", min_lon) \
            .lte("bounds_min_lon", max_lon)
        response = order_by(query, "total_vert_m.desc", "id").limit(limit).execute()

        climbs = [self._row_to_vault_climb(row) for row in (response.data or [])]
        climbs.sort(key=lambda c: (-c.total_vert_m, str(c.id)))
        logger.info(f"[VaultQuery] Query result: {len(climbs)} climbs{': ' + str([c.name for c in climbs]) if climbs else ''}")
        return climbs

    async def find_climbs_by_tiles(
        self,
        tile_ids: List[str],
        limit: int = 20,
    ) -> List[VaultClimb]:
        """
        Find vault climbs that contain any of the given H3 tiles.

        More precise than bounds-based search but requires h3_tile_ids to be populated.
        """
        # Supabase array overlap using PostgREST 'ov' operator
        # Format: {val1,val2,val3} for array overlap
        tile_array = "{" + ",".join(tile_ids) + "}"
        query = self.client.from_("climb_vault") \
            .select("*") \
            .eq("active", True) \
            .filter("h3_tile_ids", "ov", tile_array)
        response = order_by(query, "total_vert_m.desc", "id").limit(limit).execute()

        climbs = [self._row_to_vault_climb(row) for row in (response.data or [])]
        climbs.sort(key=lambda c: (-c.total_vert_m, str(c.id)))
        return climbs

    # =========================================================================
    # MATCHING
    # =========================================================================

    async def match_climb_pattern(
        self,
        pattern: ClimbPattern,
        tile_samples: List[dict],
        min_similarity: float = 0.5,
    ) -> List[VaultMatch]:
        """
        Match a detected climb pattern against the vault.

        Matching strategy:
        1. If user pattern has tile_ids, try tile overlap first (most precise)
        2. Fallback to bounds overlap for geographic filtering
        3. Use signature similarity as final scoring

        Args:
            pattern: Detected ClimbPattern with signature
            tile_samples: Original tile samples (for bounds calculation)
            min_similarity: Minimum similarity threshold (0.0-1.0)

        Returns:
            List of VaultMatch objects, sorted by similarity descending
        """
        if not pattern.signature_hex:
            # Generate signature if not present
            sig = self._generate_signature_from_pattern(pattern, tile_samples)
            if sig:
                pattern.signature_hex = sig.hex
            else:
                return []

        candidates = []
        user_tiles = set(pattern.tile_ids or [])

        # Strategy 1: Tile overlap (most precise)
        if user_tiles:
            candidates = await self.find_climbs_by_tiles(list(user_tiles), limit=20)
            logger.info(f"[VaultMatch] Tile overlap search: {len(candidates)} candidates from {len(user_tiles)} user tiles")

            # Log tile overlap details for candidates
            for vc in candidates:
                if vc.h3_tile_ids:
                    vault_tiles = set(vc.h3_tile_ids)
                    overlap = user_tiles & vault_tiles
                    overlap_pct = len(overlap) / len(vault_tiles) * 100 if vault_tiles else 0
                    logger.info(f"[VaultMatch] '{vc.name}': {len(overlap)}/{len(vault_tiles)} tiles overlap ({overlap_pct:.0f}%)")

        # Strategy 2: Bounds overlap (fallback)
        if not candidates:
            bounds = self._get_bounds_from_samples(tile_samples, pattern)
            if not bounds:
                logger.warning(f"[VaultMatch] No bounds from samples for climb {pattern.vert_m:.0f}m")
                return []

            min_lat, max_lat, min_lon, max_lon = bounds
            logger.info(f"[VaultMatch] Bounds search: lat={min_lat:.4f}-{max_lat:.4f}, lon={min_lon:.4f}-{max_lon:.4f}")

            candidates = await self.find_climbs_in_bounds(
                min_lat, max_lat, min_lon, max_lon, limit=50
            )
            logger.info(f"[VaultMatch] Found {len(candidates)} candidates in bounds")

        if not candidates:
            logger.info(f"[VaultMatch] No vault candidates found")
            return []

        # Build user signature for comparison
        user_sig = ClimbSignature(
            signature=bytes.fromhex(pattern.signature_hex),
            vert_m=pattern.vert_m,
            avg_gradient_pct=pattern.avg_gradient_pct or 0,
            distance_m=pattern.distance_m or 0,
            duration_s=pattern.time_s,
        )

        # Compare against each candidate
        matches = []
        for vault_climb in candidates:
            # Calculate signature similarity
            sig_similarity = user_sig.similarity(vault_climb.signature)

            # Calculate tile overlap boost (if tiles available)
            tile_boost = 0.0
            if user_tiles and vault_climb.h3_tile_ids:
                vault_tiles = set(vault_climb.h3_tile_ids)
                overlap = user_tiles & vault_tiles
                # Tile overlap gives up to 0.1 bonus
                tile_boost = (len(overlap) / len(vault_tiles)) * 0.1 if vault_tiles else 0

            # Combined similarity (signature is primary, tile overlap is bonus)
            combined_similarity = min(1.0, sig_similarity + tile_boost)

            logger.info(
                f"[VaultMatch] '{vault_climb.name}': sig={sig_similarity:.2f} + tile_boost={tile_boost:.2f} = {combined_similarity:.2f}"
            )

            if combined_similarity >= min_similarity:
                matches.append(VaultMatch(
                    vault_climb=vault_climb,
                    similarity=combined_similarity,
                    user_signature_hex=pattern.signature_hex,
                ))

        # Sort by similarity descending
        matches.sort(key=lambda m: (-m.similarity, str(m.vault_climb.id)))
        logger.info(f"[VaultMatch] {len(matches)} matches above threshold")
        return matches

    # =========================================================================
    # VAULT MANAGEMENT
    # =========================================================================

    async def create_vault_climb(
        self,
        name: str,
        bounds: Tuple[float, float, float, float],  # min_lat, max_lat, min_lon, max_lon
        total_vert_m: float,
        avg_gradient_pct: float,
        distance_m: float,
        signature_hex: str,
        **kwargs,
    ) -> VaultClimb:
        """
        Create a new canonical climb in the vault.

        This should typically be done via OSM import, not manually.
        """
        min_lat, max_lat, min_lon, max_lon = bounds

        # Generate slug from name
        slug = kwargs.get('slug') or self._slugify(name)

        # Calculate difficulty score
        difficulty = total_vert_m * (1 + avg_gradient_pct / 10)

        # Determine UCI category
        uci_cat = kwargs.get('uci_category') or self._compute_uci_category(
            total_vert_m, avg_gradient_pct, distance_m
        )

        query = """
            INSERT INTO climb_vault (
                name, slug, region, country_code,
                bounds_min_lat, bounds_max_lat, bounds_min_lon, bounds_max_lon,
                total_vert_m, avg_gradient_pct, distance_m,
                base_elevation_m, peak_elevation_m,
                signature_hex, signature_tolerance,
                uci_category, difficulty_score,
                source, h3_tile_ids
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19
            ) RETURNING *
        """
        row = await self.db.fetchrow(
            query,
            name, slug, kwargs.get('region'), kwargs.get('country_code'),
            min_lat, max_lat, min_lon, max_lon,
            total_vert_m, avg_gradient_pct, distance_m,
            kwargs.get('base_elevation_m'), kwargs.get('peak_elevation_m'),
            signature_hex, kwargs.get('signature_tolerance', 0.65),
            uci_cat, difficulty,
            kwargs.get('source', 'manual'), kwargs.get('h3_tile_ids'),
        )

        return self._row_to_vault_climb(row)

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _row_to_vault_climb(self, row) -> VaultClimb:
        """Convert database row (dict from Supabase) to VaultClimb."""
        climb_id = row['id']
        if isinstance(climb_id, str):
            climb_id = UUID(climb_id)
        return VaultClimb(
            id=climb_id,
            name=row['name'],
            slug=row.get('slug'),
            region=row.get('region'),
            country_code=row.get('country_code'),
            bounds_min_lat=row['bounds_min_lat'],
            bounds_max_lat=row['bounds_max_lat'],
            bounds_min_lon=row['bounds_min_lon'],
            bounds_max_lon=row['bounds_max_lon'],
            h3_tile_ids=row.get('h3_tile_ids') or None,
            total_vert_m=row['total_vert_m'],
            avg_gradient_pct=row['avg_gradient_pct'],
            distance_m=row['distance_m'],
            base_elevation_m=row.get('base_elevation_m'),
            peak_elevation_m=row.get('peak_elevation_m'),
            signature_hex=row['signature_hex'],
            signature_tolerance=row.get('signature_tolerance', 0.55),
            uci_category=row.get('uci_category'),
            difficulty_score=row.get('difficulty_score'),
        )

    def _row_to_attestation(self, row) -> ClimbAttestation:
        """Convert database row to ClimbAttestation."""
        return ClimbAttestation(
            id=row['id'],
            user_id=row['user_id'],
            ride_id=row['ride_id'],
            vault_climb_id=row['vault_climb_id'],
            signature_similarity=row['signature_similarity'],
            vert_m=row['vert_m'],
            time_s=row['time_s'],
            vam=row.get('vam'),
            avg_power_w=row.get('avg_power_w'),
            user_signature_hex=row['user_signature_hex'],
            tile_ids=row['tile_ids'] or [],
            climb_started_at=row['climb_started_at'],
            climb_completed_at=row['climb_completed_at'],
            attestation_status=row.get('attestation_status', 'pending'),
            solana_tx_signature=row.get('solana_tx_signature'),
        )

    def _get_bounds_from_samples(
        self,
        samples: List[dict],
        pattern: ClimbPattern,
    ) -> Optional[Tuple[float, float, float, float]]:
        """Extract geographic bounds from tile samples for the pattern's time range."""
        # Filter samples to pattern's time range
        start_t = pattern.start_time_offset_s
        end_t = pattern.end_time_offset_s
        base_time = infer_sample_time_base(samples)

        relevant = [
            s for s in samples
            if s.get('lat') is not None
            and s.get('lon') is not None
            and sample_in_time_window(s, start_t, end_t, base_time=base_time)
        ]

        if not relevant:
            return None

        lats = [s['lat'] for s in relevant]
        lons = [s['lon'] for s in relevant]

        return (min(lats), max(lats), min(lons), max(lons))

    def _generate_signature_from_pattern(
        self,
        pattern: ClimbPattern,
        tile_samples: List[dict],
    ) -> Optional[ClimbSignature]:
        """Generate signature from pattern and samples."""
        start_t = pattern.start_time_offset_s
        end_t = pattern.end_time_offset_s

        return self._signature_gen.generate_from_climb_pattern(
            tile_samples, start_t, end_t
        )

    def _slugify(self, name: str) -> str:
        """Convert name to URL-friendly slug."""
        import re
        slug = name.lower()
        slug = re.sub(r'[^a-z0-9]+', '-', slug)
        slug = slug.strip('-')
        return slug

    def _compute_uci_category(
        self,
        vert_m: float,
        gradient_pct: float,
        distance_m: float,
    ) -> Optional[str]:
        """Read category shares the sole backend definition."""
        from .climb_read_metrics import climb_category
        return climb_category(distance_m, gradient_pct)
