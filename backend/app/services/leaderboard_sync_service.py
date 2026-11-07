"""
Leaderboard Projection Verifier

Verifies that the database's ``vault_leaderboards`` projection cache agrees
with the authoritative on-chain ``VaultLeaderboard`` PDA. Reports drift. Does
not — and must not — write DB state back to chain.

Arrow of truth (per BACKEND_TRUTHS §10.1 / §10.3 and PROTOCOL_TRUTHS §5.1):

    chain (VaultLeaderboard PDA)  ->  indexer projection (indexed_leaderboards)
                                  ->  read-layer cache (vault_leaderboards)
                                  ->  rider-facing views

    The chain is authoritative. Projection may lag, may stutter, may be
    rebuilt. Projection is NEVER authoritative over the chain.

    If the projection falls out of sync, the repair is to re-index from
    on-chain state (BACKEND_TRUTHS §10.3). The repair is NEVER to push DB
    state back to chain. This service surfaces drift; it does not reconcile
    it by mutating the chain.

Historical context (why this file existed with the inverted framing):

    An earlier design treated the DB's ``vault_leaderboards`` table as the
    source of truth and imagined a future ``admin_update_leaderboard``
    instruction that would push DB state onto the ``VaultLeaderboard`` PDA.
    That instruction was never built, by design — the chain already owns
    leaderboard truth. Today:

    * Receipt-backed ``record_climb_completion`` writes ``VaultLeaderboard``
      directly via ``leaderboard.update_entry(...)``. The receipt-less ABI
      compatibility entry fails closed.
    * ``distribute_epoch_rewards`` reads the on-chain PDA directly for
      Record Royalty payout — it never touches DB.
    * The only DB->chain instruction (``admin_replace_vault_leaderboard``)
      is gated on ``!activation.is_active`` and exists solely for historical
      pre-activation seeding from Strava imports.

    This service therefore never had a write path to chain. What it actually
    did was compare DB cache vs chain and log mismatches. The original
    framing was cargo-cult under the inverted model. This docstring
    restores TRUTHS-coherent framing while preserving the verification /
    observability behavior.

Recovery plan when chain fields change (0uv8 and successors):

    If ``VaultLeaderboard`` on-chain layout shifts (entry struct size,
    added fields, sort order, etc.), the two touchpoints to update are:
      1. ``_parse_vault_leaderboard`` in this module — byte layout must
         mirror ``VaultLeaderboard`` in ``protocol/anchor/programs/boulder_rollers/src/model.rs``.
      2. ``indexer/src/writers/leaderboard.ts`` — the canonical chain->DB
         projector that populates ``indexed_leaderboards``.

    Under TRUTHS §10.3, fixing drift here means fixing the projection
    parsers, not writing DB->chain. A future reindex pass from chain
    state is the authoritative repair.

Usage:
    from .leaderboard_sync_service import LeaderboardSyncService

    verifier = LeaderboardSyncService(supabase_client)
    result = await verifier.sync_vault_leaderboard(vault_id)
    # ``result.status`` is one of: synced (DB agrees with chain),
    # mismatch_detected (drift observed, logged for operator),
    # skipped (no DB entries to verify), failed (I/O error).
"""

from __future__ import annotations

import logging
import struct
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solders.pubkey import Pubkey
from supabase import Client

logger = logging.getLogger(__name__)


# On-chain constants (must match lib.rs)
VAULT_LEADERBOARD_SEED = b"vault_leaderboard"
VAULT_SEED = b"vault"


@dataclass
class LeaderboardEntry:
    """A single leaderboard entry."""
    rank: int
    wallet: str
    best_time_seconds: int
    avg_power_w: Optional[int] = None
    achieved_at: Optional[str] = None


@dataclass
class OnchainLeaderEntry:
    """On-chain leaderboard entry (from VaultLeaderboard PDA)."""
    user: str  # Pubkey as string
    time_s: int
    recorded_at: int  # Unix timestamp


@dataclass
class SyncResult:
    """Result of a leaderboard sync operation."""
    vault_id: int
    vault_signature: str
    status: str  # synced, failed, skipped, mismatch_detected
    entries_synced: int = 0
    tx_signature: Optional[str] = None
    error: Optional[str] = None
    db_state: List[Dict[str, Any]] = field(default_factory=list)
    onchain_state: List[Dict[str, Any]] = field(default_factory=list)
    sync_type: str = "manual"


def _derive_vault_pda(vault_id: int, program_id: Pubkey) -> tuple[Pubkey, int]:
    """Derive vault PDA from vault ID."""
    return Pubkey.find_program_address(
        [VAULT_SEED, struct.pack("<Q", vault_id)],
        program_id
    )


def _derive_vault_leaderboard_pda(vault_id: int, program_id: Pubkey) -> tuple[Pubkey, int]:
    """Derive VaultLeaderboard PDA from vault ID."""
    return Pubkey.find_program_address(
        [VAULT_LEADERBOARD_SEED, struct.pack("<Q", vault_id)],
        program_id
    )


def _parse_vault_leaderboard(data: bytes) -> Optional[Dict[str, Any]]:
    """
    Parse VaultLeaderboard account data.

    Layout (from lib.rs):
        - 8 bytes: discriminator
        - 8 bytes: vault_id (u64)
        - 4 bytes: entries length (Vec prefix)
        - N * (32 + 4 + 8) bytes: LeaderEntry array (user: Pubkey, time_s: u32, recorded_at: i64)
        - 8 bytes: last_updated (i64)
        - 1 byte: bump
    """
    if len(data) < 8 + 8 + 4:
        return None

    offset = 8  # Skip discriminator
    vault_id = struct.unpack("<Q", data[offset:offset + 8])[0]
    offset += 8

    # Vec prefix: 4-byte length
    entries_len = struct.unpack("<I", data[offset:offset + 4])[0]
    offset += 4

    entries = []
    entry_size = 32 + 4 + 8  # Pubkey + u32 + i64

    for _ in range(entries_len):
        if offset + entry_size > len(data):
            break
        user = Pubkey.from_bytes(data[offset:offset + 32])
        offset += 32
        time_s = struct.unpack("<I", data[offset:offset + 4])[0]
        offset += 4
        recorded_at = struct.unpack("<q", data[offset:offset + 8])[0]
        offset += 8

        entries.append(OnchainLeaderEntry(
            user=str(user),
            time_s=time_s,
            recorded_at=recorded_at,
        ))

    # Sort entries by time_s for comparison
    entries.sort(key=lambda e: e.time_s)

    last_updated = struct.unpack("<q", data[offset:offset + 8])[0] if offset + 8 <= len(data) else 0
    offset += 8
    bump = data[offset] if offset < len(data) else 0

    return {
        "vault_id": vault_id,
        "entries": entries,
        "last_updated": last_updated,
        "bump": bump,
    }


class LeaderboardSyncService:
    """
    Verifies DB leaderboard cache against the authoritative on-chain PDA.

    The service is a **projection verifier** (BACKEND_TRUTHS §5.3, §10.1).
    It reads both DB cache and chain state, compares them, and records any
    drift for operator visibility. It does not write DB state onto chain —
    the chain is authoritative (§10.1) and projection repair happens via
    reindex from chain state (§10.3).

    Flow:
      1. Read current DB cache row (``vault_leaderboards`` projection).
      2. Read current on-chain ``VaultLeaderboard`` PDA (authoritative).
      3. Compare. Record ``status`` of ``synced`` / ``mismatch_detected`` /
         ``skipped`` / ``failed``.
      4. Log the comparison into ``leaderboard_sync_log`` for audit.

    The class name and ``sync_vault_leaderboard`` method name are kept for
    call-site back-compat. Semantically they are verify/check operations,
    not writes-to-chain. See the module docstring for the historical
    context and the recovery plan for chain-field shifts.
    """

    def __init__(
        self,
        supabase_client: Client,
        rpc_url: Optional[str] = None,
        program_id: Optional[str] = None,
    ):
        self.db = supabase_client
        self._rpc_url = rpc_url
        self._program_id = program_id
        self._config = None

    def _get_config(self):
        """Lazy-load Solana config."""
        if self._config is None:
            from ..solana_direct import load_default_config
            self._config = load_default_config()
        return self._config

    async def get_db_leaderboard(self, vault_signature: str) -> List[LeaderboardEntry]:
        """Get leaderboard entries from database."""
        result = self.db.from_("vault_leaderboards") \
            .select("rank, wallet, best_time_seconds, avg_power_w, achieved_at") \
            .eq("vault_signature", vault_signature) \
            .order("rank") \
            .execute()

        entries = []
        for row in (result.data or []):
            entries.append(LeaderboardEntry(
                rank=row["rank"],
                wallet=row["wallet"],
                best_time_seconds=row["best_time_seconds"],
                avg_power_w=row.get("avg_power_w"),
                achieved_at=row.get("achieved_at"),
            ))
        return entries

    async def get_onchain_leaderboard(self, vault_id: int) -> Optional[Dict[str, Any]]:
        """
        Read VaultLeaderboard PDA from chain.

        Returns parsed leaderboard data or None if not found.
        """
        config = self._get_config()
        leaderboard_pda, _ = _derive_vault_leaderboard_pda(vault_id, config.program_id)

        async with AsyncClient(config.rpc_url, commitment=Confirmed) as client:
            account_info = await client.get_account_info(leaderboard_pda)
            if account_info.value is None:
                return None
            return _parse_vault_leaderboard(bytes(account_info.value.data))

    def _compare_leaderboards(
        self,
        db_entries: List[LeaderboardEntry],
        onchain_data: Optional[Dict[str, Any]],
    ) -> tuple[bool, List[Dict[str, Any]]]:
        """
        Compare DB and on-chain leaderboard state.

        Returns:
            (needs_sync, differences) tuple
        """
        if onchain_data is None:
            # On-chain doesn't exist, but DB has entries
            return len(db_entries) > 0, [{"reason": "onchain_not_initialized"}]

        onchain_entries: List[OnchainLeaderEntry] = onchain_data.get("entries", [])

        # Build lookup by wallet
        onchain_by_wallet = {e.user: e for e in onchain_entries}
        db_by_wallet = {e.wallet: e for e in db_entries}

        differences = []

        # Check each DB entry
        for db_entry in db_entries:
            onchain_entry = onchain_by_wallet.get(db_entry.wallet)
            if onchain_entry is None:
                differences.append({
                    "wallet": db_entry.wallet,
                    "reason": "missing_onchain",
                    "db_time": db_entry.best_time_seconds,
                })
            elif onchain_entry.time_s != db_entry.best_time_seconds:
                differences.append({
                    "wallet": db_entry.wallet,
                    "reason": "time_mismatch",
                    "db_time": db_entry.best_time_seconds,
                    "onchain_time": onchain_entry.time_s,
                })

        # Check for entries on-chain that aren't in DB top 10
        for wallet, onchain_entry in onchain_by_wallet.items():
            if wallet not in db_by_wallet:
                differences.append({
                    "wallet": wallet,
                    "reason": "extra_onchain",
                    "onchain_time": onchain_entry.time_s,
                })

        needs_sync = len(differences) > 0
        return needs_sync, differences

    async def sync_vault_leaderboard(
        self,
        vault_id: int,
        vault_signature: Optional[str] = None,
        sync_type: str = "manual",
        triggered_by: str = "system",
    ) -> SyncResult:
        """
        Verify a single vault's DB leaderboard cache against the on-chain PDA.

        Kept named ``sync_vault_leaderboard`` for caller back-compat; the
        operation is strictly read + compare + log. It does not push DB
        state onto chain — the chain is authoritative for leaderboard
        entries (BACKEND_TRUTHS §10.1).

        Process:
        1. Read cached top 10 from ``vault_leaderboards`` (projection).
        2. Read current on-chain ``VaultLeaderboard`` PDA (authoritative).
        3. If the projection and chain differ, emit ``mismatch_detected``
           so the operator knows to reindex from chain (§10.3).
        4. Log the comparison into ``leaderboard_sync_log`` for audit.

        Args:
            vault_id: On-chain vault ID
            vault_signature: 64-byte signature hex (will be looked up if not provided)
            sync_type: Type of check (epoch, manual, verification)
            triggered_by: Who triggered the check (system, admin:<user_id>, api)

        Returns:
            SyncResult with status (``synced`` / ``mismatch_detected`` /
            ``skipped`` / ``failed``) and the two states for audit.
        """
        # Look up vault signature if not provided
        if vault_signature is None:
            vault_resp = self.db.from_("indexed_vaults") \
                .select("signature_hex") \
                .eq("id", vault_id) \
                .limit(1) \
                .execute()
            if not vault_resp.data:
                return SyncResult(
                    vault_id=vault_id,
                    vault_signature="",
                    status="failed",
                    error="Vault not found in indexed_vaults",
                    sync_type=sync_type,
                )
            vault_signature = vault_resp.data[0]["signature_hex"]

        result = SyncResult(
            vault_id=vault_id,
            vault_signature=vault_signature,
            status="pending",
            sync_type=sync_type,
        )

        try:
            # Get DB state
            db_entries = await self.get_db_leaderboard(vault_signature)
            result.db_state = [
                {
                    "rank": e.rank,
                    "wallet": e.wallet,
                    "best_time_seconds": e.best_time_seconds,
                    "avg_power_w": e.avg_power_w,
                    "achieved_at": e.achieved_at,
                }
                for e in db_entries
            ]

            if not db_entries:
                result.status = "skipped"
                result.error = "No leaderboard entries in DB"
                await self._log_sync(result, triggered_by)
                return result

            # Get on-chain state
            onchain_data = await self.get_onchain_leaderboard(vault_id)
            if onchain_data:
                result.onchain_state = [
                    {
                        "wallet": e.user,
                        "time_s": e.time_s,
                        "recorded_at": e.recorded_at,
                    }
                    for e in onchain_data.get("entries", [])
                ]

            # Compare states
            needs_sync, differences = self._compare_leaderboards(db_entries, onchain_data)

            if not needs_sync:
                result.status = "synced"
                result.entries_synced = len(db_entries)
                await self._log_sync(result, triggered_by)
                await self._mark_vault_synced(vault_id, None)
                return result

            # Log differences for debugging
            logger.info(
                f"[LeaderboardSync] Vault {vault_id} needs sync: {len(differences)} differences"
            )
            for diff in differences[:5]:  # Log first 5 differences
                logger.debug(f"[LeaderboardSync] Difference: {diff}")

            # Mark the drift for operator visibility. Per BACKEND_TRUTHS §10.3
            # the repair is to re-index from on-chain state — NOT to write DB
            # state onto chain. The on-chain leaderboard is authoritative and
            # is updated exclusively by receipt-backed
            # ``record_climb_completion`` on successful rides. No
            # ``admin_update_leaderboard`` instruction exists, and none should
            # — reconciliation via backend writes would invert the arrow of
            # truth (§10.1).
            result.status = "mismatch_detected"
            result.entries_synced = 0
            result.error = f"{len(differences)} entries differ between DB and on-chain"

            # Mark vault sync status
            self.db.from_("indexed_vaults") \
                .update({
                    "onchain_sync_status": "mismatch_detected",
                }) \
                .eq("id", vault_id) \
                .execute()

            await self._log_sync(result, triggered_by)
            return result

        except Exception as e:
            logger.error(f"[LeaderboardSync] Error syncing vault {vault_id}: {e}")
            result.status = "failed"
            result.error = str(e)
            await self._log_sync(result, triggered_by)
            return result

    async def sync_all_active_vaults(
        self,
        epoch: Optional[int] = None,
        since: Optional[datetime] = None,
    ) -> List[SyncResult]:
        """
        Verify the DB leaderboard cache against the on-chain PDA for every
        vault that has had recent activity.

        Pure read-layer observability: compares projection vs chain for each
        vault and records the result per `BACKEND_TRUTHS` §10.1 / §10.3. Does
        not write DB->chain. Used by the epoch processor as a pre-
        distribution sanity check, and by the admin route / celery task for
        ad-hoc audits.

        Args:
            epoch: Current epoch (for logging)
            since: Only check vaults with activity since this time

        Returns:
            List of SyncResult for each vault processed.
        """
        # Get vaults needing sync
        try:
            if since:
                vaults_resp = self.db.rpc(
                    "get_vaults_needing_sync",
                    {"p_since": since.isoformat()}
                ).execute()
            else:
                vaults_resp = self.db.rpc(
                    "get_vaults_needing_sync",
                    {"p_since": None}
                ).execute()

            vaults = vaults_resp.data or []
        except Exception as e:
            logger.warning(f"[LeaderboardSync] Failed to get vaults needing sync: {e}")
            # Fallback: get all vaults with leaderboard entries
            vaults_resp = self.db.from_("vault_leaderboards") \
                .select("vault_signature") \
                .execute()
            unique_sigs = set(row["vault_signature"] for row in (vaults_resp.data or []))
            # Look up vault IDs
            if unique_sigs:
                vaults_resp = self.db.from_("indexed_vaults") \
                    .select("id, signature_hex") \
                    .in_("signature_hex", list(unique_sigs)) \
                    .execute()
                vaults = [
                    {"vault_id": v["id"], "vault_signature": v["signature_hex"]}
                    for v in (vaults_resp.data or [])
                ]
            else:
                vaults = []

        logger.info(f"[LeaderboardSync] Syncing {len(vaults)} vaults for epoch {epoch}")

        results = []
        for vault in vaults:
            vault_id = vault.get("vault_id") or vault.get("id")
            vault_signature = vault.get("vault_signature") or vault.get("signature_hex")

            if vault_id is None:
                continue

            try:
                result = await self.sync_vault_leaderboard(
                    vault_id=vault_id,
                    vault_signature=vault_signature,
                    sync_type="epoch",
                    triggered_by="system",
                )
                results.append(result)
            except Exception as e:
                logger.error(f"[LeaderboardSync] Failed to sync vault {vault_id}: {e}")
                results.append(SyncResult(
                    vault_id=vault_id,
                    vault_signature=vault_signature or "",
                    status="failed",
                    error=str(e),
                    sync_type="epoch",
                ))

        # Summary logging
        synced = sum(1 for r in results if r.status == "synced")
        mismatches = sum(1 for r in results if r.status == "mismatch_detected")
        failed = sum(1 for r in results if r.status == "failed")
        skipped = sum(1 for r in results if r.status == "skipped")

        logger.info(
            f"[LeaderboardSync] Epoch {epoch} sync complete: "
            f"{synced} synced, {mismatches} mismatches, {failed} failed, {skipped} skipped"
        )

        return results

    async def verify_sync(self, vault_id: int) -> Dict[str, Any]:
        """
        Verify DB and on-chain state match without modifying anything.

        Returns:
            Dict with comparison details
        """
        vault_resp = self.db.from_("indexed_vaults") \
            .select("signature_hex") \
            .eq("id", vault_id) \
            .limit(1) \
            .execute()

        if not vault_resp.data:
            return {"error": "Vault not found", "vault_id": vault_id}

        vault_signature = vault_resp.data[0]["signature_hex"]
        db_entries = await self.get_db_leaderboard(vault_signature)
        onchain_data = await self.get_onchain_leaderboard(vault_id)

        needs_sync, differences = self._compare_leaderboards(db_entries, onchain_data)

        return {
            "vault_id": vault_id,
            "vault_signature": vault_signature,
            "in_sync": not needs_sync,
            "db_entries": len(db_entries),
            "onchain_entries": len(onchain_data.get("entries", [])) if onchain_data else 0,
            "differences": differences,
            "db_state": [
                {
                    "rank": e.rank,
                    "wallet": e.wallet,
                    "best_time_seconds": e.best_time_seconds,
                }
                for e in db_entries
            ],
            "onchain_state": [
                {
                    "wallet": e.user,
                    "time_s": e.time_s,
                }
                for e in (onchain_data.get("entries", []) if onchain_data else [])
            ],
        }

    async def _log_sync(self, result: SyncResult, triggered_by: str) -> None:
        """Log sync operation to leaderboard_sync_log."""
        try:
            self.db.from_("leaderboard_sync_log").insert({
                "vault_id": result.vault_id,
                "vault_signature": result.vault_signature,
                "db_state": result.db_state or None,
                "onchain_state": result.onchain_state or None,
                "tx_signature": result.tx_signature,
                "status": result.status,
                "error_message": result.error,
                "entries_synced": result.entries_synced,
                "sync_type": result.sync_type,
                "triggered_by": triggered_by,
            }).execute()
        except Exception as e:
            logger.warning(f"[LeaderboardSync] Failed to log sync: {e}")

    async def _mark_vault_synced(
        self,
        vault_id: int,
        tx_signature: Optional[str],
    ) -> None:
        """Update indexed_vaults sync status."""
        try:
            update_data = {
                "last_onchain_sync_at": datetime.now(timezone.utc).isoformat(),
                "onchain_sync_status": "synced",
            }
            if tx_signature:
                update_data["onchain_sync_tx"] = tx_signature

            self.db.from_("indexed_vaults") \
                .update(update_data) \
                .eq("id", vault_id) \
                .execute()
        except Exception as e:
            logger.warning(f"[LeaderboardSync] Failed to mark vault synced: {e}")


# Singleton for service reuse
_sync_service: Optional[LeaderboardSyncService] = None
_sync_lock = threading.Lock()


def get_leaderboard_sync_service(supabase_client: Client) -> LeaderboardSyncService:
    """Get or create leaderboard sync service singleton (thread-safe)."""
    global _sync_service
    if _sync_service is None:
        with _sync_lock:
            # Double-check locking pattern
            if _sync_service is None:
                _sync_service = LeaderboardSyncService(supabase_client)
    return _sync_service
