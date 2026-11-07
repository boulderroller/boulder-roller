import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mixedFeed} from '../feed/feedModel';
import {v6RideHref,pageAfter,parseFeedV6,withV6Example,feedV6Scenarios,v6NetworkTerrain} from '../feed/feedV6Model';

test('V6 gives ride, achievement, climb and analysis distinct destinations',()=>{
 const entry=mixedFeed.entries[0],climb=entry.ride.climbs[0].id;
 const url=(view?:'overview'|'analysis'|'vault')=>new URL(v6RideHref(entry,climb,view),'http://localhost');
 assert.equal(url().searchParams.get('view'),'overview');
 assert.equal(url('vault').searchParams.get('view'),'vault');
 assert.equal(url('analysis').searchParams.get('view'),'analysis');
 assert.equal(url().searchParams.get('variant'),'candidate-v13');
});
test('feed pages do not repeat or silently restart a missing cursor',()=>{
 const entries=Array.from({length:23},(_,i)=>({...mixedFeed.entries[0],id:`ride-${i}`}));
 const first=pageAfter(entries,null,8),second=pageAfter(entries,first.nextCursor,8),last=pageAfter(entries,second.nextCursor,8);
 assert.equal(new Set([...first.items,...second.items,...last.items].map(e=>e.id)).size,23);
 assert.equal(last.nextCursor,null);
 assert.throws(()=>pageAfter(entries,'missing',8),/cursor/i);
});
test('all V6 scenarios round-trip and network links require supplied recordings',()=>{
 for(const scenario of [withV6Example(mixedFeed),...feedV6Scenarios]) assert.equal(parseFeedV6(JSON.parse(JSON.stringify(scenario))).id,scenario.id);
 const bad=structuredClone(withV6Example(mixedFeed));
 bad.workshopV6!.leaderboards[0].rows[0].rideId='missing-recording';
 assert.throws(()=>parseFeedV6(bad),/recording/i);
});

test("network terrain keeps a climb with stationary samples",()=>{
 for(const feature of feedV6Scenarios.find(s=>s.id==='network-3')!.workshopV6!.features) {
  const terrain=v6NetworkTerrain(feature);assert.ok(terrain);assert.ok(terrain.profile.length>2);assert.ok(terrain.geometry);assert.equal(terrain.geometry.coordinates.length,terrain.profile.length);
 }
});
