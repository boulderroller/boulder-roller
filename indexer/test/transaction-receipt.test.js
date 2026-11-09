const test=require('node:test'),assert=require('node:assert/strict');
const {buildTransactionReceipt}=require('../dist/transaction-receipt');
const wallet='A'.repeat(32),sig='B'.repeat(88);
const q=async()=>({rows:[]});
for(const [event,kind,fields,key,value] of [
 ['ClimbCompletedV2','attestation',{time_s:235,rider:wallet},'time_s',235],
 ['EpochRewardsDistributed','settlement',{epoch:141,total_distributed:'5050000000'},'dung','5050000000'],
 ['CalStaked','deposit',{amount:'250000000000',staker:wallet},'cal','250000000000'],
 ['CalUnstaked','withdrawal',{cal_returned:'200000000000',staker:wallet},'cal','200000000000'],
 ['ClimbRegistered','registration',{canon_version:3},'canon_version',3],
 ['LocalLegendElected','legend',{winner:wallet,winner_completions:17},'completions',17],
 ['RewardsHarvested','collection',{staker:wallet,dung_received:'500'},'dung','500'],
])test(`receipt decodes ${kind} without substituting missing fields`,async()=>{
 const r=await buildTransactionReceipt(q,[{signature:sig,status:'success',instruction_accounts:{rider:{pubkey:wallet}}}],[{event_name:event,fields}],[]);
 assert.equal(r.kind,kind);assert.equal(r.fields[key],value);assert.equal(r.fields.rank,undefined);assert.equal(r.climb,undefined);assert.equal(r.accounts[0].role,'Rider');
});
test('failed transaction has no asserted completed outcome',async()=>{
 const r=await buildTransactionReceipt(q,[{status:'failed'}],[{event_name:'CalStaked',fields:{amount:'500'}}],[]);assert.equal(r.fields.cal,undefined);
});
test('multiple rides never select the first hash or rider',async()=>{
 const events=[wallet,'C'.repeat(32)].map(rider=>({event_name:'RideAttestationRecorded',fields:{rider,rideHash:'a'.repeat(64)}}));const r=await buildTransactionReceipt(q,[{status:'success'}],events,[]);assert.equal(r.rider,undefined);assert.equal(r.fields.ride_hash,undefined);
});
test('a sole completion never borrows a parent hash merely because the rider matches',async()=>{
 const r=await buildTransactionReceipt(q,[{status:'success'}],[{event_name:'ClimbCompletedV2',fields:{rider:wallet,time_s:12}},{event_name:'RideAttestationRecorded',fields:{rider:wallet,rideHash:'a'.repeat(64),economicEpoch:12}}],[]);assert.equal(r.fields.time_s,12);assert.equal(r.fields.ride_hash,undefined);assert.equal(r.fields.week,undefined);
});
test('unknown account roles stay unnamed and allocation is never Paid',async()=>{
 const r=await buildTransactionReceipt(q,[{status:'success',instruction_accounts:{newInternalRole:wallet}}],[{event_name:'EpochRewardsDistributed',fields:{total_distributed:'100'}},{event_name:'StakerAllocation',fields:{staker:wallet,amount:'100'}}],[]);
 assert.equal(r.accounts[0].pubkey,wallet);assert.equal(r.accounts[0].role,undefined);assert.deepEqual(r.paid,[]);assert.equal(r.fields.positions_paid,undefined);
});
