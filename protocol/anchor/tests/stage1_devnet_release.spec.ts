import * as anchor from '@coral-xyz/anchor';
import { expect } from 'chai';
import { createHash } from 'crypto';
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
import { PublicKey, Keypair, SystemProgram, StakeProgram, Authorized, Lockup, TransactionInstruction,
  TransactionMessage, VersionedTransaction, Signer, SYSVAR_RENT_PUBKEY } from '@solana/web3.js';
import { TOKEN_PROGRAM_ID, createInitializeMint2Instruction, createAssociatedTokenAccountIdempotentInstruction,
  getAssociatedTokenAddressSync, getAccount } from '@solana/spl-token';
import { StakePoolInstruction } from '@solana/spl-stake-pool';
import { Operator, bn, pk, runOperator, simulateThenSubmit } from '../scripts/stage1_operator.js';
import { bootstrap, CAPS } from '../scripts/stage1_bootstrap.js';
import { smoke } from '../scripts/stage1_smoke.js';
import { validateStage1 } from '../scripts/stage1_validation.js';
import { capture, replay, pause } from './helpers/stage1_replay.js';

const enabled = process.env.STAGE1_DEVNET === '1';
const poolProgram = pk('DPoo15wWDqpPJJtS2MUZ49aRxqz5ZaaJCJP4z8bLuib');
if (enabled) describe('devnet release binary on LOCAL validator, real locally created SPL pool', () => {
  const initial = anchor.AnchorProvider.env(), admin = (initial.wallet as anchor.Wallet).payer;
  const fee = Keypair.generate(), operator = Keypair.generate(), publisher = Keypair.generate();
  const poolManager = Keypair.generate(), poolStaker = Keypair.generate();
  const pool = Keypair.generate(), list = Keypair.generate(), mint = Keypair.generate(), reserve = Keypair.generate();
  const withdraw = PublicKey.findProgramAddressSync([pool.publicKey.toBuffer(), Buffer.from('withdraw')], poolProgram)[0];
  const managerFee = getAssociatedTokenAddressSync(mint.publicKey, poolManager.publicKey);
  const source = getAssociatedTokenAddressSync(mint.publicKey, operator.publicKey);
  anchor.setProvider(initial);
  let connection = initial.connection, program: any = anchor.workspace.BoulderRollers;
  const programId = program.programId;
  let directory: string, serial = 0, configInput: any, smokeInput: any, runtime: any;
  const pda = (seed: string, ...parts: Buffer[]) => PublicKey.findProgramAddressSync([Buffer.from(seed), ...parts], programId)[0];
  const asset = () => pda('s1v1_asset', mint.publicKey.toBuffer());
  const opts = () => ({ 'program-id': programId.toBase58(), rpc: connection.rpcEndpoint, cluster: 'localnet',
    'program-interface': 'devnet',
    admin: admin.publicKey.toBase58(), 'fee-payer': fee.publicKey.toBase58(),
    'admin-keypair': join(directory, 'admin.json'), 'fee-payer-keypair': join(directory, 'fee.json'),
    'operator-keypair': join(directory, 'operator.json'), 'publisher-keypair': join(directory, 'publisher.json') });
  async function send(ixs: any[], signers: Signer[] = []) {
    const instructions = await Promise.all(ixs.map(ix => ix instanceof TransactionInstruction ? ix : ix.instruction()));
    const block = await connection.getLatestBlockhash('finalized');
    const tx = new VersionedTransaction(new TransactionMessage({ payerKey: fee.publicKey, recentBlockhash: block.blockhash, instructions }).compileToLegacyMessage());
    const required = tx.message.staticAccountKeys.slice(0, tx.message.header.numRequiredSignatures);
    tx.sign([fee, admin, ...signers].filter(signer => required.some(key => key.equals(signer.publicKey))));
    return simulateThenSubmit(connection, tx);
  }
  async function rejected(action: Promise<unknown>, text: string) {
    try { await action; } catch (e: any) { expect(`${e.message}\n${e.logs?.join('\n')}`).to.include(text); return; }
    throw new Error(`Expected ${text}`);
  }
  async function execute(build: any, tool: string, input: any, action: string) {
    const file = join(directory, `input-${++serial}.json`), planFile = join(directory, `plan-${serial}.json`);
    writeFileSync(file, JSON.stringify(input));
    const options = { ...opts(), action, input: file };
    let output = ''; const log = console.log;
    try {
      console.log = (text: any) => { output += String(text); };
      await runOperator(tool, build, { ...options, mode: 'plan' });
    } finally { console.log = log; }
    const plan = JSON.parse(output); writeFileSync(planFile, output);
    await runOperator(tool, build, { ...options, mode: 'submit', plan: planFile, digest: plan.digest });
    return plan;
  }
  const registration = (provider = pool.publicKey, token = mint.publicKey) => program.methods.registerStage1TestPool().accounts({
    testPool: pda('s1v1_test_pool'), city: pda('s1v1_city'), asset: pda('s1v1_asset', token.toBuffer()), mint: token, provider,
    earnings: pda('s1v1_earnings', token.toBuffer()), programConfig: pda('program_config'), admin: admin.publicKey,
    tokenProgram: TOKEN_PROGRAM_ID, systemProgram: SystemProgram.programId, rent: SYSVAR_RENT_PUBKEY });

  before(async () => {
    expect(['127.0.0.1', 'localhost']).to.include(new URL(connection.rpcEndpoint).hostname);
    expect((await connection.getVersion())['solana-core']).to.equal('2.1.21');
    directory = mkdtempSync(join(tmpdir(), 'stage1-release-operator-'));
    for (const [name, key] of Object.entries({ admin, fee, operator, publisher })) writeFileSync(join(directory, `${name}.json`), JSON.stringify([...key.secretKey]), { mode: 0o600 });
    await connection.confirmTransaction(await connection.requestAirdrop(fee.publicKey, 2e9), 'finalized');
    await send([SystemProgram.transfer({ fromPubkey: admin.publicKey, toPubkey: poolManager.publicKey, lamports: 1e6 }),
      SystemProgram.transfer({ fromPubkey: admin.publicKey, toPubkey: poolStaker.publicKey, lamports: 1e6 }),
      SystemProgram.transfer({ fromPubkey: admin.publicKey, toPubkey: operator.publicKey, lamports: 40e9 }),
      SystemProgram.transfer({ fromPubkey: admin.publicKey, toPubkey: publisher.publicKey, lamports: 2e9 })]);
    const executable = (await connection.getAccountInfo(programId))!;
    await send([program.methods.initializeProgramConfig(admin.publicKey).accounts({ programConfig: pda('program_config'), program: programId,
      programData: new PublicKey(executable.data.subarray(4, 36)), admin: admin.publicKey, systemProgram: SystemProgram.programId })]);
    await send([SystemProgram.createAccount({ fromPubkey: admin.publicKey, newAccountPubkey: pool.publicKey, space: 611, lamports: await connection.getMinimumBalanceForRentExemption(611), programId: poolProgram }),
      SystemProgram.createAccount({ fromPubkey: admin.publicKey, newAccountPubkey: list.publicKey, space: 82, lamports: await connection.getMinimumBalanceForRentExemption(82), programId: poolProgram })], [pool, list]);
    await send([SystemProgram.createAccount({ fromPubkey: admin.publicKey, newAccountPubkey: mint.publicKey, space: 82, lamports: await connection.getMinimumBalanceForRentExemption(82), programId: TOKEN_PROGRAM_ID }),
      createInitializeMint2Instruction(mint.publicKey, 9, withdraw, null),
      createAssociatedTokenAccountIdempotentInstruction(admin.publicKey, managerFee, poolManager.publicKey, mint.publicKey),
      createAssociatedTokenAccountIdempotentInstruction(admin.publicKey, source, operator.publicKey, mint.publicKey)], [mint]);
    await send(StakeProgram.createAccount({ fromPubkey: admin.publicKey, stakePubkey: reserve.publicKey,
      authorized: new Authorized(withdraw, withdraw), lockup: new Lockup(0, 0, PublicKey.default),
      lamports: await connection.getMinimumBalanceForRentExemption(StakeProgram.space) + 1 }).instructions, [reserve]);
    // Exact Initialize encoding/account order from SPL program@v2.1.0
    // program/src/instruction.rs:739; fees are denominator then numerator.
    const data = Buffer.alloc(54); data.writeBigUInt64LE(1000n, 1); data.writeBigUInt64LE(1n, 9);
    data.writeBigUInt64LE(1000n, 17); data.writeBigUInt64LE(1n, 25); data.writeBigUInt64LE(1000n, 33); data.writeUInt32LE(1, 50);
    const keys = [pool.publicKey, poolManager.publicKey, poolStaker.publicKey, withdraw, list.publicKey, reserve.publicKey, mint.publicKey, managerFee, TOKEN_PROGRAM_ID]
      .map((pubkey, i) => ({ pubkey, isSigner: i === 1, isWritable: [0, 4, 6, 7].includes(i) }));
    await send([new TransactionInstruction({ programId: poolProgram, keys, data })], [poolManager]);
    const deposit = StakePoolInstruction.depositSol({ stakePool: pool.publicKey, reserveStake: reserve.publicKey,
      fundingAccount: operator.publicKey, destinationPoolAccount: source, managerFeeAccount: managerFee, referralPoolAccount: source,
      poolMint: mint.publicKey, lamports: 25e9, withdrawAuthority: withdraw });
    deposit.programId = poolProgram;
    await send([deposit], [operator]);
    expect((await getAccount(connection, source, 'finalized')).amount).to.equal(25_000_000_000n);
    const epoch = await connection.getEpochInfo('finalized');
    const clock = (await connection.getAccountInfo(anchor.web3.SYSVAR_CLOCK_PUBKEY, 'finalized'))!.data.readBigInt64LE(32);
    const anchorAt = 1791201600n + ((clock - 1791201600n) / 604800n) * 604800n;
    configInput = { seasonAnchor: String(anchorAt), caps: CAPS, mint: mint.publicKey.toBase58(), pool: pool.publicKey.toBase58(),
      publisher: publisher.publicKey.toBase58(), assetKind: 'SPL test asset',
      poolManager: poolManager.publicKey.toBase58(), poolStaker: poolStaker.publicKey.toBase58(),
      validatorList: list.publicKey.toBase58(), reserve: reserve.publicKey.toBase58() };
    await execute(bootstrap, 'stage1-bootstrap', configInput, 'city');
    await execute(bootstrap, 'stage1-bootstrap', configInput, 'publisher');
    expect(epoch.epoch).to.be.at.least(0);
  });
  after(async () => { await runtime?.stop(); if (directory) rmSync(directory, { recursive: true, force: true }); });

  it('rejects a non-SPL owner and a mismatched mint without reserving the singleton', async () => {
    await rejected(send([registration(admin.publicKey)]), 'Stage1InvalidProvider');
    const other = Keypair.generate();
    await send([SystemProgram.createAccount({ fromPubkey: admin.publicKey, newAccountPubkey: other.publicKey, space: 82,
      lamports: await connection.getMinimumBalanceForRentExemption(82), programId: TOKEN_PROGRAM_ID }), createInitializeMint2Instruction(other.publicKey, 9, admin.publicKey, null)], [other]);
    await rejected(send([registration(pool.publicKey, other.publicKey)]), 'Stage1InvalidProvider');
    expect(await connection.getAccountInfo(pda('s1v1_test_pool'))).to.equal(null);
  });
  it('registers the real pool once, disabled and explicitly labelled, with idempotent plans', async () => {
    await execute(bootstrap, 'stage1-bootstrap', configInput, 'asset');
    const a = await program.account.stage1AssetConfig.fetch(asset());
    expect(a.adapter).to.equal(5); expect(a.enabled).to.equal(false); expect(a.observationAdmitted).to.equal(false);
    expect((await execute(bootstrap, 'stage1-bootstrap', configInput, 'asset')).plan.instructions).to.have.length(0);
  });
  it('rejects a second registration and leaves the registered identity unchanged', async () => {
    const before = (await connection.getAccountInfo(pda('s1v1_test_pool')))!.data;
    await rejected(send([registration()]), 'already in use');
    expect((await connection.getAccountInfo(pda('s1v1_test_pool')))!.data.equals(before)).to.equal(true);
  });
  it('refreshes and enables from actual SPL accounting and admits a canonical test hill', async () => {
    await execute(bootstrap, 'stage1-bootstrap', configInput, 'refresh');
    await execute(bootstrap, 'stage1-bootstrap', configInput, 'enable');
    const hash = (s: string | Buffer) => createHash('sha256').update(s).digest();
    const id = hash('local real SPL test hill').subarray(0, 16), profile = hash('test profile');
    const bytes = Buffer.alloc(64); bytes[0] = 1; id.copy(bytes, 1); bytes.writeUInt16BE(1, 17); profile.copy(bytes, 32);
    const digest = hash(bytes), climb = pda('climb', digest), hill = pda('s1v1_hill', id);
    await send([program.methods.registerRatifiedClimb({ canonId: [...id], canonVersion: 1, canonicalProfileHash: [...profile],
      commitmentHash: [...digest], recordContinuityPolicy: { newRecordBoard: {} }, name: 'Local SPL test hill', vertM: 1000, distanceM: 2000, avgGradientPct: 500 })
      .accounts({ climb, climbVersionIndex: pda('climb_version', id, Buffer.from([0, 1])), predecessorClimb: null, programConfig: pda('program_config'), admin: admin.publicKey, systemProgram: SystemProgram.programId })]);
    configInput.climb = climb.toBase58(); await execute(bootstrap, 'stage1-bootstrap', configInput, 'hill');
    smokeInput = { allocationKind: 'synthetic operator rehearsal', operator: operator.publicKey.toBase58(), publisher: publisher.publicKey.toBase58(),
      mint: mint.publicKey.toBase58(), hill: hill.toBase58(), source: source.toBase58(), destination: source.toBase58(),
      depositId: '1', units: '4000000000', lockWeeks: 0, week: '0', harvestUnits: '100', harvestedUnitsAfter: '100', fundingNetAfter: '90', allocationUnits: '50' };
  });
  it('operator tools pledge and bond actual pool tokens, then assert finalized custody', async () => {
    await execute(smoke, 'stage1-smoke', smokeInput, 'pledge');
    await execute(smoke, 'stage1-smoke', { ...smokeInput, depositId: '2', units: '6000000000' }, 'bond');
    const h = await program.account.stage1HillBond.fetch(pk(smokeInput.hill));
    expect(h.bonded).to.equal(true); expect(h.founder.equals(operator.publicKey)).to.equal(true);
    await execute(validateStage1, 'stage1-validation', configInput, 'validate');
  });
  it('harvests actual pool appreciation, publishes one tiny synthetic allocation and claims exact units', async () => {
    // A real local SOL donation to the real SPL reserve creates appreciation.
    // No provider rates, supply, token balances or Stage1 account bytes are edited.
    await send([SystemProgram.transfer({ fromPubkey: admin.publicKey, toPubkey: reserve.publicKey, lamports: 1e9 })]);
    const epoch = (await connection.getEpochInfo('finalized')).epoch;
    const accounts = await capture(connection, programId, [admin.publicKey, fee.publicKey, operator.publicKey, publisher.publicKey,
      pool.publicKey, list.publicKey, reserve.publicKey, poolProgram]);
    const at = Number((await connection.getAccountInfo(anchor.web3.SYSVAR_CLOCK_PUBKEY, 'finalized'))!.data.readBigInt64LE(32));
    runtime = await replay(accounts, at + 1000, false, epoch + 1);
    connection = runtime.connection;
    program = new anchor.Program(program.idl, programId, new anchor.AnchorProvider(connection, initial.wallet, { commitment: 'finalized' }));
    const update = StakePoolInstruction.updateStakePoolBalance({ stakePool: pool.publicKey, withdrawAuthority: withdraw,
      validatorList: list.publicKey, reserveStake: reserve.publicKey, managerFeeAccount: managerFee, poolMint: mint.publicKey });
    update.programId = poolProgram;
    await send([update]);
    await execute(bootstrap, 'stage1-bootstrap', configInput, 'refresh');
    await execute(smoke, 'stage1-smoke', smokeInput, 'harvest');
    await execute(smoke, 'stage1-smoke', smokeInput, 'recipient');
    const saved = await capture(connection, programId, [admin.publicKey, fee.publicKey, operator.publicKey, publisher.publicKey,
      pool.publicKey, list.publicKey, reserve.publicKey, poolProgram]);
    await runtime.stop();
    runtime = await replay(saved, Number(configInput.seasonAnchor) + 604800 + 86400 + 1, false, epoch + 1);
    connection = runtime.connection;
    program = new anchor.Program(program.idl, programId, new anchor.AnchorProvider(connection, initial.wallet, { commitment: 'finalized' }));
    await execute(smoke, 'stage1-smoke', smokeInput, 'publish');
    await execute(smoke, 'stage1-smoke', smokeInput, 'claim');
    expect((await execute(smoke, 'stage1-smoke', smokeInput, 'claim')).plan.instructions).to.have.length(0);
  });
  it('operator skips an unfunded hill without books despite another hill holding this asset', async () => {
    const hash = (s: string | Buffer) => createHash('sha256').update(s).digest();
    const id = hash('local sparse SPL hill').subarray(0,16), profile = hash('sparse profile');
    const bytes = Buffer.alloc(64); bytes[0]=1; id.copy(bytes,1); bytes.writeUInt16BE(1,17); profile.copy(bytes,32);
    const digest=hash(bytes),climb=pda('climb',digest),hill=pda('s1v1_hill',id),city=pda('s1v1_city');
    await send([program.methods.registerRatifiedClimb({canonId:[...id],canonVersion:1,canonicalProfileHash:[...profile],commitmentHash:[...digest],
      recordContinuityPolicy:{newRecordBoard:{}},name:'Local sparse SPL hill',vertM:1000,distanceM:2000,avgGradientPct:500})
      .accounts({climb,climbVersionIndex:pda('climb_version',id,Buffer.from([0,1])),predecessorClimb:null,programConfig:pda('program_config'),admin:admin.publicKey,systemProgram:SystemProgram.programId})]);
    await execute(bootstrap,'stage1-bootstrap',{...configInput,climb:climb.toBase58()},'hill');
    expect((await program.account.stage1HillBond.fetch(hill)).admittedWeek.toString()).to.equal('1');
    const saved=await capture(connection,programId,[admin.publicKey,fee.publicKey,operator.publicKey,publisher.publicKey,pool.publicKey,list.publicKey,reserve.publicKey,poolProgram]);
    const epoch=(await connection.getEpochInfo('finalized')).epoch;
    await runtime.stop(); runtime=await replay(saved,Number(configInput.seasonAnchor)+11*604800+86400+1,false,epoch);
    connection=runtime.connection;program=new anchor.Program(program.idl,programId,new anchor.AnchorProvider(connection,initial.wallet,{commitment:'finalized'}));
    const input={...smokeInput,hill:hill.toBase58(),week:'10'};
    const plan=await execute(smoke,'stage1-smoke',input,'skip');
    expect(plan.plan.instructions).to.have.length(2);
    expect((await execute(smoke,'stage1-smoke',input,'skip')).plan.instructions).to.have.length(0);
    const cursor=pda('s1v1_cursor',hill.toBuffer(),mint.publicKey.toBuffer());
    expect((await program.account.stage1SettlementCursor.fetch(cursor)).nextWeek.toString()).to.equal('11');
    for(let w=1;w<=10;w++){
      const week=bn(w).toArrayLike(Buffer,'le',8);
      expect(await connection.getAccountInfo(pda('s1v1_funding',hill.toBuffer(),mint.publicKey.toBuffer(),week))).to.equal(null);
      expect(await connection.getAccountInfo(pda('s1v1_claims',hill.toBuffer(),mint.publicKey.toBuffer(),week))).to.equal(null);
    }
    expect((await program.account.stage1AssetConfig.fetch(asset())).ledger.held.toString()).to.equal('40');
  });

});
