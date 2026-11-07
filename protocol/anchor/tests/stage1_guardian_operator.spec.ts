import { expect } from 'chai';
import * as anchor from '@coral-xyz/anchor';
import * as squads from '@sqds/multisig';
import { PublicKey, TransactionMessage } from '@solana/web3.js';
import { createHash } from 'crypto';
import { readFileSync } from 'fs';
import { buildGovernance, vaultFor } from '../scripts/stage1_governance.js';
const idl = JSON.parse(readFileSync(new URL('../idl/boulder_rollers.json',import.meta.url),'utf8'));
function fixture(timeLock=0) {
  const createKey=PublicKey.unique(),[multisig,bump]=squads.getMultisigPda({createKey}),vault=vaultFor(multisig);
  const member=PublicKey.unique(),programId=PublicKey.unique(),city=PublicKey.unique(),config=PublicKey.unique();
  const state={createKey,bump,configAuthority:PublicKey.default,timeLock,threshold:1,
    transactionIndex:0,staleTransactionIndex:0,rentCollector:null,members:[{key:member,permissions:{mask:7}}]};
  const stored=new Map<string,any>();
  const real=new anchor.Program(idl,programId,{connection:{},wallet:{publicKey:member}} as any);
  const r:any={options:{role:'guardian',action:'propose'},programId,feePayer:PublicKey.unique(),
    pda:(seed:string)=>seed==='s1v1_city'?city:config,
    read:async(key:PublicKey)=>key.equals(squads.PROGRAM_ID)?{executable:true}:key.equals(multisig)
      ?{owner:squads.PROGRAM_ID,executable:false,data:squads.accounts.Multisig.fromArgs(state).serialize()[0]}
      :key.equals(city)?{owner:programId,executable:false,data:Buffer.alloc(963)}:stored.get(key.toBase58()),
    connection:{getProgramAccounts:async()=>[]},
    program:{...real,idl,coder:{...real.coder,accounts:{decode:()=>({guardian:vault,publisher:PublicKey.default,registrar:PublicKey.default})}},
      account:{stage1CityConfig:{size:963}},methods:real.methods}};
  return {r,input:{multisig:multisig.toBase58(),member:member.toBase58(),transactionIndex:'1',call:'pauseStage1Intake',transactionSha256:''},
    vault,state,stored,multisig,member,city,config};
}
async function storedProposal() {
  const f=fixture(),{r,multisig,vault,member,city}=f;
  const ix=await r.program.methods.pauseStage1Intake().accountsStrict({city,guardian:vault}).instruction();
  const compiled=new TransactionMessage({payerKey:vault,recentBlockhash:PublicKey.default.toBase58(),instructions:[ix]}).compileToLegacyMessage();
  const [txKey,bump]=squads.getTransactionPda({multisigPda:multisig,index:1n});
  const [proposalKey,proposalBump]=squads.getProposalPda({multisigPda:multisig,transactionIndex:1n});
  const tx:any={multisig,creator:member,index:1,bump,vaultIndex:0,vaultBump:squads.getVaultPda({multisigPda:multisig,index:0})[1],
    ephemeralSignerBumps:new Uint8Array(),message:{numSigners:compiled.header.numRequiredSignatures,
      numWritableSigners:compiled.header.numRequiredSignatures-compiled.header.numReadonlySignedAccounts,
      numWritableNonSigners:compiled.accountKeys.length-compiled.header.numRequiredSignatures-compiled.header.numReadonlyUnsignedAccounts,
      accountKeys:compiled.accountKeys,instructions:[{programIdIndex:compiled.accountKeys.findIndex(k=>k.equals(ix.programId)),
        accountIndexes:Uint8Array.from(ix.keys.map((k:any)=>compiled.accountKeys.findIndex(v=>v.equals(k.pubkey)))),data:ix.data}],addressTableLookups:[]}};
  const proposal:any={multisig,transactionIndex:1,bump:proposalBump,status:{__kind:'Active'},approved:[],rejected:[],cancelled:[]};
  const save=()=>{
    const bytes=squads.accounts.VaultTransaction.fromArgs(tx).serialize()[0];
    f.stored.set(txKey.toBase58(),{owner:squads.PROGRAM_ID,executable:false,data:bytes});
    f.stored.set(proposalKey.toBase58(),{owner:squads.PROGRAM_ID,executable:false,data:squads.accounts.Proposal.fromArgs(proposal).serialize()[0]});
    f.input.transactionSha256=createHash('sha256').update(bytes).digest('hex');
  };
  r.options.action='approve';f.state.transactionIndex=1;save();return {...f,tx,proposal,save};
}
async function refuses(f:Awaited<ReturnType<typeof storedProposal>>,reason:string) {
  let message='';try{await buildGovernance(f.r,f.input);}catch(e:any){message=e.message;}expect(message).include(reason);
}
describe('separate no-delay guardian Squads operator',()=>{
  for (const call of ['pauseStage1Intake','resumeStage1Intake','pauseStage1Settlement','resumeStage1Settlement']) it(`builds ${call} for a configured guardian vault`,async()=>{
    const {r,input}=fixture();input.call=call;expect((await buildGovernance(r,input)).instructions).length(2);
  });
  it('refuses an admin-delay vault, a fund-moving call and a nonmember',async()=>{
    for(const change of [(f:any)=>f.input.call='claimStage1',(f:any)=>f.input.member=PublicKey.unique().toBase58()]) {
      const f=fixture();change(f);let failed=false;try{await buildGovernance(f.r,f.input);}catch{failed=true;}expect(failed).eq(true);
    }
    const f=fixture(604800);let message='';try{await buildGovernance(f.r,f.input);}catch(e:any){message=e.message;}expect(message).include('no delay');
  });
  it('builds an actual proposal for the configured guardian vault without the admin delay',async()=>{
    const {r,input}=fixture();const op=await buildGovernance(r,input);
    expect(op.instructions).length(2);expect(op.instructions.every(ix=>ix.programId.equals(squads.PROGRAM_ID))).eq(true);
    expect(op.description).include('guardian');
  });
  it('approves the exact serialized guardian call and refuses a changed reviewed hash',async()=>{
    const f=await storedProposal();expect((await buildGovernance(f.r,f.input)).instructions).length(1);
    f.input.transactionSha256='00'.repeat(32);await refuses(f,'differs from reviewed hash');
  });
  for(const [name,change] of Object.entries({
    call:(f:any)=>f.tx.message.instructions[0].data=Buffer.alloc(8),
    program:(f:any)=>f.tx.message.accountKeys[f.tx.message.instructions[0].programIdIndex]=PublicKey.unique(),
    account:(f:any)=>f.tx.message.accountKeys[f.tx.message.instructions[0].accountIndexes[0]]=PublicKey.unique(),
    privilege:(f:any)=>f.tx.message.numWritableNonSigners=0,
  })) it(`refuses an altered stored ${name} even with its matching byte hash`,async()=>{
    const f=await storedProposal();change(f);f.save();await refuses(f,'differs from exact reviewed call');
  });
  it('refuses extra instructions and stale Approved proposals',async()=>{
    const f=await storedProposal();f.tx.message.instructions.push(f.tx.message.instructions[0]);f.save();
    await refuses(f,'Unsupported guardian transaction');
    const stale=await storedProposal();stale.state.staleTransactionIndex=1;stale.proposal.status={__kind:'Approved',timestamp:1};
    stale.save();stale.r.options.action='execute';await refuses(stale,'stale proposal');
  });
});
