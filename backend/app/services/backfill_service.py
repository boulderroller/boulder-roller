"""
Vault Backfill Service

Backfills historical ride data into newly created vaults.

When a vault is created, we need to find all historical rides that match
that climb signature and:
1. Record vault_completions for each match
2. Let vault activation derive any one-time on-chain seed entries from
   those completions
3. Track progress and handle errors

Flow:
    Vault Created -> Queue Backfill Job -> Process Historical Matches
                                                    |
                                                    v
                                     patterns_climb (geographic v2 match)
                                                    |
                                                    v
                                        vault_completions (record)
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from supabase import Client

from ..generated_program_version import PROGRAM_VERSION_FAMILY
from ..repositories.vault import VaultRepository
from .patterns.climb_signature import (
    InvalidRewardGradeCandidate,
    REWARD_GRADE_MIN_SIMILARITY,
    match_reward_grade_v2,
    validate_reward_grade_climb_evidence,
)
from .vault_reward_identity import reconcile_indexed_vault_reward_identity
from ..utils.postgrest_paging import PageCursor

logger = logging.getLogger(__name__)

# Batch size for processing historical matches
BATCH_SIZE = 100
BACKFILL_QUERY_PAGE_SIZE = 1000


@dataclass
class ClimbMatch:
    """A historical climb that matches a vault signature."""
    pattern_id: UUID
    activity_id: UUID
    wallet: str
    time_s: int
    vert_m: float
    signature_hex: str
    avg_power_w: Optional[float]
    completed_at: datetime
    similarity: float
    signature_v2_hex: Optional[str] = None
    start_lat: Optional[float] = None
    start_lon: Optional[float] = None
    end_lat: Optional[float] = None
    end_lon: Optional[float] = None


@dataclass
class BackfillResult:
    """Result of a vault backfill operation."""
    vault_id: int
    vault_signature: str
    status: str  # completed, failed, skipped
    total_candidates: int
    matched_count: int
    leaderboard_updates: int
    skipped_existing: int = 0
    error: Optional[str] = None
    duration_ms: int = 0


def _parse_timestamp(value: Any) -> Optional[datetime]:
    """Parse DB timestamp strings into timezone-aware datetimes."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class VaultBackfillService:
    """
    Service for backfilling historical rides into newly created vaults.

    Usage:
        service = VaultBackfillService(supabase_client)
        result = await service.backfill_vault(vault_id=123, vault_signature="abc...")
    """

    def __init__(self, supabase_client: Client):
        self.db = supabase_client
        self._vault_repo = VaultRepository(supabase_client)

    async def backfill_vault(
        self,
        vault_id: int,
        vault_signature: str,
        job_id: Optional[str] = None,
    ) -> BackfillResult:
        """
        Backfill a single vault from historical ride data.

        Steps:
        1. Mark vault as backfill in_progress
        2. Query patterns_climb through geographic v2 matching
        3. For each match, record completion and update leaderboard
        4. Mark vault as backfill completed with count

        Args:
            vault_id: On-chain vault ID
            vault_signature: Legacy vault identity key used by completion rows;
                matching authority comes from the indexed vault's v2 evidence.
            job_id: Optional job ID for tracking

        Returns:
            BackfillResult with status and counts
        """
        import time
        start_time = time.perf_counter()

        if PROGRAM_VERSION_FAMILY == "V4-B":
            return BackfillResult(
                vault_id=vault_id,
                vault_signature=vault_signature,
                status="failed",
                total_candidates=0,
                matched_count=0,
                leaderboard_updates=0,
                error=(
                    "legacy detector backfill is disabled for V4-B; "
                    "only exact canon traversal may authorize economics"
                ),
                duration_ms=int((time.perf_counter() - start_time) * 1000),
            )

        logger.info(f"[Backfill] Starting backfill for vault {vault_id}")

        try:
            # Mark as in_progress
            if job_id:
                claim_result = self.db.rpc("start_backfill_job", {"p_job_id": job_id}).execute()
                if claim_result.data is False:
                    logger.info(f"[Backfill] Job {job_id} was already claimed or completed; skipping vault {vault_id}")
                    return BackfillResult(
                        vault_id=vault_id,
                        vault_signature=vault_signature,
                        status="skipped",
                        total_candidates=0,
                        matched_count=0,
                        leaderboard_updates=0,
                    )
            else:
                self._update_vault_backfill_status(vault_id, "in_progress")

            # Get vault details for similarity matching
            vault = await self._get_vault(vault_id)
            if not vault:
                raise ValueError(f"Vault {vault_id} not found")
            if str(vault.get("signature_hex") or "") != vault_signature:
                raise ValueError(
                    "backfill v1 key does not match indexed vault identity"
                )

            identity_fields = (
                "signature_v2_hex",
                "start_lat",
                "start_lon",
                "end_lat",
                "end_lon",
            )
            if vault.get("signature_version") != 2 or any(
                vault.get(field) is None for field in identity_fields
            ):
                identity = reconcile_indexed_vault_reward_identity(
                    client=self.db,
                    vault=vault,
                    apply=True,
                )
                vault = {
                    **vault,
                    **identity.as_indexed_vault_patch(),
                }

            # Find historical matches
            vault_signature_v2_hex = vault.get("signature_v2_hex")
            vault_start = (vault.get("start_lat"), vault.get("start_lon"))
            vault_end = (vault.get("end_lat"), vault.get("end_lon"))
            validate_reward_grade_climb_evidence(
                signature_v2_hex=vault_signature_v2_hex,
                start=vault_start,
                end=vault_end,
                label=f"vault {vault_id}",
            )
            matches = await self.find_matching_climbs(
                vault_signature_v2_hex=vault_signature_v2_hex,
                vault_start=vault_start,
                vault_end=vault_end,
            )

            logger.info(f"[Backfill] Found {len(matches)} candidate matches for vault {vault_id}")

            if matches:
                raise RuntimeError(
                    "historical matches require a sealed generation-2 seed manifest; "
                    "receipt-less vault completion projection is disabled"
                )

            # Process matches in batches
            existing_activity_ids = await self._get_existing_activity_ids(vault_signature)
            matched_count = 0
            leaderboard_updates = 0
            skipped_existing = 0
            completion_write_failures: List[str] = []

            for i in range(0, len(matches), BATCH_SIZE):
                batch = matches[i:i + BATCH_SIZE]
                for match in batch:
                    activity_id = str(match.activity_id)
                    if activity_id in existing_activity_ids:
                        skipped_existing += 1
                        continue
                    try:
                        is_recorded, is_leaderboard = await self.process_completion(
                            vault_signature=vault_signature,
                            climb=match,
                        )
                        if is_recorded:
                            matched_count += 1
                            existing_activity_ids.add(activity_id)
                        if is_leaderboard:
                            leaderboard_updates += 1
                    except Exception as e:
                        logger.error(
                            "[Backfill] Completion write failed for pattern %s: %s",
                            match.pattern_id,
                            e,
                        )
                        completion_write_failures.append(str(match.pattern_id))

                # Log progress
                processed = min(i + BATCH_SIZE, len(matches))
                logger.info(f"[Backfill] Vault {vault_id}: processed {processed}/{len(matches)}")

            if completion_write_failures:
                raise RuntimeError(
                    f"{len(completion_write_failures)} completion write failure(s); "
                    "activation withheld"
                )

            # Mark as completed
            duration_ms = int((time.perf_counter() - start_time) * 1000)

            if job_id:
                self.db.rpc("complete_backfill_job", {
                    "p_job_id": job_id,
                    "p_matched_count": matched_count,
                    "p_leaderboard_updates": leaderboard_updates,
                }).execute()
            else:
                self._update_vault_backfill_completed(vault_id, matched_count)

            logger.info(
                f"[Backfill] Completed vault {vault_id}: "
                f"{matched_count} completions, {leaderboard_updates} leaderboard updates, "
                f"{skipped_existing} existing skipped "
                f"({duration_ms}ms)"
            )

            # Trigger on-chain seeding after successful backfill.
            # This is fire-and-forget: activation failure must NOT fail the backfill.
            await self._trigger_vault_activation(vault_id, vault_signature)

            return BackfillResult(
                vault_id=vault_id,
                vault_signature=vault_signature,
                status="completed",
                total_candidates=len(matches),
                matched_count=matched_count,
                leaderboard_updates=leaderboard_updates,
                skipped_existing=skipped_existing,
                duration_ms=duration_ms,
            )

        except Exception as e:
            logger.error(f"[Backfill] Failed for vault {vault_id}: {e}")

            if job_id:
                self.db.rpc("fail_backfill_job", {
                    "p_job_id": job_id,
                    "p_error": str(e),
                }).execute()
            else:
                self._update_vault_backfill_failed(vault_id, str(e))

            duration_ms = int((time.perf_counter() - start_time) * 1000)
            return BackfillResult(
                vault_id=vault_id,
                vault_signature=vault_signature,
                status="failed",
                total_candidates=0,
                matched_count=0,
                leaderboard_updates=0,
                skipped_existing=0,
                error=str(e),
                duration_ms=duration_ms,
            )

    async def find_matching_climbs(
        self,
        vault_signature_v2_hex: str,
        vault_start: Tuple[float, float],
        vault_end: Tuple[float, float],
    ) -> List[ClimbMatch]:
        """Find historical completions through the reward-grade v2 authority."""
        validate_reward_grade_climb_evidence(
            signature_v2_hex=vault_signature_v2_hex,
            start=vault_start,
            end=vault_end,
            label="vault",
        )

        # A self-match validates the frozen checksum and native matcher before
        # an empty candidate set can be mistaken for a successful backfill.
        self_evidence = match_reward_grade_v2(
            query_signature_v2_hex=vault_signature_v2_hex,
            candidate_signature_v2_hex=vault_signature_v2_hex,
            query_start=vault_start,
            query_end=vault_end,
            candidate_start=vault_start,
            candidate_end=vault_end,
        )
        if (
            self_evidence is None
            or self_evidence.similarity < REWARD_GRADE_MIN_SIMILARITY
        ):
            raise ValueError("vault v2 signature failed native self-validation")

        candidate_rows: List[Dict[str, Any]] = []
        pages = PageCursor(BACKFILL_QUERY_PAGE_SIZE)
        while True:
            query = self.db.from_("patterns_climb").select(
                "id, activity_id, wallet, time_s, vert_m, signature_hex, "
                "signature_v2_hex, start_lat, start_lon, end_lat, end_lon, "
                "avg_power_w, economic_eligible, created_at"
            )
            query = query.not_.is_("signature_v2_hex", "null")
            query = query.eq("economic_eligible", True)
            page = (
                query.order("id")
                .range(
                    pages.offset,
                    pages.offset + BACKFILL_QUERY_PAGE_SIZE - 1,
                )
                .execute()
                .data
                or []
            )
            candidate_rows.extend(page)
            if not pages.advance(page):  # range() is end-exclusive; see postgrest_paging.
                break

        candidate_timestamps = await self._get_activity_completion_times(
            [str(row["activity_id"]) for row in candidate_rows]
        )

        matches_by_activity: Dict[str, ClimbMatch] = {}
        for row in candidate_rows:
            if row.get("economic_eligible") is not True:
                continue
            candidate_signature_v2_hex = row.get("signature_v2_hex")
            if not candidate_signature_v2_hex or any(
                row.get(field) is None
                for field in ("start_lat", "start_lon", "end_lat", "end_lon")
            ):
                continue

            try:
                evidence = match_reward_grade_v2(
                    query_signature_v2_hex=vault_signature_v2_hex,
                    candidate_signature_v2_hex=candidate_signature_v2_hex,
                    query_start=vault_start,
                    query_end=vault_end,
                    candidate_start=(row["start_lat"], row["start_lon"]),
                    candidate_end=(row["end_lat"], row["end_lon"]),
                )
            except InvalidRewardGradeCandidate as exc:
                logger.warning(
                    "[Backfill] Skipping malformed candidate %s: %s",
                    row.get("id"),
                    exc,
                )
                continue
            if (
                evidence is None
                or evidence.similarity < REWARD_GRADE_MIN_SIMILARITY
            ):
                continue

            activity_key = str(row["activity_id"])
            completed_at = candidate_timestamps.get(activity_key)
            if completed_at is None:
                raise ValueError(
                    f"matched activity {activity_key} lacks canonical rides.completed_at"
                )
            match = ClimbMatch(
                pattern_id=UUID(str(row["id"])),
                activity_id=UUID(activity_key),
                wallet=row["wallet"],
                time_s=int(row["time_s"]),
                vert_m=float(row["vert_m"]),
                signature_hex=str(row.get("signature_hex") or ""),
                avg_power_w=row.get("avg_power_w"),
                completed_at=completed_at,
                similarity=evidence.similarity,
                signature_v2_hex=candidate_signature_v2_hex,
                start_lat=float(row["start_lat"]),
                start_lon=float(row["start_lon"]),
                end_lat=float(row["end_lat"]),
                end_lon=float(row["end_lon"]),
            )
            previous = matches_by_activity.get(activity_key)
            if previous is None or (match.similarity, -match.time_s) > (
                previous.similarity,
                -previous.time_s,
            ):
                matches_by_activity[activity_key] = match

        matches = list(matches_by_activity.values())
        matches.sort(key=lambda match: (match.time_s, str(match.activity_id)))
        logger.info("[Backfill] Found %d geographic v2 matches", len(matches))
        return matches

    async def process_completion(
        self,
        vault_signature: str,
        climb: ClimbMatch,
    ) -> tuple[bool, bool]:
        """
        Process a single historical completion.

        Record completion evidence only. The chain owns Record Board truth;
        pre-activation seeding derives top-10 entries from vault_completions
        in VaultActivationService instead of writing the DB leaderboard cache.

        Args:
            vault_signature: Vault signature hex
            climb: Historical climb match

        Returns:
            Tuple of (was_recorded, updated_leaderboard). The second value is
            retained for old job telemetry and is always False in the
            projection-only leaderboard model.
        """
        raise RuntimeError(
            "receipt-less historical completions cannot be written to vault_completions; "
            "seal them in the ratified activation manifest instead"
        )

    async def _get_vault(self, vault_id: int) -> Optional[Dict[str, Any]]:
        """Get vault details from indexed_vaults."""
        result = self.db.from_("indexed_vaults") \
            .select("*") \
            .eq("id", vault_id) \
            .execute()
        return result.data[0] if result.data else None

    async def _get_existing_activity_ids(self, vault_signature: str) -> set[str]:
        """Load already-recorded activity IDs so replay reruns stay idempotent."""
        result = self.db.from_("vault_completions") \
            .select("activity_id") \
            .eq("vault_signature", vault_signature) \
            .execute()
        return {
            str(row["activity_id"])
            for row in (result.data or [])
            if row.get("activity_id")
        }

    async def _get_activity_completion_times(self, activity_ids: List[str]) -> Dict[str, datetime]:
        """Resolve ride completion timestamps for a batch of activity IDs."""
        if not activity_ids:
            return {}

        timestamps: Dict[str, datetime] = {}
        unique_ids = list(dict.fromkeys(activity_ids))

        for i in range(0, len(unique_ids), 200):
            batch = unique_ids[i:i + 200]
            result = self.db.from_("rides") \
                .select("id, completed_at") \
                .in_("id", batch) \
                .execute()

            for row in (result.data or []):
                timestamp = _parse_timestamp(row.get("completed_at"))
                if timestamp:
                    timestamps[str(row["id"])] = timestamp

        return timestamps

    async def _trigger_vault_activation(
        self,
        vault_id: int,
        vault_signature: str,
    ) -> None:
        """
        Trigger on-chain seeding and activation for a vault after backfill completes.

        This is a best-effort operation — failures are logged but do not propagate.
        If the Solana keypair or program ID are not configured, the call is skipped
        with a log message. Activation can always be retried via the admin API.
        """
        try:
            from solders.pubkey import Pubkey

            from ..solana_direct import load_backend_authority_keypair, load_default_config
            from ..solana_env import boulder_rollers_program_id
            from .vault_activation_service import VaultActivationService

            authority = load_backend_authority_keypair()
            fee_payer = load_default_config().payer
            program_id = Pubkey.from_string(boulder_rollers_program_id())

            activation_service = VaultActivationService(
                supabase_client=self.db,
                authority_keypair=authority,
                fee_payer_keypair=fee_payer,
                program_id=program_id,
            )

            result = await activation_service.seed_and_activate_vault(
                vault_id=vault_id,
                vault_signature_hex=vault_signature,
            )

            if result.success:
                logger.info(
                    "[Backfill] On-chain activation succeeded for vault %d "
                    "(seed_tx=%s, activate_tx=%s)",
                    vault_id,
                    result.seed_tx,
                    result.activate_tx,
                )
            else:
                logger.warning(
                    "[Backfill] On-chain activation failed for vault %d: %s "
                    "(can be retried via admin API)",
                    vault_id,
                    result.error,
                )

        except Exception as e:
            logger.warning(
                "[Backfill] On-chain activation error for vault %d: %s "
                "(backfill still succeeded, activation can be retried via admin API)",
                vault_id,
                e,
            )

    def _update_vault_backfill_status(self, vault_id: int, status: str) -> None:
        """Update vault backfill status."""
        update_data = {"backfill_status": status}
        if status == "in_progress":
            update_data["backfill_started_at"] = datetime.now(timezone.utc).isoformat()
            update_data["backfill_error"] = None

        self.db.from_("indexed_vaults") \
            .update(update_data) \
            .eq("id", vault_id) \
            .execute()

    def _update_vault_backfill_completed(self, vault_id: int, count: int) -> None:
        """Mark vault backfill as completed."""
        self.db.from_("indexed_vaults") \
            .update({
                "backfill_status": "completed",
                "backfill_completed_at": datetime.now(timezone.utc).isoformat(),
                "backfill_completions_found": count,
            }) \
            .eq("id", vault_id) \
            .execute()

    def _update_vault_backfill_failed(self, vault_id: int, error: str) -> None:
        """Mark vault backfill as failed."""
        self.db.from_("indexed_vaults") \
            .update({
                "backfill_status": "failed",
                "backfill_error": error,
            }) \
            .eq("id", vault_id) \
            .execute()


# =============================================================================
# QUEUE MANAGEMENT
# =============================================================================


async def get_pending_backfill_jobs(
    supabase_client: Client,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """
    Get pending backfill jobs from the queue.

    Returns jobs ordered by priority (descending) then creation time.
    """
    result = supabase_client.rpc(
        "get_ready_vault_backfill_jobs",
        {"p_limit": limit},
    ).execute()
    return result.data or []


async def queue_vault_backfill(
    supabase_client: Client,
    vault_id: int,
    vault_signature: str,
    priority: int = 0,
) -> str:
    """
    Queue a vault for backfill processing.

    Idempotent - will not create duplicate jobs.

    Args:
        supabase_client: Database client
        vault_id: On-chain vault ID
        vault_signature: 64-byte signature hex
        priority: Job priority (higher = process sooner)

    Returns:
        Job ID (UUID string)
    """
    result = supabase_client.rpc("queue_vault_backfill", {
        "p_vault_id": vault_id,
        "p_vault_signature": vault_signature,
        "p_priority": priority,
    }).execute()
    return str(result.data) if result.data else ""


async def enqueue_vault_backfill_job(
    supabase_client: Client,
    vault_id: int,
    vault_signature: str,
    priority: int = 0,
    dispatch_immediately: bool = True,
) -> str:
    """
    Queue a vault backfill job and optionally dispatch the worker immediately.

    The queue row is the source of truth for status; immediate dispatch is only
    a latency optimization. If dispatch fails, Celery Beat can still pick up the
    queued job later.
    """
    job_id = await queue_vault_backfill(
        supabase_client=supabase_client,
        vault_id=vault_id,
        vault_signature=vault_signature,
        priority=priority,
    )

    if not job_id or not dispatch_immediately:
        return job_id

    try:
        from ..tasks import backfill_vault_leaderboard

        backfill_vault_leaderboard.delay(
            vault_id=vault_id,
            vault_signature=vault_signature,
            job_id=job_id,
        )
    except Exception as exc:
        logger.warning(f"[Backfill] Failed to dispatch queued job {job_id} immediately: {exc}")

    return job_id


# =============================================================================
# SERVICE FACTORY
# =============================================================================

_backfill_service: Optional[VaultBackfillService] = None
_backfill_lock = threading.Lock()


def get_backfill_service(supabase_client: Client) -> VaultBackfillService:
    """Get or create backfill service instance (thread-safe)."""
    global _backfill_service
    if _backfill_service is None:
        with _backfill_lock:
            # Double-check locking pattern
            if _backfill_service is None:
                _backfill_service = VaultBackfillService(supabase_client)
    return _backfill_service
