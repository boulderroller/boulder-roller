"""Offline RPC fixtures against the real PostgreSQL settlement transitions."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import struct
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import psycopg2
import httpx
import pytest
from psycopg2 import sql
from psycopg2.extras import Json
from solders.pubkey import Pubkey

from app.services.settlement_chain import SettlementChain
from app.services.settlement_queue import SettlementQueue
from app.services.settlement_reconciler import SettlementReconciler
from app.services.settlement_worker import SettlementWorker
from app.solana_direct import _derive_vault_counter_pda, _derive_vault_pda
from test_settlement_postgres_runtime import _open_connection, postgres_dsn
from test_settlement_state_machine import _vault


MIGRATION = "167_settlement_reconciliation_failures.sql"


@pytest.fixture(scope="module")
def reconciliation_dsn(postgres_dsn):
    # The shared runtime fixture supplies a disposable server. Isolate these
    # tests from other suites' public-schema fixtures in a separate database.
    database = "settlement_failures_" + uuid.uuid4().hex
    with _open_connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    dsn = psycopg2.extensions.make_dsn(postgres_dsn, dbname=database)
    try:
        with _open_connection(dsn) as connection:
            with connection.cursor() as cursor:
                for role in ("anon", "authenticated", "service_role"):
                    cursor.execute(sql.SQL(
                        "DO $$ BEGIN CREATE ROLE {} NOLOGIN; "
                        "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
                    ).format(sql.Identifier(role)))
                backend = Path(__file__).parents[2]
                for name in (
                    "113_settlement_crank_state_machine.sql",
                    "126_settlement_compute_envelope.sql",
                    "137_settlement_v0_transport.sql",
                ):
                    cursor.execute((backend / "sql" / name).read_text())
                migration = backend / "sql" / MIGRATION
                if migration.exists():  # Also exercises the pre-fix red.
                    cursor.execute(migration.read_text())
        yield dsn
    finally:
        with _open_connection(postgres_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))


class RuntimeQueue(SettlementQueue):
    def __init__(self, dsn):
        self.dsn = dsn

    def execute(self, statement, params=()):
        with _open_connection(self.dsn, dict_rows=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(statement, params)
                return list(cursor.fetchall()) if cursor.description else []

    async def _rpc(self, name, params):
        arguments = sql.SQL(", ").join(
            sql.SQL("{} => %s").format(sql.Identifier(key)) for key in params
        )
        statement = sql.SQL("SELECT * FROM public.{}({})").format(
            sql.Identifier(name), arguments,
        )
        values = [Json(value) if isinstance(value, dict) else value for value in params.values()]
        rows = self.execute(statement, values)
        if name == "br_get_settlement_reconciliation_slot_floor":
            return SimpleNamespace(data=rows[0][name])
        return SimpleNamespace(data=rows)

    async def get_indexed_distribution(self, **kwargs):
        return None

    async def get_lifecycle_signature(self, claim):
        return None

    def seed(self, vault_id=2, *, error_class=None, source_slot_max=None, attempt_count=0):
        run = self.execute(
            "INSERT INTO public.settlement_week_runs "
            "(settlement_week, source_slot_max, vault_counter_count) VALUES (118, %s, 3) "
            "ON CONFLICT (settlement_week) DO UPDATE SET source_slot_max=EXCLUDED.source_slot_max RETURNING id",
            (source_slot_max,),
        )[0]["id"]
        return str(self.execute(
            "INSERT INTO public.settlement_jobs "
            "(run_id, settlement_week, vault_id, vault_signature, state, "
            "expected_pre_open_week, raw_snapshot, last_error_class, tx_signature, attempt_count) "
            "VALUES (%s, 118, %s, %s, 'reconciling', 118, '{}', %s, 'old-signature', %s) RETURNING id",
            (run, vault_id, f"vault-{vault_id}", error_class, attempt_count),
        )[0]["id"])

    def job(self, job_id):
        return self.execute("SELECT * FROM public.settlement_jobs WHERE id=%s", (job_id,))[0]

    def make_due(self, job_id):
        self.execute(
            "UPDATE public.settlement_jobs SET next_reconcile_at=now() WHERE id=%s",
            (job_id,),
        )


@pytest.fixture
def queue(reconciliation_dsn):
    queue = RuntimeQueue(reconciliation_dsn)
    queue.execute("TRUNCATE public.settlement_week_runs CASCADE")
    return queue


def absent_chain(monkeypatch, *, count=1, slot=9001, malformed=None):
    program_id = Pubkey.new_unique()
    counter_pda, bump = _derive_vault_counter_pda(program_id)
    counter = SimpleNamespace(
        owner=program_id,
        data=hashlib.sha256(b"account:VaultCounter").digest()[:8] + struct.pack("<QB", count, bump),
    )
    if malformed == "owner":
        counter.owner = Pubkey.new_unique()
    elif malformed == "discriminator":
        counter.data = b"invalid!" + counter.data[8:]
    elif malformed == "bump":
        counter.data = counter.data[:-1] + bytes([(bump + 1) % 256])
    elif malformed == "layout":
        counter.data = counter.data[:8]
    calls = []

    class RPC:
        def __init__(self, url, *, commitment):
            assert commitment == "finalized"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get_account_info(self, pda, *, commitment):
            # Pre-fix production path: successful finalized null.
            assert commitment == "finalized"
            return SimpleNamespace(value=None, context=SimpleNamespace(slot=slot))

        async def get_multiple_accounts(self, pdas, *, commitment):
            assert commitment == "finalized"
            assert pdas[0] == counter_pda
            calls.append(pdas)
            accounts = [counter, None]
            if malformed == "incomplete":
                accounts = [counter]
            elif malformed == "missing_counter":
                accounts = [None, None]
            elif malformed == "rpc":
                raise RuntimeError("429 Too Many Requests")
            return SimpleNamespace(value=accounts, context=SimpleNamespace(slot=slot))

    monkeypatch.setattr("app.services.settlement_chain.AsyncClient", RPC)
    signatures = AsyncMock(return_value=("unknown", "signature RPC failed"))
    chain = SettlementChain(SimpleNamespace(program_id=program_id, rpc_url="offline"), signature_reader=signatures)
    return chain, calls, signatures


def test_finalized_absent_vault_blocks_without_notification(queue, monkeypatch):
    job_id = queue.seed(error_class="repairable_preflight")
    chain, calls, signatures = absent_chain(monkeypatch)
    notifications = AsyncMock()
    reconciler = SettlementReconciler(queue=queue, chain=chain, worker_id="reader", on_notification=notifications)
    assert asyncio.run(reconciler.run_pending()) == 1
    job = queue.job(job_id)
    assert job["state"] == "blocked"
    assert "absent at finalized" in job["blocked_reason"]
    assert "counter" in job["blocked_reason"]
    assert job["last_error_class"] == "vault_absent_finalized"
    assert job["next_reconcile_at"] is None
    assert len(calls) == 1
    signatures.assert_not_awaited()
    assert calls[0][1] == _derive_vault_pda(2, chain.config.program_id)[0]
    assert asyncio.run(queue.retry_repairable_blocks()) == 0
    assert asyncio.run(reconciler.run_pending()) == 0
    notifications.assert_not_awaited()
    assert queue.execute("SELECT * FROM public.settlement_notification_outbox") == []


@pytest.mark.parametrize("failure", ["rpc", "timeout", "signature", "nonfinalized"])
def test_transient_failure_backoff_and_fresh_claim(queue, failure):
    job_id = queue.seed()
    vault = _vault(2, open_week=118)
    vault["_commitment"] = "confirmed" if failure == "nonfinalized" else "finalized"
    vault_reader = AsyncMock(return_value=vault)
    if failure == "rpc":
        vault_reader.side_effect = RuntimeError("429 Too Many Requests")
    elif failure == "timeout":
        vault_reader.side_effect = TimeoutError("RPC timed out")
    chain = SettlementChain(
        object(), vault_reader=vault_reader,
        signature_reader=AsyncMock(return_value=(
            ("unknown", "signature RPC error") if failure == "signature" else ("pending", None)
        )),
    )
    for delay in (60, 120, 240, 480, 960, 1920, 3600, 3600):
        # A new worker each time proves this is durable across restarts.
        reconciler = SettlementReconciler(queue=queue, chain=chain, worker_id="reader")
        claim = asyncio.run(queue.claim_reconciliation(worker_id="reader"))
        assert claim is not None  # Includes the fresh job's immediate first claim.
        assert asyncio.run(reconciler.reconcile_claim(claim)).action == "reconciling"
        job = queue.job(job_id)
        assert (job["next_reconcile_at"] - job["updated_at"]).total_seconds() == delay
        assert job["attempt_count"] == 0
        assert asyncio.run(queue.claim_reconciliation(worker_id="other-reader")) is None
        queue.make_due(job_id)  # Advance eligibility offline; never sleep through backoff.


def test_successful_read_resets_transient_backoff(queue):
    job_id = queue.seed()
    vault_reader = AsyncMock(side_effect=RuntimeError("429 Too Many Requests"))
    chain = SettlementChain(
        object(), vault_reader=vault_reader,
        signature_reader=AsyncMock(return_value=("pending", None)),
    )
    reconciler = SettlementReconciler(queue=queue, chain=chain, worker_id="reader")
    for iteration, (failing, delay) in enumerate(((True, 60), (True, 120), (False, 60), (True, 60))):
        vault_reader.side_effect = RuntimeError("RPC unavailable") if failing else None
        vault_reader.return_value = _vault(2, open_week=118)
        claim = asyncio.run(queue.claim_reconciliation(worker_id="reader"))
        asyncio.run(reconciler.reconcile_claim(claim))
        job = queue.job(job_id)
        assert (job["next_reconcile_at"] - job["updated_at"]).total_seconds() == delay
        if failing:
            fresh_id = queue.seed(100 + iteration)
            fresh = asyncio.run(queue.claim_reconciliation(worker_id="fresh-reader"))
            assert fresh.id == fresh_id  # A backed-off job does not delay new work.
        queue.make_due(job_id)


@pytest.mark.parametrize("slot", [None, 0])
def test_absence_without_a_positive_response_slot_retries(queue, monkeypatch, slot):
    job_id = queue.seed()
    chain, _, _ = absent_chain(monkeypatch, slot=slot)
    asyncio.run(SettlementReconciler(queue=queue, chain=chain, worker_id="reader").run_pending())
    assert queue.job(job_id)["state"] == "reconciling"


@pytest.mark.parametrize("kind", ["bare_null", "nonfinalized", "missing_slot", "in_scope"])
def test_unproven_absence_does_not_block(queue, kind):
    from app.services.settlement_chain import VaultAbsenceEvidence

    job_id = queue.seed()
    vault = {
        "bare_null": None,
        "nonfinalized": VaultAbsenceEvidence(1, 9001, "confirmed"),
        "missing_slot": VaultAbsenceEvidence(1, 0),
        "in_scope": VaultAbsenceEvidence(3, 9001),
    }[kind]
    chain = SettlementChain(object(), vault_reader=AsyncMock(return_value=vault))
    for delay in (60, 120):
        asyncio.run(SettlementReconciler(queue=queue, chain=chain, worker_id="reader").run_pending())
        job = queue.job(job_id)
        assert job["state"] == "reconciling"
        assert job["blocked_reason"] is None
        assert (job["next_reconcile_at"] - job["updated_at"]).total_seconds() == delay
        queue.make_due(job_id)


def test_reconciliation_migration_has_identical_supabase_mirror():
    backend = Path(__file__).parents[2]
    assert (backend / "sql" / MIGRATION).read_bytes() == (
        backend / "supabase/migrations/20261013150000_settlement_reconciliation_failures.sql"
    ).read_bytes()


@pytest.mark.parametrize("malformed", [None, "owner", "discriminator", "bump", "layout", "incomplete", "missing_counter", "rpc"])
def test_in_scope_or_invalid_absence_stays_reconciling(queue, monkeypatch, malformed):
    job_id = queue.seed()
    chain, _, _ = absent_chain(monkeypatch, count=3 if malformed is None else 1, malformed=malformed)
    reconciler = SettlementReconciler(queue=queue, chain=chain, worker_id="reader")
    asyncio.run(reconciler.run_pending())
    assert queue.job(job_id)["state"] == "reconciling"


def test_fourteen_absent_jobs_drain_in_one_cycle(queue, monkeypatch):
    for vault_id in range(2, 16):
        queue.seed(vault_id, error_class="preflight_blocked")
    chain, calls, signatures = absent_chain(monkeypatch)
    reconciler = SettlementReconciler(queue=queue, chain=chain, worker_id="reader", on_notification=AsyncMock())
    worker = SettlementWorker(queue=queue, reconciler=reconciler, worker_id="reader", submitter=AsyncMock())
    assert asyncio.run(worker.run_cycle(max_jobs=10)).reconciled == 14
    assert {row["state"] for row in queue.execute("SELECT state FROM public.settlement_jobs")} == {"blocked"}
    assert len(calls) == 14
    assert asyncio.run(worker.run_cycle(max_jobs=10)).reconciled == 0
    assert len(calls) == 14
    signatures.assert_not_awaited()
    worker.submitter.assert_not_awaited()
    reconciler.on_notification.assert_not_awaited()


@pytest.mark.parametrize("slot", [9000, 10000, 10001])
def test_absence_must_be_newer_than_materialized_run(queue, monkeypatch, slot):
    job_id = queue.seed(source_slot_max=10000)
    chain, _, _ = absent_chain(monkeypatch, count=2, slot=slot)
    reconciler = SettlementReconciler(queue=queue, chain=chain, worker_id="reader")
    for delay in (60, 120):
        asyncio.run(reconciler.run_pending())
        job = queue.job(job_id)
        if slot > 10000:
            assert job["state"] == "blocked"
            break
        assert job["state"] == "reconciling"
        assert (job["next_reconcile_at"] - job["updated_at"]).total_seconds() == delay
        queue.make_due(job_id)


def finish_absence(queue, claim, *, slot, commitment="finalized"):
    return asyncio.run(queue.finish_reconciliation(
        claim, decision="blocked",
        evidence={"absent_vault_counter_count": "2", "source_slot": str(slot),
                  "absence_slot_floor": "0", "read_error": None},
        signature_state="unknown", chain_commitment=commitment,
        observed_open_week=None, indexed_tx_signature=None,
        indexed_signature_finalized=False, recovered_tx_signature=None,
        error="vault absent at finalized; operator review required", retry_seconds=60,
    ))


@pytest.mark.parametrize("slot", [9000, 10000])
def test_sql_guard_rejects_absence_at_or_below_run_floor(queue, slot):
    job_id = queue.seed(source_slot_max=10000)
    claim = asyncio.run(queue.claim_reconciliation(worker_id="reader"))
    with pytest.raises(psycopg2.Error, match="absent vault decision lacks"):
        finish_absence(queue, claim, slot=slot)
    job = queue.job(job_id)
    assert job["state"] == "reconciling"
    assert str(job["lease_token"]) == claim.lease_token
    assert queue.execute("SELECT * FROM public.settlement_reconciliations") == []
    assert queue.execute("SELECT * FROM public.settlement_notification_outbox") == []


def test_sql_guard_rejects_nonfinalized_absence(queue):
    queue.seed(source_slot_max=10000)
    claim = asyncio.run(queue.claim_reconciliation(worker_id="reader"))
    with pytest.raises(psycopg2.Error, match="absent vault decision lacks"):
        finish_absence(queue, claim, slot=10001, commitment="confirmed")


def test_transient_backoff_preserves_high_submission_cadence(queue):
    job_id = queue.seed(attempt_count=6)
    chain = SettlementChain(object(), vault_reader=AsyncMock(side_effect=RuntimeError("429")))
    reconciler = SettlementReconciler(queue=queue, chain=chain, worker_id="reader")
    for _ in range(2):
        asyncio.run(reconciler.run_pending())
        job = queue.job(job_id)
        assert job["state"] == "reconciling"
        assert (job["next_reconcile_at"] - job["updated_at"]).total_seconds() == 3600
        assert job["attempt_count"] == 6
        queue.make_due(job_id)


def test_real_reader_never_uses_nonfinalized_absence(queue, monkeypatch):
    # Real Solana client serialization/decoding, with a local HTTP transport.
    # The server can supply confirmed-only absence but has no finalized bank.
    job_id = queue.seed(source_slot_max=10000)
    program_id = Pubkey.new_unique()
    _, bump = _derive_vault_counter_pda(program_id)
    counter = hashlib.sha256(b"account:VaultCounter").digest()[:8] + struct.pack("<QB", 2, bump)
    requests = []

    def rpc(request):
        body = json.loads(request.content)
        assert body["method"] == "getMultipleAccounts"
        commitment = body["params"][1]["commitment"]
        requests.append(commitment)
        if commitment == "finalized":
            return httpx.Response(200, json={
                "jsonrpc": "2.0", "id": body["id"],
                "error": {"code": -32004, "message": "finalized bank unavailable"},
            })
        return httpx.Response(200, json={
            "jsonrpc": "2.0", "id": body["id"],
            "result": {"context": {"slot": 10001}, "value": [{
                "data": [base64.b64encode(counter).decode(), "base64"],
                "owner": str(program_id), "lamports": 1,
                "executable": False, "rentEpoch": 0,
            }, None]},
        })

    http_client = httpx.AsyncClient
    monkeypatch.setattr("solana.rpc.providers.async_http.httpx.AsyncClient",
                        lambda **kwargs: http_client(transport=httpx.MockTransport(rpc), **kwargs))
    chain = SettlementChain(SimpleNamespace(program_id=program_id, rpc_url="http://offline.invalid"))
    reconciler = SettlementReconciler(queue=queue, chain=chain, worker_id="reader")
    for delay in (60, 120):
        asyncio.run(reconciler.run_pending())
        job = queue.job(job_id)
        assert job["state"] == "reconciling"
        assert (job["next_reconcile_at"] - job["updated_at"]).total_seconds() == delay
        queue.make_due(job_id)
    assert requests == ["finalized", "finalized"]


@pytest.mark.parametrize("state", ["confirmed", "advanced_unproven"])
def test_smoke_reports_absent_settlement_vault_without_typeerror(monkeypatch, state):
    from scripts import smoke_full_stack as smoke
    from app.services.settlement_chain import ChainReconciliationEvidence

    class Query:
        def __init__(self, table):
            self.table = table

        def select(self, *args, **kwargs): return self
        def eq(self, *args, **kwargs): return self
        def order(self, *args, **kwargs): return self
        def limit(self, *args, **kwargs): return self
        def execute(self):
            return SimpleNamespace(data=[{"state": state, "tx_signature": "signature"}])

    chain = SimpleNamespace(read_reconciliation_evidence=AsyncMock(return_value=
        ChainReconciliationEvidence(None, "unknown", None, source_slot=10001, absent_vault_counter_count=2)))
    processor = SimpleNamespace(_settlement_chain=chain, process_settlement_cycle=AsyncMock())
    monkeypatch.setattr(smoke, "get_supabase_client", lambda: SimpleNamespace(table=Query))
    monkeypatch.setattr(smoke, "get_epoch_processor", lambda db: processor)
    monkeypatch.setattr(smoke, "get_vault_signature_cache", lambda: SimpleNamespace(load=AsyncMock()))
    with pytest.raises(RuntimeError, match="no open settlement week"):
        asyncio.run(smoke.run_epoch_settlement_for_vault(2, 118))
