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
  getAssociatedTokenAddressSync, getAccount, MINT_SIZE, TOKEN_PROGRAM_ID, createTransferInstruction, createCloseAccountInstruction } from '@solana/spl-token';
import { capture, replay, pause } from './helpers/stage1_replay.js';
import { Operator } from '../scripts/stage1_operator.js';

const ROOT=resolve(fileURLToPath(new URL('../../..',import.meta.url)));
const PYTHON=process.env.STAGE1_KEEPER_PYTHON??'python3';
const OUT=process.env.STAGE1_KEEPER_EVIDENCE!;
const PRIVATE=resolve(process.env.ANCHOR_WALLET!,'..');
const operations:any[]=[];
const LAUNCH=1791201600,W=604800;
const bn=(x:any)=>new BN(String(x));
const hash=(x:Buffer|string)=>createHash('sha256').update(x).digest();
let provider=anchor.AnchorProvider.env();
anchor.setProvider(provider);
const idl=JSON.parse(readFileSync(process.env.STAGE1_TX_IDL!,'utf8'));
let program:any=new anchor.Program(idl,new PublicKey('5TU6hcKXiVt3Lttw7VLu4Jq18FeAgiURk5WxBVYAGGYt'),provider);
const original=program, wallet=provider.wallet as anchor.Wallet;
const backer=Keypair.generate();
const publisher=Keypair.generate(), people=Array.from({length:5},()=>Keypair.generate());
// Synthetic local mint account at the release-pinned cash address; no client
// mint/provider identity is changed to make the firewall accept these bytes.
const mint=new PublicKey('DpLPBaRuLnBsR3P3meU1tmiNUxreXwskXBebTYKvNGne');
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
  for(let i=0;i<1200;i++){const s=(await provider.connection.getSignatureStatuses([signature])).value[0];
    if(s?.confirmationStatus==='finalized'){expect(s.err,JSON.stringify(s.err)).to.equal(null);return;}await pause(50);}
  throw new Error('local setup transaction missing');
}
async function move(at:number){
  previousGenesis=await provider.connection.getGenesisHash();
  const captured=await capture(provider.connection,program.programId,[wallet.publicKey,...await Promise.all([publisher,backer,...people].map(async k=>await provider.connection.getAccountInfo(k.publicKey)?k.publicKey:null)).then(keys=>keys.filter((k):k is PublicKey=>k!==null)),...lookupTables]);
  // Keep finalized slot floors increasing across the synthetic-clock replay.
  replayEpoch=Math.max(replayEpoch+1,Math.ceil((await provider.connection.getSlot('processed'))/256)+1);
  await active?.stop();active=await replay(captured,at,false,replayEpoch,8);
  provider=new anchor.AnchorProvider(active.connection,wallet,{commitment:'processed',preflightCommitment:'processed'});
  program=new anchor.Program(original.idl,original.programId,provider);
  while(await provider.connection.getSlot('finalized')<40)await pause(100);
}
function bridge(input:any){
  const request={rpc:provider.connection.rpcEndpoint,program:program.programId.toBase58(),hill:hill().toBase58(),mint:mint.toBase58(),
    canon_id:canonId,publisher_path:`${PRIVATE}/keeper-publisher.json`,export_dir:`${OUT}/proofs`,previous_genesis:previousGenesis,people:people.map(p=>p.publicKey.toBase58()),...input};
  const output=execFileSync(PYTHON,['-m','tests.services.stage1_keeper_localnet'],{cwd:resolve(ROOT,'backend'),input:JSON.stringify(request),encoding:'utf8',
    timeout:300000,env:{...process.env,PYTHONPATH:`${ROOT}:${resolve(ROOT,'backend')}`}});
  return JSON.parse(output);
}

function action(name:string,signer:Keypair,extra:any={}){
  const signers=[publisher,backer,...people];
  const request={rpc:provider.connection.rpcEndpoint,program:program.programId.toBase58(),payer_path:process.env.ANCHOR_WALLET,
    signer_path:`${PRIVATE}/signer-${signers.indexOf(signer)}.json`,action:name,...extra};
  const out=JSON.parse(execFileSync(PYTHON,['-m','tests.services.stage1_transactions_localnet'],{cwd:resolve(ROOT,'backend'),
    input:JSON.stringify(request),encoding:'utf8',timeout:300000,env:{...process.env,PYTHONPATH:`${ROOT}:${resolve(ROOT,'backend')}`}}));
  if(out.operation){expect(out.read.recorded).eq(true);operations.push({action:name,...out.operation,client_checks:out.client_checks,rpc_requests:out.rpc_requests});}
  return out;
}
async function publish(week:number){
  await move(LAUNCH+(week+1)*W+86400+100);
  const slot=await provider.connection.getSlot('finalized'),riding=week>0,evidence=hash(`transaction-boundary-${week}`).toString('hex');
  return bridge({week,people:riding?people.map(p=>p.publicKey.toBase58()):[],
    opening:{boundary:LAUNCH+week*W,live:riding,commitment:'finalized',slot,evidence,evidence_class:'synthetic localnet boundary attestation'},
    closing:{boundary:LAUNCH+(week+1)*W,commitment:'finalized',slot,evidence,board:riding?people.map(p=>({person:p.publicKey.toBase58(),time_s:60,recorded_at:LAUNCH+100})):[],
      legend:riding?{person:people[0].publicKey.toBase58(),active:true,bootstrap:false,term_start:LAUNCH,term_end:LAUNCH+29*W}:null,
      assets:[mint.toBase58()],evidence_class:'synthetic localnet boundary attestation'}});
}
async function income(week:number){
  await send(program.methods.openStage1Week(bn(week)).accounts({city:city(),hillAccount:{hill:hill()},asset:asset(),funding:funding(week),payer:wallet.publicKey,systemProgram:SystemProgram.programId,cursor:cursor()}));
  await send(program.methods.setTestLstRate(bn(2),bn(1),bn(await clock())).accounts({city:city(),asset:asset(),programConfig:config(),admin:wallet.publicKey}));
  await send(program.methods.harvestStage1(bn(1000)).accounts({city:city(),hill:hill(),asset:asset(),lot:lot(),custody:pda('s1v1_custody',lot().toBuffer()),
    ownerReserve:pda('s1v1_owner',lot().toBuffer()),earnings:earnings(),tokenProgram:TOKEN_PROGRAM_ID}).remainingAccounts([{pubkey:funding(week),isSigner:false,isWritable:true}]));
}
if(process.env.STAGE1_LOCALNET==='1'&&OUT)describe('owner transactions through HTTP and keeper on LOCALNET',()=>{
  before(async()=>{
    if(!await provider.connection.getAccountInfo(config())){
      const executable=(await provider.connection.getAccountInfo(program.programId))!;
      await send(program.methods.initializeProgramConfig(wallet.publicKey).accounts({programConfig:config(),program:program.programId,
        programData:new PublicKey(executable.data.subarray(4,36)),admin:wallet.publicKey,systemProgram:SystemProgram.programId}));
    }
    await move(LAUNCH+100);
    await send(program.methods.initCityConfig(bn(LAUNCH)).accounts({city:city(),programConfig:config(),admin:wallet.publicKey,systemProgram:SystemProgram.programId}));
    for(const p of [publisher,backer])await send(SystemProgram.transfer({fromPubkey:wallet.publicKey,toPubkey:p.publicKey,lamports:1_000_000_000}));
    for(const [i,p] of [publisher,backer,...people].entries())writeFileSync(`${PRIVATE}/signer-${i}.json`,JSON.stringify([...p.secretKey]),{mode:0o600});
    writeFileSync(`${PRIVATE}/keeper-publisher.json`,JSON.stringify([...publisher.secretKey]),{mode:0o600});
    await send(program.methods.setStage1Publisher(publisher.publicKey).accounts({city:city(),programConfig:config(),admin:wallet.publicKey}));
    action('initialize',people[0],{canon_id:canonId});
    for(const person of people){
      expect(await provider.connection.getBalance(person.publicKey)).eq(0);
      action('registration',person);
      expect(await provider.connection.getBalance(person.publicKey)).eq(0);
      expect((await program.account.stage1Recipient.fetch(pda('s1v1_recipient',person.publicKey.toBuffer()))).recipient.toBase58()).eq(person.publicKey.toBase58());
    }
    action('registration',people[0],{expect_status:409});
    await send(createInitializeMint2Instruction(mint,9,wallet.publicKey,null));
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
  });
  after(async()=>{await active?.stop();});
  it('pays the zero-SOL registered rider, then self-claims after an owner-closed ATA',async()=>{
    await publish(0);await income(1);await publish(1);
    const first=bridge({week:1,payout:true});
    expect(first.unpaid_leaves).eq(0);expect(first.sponsorships).eq(5);expect(first.failed_actions).eq(0);
    const rider=people[0],destination=getAssociatedTokenAddressSync(mint,rider.publicKey),source=getAssociatedTokenAddressSync(mint,wallet.publicKey);
    const paid=(await getAccount(provider.connection,destination,'finalized')).amount;
    expect(paid>0n).eq(true);expect(await provider.connection.getBalance(rider.publicKey)).eq(0);
    await send([createTransferInstruction(destination,source,rider.publicKey,paid),createCloseAccountInstruction(destination,rider.publicKey,rider.publicKey)],[rider]);
    const rent=await provider.connection.getBalance(rider.publicKey);expect(rent>0).eq(true);
    await income(2);const publication=await publish(2);
    const missed=bridge({week:2,payout:true});expect(missed.unpaid_leaves).eq(1);expect(missed.sponsorships).eq(5);
    const leaf=publication.claims.leaves.find((p:any)=>p.person===rider.publicKey.toBase58());expect(leaf).not.eq(undefined);
    const result=action('self-claim',rider,{payload:{claims:[{job_id:publication.job,role:-1,index:leaf.index}]}});
    expect((await getAccount(provider.connection,destination,'confirmed')).amount).eq(BigInt(leaf.amount));
    expect(await provider.connection.getBalance(rider.publicKey)).eq(0);
    const recovered=bridge({week:2,payout:true});expect(recovered.unpaid_leaves).eq(0);expect(recovered.sponsorships).eq(5);
    writeFileSync(`${OUT}/rider-outcome.json`,JSON.stringify({evidence:'synthetic localnet rides, auth and boundaries; real HTTP and chain transactions',first,missed,recovered,first_payment:String(paid),self_claim:String(leaf.amount),owner_ata_rent:rent,operation:result.operation.operation_id},null,2));
  });
  it('creates an owner-paid lookup, claims with v0, and refunds lookup rent to its owner',async()=>{
    const rider=people[0],destination=getAssociatedTokenAddressSync(mint,rider.publicKey),source=getAssociatedTokenAddressSync(mint,wallet.publicKey);
    const amount=(await getAccount(provider.connection,destination,'finalized')).amount;
    await send([createTransferInstruction(destination,source,rider.publicKey,amount),createCloseAccountInstruction(destination,rider.publicKey,rider.publicKey),
      SystemProgram.transfer({fromPubkey:wallet.publicKey,toPubkey:rider.publicKey,lamports:5000000})],[rider]);
    await income(3);const publication=await publish(3);const missed=bridge({week:3,payout:true});expect(missed.unpaid_leaves).eq(1);
    const leaf=publication.claims.leaves.find((p:any)=>p.person===rider.publicKey.toBase58());
    const claims=[{job_id:publication.job,role:-1,index:leaf.index}];
    const before=await provider.connection.getBalance(rider.publicKey);
    const setup=action('claim-transport',rider,{payload:{mode:'create',claims,recent_slot:String(await provider.connection.getSlot('finalized'))}});
    const table=new PublicKey(setup.operation.reference_id);lookupTables.push(table);
    while(!await provider.connection.getAccountInfo(table,'finalized'))await pause(100);
    const lookupRent=(await provider.connection.getAccountInfo(table,'finalized'))!.lamports;
    expect(before-await provider.connection.getBalance(rider.publicKey)).eq(lookupRent);
    action('self-claim',rider,{payload:{claims,lookup_table:table.toBase58()}});
    expect((await getAccount(provider.connection,destination,'confirmed')).amount).eq(BigInt(leaf.amount));
    const recovered=bridge({week:3,payout:true});expect(recovered.unpaid_leaves).eq(0);
    action('claim-transport',rider,{payload:{mode:'deactivate',lookup_table:table.toBase58()}});
    const deactivated=await provider.connection.getSlot('confirmed');
    while(await provider.connection.getSlot('finalized')<deactivated+520)await pause(200);
    const beforeRefund=await provider.connection.getBalance(rider.publicKey);
    action('claim-transport',rider,{payload:{mode:'close',lookup_table:table.toBase58()}});
    expect(await provider.connection.getBalance(rider.publicKey)-beforeRefund).eq(lookupRent);
    expect(await provider.connection.getAccountInfo(table,'confirmed')).eq(null);
    lookupTables.splice(lookupTables.indexOf(table),1);
    writeFileSync(`${OUT}/lookup-outcome.json`,JSON.stringify({evidence:'real localnet owner-paid lookup setup, v0 claim, cooldown and owner refund',lookupRent,returned:lookupRent},null,2));
  });
  it('pledges, notices, cancels, notices again and withdraws after synthetic lock and notice time',async()=>{
    const source=getAssociatedTokenAddressSync(mint,backer.publicKey);
    await send([createAssociatedTokenAccountIdempotentInstruction(wallet.publicKey,source,backer.publicKey,mint),createMintToInstruction(mint,source,wallet.publicKey,100000n)]);
    await send(program.methods.setTestLstRate(bn(2),bn(1),bn(await clock())).accounts({city:city(),asset:asset(),programConfig:config(),admin:wallet.publicKey}));
    const before=await provider.connection.getBalance(backer.publicKey);
    const pledge=action('pledge',backer,{payload:{hill:hill().toBase58(),mint:mint.toBase58(),deposit_id:'2',amount_base_units:'100000',lock_weeks:13}});
    const parent=pda('s1v1_lot',backer.publicKey.toBuffer(),u64(2));
    let data=await program.account.stage1PledgeLot.fetch(parent);expect(data.owner.toBase58()).eq(backer.publicKey.toBase58());
    expect(await provider.connection.getBalance(backer.publicKey)).lessThan(before);
    // Notice cannot begin before the ratified lot lock. Time here is synthetic.
    await move(data.lockEnd.toNumber()+100);
    const basis=data.basisLamports.toString();
    action('withdrawal-notice',backer,{payload:{lot:parent.toBase58(),request_id:'1',basis_lamports:basis}});
    const first=pda('s1v1_request',parent.toBuffer(),u64(1));
    action('cancel-notice',backer,{payload:{lot:parent.toBase58(),request:first.toBase58()}});
    action('withdrawal-notice',backer,{payload:{lot:parent.toBase58(),request_id:'2',basis_lamports:basis}});
    const second=pda('s1v1_request',parent.toBuffer(),u64(2));let request=await program.account.stage1WithdrawalRequest.fetch(second);
    await move(request.eligibleAt.toNumber()+100);
    await send(program.methods.setTestLstRate(bn(2),bn(1),bn(await clock())).accounts({city:city(),asset:asset(),programConfig:config(),admin:wallet.publicKey}));
    action('begin-withdrawal',backer,{payload:{lot:parent.toBase58(),request:second.toBase58()}});
    const exit=pda('s1v1_exit',second.toBuffer());
    action('complete-withdrawal',backer,{payload:{lot:exit.toBase58(),request:second.toBase58()}});
    request=await program.account.stage1WithdrawalRequest.fetch(second);expect(request.status).eq(2);
    expect((await getAccount(provider.connection,source,'confirmed')).amount).eq(100000n);
    writeFileSync(`${OUT}/transactions-outcome.json`,JSON.stringify({evidence:'real localhost HTTP prepare/sign/submit and operation reads; synthetic clock, fixtures and rides',operations,backer_returned_units:'100000',final_status:request.status},null,2));
  });
  it('checks a real-provider pre-bond pledge in both clients before signing',async()=>{
    // Zero-SOL recipients have no system account to capture; preserve every
    // existing owner account, just as the earlier clock replays do.
    const owners=await Promise.all([publisher,backer,...people].map(async p=>
      await provider.connection.getAccountInfo(p.publicKey)?p.publicKey:null));
    const captured=await capture(provider.connection,program.programId,
      [wallet.publicKey,...owners.filter((p):p is PublicKey=>p!==null)]);
    const files=resolve(ROOT,'protocol/anchor/tests/fixtures/stage1_providers');
    const pool=JSON.parse(readFileSync(`${files}/jito-pool.json`,'utf8'));
    const mintSnapshot=JSON.parse(readFileSync(`${files}/jito-mint.json`,'utf8'));
    for(const raw of [pool,mintSnapshot])captured.set(raw.pubkey,{...raw.account,owner:new PublicKey(raw.account.owner),data:Buffer.from(raw.account.data[0],'base64')});
    const jito=new PublicKey(mintSnapshot.pubkey),source=getAssociatedTokenAddressSync(jito,backer.publicKey);
    // Explicit synthetic owner inventory; retained provider and mint bytes stay exact.
    const token=Buffer.alloc(165);jito.toBuffer().copy(token);backer.publicKey.toBuffer().copy(token,32);
    token.writeBigUInt64LE(1000000n,64);token[108]=1;
    captured.set(source.toBase58(),{owner:TOKEN_PROGRAM_ID,data:token,executable:false,lamports:2039280,rentEpoch:0});
    const at=await clock();await active?.stop();active=await replay(captured,at,false,1057,8);
    provider=new anchor.AnchorProvider(active.connection,wallet,{commitment:'processed',preflightCommitment:'processed'});
    program=new anchor.Program(original.idl,original.programId,provider);
    while(await provider.connection.getSlot('finalized')<40)await pause(100);
    const jitoAsset=pda('s1v1_asset',jito.toBuffer()),jitoEarnings=pda('s1v1_earnings',jito.toBuffer());
    const pair=[new PublicKey(pool.pubkey),jito].map(pubkey=>({pubkey,isSigner:false,isWritable:false}));
    const configure=(enabled:boolean)=>program.methods.configureAsset(enabled).accounts({city:city(),asset:jitoAsset,mint:jito,earnings:jitoEarnings,
      programConfig:config(),admin:wallet.publicKey,tokenProgram:TOKEN_PROGRAM_ID,systemProgram:SystemProgram.programId,rent:SYSVAR_RENT_PUBKEY}).remainingAccounts(pair);
    await send(configure(false));
    await send(program.methods.refreshStage1Rate().accounts({city:city(),asset:jitoAsset,provider:new PublicKey(pool.pubkey),mint:jito}));
    await send(configure(true));
    const id=hash('round2-provider-hill').subarray(0,16),profile=hash('round2-provider-profile'),commitment=Buffer.alloc(64);
    commitment[0]=1;id.copy(commitment,1);commitment.writeUInt16BE(1,17);profile.copy(commitment,32);
    const digest=hash(commitment),climb=pda('climb',digest),providerHill=pda('s1v1_hill',id);
    await send(program.methods.registerRatifiedClimb({canonId:[...id],canonVersion:1,canonicalProfileHash:[...profile],commitmentHash:[...digest],
      recordContinuityPolicy:{newRecordBoard:{}},name:'Local provider check',vertM:1000,distanceM:2000,avgGradientPct:500})
      .accounts({climb,climbVersionIndex:pda('climb_version',id,Buffer.from([0,1])),predecessorClimb:null,programConfig:config(),admin:wallet.publicKey,systemProgram:SystemProgram.programId}));
    await send(program.methods.initHillBond().accounts({city:city(),climb,hill:providerHill,programConfig:config(),admin:wallet.publicKey,systemProgram:SystemProgram.programId}));
    const payload={hill:providerHill.toBase58(),mint:jito.toBase58(),deposit_id:'3',amount_base_units:'100000',lock_weeks:13};
    const out=action('pledge',backer,{payload,client_intent:{kind:'stage1_pledge',hill:payload.hill,mint:payload.mint,
      depositId:payload.deposit_id,amountBaseUnits:payload.amount_base_units,lockWeeks:payload.lock_weeks,
      climb:climb.toBase58(),providerMode:'prebond',backingMints:[jito.toBase58()]}});
    expect(out.client_checks.portal).eq(true);expect(out.client_checks.ios).eq(true);
    const held=await program.account.stage1PledgeLot.fetch(pda('s1v1_lot',backer.publicKey.toBuffer(),u64(3)));
    expect(held.owner.toBase58()).eq(backer.publicKey.toBase58());
    writeFileSync(`${OUT}/provider-pledge-outcome.json`,JSON.stringify({evidence:'real local HTTP/chain pledge, unmodified retained Jito provider bytes; synthetic owner tokens and clock',
      client_checks:out.client_checks,rpc_requests:out.rpc_requests},null,2));
  });
});
