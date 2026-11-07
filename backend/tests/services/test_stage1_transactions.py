"""Instruction/owner contract checks independent of the signing clients."""
import json
from pathlib import Path

import pytest
from app.services.stage1_transactions import require_pinned_abi, IDL
from app.routes.stage1_actions import ConvertRequest, NoticeRequest, WithdrawalRequest
from scripts.generate_stage1_transaction_fixtures import build_records, fixture_builder, WALLET


@pytest.mark.asyncio
async def test_shared_client_fixtures_are_current_backend_plans():
    path = Path(__file__).resolve().parents[3] / "web/portal/scripts/fixtures/prepared-stage1-transactions.json"
    assert json.loads(path.read_text()) == await build_records()


def test_transaction_abi_is_exactly_pinned():
    idl = json.loads(IDL.read_text())
    require_pinned_abi(idl)
    next(i for i in idl["instructions"] if i["name"] == "registerStage1Recipient")["accounts"][0]["isMut"] = False
    with pytest.raises(ValueError, match="ABI changed"):
        require_pinned_abi(idl)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ("withdrawal-notice", "cancel-notice", "begin-withdrawal", "complete-withdrawal", "convert-pledge"))
async def test_every_lot_action_refuses_another_owner(action):
    b, rows, hill, climb, lot, request, exit_lot = fixture_builder()
    chosen = exit_lot if action == "complete-withdrawal" else lot
    rows[str(chosen)]["owner"] = "11111111111111111111111111111111"
    payload = (NoticeRequest(lot=str(lot), request_id="8", basis_lamports="100") if action == "withdrawal-notice" else
               ConvertRequest(lot=str(lot), lock_weeks=13) if action == "convert-pledge" else
               WithdrawalRequest(lot=str(chosen), request=str(request)))
    with pytest.raises(ValueError, match="signed-in wallet"):
        await b.plan(action, payload, str(WALLET))


@pytest.mark.asyncio
async def test_complete_withdrawal_uses_exit_lot_and_refuses_original():
    b, rows, hill, climb, lot, request, exit_lot = fixture_builder()
    with pytest.raises(ValueError, match="this lot"):
        await b.plan("complete-withdrawal", WithdrawalRequest(lot=str(lot), request=str(request)), str(WALLET))
    rows[str(exit_lot)]["deposit_id"] = 0  # Real exit children do not copy the parent ID.
    result = await b.plan("complete-withdrawal", WithdrawalRequest(lot=str(exit_lot), request=str(request)), str(WALLET))
    assert result.instructions[-1].accounts[2].pubkey == exit_lot
    assert result.rent_payer == str(WALLET)
    assert result.intent["depositId"] == "7"


@pytest.mark.asyncio
async def test_claim_without_keeper_proofs_is_not_prepared():
    from app.routes.stage1_actions import ClaimRequest
    b, *_ = fixture_builder()
    with pytest.raises(ValueError, match="durable proofs"):
        await b.plan("self-claim", ClaimRequest(claims=[dict(job_id="missing", index=0)]), str(WALLET))

@pytest.mark.asyncio
async def test_cancel_pledge_builds_only_owner_return_and_matching_intent():
    from types import SimpleNamespace
    b, rows, hill, climb, lot, request, exit_lot = fixture_builder()
    result = await b.plan('cancel-pledge', SimpleNamespace(lot=str(lot)), str(WALLET))
    assert result.instructions[-1].data.hex() == '28693d7e979934d9'
    assert result.intent == {'kind': 'stage1_cancel_pledge', 'hill': str(hill), 'mint': rows[str(lot)]['mint'], 'depositId': '7'}

@pytest.mark.asyncio
async def test_prebond_inventory_uses_exact_sized_city_and_discriminator_filters(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock
    from app.services import stage1_transactions as module
    from scripts.generate_stage1_transaction_fixtures import JITO
    from solders.pubkey import Pubkey
    b, rows, hill_key, *_ = fixture_builder()
    city_key = b.pda("s1v1_city")
    asset_key = b.pda("s1v1_asset", bytes(Pubkey.from_string(JITO)))
    incoming = rows[str(asset_key)]
    b.coder.accounts.decode = Mock(return_value=incoming)
    row = SimpleNamespace(pubkey=asset_key, account=SimpleNamespace(owner=b.program_id, executable=False,
        data=__import__('hashlib').sha256(b"account:Stage1AssetConfig").digest()[:8] + bytes(359)))
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get_program_accounts.return_value = SimpleNamespace(value=[row])
    monkeypatch.setattr(module, "AsyncClient", lambda *a, **kw: client)
    city = {"provider_slots": 1, "asset_count": 1}
    hill = {"bonded": False, "asset_lots": [1] + [0] * 31}
    await module.Stage1TxBuilder.pledge_providers(b, city, hill, incoming)
    # The RPC default is base58, which refuses these 367-byte accounts.
    assert client.get_program_accounts.call_args.kwargs["encoding"] == "base64"
    filters = client.get_program_accounts.call_args.kwargs["filters"]
    assert 367 in filters
    assert {f.offset for f in filters if not isinstance(f, int)} == {0, 9}
    assert next(f.bytes for f in filters if not isinstance(f, int) and f.offset == 9) == str(city_key)
    row.pubkey = Pubkey.default()
    with pytest.raises(ValueError, match="inventory"):
        await module.Stage1TxBuilder.pledge_providers(b, city, hill, incoming)


@pytest.mark.asyncio
async def test_prebond_inventory_skips_sponsor_cash_in_the_backed_slot(monkeypatch):
    # Sponsor cash keeps a zero `slot` without owning a staking slot. Found on
    # devnet: the program refuses its triple, so it must never be listed.
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock
    from app.services import stage1_transactions as module
    from scripts.generate_stage1_transaction_fixtures import JITO
    from solders.pubkey import Pubkey
    b, rows, *_ = fixture_builder()
    usdc = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    staking_key = b.pda("s1v1_asset", bytes(Pubkey.from_string(JITO)))
    cash_key = b.pda("s1v1_asset", bytes(Pubkey.from_string(usdc)))
    incoming = rows[str(staking_key)]
    cash = {**incoming, "mint": usdc, "adapter": 254, "slot": 0}  # program S1_CASH_ADAPTER
    header = __import__('hashlib').sha256(b"account:Stage1AssetConfig").digest()[:8]
    def row(pubkey, marker):
        return SimpleNamespace(pubkey=pubkey, account=SimpleNamespace(owner=b.program_id, executable=False,
            data=header + bytes([marker]) + bytes(358)))
    staking_row, cash_row = row(staking_key, 0), row(cash_key, 1)
    b.coder.accounts.decode = Mock(side_effect=lambda data: cash if data[8] == 1 else incoming)
    client = AsyncMock()
    client.__aenter__.return_value = client
    monkeypatch.setattr(module, "AsyncClient", lambda *a, **kw: client)
    city = {"provider_slots": 1, "asset_count": 1}
    async def providers(listed, hill):
        client.get_program_accounts.return_value = SimpleNamespace(value=listed)
        return await module.Stage1TxBuilder.pledge_providers(b, city, hill, incoming)
    for hill in ({"bonded": False, "asset_lots": [0] * 32}, {"bonded": False, "asset_lots": [1] + [0] * 31}):
        alone = await providers([staking_row], hill)
        assert alone[0].pubkey == staking_key and cash_key not in [m.pubkey for m in alone]
        # Registration order must not matter: cash first or after the provider.
        assert await providers([cash_row, staking_row], hill) == alone
        assert await providers([staking_row, cash_row], hill) == alone
    with pytest.raises(ValueError, match="exceeds release slots"):
        await providers([cash_row, cash_row, staking_row], {"bonded": False, "asset_lots": [1] + [0] * 31})


@pytest.mark.asyncio
async def test_discovery_shares_reads_only_inside_one_request():
    from unittest.mock import AsyncMock
    b, *_ = fixture_builder()
    b.raw_account = AsyncMock(return_value=object())
    reader = b.discovery_reader()
    assert await reader.raw_account(WALLET) is await reader.raw_account(WALLET)
    assert await reader.genesis() == await reader.genesis()
    assert b.raw_account.await_count == b.genesis.await_count == 1
    await b.discovery_reader().raw_account(WALLET)
    assert b.raw_account.await_count == 2


def test_discovery_cache_expires_evicts_and_does_not_share_mutable_values(monkeypatch):
    from app.services import stage1_claim_cache as module
    now = [10.0]
    monkeypatch.setattr(module, "monotonic", lambda: now[0])
    cache = module.ClaimDiscoveryCache(max_entries=2, ttl_seconds=10)
    key = ("owner", 1)
    cache.put(key, {"claims": [1]})
    cache.get(key)["claims"].append(2)
    assert cache.get(key) == {"claims": [1]}
    cache.put(("other", 1), {}); cache.put(("third", 1), {})
    assert len(cache.entries) == 2 and cache.get(key) is None
    cache.invalidate_owner("other")
    assert cache.get(("other", 1)) is None
    now[0] = 20.0
    assert cache.get(("third", 1)) is None
