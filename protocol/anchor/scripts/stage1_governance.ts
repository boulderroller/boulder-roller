// Explicit-input governance, using the same reviewed-plan/exact-byte transport as 1c.
import * as squads from '@sqds/multisig';
import { BorshInstructionCoder } from '@coral-xyz/anchor';
import { PublicKey, SystemProgram, TransactionInstruction, TransactionMessage,
  SYSVAR_CLOCK_PUBKEY, SYSVAR_RENT_PUBKEY, VersionedTransaction } from '@solana/web3.js';
import { pathToFileURL } from 'url';
import { CURRENT_PROGRAM_VERSION, PREVIOUS_PROGRAM_VERSION } from '../generated-program-version.js';
import { args } from './stage1_operator.js';
import { Operator, Operation, pk, hash, requireThat, runOperator, instructionJson } from './stage1_operator.js';

export const DELAY = 604800;
export const SQUADS = squads.PROGRAM_ID;
export const LOADER = pk('BPFLoaderUpgradeab1e11111111111111111111111');
export const ADMIN_CALLS = new Set([
  'initializeProgramConfig', 'updateProgramConfig', 'advanceProgramVersion', 'updateProtocolParameters',
  'configureMints', 'configureTreasuryAccounts', 'configureUsdcPayment',
  'initCityConfig', 'configureAsset', 'initHillBond', 'setStage1Publisher', 'registerStage1TestPool',
  'setStage1Guardian', 'setStage1Registrar', 'configureStage1Dung', 'resumeStage1Intake', 'resumeStage1Settlement', 'registerStage1Cash', 'registerRatifiedClimb',
]);
export function vaultFor(multisig: PublicKey) { return squads.getVaultPda({ multisigPda: multisig, index: 0 })[0]; }
export function setAuthority(account: PublicKey, authority: PublicKey, next: PublicKey) {
  return new TransactionInstruction({ programId: LOADER, data: Buffer.from([4, 0, 0, 0]), keys: [
    { pubkey: account, isWritable: true, isSigner: false }, { pubkey: authority, isWritable: false, isSigner: true },
    { pubkey: next, isWritable: false, isSigner: false },
  ] });
}
export function upgradeInstruction(program: PublicKey, data: PublicKey, buffer: PublicKey, vault: PublicKey) {
  return new TransactionInstruction({ programId: LOADER, data: Buffer.from([3, 0, 0, 0]), keys: [
    { pubkey: data, isWritable: true, isSigner: false }, { pubkey: program, isWritable: true, isSigner: false },
    { pubkey: buffer, isWritable: true, isSigner: false }, { pubkey: vault, isWritable: true, isSigner: false },
    { pubkey: SYSVAR_RENT_PUBKEY, isWritable: false, isSigner: false },
    { pubkey: SYSVAR_CLOCK_PUBKEY, isWritable: false, isSigner: false }, { pubkey: vault, isWritable: false, isSigner: true },
  ] });
}
async function owned(r: Operator, key: PublicKey, owner: PublicKey) {
  const account = await r.read(key);
  requireThat(account && account.owner.equals(owner) && !account.executable, `Invalid account owner: ${key}`);
  return account;
}
export async function multisigState(r: Operator, address: PublicKey) {
  const data = (await owned(r, address, SQUADS)).data;
  requireThat(data.subarray(0, 8).equals(Buffer.from(squads.accounts.multisigDiscriminator)), 'Invalid multisig discriminator');
  const state = squads.accounts.Multisig.deserialize(data)[0];
  const [expected, bump] = squads.getMultisigPda({ createKey: state.createKey });
  requireThat(address.equals(expected) && state.bump === bump, 'Invalid multisig PDA');
  return state;
}
export function assertConfigActions(actions: squads.types.ConfigAction[], guardian = PublicKey.default, registrar = PublicKey.default) {
  requireThat(actions.length > 0 && actions.every(a => ['AddMember', 'RemoveMember', 'ChangeThreshold'].includes(a.__kind)), 'Unadmitted config action');
  for (const action of actions) {
    if (action.__kind === 'AddMember') {
      requireThat(action.newMember.permissions.mask === 7, 'Unsupported member permissions');
      requireThat(guardian.equals(PublicKey.default) || !action.newMember.key.equals(guardian), 'Guardian must remain separate from multisig members');
      requireThat(registrar.equals(PublicKey.default) || !action.newMember.key.equals(registrar), 'Registrar must remain separate from multisig members');
    }
    if (action.__kind === 'ChangeThreshold') requireThat(Number.isInteger(action.newThreshold)
      && action.newThreshold > 0 && action.newThreshold <= 65535, 'Invalid threshold');
  }
}
export function assertSettings(state: any, guardian = PublicKey.default, registrar = PublicKey.default) {
  requireThat(state.configAuthority.equals(PublicKey.default), 'Separate config authority bypasses the wait');
  requireThat(state.timeLock === DELAY, 'Multisig must have a seven-day time_lock');
  const members = state.members;
  requireThat(Number.isInteger(state.threshold) && state.threshold > 0 && state.threshold <= 65535 && state.threshold <= members.length
    && new Set(members.map((m: any) => m.key.toBase58())).size === members.length
    && members.every((m: any) => m.permissions.mask === 7), 'Invalid members/threshold/permissions');
  requireThat(guardian.equals(PublicKey.default) || !members.some((m: any) => m.key.equals(guardian)),
    'Guardian must remain separate from multisig members');
  requireThat(registrar.equals(PublicKey.default) || !members.some((m: any) => m.key.equals(registrar)),
    'Registrar must remain separate from multisig members');
}
async function programData(r: Operator) {
  const executable = await r.read(r.programId);
  requireThat(executable?.executable && executable.owner.equals(LOADER) && executable.data.readUInt32LE(0) === 2,
    'Expected an upgradeable program');
  const address = new PublicKey(executable.data.subarray(4, 36));
  const account = await owned(r, address, LOADER);
  requireThat(account.data.length >= 45 && account.data.readUInt32LE(0) === 3 && account.data[12] === 1,
    'Missing upgrade authority');
  return { address, account, authority: new PublicKey(account.data.subarray(13, 45)) };
}
async function waitForVisibleCode(r: Operator, data: Buffer) {
  const deployedAt = Number(data.readBigUInt64LE(4));
  for (let attempt = 0; attempt < 100; attempt++) {
    if (await r.connection.getSlot('finalized') > deployedAt) return;
    await new Promise(resolve => setTimeout(resolve, 200));
  }
  throw new Error('Loader change finalized; wait for the next finalized slot before calling the program');
}
export async function readCity(r: Operator) {
  const account = await r.read(r.pda('s1v1_city'));
  if (!account) return null;
  const size = r.program.account.stage1CityConfig.size;
  requireThat(size === 963 && account.owner.equals(r.programId) && !account.executable
    && [881, 897, 914, 915, 931, 963].includes(account.data.length), 'Unsupported Stage1 city layout');
  const legacy = account.data.length !== size;
  const bytes = Buffer.alloc(size);
  account.data.copy(bytes, 0, 0, 881);
  if ([897, 931, 963].includes(account.data.length)) account.data.copy(bytes);
  if ([914, 915].includes(account.data.length)) account.data.copy(bytes, 897, 881);
  // Decode a local view only. This does not write or attest migrated chain state.
  const decoded: any = r.program.coder.accounts.decode('Stage1CityConfig', bytes);
  return { legacy, account, decoded, state: [881, 897].includes(account.data.length) ? null : decoded };
}
// This empty IDL payload cannot reach an IDL mutation, even on historical code.
export async function idlStatus(r: Operator) {
  try {
    const latest = await r.connection.getLatestBlockhash('finalized');
    const tx = new VersionedTransaction(new TransactionMessage({ payerKey: r.feePayer, recentBlockhash: latest.blockhash,
      instructions: [new TransactionInstruction({ programId: r.programId, keys: [], data: Buffer.from('40f4bc78a7e9690a', 'hex') })]
    }).compileToLegacyMessage());
    const result = await r.connection.simulateTransaction(tx, { sigVerify: false, commitment: 'finalized', minContextSlot: r.floor });
    const error: any = result.value.err;
    const code = error?.InstructionError?.[0] === 0 ? error.InstructionError[1]?.Custom : undefined;
    return { idlInstructionsDisabled: code === 1000, idlProbe: code === 1000 ? 'disabled' : code === 102 ? 'enabled' : 'unknown',
      idlProbeError: code === 1000 || code === 102 ? null : JSON.stringify(error) };
  } catch (error: any) { return { idlInstructionsDisabled: false, idlProbe: 'unknown', idlProbeError: error.message }; }
}
export const EXTEND_CHECKED_FEATURE = pk('2oMRZEDWT2tqtYMofhmmfQ8SsjqUFzT6sYXppQDavxwz');
export async function checkedExtension(r: Operator) {
  const feature = await r.read(EXTEND_CHECKED_FEATURE);
  if (!feature) return false;
  requireThat(feature.owner.equals(pk('Feature111111111111111111111111111111111111')) && !feature.executable
    && feature.data.length === 9 && [0, 1].includes(feature.data[0]), 'Invalid checked-extension feature account');
  if (feature.data[0] === 0) return false;
  return feature.data.readBigUInt64LE(1) <= BigInt(await r.connection.getSlot('finalized'));
}
export async function governanceCheck(r: Operator, input: any) {
  const address = pk(input.multisig), state = await multisigState(r, address), vault = vaultFor(address);
  const data = await programData(r), config: any = await r.fetch('ProgramConfig', r.pda('program_config'));
  const cityInfo = await readCity(r), city: any = cityInfo?.state;
  // Spending limits bypass ordinary vault voting. Report them and refuse admission.
  const query = squads.accounts.SpendingLimit.gpaBuilder(SQUADS)
    .addFilter('accountDiscriminator', squads.accounts.spendingLimitDiscriminator).addFilter('multisig', address);
  const limits = await r.connection.getProgramAccounts(SQUADS, { ...query.config, commitment: 'finalized', minContextSlot: r.floor });
  for (const limit of limits) await r.read(limit.pubkey);
  const guardianRolesSeparate = !city || city.guardian.equals(PublicKey.default)
    || ![vault, config.adminAuthority, config.backendAuthority, city.publisher, city.registrar ?? PublicKey.default, ...state.members.map(m => m.key)].some(k => k.equals(city.guardian));
  const registrar = city?.registrar ?? PublicKey.default;
  const registrarRolesSeparate = registrar.equals(PublicKey.default)
    || ![vault, config.adminAuthority, config.backendAuthority, city.publisher, city.guardian, ...state.members.map(m => m.key)].some(k => k.equals(registrar));
  let supportedSettings = true;
  try { assertSettings(state, city?.guardian, city?.registrar); } catch { supportedSettings = false; }
  const currentAuthoritiesValid = supportedSettings && guardianRolesSeparate && registrarRolesSeparate && state.timeLock === DELAY && state.configAuthority.equals(PublicKey.default)
    && data.authority.equals(vault) && config.adminAuthority.equals(vault) && limits.length === 0;
  const queryProposals = squads.accounts.Proposal.gpaBuilder(SQUADS)
    .addFilter('accountDiscriminator', squads.accounts.proposalDiscriminator).addFilter('multisig', address);
  const found = await r.connection.getProgramAccounts(SQUADS, { ...queryProposals.config, commitment: 'finalized', minContextSlot: r.floor });
  const pendingProposals: any[] = [];
  for (const { pubkey } of found) {
    const proposal = await readProposal(r, address, pubkey);
    if (!['Active', 'Approved'].includes(proposal.status.__kind)) continue;
    const index = BigInt(String(proposal.transactionIndex));
    pendingProposals.push({ ...await reviewProposal(r, address, index), stale: index <= BigInt(String(state.staleTransactionIndex)) });
  }
  pendingProposals.sort((a, b) => BigInt(a.transactionIndex) < BigInt(b.transactionIndex) ? -1 : 1);
  const pendingProposalsSafe = pendingProposals.every(pendingProposalSafe);
  const idl = await idlStatus(r);
  const valid = currentAuthoritiesValid && pendingProposalsSafe && idl.idlInstructionsDisabled && !cityInfo?.legacy;
  return { multisig: address.toBase58(), vault: vault.toBase58(), threshold: state.threshold,
    members: state.members.map(m => ({ key: m.key.toBase58(), permissions: m.permissions.mask })),
    timeLockSeconds: state.timeLock, configAuthority: state.configAuthority.toBase58(), spendingLimits: limits.length, supportedSettings,
    transactionIndex: String(state.transactionIndex), staleTransactionIndex: String(state.staleTransactionIndex),
    programData: data.address.toBase58(), upgradeAuthority: data.authority.toBase58(), admin: config.adminAuthority.toBase58(),
    stage1Admin: config.adminAuthority.toBase58(), programVersion: config.programVersion, guardianRolesSeparate, registrarRolesSeparate, registrar: registrar.toBase58(), cityNeedsMigration: cityInfo?.legacy ?? false, guardian: city?.guardian.toBase58() ?? null,
    intakePaused: city?.intakePaused ?? null, settlementPaused: cityInfo?.legacy ? null : city?.settlementPaused ?? null,
    currentAuthoritiesValid, pendingProposals, pendingProposalsSafe, ...idl, sevenDayGovernanceApplied: valid };
}
export function adminInstructions(r: Operator, raw: any[], vault: PublicKey) {
  requireThat(Array.isArray(raw) && raw.length > 0, 'Explicit admin instructions required');
  return raw.map(item => {
    requireThat(pk(item.program).equals(r.programId), 'Admin call must target BoulderRoller');
    const ix = new TransactionInstruction({ programId: r.programId, data: Buffer.from(item.data, 'base64'),
      keys: item.keys.map((k: any) => ({ pubkey: pk(k.key), isSigner: k.signer === true, isWritable: k.writable === true })) });
    const decoded = (r.program.coder.instruction as BorshInstructionCoder).decode(ix.data);
    requireThat(decoded && ADMIN_CALLS.has(decoded.name), 'Instruction is not an admitted admin operation');
    if (decoded.name === 'updateProgramConfig') {
      const next = (decoded.data as any).newAdmin;
      requireThat(!next || next.equals(vault), 'Admin authority must remain the reviewed vault');
    }
    requireThat(ix.keys.some(k => k.isSigner && k.pubkey.equals(vault))
      && ix.keys.filter(k => k.isSigner).every(k => k.pubkey.equals(vault)), 'Admin must be the only inner signer and must be the vault');
    // Re-encoding rejects trailing/ambiguous payload bytes.
    requireThat(r.program.coder.instruction.encode(decoded.name, decoded.data).equals(ix.data), 'Noncanonical admin instruction');
    return ix;
  });
}
export function configActions(input: any, guardian = PublicKey.default, registrar = PublicKey.default): squads.types.ConfigAction[] {
  requireThat(Array.isArray(input.actions) && input.actions.length > 0, 'Explicit config actions required');
  const actions: squads.types.ConfigAction[] = input.actions.map((action: any) => {
    switch (action.kind) {
      case 'add-member': return { __kind: 'AddMember', newMember: { key: pk(action.key), permissions: squads.types.Permissions.all() } };
      case 'remove-member': return { __kind: 'RemoveMember', oldMember: pk(action.key) };
      case 'threshold': requireThat(Number.isInteger(action.threshold) && action.threshold > 0 && action.threshold <= 65535, 'Invalid threshold');
        return { __kind: 'ChangeThreshold', newThreshold: action.threshold };
      default: throw new Error('Only member/threshold changes admitted; no delay reduction, spending limits or config authority');
    }
  });
  assertConfigActions(actions, guardian, registrar);
  return actions;
}
export async function guardRoleChanges(r: Operator, instructions: TransactionInstruction[], memberKeys: PublicKey[] = []) {
  const city = await readCity(r);
  const config = await r.fetch('ProgramConfig', r.pda('program_config'));
  let guardian = city?.state?.guardian ?? PublicKey.default;
  let publisher = city?.decoded?.publisher ?? PublicKey.default;
  let registrar = city?.decoded?.registrar ?? PublicKey.default;
  let backend = config.backendAuthority;
  for (const ix of instructions) {
    const call = (r.program.coder.instruction as BorshInstructionCoder).decode(ix.data)!;
    const data: any = call.data;
    if (call.name === 'setStage1Guardian') guardian = data.guardian;
    if (call.name === 'setStage1Publisher') publisher = data.publisher;
    if (call.name === 'setStage1Registrar') registrar = data.registrar;
    if (call.name === 'updateProgramConfig' && data.newBackend) backend = data.newBackend;
    requireThat(guardian.equals(PublicKey.default)
      || ![backend, publisher, registrar, config.adminAuthority, ...memberKeys].some(k => k.equals(guardian)),
      'Guardian must remain separate from admin, publisher, registrar, backend authority and multisig members');
    requireThat(registrar.equals(PublicKey.default)
      || ![backend, publisher, guardian, config.adminAuthority, ...memberKeys].some(k => k.equals(registrar)),
      'Registrar must remain separate from other authority roles and multisig members');
  }
}
// Decode the stored message for each voter/executor, including externally created
// proposals. A digest alone is not a human review of a transaction.
async function readProposal(r: Operator, address: PublicKey, key: PublicKey) {
  const bytes = (await owned(r, key, SQUADS)).data;
  requireThat(bytes.subarray(0, 8).equals(Buffer.from(squads.accounts.proposalDiscriminator)), 'Invalid proposal discriminator');
  const proposal = squads.accounts.Proposal.deserialize(bytes)[0];
  const [expected, bump] = squads.getProposalPda({ multisigPda: address, transactionIndex: BigInt(String(proposal.transactionIndex)) });
  requireThat(proposal.multisig.equals(address) && key.equals(expected) && proposal.bump === bump, 'Wrong proposal identity');
  return proposal;
}
export async function reviewProposal(r: Operator, address: PublicKey, index: bigint): Promise<any> {
  const proposal = await readProposal(r, address, squads.getProposalPda({ multisigPda: address, transactionIndex: index })[0]);
  const approvedAt = proposal.status.__kind === 'Approved' ? Number(String(proposal.status.timestamp)) : null;
  const result: any = { transactionIndex: String(index), status: proposal.status.__kind, approvedAt,
    earliestExecution: approvedAt === null ? null : approvedAt + DELAY, approved: proposal.approved.map(k => k.toBase58()),
    rejected: proposal.rejected.map(k => k.toBase58()), cancelled: proposal.cancelled.map(k => k.toBase58()),
    creator: null, transactionSha256: null, kind: 'unknown', actions: [], calls: [], upgrade: null,
    admitted: false, changesGovernance: false, reason: null };
  try {
    const account = await owned(r, squads.getTransactionPda({ multisigPda: address, index })[0], SQUADS), vault = vaultFor(address);
    result.transactionSha256 = hash(account.data);
    if (account.data.subarray(0, 8).equals(Buffer.from(squads.accounts.configTransactionDiscriminator))) {
      const tx = squads.accounts.ConfigTransaction.deserialize(account.data)[0];
      requireThat(tx.multisig.equals(address) && BigInt(String(tx.index)) === index, 'Wrong config transaction');
      Object.assign(result, { kind: 'config', creator: tx.creator.toBase58(), actions: tx.actions,
        changesGovernance: tx.actions.some(a => ['AddMember', 'RemoveMember', 'ChangeThreshold', 'SetTimeLock'].includes(a.__kind)) });
      const roles = (await readCity(r))?.state;
      assertConfigActions(tx.actions, roles?.guardian, roles?.registrar);
    } else {
      requireThat(account.data.subarray(0, 8).equals(Buffer.from(squads.accounts.vaultTransactionDiscriminator)), 'Unsupported transaction type');
      const tx = squads.accounts.VaultTransaction.deserialize(account.data)[0], message = tx.message;
      Object.assign(result, { kind: 'vault', creator: tx.creator.toBase58(), message });
      requireThat(tx.multisig.equals(address) && BigInt(String(tx.index)) === index && tx.vaultIndex === 0
        && tx.ephemeralSignerBumps.length === 0 && message.addressTableLookups.length === 0, 'Unsupported vault transaction');
      const inner = message.instructions.map(ix => new TransactionInstruction({ programId: message.accountKeys[ix.programIdIndex],
        data: Buffer.from(ix.data), keys: [...ix.accountIndexes].map(i => ({ pubkey: message.accountKeys[i],
          isSigner: i < message.numSigners, isWritable: i < message.numSigners ? i < message.numWritableSigners
            : i < message.numSigners + message.numWritableNonSigners })) }));
      result.calls = inner.map(ix => ({ ...instructionJson(ix), decoded: ix.programId.equals(r.programId)
        ? (r.program.coder.instruction as BorshInstructionCoder).decode(ix.data) : null }));
      if (inner.length === 1 && inner[0].programId.equals(LOADER)) {
        const ix = inner[0], data = await programData(r), buffer = ix.keys[2]?.pubkey;
        requireThat(buffer && ix.data.equals(Buffer.from([3, 0, 0, 0])), 'Only loader Upgrade is admitted');
        const expected = upgradeInstruction(r.programId, data.address, buffer, vault);
        requireThat(ix.keys.length === expected.keys.length && ix.keys.every((k, i) => k.pubkey.equals(expected.keys[i].pubkey)),
          'Upgrade must target this program, with rent returned to the vault');
        const bytes = (await owned(r, buffer, LOADER)).data;
        requireThat(bytes.length > 37 && bytes.readUInt32LE(0) === 1 && bytes[4] === 1
          && new PublicKey(bytes.subarray(5, 37)).equals(vault), 'Buffer authority must be the vault');
        result.upgrade = { buffer: buffer.toBase58(), binarySha256: hash(bytes.subarray(37)), binaryLength: bytes.length - 37 };
      } else {
        const checked = adminInstructions(r, inner.map(instructionJson), vault);
        await guardRoleChanges(r, checked, (await multisigState(r, address)).members.map(m => m.key));
      }
    }
    result.admitted = true;
  } catch (error: any) { result.reason = error.message; }
  return result;
}
function actionable(proposal: any) { return !(proposal.status === 'Active' && proposal.stale); }
function pendingProposalSafe(proposal: any) {
  if (!actionable(proposal)) return true;
  return !(proposal.status === 'Approved' && proposal.stale) && proposal.admitted && !proposal.changesGovernance;
}
function assertMemberRemoval(actions: squads.types.ConfigAction[], pending: any[], ownIndex?: bigint) {
  for (const action of actions) if (action.__kind === 'RemoveMember') {
    const key = action.oldMember.toBase58();
    requireThat(!pending.some(p => p.transactionIndex !== String(ownIndex) && actionable(p)
      && (p.creator === key || p.approved.includes(key))), 'Reject or cancel the departing signer’s open proposals before removal');
  }
}
const GUARDIAN_CALLS = new Set(['pauseStage1Intake', 'resumeStage1Intake', 'pauseStage1Settlement', 'resumeStage1Settlement']);
export async function buildGuardian(r: Operator, input: any): Promise<Operation> {
  requireThat(['create', 'check', 'propose', 'approve', 'execute'].includes(r.options.action), 'Unsupported guardian action');
  requireThat((await r.read(SQUADS))?.executable, 'Squads v4 is not loaded');
  const address=pk(input.multisig), vault=vaultFor(address);
  if(r.options.action==='create') {
    requireThat(!await r.read(address),'Guardian multisig already exists');
    const createKey=pk(input.createKey),creator=pk(input.creator);
    requireThat(squads.getMultisigPda({createKey})[0].equals(address),'Guardian multisig/create key mismatch');
    requireThat(Array.isArray(input.members),'Explicit guardian members required');
    const members=input.members.map((key:string)=>({key:pk(key),permissions:squads.types.Permissions.all()}));
    assertSettings({configAuthority:PublicKey.default,timeLock:DELAY,members,threshold:input.threshold});
    const config=squads.accounts.ProgramConfig.deserialize((await owned(r,squads.getProgramConfigPda({})[0],SQUADS)).data)[0];
    return {instructions:[squads.instructions.multisigCreateV2({treasury:config.treasury,creator,multisigPda:address,createKey,
      configAuthority:null,threshold:input.threshold,members,timeLock:0,rentCollector:null})],
      description:'Create the supplied no-delay guardian membership',report:{vault:vault.toBase58(),members:input.members,threshold:input.threshold,timeLockSeconds:0},
      assert:async()=>{const actual=await multisigState(r,address);assertSettings({...actual,timeLock:DELAY});
        requireThat(actual.timeLock===0 && actual.threshold===input.threshold
          && actual.members.map(m=>m.key.toBase58()).sort().join() === [...input.members].sort().join(),'Guardian settings differ');}};
  }
  const state=await multisigState(r,address);
  requireThat(state.timeLock===0 && state.configAuthority.equals(PublicKey.default), 'Guardian needs no delay and no config authority');
  // Reuse the member/threshold/permission checks without weakening admin settings.
  assertSettings({...state,timeLock:DELAY});
  const city=await readCity(r);
  requireThat(city && !city.legacy && city.state.guardian.equals(vault), 'Multisig vault is not the configured guardian');
  const limits=squads.accounts.SpendingLimit.gpaBuilder(SQUADS)
    .addFilter('accountDiscriminator',squads.accounts.spendingLimitDiscriminator).addFilter('multisig',address);
  requireThat((await r.connection.getProgramAccounts(SQUADS,{...limits.config,commitment:'finalized',minContextSlot:r.floor})).length===0,
    'Guardian spending limits are not admitted');
  const report={multisig:address.toBase58(),vault:vault.toBase58(),timeLockSeconds:0,threshold:state.threshold,
    members:state.members.map(m=>m.key.toBase58()),intakePaused:city.state.intakePaused,settlementPaused:city.state.settlementPaused};
  if(r.options.action==='check' && input.transactionIndex===undefined)
    return {instructions:[],description:'Configured no-delay guardian',report,assert:async()=>{await buildGuardian(r,input);}};
  requireThat(GUARDIAN_CALLS.has(input.call), 'Guardian admits only the four pause/resume calls');
  const member=pk(input.member),index=BigInt(input.transactionIndex);
  requireThat(state.members.some(m=>m.key.equals(member)) && index>BigInt(String(state.staleTransactionIndex)), 'Invalid guardian member or stale proposal');
  const common={multisigPda:address,transactionIndex:index,creator:member,rentPayer:r.feePayer};
  const accounts=input.call.startsWith('pause') ? {city:r.pda('s1v1_city'),guardian:vault}
    : {city:r.pda('s1v1_city'),programConfig:r.pda('program_config'),admin:vault};
  const expected=await (r.program.methods as any)[input.call]().accountsStrict(accounts).instruction();
  const [txKey,txBump]=squads.getTransactionPda({multisigPda:address,index});
  const proposalKey=squads.getProposalPda({multisigPda:address,transactionIndex:index})[0];
  if(r.options.action==='propose') {
    requireThat(index===BigInt(String(state.transactionIndex))+1n && !await r.read(txKey), 'Use next guardian transaction index');
    return {instructions:[squads.instructions.vaultTransactionCreate({...common,vaultIndex:0,ephemeralSigners:0,
      transactionMessage:new TransactionMessage({payerKey:vault,recentBlockhash:PublicKey.default.toBase58(),instructions:[expected]})}),
      squads.instructions.proposalCreate({...common,isDraft:false})],description:'Propose one exact guardian pause/resume call',
      report:{...report,call:input.call,instruction:instructionJson(expected)},
      assert:async()=>{requireThat((await readProposal(r,address,proposalKey)).status.__kind==='Active','Guardian proposal not active');}};
  }
  const bytes=(await owned(r,txKey,SQUADS)).data;
  requireThat(bytes.subarray(0,8).equals(Buffer.from(squads.accounts.vaultTransactionDiscriminator)), 'Guardian requires a vault transaction');
  const tx=squads.accounts.VaultTransaction.deserialize(bytes)[0], message=tx.message;
  requireThat(tx.multisig.equals(address) && BigInt(String(tx.index))===index && tx.bump===txBump && tx.vaultIndex===0
    && tx.ephemeralSignerBumps.length===0 && message.addressTableLookups.length===0 && message.instructions.length===1,
    'Unsupported guardian transaction');
  const stored=message.instructions[0];
  const inner=new TransactionInstruction({programId:message.accountKeys[stored.programIdIndex],data:Buffer.from(stored.data),
    keys:[...stored.accountIndexes].map(i=>({pubkey:message.accountKeys[i],isSigner:i<message.numSigners,
      isWritable:i<message.numSigners?i<message.numWritableSigners:i<message.numSigners+message.numWritableNonSigners}))});
  // Squads compiles the vault as message payer, so its writable privilege is
  // promoted even when the inner instruction only needs a read-only signer.
  const compiled=new TransactionMessage({payerKey:vault,recentBlockhash:PublicKey.default.toBase58(),instructions:[expected]}).compileToLegacyMessage();
  const canonical=new TransactionInstruction({programId:expected.programId,data:expected.data,keys:expected.keys.map(k=>{
    const i=compiled.accountKeys.findIndex(a=>a.equals(k.pubkey));return {pubkey:k.pubkey,isSigner:compiled.isAccountSigner(i),isWritable:compiled.isAccountWritable(i)};})});
  requireThat(JSON.stringify(instructionJson(inner))===JSON.stringify(instructionJson(canonical)), 'Stored guardian call differs from exact reviewed call');
  const proposal=await readProposal(r,address,proposalKey), transactionSha256=hash(bytes);
  const detail={...report,call:input.call,transactionSha256,status:proposal.status.__kind,instruction:instructionJson(inner)};
  if(r.options.action==='check') return {instructions:[],description:'Exact guardian proposal review',report:detail,assert:async()=>{}};
  requireThat(input.transactionSha256===transactionSha256,'Guardian transaction differs from reviewed hash');
  if(r.options.action==='approve') {
    requireThat(proposal.status.__kind==='Active','Guardian proposal must be Active');
    return {instructions:[squads.instructions.proposalApprove({multisigPda:address,transactionIndex:index,member})],
      description:'Approve the exact guardian call',report:detail,assert:async()=>{
        requireThat((await readProposal(r,address,proposalKey)).approved.some(k=>k.equals(member)),'Guardian approval not finalized');}};
  }
  requireThat(proposal.status.__kind==='Approved','Guardian threshold not reached');
  const built=await squads.instructions.vaultTransactionExecute({connection:r.connection,multisigPda:address,transactionIndex:index,member});
  requireThat(built.lookupTableAccounts.length===0,'Guardian lookup tables are not admitted');
  return {instructions:[built.instruction],description:'Execute the approved guardian call without delay',report:detail,assert:async()=>{
    requireThat((await readProposal(r,address,proposalKey)).status.__kind==='Executed','Guardian execution not finalized');
    const after=(await readCity(r))?.state,field=input.call.endsWith('Intake')?'intakePaused':'settlementPaused';
    requireThat(after?.guardian.equals(vault) && after[field]===input.call.startsWith('pause'),'Guardian flag outcome differs');}};
}

export async function buildGovernance(r: Operator, input: any): Promise<Operation> {
  if(r.options.role==='guardian') return buildGuardian(r,input);
  requireThat(!r.options.role || r.options.role==='admin','Unknown governance role');
  const action = r.options.action, address = pk(input.multisig), vault = vaultFor(address);
  const sq = await r.read(SQUADS); requireThat(sq?.executable, 'Squads v4 is not loaded');
  if (action === 'check') return { instructions: [], description: 'Finalized governance settings',
    report: { ...await governanceCheck(r, input), ...(input.transactionIndex === undefined ? {} :
      { proposal: await reviewProposal(r, address, BigInt(input.transactionIndex)) }) }, assert: async () => { await governanceCheck(r, input); } };
  if (action === 'migrate-city') {
    const before = await readCity(r); requireThat(before, 'City does not exist');
    return { instructions: before.legacy ? [await r.program.methods.migrateStage1City().accounts({
      city: r.pda('s1v1_city'), payer: r.feePayer, systemProgram: SystemProgram.programId }).instruction()] : [],
      description: 'Permissionless city expansion; preserve historic field values and owner rights',
      assert: async () => { const after = await readCity(r); requireThat(after && !after.legacy
        && after.account.data.subarray(0, 881).equals(before.account.data.subarray(0, 881))
        && JSON.stringify(after.decoded) === JSON.stringify(before.decoded), 'City values changed'); } };
  }
  if (action === 'extend-program') {
    const before = await programData(r), length = input.binaryLength;
    requireThat(Number.isSafeInteger(length) && length > 0 && length + 45 <= 10 * 1024 * 1024, 'Invalid binary length');
    requireThat(before.authority.equals(r.admin) && !r.admin.equals(vault), 'Extend before handoff with the explicit current upgrade authority');
    const checked = await checkedExtension(r);
    const additional = Math.max(0, length + 45 - before.account.data.length);
    const bytes = Buffer.alloc(8); bytes.writeUInt32LE(checked ? 9 : 6); bytes.writeUInt32LE(additional, 4);
    const instruction = new TransactionInstruction({ programId: LOADER, data: bytes, keys: [
      { pubkey: before.address, isWritable: true, isSigner: false },
      { pubkey: r.programId, isWritable: true, isSigner: false },
      ...(checked ? [{ pubkey: r.admin, isWritable: true, isSigner: true }] : []),
      { pubkey: SystemProgram.programId, isWritable: false, isSigner: false },
      { pubkey: r.feePayer, isWritable: true, isSigner: true },
    ] });
    const rent = await r.connection.getMinimumBalanceForRentExemption(before.account.data.length + additional, 'finalized');
    return { instructions: additional ? [instruction] : [], description: 'Fund loader storage capacity without changing code or authority',
      report: { extensionInstruction: checked ? 'ExtendProgramChecked' : 'ExtendProgram', binaryLength: length, additionalBytes: additional, rentTopUpLamports: Math.max(0, rent - before.account.lamports) },
      assert: async () => { const after = await programData(r); requireThat(after.authority.equals(before.authority)
        && after.account.data.length === before.account.data.length + additional
        && after.account.data.subarray(45, before.account.data.length).equals(before.account.data.subarray(45))
        && after.account.data.subarray(before.account.data.length).every(b => b === 0), 'Program changed during extension');
        await waitForVisibleCode(r, after.account.data); } };
  }
  if (action === 'create') {
    requireThat(!await r.read(address), 'Multisig already exists');
    const createKey = pk(input.createKey), creator = pk(input.creator);
    requireThat(squads.getMultisigPda({ createKey })[0].equals(address), 'Multisig/create key mismatch');
    const members = input.members.map((key: string) => ({ key: pk(key), permissions: squads.types.Permissions.all() }));
    const roles = (await readCity(r))?.state;
    assertSettings({ configAuthority: PublicKey.default, timeLock: DELAY, members, threshold: input.threshold }, roles?.guardian, roles?.registrar);
    const config = squads.accounts.ProgramConfig.deserialize((await owned(r, squads.getProgramConfigPda({})[0], SQUADS)).data)[0];
    return { instructions: [squads.instructions.multisigCreateV2({ treasury: config.treasury, creator,
      multisigPda: address, createKey, configAuthority: null, threshold: input.threshold, members,
      timeLock: DELAY, rentCollector: null })], description: 'Create autonomous seven-day multisig',
      report: { vault: vault.toBase58(), threshold: input.threshold, members: input.members, timeLock: DELAY, configAuthority: null },
      assert: async () => { const actual = await multisigState(r, address); const roles = (await readCity(r))?.state;
        assertSettings(actual, roles?.guardian, roles?.registrar);
        requireThat(actual.threshold === input.threshold && actual.members.map(m => m.key.toBase58()).sort().join() === [...input.members].sort().join(), 'Created multisig differs'); } };
  }
  const state = await multisigState(r, address);
  if (!['reject', 'cancel'].includes(action)) assertSettings(state);
  const report = await governanceCheck(r, input);
  if (!['reject', 'cancel'].includes(action)) requireThat(report.spendingLimits === 0, 'Spending limits bypass governance');
  if (action === 'handoff') {
    requireThat(report.guardianRolesSeparate, 'Guardian must remain separate before authority handoff');
    requireThat(report.registrarRolesSeparate, 'Registrar must remain separate before authority handoff');
    const data = await programData(r);
    requireThat(data.authority.equals(r.admin) && !r.admin.equals(vault), 'Current upgrade authority must be the explicit current admin');
    requireThat(Number.isSafeInteger(input.binaryLength) && input.binaryLength > 0
      && data.account.data.length - 45 >= input.binaryLength, 'Review binaryLength and extend ProgramData before handoff');
    requireThat(BigInt(String(state.transactionIndex)) === 0n, 'Handoff requires a fresh multisig with no preapproved transactions');
    return { instructions: [await r.program.methods.updateProgramConfig(vault, null).accounts({
      programConfig: r.pda('program_config'), adminAuthority: r.admin }).instruction(), setAuthority(data.address, r.admin, vault)],
      description: 'Atomically hand ProgramConfig/Stage1 admin and loader upgrade authority to vault', report,
      assert: async () => requireThat((await governanceCheck(r, input)).currentAuthoritiesValid, 'Authority handoff incomplete') };
  }

  const member = pk(input.member), index = BigInt(input.transactionIndex);
  requireThat(state.members.some(m => m.key.equals(member)), 'Signer is not a multisig member');
  const txKey = squads.getTransactionPda({ multisigPda: address, index })[0];
  const proposalKey = squads.getProposalPda({ multisigPda: address, transactionIndex: index })[0];
  const common = { multisigPda: address, transactionIndex: index, creator: member, rentPayer: r.feePayer };
  if (['reject', 'cancel'].includes(action)) {
    const review = await reviewProposal(r, address, index);
    requireThat(review.transactionSha256 && review.transactionSha256 === input.transactionSha256, 'Transaction differs from reviewed proposal hash');
    requireThat(review.status === (action === 'reject' ? 'Active' : 'Approved'), 'Reject needs Active; cancel needs Approved');
    return { instructions: [(action === 'reject' ? squads.instructions.proposalReject : squads.instructions.proposalCancel)({
      multisigPda: address, transactionIndex: index, member })], description: 'Vote to reject or cancel the hash-bound proposal', report: review,
      assert: async () => { const p = await readProposal(r, address, proposalKey);
        requireThat((action === 'reject' ? p.rejected : p.cancelled).some(k => k.equals(member)), 'Remediation vote not finalized'); } };
  }
  requireThat(report.currentAuthoritiesValid && r.admin.equals(vault), 'Hand off both authorities before proposals');
  const otherHazards = report.pendingProposals.filter(p => p.transactionIndex !== String(index) && !pendingProposalSafe(p));
  requireThat(otherHazards.length === 0, 'Reject or cancel other unsafe pending proposals first');

  if (['propose-admin', 'propose-upgrade', 'propose-config'].includes(action)) {
    requireThat(index === BigInt(String(state.transactionIndex)) + 1n && !await r.read(txKey), 'Use next transaction index');
    requireThat(!report.cityNeedsMigration || action === 'propose-upgrade', 'Migrate the city before administration');
    requireThat(report.idlInstructionsDisabled || (action === 'propose-upgrade' && report.idlProbe === 'enabled'), 'Disable IDL instructions through a reviewed upgrade before administration');
    let create: TransactionInstruction;
    let detail: unknown;
    if (action === 'propose-config') {
      const roles = (await readCity(r))?.state;
      const actions = configActions(input, roles?.guardian, roles?.registrar); detail = input.actions;
      assertMemberRemoval(actions, report.pendingProposals);
      create = squads.instructions.configTransactionCreate({ ...common, actions });
    } else {
      let inner: TransactionInstruction[];
      if (action === 'propose-upgrade') {
        await (await import('./stage1_cutover.js')).freshStage1Inventory(r);
        const buffer = pk(input.buffer), account = await owned(r, buffer, LOADER);
        requireThat(account.data.length > 37 && account.data.readUInt32LE(0) === 1 && account.data[4] === 1
          && new PublicKey(account.data.subarray(5, 37)).equals(vault), 'Buffer authority must already be the vault');
        requireThat(hash(account.data.subarray(37)) === input.binarySha256, 'Published binary hash does not match buffer');
        requireThat(typeof input.migrationNotes === 'string' && input.migrationNotes.trim().length > 0, 'Migration notes required');
        const data = await programData(r);
        requireThat(data.account.data.length - 45 >= account.data.length - 37, 'Extend ProgramData capacity before proposing this binary');
        inner = [upgradeInstruction(r.programId, data.address, buffer, vault)];
        detail = { buffer: input.buffer, binarySha256: input.binarySha256, migrationNotes: input.migrationNotes };
      } else {
        inner = adminInstructions(r, input.instructions, vault);
        await guardRoleChanges(r, inner, state.members.map(m => m.key));
        detail = inner.map(ix => ({ ...instructionJson(ix), decoded: (r.program.coder.instruction as BorshInstructionCoder).decode(ix.data) }));
      }
      create = squads.instructions.vaultTransactionCreate({ ...common, vaultIndex: 0, ephemeralSigners: 0,
        transactionMessage: new TransactionMessage({ payerKey: vault, recentBlockhash: PublicKey.default.toBase58(), instructions: inner }) });
    }
    return { instructions: [create, squads.instructions.proposalCreate({ ...common, isDraft: false })],
      description: 'Create proposal; waiting period starts when threshold approval is reached', report: detail,
      assert: async () => { await owned(r, txKey, SQUADS); const p = squads.accounts.Proposal.deserialize((await owned(r, proposalKey, SQUADS)).data)[0];
        requireThat(p.status.__kind === 'Active', 'Proposal is not active'); } };
  }
  const timing = await reviewProposal(r, address, index);
  requireThat(!report.cityNeedsMigration || timing.upgrade, 'Migrate the city before administration');
  requireThat(timing.admitted, timing.reason ?? 'Unadmitted proposal');
  requireThat(report.idlInstructionsDisabled || (timing.upgrade && report.idlProbe === 'enabled'), 'Disable IDL instructions through a reviewed upgrade before administration');
  assertMemberRemoval(timing.actions, report.pendingProposals, index);
  requireThat(timing.transactionSha256 === input.transactionSha256, 'Transaction differs from reviewed proposal hash');
  if (timing.upgrade) requireThat(timing.upgrade.binarySha256 === input.binarySha256, 'Published binary hash does not match reviewed upgrade');
  const approvedAt = timing.approvedAt;
  if(timing.upgrade && action==='execute') await (await import('./stage1_cutover.js')).freshStage1Inventory(r);
  if (action === 'approve') return { instructions: [squads.instructions.proposalApprove({ multisigPda: address, transactionIndex: index, member })],
    description: 'Approve the exact reviewed proposal', report: timing,
    assert: async () => { const p = squads.accounts.Proposal.deserialize((await owned(r, proposalKey, SQUADS)).data)[0];
      requireThat(p.approved.some(key => key.equals(member)), 'Approval not finalized'); } };
  requireThat(action === 'execute', 'Unknown governance action');
  requireThat(approvedAt !== null, 'Proposal has not reached approval threshold');
  // Use chain time, never the operator machine clock. The program checks again.
  const clock = await r.read(SYSVAR_CLOCK_PUBKEY, false);
  requireThat(Number(clock!.data.readBigInt64LE(32)) >= approvedAt + DELAY, 'Seven-day wait has not elapsed');
  let instruction: TransactionInstruction;
  if (input.kind === 'config') {
    requireThat(timing.kind === 'config', 'Transaction kind mismatch');
    instruction = squads.instructions.configTransactionExecute({ multisigPda: address, transactionIndex: index, member, rentPayer: r.feePayer });
  } else {
    requireThat(input.kind === 'vault' && timing.kind === 'vault', 'Explicit kind must match stored transaction');
    const built = await squads.instructions.vaultTransactionExecute({ connection: r.connection, multisigPda: address, transactionIndex: index, member });
    requireThat(built.lookupTableAccounts.length === 0, 'Split large operations; lookup tables are not admitted by this transport');
    instruction = built.instruction;
  }
  return { instructions: [instruction], description: 'Execute approved proposal after seven days', report: timing,
    assert: async () => { const p = squads.accounts.Proposal.deserialize((await owned(r, proposalKey, SQUADS)).data)[0];
      requireThat(p.status.__kind === 'Executed', 'Execution not finalized');
      if (timing.upgrade) {
        const data = await programData(r);
        requireThat(hash(data.account.data.subarray(45, 45 + timing.upgrade.binaryLength)) === timing.upgrade.binarySha256
          && data.account.data.subarray(45 + timing.upgrade.binaryLength).every(b => b === 0), 'Finalized program binary differs');
        requireThat(!await r.read(pk(timing.upgrade.buffer)), 'Upgrade buffer was not consumed');
        // A finalized Upgrade can still be the latest finalized slot. Loader
        // code becomes callable one slot later; do not hand off to migration
        // until that later slot is finalized too. Never resend the upgrade.
        await waitForVisibleCode(r, data.account.data);
        const after = await governanceCheck(r, input);
        requireThat(after.currentAuthoritiesValid && after.idlInstructionsDisabled
          && after.pendingProposals.every(pendingProposalSafe),
          'Upgrade finalized but governance or disabled-IDL checks failed');
        return;
      }
      const after = await governanceCheck(r, input);
      requireThat(after.currentAuthoritiesValid && after.idlInstructionsDisabled && !after.cityNeedsMigration
        && after.pendingProposals.every(pendingProposalSafe), 'Governance changed unexpectedly');
    } };
}
export function runGovernance(options = args()) {
  return runOperator('stage1-governance', buildGovernance, options, options.role==='guardian' ? [CURRENT_PROGRAM_VERSION] : [PREVIOUS_PROGRAM_VERSION, CURRENT_PROGRAM_VERSION]);
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href)
  runGovernance().catch(error => { console.error(`Governance refused: ${error.message}`); process.exitCode = 1; });
