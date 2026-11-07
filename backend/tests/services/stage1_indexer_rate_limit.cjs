/* Real web3 HTTP retries and PostgreSQL; synthetic localhost RPC responses. */
const assert=require('node:assert/strict'),http=require('node:http'),path=require('node:path');
const root=path.resolve(__dirname,'../../..');
const {PublicKey}=require(root+'/indexer/node_modules/@solana/web3.js');
const key=n=>new PublicKey(Buffer.alloc(32,n)).toBase58();
const mode=process.argv[2],at=1791201500;
const signatures=Array.from({length:30},(_,n)=>({signature:`burst-${n}`,slot:200+n,blockTime:at,err:null,memo:null,confirmationStatus:'finalized'})).reverse();
const successful=new Map();let started=Date.now(),used=0,limited=0;
const server=http.createServer(async(req,res)=>{
 let body='';for await(const data of req)body+=data;
 const call=JSON.parse(body);
 if(Date.now()-started>=1000){started=Date.now();used=0;}
 if(used++>=10){limited++;res.writeHead(429);res.end('local fixture: 10 requests per second');return;}
 let result;
 switch(call.method){
  case 'getSlot':result=300;break;
  case 'getGenesisHash':result=key(31);break;
  case 'getEpochSchedule':result={slotsPerEpoch:432000,leaderScheduleSlotOffset:432000,warmup:false,firstNormalEpoch:0,firstNormalSlot:0};break;
  case 'getFirstAvailableBlock':result=0;break;
  case 'getSignaturesForAddress':result=[...signatures,{signature:'before',slot:100,blockTime:at-1,err:null,memo:null,confirmationStatus:'finalized'}];break;
  case 'getTransaction':{
   const info=signatures.find(s=>s.signature===call.params[0]);assert.ok(info);
   successful.set(info.signature,(successful.get(info.signature)??0)+1);
   result={slot:info.slot,blockTime:at,version:'legacy',meta:{err:null,fee:5000,preBalances:[],postBalances:[],logMessages:[]},
    transaction:{signatures:[],message:{accountKeys:[],header:{numRequiredSignatures:0,numReadonlySignedAccounts:0,numReadonlyUnsignedAccounts:0},instructions:[],recentBlockhash:key(32)}}};break;
  }
  default:res.writeHead(500);res.end('unexpected fixture method '+call.method);return;
 }
 res.setHeader('Content-Type','application/json');res.end(JSON.stringify({jsonrpc:'2.0',id:call.id,result}));
});
(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 process.env.SOLANA_RPC_URL=`http://127.0.0.1:${server.address().port}`;
 const db=require(root+'/indexer/dist/db');
 try{
  require(root+'/indexer/dist/finalized-head').boundaryClock.now=()=>at;
  const {programVersionWindow}=require(root+'/indexer/dist/program-version-window');
  programVersionWindow.observe(mode==='legacy'?0x4c:0x4d);
  await db.query("INSERT INTO indexer_sync_state(id,last_tx_signature,last_tx_slot) VALUES(1,'before',100)");
  if(mode==='stage1'){
   await db.query("INSERT INTO stage1_indexer_activation(genesis,program,slot,kind) VALUES($1,$2,150,'version_advance')",[key(31),process.env.PROGRAM_ID]);
   await db.query("INSERT INTO stage1_indexer_stream(singleton,cursor,cursor_slot,legacy_attached,history_start) VALUES(true,'before',100,true,100)");
  }
  const {runReplaySweep}=require(root+'/indexer/dist/modes/replay');
  const result=await runReplaySweep();
  assert.equal(result.processed,30,`${mode}: the entire rate-limited burst must finish in one poll`);
  const cursor=(await db.query('SELECT last_tx_signature,last_tx_slot FROM indexer_sync_state WHERE id=1')).rows[0];
  assert.equal(cursor.last_tx_signature,'burst-29');assert.equal(Number(cursor.last_tx_slot),229);
  assert.equal(successful.size,30);assert.ok([...successful.values()].every(n=>n===1),'no successfully fetched transaction was refetched');
  assert.ok(limited>0,'the real HTTP transport encountered 429s');
  if(mode==='stage1')assert.equal(Number((await db.query('SELECT count(*) FROM stage1_indexer_pending WHERE ingested AND legacy_done')).rows[0].count),30);
  console.log(JSON.stringify({mode,processed:result.processed,rate_limits:limited,cursor:cursor.last_tx_signature}));
 }finally{await db.closePool();await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error);process.exitCode=1;server.close();});
