import { expect } from 'chai';
import * as squads from '@sqds/multisig';
import { PublicKey } from '@solana/web3.js';
import { BorshInstructionCoder } from '@coral-xyz/anchor';
import { readFileSync } from 'fs';
import { buildGovernance, governanceCheck, vaultFor, LOADER, DELAY, checkedExtension, EXTEND_CHECKED_FEATURE } from '../scripts/stage1_governance.js';

function fixture() {
  const createKey = PublicKey.unique(), [address, bump] = squads.getMultisigPda({ createKey });
  const vault = vaultFor(address), member = PublicKey.unique(), programId = PublicKey.unique(), dataKey = PublicKey.unique();
  const accounts = new Map<string, any>(), proposals: {pubkey: PublicKey}[] = [];
  const put = (key: PublicKey, data: Buffer, owner = squads.PROGRAM_ID, executable = false) =>
    accounts.set(key.toBase58(), { owner, executable, data, lamports: 1 });
  const state = { createKey, bump, configAuthority: PublicKey.default, threshold: 1, timeLock: DELAY,
    transactionIndex: 2, staleTransactionIndex: 2, rentCollector: null,
    members: [{ key: member, permissions: squads.types.Permissions.all() }] };
  put(address, squads.accounts.Multisig.fromArgs(state).serialize()[0]);
  put(squads.PROGRAM_ID, Buffer.alloc(0), LOADER, true);
  const executable = Buffer.alloc(36); executable.writeUInt32LE(2); dataKey.toBuffer().copy(executable, 4);
  put(programId, executable, LOADER, true);
  const data = Buffer.alloc(45); data.writeUInt32LE(3); data[12] = 1; vault.toBuffer().copy(data, 13); put(dataKey, data, LOADER);
  const r: any = { options: { action: 'check' }, programId, admin: vault, feePayer: PublicKey.unique(), floor: 0,
    read: async (key: PublicKey) => accounts.get(key.toBase58()), pda: () => PublicKey.unique(),
    fetch: async () => ({ adminAuthority: vault, backendAuthority: PublicKey.unique(), programVersion: 77 }),
    connection: { getProgramAccounts: async (_: any, config: any) => config.filters[0].memcmp.bytes ===
      (squads.accounts.Proposal.gpaBuilder().addFilter('accountDiscriminator', squads.accounts.proposalDiscriminator).config.filters[0] as any).memcmp.bytes ? proposals : [],
      getLatestBlockhash: async () => ({blockhash: PublicKey.default.toBase58()}), getSlot: async () => 100,
      simulateTransaction: async () => ({ value: {err: {InstructionError: [0, {Custom: 1000}]}} }) } };
  function add(index: number, status: any, actions: any[]) {
    const [tx, txBump] = squads.getTransactionPda({multisigPda: address, index: BigInt(index)});
    const [proposal, pBump] = squads.getProposalPda({multisigPda: address, transactionIndex: BigInt(index)});
    put(tx, squads.accounts.ConfigTransaction.fromArgs({multisig: address, creator: member, index, bump: txBump, actions}).serialize()[0]);
    put(proposal, squads.accounts.Proposal.fromArgs({multisig: address, transactionIndex: index, bump: pBump, status,
      approved: status.__kind === 'Approved' ? [member] : [], rejected: [], cancelled: []}).serialize()[0]);
    proposals.push({pubkey: proposal});
  }
  function addAdmittedVault(index: number, status: any) {
    add(index, status, []);
    const coder = new BorshInstructionCoder(JSON.parse(readFileSync(new URL('../idl/boulder_rollers.json', import.meta.url), 'utf8')));
    r.program = { coder: { instruction: coder } };
    const [tx, bump] = squads.getTransactionPda({multisigPda: address, index: BigInt(index)});
    put(tx, squads.accounts.VaultTransaction.fromArgs({multisig: address, creator: member, index, bump,
      vaultIndex: 0, vaultBump: squads.getVaultPda({multisigPda: address, index: 0})[1], ephemeralSignerBumps: new Uint8Array(),
      message: {numSigners: 1, numWritableSigners: 0, numWritableNonSigners: 0, accountKeys: [vault, programId],
        instructions: [{programIdIndex: 1, accountIndexes: new Uint8Array([0]),
          data: coder.encode('setStage1Publisher', {publisher: PublicKey.unique()})}], addressTableLookups: []}}).serialize()[0]);
  }
  return {r, address, member, add, addAdmittedVault, dataKey, put, state};
}
describe('Stage1 pending governance and remediation', () => {
  it('keeps status false for a stale approved admitted vault proposal after raw member removal', async () => {
    const f = fixture();
    f.addAdmittedVault(1, {__kind: 'Approved', timestamp: 10});
    f.state.members = [{key: PublicKey.unique(), permissions: squads.types.Permissions.all()}];
    f.put(f.address, squads.accounts.Multisig.fromArgs(f.state).serialize()[0]);
    const report = await governanceCheck(f.r, {multisig: f.address.toBase58()});
    expect(report.currentAuthoritiesValid).to.equal(true);
    expect(report.pendingProposals[0]).to.include({admitted: true, changesGovernance: false, stale: true, status: 'Approved'});
    expect(report.pendingProposalsSafe).to.equal(false);
    expect(report.sevenDayGovernanceApplied).to.equal(false);
  });
  it('ignores stale Active proposals that can no longer reach approval', async () => {
    const f = fixture();
    f.add(1, {__kind: 'Active', timestamp: 10}, [{__kind: 'SetTimeLock', newTimeLock: 0}]);
    const report = await governanceCheck(f.r, {multisig: f.address.toBase58()});
    expect(report.pendingProposals[0]).to.include({admitted: false, stale: true, status: 'Active'});
    expect(report.sevenDayGovernanceApplied).to.equal(true);
  });
  it('lists and decodes active and stale approved proposals, refusing a pending zero delay', async () => {
    const f = fixture();
    f.add(1, {__kind:'Approved', timestamp: 10}, [{__kind:'SetTimeLock', newTimeLock:0}]);
    f.add(2, {__kind:'Active', timestamp: 11}, [{__kind:'ChangeThreshold', newThreshold:1}]);
    const report: any = await governanceCheck(f.r, {multisig:f.address.toBase58()});
    expect(report.sevenDayGovernanceApplied).to.equal(false);
    expect(report.pendingProposals).to.have.length(2);
    expect(report.pendingProposals[0]).to.include({stale:true, admitted:false, status:'Approved'});
    expect(report.pendingProposals[0].actions[0]).to.include({__kind:'SetTimeLock',newTimeLock:0});
    expect(report.pendingProposals[0].reason).to.include('Unadmitted config action');
    expect(report.pendingProposals[1]).to.include({admitted:true,changesGovernance:true});
  });
  it('check returns an unadmitted proposal and reason instead of throwing', async () => {
    const f=fixture();f.add(1,{__kind:'Approved',timestamp:10},[{__kind:'SetTimeLock',newTimeLock:0}]);
    const op=await buildGovernance(f.r,{multisig:f.address.toBase58(),transactionIndex:'1'});
    expect((op.report as any).proposal.admitted).to.equal(false);
    expect((op.report as any).proposal.reason).to.include('Unadmitted config action');
  });
  it('allows hash-bound cancellation of a proposal the admission policy rejects', async () => {
    const f=fixture();f.add(1,{__kind:'Approved',timestamp:10},[{__kind:'SetTimeLock',newTimeLock:0}]);
    const report: any=await governanceCheck(f.r,{multisig:f.address.toBase58()});f.r.options.action='cancel';
    const op=await buildGovernance(f.r,{multisig:f.address.toBase58(),transactionIndex:'1',member:f.member.toBase58(),
      transactionSha256:report.pendingProposals[0].transactionSha256});
    expect(op.instructions[0].data.equals(squads.instructions.proposalCancel({multisigPda:f.address,transactionIndex:1n,member:f.member}).data)).to.equal(true);
  });
  it('reports IDL dispatch enabled or unknown without claiming complete governance', async () => {
    const f=fixture();
    for(const error of [{InstructionError:[0,{Custom:102}]}, 'AccountNotFound']) {
      f.r.connection.simulateTransaction=async()=>({value:{err:error}});
      const report:any=await governanceCheck(f.r,{multisig:f.address.toBase58()});
      expect(report.sevenDayGovernanceApplied).to.equal(false);
      expect(report.idlInstructionsDisabled).to.equal(false);
    }
  });
  it('selects checked extension from the finalized feature account, never a cluster label', async () => {
    const f=fixture(), bytes=Buffer.alloc(9);bytes[0]=1;bytes.writeBigUInt64LE(99n,1);
    const original=f.r.read;
    let feature:any={owner:new PublicKey('Feature111111111111111111111111111111111111'),executable:false,data:bytes};
    f.r.read=async(key:PublicKey)=>key.equals(EXTEND_CHECKED_FEATURE)?feature:original(key);
    expect(await checkedExtension(f.r)).to.equal(true);
    bytes.writeBigUInt64LE(101n,1);expect(await checkedExtension(f.r)).to.equal(false);
    bytes[0]=0;expect(await checkedExtension(f.r)).to.equal(false);
    feature=null;expect(await checkedExtension(f.r)).to.equal(false);
    feature={owner:PublicKey.default,executable:false,data:bytes};
    let error='';try{await checkedExtension(f.r);}catch(e:any){error=e.message;}
    expect(error).to.include('Invalid checked-extension');
  });
  it('builds the exact checked/unchecked loader encoding and required authority metas', async () => {
    for(const checked of [false,true]) {
      const f=fixture(),owner=PublicKey.unique(),data=Buffer.alloc(45);data.writeUInt32LE(3);data[12]=1;owner.toBuffer().copy(data,13);
      f.put(f.dataKey,data,LOADER);f.r.admin=owner;f.r.options.action='extend-program';
      f.r.connection.getMinimumBalanceForRentExemption=async()=>100;
      if(checked){const feature=Buffer.alloc(9);feature[0]=1;feature.writeBigUInt64LE(50n,1);
        f.put(EXTEND_CHECKED_FEATURE,feature,new PublicKey('Feature111111111111111111111111111111111111'));}
      const op=await buildGovernance(f.r,{multisig:f.address.toBase58(),binaryLength:1024}),ix=op.instructions[0];
      expect(ix.data.readUInt32LE(0)).to.equal(checked?9:6);expect(ix.data.readUInt32LE(4)).to.equal(1024);
      expect(ix.keys.map(k=>[k.pubkey.toBase58(),k.isWritable,k.isSigner])).to.deep.equal([
        [f.dataKey.toBase58(),true,false],[f.r.programId.toBase58(),true,false],
        ...(checked?[[owner.toBase58(),true,true]]:[]),[PublicKey.default.toBase58(),false,false],[f.r.feePayer.toBase58(),true,true]]);
    }
  });
  it('refuses extension after authority handoff', async () => {
    const f=fixture();f.r.options.action='extend-program';let error='';
    try{await buildGovernance(f.r,{multisig:f.address.toBase58(),binaryLength:100});}catch(e:any){error=e.message;}
    expect(error).to.include('Extend before handoff');
  });
  it('retains Round1 guardian separation while the settlement byte needs migration', async () => {
    const f=fixture(),city=PublicKey.unique(),read=f.r.read;
    f.r.pda=()=>city;
    f.r.read=async(key:PublicKey)=>key.equals(city)?{owner:f.r.programId,executable:false,data:Buffer.alloc(914)}:read(key);
    f.r.program={account:{stage1CityConfig:{size:963}},coder:{accounts:{decode:()=>({guardian:f.member,intakePaused:true,publisher:PublicKey.unique()})}}};
    const report:any=await governanceCheck(f.r,{multisig:f.address.toBase58()});
    expect(report).to.include({cityNeedsMigration:true,guardianRolesSeparate:false,intakePaused:true,settlementPaused:null,sevenDayGovernanceApplied:false});
    expect(report.guardian).to.equal(f.member.toBase58());
  });

});
