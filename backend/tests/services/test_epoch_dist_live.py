"""
Tests for epoch distribution on-chain processing.

Covers:
- Live mode: calls send_distribute_epoch_rewards, records real sig
- Error handling: config missing, tx failure
- Points-period vs on-chain routing
- Multiple distributions
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pending_distribution(
    vault_id: int = 1,
    distribution_id: str = "dist-001",
    epoch: int = 116,
    dung_to_mint: int = 10,
    cal_to_convert: int = 10000,
) -> dict:
    """Create a mock epoch_distributions row."""
    return {
        "id": distribution_id,
        "epoch": epoch,
        "vault_id": vault_id,
        "vault_signature": "aa" * 64,
        "cal_to_convert": cal_to_convert,
        "dung_to_mint": dung_to_mint,
        "leaderboard_amount": 6,  # ~55% of 10
        "staker_amount": 3,       # ~27% of 10
        "local_legend_amount": 0,
        "pol_amount": 1,          # ~5% of 10
        "protocol_amount": 1,     # ~10% of 10 (rounded)
        "status": "pending",
        "is_points_period": False,
        "attempt_count": 0,
        "staker_count": 0,
        "unlock_pct": 0,
        "locked_staker_amount": 0,
    }


class FakeDB:
    """Supabase-like chainable mock that captures updates."""

    def __init__(self, pending_rows=None, claim_returns_rows: bool = True, table_rows=None):
        self._pending_rows = pending_rows or []
        self._table_rows = table_rows or {}
        self._claim_returns_rows = claim_returns_rows
        self.updates_captured: List[Dict[str, Any]] = []
        self.inserts_captured: List[Dict[str, Any]] = []
        self.order_calls: List[tuple[str, bool]] = []
        self.eq_calls: List[tuple[Any, Any]] = []
        self._current_table = ""
        self._last_operation = ""
        self._query_filters: List[tuple[str, str, Any]] = []
        self._query_limit: Optional[int] = None
        self._query_order: Optional[tuple[str, bool]] = None

    def from_(self, table):
        self._current_table = table
        self._query_filters = []
        self._query_limit = None
        self._query_order = None
        return self

    def table(self, table):
        return self.from_(table)

    def select(self, *a, **kw):
        self._last_operation = "select"
        return self

    def eq(self, *a, **kw):
        if a:
            self.eq_calls.append((a[0], a[1] if len(a) > 1 else None))
            self._query_filters.append(
                ("eq", a[0], a[1] if len(a) > 1 else None)
            )
        return self

    def gte(self, *a, **kw):
        if a:
            self._query_filters.append(
                ("gte", a[0], a[1] if len(a) > 1 else None)
            )
        return self

    def lt(self, *a, **kw):
        if a:
            self._query_filters.append(
                ("lt", a[0], a[1] if len(a) > 1 else None)
            )
        return self

    def order(self, column, desc=False):
        self.order_calls.append((column, desc))
        self._query_order = (column, desc)
        return self

    def limit(self, value, *a, **kw):
        self._query_limit = int(value)
        return self

    def single(self):
        return self

    def update(self, data):
        self._last_operation = "update"
        self.updates_captured.append(data)
        return self

    def insert(self, data):
        self._last_operation = "insert"
        self.inserts_captured.append(data)
        return self

    def upsert(self, data, **kw):
        self._last_operation = "upsert"
        self.inserts_captured.append(data)
        return self

    def execute(self):
        if self._current_table == "epoch_distributions":
            if self._last_operation == "update" and not self._claim_returns_rows:
                return SimpleNamespace(data=[])
            return SimpleNamespace(data=self._pending_rows)
        if self._current_table == "confirmed_vault_completion_candidates":
            rows = list(
                self._table_rows.get(
                    "confirmed_vault_completion_candidates",
                    self._table_rows.get("vault_completions", []),
                )
            )
            for operation, column, expected in self._query_filters:
                if operation == "eq":
                    rows = [row for row in rows if row.get(column) == expected]
                elif operation == "gte":
                    rows = [row for row in rows if row.get(column) >= expected]
                elif operation == "lt":
                    rows = [row for row in rows if row.get(column) < expected]
            if self._query_order is not None:
                column, descending = self._query_order
                rows.sort(key=lambda row: row.get(column), reverse=descending)
            if self._query_limit is not None:
                rows = rows[: self._query_limit]
            return SimpleNamespace(data=rows)
        if self._current_table in self._table_rows:
            return SimpleNamespace(data=self._table_rows[self._current_table])
        if self._current_table == "vault_distributions":
            return SimpleNamespace(data=[])
        if self._current_table == "vault_leaderboards":
            return SimpleNamespace(data=[])
        if self._current_table == "vault_stakes":
            return SimpleNamespace(data=[])
        if self._current_table == "vault_distribution_config":
            return SimpleNamespace(data={"pol_account": "", "protocol_treasury": ""})
        if self._current_table == "distribution_receipts":
            return SimpleNamespace(data=[])
        return SimpleNamespace(data=[])

    def rpc(self, name, params=None):
        """Mock Supabase RPC calls."""
        if name != "get_confirmed_local_legend_candidates":
            return _ExecutableResponse([])

        params = params or {}
        completed_from = datetime.fromisoformat(
            str(params["p_completed_from"]).replace("Z", "+00:00")
        )
        completed_before = datetime.fromisoformat(
            str(params["p_completed_before"]).replace("Z", "+00:00")
        )
        rows = self._table_rows.get(
            "confirmed_vault_completion_candidates",
            self._table_rows.get("vault_completions", []),
        )
        aggregate: Dict[str, Dict[str, Any]] = {}
        confirmed_receipt_count = 0
        for row in rows:
            completed_at = datetime.fromisoformat(
                str(row["completed_at"]).replace("Z", "+00:00")
            )
            tx_signature = str(row.get("on_chain_tx") or "")
            authoritative = bool(
                row.get("vault_id") == params["p_vault_id"]
                and completed_from <= completed_at < completed_before
                and row.get("chain_confirmation_status") == "confirmed"
                and row.get("completion_receipt_pda")
                and row.get("completion_evidence_hash")
                and row.get("chain_confirmed_at")
                and not tx_signature.startswith("exists:")
            )
            if not authoritative:
                continue
            confirmed_receipt_count += 1
            candidate = aggregate.setdefault(
                row["wallet"],
                {
                    "wallet": row["wallet"],
                    "completion_count": 0,
                    "first_completed_at": completed_at.isoformat(),
                },
            )
            candidate["completion_count"] += 1
            if completed_at < datetime.fromisoformat(candidate["first_completed_at"]):
                candidate["first_completed_at"] = completed_at.isoformat()

        candidates = sorted(
            aggregate.values(),
            key=lambda row: (
                -row["completion_count"],
                row["first_completed_at"],
                row["wallet"],
            ),
        )
        return _ExecutableResponse(
            {
                "authoritative": True,
                "confirmed_receipt_count": confirmed_receipt_count,
                "wallet_count": len(candidates),
                "candidates": candidates,
            }
        )


class _ExecutableResponse:
    def __init__(self, data: Any):
        self.data = data

    def execute(self):
        return self


def _make_fake_config():
    """Create a mock DirectConfig."""
    return SimpleNamespace(
        rpc_url="https://api.devnet.solana.com",
        payer=SimpleNamespace(pubkey=lambda: "FakePayer111"),
        program_id="FakeProgram111",
        dung_mint_address="FakeDungMint111",
    )


WINNER_WALLET = "Ch8uwuNxXkQBTJfBNbCq57yhaKdADCTiLLHqzb7G9uXF"
RUNNER_UP_WALLET = "3boUdoGfS1QMJ9pGQhZGNj8n7w1M3YDnL2a1tDk9K1aR"
PREVIOUS_WALLET = "9h6UJdZqUPNnShaUHkSoxvEeZ7gBeNxzXGQcShhBnzEP"
VAULT_SIGNATURE = "aa" * 64


def _legend_row(**overrides: Any) -> dict:
    row = {
        "vault_id": 7,
        "holder": PREVIOUS_WALLET,
        "election_period": 0,
        "term_start_epoch": 10,
        "term_end_epoch": 18,
        "completions_at_election": 0,
        "runner_up": None,
        "runner_up_completions": 0,
        "total_earned": "0",
        "is_active": True,
        "is_bootstrap": True,
    }
    row.update(overrides)
    return row


def _completion(
    wallet: str,
    completed_at_s: int,
    validated: bool = True,
    chain_confirmation_status: str = "confirmed",
) -> dict:
    return {
        "vault_id": 7,
        "vault_signature": VAULT_SIGNATURE,
        "wallet": wallet,
        "completed_at": datetime.fromtimestamp(completed_at_s, timezone.utc).isoformat().replace("+00:00", "Z"),
        "validated": validated,
        "chain_confirmation_status": chain_confirmation_status,
        "completion_receipt_pda": "receipt-pda",
        "completion_evidence_hash": "\\x" + "ab" * 32,
        "chain_confirmed_at": datetime.fromtimestamp(completed_at_s, timezone.utc).isoformat().replace("+00:00", "Z"),
        "on_chain_tx": None,
    }


def _last_rollover_audit(db: "FakeDB") -> dict:
    for row in reversed(db.inserts_captured):
        if "outcome" in row and "term_end_epoch" in row:
            return row
    raise AssertionError("No Local Legend rollover audit row captured")


def _frozen_legend_intent(
    *,
    winner: Optional[str] = WINNER_WALLET,
    settlement_week: int = 18,
) -> dict[str, Any]:
    outcome = "elected" if winner else "dormant"
    return {
        "required": True,
        "settlement_week": str(settlement_week),
        "vault_id": "7",
        "vault_signature": VAULT_SIGNATURE,
        "term_start_epoch": "10",
        "term_end_epoch": "18",
        "previous_holder": PREVIOUS_WALLET,
        "outcome": outcome,
        "winner": winner,
        "winner_completions": "1" if winner else "0",
        "runner_up": None,
        "runner_up_completions": "0",
        "candidate_tiebreak_evidence": (
            [{
                "wallet": winner,
                "completion_count": "1",
                "first_completed_at": "1970-01-01T00:10:01+00:00",
            }]
            if winner
            else []
        ),
    }


def _build_processor(
    pending_rows=None,
    solana_config=None,
    pol_account="FakePOL111",
    protocol_treasury="FakeTreasury111",
    claim_returns_rows: bool = True,
    table_rows=None,
    confirmed_completion_provider=None,
):
    """Build an EpochProcessor with mocked dependencies."""
    db = FakeDB(
        pending_rows=pending_rows or [],
        claim_returns_rows=claim_returns_rows,
        table_rows=table_rows,
    )

    from app.services.epoch_processor import EpochProcessor
    from app.settlement_clock import SettlementClock

    processor = EpochProcessor(
        supabase_client=db,
        solana_config=solana_config or _make_fake_config(),
        confirmed_completion_provider=confirmed_completion_provider,
        settlement_clock=SettlementClock.v2_only(),
    )
    candidate_reader = (
        processor.confirmed_completion_provider.list_confirmed_local_legend_candidates
    )
    if not isinstance(candidate_reader, AsyncMock):
        processor.confirmed_completion_provider.list_confirmed_local_legend_candidates = (
            AsyncMock(wraps=candidate_reader)
        )

    # Mock the points service to report non-points period
    processor.points_service = MagicMock()
    processor.points_service.is_points_period_active = AsyncMock(return_value=False)

    # Mock vault repo methods used in _record_distribution_ledger
    processor.vault_repo = MagicMock()
    processor.vault_repo.get_unique_staker_count = AsyncMock(return_value=0)
    processor.vault_repo.get_local_legend = AsyncMock(return_value=None)
    processor.vault_repo.get_vault_leaderboard = AsyncMock(return_value=[])
    processor.vault_repo.get_vault_stakes = AsyncMock(return_value=[])

    indexed_legends = (table_rows or {}).get("indexed_legends", [])
    if indexed_legends:
        indexed = indexed_legends[0]
        processor._read_authoritative_local_legend = AsyncMock(
            return_value=SimpleNamespace(
                holder=indexed.get("holder"),
                is_active=bool(indexed.get("is_active", True)),
                term_start_epoch=int(indexed.get("term_start_epoch") or 0),
                term_end_epoch=int(indexed.get("term_end_epoch") or 0),
            )
        )

    return processor, db


def test_latest_finalizable_week_does_not_move_backward_at_clock_cutover():
    from app.settlement_clock import (
        SETTLEMENT_WEEK_DURATION_SECONDS,
        SETTLEMENT_WEEK_V2_ANCHOR,
        SettlementClock,
    )

    transition_week = 200
    cutover = SETTLEMENT_WEEK_V2_ANCHOR + (
        transition_week * SETTLEMENT_WEEK_DURATION_SECONDS
    )
    clock = SettlementClock.with_legacy_cutover(cutover)
    processor, _ = _build_processor()

    assert processor._latest_finalizable_epoch(clock, cutover) == transition_week - 1


class FakeLock:
    def __init__(self, acquired: bool = True):
        self.acquired = acquired
        self.acquire_calls = 0
        self.release_calls = 0

    async def acquire(self) -> bool:
        self.acquire_calls += 1
        return self.acquired

    async def release(self) -> bool:
        self.release_calls += 1
        return True


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLiveMode:
    """All live entry points delegate to the durable settlement worker."""

    @staticmethod
    def _install_worker(processor, *, submitted: int = 0):
        result = SimpleNamespace(
            reaped=1,
            reconciled=2,
            submitted=submitted,
            blocked=0,
        )
        worker = SimpleNamespace(run_cycle=AsyncMock(return_value=result))
        processor._settlement_chain = object()
        processor._settlement_worker = worker
        return worker

    def test_process_pending_delegates_to_fenced_worker(self):
        processor, _db = _build_processor()
        worker = self._install_worker(processor, submitted=1)

        count = asyncio.run(processor._process_pending_onchain_distributions(vault_id=7))

        assert count == 1
        worker.run_cycle.assert_awaited_once_with(max_jobs=10, vault_id=7)

    def test_legacy_queue_path_is_rejected(self):
        from app.services.settlement_queue import SettlementStateError

        processor, _db = _build_processor()

        with pytest.raises(SettlementStateError, match="legacy epoch_distributions"):
            asyncio.run(
                processor._queue_distribution(
                    epoch=116,
                    vault_signature="aa" * 64,
                    vault_id=7,
                    cal_amount=10,
                    dung_to_mint=10,
                )
            )

    def test_legacy_unfenced_claim_path_is_rejected(self):
        from app.services.settlement_queue import SettlementStateError

        processor, _db = _build_processor()

        with pytest.raises(SettlementStateError, match="legacy distribution claims"):
            asyncio.run(processor._claim_distribution_for_processing("dist-1", 1))

    def test_settlement_cycle_uses_shared_lock(self):
        """Admin/cron entry point must share the same processor lease."""
        processor, _db = _build_processor(pending_rows=[])
        fake_lock = FakeLock(acquired=True)
        processor._lock = fake_lock
        processor._recover_open_settlement_weeks = AsyncMock(return_value=0)

        check_transition = AsyncMock(return_value=True)
        process_pending = AsyncMock(side_effect=[3, 0])
        get_stored_epoch = AsyncMock(side_effect=[10, 11])
        has_unfinished = AsyncMock(side_effect=[False, True])
        with patch.object(processor, "check_epoch_transition", check_transition):
            with patch.object(processor, "process_pending_distributions", process_pending):
                with patch.object(processor, "get_stored_epoch", get_stored_epoch):
                    with patch.object(
                        processor._settlement_queue,
                        "has_unfinished_jobs",
                        has_unfinished,
                    ):
                        transitioned, processed = asyncio.run(
                            processor.process_settlement_cycle()
                        )

        assert transitioned is True
        assert processed == 3
        assert fake_lock.acquire_calls == 1
        assert fake_lock.release_calls == 1
        check_transition.assert_awaited_once()
        assert process_pending.await_count == 2

    def test_settlement_cycle_does_not_plan_past_unfinished_cursor_week(self):
        """Later weeks must not snapshot chain state while the cursor week is open."""
        processor, _db = _build_processor(pending_rows=[])
        processor._lock = FakeLock(acquired=True)
        processor._recover_open_settlement_weeks = AsyncMock(return_value=0)

        check_transition = AsyncMock(return_value=True)
        with patch.object(processor, "check_epoch_transition", check_transition):
            with patch.object(
                processor,
                "process_pending_distributions",
                AsyncMock(return_value=0),
            ):
                with patch.object(
                    processor,
                    "get_stored_epoch",
                    AsyncMock(return_value=10),
                ):
                    with patch.object(
                        processor._settlement_queue,
                        "has_unfinished_jobs",
                        AsyncMock(return_value=True),
                    ):
                        transitioned, processed = asyncio.run(
                            processor.process_settlement_cycle()
                        )

        assert transitioned is False
        assert processed == 0
        check_transition.assert_not_awaited()

    def test_settlement_cycle_skips_when_lock_is_held_elsewhere(self):
        """Cron/admin callers must not process while another worker owns the lease."""
        processor, _db = _build_processor(pending_rows=[])
        processor._lock = FakeLock(acquired=False)

        check_transition = AsyncMock(return_value=True)
        process_pending = AsyncMock(return_value=3)
        with patch.object(processor, "check_epoch_transition", check_transition):
            with patch.object(processor, "process_pending_distributions", process_pending):
                transitioned, processed = asyncio.run(processor.process_settlement_cycle())

        assert transitioned is False
        assert processed == 0
        check_transition.assert_not_called()
        process_pending.assert_not_called()

    def test_no_longer_records_offchain_ledger(self):
        """Distribution processing no longer recomputes off-chain receipt ledgers."""
        processor, _db = _build_processor()

        assert asyncio.run(processor._record_distribution_ledger()) is None

    def test_requires_config(self):
        """Config failure propagates so the cycle cannot report false success."""
        processor, _db = _build_processor(solana_config=None)
        processor.config = None

        with patch("app.services.epoch_processor.load_default_config", side_effect=RuntimeError("no keypair")):
            with pytest.raises(RuntimeError, match="no keypair"):
                asyncio.run(processor._process_pending_onchain_distributions())

    def test_tx_failure_enters_reconciliation_instead_of_terminal_failed(self):
        from app.services.settlement_queue import SettlementClaim
        from app.services.settlement_worker import SettlementWorker

        claim = SettlementClaim.from_row({
            "id": "job-1",
            "run_id": "run-1",
            "settlement_week": "116",
            "vault_id": "7",
            "vault_signature": "aa" * 64,
            "state": "leased",
            "lease_owner": "worker-1",
            "lease_token": "lease-1",
            "attempt_count": 1,
            "expected_pre_open_week": "116",
            "auto_roll_from_empty": False,
            "tx_signature": None,
            "raw_snapshot": {},
        })

        class Queue:
            def __init__(self):
                self.claimed = False
                self.ambiguous_errors: list[tuple[str, str]] = []
                self.blocked_errors: list[str] = []

            async def reap_stale_leases(self):
                return 0

            async def claim(self, **_kwargs):
                if self.claimed:
                    return None
                self.claimed = True
                return claim

            async def mark_ambiguous(self, _claim, *, error, error_class):
                self.ambiguous_errors.append((error_class, error))

            async def mark_blocked(self, _claim, *, error):
                self.blocked_errors.append(error)

            async def mark_submitted(self, *_args, **_kwargs):
                raise AssertionError("send must fail")

        class Reconciler:
            async def run_pending(self, **_kwargs):
                return 0

        async def fail_submit(_claim):
            raise RuntimeError("distribute_epoch_rewards failed: InsufficientTribute")

        queue = Queue()
        worker = SettlementWorker(
            queue=queue,
            reconciler=Reconciler(),
            worker_id="worker-1",
            submitter=fail_submit,
        )

        result = asyncio.run(worker.run_cycle(max_jobs=1))

        assert result.submitted == 0
        assert queue.blocked_errors == []
        assert queue.ambiguous_errors == [(
            "deterministic_submit",
            "distribute_epoch_rewards failed: InsufficientTribute",
        )]


class TestNoPendingDistributions:
    """No pending distributions returns 0."""

    def test_no_pending_returns_zero(self):
        """A worker cycle with no claim returns zero submitted jobs."""
        processor, _db = _build_processor()
        worker = TestLiveMode._install_worker(processor, submitted=0)

        count = asyncio.run(processor._process_pending_onchain_distributions())

        assert count == 0
        worker.run_cycle.assert_awaited_once()


class TestMultipleDistributions:
    """Multiple distributions in a batch."""

    def test_processes_multiple_vaults(self):
        """Compatibility return value reports all submitted durable jobs."""
        processor, _db = _build_processor()
        worker = TestLiveMode._install_worker(processor, submitted=2)

        count = asyncio.run(processor._process_pending_onchain_distributions())

        assert count == 2
        worker.run_cycle.assert_awaited_once_with(max_jobs=10, vault_id=None)


class TestLocalLegendRollover:
    """Local Legend terms roll before settlement distribution is queued."""

    def test_actual_candidate_consumer_excludes_legacy_unverified_rows(self):
        processor, _ = _build_processor(
            table_rows={
                "confirmed_vault_completion_candidates": [
                    _completion(
                        WINNER_WALLET,
                        601,
                        validated=False,
                        chain_confirmation_status="legacy_unverified",
                    ),
                    _completion(
                        WINNER_WALLET,
                        602,
                        validated=False,
                        chain_confirmation_status="legacy_unverified",
                    ),
                    _completion(RUNNER_UP_WALLET, 603),
                ]
            }
        )

        with patch(
            "app.services.epoch_processor._epoch_start_datetime",
            side_effect=lambda epoch, _clock: datetime.fromtimestamp(epoch * 60, timezone.utc),
        ):
            candidates = asyncio.run(
                processor._derive_local_legend_candidates(
                    vault_id=7,
                    vault_signature=VAULT_SIGNATURE,
                    term_start_epoch=10,
                    term_end_epoch=11,
                )
            )

        assert candidates == [
            {
                "wallet": RUNNER_UP_WALLET,
                "completion_count": 1,
                "first_completed_at": datetime.fromtimestamp(603, timezone.utc),
            }
        ]

    def test_bootstrap_rolls_to_elected_winner(self):
        processor, db = _build_processor(
            table_rows={
                "indexed_legends": [_legend_row()],
                "vault_completions": [
                    _completion(WINNER_WALLET, 601),
                    _completion(WINNER_WALLET, 602),
                    _completion(RUNNER_UP_WALLET, 603),
                ],
                "local_legend_rollovers": [],
            }
        )
        elect = AsyncMock(return_value="elect-sig")

        with patch("app.services.epoch_processor._epoch_start_datetime", side_effect=lambda epoch, _clock: datetime.fromtimestamp(epoch * 60, timezone.utc)):
            with patch("app.services.epoch_processor.send_elect_local_legend", elect):
                asyncio.run(
                    processor._rollover_local_legend_for_vault(
                        ended_epoch=18,
                        vault_id=7,
                        vault_signature=VAULT_SIGNATURE,
                    )
                )

        elect.assert_called_once_with(
            config=processor.config,
            vault_id=7,
            term_start_epoch=18,
            winner=WINNER_WALLET,
            winner_completions=2,
            runner_up=RUNNER_UP_WALLET,
            runner_up_completions=1,
        )
        audit = _last_rollover_audit(db)
        assert audit["outcome"] == "elected"
        assert audit["status"] == "confirmed"
        assert audit["tx_signature"] == "elect-sig"

    def test_election_counts_all_confirmed_receipts_beyond_query_limit(self):
        processor, _ = _build_processor(
            table_rows={
                "indexed_legends": [_legend_row()],
                "vault_completions": [
                    *[_completion(RUNNER_UP_WALLET, 601) for _ in range(5000)],
                    *[_completion(WINNER_WALLET, 602) for _ in range(5001)],
                ],
                "local_legend_rollovers": [],
            }
        )
        elect = AsyncMock(return_value="complete-election-sig")

        with patch(
            "app.services.epoch_processor._epoch_start_datetime",
            side_effect=lambda epoch, _clock: datetime.fromtimestamp(epoch * 60, timezone.utc),
        ), patch(
            "app.services.epoch_processor.send_elect_local_legend", elect
        ):
            asyncio.run(
                processor._rollover_local_legend_for_vault(
                    ended_epoch=18,
                    vault_id=7,
                    vault_signature=VAULT_SIGNATURE,
                )
            )

        elect.assert_called_once_with(
            config=processor.config,
            vault_id=7,
            term_start_epoch=18,
            winner=WINNER_WALLET,
            winner_completions=5001,
            runner_up=RUNNER_UP_WALLET,
            runner_up_completions=5000,
        )

    def test_re_elects_existing_holder_when_they_win_next_term(self):
        processor, db = _build_processor(
            table_rows={
                "indexed_legends": [
                    _legend_row(
                        holder=WINNER_WALLET,
                        is_bootstrap=False,
                        completions_at_election=4,
                    )
                ],
                "vault_completions": [
                    _completion(WINNER_WALLET, 601),
                    _completion(WINNER_WALLET, 602),
                ],
                "local_legend_rollovers": [],
            }
        )
        elect = AsyncMock(return_value="same-holder-sig")

        with patch("app.services.epoch_processor._epoch_start_datetime", side_effect=lambda epoch, _clock: datetime.fromtimestamp(epoch * 60, timezone.utc)):
            with patch("app.services.epoch_processor.send_elect_local_legend", elect):
                asyncio.run(
                    processor._rollover_local_legend_for_vault(
                        ended_epoch=18,
                        vault_id=7,
                        vault_signature=VAULT_SIGNATURE,
                    )
                )

        elect.assert_called_once()
        assert elect.call_args.kwargs["winner"] == WINNER_WALLET
        assert _last_rollover_audit(db)["previous_holder"] == WINNER_WALLET

    def test_elects_new_winner_over_previous_holder(self):
        processor, db = _build_processor(
            table_rows={
                "indexed_legends": [_legend_row(holder=PREVIOUS_WALLET, is_bootstrap=False)],
                "vault_completions": [
                    _completion(PREVIOUS_WALLET, 601),
                    _completion(WINNER_WALLET, 602),
                    _completion(WINNER_WALLET, 603),
                ],
                "local_legend_rollovers": [],
            }
        )
        elect = AsyncMock(return_value="new-winner-sig")

        with patch("app.services.epoch_processor._epoch_start_datetime", side_effect=lambda epoch, _clock: datetime.fromtimestamp(epoch * 60, timezone.utc)):
            with patch("app.services.epoch_processor.send_elect_local_legend", elect):
                asyncio.run(
                    processor._rollover_local_legend_for_vault(
                        ended_epoch=18,
                        vault_id=7,
                        vault_signature=VAULT_SIGNATURE,
                    )
                )

        assert elect.call_args.kwargs["winner"] == WINNER_WALLET
        assert elect.call_args.kwargs["runner_up"] == PREVIOUS_WALLET
        assert _last_rollover_audit(db)["outcome"] == "elected"

    def test_no_completions_marks_seat_dormant(self):
        processor, db = _build_processor(
            table_rows={
                "indexed_legends": [_legend_row()],
                "vault_completions": [],
                "local_legend_rollovers": [],
            }
        )
        deactivate = AsyncMock(return_value="dormant-sig")

        with patch("app.services.epoch_processor._epoch_start_datetime", side_effect=lambda epoch, _clock: datetime.fromtimestamp(epoch * 60, timezone.utc)):
            with patch("app.services.epoch_processor.send_deactivate_local_legend", deactivate):
                asyncio.run(
                    processor._rollover_local_legend_for_vault(
                        ended_epoch=18,
                        vault_id=7,
                        vault_signature=VAULT_SIGNATURE,
                    )
                )

        deactivate.assert_called_once_with(
            config=processor.config,
            vault_id=7,
            term_start_epoch=18,
        )
        audit = _last_rollover_audit(db)
        assert audit["outcome"] == "dormant"
        assert audit["status"] == "confirmed"

    def test_candidate_provider_failure_never_deactivates_legend(self):
        provider = MagicMock()
        provider.list_confirmed_local_legend_candidates = AsyncMock(
            side_effect=RuntimeError("candidate provider unavailable")
        )
        processor, _db = _build_processor(
            table_rows={
                "indexed_legends": [_legend_row()],
                "local_legend_rollovers": [],
            },
            confirmed_completion_provider=provider,
        )

        with pytest.raises(RuntimeError, match="candidate provider unavailable"):
            asyncio.run(
                processor._derive_local_legend_candidates(
                    vault_id=7,
                    vault_signature=VAULT_SIGNATURE,
                    term_start_epoch=10,
                    term_end_epoch=18,
                )
            )

    def test_candidate_provider_failure_leaves_election_retryable(self):
        from app.services.settlement_queue import SettlementStateError

        provider = MagicMock()
        provider.list_confirmed_local_legend_candidates = AsyncMock(
            side_effect=RuntimeError("candidate view unavailable")
        )
        processor, db = _build_processor(
            table_rows={
                "indexed_legends": [_legend_row()],
                "local_legend_rollovers": [],
            },
            confirmed_completion_provider=provider,
        )
        elect = AsyncMock(return_value="should-not-submit")
        deactivate = AsyncMock(return_value="should-not-submit")

        with patch(
            "app.services.epoch_processor._epoch_start_datetime",
            side_effect=lambda epoch, _clock: datetime.fromtimestamp(epoch * 60, timezone.utc),
        ), patch(
            "app.services.epoch_processor.send_elect_local_legend", elect
        ), patch(
            "app.services.epoch_processor.send_deactivate_local_legend", deactivate
        ):
            with pytest.raises(
                SettlementStateError,
                match="candidate view unavailable",
            ):
                asyncio.run(
                    processor._rollover_local_legend_for_vault(
                        ended_epoch=18,
                        vault_id=7,
                        vault_signature=VAULT_SIGNATURE,
                    )
                )

        elect.assert_not_called()
        deactivate.assert_not_called()
        assert not any("outcome" in row for row in db.inserts_captured)

    def test_confirmed_rollover_is_idempotent(self):
        processor, db = _build_processor(
            table_rows={
                "indexed_legends": [_legend_row()],
                "vault_completions": [_completion(WINNER_WALLET, 601)],
                "local_legend_rollovers": [{"id": "rollover-1", "status": "confirmed"}],
            }
        )
        elect = AsyncMock(return_value="elect-sig")
        processor._read_authoritative_local_legend = AsyncMock(
            return_value=SimpleNamespace(
                holder=WINNER_WALLET,
                is_active=True,
                term_start_epoch=18,
                term_end_epoch=26,
            )
        )

        with patch("app.services.epoch_processor._epoch_start_datetime", side_effect=lambda epoch, _clock: datetime.fromtimestamp(epoch * 60, timezone.utc)):
            with patch("app.services.epoch_processor.send_elect_local_legend", elect):
                asyncio.run(
                    processor._rollover_local_legend_for_vault(
                        ended_epoch=18,
                        vault_id=7,
                        vault_signature=VAULT_SIGNATURE,
                        frozen_intent=_frozen_legend_intent(),
                    )
                )

        elect.assert_not_called()
        assert _last_rollover_audit(db)["tx_signature"] == "chain-state-reconciled"

    def test_election_response_loss_reconciles_from_chain_and_restart_does_not_resend(self):
        processor, db = _build_processor(
            table_rows={
                "indexed_legends": [_legend_row()],
                "vault_completions": [_completion(WINNER_WALLET, 601)],
                "local_legend_rollovers": [],
            }
        )
        old_state = SimpleNamespace(
            holder=PREVIOUS_WALLET,
            is_active=True,
            term_start_epoch=10,
            term_end_epoch=18,
        )
        landed_state = SimpleNamespace(
            holder=WINNER_WALLET,
            is_active=True,
            term_start_epoch=18,
            term_end_epoch=26,
        )
        read_chain = AsyncMock(side_effect=[old_state, landed_state, landed_state])
        elect = AsyncMock(side_effect=TimeoutError("response lost after election landed"))

        with patch("app.services.epoch_processor._epoch_start_datetime", side_effect=lambda epoch, _clock: datetime.fromtimestamp(epoch * 60, timezone.utc)):
            with patch.object(processor, "_read_authoritative_local_legend", read_chain):
                with patch("app.services.epoch_processor.send_elect_local_legend", elect):
                    asyncio.run(
                        processor._rollover_local_legend_for_vault(
                            ended_epoch=18,
                            vault_id=7,
                            vault_signature=VAULT_SIGNATURE,
                            frozen_intent=_frozen_legend_intent(),
                        )
                    )
                    asyncio.run(
                        processor._rollover_local_legend_for_vault(
                            ended_epoch=18,
                            vault_id=7,
                            vault_signature=VAULT_SIGNATURE,
                            frozen_intent=_frozen_legend_intent(),
                        )
                    )

        elect.assert_awaited_once()
        audit = _last_rollover_audit(db)
        assert audit["status"] == "confirmed"
        assert audit["outcome"] == "elected"
        assert audit["tx_signature"] == "chain-state-reconciled"

    def test_wall_clock_term_does_not_reconcile_a_frozen_historical_rollover(self):
        processor, db = _build_processor(
            table_rows={
                "indexed_legends": [_legend_row()],
                "vault_completions": [_completion(WINNER_WALLET, 601)],
                "local_legend_rollovers": [],
            }
        )
        old_state = SimpleNamespace(
            holder=PREVIOUS_WALLET,
            is_active=True,
            term_start_epoch=10,
            term_end_epoch=18,
        )
        wrong_wall_clock_state = SimpleNamespace(
            holder=WINNER_WALLET,
            is_active=True,
            term_start_epoch=30,
            term_end_epoch=38,
        )
        processor._read_authoritative_local_legend = AsyncMock(
            side_effect=[old_state, wrong_wall_clock_state]
        )
        elect = AsyncMock(side_effect=TimeoutError("response lost"))

        with patch("app.services.epoch_processor.send_elect_local_legend", elect):
            with pytest.raises(TimeoutError, match="response lost"):
                asyncio.run(
                    processor._rollover_local_legend_for_vault(
                        ended_epoch=30,
                        vault_id=7,
                        vault_signature=VAULT_SIGNATURE,
                        frozen_intent=_frozen_legend_intent(settlement_week=30),
                    )
                )

        elect.assert_awaited_once_with(
            config=processor.config,
            vault_id=7,
            term_start_epoch=18,
            winner=WINNER_WALLET,
            winner_completions=1,
            runner_up=None,
            runner_up_completions=0,
        )
        assert _last_rollover_audit(db)["status"] == "failed"

    def test_dormant_response_loss_reconciles_from_chain_and_restart_does_not_resend(self):
        processor, db = _build_processor(
            table_rows={
                "indexed_legends": [_legend_row()],
                "vault_completions": [],
                "local_legend_rollovers": [],
            }
        )
        old_state = SimpleNamespace(
            holder=PREVIOUS_WALLET,
            is_active=True,
            term_start_epoch=10,
            term_end_epoch=18,
        )
        landed_state = SimpleNamespace(
            holder=PREVIOUS_WALLET,
            is_active=False,
            term_start_epoch=18,
            term_end_epoch=26,
        )
        read_chain = AsyncMock(side_effect=[old_state, landed_state, landed_state])
        deactivate = AsyncMock(side_effect=TimeoutError("response lost after dormancy landed"))

        with patch("app.services.epoch_processor._epoch_start_datetime", side_effect=lambda epoch, _clock: datetime.fromtimestamp(epoch * 60, timezone.utc)):
            with patch.object(processor, "_read_authoritative_local_legend", read_chain):
                with patch("app.services.epoch_processor.send_deactivate_local_legend", deactivate):
                    asyncio.run(
                        processor._rollover_local_legend_for_vault(
                            ended_epoch=18,
                            vault_id=7,
                            vault_signature=VAULT_SIGNATURE,
                            frozen_intent=_frozen_legend_intent(winner=None),
                        )
                    )
                    asyncio.run(
                        processor._rollover_local_legend_for_vault(
                            ended_epoch=18,
                            vault_id=7,
                            vault_signature=VAULT_SIGNATURE,
                            frozen_intent=_frozen_legend_intent(winner=None),
                        )
                    )

        deactivate.assert_awaited_once()
        audit = _last_rollover_audit(db)
        assert audit["status"] == "confirmed"
        assert audit["outcome"] == "dormant"
        assert audit["tx_signature"] == "chain-state-reconciled"

    def test_missing_indexed_legend_retries_instead_of_skipping_precondition(self):
        processor, _db = _build_processor(
            table_rows={"indexed_legends": [], "local_legend_rollovers": []}
        )
        processor._read_authoritative_local_legend = AsyncMock(
            return_value=SimpleNamespace(
                holder=PREVIOUS_WALLET,
                is_active=True,
                term_start_epoch=10,
                term_end_epoch=18,
            )
        )

        with pytest.raises(RuntimeError, match="indexed Local Legend is missing"):
            asyncio.run(
                processor._build_local_legend_intent(
                    ended_epoch=18,
                    vault_id=7,
                    vault_signature=VAULT_SIGNATURE,
                )
            )
        processor.confirmed_completion_provider.list_confirmed_local_legend_candidates.assert_not_awaited()

    def test_divergent_indexed_legend_retries_before_candidate_math(self):
        processor, _db = _build_processor(
            table_rows={
                "indexed_legends": [_legend_row()],
                "local_legend_rollovers": [],
            }
        )
        processor._read_authoritative_local_legend = AsyncMock(
            return_value=SimpleNamespace(
                holder=WINNER_WALLET,
                is_active=True,
                term_start_epoch=10,
                term_end_epoch=18,
            )
        )

        with pytest.raises(RuntimeError, match="diverges from finalized chain"):
            asyncio.run(
                processor._build_local_legend_intent(
                    ended_epoch=18,
                    vault_id=7,
                    vault_signature=VAULT_SIGNATURE,
                )
            )
        processor.confirmed_completion_provider.list_confirmed_local_legend_candidates.assert_not_awaited()

    def test_divergent_indexed_term_start_retries_before_candidate_math(self):
        processor, _db = _build_processor(
            table_rows={
                "indexed_legends": [_legend_row(term_start_epoch=10)],
                "local_legend_rollovers": [],
            }
        )
        processor._read_authoritative_local_legend = AsyncMock(
            return_value=SimpleNamespace(
                holder=PREVIOUS_WALLET,
                is_active=True,
                term_start_epoch=9,
                term_end_epoch=18,
            )
        )

        with pytest.raises(RuntimeError, match="diverges from finalized chain"):
            asyncio.run(
                processor._build_local_legend_intent(
                    ended_epoch=18,
                    vault_id=7,
                    vault_signature=VAULT_SIGNATURE,
                )
            )
        processor.confirmed_completion_provider.list_confirmed_local_legend_candidates.assert_not_awaited()

    def test_indexed_legend_read_failure_is_not_an_authoritative_no_row(self):
        processor, _db = _build_processor(
            table_rows={
                "indexed_legends": [_legend_row()],
                "local_legend_rollovers": [],
            }
        )
        processor._get_indexed_legend_row = AsyncMock(
            side_effect=RuntimeError("indexed legend database unavailable")
        )

        with pytest.raises(RuntimeError, match="indexed legend database unavailable"):
            asyncio.run(
                processor._build_local_legend_intent(
                    ended_epoch=18,
                    vault_id=7,
                    vault_signature=VAULT_SIGNATURE,
                )
            )
        processor.confirmed_completion_provider.list_confirmed_local_legend_candidates.assert_not_awaited()

    def test_frozen_intent_survives_candidate_drift_after_response_loss(self):
        provider = MagicMock()
        provider.list_confirmed_local_legend_candidates = AsyncMock(
            return_value=[{
                "wallet": WINNER_WALLET,
                "completion_count": 1,
                "first_completed_at": "1970-01-01T00:10:01+00:00",
            }]
        )
        processor, db = _build_processor(
            table_rows={
                "indexed_legends": [_legend_row()],
                "local_legend_rollovers": [],
            },
            confirmed_completion_provider=provider,
        )
        with patch(
            "app.services.epoch_processor._epoch_start_datetime",
            side_effect=lambda epoch, _clock: datetime.fromtimestamp(epoch * 60, timezone.utc),
        ):
            intent = asyncio.run(
                processor._build_local_legend_intent(
                    ended_epoch=18,
                    vault_id=7,
                    vault_signature=VAULT_SIGNATURE,
                )
            )

            provider.list_confirmed_local_legend_candidates.return_value = [{
                "wallet": RUNNER_UP_WALLET,
                "completion_count": 99,
                "first_completed_at": "1970-01-01T00:10:02+00:00",
            }]
            old_state = SimpleNamespace(
                holder=PREVIOUS_WALLET,
                is_active=True,
                term_start_epoch=10,
                term_end_epoch=18,
            )
            landed_state = SimpleNamespace(
                holder=WINNER_WALLET,
                is_active=True,
                term_start_epoch=18,
                term_end_epoch=26,
            )
            processor._read_authoritative_local_legend = AsyncMock(
                side_effect=[old_state, landed_state, landed_state]
            )
            elect = AsyncMock(
                side_effect=TimeoutError("response lost after election landed")
            )
            with patch("app.services.epoch_processor.send_elect_local_legend", elect):
                asyncio.run(
                    processor._rollover_local_legend_for_vault(
                        ended_epoch=18,
                        vault_id=7,
                        vault_signature=VAULT_SIGNATURE,
                        frozen_intent=intent,
                    )
                )
                asyncio.run(
                    processor._rollover_local_legend_for_vault(
                        ended_epoch=18,
                        vault_id=7,
                        vault_signature=VAULT_SIGNATURE,
                        frozen_intent=intent,
                    )
                )

        provider.list_confirmed_local_legend_candidates.assert_awaited_once()
        elect.assert_awaited_once()
        assert elect.call_args.kwargs["winner"] == WINNER_WALLET
        assert _last_rollover_audit(db)["winner"] == WINNER_WALLET

    def test_rollover_outcome_persistence_failure_never_completes_precondition(self):
        processor, _db = _build_processor(
            table_rows={
                "indexed_legends": [_legend_row()],
                "local_legend_rollovers": [],
            }
        )
        old_state = SimpleNamespace(
            holder=PREVIOUS_WALLET,
            is_active=True,
            term_start_epoch=10,
            term_end_epoch=18,
        )
        processor._read_authoritative_local_legend = AsyncMock(
            side_effect=[old_state, old_state]
        )
        processor._record_legend_rollover = AsyncMock(
            side_effect=RuntimeError("rollover audit write unavailable")
        )
        elect = AsyncMock(return_value="accepted-election-signature")

        with patch("app.services.epoch_processor.send_elect_local_legend", elect):
            with pytest.raises(RuntimeError, match="rollover audit write unavailable"):
                asyncio.run(
                    processor._rollover_local_legend_for_vault(
                        ended_epoch=18,
                        vault_id=7,
                        vault_signature=VAULT_SIGNATURE,
                        frozen_intent=_frozen_legend_intent(),
                    )
                )

        elect.assert_awaited_once()
