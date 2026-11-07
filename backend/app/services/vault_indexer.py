"""Read-only cache of TypeScript-indexed vault signatures for climb discovery.

The former Python chain writer was retired because it had no finalized slot
provenance and could overwrite newer TypeScript projections. The TypeScript
indexer is the only service that writes chain-owned vault fields.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from supabase import Client

from .patterns.climb_signature import ClimbSignature, ClimbSignatureV2
from .vault_activation_policy import REWARD_AUTHORITATIVE_SEED_GENERATION
from ..utils.postgrest_paging import PageCursor

logger = logging.getLogger(__name__)

@dataclass
class IndexedVault:
    """Cached vault data from chain."""
    id: int
    signature_hex: str
    signature_hash_hex: str
    minter: str
    name: str
    vert_m: float
    distance_m: int
    avg_gradient_pct: float
    total_completions: int
    total_staked: int
    kom_holder: Optional[str]
    kom_time_s: int
    created_at: datetime
    pda: str
    signature_v2_hex: Optional[str] = None
    start_lat: Optional[float] = None
    start_lon: Optional[float] = None
    end_lat: Optional[float] = None
    end_lon: Optional[float] = None
    polyline_json: Optional[str] = None  # JSON array of [[lat, lon], ...] for template matching
    activation_status: Optional[str] = None
    chain_activation_active: Optional[bool] = None
    chain_activation_seed_generation: Optional[int] = None

    @property
    def signature(self) -> ClimbSignature:
        """Parse v1 signature for matching."""
        sig_bytes = bytes.fromhex(self.signature_hex)
        return ClimbSignature(
            signature=sig_bytes,
            vert_m=self.vert_m,
            avg_gradient_pct=self.avg_gradient_pct,
            distance_m=float(self.distance_m),
            duration_s=0,  # Not stored, but not needed for matching
        )

    @property
    def signature_v2(self) -> Optional[ClimbSignatureV2]:
        """Parse v2 signature if available."""
        if not self.signature_v2_hex:
            return None
        return ClimbSignatureV2.from_hex(self.signature_v2_hex)


class VaultSignatureCache:
    """
    In-memory cache of vault signatures for fast matching.

    Loaded from indexed_vaults table at startup.
    Refreshed when new vaults are indexed.
    """

    def __init__(self):
        self._vaults: Dict[int, IndexedVault] = {}
        self._loaded: bool = False
        self._load_time: Optional[datetime] = None

    @property
    def count(self) -> int:
        return len(self._vaults)

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    async def load(self, supabase_client: Client) -> int:
        """
        Load all vault signatures from database.

        Uses asyncpg (direct Postgres) when available to avoid Supabase REST
        egress.  Falls back to the Supabase client if asyncpg is not configured.

        Returns:
            Number of vaults loaded
        """
        rows = None

        # Try asyncpg bulk load first (avoids REST egress)
        try:
            from ..db_pool import get_pool
            pool = await get_pool()
            async with pool.acquire() as conn:
                pg_rows = await conn.fetch(
                    """
                    SELECT
                        iv.*,
                        iva.is_active AS chain_activation_active,
                        iva.seed_generation AS chain_activation_seed_generation
                    FROM indexed_vaults AS iv
                    LEFT JOIN indexed_vault_activations AS iva
                      ON iva.vault_id = iv.id
                    """
                )
                rows = [dict(r) for r in pg_rows]
            logger.info(f"[VaultSignatureCache] Loaded {len(rows)} rows via asyncpg")
        except Exception as e:
            logger.debug(f"[VaultSignatureCache] asyncpg load failed, trying REST: {e}")

        # Fallback to Supabase REST
        if rows is None:
            try:
                page_size = 1000
                pages = PageCursor(page_size)
                rows = []
                query = (
                    supabase_client.from_("indexed_vaults")
                    .select("*")
                    .order("id")
                )
                while True:
                    response = query.range(
                        pages.offset, pages.offset + page_size - 1,
                    ).execute()
                    page = response.data or []
                    rows.extend(page)
                    if not pages.advance(page):  # range() is end-exclusive; see postgrest_paging.
                        break

                activation_by_vault: Dict[int, Dict] = {}
                pages = PageCursor(page_size)
                activation_query = (
                    supabase_client.from_("indexed_vault_activations")
                    .select("vault_id, is_active, seed_generation")
                    .eq("is_active", True)
                    .gte(
                        "seed_generation",
                        REWARD_AUTHORITATIVE_SEED_GENERATION,
                    )
                    .order("vault_id")
                )
                while True:
                    response = activation_query.range(
                        pages.offset,
                        pages.offset + page_size - 1,
                    ).execute()
                    page = response.data or []
                    for activation in page:
                        activation_by_vault[int(activation["vault_id"])] = activation
                    if not pages.advance(page):
                        break

                rows = [
                    {
                        **row,
                        "chain_activation_active": (
                            activation_by_vault.get(int(row["id"])) or {}
                        ).get("is_active"),
                        "chain_activation_seed_generation": (
                            activation_by_vault.get(int(row["id"])) or {}
                        ).get("seed_generation"),
                    }
                    for row in rows
                ]
            except Exception as e:
                logger.exception(f"[VaultSignatureCache] Failed to load: {e}")
                return 0

        self._vaults.clear()

        for row in rows:
            # Handle created_at: asyncpg returns datetime objects, REST returns strings
            created_at_raw = row.get("created_at")
            if isinstance(created_at_raw, datetime):
                created_at = created_at_raw
            elif isinstance(created_at_raw, str):
                created_at = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
            else:
                created_at = datetime.now(timezone.utc)

            vault = IndexedVault(
                id=row["id"],
                signature_hex=row["signature_hex"],
                signature_hash_hex=row["signature_hash_hex"],
                minter=row["minter"],
                name=row["name"] or "",
                vert_m=float(row["vert_m"] or 0),
                distance_m=int(row["distance_m"] or 0),
                avg_gradient_pct=float(row["avg_gradient_pct"] or 0),
                total_completions=int(row["total_completions"] or 0),
                total_staked=int(row["total_staked"] or 0),
                kom_holder=row["kom_holder"],
                kom_time_s=int(row["kom_time_s"] or 0),
                created_at=created_at,
                pda=row["pda"],
                signature_v2_hex=row.get("signature_v2_hex"),
                start_lat=(
                    float(row["start_lat"])
                    if row.get("start_lat") is not None
                    else None
                ),
                start_lon=(
                    float(row["start_lon"])
                    if row.get("start_lon") is not None
                    else None
                ),
                end_lat=(
                    float(row["end_lat"])
                    if row.get("end_lat") is not None
                    else None
                ),
                end_lon=(
                    float(row["end_lon"])
                    if row.get("end_lon") is not None
                    else None
                ),
                polyline_json=row.get("polyline_json"),
                activation_status=(
                    row.get("activation_status")
                    or row.get("on_chain_seeding_status")
                ),
                chain_activation_active=row.get("chain_activation_active"),
                chain_activation_seed_generation=(
                    int(row["chain_activation_seed_generation"])
                    if row.get("chain_activation_seed_generation") is not None
                    else None
                ),
            )
            self._vaults[vault.id] = vault

        self._loaded = True
        self._load_time = datetime.now(timezone.utc)

        logger.info(f"[VaultSignatureCache] Loaded {len(self._vaults)} vaults")
        return len(self._vaults)

    def get_vault(self, vault_id: int) -> Optional[IndexedVault]:
        """Get a vault by ID."""
        return self._vaults.get(vault_id)

    def find_matches(
        self,
        user_signature: ClimbSignature,
        min_similarity: float = 0.90,
        user_signature_v2: Optional[ClimbSignatureV2] = None,
    ) -> List[Tuple[IndexedVault, float]]:
        """
        Find non-economic discovery matches for a user's climb signature.

        When both the user and vault have v2 signatures, uses DCT multi-gate
        matching. The v1 fallback is compatibility-only and cannot authorize
        tribute, completions, or Record Board state.

        Args:
            user_signature: User's detected v1 climb signature
            min_similarity: Minimum similarity threshold (0.0-1.0)
            user_signature_v2: Optional v2 signature for DCT matching

        Returns:
            List of (IndexedVault, similarity) tuples, sorted by similarity descending
        """
        if not self._loaded:
            logger.warning("[VaultSignatureCache] Cache not loaded, returning empty matches")
            return []

        matches: List[Tuple[IndexedVault, float]] = []

        for vault in self._vaults.values():
            try:
                # Prefer v2 matching when both sides have DCT signatures
                if user_signature_v2 and vault.signature_v2:
                    similarity = user_signature_v2.similarity(vault.signature_v2)
                else:
                    similarity = user_signature.similarity(vault.signature)

                if similarity >= min_similarity:
                    matches.append((vault, similarity))
            except Exception as e:
                logger.debug(f"[VaultSignatureCache] Error comparing vault {vault.id}: {e}")
                continue

        # Sort by similarity descending, then vault id for determinism
        matches.sort(key=lambda x: (-x[1], x[0].id))
        return matches


# Singleton instance
_cache: Optional[VaultSignatureCache] = None


def get_vault_signature_cache() -> VaultSignatureCache:
    """Get or create vault signature cache singleton."""
    global _cache
    if _cache is None:
        _cache = VaultSignatureCache()
    return _cache
