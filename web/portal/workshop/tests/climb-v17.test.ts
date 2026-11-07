import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {kitRoute} from '../entry';

test('V17 has an isolated kit route and preserves the earlier Climb route',()=>{
 assert.equal(kitRoute('?climb-preview=1&variant=climb-v17')?.title,'Climb V17');
 assert.equal(kitRoute('?climb-preview=1&variant=climb-v16'),undefined);
});

test('V17 ranks the fastest ascent per rider within the exact version and period',async()=>{
 const {climbState,climbData,leaderboardRows}=await import('../climb/climbV17Model');
 const state=climbState('?scenario=wises'),data=climbData(state);
 const rows=leaderboardRows(data,{tab:'overall',period:'all-time'});
 assert.equal(new Set(rows.map(r=>r.name)).size,rows.length);
 assert.equal(rows.find(r=>r.current)?.id,data.best?.id);
 assert.equal(rows.length,6,'the retained Wises corpus has six distinct riders');
 assert.ok(rows.every(r=>new URL(r.effortHref!,'http://local').searchParams.get('gates')==='v1'));
 assert.deepEqual(leaderboardRows(data,{tab:'qualified',period:'all-time'}),[],'measured is not verified');
 assert.ok(leaderboardRows(data,{tab:'overall',period:'2016'}).every(r=>r.id.includes('2016')||r.id.startsWith('board-')));
 const successor=climbData(climbState('?scenario=successor'));
 assert.equal(successor.version,2);
 assert.deepEqual(leaderboardRows(successor,{tab:'overall',period:'all-time'}),[],'publication never migrates earlier times');
 assert.equal(successor.history.length,0);
 assert.equal(successor.terrain.profile.at(-1)!.d,1057.96);
 assert.notDeepEqual(successor.geometry.coordinates.at(-1),data.geometry.coordinates.at(-1));
});

test('no-vault choices are explicit and visitor pages never acquire a current rider',async()=>{
 const {climbState,climbData,leaderboardRows}=await import('../climb/climbV17Model');
 for(const scenario of ['no-vault-rides','no-vault-empty']){
  const data=climbData(climbState(`?scenario=${scenario}`));
  assert.equal(data.hasVault,false);
  assert.equal(leaderboardRows(data,{tab:'overall',period:'all-time'}).length>0,scenario==='no-vault-rides');
 }
 for(const viewer of ['visitor','anon']){
  const data=climbData(climbState(`?viewer=${viewer}`));
  assert.equal(data.history.length,0);
  assert.ok(leaderboardRows(data,{tab:'overall',period:'all-time'}).every(r=>!r.current));
 }
});

test('V17 imports kit components, original effort data and no predecessor UI or CSS',()=>{
 const source=readFileSync(new URL('../climb/ClimbV17.tsx',import.meta.url),'utf8');
 assert.match(source,/from ['"]\.\.\/v15['"]/);
 assert.doesNotMatch(source,/ClimbV1[0-6]|climb-v1[0-6]\.css|Collect DUNG|Ride it to set the first time/);
});
