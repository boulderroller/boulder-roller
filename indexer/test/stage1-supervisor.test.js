const test=require('node:test');
const assert=require('node:assert/strict');
const {setTimeout: sleep}=require('node:timers/promises');
const {startIndexerServices}=require('../dist/stage1-supervisor');

for(const failure of ['429 Max usage reached','request timeout','Undecodable finalized account','Finalized transaction unavailable']) {
  test(`supervised Stage1 ${failure}: legacy continues, then Stage1 recovers`,async(t)=>{
    let attempts=0,legacy=0,healthy=false,timer,resolveRecovery;
    const alerts=[],order=[],progress=[];
    const recovered=new Promise(resolve=>{resolveRecovery=resolve;});
    const worker=await startIndexerServices({
      health:()=>{healthy=true;order.push('health');},
      legacy:async()=>{order.push('legacy');timer=setInterval(()=>legacy++,1);},
      stage1:async()=>{
        order.push('stage1');progress.push(legacy);
        if(++attempts<3)throw new Error(failure);
        resolveRecovery();
      },
      alert:async(kind,count)=>{alerts.push({kind,count});},
      delay:()=>10,intervalMs:60_000,
    });
    t.after(()=>{worker.stop();clearInterval(timer);});
    const abort=new AbortController();
    try {
      await Promise.race([recovered,sleep(2000,null,{signal:abort.signal}).then(()=>{throw new Error('Stage1 did not recover');})]);
    } finally {abort.abort();}
    assert.deepEqual(order.slice(0,3),['health','legacy','stage1']);
    assert.ok(healthy);
    assert.ok(progress[1]>progress[0]&&progress[2]>progress[1],String(progress));
    assert.equal(attempts,3);
    assert.deepEqual(alerts,[1,2].map(count=>({count,kind:failure.startsWith('429')?'rate_limit':failure.includes('timeout')?'timeout':'source_unavailable'})));
  });
}

test('retry backoff wakes for both Monday boundary banks',()=>{
  const {boundaryRetryDeadlineMs}=require('../dist/stage1-supervisor');
  const monday=Date.parse('2026-10-19T12:00:00Z');
  assert.equal(boundaryRetryDeadlineMs(monday-120_000),30_000);
  assert.equal(boundaryRetryDeadlineMs(monday-60_000),30_000);
  assert.equal(boundaryRetryDeadlineMs(monday+20_000),30_000);
});
