"""Cluster gates use mocked RPC only: these tests send no network transactions."""
import json
import logging

import httpx
import pytest
from solders.keypair import Keypair

from app.services.stage1_keeper_chain import KeeperChain

DEVNET = 'EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG'
MAINNET = '5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d'
TESTNET = '4uhcVJyU9pJkvQyS88uRDiswHXSCkY3zQawwpjk2NsNY'


def test_malformed_url_cannot_echo_credentials():
    with pytest.raises(ValueError) as caught:
        KeeperChain('https://rpc-user:rpc-password@private.example／bad',str(Keypair().pubkey()),'/not/read',allowed_clusters=('devnet',))
    assert 'rpc-user' not in str(caught.value) and 'rpc-password' not in str(caught.value)
    assert caught.value.__suppress_context__


@pytest.mark.asyncio
@pytest.mark.parametrize('endpoint,allowed,release,genesis,accept', [
    ('http://127.0.0.1:8899', ('localnet',), False, 'local-fixture', True),
    ('http://127.0.0.1:8899', ('localnet',), False, DEVNET, False),
    ('https://private-rpc.example/?api-key=secret', ('devnet',), False, DEVNET, True),
    ('https://api.devnet.solana.com', ('devnet',), False, MAINNET, False),
    ('https://private-rpc.example', ('devnet',), False, 'unknown-genesis', False),
    ('https://private-rpc.example', ('devnet',), False, TESTNET, False),
    ('https://private-rpc.example', ('mainnet-beta',), False, MAINNET, False),
    ('https://private-rpc.example', ('mainnet-beta',), True, MAINNET, True),
    ('https://private-rpc.example', ('devnet',), True, MAINNET, False),
])
async def test_genesis_allowlist_precedes_publisher_key_read(tmp_path,endpoint,allowed,release,genesis,accept):
    wallet=tmp_path/'publisher.json'
    signer=Keypair()
    keys={c:str(Keypair().pubkey()) for c in ('localnet','devnet','mainnet-beta')}
    keys['devnet' if genesis==DEVNET else 'mainnet-beta' if genesis==MAINNET else 'localnet']=str(signer.pubkey())
    if accept:
        wallet.write_text(json.dumps(list(bytes(signer))))
    chain=KeeperChain(endpoint,str(Keypair().pubkey()),wallet,
                      allowed_clusters=allowed,mainnet_release=release,publisher_keys=keys)
    await chain.client.aclose()
    chain.client=httpx.AsyncClient(transport=httpx.MockTransport(lambda req:httpx.Response(200,json={'result':genesis})))
    try:
        if accept:
            await chain.start()
            assert chain.genesis==genesis and chain.signer is not None
        else:
            with pytest.raises(ValueError,match='cluster|mainnet|public network'):
                await chain.start()
            assert chain.signer is None
    finally:
        await chain.close()


@pytest.mark.asyncio
async def test_credential_endpoint_is_absent_from_logs_and_errors(caplog):
    endpoint='https://rpc-user:rpc-password@private.example/secret-path/?api-key=secret-query'
    chain=KeeperChain(endpoint,str(Keypair().pubkey()),'/not/read',allowed_clusters=('devnet',))
    await chain.client.aclose()
    chain.client=httpx.AsyncClient(transport=httpx.MockTransport(lambda req:httpx.Response(503,text=endpoint)))
    try:
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(RuntimeError) as caught:
                await chain.rpc('getGenesisHash',[])
        for secret in ('rpc-user','rpc-password','secret-path','secret-query'):
            assert secret not in caplog.text + str(caught.value)
        assert caught.value.__suppress_context__
    finally:
        await chain.close()
