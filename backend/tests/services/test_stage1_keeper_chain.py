import pytest
from solders.keypair import Keypair

from app.services.stage1_keeper_chain import KeeperChain
from app.services.stage1_keeper_worker import Blocked


@pytest.mark.asyncio
@pytest.mark.parametrize('error,terminal', [
    ({'code':-32002,'data':{'err':{'InstructionError':[0,{'Custom':6011}]}}},True),
    ({'code':-32002,'data':{'err':'BlockhashNotFound'}},False),
    ({'code':-32005},False),
])
async def test_rpc_program_refusal_is_terminal_but_transport_lag_retries(error,terminal):
    import httpx
    chain=KeeperChain('http://127.0.0.1:28999',str(Keypair().pubkey()),'/not/read')
    await chain.client.aclose()
    chain.client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'error':error})))
    try:
        with pytest.raises(Blocked if terminal else RuntimeError):
            await chain.rpc('sendTransaction',[])
    finally:
        await chain.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('status',[200,429,503])
async def test_non_json_transport_failure_never_becomes_measurement_refusal(status):
    import httpx
    chain=KeeperChain('http://127.0.0.1:28999',str(Keypair().pubkey()),'/not/read')
    await chain.client.aclose()
    chain.client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(status,text='temporarily unavailable')))
    try:
        with pytest.raises((httpx.HTTPStatusError,RuntimeError)):
            await chain.rpc('sendTransaction',[])
    finally:
        await chain.close()


@pytest.mark.parametrize("kind", ["init", "open", "publish"])
def test_hill_composite_is_writable_per_anchor_abi(kind):
    p = [str(Keypair().pubkey()) for _ in range(4)]
    chain = KeeperChain("http://127.0.0.1:28999", p[0], "/not/read")
    chain.signer = Keypair()
    scope = {"city": p[1], "hill": p[2], "mint": p[3]}
    op = {"kind": kind, "week": 0, "root": "11"*32, "total": 1, "count": 1, "holds": [0]*5, "sources": []}
    ix = chain.instructions(scope, op)[0]
    assert next(m for m in ix.accounts if str(m.pubkey) == scope["hill"]).is_writable


@pytest.mark.parametrize("rpc", ["https://api.devnet.solana.com", "http://example.com", "http://u:p@127.0.0.1:8899", "http://127.0.0.1:8899/?api-key=x"])
def test_nonlocal_or_credential_rpc_rejected_before_key_read(rpc):
    with pytest.raises(ValueError, match="loopback"):
        KeeperChain(rpc, str(Keypair().pubkey()), "/not/read")


@pytest.mark.asyncio
async def test_stale_absence_cannot_authorize_new_signature():
    chain = KeeperChain("http://127.0.0.1:28999", str(Keypair().pubkey()), "/not/read")
    chain.signer = Keypair()
    chain.genesis = "local"
    async def rpc(method, params):
        return {"getGenesisHash": "local", "getSignatureStatuses": {"context": {"slot": 100}, "value": [None]},
                "getBlockHeight": 201, "getSlot": 300, "getBlock": {"blockHeight": 201}}[method]
    chain.rpc = rpc
    with pytest.raises(RuntimeError, match="stale"):
        await chain.status({"signature": "persisted", "last_valid_block_height": 200, "genesis": "local"})


@pytest.mark.asyncio
async def test_persisted_submission_rechecks_genesis_before_send():
    chain = KeeperChain("http://127.0.0.1:28999", str(Keypair().pubkey()), "/not/read")
    calls = []
    async def rpc(method, params):
        calls.append(method)
        if method == "getGenesisHash":
            return "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG"
        return "persisted"
    chain.rpc = rpc
    with pytest.raises(ValueError, match="public network"):
        await chain.submit({"bytes": "persisted bytes", "signature": "persisted", "genesis": "local"})
    assert "sendTransaction" not in calls


@pytest.mark.asyncio
async def test_lookup_read_is_fenced_by_prior_finalized_transaction():
    chain = KeeperChain("http://127.0.0.1:28999", str(Keypair().pubkey()), "/not/read")
    chain.signer = Keypair()
    chain.genesis = "local"
    async def authorized(kind, floor):
        return floor
    chain.authorize = authorized
    calls = []
    async def rpc(method, params):
        calls.append((method, params))
        return {"getGenesisHash": "local", "getLatestBlockhash": {"context": {"slot": 150}},
                "getAccountInfo": {"context": {"slot": 100}, "value": None}}[method]
    chain.rpc = rpc
    with pytest.raises(RuntimeError, match="stale"):
        await chain.prepare({}, {"kind": "cash_claim", "lookup": str(Keypair().pubkey())}, floor=150)
    assert next(p for m,p in calls if m == "getAccountInfo")[1]["minContextSlot"] == 150
