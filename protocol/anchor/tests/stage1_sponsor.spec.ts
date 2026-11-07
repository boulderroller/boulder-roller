import * as anchor from '@coral-xyz/anchor';
import BN from 'bn.js';
import { expect } from 'chai';
import { createHash } from 'crypto';
import { execFileSync } from 'child_process';
import { fileURLToPath } from 'url';
import { resolve } from 'path';
import { AddressLookupTableProgram, ComputeBudgetProgram, Keypair, PublicKey, SYSVAR_SLOT_HASHES_PUBKEY,
  SYSVAR_RENT_PUBKEY, SystemProgram, TransactionInstruction, TransactionMessage, VersionedTransaction } from '@solana/web3.js';
import { createInitializeMint2Instruction, createMintToInstruction, createAssociatedTokenAccountIdempotentInstruction, getAssociatedTokenAddressSync, MINT_SIZE, MintLayout, getAccount, TOKEN_PROGRAM_ID } from '@solana/spl-token';
import { claimTerms, withClaimStorage } from './helpers/stage1_claim_storage.js';
import { capture, replay, pause, Capture } from './helpers/stage1_replay.js';

const testMintBuild=process.env.STAGE1_LOCALNET==='1'||process.env.STAGE1_DEVNET==='1';
const enabled=testMintBuild||process.env.STAGE1_DEPLOYABLE==='1';
const ROOT=resolve(fileURLToPath(new URL('../../..',import.meta.url)));
const PYTHON=process.env.STAGE1_ORACLE_PYTHON??'python3';
let provider=anchor.AnchorProvider.env();anchor.setProvider(provider);
let program:any=anchor.workspace.BoulderRollers;
const originalProvider=provider,originalProgram=program;
const wallet=provider.wallet as anchor.Wallet,publisher=Keypair.generate(),guardian=Keypair.generate();
const people=Array.from({length:5},()=>Keypair.generate());
const W=604800,LAUNCH=1791201600;
const bn=(v:any)=>new BN(String(v));
const u64=(v:number)=>bn(v).toArrayLike(Buffer,'le',8);
const hash=(v:string|Buffer)=>createHash('sha256').update(v).digest();
const pda=(seed:string,...parts:Buffer[])=>PublicKey.findProgramAddressSync([Buffer.from(seed),...parts],program.programId)[0];
const city=()=>pda('s1v1_city'),config=()=>pda('program_config'),cash=()=>pda('s1v1_cash');
let mint:PublicKey,source:PublicKey,baseline:Capture;
const asset=()=>pda('s1v1_asset',mint.toBuffer()),earnings=()=>pda('s1v1_earnings',mint.toBuffer());
const cursor=(h:PublicKey)=>pda('s1v1_cursor',h.toBuffer(),mint.toBuffer());
const funding=(h:PublicKey,w:number)=>pda('s1v1_funding',h.toBuffer(),mint.toBuffer(),u64(w));
const setKey=(h:PublicKey,w:number)=>pda('s1v1_claims',h.toBuffer(),mint.toBuffer(),u64(w));
const boost=(id:Buffer,funder=wallet.publicKey)=>pda('s1v1_boost',funder.toBuffer(),id);
const stream=(id:Buffer,h:PublicKey,funder=wallet.publicKey)=>pda('s1v1_boost_hill',boost(id,funder).toBuffer(),h.toBuffer());
let active:Awaited<ReturnType<typeof replay>>|undefined,serial=0;
async function send(builder:any,signers:Keypair[]=[],lookup:any[]=[]){
  const builders=Array.isArray(builder)?builder:[builder];
  const ixs=await Promise.all(builders.map(b=>b instanceof TransactionInstruction?b:b.instruction()));
  const instructions=[ComputeBudgetProgram.setComputeUnitLimit({units:1000000}),ComputeBudgetProgram.setComputeUnitPrice({microLamports:++serial}),...(await Promise.all(ixs.map(ix=>withClaimStorage(program,ix)))).flat()];
  const latest=await provider.connection.getLatestBlockhash('processed');
  const message=new TransactionMessage({payerKey:wallet.publicKey,recentBlockhash:latest.blockhash,instructions});
  const tx=new VersionedTransaction(lookup.length?message.compileToV0Message(lookup):message.compileToLegacyMessage());
  tx.sign([wallet.payer,...signers]);
  const sig=await provider.connection.sendRawTransaction(tx.serialize(),{preflightCommitment:'processed'});
  // Wait through the actual blockhash validity window; a fixed ten seconds
  // can expire while a freshly replayed validator is still forwarding it.
  const confirmed=await provider.connection.confirmTransaction({...latest,signature:sig},'processed');
  expect(confirmed.value.err,sig).to.equal(null);return sig;
}
async function reject(action:Promise<unknown>,reason?:string){
  try{await action;}catch(e:any){if(reason)expect(`${e.message}\n${e.logs?.join('\n')}`).to.include(reason);return;}
  throw Error(`Expected refusal ${reason??''}`);
}
async function saved(){return capture(provider.connection,program.programId,[wallet.publicKey,publisher.publicKey,guardian.publicKey,...people.map(p=>p.publicKey)]);}
async function move(at:number,from?:Capture){
  const accounts=from??await saved();await active?.stop();active=await replay(accounts,at,false);
  provider=new anchor.AnchorProvider(active.connection,wallet,{commitment:'processed',preflightCommitment:'processed'});
  program=new anchor.Program(originalProgram.idl,originalProgram.programId,provider);
}
async function bytes(keys:PublicKey[]){return Promise.all(keys.map(async k=>(await provider.connection.getAccountInfo(k,'processed'))?.data.toString('base64')??null));}
async function audit(){
  const a=await program.account.stage1AssetConfig.fetch(asset()),l=a.ledger;
  const n=(k:string)=>BigInt(l[k].toString()),fees=BigInt(a.feesAssessed.toString()),realized=BigInt(a.harvestedUnits.toString());
  expect(n('paid')+fees+n('claimable')+n('held')).eq(realized+n('admittedCashLifetime'));
  expect(n('earnings')).eq(fees+n('claimable')+n('held'));
  expect(n('deposited')+n('admittedCashLifetime')).eq(n('ownerCustody')+n('ownerReturns')+n('earnings')+n('paid'));
  expect((await getAccount(provider.connection,earnings(),'processed')).amount>=n('earnings')).eq(true);
  expect(fees).eq(0n);expect(realized).eq(0n);expect(n('deposited')).eq(0n);expect(n('ownerCustody')).eq(0n);
  return l;
}
async function hill(name:string){
  const id=hash(`sponsor-${name}`).subarray(0,16),profile=hash(`profile-${name}`),commitment=Buffer.alloc(64);
  commitment[0]=1;id.copy(commitment,1);commitment.writeUInt16BE(1,17);profile.copy(commitment,32);
  const digest=hash(commitment),climb=pda('climb',digest),h=pda('s1v1_hill',id);
  await send(program.methods.registerRatifiedClimb({canonId:[...id],canonVersion:1,canonicalProfileHash:[...profile],commitmentHash:[...digest],
    recordContinuityPolicy:{newRecordBoard:{}},name:`Local sponsor ${name}`,vertM:1000,distanceM:2000,avgGradientPct:500})
    .accounts({climb,climbVersionIndex:pda('climb_version',id,Buffer.from([0,1])),predecessorClimb:null,programConfig:config(),admin:wallet.publicKey,systemProgram:SystemProgram.programId}));
  await send(program.methods.initHillBond().accounts({city:city(),climb,hill:h,programConfig:config(),admin:wallet.publicKey,systemProgram:SystemProgram.programId}));
  await send(program.methods.initStage1Settlement().accounts({city:city(),hillAccount:{hill:h},asset:asset(),cursor:cursor(h),payer:wallet.publicKey,systemProgram:SystemProgram.programId}));
  return h;
}
const open=(h:PublicKey,w:number)=>program.methods.openStage1Week(bn(w)).accounts({city:city(),hillAccount:{hill:h},asset:asset(),funding:funding(h,w),cursor:cursor(h),payer:wallet.publicKey,systemProgram:SystemProgram.programId});
const sponsor=(h:PublicKey,w:number,amount:number,over:any={})=>program.methods.sponsorStage1(bn(amount)).accounts({city:city(),cash:cash(),asset:asset(),funding:funding(h,w),cursor:cursor(h),earnings:earnings(),source,funder:wallet.publicKey,tokenProgram:TOKEN_PROGRAM_ID,...over});
const post=(id:Buffer,hills:PublicKey[],total:number,start=1,weeks=1,funder=wallet.publicKey,tokenSource=source)=>program.methods.postStage1Boost([...id],bn(total),bn(start),weeks).accounts({city:city(),cash:cash(),asset:asset(),boost:boost(id,funder),earnings:earnings(),source:tokenSource,funder,tokenProgram:TOKEN_PROGRAM_ID,systemProgram:SystemProgram.programId})
  .remainingAccounts(hills.flatMap(h=>[{pubkey:h,isWritable:false,isSigner:false},{pubkey:cursor(h),isWritable:true,isSigner:false},{pubkey:stream(id,h,funder),isWritable:true,isSigner:false}]));
const freeze=(h:PublicKey,w:number,s:any)=>program.methods.freezeStage1Snapshot([...Buffer.from(s.snapshot,'hex')],bn(s.cap)).accounts({city:city(),hill:h,asset:asset(),funding:funding(h,w),previous:null,publisher:publisher.publicKey,cursor:cursor(h)});
const processStream=(h:PublicKey,w:number,id:Buffer,remaining:any)=>program.methods.processStage1Boost(remaining.map((r:any)=>r.map(bn))).accounts({city:city(),asset:asset(),funding:funding(h,w),cursor:cursor(h),stream:stream(id,h),earnings:earnings(),publisher:publisher.publicKey});
const publish=(h:PublicKey,w:number,s:any,holds:any=[0,0,0,0,0])=>program.methods.publishStage1ClaimSet([...Buffer.from(s.root,'hex')],bn(s.total),s.count,holds.map(bn)).accounts({city:city(),hillAccount:{hill:h},asset:asset(),funding:funding(h,w),claimSet:setKey(h,w),earnings:earnings(),publisher:publisher.publicKey,systemProgram:SystemProgram.programId,cursor:cursor(h)});
const empty=(h:PublicKey,w:number)=>({snapshot:hash(`snapshot-${w}`).toString('hex'),cap:0,total:0,count:0,
  root:hash(Buffer.concat([Buffer.from('BR-stage1-v1:empty\0'),Buffer.from(JSON.stringify([program.programId.toBase58(),city().toBase58(),h.toBase58(),w,mint.toBase58()]))])).toString('hex')});
const skip=(h:PublicKey,w:number,start=w)=>program.methods.skipStage1EmptyWeeks(bn(w)).accounts({city:city(),hill:h,asset:asset(),cursor:cursor(h),earnings:earnings(),publisher:publisher.publicKey})
  .remainingAccounts(Array.from({length:w-start+1},(_,i)=>({pubkey:funding(h,start+i),isSigner:false,isWritable:false})));
const register=(testMint:PublicKey)=>program.methods.registerStage1Cash().accounts({city:city(),cash:cash(),asset:pda('s1v1_asset',testMint.toBuffer()),mint:testMint,earnings:pda('s1v1_earnings',testMint.toBuffer()),programConfig:config(),admin:wallet.publicKey,tokenProgram:TOKEN_PROGRAM_ID,systemProgram:SystemProgram.programId});
async function makeMint(decimals=6){
  const k=Keypair.generate();await send([SystemProgram.createAccount({fromPubkey:wallet.publicKey,newAccountPubkey:k.publicKey,space:MINT_SIZE,
    lamports:await provider.connection.getMinimumBalanceForRentExemption(MINT_SIZE),programId:TOKEN_PROGRAM_ID}),createInitializeMint2Instruction(k.publicKey,decimals,wallet.publicKey,null)],[k]);return k.publicKey;
}
async function pay(h:PublicKey,w:number,leaf:any){
  const person=new PublicKey(leaf.person),recipient=new PublicKey(leaf.recipient),dest=getAssociatedTokenAddressSync(mint,recipient);
  await send(createAssociatedTokenAccountIdempotentInstruction(wallet.publicKey,dest,recipient,mint));
  const before=(await getAccount(provider.connection,dest,'processed')).amount,set=setKey(h,w);
  await send(program.methods.claimStage1(leaf.index,person,bn(leaf.amount),leaf.proof.map((n:any)=>({hash:[...Buffer.from(n.hash,'hex')],sum:bn(n.sum)})),claimTerms(program,set)).accounts({city:city(),asset:asset(),claimSet:set,registration:pda('s1v1_recipient',person.toBuffer()),earnings:earnings(),destination:dest,tokenProgram:TOKEN_PROGRAM_ID}));
  expect((await getAccount(provider.connection,dest,'processed')).amount-before).eq(BigInt(leaf.amount));await audit();
}

if(process.env.STAGE1_DEPLOYABLE==='1'&&!testMintBuild)describe('default build USDC identity on LOCAL validator',()=>{
  it('refuses a caller-chosen six-decimal mint without creating a cash registry or asset',async()=>{
    expect(['127.0.0.1','localhost']).include(new URL(provider.connection.rpcEndpoint).hostname);
    try{
      if(!await provider.connection.getAccountInfo(config())){
        const executable=(await provider.connection.getAccountInfo(program.programId))!;
        await send(program.methods.initializeProgramConfig(wallet.publicKey).accounts({programConfig:config(),program:program.programId,programData:new PublicKey(executable.data.subarray(4,36)),admin:wallet.publicKey,systemProgram:SystemProgram.programId}));
      }
      await send(SystemProgram.transfer({fromPubkey:wallet.publicKey,toPubkey:guardian.publicKey,lamports:100_000_000}));
    const clean=await capture(provider.connection,program.programId,[wallet.publicKey,guardian.publicKey]);
      for(const [key,a] of clean)if((a.owner.equals(program.programId)&&key!==config().toBase58())||a.owner.equals(TOKEN_PROGRAM_ID))clean.delete(key);
      await move(LAUNCH+100,clean);
      await send(program.methods.initCityConfig(bn(LAUNCH)).accounts({city:city(),programConfig:config(),admin:wallet.publicKey,systemProgram:SystemProgram.programId}));
      mint=await makeMint();await reject(send(register(mint)),'Stage1InvalidAsset');
      expect(await provider.connection.getAccountInfo(cash(),'processed')).eq(null);
      expect(await provider.connection.getAccountInfo(asset(),'processed')).eq(null);
    }finally{await active?.stop();provider=originalProvider;program=originalProgram;anchor.setProvider(provider);}
  });
});

if(enabled)describe('stage 1 sponsor USDC and boosts, real tokens on LOCAL validator',()=>{
  before(async()=>{
    expect(['127.0.0.1','localhost']).include(new URL(provider.connection.rpcEndpoint).hostname);
    if(!await provider.connection.getAccountInfo(config())){
      const executable=(await provider.connection.getAccountInfo(program.programId))!;
      await send(program.methods.initializeProgramConfig(wallet.publicKey).accounts({programConfig:config(),program:program.programId,programData:new PublicKey(executable.data.subarray(4,36)),admin:wallet.publicKey,systemProgram:SystemProgram.programId}));
    }
    await send(SystemProgram.transfer({fromPubkey:wallet.publicKey,toPubkey:guardian.publicKey,lamports:100_000_000}));
    const clean=await capture(provider.connection,program.programId,[wallet.publicKey,guardian.publicKey]);
    for(const [key,a] of clean)if((a.owner.equals(program.programId)&&key!==config().toBase58())||a.owner.equals(TOKEN_PROGRAM_ID))clean.delete(key);
    await move(LAUNCH+100,clean);
    await send(program.methods.initCityConfig(bn(LAUNCH)).accounts({city:city(),programConfig:config(),admin:wallet.publicKey,systemProgram:SystemProgram.programId}));
    await send(SystemProgram.transfer({fromPubkey:wallet.publicKey,toPubkey:publisher.publicKey,lamports:2_000_000_000}));
    await send(program.methods.setStage1Publisher(publisher.publicKey).accounts({city:city(),programConfig:config(),admin:wallet.publicKey}));
    for(const p of people){await send(SystemProgram.transfer({fromPubkey:wallet.publicKey,toPubkey:p.publicKey,lamports:100_000_000}));
      await send(program.methods.registerStage1Recipient(p.publicKey).accounts({registration:pda('s1v1_recipient',p.publicKey.toBuffer()),person:p.publicKey,payer:wallet.publicKey,systemProgram:SystemProgram.programId}),[p]);}
    const wrongDecimals=await makeMint(9);await reject(send(register(wrongDecimals)),'Stage1InvalidAsset');
    if(testMintBuild) mint=await makeMint();
    else {
      // Explicit synthetic SPL mint/inventory fixture at the canonical USDC key.
      // This exercises default-binary identity/transfer checks; it is not a Circle capture.
      mint=new PublicKey('EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v');
      const data=Buffer.alloc(MINT_SIZE);
      MintLayout.encode({mintAuthorityOption:1,mintAuthority:wallet.publicKey,supply:0n,decimals:6,
        isInitialized:true,freezeAuthorityOption:0,freezeAuthority:PublicKey.default},data);
      const state=await capture(provider.connection,program.programId,[wallet.publicKey,publisher.publicKey,guardian.publicKey,...people.map(p=>p.publicKey)]);
      state.set(mint.toBase58(),{owner:TOKEN_PROGRAM_ID,data,executable:false,lamports:await provider.connection.getMinimumBalanceForRentExemption(MINT_SIZE),rentEpoch:0});
      await move(LAUNCH+100,state);
    }
    source=getAssociatedTokenAddressSync(mint,wallet.publicKey);
    await send([createAssociatedTokenAccountIdempotentInstruction(wallet.publicKey,source,wallet.publicKey,mint),createMintToInstruction(mint,source,wallet.publicKey,1_000_000_000n)]);
    await send(register(mint));
    await send(program.methods.setStage1Guardian(guardian.publicKey).accounts({city:city(),programConfig:config(),admin:wallet.publicKey}));baseline=await saved();
  });
  after(async()=>{await active?.stop();provider=originalProvider;program=originalProgram;anchor.setProvider(provider);});
  beforeEach(async()=>{await move(LAUNCH+100,baseline);});

  it('pins the build-appropriate USDC identity, labels it, and never enables principal intake',async()=>{
    const c=await program.account.stage1CashConfig.fetch(cash());expect(c.isTest).eq(testMintBuild);expect(c.mint.equals(mint)).eq(true);
    await reject(send(register(await makeMint())));
    await reject(send(program.methods.configureAsset(true).accounts({city:city(),asset:asset(),mint,earnings:earnings(),programConfig:config(),admin:wallet.publicKey,tokenProgram:TOKEN_PROGRAM_ID,systemProgram:SystemProgram.programId,rent:SYSVAR_RENT_PUBKEY})),'Stage1InvalidAsset');
    const a=await program.account.stage1AssetConfig.fetch(asset());expect(a.enabled).eq(false);expect(a.adapter).eq(254);await audit();
  });
  it('guardian intake pause refuses sponsor and boost transfers, then resumes both',async()=>{
    const h=await hill('guardian-intake');await send(open(h,0));const id=hash('guardian-boost');
    const pauseIx=program.methods.pauseStage1Intake().accounts({city:city(),guardian:guardian.publicKey});
    await send(pauseIx,[guardian]);
    const keys=[asset(),earnings(),source,funding(h,0),boost(id),stream(id,h)],before=await bytes(keys);
    await reject(send(sponsor(h,0,101)),'Stage1IntakePaused');
    await reject(send(post(id,[h],1_000_000)),'Stage1IntakePaused');
    expect(await bytes(keys)).deep.eq(before);
    await send(program.methods.resumeStage1Intake().accounts({city:city(),programConfig:config(),admin:guardian.publicKey}),[guardian]);
    await send(sponsor(h,0,101));await send(post(id,[h],1_000_000));
    expect((await audit()).admittedCashLifetime.toString()).eq('1000101');
  });
  it('admits only received cash on a registered unbonded hill and rolls back invalid transfers',async()=>{
    const h=await hill('receipt');await send(open(h,0));
    const keys=[asset(),earnings(),source,funding(h,0)],before=await bytes(keys);
    await reject(send(sponsor(h,0,0)),'Stage1InvalidFunding');expect(await bytes(keys)).deep.eq(before);
    await reject(send(sponsor(h,0,1_000_000_001)));expect(await bytes(keys)).deep.eq(before);
    await reject(send(sponsor(h,0,1,{funder:publisher.publicKey}),[publisher]), 'ConstraintTokenOwner');
    await send(sponsor(h,0,101));expect((await audit()).admittedCashLifetime.toString()).eq('101');
    expect((await program.account.stage1HillBond.fetch(h)).bonded).eq(false);
    await move(LAUNCH-1000);await reject(send(sponsor(h,0,1)),'Stage1NotLaunched');
  });
  for(const kind of ['cash','boost'])for(const n of [0,1,4,5])trace(`${kind}-${n}`);
  for(const name of ['retry','expire','grace-before','grace-at','late-five','coalesce','window-end','window-start','age-seven','coalesce-retry','coalesce-expire','quiet-boost'])trace(name);
  function trace(name:string){it(`matches independent oracle, pays and balances every step: ${name}`,async()=>{
    const h=await hill(name),oracle=JSON.parse(execFileSync(PYTHON,['-m','tools.stage1_reference.sponsor_vectors','--stdin'],{cwd:ROOT,encoding:'utf8',input:JSON.stringify({case:name,deployment:program.programId.toBase58(),city:city().toBase58(),hill:h.toBase58(),mint:mint.toBase58(),people:people.map(p=>p.publicKey.toBase58()),recipients:people.map(p=>p.publicKey.toBase58())})}));
    const ids:Buffer[]=oracle.amounts.map((_:any,i:number)=>hash(`${name}-${i}`));
    if(oracle.cash){await send(open(h,0));await send(sponsor(h,0,oracle.amounts[0]));}
    else for(let i=0;i<ids.length;i++){await send(post(ids[i],[h],oracle.amounts[i],oracle.start,oracle.duration));await audit();}
    for(const s of oracle.steps){
      await move(LAUNCH+(Math.max(s.week,s.refused??0)+1)*W+86400+10);
      if(s.skip){
        const keys=[asset(),earnings(),...ids.map(id=>stream(id,h))],before=await bytes(keys);
        if(s.refused!==null)await reject(send(skip(h,s.refused,s.start),[publisher]),s.refused===13?'Stage1SkipBoostDue':'Stage1SkipHoldMaturity');
        await send(skip(h,s.week,s.start),[publisher]);await audit();expect(await bytes(keys)).deep.eq(before);
        expect((await program.account.stage1SettlementCursor.fetch(cursor(h))).nextWeek.toNumber()).eq(s.week+1);
        continue;
      }
      if(name==='quiet-boost')await reject(send(skip(h,s.week),[publisher]),s.week<=14?'Stage1SkipBoostDue':'Stage1SkipHoldMaturity');
      await send(open(h,s.week));
      await send(freeze(h,s.week,s),[publisher]);
      for(let i=0;i<(oracle.cash?0:ids.length);i++){
        const old=await program.account.stage1BoostHill.fetch(stream(ids[i],h));if(old.retired)continue;
        await reject(send(publish(h,s.week,s),[publisher]),'Stage1WeekNotFinalizable');
        if(name==='expire'&&s.week===2){
          const keys=[stream(ids[i],h),cursor(h),asset(),funding(h,s.week)],before=await bytes(keys);
          await reject(send(processStream(h,s.week,ids[i],Array.from({length:13},()=>[0,0,0,0,0])),[publisher]),'Stage1InvalidHold');
          expect(await bytes(keys)).deep.eq(before);
        }
        if(name==='boost-5'&&s.week===1){
          const guardian=Keypair.generate(),admin={city:city(),programConfig:config(),admin:wallet.publicKey};
          await send(program.methods.setStage1Guardian(guardian.publicKey).accounts(admin));
          const keys=[stream(ids[i],h),cursor(h),asset(),earnings(),funding(h,s.week)],before=await bytes(keys);
          await send(program.methods.pauseStage1Settlement().accounts({city:city(),guardian:guardian.publicKey}),[guardian]);
          await reject(send(processStream(h,s.week,ids[i],s.streams[i]),[publisher]),'Stage1SettlementPaused');
          expect(await bytes(keys)).deep.eq(before);
          await send(program.methods.resumeStage1Settlement().accounts(admin));
        }
        await send(processStream(h,s.week,ids[i],s.streams[i]),[publisher]);await audit();
        await reject(send(processStream(h,s.week,ids[i],s.streams[i]),[publisher]),'Stage1InvalidHold');
        expect((await program.account.stage1BoostHill.fetch(stream(ids[i],h))).pool.toString()).eq(String(s.pools[i]));
      }
      if(!oracle.cash&&BigInt(s.total)>0n){
        const keys=[asset(),cursor(h),funding(h,s.week),setKey(h,s.week)],before=await bytes(keys);
        await reject(send(publish(h,s.week,{...s,total:String(BigInt(s.total)+1n)}),[publisher]));
        expect(await bytes(keys)).deep.eq(before);
      }
      await send(publish(h,s.week,s,s.sponsor_holds[String(s.week)]?.buckets),[publisher]);
      let l=await audit();for(const [field,k] of [['paid','paid'],['claimable','claimable'],['held','held'],['earnings','custody'],['admittedCashLifetime','cash']])expect(l[field].toString(),`${name} week ${s.week} ${field}`).eq(String(s.before_claims[k]));
      for(const leaf of s.leaves)await pay(h,s.week,leaf);
      l=await audit();expect(l.paid.toString()).eq(String(s.after_claims.paid));expect(s.dung).eq(0);
    }
    if(name==='expire'||name==='coalesce-expire'){
      const before=await bytes([asset(),earnings()]);await move(LAUNCH+29*W+86400+10);
      await send(skip(h,28),[publisher]);expect(await bytes([asset(),earnings()])).deep.eq(before);
      expect((await program.account.stage1SettlementCursor.fetch(cursor(h))).nextWeek.toNumber()).eq(29);
    }
  });}
  it('rejects duplicate IDs, duplicate hills, nonfuture starts and invalid duration atomically',async()=>{
    const h=await hill('invalid'),id=hash('unique'),keys=[asset(),earnings(),source,cursor(h)],before=await bytes(keys);
    for(const weeks of [0,14])await reject(send(post(id,[h],14_000_000,1,weeks)),'Stage1InvalidFunding');
    for(const start of [0,14,1000])await reject(send(post(id,[h],1_000_000,start)),'Stage1BoostStartHorizon');
    await reject(send(post(id,[h],999_999)),'Stage1BoostTrancheMinimum');
    expect(await bytes(keys)).deep.eq(before);
    await reject(send(post(id,[cash()],1_000_000)),'Stage1InvalidHill');expect(await bytes(keys)).deep.eq(before);
    await reject(send(post(id,[h,h],2_000_000)),'Stage1InvalidHill');expect(await bytes(keys)).deep.eq(before);
    await send(post(id,[h],1_000_000));const received=await bytes(keys);await reject(send(post(id,[h],1_000_000)));expect(await bytes(keys)).deep.eq(received);await audit();
  });
  it('cannot spend a future tranche or reuse a post-freeze stream for the frozen count',async()=>{
    const h=await hill('future'),id=hash('future'),late=hash('late');await send(post(id,[h],13_000_000,13,13));
    await move(LAUNCH+W+86400+10);await send(open(h,0));const s=empty(h,0);await send(freeze(h,0,s),[publisher]);
    await send(post(late,[h],1_000_000,2,1));const one=await program.account.stage1BoostHill.fetch(stream(id,h));
    const held=one.holds.map((a:any)=>a.map((v:any)=>Number(v.toString()))),bad=held.map((a:any)=>[...a]);bad[0][0]--;
    const keys=[stream(id,h),cursor(h),funding(h,0),asset()],before=await bytes(keys);
    await reject(send(processStream(h,0,id,bad),[publisher]),'Stage1InvalidHold');expect(await bytes(keys)).deep.eq(before);
    const newer=await program.account.stage1BoostHill.fetch(stream(late,h));await reject(send(processStream(h,0,late,newer.holds),[publisher]),'Stage1InvalidHold');
    await send(processStream(h,0,id,held),[publisher]);await send(publish(h,0,s),[publisher]);
    const c=await program.account.stage1SettlementCursor.fetch(cursor(h));expect(c.futureCash.toString()).eq('14000000');expect(c.nextBoostDueWeek.toNumber()).eq(2);expect(c.cashHolds.every((v:any)=>v.isZero())).eq(true);await audit();
  });
  it('lets two funders use the same published ID and refuses reuse within one funder',async()=>{
    const h=await hill('funder-ids'),id=hash('published-id'),other=people[0];
    const otherSource=getAssociatedTokenAddressSync(mint,other.publicKey);
    await send([createAssociatedTokenAccountIdempotentInstruction(wallet.publicKey,otherSource,other.publicKey,mint),
      createMintToInstruction(mint,otherSource,wallet.publicKey,2_000_000)]);
    await send(post(id,[h],1_000_000));
    await send(post(id,[h],1_000_000,1,1,other.publicKey,otherSource),[other]);
    expect(boost(id).equals(boost(id,other.publicKey))).eq(false);
    expect((await program.account.stage1Boost.fetch(boost(id,other.publicKey))).funder.equals(other.publicKey)).eq(true);
    const keys=[asset(),cursor(h),source,otherSource],before=await bytes(keys);
    await reject(send(post(id,[h],1_000_000,1,1,other.publicKey,otherSource),[other]));
    expect(await bytes(keys)).deep.eq(before);await audit();
  });
  it('matches hill UTF-8/week Hamilton dust for multiple hills',async()=>{
    const hills=[await hill('dust-a'),await hill('dust-b')].sort((a,b)=>Buffer.compare(Buffer.from(a.toBase58()),Buffer.from(b.toBase58()))),id=hash('dust');
    const keys=[asset(),earnings(),source,...hills.map(cursor)],before=await bytes(keys);
    await reject(send(post(id,hills,5_999_999,1,3)),'Stage1BoostTrancheMinimum');
    expect(await bytes(keys)).deep.eq(before);expect(await provider.connection.getAccountInfo(boost(id),'processed')).eq(null);
    await send(post(id,hills,6_000_005,1,3));
    const a=await program.account.stage1BoostHill.fetch(stream(id,hills[0])),b=await program.account.stage1BoostHill.fetch(stream(id,hills[1]));
    expect(a.scheduled.slice(0,3).map((v:any)=>v.toNumber())).deep.eq([1000001,1000001,1000001]);expect(b.scheduled.slice(0,3).map((v:any)=>v.toNumber())).deep.eq([1000001,1000001,1000000]);await audit();
  });
  it('posts the maximum 16 hills atomically with a rooted lookup table and refuses 17',async()=>{
    const hills:PublicKey[]=[];for(let i=0;i<17;i++)hills.push(await hill(`max-${i}`));
    hills.sort((a,b)=>Buffer.compare(Buffer.from(a.toBase58()),Buffer.from(b.toBase58())));
    const id=hash('max16'),other=hash('max17'),builder=post(id,hills.slice(0,16),208_000_001,1,13),refused=post(other,hills,208_000_001,1,13);
    const ixs=await Promise.all([builder.instruction(),refused.instruction()]);
    const addresses=[...new Map(ixs.flatMap(ix=>ix.keys).filter(k=>!k.isSigner).map(k=>[k.pubkey.toBase58(),k.pubkey])).values()];
    const history=(await provider.connection.getAccountInfo(SYSVAR_SLOT_HASHES_PUBKEY,'processed'))!;
    const [create,table]=AddressLookupTableProgram.createLookupTable({authority:wallet.publicKey,payer:wallet.publicKey,recentSlot:Number(history.data.readBigUInt64LE(8))});await send(create);
    for(let i=0;i<addresses.length;i+=20)await send(AddressLookupTableProgram.extendLookupTable({authority:wallet.publicKey,payer:wallet.publicKey,lookupTable:table,addresses:addresses.slice(i,i+20)}));
    let lookup:any;for(let i=0;i<300;i++){lookup=(await provider.connection.getAddressLookupTable(table,{commitment:'finalized'})).value;
      if(lookup?.state.addresses.length===addresses.length&&await provider.connection.getSlot('finalized')>lookup.state.lastExtendedSlot)break;await pause(100);}
    expect(lookup?.state.addresses.length).eq(addresses.length);
    const signature=await send(builder,[],[lookup]);
    let receipt:any;for(let i=0;i<200;i++){
      receipt=await provider.connection.getTransaction(signature,{commitment:'confirmed',maxSupportedTransactionVersion:0});
      if(receipt)break;await pause(50);
    }
    expect(receipt?.meta?.computeUnitsConsumed).to.be.lessThan(1_000_000);
    console.log(`    16 hills × 13 weeks: ${receipt.meta.computeUnitsConsumed} CU (1,000,000 requested)`);
    const posted=await program.account.stage1Boost.fetch(boost(id));expect(posted.hills.length).eq(16);expect(posted.total.toNumber()).eq(208_000_001);
    let total=0;for(const h of hills.slice(0,16)){const row=await program.account.stage1BoostHill.fetch(stream(id,h));total+=row.scheduled.reduce((s:number,n:any)=>s+n.toNumber(),0);}
    expect(total).eq(208_000_001);const before=await bytes([asset(),earnings(),source]);
    await reject(send(refused,[],[lookup]),'Stage1InvalidHill');expect(await bytes([asset(),earnings(),source])).deep.eq(before);await audit();
  });
});
