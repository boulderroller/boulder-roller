import assert from 'node:assert/strict';
import test from 'node:test';
import { analysisSamples } from '../v3Model';
import { bestPower, displayTraces } from '../v6Model';
const samples = (times: number[], powers: (number | null)[]) => analysisSamples(times.map((t, i) => ({ t, d: t * 4, lon: 0, lat: 0, elevation: 0, power: powers[i] })));
test('power curve finds windows ending between sample starts and counts measured zeros', () => {
 assert.deepEqual(bestPower(samples([0,3,7,10], [50,100,0,0]), 5), { duration: 5, watts: 90, start: 2, end: 7 });
 assert.equal(bestPower(samples([0,2,10], [100,0,1000]), 10)?.watts, 20);
 assert.equal(bestPower(samples([0,10], [0,0]), 10)?.watts, 0);
});
test('power curve never joins recording gaps or missing power', () => {
 assert.equal(bestPower(samples([0,10,50,60], [300,300,300,300]), 15), null);
 assert.equal(bestPower(samples([0,10,20,30], [300,null,300,300]), 15), null);
});
test('display averaging shares an axis budget, preserves gaps and leaves source values untouched', () => {
 const source = samples(Array.from({length: 4000}, (_, i) => i), Array.from({length: 4000}, (_, i) => i % 200 === 0 ? null : i % 2 ? 0 : 400));
 const before = JSON.stringify(source);
 const traces = displayTraces(source, 'power', 'time', 400);
 assert.equal(traces.runs.length, 20);
 assert.ok(traces.runs.flat().length < 500);
 assert.ok(traces.averaged);
 assert.equal(JSON.stringify(source), before);
 const simple = samples([0,1,2], [0,400,0]);
 assert.equal(displayTraces(simple,'power','time',400).averaged,false);
});
test('display bin averages use elapsed coverage, including stationary distance intervals', () => {
 const source = samples([0,2,10], [100,0,0]);
 source.forEach(p => { p.d = 0; });
 const trace = displayTraces(source,'power','distance',2);
 assert.equal(trace.runs[0][0].value,20);
});
test('display includes covered power immediately before a missing reading', () => {
 const trace = displayTraces(samples([0,10,20], [0,100,null]), 'power','time',2);
 assert.equal(trace.runs[0][0].value,50);
});
