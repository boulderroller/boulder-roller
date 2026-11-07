import {test} from 'node:test';
import assert from 'node:assert/strict';
import {climbMeasurements,elevationLabel} from '../climb/climbV12Measurements';

const rolling={length:1000,gain:65,profile:[
 {d:0,elevation:100},{d:200,elevation:140},{d:500,elevation:90},
 {d:750,elevation:155},{d:1000,elevation:120},
]};
test('elevation difference is highest minus lowest; grade remains signed endpoint rise',()=>{
 const m=climbMeasurements(rolling);
 assert.equal(m.min,90);assert.equal(m.max,155);
 assert.equal(m.difference,65);assert.equal(m.grade,2);
});
test('cumulative gain counts re-climbing and stays distinct from endpoint rise',()=>{
 const m=climbMeasurements(rolling);
 assert.equal(m.gain,105);assert.equal(m.rise,20);
 const descending=climbMeasurements({...rolling,profile:[...rolling.profile].reverse().map((p,i)=>({...p,d:i*250}))});
 assert.equal(descending.gain,85);assert.equal(descending.difference,65);assert.equal(descending.grade,-2);
});
test('flat profiles retain valid zeroes',()=>{
 const m=climbMeasurements({length:1000,profile:[{d:0,elevation:32},{d:1000,elevation:32}]});
 assert.equal(m.gain,0);assert.equal(m.difference,0);assert.equal(m.grade,0);
});
import {v12Effort,v12Ride} from '../climb/climbV12Model';
import {climbReturnHref} from '../climb/climbV3Navigation';
test('V12 effort and ride links return to V12 with their viewer context',()=>{
 const href='/?surface=ride&scenario=r&climb=c&from=1&to=2&climbOrigin=wises&climbOriginViewer=visitor';
 for(const destination of [v12Ride(href),v12Effort(href)]){
  assert.equal(climbReturnHref(new URL(destination,'http://local.test').searchParams),'/?surface=climb&variant=climb-v12&scenario=wises&viewer=visitor');
 }
});
test('elevation formatting retains useful tenths without decorative zeroes',()=>{
 assert.equal(elevationLabel(62.2),'62.2');assert.equal(elevationLabel(60),'60');
 assert.equal(elevationLabel(55.2),'55.2');assert.equal(elevationLabel(122.6),'122.6');
 assert.equal(elevationLabel(122.6-55.2),'67.4');assert.equal(elevationLabel(-0.01),'0');
});
