import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {mixedFeed,feedScenarios} from '../feed/feedModel';
import {climbResult} from '../scenario';
import {withV5Example,parseFeedV5,v5Collection,feedV5Scenarios,feedV5Ride,networkDiscovery} from '../feed/feedV5Model';

test('V5 combines known placement and personal best once, never borrowing current standings',()=>{
 const s=withV5Example(mixedFeed),e=s.entries[0],c=v5Collection(e,s);
 assert.equal(c.results.filter(r=>r.climb.id===e.ride.climbs[0].id).length,1);
 assert.equal(c.results[0].leaderboard?.rank,7);assert.equal(c.results[0].newBest,true);
 const absent=structuredClone(s);delete absent.workshopV5;
 assert.ok(v5Collection(absent.entries[0],absent).results.every(r=>!r.leaderboard));
 assert.equal(withV5Example(structuredClone(mixedFeed)).workshopV5,undefined);
});
test('personal podium needs complete comparable history and preserves ties',()=>{
 const s=structuredClone(feedV5Scenarios.find(s=>s.id==='personal-podium')!),e=s.entries[0];
 assert.deepEqual(v5Collection(e,s).results.map(r=>r.personalRank),[1,2,3]);
 const c=e.ride.climbs[1],duration=climbResult(e.ride,c).duration;
 c.history.push({date:'2016-08-18',duration});
 assert.equal(v5Collection(e,s).results.find(r=>r.climb.id===c.id)?.personalTied,true);
 s.workshopV5!.results.forEach(r=>delete r.personalHistoryComplete);
 assert.equal(v5Collection(e,s).results.find(r=>r.climb.id===c.id)?.personalRank,null);
});
test('all V5 menu scenarios validate and preserve a resolvable independent network effort',()=>{
 for(const source of [...feedScenarios,...feedV5Scenarios]){
  const s=withV5Example(source);assert.ok(parseFeedV5(s));
  s.entries.forEach(e=>assert.ok(v5Collection(e,s).visible.length<=2));
  const n=s.workshopV5?.network;if(!n)continue;
  assert.deepEqual(feedV5Ride(n.entry.ride.id),n.entry.ride);
  const d=networkDiscovery(n);assert.ok(d);assert.equal(d.profile.length,d.geometry!.coordinates.length);
  assert.equal(d.profile[0].d,0);assert.equal(d.profile.at(-1)!.d,d.length);
 }
 const ladder=feedV5Scenarios.find(s=>s.id==='leaderboard-10')!;
 assert.deepEqual(v5Collection(ladder.entries[0],ladder).results.map(r=>r.leaderboard!.rank),[1,2,3,4,5,6,7,8,9,10]);
});
test('V5 rejects unsupported awards and mismatched feature bindings',()=>{
 const s=structuredClone(withV5Example(mixedFeed));
 s.workshopV5!.results[0].leaderboard!.rank=11;
 assert.throws(()=>parseFeedV5(s),/leaderboard/i);
 const n=structuredClone(withV5Example(mixedFeed));n.workshopV5!.network!.climbId='absent';
 assert.throws(()=>parseFeedV5(n),/network.*climb/i);
 const duplicate=structuredClone(withV5Example(mixedFeed));duplicate.workshopV5!.results.push(duplicate.workshopV5!.results[0]);
 assert.throws(()=>parseFeedV5(duplicate),/unique/i);
});
test('V5 preserves V4 source and styling',()=>{
 for(const name of ['FeedV4.tsx','FeedV4Context.tsx','FeedV4Discovery.tsx','FeedV4DiscoveryMap.tsx','FeedV4Results.tsx','feed-v4.css','feedV4Model.ts'])assert.equal(readFileSync(new URL('../feed/'+name,import.meta.url),'utf8'),execFileSync('git',['show','4989f4ef8:web/portal/workshop/feed/'+name],{encoding:'utf8'}));
});
test('network bindings are checked against normalized recording identities',()=>{
 const s=structuredClone(withV5Example(mixedFeed)),n=s.workshopV5!.network!;
 n.entry.ride.climbs[0].id=' '+n.climbId+' ';n.climbId=' '+n.climbId+' ';
 assert.throws(()=>parseFeedV5(s),/matching climb/);
 const collision=structuredClone(withV5Example(mixedFeed));collision.workshopV5!.network!.entry.ride.id=' '+collision.entries[0].ride.id+' ';
 assert.throws(()=>parseFeedV5(collision),/own ride identity/);
});
