#!/usr/bin/env python3
"""Owned local validator/database runner; no public-network configuration or keys."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import urllib.request
import uuid
from urllib.parse import urlparse,urlunparse

import psycopg2

ROOT=Path(__file__).resolve().parents[3]
ANCHOR=ROOT/'protocol/anchor'
LOCAL='5TU6hcKXiVt3Lttw7VLu4Jq18FeAgiURk5WxBVYAGGYt'


def main():
    base=os.environ['STAGE1_KEEPER_TEST_DSN'];parsed=urlparse(base)
    if parsed.hostname!='127.0.0.1':raise ValueError('disposable localhost database required')
    binary=Path(os.environ['STAGE1_INDEXER_LOCAL_BINARY']).resolve()
    if not binary.is_file():raise ValueError('build the current stage1-localnet binary first')
    evidence=Path(os.environ['STAGE1_KEEPER_EVIDENCE']).resolve();evidence.mkdir(parents=True,exist_ok=True,mode=0o700)
    directory=Path(tempfile.mkdtemp(prefix='stage1-indexer-e2e-',dir='/private/tmp'))
    database='keeper_indexer_e2e_'+uuid.uuid4().hex
    connection=psycopg2.connect(base);connection.autocommit=True
    cursor=connection.cursor();cursor.execute('CREATE DATABASE "'+database+'"')
    dsn=urlunparse(parsed._replace(path='/'+database))
    child=None
    try:
        wallet=directory/'wallet.json'
        subprocess.run(['solana-keygen','new','--silent','--no-bip39-passphrase','--outfile',str(wallet)],check=True,stdout=subprocess.DEVNULL)
        public=subprocess.check_output(['solana-keygen','pubkey',str(wallet)],text=True).strip()
        idl=json.loads((ANCHOR/'idl/boulder_rollers.json').read_text())
        # Exact local-only wrapper from stage1_localnet_idl.rs; production IDL stays unchanged.
        idl['instructions'].append({'name':'setTestLstRate','accounts':[
          {'name':'city','isMut':True,'isSigner':False},{'name':'asset','isMut':True,'isSigner':False},
          {'name':'programConfig','isMut':False,'isSigner':False},{'name':'admin','isMut':False,'isSigner':True}],
          'args':[{'name':'n','type':'u64'},{'name':'d','type':'u64'},{'name':'observedAt','type':'i64'}]})
        idl_path=directory/'localnet-idl.json';idl_path.write_text(json.dumps(idl))
        rpc='http://127.0.0.1:19880'
        log=open(directory/'validator.log','w')
        child=subprocess.Popen(['solana-test-validator','--ledger',str(directory/'ledger'),'--rpc-port','19880','--faucet-port','19882','--bind-address','127.0.0.1','--dynamic-port-range','19890-19920','--mint',public,'--upgradeable-program',LOCAL,str(binary),public,'--log'],stdout=log,stderr=log)
        for _ in range(150):
            if child.poll() is not None:raise RuntimeError((directory/'validator.log').read_text()[-4000:])
            try:
                req=urllib.request.Request(rpc,data=b'{"jsonrpc":"2.0","id":1,"method":"getLatestBlockhash"}',headers={'Content-Type':'application/json'})
                with urllib.request.urlopen(req,timeout=1) as response:json.load(response)
                break
            except Exception:time.sleep(.2)
        else:raise RuntimeError('local validator did not start')
        env={**os.environ,'ANCHOR_PROVIDER_URL':rpc,'ANCHOR_WALLET':str(wallet),'STAGE1_LOCALNET':'1','STAGE1_INDEXER_IDL':str(idl_path),
             'STAGE1_KEEPER_EVIDENCE':str(evidence),'STAGE1_KEEPER_TEST_DSN':dsn,'DATABASE_URL':dsn,'STAGE1_KEEPER_PYTHON':os.environ.get('STAGE1_KEEPER_PYTHON',os.sys.executable),
             'STAGE1_REPLAY_RPC_PORT':'19950','STAGE1_REPLAY_FAUCET_PORT':'19952','STAGE1_REPLAY_DYNAMIC_PORTS':'20100-20130',
             'STAGE1_REPLAY_ROOT':str(directory),'NODE_OPTIONS':'--loader ts-node/esm --no-warnings','TS_NODE_TRANSPILE_ONLY':'true','LC_ALL':'en_US.UTF-8'}
        subprocess.run(['./node_modules/.bin/mocha','-t','900000','tests/stage1_indexer.spec.ts'],cwd=ANCHOR,env=env,check=True)
        if any(p.name.startswith('stage1-genesis-replay-') for p in directory.iterdir()):raise RuntimeError('replay ledger leaked')
    finally:
        if child:
            child.terminate()
            try:child.wait(timeout=8)
            except subprocess.TimeoutExpired:child.kill();child.wait()
            log.close()
        cursor.execute('DROP DATABASE "'+database+'" WITH (FORCE)');cursor.close();connection.close()
        shutil.rmtree(directory)

if __name__=='__main__':main()
