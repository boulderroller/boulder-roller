"""Owner-only Stage 1 signing boundary; no RPC in dark-mode checks."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.dependencies import AuthenticatedUser, get_current_user, get_repository, get_user_repository
from app.routes import stage1
from app.routes import stage1_actions


ACTIONS = ("cancel-pledge", "registration", "self-claim", "claim-transport", "pledge", "withdrawal-notice",
           "cancel-notice", "begin-withdrawal", "complete-withdrawal", "convert-pledge")


@pytest.fixture
def api(monkeypatch):
    monkeypatch.delenv("STAGE1_ACTIONS_ENABLED", raising=False)
    app = FastAPI()
    app.include_router(stage1.router, prefix="/stage1")
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        wallet="8qbHbw2BbbTHBW1sbeqakYXVKRQM8Ne7pLK7m6CVfeR", user_id="owner", device_id="test")
    app.dependency_overrides[get_repository] = lambda: None
    app.dependency_overrides[get_user_repository] = lambda: None
    return TestClient(app), app


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("suffix", ("", "/prepare"))
def test_all_actions_are_dark_by_default(api, action, suffix):
    client, _ = api
    response = client.post(f"/stage1/me/{action}{suffix}", json={})
    assert response.status_code == 503, response.text


@pytest.mark.parametrize("action", ACTIONS)
def test_all_actions_require_authentication(api, action):
    client, app = api
    del app.dependency_overrides[get_current_user]
    assert client.post(f"/stage1/me/{action}/prepare", json={}).status_code in (401, 403)


@pytest.mark.parametrize("flag", ("0", "false", "yes", "garbage"))
def test_only_explicit_flag_admits_actions(api, monkeypatch, flag):
    monkeypatch.setenv("STAGE1_ACTIONS_ENABLED", flag)
    assert api[0].post("/stage1/me/registration/prepare", json={}).status_code == 503


def test_flag_does_not_bypass_chain_version(api, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    monkeypatch.setenv("STAGE1_ACTIONS_ENABLED", "true")
    builder = SimpleNamespace(require_enabled_chain=AsyncMock(side_effect=RuntimeError("0x4C")))
    monkeypatch.setattr(stage1_actions, "get_stage1_tx_builder", lambda: builder)
    for action in ACTIONS:
        assert api[0].post(f"/stage1/me/{action}/prepare", json={}).status_code == 503
    assert builder.require_enabled_chain.await_count == len(ACTIONS)


@pytest.mark.parametrize("field", ("wallet", "recipient", "payer", "program", "instructions"))
def test_no_caller_wallet_recipient_or_signing_policy(api, field):
    api[1].dependency_overrides[stage1_actions.action_builder] = lambda: object()
    assert api[0].post("/stage1/me/registration/prepare", json={field: "untrusted"}).status_code == 422


@pytest.mark.parametrize("field,value", (
    ("amount_base_units", "0"), ("amount_base_units", "18446744073709551616"),
    ("amount_base_units", "01"), ("amount_base_units", "1.5"), ("amount_base_units", 1),
    ("deposit_id", True), ("lock_weeks", 1), ("lock_weeks", True), ("lock_weeks", "13"), ("mint", "bad"),
))
def test_pledge_exact_units_keys_and_ratified_locks(api, field, value):
    api[1].dependency_overrides[stage1_actions.action_builder] = lambda: object()
    payload = dict(hill="11111111111111111111111111111111", mint="11111111111111111111111111111111",
                   deposit_id="1", amount_base_units="1", lock_weeks=0)
    payload[field] = value
    assert api[0].post("/stage1/me/pledge/prepare", json=payload).status_code == 422


def test_registration_prepare_sign_submit_records_existing_balance_operation(api, monkeypatch):
    import base64
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from solders.hash import Hash
    from solders.keypair import Keypair
    from solders.transaction import Transaction
    from app.services.balance_transaction_coordinator import BalanceTransactionCoordinator, InMemoryBalanceOperationLog
    from scripts.generate_stage1_transaction_fixtures import fixture_builder, WALLET
    builder, *_ = fixture_builder()
    builder.fee_payer = Keypair.from_seed(bytes([2] * 32))
    builder._get_recent_blockhash = AsyncMock(return_value=(Hash.default(), 123456))
    builder.submit_signed_transaction = AsyncMock(side_effect=lambda tx, **kw: str(Transaction.from_bytes(base64.b64decode(tx)).signatures[0]))
    log = InMemoryBalanceOperationLog()
    monkeypatch.setattr(stage1_actions, "load_record", lambda c, id, owner: log.get(id))
    monkeypatch.setattr(stage1_actions, "_balance_coordinator", lambda _: BalanceTransactionCoordinator(sink=log))
    client, app = api
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(wallet=str(WALLET), user_id="owner", device_id="test")
    app.dependency_overrides[get_repository] = lambda: SimpleNamespace(client=object())
    app.dependency_overrides[stage1_actions.action_builder] = lambda: builder
    prepared = client.post("/stage1/me/registration/prepare", json={})
    assert prepared.status_code == 200, prepared.text
    assert prepared.headers["cache-control"] == "private, no-store"
    body = prepared.json()
    assert body["contractVersion"] == "portfolio_balance_action.v2"
    assert body["rider_label"].startswith("TIM:") and body["rider_detail"].startswith("TIM:")
    tx = Transaction.from_bytes(base64.b64decode(body["prepared_transaction"]["transaction"]))
    # Registration needs only the rider and sponsor; no rider SOL balance read.
    assert tx.message.header.num_required_signatures == 2
    tx.partial_sign([Keypair.from_seed(bytes([7] * 32))], tx.message.recent_blockhash)
    signed = dict(signed_transaction=base64.b64encode(bytes(tx)).decode(), last_valid_block_height=123456, client_request_id="local-test")
    response = client.post("/stage1/me/registration", json=signed)
    assert response.status_code == 200, response.text
    operation = response.json()["operation"]
    assert operation["action_type"] == "stage1_registration"
    assert operation["protocol_wallet"] == str(WALLET) and operation["rider_account_id"] == "owner"
    assert operation["confirmation_status"] == "confirmed"
    assert operation["projection_status"] == "recorded"
    assert operation["metadata"]["rent_payer"] == str(builder.fee_payer.pubkey())
    assert operation["operation_id"] in log.records
    assert builder.submit_signed_transaction.await_count == 1
    # A second on-chain registration is refused before any transaction build.
    builder.raw_account.return_value = object()
    retry = client.post("/stage1/me/registration", json=signed)
    assert retry.status_code == 200 and retry.json()["operation"]["operation_id"] == operation["operation_id"]
    assert builder.submit_signed_transaction.await_count == 1
    assert client.post("/stage1/me/registration/prepare", json={}).status_code == 409


@pytest.mark.parametrize("mutation", ("recipient", "fee", "program", "extra", "unsigned"))
def test_submit_rebuilds_and_refuses_changed_or_unsigned_message(api, mutation, monkeypatch):
    monkeypatch.setattr(stage1_actions, "load_record", lambda *args: None)
    import base64
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from solders.hash import Hash
    from solders.keypair import Keypair
    from solders.instruction import Instruction
    from solders.message import Message
    from solders.transaction import Transaction
    from scripts.generate_stage1_transaction_fixtures import fixture_builder, WALLET
    builder, *_ = fixture_builder()
    owner, fee, other = [Keypair.from_seed(bytes([i] * 32)) for i in (7, 2, 9)]
    builder.fee_payer = fee
    builder._get_recent_blockhash = AsyncMock(return_value=(Hash.default(), 123456))
    builder.submit_signed_transaction = AsyncMock(side_effect=AssertionError("must not submit"))
    client, app = api
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(wallet=str(WALLET), user_id="owner", device_id="test")
    app.dependency_overrides[get_repository] = lambda: SimpleNamespace(client=object())
    app.dependency_overrides[stage1_actions.action_builder] = lambda: builder
    keys = dict(registration=builder.pda("s1v1_recipient", bytes(WALLET)), person=WALLET, payer=fee.pubkey(), system_program=__import__('solders.pubkey', fromlist=['Pubkey']).Pubkey.default())
    ix = builder.ix("register_stage1_recipient", {"recipient": other.pubkey() if mutation == "recipient" else WALLET}, keys)
    if mutation == "program": ix = Instruction(other.pubkey(), ix.data, ix.accounts)
    ixs = [ix, ix] if mutation == "extra" else [ix]
    tx = Transaction.new_unsigned(Message.new_with_blockhash(ixs, other.pubkey() if mutation == "fee" else fee.pubkey(), Hash.default()))
    if mutation != "unsigned": tx.sign([owner, fee, *([other] if mutation == "fee" else [])], Hash.default())
    response = client.post("/stage1/me/registration", json={"signed_transaction": base64.b64encode(bytes(tx)).decode(), "last_valid_block_height": 123456, "client_request_id": "mutated"})
    assert response.status_code in (400, 409), response.text
    builder.submit_signed_transaction.assert_not_awaited()


def test_claim_discovery_is_owner_only_and_dark(api):
    client, app = api
    assert client.get("/stage1/me/claims").status_code == 503
    del app.dependency_overrides[get_current_user]
    assert client.get("/stage1/me/claims").status_code in (401,403)


@pytest.mark.parametrize('refresh_succeeds', [True, False])
def test_provider_eligibility_simulates_refresh_then_stale_exit_without_submitting(api, refresh_succeeds):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    wallet = '8qbHbw2BbbTHBW1sbeqakYXVKRQM8Ne7pLK7m6CVfeR'
    async def simulate(plan):
        return plan.refresh_rate is refresh_succeeds
    builder = SimpleNamespace(program_id=wallet, pda=lambda *args: wallet, clock=AsyncMock(return_value=604801), account=AsyncMock(return_value={'owner':wallet,'pending_request':wallet,'season_anchor':0}),
        plan=AsyncMock(side_effect=lambda action,payload,owner,**kwargs: payload), simulate=AsyncMock(side_effect=simulate))
    stage1_actions.eligibility_cache.clear()
    from app.middleware.rate_limiter import rate_limiter
    rate_limiter.reset_fallback()
    api[1].dependency_overrides[stage1_actions.action_read_builder] = lambda: builder
    response = api[0].post('/stage1/me/eligibility', json={'lot':wallet})
    assert response.status_code == 200
    assert response.json()['actions']['begin-withdrawal']['refresh_rate'] is refresh_succeeds
    assert response.json()['actions']['convert-pledge']['refresh_rate'] is refresh_succeeds
    assert builder.simulate.await_count >= 1
    stage1_actions.eligibility_cache.clear()
    builder.account.return_value['owner'] = 'someone-else'
    assert api[0].post('/stage1/me/eligibility', json={'lot':wallet}).status_code == 409


def test_eligibility_is_dark_by_default(api):
    assert api[0].post('/stage1/me/eligibility', json={'lot':'11111111111111111111111111111111'}).status_code == 503
@pytest.mark.parametrize("path,method", [(f"/stage1/me/{a}{s}", "post") for a in ACTIONS for s in ("", "/prepare")] + [("/stage1/me/claims", "get")])
def test_rate_limit_refuses_every_action_before_any_rpc(api, monkeypatch, path, method):
    from unittest.mock import AsyncMock, Mock
    from app.middleware.rate_limiter import rate_limiter
    monkeypatch.setenv("STAGE1_ACTIONS_ENABLED", "true")
    deny = AsyncMock(return_value=False)
    monkeypatch.setattr(rate_limiter, "check_burst", deny)
    builder = Mock(side_effect=AssertionError("rate denial must precede RPC builder"))
    monkeypatch.setattr(stage1_actions, "get_stage1_tx_builder", builder)
    response = getattr(api[0], method)(path, **({"json": {}} if method == "post" else {}))
    assert response.status_code == 429, response.text
    assert response.headers["Retry-After"] == "1"
    builder.assert_not_called()
    assert "user:owner" in deny.call_args.args[0]


def test_claim_discovery_is_cached_by_owner_and_proof_week_and_bounded(api, monkeypatch):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    row = {"job_id": "job", "role": -1, "leaf_index": 0, "week": 1}
    connection = SimpleNamespace(fetch=AsyncMock(side_effect=lambda *args: [dict(row)]), fetchval=AsyncMock(return_value="network"))
    @asynccontextmanager
    async def proof_connection(_):
        yield connection
    monkeypatch.setattr(stage1_actions, "proof_connection", proof_connection)
    builder = SimpleNamespace(program_id="program", rpc_url="local", observed_genesis="network", plan=AsyncMock(return_value=SimpleNamespace(intent={"kind": "stage1_self_claim"})),
                              requires_lookup=lambda _: False)
    builder.discovery_reader = lambda: builder
    api[1].dependency_overrides[stage1_actions.action_builder] = lambda: builder
    if hasattr(stage1_actions, "claim_cache"): stage1_actions.claim_cache.clear()
    client = api[0]
    assert client.get("/stage1/me/claims?limit=11").status_code == 422
    first = client.get("/stage1/me/claims")
    second = client.get("/stage1/me/claims")
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() and first.headers["cache-control"] == "private, no-store"
    assert builder.plan.await_count == 1
    row["week"] = 2
    assert client.get("/stage1/me/claims").status_code == 200
    assert builder.plan.await_count == 2
    api[1].dependency_overrides[get_current_user] = lambda: AuthenticatedUser(wallet="another-owner", user_id="another-user", device_id="test")
    assert client.get("/stage1/me/claims").status_code == 200
    assert builder.plan.await_count == 3
    builder.observed_genesis = "different-live-network"
    assert client.get("/stage1/me/claims").status_code == 503
    builder.observed_genesis = "network"
    # Every request still queries eligibility; paid/suspended/deleted proofs
    # cannot be resurrected from a cached page.
    connection.fetch.side_effect = lambda *args: []
    assert client.get("/stage1/me/claims").json()["claims"] == []
