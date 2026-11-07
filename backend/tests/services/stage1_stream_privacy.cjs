/* Real PostgreSQL tombstone, synthetic finalized RPC event. No transactions sent. */
const assert=require('node:assert/strict'),path=require('path'),crypto=require('crypto');
const root=path.resolve(__dirname,'../../..');
const {PublicKey}=require(root+'/indexer/node_modules/@solana/web3.js');
const db=require(root+'/indexer/dist/db');
const {getCoder}=require(root+'/indexer/dist/decoder');
const {programVersionWindow}=require(root+'/indexer/dist/program-version-window');
const {processTransaction}=require(root+'/indexer/dist/modes/replay');
const {projectTransaction,writeStage1Account}=require(root+'/indexer/dist/stage1');
const program=new PublicKey(process.env.PROGRAM_ID),key=n=>new PublicKey(Buffer.alloc(32,n));
const u64=n=>{const b=Buffer.alloc(8);b.writeBigUInt64LE(BigInt(n));return b;};
const u32=n=>{const b=Buffer.alloc(4);b.writeUInt32LE(n);return b;};
(async()=>{
 programVersionWindow.observe(77);
 const event=Buffer.concat([crypto.createHash('sha256').update('event:ClimbCompleted').digest().subarray(0,8),u64(1),key(5).toBuffer(),key(8).toBuffer(),u32(100),u64(5),Buffer.alloc(32),Buffer.from([0]),u64(1791201600),u64(1791201600)]);
 const live=Buffer.concat([crypto.createHash('sha256').update('event:Stage1CashReceived').digest().subarray(0,8),key(2).toBuffer(),u64(0),key(7).toBuffer(),u64(5),Buffer.alloc(32)]);
 const tx={slot:100,blockTime:1791201600,transaction:{message:{compiledInstructions:[{programIdIndex:2,accountKeyIndexes:[1,0],data:getCoder().instruction.encode('updateProgramConfig',{backendAuthority:key(8)})}],staticAccountKeys:[key(8),key(4),program]}},meta:{err:null,fee:0,logMessages:[`Program ${program} invoke [1]`,`Program data: ${event.toString('base64')}`,`Program data: ${live.toString('base64')}`,`Program ${program} success`]}};
 if(process.argv[2]==='pending') {
   await assert.rejects(()=>processTransaction({}, {signature:'erased-rider',slot:100,blockTime:1791201600,err:null,memo:null},tx),/account_deletion_pending/);
   assert.equal((await db.query('SELECT count(*) FROM indexed_events')).rows[0].count,'0');
   await db.closePool();return;
 }
 const result=await processTransaction({}, {signature:'erased-rider',slot:100,blockTime:1791201600,err:null,memo:null},tx);
 assert.equal(result.processed,true);
 assert.equal((await db.query("SELECT count(*) FROM indexed_events WHERE tx_signature='erased-rider' AND event_name='ClimbCompleted'")).rows[0].count,'0','delayed legacy replay must not restore a deleted rider');
 assert.equal((await db.query("SELECT count(*) FROM indexed_transactions WHERE signature='erased-rider'")).rows[0].count,'0');
 assert.equal((await db.query("SELECT count(*) FROM indexed_events WHERE event_name='Stage1CashReceived'")).rows[0].count,'1','surviving event continues');
 const claim={signature:'erased-payment',slot:101,block_time:1791201601,success:true,writes:[],events:[],instructions:[{index:'0:0',name:'claimStage1',accounts:{registration:key(4).toBase58(),claimSet:key(3).toBase58()},args:{person:'anonymous:erased',index:0,amount:'5'}}]};
 await projectTransaction(claim);
 assert.equal((await db.query('SELECT count(*) FROM indexed_stage1_payouts')).rows[0].count,'0');
 claim.instructions[0].args.person=key(7).toBase58();
 await assert.rejects(()=>projectTransaction(claim),/Missing finalized recipient/);
 await writeStage1Account('Stage1Recipient',key(4).toBase58(),{person:key(7).toBase58(),recipient:key(8).toBase58()},102);
 const registration=(await db.query('SELECT data FROM indexed_stage1_recipients WHERE address=$1',[key(4).toBase58()])).rows[0];
 assert.ok(registration?.data.recipient.startsWith('anonymous:'),'erased recipient metadata is retained only as anonymous');
 await writeStage1Account('Stage1ClaimSet',key(3).toBase58(),{hill:key(2).toBase58(),week:0,mint:key(6).toBase58()},102);
 claim.instructions.unshift({...claim.instructions[0],index:'0:0',accounts:{registration:key(20).toBase58()},args:{person:'anonymous:erased',index:0,amount:'5'}});
 claim.instructions[1].index='1:0';await projectTransaction(claim);
 assert.equal((await db.query('SELECT count(*) FROM indexed_stage1_payouts WHERE person=$1',[key(7).toBase58()])).rows[0].count,'1','surviving payout in the same transaction continues');
 await db.closePool();
})().catch(async error=>{console.error(error);await db.closePool();process.exitCode=1;});
