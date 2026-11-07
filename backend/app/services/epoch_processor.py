"""
Epoch Processor Service

Handles settlement-week finalization and on-chain DUNG settlement for vaults.

Architecture:
    Scheduler/Admin/Crank → acquire epoch_processor lease → queue distributions
    for finalizable settlement weeks → process queued rows on-chain in
    deterministic order.

Flow:
    1. Every minute, check if a settlement week has become finalizable
    2. When a week is finalizable:
       a. Query all vaults with unsettled current/next-week value
       b. Queue distributions in epoch_distributions table
       c. Process queued distributions on-chain (batch or individual)
    3. Claim pending rows before submitting transactions so a cron fallback,
       admin trigger, or second API instance cannot process the same row
       concurrently.
    4. Update settlement state and epoch_history

On-Chain Distribution:
    Receipt-backed `record_climb_completion_v2` routes accepted tribute into
    the Vault's oldest open lifetime flow. `distribute_epoch_rewards` finalizes
    one week at a time and settles the configured buckets on-chain.

Usage:
    from .epoch_processor import start_epoch_processor

    # In app lifespan:
    epoch_task = await start_epoch_processor(supabase_client)
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from supabase import Client
from solders.pubkey import Pubkey

from ..repositories.notification import NotificationRepository
from ..repositories.ride_economic import (
    ConfirmedCompletionCandidateProvider,
    RideEconomicRepository,
)
from ..solana_direct import (
    DirectConfig,
    SETTLEMENT_COMPUTE_UNIT_LIMIT,
    build_settlement_distribution_plan,
    get_program_settlement_clock,
    load_default_config,
    send_deactivate_local_legend,
    send_elect_local_legend,
)
from ..settlement_clock import SettlementClock
from .background_job_lock import BackgroundJobLock
from .settlement_chain import SettlementChain
from .settlement_queue import (
    SettlementBootstrapRequired,
    SettlementClaim,
    SettlementNotificationEvent,
    SettlementQueue,
    SettlementStateError,
)
from .settlement_reconciler import SettlementReconciler
from .settlement_transport import SettlementTransportManager
from .settlement_worker import SettlementPlanner, SettlementWorker

logger = logging.getLogger(__name__)

# Check interval for epoch changes (1 minute)
EPOCH_CHECK_INTERVAL_SECONDS = 60

# Circuit breaker constants
MAX_CONSECUTIVE_FAILURES = 10
BASE_BACKOFF_SECONDS = 60
MAX_BACKOFF_SECONDS = 3600  # Cap at 1 hour
MAX_CATCHUP_WEEKS_PER_CYCLE = 10


def _parse_completion_timestamp(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        parsed = datetime.fromtimestamp(value, timezone.utc)
    elif isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _epoch_start_datetime(epoch: int, settlement_clock: SettlementClock) -> datetime:
    return datetime.fromtimestamp(settlement_clock.week_start(epoch), timezone.utc)


def _iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_valid_pubkey(value: Any) -> bool:
    try:
        Pubkey.from_string(str(value))
        return True
    except Exception:
        return False

class EpochProcessor:
    """
    Processes weekly epoch transitions for vault CAL→DUNG distribution.

    Responsibilities:
    - Detect epoch changes
    - Query vaults ready for distribution
    - Queue distributions in database
    - Process on-chain (when implemented)
    """

    def __init__(
        self,
        supabase_client: Client,
        solana_config: Optional[DirectConfig] = None,
        confirmed_completion_provider: Optional[
            ConfirmedCompletionCandidateProvider
        ] = None,
        settlement_clock: Optional[SettlementClock] = None,
    ):
        self.db = supabase_client
        self.config = solana_config
        self._last_epoch: Optional[int] = None
        self._settlement_clock = settlement_clock
        self._running = False
        self._consecutive_failures = 0
        self.notification_repo = NotificationRepository(supabase_client)
        self.confirmed_completion_provider = (
            confirmed_completion_provider or RideEconomicRepository(supabase_client)
        )
        self._lock = BackgroundJobLock(
            supabase_client,
            "epoch_processor",
            ttl_seconds=max(EPOCH_CHECK_INTERVAL_SECONDS * 10, 900),
        )
        self._settlement_queue = SettlementQueue(supabase_client)
        self._settlement_chain: Optional[SettlementChain] = None
        self._settlement_planner: Optional[SettlementPlanner] = None
        self._settlement_reconciler: Optional[SettlementReconciler] = None
        self._settlement_worker: Optional[SettlementWorker] = None
        self._settlement_transport: Optional[SettlementTransportManager] = None

    def _ensure_settlement_services(self) -> None:
        if self.config is None:
            self.config = load_default_config()
        if self._settlement_chain is not None:
            return
        self._settlement_chain = SettlementChain(self.config)
        self._settlement_reconciler = SettlementReconciler(
            queue=self._settlement_queue,
            chain=self._settlement_chain,
            worker_id=self._lock.owner_id,
            on_notification=self._deliver_settlement_notification,
        )
        self._settlement_transport = SettlementTransportManager(
            db=self.db,
            config=self.config,
        )
        self._settlement_planner = SettlementPlanner(
            queue=self._settlement_queue,
            chain=self._settlement_chain,
            prepare_vault=self._prepare_vault_for_settlement,
        )
        self._settlement_worker = SettlementWorker(
            queue=self._settlement_queue,
            reconciler=self._settlement_reconciler,
            worker_id=self._lock.owner_id,
            config=self.config,
            prepare_vault=self._prepare_vault_for_settlement,
        )

    async def _load_settlement_clock(self) -> SettlementClock:
        if self._settlement_clock is not None:
            return self._settlement_clock
        if self.config is None:
            self.config = load_default_config()
        self._settlement_clock = await get_program_settlement_clock(self.config)
        return self._settlement_clock

    def _latest_finalizable_epoch(
        self,
        settlement_clock: SettlementClock,
        current_time: Optional[int] = None,
    ) -> int:
        timestamp = (
            int(datetime.now(timezone.utc).timestamp())
            if current_time is None
            else current_time
        )
        return settlement_clock.latest_finalizable_week(timestamp)

    async def get_stored_epoch(
        self,
        latest_finalizable_week: Optional[int] = None,
    ) -> int:
        """Read or transactionally bootstrap the finalized planning cursor."""
        try:
            return await self._settlement_queue.get_planning_cursor()
        except SettlementBootstrapRequired:
            self._ensure_settlement_services()
            if self._settlement_planner is None:
                raise SettlementStateError("settlement planner failed to initialize")
            latest = (
                self._latest_finalizable_epoch(
                    await self._load_settlement_clock(),
                    await self._settlement_chain.read_chain_time(),
                )
                if latest_finalizable_week is None
                else latest_finalizable_week
            )
            return await self._settlement_planner.bootstrap(latest)

    async def update_stored_epoch(self, epoch: int) -> None:
        """Reject detached cursor writes; materialization owns this transition."""
        raise SettlementStateError(
            "settlement planning cursor advances only inside br_materialize_settlement_week"
        )

    async def check_epoch_transition(self) -> bool:
        """
        Check if epoch has changed and process if needed.

        Returns:
            True if epoch transitioned and was processed
        """
        settlement_clock = await self._load_settlement_clock()
        self._ensure_settlement_services()
        current_time = await self._settlement_chain.read_chain_time()
        current_epoch = settlement_clock.week_at(current_time)
        latest_finalizable_epoch = self._latest_finalizable_epoch(
            settlement_clock,
            current_time,
        )
        stored_epoch = await self.get_stored_epoch(latest_finalizable_epoch)

        if stored_epoch > latest_finalizable_epoch:
            raise SettlementStateError(
                "settlement planning cursor "
                f"{stored_epoch} is ahead of latest finalizable week "
                f"{latest_finalizable_epoch}; refusing a detached clamp"
            )

        if stored_epoch >= latest_finalizable_epoch:
            return False

        ended_epoch = stored_epoch + 1
        logger.info(
            "[EpochProcessor] Settlement transition detected: last_materialized=%s next=%s current=%s",
            stored_epoch,
            ended_epoch,
            current_epoch,
        )
        await self._process_epoch_end(ended_epoch)
        return True

    async def _process_epoch_end(
        self,
        ended_epoch: int,
        vault_id: Optional[int] = None,
    ) -> None:
        """
        Materialize one complete authoritative Settlement Week plan.

        Args:
            ended_epoch: The epoch number that just ended
            vault_id: Legacy compatibility argument. Planning always includes the
                complete VaultCounter scope; execution may still be target-scoped.
        """
        logger.info("[EpochProcessor] Materializing Settlement Week %s", ended_epoch)
        if vault_id is not None:
            logger.info(
                "[EpochProcessor] Target vault %s requested; materialization remains full-scope",
                vault_id,
            )
        self._ensure_settlement_services()
        if self._settlement_planner is None:
            raise SettlementStateError("settlement planner failed to initialize")
        result = await self._settlement_planner.materialize_week(ended_epoch)
        logger.info(
            "[EpochProcessor] Settlement Week %s materialized: jobs=%s ready=%s skipped=%s state=%s",
            ended_epoch,
            result.job_count,
            result.ready_count,
            result.skipped_count,
            result.state,
        )

    async def _prepare_vault_for_settlement(
        self,
        claim: SettlementClaim,
    ) -> dict[str, Any]:
        intent = claim.precondition_intent
        if intent is None:
            intent = await self._build_local_legend_intent(
                ended_epoch=claim.settlement_week,
                vault_id=claim.vault_id,
                vault_signature=claim.vault_signature,
            )
            intent = await self._settlement_queue.persist_precondition_intent(
                claim,
                intent,
            )
        legend_result = await self._rollover_local_legend_for_vault(
            ended_epoch=claim.settlement_week,
            vault_id=claim.vault_id,
            vault_signature=claim.vault_signature,
            frozen_intent=intent,
        )
        if self.config is None or self._settlement_transport is None:
            raise SettlementStateError("settlement transport failed to initialize")
        distribution = await build_settlement_distribution_plan(
            config=self.config,
            vault_id=claim.vault_id,
            settlement_week=claim.settlement_week,
        )
        transport_result = await self._settlement_transport.prepare(
            vault_id=claim.vault_id,
            settlement_week=claim.settlement_week,
            distribution=distribution,
            compute_unit_limit=SETTLEMENT_COMPUTE_UNIT_LIMIT,
        )
        return {
            "completed": True,
            "legend": legend_result,
            "transport": transport_result,
        }

    async def _deliver_settlement_notification(
        self,
        event: SettlementNotificationEvent,
    ) -> None:
        await self._notify_settlement_finalized(event)

    async def _get_indexed_legend_row(self, vault_id: int) -> Optional[dict[str, Any]]:
        result = self.db.from_("indexed_legends") \
            .select("*") \
            .eq("vault_id", vault_id) \
            .limit(1) \
            .execute()
        rows = getattr(result, "data", None) or []
        return dict(rows[0]) if rows else None

    async def _insert_wallet_notification(
        self,
        *,
        wallet: Optional[str],
        notification_type: str,
        title: str,
        message: str,
        metadata: dict[str, Any],
        target_type: str,
        target_id: str,
        dedupe_key: str,
    ) -> None:
        if not wallet or not _is_valid_pubkey(wallet):
            return
        try:
            await self.notification_repo.create_event_notification(
                wallet=wallet,
                notification_type=notification_type,
                title=title,
                message=message,
                metadata=metadata,
                target_type=target_type,
                target_id=target_id,
                dedupe_key=dedupe_key,
            )
        except Exception:
            logger.warning(
                "[EpochProcessor] Failed to emit %s notification for wallet %s",
                notification_type,
                "[redacted]",
                exc_info=True,
            )

    async def _notify_local_legend_rollover(
        self,
        *,
        vault_id: int,
        vault_signature: str,
        term_end_epoch: int,
        outcome: str,
        winner: Optional[str],
        previous_holder: Optional[str],
        winner_completions: int = 0,
        tx_signature: Optional[str] = None,
    ) -> None:
        metadata = {
            "vault_id": vault_id,
            "vault_signature": vault_signature,
            "term_end_epoch": term_end_epoch,
            "outcome": outcome,
            "winner": winner,
            "previous_holder": previous_holder,
            "winner_completions": winner_completions,
            "tx_signature": tx_signature,
        }
        if outcome == "elected" and winner:
            await self._insert_wallet_notification(
                wallet=winner,
                notification_type="local_legend_moved",
                title="Local Legend updated",
                message="You are the current Local Legend.",
                metadata=metadata,
                target_type="local_legend",
                target_id=str(vault_id),
                dedupe_key=f"local_legend_moved:{vault_id}:{term_end_epoch}:{winner}",
            )
        if previous_holder and previous_holder != winner:
            await self._insert_wallet_notification(
                wallet=previous_holder,
                notification_type="local_legend_moved",
                title="Local Legend updated",
                message="Your Local Legend term has rolled over.",
                metadata=metadata,
                target_type="local_legend",
                target_id=str(vault_id),
                dedupe_key=f"local_legend_moved:{vault_id}:{term_end_epoch}:{previous_holder}",
            )

    async def _settlement_recipient_wallets(self, vault_id: int) -> list[str]:
        try:
            result = self.db.from_("indexed_leaderboards") \
                .select("entries") \
                .eq("vault_id", vault_id) \
                .limit(1) \
                .execute()
            rows = getattr(result, "data", None) or []
            entries = rows[0].get("entries") if rows else []
        except Exception:
            logger.warning(
                "[EpochProcessor] Could not read settlement notification recipients for vault %s",
                vault_id,
                exc_info=True,
            )
            return []
        wallets: list[str] = []
        for entry in entries or []:
            if not isinstance(entry, dict):
                continue
            wallet = entry.get("user") or entry.get("wallet") or entry.get("user_pubkey")
            if wallet and _is_valid_pubkey(wallet) and str(wallet) not in wallets:
                wallets.append(str(wallet))
        return wallets[:10]

    async def _notify_settlement_finalized(
        self,
        event: SettlementNotificationEvent,
    ) -> None:
        vault_id = event.vault_id
        settlement_week = event.settlement_week
        metadata = event.as_notification_metadata()
        metadata["vault_signature"] = event.vault_signature
        for wallet in await self._settlement_recipient_wallets(vault_id):
            await self._insert_wallet_notification(
                wallet=wallet,
                notification_type="settlement_finalized",
                title="Settlement finalized",
                message="A vault settlement you participated in finalized on-chain.",
                metadata=metadata,
                target_type="settlement",
                target_id=f"{vault_id}:{settlement_week}",
                dedupe_key=f"settlement_finalized:{vault_id}:{settlement_week}:{wallet}",
            )

    async def _record_legend_rollover(
        self,
        *,
        vault_id: int,
        vault_signature: str,
        term_start_epoch: int,
        term_end_epoch: int,
        previous_holder: Optional[str],
        outcome: str,
        status: str,
        winner: Optional[str] = None,
        winner_completions: int = 0,
        runner_up: Optional[str] = None,
        runner_up_completions: int = 0,
        tx_signature: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.db.from_("local_legend_rollovers").upsert({
            "vault_id": vault_id,
            "vault_signature": vault_signature,
            "term_start_epoch": term_start_epoch,
            "term_end_epoch": term_end_epoch,
            "previous_holder": previous_holder,
            "outcome": outcome,
            "status": status,
            "winner": winner,
            "winner_completions": winner_completions,
            "runner_up": runner_up,
            "runner_up_completions": runner_up_completions,
            "tx_signature": tx_signature,
            "error_message": error_message,
            "processed_at": now,
            "updated_at": now,
        }, on_conflict="vault_id,term_end_epoch").execute()

    async def _derive_local_legend_candidates(
        self,
        *,
        vault_id: int,
        vault_signature: str,
        term_start_epoch: int,
        term_end_epoch: int,
    ) -> list[dict[str, Any]]:
        settlement_clock = await self._load_settlement_clock()
        start_at = _epoch_start_datetime(term_start_epoch, settlement_clock)
        end_at = _epoch_start_datetime(term_end_epoch, settlement_clock)

        provider = self.confirmed_completion_provider
        if provider is None or not hasattr(
            provider,
            "list_confirmed_local_legend_candidates",
        ):
            raise SettlementStateError(
                "authoritative confirmed completion provider is unavailable"
            )
        try:
            rows = await provider.list_confirmed_local_legend_candidates(
                vault_id=vault_id,
                completed_from=start_at,
                completed_before=end_at,
            )
            candidates: list[dict[str, Any]] = []
            for row in rows:
                wallet = row.get("wallet")
                completion_count = row.get("completion_count")
                first_completed_at = _parse_completion_timestamp(
                    row.get("first_completed_at")
                )
                if (
                    not isinstance(wallet, str)
                    or not _is_valid_pubkey(wallet)
                    or isinstance(completion_count, bool)
                    or not isinstance(completion_count, int)
                    or completion_count <= 0
                    or first_completed_at is None
                    or first_completed_at < start_at
                    or first_completed_at >= end_at
                ):
                    raise ValueError("malformed confirmed candidate aggregate")
                candidates.append({
                    "wallet": wallet,
                    "completion_count": completion_count,
                    "first_completed_at": first_completed_at,
                })
            return sorted(
                candidates,
                key=lambda item: (
                    -int(item["completion_count"]),
                    item["first_completed_at"],
                    item["wallet"],
                ),
            )
        except Exception as exc:
            raise SettlementStateError(
                f"confirmed completion candidates unavailable for vault "
                f"{vault_signature}: {exc}"
            ) from exc

    async def _read_authoritative_local_legend(self, vault_id: int) -> Any:
        self._ensure_settlement_services()
        if self._settlement_chain is None:
            raise SettlementStateError("settlement chain reader failed to initialize")
        legend = await self._settlement_chain.read_local_legend(vault_id)
        if legend is None:
            raise SettlementStateError(
                f"finalized LocalLegend account is missing for vault {vault_id}"
            )
        return legend

    async def _build_local_legend_intent(
        self,
        *,
        ended_epoch: int,
        vault_id: int,
        vault_signature: str,
    ) -> dict[str, Any]:
        finalized_legend = await self._read_authoritative_local_legend(vault_id)
        legend = await self._get_indexed_legend_row(vault_id)
        if not legend:
            raise SettlementStateError(
                f"indexed Local Legend is missing for vault {vault_id}; "
                "settlement precondition cannot be frozen"
            )

        indexed_holder = str(legend.get("holder") or "")
        indexed_active = bool(legend.get("is_active"))
        indexed_term_start = int(legend.get("term_start_epoch") or 0)
        indexed_term_end = int(legend.get("term_end_epoch") or 0)
        if (
            indexed_holder != str(getattr(finalized_legend, "holder", ""))
            or indexed_active != bool(getattr(finalized_legend, "is_active", False))
            or indexed_term_start
            != int(getattr(finalized_legend, "term_start_epoch", -1))
            or indexed_term_end
            != int(getattr(finalized_legend, "term_end_epoch", 0))
        ):
            raise SettlementStateError(
                f"indexed Local Legend diverges from finalized chain for vault {vault_id}"
            )

        term_end_epoch = indexed_term_end
        term_start_epoch = indexed_term_start
        if term_end_epoch <= 0 or term_end_epoch > ended_epoch:
            return {
                "required": False,
                "reason": "local_legend_term_not_due",
                "settlement_week": str(ended_epoch),
                "vault_id": str(vault_id),
                "vault_signature": vault_signature,
                "term_start_epoch": str(term_start_epoch),
                "term_end_epoch": str(term_end_epoch),
            }

        previous_holder = legend.get("holder")
        candidates = await self._derive_local_legend_candidates(
            vault_id=vault_id,
            vault_signature=vault_signature,
            term_start_epoch=term_start_epoch,
            term_end_epoch=term_end_epoch,
        )
        outcome = "elected" if candidates else "dormant"
        winner = candidates[0] if candidates else None
        runner_up = candidates[1] if len(candidates) > 1 else None

        return {
            "required": True,
            "settlement_week": str(ended_epoch),
            "vault_id": str(vault_id),
            "vault_signature": vault_signature,
            "term_start_epoch": str(term_start_epoch),
            "term_end_epoch": str(term_end_epoch),
            "previous_holder": previous_holder,
            "outcome": outcome,
            "winner": winner["wallet"] if winner else None,
            "winner_completions": str(winner["completion_count"]) if winner else "0",
            "runner_up": runner_up["wallet"] if runner_up else None,
            "runner_up_completions": (
                str(runner_up["completion_count"]) if runner_up else "0"
            ),
            "candidate_tiebreak_evidence": [
                {
                    "wallet": candidate["wallet"],
                    "completion_count": str(candidate["completion_count"]),
                    "first_completed_at": candidate["first_completed_at"].isoformat(),
                }
                for candidate in candidates
            ],
        }

    async def _rollover_local_legend_for_vault(
        self,
        *,
        ended_epoch: int,
        vault_id: int,
        vault_signature: str,
        frozen_intent: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        intent = frozen_intent or await self._build_local_legend_intent(
            ended_epoch=ended_epoch,
            vault_id=vault_id,
            vault_signature=vault_signature,
        )
        if str(intent.get("settlement_week")) != str(ended_epoch):
            raise SettlementStateError("Local Legend intent settlement week changed")
        if str(intent.get("vault_id")) != str(vault_id):
            raise SettlementStateError("Local Legend intent vault ID changed")
        if str(intent.get("vault_signature")) != vault_signature:
            raise SettlementStateError("Local Legend intent vault signature changed")
        if not intent.get("required"):
            return {
                "completed": True,
                "required": False,
                "reason": str(intent.get("reason") or "not_required"),
                "intent": intent,
            }

        term_start_epoch = int(intent["term_start_epoch"])
        term_end_epoch = int(intent["term_end_epoch"])
        previous_holder = intent.get("previous_holder")
        outcome = str(intent["outcome"])
        winner_wallet = str(intent["winner"]) if intent.get("winner") else None
        winner_completions = int(intent.get("winner_completions") or 0)
        runner_up_wallet = (
            str(intent["runner_up"]) if intent.get("runner_up") else None
        )
        runner_up_completions = int(intent.get("runner_up_completions") or 0)
        if outcome not in {"elected", "dormant"}:
            raise SettlementStateError("Local Legend intent outcome is invalid")
        if (outcome == "elected") != bool(winner_wallet):
            raise SettlementStateError("Local Legend intent winner is inconsistent")

        def finalized_state_matches(state: Any) -> bool:
            if state is None:
                return False
            finalized_term_start = int(getattr(state, "term_start_epoch", -1))
            finalized_term_end = int(getattr(state, "term_end_epoch", 0))
            if (
                finalized_term_start != term_end_epoch
                or finalized_term_end <= finalized_term_start
            ):
                return False
            if winner_wallet is not None:
                return bool(getattr(state, "is_active", False)) and str(
                    getattr(state, "holder", "")
                ) == winner_wallet
            return not bool(getattr(state, "is_active", True))

        async def record_reconciled(signature: str) -> dict[str, Any]:
            await self._record_legend_rollover(
                vault_id=vault_id,
                vault_signature=vault_signature,
                term_start_epoch=term_start_epoch,
                term_end_epoch=term_end_epoch,
                previous_holder=previous_holder,
                outcome=outcome,
                status="confirmed",
                winner=winner_wallet,
                winner_completions=winner_completions,
                runner_up=runner_up_wallet,
                runner_up_completions=runner_up_completions,
                tx_signature=signature,
            )
            await self._notify_local_legend_rollover(
                vault_id=vault_id,
                vault_signature=vault_signature,
                term_end_epoch=term_end_epoch,
                outcome=outcome,
                winner=winner_wallet,
                previous_holder=previous_holder,
                winner_completions=winner_completions,
                tx_signature=signature,
            )
            return {
                "completed": True,
                "required": True,
                "outcome": outcome,
                "term_end_epoch": str(term_end_epoch),
                "winner": winner_wallet,
                "tx_signature": signature,
                "evidence": "finalized_local_legend",
                "intent": intent,
            }

        finalized_before = await self._read_authoritative_local_legend(vault_id)
        if finalized_state_matches(finalized_before):
            return await record_reconciled("chain-state-reconciled")
        if int(getattr(finalized_before, "term_end_epoch", 0)) > term_end_epoch:
            raise SettlementStateError(
                f"finalized LocalLegend outcome for vault {vault_id} does not match "
                "the durable settlement precondition"
            )

        try:
            if winner_wallet is not None:
                tx_signature = await send_elect_local_legend(
                    config=self.config,
                    vault_id=vault_id,
                    term_start_epoch=term_end_epoch,
                    winner=winner_wallet,
                    winner_completions=winner_completions,
                    runner_up=runner_up_wallet,
                    runner_up_completions=runner_up_completions,
                )
                result = await record_reconciled(tx_signature)
                logger.info(
                    "[EpochProcessor] Local Legend elected for vault %s: winner=%s completions=%s sig=%s",
                    vault_id,
                    "[redacted]",
                    winner_completions,
                    tx_signature,
                )
                return result

            tx_signature = await send_deactivate_local_legend(
                config=self.config,
                vault_id=vault_id,
                term_start_epoch=term_end_epoch,
            )
            result = await record_reconciled(tx_signature)
            logger.info(
                "[EpochProcessor] Local Legend dormant rollover for vault %s confirmed: sig=%s",
                vault_id,
                tx_signature,
            )
            return result
        except Exception as exc:
            try:
                finalized_after = await self._read_authoritative_local_legend(vault_id)
            except Exception:
                finalized_after = None
            if finalized_state_matches(finalized_after):
                return await record_reconciled("chain-state-reconciled")
            await self._record_legend_rollover(
                vault_id=vault_id,
                vault_signature=vault_signature,
                term_start_epoch=term_start_epoch,
                term_end_epoch=term_end_epoch,
                previous_holder=previous_holder,
                outcome=outcome,
                status="failed",
                error_message=str(exc),
            )
            raise

    async def _queue_distribution(
        self,
        epoch: int,
        vault_signature: str,
        vault_id: int,
        cal_amount: int,
        dung_to_mint: int,
    ) -> None:
        """Reject writes through the retired non-transactional queue path."""
        raise SettlementStateError(
            "legacy epoch_distributions queueing is disabled; materialize the full week"
        )

    async def _record_epoch_history(self, epoch: int) -> None:
        """Retained only as an explicit guard against the retired shadow ledger."""
        raise SettlementStateError(
            "epoch_history is not settlement authority; read settlement_week_runs"
        )

    async def process_pending_distributions(self, vault_id: Optional[int] = None) -> int:
        """
        Reap, reconcile, claim, and submit durable on-chain settlement jobs.

        Args:
            vault_id: Optional target vault. Production callers leave this unset;
                smoke/admin repair paths can scope processing to avoid draining
                unrelated stale devnet queue rows.

        Returns:
            Number of newly submitted settlement transactions
        """
        return await self._process_pending_onchain_distributions(vault_id=vault_id)

    async def process_settlement_cycle(
        self,
        *,
        force: bool = False,
        vault_id: Optional[int] = None,
    ) -> tuple[bool, int]:
        """
        Run one complete settlement cycle behind the shared processor lease.

        This is the canonical entry point for admin-triggered processing and the
        cron crank. The background loop uses the same unlocked work once it has
        acquired the lease for its long-running iteration.
        """
        if not await self._lock.acquire():
            logger.info("[EpochProcessor] Settlement cycle skipped; another worker holds the lease")
            return False, 0
        try:
            return await self._run_settlement_cycle_unlocked(force=force, vault_id=vault_id)
        finally:
            await self._lock.release()

    async def _recover_open_settlement_weeks(self) -> int:
        self._ensure_settlement_services()
        clock = await self._load_settlement_clock()
        latest = clock.latest_finalizable_week(await self._settlement_chain.read_chain_time())
        await self.get_stored_epoch(latest)
        return await self._settlement_planner.recover_open_weeks(latest)

    async def _run_settlement_cycle_unlocked(
        self,
        *,
        force: bool = False,
        vault_id: Optional[int] = None,
    ) -> tuple[bool, int]:
        processed = 0
        transitioned = False
        for _ in range(MAX_CATCHUP_WEEKS_PER_CYCLE):
            recovered = await self._recover_open_settlement_weeks()
            processed += await self.process_pending_distributions(vault_id=vault_id)
            recovered_after = await self._recover_open_settlement_weeks()
            if recovered_after:
                continue
            cursor = await self.get_stored_epoch()
            if await self._settlement_queue.has_unfinished_jobs(settlement_week=cursor):
                break
            if recovered:
                # Re-read finalized open weeks before recovering another historical
                # skip. Never increment a Vault pointer locally.
                continue
            if force:
                break
            planned = await self.check_epoch_transition()
            if not planned:
                break
            transitioned = True
            logger.info("[EpochProcessor] Settlement Week materialized")
        return transitioned, processed

    async def _claim_distribution_for_processing(
        self,
        distribution_id: Any,
        attempt_count: int,
    ) -> bool:
        """Reject the unfenced legacy claim path."""
        raise SettlementStateError(
            "legacy distribution claims are disabled; use br_claim_settlement_job"
        )

    async def _process_pending_onchain_distributions(
        self,
        vault_id: Optional[int] = None,
    ) -> int:
        """Reap, reconcile, atomically claim, and submit durable settlement jobs."""
        self._ensure_settlement_services()
        if self._settlement_worker is None:
            raise SettlementStateError("settlement worker failed to initialize")
        result = await self._settlement_worker.run_cycle(
            max_jobs=10,
            vault_id=vault_id,
        )
        logger.info(
            "[EpochProcessor] Settlement cycle: reaped=%s reconciled=%s submitted=%s blocked=%s",
            result.reaped,
            result.reconciled,
            result.submitted,
            result.blocked,
        )
        return result.submitted

    async def _record_distribution_ledger(self, *args: Any, **kwargs: Any) -> Optional[str]:
        """Deprecated placeholder.

        Distribution history must come from indexed on-chain events, not backend
        recomputation. Keep the method so older callers/tests fail soft while the
        indexer/event layer catches up.
        """
        return None

    async def run(self) -> None:
        """Main loop: periodically check for epoch transitions."""
        self._running = True
        logger.info("[EpochProcessor] Starting epoch processor")

        try:
            while self._running:
                try:
                    if not await self._lock.acquire():
                        await asyncio.sleep(EPOCH_CHECK_INTERVAL_SECONDS)
                        continue

                    await self._run_settlement_cycle_unlocked()

                    # Reset failure counter on success
                    if self._consecutive_failures > 0:
                        logger.info(
                            f"[EpochProcessor] Recovered after {self._consecutive_failures} failures"
                        )
                        self._consecutive_failures = 0

                except Exception as e:
                    self._consecutive_failures += 1

                    # Calculate exponential backoff: base * 2^(failures-1), capped at max
                    backoff = min(
                        BASE_BACKOFF_SECONDS * (2 ** (self._consecutive_failures - 1)),
                        MAX_BACKOFF_SECONDS,
                    )

                    if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                        logger.critical(
                            f"[EpochProcessor] Circuit breaker: {self._consecutive_failures} "
                            f"consecutive failures, backing off {backoff}s. Error: {e}"
                        )
                    else:
                        logger.error(
                            f"[EpochProcessor] Error in main loop (failure {self._consecutive_failures}/"
                            f"{MAX_CONSECUTIVE_FAILURES}): {e}"
                        )

                    # Wait with backoff instead of normal sleep below
                    await asyncio.sleep(backoff)
                    continue

                await asyncio.sleep(EPOCH_CHECK_INTERVAL_SECONDS)
        finally:
            await self._lock.release()

    def stop(self) -> None:
        """Stop the processor."""
        self._running = False


# Singleton instance
_processor: Optional[EpochProcessor] = None
_processor_lock = threading.Lock()


def get_epoch_processor(supabase_client: Client) -> EpochProcessor:
    """Get or create epoch processor singleton (thread-safe)."""
    global _processor
    if _processor is None:
        with _processor_lock:
            # Double-check locking pattern
            if _processor is None:
                _processor = EpochProcessor(supabase_client)
    return _processor


async def start_epoch_processor(supabase_client: Client) -> asyncio.Task:
    """
    Start the epoch processor as a background task.

    Call this at app startup to enable automatic epoch processing.
    """
    processor = get_epoch_processor(supabase_client)

    async def processor_loop():
        await processor.run()

    task = asyncio.create_task(processor_loop())
    logger.info("[EpochProcessor] Background processor started")
    return task
