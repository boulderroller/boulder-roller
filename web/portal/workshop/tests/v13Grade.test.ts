import assert from 'node:assert/strict';
import test from 'node:test';
import type { Sample } from '../scenario';
import { selectedAverageGrade, gradeLabel } from '../v13Grade';
const point=(d:number,elevation:number|null,t:number):Sample=>({d,elevation,t,lat:0,lon:0,power:null});
test('V13 selection grade measures signed net rise rather than accumulated climbing',()=>{
 assert.equal(selectedAverageGrade([point(0,100,0),point(100,120,10),point(200,102,20)]),1);
 assert.equal(selectedAverageGrade([point(0,102,0),point(200,100,20)]),-1);
 assert.equal(selectedAverageGrade([point(0,100,0),point(100,120,10),point(200,100,20)]),0);
 assert.equal(gradeLabel(1),'+1.0');assert.equal(gradeLabel(-1),'−1.0');assert.equal(gradeLabel(0),'0.0');assert.equal(gradeLabel(-.01),'0.0');
});
test('V13 selection grade withholds absent, stationary, short, or discontinuous measurements',()=>{
 for(const points of [[],[point(0,100,0)],[point(0,100,0),point(0,101,10)],[point(0,100,0),point(20,101,10)],[point(0,null,0),point(200,101,10)],[point(0,100,0),point(100,null,10),point(200,101,20)],[point(0,100,0),point(200,101,31)],[point(0,100,0),point(200,101,0)]])assert.equal(selectedAverageGrade(points),null);
 assert.equal(selectedAverageGrade([point(0,100,0),point(50,101,30)]),2);
 assert.equal(gradeLabel(null),'—');
});
