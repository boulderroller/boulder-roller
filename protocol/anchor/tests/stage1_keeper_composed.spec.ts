// Evidence: synthetic database rides/boundary attestations, REAL local custody,
// publication and claim transactions. Replay time is not elapsed-world evidence.
import * as anchor from '@coral-xyz/anchor';
import BN from 'bn.js';
import { expect } from 'chai';
import { createHash } from 'crypto';
import { execFileSync } from 'child_process';
import { fileURLToPath } from 'url';
import { resolve } from 'path';
import { writeFileSync, readFileSync } from 'fs';
import { Keypair, PublicKey, SYSVAR_CLOCK_PUBKEY, SYSVAR_RENT_PUBKEY, SystemProgram,
  ComputeBudgetProgram, TransactionMessage, VersionedTransaction } from '@solana/web3.js';
import { createInitializeMint2Instruction, createMintToInstruction, createAssociatedTokenAccountIdempotentInstruction, createBurnInstruction, createCloseAccountInstruction,
  getAssociatedTokenAddressSync, getAccount, createFreezeAccountInstruction, createThawAccountInstruction, getMint, MINT_SIZE, TOKEN_PROGRAM_ID } from '@solana/spl-token';
import { capture, replay, pause } from './helpers/stage1_replay.js';
import { Operator } from '../scripts/stage1_operator.js';

const ROOT=resolve(fileURLToPath(new URL('../../..',import.meta.url)));
const PYTHON=process.env.STAGE1_KEEPER_PYTHON??'python3';
const OUT=process.env.STAGE1_KEEPER_EVIDENCE!;
const LAUNCH=1791201600,W=604800;
const bn=(x:any)=>new BN(String(x));
const hash=(x:Buffer|string)=>createHash('sha256').update(x).digest();
let provider=anchor.AnchorProvider.env();
anchor.setProvider(provider);
let program:any=anchor.workspace.BoulderRollers;
const original=program, wallet=provider.wallet as anchor.Wallet;
const guardian=Keypair.generate(),unregistered=Keypair.generate();
const publisher=Keypair.generate(), people=Array.from({length:5},()=>Keypair.generate());
const mintKey=Keypair.generate(), mint=mintKey.publicKey;
const canon=hash('keeper-canon').subarray(0,16);
const canonId=[canon.subarray(0,4),canon.subarray(4,6),canon.subarray(6,8),canon.subarray(8,10),canon.subarray(10)].map(b=>b.toString('hex')).join('-');
const pda=(seed:string,...parts:Buffer[])=>PublicKey.findProgramAddressSync([Buffer.from(seed),...parts],program.programId)[0];
const u64=(n:number)=>bn(n).toArrayLike(Buffer,'le',8);
const city=()=>pda('s1v1_city'),config=()=>pda('program_config'),hill=()=>pda('s1v1_hill',canon);
const asset=()=>pda('s1v1_asset',mint.toBuffer()),earnings=()=>pda('s1v1_earnings',mint.toBuffer());
const cursor=()=>pda('s1v1_cursor',hill().toBuffer(),mint.toBuffer());
const funding=(w:number)=>pda('s1v1_funding',hill().toBuffer(),mint.toBuffer(),u64(w));
const claimSet=(w:number)=>pda('s1v1_claims',hill().toBuffer(),mint.toBuffer(),u64(w));
const lot=()=>pda('s1v1_lot',wallet.publicKey.toBuffer(),u64(1));
let active:Awaited<ReturnType<typeof replay>>|undefined;
let replayEpoch=0;
let previousGenesis:string|undefined;
const lookupTables:PublicKey[]=[];
const clock=async()=>Number((await provider.connection.getAccountInfo(SYSVAR_CLOCK_PUBKEY,'processed'))!.data.readBigInt64LE(32));
async function send(builders:any,signers:Keypair[]=[]){
  const list=Array.isArray(builders)?builders:[builders];
  const ixs=await Promise.all(list.map(x=>x.instruction?x.instruction():x));
  const latest=await provider.connection.getLatestBlockhash('processed');
  const tx=new VersionedTransaction(new TransactionMessage({payerKey:wallet.publicKey,recentBlockhash:latest.blockhash,
    instructions:[ComputeBudgetProgram.setComputeUnitLimit({units:1400000}),...ixs]}).compileToLegacyMessage());
  tx.sign([wallet.payer,...signers]);
  const signature=await provider.connection.sendRawTransaction(tx.serialize(),{preflightCommitment:'processed'});
  for(let i=0;i<250;i++){const s=(await provider.connection.getSignatureStatuses([signature])).value[0];
    if(s){expect(s.err,JSON.stringify(s.err)).to.equal(null);return signature;}await pause(50);}
  throw new Error('local setup transaction missing');
}
async function move(at:number){
  previousGenesis=await provider.connection.getGenesisHash();
  const captured=await capture(provider.connection,program.programId,[wallet.publicKey,...(active?[publisher,guardian,unregistered,...people].map(k=>k.publicKey):[]),...lookupTables]);
  // Keep finalized slot floors increasing across the synthetic-clock replay.
  replayEpoch=Math.max(replayEpoch+1,Math.ceil((await provider.connection.getSlot('processed'))/256)+1);
  await active?.stop();active=await replay(captured,at,false,replayEpoch,8);
  provider=new anchor.AnchorProvider(active.connection,wallet,{commitment:'processed',preflightCommitment:'processed'});
  program=new anchor.Program(original.idl,original.programId,provider);
  while(await provider.connection.getSlot('finalized')<40)await pause(100);
}
function bridge(input:any){
  const request={rpc:provider.connection.rpcEndpoint,program:program.programId.toBase58(),hill:hill().toBase58(),mint:mint.toBase58(),
    canon_id:canonId,publisher_path:`${OUT}/keeper-publisher.json`,export_dir:`${OUT}/proofs`,previous_genesis:previousGenesis,people:people.map(p=>p.publicKey.toBase58()),...input};
  const output=execFileSync(PYTHON,['-m','tests.services.stage1_keeper_localnet'],{cwd:resolve(ROOT,'backend'),input:JSON.stringify(request),encoding:'utf8',
    timeout:input.lookup_probe?900000:300000,env:{...process.env,PYTHONPATH:`${process.env.PYTHONPATH??''}:${resolve(ROOT,'backend')}`}});
  return JSON.parse(output);
}

if(process.env.STAGE1_LOCALNET==='1'&&OUT)describe('composed keeper on LOCALNET',()=>{
  before(async()=>{
    if(!await provider.connection.getAccountInfo(config())){
      const executable=(await provider.connection.getAccountInfo(program.programId))!;
      await send(program.methods.initializeProgramConfig(wallet.publicKey).accounts({programConfig:config(),program:program.programId,
        programData:new PublicKey(executable.data.subarray(4,36)),admin:wallet.publicKey,systemProgram:SystemProgram.programId}));
    }
    await move(LAUNCH+100);
    await send(program.methods.initCityConfig(bn(LAUNCH)).accounts({city:city(),programConfig:config(),admin:wallet.publicKey,systemProgram:SystemProgram.programId}));
    for(const p of [publisher,unregistered,...people])await send(SystemProgram.transfer({fromPubkey:wallet.publicKey,toPubkey:p.publicKey,lamports:1_000_000_000}));
    writeFileSync(`${OUT}/keeper-publisher.json`,JSON.stringify([...publisher.secretKey]),{mode:0o600});
    await send(program.methods.setStage1Publisher(publisher.publicKey).accounts({city:city(),programConfig:config(),admin:wallet.publicKey}));
    for(const p of people)await send(program.methods.registerStage1Recipient(p.publicKey).accounts({
      registration:pda('s1v1_recipient',p.publicKey.toBuffer()),person:p.publicKey,systemProgram:SystemProgram.programId}),[p]);
    await send([SystemProgram.createAccount({fromPubkey:wallet.publicKey,newAccountPubkey:mint,space:MINT_SIZE,
      lamports:await provider.connection.getMinimumBalanceForRentExemption(MINT_SIZE),programId:TOKEN_PROGRAM_ID}),
      createInitializeMint2Instruction(mint,9,wallet.publicKey,null)],[mintKey]);
    const source=getAssociatedTokenAddressSync(mint,wallet.publicKey);
    await send([createAssociatedTokenAccountIdempotentInstruction(wallet.publicKey,source,wallet.publicKey,mint),
      createMintToInstruction(mint,source,wallet.publicKey,20_000_000_000n)]);
    await send(program.methods.configureAsset(true).accounts({city:city(),asset:asset(),mint,earnings:earnings(),programConfig:config(),admin:wallet.publicKey,
      tokenProgram:TOKEN_PROGRAM_ID,systemProgram:SystemProgram.programId,rent:SYSVAR_RENT_PUBKEY}));
    await send(program.methods.setTestLstRate(bn(1),bn(1),bn(await clock())).accounts({city:city(),asset:asset(),programConfig:config(),admin:wallet.publicKey}));
    const profile=hash('keeper-profile'),commitment=Buffer.alloc(64);commitment[0]=1;canon.copy(commitment,1);commitment.writeUInt16BE(1,17);profile.copy(commitment,32);
    const digest=hash(commitment),climb=pda('climb',digest);
    await send(program.methods.registerRatifiedClimb({canonId:[...canon],canonVersion:1,canonicalProfileHash:[...profile],commitmentHash:[...digest],
      recordContinuityPolicy:{newRecordBoard:{}},name:'Keeper local hill',vertM:1000,distanceM:2000,avgGradientPct:500})
      .accounts({climb,climbVersionIndex:pda('climb_version',canon,Buffer.from([0,1])),predecessorClimb:null,programConfig:config(),admin:wallet.publicKey,systemProgram:SystemProgram.programId}));
    await send(program.methods.initHillBond().accounts({city:city(),climb,hill:hill(),programConfig:config(),admin:wallet.publicKey,systemProgram:SystemProgram.programId}));
    await send(program.methods.bond(bn(1),bn(10_000_000_000n),0).accounts({city:city(),hillAccount:{hill:hill()},climb,asset:asset(),mint,lot:lot(),
      custody:pda('s1v1_custody',lot().toBuffer()),ownerReserve:pda('s1v1_owner',lot().toBuffer()),source,owner:wallet.publicKey,
      tokenProgram:TOKEN_PROGRAM_ID,systemProgram:SystemProgram.programId,rent:SYSVAR_RENT_PUBKEY}));
    const operator=new Operator({'rpc':provider.connection.rpcEndpoint,'cluster':'localnet','program-id':program.programId.toBase58(),
      'admin':wallet.publicKey.toBase58(),'fee-payer':publisher.publicKey.toBase58()});
    await operator.start(); // 1c explicit network, version and authority guard.
  });
  after(async()=>{await active?.stop();});

  let cashMint:PublicKey,dungMint:PublicKey,cashResult:any,dungResult:any;
  const cashAsset=()=>pda('s1v1_asset',cashMint.toBuffer());
  const cashCursor=()=>pda('s1v1_cursor',hill().toBuffer(),cashMint.toBuffer());
  const cashFunding=(w:number)=>pda('s1v1_funding',hill().toBuffer(),cashMint.toBuffer(),u64(w));
  const cashEarnings=()=>pda('s1v1_earnings',cashMint.toBuffer());
  const dung=(w:number)=>pda('s1v1_dung',hill().toBuffer(),u64(w));
  const dungSet=(w:number,r:number)=>pda('s1v1_dung_claims',dung(w).toBuffer(),Buffer.from([r]));
  function normal(v:any):any{
    if(v instanceof PublicKey)return v.toBase58();
    if(BN.isBN(v))return v.toNumber();
    if(Array.isArray(v))return v.map(normal);
    if(v&&typeof v==='object')return Object.fromEntries(Object.entries(v).map(([k,x])=>[k.replace(/[A-Z]/g,c=>'_'+c.toLowerCase()),normal(x)]));
    return v;
  }
  async function boundary(week:number,riding=true){
    const slot=await provider.connection.getSlot('finalized'),evidence=hash(`synthetic-composed-${week}`).toString('hex');
    const h=normal(await program.account.stage1HillBond.fetch(hill()));
    const l={...normal(await program.account.stage1PledgeLot.fetch(lot())),address:lot().toBase58()};
    return {opening:{boundary:LAUNCH+week*W,live:week>0,commitment:'finalized',slot,evidence,
      evidence_class:'synthetic historical boundary attestation',dung:{hill:h,lots:[l],rates:{[mint.toBase58()]:{
        numerator:1,denominator:1,boundary:LAUNCH+week*W,slot,evidence,mint:mint.toBase58(),city:city().toBase58(),asset:asset().toBase58()}}}},
      closing:{boundary:LAUNCH+(week+1)*W,commitment:'finalized',slot,evidence,assets:[mint.toBase58(),cashMint.toBase58()],
        board:riding?people.map(p=>({person:p.publicKey.toBase58(),time_s:60,recorded_at:LAUNCH+100})):[],
        legend:riding?{person:people[0].publicKey.toBase58(),active:true,bootstrap:false,term_start:LAUNCH,term_end:LAUNCH+10*W}:null}};
  }
  before(async()=>{
    await send(SystemProgram.transfer({fromPubkey:wallet.publicKey,toPubkey:guardian.publicKey,lamports:100_000_000}));
    await send(program.methods.setStage1Guardian(guardian.publicKey).accounts({city:city(),programConfig:config(),admin:wallet.publicKey}));
    await send(program.methods.registerStage1Recipient(wallet.publicKey).accounts({registration:pda('s1v1_recipient',wallet.publicKey.toBuffer()),person:wallet.publicKey,payer:wallet.publicKey,systemProgram:SystemProgram.programId}));
    async function make(decimals:number,authority:PublicKey){
      const k=Keypair.generate();
      await send([SystemProgram.createAccount({fromPubkey:wallet.publicKey,newAccountPubkey:k.publicKey,space:MINT_SIZE,
        lamports:await provider.connection.getMinimumBalanceForRentExemption(MINT_SIZE),programId:TOKEN_PROGRAM_ID}),
        createInitializeMint2Instruction(k.publicKey,decimals,authority,wallet.publicKey)],[k]);
      return k.publicKey;
    }
    cashMint=await make(6,wallet.publicKey);dungMint=await make(9,pda('dung_mint_auth'));
    await send(program.methods.registerStage1Cash().accounts({city:city(),cash:pda('s1v1_cash'),asset:cashAsset(),mint:cashMint,earnings:cashEarnings(),
      programConfig:config(),admin:wallet.publicKey,tokenProgram:TOKEN_PROGRAM_ID,systemProgram:SystemProgram.programId}));
    await send(program.methods.configureMints(mint,dungMint).accounts({programConfig:config(),admin:wallet.publicKey}));
    await send(program.methods.configureStage1Dung(bn(20_000_000_000),bn(1)).accounts({city:city(),programConfig:config(),admin:wallet.publicKey}));
    await send(program.methods.initStage1Settlement().accounts({city:city(),hillAccount:{hill:hill()},asset:cashAsset(),cursor:cashCursor(),payer:wallet.publicKey,systemProgram:SystemProgram.programId}));
    const source=getAssociatedTokenAddressSync(cashMint,wallet.publicKey),id=hash('keeper-composed-boost');
    const boost=pda('s1v1_boost',wallet.publicKey.toBuffer(),id),stream=pda('s1v1_boost_hill',boost.toBuffer(),hill().toBuffer());
    await send([createAssociatedTokenAccountIdempotentInstruction(wallet.publicKey,source,wallet.publicKey,cashMint),createMintToInstruction(cashMint,source,wallet.publicKey,10_000_000n)]);
    await send(program.methods.postStage1Boost([...id],bn(1_000_000),bn(1),1).accounts({city:city(),cash:pda('s1v1_cash'),asset:cashAsset(),boost,
      earnings:cashEarnings(),source,funder:wallet.publicKey,tokenProgram:TOKEN_PROGRAM_ID,systemProgram:SystemProgram.programId})
      .remainingAccounts([{pubkey:hill(),isSigner:false,isWritable:false},{pubkey:cashCursor(),isSigner:false,isWritable:true},{pubkey:stream,isSigner:false,isWritable:true}]));
  });
  it('retains future boost escrow and admits powered canonical sources',async()=>{
    await move(LAUNCH+W+86400+100);
    const boundaries=await boundary(0,false);
    bridge({initialize:true,powered_wallets:[...people,unregistered].map(p=>p.publicKey.toBase58()),week:0,people:[],...boundaries});
    const result=bridge({mint:cashMint.toBase58(),week:0,people:[],...boundaries});
    expect(result.operations.map((o:any)=>o.kind)).include('boost');
    expect(result.claims.total).eq(0);
  });
  it('publishes sponsor cash plus boost and both DUNG roles through the keeper',async()=>{
    await send(program.methods.openStage1Week(bn(1)).accounts({city:city(),hillAccount:{hill:hill()},asset:cashAsset(),funding:cashFunding(1),payer:wallet.publicKey,systemProgram:SystemProgram.programId,cursor:cashCursor()}));
    await send(program.methods.sponsorStage1(bn(1_000_000)).accounts({city:city(),cash:pda('s1v1_cash'),asset:cashAsset(),funding:cashFunding(1),cursor:cashCursor(),
      earnings:cashEarnings(),source:getAssociatedTokenAddressSync(cashMint,wallet.publicKey),funder:wallet.publicKey,tokenProgram:TOKEN_PROGRAM_ID}));
    await move(LAUNCH+2*W+86400+100);
    const boundaries=await boundary(1);
    cashResult=bridge({mint:cashMint.toBase58(),week:1,powered:true,...boundaries});
    expect(cashResult.claims.total).eq(2_000_000);
    dungResult=bridge({mint:dungMint.toBase58(),week:1,powered:true,...boundaries});
    expect(dungResult.allocation.potential).eq(8_333_330);
    expect(dungResult.claims.roles.every((r:any)=>r.total>0)).eq(true);
    const before=bridge({mint:dungMint.toBase58(),week:1,payout:true});
    expect(before.unpaid_leaves).greaterThan(0);
    expect((await getMint(provider.connection,dungMint,'finalized')).supply).eq(0n);
  });
  it('waits without terminal leaves when publisher and ATA sponsor run out of SOL',async()=>{
    const balance=await provider.connection.getBalance(publisher.publicKey,'finalized');
    await provider.connection.confirmTransaction(await send(SystemProgram.transfer({fromPubkey:publisher.publicKey,toPubkey:wallet.publicKey,lamports:balance}),[publisher]),'finalized');
    const waiting=bridge({mint:cashMint.toBase58(),week:1,payout:true});
    expect(waiting.failed_actions).eq(0);expect(waiting.unpaid_leaves).greaterThan(0);
    expect(waiting.alerts.some((a:any)=>a.kind==='sponsor_unfunded')).eq(true);
    expect(waiting.rpc_calls.sendTransaction??0).eq(0);
    await provider.connection.confirmTransaction(await send(SystemProgram.transfer({fromPubkey:wallet.publicKey,toPubkey:publisher.publicKey,lamports:balance})),'finalized');
    await pause(31_000); // Real retry backoff; do not alter database clocks.
  });
  it('pays cash during both pauses and waits before paying mature DUNG',async()=>{
    await send(program.methods.pauseStage1Intake().accounts({city:city(),guardian:guardian.publicKey}),[guardian]);
    await send(program.methods.pauseStage1Settlement().accounts({city:city(),guardian:guardian.publicKey}),[guardian]);
    const paid=bridge({mint:cashMint.toBase58(),week:1,payout:true});
    expect(paid.unpaid_leaves).eq(0);expect(paid.failed_actions).eq(0);
    expect(await provider.connection.getAccountInfo(cashFunding(1),'finalized')).eq(null);
    const sets=await Promise.all([0,1].map(r=>program.account.stage1DungClaimSet.fetch(dungSet(1,r))));
    await move(Math.max(...sets.map(s=>s.publishedAt.toNumber()))+172800+100);
    const waiting=bridge({mint:dungMint.toBase58(),week:1,payout:true});
    expect(waiting.alerts.some((a:any)=>a.kind==='settlement_paused')).eq(true);
    expect((await getMint(provider.connection,dungMint,'finalized')).supply).eq(0n);
  });
  it('isolates a frozen destination while paying other riders and the backer',async()=>{
    await provider.connection.confirmTransaction(await send(program.methods.resumeStage1Settlement().accounts({city:city(),programConfig:config(),admin:guardian.publicKey}),[guardian]),'finalized');
    await pause(31_000); // Resume after the persisted settlement-pause backoff.
    const victim=people[0].publicKey,ata=getAssociatedTokenAddressSync(dungMint,victim);
    await provider.connection.confirmTransaction(await send([createAssociatedTokenAccountIdempotentInstruction(wallet.publicKey,ata,victim,dungMint),createFreezeAccountInstruction(ata,dungMint,wallet.publicKey)]),'finalized');
    const result=bridge({mint:dungMint.toBase58(),week:1,payout:true});
    expect(result.unpaid_leaves,JSON.stringify(result.transitions)).eq(1);expect(result.failed_actions).eq(1);
    for(const role of dungResult.claims.roles)for(const leaf of role.leaves){
      const balance=(await getAccount(provider.connection,getAssociatedTokenAddressSync(dungMint,new PublicKey(leaf.recipient)),'finalized')).amount;
      expect(balance).eq(leaf.person===victim.toBase58()?0n:BigInt(leaf.amount));
    }
    const again=bridge({mint:dungMint.toBase58(),week:1,payout:true});
    expect(again.failed_actions).eq(1);expect(again.transitions.submitted??0).eq(0);
    expect(await provider.connection.getAccountInfo(dungSet(1,0),'finalized')).not.eq(null);
    writeFileSync(`${OUT}/composed-outcome.json`,JSON.stringify({evidence:'synthetic rides and archived boundaries; actual localnet sponsor, boost, DUNG, pause and automatic payout',cash:cashResult.allocation,dung:dungResult.allocation,result},null,2));
  });
  it('pays registered DUNG, preserves unminted shares, and leaves a reclaimed ATA for self-claim',async()=>{
    // Fund cash while week 2 is still open, before replay advances its clock.
    await provider.connection.confirmTransaction(await send(program.methods.resumeStage1Intake().accounts({city:city(),programConfig:config(),admin:guardian.publicKey}),[guardian]),'finalized');
    await send(program.methods.openStage1Week(bn(2)).accounts({city:city(),hillAccount:{hill:hill()},asset:cashAsset(),funding:cashFunding(2),payer:wallet.publicKey,systemProgram:SystemProgram.programId,cursor:cashCursor()}));
    await send(program.methods.sponsorStage1(bn(1_000_000)).accounts({city:city(),cash:pda('s1v1_cash'),asset:cashAsset(),funding:cashFunding(2),cursor:cashCursor(),
      earnings:cashEarnings(),source:getAssociatedTokenAddressSync(cashMint,wallet.publicKey),funder:wallet.publicKey,tokenProgram:TOKEN_PROGRAM_ID}));
    await provider.connection.confirmTransaction(await send(createThawAccountInstruction(getAssociatedTokenAddressSync(dungMint,people[0].publicKey),dungMint,wallet.publicKey)),'finalized');
    const owner=people[1],ata=getAssociatedTokenAddressSync(dungMint,owner.publicKey);
    const previous=(await getAccount(provider.connection,ata,'finalized')).amount;
    await provider.connection.confirmTransaction(await send([createBurnInstruction(ata,dungMint,owner.publicKey,previous),
      createCloseAccountInstruction(ata,owner.publicKey,owner.publicKey)],[owner]),'finalized');
    await move(LAUNCH+3*W+86400+100);
    expect(await provider.connection.getAccountInfo(pda('s1v1_recipient',unregistered.publicKey.toBuffer()),'finalized')).eq(null);
    const boundaries=await boundary(2);
    const result=bridge({mint:dungMint.toBase58(),week:2,people:[...people,unregistered].map(p=>p.publicKey.toBase58()),powered:true,...boundaries});
    expect(result.claims.roles.every((r:any)=>r.total>0)).eq(true);
    expect(result.allocation.unminted).greaterThan(0);
    expect(result.claims.leaves.some((l:any)=>l.person===unregistered.publicKey.toBase58())).eq(false);
    const record=await program.account.stage1DungMint.fetch(dung(2));
    expect(record.unminted.toNumber()).eq(result.allocation.unminted);
    expect(record.roleTotals.reduce((n:number,x:BN)=>n+x.toNumber(),0)+record.unminted.toNumber()).eq(result.allocation.potential);
    // Registration after publication cannot change this frozen allocation.
    await send(program.methods.registerStage1Recipient(unregistered.publicKey).accounts({registration:pda('s1v1_recipient',unregistered.publicKey.toBuffer()),person:unregistered.publicKey,systemProgram:SystemProgram.programId}),[unregistered]);
    const sets=await Promise.all([0,1].map(r=>program.account.stage1DungClaimSet.fetch(dungSet(2,r))));
    await move(Math.max(...sets.map(s=>s.publishedAt.toNumber()))+172800+100);
    const paid=bridge({mint:dungMint.toBase58(),week:2,payout:true});
    expect(paid.transitions.blocked??0,JSON.stringify(paid.transitions)).eq(0);
    expect(paid.unpaid_leaves,JSON.stringify(paid.transitions)).eq(2);expect(paid.failed_actions).eq(2);
    expect(await provider.connection.getAccountInfo(ata,'finalized')).eq(null);
    expect(await provider.connection.getAccountInfo(dungSet(2,0),'finalized')).not.eq(null);
    expect(await provider.connection.getAccountInfo(dungSet(2,1),'finalized')).eq(null);
    const again=bridge({mint:dungMint.toBase58(),week:2,payout:true});
    expect(again.sponsorships).eq(paid.sponsorships);expect(again.alerts).deep.eq(paid.alerts);
    // Cash for this same person still pays automatically in its other mint.
    const cashBefore=(await getAccount(provider.connection,getAssociatedTokenAddressSync(cashMint,owner.publicKey),'finalized')).amount;
    bridge({mint:cashMint.toBase58(),week:2,people:[...people,unregistered].map(p=>p.publicKey.toBase58()),powered:true,...boundaries});
    const cashPaid=bridge({mint:cashMint.toBase58(),week:2,payout:true});
    expect(cashPaid.failed_actions).eq(0);
    expect((await getAccount(provider.connection,getAssociatedTokenAddressSync(cashMint,owner.publicKey),'finalized')).amount>cashBefore).eq(true);
    const leaf=result.claims.roles[0].leaves.find((l:any)=>l.person===owner.publicKey.toBase58());
    await provider.connection.confirmTransaction(await send([
      createAssociatedTokenAccountIdempotentInstruction(owner.publicKey,ata,owner.publicKey,dungMint),
      program.methods.claimStage1Dung(leaf.index,owner.publicKey,bn(leaf.amount),leaf.proof.map((p:any)=>({hash:[...Buffer.from(p.hash,'hex')],sum:bn(p.sum)})))
        .accounts({city:city(),dung:dung(2),claimSet:dungSet(2,0),state:pda('s1v1_dung_state'),registration:pda('s1v1_recipient',owner.publicKey.toBuffer()),
          destination:ata,mint:dungMint,programConfig:config(),dungMintAuth:pda('dung_mint_auth'),tokenProgram:TOKEN_PROGRAM_ID})
    ],[owner]),'finalized');
    const closed=bridge({mint:dungMint.toBase58(),week:2,payout:true});
    expect(closed.unpaid_leaves).eq(1);
    for(const key of [dungSet(2,0),dungSet(2,1),dung(2)])expect(await provider.connection.getAccountInfo(key,'finalized')).eq(null);
    expect(closed.costs.find((w:any)=>w.week===2).refundable_deposits_lamports).eq(0);
    expect(closed.costs.every((w:any)=>w.retained_lookup_deposits_lamports===0)).eq(true);
    const outcome=JSON.parse(readFileSync(`${OUT}/composed-outcome.json`,'utf8'));
    writeFileSync(`${OUT}/composed-outcome.json`,JSON.stringify({...outcome,mixed_registration:result.allocation,reclaimed_destination:paid,other_asset:cashPaid,self_claim_and_close:closed},null,2));
  });
  it('deactivates a fallback lookup table, waits for cooldown and recovers every lamport',async()=>{
    // Exercise the rare transport lifecycle independently of ordinary claims,
    // which the preceding assertions prove need no table at these proof sizes.
    const result=bridge({mint:dungMint.toBase58(),week:1,payout:true,lookup_probe:people.map(p=>p.publicKey.toBase58())});
    expect(result.lookup_tables.length).eq(1);
    const table=result.lookup_tables[0];
    expect(table.closed).eq(true);expect(Number(table.deposited_lamports)).greaterThan(0);
    expect(Number(result.lookup_refunds)).eq(Number(table.deposited_lamports));
    expect(await provider.connection.getAccountInfo(new PublicKey(table.address),'finalized')).eq(null);
    expect(result.costs.every((w:any)=>w.retained_lookup_deposits_lamports===0)).eq(true);
    const outcome=JSON.parse(readFileSync(`${OUT}/composed-outcome.json`,'utf8'));
    writeFileSync(`${OUT}/composed-outcome.json`,JSON.stringify({...outcome,lookup_cleanup:result},null,2));
  });
});
