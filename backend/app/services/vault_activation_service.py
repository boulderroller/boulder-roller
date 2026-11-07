"""
Vault Activation Service

Orchestrates on-chain seeding and activation of vaults after the backfill
service has populated historical completions in the database.

Flow:
    Backfill Complete (vault_completions populated)
        -> Seed completion summary on-chain (admin_seed_vault_completion_summary)
        -> Seed Record Board on-chain from vault_completions (admin_replace_vault_leaderboard)
        -> Activate vault on-chain (admin_activate_vault)
        -> Update DB with tx signatures and status

Lifecycle states (in indexed_vaults.on_chain_seeding_status):
    pending -> seeding -> seeded -> activating -> active
                   |          |            |
                   v          v            v
                 failed     failed       failed (partial: seeded but not active)

All on-chain operations use submit_and_confirm() for priority fees, retries,
and tx_lifecycle tracking. Seed instructions require vault_activation.is_active
== false; the activate instruction flips it to true (one-way).
"""

from __future__ import annotations

from .privacy_logging import scrub_log_text
import asyncio
import hashlib
import logging
import struct
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from solders.keypair import Keypair
from solders.pubkey import Pubkey
from supabase import Client

from ..generated_program_version import PROGRAM_VERSION_FAMILY
from ..solana_direct import (
    make_admin_activate_vault_ix,
    make_admin_replace_vault_leaderboard_ix,
    make_admin_seed_vault_completion_summary_ix,
)
from .solana_submit import TxResult, submit_and_confirm
from .vault_completion_evidence import (
    build_vault_completion_evidence_hash,
    normalize_signature_hash,
)
from .vault_activation_policy import REWARD_AUTHORITATIVE_SEED_GENERATION
from ..utils.postgrest_paging import PageCursor, order_by

logger = logging.getLogger(__name__)

# Rate-limit delay between vaults when processing batch (seconds)
INTER_VAULT_DELAY_S = 2.5
ACTIVATION_EVIDENCE_DOMAIN = b"BR_VAULT_ACTIVATION_V1"


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class SeedingResult:
    """Outcome of seeding and activating a single vault."""

    vault_id: int
    vault_name: str
    success: bool
    seed_tx: Optional[str] = None
    leaderboard_tx: Optional[str] = None
    activate_tx: Optional[str] = None
    error: Optional[str] = None
    duration_ms: int = 0


@dataclass(frozen=True)
class SeedCompletion:
    """Validated historical completion included in an activation bundle."""

    wallet: str
    user_pubkey: Pubkey
    activity_id: str
    completed_at: int
    time_s: int


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class VaultActivationService:
    """
    Service for seeding historical data on-chain and activating vaults.

    After VaultBackfillService populates vault_completions in the database,
    this service derives one-time seed state, submits it to the Solana program
    via admin instructions, and then activates the vault so live operations
    (staking, earning, etc.) are unblocked.

    Usage:
        service = VaultActivationService(
            supabase_client=db,
            authority_keypair=payer,
            program_id=Pubkey.from_string("6ciJ..."),
        )
        result = await service.seed_and_activate_vault(vault_id=42, vault_signature_hex="ab12...")
    """

    def __init__(
        self,
        supabase_client: Client,
        authority_keypair: Keypair,
        fee_payer_keypair: Optional[Keypair],
        program_id: Pubkey,
    ):
        self.db = supabase_client
        self.authority = authority_keypair
        self.fee_payer = fee_payer_keypair or authority_keypair
        self.program_id = program_id

    def _submission_signers(self) -> list[Keypair]:
        """Return the signer set needed for admin submissions."""
        signers = [self.authority]
        if self.fee_payer.pubkey() != self.authority.pubkey():
            signers.append(self.fee_payer)
        return signers

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    async def seed_and_activate_vault(
        self,
        vault_id: int,
        vault_signature_hex: str,
    ) -> SeedingResult:
        """Verify a generation-2 activation or fail closed.

        Historical generation-1 execution has been removed. This compatibility
        API can verify sealed generation-2 evidence but cannot create it; the
        ratified V4-B path starts from a clean program.
        """
        start_time = time.perf_counter()

        if PROGRAM_VERSION_FAMILY == "V4-B":
            return SeedingResult(
                vault_id=vault_id,
                vault_name=f"vault-{vault_id}",
                success=False,
                error=(
                    "legacy seed/activate is disabled for V4-B; "
                    "activation requires the exact finalized Climb/Vault binding"
                ),
                duration_ms=int((time.perf_counter() - start_time) * 1000),
            )

        # Resolve vault name for logging/result
        vault = self._get_vault(vault_id)
        vault_name = vault.get("name", f"vault-{vault_id}") if vault else f"vault-{vault_id}"

        logger.info(
            "[VaultActivation] Verifying activation authority for vault %d (%s)",
            vault_id,
            vault_name,
        )

        try:
            # 1. Check current status
            current_status = vault.get("on_chain_seeding_status", "pending") if vault else "pending"
            seed_manifest = self._get_seed_manifest_v2(vault_id)
            if current_status == "active":
                manifest_hash = (
                    str(seed_manifest.get("evidence_hash") or "").removeprefix("\\x")
                    if seed_manifest
                    else ""
                )
                activation_hash = str(
                    vault.get("activation_evidence_hash") or ""
                ).removeprefix("\\x")
                activation_generation = int(
                    vault.get("activation_seed_generation") or 0
                )
                if (
                    seed_manifest is None
                    or seed_manifest.get("state") != "activated"
                    or activation_generation < REWARD_AUTHORITATIVE_SEED_GENERATION
                    or not manifest_hash
                    or manifest_hash != activation_hash
                ):
                    error = (
                        "legacy activation is not reward-authoritative; "
                        "a sealed generation-2 manifest and matching activation hash are required"
                    )
                    logger.error("[VaultActivation] Vault %d: %s", vault_id, error)
                    return SeedingResult(
                        vault_id=vault_id,
                        vault_name=vault_name,
                        success=False,
                        error=error,
                        duration_ms=int((time.perf_counter() - start_time) * 1000),
                    )
                logger.info(
                    "[VaultActivation] Vault %d already active with verified V2 evidence",
                    vault_id,
                )
                return SeedingResult(
                    vault_id=vault_id,
                    vault_name=vault_name,
                    success=True,
                    duration_ms=int((time.perf_counter() - start_time) * 1000),
                )

            if seed_manifest is None:
                error = (
                    "sealed historical seed manifest V2 is required before one-way activation"
                )
                self._update_seeding_failed(vault_id, error)
                return SeedingResult(
                    vault_id=vault_id,
                    vault_name=vault_name,
                    success=False,
                    error=error,
                    duration_ms=int((time.perf_counter() - start_time) * 1000),
                )

            error = (
                "historical seed manifest V2 execution is not implemented; "
                "use the ratified clean V4-B deployment path"
            )
            self._update_seeding_failed(vault_id, error)
            return SeedingResult(
                vault_id=vault_id,
                vault_name=vault_name,
                success=False,
                error=error,
                duration_ms=int((time.perf_counter() - start_time) * 1000),
            )

        except Exception as e:
            logger.error(
                "[VaultActivation] Unexpected error for vault %d: %s",
                vault_id,
                e,
                exc_info=True,
            )
            self._update_seeding_failed(vault_id, str(e))

            return SeedingResult(
                vault_id=vault_id,
                vault_name=vault_name,
                success=False,
                error=str(e),
                duration_ms=int((time.perf_counter() - start_time) * 1000),
            )

    async def seed_and_activate_all_pending(self) -> List[SeedingResult]:
        """
        Find all vaults with backfill_status='completed' and
        on_chain_seeding_status in ('pending', 'seeded', 'failed')
        and process them sequentially with rate limiting.

        Returns:
            List of SeedingResult for each processed vault
        """
        # Query vaults ready for on-chain seeding
        result = self.db.from_("indexed_vaults") \
            .select("id, signature_hex, name, on_chain_seeding_status") \
            .eq("backfill_status", "completed") \
            .in_("on_chain_seeding_status", ["pending", "seeded", "failed"]) \
            .order("id") \
            .execute()

        pending_vaults = result.data or []

        if not pending_vaults:
            logger.info("[VaultActivation] No pending vaults found for seeding")
            return []

        logger.info(
            "[VaultActivation] Found %d vaults pending on-chain seeding",
            len(pending_vaults),
        )

        results: List[SeedingResult] = []

        for i, vault_row in enumerate(pending_vaults):
            vault_id = vault_row["id"]
            signature_hex = vault_row["signature_hex"]

            seeding_result = await self.seed_and_activate_vault(
                vault_id=vault_id,
                vault_signature_hex=signature_hex,
            )
            results.append(seeding_result)

            status_label = "OK" if seeding_result.success else "FAILED"
            logger.info(
                "[VaultActivation] [%d/%d] Vault %d: %s",
                i + 1,
                len(pending_vaults),
                vault_id,
                status_label,
            )

            # Rate limit between vaults to avoid RPC throttling
            if i < len(pending_vaults) - 1:
                await asyncio.sleep(INTER_VAULT_DELAY_S)

        # Summary
        succeeded = sum(1 for r in results if r.success)
        failed = sum(1 for r in results if not r.success)
        logger.info(
            "[VaultActivation] Batch complete: %d succeeded, %d failed out of %d",
            succeeded,
            failed,
            len(results),
        )

        return results

    async def get_seeding_status(self, vault_id: int) -> dict:
        """
        Return current on-chain seeding state for a vault.

        Returns dict with keys:
            vault_id, on_chain_seeding_status, on_chain_seed_tx,
            on_chain_leaderboard_tx, on_chain_activate_tx,
            on_chain_seeded_at, on_chain_activated_at, on_chain_seeding_error
        """
        result = self.db.from_("indexed_vaults") \
            .select(
                "id, name, on_chain_seeding_status, "
                "on_chain_seed_tx, on_chain_leaderboard_tx, on_chain_activate_tx, "
                "on_chain_seeded_at, on_chain_activated_at, on_chain_seeding_error, "
                "activation_seed_generation, activation_seed_cutoff_at, "
                "activation_matched_users, activation_matched_completions, "
                "activation_evidence_hash"
            ) \
            .eq("id", vault_id) \
            .execute()

        if not result.data:
            return {"vault_id": vault_id, "error": "vault not found"}

        row = result.data[0]
        return {
            "vault_id": row["id"],
            "vault_name": row.get("name"),
            "on_chain_seeding_status": row.get("on_chain_seeding_status", "pending"),
            "on_chain_seed_tx": row.get("on_chain_seed_tx"),
            "on_chain_leaderboard_tx": row.get("on_chain_leaderboard_tx"),
            "on_chain_activate_tx": row.get("on_chain_activate_tx"),
            "on_chain_seeded_at": row.get("on_chain_seeded_at"),
            "on_chain_activated_at": row.get("on_chain_activated_at"),
            "on_chain_seeding_error": row.get("on_chain_seeding_error"),
            "activation_seed_generation": row.get("activation_seed_generation"),
            "activation_seed_cutoff_at": row.get("activation_seed_cutoff_at"),
            "activation_matched_users": row.get("activation_matched_users"),
            "activation_matched_completions": row.get("activation_matched_completions"),
            "activation_evidence_hash": row.get("activation_evidence_hash"),
        }

    # =========================================================================
    # TRANSACTION SUBMISSION (private)
    # =========================================================================

    async def _submit_seed_summary(
        self,
        vault_id: int,
        total_completions: int,
        best_time_s: int,
        best_time_holder: Pubkey,
    ) -> TxResult:
        """Build and submit admin_seed_vault_completion_summary instruction."""
        ix = make_admin_seed_vault_completion_summary_ix(
            authority=self.authority.pubkey(),
            vault_id=vault_id,
            total_completions=total_completions,
            best_time_s=best_time_s,
            best_time_holder=best_time_holder,
            program_id=self.program_id,
        )

        return await submit_and_confirm(
            instructions=[ix],
            signers=self._submission_signers(),
            fee_payer=self.fee_payer.pubkey(),
            tx_type="admin_seed_vault_completion_summary",
            reference_type="vault",
            reference_id=str(vault_id),
        )

    async def _submit_leaderboard_seed(
        self,
        vault_id: int,
        entries: list[tuple[Pubkey, int, int]],
    ) -> TxResult:
        """Build and submit admin_replace_vault_leaderboard instruction."""
        ix = make_admin_replace_vault_leaderboard_ix(
            authority=self.authority.pubkey(),
            vault_id=vault_id,
            entries=entries,
            program_id=self.program_id,
        )

        return await submit_and_confirm(
            instructions=[ix],
            signers=self._submission_signers(),
            fee_payer=self.fee_payer.pubkey(),
            tx_type="admin_replace_vault_leaderboard",
            reference_type="vault",
            reference_id=str(vault_id),
        )

    async def _submit_activate(
        self,
        vault_id: int,
        total_completions: int,
        kom_holder: Pubkey,
        kom_time_s: int,
        kom_recorded_at: int,
        seed_generation: int,
        seed_cutoff_at: int,
        matched_users: int,
        matched_completions: int,
        evidence_hash: bytes,
    ) -> TxResult:
        """Build and submit admin_activate_vault instruction."""
        ix = make_admin_activate_vault_ix(
            authority=self.authority.pubkey(),
            vault_id=vault_id,
            total_completions=total_completions,
            kom_holder=kom_holder,
            kom_time_s=kom_time_s,
            kom_recorded_at=kom_recorded_at,
            seed_generation=seed_generation,
            seed_cutoff_at=seed_cutoff_at,
            matched_users=matched_users,
            matched_completions=matched_completions,
            evidence_hash=evidence_hash,
            program_id=self.program_id,
        )

        return await submit_and_confirm(
            instructions=[ix],
            signers=self._submission_signers(),
            fee_payer=self.fee_payer.pubkey(),
            tx_type="admin_activate_vault",
            reference_type="vault",
            reference_id=str(vault_id),
        )

    # =========================================================================
    # DATABASE QUERIES (private)
    # =========================================================================

    def _get_vault(self, vault_id: int) -> Optional[dict]:
        """Get vault row from indexed_vaults."""
        result = self.db.from_("indexed_vaults") \
            .select("*") \
            .eq("id", vault_id) \
            .execute()
        return result.data[0] if result.data else None

    def _get_seed_manifest_v2(self, vault_id: int) -> Optional[dict]:
        """Load sealed V2 activation evidence, failing closed when unavailable."""
        try:
            result = self.db.from_("vault_activation_seed_manifests") \
                .select("vault_id, seed_generation, state, evidence_hash") \
                .eq("vault_id", vault_id) \
                .eq("seed_generation", REWARD_AUTHORITATIVE_SEED_GENERATION) \
                .limit(1) \
                .execute()
        except Exception as exc:
            logger.warning(
                "[VaultActivation] V2 seed manifest unavailable for vault %d: %s",
                vault_id,
                exc,
            )
            return None
        return result.data[0] if result.data else None

    def _get_seed_completions(self, vault_signature: str) -> list[SeedCompletion]:
        """Load validated historical rows that can be committed on-chain."""
        raw_rows: list[dict] = []
        page_size = 1000
        pages = PageCursor(page_size)

        while True:
            query = self.db.from_("vault_completions") \
                .select("id, wallet, activity_id, time_seconds, completed_at") \
                .eq("vault_signature", vault_signature) \
                .eq("validated", True)
            result = order_by(query, "completed_at", "activity_id", "id") \
                .range(pages.offset, pages.offset + page_size - 1) \
                .execute()

            batch = result.data or []
            raw_rows.extend(batch)
            if not pages.advance(batch):  # range() is end-exclusive; see postgrest_paging.
                break

        completions: list[SeedCompletion] = []
        for row in raw_rows:
            wallet = row.get("wallet")
            user_pubkey = self._wallet_to_pubkey(wallet, context="seed_completion")
            if user_pubkey is None:
                continue

            raw_time = row.get("time_seconds")
            if raw_time is None:
                continue

            time_s = int(raw_time)
            completed_at = self._parse_to_unix(row.get("completed_at"))
            if time_s <= 0 or completed_at <= 0:
                continue

            activity_id = str(row.get("activity_id") or row.get("id") or "")
            completions.append(
                SeedCompletion(
                    wallet=str(wallet),
                    user_pubkey=user_pubkey,
                    activity_id=activity_id,
                    completed_at=completed_at,
                    time_s=time_s,
                )
            )

        completions.sort(
            key=lambda c: (c.time_s, c.completed_at, c.wallet, c.activity_id)
        )
        logger.info(
            "[VaultActivation] Seed material for %s: %d validated completions",
            vault_signature[:16] + "...",
            len(completions),
        )
        return completions

    def _summarize_seed_completions(
        self,
        completions: list[SeedCompletion],
    ) -> tuple[int, int, Pubkey, int]:
        """
        Return chain-finalized completion count and KOM state.

        Empty seeds are valid for quiet climbs: they activate with no KOM and a
        zero completion count, but still commit a non-zero activation bundle hash.
        """
        if not completions:
            return 0, 0, Pubkey.default(), 0

        best = completions[0]
        return len(completions), best.time_s, best.user_pubkey, best.completed_at

    @staticmethod
    def _leaderboard_entries_from_seed(
        completions: list[SeedCompletion],
    ) -> list[tuple[Pubkey, int, int]]:
        """Build deterministic top-10 unique-rider historical entries."""
        best_by_rider: dict[Pubkey, SeedCompletion] = {}
        for completion in completions:
            current = best_by_rider.get(completion.user_pubkey)
            if current is None or (
                completion.time_s,
                completion.completed_at,
                completion.activity_id,
            ) < (
                current.time_s,
                current.completed_at,
                current.activity_id,
            ):
                best_by_rider[completion.user_pubkey] = completion

        ordered = sorted(
            best_by_rider.values(),
            key=lambda completion: (
                completion.time_s,
                completion.completed_at,
                bytes(completion.user_pubkey),
            ),
        )
        return [
            (
                completion.user_pubkey,
                completion.time_s,
                completion.completed_at,
            )
            for completion in ordered[:10]
        ]

    @staticmethod
    def _seed_cutoff_at(completions: list[SeedCompletion]) -> int:
        """Ride-time upper bound included in this activation seed."""
        if completions:
            return max(completion.completed_at for completion in completions)
        return int(datetime.now(timezone.utc).timestamp())

    def _build_activation_evidence_hash(
        self,
        vault_id: int,
        vault_signature: str,
        seed_generation: int,
        seed_cutoff_at: int,
        completions: list[SeedCompletion],
    ) -> bytes:
        signature_hash = normalize_signature_hash(vault_signature)
        completion_hashes = sorted(
            self._completion_evidence_hash(completion, vault_id, signature_hash)
            for completion in completions
        )

        hasher = hashlib.sha256()
        hasher.update(ACTIVATION_EVIDENCE_DOMAIN)
        hasher.update(
            struct.pack(
                "<QIqI",
                vault_id,
                seed_generation,
                seed_cutoff_at,
                len(completion_hashes),
            )
        )
        for evidence_hash in completion_hashes:
            hasher.update(evidence_hash)
        return hasher.digest()

    @staticmethod
    def _completion_evidence_hash(
        completion: SeedCompletion,
        vault_id: int,
        signature_hash: bytes,
    ) -> bytes:
        return build_vault_completion_evidence_hash(
            wallet=completion.user_pubkey,
            vault_id=vault_id,
            activity_id=completion.activity_id,
            completed_at=completion.completed_at,
            time_s=completion.time_s,
            signature_hash=signature_hash,
        )

    # =========================================================================
    # DATABASE UPDATES (private)
    # =========================================================================

    def _update_seeding_status(
        self,
        vault_id: int,
        status: str,
        seed_tx: Optional[str] = None,
        leaderboard_tx: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Update on-chain seeding status columns on indexed_vaults."""
        update_data: dict = {
            "on_chain_seeding_status": status,
        }
        if seed_tx is not None:
            update_data["on_chain_seed_tx"] = seed_tx
        if leaderboard_tx is not None:
            update_data["on_chain_leaderboard_tx"] = leaderboard_tx
        if status == "seeded":
            update_data["on_chain_seeded_at"] = datetime.now(timezone.utc).isoformat()
        if error is not None:
            update_data["on_chain_seeding_error"] = error
        else:
            # Clear error on successful status transitions
            update_data["on_chain_seeding_error"] = None

        self.db.from_("indexed_vaults") \
            .update(update_data) \
            .eq("id", vault_id) \
            .execute()

    def _update_seeding_failed(
        self,
        vault_id: int,
        error: str,
        seed_tx: Optional[str] = None,
    ) -> None:
        """Mark vault seeding as failed with error message."""
        update_data: dict = {
            "on_chain_seeding_status": "failed",
            "on_chain_seeding_error": error,
        }
        if seed_tx is not None:
            update_data["on_chain_seed_tx"] = seed_tx

        self.db.from_("indexed_vaults") \
            .update(update_data) \
            .eq("id", vault_id) \
            .execute()

    def _update_seeding_active(
        self,
        vault_id: int,
        seed_tx: Optional[str] = None,
        leaderboard_tx: Optional[str] = None,
        activate_tx: Optional[str] = None,
        seed_generation: Optional[int] = None,
        seed_cutoff_at: Optional[int] = None,
        matched_users: Optional[int] = None,
        matched_completions: Optional[int] = None,
        evidence_hash: Optional[bytes] = None,
    ) -> None:
        """Mark vault as fully active with all tx signatures."""
        now = datetime.now(timezone.utc).isoformat()
        update_data: dict = {
            "on_chain_seeding_status": "active",
            "on_chain_activated_at": now,
            "on_chain_seeding_error": None,
        }
        if seed_tx is not None:
            update_data["on_chain_seed_tx"] = seed_tx
        if leaderboard_tx is not None:
            update_data["on_chain_leaderboard_tx"] = leaderboard_tx
        if activate_tx is not None:
            update_data["on_chain_activate_tx"] = activate_tx
        if seed_generation is not None:
            update_data["activation_seed_generation"] = seed_generation
        if seed_cutoff_at is not None:
            update_data["activation_seed_cutoff_at"] = seed_cutoff_at
        if matched_users is not None:
            update_data["activation_matched_users"] = matched_users
        if matched_completions is not None:
            update_data["activation_matched_completions"] = matched_completions
        if evidence_hash is not None:
            update_data["activation_evidence_hash"] = evidence_hash.hex()

        self.db.from_("indexed_vaults") \
            .update(update_data) \
            .eq("id", vault_id) \
            .execute()

    # =========================================================================
    # HELPERS (private)
    # =========================================================================

    @staticmethod
    def _wallet_to_pubkey(
        wallet: Optional[str],
        context: str = "",
    ) -> Optional[Pubkey]:
        """
        Convert a wallet address string to a Solders Pubkey.

        Returns None (with warning log) if the wallet is missing or invalid.
        Callers that require a non-None Pubkey should fall back to the
        authority pubkey.
        """
        if not wallet:
            logger.warning(
                "[VaultActivation] Missing wallet for %s, will use authority fallback",
                context,
            )
            return None

        try:
            return Pubkey.from_string(wallet)
        except Exception as e:
            logger.warning(
                "[VaultActivation] Invalid wallet '%s' for %s: %s",
                "[redacted]",
                context,
                scrub_log_text(e),
            )
            return None

    @staticmethod
    def _parse_to_unix(timestamp_value) -> int:
        """
        Parse a DB timestamp (ISO string or datetime) to a Unix timestamp (i64).

        Returns 0 if the value is missing or unparseable.
        """
        if timestamp_value is None:
            return 0

        if isinstance(timestamp_value, (int, float)):
            return int(timestamp_value)

        try:
            dt = datetime.fromisoformat(
                str(timestamp_value).replace("Z", "+00:00")
            )
            return int(dt.timestamp())
        except (ValueError, TypeError):
            return 0
