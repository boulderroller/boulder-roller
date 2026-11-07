import assert from 'node:assert/strict';
import test from 'node:test';
import { analysisSamples } from '../v3Model';
import { powerCadenceDensity } from '../v9Density';

const points = (times: number[], powers: (number|null)[], cadences: (number|null)[]) => analysisSamples(times.map((t,i)=>({t,d:i*10,lon:0,lat:0,elevation:0,power:powers[i],cadence:cadences[i]})));
test('V9 density weights irregular samples by covered time and ignores the terminal reading',()=>{
 const input=points([0,1,11,12],[100,200,100,950],[80,90,80,127]);
 const before=JSON.stringify(input), result=powerCadenceDensity(input);
 assert.equal(result.coveredSeconds,12);
 assert.deepEqual(result.cells.filter(c=>c.seconds).map(c=>[c.powerFrom,c.cadenceFrom,c.seconds]),[[100,80,2],[200,90,10]]);
 assert.equal(JSON.stringify(input),before);
 assert.ok(result.powerMax<950);
});
test('V9 density includes coasting, omits unpaired data and gaps, and accepts a missing closing sample',()=>{
 const result=powerCadenceDensity(points([0,5,15,25,70,80],[0,100,null,900,200,1500],[0,80,80,100,null,90]));
 assert.equal(result.coveredSeconds,15);
 assert.deepEqual(result.cells.filter(c=>c.seconds).map(c=>[c.powerFrom,c.cadenceFrom,c.seconds]),[[0,0,5],[100,80,10]]);
});
test('V9 density places exact boundaries once and sums disjoint occurrences without including intervening work',()=>{
 const result=powerCadenceDensity(points([0,2,12,15,20],[24.9,100,25,24.9,0],[4.9,80,5,4.9,0]));
 assert.equal(result.cells.find(c=>c.powerFrom===0&&c.cadenceFrom===0)?.seconds,7);
 assert.equal(result.cells.find(c=>c.powerFrom===25&&c.cadenceFrom===5)?.seconds,3);
 assert.equal(result.cells.reduce((s,c)=>s+c.seconds,0),20);
});
test('V9 density keeps empty, zero-only and extreme imported ranges finite and bounded',()=>{
 assert.equal(powerCadenceDensity(points([0,31],[100,100],[80,80])).cells.length,0);
 const zero=powerCadenceDensity(points([0,1],[0,0],[0,0]));
 assert.equal(zero.coveredSeconds,1); assert.equal(zero.cells[0].seconds,1);
 const outlier=powerCadenceDensity(points([0,1],[1e9,0],[1e9,0]));
 assert.ok(outlier.cells.length<=4096); assert.equal(outlier.coveredSeconds,1);
 const extreme=powerCadenceDensity(points([0,1],[Number.MAX_VALUE,0],[Number.MAX_VALUE,0]));
 assert.equal(extreme.status,'unavailable'); assert.equal(extreme.coveredSeconds,1); assert.equal(extreme.cells.length,0);
});
