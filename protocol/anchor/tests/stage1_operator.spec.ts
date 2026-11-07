import { expect } from 'chai';
import { Keypair, SystemProgram, TransactionMessage, VersionedTransaction } from '@solana/web3.js';
import { simulateThenSubmit, Operator, u64, runOperator, planFor } from '../scripts/stage1_operator.js';
import { CURRENT_PROGRAM_VERSION } from '../generated-program-version.js';
import { mkdtempSync, writeFileSync, rmSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

describe('Stage1 exact-input operator transport', () => {
  it('advances finalized reads monotonically, including concurrent responses', async () => {
    const key = () => Keypair.generate().publicKey.toBase58();
    const r = new Operator({ 'program-id': key(), admin: key(), 'fee-payer': key(), cluster: 'localnet', rpc: 'http://127.0.0.1:28999' });
    r.floor = 100;
    const pending: ((value: any) => void)[] = [];
    r.connection.getAccountInfoAndContext = async (_key, options: any) => {
      expect(options.minContextSlot).eq(100);
      return await new Promise(resolve => pending.push(resolve));
    };
    const first = r.read(Keypair.generate().publicKey), second = r.read(Keypair.generate().publicKey);
    pending[0]({ context: { slot: 120 }, value: null }); await first;
    expect(r.floor).eq(120);
    pending[1]({ context: { slot: 110 }, value: null }); await second;
    expect(r.floor).eq(120);
    r.connection.getAccountInfoAndContext = async (_key, options: any) => {
      expect(options.minContextSlot).eq(120); return { context: { slot: 119 }, value: null };
    };
    let error=''; try { await r.read(Keypair.generate().publicKey); } catch (e: any) { error=e.message; }
    expect(error).include('below finalized floor');
    r.connection.getSlot = async () => 100;
    await r.finalizedAssert(async () => { expect(r.floor).eq(120); });
  });
  function transaction() {
    const payer = Keypair.generate();
    const tx = new VersionedTransaction(new TransactionMessage({ payerKey: payer.publicKey,
      recentBlockhash: Keypair.generate().publicKey.toBase58(), instructions: [SystemProgram.transfer({
        fromPubkey: payer.publicKey, toPubkey: Keypair.generate().publicKey, lamports: 1 })] }).compileToLegacyMessage());
    tx.sign([payer]); return tx;
  }
  it('simulates with signatures, sends identical bytes, then requires finalized confirmation', async () => {
    const tx = transaction(), expected = Buffer.from(tx.serialize()), calls: string[] = [];
    await simulateThenSubmit({
      simulateTransaction: async (signed: any, options: any) => {
        calls.push('simulate'); expect(Buffer.from(signed.serialize()).equals(expected)).to.equal(true);
        expect(options).to.deep.equal({ sigVerify: true, replaceRecentBlockhash: false, commitment: 'finalized' });
        return { value: { err: null } };
      },
      sendRawTransaction: async (bytes: any) => { calls.push('send'); expect(Buffer.from(bytes).equals(expected)).to.equal(true); return 'signature'; },
      confirmTransaction: async (signature: string, commitment: string) => { calls.push('finalized'); expect([signature, commitment]).to.deep.equal(['signature', 'finalized']); return { value: { err: null } }; },
    } as any, tx);
    expect(calls).to.deep.equal(['simulate', 'send', 'finalized']);
  });
  it('never sends after a simulation failure or a mutation of signed bytes', async () => {
    for (const mutation of [false, true]) {
      let sends = 0; const tx = transaction();
      try {
        await simulateThenSubmit({ simulateTransaction: async () => {
          if (mutation) tx.signatures[0][0] ^= 1;
          return { value: { err: mutation ? null : 'failed' } };
        }, sendRawTransaction: async () => { sends++; } } as any, tx);
        throw new Error('accepted');
      } catch (e: any) { expect(e.message).to.include(mutation ? 'changed after simulation' : 'Simulation failed'); }
      expect(sends).to.equal(0);
    }
  });
  it('rejects signed and overflowing amounts before PDA encoding', () => {
    expect(() => u64('-1')).to.throw('out of range');
    expect(() => u64('18446744073709551616')).to.throw('out of range');
    expect(u64('18446744073709551615').toString('hex')).to.equal('ffffffffffffffff');
  });
  it('requires explicit targets and distinct fee payer before any RPC or keypair read', () => {
    expect(() => new Operator({})).to.throw('program-id');
    const key = Keypair.generate().publicKey.toBase58();
    expect(() => new Operator({ 'program-id': key, admin: key, 'fee-payer': key })).to.throw('distinct');
    expect(() => new Operator({ 'program-id': key, admin: key, 'fee-payer': Keypair.generate().publicKey.toBase58(), cluster: 'localnet', rpc: 'https://api.devnet.solana.com' })).to.throw('loopback');
  });
});

describe('Stage1 network and signer boundaries', () => {
  const publicHashes: Record<string, string> = {
    'mainnet-beta': '5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d',
    devnet: 'EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG',
    testnet: '4uhcVJyU9pJkvQyS88uRDiswHXSCkY3zQawwpjk2NsNY',
  };
  const key = () => Keypair.generate().publicKey.toBase58();
  const options = () => ({ 'program-id': key(), admin: key(), 'fee-payer': key(),
    cluster: 'localnet', rpc: 'http://127.0.0.1:28999', action: 'publisher', mode: 'plan' });
  for (const [network, genesis] of Object.entries(publicHashes)) {
    for (const label of ['mainnet-beta', 'devnet', 'localnet']) {
      it(`real start checks full ${network} genesis against the ${label} label, including loopback forwarding`, async () => {
        const r = new Operator({ ...options(), cluster: label }); let reads = 0;
        r.connection.getGenesisHash = async () => genesis;
        r.connection.getSlot = async () => 100;
        r.read = async () => { reads++; return { executable: true } as any; };
        r.fetch = async () => ({ initialized: true, programVersion: CURRENT_PROGRAM_VERSION, adminAuthority: r.admin });
        let error: any; try { await r.start(); } catch (e) { error = e; }
        if (network === label) { expect(error).to.equal(undefined); expect(reads).to.equal(1); }
        else { expect(error?.message).to.match(/genesis|Public cluster/); expect(reads).to.equal(0); }
      });
    }
  }
  it('real start admits a private genesis on loopback', async () => {
    const r = new Operator(options());
    r.connection.getGenesisHash = async () => key(); r.connection.getSlot = async () => 100;
    r.read = async () => ({ executable: true } as any);
    r.fetch = async () => ({ initialized: true, programVersion: CURRENT_PROGRAM_VERSION, adminAuthority: r.admin });
    await r.start(); expect(r.floor).to.equal(100);
    const devnet = new Operator({ ...r.options, 'program-interface': 'devnet' });
    expect(r.program.methods.registerStage1TestPool).to.equal(undefined);
    expect(devnet.program.methods.registerStage1TestPool).to.be.a('function');
    const op = { instructions: [], assert: async () => {}, description: 'interface binding' };
    expect(planFor(r, 'test', {}, op).idlHash).not.to.equal(planFor(devnet, 'test', {}, op).idlHash);
    expect(() => new Operator({ ...r.options, cluster: 'mainnet-beta', 'program-interface': 'devnet' })).to.throw('Devnet interface');
  });
  for (const rpc of ['https://user:secret@example.com', 'https://example.com/?api-key=secret',
    'https://example.com/secret', 'https://example.com/#secret', 'https://example.com/%73ecret']) {
    it(`rejects credential-bearing RPC structure ${new URL(rpc).username ? 'userinfo' : new URL(rpc).pathname !== '/' ? 'path' : 'query/fragment'}`, () => {
      let error: any; try { new Operator({ ...options(), cluster: 'devnet', rpc }); } catch (e) { error = e; }
      expect(error?.message).to.match(/credential|origin/i); expect(error.message).not.to.include('secret');
    });
  }
  const roles = ['publisher', 'operator', 'testOwner', 'pool', 'mint', 'poolManager', 'poolStaker', 'validatorList',
    'reserve', 'validatorIdentity', 'validatorVote'];
  for (const [first, second] of [...roles.map(role => [role, 'fee-payer']), ['publisher', 'admin'], ['operator', 'publisher'],
    ['poolStaker', 'admin'], ['validatorList', 'pool'], ['reserve', 'mint']]) {
    it(`rejects ${first}/${second} role overlap before RPC, keypair reads or plan output`, async () => {
      const opts = options(), input: Record<string, string> = {};
      for (const role of roles) input[role] = key();
      input[first] = (opts as any)[second] ?? input[second];
      const dir = mkdtempSync(join(tmpdir(), 'stage1-role-test-')), file = join(dir, 'input.json');
      writeFileSync(file, JSON.stringify(input));
      const start = Operator.prototype.start, log = console.log; let starts = 0, prints = 0, error: any;
      Operator.prototype.start = async () => { starts++; }; console.log = () => { prints++; };
      try { await runOperator('role-test', async () => ({ instructions: [], assert: async () => {}, description: 'test' }), { ...opts, input: file }); }
      catch (e) { error = e; }
      finally { Operator.prototype.start = start; console.log = log; rmSync(dir, { recursive: true }); }
      expect(error?.message).to.include('distinct'); expect(starts).to.equal(0); expect(prints).to.equal(0);
    });
  }
});
