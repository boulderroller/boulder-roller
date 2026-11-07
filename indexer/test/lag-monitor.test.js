const test = require('node:test');
const assert = require('node:assert/strict');
const heads = require('../dist/finalized-head');
const { measureReplayLag, readReplayLag, recordReplayCoverage, replayLagNeedsAlert } = require('../dist/lag-monitor');

function fixture(t) {
  let now=Date.now(),slot=3000000,reads=0,fail=false;
  const reader=new heads.FinalizedHeads(()=>now),old=heads.finalizedHeads;
  heads.finalizedHeads=reader;t.after(()=>{heads.finalizedHeads=old;});
  const rpc={rpcEndpoint:'http://local-fixture',getSlot:async()=>{reads++;if(fail)throw Error('unavailable');return slot;},getSignaturesForAddress:async()=>assert.fail('lag must use the stream page')};
  recordReplayCoverage(rpc,'program');
  return {rpc,reader,reads:()=>reads,advance:n=>{now+=n;},setSlot:n=>{slot=n;},fail:()=>{fail=true;}};
}
test('one head attempt is shared across concurrent connections and 30-second cache reuse',async(t)=>{
  const f=fixture(t),other={...f.rpc};
  const samples=await Promise.all([f.reader.read(f.rpc),f.reader.read(other)]);
  assert.equal(f.reads(),1);assert.deepEqual(samples[0],samples[1]);
  f.advance(29999);assert.deepEqual(await f.reader.read(other),samples[0]);assert.equal(f.reads(),1);
  f.advance(1);await f.reader.read(other);assert.equal(f.reads(),2);
  f.advance(30000);f.fail();await assert.rejects(()=>f.reader.read(f.rpc));await assert.rejects(()=>f.reader.read(other));
  assert.equal(f.reads(),3);assert.equal(f.reader.peek(f.rpc),undefined);
});
test('idle lag uses complete replay coverage and no signature probe',async(t)=>{
  const f=fixture(t),sample=await f.reader.read(f.rpc),sync={last_tx_signature:'indexed',last_tx_slot:100};
  recordReplayCoverage(f.rpc,'program',{head:sample,signature:'indexed',slot:100});
  const result=await measureReplayLag(f.rpc,'program',sync);
  assert.equal(result.status,'current');assert.equal(result.lag_slots,0);assert.equal(f.reads(),1);
  assert.equal(readReplayLag(f.rpc,'program',{...sync,last_tx_signature:'different'}).status,'behind');
  f.advance(30000);f.setSlot(3002000);await f.reader.read(f.rpc);
  assert.equal(readReplayLag(f.rpc,'program',sync).lag_slots,2000);assert.equal(replayLagNeedsAlert(readReplayLag(f.rpc,'program',sync)),true);
  recordReplayCoverage(f.rpc,'program');assert.equal(readReplayLag(f.rpc,'program',sync).status,'unknown');
});
test('stale completion, failed head and regression cannot attest zero lag',async(t)=>{
  const f=fixture(t),sample=await f.reader.read(f.rpc),sync={last_tx_signature:'indexed',last_tx_slot:100};
  recordReplayCoverage(f.rpc,'program',{head:{...sample,sampledAt:Date.now()-90001},signature:'indexed',slot:100});
  assert.equal(readReplayLag(f.rpc,'program',sync).status,'unknown');
  f.advance(30000);f.setSlot(2999999);await assert.rejects(()=>f.reader.read(f.rpc),/regressed/);
  assert.equal(f.reader.peek(f.rpc),undefined);
});
test('health never keeps stale or failed coverage as a zero lag',()=>{
  const {attestedReplayLag}=require('../dist/health');const c={status:'current',checked_through_slot:100};
  assert.equal(attestedReplayLag(150,c,30000),50);assert.equal(attestedReplayLag(150,c,90001),null);
  assert.equal(attestedReplayLag(null,c,0),null);assert.equal(attestedReplayLag(150,null,0),null);
});
test('head clock is read once per sampled slot and only the pre-boundary window is scheduled',async()=>{
  let reads=0;const rpc={getBlockTime:async()=>{reads++;return 388799;}};
  assert.equal(await heads.finalizedHeadTime(rpc,10),388799);await heads.finalizedHeadTime(rpc,10);assert.equal(reads,1);
  await heads.finalizedHeadTime(rpc,9);await heads.finalizedHeadTime(rpc,10);assert.equal(reads,2);
  assert.equal(heads.inBoundaryWindow(388800-91),false);assert.equal(heads.inBoundaryWindow(388800-90),true);
  assert.equal(heads.inBoundaryWindow(388800),false);
});

test('a head RPC slower than the polling period stays singleflight and monotone',async()=>{
  let now=0,calls=0;const pending=[];
  const reader=new heads.FinalizedHeads(()=>now),rpc={getSlot:()=>{calls++;return new Promise(resolve=>pending.push(resolve));}};
  const first=reader.read(rpc);await Promise.resolve();now=30001;
  const next=reader.read(rpc);await Promise.resolve();
  pending[0](200);if(pending[1])pending[1](100);
  const samples=await Promise.all([first,next]);
  assert.equal(calls,1);assert.equal(samples[1].slot,200);assert.equal(reader.peek(rpc).slot,200);
});
