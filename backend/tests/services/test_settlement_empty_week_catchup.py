"""H1 orchestration proof using the settlement suite's injected fixture chain.

This models the frozen/pending LP queue; it is not an SBF or devnet proof.
"""
import asyncio
from unittest.mock import AsyncMock

import pytest

from app.services.epoch_processor import EpochProcessor
from app.services.settlement_chain import SettlementChain
from app.services.settlement_queue import MaterializationResult, SettlementClaim
from app.services.settlement_reconciler import SettlementReconciler
from app.services.settlement_worker import SettlementPlanner, SettlementWorker
from app.settlement_clock import SettlementClock
from test_settlement_state_machine import _vault, _claim_row


def test_quiet_deposit_two_empty_weeks_then_withdraw():
    async def scenario():
        clock = SettlementClock.v2_only()
        now = clock.week_finalization_time(11)
        vault = _vault(0, open_week=10)
        # Ordinary fixture deposit at week_start(10)+1: one W+1 target.
        position = {"lp": 100, "snapshot": 0, "pending": 100, "effective": 11}
        reads = []
        submitted = []

        def withdraw():
            if position["pending"] and vault["open_settlement_week"] < position["effective"]:
                raise ValueError("unresolved snapshot queue")
            amount = position["lp"]
            position["lp"] = 0
            return amount

        with pytest.raises(ValueError, match="unresolved"):
            withdraw()

        async def snapshot():
            reads.append(vault["open_settlement_week"])
            return 1, 1, 9000 + len(reads), (dict(vault),)

        async def read_vault(_id):
            reads.append(vault["open_settlement_week"])
            return dict(vault)

        chain = SettlementChain(
            object(), snapshot_reader=snapshot,
            vault_reader=read_vault,
            signature_reader=AsyncMock(return_value=("finalized", None)),
        )
        chain.read_chain_time = AsyncMock(side_effect=lambda: now)

        class Queue:
            cursor = 9
            row = None
            async def get_planning_cursor(self): return self.cursor
            async def reopen_zero_value_jobs(self, **kwargs): return 0
            async def materialize_week(self, **kwargs):
                week = kwargs["settlement_week"]
                job = kwargs["jobs"][0]
                self.row = _claim_row(state=job["state"], **{
                    **{k: v for k, v in job.items() if k != "state"},
                    "settlement_week": str(week), "id": f"job-{week}",
                })
                self.cursor = week
                return MaterializationResult(
                    run_id=f"run-{week}", settlement_week=week, state="materialized",
                    job_count=1, ready_count=int(job["state"] == "ready"), skipped_count=0,
                )
            async def has_unfinished_jobs(self, **kwargs):
                return self.row is not None and self.row["state"] not in ("confirmed", "skipped_empty")
            async def reap_stale_leases(self): return 0
            async def claim(self, **kwargs):
                if self.row and self.row["state"] == "ready":
                    self.row["state"] = "leased"
                    return SettlementClaim.from_row(self.row)
            async def mark_submitted(self, claim, signature):
                self.row.update(state="submitted", tx_signature=signature)
            async def claim_reconciliation(self, **kwargs):
                if self.row and self.row["state"] == "submitted":
                    return SettlementClaim.from_row(self.row)
            async def get_indexed_distribution(self, **kwargs): return None
            async def get_lifecycle_signature(self, claim): return claim.tx_signature
            async def finish_reconciliation(self, claim, **kwargs):
                assert kwargs["decision"] == "confirmed"
                self.row["state"] = kwargs["decision"]

        queue = Queue()
        reconciler = SettlementReconciler(queue=queue, chain=chain, worker_id="fixture")
        async def settle(claim):
            assert claim.settlement_week == vault["open_settlement_week"]
            assert now >= clock.week_finalization_time(claim.settlement_week)
            assert claim.dung_to_mint == 0
            submitted.append(claim.settlement_week)
            if position["pending"] and claim.settlement_week >= position["effective"]:
                position.update(snapshot=position["pending"], pending=0)
            vault["open_settlement_week"] += 1
            return f"settled-{claim.settlement_week}"

        worker = SettlementWorker(queue=queue, reconciler=reconciler, worker_id="fixture", submitter=settle)
        processor = EpochProcessor(object(), solana_config=object(), settlement_clock=clock)
        processor._settlement_chain = chain
        processor._settlement_queue = queue
        processor._settlement_planner = SettlementPlanner(queue=queue, chain=chain)
        processor._settlement_worker = worker
        async def process(**kwargs):
            return (await worker.run_cycle()).submitted
        processor.process_pending_distributions = process

        await processor._run_settlement_cycle_unlocked()
        assert submitted == [10, 11]
        assert vault["open_settlement_week"] == 12
        assert 11 in reads and 12 in reads
        assert queue.row["state"] == "confirmed"
        assert position["snapshot"] == 100
        assert withdraw() == 100
        assert position["lp"] == 0

    asyncio.run(scenario())
