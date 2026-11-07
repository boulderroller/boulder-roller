import { expect } from 'chai';
import * as anchor from '@coral-xyz/anchor';
import BN from 'bn.js';
import { PublicKey } from '@solana/web3.js';
import { readFileSync } from 'fs';
import { releaseOperation, typedValue, acceptedReleaseVersions } from '../scripts/stage1_release_operator.js';
import { CURRENT_PROGRAM_VERSION, PREVIOUS_PROGRAM_VERSION } from '../generated-program-version.js';
const idl = JSON.parse(readFileSync(new URL('../idl/boulder_rollers.json', import.meta.url), 'utf8'));
const admin = PublicKey.unique(), config = PublicKey.unique(), programId = PublicKey.unique();
function operator(action: string, version: number = PREVIOUS_PROGRAM_VERSION): any {
  return { options: { action }, admin, pda: () => config, read: async () => null,
    fetch: async () => ({ initialized: true, programVersion: version }),
    program: new anchor.Program(idl, programId, { connection: {}, wallet: { publicKey: admin } } as any) };
}
function advanceInput() {
  return { calls: [{ name: 'advanceProgramVersion', args: { expectedCurrentVersion: String(PREVIOUS_PROGRAM_VERSION), newVersion: String(CURRENT_PROGRAM_VERSION) },
    accounts: { programConfig: config.toBase58(), admin: admin.toBase58() } }],
    assertions: [{ account: config.toBase58(), type: 'ProgramConfig', fields: { programVersion: CURRENT_PROGRAM_VERSION } }] };
}
async function refuses(action: Promise<any>, reason: string) {
  let error = ''; try { await action; } catch (e: any) { error = e.message; }
  expect(error).to.include(reason);
}
describe('composed release exact-input operator', () => {
  it('admits old config only for advance, and makes an already advanced config a checked no-op', async () => {
    expect(acceptedReleaseVersions('advance')).deep.eq([PREVIOUS_PROGRAM_VERSION, CURRENT_PROGRAM_VERSION]);
    expect(acceptedReleaseVersions('execute')).deep.eq([CURRENT_PROGRAM_VERSION]);
    expect(() => acceptedReleaseVersions('anything')).to.throw('action');
    const op = await releaseOperation(operator('advance', CURRENT_PROGRAM_VERSION), advanceInput());
    expect(op.instructions).to.have.length(0); await op.assert();
  });
  it('requires the constrained advance action for version mutation', async () => {
    await refuses(releaseOperation(operator('execute'), advanceInput()), 'advance action');
  });
  it('refuses other calls, extra accounts, version choices and missing outcome in advance action', async () => {
    for (const change of [
      (x: any) => x.calls.push(x.calls[0]),
      (x: any) => x.calls[0].name = 'setStage1Publisher',
      (x: any) => x.calls[0].args.newVersion = String(CURRENT_PROGRAM_VERSION + 1),
      (x: any) => x.calls[0].accounts.admin = PublicKey.unique().toBase58(),
      (x: any) => x.calls[0].remainingAccounts = [{ key: PublicKey.unique().toBase58(), writable: false, signer: false }],
      (x: any) => x.assertions[0].fields.programVersion = PREVIOUS_PROGRAM_VERSION,
    ]) { const input = advanceInput(); change(input); await refuses(releaseOperation(operator('advance'), input), 'advance'); }
  });
  it('encodes exactly the admitted version advance and verifies its finalized outcome', async () => {
    const r = operator('advance'); const op = await releaseOperation(r, advanceInput());
    expect(op.instructions).to.have.length(1);
    expect(r.program.coder.instruction.decode(op.instructions[0].data).data)
      .deep.eq({ expectedCurrentVersion: PREVIOUS_PROGRAM_VERSION, newVersion: CURRENT_PROGRAM_VERSION });
    await refuses(op.assert(), 'Finalized outcome differs');
    r.fetch = async () => ({ programVersion: CURRENT_PROGRAM_VERSION }); await op.assert();
  });
  it('rejects malformed outcome assertions during planning, before any submission', async () => {
    for (const assertion of [
      {account: config.toBase58(),type:'ProgramConfig',fields:{}},
      {account: config.toBase58(),type:'MissingAccount',fields:{programVersion:77}},
      {account: config.toBase58(),type:'ProgramConfig',fields:{notAField:77}},
      {account: config.toBase58(),type:'spl-token',fields:{amount:'01'}},
      {account: config.toBase58(),type:'spl-token',fields:{owner:[...admin.toBytes()]}},
    ]) {
      const input = {calls:[{name:'setStage1Publisher',args:{publisher:PublicKey.unique().toBase58()},
        accounts:{city:config.toBase58(),programConfig:config.toBase58(),admin:admin.toBase58()}}],assertions:[assertion]};
      await refuses(releaseOperation(operator('execute', CURRENT_PROGRAM_VERSION),input),'outcome');
    }
  });
  it('requires precise integers and complete argument fields', async () => {
    expect(() => typedValue('u64', 9007199254740992, idl)).to.throw('decimal strings');
    expect(() => typedValue('u8', '256', idl)).to.throw('out of range');
    expect(typedValue('u64', '9007199254740993', idl).toString()).eq('9007199254740993');
    const input = advanceInput(); delete (input.calls[0].args as any).newVersion;
    await refuses(releaseOperation(operator('advance'), input), 'advance');
  });
  it('verifies closure absence and the original payer lamport refund without fabricating absent balances',async()=>{
    const r=operator('execute',CURRENT_PROGRAM_VERSION),closed=PublicKey.unique(),payer=PublicKey.unique();
    const input={calls:[{name:'closeStage1ClaimSet',args:{},accounts:{claimSet:closed.toBase58(),rentPayer:payer.toBase58()}}],
      assertions:[{account:closed.toBase58(),type:'account-state',fields:{exists:false}},
        {account:payer.toBase58(),type:'account-state',fields:{exists:true,lamports:'12345'}}]};
    const op=await releaseOperation(r,input);
    r.read=async(key:PublicKey)=>key.equals(closed)?null:{lamports:12345};await op.assert();
    r.read=async()=>({lamports:12345});await refuses(op.assert(),'Finalized outcome differs');
    const invalid={...input,assertions:[{account:closed.toBase58(),type:'account-state',fields:{exists:false,lamports:'0'}}]};
    await refuses(releaseOperation(r,invalid),'Absent accounts');
  });

  it('requires explicit registered DUNG totals and accepts the unminted outcome',async()=>{
    const value:any={sourceSnapshot:Array(32).fill('1'),fieldCount:'5',postbondTssMicros:'5000000',topCount:'3',ascentCount:'5',earnedLegend:true,
      opening:{basis:Array(8).fill('0'),backing:Array(8).fill('0')},payableRoleTotals:['2325000','2500000']};
    expect(typedValue({defined:'Stage1DungInput'},value,idl).payableRoleTotals.map((n:any)=>n.toString())).deep.eq(['2325000','2500000']);
    delete value.payableRoleTotals;
    expect(()=>typedValue({defined:'Stage1DungInput'},value,idl)).to.throw();
    const r=operator('execute',CURRENT_PROGRAM_VERSION),record=PublicKey.unique();
    const op=await releaseOperation(r,{calls:[{name:'setStage1Publisher',args:{publisher:admin.toBase58()},accounts:{city:config.toBase58(),programConfig:config.toBase58(),admin:admin.toBase58()}}],
      assertions:[{account:record.toBase58(),type:'Stage1DungMint',fields:{unminted:'175000'}}]});
    r.fetch=async()=>({unminted:new BN(175000)});await op.assert();
  });

});
