import assert from 'node:assert/strict';
import test from 'node:test';
import { analysisSamples } from '../v3Model';
import { powerCurve, powerEffortRange } from '../v11Model';
import { selectPowerEffort } from '../v11PowerSelection';
const points=analysisSamples([0,2.5,5.5,6].map((t,i)=>({t,d:i*50,lon:0,lat:0,elevation:i,power:[0,300,0,0][i],cadence:80})));
test('V11 duration selection resolves to the finishing best effort in either direction',()=>{
 const curve=powerCurve(points), short=curve.findIndex(p=>p.duration===2), long=curve.findIndex(p=>p.duration===4);
 const forward=selectPowerEffort(curve,short,long)!, reverse=selectPowerEffort(curve,long,short)!;
 assert.deepEqual(forward.band,reverse.band);
 assert.equal(forward.effort.duration,4);assert.equal(forward.effort.watts,225);
 assert.equal(forward.effort.start,1.5);assert.equal(forward.effort.end,5.5);
 assert.equal(reverse.effort.duration,2);assert.equal(reverse.effort.watts,300);
 // Selecting two duration coordinates never averages separate best efforts.
 assert.deepEqual(powerEffortRange(points,forward.effort),{startIndex:0,endIndex:2,expanded:true});
 assert.equal(selectPowerEffort(curve,long,long)?.effort,curve[long]);
});
test('V11 rejects absent or stale curve positions rather than redirecting to a different effort',()=>{
 const curve=powerCurve(points);
 for(const [start,end] of [[0,curve.length],[-1,0],[0,NaN],[0,.5]])assert.equal(selectPowerEffort(curve,start,end),null);
 assert.equal(selectPowerEffort([],0,0),null);
});
