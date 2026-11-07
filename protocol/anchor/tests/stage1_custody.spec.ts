import { fundedSweep } from './helpers/stage1_funding.js';
import * as anchor from '@coral-xyz/anchor';
import BN from 'bn.js';
import { expect } from 'chai';
import { createHash } from 'crypto';
import { readFileSync } from 'fs';
import { PublicKey, SystemProgram, Keypair, SYSVAR_RENT_PUBKEY, SYSVAR_CLOCK_PUBKEY,
  TransactionMessage, VersionedTransaction, ComputeBudgetProgram, TransactionInstruction } from '@solana/web3.js';
import { createMint, getOrCreateAssociatedTokenAccount, mintTo, getAccount, transfer, TOKEN_PROGRAM_ID } from '@solana/spl-token';
import { capture, replay, pause, Capture } from './helpers/stage1_replay.js';

// Local transactions and a simulated LST, never production-provider evidence.
let provider = anchor.AnchorProvider.env();
anchor.setProvider(provider);
let program: any = anchor.workspace.BoulderRollers;
const originalProgram = program;
const wallet = provider.wallet as anchor.Wallet;
const other = Keypair.generate();
const W = 604800, SOL = 1_000_000_000n;
let serial = 0;
let transactionSerial = 0;
let simulateTransactions = false;
const bn = (v: bigint | number | string) => new BN(String(v));
const u64 = (v: number) => bn(v).toArrayLike(Buffer, 'le', 8);
const pda = (seed: string, ...parts: Buffer[]) => PublicKey.findProgramAddressSync([Buffer.from(seed), ...parts], program.programId)[0];
const city = () => pda('s1v1_city');
const config = () => pda('program_config');
const asset = (mint: PublicKey) => pda('s1v1_asset', mint.toBuffer());
const earnings = (mint: PublicKey) => pda('s1v1_earnings', mint.toBuffer());
const custody = (lot: PublicKey) => pda('s1v1_custody', lot.toBuffer());
const reserve = (lot: PublicKey) => pda('s1v1_owner', lot.toBuffer());
const lotState = (lot: PublicKey) => program.account.stage1PledgeLot.fetch(lot);
const hillState = (hill: PublicKey) => program.account.stage1HillBond.fetch(hill);
const now = async () => Number((await provider.connection.getAccountInfo(SYSVAR_CLOCK_PUBKEY,
  simulateTransactions ? 'finalized' : 'processed'))!.data.readBigInt64LE(32));
let mint: PublicKey, source: PublicKey, otherSource: PublicKey;
let bondedHill: PublicKey, founderLot: PublicKey, triggerLot: PublicKey, healthyLot: PublicKey;
let prebondCapture: Capture;
const oracle = JSON.parse(readFileSync(new URL('./fixtures/stage1_custody_vectors.json', import.meta.url), 'utf8'));
const vectors = oracle.cases;

async function send(builder: any, signers: Keypair[] = []) {
  const ix: TransactionInstruction = builder instanceof TransactionInstruction ? builder : await builder.instruction();
  // Fresh signatures even within a frozen replay bank. Replay rejection must
  // execute the instruction again, not return a cached successful signature.
  const instructions = [ComputeBudgetProgram.setComputeUnitLimit({ units: 1_400_000 }),
    ComputeBudgetProgram.setComputeUnitPrice({ microLamports: ++transactionSerial }),
    ...await fundedSweep(program, provider, wallet.publicKey, ix)];
  let latest = await provider.connection.getLatestBlockhash(simulateTransactions ? 'finalized' : 'processed');
  const tx = new VersionedTransaction(new TransactionMessage({ payerKey: wallet.publicKey,
    recentBlockhash: latest.blockhash, instructions }).compileToLegacyMessage());
  tx.sign([wallet.payer, ...signers.filter(k => !k.publicKey.equals(wallet.publicKey))]);
  if (simulateTransactions) {
    const addresses = [...new Set(ix.keys.filter(k => k.isWritable).map(k => k.pubkey.toBase58()))];
    const result = await provider.connection.simulateTransaction(tx, { commitment: 'finalized', sigVerify: true,
      accounts: { encoding: 'base64', addresses } });
    if (result.value.err) throw new Error(`Local exact-clock simulation: ${JSON.stringify(result.value.err)}\n${result.value.logs?.join('\n')}`);
    // Returned buffers are simulation output, never written into a validator.
    return new Map(addresses.map((address, i) => [address, Buffer.from(result.value.accounts![i]!.data[0], 'base64')]));
  }
  const signature = await provider.connection.sendRawTransaction(tx.serialize(), { preflightCommitment: 'processed' });
  for (let i = 0; i < 1200; i++) {
    const status = (await provider.connection.getSignatureStatuses([signature])).value[0];
    if (status) { expect(status.err, signature).to.equal(null); return signature; }
    await pause(50);
  }
  throw new Error(`Local transaction did not process before its bounded wait: ${signature}; slot=${await provider.connection.getSlot('processed')}; blockhashValid=${(await provider.connection.isBlockhashValid(latest.blockhash, { commitment: 'processed' })).value}`);
}
async function rejected(action: Promise<unknown>, reason: string) {
  try { await action; } catch (error: any) {
    const detail = `${error.message}\n${error.logs?.join('\n')}`;
    if (!detail.includes(reason)) throw new Error(`Expected ${reason}, got ${detail}`);
    return;
  }
  throw new Error(`Expected rejection: ${reason}`);
}
async function refreshLot(lot: PublicKey, materialize = false) {
  const state = await lotState(lot);
  return send(program.methods[materialize ? 'materializeStage1Lot' : 'refreshCampaignLot']().accounts({
    city: city(), hill: state.hill, lot, asset: asset(state.mint), custody: custody(lot),
    ownerReserve: reserve(lot), tokenProgram: TOKEN_PROGRAM_ID,
  }));
}
async function rate(n: number, d = 1, observed?: number, token = mint) {
  await send(program.methods.setTestLstRate(bn(n), bn(d), bn(observed ?? await now())).accounts({
    city: city(), asset: asset(token), programConfig: config(), admin: wallet.publicKey,
  }));
}
async function newHill(options: any = {}) {
  const hash = (s: string) => createHash('sha256').update(s).digest();
  const id = hash(`stage1-canon-${++serial}`).subarray(0, 16), profile = hash(`stage1-profile-${serial}`);
  const commitment = Buffer.alloc(64); commitment[0] = 1; id.copy(commitment, 1);
  commitment.writeUInt16BE(1, 17); profile.copy(commitment, 32);
  const digest = createHash('sha256').update(commitment).digest();
  const climb = pda('climb', digest);
  await send(program.methods.registerRatifiedClimb({ canonId: [...id], canonVersion: 1,
    canonicalProfileHash: [...profile], commitmentHash: [...digest], recordContinuityPolicy: { newRecordBoard: {} },
    name: `Local stage1 hill ${serial}`, vertM: 1000, distanceM: 2000, avgGradientPct: 500,
  }).accounts({ climb, climbVersionIndex: pda('climb_version', id, Buffer.from([0, 1])), predecessorClimb: null,
    programConfig: config(), admin: wallet.publicKey, systemProgram: SystemProgram.programId }));
  const hill = pda('s1v1_hill', id);
  await send(program.methods.initHillBond().accounts({ city: city(), climb, hill, admin: options.admin ?? wallet.publicKey, programConfig: config(), systemProgram: SystemProgram.programId }), options.signers ?? []);
  expect((await program.account.climb.fetch(climb)).vault.equals(PublicKey.default)).to.equal(true);
  return hill;
}
async function deposit(hill: PublicKey, units: bigint | number, options: any = {}) {
  const id = options.id ?? ++serial, owner = options.owner ?? wallet.publicKey;
  const token = options.mint ?? mint;
  const lot = pda('s1v1_lot', owner.toBuffer(), u64(id));
  const builder = program.methods[options.bond ? 'bond' : 'pledge'](bn(id), bn(units), options.lock ?? 0).accounts({
    city: city(), hillAccount: { hill }, climb: options.climb ?? (await hillState(hill)).climb,
    asset: options.asset ?? asset(token), mint: token, lot, custody: options.custody ?? custody(lot), ownerReserve: reserve(lot),
    source: options.source ?? source, owner, tokenProgram: TOKEN_PROGRAM_ID,
    systemProgram: SystemProgram.programId, rent: SYSVAR_RENT_PUBKEY,
  });
  await send(builder, options.signers ?? []);
  return lot;
}
async function ownerAction(name: string, lot: PublicKey, options: any = {}) {
  const state = await lotState(lot);
  return send(program.methods[name]().accounts({ city: city(), hill: state.hill, lot, asset: asset(state.mint), custody: custody(lot),
    ownerReserve: reserve(lot), destination: options.destination ?? source,
    owner: options.owner ?? wallet.publicKey, tokenProgram: TOKEN_PROGRAM_ID }), options.signers ?? []);
}
async function convert(lot: PublicKey, lock: number, owner = wallet.publicKey, signers: Keypair[] = []) {
  const state = await lotState(lot);
  return send(program.methods.convertExcludedPledge(lock).accounts({ city: city(), hill: state.hill, lot,
    asset: asset(state.mint), custody: custody(lot), ownerReserve: reserve(lot), owner,
    tokenProgram: TOKEN_PROGRAM_ID }), signers);
}
async function checkBasisTotals() {
  const [lots, assets, hills, deployment] = await Promise.all([
    program.account.stage1PledgeLot.all(), program.account.stage1AssetConfig.all(),
    program.account.stage1HillBond.all(), program.account.stage1CityConfig.fetch(city()),
  ]);
  const sum = (predicate: (lot: any) => boolean) => lots.filter((x: any) => predicate(x.account))
    .reduce((total: bigint, x: any) => total + BigInt(x.account.basisLamports.toString()), 0n).toString();
  expect(deployment.heldBasisLamports.toString()).to.equal(sum(() => true));
  for (const x of assets) expect(x.account.heldBasisLamports.toString()).to.equal(sum(lot => lot.mint.equals(x.account.mint)));
  for (const x of hills) expect(x.account.heldBasisLamports.toString()).to.equal(sum(lot => lot.hill.equals(x.publicKey)));
  expect(deployment.heldLots.toNumber()).to.equal(lots.filter((x: any) => !x.account.basisLamports.isZero()).length);
}
async function checked<T>(action: Promise<T>): Promise<T> {
  const result = await action;
  await checkBasisTotals();
  return result;
}
async function testAsset(units: bigint) {
  const token = await createMint(provider.connection, wallet.payer, wallet.publicKey, null, 9);
  const from = (await getOrCreateAssociatedTokenAccount(provider.connection, wallet.payer, token, wallet.publicKey)).address;
  await mintTo(provider.connection, wallet.payer, token, from, wallet.payer, units);
  await send(program.methods.configureAsset(true).accounts({ city: city(), asset: asset(token), mint: token,
    earnings: earnings(token), programConfig: config(), admin: wallet.publicKey, tokenProgram: TOKEN_PROGRAM_ID,
    systemProgram: SystemProgram.programId, rent: SYSVAR_RENT_PUBKEY }));
  await rate(1, 1, undefined, token);
  return { token, from };
}
async function harvest(lot: PublicKey, amount: number | bigint, options: any = {}) {
  const state = await lotState(lot);
  return send(program.methods.harvestStage1(bn(amount)).accounts({ city: city(), hill: state.hill, lot,
    asset: options.asset ?? asset(state.mint), custody: options.custody ?? custody(lot), ownerReserve: reserve(lot), earnings: earnings(state.mint), tokenProgram: TOKEN_PROGRAM_ID }));
}
async function notice(lot: PublicKey, basis: number | bigint, id = ++serial, options: any = {}) {
  const state = await lotState(lot), request = pda('s1v1_request', lot.toBuffer(), u64(id));
  const result = await send(program.methods.requestWithdrawal(bn(id), bn(basis)).accounts({ city: city(), hill: state.hill,
    lot, request, owner: options.owner ?? wallet.publicKey, systemProgram: SystemProgram.programId }), options.signers ?? []);
  if (result instanceof Map) {
    const simulated = program.coder.accounts.decode('Stage1WithdrawalRequest', result.get(request.toBase58()));
    expect(simulated.noticeAt.toNumber(), 'Clock syscall agrees with the exact replay Clock account').to.equal(await now());
  }
  return request;
}
async function begin(lot: PublicKey, request: PublicKey, options: any = {}) {
  const state = await lotState(lot), child = pda('s1v1_exit', request.toBuffer());
  await send(program.methods.beginWithdrawal().accounts({ city: city(), hillAccount: { hill: state.hill }, lot, request,
    mint: state.mint, asset: asset(state.mint), custody: custody(lot), ownerReserve: reserve(lot),
    earnings: earnings(state.mint), exitLot: child, exitCustody: custody(child), exitReserve: reserve(child),
    owner: options.owner ?? wallet.publicKey, tokenProgram: TOKEN_PROGRAM_ID, systemProgram: SystemProgram.programId, rent: SYSVAR_RENT_PUBKEY }), options.signers ?? []);
  return child;
}
async function finish(child: PublicKey, request: PublicKey, options: any = {}) {
  const state = await lotState(child);
  return send(program.methods.completeWithdrawal().accounts({ city: city(), hill: state.hill, lot: child,
    request, asset: asset(state.mint), custody: custody(child), ownerReserve: reserve(child), earnings: earnings(state.mint),
    destination: options.destination ?? source, owner: options.owner ?? wallet.publicKey,
    tokenProgram: TOKEN_PROGRAM_ID }), options.signers ?? []);
}
// Long slots freeze the exact boundary for validator simulation. Ordinary
// submitted transactions use normal slots and the same unmodified account bytes.
async function inReplay(accounts: Capture, at: number, action: () => Promise<void>, exact = false) {
  const runtime = await replay(accounts, at, exact);
  const saved = { provider, program, simulateTransactions };
  try {
    provider = new anchor.AnchorProvider(runtime.connection, wallet, { commitment: 'processed', preflightCommitment: 'processed' });
    program = new anchor.Program(originalProgram.idl, originalProgram.programId, provider);
    simulateTransactions = exact;
    if (exact) expect(await now(), 'runtime clock before instructions').to.equal(at);
    await action();
    if (exact) expect(await now(), 'runtime clock after simulations').to.equal(at);
  } finally { await runtime.stop(); ({ provider, program, simulateTransactions } = saved); }
}

describe('stage 1 custody on the local validator', () => {
  before(async () => {
    expect(['127.0.0.1', 'localhost', '0.0.0.0']).to.include(new URL(provider.connection.rpcEndpoint).hostname);
    if (!await provider.connection.getAccountInfo(config())) {
      const executable = (await provider.connection.getAccountInfo(program.programId))!;
      await send(program.methods.initializeProgramConfig(wallet.publicKey).accounts({ programConfig: config(),
        program: program.programId, programData: new PublicKey(executable.data.subarray(4, 36)),
        admin: wallet.publicKey, systemProgram: SystemProgram.programId }));
    }
    await send(SystemProgram.transfer({ fromPubkey: wallet.publicKey, toPubkey: other.publicKey, lamports: 2_000_000_000 }));
  });
  it('initializes the immutable Philadelphia line and Monday season anchor', async () => {
    const args = { city: city(), programConfig: config(), admin: wallet.publicKey, systemProgram: SystemProgram.programId };
    await rejected(send(program.methods.initCityConfig(bn(1791201601)).accounts(args)), 'Stage1InvalidCalendar');
    await send(program.methods.initCityConfig(bn(1791201600)).accounts(args));
    const state = await program.account.stage1CityConfig.fetch(city());
    expect([state.lineLamports.toString(), state.liveLamports.toString(), state.seasonAnchor.toString()])
      .to.deep.equal(['10000000000', '5000000000', '1791201600']);
    await rejected(send(program.methods.initCityConfig(bn(1791806400)).accounts(args)), 'already in use');
  });
  if (process.env.STAGE1_LOCALNET !== '1') {
    it('keeps the simulated adapter disabled in the production build with atomic rollback', async () => {
      const token = await createMint(provider.connection, wallet.payer, wallet.publicKey, null, 9);
      await rejected(send(program.methods.configureAsset(true).accounts({ city: city(), asset: asset(token),
        mint: token, earnings: earnings(token), programConfig: config(), admin: wallet.publicKey,
        tokenProgram: TOKEN_PROGRAM_ID, systemProgram: SystemProgram.programId, rent: SYSVAR_RENT_PUBKEY })), 'Stage1AdapterDisabled');
      expect(await provider.connection.getAccountInfo(asset(token))).to.equal(null);
      expect(await provider.connection.getAccountInfo(earnings(token))).to.equal(null);
      if (process.env.STAGE1_DEVNET === '1') {
        expect(program.methods.registerStage1TestPool).to.be.a('function');
      } else {
        expect(program.methods.registerStage1TestPool).to.equal(undefined);
        await rejected(send(new TransactionInstruction({ programId: program.programId, keys: [],
          data: createHash('sha256').update('global:register_stage1_test_pool').digest().subarray(0, 8) })), 'InstructionFallbackNotFound');
      }
      expect(await provider.connection.getAccountInfo(pda('s1v1_test_pool'))).to.equal(null);
    });
    it('exposes real intake but excludes the test setter from deployable IDL and dispatch', async () => {
      for (const name of ['pledge', 'bond']) expect(program.methods[name]).to.be.a('function');
      expect(program.methods.setTestLstRate).to.equal(undefined);
      const forbidden = process.env.STAGE1_DEVNET === '1' ? ['set_test_lst_rate'] : ['set_test_lst_rate', 'register_stage1_test_pool'];
      for (const name of forbidden) {
        const data = Buffer.concat([createHash('sha256').update(`global:${name}`).digest().subarray(0, 8), Buffer.alloc(32)]);
        await rejected(send(new TransactionInstruction({ programId: program.programId, keys: [], data })), 'InstructionFallbackNotFound');
      }
      for (const length of [0, 1, 7]) await rejected(send(new TransactionInstruction({
        programId: program.programId, keys: [], data: Buffer.alloc(length),
      })), 'InstructionMissing');
    });
    it('admits a canonical lineage with a real legacy CAL vault without changing its bytes', async function () {
      const climbs = await program.account.climb.all();
      const existing = climbs.find((x: any) => !x.account.vault.equals(PublicKey.default) && x.account.successorClimb.equals(PublicKey.default));
      if (!existing) { if (process.env.ANCHOR_TEST_FILES) this.skip(); else throw new Error('full legacy suite must create a CAL vault'); }
      const vault = existing.account.vault;
      const before = (await provider.connection.getAccountInfo(vault))!.data;
      const hill = pda('s1v1_hill', Buffer.from(existing.account.canonId));
      await send(program.methods.initHillBond().accounts({ city: city(), climb: existing.publicKey, hill,
        admin: wallet.publicKey, programConfig: config(), systemProgram: SystemProgram.programId }));
      expect((await provider.connection.getAccountInfo(vault))!.data.equals(before)).to.equal(true);
      expect((await hillState(hill)).climb.equals(existing.publicKey)).to.equal(true);
    });
    return;
  }
  it('requires configured assets, admin provenance and a valid fresh exact rate', async () => {
    mint = await createMint(provider.connection, wallet.payer, wallet.publicKey, null, 9);
    source = (await getOrCreateAssociatedTokenAccount(provider.connection, wallet.payer, mint, wallet.publicKey)).address;
    otherSource = (await getOrCreateAssociatedTokenAccount(provider.connection, wallet.payer, mint, other.publicKey)).address;
    await mintTo(provider.connection, wallet.payer, mint, source, wallet.payer, 20_000n * SOL);
    await mintTo(provider.connection, wallet.payer, mint, otherSource, wallet.payer, 10n * SOL);
    const hill = await newHill();
    await rejected(deposit(hill, 1), 'AccountNotInitialized');
    const args = { city: city(), asset: asset(mint), mint, earnings: earnings(mint), programConfig: config(),
      admin: other.publicKey, tokenProgram: TOKEN_PROGRAM_ID, systemProgram: SystemProgram.programId, rent: SYSVAR_RENT_PUBKEY };
    await rejected(send(program.methods.configureAsset(true).accounts(args), [other]), 'Stage1Unauthorized');
    await send(program.methods.configureAsset(false).accounts({ ...args, admin: wallet.publicKey }));
    await rejected(deposit(hill, 1), 'Stage1AdapterDisabled');
    await send(program.methods.configureAsset(true).accounts({ ...args, admin: wallet.publicKey }));
    await rejected(deposit(hill, 1), 'Stage1InvalidRate');
    await rejected(rate(0), 'Stage1InvalidRate');
    await rejected(rate(1, 0), 'Stage1InvalidRate');
    await rate(1, 1, await now() - 61);
    await rejected(deposit(hill, 1), 'Stage1StaleRate');
    await rate(1, 1, await now() + 60);
    await rejected(deposit(hill, 1), 'Stage1StaleRate');
    await rate(1);
  });
  it('never shortens freshness for a backdated admitted observation', async () => {
    await rate(1);
    const admitted = await program.account.stage1AssetConfig.fetch(asset(mint));
    const before = await program.account.stage1CityConfig.fetch(city());
    await rate(2, 1, await now() - 30);
    const current = await program.account.stage1AssetConfig.fetch(asset(mint));
    const deployment = await program.account.stage1CityConfig.fetch(city());
    expect(current.observationAdmitted).to.equal(true);
    expect(current.admittedNumerator.toString()).to.equal('2');
    expect(deployment.rateEpochs[admitted.slot].toString()).to.equal(before.rateEpochs[admitted.slot].addn(1).toString());
    expect(current.lastFreshUntil.toString()).to.equal(admitted.lastFreshUntil.toString());
    expect(deployment.freshUntil[admitted.slot].toString()).to.equal(admitted.lastFreshUntil.toString());
    await rate(1);
  });
  it('preserves admitted freshness and pricing after rejection until the exact expiry', async () => {
    const { token, from } = await testAsset(13n * SOL);
    const freshHill = await newHill(), expiryHill = await newHill();
    const victim = await checked(deposit(freshHill, 6n * SOL, { mint: token, source: from }));
    await checked(deposit(expiryHill, 6n * SOL, { mint: token, source: from }));
    const admitted = await program.account.stage1AssetConfig.fetch(asset(token));
    const before = await program.account.stage1CityConfig.fetch(city()), slot = admitted.slot;
    for (const observed of [await now() - 61, await now() + 60]) {
      await checked(rate(9, 1, observed, token));
      const current = await program.account.stage1AssetConfig.fetch(asset(token));
      const deployment = await program.account.stage1CityConfig.fetch(city());
      expect(deployment.freshUntil[slot].toString()).to.equal(before.freshUntil[slot].toString());
      expect(deployment.rateEpochs[slot].toString()).to.equal(before.rateEpochs[slot].toString());
      expect(current.lastFreshUntil.toString()).to.equal(admitted.lastFreshUntil.toString());
      expect([current.admittedNumerator.toString(), current.admittedDenominator.toString()]).to.deep.equal(['1', '1']);
    }
    const sameToken = await checked(deposit(expiryHill, 1, { mint: token, source: from }));
    expect((await lotState(sameToken)).basisLamports.toString()).to.equal('1');
    await checked(refreshLot(victim));
    await rate(1);
    await checked(deposit(freshHill, 4n * SOL, { bond: true }));
    expect((await hillState(freshHill)).foundingFreshSlots & (1 << slot)).not.to.equal(0);
    await checked(refreshLot(victim, true));
    expect((await lotState(victim)).founding).to.equal(true);
    expect((await lotState(victim)).ownerUnits.toString()).to.equal('0');
    const accounts = await capture(provider.connection, program.programId, [wallet.publicKey, other.publicKey]);
    const expiry = admitted.lastFreshUntil.toNumber();
    expect((await program.account.stage1AssetConfig.fetch(asset(mint))).lastFreshUntil.toNumber()).to.be.greaterThan(expiry);
    await inReplay(accounts, expiry - 1, async () => {
      await deposit(expiryHill, 4n * SOL, { bond: true });
    }, true);
    await inReplay(accounts, expiry, async () => {
      await rejected(deposit(expiryHill, 1, { mint: token, source: from }), 'Stage1StaleRate');
      await rejected(deposit(expiryHill, 4n * SOL, { bond: true }), 'Stage1BelowLine');
      await deposit(expiryHill, 10n * SOL, { bond: true });
    }, true);
  });
  it('counts stale slots as zero and preserves excluded cancellation and owner conversion', async () => {
    const expected = oracle.stale_campaign;
    const { token, from } = await testAsset(100n);
    await rate(1);
    const hill = await newHill();
    await checked(deposit(hill, 6n * SOL));
    const dust = await checked(deposit(hill, 1, { mint: token, source: from }));
    const excluded = await checked(deposit(hill, 10, { mint: token, source: from }));
    const recovered = await checked(deposit(hill, 3, { mint: token, source: from }));
    const beforeExpiry = await capture(provider.connection, program.programId, [wallet.publicKey, other.publicKey]);
    const expiry = (await program.account.stage1AssetConfig.fetch(asset(token))).lastFreshUntil.toNumber();
    let convertedCapture: Capture, convertedLockEnd: number;
    // Expire the admitted window using elapsed-time replay, never rejection.
    await inReplay(beforeExpiry, expiry, async () => {
      await checked(rate(1));
      await checked(rate(9, 1, await now() - 61, token)); // rejection cannot renew an expired quote
      await rejected(deposit(hill, 1, { mint: token, source: from }), 'Stage1StaleRate');
      await checked(deposit(hill, 1));
      const trigger = await checked(deposit(hill, 4n * SOL, { bond: true, owner: other.publicKey, source: otherSource, signers: [other] }));
      const frozen = await hillState(hill), slot = (await program.account.stage1AssetConfig.fetch(asset(token))).slot;
      expect(frozen.foundingCount.toNumber()).to.equal(expected.founding_count);
      expect(frozen.founder.equals((await lotState(trigger)).owner)).to.equal(true);
      expect(frozen.founder.equals((await lotState(excluded)).owner)).to.equal(false);
      expect(frozen.foundingFreshSlots & (1 << slot)).to.equal(0);
      expect(frozen.quotedNumerators[slot].toString()).to.equal('0');
      expect(frozen.quotedDenominators[slot].toString()).to.equal('0');
      await checked(refreshLot(excluded, true));
      expect((await lotState(excluded)).founding).to.equal(false);
      await rejected(notice(excluded, 1), 'Stage1InvalidRequest');
      await rejected(convert(excluded, 13), 'Stage1StaleRate');
      await rejected(ownerAction('cancelPledge', dust, { owner: other.publicKey, destination: otherSource, signers: [other] }), 'ConstraintHasOne');
      const beforeCancel = (await getAccount(provider.connection, from)).amount;
      await checked(ownerAction('cancelPledge', dust, { destination: from }));
      expect(((await getAccount(provider.connection, from)).amount - beforeCancel).toString()).to.equal(expected.cancelled_units);
      await checked(rate(2, 1, undefined, token));
      const beforeFreshCancel = (await getAccount(provider.connection, from)).amount;
      await checked(ownerAction('cancelPledge', recovered, { destination: from }));
      expect(((await getAccount(provider.connection, from)).amount - beforeFreshCancel).toString()).to.equal(expected.fresh_cancelled_units);
      await rejected(harvest(excluded, 1), 'Stage1NotBonded');
      await rejected(notice(excluded, 1), 'Stage1InvalidRequest');
      await rejected(convert(excluded, 13, other.publicKey, [other]), 'ConstraintHasOne');
      await rejected(convert(excluded, 1), 'Stage1InvalidAmount');
      // Intake disabled still permits conversion of principal already in custody.
      await send(program.methods.configureAsset(false).accounts({ city: city(), asset: asset(token), mint: token,
        earnings: earnings(token), programConfig: config(), admin: wallet.publicKey, tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: SystemProgram.programId, rent: SYSVAR_RENT_PUBKEY }));
      const before = (await program.account.stage1CityConfig.fetch(city())).heldBasisLamports.toString();
      const start = await now();
      await checked(convert(excluded, 13));
      const converted = await lotState(excluded);
      expect(converted.converted).to.equal(true);
      expect(converted.founding).to.equal(expected.excluded_founding);
      expect([converted.units.toString(), converted.basisLamports.toString(), converted.ownerUnits.toString()])
        .to.deep.equal([expected.converted_units, expected.converted_basis, expected.owner_reserve]);
      expect(converted.lockWeeks).to.equal(13);
      expect(converted.lockEnd.toNumber()).to.be.within(start + expected.lock_seconds, await now() + expected.lock_seconds);
      expect((await program.account.stage1CityConfig.fetch(city())).heldBasisLamports.toString()).to.equal(before);
      expect((await getAccount(provider.connection, reserve(excluded))).amount.toString()).to.equal(expected.owner_reserve);
      await rejected(convert(excluded, 0), 'Stage1CannotCancel');
      await rejected(ownerAction('cancelPledge', excluded, { destination: from }), 'Stage1CannotCancel');
      await rejected(notice(excluded, 1), 'Stage1Locked');
      const beforeYield = (await getAccount(provider.connection, from)).amount;
      await checked(ownerAction('withdrawPrebond', excluded, { destination: from }));
      expect(((await getAccount(provider.connection, from)).amount - beforeYield).toString()).to.equal(expected.owner_reserve);
      expect((await program.account.stage1AssetConfig.fetch(asset(token))).harvestedUnits.toString()).to.equal(expected.harvested);
      const after = await hillState(hill);
      expect(after.heldBasisLamports.toString()).to.equal(expected.held_basis);
      expect(after.foundingFreshSlots).to.equal(frozen.foundingFreshSlots);
      expect(after.foundingCount.toString()).to.equal(frozen.foundingCount.toString());
      expect(after.quotedNumerators.map(String)).to.deep.equal(frozen.quotedNumerators.map(String));
      expect(after.quotedDenominators.map(String)).to.deep.equal(frozen.quotedDenominators.map(String));
      // Exercise the converted parent -> exiting child -> actual return with
      // ordinary signed transactions, retaining the same captured custody bytes.
      convertedLockEnd = converted.lockEnd.toNumber();
      convertedCapture = await capture(provider.connection, program.programId, [wallet.publicKey, other.publicKey]);
    });
    let request: PublicKey, withNotice: Capture, eligible: number;
    await inReplay(convertedCapture!, convertedLockEnd!, async () => {
      request = await checked(notice(excluded, 10));
      eligible = (await program.account.stage1WithdrawalRequest.fetch(request)).eligibleAt.toNumber();
      withNotice = await capture(provider.connection, program.programId, [wallet.publicKey, other.publicKey]);
    });
    await inReplay(withNotice!, eligible!, async () => {
      await rate(2, 1, undefined, token);
      const child = await checked(begin(excluded, request!));
      expect((await lotState(child)).founding).to.equal(false);
      const beforeReturn = (await getAccount(provider.connection, from, 'processed')).amount;
      await checked(finish(child, request!, { destination: from }));
      expect(((await getAccount(provider.connection, from, 'processed')).amount - beforeReturn).toString()).to.equal(expected.converted_units);
      expect((await hillState(hill)).heldBasisLamports.toString()).to.equal((BigInt(expected.held_basis) - 10n).toString());
    });
  });
  it('rejects an all-stale bond and counts a slot readmitted before bonding', async () => {
    const { token, from } = await testAsset(5n * SOL);
    await rate(1);
    const hill = await newHill();
    const x = await checked(deposit(hill, 4n * SOL, { mint: token, source: from }));
    await checked(deposit(hill, 5n * SOL));
    const beforeExpiry = await capture(provider.connection, program.programId, [wallet.publicKey, other.publicKey]);
    const expiry = Math.max(...await Promise.all([mint, token].map(async t =>
      (await program.account.stage1AssetConfig.fetch(asset(t))).lastFreshUntil.toNumber())));
    let bonded: Capture, bondedExpiry: number;
    await inReplay(beforeExpiry, expiry, async () => {
      await checked(rate(1, 1, await now() - 61, token));
      await checked(rate(1, 1, await now() - 61));
      await rejected(deposit(hill, SOL, { bond: true }), 'Stage1StaleRate');
      expect((await hillState(hill)).bonded).to.equal(false);
      await rate(1);
      await rate(2, 1, undefined, token);
      await rejected(deposit(hill, SOL, { bond: true }), 'Stage1CampaignRefreshRequired');
      await checked(refreshLot(x));
      await checked(deposit(hill, SOL, { bond: true }));
      const frozen = await hillState(hill);
      expect(frozen.foundingCount.toNumber()).to.equal(3);
      bonded = await capture(provider.connection, program.programId, [wallet.publicKey, other.publicKey]);
      bondedExpiry = (await program.account.stage1AssetConfig.fetch(asset(token))).lastFreshUntil.toNumber();
    });
    await inReplay(bonded!, bondedExpiry!, async () => {
      await checked(refreshLot(x, true));
      expect((await lotState(x)).founding).to.equal(true);
      expect((await lotState(x)).ownerUnits.toString()).to.equal((2n * SOL).toString());
      await rejected(ownerAction('cancelPledge', x, { destination: from }), 'Stage1CannotCancel');
    });
  });
  it('rejects short localnet wire instructions without a dispatcher panic', async () => {
    for (const length of [0, 1, 7]) await rejected(send(new TransactionInstruction({
      programId: program.programId, keys: [], data: Buffer.alloc(length),
    })), 'InstructionMissing');
  });
  it('rejects wrong mint, wrong owner and deposit replay without moving funds', async () => {
    const hill = await newHill(), id = ++serial;
    const wrongMint = await createMint(provider.connection, wallet.payer, wallet.publicKey, null, 9);
    const wrongSource = (await getOrCreateAssociatedTokenAccount(provider.connection, wallet.payer, wrongMint, wallet.publicKey)).address;
    await rejected(deposit(hill, 100, { source: wrongSource }), 'ConstraintTokenMint');
    await rejected(deposit(hill, 100, { source: otherSource }), 'ConstraintTokenOwner');
    await rate(1);
    const lot = await deposit(hill, 100, { id });
    const amount = (await getAccount(provider.connection, custody(lot))).amount;
    await rejected(deposit(hill, 100, { id }), 'already in use');
    expect((await getAccount(provider.connection, custody(lot))).amount).to.equal(amount);
    await rejected(ownerAction('cancelPledge', lot, { owner: other.publicKey, destination: otherSource, signers: [other] }), 'ConstraintHasOne');
    await ownerAction('cancelPledge', lot);
    await rejected(deposit(hill, 100, { id }), 'already in use');
  });
  it('requires admin admission and shares one bond across canonical successors', async () => {
    await rejected(newHill({ admin: other.publicKey, signers: [other] }), 'Stage1Unauthorized');
    const hill = await newHill(), old = (await hillState(hill)).climb;
    const prior = await program.account.climb.fetch(old), id = Buffer.from(prior.canonId);
    const profile = createHash('sha256').update(`successor-${++serial}`).digest();
    const commitment = Buffer.alloc(64); commitment[0] = 1; id.copy(commitment, 1);
    commitment.writeUInt16BE(2, 17); profile.copy(commitment, 32);
    const digest = createHash('sha256').update(commitment).digest(), next = pda('climb', digest);
    await send(program.methods.registerRatifiedClimb({ canonId: [...id], canonVersion: 2,
      canonicalProfileHash: [...profile], commitmentHash: [...digest], recordContinuityPolicy: { newRecordBoard: {} },
      name: 'Local successor', vertM: 1000, distanceM: 2000, avgGradientPct: 500,
    }).accounts({ climb: next, climbVersionIndex: pda('climb_version', id, Buffer.from([0, 2])), predecessorClimb: old,
      programConfig: config(), admin: wallet.publicKey, systemProgram: SystemProgram.programId }));
    await rate(1);
    await rejected(deposit(hill, 1), 'Stage1InvalidHill');
    await rejected(send(program.methods.initHillBond().accounts({ city: city(), climb: next, hill,
      admin: wallet.publicKey, programConfig: config(), systemProgram: SystemProgram.programId })), 'already in use');
    const lot = await deposit(hill, 10n * SOL, { climb: next, bond: true });
    expect((await hillState(hill)).bonded).to.equal(true);
    expect((await lotState(lot)).hill.equals(hill)).to.equal(true);
    await rejected(deposit(hill, 1), 'Stage1InvalidHill');
    await deposit(hill, 1, { climb: next });
  });
  it('serializes cancellation before a crossing pledge and rolls back a below-line bond', async () => {
    await rate(1);
    const hill = await newHill(), first = await deposit(hill, 6n * SOL);
    await ownerAction('cancelPledge', first);
    const second = await deposit(hill, 4n * SOL);
    expect((await hillState(hill)).bonded).to.equal(false);
    const count = (await program.account.stage1CityConfig.fetch(city())).heldLots.toString();
    await rejected(deposit(hill, 1, { bond: true }), 'Stage1BelowLine');
    expect((await program.account.stage1CityConfig.fetch(city())).heldLots.toString()).to.equal(count);
    await ownerAction('cancelPledge', second);
  });
  it('atomically bonds escrowed basis, names the triggering Founder and freezes owner yield', async () => {
    await rate(1);
    bondedHill = await newHill();
    founderLot = await deposit(bondedHill, BigInt(oracle.bonding.first_units));
    await rejected(harvest(founderLot, 1), 'Stage1NotBonded');
    await rate(2);
    expect((await hillState(bondedHill)).bonded).to.equal(false);
    await refreshLot(founderLot);
    triggerLot = await deposit(bondedHill, BigInt(oracle.bonding.trigger_units), { bond: true, owner: other.publicKey, source: otherSource, signers: [other] });
    await refreshLot(founderLot, true);
    const hill = await hillState(bondedHill), first = await lotState(founderLot), second = await lotState(triggerLot);
    expect(hill.founder.equals(other.publicKey)).to.equal(true);
    expect(hill.foundingCount.toString()).to.equal('2');
    expect(hill.foundingCutoff.toString()).to.equal(second.sequence.toString());
    expect(first.quoteEpoch.toString()).to.equal(hill.rateEpochs[first.assetSlot].toString());
    expect(first.units.toString()).to.equal(oracle.bonding.first_principal_units);
    expect(second.basisLamports.toString()).to.equal(oracle.bonding.trigger_basis);
    for (const lot of [first, second]) {
      expect(lot.founding).to.equal(true); expect(lot.lockWeeks).to.equal(26);
      expect(lot.lockEnd.toNumber()).to.equal(hill.bondedAt.toNumber() + oracle.bonding.lock_seconds);
    }
    expect(first.prebondUnitsFrozen.toString()).to.equal(oracle.bonding.owner_reserve);
    expect((await getAccount(provider.connection, reserve(founderLot))).amount).to.equal(3n * SOL);
    await rejected(ownerAction('cancelPledge', founderLot), 'Stage1CannotCancel');
    await rejected(notice(founderLot, 1), 'Stage1Locked');
    prebondCapture = await capture(provider.connection, program.programId, [wallet.publicKey, other.publicKey]);
    const before = (await getAccount(provider.connection, source)).amount;
    await ownerAction('withdrawPrebond', founderLot);
    expect((await getAccount(provider.connection, source)).amount - before).to.equal(3n * SOL);
    expect((await program.account.stage1AssetConfig.fetch(asset(mint))).harvestedUnits.toString()).to.equal('0');
  });
  it('serializes concurrently submitted cancellation and threshold crossing without a cancelled founder', async () => {
    await rate(1);
    const hill = await newHill(), first = await deposit(hill, 6n * SOL);
    const [cancelled, bonded] = await Promise.allSettled([
      ownerAction('cancelPledge', first), deposit(hill, 4n * SOL, { bond: true }),
    ]);
    const rejectedBy = (result: PromiseSettledResult<unknown>, name: string) => {
      if (result.status !== 'rejected') throw new Error(`Expected race loser: ${name}`);
      const detail = `${result.reason.message}\n${result.reason.logs?.join('\n')}`;
      const code = program.idl.errors.find((e: any) => e.name === name).code;
      // Preflight can reject the losing attempt; a processed bank error is
      // also accepted, but transport failures never count as race proof.
      expect(detail.includes(name) || result.reason.actual?.InstructionError?.[1]?.Custom === code, detail).to.equal(true);
    };
    const state = await hillState(hill), lot = await lotState(first);
    if (state.bonded) {
      expect(bonded.status).to.equal('fulfilled');
      rejectedBy(cancelled, 'Stage1CannotCancel');
      await refreshLot(first, true);
      expect((await lotState(first)).founding).to.equal(true);
      expect(lot.basisLamports.toString()).to.equal((6n * SOL).toString());
    } else {
      expect(cancelled.status).to.equal('fulfilled');
      rejectedBy(bonded, 'Stage1BelowLine');
      expect(lot.founding).to.equal(false);
      expect(lot.basisLamports.toString()).to.equal('0');
      const next = await deposit(hill, 4n * SOL);
      expect((await hillState(hill)).bonded).to.equal(false);
      await ownerAction('cancelPledge', next);
    }
  });
  it('isolates losses and forbids new deposits and donations from repairing a deficit', async () => {
    await rate(1);
    const before = (await lotState(founderLot)).units.toString();
    healthyLot = await deposit(bondedHill, 100);
    await transfer(provider.connection, wallet.payer, source, custody(founderLot), wallet.payer, 100n);
    await rejected(harvest(founderLot, 1), 'Stage1PrincipalProtected');
    await rate(3, 2);
    await rejected(harvest(founderLot, 1), 'Stage1PrincipalProtected');
    await rejected(harvest(healthyLot, 34), 'Stage1PrincipalProtected');
    await rejected(harvest(healthyLot, 0), 'Stage1InvalidAmount');
    expect(program.idl.instructions.find((x: any) => x.name === 'harvestStage1').accounts.find((x: any) => x.name === 'city').isMut).to.equal(false);
    expect(program.idl.instructions.find((x: any) => x.name === 'harvestStage1').accounts.find((x: any) => x.name === 'hill').isMut).to.equal(false);
    await rejected(harvest(healthyLot, 1, { custody: custody(founderLot) }), 'ConstraintSeeds');
    await harvest(healthyLot, 33);
    expect((await lotState(founderLot)).units.toString()).to.equal(before);
    expect((await lotState(healthyLot)).basisLamports.toString()).to.equal('100');
    expect((await getAccount(provider.connection, earnings(mint))).amount).to.equal(33n);
    const hill = await newHill(), lot = await deposit(hill, 1);
    await ownerAction('cancelPledge', lot);
  });
  it('uses running basis caps through appreciation and losses', async () => {
    await rate(1);
    await rejected(deposit(bondedHill, 501n * SOL), 'Stage1ExposureCap');
    const before = (await program.account.stage1CityConfig.fetch(city())).heldBasisLamports;
    await rate(200);
    const lot = await deposit(bondedHill, 1);
    expect((await program.account.stage1CityConfig.fetch(city())).heldBasisLamports.sub(before).toString()).to.equal('200');
    await rate(1);
    expect((await program.account.stage1CityConfig.fetch(city())).heldBasisLamports.sub(before).toString()).to.equal('200');
    const alienMint = await createMint(provider.connection, wallet.payer, wallet.publicKey, null, 9);
    await send(program.methods.configureAsset(true).accounts({ city: city(), asset: asset(alienMint), mint: alienMint,
      earnings: earnings(alienMint), programConfig: config(), admin: wallet.publicKey, tokenProgram: TOKEN_PROGRAM_ID,
      systemProgram: SystemProgram.programId, rent: SYSVAR_RENT_PUBKEY }));
    await rejected(harvest(lot, 1, { asset: asset(alienMint) }), 'ConstraintSeeds');
  });
  it('charges the cumulative one-tenth fee once despite one-unit harvest fragmentation', async () => {
    await rate(3);
    const before = await program.account.stage1AssetConfig.fetch(asset(mint));
    for (let i = 0; i < 10; i++) {
      await harvest(healthyLot, 1);
    }
    const after = await program.account.stage1AssetConfig.fetch(asset(mint));
    expect(after.harvestedUnits.sub(before.harvestedUnits).toString()).to.equal('10');
    expect(after.feesAssessed.sub(before.feesAssessed).toString()).to.equal('1');
    await rate(1);
  });
  it('matches elapsed dates for all later locks and enforces one cancellable notice', async () => {
    for (const lock of [0, 13, 26, 52]) {
      const lot = await deposit(bondedHill, 100, { lock });
      const state = await lotState(lot);
      expect(state.founding).to.equal(false);
      expect(state.lockEnd.toNumber()).to.equal(state.depositedAt.toNumber() + lock * W);
      if (lock) { await rejected(notice(lot, 1), 'Stage1Locked'); continue; }
      await rejected(notice(lot, 40, ++serial, { owner: other.publicKey, signers: [other] }), 'ConstraintHasOne');
      const request = await notice(lot, 40), req = await program.account.stage1WithdrawalRequest.fetch(request);
      expect(req.eligibleAt.toNumber()).to.equal(req.noticeAt.toNumber() + 4 * W);
      await rejected(notice(lot, 1), 'Stage1InvalidRequest');
      await rejected(begin(lot, request), 'Stage1NoticeIncomplete');
      await rejected(begin(lot, request, { owner: other.publicKey, signers: [other] }), 'ConstraintHasOne');
      await rejected(send(program.methods.cancelWithdrawal().accounts({ lot, request, owner: other.publicKey }), [other]), 'ConstraintHasOne');
      await send(program.methods.cancelWithdrawal().accounts({ lot, request, owner: wallet.publicKey }));
      await rejected(begin(lot, request), 'Stage1InvalidRequest');
      expect((await program.account.stage1WithdrawalRequest.fetch(request)).status).to.equal(3);
    }
  });
  it('simulates identical custody bytes at the exact founding lock boundary on a local validator', async () => {
    const state = await lotState(founderLot), expiry = state.lockEnd.toNumber();
    const accounts = await capture(provider.connection, program.programId, [wallet.publicKey, other.publicKey]);
    await inReplay(accounts, expiry - 1, async () => { await rejected(notice(founderLot, 100), 'Stage1Locked'); }, true);
    await inReplay(accounts, expiry, async () => {
      await notice(founderLot, 100); // Successful simulation, not a created request.
    }, true);
  });
  it('keeps original pre-bond earnings collectible after a full principal exit', async () => {
    const state = await lotState(founderLot);
    let withNotice: Capture, request: PublicKey, eligible: number;
    await inReplay(prebondCapture, state.lockEnd.toNumber(), async () => {
      request = await notice(founderLot, BigInt(state.basisLamports.toString()));
      eligible = (await program.account.stage1WithdrawalRequest.fetch(request)).eligibleAt.toNumber();
      withNotice = await capture(provider.connection, program.programId, [wallet.publicKey, other.publicKey]);
    });
    await inReplay(withNotice!, eligible!, async () => {
      await rate(2);
      const child = await begin(founderLot, request!);
      await finish(child, request!);
      expect((await lotState(founderLot)).basisLamports.toString()).to.equal('0');
      expect((await lotState(founderLot)).ownerUnits.toString()).to.equal(oracle.bonding.owner_reserve);
      const before = (await getAccount(provider.connection, source, 'processed')).amount;
      await ownerAction('withdrawPrebond', founderLot);
      expect((await getAccount(provider.connection, source, 'processed')).amount - before).to.equal(BigInt(oracle.bonding.owner_reserve));
      expect((await lotState(founderLot)).ownerUnits.toString()).to.equal('0');
    });
  });
  for (const vector of vectors) it(`matches oracle exit vector: ${vector.name}`, async () => {
    await rate(...vector.deposit_rate as [number, number]);
    const lot = await deposit(bondedHill, BigInt(vector.units), { lock: vector.lock_weeks });
    const state = await lotState(lot);
    expect(state.basisLamports.toString()).to.equal(vector.original_basis);
    const depositedBacking = BigInt(vector.units) * BigInt(vector.deposit_rate[0]) / BigInt(vector.deposit_rate[1]);
    expect(state.observedLossLamports.toString()).to.equal((BigInt(vector.original_basis) - depositedBacking).toString());
    expect(state.lockEnd.sub(state.depositedAt).toNumber()).to.equal(vector.lock_seconds);
    const original = await capture(provider.connection, program.programId, [wallet.publicKey, other.publicKey]);
    let withNotice: Capture, request: PublicKey, eligible: number;
    await inReplay(original, state.lockEnd.toNumber(), async () => {
      request = await notice(lot, BigInt(vector.requested_basis));
      const req = await program.account.stage1WithdrawalRequest.fetch(request);
      eligible = req.eligibleAt.toNumber();
      expect(eligible - req.noticeAt.toNumber()).to.equal(vector.notice_seconds);
      withNotice = await capture(provider.connection, program.programId, [wallet.publicKey, other.publicKey]);
    });
    if (vector.name === 'unchanged') await inReplay(withNotice!, eligible! - 1, async () => {
      await rejected(begin(lot, request!), 'Stage1NoticeIncomplete');
    }, true);
    await inReplay(withNotice!, eligible!, async () => {
      await rate(...vector.exit_rate as [number, number]);
      const beforeLot = (await provider.connection.getAccountInfo(lot, 'processed'))!.data;
      const beforeAsset = await program.account.stage1AssetConfig.fetch(asset(mint));
      const beforeAssetBytes = (await provider.connection.getAccountInfo(asset(mint), 'processed'))!.data;
      const beforeEarnings = (await getAccount(provider.connection, earnings(mint), 'processed')).amount;
      const beforeCount = (await program.account.stage1CityConfig.fetch(city())).heldLots;
      if (vector.reject) {
        await rejected(begin(lot, request!), 'Stage1ExitTooSmall');
        expect((await provider.connection.getAccountInfo(lot, 'processed'))!.data.equals(beforeLot)).to.equal(true);
        expect((await provider.connection.getAccountInfo(asset(mint), 'processed'))!.data.equals(beforeAssetBytes)).to.equal(true);
        expect((await getAccount(provider.connection, earnings(mint), 'processed')).amount).to.equal(beforeEarnings);
        return;
      }
      const child = pda('s1v1_exit', request!.toBuffer());
      // Pre-funding a deterministic token PDA must not strand this owner's exit.
      const prefund = await provider.connection.getMinimumBalanceForRentExemption(0);
      await send(SystemProgram.transfer({ fromPubkey: wallet.publicKey, toPubkey: custody(child), lamports: prefund }));
      await send(SystemProgram.transfer({ fromPubkey: wallet.publicKey, toPubkey: reserve(child), lamports: prefund }));
      await begin(lot, request!);
      const parent = await lotState(lot), exiting = await lotState(child);
      expect(parent.basisLamports.toString()).to.equal(vector.remaining_basis);
      expect(parent.units.toString()).to.equal(vector.remaining_units);
      expect(exiting.units.toString()).to.equal(vector.exit_units);
      expect(exiting.ownerUnits.toString()).to.equal(vector.owner_dust);
      const afterBegin = await program.account.stage1AssetConfig.fetch(asset(mint));
      expect(afterBegin.harvestedUnits.sub(beforeAsset.harvestedUnits).toString()).to.equal(vector.harvest_at_begin);
      expect((await program.account.stage1CityConfig.fetch(city())).heldLots.sub(beforeCount).toNumber())
        .to.equal(BigInt(vector.remaining_basis) > 0n ? 1 : 0);
      await rejected(ownerAction('withdrawPrebond', child), 'Stage1CannotCancel');
      await rejected(finish(child, request!, { owner: other.publicKey, destination: otherSource, signers: [other] }), 'ConstraintHasOne');
      const differentRequest = (await program.account.stage1WithdrawalRequest.all()).find((x: any) => !x.publicKey.equals(request));
      if (differentRequest) await rejected(finish(child, differentRequest.publicKey), 'Stage1InvalidRequest');
      await rate(...vector.return_rate as [number, number]);
      const beforeReturn = (await getAccount(provider.connection, source, 'processed')).amount;
      await finish(child, request!);
      expect((await getAccount(provider.connection, source, 'processed')).amount - beforeReturn).to.equal(BigInt(vector.returned));
      const after = await program.account.stage1AssetConfig.fetch(asset(mint));
      expect(after.harvestedUnits.sub(beforeAsset.harvestedUnits).toString()).to.equal(vector.harvested);
      expect(after.feesAssessed.toString()).to.equal(after.harvestedUnits.divn(10).toString());
      expect((await getAccount(provider.connection, earnings(mint), 'processed')).amount - beforeEarnings).to.equal(BigInt(vector.harvested));
      expect((await lotState(child)).basisLamports.toString()).to.equal('0');
      const returnRateValue = BigInt(vector.returned)
        * BigInt(vector.return_rate[0]) / BigInt(vector.return_rate[1]);
      const principalLoss = BigInt(vector.requested_basis) > returnRateValue
        ? BigInt(vector.requested_basis) - returnRateValue : 0n;
      expect((await lotState(child)).realizedLossLamports.toString()).to.equal(principalLoss.toString());
      expect((await lotState(lot)).basisLamports.toString()).to.equal(vector.remaining_basis);
      await rejected(finish(child, request!), 'Stage1InvalidRequest');
      expect((await hillState(bondedHill)).bonded).to.equal(true);
    });
  });
  it('returns all units without harvest only after seven continuous stale days and a full mature notice', async () => {
    await rate(1);
    const lot = await deposit(bondedHill, 100), request = await notice(lot, 100);
    const req = await program.account.stage1WithdrawalRequest.fetch(request);
    const base = await capture(provider.connection, program.programId, [wallet.publicKey, other.publicKey]);
    let stale: Capture, escape: number;
    await inReplay(base, req.eligibleAt.toNumber(), async () => {
      await rate(2);
      // Disable intake; held owners retain the same exit rights.
      await send(program.methods.configureAsset(false).accounts({ city: city(), asset: asset(mint), mint,
        earnings: earnings(mint), programConfig: config(), admin: wallet.publicKey, tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: SystemProgram.programId, rent: SYSVAR_RENT_PUBKEY }));
      const admitted = await program.account.stage1AssetConfig.fetch(asset(mint));
      escape = admitted.lastFreshUntil.toNumber() + W;
      await rate(9, 1, await now() - 61); // invalid observations cannot reset that timer
      expect((await program.account.stage1AssetConfig.fetch(asset(mint))).lastFreshUntil.toString()).to.equal(admitted.lastFreshUntil.toString());
      stale = await capture(provider.connection, program.programId, [wallet.publicKey, other.publicKey]);
    });
    await inReplay(stale!, escape! - 1, async () => { await rejected(begin(lot, request), 'Stage1StaleRate'); }, true);
    await inReplay(stale!, escape!, async () => {
      await rejected(harvest(lot, 1), 'Stage1StaleRate');
      const before = (await getAccount(provider.connection, source, 'processed')).amount;
      const earningsBefore = (await getAccount(provider.connection, earnings(mint), 'processed')).amount;
      const basisBefore = (await program.account.stage1CityConfig.fetch(city())).heldBasisLamports;
      const child = await begin(lot, request);
      expect((await program.account.stage1CityConfig.fetch(city())).heldBasisLamports.eq(basisBefore)).to.equal(true);
      await finish(child, request);
      expect((await getAccount(provider.connection, source, 'processed')).amount - before).to.equal(BigInt(oracle.stale_exit.returned));
      expect((await getAccount(provider.connection, earnings(mint), 'processed')).amount).to.equal(earningsBefore);
      expect((await lotState(child)).realizedLossLamports).to.equal(null);
      expect(basisBefore.sub((await program.account.stage1CityConfig.fetch(city())).heldBasisLamports).toString()).to.equal(oracle.stale_exit.released_basis);
    });
  });
  it('does not expand partial stale notice, and a fresh readmission resets escape for an exiting child', async () => {
    await rate(1);
    const lot = await deposit(bondedHill, 100), request = await notice(lot, 50);
    const req = await program.account.stage1WithdrawalRequest.fetch(request);
    const base = await capture(provider.connection, program.programId, [wallet.publicKey, other.publicKey]);
    let child: PublicKey, exiting: Capture, escape: number;
    await inReplay(base, req.eligibleAt.toNumber(), async () => {
      await rejected(begin(lot, request), 'Stage1StalePartialExit');
      await rate(2);
      child = await begin(lot, request);
      escape = (await program.account.stage1AssetConfig.fetch(asset(mint))).lastFreshUntil.toNumber() + W;
      exiting = await capture(provider.connection, program.programId, [wallet.publicKey, other.publicKey]);
    });
    await inReplay(exiting!, escape! - 1, async () => { await rejected(finish(child!, request), 'Stage1StaleRate'); }, true);
    await inReplay(exiting!, escape!, async () => {
      const before = (await getAccount(provider.connection, source, 'processed')).amount;
      await finish(child!, request);
      expect((await getAccount(provider.connection, source, 'processed')).amount - before).to.equal(25n);
      expect((await lotState(lot)).basisLamports.toString()).to.equal('50');
      expect((await lotState(child!)).realizedLossLamports).to.equal(null);
    });
  });
  it('keeps intake and exact bonding available after 200 dust lots and repricing', async () => {
    await rate(1);
    const hill = await newHill(), lots: PublicKey[] = [];
    for (let i = 0; i < 200; i++) {
      if (i % 25 === 0) await rate(1);
      lots.push(await deposit(hill, 1));
    }
    await rate(1, 2);
    await rejected(deposit(hill, 1), 'Stage1CampaignRefreshRequired');
    // Unrelated admission stays available despite the campaign's pending work.
    const unrelated = await newHill();
    await deposit(unrelated, 2);
    for (let i = 0; i < lots.length; i++) {
      if (i % 25 === 0) await rate(1, 2);
      await refreshLot(lots[i]);
    }
    await refreshLot(lots[0]); // cannot double-count a refreshed lot
    const slot = (await program.account.stage1AssetConfig.fetch(asset(mint))).slot;
    expect((await hillState(hill)).quotedCount[slot].toNumber()).to.equal(200);
    expect((await hillState(hill)).quotedBacking[slot].toString()).to.equal('0');
    const near = await deposit(hill, 19_999_999_998n);
    expect((await hillState(hill)).bonded).to.equal(false);
    const trigger = await deposit(hill, 2, { bond: true });
    const state = await hillState(hill);
    expect(state.bonded).to.equal(true);
    expect(state.foundingCount.toNumber()).to.equal(202);
    expect(state.foundingCutoff.toString()).to.equal((await lotState(trigger)).sequence.toString());
    await rate(1, 3); // founding materialization must still use the frozen 1/2 rate
    await refreshLot(lots[0], true);
    expect((await lotState(lots[0])).units.toString()).to.equal('1');
    expect((await lotState(lots[0])).observedLossLamports.toString()).to.equal('1');
    await rejected(refreshLot(near), 'Stage1CannotCancel');
    await deposit(hill, 3); // post-bond intake needs no campaign refresh
    await deposit(await newHill(), 3);
    await rate(1);
  });
  it('guardian pause blocks every intake path but preserves cancellation and a full owner exit', async () => {
    const guardian = Keypair.generate();
    const adminAccounts = { city: city(), programConfig: config(), admin: wallet.publicKey };
    await send(program.methods.setStage1Guardian(guardian.publicKey).accounts(adminAccounts));
    await rate(1);
    const campaign = await newHill(), cancellable = await deposit(campaign, 100);
    const bonded = await newHill(); await deposit(bonded, 10n * SOL, { bond: true });
    const exiting = await deposit(bonded, 100, { lock: 0 });
    await send(program.methods.pauseStage1Intake().accounts({ city: city(), guardian: guardian.publicKey }), [guardian]);
    await send(program.methods.pauseStage1Settlement().accounts({ city: city(), guardian: guardian.publicKey }), [guardian]);
    await rejected(deposit(campaign, 1), 'Stage1IntakePaused');
    await rejected(deposit(campaign, 10n * SOL, { bond: true }), 'Stage1IntakePaused');
    await rejected(deposit(bonded, 1), 'Stage1IntakePaused');
    await rejected(convert(cancellable, 0), 'Stage1IntakePaused');
    await send(program.methods.resumeStage1Intake().accounts({ ...adminAccounts, admin: guardian.publicKey }), [guardian]);
    expect((await program.account.stage1CityConfig.fetch(city())).intakePaused).to.equal(false);
    await send(program.methods.pauseStage1Intake().accounts({ city: city(), guardian: guardian.publicKey }), [guardian]);
    await rejected(send(program.methods.setStage1Guardian(other.publicKey).accounts({ ...adminAccounts, admin: guardian.publicKey }), [guardian]), 'Stage1Unauthorized');
    const before = (await getAccount(provider.connection, source)).amount;
    await ownerAction('cancelPledge', cancellable);
    expect((await getAccount(provider.connection, source)).amount - before).to.equal(100n);
    const cancelled = await notice(exiting, 100);
    await send(program.methods.cancelWithdrawal().accounts({ lot: exiting, request: cancelled, owner: wallet.publicKey }));
    const request = await notice(exiting, 100);
    const eligible = (await program.account.stage1WithdrawalRequest.fetch(request)).eligibleAt.toNumber();
    const captured = await capture(provider.connection, program.programId, [wallet.publicKey, other.publicKey]);
    await inReplay(captured, eligible + 2, async () => {
      expect((await program.account.stage1CityConfig.fetch(city())).intakePaused).to.equal(true);
      expect((await program.account.stage1CityConfig.fetch(city())).settlementPaused).to.equal(true);
      await rate(1);
      const child = await begin(exiting, request);
      const before = (await getAccount(provider.connection, source)).amount;
      await rejected(finish(child, request, { destination: otherSource }), 'ConstraintTokenOwner');
      await finish(child, request);
      expect((await getAccount(provider.connection, source)).amount - before).to.equal(100n);
    });
    await send(program.methods.setStage1Guardian(other.publicKey).accounts(adminAccounts));
    expect((await program.account.stage1CityConfig.fetch(city())).intakePaused).to.equal(true);
    await rejected(send(program.methods.pauseStage1Intake().accounts({ city: city(), guardian: guardian.publicKey }), [guardian]), 'Stage1Unauthorized');
    await send(program.methods.resumeStage1Intake().accounts(adminAccounts));
    await rate(1); await deposit(campaign, 1);
  });
  it('enforces per-token and deployment caps on the normal validator, retaining exit basis until return', async () => {
    const tokens: PublicKey[] = [mint];
    let finalLot: PublicKey = founderLot, finalSource = source, finalMint = mint;
    for (let group = 0; group < 3; group++) {
      let token = mint, from = source;
      if (group) {
        token = await createMint(provider.connection, wallet.payer, wallet.publicKey, null, 9);
        from = (await getOrCreateAssociatedTokenAccount(provider.connection, wallet.payer, token, wallet.publicKey)).address;
        await mintTo(provider.connection, wallet.payer, token, from, wallet.payer, 3000n * SOL);
        await send(program.methods.configureAsset(true).accounts({ city: city(), asset: asset(token), mint: token,
          earnings: earnings(token), programConfig: config(), admin: wallet.publicKey, tokenProgram: TOKEN_PROGRAM_ID,
          systemProgram: SystemProgram.programId, rent: SYSVAR_RENT_PUBKEY }));
        tokens.push(token);
      }
      await rate(1, 1, undefined, token);
      while (true) {
        const cityState = await program.account.stage1CityConfig.fetch(city());
        const held = await program.account.stage1AssetConfig.fetch(asset(token));
        const capacity = [2000n * SOL - BigInt(held.heldBasisLamports.toString()),
          5000n * SOL - BigInt(cityState.heldBasisLamports.toString()), 500n * SOL].reduce((a, b) => a < b ? a : b);
        if (!capacity) break;
        const lot = await deposit(await newHill(), capacity, { mint: token, source: from });
        if (capacity >= 10n * SOL) { finalLot = lot; finalSource = from; finalMint = token; }
      }
      await rejected(deposit(await newHill(), 1, { mint: token, source: from }), 'Stage1ExposureCap');
    }
    expect((await program.account.stage1CityConfig.fetch(city())).heldBasisLamports.toString()).to.equal((5000n * SOL).toString());
    const state = await lotState(finalLot), basis = BigInt(state.basisLamports.toString());
    const full = await capture(provider.connection, program.programId, [wallet.publicKey, other.publicKey]);
    let withNotice: Capture, request: PublicKey, eligible: number;
    await inReplay(full, state.lockEnd.toNumber(), async () => {
      request = await notice(finalLot, basis);
      eligible = (await program.account.stage1WithdrawalRequest.fetch(request)).eligibleAt.toNumber();
      withNotice = await capture(provider.connection, program.programId, [wallet.publicKey, other.publicKey]);
    });
    await inReplay(withNotice!, eligible!, async () => {
      await rate(1, 1, undefined, finalMint);
      const child = await begin(finalLot, request!);
      expect((await program.account.stage1CityConfig.fetch(city())).heldBasisLamports.toString()).to.equal((5000n * SOL).toString());
      const hill = await newHill();
      await rejected(deposit(hill, 1, { mint: finalMint, source: finalSource }), 'Stage1ExposureCap');
      await finish(child, request!, { destination: finalSource });
      expect((await program.account.stage1CityConfig.fetch(city())).heldBasisLamports.toString()).to.equal((5000n * SOL - basis).toString());
      await deposit(hill, 1, { mint: finalMint, source: finalSource });
    });
  });
});
