import test from 'node:test';
import assert from 'node:assert/strict';
import {parseMapV6Study,publicLeader} from '../mapV6Leaderboard';

// Synthetic test data only; never included in workshop scenarios.
const id='43f15658-a824-438d-9925-e61c67ddabe9';
const study=()=>({version:1,id:'test',label:'Test',source:'Unit test',climbs:[{
 id,name:'Test climb',source:'Unit test',lengthM:1000,riseM:80,gradePct:8,bounds:[-75.25,40.04,-75.24,40.05],
 publicLeaderboard:{sourceUrl:`https://api.boulderroller.xyz/climbs/${id}/leaderboard`,capturedAt:'2026-09-13T21:27:00Z',
  response:{climb_id:id,kom_holder:'test-wallet',kom_time_s:120,entries:[{wallet:'test-wallet',position:1,competition_rank:1,best_time_seconds:120,tie_size:1,is_tied:false}]}}
}]});
test('rejects a public holder snapshot belonging to another climb',()=>{
 const input=study();input.climbs[0].publicLeaderboard.response.climb_id='another-climb';
 assert.throws(()=>parseMapV6Study(input),/same canonical climb/);
});
test('only the explicit public holder receives first-place chrome',()=>{
 const input=study(),c=input.climbs[0];
 const parsed=parseMapV6Study(input);
 assert.equal(publicLeader(parsed.climbs[0])?.timeSeconds,120);
 assert.equal(publicLeader(parsed.climbs[0])?.wallet,'test-wallet');
 c.publicLeaderboard.response.entries.unshift({wallet:'other-test-wallet',position:2,competition_rank:2,best_time_seconds:130,tie_size:1,is_tied:false});
 assert.equal(publicLeader(parseMapV6Study(input).climbs[0])?.wallet,'test-wallet');
});
test('withheld and empty public holders stay absent without promoting a visible row',()=>{
 const input=study() as any,b=input.climbs[0].publicLeaderboard.response;
 b.kom_holder=null;b.kom_time_s=null;b.entries[0].position=2;b.entries[0].competition_rank=2;
 assert.equal(publicLeader(parseMapV6Study(input).climbs[0]),null);
 b.entries=[];assert.equal(publicLeader(parseMapV6Study(input).climbs[0]),null);
 delete input.climbs[0].publicLeaderboard;
 assert.equal(publicLeader(parseMapV6Study(input).climbs[0]),null);
});
test('rejects mismatched holder times, unbound sources and unsupported identity',()=>{
 const mutations=[
  (s:any)=>{s.climbs[0].publicLeaderboard.response.kom_time_s=119;},
  (s:any)=>{s.climbs[0].publicLeaderboard.sourceUrl='https://example.com/leaderboard';},
  (s:any)=>{s.climbs[0].publicLeaderboard.sourceUrl+='?viewer=private';},
  (s:any)=>{s.climbs[0].publicLeaderboard.response.entries[0].avatar_url='http://example.com/rider.jpg';},
  (s:any)=>{s.climbs[0].publicLeaderboard.response.entries[0].competition_rank=2;},
  (s:any)=>{s.climbs[0].publicLeaderboard.response.kom_holder=null;},
 ];
 for(const mutate of mutations){const input=study();mutate(input);assert.throws(()=>parseMapV6Study(input));assert.equal(publicLeader(input.climbs[0] as any),null);}
});
test('preserves ties and original positions, and does not mistake viewer standing for the public holder',()=>{
 const input=study() as any,e=input.climbs[0].publicLeaderboard.response.entries[0];e.tie_size=2;e.is_tied=true;e.position=2;
 assert.equal(publicLeader(parseMapV6Study(input).climbs[0])?.tied,true);
 delete input.climbs[0].publicLeaderboard;
 input.climbs[0].standing={viewerId:'test-viewer',name:'Test viewer',rank:1,timeSeconds:120,source:'Unit test'};
 assert.equal(publicLeader(input.climbs[0]),null);
});
test('rejects fractional seconds and contradictory tie metadata from imports',()=>{
 for(const mutate of [
  (s:any)=>{s.climbs[0].publicLeaderboard.response.kom_time_s=.4;s.climbs[0].publicLeaderboard.response.entries[0].best_time_seconds=.4;},
  (s:any)=>{s.climbs[0].publicLeaderboard.response.entries[0].is_tied=true;},
  (s:any)=>{delete s.climbs[0].publicLeaderboard.response.entries[0].tie_size;},
  (s:any)=>{s.climbs[0].publicLeaderboard.response.entries[0].display_name='Not supplied by this endpoint';},
 ]){const input=study();mutate(input);assert.throws(()=>parseMapV6Study(input));}
});
