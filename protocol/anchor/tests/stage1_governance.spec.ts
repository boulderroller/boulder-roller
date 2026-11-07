import * as anchor from '@coral-xyz/anchor';
import * as squads from '@sqds/multisig';
import { expect } from 'chai';
import { createHash } from 'crypto';
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from 'fs';
import { execFileSync } from 'child_process';
import { join } from 'path';
import { PublicKey, Keypair, SystemProgram, TransactionInstruction, TransactionMessage, VersionedTransaction,
  ComputeBudgetProgram, StakeProgram, Authorized, Lockup, SYSVAR_CLOCK_PUBKEY, SYSVAR_RENT_PUBKEY } from '@solana/web3.js';
import { TOKEN_PROGRAM_ID, createMint, getOrCreateAssociatedTokenAccount, createInitializeMint2Instruction,
  createAssociatedTokenAccountIdempotentInstruction, getAssociatedTokenAddressSync } from '@solana/spl-token';
import { StakePoolInstruction } from '@solana/spl-stake-pool';
import { capture, replay, pause, Capture } from './helpers/stage1_replay.js';
import { hash, bn } from '../scripts/stage1_operator.js';
import { runGovernance, DELAY, SQUADS, LOADER, vaultFor, setAuthority } from '../scripts/stage1_governance.js';
import { CURRENT_PROGRAM_VERSION, PREVIOUS_PROGRAM_VERSION } from '../generated-program-version.js';

if (process.env.STAGE1_GOVERNANCE === '1') describe(`Stage1 governance: actual Squads/mainnet dump, ${process.env.STAGE1_GOVERNANCE_BUILD} ELF on LOCALNET`, () => {
  const initial = anchor.AnchorProvider.env(), wallet = initial.wallet as anchor.Wallet;
  anchor.setProvider(initial);
  let connection = initial.connection, program: any = anchor.workspace.BoulderRollers;
  const programId = program.programId, idl = program.idl;
  const fee = Keypair.generate(), guardian = Keypair.generate(), publisher = Keypair.generate(), createKey = Keypair.generate();
  const members = Array.from({ length: 5 }, () => Keypair.generate());
  const multisig = squads.getMultisigPda({ createKey: createKey.publicKey })[0], vault = vaultFor(multisig);
  const pda = (seed: string, ...parts: Buffer[]) => PublicKey.findProgramAddressSync([Buffer.from(seed), ...parts], programId)[0];
  const config = pda('program_config'), city = pda('s1v1_city');
  let dataAddress: PublicKey, directory: string, serial = 0, runtime: any, index = 0n, bare: Capture;
  const poolProgram = new PublicKey('DPoo15wWDqpPJJtS2MUZ49aRxqz5ZaaJCJP4z8bLuib');
  // Preserve the actual test-pool program from the first replay, before a pool
  // is created later in the delayed administration case.
  const extraCapture: PublicKey[] = process.env.STAGE1_GOVERNANCE_BUILD === 'devnet' ? [poolProgram] : [];
  const identities = [wallet.payer, fee, guardian, publisher, createKey, ...members];
  const clock = async () => Number((await connection.getAccountInfo(SYSVAR_CLOCK_PUBKEY, 'processed'))!.data.readBigInt64LE(32));
  const common = () => ({ city, programConfig: config, adminAuthority: vault, admin: vault });
  const snapshot = async () => {
    const a = await capture(connection, programId, [...identities.map(k => k.publicKey), vault, SQUADS, ...extraCapture]);
    for (const { pubkey, account } of await connection.getProgramAccounts(SQUADS, 'processed')) a.set(pubkey.toBase58(), account);
    return a;
  };
  async function send(builders: any[], keys: Keypair[] = []) {
    const instructions = [ComputeBudgetProgram.setComputeUnitLimit({ units: 1_400_000 }),
      ComputeBudgetProgram.setComputeUnitPrice({ microLamports: ++serial }), ...await Promise.all(builders.map(b => b instanceof TransactionInstruction ? b : b.instruction()))];
    const block = await connection.getLatestBlockhash('processed');
    const tx = new VersionedTransaction(new TransactionMessage({ payerKey: fee.publicKey, recentBlockhash: block.blockhash, instructions }).compileToLegacyMessage());
    const required = tx.message.staticAccountKeys.slice(0, tx.message.header.numRequiredSignatures);
    tx.sign([fee, wallet.payer, ...keys].filter((s, i, all) => required.some(k => k.equals(s.publicKey)) && all.findIndex(x => x.publicKey.equals(s.publicKey)) === i));
    const signature = await connection.sendRawTransaction(tx.serialize(), { preflightCommitment: 'processed' });
    for (let n = 0; n < 1200; n++) { const status = (await connection.getSignatureStatuses([signature])).value[0];
      if (status) { expect(status.err).to.equal(null); return signature; } await pause(50); }
    throw new Error(`Local transaction did not process before its bounded wait: ${signature}; slot=${await connection.getSlot('processed')}; blockhashValid=${(await connection.isBlockhashValid(block.blockhash, { commitment: 'processed' })).value}`);
  }
  async function reject(action: Promise<unknown>, text: string) {
    try { await action; } catch (e: any) { expect(`${e.message}\n${e.logs?.join('\n')}`).to.include(text); return; }
    throw new Error(`Expected ${text}`);
  }
  async function tool(action: string, input: any, admin: PublicKey) {
    const inputFile = join(directory, `input-${++serial}.json`), planFile = join(directory, `plan-${serial}.json`);
    writeFileSync(inputFile, JSON.stringify({ multisig: multisig.toBase58(), ...input }));
    const options = { mode: 'plan', action, input: inputFile, cluster: 'localnet', rpc: connection.rpcEndpoint,
      'program-id': programId.toBase58(), 'program-interface': process.env.STAGE1_GOVERNANCE_BUILD === 'devnet' ? 'devnet' : 'mainnet',
      admin: admin.toBase58(), 'fee-payer': fee.publicKey.toBase58(), 'fee-payer-keypair': join(directory, 'fee.json'),
      'member-keypair': join(directory, `member-${members.findIndex(k => k.publicKey.toBase58() === input.member)}.json`),
      'admin-keypair': join(directory, 'admin.json'), 'creator-keypair': join(directory, 'member.json'), 'create-key-keypair': join(directory, 'create.json') };
    let output = ''; const log = console.log;
    try { console.log = (v: any) => { output += String(v); }; await runGovernance(options); }
    finally { console.log = log; }
    const plan = JSON.parse(output); writeFileSync(planFile, output);
    await runGovernance({ ...options, mode: 'submit', plan: planFile, digest: plan.digest });
    return plan;
  }
  async function propose(ixs: any[], configActions?: any[]) {
    const txIndex = ++index, creator = members[0].publicKey;
    const common = { multisigPda: multisig, transactionIndex: txIndex, creator, rentPayer: fee.publicKey };
    const create = configActions ? squads.instructions.configTransactionCreate({ ...common, actions: configActions })
      : squads.instructions.vaultTransactionCreate({ ...common, vaultIndex: 0, ephemeralSigners: 0,
        transactionMessage: new TransactionMessage({ payerKey: vault, recentBlockhash: PublicKey.default.toBase58(),
          instructions: await Promise.all(ixs.map(b => b instanceof TransactionInstruction ? b : b.instruction())) }) });
    await send([create, squads.instructions.proposalCreate(common)], [members[0]]);
    // Approval starts the wait, not creation or the first vote.
    const threshold = (await squads.accounts.Multisig.fromAccountAddress(connection, multisig, 'processed')).threshold;
    await send(members.slice(0, threshold).map(m => squads.instructions.proposalApprove({ multisigPda: multisig, transactionIndex: txIndex, member: m.publicKey })), members.slice(0, threshold));
    const proposal = await squads.accounts.Proposal.fromAccountAddress(connection, squads.getProposalPda({ multisigPda: multisig, transactionIndex: txIndex })[0], 'processed');
    expect(proposal.status.__kind).to.equal('Approved');
    return { index: txIndex, at: Number(String((proposal.status as any).timestamp)), config: !!configActions };
  }
  async function execution(p: any) {
    return p.config ? squads.instructions.configTransactionExecute({ multisigPda: multisig, transactionIndex: p.index,
      member: members[0].publicKey, rentPayer: fee.publicKey }) : (await squads.instructions.vaultTransactionExecute({
      connection, multisigPda: multisig, transactionIndex: p.index, member: members[0].publicKey })).instruction;
  }
  function use(c: any) { connection = c; program = new anchor.Program(idl, programId,
    new anchor.AnchorProvider(c, wallet, { commitment: 'processed', preflightCommitment: 'processed' })); }
  async function advance(accounts: Capture, at: number) {
    if (runtime) await runtime.stop(); runtime = await replay(accounts, at, false); use(runtime.connection);
  }
  async function exact(accounts: Capture, at: number, p: any, succeeds: boolean) {
    const saved = connection, r = await replay(accounts, at, true);
    try { use(r.connection); expect(await clock()).to.equal(at);
      const tx = new VersionedTransaction(new TransactionMessage({ payerKey: fee.publicKey,
        recentBlockhash: (await connection.getLatestBlockhash('processed')).blockhash,
        instructions: [ComputeBudgetProgram.setComputeUnitLimit({ units: 1_400_000 }), await execution(p)] }).compileToLegacyMessage());
      tx.sign([fee, members[0]]);
      const result = await connection.simulateTransaction(tx, { sigVerify: true, commitment: 'processed' });
      if (succeeds) expect(result.value.err, result.value.logs?.join('\n')).to.equal(null);
      else { expect(result.value.err).not.to.equal(null); expect(result.value.logs?.join('\n'), JSON.stringify(result.value.err)).to.include('TimeLockNotReleased'); }
    } finally { await r.stop(); use(saved); }
  }
  async function devnetPool() {
    const pool = Keypair.generate(), list = Keypair.generate(), mint = Keypair.generate(), reserve = Keypair.generate();
    const manager = wallet.publicKey, withdraw = PublicKey.findProgramAddressSync([pool.publicKey.toBuffer(), Buffer.from('withdraw')], poolProgram)[0];
    const managerFee = getAssociatedTokenAddressSync(mint.publicKey, manager);
    await send([SystemProgram.createAccount({ fromPubkey: fee.publicKey, newAccountPubkey: pool.publicKey, space: 611,
      lamports: await connection.getMinimumBalanceForRentExemption(611), programId: poolProgram }),
      SystemProgram.createAccount({ fromPubkey: fee.publicKey, newAccountPubkey: list.publicKey, space: 82,
        lamports: await connection.getMinimumBalanceForRentExemption(82), programId: poolProgram })], [pool, list]);
    await send([SystemProgram.createAccount({ fromPubkey: fee.publicKey, newAccountPubkey: mint.publicKey, space: 82,
      lamports: await connection.getMinimumBalanceForRentExemption(82), programId: TOKEN_PROGRAM_ID }),
      createInitializeMint2Instruction(mint.publicKey, 9, withdraw, null),
      createAssociatedTokenAccountIdempotentInstruction(fee.publicKey, managerFee, manager, mint.publicKey)], [mint]);
    await send(StakeProgram.createAccount({ fromPubkey: fee.publicKey, stakePubkey: reserve.publicKey,
      authorized: new Authorized(withdraw, withdraw), lockup: new Lockup(0, 0, PublicKey.default),
      lamports: await connection.getMinimumBalanceForRentExemption(StakeProgram.space) + 1 }).instructions, [reserve]);
    const data = Buffer.alloc(54); data.writeBigUInt64LE(1000n, 1); data.writeBigUInt64LE(1n, 9);
    data.writeBigUInt64LE(1000n, 17); data.writeBigUInt64LE(1n, 25); data.writeBigUInt64LE(1000n, 33); data.writeUInt32LE(1, 50);
    const keys = [pool.publicKey, manager, manager, withdraw, list.publicKey, reserve.publicKey, mint.publicKey, managerFee, TOKEN_PROGRAM_ID]
      .map((pubkey, i) => ({ pubkey, isSigner: i === 1, isWritable: [0, 4, 6, 7].includes(i) }));
    await send([new TransactionInstruction({ programId: poolProgram, keys, data })]);
    const deposit = StakePoolInstruction.depositSol({ stakePool: pool.publicKey, reserveStake: reserve.publicKey,
      fundingAccount: wallet.publicKey, destinationPoolAccount: managerFee, managerFeeAccount: managerFee, referralPoolAccount: managerFee,
      poolMint: mint.publicKey, lamports: 25e9, withdrawAuthority: withdraw });
    deposit.programId = poolProgram; await send([deposit]);
    extraCapture.push(pool.publicKey, list.publicKey, reserve.publicKey);
    return { mint: mint.publicKey, pool: pool.publicKey, refresh: async () => {
      const update = StakePoolInstruction.updateStakePoolBalance({ stakePool: pool.publicKey, withdrawAuthority: withdraw,
        validatorList: list.publicKey, reserveStake: reserve.publicKey, managerFeeAccount: managerFee, poolMint: mint.publicKey });
      update.programId = poolProgram; await send([update]);
    } };
  }
  before(async () => {
    expect(new URL(connection.rpcEndpoint).hostname).to.equal('127.0.0.1');
    directory = mkdtempSync('/tmp/stage1-governance-keys-');
    for (const [name, key] of Object.entries({ fee, admin: wallet.payer, member: members[0], create: createKey }))
      writeFileSync(join(directory, `${name}.json`), JSON.stringify([...key.secretKey]), { mode: 0o600 });
    await connection.confirmTransaction(await connection.requestAirdrop(fee.publicKey, 100e9), 'finalized');
    await send(identities.filter(k => !k.publicKey.equals(fee.publicKey)).map(k => SystemProgram.transfer({
      fromPubkey: fee.publicKey, toPubkey: k.publicKey, lamports: 1e9 })));
    dataAddress = new PublicKey((await connection.getAccountInfo(programId))!.data.subarray(4, 36));
    await connection.confirmTransaction(await connection.requestAirdrop(vault, 100e9), 'finalized');
    bare = await snapshot();
    for (let i = 0; i < members.length; i++) writeFileSync(join(directory, `member-${i}.json`), JSON.stringify([...members[i].secretKey]), { mode: 0o600 });
    const initialized = await send([program.methods.initializeProgramConfig(wallet.publicKey).accounts({ programConfig: config, program: programId,
      programData: dataAddress, admin: wallet.publicKey, systemProgram: SystemProgram.programId })]);
    await connection.confirmTransaction(initialized!, 'finalized');
  });
  after(async () => { if (runtime) await runtime.stop(); if (directory) rmSync(directory, { recursive: true, force: true }); });

  it('initializes ProgramConfig through the actual upgrade-authority vault, including rent payment', async () => {
    const original = connection;
    await advance(bare, await clock());
    try {
      const sqConfig = await squads.accounts.ProgramConfig.fromAccountAddress(connection, squads.getProgramConfigPda({})[0], 'processed');
      await send([squads.instructions.multisigCreateV2({ treasury: sqConfig.treasury, creator: members[0].publicKey,
        multisigPda: multisig, createKey: createKey.publicKey, configAuthority: null, timeLock: DELAY,
        threshold: 3, members: members.map(k => ({ key: k.publicKey, permissions: squads.types.Permissions.all() })), rentCollector: null })], [members[0], createKey]);
      await send([setAuthority(dataAddress, wallet.publicKey, vault)]);
      const p = await propose([program.methods.initializeProgramConfig(wallet.publicKey).accounts({ programConfig: config,
        program: programId, programData: dataAddress, admin: vault, systemProgram: SystemProgram.programId })]);
      await advance(await snapshot(), p.at + DELAY + 2);
      await send([await execution(p)], [members[0]]);
      expect((await program.account.programConfig.fetch(config)).adminAuthority.equals(vault)).to.equal(true);
    } finally { await runtime.stop(); runtime = undefined; use(original); index = 0n; }
  });
  it('creates 3-of-5, seven days, no config authority using reviewed plans and exact-byte finalized transport', async () => {
    const plan = await tool('create', { createKey: createKey.publicKey.toBase58(), creator: members[0].publicKey.toBase58(),
      members: members.map(k => k.publicKey.toBase58()), threshold: 3 }, wallet.publicKey);
    expect(plan.plan.report.timeLock).to.equal(DELAY);
  });
  it('atomically hands the actual loader authority and the shared Stage1 admin to the vault', async () => {
    const binaryLength = readFileSync(process.env.STAGE1_GOVERNANCE_BINARY!).length;
    await tool('extend-program', { binaryLength }, wallet.publicKey);
    await tool('handoff', { binaryLength }, wallet.publicKey);
    const plan = await tool('check', {}, vault);
    expect(plan.plan.report.currentAuthoritiesValid).to.equal(true);
    // The 1c parent still answers Anchor IDL instructions; the 0x4D release base
    // (version upgrade) is built with no-idl, so governance is fully applied.
    expect(plan.plan.report.sevenDayGovernanceApplied).to.equal(process.env.STAGE1_GOVERNANCE_INITIAL !== '1' || process.env.STAGE1_GOVERNANCE_VERSION === '1');
    await reject(send([program.methods.updateProgramConfig(wallet.publicKey, null).accounts({ programConfig: config, adminAuthority: wallet.publicKey, admin: wallet.publicKey })]), 'UnauthorizedAdmin');
  });
  it('admin initialization through Squads fails at 604799 seconds and succeeds at 604800; then commits', async () => {
    const p = await propose([program.methods.initCityConfig(bn(1791201600)).accounts({ ...common(), systemProgram: SystemProgram.programId })]);
    await reject(send([await execution(p)], [members[0]]), 'TimeLockNotReleased');
    const accounts = await snapshot();
    await exact(accounts, p.at + DELAY - 1, p, false); await exact(accounts, p.at + DELAY, p, true);
    await advance(accounts, p.at + DELAY + 2); await send([await execution(p)], [members[0]]);
    expect((await connection.getAccountInfo(city))!.data.readBigUInt64LE(9)).to.equal(10000000000n);
  });
  it('real loader upgrade from a vault-owned buffer waits 604800 seconds, then commits the reviewed binary', async () => {
    await reject(tool('extend-program', { binaryLength: readFileSync(process.env.STAGE1_GOVERNANCE_BINARY!).length }, vault), 'Extend before handoff');
    const buffer = Keypair.generate(), path = join(directory, 'buffer.json');
    writeFileSync(path, JSON.stringify([...buffer.secretKey]), { mode: 0o600 });
    execFileSync('solana', ['program', 'write-buffer', process.env.STAGE1_GOVERNANCE_BINARY!, '--url', connection.rpcEndpoint,
      '--keypair', join(directory, 'fee.json'), '--buffer', path, '--buffer-authority', join(directory, 'fee.json')], { stdio: 'pipe' });
    await send([setAuthority(buffer.publicKey, fee.publicKey, vault)]);
    const binaryHash = hash(readFileSync(process.env.STAGE1_GOVERNANCE_BINARY!));
    expect(hash((await connection.getAccountInfo(buffer.publicKey))!.data.subarray(37))).to.equal(binaryHash);
    const beforeCity = (await connection.getAccountInfo(city))?.data;
    const txIndex = ++index, proposalInput = { member: members[0].publicKey.toBase58(), transactionIndex: String(txIndex),
      buffer: buffer.publicKey.toBase58(), binarySha256: binaryHash, migrationNotes: 'Permissionless migrate-city after finalized upgrade; preserve every old city byte.' };
    // Wait for the buffer-authority transfer to become visible to finalized plans.
    while (!(await connection.getAccountInfo(buffer.publicKey, 'finalized'))!.data.subarray(5, 37).equals(vault.toBuffer())) await pause(100);
    await tool('propose-upgrade', proposalInput, vault);
    const review = await tool('check', { transactionIndex: String(txIndex) }, vault);
    const approvedInput = { ...proposalInput, transactionSha256: review.plan.report.proposal.transactionSha256 };
    for (const member of members.slice(0, 3)) await tool('approve', { ...approvedInput, member: member.publicKey.toBase58() }, vault);
    const proposal = await squads.accounts.Proposal.fromAccountAddress(connection, squads.getProposalPda({ multisigPda: multisig, transactionIndex: txIndex })[0], 'finalized');
    const p = { index: txIndex, at: Number(String((proposal.status as any).timestamp)), config: false };
    const accounts = await snapshot(); accounts.set(buffer.publicKey.toBase58(), (await connection.getAccountInfo(buffer.publicKey))!);
    if (runtime) await runtime.stop(); runtime = undefined;
    await exact(accounts, p.at + DELAY - 1, p, false); await exact(accounts, p.at + DELAY, p, true);
    await advance(accounts, p.at + DELAY + 2); await tool('execute', { ...approvedInput, kind: 'vault' }, vault);
    const upgraded = (await connection.getAccountInfo(dataAddress))!;
    expect(hash(upgraded.data.subarray(45, 45 + readFileSync(process.env.STAGE1_GOVERNANCE_BINARY!).length))).to.equal(binaryHash);
    expect(new PublicKey(upgraded.data.subarray(13, 45)).equals(vault)).to.equal(true);
    expect(await connection.getAccountInfo(buffer.publicKey)).to.equal(null);
    if (beforeCity) {
      await tool('migrate-city', {}, vault);
      const afterCity = (await connection.getAccountInfo(city))!.data;
      expect(afterCity.subarray(0, beforeCity.length).equals(beforeCity)).to.equal(true);
      expect((await program.account.stage1CityConfig.fetch(city)).intakePaused).to.equal(false);
      await tool('migrate-city', {}, vault); // idempotent, no second rent charge
      expect((await connection.getAccountInfo(city))!.data.equals(afterCity)).to.equal(true);
    }
  });
  // The previous ELF is the release base (build-stage1-initial.py --previous-version).
  if (process.env.STAGE1_GOVERNANCE_VERSION === '1') it(`advances actual 0x${PREVIOUS_PROGRAM_VERSION.toString(16)} ProgramConfig to 0x${CURRENT_PROGRAM_VERSION.toString(16)} through the vault after upgrade`, async () => {
    expect((await program.account.programConfig.fetch(config)).programVersion).to.equal(PREVIOUS_PROGRAM_VERSION);
    const p = await propose([program.methods.advanceProgramVersion(PREVIOUS_PROGRAM_VERSION, CURRENT_PROGRAM_VERSION).accounts({ programConfig: config, admin: vault })]);
    await advance(await snapshot(), p.at + DELAY + 2);
    await send([await execution(p)], [members[0]]);
    expect((await program.account.programConfig.fetch(config)).programVersion).to.equal(CURRENT_PROGRAM_VERSION);
  });
  it('config changes also wait; an old signer cannot bypass with direct config authority', async () => {
    await reject(send([squads.instructions.multisigSetTimeLock({ multisigPda: multisig, configAuthority: members[0].publicKey, timeLock: 0 })], [members[0]]), 'custom program error');
    const p = await propose([], [{ __kind: 'ChangeThreshold', newThreshold: 4 }]);
    const accounts = await snapshot();
    // Release the persistent replay port while running exact boundary probes.
    await runtime.stop(); runtime = undefined;
    await exact(accounts, p.at + DELAY - 1, p, false); await exact(accounts, p.at + DELAY, p, true);
    await advance(accounts, p.at + DELAY + 2); await send([await execution(p)], [members[0]]);
    expect((await squads.accounts.Multisig.fromAccountAddress(connection, multisig, 'processed')).threshold).to.equal(4);
    // Restore the threshold through the same delayed path, never an override.
    const q = await propose([], [{ __kind: 'ChangeThreshold', newThreshold: 3 }]);
    const approved = await squads.accounts.Proposal.fromAccountAddress(connection, squads.getProposalPda({ multisigPda: multisig, transactionIndex: q.index })[0], 'processed');
    await advance(await snapshot(), Number(String((approved.status as any).timestamp)) + DELAY + 2);
    await send([await execution(q)], [members[0]]);
  });
  it('vault signs ProgramConfig mutations and all normal Stage1 administration, including custody rent', async () => {
    const mint = new PublicKey('J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn');
    const state = await program.account.programConfig.fetch(config);
    const params = Object.fromEntries(['vaultCreationDung', 'vaultCreationCal', 'harvestFeeBps', 'minterRightsEpochs', 'localLegendTermEpochs', 'epochsPerHalving'].map(k => [k, state[k]]));
    const hashBytes = (s: string) => createHash('sha256').update(s).digest();
    const id = hashBytes('governance-canon').subarray(0, 16), profile = hashBytes('governance-profile');
    const commitment = Buffer.alloc(64); commitment[0] = 1; id.copy(commitment, 1); commitment.writeUInt16BE(1, 17); profile.copy(commitment, 32);
    const digest = hashBytes(commitment as any), climb = pda('climb', digest), hill = pda('s1v1_hill', id);
    const usdc = await createMint(connection, fee, fee.publicKey, null, 6);
    const treasury = (await getOrCreateAssociatedTokenAccount(connection, fee, usdc, vault, true)).address;
    const calls = [
      program.methods.configureUsdcPayment(bn(1000000)).accounts({ programConfig: config, admin: vault, usdcMint: usdc, usdcTreasuryTokenAccount: treasury }),
      program.methods.updateProgramConfig(null, wallet.publicKey).accounts({ programConfig: config, adminAuthority: vault, admin: vault }),
      program.methods.updateProtocolParameters(params).accounts({ programConfig: config, adminAuthority: vault, admin: vault }),
      program.methods.configureMints(mint, mint).accounts({ programConfig: config, adminAuthority: vault, admin: vault }),
      program.methods.configureTreasuryAccounts(vault, vault).accounts({ programConfig: config, adminAuthority: vault, admin: vault }),
      program.methods.setStage1Publisher(publisher.publicKey).accounts(common()),
      program.methods.setStage1Guardian(guardian.publicKey).accounts(common()),
      program.methods.resumeStage1Intake().accounts(common()),
      program.methods.resumeStage1Settlement().accounts(common()),
    ];
    let refreshPool: (() => Promise<void>) | undefined;
    if (process.env.STAGE1_GOVERNANCE_BUILD === 'devnet') {
      calls.push(program.methods.registerStage1Cash().accounts({ ...common(), cash: pda('s1v1_cash'),
        asset: pda('s1v1_asset', usdc.toBuffer()), mint: usdc, earnings: pda('s1v1_earnings', usdc.toBuffer()),
        tokenProgram: TOKEN_PROGRAM_ID, systemProgram: SystemProgram.programId }));
      const pool = await devnetPool();
      refreshPool = pool.refresh;
      const accounts = { ...common(), asset: pda('s1v1_asset', pool.mint.toBuffer()), mint: pool.mint,
        earnings: pda('s1v1_earnings', pool.mint.toBuffer()), tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: SystemProgram.programId, rent: SYSVAR_RENT_PUBKEY };
      calls.push(program.methods.registerStage1TestPool().accounts({ ...accounts, testPool: pda('s1v1_test_pool'), provider: pool.pool }));
      calls.push(program.methods.configureAsset(false).accounts(accounts));
    } else calls.push(program.methods.configureAsset(false).accounts({ ...common(),
      asset: pda('s1v1_asset', mint.toBuffer()), mint, earnings: pda('s1v1_earnings', mint.toBuffer()),
      tokenProgram: TOKEN_PROGRAM_ID, systemProgram: SystemProgram.programId, rent: SYSVAR_RENT_PUBKEY }));
    calls.push(program.methods.registerRatifiedClimb({ canonId: [...id], canonVersion: 1, canonicalProfileHash: [...profile],
      commitmentHash: [...digest], recordContinuityPolicy: { newRecordBoard: {} }, name: 'Local governance hill', vertM: 1000, distanceM: 2000, avgGradientPct: 500 })
      .accounts({ climb, climbVersionIndex: pda('climb_version', id, Buffer.from([0, 1])), predecessorClimb: null,
        programConfig: config, adminAuthority: vault, admin: vault, systemProgram: SystemProgram.programId }));
    calls.push(program.methods.initHillBond().accounts({ ...common(), climb, hill, systemProgram: SystemProgram.programId }));
    const ps = [];
    for (const call of calls) ps.push(await propose([call]));
    await advance(await snapshot(), Math.max(...ps.map(p => p.at)) + DELAY + 2);
    // Provider freshness is maintained by its real permissionless instruction,
    // including when the delayed replay crosses an epoch; no pool bytes change
    // outside a transaction.
    if (refreshPool) await refreshPool();
    for (const p of ps) await send([await execution(p)], [members[0]]);
    expect((await program.account.stage1HillBond.fetch(hill)).climb.equals(climb)).to.equal(true);
    expect((await program.account.stage1CityConfig.fetch(city)).guardian.equals(guardian.publicKey)).to.equal(true);
  });
  it('guardian pauses and resumes instantly, cannot rotate roles, change publisher, config or transfer admin', async () => {
    await send([program.methods.pauseStage1Intake().accounts({ city, guardian: guardian.publicKey }),
      program.methods.pauseStage1Settlement().accounts({ city, guardian: guardian.publicKey })], [guardian]);
    expect((await program.account.stage1CityConfig.fetch(city)).intakePaused).to.equal(true);
    await send([program.methods.resumeStage1Intake().accounts({...common(), admin: guardian.publicKey}), program.methods.resumeStage1Settlement().accounts({...common(), admin: guardian.publicKey})], [guardian]);
    expect((await program.account.stage1CityConfig.fetch(city)).intakePaused).to.equal(false);
    await send([program.methods.pauseStage1Intake().accounts({city, guardian: guardian.publicKey}), program.methods.pauseStage1Settlement().accounts({city, guardian: guardian.publicKey})], [guardian]);
    for (const call of [program.methods.setStage1Guardian(fee.publicKey), program.methods.setStage1Publisher(fee.publicKey)])
      await reject(send([call.accounts({ ...common(), admin: guardian.publicKey })], [guardian]), 'Stage1Unauthorized');
    await reject(send([program.methods.updateProgramConfig(guardian.publicKey, null).accounts({ programConfig: config, adminAuthority: guardian.publicKey, admin: guardian.publicKey })], [guardian]), 'UnauthorizedAdmin');
    await reject(send([program.methods.pauseStage1Intake().accounts({ city, guardian: wallet.publicKey })]), 'Stage1Unauthorized');
    const txIndex = ++index, input = { member: members[0].publicKey.toBase58(), transactionIndex: String(txIndex),
      instructions: [(await program.methods.resumeStage1Intake().accounts(common()).instruction()),
        (await program.methods.resumeStage1Settlement().accounts(common()).instruction())].map(ix => ({
        program: ix.programId.toBase58(), data: ix.data.toString('base64'),
        keys: ix.keys.map(k => ({ key: k.pubkey.toBase58(), signer: k.isSigner, writable: k.isWritable })) })) };
    await tool('propose-admin', input, vault);
    const review = await tool('check', { transactionIndex: String(txIndex) }, vault);
    const approval = { member: input.member, transactionIndex: String(txIndex), transactionSha256: review.plan.report.proposal.transactionSha256 };
    for (const member of members.slice(0, 3)) await tool('approve', { ...approval, member: member.publicKey.toBase58() }, vault);
    await reject(tool('execute', { ...approval, kind: 'vault' }, vault), 'Seven-day wait');
    const proposal = await squads.accounts.Proposal.fromAccountAddress(connection, squads.getProposalPda({ multisigPda: multisig, transactionIndex: txIndex })[0], 'finalized');
    await advance(await snapshot(), Number(String((proposal.status as any).timestamp)) + DELAY + 2);
    await tool('execute', { ...approval, kind: 'vault' }, vault);
    expect((await program.account.stage1CityConfig.fetch(city)).intakePaused).to.equal(false);
    expect((await program.account.stage1CityConfig.fetch(city)).settlementPaused).to.equal(false);
  });
  it('reports stale approved hazards, cancels approvals before signer removal, and rejects active proposals', async () => {
    const inert = ++index, former = members[2].publicKey;
    await send([squads.instructions.vaultTransactionCreate({ multisigPda: multisig, transactionIndex: inert, creator: former,
      rentPayer: fee.publicKey, vaultIndex: 0, ephemeralSigners: 0, transactionMessage: new TransactionMessage({payerKey:vault,
        recentBlockhash:PublicKey.default.toBase58(),instructions:[await program.methods.setStage1Publisher(publisher.publicKey).accounts(common()).instruction()]}) }),
      squads.instructions.proposalCreate({multisigPda:multisig,transactionIndex:inert,creator:former})], [members[2]]);
    const old = await propose([program.methods.setStage1Publisher(publisher.publicKey).accounts(common())]);
    const unsafe = await propose([], [{ __kind: 'SetTimeLock', newTimeLock: 0 }]);
    // A real configuration execution makes older proposals stale. Approved
    // proposals nevertheless remain executable: status must retain them.
    const revision = await propose([], [{ __kind: 'ChangeThreshold', newThreshold: 3 }]);
    await advance(await snapshot(), revision.at + DELAY + 2);
    const revisionSignature = await send([await execution(revision)], [members[0]]);
    expect((await connection.confirmTransaction(revisionSignature, 'finalized')).value.err).to.equal(null);
    const status = await tool('check', { transactionIndex: String(unsafe.index) }, vault);
    expect(status.plan.report.sevenDayGovernanceApplied).to.equal(false);
    const flagged = status.plan.report.pendingProposals.find((p: any) => p.transactionIndex === String(unsafe.index));
    expect(flagged).to.include({ stale: true, admitted: false, status: 'Approved' });
    expect(flagged.actions[0]).to.include({ __kind: 'SetTimeLock', newTimeLock: 0 });
    expect(flagged.reason).to.include('Unadmitted config action');
    for (const member of members.slice(0, 3)) await tool('cancel', { member: member.publicKey.toBase58(),
      transactionIndex: String(unsafe.index), transactionSha256: flagged.transactionSha256 }, vault);
    await reject(send([await execution(unsafe)], [members[0]]), 'InvalidProposalStatus');
    const active = ++index, creator = members[0].publicKey;
    await send([squads.instructions.configTransactionCreate({ multisigPda: multisig, transactionIndex: active, creator,
      rentPayer: fee.publicKey, actions: [{ __kind: 'SetTimeLock', newTimeLock: 0 }] }),
      squads.instructions.proposalCreate({ multisigPda: multisig, transactionIndex: active, creator })], [members[0]]);
    while ((await squads.accounts.Multisig.fromAccountAddress(connection, multisig, 'finalized')).transactionIndex.toString() !== String(active)) await pause(100);
    const review = await tool('check', { transactionIndex: String(active) }, vault);
    for (const member of members.slice(0, 3)) await tool('reject', { member: member.publicKey.toBase58(), transactionIndex: String(active),
      transactionSha256: review.plan.report.proposal.transactionSha256 }, vault);
    const removal = { transactionIndex: String(index + 1n), member: members[0].publicKey.toBase58(),
      actions: [{ kind: 'remove-member', key: members[2].publicKey.toBase58() }] };
    // The stale approved proposal is independently unsafe, even before the
    // narrower departing-signer check is reached.
    await reject(tool('propose-config', removal, vault), 'unsafe pending proposals');
    const oldReview = await tool('check', { transactionIndex: String(old.index) }, vault);
    for (const member of members.slice(0, 3)) await tool('cancel', { member: member.publicKey.toBase58(), transactionIndex: String(old.index),
      transactionSha256: oldReview.plan.report.proposal.transactionSha256 }, vault);
    await tool('propose-config', removal, vault); ++index;
    const removalReview = await tool('check', { transactionIndex: String(index) }, vault);
    const approval = { ...removal, transactionSha256: removalReview.plan.report.proposal.transactionSha256 };
    for (const member of [members[0], members[1], members[3]]) await tool('approve', { ...approval, member: member.publicKey.toBase58() }, vault);
    const approved = await squads.accounts.Proposal.fromAccountAddress(connection,
      squads.getProposalPda({multisigPda:multisig,transactionIndex:index})[0], 'finalized');
    await advance(await snapshot(), Number(String((approved.status as any).timestamp)) + DELAY + 2);
    await tool('execute', { ...approval, kind: 'config' }, vault);
    expect((await squads.accounts.Multisig.fromAccountAddress(connection,multisig,'finalized')).members.some(m=>m.key.equals(members[2].publicKey))).to.equal(false);
    await reject(send([await execution(old)], [members[0]]), 'InvalidProposalStatus');
    expect((await tool('check', {}, vault)).plan.report.sevenDayGovernanceApplied).to.equal(true);
  });
  it('legacy backend smoke/setup helpers cannot deserialize any Stage1 account; state/time terms are unchanged', async () => {
    // Select by coder discriminator, not account length or invented fixture bytes.
    const accounts = (await connection.getProgramAccounts(programId)).filter(({ account }) => idl.accounts.some(a =>
      a.name.startsWith('Stage1') && anchor.BorshAccountsCoder.accountDiscriminator(a.name).equals(account.data.subarray(0, 8))));
    expect(accounts.length).to.be.greaterThan(1);
    for (const target of accounts) {
      for (const call of [program.methods.adminSeedVaultCompletionSummary(bn(1), 1, wallet.publicKey),
        program.methods.adminReplaceVaultLeaderboard([]),
        program.methods.adminActivateVault(bn(1), bn(1), wallet.publicKey, 1, bn(0), 1, bn(0), 1, 1, Array(32).fill(1))]) {
        const ix = await call.accounts({ vault: target.pubkey, vaultActivation: target.pubkey, vaultStake: target.pubkey, vaultLeaderboard: target.pubkey, systemProgram: SystemProgram.programId,
          programConfig: config, authority: wallet.publicKey }).instruction();
        await reject(send([ix]), 'AccountDiscriminatorMismatch');
      }
      const id = bn(887766), activation = pda('vault_activation', id.toArrayLike(Buffer, 'le', 8));
      await reject(send([program.methods.adminBackfillVaultActivation(id).accounts({ vault: target.pubkey,
        vaultActivation: activation, programConfig: config, authority: wallet.publicKey, systemProgram: SystemProgram.programId })]), 'InvalidVault');
      expect((await connection.getAccountInfo(target.pubkey))!.data.equals(target.account.data)).to.equal(true);
    }
    // Localnet-only rate setter and test setup helpers are absent from deployable builds.
    for (const name of ['set_test_lst_rate', 'admin_override_open_settlement_week', 'admin_seed_pending_rewards', 'admin_override_stake_eligibility']) {
      const raw = new TransactionInstruction({ programId, data: Buffer.concat([createHash('sha256').update(`global:${name}`).digest().subarray(0, 8), Buffer.alloc(24)]), keys: [] });
      await reject(send([raw]), 'custom program error: 0x65');
    }
    expect((await program.account.stage1CityConfig.fetch(city)).seasonAnchor.toNumber()).to.equal(1791201600);
  });

});
