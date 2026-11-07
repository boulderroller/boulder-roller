import { expect } from 'chai';
import * as anchor from '@coral-xyz/anchor';
import * as squads from '@sqds/multisig';
import { readFileSync } from 'fs';
import { PublicKey, TransactionInstruction } from '@solana/web3.js';
import { assertSettings, assertConfigActions, multisigState, configActions, adminInstructions, guardRoleChanges, buildGovernance, vaultFor, LOADER, DELAY, ADMIN_CALLS } from '../scripts/stage1_governance.js';
import { instructionJson } from '../scripts/stage1_operator.js';
import { SystemProgram } from '@solana/web3.js';

const idl = JSON.parse(readFileSync(new URL('../idl/boulder_rollers.json', import.meta.url), 'utf8'));
describe('Stage1 governance ABI and authority inventory', () => {
  it('encodes guardian configuration, immediate pause and guardian/admin resume', () => {
    const coder = new anchor.BorshInstructionCoder(idl);
    expect(coder.encode('setStage1Guardian', { guardian: PublicKey.unique() })).to.have.length(40);
    expect(coder.encode('pauseStage1Intake', {})).to.have.length(8);
    expect(coder.encode('resumeStage1Intake', {})).to.have.length(8);
    expect(coder.encode('pauseStage1Settlement', {})).to.have.length(8);
    expect(coder.encode('resumeStage1Settlement', {})).to.have.length(8);
    expect(coder.encode('migrateStage1City', {})).to.have.length(8);
  });
  it('guardian has exactly one signer and one writable config, with no value account', () => {
    expect(idl.instructions.find(i => i.name === 'pauseStage1Intake').accounts.map(a => [a.name, a.isMut, a.isSigner]))
      .to.deep.equal([['city', true, false], ['guardian', false, true]]);
    expect(idl.instructions.find(i => i.name === 'pauseStage1Settlement').accounts.map(a => [a.name, a.isMut, a.isSigner]))
      .to.deep.equal([['city', true, false], ['guardian', false, true]]);
    for (const name of ['setStage1Guardian', 'resumeStage1Intake', 'resumeStage1Settlement', 'setStage1Publisher']) {
      expect(idl.instructions.find(i => i.name === name).accounts.filter(a => a.isMut).map(a => a.name)).to.deep.equal(['city']);
    }
  });
  it('inventories every economic admin surface: config edits or exact PDA rent, never a recipient account', () => {
    const expected = {
      initCityConfig: ['city', 'admin'], configureAsset: ['city', 'asset', 'earnings', 'admin'],
      initHillBond: ['hill', 'admin'], setStage1Registrar: ['city'], configureStage1Dung: ['city'], setStage1Publisher: ['city'], setStage1Guardian: ['city'], resumeStage1Intake: ['city'],
      resumeStage1Settlement: ['city'], registerStage1Cash: ['cash', 'asset', 'earnings', 'admin'],
      updateProgramConfig: ['programConfig'], updateProtocolParameters: ['programConfig'],
      configureMints: ['programConfig'], configureTreasuryAccounts: ['programConfig'], configureUsdcPayment: ['programConfig'],
      initializeProgramConfig: ['programConfig', 'admin'], advanceProgramVersion: ['programConfig'],
      registerRatifiedClimb: ['climb', 'climbVersionIndex', 'predecessorClimb', 'admin'],
    };
    for (const [name, writable] of Object.entries(expected)) {
      expect(ADMIN_CALLS.has(name), name).to.equal(true);
      expect(idl.instructions.find(i => i.name === name).accounts.filter(a => a.isMut).map(a => a.name), name).to.deep.equal(writable);
    }
    const devnet = JSON.parse(readFileSync(new URL('../idl/boulder_rollers.devnet.json', import.meta.url), 'utf8'));
    expect(devnet.instructions.find(i => i.name === 'registerStage1TestPool').accounts.filter(a => a.isMut).map(a => a.name))
      .to.deep.equal(['testPool', 'city', 'asset', 'earnings', 'admin']);
    expect([...ADMIN_CALLS].sort()).to.deep.equal([...Object.keys(expected), 'registerStage1TestPool'].sort());
    expect(idl.instructions.find(i => i.name === 'migrateStage1City').accounts.map(a => [a.name, a.isMut, a.isSigner]))
      .to.deep.equal([['city', true, false], ['payer', true, true], ['systemProgram', false, false]]);
  });
  it('refuses delay/config-authority/spending-limit bypass and invalid membership', () => {
    const state = { configAuthority: PublicKey.default, timeLock: DELAY, threshold: 1,
      members: [{ key: PublicKey.unique(), permissions: { mask: 7 } }] };
    expect(() => assertSettings(state)).not.to.throw();
    expect(() => assertSettings({ ...state, timeLock: DELAY - 1 })).to.throw('seven-day');
    expect(() => assertSettings({ ...state, configAuthority: PublicKey.unique() })).to.throw('config authority');
    expect(() => assertSettings({ ...state, threshold: 2 })).to.throw('threshold');
    for (const kind of ['time-lock', 'spending-limit', 'config-authority'])
      expect(() => configActions({ actions: [{ kind }] })).to.throw('Only member/threshold');
  });
  it('refuses arbitrary vault transfers and direct admin escape in a reviewed admin proposal', () => {
    const vault = PublicKey.unique(), programId = PublicKey.unique();
    const r = { programId, program: { coder: { instruction: new anchor.BorshInstructionCoder(idl) } } } as any;
    expect(() => adminInstructions(r, [instructionJson(SystemProgram.transfer({ fromPubkey: vault,
      toPubkey: PublicKey.unique(), lamports: 1 }))], vault)).to.throw('BoulderRoller');
    const ix = { program: programId.toBase58(), keys: [{ key: vault.toBase58(), signer: true, writable: false }],
      data: r.program.coder.instruction.encode('updateProgramConfig', { newAdmin: PublicKey.unique(), newBackend: null }).toString('base64') };
    expect(() => adminInstructions(r, [ix], vault)).to.throw('remain the reviewed vault');
  });
  it('rejects a batch that assigns a new guardian and then grants it backend powers', async () => {
    const coder = new anchor.BorshInstructionCoder(idl), key = PublicKey.unique();
    const r = { program: { coder: { instruction: coder } }, read: async () => null, pda: () => PublicKey.unique(),
      fetch: async () => ({ adminAuthority: PublicKey.unique(), backendAuthority: PublicKey.unique() }) } as any;
    const instructions = [new TransactionInstruction({ programId: PublicKey.unique(), keys: [],
      data: coder.encode('setStage1Guardian', { guardian: key }) }),
    new TransactionInstruction({ programId: PublicKey.unique(), keys: [],
      data: coder.encode('updateProgramConfig', { newAdmin: null, newBackend: key }) })];
    let error = '';
    try { await guardRoleChanges(r, instructions); } catch (e: any) { error = e.message; }
    expect(error).to.include('Guardian must remain separate');
  });
  it('rejects a Squads-owned account with the wrong discriminator or multisig PDA', async () => {
    const createKey = PublicKey.unique(), [address, bump] = squads.getMultisigPda({ createKey });
    const [bytes] = squads.accounts.Multisig.fromArgs({ createKey, bump, configAuthority: PublicKey.default,
      threshold: 1, timeLock: DELAY, transactionIndex: 0, staleTransactionIndex: 0, rentCollector: null,
      members: [{ key: PublicKey.unique(), permissions: squads.types.Permissions.all() }] }).serialize();
    const r = { read: async () => ({ owner: squads.PROGRAM_ID, executable: false, data: bytes }) } as any;
    expect((await multisigState(r, address)).createKey.equals(createKey)).to.equal(true);
    for (const wrong of ['discriminator', 'address']) {
      if (wrong === 'discriminator') bytes[0] ^= 1;
      let error = '';
      try { await multisigState(r, wrong === 'address' ? PublicKey.unique() : address); } catch (e: any) { error = e.message; }
      expect(error).to.include('Invalid multisig');
      if (wrong === 'discriminator') bytes[0] ^= 1;
    }
  });
  it('applies the same member permission policy to externally created config proposals', () => {
    expect(() => assertConfigActions([{ __kind: 'AddMember', newMember: {
      key: PublicKey.unique(), permissions: { mask: 1 } } }])).to.throw('member permissions');
  });
  it('rejects assigning a multisig member as the separate guardian', async () => {
    const coder = new anchor.BorshInstructionCoder(idl), member = PublicKey.unique();
    const r = { program: { coder: { instruction: coder } }, read: async () => null, pda: () => PublicKey.unique(),
      fetch: async () => ({ adminAuthority: PublicKey.unique(), backendAuthority: PublicKey.unique() }) } as any;
    const ix = new TransactionInstruction({ programId: PublicKey.unique(), keys: [],
      data: coder.encode('setStage1Guardian', { guardian: member }) });
    let error = '';
    try { await guardRoleChanges(r, [ix], [member]); } catch (e: any) { error = e.message; }
    expect(error).to.include('Guardian must remain separate');
    expect(() => assertSettings({ configAuthority: PublicKey.default, timeLock: DELAY, threshold: 1,
      members: [{ key: member, permissions: { mask: 7 } }] }, member)).to.throw('Guardian must remain separate');
    expect(() => configActions({ actions: [{ kind: 'add-member', key: member.toBase58() }] }, member))
      .to.throw('Guardian must remain separate');
    expect(() => assertConfigActions([{ __kind: 'AddMember', newMember: {
      key: member, permissions: { mask: 7 } } }], member)).to.throw('Guardian must remain separate');
  });

  it('rejects registrar membership in settings and prospective config actions', () => {
    const registrar = PublicKey.unique();
    const state = { configAuthority: PublicKey.default, timeLock: DELAY, threshold: 1,
      members: [{ key: registrar, permissions: { mask: 7 } }] };
    expect(() => (assertSettings as any)(state, PublicKey.default, registrar)).to.throw('Registrar must remain separate');
    expect(() => (configActions as any)({ actions: [{ kind: 'add-member', key: registrar.toBase58() }] }, PublicKey.default, registrar))
      .to.throw('Registrar must remain separate');
    expect(() => (assertConfigActions as any)([{ __kind: 'AddMember', newMember: {
      key: registrar, permissions: { mask: 7 } } }], PublicKey.default, registrar)).to.throw('Registrar must remain separate');
  });
  it('refuses multisig creation before reading treasury when a member is the registrar', async () => {
    const createKey = PublicKey.unique(), [address] = squads.getMultisigPda({ createKey });
    const city = PublicKey.unique(), programId = PublicKey.unique(), registrar = PublicKey.unique();
    let treasuryRead = false;
    const r = { options: { action: 'create' }, programId, pda: () => city,
      read: async (key: PublicKey) => {
        if (key.equals(squads.PROGRAM_ID)) return { executable: true };
        if (key.equals(city)) return { owner: programId, executable: false, data: Buffer.alloc(963) };
        if (key.equals(address)) return null;
        treasuryRead = true; throw Error('Unexpected treasury read');
      }, program: { account: { stage1CityConfig: { size: 963 } }, coder: { accounts: {
        decode: () => ({ guardian: PublicKey.default, registrar, publisher: PublicKey.unique() }) } } } } as any;
    let error = '';
    try { await buildGovernance(r, { multisig: address.toBase58(), createKey: createKey.toBase58(),
      creator: PublicKey.unique().toBase58(), threshold: 1, members: [registrar.toBase58()] }); } catch (e: any) { error = e.message; }
    expect(error).to.include('Registrar must remain separate');
    expect(treasuryRead).to.equal(false);
  });
  for (const role of ['guardian', 'registrar']) it(`refuses handoff before signing when the ${role} is the destination vault`, async () => {
    const createKey = PublicKey.unique(), [address, bump] = squads.getMultisigPda({ createKey });
    const vault = vaultFor(address), admin = PublicKey.unique(), programId = PublicKey.unique();
    const city = PublicKey.unique(), dataKey = PublicKey.unique();
    const [multisigBytes] = squads.accounts.Multisig.fromArgs({ createKey, bump, configAuthority: PublicKey.default,
      threshold: 1, timeLock: DELAY, transactionIndex: 0, staleTransactionIndex: 0, rentCollector: null,
      members: [{ key: PublicKey.unique(), permissions: squads.types.Permissions.all() }] }).serialize();
    const executable = Buffer.alloc(36); executable.writeUInt32LE(2); dataKey.toBuffer().copy(executable, 4);
    const programData = Buffer.alloc(45); programData.writeUInt32LE(3); programData[12] = 1; admin.toBuffer().copy(programData, 13);
    const accounts = new Map([
      [squads.PROGRAM_ID.toBase58(), { executable: true }],
      [address.toBase58(), { owner: squads.PROGRAM_ID, executable: false, data: multisigBytes }],
      [programId.toBase58(), { owner: LOADER, executable: true, data: executable }],
      [dataKey.toBase58(), { owner: LOADER, executable: false, data: programData }],
      [city.toBase58(), { owner: programId, executable: false, data: Buffer.alloc(963) }],
    ]);
    let instructionBuilt = false;
    const r = { options: { action: 'handoff' }, programId, admin, floor: 0,
      read: async (key: PublicKey) => accounts.get(key.toBase58()), pda: () => city,
      fetch: async () => ({ adminAuthority: admin, backendAuthority: PublicKey.unique(), programVersion: 77 }),
      connection: { getProgramAccounts: async () => [] },
      program: { account: { stage1CityConfig: { size: 963 } },
        coder: { accounts: { decode: () => ({ guardian: PublicKey.default, registrar: PublicKey.default, [role]: vault, publisher: PublicKey.unique() }) } },
        methods: { updateProgramConfig: () => ({ accounts: () => ({ instruction: async () => {
          instructionBuilt = true; return new TransactionInstruction({ programId, keys: [], data: Buffer.alloc(0) });
        } }) }) } } } as any;
    let error = '';
    try { await buildGovernance(r, { multisig: address.toBase58() }); } catch (e: any) { error = e.message; }
    expect(error).to.include(`${role[0].toUpperCase() + role.slice(1)} must remain separate`);
    expect(instructionBuilt).to.equal(false);
  });
});
