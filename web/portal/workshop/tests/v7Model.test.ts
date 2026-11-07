import assert from 'node:assert/strict';
import test from 'node:test';
import { analysisSamples } from '../v3Model';
import { displayTraces } from '../v7Model';
const points = analysisSamples([0,10,50,60].map((t,i) => ({ t,d:[0,100,100,200][i],power:[100,100,200,200][i],lon:0,lat:0,elevation:0 })));
test('V7 averaged distance runs reach their actual coverage boundaries without inventing a road gap', () => {
 const before=JSON.stringify(points), {runs}=displayTraces(points,'power','distance',2);
 assert.equal(runs.length,2);
 assert.deepEqual([runs[0].at(-1)!.position,runs[1][0].position],[100,100]);
 assert.equal(JSON.stringify(points),before);
});
test('V7 averaged time runs preserve exactly the real recording gap', () => {
 const {runs}=displayTraces(points,'power','time',2);
 assert.deepEqual([runs[0].at(-1)!.position,runs[1][0].position],[10,50]);
});
