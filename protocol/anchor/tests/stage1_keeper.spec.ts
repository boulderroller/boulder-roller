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
import { createInitializeMint2Instruction, createMintToInstruction, createAssociatedTokenAccountIdempotentInstruction,
  getAssociatedTokenAddressSync, getAccount, MINT_SIZE, TOKEN_PROGRAM_ID } from '@solana/spl-token';
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
    if(s){expect(s.err,JSON.stringify(s.err)).to.equal(null);return;}await pause(50);}
  throw new Error('local setup transaction missing');
}
async function move(at:number){
  previousGenesis=await provider.connection.getGenesisHash();
  const captured=await capture(provider.connection,program.programId,[wallet.publicKey,...(active?[publisher,...people].map(k=>k.publicKey):[]),...lookupTables]);
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
    timeout:300000,env:{...process.env,PYTHONPATH:`${process.env.PYTHONPATH??''}:${resolve(ROOT,'backend')}`}});
  return JSON.parse(output);
}

if(process.env.STAGE1_LOCALNET==='1'&&OUT)describe('weekly keeper through PostgreSQL on LOCALNET',()=>{
  before(async()=>{
    if(!await provider.connection.getAccountInfo(config())){
      const executable=(await provider.connection.getAccountInfo(program.programId))!;
      await send(program.methods.initializeProgramConfig(wallet.publicKey).accounts({programConfig:config(),program:program.programId,
        programData:new PublicKey(executable.data.subarray(4,36)),admin:wallet.publicKey,systemProgram:SystemProgram.programId}));
    }
    await move(LAUNCH+100);
    await send(program.methods.initCityConfig(bn(LAUNCH)).accounts({city:city(),programConfig:config(),admin:wallet.publicKey,systemProgram:SystemProgram.programId}));
    for(const p of [publisher,...people])await send(SystemProgram.transfer({fromPubkey:wallet.publicKey,toPubkey:p.publicKey,lamports:1_000_000_000}));
    writeFileSync(`${OUT}/keeper-publisher.json`,JSON.stringify([...publisher.secretKey]),{mode:0o600});
    await send(program.methods.setStage1Publisher(publisher.publicKey).accounts({city:city(),programConfig:config(),admin:wallet.publicKey}));
    for(const p of people.slice(2))await send(program.methods.registerStage1Recipient(p.publicKey).accounts({
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
  let latest:any,claimable:any,claimWeek=0;
  for(const week of Array.from({length:28},(_,i)=>i))it(`publishes and reconciles week ${week} through the actual keeper`,async()=>{
    if(week===20){
      const person=people[0];
      await send(program.methods.registerStage1Recipient(person.publicKey).accounts({registration:pda('s1v1_recipient',person.publicKey.toBuffer()),person:person.publicKey,systemProgram:SystemProgram.programId}),[person]);
    }
    // Week 0 lets the keeper initialize and skip. Week 2 and later unfunded
    // weeks must open/publish because attributed holds still exist.
    if(week===1 || (week>=3 && week<=19)){
      await send(program.methods.openStage1Week(bn(week)).accounts({city:city(),hillAccount:{hill:hill()},asset:asset(),funding:funding(week),payer:wallet.publicKey,systemProgram:SystemProgram.programId,cursor:cursor()}));
      await send(program.methods.setTestLstRate(bn(2),bn(1),bn(await clock())).accounts({city:city(),asset:asset(),programConfig:config(),admin:wallet.publicKey}));
      await send(program.methods.harvestStage1(bn(1000)).accounts({city:city(),hill:hill(),asset:asset(),lot:lot(),
        custody:pda('s1v1_custody',lot().toBuffer()),ownerReserve:pda('s1v1_owner',lot().toBuffer()),earnings:earnings(),tokenProgram:TOKEN_PROGRAM_ID})
        .remainingAccounts([{pubkey:funding(week),isSigner:false,isWritable:true}]));
    }
    await move(LAUNCH+(week+1)*W+86400+100);
    const slot=await provider.connection.getSlot('finalized');
    // These boundary facts are explicit test attestations. They are not a
    // claim that a current account read can reconstruct historical live/boards.
    const evidence=hash(`synthetic-boundary-${week}`).toString('hex');
    const riding=week===1 || week===20;
    const request={initialize:week===0,week,people:riding?people.map(p=>p.publicKey.toBase58()):[],
      opening:{boundary:LAUNCH+week*W,live:week===1 || week>=20,commitment:'finalized',slot,evidence,evidence_class:'synthetic localnet boundary attestation'},
      closing:{boundary:LAUNCH+(week+1)*W,commitment:'finalized',slot,evidence,board:riding?people.map(p=>({person:p.publicKey.toBase58(),time_s:60,recorded_at:LAUNCH+100})):[],
        legend:riding?{person:people[0].publicKey.toBase58(),active:true,bootstrap:false,term_start:LAUNCH,term_end:LAUNCH+29*W}:null,assets:[mint.toBase58()],evidence_class:'synthetic localnet boundary attestation'}};
    if(week===3){
      const pending=bridge({...request,stop_after_publish_submit:true});
      await provider.connection.confirmTransaction(pending.pending_signature,'finalized');
      const set=await program.account.stage1ClaimSet.fetch(claimSet(week));
      expect(set.leafCount).eq(0);
      await send(program.methods.closeStage1ClaimSet().accounts({claimSet:claimSet(week),rentPayer:set.rentPayer}));
      const book=await program.account.stage1WeekFunding.fetch(funding(week));
      await send(program.methods.closeStage1WeekFunding().accounts({funding:funding(week),cursor:cursor(),asset:asset(),earnings:earnings(),claimSet:claimSet(week),rentPayer:book.rentPayer}));
      // Keeper has not captured the publication yet. Another caller's canonical
      // close must recover from its persisted pre-submit witness and event.
    }
    latest=bridge(request);
    const kinds=latest.operations.map((o:any)=>o.kind);
    if(week===0){expect(kinds).to.deep.equal(['init','skip']);}
    else if(week!==3){
      const set=await program.account.stage1ClaimSet.fetch(claimSet(week));
      expect(Buffer.from(set.root).toString('hex')).to.equal(latest.claims.root);
      expect(set.total.toString()).to.equal(String(latest.claims.total));
      expect(kinds).not.to.include('skip');
    }
    if(week===2)expect(kinds).to.include('open');
    if(week===1){expect(Object.keys(latest.allocation.reserved[funding(1).toBase58()])).to.have.length(2);}
    if(week===20){
      expect(kinds).to.include('lookup');
      lookupTables.push(new PublicKey(latest.lookup_address));
      claimWeek=20;claimable=latest;
    }
    if(week===27){expect(kinds).to.include('expire');expect(latest.allocation.pool[funding(1).toBase58()]).to.be.greaterThan(0);}
    expect((await program.account.stage1SettlementCursor.fetch(cursor())).nextWeek.toNumber()).to.equal(week+1);
    const exported=JSON.parse(readFileSync(`${OUT}/proofs/${latest.job}.json`,'utf8'));
    expect(exported.claims).to.deep.equal(latest.claims);
    if(week===1||week===3){
      const paid=bridge({week,payout:true});
      expect(paid.transitions.blocked??0,JSON.stringify(paid.transitions)).eq(0);
      expect(paid.failed_actions).eq(0);
      expect(await provider.connection.getAccountInfo(funding(week),'finalized')).eq(null);
      expect((await program.account.stage1SettlementCursor.fetch(cursor())).carriedHolds.length).greaterThan(0);
    }
  });
  it('automatically pays retained proofs, creates ATAs and closes paid sets',async()=>{
    const result=bridge({week:27,payout:true});
    expect(result.unpaid_leaves).eq(0);
    expect(result.failed_actions).eq(0);
    expect(result.closed_sets).eq(27);
    expect(result.transitions.blocked??0,JSON.stringify(result.transitions)).eq(0);
    for(let week=1;week<=27;week++)expect(await provider.connection.getAccountInfo(funding(week),'finalized')).eq(null);
    expect(result.costs.every((w:any)=>w.refundable_deposits_lamports===w.retained_lookup_deposits_lamports)).eq(true);
    const audit=bridge({week:27,audit:true});
    expect(audit.ledger.paid).greaterThan(0);
    for(const person of people.slice(2)){
      expect((await getAccount(provider.connection,getAssociatedTokenAddressSync(mint,person.publicKey),'finalized')).amount > 0n).eq(true);
    }
    writeFileSync(`${OUT}/localnet-outcome.json`,JSON.stringify({evidence:'synthetic rides and boundaries; actual localnet funding/publication/automatic claims and closure',
      weeks:28,result,ledger:audit.ledger,slot:audit.slot},null,2));
  });
});
