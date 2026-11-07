import test from 'node:test';
import assert from 'node:assert/strict';
import {filterClimbs,restoreCandidateState,candidateSnapshotKey,stateFromCandidateQuery,mapV4ExploreHref} from '../mapV4Model';
import {initialMapState,openClimb,closeClimb} from '../../mapModel';
import {wisesStudy} from '../../mapScenarios';

test('metric filters apply together to supplied measurements without inventing geometry',()=>{
 const boundsOnly={...wisesStudy.climbs[0],geometry:undefined,geometrySource:undefined,lengthM:1500,gradePct:9,riseM:135};
 const filters={distance:'1-2',grade:'8-12',rise:'100-200'};
 assert.deepEqual(filterClimbs([boundsOnly],filters,''),[boundsOnly]);
 assert.deepEqual(filterClimbs([{...boundsOnly,gradePct:7}],filters,''),[]);
 assert.equal(filterClimbs([boundsOnly],filters,'unmatched').length,0);
 assert.equal(filterClimbs([boundsOnly],filters,'')[0].geometry,undefined);
});
test('V4 filters survive detail return and query restoration without leaking to V3',()=>{
 const saved={...initialMapState(wisesStudy),filters:{distance:'1-2',grade:'8-12',rise:'100-200'},camera:{center:[-75.22,40.05] as [number,number],zoom:13.6}};
 const back=closeClimb(openClimb(saved,wisesStudy.originId!));
 const restored=restoreCandidateState(wisesStudy,back,'map-v4');
 assert.deepEqual(restored.filters,saved.filters);assert.deepEqual(restored.camera,saved.camera);
 assert.deepEqual(stateFromCandidateQuery(wisesStudy,new URLSearchParams('variant=map-v4'),back).filters,saved.filters);
 assert.equal(restoreCandidateState(wisesStudy,back,'map-v3').filters,undefined);
 assert.notEqual(candidateSnapshotKey('wises','map-v4'),candidateSnapshotKey('wises','map-v3'));
});
test('unknown filter values and another study cannot poison a restored Map',()=>{
 const saved={...initialMapState(wisesStudy),filters:{distance:'bad',grade:'8-12',rise:'bad'}};
 assert.deepEqual(restoreCandidateState(wisesStudy,saved,'map-v4').filters,{distance:'any',grade:'8-12',rise:'any'});
 assert.deepEqual(restoreCandidateState(wisesStudy,{...saved,studyId:'other'},'map-v4').filters,{distance:'any',grade:'any',rise:'any'});
});
test('arriving from another hill clears old filters so that hill remains recognizable',()=>{
 const next=wisesStudy.climbs.find(c=>c.id!==wisesStudy.originId)!;
 const saved={...initialMapState(wisesStudy),filters:{distance:'0-1',grade:'12+',rise:'200+'}};
 const restored=stateFromCandidateQuery(wisesStudy,new URLSearchParams({variant:'map-v4',origin:next.id}),saved);
 assert.equal(restored.selectedId,next.id);
 assert.deepEqual(restored.filters,{distance:'any',grade:'any',rise:'any'});
});
test('a fresh Explore entry reveals the same origin even when old filters excluded it',()=>{
 const saved={...initialMapState(wisesStudy),selectedId:null,filters:{distance:'any',grade:'12+',rise:'any'},camera:{center:[-75.22,40.05] as [number,number],zoom:14}};
 const query=new URL(mapV4ExploreHref(wisesStudy.originId!),'http://localhost').searchParams;
 const restored=stateFromCandidateQuery(wisesStudy,query,saved);
 assert.equal(restored.selectedId,wisesStudy.originId);
 assert.deepEqual(restored.filters,{distance:'any',grade:'any',rise:'any'});
 assert.equal(restored.camera,null);
 const regular=stateFromCandidateQuery(wisesStudy,new URLSearchParams({variant:'map-v4',origin:wisesStudy.originId!}),saved);
 assert.deepEqual(regular.filters,saved.filters);assert.deepEqual(regular.camera,saved.camera);
});
