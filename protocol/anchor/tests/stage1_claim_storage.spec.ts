import * as anchor from '@coral-xyz/anchor';
import BN from 'bn.js';
import { expect } from 'chai';
import { createHash } from 'crypto';
import { execFileSync } from 'child_process';
import { fileURLToPath } from 'url';
import { resolve } from 'path';
import { writeFileSync } from 'fs';
import { ComputeBudgetProgram, Keypair, PublicKey, SystemProgram, TransactionInstruction, TransactionMessage, VersionedTransaction } from '@solana/web3.js';
import { MINT_SIZE, MintLayout, TOKEN_PROGRAM_ID, createInitializeMint2Instruction, createMintToInstruction,
  createAssociatedTokenAccountIdempotentInstruction, createFreezeAccountInstruction, createThawAccountInstruction,
  getAccount, getAssociatedTokenAddressSync } from '@solana/spl-token';
import { capture, replay, Capture } from './helpers/stage1_replay.js';
import {cashClaimTerms,cashTermsCommitment,digest} from '../scripts/stage1_claim_metadata.js';
import { claimTerms, rememberCashTerms, verifyStoredTerms, claimHeaderBytes, claimTailBytes } from './helpers/stage1_claim_storage.js';

const enabled=process.env.STAGE1_LOCALNET==='1'||process.env.STAGE1_DEPLOYABLE==='1';
const testMint=process.env.STAGE1_LOCALNET==='1'||process.env.STAGE1_DEVNET==='1';
const ROOT=resolve(fileURLToPath(new URL('../../..',import.meta.url)));
const PYTHON=process.env.STAGE1_ORACLE_PYTHON??'python3';
let provider=anchor.AnchorProvider.env();anchor.setProvider(provider);let program:any=anchor.workspace.BoulderRollers;
const originalProvider=provider,originalProgram=program,wallet=provider.wallet as anchor.Wallet;
const publisher=Keypair.generate(),replacement=Keypair.generate(),people=[Keypair.generate(),Keypair.generate()],recipient=Keypair.generate().publicKey;
const newRider=Keypair.generate(),newRecipient=Keypair.generate().publicKey;
const W=604800,LAUNCH=1791201600,bn=(n:any)=>new BN(String(n)),u64=(n:number)=>bn(n).toArrayLike(Buffer,'le',8);
const hash=(v:string)=>createHash('sha256').update(v).digest();
const pda=(s:string,...parts:Buffer[])=>PublicKey.findProgramAddressSync([Buffer.from(s),...parts],program.programId)[0];
const city=()=>pda('s1v1_city'),config=()=>pda('program_config');
let mint:PublicKey,hill:PublicKey,source:PublicKey,destination:PublicKey,serial=0,active:Awaited<ReturnType<typeof replay>>|undefined;
const asset=()=>pda('s1v1_asset',mint.toBuffer()),earnings=()=>pda('s1v1_earnings',mint.toBuffer()),cursor=()=>pda('s1v1_cursor',hill.toBuffer(),mint.toBuffer());
const funding=(week:number)=>pda('s1v1_funding',hill.toBuffer(),mint.toBuffer(),u64(week));
const set=(week:number)=>pda('s1v1_claims',hill.toBuffer(),mint.toBuffer(),u64(week));
const evidence:any={evidence:'LOCAL transactions, synthetic cash allocations; standard-rent comparisons',build:process.env.STAGE1_LOCALNET?'localnet':process.env.STAGE1_DEVNET?'devnet':'default',weeks:[]};
async function send(calls:any,signers:Keypair[]=[],measure=false,payer=wallet.payer){
  const instructions=await Promise.all((Array.isArray(calls)?calls:[calls]).map(c=>c instanceof TransactionInstruction?c:c.instruction()));
  const publications=instructions.filter(ix=>ix.programId.equals(program.programId)&&program.coder.instruction.decode(ix.data)?.name==='publishStage1ClaimSet');
  const previousCommitment=publications.length?Buffer.from((await program.account.stage1SettlementCursor.fetch(cursor())).publicationCommitment):undefined;
  for(const ix of instructions)await rememberCashTerms(program,ix);
  const block=await provider.connection.getLatestBlockhash('processed');
  const tx=new VersionedTransaction(new TransactionMessage({payerKey:payer.publicKey,recentBlockhash:block.blockhash,
    instructions:[ComputeBudgetProgram.setComputeUnitLimit({units:1_400_000}),ComputeBudgetProgram.setComputeUnitPrice({microLamports:++serial}),...instructions]}).compileToLegacyMessage());
  tx.sign([payer,...signers]);
  const wire=tx.serialize();expect(wire.length).at.most(1232);
  let probe:any;
  if(measure){const result=await provider.connection.simulateTransaction(tx,{commitment:'processed',sigVerify:true});
    expect(result.value.err,result.value.logs?.join('\n')).eq(null);probe={computeUnits:result.value.unitsConsumed,transactionBytes:wire.length,feeLamports:(await provider.connection.getFeeForMessage(tx.message,'processed')).value};}
  const signature=await provider.connection.sendRawTransaction(wire,{preflightCommitment:'processed'});
  expect((await provider.connection.confirmTransaction({...block,signature},'processed')).value.err).eq(null);
  if(publications.length){
    await provider.connection.confirmTransaction({...block,signature},'confirmed');
    let tx:any;for(let n=0;n<30&&!tx;n++){tx=await provider.connection.getTransaction(signature,{commitment:'confirmed',maxSupportedTransactionVersion:0});if(!tx)await new Promise(r=>setTimeout(r,100));}
    expect(tx,'confirmed cash publication').not.eq(null);let commitment=previousCommitment!;
    for(const line of tx.meta.logMessages??[]){
      if(!line.startsWith('Program data: '))continue;
      const encoded=line.slice(14),event=program.coder.events.decode(encoded);
      if(event?.name!=='Stage1CashPublished')continue;
      const e=event.data,a=e.audit,terms=cashClaimTerms({cap:e.terms.cap,frozenAt:e.terms.frozenAt,snapshot:a.snapshot,lineage:a.sourceLineage,boostCommitment:a.boostCommitment},a.newHolds,Buffer.from(a.releaseCommitment));
      expect(terms.auditHash).deep.eq(e.terms.auditHash);
      const set=await program.account.stage1ClaimSet.fetch(e.claimSet);
      expect(cashTermsCommitment(e.claimSet,terms).equals(Buffer.from(set.metadataHash))).eq(true);
      commitment=digest(Buffer.from('BR-stage1-v2:cash-publication\0'),commitment,Buffer.from(encoded,'base64').subarray(8));
    }
    expect(Buffer.from((await program.account.stage1SettlementCursor.fetch(cursor())).publicationCommitment).equals(commitment)).eq(true);
  }
  return {...probe,signature};
}
async function reject(action:Promise<unknown>,reason:string){try{await action;}catch(e:any){expect(`${e.message}\n${e.logs?.join('\n')}`).include(reason);return;}throw Error(`Expected ${reason}`);}
async function saved(){return capture(provider.connection,program.programId,[wallet.publicKey,publisher.publicKey,replacement.publicKey,...people.map(p=>p.publicKey)]);}
async function move(at:number,from?:Capture){const accounts=from??await saved();await active?.stop();active=await replay(accounts,at,false);
  provider=new anchor.AnchorProvider(active.connection,wallet,{commitment:'processed',preflightCommitment:'processed'});program=new anchor.Program(originalProgram.idl,originalProgram.programId,provider);}
const bytes=async(keys:PublicKey[])=>Promise.all(keys.map(async key=>(await provider.connection.getAccountInfo(key,'processed'))?.data.toString('base64')??null));
const prepare=(week:number,count:number,pub=publisher.publicKey)=>program.methods.prepareStage1ClaimSet(count).accounts({city:city(),asset:asset(),funding:funding(week),claimSet:set(week),publisher:pub,systemProgram:SystemProgram.programId});
const seal=(week:number,tree:any)=>program.methods.publishStage1ClaimSet([...Buffer.from(tree.root,'hex')],bn(tree.total),tree.count,Array(5).fill(bn(0)))
  .accounts({city:city(),hillAccount:{hill},asset:asset(),funding:funding(week),claimSet:set(week),earnings:earnings(),publisher:publisher.publicKey,systemProgram:SystemProgram.programId,cursor:cursor()});
const leafArgs=(leaf:any)=>({index:leaf.index,amount:bn(leaf.amount),proof:leaf.proof.map((p:any)=>({hash:[...Buffer.from(p.hash,'hex')],sum:bn(p.sum)}))});
const claim=(week:number,leaf:any)=>{const v=leafArgs(leaf);return program.methods.claimStage1(v.index,new PublicKey(leaf.person),v.amount,v.proof,claimTerms(program,set(week))).accounts({city:city(),asset:asset(),claimSet:set(week),registration:pda('s1v1_recipient',new PublicKey(leaf.person).toBuffer()),earnings:earnings(),destination,tokenProgram:TOKEN_PROGRAM_ID});};
const batch=(entries:{week:number,leaf:any,terms?:any}[])=>program.methods.claimStage1Batch(people[0].publicKey,entries.map(e=>({...leafArgs(e.leaf),terms:e.terms??claimTerms(program,set(e.week))}))).accounts({city:city(),asset:asset(),registration:pda('s1v1_recipient',people[0].publicKey.toBuffer()),earnings:earnings(),destination,tokenProgram:TOKEN_PROGRAM_ID}).remainingAccounts(entries.map(e=>({pubkey:set(e.week),isWritable:true,isSigner:false})));
function tree(week:number,keys:PublicKey[],recipientKey=recipient){return JSON.parse(execFileSync(PYTHON,['-m','tools.stage1_reference.claim_vectors','--merkle-stdin'],{cwd:ROOT,encoding:'utf8',input:JSON.stringify({kind:'payments',context:[program.programId.toBase58(),city().toBase58(),hill.toBase58(),week,mint.toBase58()],payments:keys.map(p=>[p.toBase58(),recipientKey.toBase58(),9]),...(keys.length>300?{indices:[0,1]}:{})})}));}
async function fund(week:number,count:number){
  await send(program.methods.openStage1Week(bn(week)).accounts({city:city(),hillAccount:{hill},asset:asset(),funding:funding(week),payer:wallet.publicKey,systemProgram:SystemProgram.programId,cursor:cursor()}));
  await send(program.methods.sponsorStage1(bn(count*9)).accounts({city:city(),asset:asset(),cash:pda('s1v1_cash'),funding:funding(week),cursor:cursor(),earnings:earnings(),source,funder:wallet.publicKey,tokenProgram:TOKEN_PROGRAM_ID}));
  await move(LAUNCH+(week+1)*W+86400+100);
  await send(program.methods.freezeStage1Snapshot([...hash(`storage-${week}`)],bn(9)).accounts({city:city(),hill,asset:asset(),funding:funding(week),previous:null,publisher:publisher.publicKey,cursor:cursor()}),[publisher]);
}
async function allocate(week:number,count:number){const required=claimHeaderBytes(program)+claimTailBytes(count);
  while((await provider.connection.getAccountInfo(set(week),'processed'))?.data.length!==required){const length=(await provider.connection.getAccountInfo(set(week),'processed'))?.data.length??0;
    await send(Array.from({length:Math.min(8,Math.ceil((required-length)/10240))},()=>prepare(week,count)),[publisher]);}
}
async function publish(week:number,keys:PublicKey[]){const t=tree(week,keys);await fund(week,keys.length);await allocate(week,keys.length);await send(seal(week,t),[publisher]);return t;}

if(enabled)describe('publisher prepaid claims and multiweek batches on LOCAL validator',()=>{
  before(async()=>{
    expect(['127.0.0.1','localhost']).include(new URL(provider.connection.rpcEndpoint).hostname);
    const clean=await capture(provider.connection,program.programId,[wallet.publicKey]);
    for(const [key,a] of clean)if(a.owner.equals(program.programId)||a.owner.equals(TOKEN_PROGRAM_ID))clean.delete(key);
    await move(LAUNCH+100,clean);
    const executable=(await provider.connection.getAccountInfo(program.programId))!;
    await send(program.methods.initializeProgramConfig(wallet.publicKey).accounts({programConfig:config(),program:program.programId,programData:new PublicKey(executable.data.subarray(4,36)),admin:wallet.publicKey,systemProgram:SystemProgram.programId}));
    await send(program.methods.initCityConfig(bn(LAUNCH)).accounts({city:city(),programConfig:config(),admin:wallet.publicKey,systemProgram:SystemProgram.programId}));
    for(const p of [publisher,replacement,...people])await send(SystemProgram.transfer({fromPubkey:wallet.publicKey,toPubkey:p.publicKey,lamports:3_000_000_000}));
    await send(program.methods.setStage1Publisher(publisher.publicKey).accounts({city:city(),programConfig:config(),admin:wallet.publicKey}));
    for(const p of people)await send(program.methods.registerStage1Recipient(recipient).accounts({registration:pda('s1v1_recipient',p.publicKey.toBuffer()),person:p.publicKey,payer:wallet.publicKey,systemProgram:SystemProgram.programId}),[p]);
    if(testMint){const key=Keypair.generate();mint=key.publicKey;await send([SystemProgram.createAccount({fromPubkey:wallet.publicKey,newAccountPubkey:mint,space:MINT_SIZE,lamports:await provider.connection.getMinimumBalanceForRentExemption(MINT_SIZE),programId:TOKEN_PROGRAM_ID}),createInitializeMint2Instruction(mint,6,wallet.publicKey,wallet.publicKey)],[key]);}
    else{mint=new PublicKey('EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v');const data=Buffer.alloc(MINT_SIZE);
      // Synthetic LOCAL SPL mint at the production USDC identity, not a Circle capture.
      MintLayout.encode({mintAuthorityOption:1,mintAuthority:wallet.publicKey,supply:0n,decimals:6,isInitialized:true,freezeAuthorityOption:1,freezeAuthority:wallet.publicKey},data);
      const accounts=await saved();accounts.set(mint.toBase58(),{data,owner:TOKEN_PROGRAM_ID,executable:false,rentEpoch:0,lamports:await provider.connection.getMinimumBalanceForRentExemption(MINT_SIZE)});await move(LAUNCH+100,accounts);}
    source=getAssociatedTokenAddressSync(mint,wallet.publicKey);destination=getAssociatedTokenAddressSync(mint,recipient);
    await send([createAssociatedTokenAccountIdempotentInstruction(wallet.publicKey,source,wallet.publicKey,mint),createAssociatedTokenAccountIdempotentInstruction(wallet.publicKey,destination,recipient,mint),createMintToInstruction(mint,source,wallet.publicKey,1000000)]);
    await send(program.methods.registerStage1Cash().accounts({city:city(),cash:pda('s1v1_cash'),asset:asset(),mint,earnings:earnings(),programConfig:config(),admin:wallet.publicKey,tokenProgram:TOKEN_PROGRAM_ID,systemProgram:SystemProgram.programId}));
    const id=hash('storage-hill').subarray(0,16),profile=hash('storage-profile'),commitment=Buffer.alloc(64);commitment[0]=1;id.copy(commitment,1);commitment.writeUInt16BE(1,17);profile.copy(commitment,32);const digest=createHash('sha256').update(commitment).digest(),climb=pda('climb',digest);hill=pda('s1v1_hill',id);
    await send(program.methods.registerRatifiedClimb({canonId:[...id],canonVersion:1,canonicalProfileHash:[...profile],commitmentHash:[...digest],recordContinuityPolicy:{newRecordBoard:{}},name:'Local claim storage',vertM:100,distanceM:1000,avgGradientPct:1000}).accounts({climb,climbVersionIndex:pda('climb_version',id,Buffer.from([0,1])),predecessorClimb:null,programConfig:config(),admin:wallet.publicKey,systemProgram:SystemProgram.programId}));
    await send(program.methods.initHillBond().accounts({city:city(),climb,hill,programConfig:config(),admin:wallet.publicKey,systemProgram:SystemProgram.programId}));
    await send(program.methods.initStage1Settlement().accounts({city:city(),hillAccount:{hill},asset:asset(),cursor:cursor(),payer:wallet.publicKey,systemProgram:SystemProgram.programId}));
  });
  after(async()=>{if(process.env.STAGE1_STORAGE_EVIDENCE)writeFileSync(process.env.STAGE1_STORAGE_EVIDENCE,JSON.stringify(evidence,null,2)+'\n');await active?.stop();provider=originalProvider;program=originalProgram;});
  it('registers a zero-lamport person using a separate rent payer, once and without redirect',async()=>{
    const person=newRider,registration=pda('s1v1_recipient',person.publicKey.toBuffer());
    expect(await provider.connection.getBalance(person.publicKey,'processed')).eq(0);
    const register=(recipient:PublicKey)=>program.methods.registerStage1Recipient(recipient).accounts({registration,person:person.publicKey,payer:wallet.publicKey,systemProgram:SystemProgram.programId});
    await send(register(newRecipient),[person]);
    expect(await provider.connection.getBalance(person.publicKey,'processed')).eq(0);
    expect((await program.account.stage1Recipient.fetch(registration)).recipient.equals(newRecipient)).eq(true);
    const before=await bytes([registration]);
    await reject(send(register(Keypair.generate().publicKey),[person]),'already in use');
    expect(await bytes([registration])).deep.eq(before);
    evidence.registration={personLamports:0,rentLamports:(await provider.connection.getAccountInfo(registration,'processed'))!.lamports,payer:'separate transaction sponsor'};
  });
  for(const [week,count] of [10,100,1000].entries())it(`publishes ${count} leaves with measured publisher rent and no per-claim allocation`,async()=>{
    const keys=[...people.map(p=>p.publicKey),...Array.from({length:count-2},()=>Keypair.generate().publicKey)];const t=tree(week,keys);await fund(week,count);
    const before=await provider.connection.getBalance(publisher.publicKey,'processed');await allocate(week,count);await send(seal(week,t),[publisher]);
    await verifyStoredTerms(program,set(week));
    const info=(await provider.connection.getAccountInfo(set(week),'processed'))!,rent=await provider.connection.getMinimumBalanceForRentExemption(info.data.length);
    expect(info.data.length).eq(claimHeaderBytes(program)+claimTailBytes(count));expect(info.lamports).eq(rent);expect(before-await provider.connection.getBalance(publisher.publicKey,'processed')).eq(rent);
    const old=await provider.connection.getMinimumBalanceForRentExemption(393)+count*(await provider.connection.getMinimumBalanceForRentExemption(84)+await provider.connection.getMinimumBalanceForRentExemption(44));
    const accounts=(await provider.connection.getProgramAccounts(program.programId,{commitment:'processed'})).length,balance=(await getAccount(provider.connection,destination,'processed')).amount;
    const probe=await send(claim(week,t.leaves[0]),[],true);await send(claim(week,t.leaves[1]));
    expect((await getAccount(provider.connection,destination,'processed')).amount-balance).eq(18n);expect((await provider.connection.getProgramAccounts(program.programId,{commitment:'processed'})).length).eq(accounts);
    expect((await provider.connection.getAccountInfo(set(week),'processed'))!.lamports).eq(rent);
    const stored=(await provider.connection.getAccountInfo(set(week),'processed'))!.data;expect(stored[claimHeaderBytes(program)]&3).eq(3);
    await reject(send(claim(week,t.leaves[0])),'Stage1ClaimReplay');await reject(send(prepare(week,1),[publisher]),'Stage1ClaimStorage');
    const dungBytes=claimHeaderBytes(program,'Stage1DungClaimSet')+claimTailBytes(count),dungRoleRentLamports=await provider.connection.getMinimumBalanceForRentExemption(dungBytes);
    evidence.weeks.push({leaves:count,bytes:info.data.length,rentLamports:rent,dungBytes,dungRoleRentLamports,oldTotalRentLamports:old,claimRentLamports:0,...probe});console.log(`    ${count} leaves: ${rent} lamports vs ${old}; claim ${probe.computeUnits} CU, ${probe.transactionBytes} bytes, zero tracking accounts`);
  });
  it('pays three weeks atomically, rejects alias/proof/CPI failures, and preserves single-claim bits',async()=>{
    const entries=[];for(const week of [3,4,5]){const t=await publish(week,people.map(p=>p.publicKey));entries.push({week,leaf:t.leaves[0]});await send(claim(week,t.leaves[1]));}
    const tracked=[asset(),earnings(),destination,...entries.map(e=>set(e.week))];const before=await bytes(tracked);
    const badTerms={...claimTerms(program,set(entries[2].week)),cap:bn(10)};
    await reject(send(batch([entries[0],entries[1],{...entries[2],terms:badTerms}])),'Stage1InvalidProof');expect(await bytes(tracked)).deep.eq(before);
    await reject(send(batch([entries[0],entries[0]])),'Stage1InvalidBatch');expect(await bytes(tracked)).deep.eq(before);
    await reject(send(batch([entries[0],entries[1],{...entries[2],leaf:{...entries[2].leaf,amount:8}}])),'Stage1InvalidProof');expect(await bytes(tracked)).deep.eq(before);
    await send(createFreezeAccountInstruction(destination,mint,wallet.publicKey));const frozen=await bytes(tracked);
    await reject(send(batch(entries)),'frozen');expect(await bytes(tracked)).deep.eq(frozen);await send(createThawAccountInstruction(destination,mint,wallet.publicKey));
    const amount=(await getAccount(provider.connection,destination,'processed')).amount;const probe=await send(batch(entries),[],true);expect((await getAccount(provider.connection,destination,'processed')).amount-amount).eq(27n);
    for(const e of entries){await reject(send(claim(e.week,e.leaf)),'Stage1ClaimReplay');expect((await program.account.stage1ClaimSet.fetch(set(e.week))).claimedCount).eq(2);}
    evidence.batch={weeks:3,...probe};console.log(`    three-week batch: ${probe.computeUnits} CU, ${probe.transactionBytes} bytes`);
  });
  for(const [week,first] of [[6,0],[7,1]])it(`pays distinct indices for the same person within the publisher root, first index ${first}`,async()=>{
    const t=await publish(week,[people[0].publicKey,people[0].publicKey]);await send(claim(week,t.leaves[first]));const before=await bytes([set(week),asset(),earnings(),destination]);
    await send(claim(week,t.leaves[1-first]));expect((await program.account.stage1ClaimSet.fetch(set(week))).claimedCount).eq(2);
    await reject(send(claim(week,t.leaves[first])),'Stage1ClaimReplay');
  });
  it('handles prefunding, maximum allocation, capacity correction and publisher rotation before sealing',async()=>{
    const week=8,t=tree(week,people.map(p=>p.publicKey));await fund(week,2);await send(SystemProgram.transfer({fromPubkey:wallet.publicKey,toPubkey:set(week),lamports:await provider.connection.getMinimumBalanceForRentExemption(0)}));
    await send(prepare(week,65536),[publisher]);expect((await provider.connection.getAccountInfo(set(week),'processed'))!.data.length).eq(claimHeaderBytes(program)+8192);
    const before=await bytes([funding(week),cursor(),asset(),set(week)]);await reject(send(seal(week,{...t,count:1000}),[publisher]),'Stage1ClaimStorage');expect(await bytes([funding(week),cursor(),asset(),set(week)])).deep.eq(before);
    await send(program.methods.setStage1Publisher(replacement.publicKey).accounts({city:city(),programConfig:config(),admin:wallet.publicKey}));await reject(send(prepare(week,2),[publisher]),'Stage1Unauthorized');
    await send(prepare(week,2,replacement.publicKey),[replacement]);expect((await provider.connection.getAccountInfo(set(week),'processed'))!.data.length).eq(claimHeaderBytes(program)+claimTailBytes(2));
    await send(prepare(week,1000,replacement.publicKey),[replacement]);await send(prepare(week,2,replacement.publicKey),[replacement]);
    await send(program.methods.setStage1Publisher(publisher.publicKey).accounts({city:city(),programConfig:config(),admin:wallet.publicKey}));await send(seal(week,t),[publisher]);
    await reject(send(prepare(week,1000),[publisher]),'Stage1ClaimStorage');await send(claim(week,t.leaves[0]));
  });
  it('checks compact witnesses atomically and refunds only fully claimed sets to their original payer',async()=>{
    const week=0,t=tree(week,[...people.map(p=>p.publicKey),...Array.from({length:8},()=>Keypair.generate().publicKey)]);
    const close=(week:number,payer=publisher.publicKey)=>program.methods.closeStage1ClaimSet().accounts({claimSet:set(week),rentPayer:payer});
    await reject(send(close(0)),'Stage1ClaimStorage');
    const entries=[6,7].map(week=>({week,leaf:{...t.leaves[0],index:0}}));
    // Weeks 6/7 are already fully paid; metadata must be authenticated before replay/progress checks.
    const fields=leafArgs(t.leaves[0]),good=claimTerms(program,set(6));
    for(const terms of [{...good,cap:good.cap.addn(1)},{...good,frozenAt:good.frozenAt.addn(1)},{...good,auditHash:Array(32).fill(0)}]){
      const before=await bytes([set(6),asset(),earnings(),destination]);
      await reject(send(program.methods.claimStage1(fields.index,people[0].publicKey,fields.amount,fields.proof,terms).accounts({city:city(),asset:asset(),claimSet:set(6),registration:pda('s1v1_recipient',people[0].publicKey.toBuffer()),earnings:earnings(),destination,tokenProgram:TOKEN_PROGRAM_ID})),'Stage1InvalidProof');
      expect(await bytes([set(6),asset(),earnings(),destination])).deep.eq(before);
    }
    await reject(send(close(3,replacement.publicKey)),'ConstraintHasOne');
    await send(SystemProgram.transfer({fromPubkey:wallet.publicKey,toPubkey:set(3),lamports:1000}));
    const rent=(await provider.connection.getAccountInfo(set(3),'processed'))!.lamports;
    const balance=await provider.connection.getBalance(publisher.publicKey,'processed');
    await send(program.methods.setStage1Publisher(replacement.publicKey).accounts({city:city(),programConfig:config(),admin:wallet.publicKey}));
    const history=await bytes([cursor()]);
    await send(close(3));expect(await bytes([cursor()])).deep.eq(history);expect(await provider.connection.getAccountInfo(set(3),'processed')).eq(null);
    expect(await provider.connection.getBalance(publisher.publicKey,'processed')-balance).eq(rent);
    await reject(send(prepare(3,2,replacement.publicKey),[replacement]),'Stage1ClaimStorage');
    await send(program.methods.setStage1Publisher(publisher.publicKey).accounts({city:city(),programConfig:config(),admin:wallet.publicKey}));
    evidence.closure={returnedLamports:rent,originalPayer:true,namespaceRemainsClosed:true};
  });
  it('measures a successful populated bitmap claim from explicitly synthetic populated storage',async()=>{
    const week=9,key=people[0].publicKey.toBuffer(),keys=Array.from({length:256},(_,bit)=>{const value=Buffer.from(key);value[Math.floor(bit/8)]^=1<<(7-bit%8);return new PublicKey(value);});
    const t=await publish(week,[...keys,people[0].publicKey]);
    // Conservative compute fixture only: 256 prior payments/bitmap bits are
    // inserted into a LOCAL captured bank, not claimed as submitted payments.
    // The target claim itself is signature-verified, submitted, and conserved.
    const accounts=await saved(),info=accounts.get(set(week).toBase58())!,data=Buffer.from(info.data);
    const state=program.coder.accounts.decode('Stage1ClaimSet',data),paid=256*9;state.paid=bn(paid);state.claimedCount=256;
    (await program.coder.accounts.encode('Stage1ClaimSet',state)).copy(data);
    const start=claimHeaderBytes(program);
    data.fill(255,start,start+32);
    accounts.set(set(week).toBase58(),{...info,data});
    const aInfo=accounts.get(asset().toBase58())!,a=program.coder.accounts.decode('Stage1AssetConfig',aInfo.data);
    a.ledger.paid=a.ledger.paid.addn(paid);a.ledger.earnings=a.ledger.earnings.subn(paid);a.ledger.claimable=a.ledger.claimable.subn(paid);
    accounts.set(asset().toBase58(),{...aInfo,data:await program.coder.accounts.encode('Stage1AssetConfig',a)});
    for(const [address,delta] of [[earnings(),-paid],[destination,paid]] as const){const account=accounts.get(address.toBase58())!,bytes=Buffer.from(account.data);bytes.writeBigUInt64LE(bytes.readBigUInt64LE(64)+BigInt(delta),64);accounts.set(address.toBase58(),{...account,data:bytes});}
    await move(LAUNCH+10*W+86400+100,accounts);
    const balance=(await getAccount(provider.connection,destination,'processed')).amount,probe=await send(claim(week,t.leaves[256]),[],true);
    expect((await getAccount(provider.connection,destination,'processed')).amount-balance).eq(9n);
    const after=await program.account.stage1ClaimSet.fetch(set(week));expect(after.claimedCount).eq(257);expect(after.paid.toString()).eq(t.total);
    evidence.worstPath={fixture:'synthetic prior payment progress and index bitmap; final transfer committed',priorClaims:256,bitmapBytes:33,...probe};
    console.log(`    populated worst path: ${probe.computeUnits} CU, ${probe.transactionBytes} bytes (synthetic prior progress)`);
  });
  it('closes an empty published cash set without reopening its week',async()=>{
    const week=10;
    await send(program.methods.openStage1Week(bn(week)).accounts({city:city(),hillAccount:{hill},asset:asset(),funding:funding(week),payer:wallet.publicKey,systemProgram:SystemProgram.programId,cursor:cursor()}));
    await move(LAUNCH+11*W+86400+100);
    await send(program.methods.freezeStage1Snapshot([...hash('empty-cash')],bn(0)).accounts({city:city(),hill,asset:asset(),funding:funding(week),previous:null,publisher:publisher.publicKey,cursor:cursor()}),[publisher]);
    const context=JSON.stringify([program.programId.toBase58(),city().toBase58(),hill.toBase58(),week,mint.toBase58()]);
    const empty=createHash('sha256').update(Buffer.from('BR-stage1-v1:empty\0')).update(context).digest('hex');
    await send(prepare(week,0),[publisher]);await send(seal(week,{root:empty,total:0,count:0}),[publisher]);
    await send(program.methods.closeStage1ClaimSet().accounts({claimSet:set(week),rentPayer:publisher.publicKey}));
    expect(await provider.connection.getAccountInfo(set(week),'processed')).eq(null);
    await reject(send(prepare(week,0),[publisher]),'Stage1ClaimStorage');
  });

  it('sponsors a new rider first payout and all three needed token accounts in the same transaction',async()=>{
    const week=11,t=tree(week,[newRider.publicKey],newRecipient);
    const additionalMints=[Keypair.generate(),Keypair.generate()];
    for(const m of additionalMints)await send([SystemProgram.createAccount({fromPubkey:wallet.publicKey,newAccountPubkey:m.publicKey,space:MINT_SIZE,lamports:await provider.connection.getMinimumBalanceForRentExemption(MINT_SIZE),programId:TOKEN_PROGRAM_ID}),createInitializeMint2Instruction(m.publicKey,9,wallet.publicKey,null)],[m]);
    await fund(week,1);await allocate(week,1);await send(seal(week,t),[publisher]);
    // Keep this sponsor below Number.MAX_SAFE_INTEGER: the validator's genesis
    // wallet is too large for exact lamport subtraction through web3.js numbers.
    const sponsor=Keypair.generate();
    await send(SystemProgram.transfer({fromPubkey:wallet.publicKey,toPubkey:sponsor.publicKey,lamports:1_000_000_000}));
    const payoutMints=[mint,...additionalMints.map(m=>m.publicKey)],atas=payoutMints.map(m=>getAssociatedTokenAddressSync(m,newRecipient));
    for(const ata of atas)expect(await provider.connection.getAccountInfo(ata,'processed')).eq(null);
    const setup=payoutMints.map((m,i)=>createAssociatedTokenAccountIdempotentInstruction(sponsor.publicKey,atas[i],newRecipient,m));
    const leaf=leafArgs(t.leaves[0]),ix=program.methods.claimStage1(leaf.index,newRider.publicKey,leaf.amount,leaf.proof,claimTerms(program,set(week))).accounts({city:city(),asset:asset(),claimSet:set(week),registration:pda('s1v1_recipient',newRider.publicKey.toBuffer()),earnings:earnings(),destination:atas[0],tokenProgram:TOKEN_PROGRAM_ID});
    const balance=await provider.connection.getBalance(sponsor.publicKey,'processed');
    const probe=await send([...setup,ix],[],true,sponsor);
    const rent=(await Promise.all(atas.map(a=>provider.connection.getAccountInfo(a,'processed')))).reduce((n,a)=>n+a!.lamports,0);
    expect(balance-await provider.connection.getBalance(sponsor.publicKey,'processed')).eq(rent+probe.feeLamports);
    expect((await getAccount(provider.connection,atas[0],'processed')).amount).eq(9n);
    expect(await provider.connection.getBalance(newRider.publicKey,'processed')).eq(0);
    const count=(await provider.connection.getProgramAccounts(TOKEN_PROGRAM_ID,{commitment:'processed'})).length;
    await send(setup,[],false,sponsor);expect((await provider.connection.getProgramAccounts(TOKEN_PROGRAM_ID,{commitment:'processed'})).length).eq(count);
    evidence.firstPayout={tokenAccounts:3,tokenAccountRentLamports:rent,registrationRentLamports:evidence.registration.rentLamports,payer:'transaction sponsor; rider remains at zero SOL',...probe};
  });

  it('closes weekly funding only after payment and refuses every cash namespace recreation path',async()=>{
    const closeBook=(week:number,payer=replacement.publicKey)=>program.methods.closeStage1WeekFunding().accounts({
      funding:funding(week),cursor:cursor(),asset:asset(),earnings:earnings(),claimSet:set(week),rentPayer:payer});
    await reject(send(closeBook(0,wallet.publicKey)),'Stage1ClaimStorage');
    const week=12;
    const open=()=>program.methods.openStage1Week(bn(week)).accounts({city:city(),hillAccount:{hill},asset:asset(),funding:funding(week),payer:replacement.publicKey,systemProgram:SystemProgram.programId,cursor:cursor()});
    await send(open(),[replacement]);
    await reject(send(prepare(week,0),[publisher]),'Stage1ClaimStorage');
    expect(await provider.connection.getAccountInfo(set(week),'processed')).eq(null);
    const t=await publish(week,people.map(p=>p.publicKey));
    await send(claim(week,t.leaves[0]),[],false,people[0]);
    await reject(send(closeBook(week)),'Stage1ClaimStorage');
    await reject(send(program.methods.closeStage1ClaimSet().accounts({claimSet:set(week),rentPayer:publisher.publicKey})),'Stage1ClaimStorage');
    await send(claim(week,t.leaves[1]),[],false,people[1]);
    await reject(send(closeBook(week)),'Stage1ClaimStorage');
    await send(program.methods.closeStage1ClaimSet().accounts({claimSet:set(week),rentPayer:publisher.publicKey}));
    await reject(send(closeBook(week,publisher.publicKey)),'ConstraintHasOne');
    await send(SystemProgram.transfer({fromPubkey:wallet.publicKey,toPubkey:funding(week),lamports:1000}));
    const info=(await provider.connection.getAccountInfo(funding(week),'processed'))!,balance=await provider.connection.getBalance(replacement.publicKey,'processed');
    const accounting=await bytes([asset(),earnings(),cursor()]);
    await send(closeBook(week));
    expect(await provider.connection.getBalance(replacement.publicKey,'processed')-balance).eq(info.lamports);
    expect(await bytes([asset(),earnings(),cursor()])).deep.eq(accounting);
    expect(await provider.connection.getAccountInfo(funding(week),'processed')).eq(null);
    const init=()=>program.methods.initStage1Settlement().accounts({city:city(),hillAccount:{hill},asset:asset(),cursor:cursor(),payer:wallet.publicKey,systemProgram:SystemProgram.programId});
    await send(init());
    for(const attempt of [()=>send(open(),[replacement]),()=>send(prepare(week,2),[publisher]),()=>send(seal(week,t),[publisher]),
      ()=>send(program.methods.freezeStage1Snapshot([...hash('recreate')],bn(9)).accounts({city:city(),hill,asset:asset(),funding:funding(week),previous:null,publisher:publisher.publicKey,cursor:cursor()}),[publisher])]){
      try{await attempt();throw Error('closed namespace recreated');}catch(e:any){expect(e.message).not.eq('closed namespace recreated');}
      expect(await provider.connection.getAccountInfo(funding(week),'processed')).eq(null);
      expect(await provider.connection.getAccountInfo(set(week),'processed')).eq(null);
      expect(await bytes([asset(),earnings(),cursor()])).deep.eq(accounting);
    }
    evidence.weeklyClosure={returnedLamports:info.lamports,originalPayer:true,allCashInitPathsRefused:true,accountingUnchanged:true};
  });

  it('closes an opened skipped week without creating claims or resetting its cursor',async()=>{
    const week=13;
    await send(program.methods.openStage1Week(bn(week)).accounts({city:city(),hillAccount:{hill},asset:asset(),funding:funding(week),payer:wallet.publicKey,systemProgram:SystemProgram.programId,cursor:cursor()}));
    await reject(send(prepare(week,0),[publisher]),'Stage1ClaimStorage');
    await move(LAUNCH+14*W+86400+100);
    await send(program.methods.skipStage1EmptyWeeks(bn(week)).accounts({city:city(),hill,asset:asset(),cursor:cursor(),earnings:earnings(),publisher:publisher.publicKey}).remainingAccounts([{pubkey:funding(week),isSigner:false,isWritable:false}]),[publisher]);
    const before=await bytes([asset(),earnings(),cursor()]);
    await send(program.methods.closeStage1WeekFunding().accounts({funding:funding(week),cursor:cursor(),asset:asset(),earnings:earnings(),claimSet:set(week),rentPayer:wallet.publicKey}));
    expect(await bytes([asset(),earnings(),cursor()])).deep.eq(before);
    expect(await provider.connection.getAccountInfo(funding(week),'processed')).eq(null);
    expect(await provider.connection.getAccountInfo(set(week),'processed')).eq(null);
  });
});
