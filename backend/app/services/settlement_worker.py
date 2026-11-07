"""Settlement planning and execution orchestration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Optional

from ..solana_direct import (
    AcceptedSettlementTransactionError,
    DirectConfig,
    SETTLEMENT_COMPUTE_UNIT_LIMIT,
    send_distribute_epoch_rewards,
)
from .settlement_chain import SettlementChain, build_materialization_job
from .settlement_queue import MaterializationResult, SettlementClaim, SettlementQueue
from .settlement_transport import SettlementTransportStaleError


Submitter = Callable[[SettlementClaim], Awaitable[str]]
PrepareVault = Callable[[SettlementClaim], Awaitable[Mapping[str, Any]]]

_DETERMINISTIC_SUBMIT_ERRORS = (
    "insufficienttribute",
    "settlementweekmismatch",
    "settlementweekoutofsync",
    "invalidsettlementweek",
    "invalid settlement week",
    "supplycapreached",
    "invaliddistributionconfig",
    "invalidmetadata",
    "computationalbudgetexceeded",
    "computational budget exceeded",
    "compute units exceeded",
    "settlement supports at most",
    "transaction serializes to",
    "solana packet limit",
)
_REPAIRABLE_PREFLIGHT_ERRORS = (
    "programconfig not found",
    "missing pol or treasury",
    "account does not exist",
    "token account does not exist",
    "associated token account",
    "configuration unavailable",
    "settlement lookup table",
)
_RETRYABLE_SUBMIT_ERRORS = (
    "blockhash",
    "settlementweeknotfinalizable",
    "accountinuse",
    "account in use",
    "node is behind",
    "too many requests",
    "rate limit",
    "429",
    "connection",
)


def classify_submit_error(error: Exception) -> str:
    """Classify a failed submit while still requiring reconciliation first."""
    message = str(error).lower().replace("_", "")
    if any(marker in message for marker in _REPAIRABLE_PREFLIGHT_ERRORS):
        return "repairable_preflight"
    if any(marker in message for marker in _DETERMINISTIC_SUBMIT_ERRORS):
        return "deterministic_submit"
    if any(marker in message for marker in _RETRYABLE_SUBMIT_ERRORS):
        return "retryable_submit"
    return "ambiguous_submit"


class SettlementInvariantError(ValueError):
    """The durable materialized plan violates a non-repairable invariant."""


@dataclass(frozen=True)
class SettlementCycleResult:
    reaped: int = 0
    reconciled: int = 0
    submitted: int = 0
    blocked: int = 0


class SettlementPlanner:
    def __init__(
        self,
        *,
        queue: SettlementQueue,
        chain: SettlementChain,
        prepare_vault: Optional[PrepareVault] = None,
    ) -> None:
        self.queue = queue
        self.chain = chain
        self.prepare_vault = prepare_vault

    async def bootstrap(self, latest_finalizable_week: int) -> int:
        scope = await self.chain.read_authoritative_scope()
        return await self.queue.bootstrap(
            scope=scope,
            latest_finalizable_week=latest_finalizable_week,
        )

    async def recover_open_weeks(self, latest_finalizable_week: int) -> int:
        scope = await self.chain.read_authoritative_scope()
        jobs = []
        for vault in scope.vaults:
            job = build_materialization_job(
                vault, settlement_week=int(vault["open_settlement_week"])
            )
            if self.prepare_vault is not None:
                job["state"] = "precondition_pending"
            jobs.append(job)
        return await self.queue.reopen_zero_value_jobs(
            latest_finalizable_week=latest_finalizable_week,
            scope_evidence=scope.scope_evidence(), jobs=jobs,
        )

    async def materialize_week(self, settlement_week: int) -> MaterializationResult:
        scope = await self.chain.read_authoritative_scope()
        jobs = []
        for vault in scope.vaults:
            job = build_materialization_job(vault, settlement_week=settlement_week)
            if self.prepare_vault is not None and job["state"] == "ready":
                # Local Legend work is claimed only after this intent is durable.
                # The settlement submit claim excludes this state.
                job["state"] = "precondition_pending"
            jobs.append(job)

        return await self.queue.materialize_week(
            settlement_week=settlement_week,
            counter_count=scope.counter_count,
            source_slot=scope.source_slot,
            source_slot_min=scope.source_slot_min,
            source_slot_max=scope.source_slot_max,
            scope_evidence=scope.scope_evidence(),
            jobs=jobs,
        )


class SettlementWorker:
    def __init__(
        self,
        *,
        queue: Any,
        reconciler: Any,
        worker_id: str,
        config: Optional[DirectConfig] = None,
        submitter: Optional[Submitter] = None,
        lease_seconds: int = 300,
        heartbeat_interval_seconds: Optional[float] = None,
        prepare_vault: Optional[PrepareVault] = None,
    ) -> None:
        if submitter is None and config is None:
            raise ValueError("settlement worker requires a config or submitter")
        self.queue = queue
        self.reconciler = reconciler
        self.worker_id = worker_id
        self.config = config
        self.lease_seconds = lease_seconds
        self.heartbeat_interval_seconds = (
            max(float(heartbeat_interval_seconds), 0.001)
            if heartbeat_interval_seconds is not None
            else max(min(float(lease_seconds) / 3.0, 60.0), 1.0)
        )
        self.submitter = submitter or self._submit_on_chain
        self.prepare_vault = prepare_vault
        self.compute_unit_limit = SETTLEMENT_COMPUTE_UNIT_LIMIT
        self._prepared_signatures: dict[str, str] = {}
        self._accepted_signatures: dict[str, str] = {}

    async def _run_preparations(
        self,
        *,
        max_jobs: int,
        vault_id: Optional[int],
    ) -> None:
        claim_preparation = getattr(self.queue, "claim_preparation", None)
        finish_preparation = getattr(self.queue, "finish_preparation", None)
        if (
            self.prepare_vault is None
            or claim_preparation is None
            or finish_preparation is None
        ):
            return
        for _ in range(max(int(max_jobs), 0)):
            claim = await claim_preparation(
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
                vault_id=vault_id,
            )
            if claim is None:
                return
            try:
                result = await self.prepare_vault(claim)
            except Exception as exc:
                await finish_preparation(
                    claim,
                    completed=False,
                    error=str(exc),
                    retry_seconds=min(60 * (2 ** min(claim.attempt_count, 6)), 3600),
                    result=None,
                )
                continue
            await finish_preparation(
                claim,
                completed=True,
                error=None,
                retry_seconds=1,
                result=result,
            )

    async def _submit_on_chain(self, claim: SettlementClaim) -> str:
        if self.config is None:
            raise ValueError("Solana settlement config is unavailable")
        precondition_result = claim.precondition_result or {}
        transport_plan = precondition_result.get("transport")
        if not isinstance(transport_plan, Mapping):
            raise SettlementTransportStaleError(
                "settlement transport precondition is missing"
            )

        async def persist_prepared_signature(signature: str) -> None:
            await self.queue.mark_prepared(
                claim,
                signature,
                compute_unit_limit=self.compute_unit_limit,
                transport_plan=transport_plan,
            )
            self._prepared_signatures[claim.id] = signature

        async def persist_accepted_signature(signature: str) -> None:
            await self.queue.mark_submitted(claim, signature)
            self._accepted_signatures[claim.id] = signature

        return await send_distribute_epoch_rewards(
            config=self.config,
            vault_id=claim.vault_id,
            settlement_week=claim.settlement_week,
            compute_unit_limit=self.compute_unit_limit,
            on_prepared=persist_prepared_signature,
            on_submitted=persist_accepted_signature,
            transport_plan=transport_plan,
        )

    async def _submit_with_heartbeat(self, claim: SettlementClaim) -> str:
        renew = getattr(self.queue, "renew_lease", None)
        if renew is None:
            return await self.submitter(claim)

        stopped = asyncio.Event()
        heartbeat_error: list[Exception] = []

        async def heartbeat() -> None:
            while not stopped.is_set():
                try:
                    await asyncio.wait_for(
                        stopped.wait(),
                        timeout=self.heartbeat_interval_seconds,
                    )
                    return
                except asyncio.TimeoutError:
                    try:
                        await renew(claim, lease_seconds=self.lease_seconds)
                    except Exception as exc:
                        heartbeat_error.append(exc)
                        return

        heartbeat_task = asyncio.create_task(heartbeat())
        try:
            signature = await self.submitter(claim)
        finally:
            stopped.set()
            await heartbeat_task

        if heartbeat_error:
            # The chain result is still returned so the fenced signature write is
            # attempted. If the fence was lost, lifecycle/open-week reconciliation
            # prevents a blind resend.
            pass
        return signature

    async def run_cycle(
        self,
        *,
        max_jobs: int = 10,
        vault_id: Optional[int] = None,
    ) -> SettlementCycleResult:
        reaped = await self.queue.reap_stale_leases()
        retry_repairable = getattr(self.queue, "retry_repairable_blocks", None)
        if retry_repairable is not None:
            await retry_repairable(limit=max_jobs)
        await self._run_preparations(max_jobs=max_jobs, vault_id=vault_id)
        reconciled = await self.reconciler.run_pending(limit=max_jobs, vault_id=vault_id)
        submitted = 0
        blocked = 0

        for _ in range(max(int(max_jobs), 0)):
            claim = await self.queue.claim(
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
                vault_id=vault_id,
            )
            if claim is None:
                break
            try:
                signature = await self._submit_with_heartbeat(claim)
            except SettlementInvariantError as exc:
                await self.queue.mark_blocked(claim, error=str(exc))
                blocked += 1
                continue
            except SettlementTransportStaleError as exc:
                self._prepared_signatures.pop(claim.id, None)
                await self.queue.return_to_preparation(claim, error=str(exc))
                continue
            except AcceptedSettlementTransactionError as exc:
                persisted_signature = self._accepted_signatures.pop(claim.id, None)
                self._prepared_signatures.pop(claim.id, None)
                if persisted_signature is not None:
                    submitted += 1
                    continue
                await self.queue.mark_ambiguous(
                    claim,
                    error=str(exc),
                    error_class="ambiguous_submit",
                    tx_signature=exc.signature,
                )
                break
            except Exception as exc:
                persisted_signature = self._accepted_signatures.pop(claim.id, None)
                if persisted_signature is not None:
                    self._prepared_signatures.pop(claim.id, None)
                    submitted += 1
                    continue
                prepared_signature = self._prepared_signatures.pop(claim.id, None)
                # send_distribute_epoch_rewards can lose the response after RPC
                # acceptance. Every non-preflight failure reconciles before resend.
                ambiguous_args = {
                    "error": str(exc),
                    "error_class": classify_submit_error(exc),
                }
                if prepared_signature is not None:
                    ambiguous_args["tx_signature"] = prepared_signature
                await self.queue.mark_ambiguous(claim, **ambiguous_args)
                break
            persisted_signature = self._accepted_signatures.pop(claim.id, None)
            self._prepared_signatures.pop(claim.id, None)
            if persisted_signature is None:
                try:
                    await self.queue.mark_submitted(claim, signature)
                except Exception:
                    # Injected submitters do not have the accepted callback. Their
                    # response is still treated as ambiguous if the fenced write
                    # cannot be completed.
                    break
            submitted += 1

        reconciled += await self.reconciler.run_pending(limit=max_jobs, vault_id=vault_id)
        return SettlementCycleResult(
            reaped=reaped,
            reconciled=reconciled,
            submitted=submitted,
            blocked=blocked,
        )
