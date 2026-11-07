import test from 'node:test';
import assert from 'node:assert/strict';
import {profileGlyph} from '../mapV7Profile';
import {readCandidate,candidateSnapshotKey} from '../mapV7Model';

test('compact traces disclose the same twofold vertical exaggeration for every climb',()=>{
 const input=(rise:number)=>({lengthM:1000,profile:[{distanceM:0,elevationM:20},{distanceM:1000,elevationM:20+rise}]});
 const gentle=profileGlyph(input(40))!,steep=profileGlyph(input(100))!;
 const slope=(p:typeof gentle)=>Math.abs((p.points[1][1]-p.points[0][1])/(p.points[1][0]-p.points[0][0]));
 assert.ok(Math.abs(slope(gentle)-.04*2)<1e-9);
 assert.ok(Math.abs(slope(steep)/slope(gentle)-2.5)<1e-9);
});
test('V7 has its own candidate and snapshot namespace',()=>{
 const candidate=readCandidate('map-v7');
 assert.equal(candidate,'map-v7');
 assert.equal(candidateSnapshotKey('wises',candidate),'br-map-v7:wises');
 assert.equal(candidateSnapshotKey('wises','map-v5'),'br-map-v5:wises');
 assert.equal(candidateSnapshotKey('wises','map-v6'),'br-map-v6:wises');
});
