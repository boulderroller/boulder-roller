import { fundedSweep } from './helpers/stage1_funding.js';
import * as anchor from '@coral-xyz/anchor';
import BN from 'bn.js';
import { expect } from 'chai';
import { createHash } from 'crypto';
import { readFileSync } from 'fs';
import { PublicKey, Keypair, SystemProgram, SYSVAR_RENT_PUBKEY, SYSVAR_CLOCK_PUBKEY,
  ComputeBudgetProgram, TransactionMessage, VersionedTransaction } from '@solana/web3.js';
import { TOKEN_PROGRAM_ID, getAccount } from '@solana/spl-token';
import { capture, replay, Capture, pause } from './helpers/stage1_replay.js';

// Retained provider bytes are REAL read-only mainnet snapshots. Wallet LST
// balances, byte faults, epoch transitions and all transactions below are LOCAL
// SIMULATIONS. They are never evidence of provider behavior across real epochs.
const enabled = process.env.STAGE1_LOCALNET === '1' || process.env.STAGE1_DEPLOYABLE === '1';
const initialProvider = anchor.AnchorProvider.env();
anchor.setProvider(initialProvider);
const original: any = anchor.workspace.BoulderRollers;
const wallet = initialProvider.wallet as anchor.Wallet;
let provider = initialProvider, program: any = original;
const EPOCH = 1057, AT = 1791938000, WEEK = 604800;
const bn = (v: any) => new BN(String(v));
const pda = (seed: string, ...parts: Buffer[]) => PublicKey.findProgramAddressSync([Buffer.from(seed), ...parts], program.programId)[0];
const city = () => pda('s1v1_city'), config = () => pda('program_config');
const asset = (mint: PublicKey) => pda('s1v1_asset', mint.toBuffer());
const custody = (lot: PublicKey) => pda('s1v1_custody', lot.toBuffer());
const reserve = (lot: PublicKey) => pda('s1v1_owner', lot.toBuffer());
const earnings = (mint: PublicKey) => pda('s1v1_earnings', mint.toBuffer());
const fixtures = new URL('./fixtures/stage1_providers/', import.meta.url);
const vectors = JSON.parse(readFileSync(new URL('./fixtures/stage1_provider_vectors.json', import.meta.url), 'utf8'));
const definitions = [
  ['jito-pool', 'jito-mint', '10650132353883915', '8153209489021421'],
  ['msol-state', 'msol-mint', '2254985557764365', '1596971612132375'],
  ['jup-pool', 'jup-mint', '5194388907066853', '4277554095630348'],
];
const tokens = definitions.map(([stateName, mintName, n, d]) => {
  const state = JSON.parse(readFileSync(new URL(`${stateName}.json`, fixtures), 'utf8'));
  const mint = JSON.parse(readFileSync(new URL(`${mintName}.json`, fixtures), 'utf8'));
  return { state, mint, key: new PublicKey(mint.pubkey), provider: new PublicKey(state.pubkey),
    source: Keypair.generate().publicKey, n: BigInt(n), d: BigInt(d) };
});
let serial = 500000, txSerial = 0;
let simulateTransactions = false;
let baseline: Capture, campaign: Capture;
let hill: PublicKey, xLot: PublicKey;
const clock = async () => (await provider.connection.getAccountInfo(SYSVAR_CLOCK_PUBKEY, 'processed'))!.data;
const now = async () => Number((await clock()).readBigInt64LE(32));
const epoch = async () => Number((await clock()).readBigUInt64LE(16));
const pair = (t: typeof tokens[number]) => [t.provider, t.key].map(pubkey => ({ pubkey, isSigner: false, isWritable: false }));
const state = (t: typeof tokens[number]) => program.account.stage1AssetConfig.fetch(asset(t.key));
const unitsFor = (lamports: bigint, t: typeof tokens[number]) => lamports * t.d / t.n;

async function send(builder: any, payer = wallet.payer) {
  const ix = builder.instruction ? await builder.instruction() : builder;
  const latest = await provider.connection.getLatestBlockhash(simulateTransactions ? 'finalized' : 'processed');
  const tx = new VersionedTransaction(new TransactionMessage({ payerKey: payer.publicKey, recentBlockhash: latest.blockhash,
    instructions: [ComputeBudgetProgram.setComputeUnitLimit({ units: 1400000 }),
      ComputeBudgetProgram.setComputeUnitPrice({ microLamports: ++txSerial }),
      ...await fundedSweep(program, provider, payer.publicKey, ix)] }).compileToLegacyMessage());
  tx.sign([payer]);
  if (simulateTransactions) {
    const result = await provider.connection.simulateTransaction(tx, { sigVerify: true, commitment: 'finalized' });
    if (result.value.err) throw new Error(`Local exact-clock simulation: ${JSON.stringify(result.value.err)}\n${result.value.logs?.join('\n')}`);
    return;
  }
  const signature = await provider.connection.sendRawTransaction(tx.serialize(), { preflightCommitment: 'processed' });
  const confirmed = await provider.connection.confirmTransaction({...latest, signature}, 'processed');
  expect(confirmed.value.err, signature).to.equal(null);
}
async function rejected(action: Promise<any>, reason: string) {
  try { await action; } catch (e: any) {
    const detail = `${e.message}\n${e.logs?.join('\n')}`;
    if (!detail.includes(reason)) throw new Error(`Wanted ${reason}; got ${detail}`);
    return;
  }
  throw new Error(`Expected ${reason}`);
}
function refresh(t: typeof tokens[number], supplied = t.provider) {
  return program.methods.refreshStage1Rate().accounts({ city: city(), asset: asset(t.key), provider: supplied, mint: t.key });
}
function outage(t: typeof tokens[number], supplied = t.provider) {
  return program.methods.recordStage1ProviderOutage().accounts({ city: city(), asset: asset(t.key), provider: supplied, mint: t.key });
}
function configure(t: typeof tokens[number], value: boolean) {
  return program.methods.configureAsset(value).accounts({ city: city(), asset: asset(t.key), mint: t.key,
    earnings: earnings(t.key), programConfig: config(), admin: wallet.publicKey, tokenProgram: TOKEN_PROGRAM_ID,
    systemProgram: SystemProgram.programId, rent: SYSVAR_RENT_PUBKEY }).remainingAccounts(pair(t));
}
async function saved(): Promise<Capture> {
  return capture(provider.connection, program.programId, [wallet.publicKey, ...tokens.map(t => t.provider)]);
}
function clone(accounts: Capture): Capture {
  return new Map([...accounts].map(([key, value]) => [key, { ...value, data: Buffer.from(value.data) }]));
}
function changed(accounts: Capture, token: number, offset: number, value: bigint, width = 8) {
  const copy = clone(accounts), data = copy.get(tokens[token].provider.toBase58())!.data;
  if (width === 1) data[offset] = Number(value); else data.writeBigUInt64LE(value, offset);
  return copy;
}
function updated(accounts: Capture, value: number) {
  return changed(changed(accounts, 0, 274, BigInt(value)), 2, 274, BigInt(value));
}
function excessMintSupply(accounts: Capture, index = 0) {
  const copy = clone(accounts);
  copy.get(tokens[index].key.toBase58())!.data.writeBigUInt64LE(tokens[index].d * 2n, 36);
  return copy;
}
function harvestLot(target: PublicKey, lot: PublicKey, index = 0) {
  const t = tokens[index];
  return program.methods.harvestStage1(bn(1)).accounts({ city: city(), hill: target, lot,
    asset: asset(t.key), custody: custody(lot), ownerReserve: reserve(lot), earnings: earnings(t.key),
    tokenProgram: TOKEN_PROGRAM_ID }).remainingAccounts(pair(t));
}
async function unchangedAfterRejection(action: Promise<any>, keys: PublicKey[], before: Buffer[], reason = 'Stage1InvalidProvider') {
  await rejected(action, reason);
  for (const [i, key] of keys.entries()) {
    expect((await provider.connection.getAccountInfo(key))!.data.equals(before[i]), key.toBase58()).to.equal(true);
  }
}
async function scenario(accounts: Capture, atEpoch: number, at: number, work: () => Promise<void>, exact = false) {
  const runtime = await replay(accounts, at, exact, atEpoch);
  try {
    provider = new anchor.AnchorProvider(runtime.connection, wallet, { commitment: 'processed', preflightCommitment: 'processed' });
    program = new anchor.Program(original.idl, original.programId, provider);
    simulateTransactions = exact;
    expect(await epoch()).to.equal(atEpoch);
    if (exact) expect(await now()).to.equal(at);
    await work();
    if (exact) expect(await now()).to.equal(at);
  } finally { await runtime.stop(); provider = initialProvider; program = original; simulateTransactions = false; }
}
async function newHill() {
  const hash = (s: string) => createHash('sha256').update(s).digest();
  const id = hash(`provider-hill-${++serial}`).subarray(0, 16), profile = hash(`provider-profile-${serial}`);
  const commitment = Buffer.alloc(64); commitment[0] = 1; id.copy(commitment, 1); commitment.writeUInt16BE(1, 17); profile.copy(commitment, 32);
  const realDigest = createHash('sha256').update(commitment).digest();
  const climb = pda('climb', realDigest);
  await send(program.methods.registerRatifiedClimb({ canonId: [...id], canonVersion: 1, canonicalProfileHash: [...profile],
    commitmentHash: [...realDigest], recordContinuityPolicy: { newRecordBoard: {} }, name: 'Local adapter hill',
    vertM: 1000, distanceM: 2000, avgGradientPct: 500 }).accounts({ climb, climbVersionIndex: pda('climb_version', id, Buffer.from([0, 1])),
    predecessorClimb: null, programConfig: config(), admin: wallet.publicKey, systemProgram: SystemProgram.programId }));
  const result = pda('s1v1_hill', id);
  await send(program.methods.initHillBond().accounts({ city: city(), climb, hill: result, admin: wallet.publicKey,
    programConfig: config(), systemProgram: SystemProgram.programId }));
  return result;
}
async function deposit(target: PublicKey, index: number, units: bigint, indices: number[], bond = false) {
  const t = tokens[index], id = ++serial, encoded = bn(id).toArrayLike(Buffer, 'le', 8);
  const lot = pda('s1v1_lot', wallet.publicKey.toBuffer(), encoded);
  const h = await program.account.stage1HillBond.fetch(target);
  const remaining = h.bonded ? pair(t) : indices.flatMap(i => [
    { pubkey: asset(tokens[i].key), isSigner: false, isWritable: true }, ...pair(tokens[i])]);
  await send(program.methods[bond ? 'bond' : 'pledge'](bn(id), bn(units), 0).accounts({ city: city(), hillAccount: { hill: target },
    climb: h.climb, asset: asset(t.key), mint: t.key, lot, custody: custody(lot), ownerReserve: reserve(lot), source: t.source,
    owner: wallet.publicKey, tokenProgram: TOKEN_PROGRAM_ID, systemProgram: SystemProgram.programId, rent: SYSVAR_RENT_PUBKEY }).remainingAccounts(remaining));
  return lot;
}

type ExitFixture = { token: number; hill: PublicKey; lot: PublicKey; request: PublicKey;
  child: PublicKey; units: bigint; eligible: number; accounts: Capture };
async function exitFixture(index: number): Promise<ExitFixture> {
  let result: ExitFixture;
  await scenario(baseline, EPOCH, AT, async () => {
    const t = tokens[index], target = await newHill();
    await deposit(target, index, unitsFor(10000000000n, t) + 2n, [index], true);
    const lot = await deposit(target, index, unitsFor(1000000000n, t), [index]);
    const l = await program.account.stage1PledgeLot.fetch(lot), id = ++serial;
    const request = pda('s1v1_request', lot.toBuffer(), bn(id).toArrayLike(Buffer, 'le', 8));
    await send(program.methods.requestWithdrawal(bn(id), l.basisLamports).accounts({ city: city(), hill: target,
      lot, request, owner: wallet.publicKey, systemProgram: SystemProgram.programId }));
    result = { token: index, hill: target, lot, request, child: pda('s1v1_exit', request.toBuffer()),
      units: BigInt(l.units.toString()), eligible: (await program.account.stage1WithdrawalRequest.fetch(request)).eligibleAt.toNumber(), accounts: await saved() };
  });
  return result!;
}
function beginExit(e: ExitFixture, providerKey = tokens[e.token].provider) {
  const t = tokens[e.token];
  return program.methods.beginWithdrawal().accounts({ city: city(), hillAccount: { hill: e.hill }, lot: e.lot,
    request: e.request, mint: t.key, asset: asset(t.key), custody: custody(e.lot), ownerReserve: reserve(e.lot),
    earnings: earnings(t.key), exitLot: e.child, exitCustody: custody(e.child), exitReserve: reserve(e.child),
    owner: wallet.publicKey, tokenProgram: TOKEN_PROGRAM_ID, systemProgram: SystemProgram.programId,
    rent: SYSVAR_RENT_PUBKEY }).remainingAccounts([{ pubkey: providerKey, isWritable: false, isSigner: false }, pair(t)[1]]);
}
function finishExit(e: ExitFixture, providerKey = tokens[e.token].provider) {
  const t = tokens[e.token];
  return program.methods.completeWithdrawal().accounts({ city: city(), hill: e.hill, lot: e.child, request: e.request,
    asset: asset(t.key), custody: custody(e.child), ownerReserve: reserve(e.child), earnings: earnings(t.key),
    destination: t.source, owner: wallet.publicKey, tokenProgram: TOKEN_PROGRAM_ID })
    .remainingAccounts([{ pubkey: providerKey, isWritable: false, isSigner: false }, pair(t)[1]]);
}

if (enabled) describe('stage 1 real provider snapshots on a LOCAL validator', () => {
  before(async () => {
    expect(['127.0.0.1', 'localhost']).to.include(new URL(provider.connection.rpcEndpoint).hostname);
    if (!await provider.connection.getAccountInfo(config())) {
      const executable = (await provider.connection.getAccountInfo(program.programId))!;
      await send(program.methods.initializeProgramConfig(wallet.publicKey).accounts({ programConfig: config(), program: program.programId,
        programData: new PublicKey(executable.data.subarray(4, 36)), admin: wallet.publicKey, systemProgram: SystemProgram.programId }));
    }
    const accounts = await capture(provider.connection, program.programId, [wallet.publicKey]);
    // Start a fresh synthetic adapter ledger after any earlier custody suite.
    // Preserve the executable, ProgramConfig and wallet, but do not inherit
    // another scenario's positions or full deployment cap. New Stage1 state
    // is created by instructions below, never by editing accounting bytes.
    for (const [key, account] of accounts) {
      if ((account.owner.equals(program.programId) && key !== config().toBase58())
        || account.owner.equals(TOKEN_PROGRAM_ID)) accounts.delete(key);
    }
    for (const t of tokens) {
      for (const raw of [t.state, t.mint]) accounts.set(raw.pubkey, { ...raw.account, owner: new PublicKey(raw.account.owner), data: Buffer.from(raw.account.data[0], 'base64') });
      // Explicit synthetic local owner inventory. Provider state/mint bytes stay exact.
      const data = Buffer.alloc(165); t.key.toBuffer().copy(data); wallet.publicKey.toBuffer().copy(data, 32);
      data.writeBigUInt64LE(20000n * 1000000000n, 64); data[108] = 1;
      accounts.set(t.source.toBase58(), { owner: TOKEN_PROGRAM_ID, data, executable: false, lamports: 2039280, rentEpoch: 0 });
    }
    await scenario(accounts, EPOCH, AT, async () => {
      if (!await provider.connection.getAccountInfo(city())) await send(program.methods.initCityConfig(bn(1791201600)).accounts({
        city: city(), programConfig: config(), admin: wallet.publicKey, systemProgram: SystemProgram.programId }));
      for (const t of tokens) {
        await send(configure(t, false));
        expect((await state(t)).enabled).to.equal(false);
        await rejected(send(configure(t, true)), 'Stage1RateRefreshRequired');
        await send(refresh(t));
        await send(configure(t, true));
      }
      baseline = await saved();
      hill = await newHill();
      xLot = await deposit(hill, 0, unitsFor(4000000000n, tokens[0]), [0]);
      await deposit(hill, 2, unitsFor(100000000n, tokens[2]), [0, 2]);
      campaign = await saved();
    });
  });
  for (const [i, t] of tokens.entries()) it(`derives the exact snapshot rational for ${definitions[i][0]}, without fee discount`, async () => {
    await scenario(baseline, EPOCH, AT, async () => {
      const actual = await state(t);
      expect([actual.admittedNumerator.toString(), actual.admittedDenominator.toString()]).to.deep.equal([String(t.n), String(t.d)]);
      const vector = vectors.providers[i];
      expect([actual.admittedNumerator.toString(), actual.admittedDenominator.toString()]).to.deep.equal([vector.numerator, vector.denominator]);
      expect(actual.admittedEpoch.toNumber()).to.equal(EPOCH);
      expect((await provider.connection.getAccountInfo(t.provider))!.data.equals(Buffer.from(t.state.account.data[0], 'base64'))).to.equal(true);
      if (process.env.STAGE1_LOCALNET === '1') {
      await rejected(send(program.methods.setTestLstRate(bn(1), bn(1), bn(await now())).accounts({ city: city(), asset: asset(t.key),
        programConfig: config(), admin: wallet.publicKey })), 'Stage1AdapterDisabled');
      }
    });
  });
  for (const [i, t] of tokens.entries()) {
  it(`refreshes ${definitions[i][0]} permissionlessly and retains one value through intra-epoch drift`, async () => {
    const drift = changed(baseline, i, i === 1 ? 376 : 258, Buffer.from(t.state.account.data[0], 'base64').readBigUInt64LE(i === 1 ? 376 : 258) + 12345n);
    await scenario(drift, EPOCH, AT, async () => {
      const stranger = Keypair.generate();
      await send(SystemProgram.transfer({ fromPubkey: wallet.publicKey, toPubkey: stranger.publicKey, lamports: 1000000000 }));
      const before = await state(t);
      const beforeCity = await program.account.stage1CityConfig.fetch(city());
      await send(refresh(t), stranger);
      const after = await state(t);
      const afterCity = await program.account.stage1CityConfig.fetch(city());
      expect(afterCity.rateEpochs[after.slot].toString()).to.equal(beforeCity.rateEpochs[before.slot].toString());
      expect(after.admittedNumerator.toString()).to.equal(before.admittedNumerator.toString());
      expect(after.admittedEpoch.toString()).to.equal(before.admittedEpoch.toString());
      const [n, d] = vectors.providers[i].same_epoch_drift_rate.map(BigInt);
      expect(BigInt(after.admittedNumerator.toString()) * d).to.equal(BigInt(after.admittedDenominator.toString()) * n);
    });
  });
  it(`admits ${definitions[i][0]} in the next epoch exactly once without crediting earnings`, async () => {
    const drift = updated(changed(baseline, i, i === 1 ? 376 : 258, Buffer.from(t.state.account.data[0], 'base64').readBigUInt64LE(i === 1 ? 376 : 258) + 12345n), EPOCH + 1);
    await scenario(drift, EPOCH + 1, AT + 200000, async () => {
      const before = (await provider.connection.getAccountInfo(earnings(t.key)))!.data;
      await send(refresh(t));
      const admitted = await state(t);
      const deployment = await program.account.stage1CityConfig.fetch(city());
      expect(deployment.rateEpochs[admitted.slot].toNumber()).to.equal(vectors.providers[i].numeric_revisions);
      expect(admitted.admittedNumerator.toString()).to.equal(String(t.n + 12345n));
      const [n, d] = vectors.providers[i].next_epoch_drift_rate.map(BigInt);
      expect(BigInt(admitted.admittedNumerator.toString()) * d).to.equal(BigInt(admitted.admittedDenominator.toString()) * n);
      expect((await provider.connection.getAccountInfo(earnings(t.key)))!.data.equals(before)).to.equal(true);
    });
  });
  }
  for (const fault of ['owner', 'mint', 'layout', 'epoch']) it(`rejects ${fault} without changing admitted freshness`, async () => {
    const bad = clone(baseline), info = bad.get(tokens[0].provider.toBase58())!;
    if (fault === 'owner') info.owner = SystemProgram.programId;
    if (fault === 'mint') tokens[1].key.toBuffer().copy(info.data, 162);
    if (fault === 'layout') info.data[0] = 2;
    if (fault === 'epoch') info.data.writeBigUInt64LE(BigInt(EPOCH - 1), 274);
    await scenario(bad, EPOCH, AT, async () => {
      const before = (await provider.connection.getAccountInfo(asset(tokens[0].key)))!.data;
      await rejected(send(refresh(tokens[0])), fault === 'epoch' ? 'Stage1StaleRate' : 'Stage1InvalidProvider');
      expect((await provider.connection.getAccountInfo(asset(tokens[0].key)))!.data.equals(before)).to.equal(true);
      await rejected(send(outage(tokens[0])), fault === 'owner' ? 'Stage1InvalidProvider' : 'Stage1ProviderAvailable');
    });
  });
  it('rejects a substituted pool and an omitted backed slot atomically', async () => {
    await scenario(updated(campaign, EPOCH + 1), EPOCH + 1, AT + 200000, async () => {
      await rejected(send(refresh(tokens[0], tokens[2].provider)), 'Stage1InvalidProvider');
      const before = (await provider.connection.getAccountInfo(hill))!.data;
      await rejected(deposit(hill, 1, unitsFor(7000000000n, tokens[1]), [1, 2], true), 'Stage1InvalidProvider');
      expect((await provider.connection.getAccountInfo(hill))!.data.equals(before)).to.equal(true);
    });
  });
  it('refreshes all three backed slots at bonding, including disabled X, so the 7 SOL timing probe includes X', async () => {
    await scenario(updated(campaign, EPOCH + 1), EPOCH + 1, AT + 200000, async () => {
      await send(configure(tokens[0], false));
      await deposit(hill, 1, unitsFor(7000000000n, tokens[1]), [0, 1, 2], true);
      const h = await program.account.stage1HillBond.fetch(hill);
      for (const t of tokens) {
        const a = await state(t);
        expect(a.admittedEpoch.toNumber()).to.equal(EPOCH + 1);
        expect(h.foundingFreshSlots & (1 << a.slot)).not.to.equal(0);
      }
      expect(h.foundingCount.toNumber()).to.equal(3);
      expect(h.founder.equals(wallet.publicKey)).to.equal(true);
      await send(program.methods.materializeStage1Lot().accounts({ city: city(), hill, lot: xLot, asset: asset(tokens[0].key),
        custody: custody(xLot), ownerReserve: reserve(xLot), tokenProgram: TOKEN_PROGRAM_ID }));
      expect((await program.account.stage1PledgeLot.fetch(xLot)).founding).to.equal(true);
    });
  });
  it('requires per-lot repricing when the atomic provider refresh finds a new numeric rate', async () => {
    const drift = updated(changed(campaign, 0, 258, tokens[0].n + 12345n), EPOCH + 1);
    await scenario(drift, EPOCH + 1, AT + 200000, async () => {
      await rejected(deposit(hill, 1, unitsFor(7000000000n, tokens[1]), [0, 1, 2], true), 'Stage1CampaignRefreshRequired');
      await send(refresh(tokens[0]));
      await send(program.methods.refreshCampaignLot().accounts({ city: city(), hill, lot: xLot, asset: asset(tokens[0].key),
        custody: custody(xLot), ownerReserve: reserve(xLot), tokenProgram: TOKEN_PROGRAM_ID }).remainingAccounts(pair(tokens[0])));
      await deposit(hill, 1, unitsFor(7000000000n, tokens[1]), [0, 1, 2], true);
      expect((await program.account.stage1HillBond.fetch(hill)).foundingCount.toNumber()).to.equal(3);
    });
  });
  it('keeps lagging provider lots founding at zero threshold value', async () => {
    await scenario(campaign, EPOCH + 1, AT + 200000, async () => {
      await rejected(send(outage(tokens[0], tokens[2].provider)), 'Stage1InvalidProvider');
      await rejected(send(outage(tokens[0])), 'Stage1ProviderAvailable');
      await rejected(deposit(hill, 1, unitsFor(7000000000n, tokens[1]), [0, 1, 2], true), 'Stage1BelowLine');
      await deposit(hill, 1, unitsFor(11000000000n, tokens[1]), [0, 1, 2], true);
      const h = await program.account.stage1HillBond.fetch(hill);
      expect(h.foundingCount.toNumber()).to.equal(3);
      expect(h.foundingFreshSlots & (1 << (await state(tokens[0])).slot)).not.to.equal(0);
      for (const i of [0, 2]) expect(h.foundingLaggingSlots & (1 << (await state(tokens[i])).slot)).not.to.equal(0);
      expect(h.foundingLaggingSlots & (1 << (await state(tokens[1])).slot)).to.equal(0);
      expect(h.foundingCount.toNumber()).to.equal(vectors.grace.founding_count);
      await send(program.methods.materializeStage1Lot().accounts({ city: city(), hill, lot: xLot, asset: asset(tokens[0].key),
        custody: custody(xLot), ownerReserve: reserve(xLot), tokenProgram: TOKEN_PROGRAM_ID }));
      expect((await program.account.stage1PledgeLot.fetch(xLot)).founding).to.equal(true);
    });
  });
  it('ends founding grace after a whole missed epoch and keeps mSOL current', async () => {
    await scenario(campaign, EPOCH + 2, AT + 400000, async () => {
      await send(outage(tokens[0]));
      await deposit(hill, 1, unitsFor(11000000000n, tokens[1]), [0, 1, 2], true);
      const h = await program.account.stage1HillBond.fetch(hill);
      expect(h.foundingCount.toNumber()).to.equal(vectors.grace.expired_founding_count);
      expect(h.foundingLaggingSlots).to.equal(0);
      expect((await state(tokens[1])).admittedEpoch.toNumber()).to.equal(EPOCH + 2);
    });
  });
  it('freezes the prior admitted quote despite unfinished repricing and later recovery', async () => {
    let revised: Capture, bonded: Capture, frozenN: bigint, frozenD: bigint, expectedSurplus: bigint;
    await scenario(updated(changed(campaign, 0, 258, tokens[0].n * 2n), EPOCH + 1), EPOCH + 1, AT + 200000, async () => {
      await send(refresh(tokens[0])); // Deliberately do not reprice xLot.
      await send(refresh(tokens[2]));
      const a = await state(tokens[0]), lot = await program.account.stage1PledgeLot.fetch(xLot);
      frozenN = BigInt(a.admittedNumerator.toString()); frozenD = BigInt(a.admittedDenominator.toString());
      expectedSurplus = BigInt(lot.units.toString()) - (BigInt(lot.basisLamports.toString()) * frozenD + frozenN - 1n) / frozenN;
      expect(expectedSurplus > 0n).to.equal(true);
      revised = await saved();
    });
    await scenario(revised!, EPOCH + 2, AT + 400000, async () => {
      await deposit(hill, 1, unitsFor(11000000000n, tokens[1]), [0, 1, 2], true);
      const h = await program.account.stage1HillBond.fetch(hill), a = await state(tokens[0]);
      expect(h.foundingCount.toNumber()).to.equal(3);
      expect(h.quotedNumerators[a.slot].toString()).to.equal(String(frozenN!));
      bonded = await saved();
    });
    await scenario(updated(changed(bonded!, 0, 258, tokens[0].n * 3n), EPOCH + 3), EPOCH + 3, AT + 600000, async () => {
      await send(refresh(tokens[0]));
      await send(program.methods.materializeStage1Lot().accounts({ city: city(), hill, lot: xLot, asset: asset(tokens[0].key),
        custody: custody(xLot), ownerReserve: reserve(xLot), tokenProgram: TOKEN_PROGRAM_ID }));
      const lot = await program.account.stage1PledgeLot.fetch(xLot);
      expect(lot.founding).to.equal(true);
      expect(lot.prebondUnitsFrozen.toString()).to.equal(String(expectedSurplus!));
      expect((await getAccount(provider.connection, reserve(xLot), 'processed')).amount).to.equal(expectedSurplus!);
    });
  });
  for (const action of ['pledge', 'bond', 'bonded intake']) it(`round3 rejects excess mint supply for ${action} inside the admitted epoch`, async () => {
    let prepared = campaign, target = hill;
    if (action === 'bonded intake') {
      await scenario(baseline, EPOCH, AT, async () => {
        target = await newHill();
        await deposit(target, 0, unitsFor(11000000000n, tokens[0]), [0], true);
        prepared = await saved();
      });
    }
    await scenario(excessMintSupply(prepared), EPOCH, AT + 100, async () => {
      await rejected(send(refresh(tokens[0])), 'Stage1InvalidProvider');
      const keys = [city(), target, asset(tokens[0].key), tokens[0].source, earnings(tokens[0].key)];
      const before = await Promise.all(keys.map(async key => (await provider.connection.getAccountInfo(key))!.data));
      await unchangedAfterRejection(deposit(target, 0, unitsFor(action === 'bond' ? 11000000000n : 1000000000n, tokens[0]),
        action === 'bonded intake' ? [0] : [0, 2], action === 'bond'), keys, before);
    });
  });
  for (const bonded of [false, true]) it(`round3_lagged rejects intake with a current cache on a ${bonded ? 'bonded' : 'campaign'} hill`, async () => {
    let prepared = campaign, target = hill;
    if (bonded) {
      await scenario(baseline, EPOCH, AT, async () => {
        target = await newHill();
        await deposit(target, 0, unitsFor(11000000000n, tokens[0]), [0], true);
        prepared = await saved();
      });
    }
    const previous = changed(changed(prepared, 0, 258, tokens[0].n * 2n), 0, 274, BigInt(EPOCH - 1));
    await scenario(previous, EPOCH, AT + 100, async () => {
      expect((await state(tokens[0])).admittedEpoch.toNumber()).to.equal(EPOCH);
      const keys = [city(), target, asset(tokens[0].key), tokens[0].source, earnings(tokens[0].key)];
      const before = await Promise.all(keys.map(async key => (await provider.connection.getAccountInfo(key))!.data));
      await unchangedAfterRejection(deposit(target, 0, unitsFor(1000000000n, tokens[0]), bonded ? [0] : [0, 2]),
        keys, before, 'Stage1StaleRate');
    });
  });
  it('round3 rejects harvest from an unreadable current-epoch provider without moving principal', async () => {
    let target: PublicKey, lot: PublicKey, prepared: Capture, admitted: Capture;
    await scenario(baseline, EPOCH, AT, async () => {
      target = await newHill();
      await deposit(target, 0, unitsFor(11000000000n, tokens[0]), [0], true);
      lot = await deposit(target, 0, unitsFor(1000000000n, tokens[0]), [0]);
      prepared = await saved();
    });
    await scenario(updated(changed(prepared!, 0, 258, tokens[0].n * 2n), EPOCH + 1), EPOCH + 1, AT + 200000, async () => {
      await send(refresh(tokens[0]));
      await send(harvestLot(target!, lot!)); // The valid quote has real surplus.
      admitted = await saved();
    });
    await scenario(excessMintSupply(admitted!), EPOCH + 1, AT + 200100, async () => {
      const keys = [city(), target!, lot!, asset(tokens[0].key), custody(lot!), reserve(lot!), earnings(tokens[0].key)];
      const before = await Promise.all(keys.map(async key => (await provider.connection.getAccountInfo(key))!.data));
      await unchangedAfterRejection(send(harvestLot(target!, lot!)), keys, before);
    });
    const e = await exitFixture(0);
    await scenario(updated(e.accounts, EPOCH + 15), EPOCH + 15, e.eligible + 100, async () => {
      await send(refresh(tokens[0]));
      admitted = await saved();
    });
    await scenario(excessMintSupply(admitted!), EPOCH + 15, e.eligible + 200, async () => {
      const balance = (await getAccount(provider.connection, tokens[0].source, 'processed')).amount;
      await send(beginExit(e));
      await send(finishExit(e));
      expect((await getAccount(provider.connection, tokens[0].source, 'processed')).amount - balance).to.equal(e.units);
      expect((await state(tokens[0])).admittedEpoch.toNumber()).to.equal(EPOCH + 15);
      expect((await state(tokens[0])).providerStaleSince.toNumber()).to.equal(0);
    });
  });
  it('round3 gives unreadable cached backing zero value without jamming healthy intake', async () => {
    await scenario(excessMintSupply(campaign), EPOCH, AT + 100, async () => {
      const before = (await provider.connection.getAccountInfo(asset(tokens[0].key)))!.data;
      await rejected(deposit(hill, 1, unitsFor(7000000000n, tokens[1]), [0, 1, 2], true), 'Stage1BelowLine');
      await deposit(hill, 1, unitsFor(11000000000n, tokens[1]), [0, 1, 2], true);
      const h = await program.account.stage1HillBond.fetch(hill);
      expect(h.foundingCount.toNumber()).to.equal(2); // Healthy mSOL and JupSOL only.
      expect(h.foundingFreshSlots & (1 << (await state(tokens[0])).slot)).to.equal(0);
      expect((await provider.connection.getAccountInfo(asset(tokens[0].key)))!.data.equals(before)).to.equal(true);
    });
  });
  it('round3 preserves grace and the pool quote when BoulderRoller skipped the previous epoch', async () => {
    const previous = updated(changed(changed(campaign, 0, 258, tokens[0].n * 2n), 2, 258, tokens[2].n * 2n), EPOCH + 1);
    let bonded: Capture, surplus: bigint;
    await scenario(previous, EPOCH + 2, AT + 400000, async () => {
      await rejected(deposit(hill, 1, unitsFor(7000000000n, tokens[1]), [0, 1, 2], true), 'Stage1BelowLine');
      await deposit(hill, 1, unitsFor(11000000000n, tokens[1]), [0, 1, 2], true);
      const h = await program.account.stage1HillBond.fetch(hill);
      expect(h.foundingCount.toNumber()).to.equal(vectors.skipped_refresh_grace.founding_count);
      for (const i of [0, 2]) {
        const a = await state(tokens[i]);
        expect(a.admittedEpoch.toNumber()).to.equal(EPOCH);
        expect(h.foundingLaggingSlots & (1 << a.slot)).not.to.equal(0);
        expect(h.quotedNumerators[a.slot].toString()).to.equal(String(tokens[i].n * 2n));
        expect(h.quotedDenominators[a.slot].toString()).to.equal(String(tokens[i].d));
        await rejected(send(outage(tokens[i])), 'Stage1ProviderAvailable');
      }
      const lot = await program.account.stage1PledgeLot.fetch(xLot), n = tokens[0].n * 2n;
      surplus = BigInt(lot.units.toString()) - (BigInt(lot.basisLamports.toString()) * tokens[0].d + n - 1n) / n;
      expect(String(surplus)).to.equal(vectors.skipped_refresh_grace.prebond_units.jitoSOL);
      bonded = await saved();
    });
    await scenario(updated(changed(bonded!, 0, 258, tokens[0].n * 3n), EPOCH + 3), EPOCH + 3, AT + 600000, async () => {
      await send(refresh(tokens[0]));
      await send(program.methods.materializeStage1Lot().accounts({ city: city(), hill, lot: xLot, asset: asset(tokens[0].key),
        custody: custody(xLot), ownerReserve: reserve(xLot), tokenProgram: TOKEN_PROGRAM_ID }));
      expect((await program.account.stage1PledgeLot.fetch(xLot)).prebondUnitsFrozen.toString()).to.equal(String(surplus!));
      expect((await getAccount(provider.connection, reserve(xLot), 'processed')).amount).to.equal(surplus!);
    });
    await scenario(previous, EPOCH + 3, AT + 600000, async () => {
      await send(outage(tokens[0]));
      await deposit(hill, 1, unitsFor(11000000000n, tokens[1]), [0, 1, 2], true);
      expect((await program.account.stage1HillBond.fetch(hill)).foundingCount.toNumber()).to.equal(1);
    });
  });
  it('round3_restore uses the admitted quote after a temporary lagged quote recovers', async () => {
    let waiting: Capture;
    await scenario(changed(campaign, 0, 258, tokens[0].n * 2n), EPOCH + 1, AT + 200000, async () => {
      await deposit(hill, 1, unitsFor(1000000000n, tokens[1]), [0, 1, 2]);
      expect((await program.account.stage1HillBond.fetch(hill)).bonded).to.equal(false);
      waiting = await saved();
    });
    await scenario(updated(changed(waiting!, 0, 258, tokens[0].n), EPOCH + 2), EPOCH + 2, AT + 400000, async () => {
      const revision = (await program.account.stage1CityConfig.fetch(city())).rateEpochs[(await state(tokens[0])).slot];
      await deposit(hill, 1, unitsFor(7000000000n, tokens[1]), [0, 1, 2], true);
      const h = await program.account.stage1HillBond.fetch(hill), a = await state(tokens[0]);
      expect(h.foundingCount.toNumber()).to.equal(4);
      expect(h.rateEpochs[a.slot].toString()).to.equal(revision.toString());
      expect(h.quotedNumerators[a.slot].toString()).to.equal(String(tokens[0].n));
      expect(h.foundingLaggingSlots).to.equal(0);
      await send(program.methods.materializeStage1Lot().accounts({ city: city(), hill, lot: xLot, asset: asset(tokens[0].key),
        custody: custody(xLot), ownerReserve: reserve(xLot), tokenProgram: TOKEN_PROGRAM_ID }));
      expect((await program.account.stage1PledgeLot.fetch(xLot)).prebondUnitsFrozen.toNumber()).to.equal(0);
      expect((await getAccount(provider.connection, reserve(xLot), 'processed')).amount).to.equal(0n);
    });
  });
  it('returns a mature full lot in kind only for a genuine seven-day provider outage', async () => {
    let prepared: Capture, grace: Capture, lot: PublicKey, request: PublicKey, target: PublicKey;
    let actualUnits: string, eligible: number, graceAt: number;
    await scenario(baseline, EPOCH, AT, async () => {
      target = await newHill();
      await deposit(target, 0, unitsFor(10000000000n, tokens[0]) + 2n, [0], true);
      lot = await deposit(target, 0, unitsFor(1000000000n, tokens[0]), [0]);
      const l = await program.account.stage1PledgeLot.fetch(lot);
      actualUnits = l.units.toString();
      const id = ++serial;
      request = pda('s1v1_request', lot.toBuffer(), bn(id).toArrayLike(Buffer, 'le', 8));
      await send(program.methods.requestWithdrawal(bn(id), l.basisLamports).accounts({ city: city(), hill: target,
        lot, request, owner: wallet.publicKey, systemProgram: SystemProgram.programId }));
      eligible = (await program.account.stage1WithdrawalRequest.fetch(request)).eligibleAt.toNumber();
      prepared = await saved();
    });
    await scenario(prepared!, EPOCH + 2, eligible! + 100, async () => {
      await send(outage(tokens[0]));
      graceAt = (await state(tokens[0])).providerStaleSince.toNumber();
      grace = await saved();
    });
    const begin = (providerKey = tokens[0].provider) => {
      const child = pda('s1v1_exit', request!.toBuffer());
      return program.methods.beginWithdrawal().accounts({ city: city(), hillAccount: { hill: target! }, lot: lot!, request: request!,
        mint: tokens[0].key, asset: asset(tokens[0].key), custody: custody(lot!), ownerReserve: reserve(lot!),
        earnings: earnings(tokens[0].key), exitLot: child, exitCustody: custody(child), exitReserve: reserve(child),
        owner: wallet.publicKey, tokenProgram: TOKEN_PROGRAM_ID, systemProgram: SystemProgram.programId,
        rent: SYSVAR_RENT_PUBKEY }).remainingAccounts([
          { pubkey: providerKey, isWritable: false, isSigner: false }, pair(tokens[0])[1]]);
    };
    await scenario(grace!, EPOCH + 15, graceAt! + WEEK - 1, async () => {
      await rejected(send(begin()), 'Stage1StaleRate');
    }, true);
    await scenario(grace!, EPOCH + 15, graceAt! + WEEK, async () => {
      await send(begin());
    }, true);
    await scenario(grace!, EPOCH + 15, graceAt! + WEEK + 10, async () => {
      const before = (await provider.connection.getAccountInfo(lot!))!.data;
      await rejected(send(begin(tokens[2].provider)), 'Stage1InvalidProvider');
      expect((await provider.connection.getAccountInfo(lot!))!.data.equals(before)).to.equal(true);
      const earningsBefore = (await provider.connection.getAccountInfo(earnings(tokens[0].key)))!.data;
      await send(begin());
      const child = pda('s1v1_exit', request!.toBuffer());
      await rejected(send(program.methods.completeWithdrawal().accounts({ city: city(), hill: target!, lot: child, request: request!,
        asset: asset(tokens[0].key), custody: custody(child), ownerReserve: reserve(child), earnings: earnings(tokens[0].key),
        destination: tokens[0].source, owner: wallet.publicKey, tokenProgram: TOKEN_PROGRAM_ID }).remainingAccounts(pair(tokens[2]))), 'Stage1InvalidProvider');
      await send(program.methods.completeWithdrawal().accounts({ city: city(), hill: target!, lot: child, request: request!,
        asset: asset(tokens[0].key), custody: custody(child), ownerReserve: reserve(child), earnings: earnings(tokens[0].key),
        destination: tokens[0].source, owner: wallet.publicKey, tokenProgram: TOKEN_PROGRAM_ID }).remainingAccounts(pair(tokens[0])));
      const returned = await program.account.stage1PledgeLot.fetch(child);
      expect(returned.returnedUnits.toString()).to.equal(actualUnits!);
      expect(returned.realizedLossLamports).to.equal(null);
      expect((await provider.connection.getAccountInfo(earnings(tokens[0].key)))!.data.equals(earningsBefore)).to.equal(true);
    });
    // A genuinely recovered pool followed by a brief new epoch lag cannot
    // reuse the old outage timer, even if nobody refreshed the BR cache.
    const recovered = changed(grace!, 0, 274, BigInt(EPOCH + 14));
    await scenario(recovered, EPOCH + 15, graceAt! + WEEK + 10, async () => {
      await rejected(send(begin()), 'Stage1StaleRate');
      await rejected(send(outage(tokens[0])), 'Stage1ProviderAvailable');
    });
    await scenario(recovered, EPOCH + 16, graceAt! + WEEK + 100, async () => {
      await rejected(send(begin()), 'Stage1StaleRate');
      await send(outage(tokens[0]));
      expect((await state(tokens[0])).outageProviderEpoch.toNumber()).to.equal(EPOCH + 14);
      await rejected(send(begin()), 'Stage1StaleRate');
    });
    await scenario(updated(grace!, EPOCH + 15), EPOCH + 15, graceAt! + WEEK + 10, async () => {
      await rejected(send(begin()), 'Stage1RateRefreshRequired');
      await send(refresh(tokens[0]));
      await send(begin());
    });
  });
  for (const [index, fault] of tokens.flatMap((_, i) => [[i, 'layout'], [i, 'zero supply']] as [number, string][])
    .concat([[1, 'tickets exceed total']])) it(`returns all units after authenticated ${definitions[index][0]} ${fault}`, async () => {
    const e = await exitFixture(index), t = tokens[index];
    const breakState = (accounts: Capture) => fault === 'layout' ? changed(accounts, index, 0, 255n, 1)
      : changed(accounts, index, fault === 'zero supply' ? (index === 1 ? 504 : 266) : 528,
        fault === 'zero supply' ? 0n : (1n << 64n) - 1n);
    let grace: Capture, begun: Capture, graceAt: number;
    await scenario(breakState(e.accounts), EPOCH + 2, e.eligible + 100, async () => {
      await rejected(send(refresh(t)), 'Stage1InvalidProvider');
      await send(outage(t));
      const a = await state(t);
      expect(a.outageIsOpaque).to.equal(true);
      graceAt = a.providerStaleSince.toNumber();
      grace = await saved();
    });
    const churn = changed(grace!, index, Buffer.from(t.state.account.data[0], 'base64').length - 1, 1n, 1);
    await scenario(churn, EPOCH + 3, graceAt! + 100, async () => {
      await send(outage(t));
      expect((await state(t)).providerStaleSince.toNumber()).to.equal(graceAt!);
      grace = await saved();
    });
    if (index === 0 && fault === 'layout') {
      await scenario(grace!, EPOCH + 15, graceAt! + WEEK - 1, async () => {
        await rejected(send(beginExit(e)), 'Stage1StaleRate');
      }, true);
      await scenario(grace!, EPOCH + 15, graceAt! + WEEK, async () => { await send(beginExit(e)); }, true);
    }
    await scenario(grace!, EPOCH + 15, graceAt! + WEEK + 10, async () => {
      const wrong = tokens[(index + 1) % tokens.length].provider;
      await rejected(send(beginExit(e, wrong)), 'Stage1InvalidProvider');
      const earningsBefore = (await provider.connection.getAccountInfo(earnings(t.key)))!.data;
      await send(beginExit(e));
      begun = await saved();
      await rejected(send(finishExit(e, wrong)), 'Stage1InvalidProvider');
      const balance = (await getAccount(provider.connection, t.source, 'processed')).amount;
      await send(finishExit(e));
      const returned = await program.account.stage1PledgeLot.fetch(e.child);
      expect(returned.returnedUnits.toString()).to.equal(String(e.units));
      expect(returned.realizedLossLamports).to.equal(null);
      expect((await getAccount(provider.connection, t.source, 'processed')).amount - balance).to.equal(e.units);
      expect((await provider.connection.getAccountInfo(earnings(t.key)))!.data.equals(earningsBefore)).to.equal(true);
    });
    if (index === 0 && fault === 'layout') {
      for (const [accounts, complete] of [[grace!, false], [begun!, true]] as [Capture, boolean][]) {
        const wrongOwner = clone(accounts); wrongOwner.get(t.provider.toBase58())!.owner = SystemProgram.programId;
        await scenario(wrongOwner, EPOCH + 15, graceAt! + WEEK + 10, async () => {
          await rejected(send(outage(t)), 'Stage1InvalidProvider');
          await rejected(send(complete ? finishExit(e) : beginExit(e)), 'Stage1InvalidProvider');
        });
      }
      const readable = clone(grace!);
      readable.get(t.provider.toBase58())!.data = Buffer.from(t.state.account.data[0], 'base64');
      await scenario(readable, EPOCH + 15, graceAt! + WEEK + 10, async () => {
        await rejected(send(beginExit(e)), 'Stage1StaleRate');
        await send(outage(t));
        const a = await state(t);
        expect(a.outageIsOpaque).to.equal(false);
        expect(a.providerStaleSince.toNumber()).to.be.greaterThan(graceAt!);
        await rejected(send(beginExit(e)), 'Stage1StaleRate');
      });
    }
    if (fault === 'tickets exceed total') {
      const recovered = clone(grace!);
      recovered.get(t.provider.toBase58())!.data = Buffer.from(t.state.account.data[0], 'base64');
      let healthy: Capture;
      await scenario(recovered, EPOCH + 15, graceAt! + WEEK + 10, async () => {
        await rejected(send(beginExit(e)), 'Stage1RateRefreshRequired');
        await send(refresh(t));
        expect((await state(t)).providerStaleSince.toNumber()).to.equal(0);
        healthy = await saved();
      });
      await scenario(breakState(healthy!), EPOCH + 16, graceAt! + WEEK + 100, async () => {
        await send(outage(t));
        expect((await state(t)).providerStaleSince.toNumber()).to.be.greaterThan(graceAt!);
        await rejected(send(beginExit(e)), 'Stage1StaleRate');
      });
    }
  });
  it('keeps mSOL accounting available while provider redemption operations are paused', async () => {
    await scenario(changed(baseline, 1, 608, 1n, 1), EPOCH + 1, AT + 200000, async () => {
      await send(refresh(tokens[1]));
      expect((await state(tokens[1])).admittedNumerator.toString()).to.equal(String(tokens[1].n));
      await rejected(send(outage(tokens[1])), 'Stage1ProviderAvailable');
    });
  });
  it('refuses to re-enable JupSOL after an unverified withdrawal-setting change', async () => {
    // Snapshot-specific offset: stake withdrawal fee denominator@365, numerator@373.
    await scenario(changed(baseline, 2, 373, 2n), EPOCH, AT, async () => {
      await send(configure(tokens[2], false));
      await rejected(send(configure(tokens[2], true)), 'Stage1ProviderPolicyUnverified');
      expect((await state(tokens[2])).enabled).to.equal(false);
      expect((await state(tokens[2])).admittedNumerator.toString()).to.equal(String(tokens[2].n));
    });
  });
});
