import {PublicKey, TransactionInstruction} from '@solana/web3.js';
import BN from 'bn.js';
import {cashClaimTerms,cashTermsCommitment,digest} from '../../scripts/stage1_claim_metadata.js';

export const claimTailBytes=(count:number)=>Math.ceil(count/8);
export const claimHeaderBytes=(program:any,name='Stage1ClaimSet')=>program.coder.accounts.size(program.idl.accounts.find((a:any)=>a.name===name));

// Publication witnesses retained by the test publisher across replay banks.
// This mirrors durable proof-bundle storage; it never invents missing metadata.
const witnesses=new Map<string,any>();
export function claimTerms(program:any,address:PublicKey){
  const value=witnesses.get(`${program.programId}:${address}`);
  if(!value)throw Error(`Publication witness unavailable for ${address}`);
  return value;
}
export async function rememberCashTerms(program:any,ix:TransactionInstruction){
  if(!ix.programId.equals(program.programId))return;
  const decoded=program.coder.instruction.decode(ix.data);
  if(decoded?.name!=='publishStage1ClaimSet')return;
  const def=program.idl.instructions.find((i:any)=>i.name===decoded.name);
  const flatten=(accounts:any[]):string[]=>accounts.flatMap(a=>a.accounts?flatten(a.accounts):[a.name]);
  const names=flatten(def.accounts),key=(name:string)=>ix.keys[names.indexOf(name)].pubkey;
  const book=await program.account.stage1WeekFunding.fetch(key('funding'));
  let release=Buffer.alloc(32);
  const be=(n:BN)=>n.toArrayLike(Buffer,'be',8);
  for(const meta of ix.keys.slice(names.length)){
    const info=await program.provider.connection.getAccountInfo(meta.pubkey,'processed');
    const source=info?.owner.equals(program.programId)
      ? await program.account.stage1WeekFunding.fetch(meta.pubkey)
      : (await program.account.stage1SettlementCursor.fetch(key('cursor'))).carriedHolds.find((h:any)=>h.source.equals(meta.pubkey));
    if(!source)throw Error(`Original hold witness unavailable for ${meta.pubkey}`);
    const expired=book.week.sub(source.week).gten(26);
    const after=expired?source.holds.map(()=>new BN(0)):source.proposalRemaining;
    const pool=expired?source.holds.reduce((a:BN,b:BN)=>a.add(b),source.pool):source.pool;
    release=digest(Buffer.from('BR-stage1-v1:release\0'),release,meta.pubkey.toBuffer(),Buffer.from(source.lineage),be(source.week),be(source.revision),...source.holds.map(be),...after.map(be),be(pool));
  }
  witnesses.set(`${program.programId}:${key('claimSet')}`,cashClaimTerms(book,decoded.data.newHolds,release));
}
export async function verifyStoredTerms(program:any,address:PublicKey){
  const set=await program.account.stage1ClaimSet.fetch(address);
  if(!cashTermsCommitment(address,claimTerms(program,address)).equals(Buffer.from(set.metadataHash)))throw Error('Publication witness mismatch');
}

// Small sets prepare and seal atomically. Large sets are explicitly grown by
// the publisher in the capacity tests before the publication transaction.
export async function withClaimStorage(program:any,ix:TransactionInstruction):Promise<TransactionInstruction[]> {
  if(!ix.programId.equals(program.programId))return [ix];
  const decoded=program.coder.instruction.decode(ix.data);
  if(!decoded||!['publishStage1ClaimSet','publishStage1DungClaimSet'].includes(decoded.name))return [ix];
  await rememberCashTerms(program,ix);
  const definition=program.idl.instructions.find((i:any)=>i.name===decoded.name);
  const flatten=(accounts:any[]):string[]=>accounts.flatMap(a=>a.accounts?flatten(a.accounts):[a.name]);
  const names=flatten(definition.accounts);
  const key=(name:string)=>ix.keys[names.indexOf(name)].pubkey;
  const shared={city:key('city'),claimSet:key('claimSet'),publisher:key('publisher'),systemProgram:key('systemProgram')};
  const prepare=decoded.name==='publishStage1ClaimSet'
    ? program.methods.prepareStage1ClaimSet(decoded.data.leafCount).accounts({...shared,asset:key('asset'),funding:key('funding')})
    : program.methods.prepareStage1DungClaimSet(decoded.data.role,decoded.data.root.leafCount).accounts({...shared,dung:key('dung')});
  return [await prepare.instruction(),ix];
}
