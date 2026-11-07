import test from 'node:test';
import assert from 'node:assert/strict';
import {profileGlyph} from '../mapV5Profile';

const climb=(rise:number,length=1000)=>({lengthM:length,profile:[{distanceM:0,elevationM:20},{distanceM:length,elevationM:20+rise}]});
test('list profiles preserve comparative grade with the same fourfold vertical exaggeration',()=>{
 const gentle=profileGlyph(climb(40)),steep=profileGlyph(climb(100));
 assert.ok(gentle&&steep);
 const slope=(p:typeof gentle)=>Math.abs((p.points[1][1]-p.points[0][1])/(p.points[1][0]-p.points[0][0]));
 assert.ok(Math.abs(slope(steep)/slope(gentle)-2.5)<1e-9);
 assert.ok(Math.abs(slope(gentle)-.04*4)<1e-9);
 const extreme=profileGlyph(climb(700))!;
 assert.ok(extreme.points.every(([x,y])=>x>=0&&x<=extreme.width&&y>=0&&y<=extreme.height));
});
test('profile uses supplied samples and leaves missing geometry absent',()=>{
 assert.equal(profileGlyph({lengthM:1000}),null);
 const input={lengthM:1000,profile:[{distanceM:0,elevationM:20},{distanceM:400,elevationM:80},{distanceM:600,elevationM:70},{distanceM:1000,elevationM:100}]};
 const result=profileGlyph(input)!;
 assert.equal(result.points.length,input.profile.length);
 assert.ok(result.points[2][1]>result.points[1][1]);
 assert.equal(profileGlyph({lengthM:0,profile:input.profile}),null);
});
