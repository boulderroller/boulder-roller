// Real localnet boundary->archive->keeper->payout. Ride DB rows are synthetic.
import * as anchor from '@coral-xyz/anchor';
import BN from 'bn.js';
import { expect } from 'chai';
import { createHash } from 'crypto';
import { createRequire } from 'module';
import { execFileSync } from 'child_process';
import { fileURLToPath } from 'url';
import { resolve } from 'path';
import { writeFileSync,readFileSync } from 'fs';
import { Keypair,PublicKey,SystemProgram,SYSVAR_CLOCK_PUBKEY,SYSVAR_RENT_PUBKEY,ComputeBudgetProgram,TransactionMessage,VersionedTransaction } from '@solana/web3.js';
import { MINT_SIZE,TOKEN_PROGRAM_ID,createInitializeMint2Instruction,createAssociatedTokenAccountIdempotentInstruction,createMintToInstruction,getAssociatedTokenAddressSync,getAccount } from '@solana/spl-token';
import { capture,replay,pause } from './helpers/stage1_replay.js';

const ROOT=resolve(fileURLToPath(new URL('../../..',import.meta.url))), OUT=process.env.STAGE1_KEEPER_EVIDENCE!;
const require=createRequire(import.meta.url);
const LAUNCH=1790596800,W=604800,OPEN=LAUNCH+W,CLOSE=OPEN+W;
const bn=(x:any)=>new BN(String(x)),hash=(x:string|Buffer)=>createHash('sha256').update(x).digest();
let provider=anchor.AnchorProvider.env();const wallet=provider.wallet as anchor.Wallet;
const idl=JSON.parse(readFileSync(process.env.STAGE1_INDEXER_IDL??resolve(ROOT,'protocol/anchor/idl/boulder_rollers.json'),'utf8'));
let program:any=new anchor.Program(idl,new PublicKey('5TU6hcKXiVt3Lttw7VLu4Jq18FeAgiURk5WxBVYAGGYt'),provider);
const people=Array.from({length:5},()=>Keypair.generate()),publisher=Keypair.generate(),lst=Keypair.generate(),cash=Keypair.generate();
const canon=hash('indexer-local-canon').subarray(0,16),profile=hash('indexer-local-profile');
const canonId=[canon.subarray(0,4),canon.subarray(4,6),canon.subarray(6,8),canon.subarray(8,10),canon.subarray(10)].map(b=>b.toString('hex')).join('-');
const pda=(seed:string,...parts:Buffer[])=>PublicKey.findProgramAddressSync([Buffer.from(seed),...parts],program.programId)[0];
const city=()=>pda('s1v1_city'),config=()=>pda('program_config'),hill=()=>pda('s1v1_hill',canon),asset=(mint:PublicKey)=>pda('s1v1_asset',mint.toBuffer());
const earnings=(mint:PublicKey)=>pda('s1v1_earnings',mint.toBuffer()),cursor=()=>pda('s1v1_cursor',hill().toBuffer(),cash.publicKey.toBuffer());
const funding=(week=1)=>pda('s1v1_funding',hill().toBuffer(),cash.publicKey.toBuffer(),bn(week).toArrayLike(Buffer,'le',8));
const cal=Keypair.generate(),dung=Keypair.generate();
const u64=(n:any)=>bn(n).toArrayLike(Buffer,'le',8);
const [tieLow,tieHigh]=people.slice(0,2).sort((a,b)=>Buffer.compare(a.publicKey.toBuffer(),b.publicKey.toBuffer()));
let vaultId:BN,vault:PublicKey,board:PublicKey,legend:PublicKey,activation:PublicKey,tieAt:number;
function rideIx(rider:PublicKey,label:string,at:number,earned:BN=bn(0)) {
  const rideHash=hash(label),att=pda('ride_attestation',rider.toBuffer(),rideHash);
  return {att,ix:program.methods.recordRide([...rideHash],[...hash(label+':evidence')],1,1,bn(at),bn(at-3600),Math.max(250,earned.div(bn(1_000_000_000)).toNumber()),42000,900,earned,1).accounts({rideAttestation:att,riderSoul:pda('rider_soul',rider.toBuffer()),rider,programConfig:config(),authority:wallet.publicKey,payer:wallet.publicKey,systemProgram:SystemProgram.programId})};
}
async function complete(rider:PublicKey,label:string,timeS:number,at:number) {
  const {att,ix}=rideIx(rider,label,at),time=Buffer.alloc(4);time.writeUInt32LE(timeS);
  const evidence=hash(Buffer.concat([Buffer.from('BR_CLIMB_COMPLETION_V2'),att.toBuffer(),vault.toBuffer(),time,u64(0)]));
  return send([ix,program.methods.recordClimbCompletionV2(timeS,bn(0),[...evidence]).accounts({rideAttestation:att,climbCompletionReceipt:pda('climb_completion_receipt',att.toBuffer(),vault.toBuffer()),vault,vaultCompletion:pda('vault_completion',rider.toBuffer(),u64(vaultId)),vaultLeaderboard:board,vaultActivation:activation,rider,programConfig:config(),authority:wallet.publicKey,systemProgram:SystemProgram.programId}).remainingAccounts([{pubkey:pda('ride_tribute_budget',att.toBuffer()),isWritable:true,isSigner:false}])]);
}
let active:Awaited<ReturnType<typeof replay>>|undefined;
const clock=async()=>Number((await provider.connection.getAccountInfo(SYSVAR_CLOCK_PUBKEY,'finalized'))!.data.readBigInt64LE(32));
async function send(builders:any,signers:Keypair[]=[]){
  const list=Array.isArray(builders)?builders:[builders],ixs=await Promise.all(list.map(x=>x.instruction?x.instruction():x));
  const latest=await provider.connection.getLatestBlockhash('processed');
  const tx=new VersionedTransaction(new TransactionMessage({payerKey:wallet.publicKey,recentBlockhash:latest.blockhash,instructions:[ComputeBudgetProgram.setComputeUnitLimit({units:1400000}),...ixs]}).compileToLegacyMessage());
  tx.sign([wallet.payer,...signers]);
  const sig=await provider.connection.sendRawTransaction(tx.serialize(),{preflightCommitment:'processed'});
  for(let i=0;i<300;i++){const row=(await provider.connection.getSignatureStatuses([sig])).value[0];if(row?.err)throw new Error(JSON.stringify(row.err));if(row?.confirmationStatus==='finalized')return sig;await pause(100);}
  throw new Error('setup signature not finalized');
}
async function bootstrap(at:number,epochLength?:number){
  const accounts=await capture(provider.connection,program.programId,[wallet.publicKey,...(active?[publisher,...people].map(p=>p.publicKey):[])]);
  await active?.stop();active=await replay(accounts,at,false,undefined,epochLength?64:8,epochLength);
  provider=new anchor.AnchorProvider(active.connection,wallet,{commitment:'finalized',preflightCommitment:'processed'});
  program=new anchor.Program(idl,program.programId,provider);
  for(let i=0;i<200 && await provider.connection.getSlot('finalized')<33;i++)await pause(100);
}
function bridge(action:string,extra:any={}){
  const request={action,rpc:provider.connection.rpcEndpoint,program:program.programId.toBase58(),hill:hill().toBase58(),mint:cash.publicKey.toBase58(),canon_id:canonId,
    publisher_path:`${OUT}/publisher.json`,export_dir:`${OUT}/proofs`,boundary_export_dir:`${OUT}/boundaries`,people:people.map(p=>p.publicKey.toBase58()),...extra};
  return JSON.parse(execFileSync(process.env.STAGE1_KEEPER_PYTHON!,['-m','tests.services.stage1_indexer_localnet'],{cwd:resolve(ROOT,'backend'),input:JSON.stringify(request),encoding:'utf8',timeout:300000,env:{...process.env,PYTHONPATH:ROOT+':'+resolve(ROOT,'backend')}}));
}
async function sweep(polls=2){
  process.env.SOLANA_RPC_URL=provider.connection.rpcEndpoint;process.env.PROGRAM_ID=program.programId.toBase58();process.env.IDL_PATH=process.env.STAGE1_INDEXER_IDL;
  const {programVersionWindow}=require(resolve(ROOT,'indexer/dist/program-version-window.js'));programVersionWindow.observe(0x4d);
  const {runStage1Replay}=require(resolve(ROOT,'indexer/dist/stage1.js'));
  const {finalizedHeads,boundaryClock}=require(resolve(ROOT,'indexer/dist/finalized-head.js'));
  const poll=async()=>{
    const previous=finalizedHeads.peek(provider.connection);
    if(previous)await pause(Math.max(0,30001-(Date.now()-previous.sampledAt)));
    // Drive only scheduling from the real accelerated localnet Clock. All
    // witnesses still use real finalized RPC banks and their block times.
    const scheduled=await clock();boundaryClock.now=()=>scheduled;
    return runStage1Replay(provider.connection);
  };
  let result;
  // Ordinary scheduling uses the real 30-second head cadence. A pre-boundary
  // capture can be covered by the next post-boundary poll without waiting here.
  for(let i=0;i<polls;i++)result=await poll();
  return result;
}

if(process.env.STAGE1_LOCALNET==='1'&&OUT)describe('finalized Stage 1 indexer archive on LOCALNET',()=>{
  after(async()=>{await active?.stop();await require(resolve(ROOT,'indexer/dist/db.js')).closePool();});
  it('freezes real single-genesis boundaries, imports them, publishes and automatically pays',async()=>{
    const executable=(await provider.connection.getAccountInfo(program.programId))!;
    await send(program.methods.initializeProgramConfig(wallet.publicKey).accounts({programConfig:config(),program:program.programId,programData:new PublicKey(executable.data.subarray(4,36)),admin:wallet.publicKey,systemProgram:SystemProgram.programId}));
    await bootstrap(LAUNCH+100);
    await send(program.methods.initCityConfig(bn(LAUNCH)).accounts({city:city(),programConfig:config(),admin:wallet.publicKey,systemProgram:SystemProgram.programId}));
    for(const p of [publisher,...people])await send(SystemProgram.transfer({fromPubkey:wallet.publicKey,toPubkey:p.publicKey,lamports:1_000_000_000}));
    writeFileSync(`${OUT}/publisher.json`,JSON.stringify([...publisher.secretKey]),{mode:0o600});
    await send(program.methods.setStage1Publisher(publisher.publicKey).accounts({city:city(),programConfig:config(),admin:wallet.publicKey}));
    for(const p of people)await send(program.methods.registerStage1Recipient(p.publicKey).accounts({registration:pda('s1v1_recipient',p.publicKey.toBuffer()),person:p.publicKey,systemProgram:SystemProgram.programId}),[p]);
    for(const [mint,decimals] of [[lst,9],[cash,6]] as const){
      await send([SystemProgram.createAccount({fromPubkey:wallet.publicKey,newAccountPubkey:mint.publicKey,space:MINT_SIZE,lamports:await provider.connection.getMinimumBalanceForRentExemption(MINT_SIZE),programId:TOKEN_PROGRAM_ID}),createInitializeMint2Instruction(mint.publicKey,decimals,wallet.publicKey,null)],[mint]);
      const source=getAssociatedTokenAddressSync(mint.publicKey,wallet.publicKey);
      await send([createAssociatedTokenAccountIdempotentInstruction(wallet.publicKey,source,wallet.publicKey,mint.publicKey),createMintToInstruction(mint.publicKey,source,wallet.publicKey,20_000_000_000n)]);
    }
    for(const [mint,auth] of [[cal,pda('cal_mint_auth')],[dung,pda('dung_mint_auth')]] as const)
      await send([SystemProgram.createAccount({fromPubkey:wallet.publicKey,newAccountPubkey:mint.publicKey,space:MINT_SIZE,lamports:await provider.connection.getMinimumBalanceForRentExemption(MINT_SIZE),programId:TOKEN_PROGRAM_ID}),createInitializeMint2Instruction(mint.publicKey,9,auth,null)],[mint]);
    await send(program.methods.configureMints(cal.publicKey,dung.publicKey).accounts({programConfig:config(),admin:wallet.publicKey}));
    const cfg=await program.account.programConfig.fetch(config());
    // Explicit local test configuration: a one-week election term.
    await send(program.methods.updateProtocolParameters({vaultCreationDung:cfg.vaultCreationDung,vaultCreationCal:cfg.vaultCreationCal,harvestFeeBps:cfg.harvestFeeBps,minterRightsEpochs:cfg.minterRightsEpochs,localLegendTermEpochs:bn(1),epochsPerHalving:cfg.epochsPerHalving}).accounts({programConfig:config(),adminAuthority:wallet.publicKey}));
    const calAta=getAssociatedTokenAddressSync(cal.publicKey,wallet.publicKey),treasuryAta=getAssociatedTokenAddressSync(cash.publicKey,publisher.publicKey);
    await send([createAssociatedTokenAccountIdempotentInstruction(wallet.publicKey,calAta,wallet.publicKey,cal.publicKey),createAssociatedTokenAccountIdempotentInstruction(wallet.publicKey,treasuryAta,publisher.publicKey,cash.publicKey)]);
    await send(program.methods.configureUsdcPayment(bn(2_000_000)).accounts({programConfig:config(),admin:wallet.publicKey,usdcMint:cash.publicKey,usdcTreasuryTokenAccount:treasuryAta}));
    const creationCal=cfg.vaultCreationCal.mul(bn(1_000_000_000));
    const fundingRide=rideIx(wallet.publicKey,'indexer:creation-cal',(await clock())-1,creationCal);
    await send([fundingRide.ix,program.methods.creditCal(creationCal).accounts({rideAttestation:fundingRide.att,calMintReceipt:pda('cal_mint_receipt',fundingRide.att.toBuffer(),wallet.publicKey.toBuffer()),rider:wallet.publicKey,programConfig:config(),authority:wallet.publicKey,calMint:cal.publicKey,calMintAuth:pda('cal_mint_auth'),destination:calAta,payer:wallet.publicKey,tokenProgram:TOKEN_PROGRAM_ID,systemProgram:SystemProgram.programId})]);
    await send(program.methods.initializeVaultCounter().accounts({vaultCounter:pda('vault_counter'),authority:wallet.publicKey,systemProgram:SystemProgram.programId}));
    vaultId=(await program.account.vaultCounter.fetch(pda('vault_counter'))).count;
    vault=pda('vault',u64(vaultId));board=pda('vault_leaderboard',u64(vaultId));legend=pda('local_legend',u64(vaultId));activation=pda('vault_activation',u64(vaultId));
    await send(program.methods.configureAsset(true).accounts({city:city(),asset:asset(lst.publicKey),mint:lst.publicKey,earnings:earnings(lst.publicKey),programConfig:config(),admin:wallet.publicKey,tokenProgram:TOKEN_PROGRAM_ID,systemProgram:SystemProgram.programId,rent:SYSVAR_RENT_PUBKEY}));
    await send(program.methods.setTestLstRate(bn(1),bn(1),bn(await clock())).accounts({city:city(),asset:asset(lst.publicKey),programConfig:config(),admin:wallet.publicKey}));
    const commitment=Buffer.alloc(64);commitment[0]=1;canon.copy(commitment,1);commitment.writeUInt16BE(1,17);profile.copy(commitment,32);const digest=hash(commitment),climb=pda('climb',digest);
    await send(program.methods.registerRatifiedClimb({canonId:[...canon],canonVersion:1,canonicalProfileHash:[...profile],commitmentHash:[...digest],recordContinuityPolicy:{newRecordBoard:{}},name:'Indexer local hill',vertM:1000,distanceM:2000,avgGradientPct:500}).accounts({climb,climbVersionIndex:pda('climb_version',canon,Buffer.from([0,1])),predecessorClimb:null,programConfig:config(),admin:wallet.publicKey,systemProgram:SystemProgram.programId}));
    await send(program.methods.createVaultWithUsdc().accounts({vaultCounter:pda('vault_counter'),vault,climb,vaultLeaderboard:board,localLegend:legend,vaultActivation:activation,sponsorAuthority:wallet.publicKey,creator:wallet.publicKey,creatorCalAccount:calAta,protocolUsdcAccount:treasuryAta,tokenProgram:TOKEN_PROGRAM_ID,systemProgram:SystemProgram.programId}).remainingAccounts([{pubkey:cal.publicKey,isWritable:true,isSigner:false},{pubkey:config(),isWritable:false,isSigner:false},{pubkey:getAssociatedTokenAddressSync(cash.publicKey,wallet.publicKey),isWritable:true,isSigner:false}]));
    expect((await getAccount(provider.connection,calAta,'finalized')).amount).eq(0n);
    expect((await getAccount(provider.connection,treasuryAta,'finalized')).amount).eq(2_000_000n);
    await send(program.methods.initHillBond().accounts({city:city(),climb,hill:hill(),programConfig:config(),admin:wallet.publicKey,systemProgram:SystemProgram.programId}));
    const lot=pda('s1v1_lot',wallet.publicKey.toBuffer(),bn(1).toArrayLike(Buffer,'le',8));
    await send(program.methods.bond(bn(1),bn(10_000_000_000n),0).accounts({city:city(),hillAccount:{hill:hill()},climb,asset:asset(lst.publicKey),mint:lst.publicKey,lot,custody:pda('s1v1_custody',lot.toBuffer()),ownerReserve:pda('s1v1_owner',lot.toBuffer()),source:getAssociatedTokenAddressSync(lst.publicKey,wallet.publicKey),owner:wallet.publicKey,tokenProgram:TOKEN_PROGRAM_ID,systemProgram:SystemProgram.programId,rent:SYSVAR_RENT_PUBKEY}));
    await send(program.methods.registerStage1Cash().accounts({city:city(),cash:pda('s1v1_cash'),asset:asset(cash.publicKey),mint:cash.publicKey,earnings:earnings(cash.publicKey),programConfig:config(),admin:wallet.publicKey,tokenProgram:TOKEN_PROGRAM_ID,systemProgram:SystemProgram.programId}));
    bridge('initialize');
    await bootstrap(OPEN-360,1_000_000);
    const genesis=await provider.connection.getGenesisHash();
    await sweep();console.log('[Localnet] initial capture clock',await clock());
    tieAt=(await clock())-1;
    const completionSigs=[await complete(tieHigh.publicKey,'indexer:tie-high',1615,tieAt),await complete(tieLow.publicKey,'indexer:tie-low',1615,tieAt),await complete(tieHigh.publicKey,'indexer:legend-extra',1700,tieAt)];
    console.log('[Localnet] completed rides clock',await clock());
    expect(await clock()).lessThan(OPEN);
    const actualBoard=await program.account.vaultLeaderboard.fetch(board);
    expect(actualBoard.entries.map((e:any)=>[e.user.toBase58(),e.timeS,e.recordedAt.toNumber()])).deep.eq([tieLow,tieHigh].map(p=>[p.publicKey.toBase58(),1615,tieAt]));
    const countFor=async(p:PublicKey)=>(await program.account.vaultCompletion.fetch(pda('vault_completion',p.toBuffer(),u64(vaultId)))).completions;
    expect(await countFor(tieHigh.publicKey)).eq(2);expect(await countFor(tieLow.publicKey)).eq(1);
    for(let i=0;i<1600 && await clock()<OPEN-50;i++)await pause(100);
    await send(program.methods.setTestLstRate(bn(1),bn(1),bn(await clock())).accounts({city:city(),asset:asset(lst.publicKey),programConfig:config(),admin:wallet.publicKey}));
    expect((await program.account.stage1AssetConfig.fetch(asset(lst.publicKey))).lastFreshUntil.toNumber()).greaterThan(OPEN);
    await sweep(1);console.log('[Localnet] pre-boundary capture clock',await clock());expect(await clock()).lessThan(OPEN);
    await active!.advance(600000,OPEN+100);
    // Wait until the first warp's ordinary timestamp correction has settled.
    for(let i=0;i<200 && await clock()<CLOSE-7200;i++)await pause(200);
    expect(await clock()).lessThan(CLOSE);expect(await provider.connection.getGenesisHash()).eq(genesis);
    await sweep();const opened=bridge('produce');
    expect(opened.witnesses.find((w:any)=>w.boundary===OPEN)?.opening_live,JSON.stringify(opened)).eq(true);
    const priorLegend=await program.account.localLegend.fetch(legend);
    expect(priorLegend.isBootstrap).eq(true);expect(1704110400+priorLegend.termEndEpoch.toNumber()*W).eq(OPEN);
    await send(program.methods.electLocalLegend(2,tieLow.publicKey,1,priorLegend.termEndEpoch).accounts({vault,localLegend:legend,winner:tieHigh.publicKey,programConfig:config(),authority:wallet.publicKey,systemProgram:SystemProgram.programId}));
    const elected=await program.account.localLegend.fetch(legend);
    expect(elected.isActive).eq(true);expect(elected.isBootstrap).eq(false);expect(elected.holder.equals(tieHigh.publicKey)).eq(true);
    expect(1704110400+elected.termStartEpoch.toNumber()*W).eq(OPEN);expect(1704110400+elected.termEndEpoch.toNumber()*W).eq(CLOSE);
    await send(program.methods.initStage1Settlement().accounts({city:city(),hillAccount:{hill:hill()},asset:asset(cash.publicKey),cursor:cursor(),payer:wallet.publicKey,systemProgram:SystemProgram.programId}));
    await send(program.methods.skipStage1EmptyWeeks(bn(0)).accounts({city:city(),hill:hill(),asset:asset(cash.publicKey),cursor:cursor(),earnings:earnings(cash.publicKey),publisher:publisher.publicKey})
      .remainingAccounts([{pubkey:funding(0),isSigner:false,isWritable:false}]),[publisher]);
    await send(program.methods.openStage1Week(bn(1)).accounts({city:city(),hillAccount:{hill:hill()},asset:asset(cash.publicKey),funding:funding(),cursor:cursor(),payer:wallet.publicKey,systemProgram:SystemProgram.programId}));
    await send(program.methods.sponsorStage1(bn(1_000_000)).accounts({city:city(),cash:pda('s1v1_cash'),asset:asset(cash.publicKey),funding:funding(),cursor:cursor(),earnings:earnings(cash.publicKey),source:getAssociatedTokenAddressSync(cash.publicKey,wallet.publicKey),funder:wallet.publicKey,tokenProgram:TOKEN_PROGRAM_ID}));
    await sweep();await active!.advance(601000,CLOSE+86400+100);expect(await provider.connection.getGenesisHash()).eq(genesis);
    await sweep();const closed=bridge('produce');expect(closed.tasks.find((t:any)=>t.week===1)?.state,JSON.stringify(closed)).eq('complete');
    for(const sig of completionSigs)expect(await provider.connection.getTransaction(sig,{commitment:'finalized',maxSupportedTransactionVersion:0})).not.eq(null);
    const archived=JSON.parse(readFileSync(closed.archive,'utf8')).find((e:any)=>e.week===1&&e.inputs.context[4]===cash.publicKey.toBase58()).inputs;
    expect(archived.closing.board).deep.eq([tieLow,tieHigh].map(p=>({person:p.publicKey.toBase58(),time_s:1615,recorded_at:tieAt})));
    expect(archived.closing.legend).deep.eq({person:tieHigh.publicKey.toBase58(),active:true,bootstrap:false,term_start:OPEN,term_end:CLOSE});
    const settled=bridge('settle',{archive:closed.archive});
    const expected=Object.fromEntries(people.map(p=>[p.publicKey.toBase58(),130_000]));
    expected[tieLow.publicKey.toBase58()]+=125_000;expected[tieHigh.publicKey.toBase58()]+=225_000;
    expect(settled.allocation.payments).deep.eq(expected);expect(settled.allocation.cap).eq(390_000);
    expect(settled.claims.total).eq(1_000_000);expect(settled.claims.count).eq(5);
    expect(Object.fromEntries(settled.claims.leaves.map((l:any)=>[l.person,l.amount]))).deep.eq(expected);
    expect(Object.values(settled.allocation.holds).flat().every(n=>n===0)).eq(true);
    const paid=bridge('payout');expect(paid.unpaid_leaves,JSON.stringify(paid)).eq(0);expect(paid.failed_actions).eq(0);
    for(const leaf of settled.claims.leaves)expect((await getAccount(provider.connection,getAssociatedTokenAddressSync(cash.publicKey,new PublicKey(leaf.recipient)),'finalized')).amount).eq(BigInt(leaf.amount));
    await sweep();
    const db=require(resolve(ROOT,'indexer/dist/db.js'));
    const frozen=(await db.query('SELECT snapshot FROM stage1_keeper_jobs WHERE id=$1',[settled.job])).rows[0].snapshot;
    expect(frozen.board).deep.eq([tieLow,tieHigh].map(p=>p.publicKey.toBase58()));expect(frozen.legend).eq(tieHigh.publicKey.toBase58());expect(frozen.field).eq(true);
    const projected=await db.query('SELECT count(*)::int AS count,sum(amount)::text AS total FROM indexed_stage1_payouts');
    expect(projected.rows[0].count).eq(settled.claims.leaves.length);expect(projected.rows[0].total).eq(String(settled.claims.total));
    writeFileSync(`${OUT}/outcome.json`,JSON.stringify({evidence:'Real localnet finalized tied board, earned Legend, boundaries, publication and automatic SPL payout; synthetic ride DB rows; captured bootstrap before observation floor',genesis,opened,closed,claim_total:settled.claims.total,paid,projection:projected.rows[0]},null,2));
  });
});
