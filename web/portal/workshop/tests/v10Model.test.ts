import assert from 'node:assert/strict';
import test from 'node:test';
import * as model from '../v10Model';
import * as density from '../v10Density';
import { analysisSamples, type AnalysisSample } from '../v3Model';
const samples=(times:number[],powers:(number|null)[])=>analysisSamples(times.map((t,i)=>({t,d:i*50,lon:0,lat:0,elevation:i,power:powers[i],cadence:80})));
test('V10 opens the full power effort using time boundaries and honest surrounding samples',()=>{
 const points=samples([0,2,5,8],[100,400,0,null]);
 assert.deepEqual(model.powerEffortRange(points,{start:2,end:5,duration:3,watts:400}),{startIndex:1,endIndex:2,expanded:false});
 assert.deepEqual(model.powerEffortRange(points,{start:3,end:6,duration:3,watts:800/3}),{startIndex:1,endIndex:3,expanded:true});
 assert.equal(model.powerEffortRange(points,{start:2,end:5,duration:3,watts:900}),null);
 assert.equal(model.powerEffortRange(points,{start:-1,end:2,duration:3,watts:100}),null);
 assert.equal(model.powerEffortRange(samples([0,31],[0,null]),{start:0,end:1,duration:1,watts:0}),null);
 assert.deepEqual(model.powerEffortRange(samples([0,2],[0,null]),{start:0,end:2,duration:2,watts:0}),{startIndex:0,endIndex:1,expanded:false});
});
test('V10 gradient density preserves signed grade, zeros, covered time and fixed climb bins',()=>{
 const points=samples([0,2,5,45,49],[1,1,1,1,1]).map((p,i)=>({...p,grade:[-4,0,4,null,8][i],cadence:[0,80,80,80,80][i]})) as AnalysisSample[];
 const all=density.cadenceGradientDensity(points), scoped=density.cadenceGradientDensity(points,{startIndex:1,endIndex:2});
 assert.equal(all.coveredSeconds,5);assert.equal(all.cells.reduce((s,c)=>s+c.seconds,0),5);
 assert.equal(scoped.cells.reduce((s,c)=>s+c.selectedSeconds,0),3);
 assert.deepEqual([all.rows,all.columns,all.xMin,all.xStep],[scoped.rows,scoped.columns,scoped.xMin,scoped.xStep]);
 assert.equal(all.cells.find(c=>c.xFrom<=-4&&c.xTo>-4&&c.yFrom===0)?.seconds,2);
 assert.equal(density.cadenceGradientDensity(points.map(p=>({...p,grade:null}))).status,'empty');
 assert.ok(all.columns<=64&&all.rows<=64);
});
