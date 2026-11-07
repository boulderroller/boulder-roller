from __future__ import annotations

import asyncio
import json
import struct
from pathlib import Path
from typing import Any

import pytest


U64_MAX = 18_446_744_073_709_551_615


def _transport_plan() -> dict[str, str]:
    return {
        "transaction_version": "0",
        "lookup_table_address": "lookup-table-address",
        "lookup_table_generation": "1",
        "manifest_sha256": "a" * 64,
        "last_extended_slot": "99",
        "planned_serialized_bytes": "815",
    }


class _FailingStateQuery:
    def select(self, *_args: Any, **_kwargs: Any) -> "_FailingStateQuery":
        return self

    def eq(self, *_args: Any, **_kwargs: Any) -> "_FailingStateQuery":
        return self

    def limit(self, *_args: Any, **_kwargs: Any) -> "_FailingStateQuery":
        return self

    def execute(self) -> Any:
        raise RuntimeError("database unavailable")


class _FailingStateDB:
    def __init__(self) -> None:
        self.mutations: list[tuple[str, Any]] = []

    def from_(self, _table: str) -> _FailingStateQuery:
        return _FailingStateQuery()


def _vault(
    vault_id: int,
    *,
    open_week: int = 10,
    current_dung: int = 0,
    current_cal: int = 0,
    next_dung: int = 0,
    next_cal: int = 0,
) -> dict[str, Any]:
    return {
        "id": vault_id,
        "signature_hex": f"vault-{vault_id}",
        "pda": f"pda-{vault_id}",
        "account_layout": "idl",
        "open_settlement_week": open_week,
        "pending_rewards": current_dung,
        "cal_tribute_accumulated": current_cal,
        "pending_rewards_next_week": next_dung,
        "cal_tribute_accumulated_next": next_cal,
        "carry_record_royalty": 0,
        "carry_stakers": 0,
        "carry_local_legend": 0,
        "carry_pol": 0,
        "carry_treasury": 0,
    }


def _claim_row(
    *,
    state: str,
    lease_token: str = "lease-1",
    **overrides: Any,
) -> dict[str, Any]:
    row = {
        "id": "job-1",
        "run_id": "run-1",
        "settlement_week": "10",
        "vault_id": "0",
        "vault_signature": "vault-0",
        "state": state,
        "lease_owner": "worker-1",
        "lease_token": lease_token,
        "attempt_count": 0,
        "expected_pre_open_week": "10",
        "auto_roll_from_empty": False,
        "dung_to_mint": "0",
        "prepared_tx_signature": None,
        "tx_signature": None,
        "submit_started_at": "2026-07-13T12:00:00+00:00",
        "precondition_intent": None,
        "precondition_result": None,
        "raw_snapshot": {},
    }
    row.update(overrides)
    return row


def test_state_read_failure_never_bootstraps_or_advances() -> None:
    from app.services.epoch_processor import EpochProcessor

    db = _FailingStateDB()
    processor = EpochProcessor(db)

    with pytest.raises(RuntimeError, match="settlement planning state"):
        asyncio.run(processor.get_stored_epoch())

    assert db.mutations == []


def test_planning_requires_complete_authoritative_counter_scope() -> None:
    from app.services.settlement_chain import IncompleteVaultScopeError, SettlementChain

    async def read_snapshot() -> tuple[int, int, int, tuple[dict[str, Any], ...]]:
        return 2, 2, 9001, (_vault(0),)

    chain = SettlementChain(
        config=object(),
        snapshot_reader=read_snapshot,
    )

    with pytest.raises(IncompleteVaultScopeError, match="requires 2 vaults"):
        asyncio.run(chain.read_authoritative_scope())


def test_authoritative_scope_rejects_counter_mutation_during_snapshot() -> None:
    from app.services.settlement_chain import IncompleteVaultScopeError, SettlementChain

    calls = 0

    async def read_snapshot() -> tuple[int, int, int, tuple[dict[str, Any], ...]]:
        nonlocal calls
        calls += 1
        return 1, 2, 9000 + calls, (_vault(0), _vault(1))

    chain = SettlementChain(
        config=object(),
        snapshot_reader=read_snapshot,
        scope_read_retries=2,
    )

    with pytest.raises(IncompleteVaultScopeError, match="changed during authoritative read"):
        asyncio.run(chain.read_authoritative_scope())
    assert calls == 2


def test_authoritative_scope_batches_above_rpc_limit_without_protocol_cap() -> None:
    from app.services.settlement_chain import partition_vault_scope

    assert partition_vault_scope(0) == []
    assert partition_vault_scope(99) == [(0, 99)]
    assert partition_vault_scope(205) == [(0, 99), (99, 198), (198, 205)]

    source = (
        Path(__file__).parents[2] / "app" / "services" / "settlement_chain.py"
    ).read_text()
    assert "MAX_ATOMIC_SCOPE_VAULTS" not in source
    assert "scope exceeds the atomic getMultipleAccounts limit" not in source
    assert "batch_evidence" in source
    assert "source_slot_min" in source
    assert "source_slot_max" in source


def test_bootstrap_cursor_is_derived_from_open_weeks_not_legacy_state() -> None:
    from app.services.settlement_queue import safe_bootstrap_cursor

    assert safe_bootstrap_cursor([8, 11], latest_finalizable_week=12) == 7
    assert safe_bootstrap_cursor([13, 14], latest_finalizable_week=12) == 12
    assert safe_bootstrap_cursor([], latest_finalizable_week=12) == 12
    assert safe_bootstrap_cursor([0], latest_finalizable_week=12) == -1


def test_bootstrap_runtime_is_complete_and_replay_idempotent() -> None:
    from app.services.settlement_chain import AuthoritativeVaultScope
    from app.services.settlement_queue import SettlementQueue

    class RpcResult:
        data = [{
            "bootstrap_state": "initialized",
            "last_materialized_week": "7",
            "bootstrap_scope_hash": "scope-hash",
        }]

        def execute(self) -> "RpcResult":
            return self

    class DB:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        def rpc(self, name: str, params: dict[str, Any]) -> RpcResult:
            self.calls.append((name, params))
            return RpcResult()

    scope = AuthoritativeVaultScope(
        counter_count=2,
        source_slot=9001,
        vaults=(_vault(0, open_week=8), _vault(1, open_week=11)),
    )
    db = DB()
    queue = SettlementQueue(db)

    first = asyncio.run(queue.bootstrap(scope=scope, latest_finalizable_week=12))
    replay = asyncio.run(queue.bootstrap(scope=scope, latest_finalizable_week=12))

    assert first == replay == 7
    assert [name for name, _params in db.calls] == [
        "br_bootstrap_settlement_planning",
        "br_bootstrap_settlement_planning",
    ]
    first_params = db.calls[0][1]
    assert first_params == db.calls[1][1]
    assert first_params["p_counter_count"] == "2"
    assert first_params["p_latest_finalizable_week"] == "12"
    assert [vault["open_settlement_week"] for vault in first_params["p_vaults"]] == [
        "8",
        "11",
    ]


def test_materialization_failure_is_not_swallowed_or_followed_by_cursor_write() -> None:
    from app.services.settlement_queue import SettlementQueue

    class BrokenRpc:
        def execute(self) -> Any:
            raise RuntimeError("insert failed")

    class DB:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []
            self.table_calls: list[str] = []

        def rpc(self, name: str, params: dict[str, Any]) -> BrokenRpc:
            self.calls.append((name, params))
            return BrokenRpc()

        def from_(self, table: str) -> Any:
            self.table_calls.append(table)
            raise AssertionError("materialization must be one transactional RPC")

    db = DB()
    queue = SettlementQueue(db)
    job = {
        "vault_id": "0",
        "vault_signature": "vault-0",
        "state": "skipped_empty",
        "expected_pre_open_week": "10",
        "auto_roll_from_empty": False,
        "raw_snapshot": {},
    }

    with pytest.raises(RuntimeError, match="insert failed"):
        asyncio.run(
            queue.materialize_week(
                settlement_week=10,
                counter_count=1,
                source_slot=9001,
                jobs=[job],
            )
        )

    assert [name for name, _params in db.calls] == ["br_materialize_settlement_week"]
    assert db.table_calls == []


def test_quiet_open_week_is_ready_and_future_weeks_never_auto_roll() -> None:
    from app.services.settlement_chain import build_materialization_job

    snapshot = _vault(0, open_week=10, next_dung=U64_MAX)
    quiet = build_materialization_job(snapshot, settlement_week=10)
    assert quiet["state"] == "ready"
    assert quiet["skip_reason"] is None
    assert quiet["dung_to_mint"] == "0"
    assert quiet["auto_roll_from_empty"] is False
    for target in (11, 12):
        future = build_materialization_job(snapshot, settlement_week=target)
        assert future["state"] == "blocked"
        assert future["auto_roll_from_empty"] is False
        assert future["dung_to_mint"] == "0"
    promoted = build_materialization_job(
        _vault(0, open_week=11, current_dung=U64_MAX), settlement_week=11
    )
    assert promoted["state"] == "ready"
    assert promoted["dung_to_mint"] == str(U64_MAX)


def test_crash_after_claim_is_reaped_and_converges() -> None:
    from app.services.settlement_queue import SettlementClaim
    from app.services.settlement_worker import SettlementWorker

    class Queue:
        def __init__(self) -> None:
            self.state = "leased"
            self.events: list[str] = []

        async def reap_stale_leases(self) -> int:
            self.events.append("reap")
            if self.state == "leased":
                self.state = "reconciling"
                return 1
            return 0

        async def claim(self, **_kwargs: Any) -> SettlementClaim | None:
            if self.state != "ready":
                self.events.append("claim:none")
                return None
            self.events.append("claim:leased")
            self.state = "leased"
            return SettlementClaim.from_row(_claim_row(state="leased", lease_token="lease-2"))

        async def mark_submitted(self, _claim: SettlementClaim, signature: str) -> None:
            self.events.append(f"submitted:{signature}")
            self.state = "submitted"

        async def mark_ambiguous(self, *_args: Any, **_kwargs: Any) -> None:
            raise AssertionError("submit should succeed")

        async def mark_blocked(self, *_args: Any, **_kwargs: Any) -> None:
            raise AssertionError("submit should succeed")

    class Reconciler:
        def __init__(self, queue: Queue) -> None:
            self.queue = queue

        async def run_pending(self, **_kwargs: Any) -> int:
            self.queue.events.append("reconcile")
            if self.queue.state == "reconciling":
                self.queue.state = "retry_wait"
                return 1
            if self.queue.state == "retry_wait":
                self.queue.state = "ready"
                return 1
            if self.queue.state == "submitted":
                self.queue.state = "confirmed"
                return 1
            return 0

    queue = Queue()
    sends: list[str] = []

    async def submit(_claim: SettlementClaim) -> str:
        sends.append("send")
        return "sig-1"

    worker = SettlementWorker(
        queue=queue,
        reconciler=Reconciler(queue),
        submitter=submit,
        worker_id="worker-2",
    )

    first = asyncio.run(worker.run_cycle(max_jobs=1))
    second = asyncio.run(worker.run_cycle(max_jobs=1))

    assert queue.state == "confirmed"
    assert sends == ["send"]
    assert first.reaped == 1
    assert first.submitted == 0
    assert second.submitted == 1
    submit_claim_index = queue.events.index("claim:leased")
    assert queue.events.index("reap") < submit_claim_index
    assert queue.events[:submit_claim_index].count("reconcile") >= 2


def test_ambiguous_submit_reconciles_before_any_resend() -> None:
    from app.services.settlement_queue import SettlementClaim
    from app.services.settlement_worker import SettlementWorker

    class Queue:
        def __init__(self) -> None:
            self.state = "ready"
            self.events: list[str] = []

        async def reap_stale_leases(self) -> int:
            return 0

        async def claim(self, **_kwargs: Any) -> SettlementClaim | None:
            self.events.append("claim")
            if self.state != "ready":
                return None
            self.state = "leased"
            return SettlementClaim.from_row(_claim_row(state="leased"))

        async def mark_submitted(self, *_args: Any, **_kwargs: Any) -> None:
            raise AssertionError("submit is intentionally ambiguous")

        async def mark_ambiguous(
            self,
            _claim: SettlementClaim,
            *,
            error: str,
            error_class: str,
        ) -> None:
            self.events.append(f"ambiguous:{error_class}:{error}")
            self.state = "reconciling"

        async def mark_blocked(self, *_args: Any, **_kwargs: Any) -> None:
            raise AssertionError("timeout must reconcile, not block")

    class Reconciler:
        def __init__(self, queue: Queue) -> None:
            self.queue = queue

        async def run_pending(self, **_kwargs: Any) -> int:
            self.queue.events.append("reconcile")
            if self.queue.state == "reconciling":
                self.queue.state = "confirmed"
                return 1
            return 0

    queue = Queue()
    sends = 0

    async def submit(_claim: SettlementClaim) -> str:
        nonlocal sends
        sends += 1
        raise TimeoutError("response lost after submit")

    worker = SettlementWorker(
        queue=queue,
        reconciler=Reconciler(queue),
        submitter=submit,
        worker_id="worker-1",
    )

    asyncio.run(worker.run_cycle(max_jobs=2))

    assert queue.state == "confirmed"
    assert sends == 1
    ambiguous_index = next(i for i, event in enumerate(queue.events) if event.startswith("ambiguous:"))
    assert ambiguous_index < len(queue.events) - 1
    assert queue.events[ambiguous_index + 1] == "reconcile"


def test_atomic_claim_contract_prevents_two_workers_receiving_same_fence() -> None:
    sql_path = Path(__file__).parents[2] / "sql" / "113_settlement_crank_state_machine.sql"
    sql = sql_path.read_text()

    claim_start = sql.index("CREATE OR REPLACE FUNCTION public.br_claim_settlement_job")
    claim_end = sql.index("CREATE OR REPLACE FUNCTION", claim_start + 1)
    claim_sql = sql[claim_start:claim_end]

    assert "FOR UPDATE SKIP LOCKED" in claim_sql
    assert "lease_token = pg_catalog.gen_random_uuid()" in claim_sql
    assert "WHERE j.state = 'ready'" in claim_sql
    assert "state IN ('submitted', 'reconciling', 'retry_wait')" in sql
    assert "lease_token = p_lease_token" in sql
    assert "settlement week % is not terminal" in sql
    assert "raw snapshot field % must be a decimal string" in sql
    assert "SET search_path = pg_catalog" in sql


def test_u64_max_raw_amount_round_trips_as_decimal_string() -> None:
    from app.services.settlement_queue import parse_u64, u64_string

    encoded = u64_string(U64_MAX, field_name="pending_rewards")

    assert encoded == "18446744073709551615"
    assert parse_u64(encoded, field_name="pending_rewards") == U64_MAX
    with pytest.raises(ValueError, match="u64"):
        u64_string(U64_MAX + 1, field_name="pending_rewards")

    from app.services.settlement_chain import build_materialization_job

    multi_bucket = build_materialization_job(
        _vault(0, current_dung=U64_MAX, current_cal=U64_MAX),
        settlement_week=10,
    )
    assert multi_bucket["current_week_value"] == str(U64_MAX * 2)
    assert all(
        isinstance(value, str)
        for key, value in multi_bucket["raw_snapshot"].items()
        if key not in {"signature_hex", "pda", "account_layout"}
    )


def test_legacy_row_is_not_completed_without_matching_chain_evidence() -> None:
    from app.services.settlement_queue import SettlementClaim
    from app.services.settlement_reconciler import (
        ReconciliationEvidence,
        decide_reconciliation,
    )

    claim = SettlementClaim.from_row(
        _claim_row(
            state="reconciling",
            tx_signature="legacy-sig",
            last_error_class=None,
            legacy_distribution_id="legacy-row-1",
        )
    )
    chain_advanced_only = ReconciliationEvidence(
        open_settlement_week=11,
        signature_state="absent",
        signature_error=None,
        indexed_tx_signature=None,
        indexed_distribution=None,
    )

    assert decide_reconciliation(claim, chain_advanced_only).action == "advanced_unproven"

    no_chain_effect = ReconciliationEvidence(
        open_settlement_week=10,
        signature_state="absent",
        signature_error=None,
        indexed_tx_signature=None,
        indexed_distribution=None,
    )
    assert decide_reconciliation(claim, no_chain_effect).action == "blocked"

    matching_index = ReconciliationEvidence(
        open_settlement_week=11,
        signature_state="finalized",
        signature_error=None,
        indexed_tx_signature="indexed-sig",
        indexed_signature_finalized=True,
        indexed_distribution={"vault_id": "0", "epoch": "10"},
    )
    assert decide_reconciliation(claim, matching_index).action == "confirmed"


def test_confirmed_fork_never_closes_but_finalized_evidence_does() -> None:
    from app.services.settlement_queue import SettlementClaim
    from app.services.settlement_reconciler import (
        ReconciliationEvidence,
        decide_reconciliation,
    )

    claim = SettlementClaim.from_row(
        _claim_row(state="reconciling", tx_signature="candidate-sig")
    )
    confirmed_fork = ReconciliationEvidence(
        open_settlement_week=11,
        signature_state="confirmed",
        signature_error=None,
        indexed_tx_signature="candidate-sig",
        indexed_distribution={"vault_id": "0", "epoch": "10"},
        chain_commitment="confirmed",
        indexed_signature_finalized=False,
    )
    finalized = ReconciliationEvidence(
        open_settlement_week=11,
        signature_state="finalized",
        signature_error=None,
        indexed_tx_signature="candidate-sig",
        indexed_distribution={"vault_id": "0", "epoch": "10"},
        chain_commitment="finalized",
        indexed_signature_finalized=True,
    )

    assert decide_reconciliation(claim, confirmed_fork).action == "reconciling"
    assert decide_reconciliation(claim, finalized).action == "confirmed"


def test_authoritative_and_reconciliation_reads_default_to_finalized() -> None:
    source = (
        Path(__file__).parents[2] / "app" / "services" / "settlement_chain.py"
    ).read_text()

    assert "from solana.rpc.commitment import Finalized" in source
    assert "commitment=Finalized" in source
    assert "get_vault_account" not in source
    assert 'return "finalized", None' in source


def test_local_legend_parser_carries_term_start_epoch_for_index_agreement() -> None:
    from solders.pubkey import Pubkey

    from app.solana_direct import parse_local_legend

    holder = Pubkey.new_unique()
    raw = (
        b"discrim0"
        + struct.pack("<Q", 7)
        + bytes(holder)
        + struct.pack("<Q", 3)
        + struct.pack("<Q", 10)
        + struct.pack("<Q", 18)
        + struct.pack("<I", 4)
        + bytes(Pubkey.default())
        + struct.pack("<I", 2)
        + struct.pack("<Q", 99)
        + b"\x01\x00"
    )

    parsed = parse_local_legend(raw)

    assert parsed is not None
    assert parsed.holder == holder
    assert parsed.term_start_epoch == 10
    assert parsed.term_end_epoch == 18


def test_retry_taxonomy_is_applied_only_after_no_evidence_is_observed() -> None:
    from app.services.settlement_queue import SettlementClaim
    from app.services.settlement_reconciler import (
        ReconciliationEvidence,
        decide_reconciliation,
    )

    no_evidence = ReconciliationEvidence(
        open_settlement_week=10,
        signature_state="absent",
        signature_error=None,
        indexed_tx_signature=None,
        indexed_distribution=None,
    )
    deterministic = SettlementClaim.from_row(
        _claim_row(
            state="reconciling",
            last_error_class="deterministic_submit",
        )
    )
    retryable = SettlementClaim.from_row(
        _claim_row(
            state="reconciling",
            last_error_class="retryable_submit",
        )
    )

    assert decide_reconciliation(deterministic, no_evidence).action == "blocked"
    assert decide_reconciliation(retryable, no_evidence).action == "retry_wait"

    freshly_rechecked = SettlementClaim.from_row(
        _claim_row(
            state="reconciling",
            last_error_class="retry_recheck_required",
        )
    )
    assert decide_reconciliation(freshly_rechecked, no_evidence).action == "ready"


def test_retry_wait_cannot_be_claimed_until_fresh_reconciliation() -> None:
    sql_path = Path(__file__).parents[2] / "sql" / "113_settlement_crank_state_machine.sql"
    sql = sql_path.read_text()

    submit_claim_start = sql.index(
        "CREATE OR REPLACE FUNCTION public.br_claim_settlement_job"
    )
    submit_claim_end = sql.index("CREATE OR REPLACE FUNCTION", submit_claim_start + 1)
    submit_claim_sql = sql[submit_claim_start:submit_claim_end]
    reconcile_claim_start = sql.index(
        "CREATE OR REPLACE FUNCTION public.br_claim_settlement_reconciliation"
    )
    reconcile_claim_end = sql.index(
        "CREATE OR REPLACE FUNCTION",
        reconcile_claim_start + 1,
    )
    reconcile_claim_sql = sql[reconcile_claim_start:reconcile_claim_end]

    assert "retry_wait" not in submit_claim_sql
    assert "'retry_wait'" in reconcile_claim_sql
    assert "retry_recheck_required" in sql


def test_bootstrap_and_sql_authority_contract_is_fail_closed() -> None:
    sql_path = Path(__file__).parents[2] / "sql" / "113_settlement_crank_state_machine.sql"
    sql = sql_path.read_text()

    assert "CREATE OR REPLACE FUNCTION public.br_bootstrap_settlement_planning" in sql
    assert "bootstrap_state TEXT NOT NULL DEFAULT 'uninitialized'" in sql
    assert "bootstrap_counter_count" in sql
    assert "bootstrap_source_slot" in sql
    assert "bootstrap_scope_hash" in sql
    assert "bootstrap_min_open_week" in sql
    assert "bootstrap_latest_finalizable_week" in sql
    assert "SELECT COALESCE(MAX(current_epoch), 0)::NUMERIC" not in sql
    assert "SET current_epoch = $1" not in sql
    assert "GRANT SELECT, INSERT, UPDATE, DELETE" not in sql
    assert (
        "GRANT SELECT ON TABLE public.settlement_planning_state, "
        "public.settlement_jobs TO service_role;"
    ) in sql

    security_definer_blocks = sql.split("SECURITY DEFINER")[1:]
    assert security_definer_blocks
    assert all("SET search_path = pg_catalog" in block.split("$$;", 1)[0] for block in security_definer_blocks)


def test_legacy_fractional_amount_is_preserved_as_non_executable_evidence() -> None:
    sql_path = Path(__file__).parents[2] / "sql" / "113_settlement_crank_state_machine.sql"
    sql = sql_path.read_text()

    assert "ALTER COLUMN cal_to_convert TYPE NUMERIC(39, 0) USING (" not in sql
    assert "'legacy_original_cal_to_convert'" in sql
    assert "'legacy_amount_valid'" in sql
    assert "legacy row crossed a non-integral protocol amount boundary" in sql
    assert "legacy_evidence_only" in sql


def test_canonical_sql_and_supabase_migration_are_identical() -> None:
    backend = Path(__file__).parents[2]
    canonical = backend / "sql" / "113_settlement_crank_state_machine.sql"
    migration = (
        backend
        / "supabase"
        / "migrations"
        / "20260713_120_settlement_crank_state_machine.sql"
    )

    assert canonical.read_bytes() == migration.read_bytes()


def test_settlement_compute_envelope_migration_is_mirrored_and_fenced() -> None:
    backend = Path(__file__).parents[2]
    canonical = backend / "sql" / "126_settlement_compute_envelope.sql"
    migration = (
        backend
        / "supabase"
        / "migrations"
        / "20260715_134_settlement_compute_envelope.sql"
    )

    assert canonical.read_bytes() == migration.read_bytes()
    sql = canonical.read_text()
    assert "ADD COLUMN IF NOT EXISTS compute_unit_limit INTEGER" in sql
    assert "compute_unit_limit IS NULL" in sql
    assert "compute_unit_limit BETWEEN 1 AND 1400000" in sql
    assert "p_compute_unit_limit INTEGER" in sql
    assert "p_compute_unit_limit IS NULL" in sql
    assert "compute_unit_limit = p_compute_unit_limit" in sql
    assert "settlement attempt fence was lost for prepared job" in sql
    assert "br_mark_settlement_prepared(UUID, UUID, TEXT, INTEGER)" in sql
    assert "DROP FUNCTION" not in sql


def test_settlement_v0_transport_migration_is_mirrored_and_fenced() -> None:
    backend = Path(__file__).parents[2]
    canonical = backend / "sql" / "137_settlement_v0_transport.sql"
    migration = (
        backend
        / "supabase"
        / "migrations"
        / "20260718_145_settlement_v0_transport.sql"
    )

    assert canonical.read_bytes() == migration.read_bytes()
    sql = canonical.read_text()
    assert "settlement_lookup_table_generations" in sql
    assert "WHERE status IN ('planned', 'active')" in sql
    assert "signed_transaction_bytes BETWEEN 1 AND 900" in sql
    assert "br_mark_settlement_prepared_v0" in sql
    assert "precondition_result->'transport'" in sql
    assert "br_return_settlement_to_preparation" in sql
    assert "prepared_tx_signature IS NULL AND tx_signature IS NULL" in sql
    assert "FROM PUBLIC, anon, authenticated, service_role" in sql


def test_worker_persists_production_compute_limit_with_prepared_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.solana_direct import SETTLEMENT_COMPUTE_UNIT_LIMIT
    from app.services import settlement_worker as settlement_worker_module
    from app.services.settlement_queue import SettlementClaim, SettlementQueue

    class RpcResult:
        data = True

        def execute(self) -> "RpcResult":
            return self

    class DB:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        def rpc(self, name: str, params: dict[str, Any]) -> RpcResult:
            self.calls.append((name, params))
            return RpcResult()

    sent_compute_unit_limits: list[int] = []

    async def submit(**kwargs: Any) -> str:
        sent_compute_unit_limits.append(kwargs["compute_unit_limit"])
        await kwargs["on_prepared"]("locally-signed-signature")
        return "locally-signed-signature"

    monkeypatch.setattr(
        settlement_worker_module,
        "send_distribute_epoch_rewards",
        submit,
    )
    db = DB()
    worker = settlement_worker_module.SettlementWorker(
        queue=SettlementQueue(db),
        reconciler=object(),
        worker_id="worker-1",
        config=object(),
    )
    claim = SettlementClaim.from_row(
        _claim_row(
            state="leased",
            precondition_result={
                "completed": True,
                "transport": _transport_plan(),
            },
        )
    )

    signature = asyncio.run(worker._submit_on_chain(claim))

    assert signature == "locally-signed-signature"
    assert worker.compute_unit_limit == SETTLEMENT_COMPUTE_UNIT_LIMIT
    assert sent_compute_unit_limits == [SETTLEMENT_COMPUTE_UNIT_LIMIT]
    assert db.calls == [
        (
            "br_mark_settlement_prepared_v0",
            {
                "p_job_id": claim.id,
                "p_lease_token": claim.lease_token,
                "p_tx_signature": "locally-signed-signature",
                "p_compute_unit_limit": SETTLEMENT_COMPUTE_UNIT_LIMIT,
                "p_lookup_table_address": "lookup-table-address",
                "p_lookup_table_generation": 1,
                "p_transport_manifest_sha256": "a" * 64,
                "p_lookup_table_last_extended_slot": "99",
                "p_signed_transaction_bytes": 815,
            },
        )
    ]


@pytest.mark.parametrize(
    "message",
    [
        "ComputationalBudgetExceeded",
        "computational budget exceeded",
        "compute units exceeded",
        "settlement supports at most 10 settlement-relevant VaultStake accounts",
    ],
)
def test_compute_envelope_failures_are_deterministic_submit(message: str) -> None:
    from app.services.settlement_worker import classify_submit_error

    assert classify_submit_error(ValueError(message)) == "deterministic_submit"


def test_repairable_preflight_enters_reconciliation_not_permanent_block() -> None:
    from app.services.settlement_queue import SettlementClaim
    from app.services.settlement_worker import SettlementWorker, classify_submit_error

    assert classify_submit_error(ValueError("ProgramConfig not found on-chain")) == (
        "repairable_preflight"
    )

    claim = SettlementClaim.from_row(_claim_row(state="leased"))

    class Queue:
        def __init__(self) -> None:
            self.claimed = False
            self.errors: list[tuple[str, str]] = []

        async def reap_stale_leases(self) -> int:
            return 0

        async def retry_repairable_blocks(self, **_kwargs: Any) -> int:
            return 0

        async def claim(self, **_kwargs: Any) -> SettlementClaim | None:
            if self.claimed:
                return None
            self.claimed = True
            return claim

        async def renew_lease(self, *_args: Any, **_kwargs: Any) -> None:
            return None

        async def mark_ambiguous(
            self,
            _claim: SettlementClaim,
            *,
            error: str,
            error_class: str,
        ) -> None:
            self.errors.append((error_class, error))

        async def mark_submitted(self, *_args: Any, **_kwargs: Any) -> None:
            raise AssertionError("submit must fail")

    class Reconciler:
        async def run_pending(self, **_kwargs: Any) -> int:
            return 0

    async def submit(_claim: SettlementClaim) -> str:
        raise ValueError("ProgramConfig not found on-chain")

    queue = Queue()
    worker = SettlementWorker(
        queue=queue,
        reconciler=Reconciler(),
        worker_id="worker-1",
        submitter=submit,
        heartbeat_interval_seconds=0.01,
    )

    result = asyncio.run(worker.run_cycle(max_jobs=1))

    assert result.blocked == 0
    assert queue.errors == [
        ("repairable_preflight", "ProgramConfig not found on-chain")
    ]


def test_planner_materializes_precondition_before_any_legend_side_effect() -> None:
    from app.services.settlement_chain import AuthoritativeVaultScope
    from app.services.settlement_queue import MaterializationResult
    from app.services.settlement_worker import SettlementPlanner

    scope = AuthoritativeVaultScope(
        counter_count=1,
        source_slot=100,
        vaults=(_vault(0, open_week=10, current_dung=5),),
    )

    class Chain:
        async def read_authoritative_scope(self) -> AuthoritativeVaultScope:
            return scope

    class Queue:
        def __init__(self) -> None:
            self.jobs: list[dict[str, Any]] = []

        async def materialize_week(self, **kwargs: Any) -> MaterializationResult:
            self.jobs = list(kwargs["jobs"])
            return MaterializationResult(
                run_id="run-1",
                settlement_week=10,
                state="materialized",
                job_count=1,
                ready_count=0,
                skipped_count=0,
            )

    prepared: list[str] = []

    async def prepare(_claim: Any) -> dict[str, Any]:
        prepared.append("side-effect")
        return {"completed": True}

    queue = Queue()
    planner = SettlementPlanner(queue=queue, chain=Chain(), prepare_vault=prepare)

    asyncio.run(planner.materialize_week(10))

    assert prepared == []
    assert queue.jobs[0]["state"] == "precondition_pending"


def test_status_and_catchup_include_precondition_reconciliation_and_review_states() -> None:
    from app.services.settlement_queue import SettlementQueue

    rows = [
        {
            "id": "prep",
            "state": "precondition_retry",
            "dung_to_mint": "5",
            "blocked_reason": None,
            "last_error": "indexed legend unavailable",
            "created_at": "2026-07-13T10:00:00+00:00",
            "settlement_week": 10,
        },
        {
            "id": "reconcile",
            "state": "reconciling",
            "dung_to_mint": "7",
            "blocked_reason": None,
            "last_error": "response lost",
            "created_at": "2026-07-13T10:01:00+00:00",
            "settlement_week": 10,
        },
        {
            "id": "review",
            "state": "advanced_unproven",
            "dung_to_mint": "0",
            "blocked_reason": None,
            "last_error": None,
            "created_at": "2026-07-13T10:02:00+00:00",
            "settlement_week": 9,
        },
    ]

    class Query:
        def __init__(self) -> None:
            self.week: int | None = None
            self.states: set[str] | None = None
            self.row_limit: int | None = None

        def select(self, *_args: Any) -> "Query":
            return self

        def eq(self, column: str, value: Any) -> "Query":
            if column == "settlement_week":
                self.week = int(value)
            return self

        def lte(self, column: str, value: Any) -> "Query":
            self.week = int(value)
            return self

        def in_(self, column: str, values: list[str]) -> "Query":
            assert column == "state"
            self.states = set(values)
            return self

        def limit(self, value: int) -> "Query":
            self.row_limit = value
            return self

        def execute(self) -> Any:
            selected = [
                row
                for row in rows
                if (self.week is None or row["settlement_week"] <= self.week)
                and (self.states is None or row["state"] in self.states)
            ]
            if self.row_limit is not None:
                selected = selected[: self.row_limit]
            return type("Response", (), {"data": selected})()

    class DB:
        def from_(self, table: str) -> Query:
            assert table == "settlement_jobs"
            return Query()

    queue = SettlementQueue(DB())
    status = asyncio.run(queue.status())

    assert status["pending"] == 2
    assert status["pending_dung"] == "12"
    assert status["preconditions_pending"] == 1
    assert status["reconciliation_pending"] == 1
    assert status["review_required"] == 1
    assert status["healthy"] is False
    assert asyncio.run(queue.has_unfinished_jobs(settlement_week=10)) is True


def test_lease_heartbeat_prevents_reap_after_rpc_acceptance() -> None:
    from app.services.settlement_queue import SettlementClaim
    from app.services.settlement_worker import SettlementWorker

    claim = SettlementClaim.from_row(_claim_row(state="leased"))

    class Queue:
        def __init__(self) -> None:
            self.claimed = False
            self.accepted = False
            self.renewed = 0
            self.reaped_after_acceptance = 0
            self.submitted: list[str] = []

        async def reap_stale_leases(self) -> int:
            if self.accepted and self.renewed == 0:
                self.reaped_after_acceptance += 1
                return 1
            return 0

        async def retry_repairable_blocks(self, **_kwargs: Any) -> int:
            return 0

        async def claim(self, **_kwargs: Any) -> SettlementClaim | None:
            if self.claimed:
                return None
            self.claimed = True
            return claim

        async def renew_lease(self, *_args: Any, **_kwargs: Any) -> None:
            self.renewed += 1

        async def mark_submitted(self, _claim: SettlementClaim, signature: str) -> None:
            self.submitted.append(signature)

        async def mark_ambiguous(self, *_args: Any, **_kwargs: Any) -> None:
            raise AssertionError("accepted transaction should persist its signature")

    class Reconciler:
        async def run_pending(self, **_kwargs: Any) -> int:
            return 0

    queue = Queue()
    sends = 0

    async def submit(_claim: SettlementClaim) -> str:
        nonlocal sends
        sends += 1
        queue.accepted = True
        await asyncio.sleep(0.04)
        await queue.reap_stale_leases()
        return "accepted-signature"

    worker = SettlementWorker(
        queue=queue,
        reconciler=Reconciler(),
        worker_id="worker-1",
        submitter=submit,
        lease_seconds=1,
        heartbeat_interval_seconds=0.01,
    )

    asyncio.run(worker.run_cycle(max_jobs=1))

    assert sends == 1
    assert queue.renewed > 0
    assert queue.reaped_after_acceptance == 0
    assert queue.submitted == ["accepted-signature"]


def test_selected_auto_roll_amount_survives_claim_and_outbox_boundary() -> None:
    from app.services.settlement_queue import SettlementClaim, SettlementNotificationEvent

    claim = SettlementClaim.from_row(
        _claim_row(
            state="leased",
            auto_roll_from_empty=True,
            dung_to_mint=str(U64_MAX),
            raw_snapshot={"pending_rewards": "0", "pending_rewards_next_week": str(U64_MAX)},
        )
    )
    event = SettlementNotificationEvent.from_row({
        "id": "event-1",
        "job_id": claim.id,
        "vault_id": str(claim.vault_id),
        "vault_signature": claim.vault_signature,
        "settlement_week": str(claim.settlement_week),
        "raw_pending_dung": str(claim.dung_to_mint),
        "total_distributed": None,
        "tx_signature": "sig-1",
        "lease_owner": "notify-1",
        "lease_token": "notify-token",
    })

    assert claim.dung_to_mint == U64_MAX
    assert event.raw_pending_dung == U64_MAX
    assert event.total_distributed is None
    assert event.as_notification_metadata()["raw_pending_dung"] == str(U64_MAX)
    assert "dung_to_mint" not in event.as_notification_metadata()
    assert "total_distributed" not in event.as_notification_metadata()


def test_notification_outbox_is_durable_across_crash_after_confirmation() -> None:
    from app.services.settlement_queue import SettlementNotificationEvent
    from app.services.settlement_reconciler import SettlementReconciler

    event = SettlementNotificationEvent.from_row({
        "id": "event-1",
        "job_id": "job-1",
        "vault_id": "7",
        "vault_signature": "vault-7",
        "settlement_week": "10",
        "raw_pending_dung": "99",
        "total_distributed": "77",
        "tx_signature": "sig-1",
        "lease_owner": "notify-worker",
        "lease_token": "notify-token",
    })

    class Queue:
        def __init__(self) -> None:
            self.delivered = False

        async def claim_reconciliation(self, **_kwargs: Any) -> None:
            return None

        async def claim_notification(self, **_kwargs: Any) -> SettlementNotificationEvent | None:
            if self.delivered:
                return None
            return event

        async def mark_notification_delivered(self, claimed: SettlementNotificationEvent) -> None:
            assert claimed == event
            self.delivered = True

        async def mark_notification_retry(
            self,
            *_args: Any,
            **_kwargs: Any,
        ) -> None:
            raise AssertionError("delivery succeeds after restart")

    delivered: list[str] = []

    async def notify(claimed: SettlementNotificationEvent) -> None:
        delivered.append(claimed.tx_signature)

    queue = Queue()
    restarted = SettlementReconciler(
        queue=queue,
        chain=object(),
        worker_id="worker-restarted",
        on_notification=notify,
    )

    assert asyncio.run(restarted.run_pending(limit=2)) == 0
    assert delivered == ["sig-1"]
    assert queue.delivered is True


def test_admin_settlement_money_and_block_health_are_json_exact(monkeypatch) -> None:
    monkeypatch.setenv("ACCESS_TOKEN_SECRET", "test-access-secret-with-32-bytes-minimum")
    monkeypatch.setenv("REFRESH_TOKEN_SECRET", "test-refresh-secret-with-32-bytes-minimum")
    from app.config import load_auth_settings

    load_auth_settings.cache_clear()
    from app.routes.admin import EpochStatusResponse
    from app.routes.admin_platform import VaultKPIs, _decimal_string

    response = EpochStatusResponse(
        current_epoch=12,
        stored_epoch=10,
        epoch_needs_transition=True,
        pending_distributions=1,
        pending_dung_total=str(U64_MAX),
        recently_completed=0,
        blocked_distributions=2,
        blocked_reasons=["missing ProgramConfig"],
        oldest_blocked_at="2026-07-13T12:00:00+00:00",
        settlement_healthy=False,
    )

    assert json.loads(response.model_dump_json())["pending_dung_total"] == str(U64_MAX)
    assert response.settlement_healthy is False
    vaults = VaultKPIs(total_staked_cal=_decimal_string(U64_MAX))
    assert vaults.model_dump()["total_staked_cal"] == str(U64_MAX)


def test_legacy_classification_imports_default_true_rows_instead_of_dropping_them() -> None:
    sql_path = Path(__file__).parents[2] / "sql" / "113_settlement_crank_state_machine.sql"
    sql = sql_path.read_text()

    assert "ALTER COLUMN is_points_period SET DEFAULT FALSE" in sql
    assert "WHERE NOT COALESCE(ed.is_points_period, FALSE)" not in sql
    assert "legacy_original_is_points_period" in sql
    assert "legacy points classification is ambiguous" in sql
    for status in ("pending", "processing", "failed", "completed"):
        assert f"'{status}'" in sql


def test_run_refresh_requires_complete_materialized_scope_and_preserves_review_state() -> None:
    sql_path = Path(__file__).parents[2] / "sql" / "113_settlement_crank_state_machine.sql"
    sql = sql_path.read_text()
    refresh_start = sql.index("CREATE OR REPLACE FUNCTION public.br_refresh_settlement_run")
    refresh_end = sql.index("CREATE OR REPLACE FUNCTION", refresh_start + 1)
    refresh_sql = sql[refresh_start:refresh_end]

    assert "materialized_job_count <> expected_job_count" in refresh_sql
    assert "review_required" in refresh_sql
    assert "advanced_unproven" in refresh_sql
    assert "legacy_evidence_only" in refresh_sql


def test_deployed_full_stack_smoke_uses_state_machine_and_chain_evidence() -> None:
    smoke = (Path(__file__).parents[2] / "scripts" / "smoke_full_stack.py").read_text()
    settlement_function = smoke[
        smoke.index("async def run_epoch_settlement_for_vault"):
        smoke.index("\ndef wait_for_ride_status", smoke.index("async def run_epoch_settlement_for_vault"))
    ]

    assert "process_settlement_cycle" in settlement_function
    assert "settlement_jobs" in settlement_function
    assert '.table("epoch_distributions")' not in settlement_function
    assert "read_reconciliation_evidence" in settlement_function
