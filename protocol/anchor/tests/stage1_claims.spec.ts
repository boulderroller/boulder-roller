import * as anchor from '@coral-xyz/anchor';
import BN from 'bn.js';
import { expect } from 'chai';
import { createHash } from 'crypto';
import { execFileSync } from 'child_process';
import { fileURLToPath } from 'url';
import { resolve } from 'path';
import { writeFileSync } from 'fs';
import { AddressLookupTableProgram, ComputeBudgetProgram, Keypair, PublicKey, SYSVAR_CLOCK_PUBKEY, SYSVAR_SLOT_HASHES_PUBKEY,
  SYSVAR_RENT_PUBKEY, SystemProgram, TransactionInstruction, TransactionMessage, VersionedTransaction } from '@solana/web3.js';
import { createInitializeMint2Instruction, createMintToInstruction, createAssociatedTokenAccountIdempotentInstruction, getAssociatedTokenAddressSync, MINT_SIZE, getAccount, TOKEN_PROGRAM_ID } from '@solana/spl-token';
import { capture, replay, pause, Capture } from './helpers/stage1_replay.js';
import { claimTerms, verifyStoredTerms, withClaimStorage, claimHeaderBytes, claimTailBytes } from './helpers/stage1_claim_storage.js';
import { fundedSweep } from './helpers/stage1_funding.js';

const enabled = process.env.STAGE1_LOCALNET === '1';
const ROOT = resolve(fileURLToPath(new URL('../../..', import.meta.url)));
const PYTHON = process.env.STAGE1_ORACLE_PYTHON ?? 'python3';
let provider = anchor.AnchorProvider.env();
anchor.setProvider(provider);
let program: any = anchor.workspace.BoulderRollers;
const originalProvider=provider, originalProgram=program;
const wallet=provider.wallet as anchor.Wallet, publisher=Keypair.generate(), guardian=Keypair.generate();
const people=Array.from({length:12},()=>Keypair.generate());
const recipients=Array.from({length:12},()=>Keypair.generate());
const W=604800, LAUNCH=1791201600, SOL=1_000_000_000n;
const bn=(v:any)=>new BN(String(v));
const pda=(seed:string,...parts:Buffer[])=>PublicKey.findProgramAddressSync([Buffer.from(seed),...parts],program.programId)[0];
const city=()=>pda('s1v1_city'), config=()=>pda('program_config');
const asset=(mint:PublicKey)=>pda('s1v1_asset',mint.toBuffer());
const earnings=(mint:PublicKey)=>pda('s1v1_earnings',mint.toBuffer());
const u64=(n:number)=>bn(n).toArrayLike(Buffer,'le',8);
const funding=(c:Case,w:number)=>pda('s1v1_funding',c.hill.toBuffer(),c.mint.toBuffer(),u64(w));
const cursor=(c:Case)=>pda('s1v1_cursor',c.hill.toBuffer(),c.mint.toBuffer());
const setKey=(c:Case,w:number)=>pda('s1v1_claims',c.hill.toBuffer(),c.mint.toBuffer(),u64(w));
const hash=(text:string)=>createHash('sha256').update(text).digest();
const clock=async()=>Number((await provider.connection.getAccountInfo(SYSVAR_CLOCK_PUBKEY,'processed'))!.data.readBigInt64LE(32));
let serial=910000, txSerial=0, active: Awaited<ReturnType<typeof replay>>|undefined;
type Case={name:string,mint:PublicKey,source:PublicKey,hill:PublicKey,lot:PublicKey,oracle:any};
const cases:Case[]=[];
const names=['zero','one','four','five','empty-board','tied-board','cap-redistribution','odd-median','even-median','zeros-excluded','release','expire'];
let deep:Case, duplicate:Case, sameSecond:Case;
type ComputeProbe={computeUnits?:number,messageBytes?:number};
async function send(builder:any, signers:Keypair[]=[], lookup:any[]=[], probe?:ComputeProbe){
  const builders=Array.isArray(builder)?builder:[builder];
  const ixs:TransactionInstruction[]=await Promise.all(builders.map(b=>b instanceof TransactionInstruction?b:b.instruction()));
  const instructions=[ComputeBudgetProgram.setComputeUnitLimit({units:1400000}),
    ComputeBudgetProgram.setComputeUnitPrice({microLamports:++txSerial}),...(await Promise.all((await Promise.all(ixs.map(ix=>withClaimStorage(program,ix)))).flat().map(ix=>fundedSweep(program,provider,wallet.publicKey,ix)))).flat()];
  const latest=await provider.connection.getLatestBlockhash('processed');
  const message=new TransactionMessage({payerKey:wallet.publicKey,recentBlockhash:latest.blockhash,instructions});
  const tx=new VersionedTransaction(lookup.length?message.compileToV0Message(lookup):message.compileToLegacyMessage());
  tx.sign([wallet.payer,...signers]);
  if(probe){
    const result=await provider.connection.simulateTransaction(tx,{sigVerify:true,commitment:'processed'});
    expect(result.value.err,JSON.stringify(result.value.logs)).to.equal(null);
    expect(result.value.unitsConsumed).to.be.a('number');
    probe.computeUnits=result.value.unitsConsumed;
    probe.messageBytes=tx.message.serialize().length;
  }
  const signature=await provider.connection.sendRawTransaction(tx.serialize(),{preflightCommitment:'processed'});
  const confirmed=await provider.connection.confirmTransaction({...latest,signature},'processed');
  expect(confirmed.value.err,signature).to.equal(null);return signature;
}
async function reject(action:Promise<unknown>, reason:string){
  try{await action;}catch(e:any){expect(`${e.message}\n${e.logs?.join('\n')}`).to.include(reason);return;}
  throw new Error(`Expected ${reason}`);
}
async function saved(){return capture(provider.connection,program.programId,[wallet.publicKey,publisher.publicKey,guardian.publicKey,...people.map(p=>p.publicKey)]);}
async function move(at:number, from?:Capture){
  const accounts=from??await saved();
  await active?.stop();active=await replay(accounts,at,false);
  provider=new anchor.AnchorProvider(active.connection,wallet,{commitment:'processed',preflightCommitment:'processed'});
  program=new anchor.Program(originalProgram.idl,originalProgram.programId,provider);
  expect(await clock()).to.be.at.least(at);
}
async function open(c:Case,w:number){
  await send([program.methods.initStage1Settlement().accounts({city:city(),hillAccount:{hill:c.hill},asset:asset(c.mint),cursor:cursor(c),payer:wallet.publicKey,systemProgram:SystemProgram.programId}),
    program.methods.openStage1Week(bn(w)).accounts({city:city(),hillAccount:{hill:c.hill},asset:asset(c.mint),
    funding:funding(c,w),payer:wallet.publicKey,systemProgram:SystemProgram.programId,cursor:cursor(c)})]);
}
const freeze=(c:Case,w:number,snapshot:Buffer,cap:any,pub=publisher.publicKey)=>program.methods.freezeStage1Snapshot([...snapshot],bn(cap))
  .accounts({city:city(),hill:c.hill,asset:asset(c.mint),funding:funding(c,w),previous:null,publisher:pub,cursor:cursor(c)});
const publish=(c:Case,w:number,step:any,holds:any[]=[],sources:PublicKey[]=[])=>program.methods.publishStage1ClaimSet([...Buffer.from(step.root,'hex')],bn(step.total),step.count,(holds.length?holds:[0,0,0,0,0]).map(bn))
  .accounts({city:city(),hillAccount:{hill:c.hill},asset:asset(c.mint),funding:funding(c,w),claimSet:setKey(c,w),
    earnings:earnings(c.mint),publisher:publisher.publicKey,systemProgram:SystemProgram.programId,cursor:cursor(c)})
  .remainingAccounts(sources.map(pubkey=>({pubkey,isSigner:false,isWritable:true})));
const holdArgs=(c:Case,source:number,target:number)=>({city:city(),hill:c.hill,asset:asset(c.mint),source:funding(c,source),
  target:funding(c,target),earnings:earnings(c.mint),publisher:publisher.publicKey,cursor:cursor(c)});
const skipBuilder=(c:Case,start:number,through:number,keys?:PublicKey[])=>program.methods.skipStage1EmptyWeeks(bn(through))
  .accounts({city:city(),hill:c.hill,asset:asset(c.mint),cursor:cursor(c),earnings:earnings(c.mint),publisher:publisher.publicKey})
  .remainingAccounts((keys??Array.from({length:through-start+1},(_,i)=>funding(c,start+i))).map(pubkey=>({pubkey,isSigner:false,isWritable:false})));
async function skip(c:Case,start:number,through:number){await send(skipBuilder(c,start,through),[publisher]);}
async function audit(c:Case, expected?:any){
  const a=await program.account.stage1AssetConfig.fetch(asset(c.mint));const l=a.ledger;
  const n=(k:string)=>BigInt(l[k].toString()),realized=BigInt(a.harvestedUnits.toString()),fees=BigInt(a.feesAssessed.toString());
  expect(n('paid')+fees+n('claimable')+n('held')).to.equal(realized);
  expect(n('earnings')).to.equal(fees+n('claimable')+n('held'));
  expect(n('deposited')).to.equal(n('ownerCustody')+n('ownerReturns')+n('earnings')+n('paid'));
  expect(n('pool')<=n('held')).to.equal(true);
  const lots=await program.account.stage1PledgeLot.all();
  const ownerInventory=lots.filter((x:any)=>x.account.mint.equals(c.mint)).reduce((n:bigint,x:any)=>n+BigInt(x.account.units.toString())+BigInt(x.account.ownerUnits.toString()),0n);
  expect(n('ownerCustody')).to.equal(ownerInventory);
  expect((await getAccount(provider.connection,earnings(c.mint),'processed')).amount).to.equal(n('earnings'));
  if(expected){for(const [field,key] of [['paid','paid'],['claimable','claimable'],['held','held'],['earnings','custody']])
    expect(n(field),`${c.name} ${field}`).to.equal(BigInt(expected[key]));
    expect(realized).to.equal(BigInt(expected.realized));expect(fees).to.equal(BigInt(expected.fees));}
  return a;
}
async function bytes(keys:PublicKey[]){return Promise.all(keys.map(async k=>(await provider.connection.getAccountInfo(k,'processed'))?.data.toString('base64')??null));}
async function createCase(name:string):Promise<Case>{
  const mintKey=Keypair.generate(),mint=mintKey.publicKey;
  await send([SystemProgram.createAccount({fromPubkey:wallet.publicKey,newAccountPubkey:mint,space:MINT_SIZE,
    lamports:await provider.connection.getMinimumBalanceForRentExemption(MINT_SIZE),programId:TOKEN_PROGRAM_ID}),
    createInitializeMint2Instruction(mint,9,wallet.publicKey,null)], [mintKey]);
  const source=getAssociatedTokenAddressSync(mint,wallet.publicKey);
  await send([createAssociatedTokenAccountIdempotentInstruction(wallet.publicKey,source,wallet.publicKey,mint),
    createMintToInstruction(mint,source,wallet.publicKey,20n*SOL)]);
  await send(program.methods.configureAsset(true).accounts({city:city(),asset:asset(mint),mint,earnings:earnings(mint),programConfig:config(),admin:wallet.publicKey,
    tokenProgram:TOKEN_PROGRAM_ID,systemProgram:SystemProgram.programId,rent:SYSVAR_RENT_PUBKEY}));
  await send(program.methods.setTestLstRate(bn(1),bn(1),bn(await clock())).accounts({city:city(),asset:asset(mint),programConfig:config(),admin:wallet.publicKey}));
  const id=hash(`claims-hill-${name}`).subarray(0,16),profile=hash(`claims-profile-${name}`);
  const commitment=Buffer.alloc(64);commitment[0]=1;id.copy(commitment,1);commitment.writeUInt16BE(1,17);profile.copy(commitment,32);
  const digest=hashBytes(commitment),climb=pda('climb',digest),hill=pda('s1v1_hill',id);
  await send(program.methods.registerRatifiedClimb({canonId:[...id],canonVersion:1,canonicalProfileHash:[...profile],commitmentHash:[...digest],
    recordContinuityPolicy:{newRecordBoard:{}},name:`Local claims ${name}`,vertM:1000,distanceM:2000,avgGradientPct:500})
    .accounts({climb,climbVersionIndex:pda('climb_version',id,Buffer.from([0,1])),predecessorClimb:null,programConfig:config(),admin:wallet.publicKey,systemProgram:SystemProgram.programId}));
  await send(program.methods.initHillBond().accounts({city:city(),climb,hill,programConfig:config(),admin:wallet.publicKey,systemProgram:SystemProgram.programId}));
  const depositId=++serial,lot=pda('s1v1_lot',wallet.publicKey.toBuffer(),u64(depositId));
  await send(program.methods.bond(bn(depositId),bn(10n*SOL),0).accounts({city:city(),hillAccount:{hill},climb,asset:asset(mint),mint,lot,
    custody:pda('s1v1_custody',lot.toBuffer()),ownerReserve:pda('s1v1_owner',lot.toBuffer()),source,owner:wallet.publicKey,
    tokenProgram:TOKEN_PROGRAM_ID,systemProgram:SystemProgram.programId,rent:SYSVAR_RENT_PUBKEY}));
  const input={case:names.includes(name)?name:'five',deployment:program.programId.toBase58(),city:city().toBase58(),hill:hill.toBase58(),asset:mint.toBase58(),
    people:people.map(p=>p.publicKey.toBase58()),recipients:recipients.map(p=>p.publicKey.toBase58())};
  const oracle=JSON.parse(execFileSync(PYTHON,['-m','tools.stage1_reference.claim_vectors','--stdin'],{cwd:ROOT,input:JSON.stringify(input),encoding:'utf8'}));
  return {name,mint,source,hill,lot,oracle};
}
function hashBytes(b:Buffer){return createHash('sha256').update(b).digest();}
async function harvest(c:Case,units:number){
  await send(program.methods.setTestLstRate(bn(2),bn(1),bn(await clock())).accounts({city:city(),asset:asset(c.mint),programConfig:config(),admin:wallet.publicKey}));
  await send(program.methods.harvestStage1(bn(units)).accounts({city:city(),hill:c.hill,lot:c.lot,asset:asset(c.mint),
    custody:pda('s1v1_custody',c.lot.toBuffer()),ownerReserve:pda('s1v1_owner',c.lot.toBuffer()),earnings:earnings(c.mint),tokenProgram:TOKEN_PROGRAM_ID}));
}
async function destination(c:Case,leaf:any){
  const owner=new PublicKey(leaf.recipient),ata=getAssociatedTokenAddressSync(c.mint,owner);
  if(!await provider.connection.getAccountInfo(ata,'processed'))await send(createAssociatedTokenAccountIdempotentInstruction(wallet.publicKey,ata,owner,c.mint));
  return ata;
}
async function claimBuilder(c:Case,w:number,leaf:any,override:any={}){
  const person=new PublicKey(leaf.person),index=override.index??leaf.index,set=setKey(c,w);
  return program.methods.claimStage1(index,person,bn(override.amount??leaf.amount),(override.proof??leaf.proof).map((n:any)=>({hash:[...Buffer.from(n.hash,'hex')],sum:bn(n.sum)})),claimTerms(program,set))
    .accounts({city:city(),asset:asset(c.mint),claimSet:set,registration:pda('s1v1_recipient',person.toBuffer()),
      earnings:earnings(c.mint),destination:override.destination??await destination(c,leaf),tokenProgram:TOKEN_PROGRAM_ID});
}
async function pay(c:Case,step:any){
  for(const leaf of step.leaves){const dest=await destination(c,leaf),before=(await getAccount(provider.connection,dest,'processed')).amount;
    await send(await claimBuilder(c,step.week,leaf));
    const set=setKey(c,step.week),person=new PublicKey(leaf.person);
    expect(await provider.connection.getAccountInfo(pda('s1v1_claim_person',set.toBuffer(),person.toBuffer()),'processed'),'claim must create no person receipt').to.equal(null);
    expect(await provider.connection.getAccountInfo(pda('s1v1_claim_index',set.toBuffer(),bn(leaf.index).toArrayLike(Buffer,'le',4)),'processed'),'claim must create no index account').to.equal(null);
    expect((await getAccount(provider.connection,dest,'processed')).amount-before).to.equal(BigInt(leaf.amount));
    await audit(c);}
  await audit(c,step.after_claims);
}

if(enabled)describe('stage 1 funded claims on a LOCAL validator',()=>{
  before(async()=>{
    expect(['127.0.0.1','localhost']).to.include(new URL(provider.connection.rpcEndpoint).hostname);
    if(!await provider.connection.getAccountInfo(config())){
      const executable=(await provider.connection.getAccountInfo(program.programId))!;
      await send(program.methods.initializeProgramConfig(wallet.publicKey).accounts({programConfig:config(),program:program.programId,
        programData:new PublicKey(executable.data.subarray(4,36)),admin:wallet.publicKey,systemProgram:SystemProgram.programId}));
    }
    const clean=await capture(provider.connection,program.programId,[wallet.publicKey]);
    for(const [key,account] of clean)if((account.owner.equals(program.programId)&&key!==config().toBase58())||account.owner.equals(TOKEN_PROGRAM_ID))clean.delete(key);
    await move(LAUNCH+100,clean);
    await send(program.methods.initCityConfig(bn(LAUNCH)).accounts({city:city(),programConfig:config(),admin:wallet.publicKey,systemProgram:SystemProgram.programId}));
    // The publisher pays rent for every immutable root in the 27-week trace.
    for(const person of [publisher,guardian,...people])await send(SystemProgram.transfer({fromPubkey:wallet.publicKey,toPubkey:person.publicKey,
      lamports:person===publisher?30_000_000_000:100_000_000}));
    for(let i=0;i<people.length;i++)await send(program.methods.registerStage1Recipient(recipients[i].publicKey)
      .accounts({registration:pda('s1v1_recipient',people[i].publicKey.toBuffer()),person:people[i].publicKey,payer:wallet.publicKey,systemProgram:SystemProgram.programId}),[people[i]]);
    for(const name of names)cases.push(await createCase(name));
    deep=await createCase('deepest');duplicate=await createCase('duplicate');sameSecond=await createCase('same-second');
    await move(LAUNCH+W+86400+100);
  });
  after(async()=>{await active?.stop();provider=originalProvider;program=originalProgram;});
  it('admin installs a publisher that cannot configure assets or principal',async()=>{
    await reject(send(program.methods.setStage1Publisher(publisher.publicKey).accounts({city:city(),programConfig:config(),admin:publisher.publicKey}),[publisher]),'Stage1Unauthorized');
    await send(program.methods.setStage1Publisher(publisher.publicKey).accounts({city:city(),programConfig:config(),admin:wallet.publicKey}));
    const c=cases[0];await reject(send(program.methods.configureAsset(false).accounts({city:city(),asset:asset(c.mint),mint:c.mint,earnings:earnings(c.mint),
      programConfig:config(),admin:publisher.publicKey,tokenProgram:TOKEN_PROGRAM_ID,systemProgram:SystemProgram.programId,rent:SYSVAR_RENT_PUBKEY}),[publisher]),'Stage1Unauthorized');
  });
  it('funds every allocation with actual surplus after skipping empty week zero',async()=>{
    for(const c of [...cases,deep,duplicate,sameSecond]){
      await open(c,1);
      await reject(send(freeze(c,1,hash('skip'),1),[publisher]),'Stage1WeekNotFinalizable');
      await skip(c,0,0);
      expect(await provider.connection.getAccountInfo(funding(c,0))).to.equal(null);
      expect(await provider.connection.getAccountInfo(setKey(c,0))).to.equal(null);
      await harvest(c,c===deep?72818:c.oracle.harvest);
      await audit(c);
    }
    await move(LAUNCH+2*W+86400+100);
  });
  it('freezes measurement and cap exactly once; unauthorized or empty commitments fail',async()=>{
    const c=cases[4],step=c.oracle.steps[0];
    await reject(send(freeze(c,1,Buffer.alloc(32),step.cap),[publisher]),'Stage1SnapshotFrozen');
    await reject(send(freeze(c,1,Buffer.from(step.snapshot,'hex'),step.cap,wallet.publicKey)),'Stage1Unauthorized');
    await reject(send(freeze(c,1,Buffer.from(step.snapshot,'hex'),step.cap).accounts({cursor:cursor(cases[0])}),[publisher]),'ConstraintSeeds');
    await send(freeze(c,1,Buffer.from(step.snapshot,'hex'),step.cap),[publisher]);
    await reject(send(freeze(c,1,hash('different'),999),[publisher]),'Stage1SnapshotFrozen');
    for(const other of cases.filter(x=>x!==c)){const s=other.oracle.steps[0];await send(freeze(other,1,Buffer.from(s.snapshot,'hex'),s.cap),[publisher]);}
  });
  it('guardian freezes weekly publication, hold processing and skips without moving funds',async()=>{
    const admin={city:city(),programConfig:config(),admin:wallet.publicKey};
    await send(program.methods.setStage1Guardian(guardian.publicKey).accounts(admin));
    const c=cases[0],s=c.oracle.steps[0];
    const keys=[asset(c.mint),earnings(c.mint),funding(c,1),cursor(c),setKey(c,1),c.lot,c.hill];
    const before=await bytes(keys);
    await send(program.methods.pauseStage1Settlement().accounts({city:city(),guardian:guardian.publicKey}),[guardian]);
    expect(await bytes(keys)).to.deep.equal(before);
    expect((await program.account.stage1CityConfig.fetch(city())).settlementPaused).to.equal(true);
    for(const call of [publish(c,1,s,s.holds['1'].buckets),freeze(c,1,hash('paused'),1),
      program.methods.prepareStage1Hold([0,0,0,0,0].map(bn)).accounts(holdArgs(c,1,1)),
      program.methods.expireStage1Hold(bn(1)).accounts(holdArgs(c,1,1)),skipBuilder(c,1,1)]) {
      await reject(send(call,[publisher]),'Stage1SettlementPaused');
      expect(await bytes(keys)).to.deep.equal(before);
    }
    await send(program.methods.resumeStage1Settlement().accounts({...admin,admin:guardian.publicKey}),[guardian]);
    expect((await program.account.stage1CityConfig.fetch(city())).settlementPaused).to.equal(false);
    await send(program.methods.pauseStage1Settlement().accounts({city:city(),guardian:guardian.publicKey}),[guardian]);
    await reject(send(program.methods.pauseStage1Settlement().accounts({city:city(),guardian:publisher.publicKey}),[publisher]),'Stage1Unauthorized');
    await send(program.methods.resumeStage1Settlement().accounts(admin));
    expect(await bytes(keys)).to.deep.equal(before);
  });
  it('rejects an over-funded publication without creating a root or changing any ledger',async()=>{
    const c=cases[4],s=c.oracle.steps[0],keys=[funding(c,1),asset(c.mint),earnings(c.mint),c.hill,setKey(c,1)];
    const before=await bytes(keys);await reject(send(publish(c,1,{...s,total:Number(s.total)+1},s.holds['1'].buckets),[publisher]),'Stage1InvalidFunding');
    expect(await bytes(keys)).to.deep.equal(before);
  });
  for(const name of names)it(`oracle allocation, root, payment and accounting: ${name}`,async()=>{
    const c=cases.find(c=>c.name===name)!,s=c.oracle.steps[0];
    await send(publish(c,1,s,s.holds['1']?.buckets??[0,0,0,0,0]),[publisher]);
    await audit(c,s.before_claims);
    const stored=await program.account.stage1ClaimSet.fetch(setKey(c,1));
    expect(Buffer.from(stored.root).toString('hex')).to.equal(s.root);expect(stored.total.toString()).to.equal(s.total);
    await verifyStoredTerms(program,setKey(c,1));
    // Retain one unclaimed tree for adversarial claims below.
    if(name!=='five')await pay(c,s);
  });
  it('malformed sibling, sum, depth, amount, padding and redirect all roll back',async()=>{
    await send(program.methods.pauseStage1Settlement().accounts({city:city(),guardian:guardian.publicKey}),[guardian]);
    const c=cases.find(c=>c.name==='five')!,s=c.oracle.steps[0],leaf=s.leaves[0];
    const dest=await destination(c,leaf),keys=[asset(c.mint),earnings(c.mint),setKey(c,1),dest];
    const before=await bytes(keys);
    const badHash=structuredClone(leaf.proof);badHash[0].hash='ff'.repeat(32);
    const badSum=structuredClone(leaf.proof);badSum[0].sum=String(BigInt(badSum[0].sum)+1n);
    for(const opts of [{proof:badHash},{proof:badSum},{proof:leaf.proof.slice(1)},{proof:[...leaf.proof,leaf.proof[0]]},{amount:leaf.amount+1},{index:s.count}]){
      await reject(send(await claimBuilder(c,1,leaf,opts)),'Stage1InvalidProof');expect(await bytes(keys)).to.deep.equal(before);
    }
    await reject(send(await claimBuilder(c,1,leaf,{destination:c.source})),'Stage1InvalidRecipient');expect(await bytes(keys)).to.deep.equal(before);
    await pay(c,s);
    const paid=await bytes(keys);await reject(send(await claimBuilder(c,1,leaf)),'Stage1ClaimReplay');expect(await bytes(keys)).to.deep.equal(paid);
    expect((await program.account.stage1CityConfig.fetch(city())).settlementPaused).to.equal(true);
    await send(program.methods.resumeStage1Settlement().accounts({city:city(),programConfig:config(),admin:wallet.publicKey}));
  });
  it('empty roots cannot pay and published keys cannot be reused',async()=>{
    const c=cases[0],sample=cases[1].oracle.steps[0].leaves[0];
    await reject(send(await claimBuilder(c,1,sample)),'Stage1InvalidProof');
    await reject(send(publish(c,1,c.oracle.steps[0],[0,585,225,90,0]),[publisher]),'Stage1ClaimStorage');
  });
  it('carries a prepared hold through funding closure and pays the unchanged oracle root',async()=>{
    const checkpoint=await saved(),at=await clock(),c=cases.find(c=>c.name==='release')!,s=c.oracle.steps[1];
    try{
      await move(LAUNCH+3*W+86400+100);
      await open(c,2);await send(freeze(c,2,Buffer.from(s.snapshot,'hex'),s.cap),[publisher]);
      await send(program.methods.prepareStage1Hold([0,0,0,0,0].map(bn)).accounts(holdArgs(c,1,2)),[publisher]);
      const source=await program.account.stage1WeekFunding.fetch(funding(c,1));
      await send(program.methods.closeStage1ClaimSet().accounts({claimSet:setKey(c,1),rentPayer:publisher.publicKey}));
      // A third party can prefund a closed PDA, but cannot give it program data
      // or publication authority. Both absent witnesses must remain usable.
      await send(SystemProgram.transfer({fromPubkey:wallet.publicKey,toPubkey:setKey(c,1),lamports:await provider.connection.getMinimumBalanceForRentExemption(0)}));
      const before=await bytes([asset(c.mint),earnings(c.mint)]);
      await send(program.methods.closeStage1WeekFunding().accounts({funding:funding(c,1),cursor:cursor(c),asset:asset(c.mint),earnings:earnings(c.mint),claimSet:setKey(c,1),rentPayer:wallet.publicKey}));
      expect(await bytes([asset(c.mint),earnings(c.mint)])).deep.eq(before);await audit(c);
      expect(await provider.connection.getAccountInfo(funding(c,1),'processed')).eq(null);
      await send(SystemProgram.transfer({fromPubkey:wallet.publicKey,toPubkey:funding(c,1),lamports:await provider.connection.getMinimumBalanceForRentExemption(0)}));
      const carried=(await program.account.stage1SettlementCursor.fetch(cursor(c))).carriedHolds[0];
      for(const field of ['week','revision','pool','proposalWeek','proposalRevision'])expect(carried[field].toString()).eq(source[field].toString());
      for(const field of ['holds','lineage','proposalSnapshot','proposalRemaining'])expect(carried[field].map(String)).deep.eq(source[field].map(String));
      expect(carried.proposed).eq(true);expect(carried.source.equals(funding(c,1))).eq(true);
      const tracked=[cursor(c),funding(c,2),asset(c.mint),setKey(c,2)],prepared=await bytes(tracked);
      await reject(send(publish(c,2,{...s,total:Number(s.total)+1},[],[funding(c,1)]),[publisher]),'Stage1InvalidFunding');
      expect(await bytes(tracked)).deep.eq(prepared);
      await send(publish(c,2,s,[],[funding(c,1)]),[publisher]);await pay(c,s);
      expect((await program.account.stage1SettlementCursor.fetch(cursor(c))).carriedHolds).deep.eq([]);
      const closed=await provider.connection.getAccountInfo(funding(c,1),'processed');expect(closed!.owner.equals(SystemProgram.programId)&&closed!.data.length===0).eq(true);
      expect(s.closure.accounting_unchanged&&s.closure.recreation_refused).eq(true);
    }finally{await move(at+100,checkpoint);}
  });

  it('partially releases a closed week and expires its remainder at the original age exactly once',async()=>{
    const checkpoint=await saved(),at=await clock(),c=cases.find(c=>c.name==='expire')!;
    try{
      await send(program.methods.closeStage1ClaimSet().accounts({claimSet:setKey(c,1),rentPayer:publisher.publicKey}));
      await send(program.methods.closeStage1WeekFunding().accounts({funding:funding(c,1),cursor:cursor(c),asset:asset(c.mint),earnings:earnings(c.mint),claimSet:setKey(c,1),rentPayer:wallet.publicKey}));
      await move(LAUNCH+3*W+86400+100);await open(c,2);await send(freeze(c,2,hash('closed partial release'),100),[publisher]);
      const t=JSON.parse(execFileSync(PYTHON,['-m','tools.stage1_reference.claim_vectors','--merkle-stdin'],{cwd:ROOT,encoding:'utf8',input:JSON.stringify({kind:'payments',context:[program.programId.toBase58(),city().toBase58(),c.hill.toBase58(),2,c.mint.toBase58()],payments:[[people[0].publicKey.toBase58(),recipients[0].publicKey.toBase58(),100]]})}));
      const prepare=()=>program.methods.prepareStage1Hold([0,485,225,90,0].map(bn)).accounts(holdArgs(c,1,2));
      await reject(send(prepare().accounts({source:funding(cases.find(x=>x.name==='release')!,1)}),[publisher]),'Stage1InvalidFunding');
      await send(prepare(),[publisher]);await send(publish(c,2,t,[],[funding(c,1)]),[publisher]);await send(await claimBuilder(c,2,t.leaves[0]));
      let cur=await program.account.stage1SettlementCursor.fetch(cursor(c));expect(cur.holds[1].toString()).eq('800');expect(cur.carriedHolds[0].week.toString()).eq('1');await audit(c);
      await move(LAUNCH+28*W+86400+100);await skip(c,3,18);await skip(c,19,26);
      await reject(send(skipBuilder(c,27,27),[publisher]),'Stage1SkipHoldMaturity');
      await open(c,27);await send(freeze(c,27,hash('closed expiry'),0),[publisher]);
      await send(program.methods.expireStage1Hold(bn(27)).accounts(holdArgs(c,1,27)),[publisher]);
      const a=await audit(c);expect(a.ledger.pool.toString()).eq('800');expect(a.ledger.paid.toString()).eq('100');expect(a.harvestedUnits.toString()).eq('1000');
      cur=await program.account.stage1SettlementCursor.fetch(cursor(c));expect(cur.carriedHolds).deep.eq([]);expect(cur.holds[1].toString()).eq('0');
      const before=await bytes([asset(c.mint),cursor(c)]);
      await reject(send(program.methods.expireStage1Hold(bn(27)).accounts(holdArgs(c,1,27)),[publisher]),'Stage1InvalidHold');
      expect(await bytes([asset(c.mint),cursor(c)])).deep.eq(before);
      expect(await provider.connection.getAccountInfo(funding(c,1),'processed')).eq(null);
    }finally{await move(at+100,checkpoint);}
  });

  it('releases original-week holds atomically into a later oracle root without a second fee',async()=>{
    await move(LAUNCH+3*W+86400+100);
    const c=cases.find(c=>c.name==='release')!,s=c.oracle.steps[1];
    await open(c,2);await send(freeze(c,2,Buffer.from(s.snapshot,'hex'),s.cap),[publisher]);
    const before=await audit(c),initial=await bytes([asset(c.mint),earnings(c.mint)]);
    await send(program.methods.prepareStage1Hold([0,0,0,0,0].map(bn)).accounts(holdArgs(c,1,2)),[publisher]);
    expect(await bytes([asset(c.mint),earnings(c.mint)])).to.deep.equal(initial);
    const keys=[funding(c,1),funding(c,2),asset(c.mint),setKey(c,2),c.hill],prepared=await bytes(keys);
    await reject(send(publish(c,2,{...s,total:Number(s.total)+1},[],[funding(c,1)]),[publisher]),'Stage1InvalidFunding');
    expect(await bytes(keys)).to.deep.equal(prepared);
    await reject(send(publish(c,2,s,[],[funding(c,1),funding(c,1)]),[publisher]),'Stage1InvalidFunding');
    expect(await bytes(keys)).to.deep.equal(prepared);
    await send(publish(c,2,s,[],[funding(c,1)]),[publisher]);await pay(c,s);
    expect((await audit(c)).feesAssessed.toString()).to.equal(before.feesAssessed.toString());
    expect((await program.account.stage1WeekFunding.fetch(funding(c,1))).holds.map((v:BN)=>v.toString())).to.deep.equal(['0','0','0','0','0']);
  });
  it('expires at original age 26 before release, with permanent pool and no new income',async()=>{
    await move(LAUNCH+28*W+86400+100);
    const c=cases.find(c=>c.name==='expire')!;
    const heldBefore=await bytes([funding(c,1),asset(c.mint),earnings(c.mint)]);
    await skip(c,2,17);await audit(c);
    await skip(c,18,25);await audit(c);
    expect(await bytes([funding(c,1),asset(c.mint),earnings(c.mint)])).deep.eq(heldBefore);
    for(const s of c.oracle.steps.slice(1)){
      await open(c,s.week);await send(freeze(c,s.week,Buffer.from(s.snapshot,'hex'),s.cap),[publisher]);
      if(s.week===26)await reject(send(program.methods.expireStage1Hold(bn(26)).accounts({city:city(),hill:c.hill,asset:asset(c.mint),
        source:funding(c,1),target:funding(c,26),earnings:earnings(c.mint),publisher:publisher.publicKey,cursor:cursor(c)}),[publisher]),'Stage1HoldNotExpired');
      if(s.week===27)await reject(send(program.methods.prepareStage1Hold([0,0,0,0,0].map(bn)).accounts(holdArgs(c,1,27)),[publisher]),'Stage1InvalidHold');
      if(s.week===27){const keys=[funding(c,1),funding(c,s.week),asset(c.mint),setKey(c,s.week)],before=await bytes(keys);
        await reject(send(publish(c,s.week,s),[publisher]),'Stage1InvalidFunding');expect(await bytes(keys)).to.deep.equal(before);}
      await send(publish(c,s.week,s,[],s.week===27?[funding(c,1)]:[]),[publisher]);await audit(c,s.after_claims);
    }
    const a=await audit(c);expect(a.ledger.pool.toString()).to.equal('900');expect(a.harvestedUnits.toString()).to.equal('1000');
    const book=await program.account.stage1WeekFunding.fetch(funding(c,1));expect(book.week.toString()).to.equal('1');expect(book.pool.toString()).to.equal('900');
  });
  it('pays each distinct index in a publisher root even when a person is duplicated',async()=>{
    const c=duplicate;
    const data=JSON.parse(execFileSync(PYTHON,['-m','tools.stage1_reference.claim_vectors','--merkle-stdin'],{cwd:ROOT,encoding:'utf8',input:JSON.stringify({
      kind:'duplicate',context:[program.programId.toBase58(),city().toBase58(),c.hill.toBase58(),1,c.mint.toBase58()],
      person:people[0].publicKey.toBase58(),recipient:recipients[0].publicKey.toBase58()})}));
    await send(freeze(c,1,hash('adversarial duplicate person fixture'),100),[publisher]);
    await send(publish(c,1,data,[0,0,0,0,700]),[publisher]);
    await send(await claimBuilder(c,1,data.leaves[0]));
    const keys=[asset(c.mint),earnings(c.mint),setKey(c,1)],before=await bytes(keys);
    await send(await claimBuilder(c,1,data.leaves[1]));
    await reject(send(await claimBuilder(c,1,data.leaves[0])),'Stage1ClaimReplay');
    expect((await program.account.stage1ClaimSet.fetch(setKey(c,1))).paid.toString()).to.equal('200');
    await audit(c);
  });
  it('claims at supported depth 16 with a real local transaction and measured compute',async()=>{
    const c=deep;
    const data=JSON.parse(execFileSync(PYTHON,['-m','tools.stage1_reference.claim_vectors','--merkle-stdin'],{cwd:ROOT,encoding:'utf8',input:JSON.stringify({
      kind:'deep',context:[program.programId.toBase58(),city().toBase58(),c.hill.toBase58(),1,c.mint.toBase58()],
      person:people[1].publicKey.toBase58(),recipient:recipients[1].publicKey.toBase58()})}));
    expect(data.count).to.equal(65536);expect(data.leaves[0].proof).to.have.length(16);
    const book=await program.account.stage1WeekFunding.fetch(funding(c,1));
    await send(freeze(c,1,hash('synthetic maximum-depth benchmark'),1),[publisher]);
    const required=claimHeaderBytes(program)+claimTailBytes(65536);
    const prepare=()=>program.methods.prepareStage1ClaimSet(65536).accounts({city:city(),asset:asset(c.mint),funding:funding(c,1),claimSet:setKey(c,1),publisher:publisher.publicKey,systemProgram:SystemProgram.programId});
    while((await provider.connection.getAccountInfo(setKey(c,1),'processed'))?.data.length!==required) {
      const length=(await provider.connection.getAccountInfo(setKey(c,1),'processed'))?.data.length??0;
      await send(Array.from({length:Math.min(8,Math.ceil((required-length)/10240))},prepare),[publisher]);
    }
    await send(publish(c,1,data,[0,0,0,0,Number(book.available.toString())-65536]),[publisher]);
    expect((await provider.connection.getAccountInfo(setKey(c,1),'processed'))!.data.length).eq(required);
    const builder=await claimBuilder(c,1,data.leaves[0]),ix=await builder.instruction();
    // Use an actual completed recent slot; the current processed slot may
    // not yet have a hash.
    const history=(await provider.connection.getAccountInfo(SYSVAR_SLOT_HASHES_PUBKEY,'processed'))!;
    expect(Number(history.data.readBigUInt64LE(0))).to.be.greaterThan(0);
    const slot=Number(history.data.readBigUInt64LE(8));
    const [create,table]=AddressLookupTableProgram.createLookupTable({authority:wallet.publicKey,payer:wallet.publicKey,recentSlot:slot});
    await send(create);
    const addresses=ix.keys.filter((k:any)=>!k.isSigner).map((k:any)=>k.pubkey);
    await send(AddressLookupTableProgram.extendLookupTable({authority:wallet.publicKey,payer:wallet.publicKey,lookupTable:table,
      addresses}));
    // Agave's packet scheduler resolves v0 lookup addresses against the root
    // bank. A processed simulation can succeed before the table is usable there.
    let lookup:any,rooted=false;for(let i=0;i<300;i++){
      lookup=(await provider.connection.getAddressLookupTable(table,{commitment:'finalized'})).value;
      if(lookup && lookup.state.addresses.length===addresses.length
          && addresses.every((key:PublicKey,index:number)=>key.equals(lookup.state.addresses[index]))
          && await provider.connection.getSlot('finalized')>lookup.state.lastExtendedSlot){rooted=true;break;}
      await pause(100);
    }
    expect(rooted,'complete lookup table must be finalized before signing').to.equal(true);
    // Measure a signature-verified simulation, then submit those exact signed
    // bytes using a fresh blockhash obtained after the table is rooted.
    const probe:ComputeProbe={};
    const signature=await send(builder,[],[lookup],probe);
    const cu=probe.computeUnits!;expect(cu).to.be.greaterThan(0).and.lessThan(1400000);
    expect((await program.account.stage1ClaimSet.fetch(setKey(c,1))).paid.toString()).to.equal('1');
    expect((await getAccount(provider.connection,await destination(c,data.leaves[0]),'processed')).amount).to.equal(1n);
    const evidence={evidence:'local signed simulation compute; identical signed transaction committed; synthetic 65536-leaf tree',
      depth:16,leaf_count:65536,compute_units:cu,signature,message_bytes:probe.messageBytes};
    console.log(`      depth-16 claim simulation: ${cu} compute units; payment committed`);
    if(process.env.STAGE1_CLAIMS_EVIDENCE)writeFileSync(process.env.STAGE1_CLAIMS_EVIDENCE,JSON.stringify(evidence,null,2)+'\n');
    await audit(c);
  });

  it('accepts immutable recipient registration and snapshot freezing within the same transaction second',async()=>{
    const c=sameSecond,person=Keypair.generate();
    await send(SystemProgram.transfer({fromPubkey:wallet.publicKey,toPubkey:person.publicKey,lamports:10_000_000}));
    const registration=pda('s1v1_recipient',person.publicKey.toBuffer());
    const data=JSON.parse(execFileSync(PYTHON,['-m','tools.stage1_reference.claim_vectors','--merkle-stdin'],{cwd:ROOT,encoding:'utf8',input:JSON.stringify({
      kind:'single',context:[program.programId.toBase58(),city().toBase58(),c.hill.toBase58(),1,c.mint.toBase58()],
      person:person.publicKey.toBase58(),recipient:recipients[0].publicKey.toBase58()})}));
    await send([program.methods.registerStage1Recipient(recipients[0].publicKey).accounts({registration,person:person.publicKey,payer:wallet.publicKey,systemProgram:SystemProgram.programId}),
      freeze(c,1,hash('same-second registration'),100)], [person,publisher]);
    expect((await program.account.stage1Recipient.fetch(registration)).registeredAt.toString())
      .to.equal((await program.account.stage1WeekFunding.fetch(funding(c,1))).frozenAt.toString());
    await send(publish(c,1,data,[0,0,0,0,800]),[publisher]);await send(await claimBuilder(c,1,data.leaves[0]));await audit(c);
  });
  it('rejects under-covered earnings atomically in an explicitly corrupted local snapshot',async()=>{
    await move(LAUNCH+29*W+86400+100);
    const c=cases.find(c=>c.name==='expire')!;
    await open(c,28);await send(freeze(c,28,hash('coverage regression fixture'),0),[publisher]);
    const clean=await saved(),damaged=new Map(clean),key=earnings(c.mint).toBase58(),original=clean.get(key)!;
    const data=Buffer.from(original.data);data.writeBigUInt64LE(0n,64);
    damaged.set(key,{...original,data});
    const at=await clock();await move(at+100,damaged);
    const keys=[funding(c,1),funding(c,28),asset(c.mint),earnings(c.mint)],before=await bytes(keys);
    await reject(send(program.methods.expireStage1Hold(bn(28)).accounts({city:city(),hill:c.hill,asset:asset(c.mint),
      source:funding(c,1),target:funding(c,28),earnings:earnings(c.mint),publisher:publisher.publicKey,cursor:cursor(c)}),[publisher]),'Stage1InvalidCustody');
    expect(await bytes(keys)).to.deep.equal(before);
    await move(at+200,clean);await audit(c);
  });

  it('skips quiet hold-bearing weeks but refuses the original maturity',async()=>{
    const c=cases.find(c=>c.name==='zero')!,keys=[funding(c,1),asset(c.mint),earnings(c.mint)];
    const before=await bytes(keys);
    await skip(c,2,17);await audit(c);
    await skip(c,18,26);await audit(c);
    expect(await bytes(keys)).to.deep.equal(before);
    await reject(send(skipBuilder(c,27,27),[publisher]),'Stage1SkipHoldMaturity');
    expect(await bytes(keys)).to.deep.equal(before);
    expect((await program.account.stage1SettlementCursor.fetch(cursor(c))).holds[1].toString()).eq('900');
  });
  it('explicit expiry clears the original hold slot, retains pool and permits later empty skips',async()=>{
    const c=cases.find(c=>c.name==='zero')!;
    const empty=(w:number)=>({root:hash(`BR-stage1-v1:empty\0${JSON.stringify([program.programId.toBase58(),city().toBase58(),c.hill.toBase58(),w,c.mint.toBase58()])}`).toString('hex'),total:0,count:0});
    await open(c,27);await send(freeze(c,27,hash('explicit original-age 26'),1),[publisher]);
    const expiry=()=>program.methods.expireStage1Hold(bn(27)).accounts(holdArgs(c,1,27));
    expect((await program.account.stage1SettlementCursor.fetch(cursor(c))).holds[1].toString()).to.equal('900');
    await send(expiry(),[publisher]);
    expect((await program.account.stage1SettlementCursor.fetch(cursor(c))).holds[1].toString()).to.equal('0');
    const keys=[cursor(c),funding(c,1),funding(c,27),asset(c.mint),setKey(c,27)];
    await send(expiry(),[publisher]);
    expect((await audit(c)).ledger.pool.toString()).to.equal('900');
    const afterRepeat=await bytes(keys);
    await reject(send(publish(c,27,{root:hash('pool is not new income').toString('hex'),total:1,count:1}),[publisher]),'Stage1InvalidFunding');
    expect(await bytes(keys)).to.deep.equal(afterRepeat);
    await send(publish(c,27,empty(27)),[publisher]);
    await skip(c,28,28);
    expect(await provider.connection.getAccountInfo(funding(c,28))).to.equal(null);
    expect(await provider.connection.getAccountInfo(setKey(c,28))).to.equal(null);
    expect((await audit(c)).ledger.pool.toString()).to.equal('900');
  });
  it('starts at week 100, pays three funded weeks out of ten, and measures sparse rent',async()=>{
    await move(LAUNCH+100*W+100);
    const c=await createCase('late-sparse');
    expect((await program.account.stage1HillBond.fetch(c.hill)).admittedWeek.toString()).to.equal('100');
    const data=(week:number,amount=900)=>JSON.parse(execFileSync(PYTHON,['-m','tools.stage1_reference.claim_vectors','--merkle-stdin'],{
      cwd:ROOT,encoding:'utf8',input:JSON.stringify({kind:'single',amount,context:[program.programId.toBase58(),city().toBase58(),c.hill.toBase58(),week,c.mint.toBase58()],
      person:people[0].publicKey.toBase58(),recipient:recipients[0].publicKey.toBase58()})}));
    await harvest(c,1000);
    await reject(open(c,99),'Stage1WeekNotFinalizable');
    await reject(send(skipBuilder(c,100,100),[publisher]),'Stage1WeekNotFinalizable');
    await move(LAUNCH+101*W+86400+100);
    const before=await bytes([cursor(c),funding(c,100),asset(c.mint)]);
    await reject(send(skipBuilder(c,100,100),[publisher]),'Stage1InvalidFunding');
    expect(await bytes([cursor(c),funding(c,100),asset(c.mint)])).to.deep.equal(before);
    await send(freeze(c,100,hash('late week 100'),900),[publisher]);
    await send(publish(c,100,data(100)),[publisher]);
    for(const week of [104,109]){
      await move(LAUNCH+week*W+100);await harvest(c,1000);
      await move(LAUNCH+(week+1)*W+86400+100);
      const start=Number((await program.account.stage1SettlementCursor.fetch(cursor(c))).nextWeek.toString());
      const keys=[cursor(c),funding(c,week),asset(c.mint)],saved=await bytes(keys);
      // A funded final week cannot be hidden by omitted, duplicate or foreign witnesses.
      await reject(send(skipBuilder(c,start,week),[publisher]),'Stage1InvalidFunding');
      await reject(send(skipBuilder(c,start,week-1,[funding(c,start)]),[publisher]),'Stage1InvalidFunding');
      await reject(send(skipBuilder(c,start,week-1,Array.from({length:week-start},()=>funding(c,start))),[publisher]),'Stage1InvalidFunding');
      await reject(send(skipBuilder(c,start,week-1).accounts({cursor:cursor(cases[0])}),[publisher]),'ConstraintSeeds');
      expect(await bytes(keys)).to.deep.equal(saved);
      await skip(c,start,week-1);
      await reject(open(c,start),'Stage1WeekNotFinalizable');
      if(week===104)await send(await claimBuilder(c,100,data(100).leaves[0]));
      await send(freeze(c,week,hash(`late week ${week}`),900),[publisher]);
      await send(publish(c,week,data(week)),[publisher]);
      await send(await claimBuilder(c,week,data(week).leaves[0]));
      await audit(c);
    }
    expect((await program.account.stage1SettlementCursor.fetch(cursor(c))).nextWeek.toString()).to.equal('110');
    const all=await provider.connection.getMultipleAccountsInfo(Array.from({length:10},(_,i)=>funding(c,100+i)));
    const sets=await provider.connection.getMultipleAccountsInfo(Array.from({length:10},(_,i)=>setKey(c,100+i)));
    expect(all.filter(Boolean)).to.have.length(3);expect(sets.filter(Boolean)).to.have.length(3);
    const bookBytes=all[0]!.data.length,setBytes=sets[0]!.data.length;
    const progress=(await provider.connection.getAccountInfo(cursor(c)))!;
    const bookRent=await provider.connection.getMinimumBalanceForRentExemption(bookBytes),setRent=await provider.connection.getMinimumBalanceForRentExemption(setBytes);
    const cursorRent=await provider.connection.getMinimumBalanceForRentExemption(progress.data.length);
    const hillBytes=(await provider.connection.getAccountInfo(c.hill))!.data.length;
    const admissionRent=(await provider.connection.getMinimumBalanceForRentExemption(hillBytes))
      -(await provider.connection.getMinimumBalanceForRentExemption(hillBytes-8));
    const rent={evidence:'local validator rent exemption; three fully allocated funded weeks 100/104/109, no holds',
      book_bytes:bookBytes,set_bytes:setBytes,cursor_bytes:progress.data.length,
      book_lamports:bookRent,set_lamports:setRent,cursor_lamports:cursorRent,
      before_lamports:110*(bookRent+setRent),after_lamports:3*(bookRent+setRent)+cursorRent,
      shared_hill_added_bytes:8,shared_hill_added_lamports:admissionRent,
      deferred_book_recovery_lamports:3*bookRent,retained_sets_lamports:3*setRent};
    expect(all.filter(Boolean).reduce((n,x)=>n+x!.lamports,0)+sets.filter(Boolean).reduce((n,x)=>n+x!.lamports,0)+progress.lamports).to.equal(rent.after_lamports);
    console.log(`      sparse rent: ${JSON.stringify(rent)}`);
    if(process.env.STAGE1_RENT_EVIDENCE)writeFileSync(process.env.STAGE1_RENT_EVIDENCE,JSON.stringify(rent,null,2)+'\n');
  });
  it('never skips a fee-only income week and never skips a frozen empty book',async()=>{
    const week=Math.floor(((await clock())-LAUNCH)/W),c=await createCase('fee-only');
    await harvest(c,9);
    await move(LAUNCH+(week+1)*W+86400+100);
    const context=(w:number)=>[program.programId.toBase58(),city().toBase58(),c.hill.toBase58(),w,c.mint.toBase58()];
    const first=JSON.parse(execFileSync(PYTHON,['-m','tools.stage1_reference.claim_vectors','--merkle-stdin'],{cwd:ROOT,encoding:'utf8',
      input:JSON.stringify({kind:'single',amount:9,context:context(week),person:people[0].publicKey.toBase58(),recipient:recipients[0].publicKey.toBase58()})}));
    await send(freeze(c,week,hash('nine gross units'),9),[publisher]);await send(publish(c,week,first),[publisher]);
    await harvest(c,1);await move(LAUNCH+(week+2)*W+86400+100);
    const book=await program.account.stage1WeekFunding.fetch(funding(c,week+1));
    expect(book.harvestedNet.toString()).to.equal('0');expect(book.available.toString()).to.equal('0');
    expect(Buffer.from(book.lineage).equals(Buffer.alloc(32))).to.equal(false);
    await reject(send(skipBuilder(c,week+1,week+1),[publisher]),'Stage1InvalidFunding');
    const empty=(w:number)=>({root:hash(`BR-stage1-v1:empty\0${JSON.stringify(context(w))}`).toString('hex'),total:0,count:0});
    await send(freeze(c,week+1,hash('one gross unit all fee'),0),[publisher]);await send(publish(c,week+1,empty(week+1)),[publisher]);
    await open(c,week+2);await move(LAUNCH+(week+3)*W+86400+100);
    await send(freeze(c,week+2,hash('frozen cannot disappear'),0),[publisher]);
    await reject(send(skipBuilder(c,week+2,week+2),[publisher]),'Stage1InvalidFunding');
    await send(publish(c,week+2,empty(week+2)),[publisher]);
    await audit(c);
  });

});
