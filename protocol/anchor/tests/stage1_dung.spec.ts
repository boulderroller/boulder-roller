import * as anchor from '@coral-xyz/anchor';
import BN from 'bn.js';
import { expect } from 'chai';
import { createHash } from 'crypto';
import { execFileSync } from 'child_process';
import { fileURLToPath } from 'url';
import { resolve } from 'path';
import { readFileSync } from 'fs';
import { ComputeBudgetProgram, Keypair, PublicKey, SYSVAR_CLOCK_PUBKEY, SYSVAR_RENT_PUBKEY,
  SystemProgram, TransactionInstruction, TransactionMessage, VersionedTransaction } from '@solana/web3.js';
import { createInitializeMint2Instruction, createMintToInstruction, createAssociatedTokenAccountIdempotentInstruction,
  createFreezeAccountInstruction, createThawAccountInstruction, getAssociatedTokenAddressSync,
  MINT_SIZE, MintLayout, getAccount, getMint, TOKEN_PROGRAM_ID } from '@solana/spl-token';
import { withClaimStorage, claimHeaderBytes } from './helpers/stage1_claim_storage.js';
import { capture, replay, pause, Capture } from './helpers/stage1_replay.js';

const localAdapter=process.env.STAGE1_LOCALNET==='1';
const enabled=localAdapter||process.env.STAGE1_DEPLOYABLE==='1';
const jitoPool=JSON.parse(readFileSync(new URL('./fixtures/stage1_providers/jito-pool.json',import.meta.url),'utf8'));
const jitoMint=JSON.parse(readFileSync(new URL('./fixtures/stage1_providers/jito-mint.json',import.meta.url),'utf8'));
const providerPair=()=>localAdapter?[]:[new PublicKey(jitoPool.pubkey),lst].map(pubkey=>({pubkey,isSigner:false,isWritable:false}));
const ROOT=resolve(fileURLToPath(new URL('../../..',import.meta.url)));
const PYTHON=process.env.STAGE1_ORACLE_PYTHON??'python3';
let provider=anchor.AnchorProvider.env();anchor.setProvider(provider);
let program:any=anchor.workspace.BoulderRollers;
const originalProvider=provider,originalProgram=program,wallet=provider.wallet as anchor.Wallet;
const publisher=Keypair.generate(),guardian=Keypair.generate(),people=Array.from({length:12},()=>Keypair.generate()),recipients=Array.from({length:12},()=>Keypair.generate());
recipients[1]=recipients[0]; // Two different people may share one destination.
const W=604800,LAUNCH=1791201600,SOL=1_000_000_000n,CAP=20_000_000_000,WAIT=172800;
const bn=(n:any)=>new BN(String(n)),u64=(n:number)=>bn(n).toArrayLike(Buffer,'le',8);
const pda=(s:string,...p:Buffer[])=>PublicKey.findProgramAddressSync([Buffer.from(s),...p],program.programId)[0];
const city=()=>pda('s1v1_city'),config=()=>pda('program_config'),state=()=>pda('s1v1_dung_state'),legacy=()=>pda('dung_mint_state');
const hash=(v:string|Buffer)=>createHash('sha256').update(v).digest();
let active:Awaited<ReturnType<typeof replay>>|undefined,serial=950000,txSerial=0,mint:PublicKey,lst:PublicKey,legacyBytes:string,cashBytes:string;
type Case={name:string,hill:PublicKey,oracle:any};const cases:Case[]=[];let adverse:Case,duplicate:Case,timed:Case,policy:Case,paused:Case,batched:Case,unsetSnapshot:Capture,exact=false;
const names=['partial-week','five','field-four','zero-tss','missing-legend','no-board','zero-weight','loss','rounding-1','rounding-3','late-prebond','lock-13','lock-expired','founder-26','founder-27','ceiling-minus-one','ceiling','unregistered-rider','unregistered-backer','unregistered-all'];
const dung=(c:Case)=>pda('s1v1_dung',c.hill.toBuffer(),u64(c.oracle.week));
const publicationEvents=new Map<string,{data:any,raw:Buffer}>();
const set=(c:Case,role:number)=>pda('s1v1_dung_claims',dung(c).toBuffer(),Buffer.from([role]));
async function send(build:any,signers:Keypair[]=[],probe?:any){
  const ixs:TransactionInstruction[]=await Promise.all((Array.isArray(build)?build:[build]).map(b=>b instanceof TransactionInstruction?b:b.instruction()));
  const histories=new Map<string,Buffer>();
  for(const ix of ixs){
    if(!ix.programId.equals(program.programId))continue;
    const name=program.coder.instruction.decode(ix.data)?.name;
    if(!['publishStage1Dung','publishStage1DungClaimSet'].includes(name??''))continue;
    const flatten=(entries:any[]):string[]=>entries.flatMap(e=>e.accounts?flatten(e.accounts):[e.name]);
    const names=flatten(program.idl.instructions.find((i:any)=>i.name===name).accounts),key=ix.keys[names.indexOf('hill')].pubkey;
    histories.set(key.toBase58(),Buffer.from((await program.account.stage1HillBond.fetch(key)).dungPublicationCommitment));
  }
  const block=await provider.connection.getLatestBlockhash(exact?'finalized':'processed');
  const tx=new VersionedTransaction(new TransactionMessage({payerKey:wallet.publicKey,recentBlockhash:block.blockhash,
    instructions:[ComputeBudgetProgram.setComputeUnitLimit({units:1400000}),ComputeBudgetProgram.setComputeUnitPrice({microLamports:++txSerial}),...(await Promise.all(ixs.map(ix=>withClaimStorage(program,ix)))).flat()]}).compileToLegacyMessage());
  tx.sign([wallet.payer,...signers]);
  if(probe){const result=await provider.connection.simulateTransaction(tx,{commitment:'processed',sigVerify:true});
    expect(result.value.err,result.value.logs?.join('\n')).eq(null);probe.computeUnits=result.value.unitsConsumed;probe.transactionBytes=tx.serialize().length;expect(probe.transactionBytes).at.most(1232);}
  if(exact){
    const addresses=[...new Set(ixs.flatMap(ix=>ix.keys.filter(k=>k.isWritable).map(k=>k.pubkey.toBase58())))];
    const result=await provider.connection.simulateTransaction(tx,{commitment:'finalized',sigVerify:true,accounts:{encoding:'base64',addresses}});
    if(result.value.err)throw Error(`Exact-clock local simulation: ${JSON.stringify(result.value.err)}\n${result.value.logs?.join('\n')}`);
    return new Map(addresses.map((key,i)=>[key,Buffer.from(result.value.accounts![i]!.data[0],'base64')]));
  }
  const sig=await provider.connection.sendRawTransaction(tx.serialize(),{preflightCommitment:'processed'});
  const confirmed=await provider.connection.confirmTransaction({...block,signature:sig},'processed');
  expect(confirmed.value.err,sig).eq(null);
  if(ixs.some(ix=>ix.programId.equals(program.programId)&&['publishStage1Dung','publishStage1DungClaimSet'].includes(program.coder.instruction.decode(ix.data)?.name??''))){
    await provider.connection.confirmTransaction({...block,signature:sig},'confirmed');
    let transaction:any;
    for(let n=0;n<30&&!transaction;n++){transaction=await provider.connection.getTransaction(sig,{commitment:'confirmed',maxSupportedTransactionVersion:0});if(!transaction)await pause(100);}
    expect(transaction,'confirmed publication transaction').not.eq(null);
    for(const line of transaction.meta.logMessages??[]){
      if(!line.startsWith('Program data: '))continue;
      const encoded=line.slice(14),event=program.coder.events.decode(encoded);
      const raw=Buffer.from(encoded,'base64').subarray(8);
      if(event?.name==='Stage1DungPublished'){
        publicationEvents.set(event.data.dung.toBase58(),{data:event.data,raw});
        const hill=event.data.hill.toBase58(),snapshot=hash(Buffer.concat([Buffer.from('BR-stage1-v2:dung-publication\0'),raw]));
        histories.set(hill,hash(Buffer.concat([Buffer.from('BR-stage1-v2:dung-history\0'),histories.get(hill)!,snapshot])));
      }else if(event?.name==='Stage1DungRolePublished'){
        const hill=(await program.account.stage1DungMint.fetch(event.data.dung)).hill.toBase58();
        histories.set(hill,hash(Buffer.concat([Buffer.from('BR-stage1-v2:dung-role-history\0'),histories.get(hill)!,raw])));
      }
    }
    for(const [hill,commitment] of histories)expect(Buffer.from((await program.account.stage1HillBond.fetch(new PublicKey(hill))).dungPublicationCommitment).equals(commitment)).eq(true);
  }
  return sig;
}
async function reject(action:Promise<unknown>,text:string){try{await action;}catch(e:any){expect(`${e.message}\n${e.logs?.join('\n')}`).include(text);return;}throw Error(`Expected ${text}`);}
const bytes=async(keys:PublicKey[])=>Promise.all(keys.map(async k=>(await provider.connection.getAccountInfo(k,'processed'))?.data.toString('base64')??null));
async function saved(){return capture(provider.connection,program.programId,[wallet.publicKey,publisher.publicKey,guardian.publicKey,...people.map(p=>p.publicKey),...providerPair().map(a=>a.pubkey)]);}
async function move(at:number,from?:Capture,frozen=false){const accounts=from??await saved();await active?.stop();active=await replay(accounts,at,frozen,localAdapter?undefined:1057);exact=frozen;
  provider=new anchor.AnchorProvider(active.connection,wallet,{commitment:'processed',preflightCommitment:'processed'});
  program=new anchor.Program(originalProgram.idl,originalProgram.programId,provider);
  if(frozen)expect(await now()).eq(at);}
const now=async()=>Number((await provider.connection.getAccountInfo(SYSVAR_CLOCK_PUBKEY,exact?'finalized':'processed'))!.data.readBigInt64LE(32));
const configure=(ceiling:number,start:number|null,admin=wallet.publicKey)=>program.methods.configureStage1Dung(bn(ceiling),start===null?null:bn(start))
  .accounts({city:city(),programConfig:config(),admin});
async function openClaims(c:Case){const sets=await Promise.all([0,1].map(role=>program.account.stage1DungClaimSet.fetch(set(c,role))));
  await move(Math.max(await now(),...sets.map(s=>s.publishedAt.toNumber()+WAIT)));}
async function makeMint(authority:PublicKey){const m=Keypair.generate();await send([
  SystemProgram.createAccount({fromPubkey:wallet.publicKey,newAccountPubkey:m.publicKey,space:MINT_SIZE,lamports:await provider.connection.getMinimumBalanceForRentExemption(MINT_SIZE),programId:TOKEN_PROGRAM_ID}),
  createInitializeMint2Instruction(m.publicKey,9,authority,wallet.publicKey)],[m]);return m.publicKey;}
const input=(o:any)=>({sourceSnapshot:[...Buffer.from(o.source_snapshot,'hex')],fieldCount:o.field_count,postbondTssMicros:bn(o.postbond_tss_micros),
  topCount:o.top_count,ascentCount:o.ascent_count,earnedLegend:o.earned_legend,opening:{basis:o.opening.basis.map(bn),backing:o.opening.backing.map(bn)},payableRoleTotals:o.payable_role_totals.map(bn)});
const roots=(o:any)=>o.roots.map((r:any)=>({root:[...Buffer.from(r.root,'hex')],total:bn(r.total),leafCount:r.leaf_count}));
const publish=(c:Case,data=input(c.oracle.input),rs=roots(c.oracle),pub=publisher.publicKey)=>[
  program.methods.publishStage1Dung(bn(c.oracle.week),data)
    .accounts({city:city(),hillAccount:{hill:c.hill},programConfig:config(),mint,dung:dung(c),state:state(),publisher:pub,systemProgram:SystemProgram.programId}),
  ...rs.map((root:any,role:number)=>program.methods.publishStage1DungClaimSet(role,root)
    .accounts({city:city(),hill:c.hill,dung:dung(c),claimSet:set(c,role),publisher:pub,systemProgram:SystemProgram.programId}))];
async function claim(c:Case,role:number,leaf:any,overrides:any={}){
  const person=new PublicKey(leaf.person),recipient=new PublicKey(leaf.recipient),destination=getAssociatedTokenAddressSync(mint,recipient);
  await send(createAssociatedTokenAccountIdempotentInstruction(wallet.publicKey,destination,recipient,mint));
  return program.methods.claimStage1Dung(leaf.index,person,bn(leaf.amount),leaf.proof.map((p:any)=>({hash:[...Buffer.from(p.hash,'hex')],sum:bn(p.sum)})))
    .accounts({city:city(),dung:dung(c),claimSet:set(c,role),state:state(),registration:pda('s1v1_recipient',person.toBuffer()),
      programConfig:config(),mint,dungMintAuth:pda('dung_mint_auth'),destination,tokenProgram:TOKEN_PROGRAM_ID,...overrides});
}
let closedAllocated=0n,closedPaid=0n;
async function audit(){
  expect((await bytes([legacy()]))[0]).eq(legacyBytes);
  expect((await bytes([pda('s1v1_asset',lst.toBuffer())]))[0]).eq(cashBytes);
  const all=await program.account.stage1DungMint.all();let allocated=closedAllocated,paid=closedPaid;
  for(const {publicKey,account:d} of all){
    const event=publicationEvents.get(publicKey.toBase58());expect(event,'retained publication event').not.eq(undefined);
    const a=event!.data.allocation;
    expect(d.unminted.toString()).eq(a.unminted.toString());
    expect(BigInt(a.riders.toString())+BigInt(a.backers.toString())+BigInt(a.unminted.toString())).eq(BigInt(a.potential.toString()));
    expect(d.roleTotals.map((n:any)=>n.toString())).deep.eq([a.riders.toString(),a.backers.toString()]);
    expect(Buffer.from(d.snapshot).equals(hash(Buffer.concat([Buffer.from('BR-stage1-v2:dung-publication\0'),event!.raw])))).eq(true);
    allocated+=BigInt(d.roleTotals[0].toString())+BigInt(d.roleTotals[1].toString());paid+=BigInt(d.minted[0].toString())+BigInt(d.minted[1].toString());
  }
  const s=await program.account.stage1DungState.fetchNullable(state());
  if(s){expect(s.allocatedLifetime.toString()).eq(String(allocated));expect(s.mintedLifetime.toString()).eq(String(paid));}
  expect((await getMint(provider.connection,mint,'processed')).supply).eq(paid);
  expect(paid<=allocated).eq(true);
}
async function createCase(name:string){
  const id=hash(`dung-hill-${name}`).subarray(0,16),profile=hash(`dung-profile-${name}`),commitment=Buffer.alloc(64);
  commitment[0]=1;id.copy(commitment,1);commitment.writeUInt16BE(1,17);profile.copy(commitment,32);
  const digest=hash(commitment),climb=pda('climb',digest),hill=pda('s1v1_hill',id);
  await send(program.methods.registerRatifiedClimb({canonId:[...id],canonVersion:1,canonicalProfileHash:[...profile],commitmentHash:[...digest],
    recordContinuityPolicy:{newRecordBoard:{}},name:`Local DUNG ${name}`,vertM:1000,distanceM:2000,avgGradientPct:500})
    .accounts({climb,climbVersionIndex:pda('climb_version',id,Buffer.from([0,1])),predecessorClimb:null,programConfig:config(),admin:wallet.publicKey,systemProgram:SystemProgram.programId}));
  await send(program.methods.initHillBond().accounts({city:city(),climb,hill,programConfig:config(),admin:wallet.publicKey,systemProgram:SystemProgram.programId}));
  const clock=Number((await provider.connection.getAccountInfo(SYSVAR_CLOCK_PUBKEY,'processed'))!.data.readBigInt64LE(32));
  if(localAdapter)await send(program.methods.setTestLstRate(bn(1),bn(1),bn(clock)).accounts({city:city(),asset:pda('s1v1_asset',lst.toBuffer()),programConfig:config(),admin:wallet.publicKey}));
  else await send(program.methods.refreshStage1Rate().accounts({city:city(),asset:pda('s1v1_asset',lst.toBuffer()),provider:new PublicKey(jitoPool.pubkey),mint:lst}));
  for(const [owner,units,lock,bond] of [[people[0],10n*SOL,0,true],[people[1],5n*SOL,26,false],[people[0],5n*SOL,13,false]] as const){
    const n=++serial,lot=pda('s1v1_lot',owner.publicKey.toBuffer(),u64(n));
    await send(program.methods[bond?'bond':'pledge'](bn(n),bn(units),lock).accounts({city:city(),hillAccount:{hill},climb,asset:pda('s1v1_asset',lst.toBuffer()),mint:lst,lot,
      custody:pda('s1v1_custody',lot.toBuffer()),ownerReserve:pda('s1v1_owner',lot.toBuffer()),source:getAssociatedTokenAddressSync(lst,owner.publicKey),owner:owner.publicKey,
      tokenProgram:TOKEN_PROGRAM_ID,systemProgram:SystemProgram.programId,rent:SYSVAR_RENT_PUBKEY})
      .remainingAccounts(!localAdapter&&bond?[{pubkey:pda('s1v1_asset',lst.toBuffer()),isSigner:false,isWritable:true},...providerPair()]:providerPair()),[owner]);
  }
  const h=await program.account.stage1HillBond.fetch(hill);expect(h.dungDepositedBasis.toString()).eq('20000000000');expect(h.dungFoundingBasis.toString()).eq('10000000000');
  const oracle=JSON.parse(execFileSync(PYTHON,['-m','tools.stage1_reference.dung_vectors','--stdin'],{cwd:ROOT,encoding:'utf8',input:JSON.stringify({case:names.includes(name)?name:'five',
    deployment:program.programId.toBase58(),city:city().toBase58(),hill:hill.toBase58(),mint:mint.toBase58(),people:people.map(p=>p.publicKey.toBase58()),recipients:recipients.map(p=>p.publicKey.toBase58())})}));
  return {name,hill,oracle};
}
if(enabled)describe('bonded-hill DUNG on a LOCAL validator',()=>{
  before(async()=>{
    expect(['127.0.0.1','localhost']).include(new URL(provider.connection.rpcEndpoint).hostname);
    const clean=await capture(provider.connection,program.programId,[wallet.publicKey]);
    for(const [key,a] of clean)if(a.owner.equals(program.programId)||a.owner.equals(TOKEN_PROGRAM_ID))clean.delete(key);
    await move(LAUNCH+100,clean);
    const executable=(await provider.connection.getAccountInfo(program.programId))!;
    await send(program.methods.initializeProgramConfig(wallet.publicKey).accounts({programConfig:config(),program:program.programId,
      programData:new PublicKey(executable.data.subarray(4,36)),admin:wallet.publicKey,systemProgram:SystemProgram.programId}));
    mint=await makeMint(pda('dung_mint_auth'));lst=localAdapter?await makeMint(wallet.publicKey):new PublicKey(jitoMint.pubkey);
    await send(program.methods.configureMints(Keypair.generate().publicKey,mint).accounts({programConfig:config(),admin:wallet.publicKey}));
    await send(program.methods.initializeDungMintState().accounts({dungMintState:legacy(),programConfig:config(),authority:wallet.publicKey,systemProgram:SystemProgram.programId}));
    legacyBytes=(await bytes([legacy()]))[0]!;
    await send(program.methods.initCityConfig(bn(LAUNCH)).accounts({city:city(),programConfig:config(),admin:wallet.publicKey,systemProgram:SystemProgram.programId}));
    await send(program.methods.setStage1Publisher(publisher.publicKey).accounts({city:city(),programConfig:config(),admin:wallet.publicKey}));
    await send(program.methods.setStage1Guardian(guardian.publicKey).accounts({city:city(),programConfig:config(),admin:wallet.publicKey}));
    for(const p of [publisher,guardian,...people])await send(SystemProgram.transfer({fromPubkey:wallet.publicKey,toPubkey:p.publicKey,lamports:3_000_000_000}));
    for(let i=0;i<people.length;i++)await send(program.methods.registerStage1Recipient(recipients[i].publicKey).accounts({registration:pda('s1v1_recipient',people[i].publicKey.toBuffer()),person:people[i].publicKey,payer:wallet.publicKey,systemProgram:SystemProgram.programId}),[people[i]]);
    if(!localAdapter){
      // Explicit LOCAL external-provider fixture: retained Jito layout with a
      // synthetic 1:1 rate and token inventory. Stage1 state uses instructions.
      const accounts=await capture(provider.connection,program.programId,[wallet.publicKey,publisher.publicKey,guardian.publicKey,...people.map(p=>p.publicKey)]);
      for(const fixture of [jitoPool,jitoMint]){
        const a=fixture.account,data=Buffer.from(a.data[0],'base64');
        if(fixture===jitoPool){data.writeBigUInt64LE(1000n*SOL,258);data.writeBigUInt64LE(1000n*SOL,266);data.writeBigUInt64LE(1057n,274);}
        else data.writeBigUInt64LE(1000n*SOL,36);
        accounts.set(fixture.pubkey,{...a,owner:new PublicKey(a.owner),data});
      }
      for(const p of people.slice(0,2)){
        const data=Buffer.alloc(165);lst.toBuffer().copy(data,0);p.publicKey.toBuffer().copy(data,32);data.writeBigUInt64LE(500n*SOL,64);data[108]=1;
        accounts.set(getAssociatedTokenAddressSync(lst,p.publicKey).toBase58(),{data,owner:TOKEN_PROGRAM_ID,lamports:await provider.connection.getMinimumBalanceForRentExemption(165),executable:false,rentEpoch:0});
      }
      await move(LAUNCH+100,accounts);
    }
    const configureAsset=(enabled:boolean)=>program.methods.configureAsset(enabled).accounts({city:city(),asset:pda('s1v1_asset',lst.toBuffer()),mint:lst,earnings:pda('s1v1_earnings',lst.toBuffer()),programConfig:config(),admin:wallet.publicKey,tokenProgram:TOKEN_PROGRAM_ID,systemProgram:SystemProgram.programId,rent:SYSVAR_RENT_PUBKEY}).remainingAccounts(providerPair());
    if(!localAdapter){await send(configureAsset(false));await send(program.methods.refreshStage1Rate().accounts({city:city(),asset:pda('s1v1_asset',lst.toBuffer()),provider:new PublicKey(jitoPool.pubkey),mint:lst}));}
    await send(configureAsset(true));
    if(localAdapter)for(const p of people.slice(0,2)){const source=getAssociatedTokenAddressSync(lst,p.publicKey);await send([createAssociatedTokenAccountIdempotentInstruction(wallet.publicKey,source,p.publicKey,lst),createMintToInstruction(lst,source,wallet.publicKey,500n*SOL)]);}
    for(const name of names)cases.push(await createCase(name));adverse=await createCase('adversarial');duplicate=await createCase('duplicate');timed=await createCase('timed');policy=await createCase('policy');paused=await createCase('paused');batched=await createCase('batch');
    cashBytes=(await bytes([pda('s1v1_asset',lst.toBuffer())]))[0]!;
    unsetSnapshot=await saved();
    await send(configure(CAP,1));
    await move(LAUNCH+W+86400+100);
  });
  after(async()=>{await active?.stop();provider=originalProvider;program=originalProgram;});
  it('defaults to disabled; only admin can enable a prospective cutover, with no prestart issuance or empty-week fiction',async()=>{
    const resume=await saved(),at=await now();await move(LAUNCH+2*W+86400+100,unsetSnapshot);
    const cfg=await program.account.stage1CityConfig.fetch(city());expect(cfg.dungStartWeekPlusOne.toString()).eq('0');expect(cfg.dungTssCeilingMicros.toString()).eq('0');
    const c=cases[1],before=await bytes([city(),c.hill,state(),dung(c),mint]);
    await reject(send(publish(c),[publisher]),'Stage1NotLaunched');
    await reject(send(program.methods.skipStage1DungWeeks(bn(1),[...hash('disabled')],0,bn(0)).accounts({city:city(),hill:c.hill,publisher:publisher.publicKey}),[publisher]),'Stage1NotLaunched');
    await reject(send(configure(CAP,1)),'Stage1InvalidCalendar');
    await reject(send(configure(CAP,3,publisher.publicKey),[publisher]),'Stage1Unauthorized');
    expect(await bytes([city(),c.hill,state(),dung(c),mint])).deep.eq(before);
    await send(configure(CAP,3));await reject(send(publish(c),[publisher]),'Stage1WeekNotFinalizable');
    await move(LAUNCH+4*W+86400+100);
    const cutover={...c,oracle:{...c.oracle,week:3}};
    await send(publish(cutover)[0],[publisher]);expect((await program.account.stage1HillBond.fetch(c.hill)).dungNextWeek.toString()).eq('4');
    await send(program.methods.skipStage1DungWeeks(bn(3),[...hash('cutover-empty-week-3')],0,bn(0)).accounts({city:city(),hill:adverse.hill,publisher:publisher.publicKey}),[publisher]);
    expect((await program.account.stage1HillBond.fetch(adverse.hill)).dungNextWeek.toString()).eq('4');
    await reject(send(publish(c),[publisher]),'Stage1WeekNotFinalizable');
    await send(configure(CAP,null));await reject(send(configure(CAP,3)),'Stage1InvalidCalendar');
    await move(at,resume);
  });
  it('refuses partial bonding week and premature settlement without mint records',async()=>{
    await reject(send(publish(cases[0]),[publisher]),'Stage1NotBonded');
    await reject(send(publish(cases[1]),[publisher]),'Stage1WeekNotFinalizable');
    expect(await provider.connection.getAccountInfo(dung(cases[0]))).eq(null);await audit();
    await move(LAUNCH+2*W+86400+100);
  });
  it('guardian holds mature DUNG claims until settlement resumes',async()=>{
    const c=paused,roles={city:city(),programConfig:config(),admin:guardian.publicKey};
    const pauseIx=()=>program.methods.pauseStage1Settlement().accounts({city:city(),guardian:guardian.publicKey});
    const resumeIx=()=>program.methods.resumeStage1Settlement().accounts(roles);
    await send(pauseIx(),[guardian]);
    const before=await bytes([c.hill,dung(c),set(c,0),state(),mint]);
    await reject(send(publish(c)[0],[publisher]),'Stage1SettlementPaused');
    await reject(send(program.methods.skipStage1DungWeeks(bn(1),[...hash('paused-empty')],0,bn(0))
      .accounts({city:city(),hill:c.hill,publisher:publisher.publicKey}),[publisher]),'Stage1SettlementPaused');
    expect(await bytes([c.hill,dung(c),set(c,0),state(),mint])).deep.eq(before);
    await send(resumeIx(),[guardian]);await send(publish(c)[0],[publisher]);
    await send(pauseIx(),[guardian]);
    await reject(send(publish(c)[1],[publisher]),'Stage1SettlementPaused');
    expect(await provider.connection.getAccountInfo(set(c,0))).eq(null);
    await send(resumeIx(),[guardian]);await send(publish(c).slice(1),[publisher]);
    const snapshot=await saved(),at=await now();await openClaims(c);
    await send(pauseIx(),[guardian]);
    await send(program.methods.pauseStage1Intake().accounts({city:city(),guardian:guardian.publicKey}),[guardian]);
    const leaf=c.oracle.roots[0].leaves[0];
    const held=await bytes([dung(c),set(c,0),state(),mint]);
    await reject(send(await claim(c,0,leaf)),'Stage1SettlementPaused');
    expect(await bytes([dung(c),set(c,0),state(),mint])).deep.eq(held);
    await send(resumeIx(),[guardian]);
    await send(await claim(c,0,leaf));
    const dest=getAssociatedTokenAddressSync(mint,new PublicKey(leaf.recipient));
    expect((await getAccount(provider.connection,dest,'processed')).amount).eq(BigInt(leaf.amount));await audit();
    // Continue the independent vector cases from their unmodified captured clock/state.
    await move(at,snapshot);
  });
  it('bounds immutable input, roles, weights, and authorized publication',async()=>{
    const c=adverse,before=await bytes([dung(c),set(c,0),set(c,1),state(),legacy()]);
    const skip=program.methods.skipStage1DungWeeks(bn(1),[...hash('nonempty')],5,bn(1)).accounts({city:city(),hill:c.hill,publisher:publisher.publicKey});
    await reject(send(skip,[publisher]),'Stage1InvalidFunding');
    for(const through of [2,17])await reject(send(program.methods.skipStage1DungWeeks(bn(through),[...hash('empty')],0,bn(0))
      .accounts({city:city(),hill:c.hill,publisher:publisher.publicKey}),[publisher]),'Stage1WeekNotFinalizable');
    const zero=program.methods.skipStage1DungWeeks(bn(1),Array(32).fill(0),0,bn(0)).accounts({city:city(),hill:c.hill,publisher:publisher.publicKey});
    await reject(send(zero,[publisher]),'Stage1InvalidFunding');
    const reclassified=input(c.oracle.input);reclassified.opening.basis=[bn(20_000_000_000n),...Array(7).fill(bn(0))];reclassified.opening.backing=reclassified.opening.basis;
    await reject(send(publish(c,reclassified),[publisher]),'Stage1InvalidFunding');
    await reject(send(publish(c,undefined,undefined,wallet.publicKey)),'Stage1Unauthorized');
    for(const tss of [bn(CAP+1),bn('18446744073709551615')])await reject(send(publish(c,{...input(c.oracle.input),postbondTssMicros:tss}),[publisher]),'Stage1InvalidFunding');
    await reject(send(publish(c,{...input(c.oracle.input),sourceSnapshot:Array(32).fill(0)}),[publisher]),'Stage1SnapshotFrozen');
    const bad=input(c.oracle.input);bad.opening.backing[6]=bn(10_000_000_001n);
    await reject(send(publish(c,bad),[publisher]),'Stage1InvalidFunding');
    const wrong=input(c.oracle.input);wrong.opening.basis[7]=bn(1);wrong.opening.backing[7]=bn(1);
    await reject(send(publish(c,wrong),[publisher]),'Stage1Locked');
    for(const payableRoleTotals of [[bn(2_500_001),bn(0)],[bn(0),bn(2_500_001)]])await reject(send(publish(c,{...input(c.oracle.input),payableRoleTotals}),[publisher]),'Stage1InvalidFunding');
    const rs=roots(c.oracle);rs[0].total=rs[0].total.addn(1);
    await reject(send(publish(c,undefined,rs),[publisher]),'Stage1InvalidFunding');
    const otherMint=await makeMint(wallet.publicKey);
    const wrongMint=publish(c);wrongMint[0]=wrongMint[0].accounts({mint:otherMint});
    await reject(send(wrongMint,[publisher]),'InvalidMint');
    expect(await bytes([dung(c),set(c,0),set(c,1),state(),legacy()])).deep.eq(before);
  });
  it('admin can revise the ceiling while retaining an active start week',async()=>{
    await send(configure(CAP+1,1));
    await send(publish(policy,{...input(policy.oracle.input),postbondTssMicros:bn(CAP+1)})[0],[publisher]);
    expect(publicationEvents.get(dung(policy).toBase58())!.data.allocation.potential.toString()).eq(String(CAP+1));
    await send(configure(CAP,1));await audit();
  });
  for(const name of names.slice(1))it(`oracle mint allocation and actual claims: ${name}`,async()=>{
    const c=cases.find(c=>c.name===name)!;
    if(c.oracle.week>1)await move(LAUNCH+(c.oracle.week+1)*W+86400+100);
    if(!c.oracle.admitted){await reject(send(publish(c),[publisher]),'Stage1InvalidFunding');await audit();return;}
    if(c.oracle.week>1){
      await reject(send(publish(c),[publisher]),'Stage1WeekNotFinalizable');
      for(let from=1;from<c.oracle.week;from+=16){const through=Math.min(c.oracle.week-1,from+15);
        await send(program.methods.skipStage1DungWeeks(bn(through),[...hash(`oracle-empty-${c.name}-${from}-${through}`)],0,bn(0))
          .accounts({city:city(),hill:c.hill,publisher:publisher.publicKey}),[publisher]);}
    }
    await send(publish(c),[publisher]);
    const d=await program.account.stage1DungMint.fetch(dung(c));
    const event=publicationEvents.get(dung(c).toBase58())!.data;
    for(const key of ['potential','riders','backers','unminted'])expect(event.allocation[key].toString()).eq(String(c.oracle.allocation[key]));
    expect(event.backerWeightQuarters.toString()).eq(c.oracle.opening_weight_quarters);
    await openClaims(c);
    for(let role=0;role<2;role++){
      for(const leaf of c.oracle.roots[role].leaves){await send(await claim(c,role,leaf));}
      const info=(await provider.connection.getAccountInfo(set(c,role),'processed'))!,start=claimHeaderBytes(program,'Stage1DungClaimSet');
      expect(info.data.subarray(start,start+Math.ceil(c.oracle.roots[role].leaf_count/8)).toString('hex')).eq(c.oracle.roots[role].claimed_bitmap);
    }
    await audit();
  });
  it('batches weeks and shared DUNG role records, with complete proof and mint-failure rollback',async()=>{
    const first=batched,second={...batched,oracle:{...batched.oracle,week:2,roots:batched.oracle.roots.map((r:any,role:number)=>{
      const value=JSON.parse(execFileSync(PYTHON,['-m','tools.stage1_reference.claim_vectors','--merkle-stdin'],{cwd:ROOT,encoding:'utf8',input:JSON.stringify({kind:'payments',context:[program.programId.toBase58(),city().toBase58(),batched.hill.toBase58(),2,`${mint}:${role===0?'riders':'backers'}`],payments:r.leaves.map((l:any)=>[l.person,l.recipient,l.amount])})}));
      return {...value,leaf_count:value.count};})}};
    await send(publish(first),[publisher]);await send(publish(second),[publisher]);
    const entries=[{c:first,role:0},{c:first,role:1},{c:second,role:0}].map(e=>({...e,leaf:e.c.oracle.roots[e.role].leaves.find((l:any)=>l.person===people[0].publicKey.toBase58())}));
    const dest=getAssociatedTokenAddressSync(mint,recipients[0].publicKey);await send(createAssociatedTokenAccountIdempotentInstruction(wallet.publicKey,dest,recipients[0].publicKey,mint));
    const build=(items=entries)=>program.methods.claimStage1DungBatch(people[0].publicKey,items.map(e=>({index:e.leaf.index,amount:bn(e.leaf.amount),proof:e.leaf.proof.map((p:any)=>({hash:[...Buffer.from(p.hash,'hex')],sum:bn(p.sum)}))}))).accounts({city:city(),state:state(),registration:pda('s1v1_recipient',people[0].publicKey.toBuffer()),programConfig:config(),mint,dungMintAuth:pda('dung_mint_auth'),destination:dest,tokenProgram:TOKEN_PROGRAM_ID}).remainingAccounts(items.flatMap(e=>[dung(e.c),set(e.c,e.role)].map(pubkey=>({pubkey,isWritable:true,isSigner:false}))));
    await reject(send(build()),'Stage1Locked');await openClaims(second);
    const keys=[state(),mint,dest,dung(first),dung(second),...entries.map(e=>set(e.c,e.role))],before=await bytes(keys);
    await send(program.methods.pauseStage1Settlement().accounts({city:city(),guardian:guardian.publicKey}),[guardian]);
    await reject(send(build()),'Stage1SettlementPaused');expect(await bytes(keys)).deep.eq(before);
    await send(program.methods.resumeStage1Settlement().accounts({city:city(),programConfig:config(),admin:guardian.publicKey}),[guardian]);
    await reject(send(build([entries[0],entries[0]])),'Stage1InvalidBatch');expect(await bytes(keys)).deep.eq(before);
    const bad=[...entries];bad[2]={...bad[2],leaf:{...bad[2].leaf,amount:bad[2].leaf.amount+1}};
    await reject(send(build(bad)),'Stage1InvalidProof');expect(await bytes(keys)).deep.eq(before);
    await send(createFreezeAccountInstruction(dest,mint,wallet.publicKey));const frozen=await bytes(keys);await reject(send(build()),'frozen');expect(await bytes(keys)).deep.eq(frozen);await send(createThawAccountInstruction(dest,mint,wallet.publicKey));
    const count=(await provider.connection.getProgramAccounts(program.programId,{commitment:'processed'})).length,amount=(await getAccount(provider.connection,dest,'processed')).amount,probe:any={};
    await send(build(),[],probe);expect((await getAccount(provider.connection,dest,'processed')).amount-amount).eq(entries.reduce((n,e)=>n+BigInt(e.leaf.amount),0n));
    expect((await provider.connection.getProgramAccounts(program.programId,{commitment:'processed'})).length).eq(count);
    const d=await program.account.stage1DungMint.fetch(dung(first));expect(d.minted.map((v:any)=>v.toString())).deep.eq(entries.slice(0,2).map(e=>String(e.leaf.amount)));
    for(const e of entries)await reject(send(await claim(e.c,e.role,e.leaf)),'Stage1ClaimReplay');
    await send(await claim(second,1,second.oracle.roots[1].leaves[0]));await audit();
    console.log(`    DUNG three-set/two-week batch: ${probe.computeUnits} CU, ${probe.transactionBytes} bytes, zero tracking accounts`);
  });
  it('claims stay available after later weeks; rejects proof, role, recipient and CPI failures atomically',async()=>{
    const c=adverse;await send(publish(c),[publisher]);
    await openClaims(c);
    for(const through of [16,27])await send(program.methods.skipStage1DungWeeks(bn(through),[...hash(`after-root-${through}`)],0,bn(0))
      .accounts({city:city(),hill:c.hill,publisher:publisher.publicKey}),[publisher]);
    await reject(send(publish(c),[publisher]),'already in use');
    const leaf=c.oracle.roots[0].leaves[0],person=new PublicKey(leaf.person),recipient=new PublicKey(leaf.recipient),destination=getAssociatedTokenAddressSync(mint,recipient);
    const builder=await claim(c,0,leaf);
    const keys=[state(),dung(c),set(c,0),mint,legacy(),destination,pda('s1v1_claim_person',set(c,0).toBuffer(),person.toBuffer()),pda('s1v1_claim_index',set(c,0).toBuffer(),Buffer.from(new Uint32Array([leaf.index]).buffer))];
    const before=await bytes(keys);
    await reject(send(await claim(c,0,{...leaf,amount:leaf.amount+1})),'Stage1InvalidProof');
    await reject(send(await claim(c,0,{...leaf,proof:[]})),'Stage1InvalidProof');
    const badSum=structuredClone(leaf);badSum.proof[0].sum=String(BigInt(badSum.proof[0].sum)+1n);
    await reject(send(await claim(c,0,badSum)),'Stage1InvalidProof');
    const badHash=structuredClone(leaf);badHash.proof[0].hash='00'.repeat(32);
    await reject(send(await claim(c,0,badHash)),'Stage1InvalidProof');
    await reject(send(await claim(c,1,leaf)),'Stage1InvalidProof');
    const wrong=getAssociatedTokenAddressSync(mint,wallet.publicKey);await send(createAssociatedTokenAccountIdempotentInstruction(wallet.publicKey,wrong,wallet.publicKey,mint));
    await reject(send(await claim(c,0,leaf,{destination:wrong})),'Stage1InvalidRecipient');
    expect(await bytes(keys)).deep.eq(before);
    await send(createFreezeAccountInstruction(destination,mint,wallet.publicKey));const frozen=await bytes(keys);
    await reject(send(builder),'frozen');expect(await bytes(keys)).deep.eq(frozen);
    await send(createThawAccountInstruction(destination,mint,wallet.publicKey));
    const prior=(await getAccount(provider.connection,destination,'processed')).amount;
    await send(builder);expect((await getAccount(provider.connection,destination,'processed')).amount-prior).eq(BigInt(leaf.amount));
    const paid=await bytes(keys);await reject(send(builder),'Stage1ClaimReplay');expect(await bytes(keys)).deep.eq(paid);
    await audit();
  });
  it('publisher duplicate-person root pays distinct indices once within its total',async()=>{
    const c=duplicate,role=0,rs=roots(c.oracle),total=Number(c.oracle.roots[0].total);
    const person=people[0].publicKey.toBase58(),recipient=recipients[0].publicKey.toBase58();
    const context=[program.programId.toBase58(),city().toBase58(),c.hill.toBase58(),c.oracle.week,`${mint.toBase58()}:riders`];
    const amounts=[Math.floor(total/2),total-Math.floor(total/2)];
    const hashes=amounts.map((amount,index)=>hash(Buffer.concat([Buffer.from('BR-stage1-v1:leaf\0'),Buffer.from(JSON.stringify([context,index,person,recipient,amount]))])));
    const sumBytes=(v:number)=>Buffer.from(BigInt(v).toString(16).padStart(32,'0'),'hex');
    const root=hash(Buffer.concat([Buffer.from('BR-stage1-v1:parent\0'),hashes[0],sumBytes(amounts[0]),hashes[1],sumBytes(amounts[1])]));
    rs[0]={root:[...root],total:bn(total),leafCount:2};await send(publish(c,undefined,rs),[publisher]);
    await openClaims(c);
    const leaf=(index:number)=>({index,person,recipient,amount:amounts[index],proof:[{hash:hashes[index^1].toString('hex'),sum:String(amounts[index^1])}]});
    await send(await claim(c,0,leaf(0)));
    await send(await claim(c,0,leaf(1)));const before=await bytes([state(),dung(c),set(c,0),mint]);
    await reject(send(await claim(c,0,leaf(1))),'Stage1ClaimReplay');
    expect(await bytes([state(),dung(c),set(c,0),mint])).deep.eq(before);await audit();
  });

  it('closes paid and zero-leaf roles, refunds their payer and permanently prevents recreation',async()=>{
    const close=(c:Case,role:number,payer=publisher.publicKey)=>program.methods.closeStage1DungClaimSet().accounts({claimSet:set(c,role),rentPayer:payer});
    await reject(send(close(adverse,1)),'Stage1ClaimStorage');
    for(const c of [cases.find(c=>c.name==='five')!,cases.find(c=>c.name==='zero-tss')!,cases.find(c=>c.name==='unregistered-all')!])for(const role of [0,1]){
      const account=await program.account.stage1DungClaimSet.fetch(set(c,role));expect(account.claimedCount).eq(account.leafCount);
      await reject(send(close(c,role,wallet.publicKey)),'ConstraintHasOne');
      const info=(await provider.connection.getAccountInfo(set(c,role),'processed'))!,before=await provider.connection.getBalance(publisher.publicKey,'processed');
      const history=await bytes([c.hill]);
      await send(close(c,role));expect(await bytes([c.hill])).deep.eq(history);expect(await provider.connection.getAccountInfo(set(c,role),'processed')).eq(null);
      expect(await provider.connection.getBalance(publisher.publicKey,'processed')-before).eq(info.lamports);
      const d=await program.account.stage1DungMint.fetch(dung(c));expect(d.publishedRoles&(1<<role)).eq(1<<role);
      await reject(send(program.methods.prepareStage1DungClaimSet(role,account.leafCount).accounts({city:city(),dung:dung(c),claimSet:set(c,role),publisher:publisher.publicKey,systemProgram:SystemProgram.programId}),[publisher]),'Stage1ClaimStorage');
    }
    await audit();
  });

  it('closes weekly DUNG records after both roles and refuses every DUNG recreation path',async()=>{
    const closeMint=(c:Case,payer=publisher.publicKey)=>program.methods.closeStage1DungMint().accounts({
      dung:dung(c),hill:c.hill,riderSet:set(c,0),backerSet:set(c,1),rentPayer:payer});
    await reject(send(closeMint(adverse)),'Stage1ClaimStorage');
    for(const c of [cases.find(c=>c.name==='five')!,cases.find(c=>c.name==='zero-tss')!,cases.find(c=>c.name==='unregistered-all')!]){
      const d=await program.account.stage1DungMint.fetch(dung(c));
      expect(d.publishedRoles).eq(3);expect(d.minted.map((n:BN)=>n.toString())).deep.eq(d.roleTotals.map((n:BN)=>n.toString()));
      await reject(send(closeMint(c,wallet.publicKey)),'ConstraintHasOne');
      await send(SystemProgram.transfer({fromPubkey:wallet.publicKey,toPubkey:dung(c),lamports:1000}));
      const balance=await provider.connection.getBalance(publisher.publicKey,'processed'),rent=(await provider.connection.getAccountInfo(dung(c),'processed'))!.lamports;
      const permanent=await bytes([c.hill,state(),mint,legacy(),pda('s1v1_asset',lst.toBuffer())]);
      await send(closeMint(c));
      expect(await provider.connection.getBalance(publisher.publicKey,'processed')-balance).eq(rent);
      expect(await provider.connection.getAccountInfo(dung(c),'processed')).eq(null);
      expect(await bytes([c.hill,state(),mint,legacy(),pda('s1v1_asset',lst.toBuffer())])).deep.eq(permanent);
      closedAllocated+=BigInt(d.roleTotals[0].toString())+BigInt(d.roleTotals[1].toString());
      closedPaid+=BigInt(d.minted[0].toString())+BigInt(d.minted[1].toString());
      await reject(send(publish(c)[0],[publisher]),'Stage1WeekNotFinalizable');
      for(const role of [0,1])for(const call of [publish(c)[role+1],
        program.methods.prepareStage1DungClaimSet(role,c.oracle.roots[role].leaf_count).accounts({city:city(),dung:dung(c),claimSet:set(c,role),publisher:publisher.publicKey,systemProgram:SystemProgram.programId})]){
        try{await send(call,[publisher]);throw Error('closed DUNG namespace recreated');}catch(e:any){expect(e.message).not.eq('closed DUNG namespace recreated');}
        expect(await provider.connection.getAccountInfo(dung(c),'processed')).eq(null);
        expect(await provider.connection.getAccountInfo(set(c,role),'processed')).eq(null);
      }
      expect(await bytes([c.hill,state(),mint,legacy(),pda('s1v1_asset',lst.toBuffer())])).deep.eq(permanent);
    }
    await audit();
  });

  it('each late role root waits its own exact 48 hours; frozen allocations survive cap reduction and disablement',async()=>{
    const c=timed;await send(publish(c)[0],[publisher]);
    await reject(send(program.methods.closeStage1DungMint().accounts({dung:dung(c),hill:c.hill,riderSet:set(c,0),backerSet:set(c,1),rentPayer:publisher.publicKey})),'Stage1ClaimStorage');
    const frozen=(await program.account.stage1DungMint.fetch(dung(c))).frozenAt.toNumber();
    await move(frozen+3*86400);await send(publish(c)[1],[publisher]);
    const riderAt=(await program.account.stage1DungClaimSet.fetch(set(c,0))).publishedAt.toNumber();
    await send(configure(1,null));await move(riderAt+60);await send(publish(c)[2],[publisher]);
    const backerAt=(await program.account.stage1DungClaimSet.fetch(set(c,1))).publishedAt.toNumber();expect(backerAt>riderAt).eq(true);
    const builders=[await claim(c,0,c.oracle.roots[0].leaves[0]),await claim(c,1,c.oracle.roots[1].leaves[0])];
    const captured=await saved(),keys=[dung(c),state(),set(c,0),set(c,1),mint],before=await bytes(keys);
    const supply=(await getMint(provider.connection,mint,'processed')).supply;
    await move(riderAt+WAIT-1,captured,true);
    await reject(send(builders[0]),'Stage1Locked');expect(await bytes(keys)).deep.eq(before);expect(await now()).eq(riderAt+WAIT-1);
    await move(riderAt+WAIT,captured,true);
    const simulation=await send(builders[0]) as Map<string,Buffer>;
    expect(program.coder.accounts.decode('Stage1DungClaimSet',simulation.get(set(c,0).toBase58())!).paid.toString()).eq(String(c.oracle.roots[0].leaves[0].amount));
    expect(MintLayout.decode(simulation.get(mint.toBase58())!).supply-supply).eq(BigInt(c.oracle.roots[0].leaves[0].amount));
    await reject(send(builders[1]),'Stage1Locked');expect(await now()).eq(riderAt+WAIT);
    await move(backerAt+WAIT,captured,true);await send(builders[1]);expect(await now()).eq(backerAt+WAIT);
    await move(backerAt+WAIT,captured);await send(builders[0]);await send(builders[1]);await audit();
  });

});
