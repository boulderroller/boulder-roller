import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {mixedFeed} from '../feed/feedModel';
import {climbResult} from '../scenario';
import {discoveryGrade,achievementCollection,withV4Example,parseFeedV4,feedV4Scenarios,feedV4Ride} from '../feed/feedV4Model';

test('achievement collections contain every personal best and preview at most two',()=>{
 for(const [source,count] of [[withV4Example(mixedFeed),1],...feedV4Scenarios.map((s,i)=>[s,i===0?3:10] as const)] as const){
  const entry=source.entries[0], set=achievementCollection(entry);
  assert.equal(set.bests.length,count); assert.equal(set.visible.length,Math.min(count,2));
  assert.equal(new Set(set.results.map(r=>r.climb.id)).size,entry.ride.climbs.length);
  assert.ok(set.bests.every(r=>r.result.improvement!>0));
  assert.deepEqual(entry.ride.ride.samples,mixedFeed.entries[0].ride.ride.samples);
 }
 const entry=structuredClone(mixedFeed.entries[0]);
 entry.ride.climbs.forEach(c=>{c.history=[{date:'2016-08-20',duration:climbResult(entry.ride,c).duration}];});
 assert.equal(achievementCollection(entry).bests.length,0);
});
test('achievement studies resolve their own recording and declare supplied history',()=>{
 for(const s of feedV4Scenarios){
  assert.equal(parseFeedV4(s).entries[0].ride.source.history,'illustrative');
  assert.equal(feedV4Ride(s.entries[0].ride.id),s.entries[0].ride);
 }
});
test('enriched discovery remains explicit and validates its geometry',()=>{
 const bundled=withV4Example(mixedFeed);
 assert.equal(bundled.workshopV3?.world?.discovery?.locality,'Philadelphia, Pennsylvania');
 const imported=structuredClone(mixedFeed);
 assert.equal(withV4Example(imported).workshopV3,undefined);
 const copy=structuredClone(bundled);copy.workshopV3!.world!.discovery!.geometry!.coordinates[0][0]=200;
 assert.throws(()=>parseFeedV4(copy),/discovery.*coordinates/i);
 const absent=structuredClone(bundled);delete absent.workshopV3!.world!.discovery!.geometry;delete absent.workshopV3!.world!.discovery!.locality;
 assert.equal(parseFeedV4(absent).workshopV3!.world!.discovery!.locality,undefined);
});
test('V4 preserves every V3 presentation and context source',()=>{
 for(const name of ['FeedV3.tsx','FeedV3Context.tsx','FeedV3Map.tsx','FeedV3Results.tsx','FeedV3WorldMap.tsx','feed-v3.css','feedV3Model.ts'])assert.equal(readFileSync(new URL('../feed/'+name,import.meta.url),'utf8'),execFileSync('git',['show','aeca6c5b9:web/portal/workshop/feed/'+name],{encoding:'utf8'}));
});

test('partial discovery profiles do not imply whole-climb grade',()=>{
 const d={name:'Partial',source:'test',length:1000,gain:40,profile:[{d:400,elevation:100},{d:600,elevation:140}]};
 assert.equal(discoveryGrade(d),null);
 assert.equal(discoveryGrade({...d,profile:[{d:0,elevation:100},{d:1000,elevation:140}]}),4);
});
