import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mixedFeed} from '../feed/feedModel';
import {withV7Example,v7NetworkItems,allV7Scenarios,parseFeedV7,rekeyV7Feed} from '../feed/feedV7Model';
test('the featured rider, place and time are the same result shown in the leaderboard',()=>{
 const original=JSON.stringify(mixedFeed);
 const items=v7NetworkItems(withV7Example(mixedFeed));
 assert.ok(items.length);
 for(const item of items){
  const row=item.board.rows.find(row=>row.name===item.row.name);
  assert.ok(row,'featured rider must be in this leaderboard');
  assert.equal(item.row.rank,row.rank,'featured placement must agree with the leaderboard');
  assert.equal(item.row.duration,row.duration,'featured time must agree with the leaderboard');
 }
 assert.equal(JSON.stringify(mixedFeed),original,'preserved examples are never mutated');
 for(const scenario of allV7Scenarios()){
  const parsed=parseFeedV7(JSON.parse(JSON.stringify(scenario)));
  const imported=rekeyV7Feed(parsed,scenario.id);
  for(const item of v7NetworkItems(imported))assert.ok(item.terrainEntry.ride.id.startsWith('feed-local-'));
  for(const item of v7NetworkItems(parsed))assert.deepEqual(item.row,item.board.rows.find(row=>row.id===item.feature.rowId));
 }
 const legacy=structuredClone(withV7Example(mixedFeed));
 legacy.workshopV7!.features[0].terrainRideId=legacy.workshopV5!.network!.entry.ride.id;
 legacy.workshopV6!.features=[];
 assert.ok(v7NetworkItems(rekeyV7Feed(parseFeedV7(legacy),'legacy'))[0].terrainEntry.ride.id.endsWith('-network'));
 const missing=structuredClone(withV7Example(mixedFeed));missing.workshopV7!.features[0].rowId='missing';
 assert.throws(()=>parseFeedV7(missing),/resolve/);
 const collision=structuredClone(withV7Example(mixedFeed));collision.workshopV6!.features[0].entry.id=collision.entries[0].id;
 assert.throws(()=>parseFeedV7(collision),/unique entry/);
 const bound=structuredClone(withV7Example(mixedFeed));bound.workshopV7!.riders[0].commentKeys.push(bound.workshopV7!.riders[1].commentKeys[0]);
 assert.throws(()=>parseFeedV7(bound),/comment reference|unique/);

});
