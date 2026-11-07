/* Fixture RPC + real PostgreSQL/process restart. No network transactions. */
const path=require('path'),assert=require('node:assert/strict'),crypto=require('crypto');
const root=path.resolve(__dirname,'../../..');
const {PublicKey,TransactionMessage,TransactionInstruction,EpochSchedule}=require(root+'/indexer/node_modules/@solana/web3.js');
const {BN}=require(root+'/indexer/node_modules/@coral-xyz/anchor');
const bs58=require(root+'/indexer/node_modules/bs58');
const {getCoder,loadIdl}=require(root+'/indexer/dist/decoder');
const db=require(root+'/indexer/dist/db');
const heads=require(root+'/indexer/dist/finalized-head');
const {runStage1Replay,writeStage1Account,projectTransaction}=require(root+'/indexer/dist/stage1');
const {runStage1ProgramStream}=require(root+'/indexer/dist/stage1-program-stream');
const {programVersionWindow}=require(root+'/indexer/dist/program-version-window');
const v=require(root+'/indexer/test/fixtures/stage1-boundaries.json')[2],T=v.boundary;
const key=n=>new PublicKey(Buffer.alloc(32,n)).toBase58(),program=new PublicKey(v.checkpoint.program);
const defs=Object.fromEntries([...loadIdl().accounts,...loadIdl().types].map(a=>[a.name,a.type]));
function convert(t,v){
 if(typeof t==='string'){
  if(t==='publicKey')return new PublicKey(v??PublicKey.default);
  if(t==='bool')return v??false;if(t==='string')return v??'';if(t==='bytes')return Buffer.from(v??[]);
  if(/^[ui]\d+$/.test(t))return Number(t.slice(1))>=64?new BN(v??0):Number(v??0);
 }
 if(t.array)return Array.from({length:t.array[1]},(_,i)=>convert(t.array[0],v?.[i]));
 if(t.vec)return(v??[]).map(x=>convert(t.vec,x));if(t.option)return v==null?null:convert(t.option,v);
 if(t.defined)return convert(defs[t.defined],v);
 if(t.kind==='struct')return Object.fromEntries(t.fields.map(f=>[f.name,convert(f.type,v?.[f.name])]));
 if(t.kind==='enum')return v??{[t.variants[0].name[0].toLowerCase()+t.variants[0].name.slice(1)]:{}};
 throw Error('unsupported fixture type');
}
function encode(row){const buffer=Buffer.alloc(100000),len=getCoder().accounts.accountLayouts.get(row.type).encode(convert(defs[row.type],row.fields),buffer);
 return {pubkey:new PublicKey(row.address),account:{data:Buffer.concat([crypto.createHash('sha256').update('account:'+row.type).digest().subarray(0,8),buffer.subarray(0,len)]),owner:program,lamports:1,executable:false,rentEpoch:0}};}
const base=structuredClone(v.checkpoint.accounts),hillB=key(50),climbB=key(51);
const secondHill=structuredClone(base.find(a=>a.type==='Stage1HillBond'));secondHill.address=hillB;secondHill.fields.climb=climbB;secondHill.fields.canonId=Array(16).fill(4);
const secondClimb=structuredClone(base.find(a=>a.type==='Climb'));secondClimb.address=climbB;secondClimb.fields.canonId=Array(16).fill(4);secondClimb.fields.vault=PublicKey.default.toBase58();
base.push(secondHill,secondClimb);
const newLot=structuredClone(base.find(a=>a.type==='Stage1PledgeLot'));newLot.fields.depositId='2';newLot.fields.sequence='2';newLot.fields.converted=true;
const id=Buffer.alloc(8);id.writeBigUInt64LE(2n);newLot.address=PublicKey.findProgramAddressSync([Buffer.from('s1v1_lot'),new PublicKey(newLot.fields.owner).toBuffer(),id],program)[0].toBase58();
const metadata=loadIdl().instructions.find(i=>i.name==='convertExcludedPledge').accounts;
const flatten=a=>a.flatMap(x=>x.accounts?flatten(x.accounts):[x]);
const supplied={lot:newLot.address,hill:v.hill,city:newLot.fields.city,asset:base.find(a=>a.type==='Stage1AssetConfig').address,owner:newLot.fields.owner};
const ix=new TransactionInstruction({programId:program,data:getCoder().instruction.encode('convertExcludedPledge',{}),keys:flatten(metadata).map((a,i)=>({pubkey:new PublicKey(supplied[a.name]??key(30+i)),isWritable:a.isMut,isSigner:a.isSigner}))});
const message=new TransactionMessage({payerKey:new PublicKey(newLot.fields.owner),recentBlockhash:key(40),instructions:[ix]}).compileToV0Message();
const empty=process.argv[2].startsWith('empty');
const newVault=structuredClone(base.find(a=>a.type==='Vault'));newVault.address=key(54);newVault.fields.id='2';newVault.fields.climb=climbB;
let headReads=0,timeReads=0,blockReads=0;
let phase=empty?-1:1,txReads=0,gpa=0,refreshes=0,signatureReads=0,missing=false,late=false,headFailure=false;
let frozenSlot,frozenTime,scheduledTime,staleInventory=false;
const slot=()=>frozenSlot??(phase===1||phase===-1?100:phase===2||phase===-2?150:200);
const items=()=>[...base,...(phase>1?[newLot]:[]),...(phase===-2?[newVault]:[])].filter(row=>phase!==-1||['ProgramConfig','Stage1CityConfig','Stage1AssetConfig'].includes(row.type)).map(row=>{
 const item=encode(row);if(phase===5&&row.type==='Stage1HillBond')item.account.data=item.account.data.subarray(0,8);return item;
});
const rpc={
 getSlot:async()=>{headReads++;if(headFailure)throw Error('head unavailable');return slot();},
 getAccountInfoAndContext:async()=>({context:{slot:slot()},value:encode(base.find(a=>a.type==='ProgramConfig')).account}),
 getGenesisHash:async()=>v.checkpoint.genesis,getEpochSchedule:async()=>new EpochSchedule(432000,432000,false,0,0),getFirstAvailableBlock:async()=>0,
 getProgramAccounts:async(_p,{filters})=>(gpa++,{context:{slot:slot()-(staleInventory?1:0)},value:items().filter(i=>filters.every(f=>{const bytes=Buffer.from(bs58.decode(f.memcmp.bytes));return i.account.data.subarray(f.memcmp.offset,f.memcmp.offset+bytes.length).equals(bytes);} ))}),
 getAccountInfo:async(address)=>phase===2?null:items().find(i=>i.pubkey.equals(address))?.account??null,
 getMultipleAccountsInfoAndContext:async(addresses)=>(refreshes++,{context:{slot:slot()},value:addresses.map(a=>phase===4?null:items().find(i=>i.pubkey.equals(a))?.account??null)}),
 getBlockTime:async(s)=>{timeReads++;return frozenTime??(empty?(s===100?T+20:T+30):s===100?T-20:s===150?T+1:T+20);},
 getSignaturesForAddress:async(address)=>{
  if(address.equals(PublicKey.findProgramAddressSync([Buffer.from('program_config')],program)[0]))return [];
  assert.ok(address.equals(program),'only the program history is polled');signatureReads++;
  if(empty)return phase===-2?[{signature:'conversion',slot:120,blockTime:T+25,err:null}]:[];
  return phase>1?[...(late?[{signature:'tail',slot:170,blockTime:T+3,err:null},{signature:'gap',slot:160,blockTime:T+2,err:null}]:[]),{signature:'conversion',slot:120,blockTime:T,err:null}]:[];
 },
 getTransaction:async(signature)=>{txReads++;if(empty)return {slot:120,blockTime:T+25,transaction:{message:{staticAccountKeys:[new PublicKey(hillB),new PublicKey(newVault.address),program],header:{numRequiredSignatures:1,numReadonlySignedAccounts:0,numReadonlyUnsignedAccounts:1},compiledInstructions:[]}},meta:{err:null,logMessages:[]}};if(phase===3&&signature==='conversion')throw Error('restart must not refetch completed conversion');if(missing&&signature==='gap')return null;assert.ok(!missing||signature!=='tail','tail may not pass the missing transaction');return {slot:signature==='gap'?160:signature==='tail'?170:120,blockTime:signature==='gap'?T+2:signature==='tail'?T+3:T,transaction:{message},meta:{err:null,logMessages:[],loadedAddresses:{writable:[],readonly:[]}}};},
 getBlockSignatures:async(s)=>{blockReads++;return {signatures:s===160?['gap']:s===170?['tail']:['conversion']};}
};
// Each fixture invocation represents a new scheduled poll; cache/cadence is
// exercised separately with an injected clock in the indexer unit suite.
async function sweep(options){heads.finalizedHeads=new heads.FinalizedHeads();heads.boundaryClock.now=()=>scheduledTime??(empty?(phase===-1?T+20:T+30):phase===1?T-20:phase===2?T+1:T+20);return runStage1Replay(rpc,options);}
(async()=>{
 programVersionWindow.observe(77);
 if(process.argv[2]==='halt'){
  await sweep();const before={gpa,timeReads};
  for(let n=0;n<10;n++){scheduledTime=T+30*n;await sweep();}
  assert.equal(gpa,before.gpa,'a frozen pre-noon head must not trigger post-boundary captures');
  assert.equal(timeReads,before.timeReads,'the frozen head time is cached across polls');
  // Slots can advance while the bank clock is stuck before the boundary.
  frozenTime=T-20;
  for(let n=0;n<10;n++){frozenSlot=101+n;scheduledTime=T+300+30*n;await sweep();}
  assert.equal(gpa,before.gpa,'advancing slots with halted chain time must not recapture');
  assert.equal(timeReads,before.timeReads+10,'at most one head time per new sampled slot');
  frozenSlot=150;frozenTime=T+1;staleInventory=true;
  await assert.rejects(()=>sweep(),/Capture bank is behind finalized head/);
  assert.equal(Number((await db.query('SELECT last_capture_time FROM stage1_indexer_stream')).rows[0].last_capture_time),T-20,'an invalid capture cannot mark the boundary complete');
  staleInventory=false;await sweep();const completed=gpa;
  assert.ok(completed>before.gpa,'capture starts after the actual finalized head crosses noon');
  for(let n=0;n<10;n++){scheduledTime=T+600+30*n;await sweep();}
  assert.equal(gpa,completed,'a valid boundary capture is not repeated while the chain stays halted');
 }else if(process.argv[2]==='halt-restart'){
  frozenSlot=150;frozenTime=T+1;scheduledTime=T+1200;await sweep();
  assert.equal(gpa,0,'restart keeps the valid post-boundary capture complete');
 }else if(process.argv[2]==='empty-halt'){
  frozenTime=T-20;scheduledTime=T+30;await sweep();const before=gpa;
  await sweep();assert.equal(gpa,before,'empty bootstrap is not repeated on a halted head');
  phase=-2;frozenTime=T+30;await sweep();
  assert.ok(gpa>before,'an empty pre-noon capture must not mark the post-noon phase complete');
  assert.ok(Number((await db.query('SELECT count(*) FROM stage1_indexer_checkpoints')).rows[0].count)>0);
 }else if(empty){
  await sweep();const before=gpa;phase=-2;await sweep();
  assert.equal(gpa,before,'new hills project between boundary snapshots');
  assert.equal(txReads,1);
  const floor=(await db.query('SELECT from_slot,from_time FROM stage1_indexer_network')).rows[0];
  assert.equal(Number(floor.from_slot),120,'a conservative time bound must not be paired with a later head as an exact observation floor');
  assert.equal(Number(floor.from_time),T+25);
  assert.equal((await db.query('SELECT count(*) FROM indexed_stage1_hills WHERE address=$1',[hillB])).rows[0].count,'1');
  const links=(await db.query('SELECT address FROM stage1_indexer_dependencies WHERE hill=$1',[hillB])).rows.map(r=>r.address);
  assert.ok(links.includes(climbB));assert.ok(links.includes(newVault.address));
  const id=Buffer.alloc(8);id.writeBigUInt64LE(2n);
  for(const seed of ['vault_leaderboard','local_legend'])assert.ok(links.includes(PublicKey.findProgramAddressSync([Buffer.from(seed),id],program)[0].toBase58()));
 }else if(process.argv[2]==='first'){
  await sweep();
  const firstStamp=(await db.query('SELECT covered_at FROM stage1_indexer_stream')).rows[0].covered_at.toISOString();
  await db.query("UPDATE stage1_indexer_stream SET observed_time=$1,last_capture_time=$1,retry_at=now()+interval '1 minute',attempts=1",[T-120]);
  const beforeHold=gpa;heads.boundaryClock.now=()=>T-30;
  await runStage1Replay(rpc);
  assert.ok(gpa>beforeHold,'pre-boundary captures continue during source backoff with old observations');
  await db.query('UPDATE stage1_indexer_stream SET attempts=0,retry_at=now()');
  const beforeRetry=gpa;
  heads.boundaryClock.now=()=>T+1;
  await runStage1Replay(rpc);await runStage1Replay(rpc);
  assert.equal(gpa,beforeRetry,'post-boundary scheduler waits for the finalized head to cross noon');
  const recaptured=(await db.query('SELECT covered_at,last_capture_time FROM stage1_indexer_stream')).rows[0];
  assert.equal(recaptured.covered_at.toISOString(),firstStamp,'cache reuse does not renew freshness');
  assert.equal(Number(recaptured.last_capture_time),T-20,'wall-clock completion does not stand in for a post-boundary bank');
  phase=2;
  await assert.rejects(()=>sweep(),/Stage1 source capture pending/);
  assert.equal((await db.query('SELECT through_slot FROM stage1_indexer_hill_coverage WHERE hill=$1',[v.hill])).rows[0].through_slot,'100');
  assert.equal((await db.query('SELECT through_slot FROM stage1_indexer_hill_coverage WHERE hill=$1',[hillB])).rows[0].through_slot,'150');
  assert.equal((await db.query("SELECT count(*) FROM stage1_indexer_transaction_hills WHERE hill=$1 AND signature='conversion'",[v.hill])).rows[0].count,'1',JSON.stringify({txReads,pending:(await db.query('SELECT * FROM stage1_indexer_pending')).rows,alerts:(await db.query('SELECT * FROM stage1_indexer_alerts')).rows}));
  assert.equal(txReads,1);
  // Every missing capture must also reach the supervisor's backoff path.
  phase=4;await assert.rejects(()=>sweep(),/Stage1 source capture pending/);
  phase=5;await assert.rejects(()=>sweep(),/Stage1 source capture pending/);
 }else{
  phase=3;await sweep();assert.equal(txReads,0);
  const saved=(await db.query('SELECT witness FROM stage1_boundary_witnesses WHERE hill=$1 AND boundary=$2',[v.hill,T])).rows[0];
  assert.ok(saved,JSON.stringify({tasks:(await db.query('SELECT hill,week,error,retry_at FROM stage1_boundary_tasks')).rows,coverage:(await db.query('SELECT * FROM stage1_indexer_hill_coverage')).rows,stream:(await db.query('SELECT * FROM stage1_indexer_stream')).rows}));
  const witness=saved.witness;
  assert.equal(witness.opening.dung.lots.length,1);assert.equal(witness.source.transactions[0].signature,'conversion');
  await db.query("UPDATE indexed_stage1_assets SET data=jsonb_set(data,'{lastFreshUntil}','0')");
  const quiet={gpa,refreshes,signatureReads,headReads,timeReads};await sweep();
  assert.equal(headReads,quiet.headReads+1);assert.equal(timeReads,quiet.timeReads,'idle expired fixture does not need a head clock');
  assert.equal(blockReads,0,'singleton program slots require no block-order RPC');
  assert.equal(gpa,quiet.gpa,'no full captures between boundaries');
  assert.equal(refreshes,quiet.refreshes,'no account refresh without writes');
  assert.equal(signatureReads,quiet.signatureReads+1,'one program poll regardless of dependencies');
  headFailure=true;await sweep();await sweep({shared:true});
  assert.equal((await db.query('SELECT ready FROM stage1_indexer_network')).rows[0].ready,false,'consumer cannot revive stale stream coverage');
  headFailure=false;await db.query('UPDATE stage1_indexer_stream SET retry_at=now()');
  late=true;missing=true;const before=txReads;await sweep();
  assert.equal(txReads,before+1,'only the missing transaction is fetched');
  assert.equal((await db.query('SELECT through_slot FROM stage1_indexer_network')).rows[0].through_slot,'200');
  assert.equal((await db.query('SELECT count(*) FROM stage1_indexer_pending WHERE NOT done')).rows[0].count,'2');
  missing=false;phase=6;await db.query('UPDATE stage1_indexer_stream SET retry_at=now()');
  await db.query("INSERT INTO indexer_sync_state(id,last_tx_signature,last_tx_slot) VALUES(1,'conversion',120) ON CONFLICT(id) DO UPDATE SET last_tx_signature='conversion',last_tx_slot=120");
  const fetched=txReads,legacy=[];
  heads.finalizedHeads=new heads.FinalizedHeads();
  const stage1=require(root+'/indexer/dist/stage1'),decode=stage1.decodeTransactionWitness;
  stage1.decodeTransactionWitness=(signature,tx)=>{if(signature==='gap')throw Error('fixture Stage1 decode hold');return decode(signature,tx);};
  const consumeLegacy=async(_rpc,info,tx)=>{assert.equal(tx.slot,info.slot);legacy.push(info.signature);return {processed:true,events:0};};
  await assert.rejects(()=>runStage1ProgramStream(rpc,consumeLegacy),/Program stream source pending/);
  const {readReplayLag}=require(root+'/indexer/dist/lag-monitor');
  const sync=(await db.query('SELECT * FROM indexer_sync_state WHERE id=1')).rows[0];
  assert.equal(readReplayLag(rpc,program,sync).status,'current','Stage1-only decode failure does not revoke fully processed legacy coverage');
  stage1.decodeTransactionWitness=decode;
  assert.deepEqual(legacy,['conversion','gap','tail']);assert.equal(txReads-fetched,3);
  await db.query('UPDATE stage1_indexer_stream SET retry_at=now()');
  await runStage1ProgramStream(rpc,consumeLegacy);
  await db.query('SELECT stage1_indexer_prune_sources()');
  assert.equal((await db.query("SELECT count(*) FROM stage1_indexer_transactions WHERE signature IN ('gap','tail')")).rows[0].count,'2','queued witnesses survive pruning before classification');
  const afterFetch=txReads;await sweep({shared:true});assert.equal(txReads,afterFetch);
  assert.equal((await db.query('SELECT ready FROM stage1_indexer_network')).rows[0].ready,true);
  assert.equal((await db.query('SELECT chain_slot FROM indexed_stage1_lots WHERE address=$1',[newLot.address])).rows[0].chain_slot,'200','refresh uses returned bank');
  // A bank snapshot is already the end-of-slot truth. Replaying its earlier
  // publication must not reset payments or reopen a closed set in that slot.
  await db.query("UPDATE stage1_indexer_stream SET before='unfinished-page',pending_head=cursor,pending_slot=cursor_slot,fence_slot=covered_slot,fence_time=covered_time,fence_at=now()-interval '2 minutes'");
  await sweep();
  assert.equal((await db.query('SELECT ready FROM stage1_indexer_network')).rows[0].ready,false,'finishing an old page range cannot renew its original fence timestamp');
  await sweep();
  assert.equal((await db.query('SELECT ready FROM stage1_indexer_network')).rows[0].ready,true,'a new complete range restores fresh coverage');
  const claimSet=key(60),fields={claimSet,hill:v.hill,week:0,mint:key(7)};
  await writeStage1Account('Stage1ClaimSet',claimSet,{...fields,paid:'90',claimedCount:1,sealed:true},220);
  await db.query('UPDATE indexed_stage1_claim_sets SET closed=true WHERE address=$1',[claimSet]);
  await projectTransaction({signature:'same-slot-publication',slot:220,block_time:T+30,success:true,writes:[],instructions:[],events:[{name:'Stage1CashPublished',fields}]});
  const retained=(await db.query('SELECT data,closed FROM indexed_stage1_claim_sets WHERE address=$1',[claimSet])).rows[0];
  assert.equal(retained.data.paid,'90');assert.equal(retained.data.claimedCount,1);assert.equal(retained.closed,true);
 }
 await db.closePool();
})().catch(async e=>{console.error(e);await db.closePool();process.exitCode=1;});
