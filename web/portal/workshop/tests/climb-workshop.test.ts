import test from 'node:test';
import assert from 'node:assert/strict';
import {climbStudies, inspectClimb, parseClimbStudy, selectedTerrain} from '../climb/climbModel';

test('climb personal context belongs to the viewer, never the terrain source',()=>{
 const s=climbStudies[0], owner=inspectClimb(s,'rider'),visitor=inspectClimb(s,'visitor');
 assert.equal(owner.personal?.best,235);
 assert.equal(owner.personal?.rows.length,5);
 assert.equal(visitor.personal,undefined);
 assert.equal(inspectClimb(s,'signed-out').personal,undefined);
 assert.deepEqual(owner.board?.rows.map(r=>r.rank),[1,2,3,7]);
 assert.equal(owner.board?.rows.filter(r=>r.href).length,1);
});
test('climb imports require bound terrain and never inherit Vault or identity from an ID',()=>{
 const s=structuredClone(climbStudies[0]);
 assert.equal(parseClimbStudy(s).vault,undefined);
 s.terrainRideId='missing';
 assert.throws(()=>parseClimbStudy(s));
 const v=structuredClone(climbStudies.find(s=>s.id==='vault')!);
 v.vault!.climbId='unrelated';
 assert.throws(()=>parseClimbStudy(v));
});
test('terrain selection uses signed endpoint rise, keeps zero, and clears tiny selections',()=>{
 const p=[{d:0,elevation:10},{d:100,elevation:10},{d:200,elevation:5}];
 assert.equal(selectedTerrain(p,[0,1])?.grade,0);
 assert.equal(selectedTerrain(p,[1,2])?.grade,-5);
 assert.equal(selectedTerrain(p,[1,1]),null);
});
test('climb links preserve viewer permissions and return context',()=>{
 for(const viewer of ['rider','visitor','signed-out'] as const){
  const url=new URL(inspectClimb(climbStudies[0],viewer).board!.rows.find(r=>r.href)!.href!,'http://localhost');
  assert.equal(url.searchParams.get('viewer'),viewer==='rider'?'owner':'visitor');
  assert.equal(url.searchParams.get('climbOriginViewer'),viewer);
 }
});
test('leaderboard ordering follows supplied rank',()=>{
 const s=structuredClone(climbStudies[0]);
 s.feed!.workshopV6!.leaderboards.find(b=>b.climbId===s.climbId)!.rows.reverse();
 assert.equal(inspectClimb(s,'rider').board?.rows[0].rank,1);
});
