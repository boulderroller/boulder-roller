"""
Vault Repository

Database operations for vaults (indexed_vaults), completions, leaderboards, and stakes.

Read paths use chain-indexed tables (indexed_completions, indexed_leaderboards,
indexed_stakes, indexed_legends) populated by the Solana indexer.
Confirmed creation metadata and replay intent use ``vault_creation_handoffs``;
the TypeScript indexer is the only creator and writer of chain-state Vault
projections.

Heavy READ operations use asyncpg (direct Postgres) when DATABASE_URL is
configured.  This avoids Supabase REST API egress quotas.  Falls back to
the Supabase client automatically.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, TypedDict
from uuid import UUID

from .base import BaseRepository
from ..services.record_board_projection import project_competition_entries
from ..utils.postgrest_paging import PageCursor, order_by, window
from ..services.vault_activation_policy import (
    REWARD_AUTHORITATIVE_SEED_GENERATION,
    is_reward_authoritative_vault,
)

logger = logging.getLogger(__name__)

REWARD_GRADE_VAULT_PAGE_SIZE = 1000
INDEXED_STAKE_PAGE_SIZE = 1000


def _with_chain_activation(
    vault: Dict[str, Any],
    activation: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    projected = dict(vault)
    projected["chain_activation_active"] = (
        activation.get("is_active") if activation else None
    )
    projected["chain_activation_seed_generation"] = (
        activation.get("seed_generation") if activation else None
    )
    return projected


async def _asyncpg_fetch(query: str, *args) -> Optional[list]:
    """Execute a read query via the shared asyncpg pool.

    Returns a list of asyncpg.Record on success, or None if asyncpg is
    not available (missing DATABASE_URL, pool error, etc.).
    """
    try:
        from ..db_pool import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            return await conn.fetch(query, *args)
    except Exception as e:
        logger.debug("asyncpg read failed (will fall back to REST): %s", e)
        return None


async def _asyncpg_fetchrow(query: str, *args):
    """Execute a read query returning a single row, or None on error."""
    try:
        from ..db_pool import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            return await conn.fetchrow(query, *args)
    except Exception as e:
        logger.debug("asyncpg fetchrow failed (will fall back to REST): %s", e)
        return None


async def _asyncpg_fetchval(query: str, *args):
    """Execute a read query returning a single value, or None on error."""
    try:
        from ..db_pool import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            return await conn.fetchval(query, *args)
    except Exception as e:
        logger.debug("asyncpg fetchval failed (will fall back to REST): %s", e)
        return None


def _leaderboard_recorded_at_iso(recorded_at: Any) -> Optional[str]:
    if recorded_at in (None, ""):
        return None
    return datetime.fromtimestamp(int(recorded_at)).isoformat()


def _clock_timestamp_iso(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


# =============================================================================
# TYPED DICTS FOR DATABASE RESPONSES
# =============================================================================


class VaultStakeDict(TypedDict, total=False):
    """Typed dict for vault_stakes database rows."""
    id: str
    vault_signature: str
    vault_id: int
    vault_name: Optional[str]
    climb_id: Optional[str]
    wallet: str
    cal_staked: Any
    lp_tokens: Any
    rewards_earned: Any
    staked_at: str
    unstaked_at: Optional[str]
    converted_at: Optional[str]


class VaultTotalStakeDict(TypedDict):
    """Typed dict for vault total stake aggregation."""
    total_cal_staked: int
    total_lp_tokens: int


class LeaderboardEntryDict(TypedDict, total=False):
    """Typed dict for vault_leaderboards database rows."""
    vault_signature: str
    position: int
    rank: int
    competition_rank: int
    tie_size: int
    is_tied: bool
    wallet: str
    best_time_seconds: int
    avg_power_w: Optional[int]
    completion_id: Optional[str]
    achieved_at: str
    # Metadata fields (052_leaderboard_metadata.sql)
    device_name: Optional[str]
    is_personal_record: bool
    attempt_number: int
    activity_id: Optional[str]


class VaultCompletionDict(TypedDict, total=False):
    """Typed dict for vault_completions database rows."""
    id: str
    vault_signature: str
    wallet: str
    activity_id: str
    completed_at: str
    time_seconds: Optional[int]
    validated: bool
    validation_override: bool
    validation_notes: Optional[str]
    chain_confirmation_status: str
    completion_receipt_pda: Optional[str]
    completion_evidence_hash: Optional[str]
    chain_confirmed_at: Optional[str]
    on_chain_tx: Optional[str]


class TimeValidationResult(TypedDict):
    """Result of time validation check."""
    is_valid: bool
    error_message: Optional[str]
    min_time_s: Optional[int]
    max_time_s: Optional[int]


class LocalLegendDict(TypedDict, total=False):
    """Typed dict for swanny_seats (Local Legend) database rows."""
    id: str
    vault_signature: str
    wallet: str
    elected_at: str
    term_ends_at: str
    completions_count: int
    is_active: bool
    is_bootstrap: bool
    seat_status: str


class LeaderboardHistoryDict(TypedDict, total=False):
    """Typed dict for leaderboard_history database rows."""
    id: str
    vault_signature: str
    wallet: str
    rank: int
    best_time_seconds: int
    avg_power_w: Optional[int]
    entered_at: str
    entered_epoch: int
    exited_at: Optional[str]
    exited_epoch: Optional[int]
    epochs_held: int
    exit_reason: Optional[str]
    bumped_by_wallet: Optional[str]
    bumped_by_time: Optional[int]
    total_dung_earned: float
    total_cal_earned: float
    is_active: bool
    completions_count: int


@dataclass
class VaultRecord:
    """Vault from indexed_vaults table."""
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
    pda: str
    created_at: datetime
    indexed_at: datetime


@dataclass
class VaultCompletion:
    """A vault completion record."""
    id: UUID
    vault_signature: str
    wallet: str
    activity_id: str
    completed_at: datetime
    time_seconds: Optional[int]


@dataclass
class LeaderboardEntry:
    """Entry in vault leaderboard."""
    rank: int
    wallet: str
    best_time_seconds: int
    avg_power_w: Optional[int]
    achieved_at: datetime
    # Metadata fields (052_leaderboard_metadata.sql)
    device_name: Optional[str] = None
    is_personal_record: bool = False
    attempt_number: int = 1
    activity_id: Optional[str] = None


@dataclass
class VaultStake:
    """Staking position in a vault."""
    id: UUID
    vault_signature: str
    wallet: str
    cal_staked: float
    lp_tokens: float
    staked_at: datetime


class VaultRepository(BaseRepository):
    """Repository for vault operations."""

    # =========================================================================
    # VAULT QUERIES
    # =========================================================================

    async def get_vault_by_id(self, vault_id: int) -> Optional[Dict[str, Any]]:
        """Get vault by on-chain ID."""
        row = await _asyncpg_fetchrow(
            """
            SELECT
                iv.*,
                iva.is_active AS chain_activation_active,
                iva.seed_generation AS chain_activation_seed_generation
            FROM indexed_vaults AS iv
            LEFT JOIN indexed_vault_activations AS iva ON iva.vault_id = iv.id
            WHERE iv.id = $1
            """,
            vault_id,
        )
        if row is not None:
            return dict(row)
        # Fallback to Supabase REST
        result = self.client.from_("indexed_vaults") \
            .select("*") \
            .eq("id", vault_id) \
            .execute()
        if not result.data:
            return None
        activation_result = self.client.from_("indexed_vault_activations") \
            .select("vault_id, is_active, seed_generation") \
            .eq("vault_id", vault_id) \
            .limit(1) \
            .execute()
        activation = activation_result.data[0] if activation_result.data else None
        return _with_chain_activation(result.data[0], activation)

    async def get_vault_by_signature(self, signature_hex: str) -> Optional[Dict[str, Any]]:
        """Get vault by 64-byte signature hex."""
        row = await _asyncpg_fetchrow(
            "SELECT * FROM indexed_vaults WHERE signature_hex = $1", signature_hex
        )
        if row is not None:
            return dict(row)
        # Fallback to Supabase REST
        result = self.client.from_("indexed_vaults") \
            .select("*") \
            .eq("signature_hex", signature_hex) \
            .execute()
        return result.data[0] if result.data else None

    async def get_vault_by_signature_hash(self, signature_hash: str) -> Optional[Dict[str, Any]]:
        """Get vault by signature hash (used for PDA lookup)."""
        row = await _asyncpg_fetchrow(
            "SELECT * FROM indexed_vaults WHERE signature_hash_hex = $1", signature_hash
        )
        if row is not None:
            return dict(row)
        # Fallback to Supabase REST
        result = self.client.from_("indexed_vaults") \
            .select("*") \
            .eq("signature_hash_hex", signature_hash) \
            .execute()
        return result.data[0] if result.data else None

    async def list_vaults(
        self,
        limit: int = 50,
        offset: int = 0,
        min_vert_m: Optional[float] = None,
        minter: Optional[str] = None,
        search: Optional[str] = None,
        order_by: str = "total_completions",
        order_desc: bool = True,
    ) -> List[Dict[str, Any]]:
        """List vaults with optional filters."""
        allowed_order = {
            "total_completions", "vert_m", "distance_m",
            "avg_gradient_pct", "created_at", "name", "id",
        }
        safe_order = order_by if order_by in allowed_order else "total_completions"
        direction = "DESC" if order_desc else "ASC"

        # Try asyncpg first
        try:
            from ..db_pool import get_pool
            pool = await get_pool()

            conditions = []
            params: list = []
            idx = 1

            if min_vert_m is not None:
                conditions.append(f"vert_m >= ${idx}")
                params.append(min_vert_m)
                idx += 1
            if minter:
                conditions.append(f"minter = ${idx}")
                params.append(minter)
                idx += 1
            if search:
                conditions.append(f"name ILIKE ${idx}")
                params.append(f"%{search}%")
                idx += 1

            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            sql = (
                f"SELECT * FROM indexed_vaults {where} "
                f"ORDER BY {safe_order} {direction} "
                f"LIMIT ${idx} OFFSET ${idx + 1}"
            )
            params.extend([limit, offset])

            async with pool.acquire() as conn:
                rows = await conn.fetch(sql, *params)
            return [dict(r) for r in rows]
        except Exception as e:
            logger.debug("asyncpg list_vaults failed, falling back to REST: %s", e)

        # Fallback to Supabase REST
        query = self.client.from_("indexed_vaults").select("*")

        if min_vert_m is not None:
            query = query.gte("vert_m", min_vert_m)

        if minter:
            query = query.eq("minter", minter)

        if search:
            query = query.ilike("name", f"%{search}%")

        query = window(query.order(safe_order, desc=order_desc), offset, limit)
        result = query.execute()
        return result.data or []

    async def count_vaults(
        self,
        min_vert_m: Optional[float] = None,
        minter: Optional[str] = None,
        search: Optional[str] = None,
    ) -> int:
        """Count vaults with optional filters (for pagination)."""
        # Try asyncpg first
        try:
            from ..db_pool import get_pool
            pool = await get_pool()

            conditions = []
            params: list = []
            idx = 1

            if min_vert_m is not None:
                conditions.append(f"vert_m >= ${idx}")
                params.append(min_vert_m)
                idx += 1
            if minter:
                conditions.append(f"minter = ${idx}")
                params.append(minter)
                idx += 1
            if search:
                conditions.append(f"name ILIKE ${idx}")
                params.append(f"%{search}%")
                idx += 1

            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            sql = f"SELECT COUNT(*) FROM indexed_vaults {where}"

            async with pool.acquire() as conn:
                count = await conn.fetchval(sql, *params)
            return count or 0
        except Exception as e:
            logger.debug("asyncpg count_vaults failed, falling back to REST: %s", e)

        # Fallback to Supabase REST
        query = self.client.from_("indexed_vaults").select("id", count="exact")

        if min_vert_m is not None:
            query = query.gte("vert_m", min_vert_m)

        if minter:
            query = query.eq("minter", minter)

        if search:
            query = query.ilike("name", f"%{search}%")

        result = query.execute()
        return result.count or 0

    async def find_vaults_by_signatures(
        self,
        signature_hashes: List[str],
    ) -> List[Dict[str, Any]]:
        """Find vaults matching any of the given signature hashes."""
        if not signature_hashes:
            return []

        rows = await _asyncpg_fetch(
            "SELECT * FROM indexed_vaults WHERE signature_hash_hex = ANY($1)",
            signature_hashes,
        )
        if rows is not None:
            return [dict(r) for r in rows]

        # Fallback to Supabase REST
        result = self.client.from_("indexed_vaults") \
            .select("*") \
            .in_("signature_hash_hex", signature_hashes) \
            .execute()
        return result.data or []

    async def find_canon_vault_binding(
        self,
        *,
        registry_id: UUID,
        canon_id: UUID,
        canon_version: int,
        profile_hash_hex: str,
    ) -> Optional[Dict[str, Any]]:
        """Resolve economics only through one finalized exact V4-B binding."""
        row = await _asyncpg_fetchrow(
            """
            SELECT
                vault.*,
                climb.canon_climb_id,
                climb.canon_id,
                climb.canon_version,
                climb.canonical_profile_hash_hex,
                vault.canon_binding_status,
                activation.activation_status AS canon_activation_status,
                activation.vault_activation_pda AS expected_vault_activation_pda,
                activation.constructor_evidence_verified,
                activation.constructor_evidence_hash,
                chain_activation.pda AS vault_activation_pda,
                chain_activation.is_active AS vault_activation_is_active,
                chain_activation.seed_generation AS vault_activation_seed_generation,
                chain_activation.seed_completions_written
                    AS vault_activation_seed_completions_written,
                chain_activation.leaderboard_seeded AS vault_activation_leaderboard_seeded,
                chain_activation.matched_users AS vault_activation_matched_users,
                chain_activation.matched_completions
                    AS vault_activation_matched_completions,
                chain_activation.created_at AS vault_activation_created_at,
                chain_activation.activated_at AS vault_activation_activated_at,
                chain_activation.last_seed_at AS vault_activation_last_seed_at,
                chain_activation.seed_cutoff_at AS vault_activation_seed_cutoff_at,
                lower(btrim(chain_activation.evidence_hash::text))
                    AS vault_activation_evidence_hash,
                chain_activation.chain_slot AS vault_activation_chain_slot
            FROM public.canon_climbs AS registry
            JOIN public.indexed_climbs AS climb
              ON climb.canon_climb_id = registry.id
             AND climb.canon_id = registry.canon_id
             AND climb.canon_version = registry.version
             AND climb.successor_climb_pda IS NULL
             AND climb.quarantined IS FALSE
            JOIN public.indexed_vaults AS vault
              ON vault.canon_climb_id = registry.id
             AND vault.climb_pda = climb.pda
             AND vault.pda = climb.vault_pda
             AND vault.signature_hex = climb.canon_commitment_hex
             AND vault.signature_hash_hex = climb.commitment_hash_hex
             AND vault.canon_commitment_hex = climb.canon_commitment_hex
             AND vault.canon_binding_status = 'active'
            JOIN public.canon_vault_activations AS activation
              ON activation.canon_climb_id = registry.id
             AND activation.climb_pda = climb.pda
             AND activation.canon_commitment_hex = climb.canon_commitment_hex
             AND activation.commitment_hash_hex = climb.commitment_hash_hex
             AND activation.vault_id = vault.id
             AND activation.vault_pda = vault.pda
             AND activation.activation_status = 'finalized'
             AND activation.constructor_evidence_verified IS TRUE
            JOIN public.indexed_vault_activations AS chain_activation
              ON chain_activation.vault_id = vault.id
             AND chain_activation.pda = activation.vault_activation_pda
             AND chain_activation.is_active IS TRUE
             AND chain_activation.seed_generation = 2
             AND chain_activation.seed_completions_written = 0
             AND chain_activation.leaderboard_seeded IS TRUE
             AND chain_activation.matched_users = 0
             AND chain_activation.matched_completions = 0
             AND chain_activation.created_at > 0
             AND chain_activation.created_at = chain_activation.activated_at
             AND chain_activation.created_at = chain_activation.last_seed_at
             AND chain_activation.created_at = chain_activation.seed_cutoff_at
             AND lower(btrim(chain_activation.evidence_hash::text))
                   ~ '^[0-9a-f]{64}$'
             AND lower(btrim(chain_activation.evidence_hash::text))
                   <> repeat('0', 64)
             AND lower(btrim(chain_activation.evidence_hash::text))
                   = activation.constructor_evidence_hash
            WHERE registry.id = $1
              AND registry.canon_id = $2
              AND registry.version = $3
              AND registry.status = 'ratified'
              AND registry.record_continuity_policy = 'new_record_board'
              AND climb.canonical_profile_hash_hex = $4
            """,
            registry_id,
            canon_id,
            canon_version,
            profile_hash_hex,
        )
        return dict(row) if row is not None else None

    async def find_reward_grade_vault_matches(
        self,
        *,
        signature_v2_hex: str,
        start_lat: float,
        start_lon: float,
        end_lat: float,
        end_lon: float,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Find economic matches through the geographic v2 authority path."""
        from app.services.patterns.climb_signature import (
            AmbiguousRewardGradeVaultMatch,
            ClimbSignatureV2,
            InvalidRewardGradeCandidate,
            InvalidRewardGradeQuery,
            REWARD_GRADE_MIN_SIMILARITY,
            RewardGradeMatcherError,
            match_reward_grade_v2,
            validate_reward_grade_climb_evidence,
            validate_reward_grade_v2_native,
        )

        try:
            _, query_start, query_end = (
                validate_reward_grade_climb_evidence(
                    signature_v2_hex=signature_v2_hex,
                    start=(start_lat, start_lon),
                    end=(end_lat, end_lon),
                    label="query",
                )
            )
        except ValueError as exc:
            raise InvalidRewardGradeQuery(str(exc)) from exc
        validate_reward_grade_v2_native(
            signature_v2_hex=signature_v2_hex,
            role="query",
        )

        pg_rows = await _asyncpg_fetch(
            """
            SELECT
                iv.*,
                iva.is_active AS chain_activation_active,
                iva.seed_generation AS chain_activation_seed_generation
            FROM indexed_vaults AS iv
            JOIN indexed_vault_activations AS iva ON iva.vault_id = iv.id
            WHERE iva.is_active IS TRUE
              AND iva.seed_generation >= $1
              AND iv.signature_v2_hex IS NOT NULL
              AND iv.start_lat IS NOT NULL
              AND iv.start_lon IS NOT NULL
              AND iv.end_lat IS NOT NULL
              AND iv.end_lon IS NOT NULL
            """,
            REWARD_AUTHORITATIVE_SEED_GENERATION,
        )
        if pg_rows is not None:
            candidates = [dict(row) for row in pg_rows]
        else:
            candidates = []
            authoritative_activations: Dict[int, int] = {}
            activation_pages = PageCursor(REWARD_GRADE_VAULT_PAGE_SIZE)
            while True:
                activation_page = (
                    self.client.from_("indexed_vault_activations")
                    .select("vault_id, is_active, seed_generation")
                    .eq("is_active", True)
                    .gte(
                        "seed_generation",
                        REWARD_AUTHORITATIVE_SEED_GENERATION,
                    )
                    .order("vault_id")
                    .range(
                        activation_pages.offset,
                        activation_pages.offset + REWARD_GRADE_VAULT_PAGE_SIZE - 1,
                    )
                    .execute()
                    .data
                    or []
                )
                for activation in activation_page:
                    authoritative_activations[int(activation["vault_id"])] = int(
                        activation["seed_generation"]
                    )
                # range() is end-exclusive here; see postgrest_paging.
                if not activation_pages.advance(activation_page):
                    break

            vault_pages = PageCursor(REWARD_GRADE_VAULT_PAGE_SIZE)
            while True:
                query = (
                    self.client.from_("indexed_vaults")
                    .select("*")
                )
                for column in (
                    "signature_v2_hex",
                    "start_lat",
                    "start_lon",
                    "end_lat",
                    "end_lon",
                ):
                    query = query.not_.is_(column, "null")
                page = (
                    query.order("id")
                    .range(
                        vault_pages.offset,
                        vault_pages.offset + REWARD_GRADE_VAULT_PAGE_SIZE - 1,
                    )
                    .execute()
                    .data
                    or []
                )
                for vault in page:
                    generation = authoritative_activations.get(int(vault["id"]))
                    candidates.append(
                        _with_chain_activation(
                            vault,
                            {
                                "is_active": True,
                                "seed_generation": generation,
                            }
                            if generation is not None
                            else None,
                        )
                    )
                if not vault_pages.advance(page):
                    break

        matches: List[Dict[str, Any]] = []
        for vault in candidates:
            if not is_reward_authoritative_vault(vault):
                continue
            candidate_signature_hex = vault.get("signature_v2_hex")
            if ClimbSignatureV2.from_hex(candidate_signature_hex or "") is None:
                logger.warning(
                    "[VaultRepo] Vault %s has an invalid v2 signature",
                    vault.get("id"),
                )
                continue
            if any(
                vault.get(field) is None
                for field in ("start_lat", "start_lon", "end_lat", "end_lon")
            ):
                continue

            try:
                evidence = match_reward_grade_v2(
                    query_signature_v2_hex=signature_v2_hex,
                    candidate_signature_v2_hex=candidate_signature_hex,
                    query_start=query_start,
                    query_end=query_end,
                    candidate_start=(vault["start_lat"], vault["start_lon"]),
                    candidate_end=(vault["end_lat"], vault["end_lon"]),
                )
            except RewardGradeMatcherError:
                raise
            except InvalidRewardGradeCandidate as exc:
                logger.warning(
                    "[VaultRepo] Invalid geographic v2 evidence for vault %s: %s",
                    vault.get("id"),
                    exc,
                )
                continue

            if (
                evidence is None
                or evidence.similarity < REWARD_GRADE_MIN_SIMILARITY
            ):
                continue
            matches.append(
                {
                    **vault,
                    "_similarity": evidence.similarity,
                    "_match_type": evidence.result,
                    "_match_evidence": evidence.to_dict(),
                }
            )

        matches.sort(
            key=lambda vault: (-vault["_similarity"], int(vault.get("id") or 0))
        )
        if len(matches) > 1:
            raise AmbiguousRewardGradeVaultMatch(
                "more than one active vault passed reward-grade matching"
            )
        return matches[:limit]

    async def find_vaults_by_signature_similarity(
        self,
        signature_hex: str,
        min_vert_m: float = 0,
        max_vert_m: float = 10000,
        min_similarity: float = 0.75,
        limit: int = 10,
        signature_v2_hex: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Find vaults by signature similarity for non-economic discovery.

        This compatibility path may fall back to v1 Hamming distance and must
        never authorize tribute, a completion, or Record Board state.

        Args:
            signature_hex: User's 64-byte v1 signature as hex
            min_vert_m: Filter candidates by minimum vertical (reduces search space)
            max_vert_m: Filter candidates by maximum vertical
            min_similarity: Minimum similarity threshold (0.0-1.0)
            limit: Maximum results to return
            signature_v2_hex: Optional v2 signature hex for DCT matching

        Returns:
            List of vaults with similarity scores, sorted descending
        """
        from app.services.patterns.climb_signature import ClimbSignature, ClimbSignatureV2

        # Build user v1 signature for comparison
        try:
            user_sig = ClimbSignature(
                signature=bytes.fromhex(signature_hex),
                vert_m=0,  # Will be parsed from signature
                avg_gradient_pct=0,
                distance_m=0,
                duration_s=0,
            )
            # Extract metrics from signature bytes
            import struct
            sig_bytes = bytes.fromhex(signature_hex)
            user_sig.vert_m = struct.unpack('>f', sig_bytes[32:36])[0]
            user_sig.avg_gradient_pct = struct.unpack('>f', sig_bytes[36:40])[0]
            user_sig.distance_m = struct.unpack('>f', sig_bytes[40:44])[0]
            user_sig.duration_s = struct.unpack('>I', sig_bytes[44:48])[0]
        except Exception as e:
            logger.warning(f"[VaultRepo] Failed to parse v1 signature: {e}")
            return []

        # Build user v2 signature if provided
        user_sig_v2 = None
        if signature_v2_hex:
            user_sig_v2 = ClimbSignatureV2.from_hex(signature_v2_hex)

        # Query candidates with vertical range filter (reduces search space)
        # Use ±50% of user's vert to filter candidates
        user_vert = user_sig.vert_m
        filter_min = max(min_vert_m, user_vert * 0.5)
        filter_max = min(max_vert_m, user_vert * 2.0)

        # Try asyncpg for the candidate query
        pg_rows = await _asyncpg_fetch(
            "SELECT * FROM indexed_vaults WHERE vert_m >= $1 AND vert_m <= $2",
            filter_min, filter_max,
        )
        if pg_rows is not None:
            candidates = [dict(r) for r in pg_rows]
        else:
            result = self.client.from_("indexed_vaults") \
                .select("*") \
                .gte("vert_m", filter_min) \
                .lte("vert_m", filter_max) \
                .execute()
            candidates = result.data or []
        if not candidates:
            logger.info(f"[VaultRepo] No candidates in vert range {filter_min:.0f}-{filter_max:.0f}m")
            return []

        # Calculate similarity for each candidate
        matches = []
        for vault in candidates:
            vault_sig_hex = vault.get("signature_hex")
            if not vault_sig_hex:
                continue

            try:
                # Prefer v2 matching when both sides have DCT signatures
                vault_v2_hex = vault.get("signature_v2_hex")
                if user_sig_v2 and vault_v2_hex:
                    vault_sig_v2 = ClimbSignatureV2.from_hex(vault_v2_hex)
                    if vault_sig_v2:
                        similarity = user_sig_v2.similarity(vault_sig_v2)
                    else:
                        # v2 parse failed, fall back to v1
                        vault_sig = ClimbSignature(
                            signature=bytes.fromhex(vault_sig_hex),
                            vert_m=vault.get("vert_m", 0),
                            avg_gradient_pct=vault.get("avg_gradient_pct", 0),
                            distance_m=vault.get("distance_m", 0),
                            duration_s=0,
                        )
                        similarity = user_sig.similarity(vault_sig)
                else:
                    vault_sig = ClimbSignature(
                        signature=bytes.fromhex(vault_sig_hex),
                        vert_m=vault.get("vert_m", 0),
                        avg_gradient_pct=vault.get("avg_gradient_pct", 0),
                        distance_m=vault.get("distance_m", 0),
                        duration_s=0,
                    )
                    similarity = user_sig.similarity(vault_sig)

                if similarity >= min_similarity:
                    matches.append({
                        **vault,
                        "_similarity": round(similarity, 3),
                        "_match_type": "exact" if similarity >= 0.99 else (
                            "strong" if similarity >= 0.85 else (
                                "similar" if similarity >= 0.70 else "pending"
                            )
                        ),
                    })
            except Exception as e:
                logger.debug(f"[VaultRepo] Skip vault {vault.get('id')}: {e}")

        # Sort by similarity descending
        matches.sort(key=lambda v: v["_similarity"], reverse=True)
        logger.info(
            f"[VaultRepo] Similarity search: {len(matches)} matches above {min_similarity:.0%} "
            f"from {len(candidates)} candidates"
        )

        return matches[:limit]

    async def stage_confirmed_vault_creation(
        self,
        vault_id: int,
        signature_hex: str,
        signature_hash_hex: str,
        pda: str,
        signature_v2_hex: str,
        start_lat: float,
        start_lon: float,
        end_lat: float,
        end_lon: float,
        creator_wallet: str,
        create_tx_signature: str,
        source_climb_id: str,
        operation_id: Optional[str],
        priority: int = 100,
    ) -> Dict[str, Any]:
        """Atomically stage confirmed metadata and replay intent.

        This RPC never inserts or updates ``indexed_vaults`` chain-owned fields.
        It reports whether the finalized TypeScript indexer has already written
        a numbered projection for the Vault.
        """
        params = {
            "p_vault_id": vault_id,
            "p_vault_pda": pda,
            "p_signature_hex": signature_hex,
            "p_signature_hash_hex": signature_hash_hex,
            "p_signature_v2_hex": signature_v2_hex,
            "p_start_lat": start_lat,
            "p_start_lon": start_lon,
            "p_end_lat": end_lat,
            "p_end_lon": end_lon,
            "p_creator_wallet": creator_wallet,
            "p_create_tx_signature": create_tx_signature,
            "p_source_climb_id": source_climb_id,
            "p_operation_id": operation_id,
            "p_priority": priority,
        }
        result = self.client.rpc(
            "stage_confirmed_vault_creation",
            params,
        ).execute()
        rows = result.data or []
        row = rows[0] if isinstance(rows, list) and rows else rows
        if not isinstance(row, dict) or not row.get("job_id"):
            raise RuntimeError(
                f"Confirmed Vault handoff did not return replay intent for vault {vault_id}"
            )

        handoff = {
            "job_id": str(row["job_id"]),
            "projection_ready": bool(row.get("projection_ready")),
            "chain_slot": (
                int(row["chain_slot"])
                if row.get("chain_slot") is not None
                else None
            ),
        }
        logger.info(
            "[VaultRepo] Staged confirmed Vault %s (job=%s, projection_ready=%s)",
            vault_id,
            handoff["job_id"],
            handoff["projection_ready"],
        )
        return handoff

    # =========================================================================
    # TIME VALIDATION
    # =========================================================================

    async def validate_climb_time(
        self,
        vault_signature: str,
        time_seconds: int,
        climb_distance_m: Optional[float] = None,
        climb_vert_m: Optional[float] = None,
    ) -> TimeValidationResult:
        """
        Validate a climb time before recording.

        Checks against vault-specific bounds if available, otherwise falls back
        to generic speed-based validation.

        Args:
            vault_signature: The 64-byte vault signature as hex
            time_seconds: Time to complete the climb in seconds
            climb_distance_m: Fallback distance for generic validation
            climb_vert_m: Fallback vertical for generic validation

        Returns:
            TimeValidationResult with is_valid, error_message, and bounds
        """
        try:
            # Try DB-level validation first (uses vault bounds)
            result = self.client.rpc("validate_climb_time", {
                "p_vault_signature": vault_signature,
                "p_time_seconds": time_seconds,
            }).execute()

            if result.data:
                row = result.data[0] if isinstance(result.data, list) else result.data
                return TimeValidationResult(
                    is_valid=row.get("is_valid", True),
                    error_message=row.get("error_message"),
                    min_time_s=row.get("min_time_s"),
                    max_time_s=row.get("max_time_s"),
                )
        except Exception as e:
            logger.warning(f"[TimeValidation] DB validation failed, using fallback: {e}")

        # Fallback validation if DB function not available or vault not found
        return self._fallback_time_validation(
            time_seconds=time_seconds,
            distance_m=climb_distance_m,
            vert_m=climb_vert_m,
        )

    def _fallback_time_validation(
        self,
        time_seconds: int,
        distance_m: Optional[float] = None,
        vert_m: Optional[float] = None,
    ) -> TimeValidationResult:
        """
        Fallback validation when vault bounds aren't available.

        Uses generic speed/VAM limits:
        - Max speed: 15 m/s (54 km/h) - pro descent speed
        - Min speed: 1.4 m/s (5 km/h) - walking pace
        - Max VAM: 2000 - elite climber
        """
        max_speed_mps = 15.0  # ~54 km/h maximum (pro descent speed)
        min_speed_mps = 1.4   # ~5 km/h minimum (walking pace)
        max_vam = 2000        # Elite climber VAM

        # Calculate bounds
        min_time_s = 30  # Absolute minimum 30 seconds
        max_time_s = 21600  # 6 hours max

        if distance_m and distance_m > 0:
            # Distance-based bounds
            min_time_from_dist = int(distance_m / max_speed_mps)
            max_time_from_dist = int(distance_m / min_speed_mps)
            min_time_s = max(min_time_s, min_time_from_dist)
            max_time_s = min(max_time_s, max_time_from_dist)

        if vert_m and vert_m > 0:
            # VAM-based minimum: VAM = vert_m / (time_s / 3600), so time_s = vert_m * 3600 / VAM
            # VAM is in meters/hour, so we need seconds = vert * 3600 / max_vam
            min_time_from_vam = int(vert_m * 3600 / max_vam)
            min_time_s = max(min_time_s, min_time_from_vam)

        # Ensure max is at least 2x min
        max_time_s = max(max_time_s, min_time_s * 2)

        # Validate
        if time_seconds < min_time_s:
            return TimeValidationResult(
                is_valid=False,
                error_message=f"Time {time_seconds}s is impossibly fast (min: {min_time_s}s)",
                min_time_s=min_time_s,
                max_time_s=max_time_s,
            )

        if time_seconds > max_time_s:
            return TimeValidationResult(
                is_valid=False,
                error_message=f"Time {time_seconds}s exceeds maximum (max: {max_time_s}s)",
                min_time_s=min_time_s,
                max_time_s=max_time_s,
            )

        return TimeValidationResult(
            is_valid=True,
            error_message=None,
            min_time_s=min_time_s,
            max_time_s=max_time_s,
        )

    # =========================================================================
    # VAULT COMPLETIONS
    # =========================================================================

    async def record_completion(
        self,
        vault_signature: str,
        wallet: str,
        activity_id: str,
        time_seconds: Optional[int] = None,
        completed_at: Optional[datetime] = None,
        validate_time: bool = True,
        climb_distance_m: Optional[float] = None,
        climb_vert_m: Optional[float] = None,
        cal_tribute: int = 0,
    ) -> Dict[str, Any]:
        """
        Record a vault completion.

        Args:
            vault_signature: The 64-byte vault signature as hex
            wallet: User's wallet address
            activity_id: The ride/activity ID
            time_seconds: Time to complete the climb in seconds
            completed_at: When the completion occurred
            validate_time: Whether to validate the time (default True)
            climb_distance_m: Climb distance for validation (if vault not found)
            climb_vert_m: Climb vertical for validation (if vault not found)
            cal_tribute: CAL credited to this climb completion, if any

        Returns:
            The recorded completion data with validation status
        """
        validated = True
        validation_notes = None

        # Validate time if provided and validation is enabled
        if time_seconds is not None and validate_time:
            validation_result = await self.validate_climb_time(
                vault_signature=vault_signature,
                time_seconds=time_seconds,
                climb_distance_m=climb_distance_m,
                climb_vert_m=climb_vert_m,
            )
            validated = validation_result["is_valid"]
            if not validated:
                validation_notes = validation_result["error_message"]
                logger.warning(
                    f"[TimeValidation] Rejected: vault={vault_signature[:16]}... "
                    f"time={time_seconds}s reason={validation_notes}"
                )

        data = {
            "vault_signature": vault_signature,
            "wallet": wallet,
            "activity_id": activity_id,
            "time_seconds": time_seconds,
            "completed_at": (completed_at or datetime.utcnow()).isoformat(),
            "validated": validated,
            "validation_notes": validation_notes,
            "cal_tribute": int(cal_tribute or 0),
        }

        rpc_result = await self._record_completion_with_projection_rpc(data)
        if rpc_result is not None:
            return rpc_result

        return await self._record_completion_with_projection_fallback(data)

    async def _record_completion_with_projection_rpc(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Atomically insert idempotent backend-local completion evidence.

        The SQL function is the canonical path because it makes replay
        idempotency structural: duplicate (vault_signature, activity_id)
        attempts return the existing row. Chain-owned vault totals are
        projected only by the finalized TypeScript indexer.
        """
        try:
            result = self.client.rpc(
                "record_vault_completion_projection",
                {
                    "p_vault_signature": data["vault_signature"],
                    "p_wallet": data["wallet"],
                    "p_activity_id": data["activity_id"],
                    "p_time_seconds": data.get("time_seconds"),
                    "p_completed_at": data["completed_at"],
                    "p_validated": data.get("validated", True),
                    "p_validation_notes": data.get("validation_notes"),
                    "p_cal_tribute": data.get("cal_tribute", 0),
                },
            ).execute()
        except Exception as exc:
            logger.debug(
                "record_vault_completion_projection RPC unavailable; falling back to REST upsert: %s",
                exc,
            )
            return None

        row = result.data[0] if isinstance(result.data, list) and result.data else result.data
        if not row:
            return None

        completion = row.get("completion") if isinstance(row, dict) else None
        if not isinstance(completion, dict):
            return None

        completion["_inserted"] = bool(row.get("inserted", True))
        return completion

    async def _record_completion_with_projection_fallback(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Compatibility path for local/test databases missing the projection RPC.

        Production should run the RPC-backed path above. This fallback still
        avoids deterministic retry inflation by checking the unique key before
        the upsert; it is not as race-proof as the SQL function.
        """
        existing_result = self.client.from_("vault_completions") \
            .select("id") \
            .eq("vault_signature", data["vault_signature"]) \
            .eq("activity_id", data["activity_id"]) \
            .limit(1) \
            .execute()
        already_recorded = bool(existing_result.data)

        try:
            result = self.client.from_("vault_completions") \
                .upsert(data, on_conflict="vault_signature,activity_id") \
                .execute()
        except Exception:
            # Older local/staging schemas may not have cal_tribute until the
            # paired migration is applied. Keep completion idempotency alive
            # rather than failing the ride processing path.
            fallback_data = dict(data)
            fallback_data.pop("cal_tribute", None)
            result = self.client.from_("vault_completions") \
                .upsert(fallback_data, on_conflict="vault_signature,activity_id") \
                .execute()

        completion = result.data[0] if result.data else data
        completion["_inserted"] = not already_recorded
        return completion

    async def get_completions_for_wallet(
        self,
        wallet: str,
        limit: int = 100,
    ) -> List[VaultCompletionDict]:
        """Get all completions for a wallet."""
        rows = await _asyncpg_fetch(
            "SELECT * FROM indexed_completions WHERE user_pubkey = $1 "
            "ORDER BY last_completed_at DESC LIMIT $2",
            wallet, limit,
        )
        if rows is None:
            result = self.client.from_("indexed_completions") \
                .select("*") \
                .eq("user_pubkey", wallet) \
                .order("last_completed_at", desc=True) \
                .limit(limit) \
                .execute()
            rows = result.data or []
        else:
            rows = [dict(r) for r in rows]

        return [
            {
                "id": f"{row['user_pubkey']}:{row['vault_id']}",
                "vault_signature": None,  # Caller can join via vault_id if needed
                "vault_id": row["vault_id"],
                "wallet": row["user_pubkey"],
                "activity_id": None,
                "completed_at": datetime.fromtimestamp(row["last_completed_at"]).isoformat()
                    if row.get("last_completed_at") else None,
                "time_seconds": row.get("best_time_s"),
                "validated": True,
                "completions": row.get("completions", 0),
                "total_cal_tributed": row.get("total_cal_tributed", 0),
            }
            for row in rows
        ]

    # =========================================================================
    # LEADERBOARD
    # =========================================================================

    async def get_vault_leaderboard(
        self,
        vault_signature: str,
    ) -> List[LeaderboardEntryDict]:
        """Get top 10 leaderboard for a vault."""
        vault = await self.get_vault_by_signature(vault_signature)
        if not vault:
            return []

        entries = await self.get_vault_record_board_entries(int(vault["id"]))
        if not entries:
            return []

        projected_entries = project_competition_entries(entries)

        # Map indexed JSONB entries to the client-facing Record Board shape.
        return [
            {
                "vault_signature": vault_signature,
                "position": int(entry["position"]),
                "rank": int(entry["position"]),
                "competition_rank": int(entry["rank"]),
                "tie_size": int(entry["tie_size"]),
                "is_tied": bool(entry["is_tied"]),
                "wallet": entry.get("user", ""),
                "best_time_seconds": entry.get("time_s", 0),
                "avg_power_w": None,
                "completion_id": None,
                "achieved_at": _leaderboard_recorded_at_iso(entry.get("recorded_at")),
            }
            for entry in projected_entries
        ]

    async def get_vault_record_board_entries(
        self,
        vault_id: int,
    ) -> List[Dict[str, Any]]:
        """Return the exact raw indexed Board entries for privacy projection.

        Public route projections need the chain row's wallet, time, and recorded
        timestamp.  The legacy client mapper intentionally changes that shape,
        so privacy-sensitive reads must start from these raw JSONB entries.
        """

        # Try asyncpg -- fetch the JSONB entries column directly
        row = await _asyncpg_fetchrow(
            "SELECT entries FROM indexed_leaderboards WHERE vault_id = $1",
            vault_id,
        )
        entries = None
        if row is not None:
            raw = row["entries"]
            # asyncpg returns JSONB as a Python object (list/dict) automatically
            entries = raw if isinstance(raw, list) else (
                json.loads(raw) if isinstance(raw, str) else None
            )

        if entries is None:
            # Fallback to Supabase REST
            result = self.client.from_("indexed_leaderboards") \
                .select("entries") \
                .eq("vault_id", vault_id) \
                .execute()
            if not result.data or not result.data[0].get("entries"):
                return []
            entries = result.data[0]["entries"]

        if not entries:
            return []
        if not isinstance(entries, list) or any(
            not isinstance(entry, Mapping) for entry in entries
        ):
            raise ValueError("indexed Record Board entries are malformed")
        return [dict(entry) for entry in entries]

    # =========================================================================
    # STAKING
    # =========================================================================

    async def get_vault_stakes(
        self,
        vault_signature: str,
    ) -> List[VaultStakeDict]:
        """Get all active stakes for a vault."""
        vault = await self.get_vault_by_signature(vault_signature)
        if not vault:
            return []
        vault_id = vault["id"]

        pg_rows = await _asyncpg_fetch(
            "SELECT * FROM indexed_stakes WHERE vault_id = $1 AND lp_tokens > 0 "
            "ORDER BY lp_tokens DESC",
            vault_id,
        )
        if pg_rows is not None:
            rows = [dict(r) for r in pg_rows]
        else:
            result = self.client.from_("indexed_stakes") \
                .select("*") \
                .eq("vault_id", vault_id) \
                .gt("lp_tokens", 0) \
                .order("lp_tokens", desc=True) \
                .execute()
            rows = result.data or []

        return [
            {
                "id": f"{row['user_pubkey']}:{row['vault_id']}",
                "vault_signature": vault_signature,
                "wallet": row["user_pubkey"],
                "cal_staked": row.get("cal_staked", 0),
                "lp_tokens": row.get("lp_tokens", 0),
                "staked_at": datetime.fromtimestamp(row["staked_at"]).isoformat()
                    if row.get("staked_at") else None,
                "unstaked_at": None,
                "converted_at": None,
            }
            for row in rows
        ]

    async def get_unique_staker_count(
        self,
        vault_signature: str,
    ) -> int:
        """Get count of unique stakers with active stakes (lp_tokens > 0)."""
        # indexed_vaults.staker_count is maintained by the indexer
        vault = await self.get_vault_by_signature(vault_signature)
        if not vault:
            return 0
        return vault.get("staker_count", 0)

    async def get_wallet_stake(
        self,
        vault_signature: str,
        wallet: str,
    ) -> Optional[VaultStakeDict]:
        """Get a wallet's stake in a vault."""
        vault = await self.get_vault_by_signature(vault_signature)
        if not vault:
            return None
        vault_id = vault["id"]

        pg_row = await _asyncpg_fetchrow(
            "SELECT * FROM indexed_stakes "
            "WHERE user_pubkey = $1 AND vault_id = $2 AND lp_tokens > 0",
            wallet, vault_id,
        )
        if pg_row is not None:
            row = dict(pg_row)
        else:
            result = self.client.from_("indexed_stakes") \
                .select("*") \
                .eq("user_pubkey", wallet) \
                .eq("vault_id", vault_id) \
                .gt("lp_tokens", 0) \
                .execute()
            if not result.data:
                return None
            row = result.data[0]

        if not row:
            return None
        return {
            "id": f"{row['user_pubkey']}:{row['vault_id']}",
            "vault_signature": vault_signature,
            "wallet": row["user_pubkey"],
            "cal_staked": row.get("cal_staked", 0),
            "lp_tokens": row.get("lp_tokens", 0),
            "rewards_earned": row.get("rewards_earned", 0),
            "staked_at": datetime.fromtimestamp(row["staked_at"]).isoformat()
                if row.get("staked_at") else None,
            "unstaked_at": None,
            "converted_at": None,
        }

    async def get_wallet_stakes(
        self,
        wallet: str,
    ) -> List[VaultStakeDict]:
        """Get all active stakes for a wallet."""
        pg_rows = await _asyncpg_fetch(
            "SELECT stake.*, vault.signature_hex AS vault_signature, "
            "vault.name AS vault_name, "
            "vault.canon_climb_id::text AS canon_climb_id "
            "FROM indexed_stakes AS stake "
            "JOIN indexed_vaults AS vault ON vault.id = stake.vault_id "
            "WHERE stake.user_pubkey = $1 AND stake.lp_tokens > 0 "
            "ORDER BY stake.staked_at DESC",
            wallet,
        )
        if pg_rows is not None:
            rows = [dict(r) for r in pg_rows]
        else:
            result = self.client.from_("indexed_stakes") \
                .select("*") \
                .eq("user_pubkey", wallet) \
                .gt("lp_tokens", 0) \
                .order("staked_at", desc=True) \
                .execute()
            rows = result.data or []

            vault_ids = sorted({int(row["vault_id"]) for row in rows})
            vaults_by_id: Dict[int, Dict[str, Any]] = {}
            if vault_ids:
                vault_result = self.client.from_("indexed_vaults") \
                    .select("id, signature_hex, name, canon_climb_id") \
                    .in_("id", vault_ids) \
                    .execute()
                vaults_by_id = {
                    int(vault["id"]): vault
                    for vault in (vault_result.data or [])
                    if vault.get("signature_hex")
                }
            rows = [
                {
                    **row,
                    "vault_signature": (
                        vaults_by_id.get(int(row["vault_id"]), {}).get("signature_hex")
                    ),
                    "vault_name": (
                        vaults_by_id.get(int(row["vault_id"]), {}).get("name")
                    ),
                    "canon_climb_id": (
                        vaults_by_id.get(int(row["vault_id"]), {}).get("canon_climb_id")
                    ),
                }
                for row in rows
            ]

        stakes: List[VaultStakeDict] = []
        for row in rows:
            vault_signature = row.get("vault_signature")
            if not vault_signature:
                logger.warning(
                    "[VaultRepo] Skipping wallet stake without indexed Vault: "
                    "wallet=%s... vault_id=%s",
                    "[redacted]",
                    row.get("vault_id"),
                )
                continue
            stakes.append(
                {
                    "id": f"{row['user_pubkey']}:{row['vault_id']}",
                    "vault_signature": str(vault_signature),
                    "vault_id": int(row["vault_id"]),
                    "vault_name": row.get("vault_name"),
                    "climb_id": (
                        str(row["canon_climb_id"])
                        if row.get("canon_climb_id")
                        else None
                    ),
                    "wallet": row["user_pubkey"],
                    "cal_staked": row.get("cal_staked", 0),
                    "lp_tokens": row.get("lp_tokens", 0),
                    "rewards_earned": row.get("rewards_earned", 0),
                    "staked_at": datetime.fromtimestamp(row["staked_at"]).isoformat()
                        if row.get("staked_at") else None,
                    "unstaked_at": None,
                    "converted_at": None,
                }
            )
        return stakes

    async def stake_cal(
        self,
        vault_signature: str,
        wallet: str,
        cal_amount: float,
    ) -> VaultStakeDict:
        """Stake points in a vault (pre-TGE shadow system).

        Uses atomic database function to prevent race conditions where
        concurrent stakes could receive incorrect LP token allocations.

        LP tokens are 1:1 with CAL for the first stake, proportional after.
        """
        # Minimum stake check
        if cal_amount < 100:
            raise ValueError("Minimum stake is 100 CAL")

        # Use atomic function that handles locking and LP calculation
        result = self.client.rpc(
            "stake_cal_atomic",
            {
                "p_vault_signature": vault_signature,
                "p_wallet": wallet,
                "p_cal_amount": cal_amount,
            }
        ).execute()

        if not result.data:
            raise ValueError("Failed to stake - no result returned")

        stake_result = result.data[0] if isinstance(result.data, list) else result.data

        logger.info(
            f"[VaultRepo] Staked {cal_amount} CAL in vault {vault_signature[:16]}... "
            f"wallet=[redacted]... lp_tokens={stake_result.get('lp_tokens_issued', 0):.2f}"
        )

        # Return the updated stake
        stake = await self.get_wallet_stake(vault_signature, wallet)
        if stake:
            pass  # cal_staked already set by get_wallet_stake
        return stake

    async def unstake_cal(
        self,
        vault_signature: str,
        wallet: str,
        lp_amount: str,
    ) -> Dict[str, Any]:
        """Update the legacy projection using an exact human-unit LP decimal."""
        # Use atomic function that handles locking and proportional calculation
        result = self.client.rpc(
            "unstake_cal_atomic",
            {
                "p_vault_signature": vault_signature,
                "p_wallet": wallet,
                "p_lp_amount": lp_amount,
            }
        ).execute()

        if not result.data:
            raise ValueError("Failed to unstake - no result returned")

        unstake_result = result.data[0] if isinstance(result.data, list) else result.data

        logger.info(
            "[VaultRepo] Unstaked %s LP from vault %s... wallet=%s... "
            "cal_returned=%s",
            lp_amount,
            vault_signature[:16],
            "[redacted]",
            unstake_result.get("cal_returned", 0),
        )

        return {
            "lp_burned": lp_amount,
            "cal_returned": str(unstake_result.get("cal_returned", 0)),
        }

    async def get_vault_total_stake(
        self,
        vault_signature: str,
    ) -> VaultTotalStakeDict:
        """Get exact active stake totals through the shared batch authority."""
        vault = await self.get_vault_by_signature(vault_signature)
        if not vault:
            return VaultTotalStakeDict(total_cal_staked=0, total_lp_tokens=0)
        vault_id = int(vault["id"])
        return (await self.get_vault_stake_totals([vault_id]))[vault_id]

    async def get_vault_stake_totals(
        self,
        vault_ids: List[int],
    ) -> Dict[int, VaultTotalStakeDict]:
        """Batch exact active CAL and LP totals for indexed Vault positions."""
        normalized_ids = sorted({int(vault_id) for vault_id in vault_ids})
        totals: Dict[int, VaultTotalStakeDict] = {
            vault_id: VaultTotalStakeDict(
                total_cal_staked=0,
                total_lp_tokens=0,
            )
            for vault_id in normalized_ids
        }
        if not normalized_ids:
            return totals

        rows = await _asyncpg_fetch(
            "SELECT vault_id, "
            "COALESCE(SUM(cal_staked), 0) AS total_cal, "
            "COALESCE(SUM(lp_tokens), 0) AS total_lp "
            "FROM indexed_stakes "
            "WHERE vault_id = ANY($1::bigint[]) AND lp_tokens > 0 "
            "GROUP BY vault_id",
            normalized_ids,
        )
        if rows is not None:
            for row in rows:
                vault_id = int(row["vault_id"])
                totals[vault_id] = VaultTotalStakeDict(
                    total_cal_staked=int(row["total_cal"]),
                    total_lp_tokens=int(row["total_lp"]),
                )
            return totals

        pages = PageCursor(INDEXED_STAKE_PAGE_SIZE)
        while True:
            query = self.client.from_("indexed_stakes") \
                .select("vault_id, user_pubkey, cal_staked, lp_tokens") \
                .in_("vault_id", normalized_ids)
            result = order_by(query, "vault_id", "user_pubkey") \
                .range(
                    pages.offset,
                    pages.offset + INDEXED_STAKE_PAGE_SIZE - 1,
                ) \
                .execute()
            page = result.data or []
            for stake in page:
                vault_id = int(stake["vault_id"])
                cal_staked = int(stake.get("cal_staked") or 0)
                lp_tokens = int(stake.get("lp_tokens") or 0)
                if vault_id not in totals or lp_tokens <= 0:
                    continue
                totals[vault_id]["total_cal_staked"] += cal_staked
                totals[vault_id]["total_lp_tokens"] += lp_tokens
            # range() is end-exclusive here; see postgrest_paging.
            if not pages.advance(page):
                break
        return totals

    # =========================================================================
    # LOCAL LEGEND
    # =========================================================================

    async def get_local_legend(
        self,
        vault_signature: str,
    ) -> Optional[LocalLegendDict]:
        """Get current Local Legend for a vault."""
        vault = await self.get_vault_by_signature(vault_signature)
        if not vault:
            return None
        vault_id = vault["id"]

        pg_row = await _asyncpg_fetchrow(
            "SELECT * FROM indexed_legends WHERE vault_id = $1 AND is_active = true",
            vault_id,
        )
        if pg_row is not None:
            row = dict(pg_row)
        else:
            result = self.client.from_("indexed_legends") \
                .select("*") \
                .eq("vault_id", vault_id) \
                .eq("is_active", True) \
                .execute()
            if not result.data:
                return None
            row = result.data[0]

        if not row:
            return None
        return {
            "id": str(row["vault_id"]),
            "vault_signature": vault_signature,
            "wallet": row.get("holder"),
            "elected_at": _clock_timestamp_iso(row.get("term_start_at")),
            "term_ends_at": _clock_timestamp_iso(row.get("term_end_at")),
            "completions_count": row.get("completions_at_election", 0),
            "is_active": bool(row.get("is_active")),
            "is_bootstrap": bool(row.get("is_bootstrap")),
            "seat_status": "bootstrap" if row.get("is_bootstrap") else "elected",
        }

    # =========================================================================
    # VAULT DETAIL (aggregated)
    # =========================================================================

    async def get_vault_detail(
        self,
        vault_signature: str,
    ) -> Optional[Dict[str, Any]]:
        """Get comprehensive vault detail including leaderboard, stakes, legend."""
        vault = await self.get_vault_by_signature(vault_signature)
        if not vault:
            return None

        leaderboard = await self.get_vault_leaderboard(vault_signature)
        total_stake = await self.get_vault_total_stake(vault_signature)
        local_legend = await self.get_local_legend(vault_signature)

        return {
            **vault,
            "leaderboard": leaderboard,
            "total_cal_staked": total_stake["total_cal_staked"],
            "total_lp_tokens": total_stake["total_lp_tokens"],
            "local_legend": local_legend,
        }

    # =========================================================================
    # USER LEADERBOARD SUMMARY
    # =========================================================================

    async def get_user_leaderboard_positions(self, wallet: str) -> List[Dict[str, Any]]:
        """
        Get all leaderboard positions for a user across all vaults.

        Returns a list of vault positions with details including:
        - vault_id, vault_name, vault_signature
        - rank, best_time_seconds, is_kom
        - total_riders, percentile, last_achieved_at
        """
        result = self.client.rpc(
            "get_user_leaderboard_positions",
            {"p_wallet": wallet}
        ).execute()
        positions = [dict(row) for row in (result.data or [])]
        vault_ids = sorted(
            {
                int(row["vault_id"])
                for row in positions
                if row.get("vault_id") is not None
            }
        )
        if not vault_ids:
            return positions
        bindings = (
            self.client.from_("indexed_vaults")
            .select("id, canon_climb_id")
            .in_("id", vault_ids)
            .execute()
        )
        canon_ids = {
            int(row["id"]): str(row["canon_climb_id"])
            for row in (bindings.data or [])
            if row.get("id") is not None and row.get("canon_climb_id") is not None
        }
        for position in positions:
            vault_id = position.get("vault_id")
            position["canon_climb_id"] = (
                canon_ids.get(int(vault_id)) if vault_id is not None else None
            )
        return positions

    async def get_user_leaderboard_stats(self, wallet: str) -> Dict[str, Any]:
        """
        Get aggregated leaderboard stats for a user.

        Returns stats including:
        - total_positions: Total top-10 positions held
        - kom_count: Number of KOMs (rank 1)
        - podium_count: Top 3 positions
        - top10_count: All top 10 positions
        - total_vaults_completed: Unique vaults completed
        - best_percentile: Best percentile ranking achieved
        """
        result = self.client.rpc(
            "get_user_leaderboard_stats",
            {"p_wallet": wallet}
        ).execute()
        if result.data:
            return result.data[0]
        return {
            "total_positions": 0,
            "kom_count": 0,
            "podium_count": 0,
            "top10_count": 0,
            "total_vaults_completed": 0,
            "best_percentile": None,
        }

    # =========================================================================
    # FULL LEADERBOARD (All Positions)
    # =========================================================================

    async def get_vault_total_riders(self, vault_signature: str) -> int:
        """Get total number of unique riders who completed this vault with a valid time."""
        result = self.client.rpc(
            "get_vault_total_riders",
            {"p_vault_signature": vault_signature}
        ).execute()
        return result.data if result.data else 0

    # =========================================================================
    # LEADERBOARD HISTORY
    # =========================================================================

    async def get_vault_leaderboard_history(
        self,
        vault_signature: str,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Get historical leaderboard entries for a vault.

        Returns all entries and exits including:
        - Who entered/exited the leaderboard
        - When they entered/exited
        - Why they exited (bumped, improved own time, admin removed)
        - Who bumped them and with what time
        - How many epochs they held the position
        - Earnings during tenure
        """
        result = self.client.rpc(
            "get_vault_leaderboard_history",
            {
                "p_vault_signature": vault_signature,
                "p_limit": limit,
            }
        ).execute()
        return result.data or []

    async def get_user_leaderboard_history(
        self,
        wallet: str,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Get user's leaderboard history across all vaults.

        Returns historical entries including:
        - Which vaults they were on the leaderboard for
        - Their rank and time
        - When they entered/exited
        - Why they exited
        - Earnings during tenure
        """
        result = self.client.rpc(
            "get_user_leaderboard_history",
            {
                "p_wallet": wallet,
                "p_limit": limit,
            }
        ).execute()
        return result.data or []

    # =========================================================================

    # =========================================================================
    # NEARBY RIDERS VIEW
    # =========================================================================

    async def get_user_ridden_climbs(self, wallet: str) -> List[Dict[str, Any]]:
        """
        Every canon climb this rider has confirmed completions on, aggregated:
        attempts, best time, last ridden. Only receipt-confirmed evidence
        counts (same confirmation gate as effort history).
        """
        confirmed: List[Dict[str, Any]] = []
        page_size = 1000
        pages = PageCursor(page_size)
        while True:
            query = self.client.from_("vault_completions") \
                .select("vault_signature, time_seconds, completed_at") \
                .eq("wallet", wallet) \
                .eq("validated", True) \
                .eq("chain_confirmation_status", "confirmed") \
                .not_.is_("time_seconds", "null")
            result = order_by(query, "completed_at", "id") \
                .range(pages.offset, pages.offset + page_size - 1) \
                .execute()
            page = [dict(row) for row in (result.data or [])]
            confirmed.extend(page)
            if not pages.advance(page):  # range() is end-exclusive; see postgrest_paging.
                break
        if not confirmed:
            return []

        by_signature: Dict[str, Dict[str, Any]] = {}
        for row in confirmed:
            signature = str(row.get("vault_signature") or "")
            if not signature:
                continue
            bucket = by_signature.setdefault(signature, {
                "attempts": 0,
                "best_time_seconds": None,
                "last_ridden_at": None,
            })
            bucket["attempts"] += 1
            time_seconds = int(row["time_seconds"])
            if bucket["best_time_seconds"] is None or time_seconds < bucket["best_time_seconds"]:
                bucket["best_time_seconds"] = time_seconds
            completed_at = row.get("completed_at")
            if completed_at and (
                bucket["last_ridden_at"] is None or str(completed_at) > str(bucket["last_ridden_at"])
            ):
                bucket["last_ridden_at"] = completed_at

        signatures = sorted(by_signature.keys())
        vaults_result = self.client.from_("indexed_vaults") \
            .select("id, name, signature_hex, canon_climb_id, canon_binding_status") \
            .in_("signature_hex", signatures) \
            .execute()
        vaults = {
            str(v["signature_hex"]): dict(v)
            for v in (vaults_result.data or [])
        }

        canon_ids = sorted({
            str(v["canon_climb_id"])
            for v in vaults.values()
            if v.get("canon_climb_id")
        })
        canon_rows: Dict[str, Dict[str, Any]] = {}
        if canon_ids:
            canon_result = self.client.from_("canon_climbs") \
                .select("id, display_name, length_m, avg_gradient_pct") \
                .in_("id", canon_ids) \
                .execute()
            canon_rows = {str(c["id"]): dict(c) for c in (canon_result.data or [])}

        climbs: List[Dict[str, Any]] = []
        for signature, bucket in by_signature.items():
            vault = vaults.get(signature)
            if not vault:
                continue
            canon_id = str(vault.get("canon_climb_id") or "") or None
            canon = canon_rows.get(canon_id or "", {})
            climbs.append({
                "canon_climb_id": canon_id,
                "vault_id": vault.get("id"),
                "name": canon.get("display_name") or vault.get("name"),
                "attempts": bucket["attempts"],
                "best_time_seconds": bucket["best_time_seconds"],
                "last_ridden_at": bucket["last_ridden_at"],
                "length_m": canon.get("length_m"),
                "avg_gradient_pct": canon.get("avg_gradient_pct"),
            })
        climbs.sort(key=lambda c: str(c.get("last_ridden_at") or ""), reverse=True)
        return climbs

    async def get_user_vault_effort_history(
        self,
        vault_signature: str,
        wallet: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Get a user's effort history on a specific vault.

        Returns all completions for the user on this vault, sorted by date DESC,
        with isPR and improvement calculated for each effort.

        Args:
            vault_signature: The 64-byte vault signature as hex
            wallet: User's wallet address
            limit: Maximum number of efforts to return

        Returns:
            List of efforts with id, timeSeconds, avgPowerW, achievedAt, isPR, improvement
        """
        # `vault_completions` is backend-local, idempotent evidence. Only rows
        # reconciled to a finalized on-chain receipt are sporting history; old
        # detector/placeholder rows remain excluded by the confirmation gate.
        confirmed: List[Dict[str, Any]] = []
        page_size = 1000
        pages = PageCursor(page_size)
        try:
            while True:
                query = self.client.from_("vault_completions") \
                    .select(
                        "id, activity_id, time_seconds, avg_power_w, completed_at"
                    ) \
                    .eq("vault_signature", vault_signature) \
                    .eq("wallet", wallet) \
                    .eq("validated", True) \
                    .eq("chain_confirmation_status", "confirmed") \
                    .not_.is_("time_seconds", "null")
                result = order_by(query, "completed_at", "id") \
                    .range(pages.offset, pages.offset + page_size - 1) \
                    .execute()
                page = [dict(row) for row in (result.data or [])]
                confirmed.extend(page)
                if not pages.advance(page):  # range() is end-exclusive; see postgrest_paging.
                    break
        except Exception as exc:
            logger.warning(
                "[VaultRepo] Confirmed effort history unavailable for vault %s: %s",
                vault_signature[:16],
                exc,
            )
            confirmed = []

        if confirmed:
            running_best: Optional[int] = None
            efforts: List[Dict[str, Any]] = []
            total_count = len(confirmed)
            for row in confirmed:
                time_seconds = int(row["time_seconds"])
                is_pr = running_best is None or time_seconds < running_best
                improvement = (
                    running_best - time_seconds
                    if is_pr and running_best is not None
                    else None
                )
                if is_pr:
                    running_best = time_seconds
                activity_id = str(row.get("activity_id") or "")
                try:
                    ride_id = str(UUID(activity_id))
                except (TypeError, ValueError):
                    ride_id = None
                efforts.append({
                    "id": str(row["id"]),
                    "rideId": ride_id,
                    "timeSeconds": time_seconds,
                    "avgPowerW": row.get("avg_power_w"),
                    "achievedAt": _clock_timestamp_iso(row.get("completed_at")),
                    "isPR": is_pr,
                    "improvement": improvement,
                    "attemptCount": total_count,
                })
            return list(reversed(efforts[-limit:]))

        # The chain index aggregates per user+vault. If receipt history is
        # unavailable, preserve the exact best/count summary without claiming
        # a navigable historical Ride.
        vault = await self.get_vault_by_signature(vault_signature)
        if not vault:
            return []
        ic_result = self.client.from_("indexed_completions") \
            .select("best_time_s, completions, last_completed_at") \
            .eq("user_pubkey", wallet) \
            .eq("vault_id", vault["id"]) \
            .execute()
        if not ic_result.data or not ic_result.data[0].get("best_time_s"):
            return []
        row = ic_result.data[0]
        return [{
            "id": f"{wallet}:{vault['id']}",
            "rideId": None,
            "timeSeconds": row["best_time_s"],
            "avgPowerW": None,
            "achievedAt": datetime.fromtimestamp(row["last_completed_at"]).isoformat()
                if row.get("last_completed_at") else None,
            "isPR": True,
            "improvement": None,
            "attemptCount": int(row.get("completions") or 1),
        }]

    async def get_nearby_riders(
        self,
        vault_signature: str,
        wallet: str,
        above: int = 3,
        below: int = 3,
    ) -> Optional[Dict[str, Any]]:
        """
        Get riders near a user's position with configurable window.

        Args:
            vault_signature: The 64-byte vault signature as hex
            wallet: User's wallet address
            above: Number of riders above user to include (default 3)
            below: Number of riders below user to include (default 3)

        Returns:
            Dict with user_position, nearby_riders, and motivation_message,
            or None if user has no completion with valid time.
        """
        # Get nearby riders using the SQL function
        nearby_result = self.client.rpc(
            "get_nearby_riders",
            {
                "p_vault_signature": vault_signature,
                "p_wallet": wallet,
                "p_above": above,
                "p_below": below,
            }
        ).execute()

        if not nearby_result.data:
            return None

        nearby_riders = nearby_result.data

        # Get motivation context
        motivation_result = self.client.rpc(
            "get_leaderboard_motivation",
            {
                "p_vault_signature": vault_signature,
                "p_wallet": wallet,
            }
        ).execute()

        if not motivation_result.data:
            return None

        motivation = motivation_result.data[0]

        # Find user's entry in nearby riders
        user_entry = None
        for rider in nearby_riders:
            if rider.get("is_user"):
                user_entry = rider
                break

        return {
            "user_position": {
                "rank": motivation.get("user_rank"),
                "total_riders": motivation.get("total_riders"),
                "percentile": float(motivation.get("percentile", 100)),
                "best_time_seconds": motivation.get("best_time_seconds"),
                "is_top_10": motivation.get("is_top_10", False),
                "time_to_next_rank": motivation.get("time_to_next_rank"),
                "time_gap_from_behind": motivation.get("time_gap_from_behind"),
                "avg_power_w": user_entry.get("avg_power_w") if user_entry else None,
                "total_completions": user_entry.get("total_completions", 1) if user_entry else 1,
                "achieved_at": user_entry.get("achieved_at") if user_entry else None,
            },
            "nearby_riders": nearby_riders,
            "motivation_message": motivation.get("motivation_message", ""),
            "next_rank_wallet": motivation.get("next_rank_wallet"),
            "behind_rank_wallet": motivation.get("behind_rank_wallet"),
        }
