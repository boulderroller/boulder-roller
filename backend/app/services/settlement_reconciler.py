"""Finality-first reconciliation for submitted, ambiguous, and legacy settlement jobs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Optional

from .settlement_chain import SettlementChain
from .settlement_queue import (
    SettlementClaim,
    SettlementNotificationEvent,
    SettlementQueue,
    parse_u64,
    u64_string,
)


_INDEXED_AMOUNT_FIELDS = (
    "total_distributed",
    "leaderboard_distributed",
    "staker_distributed",
    "local_legend_distributed",
    "pol_distributed",
    "protocol_distributed",
    "locked_staker_amount",
)


def _exact_indexed_distribution(
    indexed: Optional[Mapping[str, Any]],
) -> Optional[dict[str, Any]]:
    if indexed is None:
        return None
    exact = dict(indexed)
    for field_name in ("vault_id", "epoch", "slot", *_INDEXED_AMOUNT_FIELDS):
        if exact.get(field_name) is not None:
            exact[field_name] = u64_string(exact[field_name], field_name=field_name)
    return exact


@dataclass(frozen=True)
class ReconciliationEvidence:
    open_settlement_week: Optional[int]
    signature_state: str
    signature_error: Optional[str]
    indexed_tx_signature: Optional[str]
    indexed_distribution: Optional[dict[str, Any]]
    chain_commitment: str = "finalized"
    indexed_signature_finalized: bool = False
    recovered_tx_signature: Optional[str] = None
    source_slot: Optional[int] = None
    read_error: Optional[str] = None
    absent_vault_counter_count: Optional[int] = None
    absence_slot_floor: Optional[int] = None

    def as_json(self) -> dict[str, Any]:
        return {
            "open_settlement_week": (
                str(self.open_settlement_week)
                if self.open_settlement_week is not None
                else None
            ),
            "signature_state": self.signature_state,
            "signature_error": self.signature_error,
            "chain_commitment": self.chain_commitment,
            "source_slot": str(self.source_slot) if self.source_slot is not None else None,
            "indexed_tx_signature": self.indexed_tx_signature,
            "indexed_signature_finalized": self.indexed_signature_finalized,
            "indexed_distribution": _exact_indexed_distribution(
                self.indexed_distribution
            ),
            "recovered_tx_signature": self.recovered_tx_signature,
            "read_error": self.read_error,
            "absent_vault_counter_count": (
                u64_string(self.absent_vault_counter_count)
                if self.absent_vault_counter_count is not None else None
            ),
            "absence_slot_floor": (
                u64_string(self.absence_slot_floor)
                if self.absence_slot_floor is not None else None
            ),
        }


@dataclass(frozen=True)
class ReconciliationDecision:
    action: str
    reason: str


def decide_reconciliation(
    claim: SettlementClaim,
    evidence: ReconciliationEvidence,
) -> ReconciliationDecision:
    """Choose a transition only from finalized chain and signature evidence."""
    if evidence.read_error:
        return ReconciliationDecision("reconciling", "authoritative evidence read failed")
    if evidence.chain_commitment != "finalized":
        return ReconciliationDecision(
            "reconciling",
            "chain evidence is not finalized and may roll back",
        )
    if evidence.open_settlement_week is None:
        count = evidence.absent_vault_counter_count
        if (
            count is not None and 0 <= count <= claim.vault_id
            and evidence.absence_slot_floor is not None
            and evidence.source_slot is not None
            and evidence.source_slot > evidence.absence_slot_floor
        ):
            return ReconciliationDecision(
                "blocked",
                f"vault {claim.vault_id} absent at finalized slot {evidence.source_slot}; "
                f"newer than run slot {evidence.absence_slot_floor} and outside current "
                f"vault counter range [0, {count}); operator review required",
            )
        return ReconciliationDecision("reconciling", "authoritative evidence read failed")

    open_week = evidence.open_settlement_week
    target_week = claim.settlement_week
    indexed = evidence.indexed_distribution
    indexed_matches = False
    if indexed is not None:
        try:
            indexed_matches = (
                parse_u64(indexed.get("vault_id"), field_name="indexed vault_id")
                == claim.vault_id
                and parse_u64(indexed.get("epoch"), field_name="indexed epoch")
                == target_week
            )
        except ValueError:
            indexed_matches = False

    if indexed is not None and not indexed_matches:
        return ReconciliationDecision(
            "blocked",
            "indexed settlement evidence does not match the claimed vault and week",
        )

    if open_week < claim.expected_pre_open_week:
        return ReconciliationDecision(
            "blocked",
            "finalized open week moved behind the materialized precondition",
        )

    if open_week > target_week:
        if indexed_matches and evidence.indexed_signature_finalized:
            return ReconciliationDecision(
                "confirmed",
                "finalized indexed distribution matches the finalized vault state",
            )
        if evidence.signature_state == "finalized":
            return ReconciliationDecision(
                "confirmed",
                "finalized transaction and finalized vault advancement match",
            )
        return ReconciliationDecision(
            "advanced_unproven",
            "finalized vault advancement prevents resend but payout evidence is unavailable",
        )

    if indexed_matches:
        return ReconciliationDecision(
            "reconciling",
            "indexed settlement exists but the finalized vault has not advanced",
        )

    if evidence.signature_state in {"finalized", "confirmed", "pending", "unknown"}:
        return ReconciliationDecision(
            "reconciling",
            "transaction may still finalize; resend is not yet safe",
        )

    if open_week in {claim.expected_pre_open_week, target_week}:
        if claim.legacy_distribution_id is not None:
            return ReconciliationDecision(
                "blocked",
                "legacy queue row has no matching finalized chain evidence; automatic resend is disabled",
            )
        if claim.last_error_class == "deterministic_submit":
            return ReconciliationDecision(
                "blocked",
                "deterministic program failure has no matching settlement evidence",
            )
        if claim.last_error_class == "retry_recheck_required":
            return ReconciliationDecision(
                "ready",
                "fresh finalized reconciliation found no settlement evidence; resend is safe",
            )
        return ReconciliationDecision(
            "retry_wait",
            "no finalized settlement evidence and the authoritative open week is unchanged",
        )

    return ReconciliationDecision(
        "blocked",
        "settlement evidence does not match the materialized week",
    )


class SettlementReconciler:
    def __init__(
        self,
        *,
        queue: SettlementQueue,
        chain: SettlementChain,
        worker_id: str,
        lease_seconds: int = 300,
        on_notification: Optional[
            Callable[[SettlementNotificationEvent], Awaitable[None]]
        ] = None,
    ) -> None:
        self.queue = queue
        self.chain = chain
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.on_notification = on_notification

    async def reconcile_claim(self, claim: SettlementClaim) -> ReconciliationDecision:
        indexed: Optional[dict[str, Any]] = None
        recovered_signature: Optional[str] = None
        try:
            indexed = await self.queue.get_indexed_distribution(
                vault_id=claim.vault_id,
                settlement_week=claim.settlement_week,
            )
            recovered_signature = await self.queue.get_lifecycle_signature(claim)
            indexed_signature = (
                str(indexed.get("tx_signature"))
                if indexed and indexed.get("tx_signature")
                else None
            )
            evidence_signature = (
                indexed_signature
                or recovered_signature
                or claim.tx_signature
                or claim.prepared_tx_signature
            )
            chain_evidence = await self.chain.read_reconciliation_evidence(
                claim,
                signature=evidence_signature,
            )
            absence_slot_floor = None
            if chain_evidence.absent_vault_counter_count is not None:
                absence_slot_floor = await self.queue.get_reconciliation_slot_floor(claim)
            evidence = ReconciliationEvidence(
                open_settlement_week=chain_evidence.open_settlement_week,
                signature_state=chain_evidence.signature_state,
                signature_error=chain_evidence.signature_error,
                chain_commitment=chain_evidence.chain_commitment,
                source_slot=chain_evidence.source_slot,
                indexed_tx_signature=indexed_signature,
                indexed_signature_finalized=(
                    indexed_signature is not None
                    and evidence_signature == indexed_signature
                    and chain_evidence.signature_state == "finalized"
                ),
                indexed_distribution=indexed,
                recovered_tx_signature=recovered_signature,
                absent_vault_counter_count=chain_evidence.absent_vault_counter_count,
                absence_slot_floor=absence_slot_floor,
            )
        except Exception as exc:
            evidence = ReconciliationEvidence(
                open_settlement_week=None,
                signature_state="unknown",
                signature_error=None,
                chain_commitment="unknown",
                indexed_tx_signature=(
                    str(indexed.get("tx_signature"))
                    if indexed and indexed.get("tx_signature")
                    else None
                ),
                indexed_signature_finalized=False,
                indexed_distribution=indexed,
                recovered_tx_signature=recovered_signature,
                read_error=str(exc),
            )

        decision = decide_reconciliation(claim, evidence)
        evidence_json = evidence.as_json()
        evidence_json["transient_read_failure"] = decision.action == "reconciling" and bool(
            evidence.read_error
            or evidence.open_settlement_week is None
            or evidence.chain_commitment != "finalized"
            or (evidence.signature_state == "unknown" and evidence.signature_error)
        )
        retry_seconds = min(60 * (2 ** min(claim.attempt_count, 6)), 3600)
        await self.queue.finish_reconciliation(
            claim,
            decision=decision.action,
            evidence=evidence_json,
            signature_state=evidence.signature_state,
            chain_commitment=evidence.chain_commitment,
            observed_open_week=evidence.open_settlement_week,
            indexed_tx_signature=evidence.indexed_tx_signature,
            indexed_signature_finalized=evidence.indexed_signature_finalized,
            recovered_tx_signature=evidence.recovered_tx_signature,
            error=evidence.read_error or decision.reason,
            retry_seconds=retry_seconds,
        )
        return decision

    async def _drain_notifications(self, *, limit: int) -> None:
        if self.on_notification is None:
            return
        for _ in range(max(int(limit), 0)):
            event = await self.queue.claim_notification(
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
            )
            if event is None:
                return
            try:
                await self.on_notification(event)
            except Exception as exc:
                await self.queue.mark_notification_retry(event, error=str(exc))
                continue
            await self.queue.mark_notification_delivered(event)

    async def run_pending(
        self,
        *,
        limit: int = 10,
        vault_id: Optional[int] = None,
    ) -> int:
        processed = 0
        for _ in range(max(int(limit), 0)):
            claim = await self.queue.claim_reconciliation(
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
                vault_id=vault_id,
            )
            if claim is None:
                break
            await self.reconcile_claim(claim)
            processed += 1
        await self._drain_notifications(limit=limit)
        return processed
