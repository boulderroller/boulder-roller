import test from 'node:test';
import assert from 'node:assert/strict';
import {selectionMove, candidateHref, candidateSnapshotKey,isCurrentMapMessage} from '../mapV3Model';
import {wisesStudy} from '../../mapScenarios';
test('selecting a nearby visible hill reframes without changing neighborhood scale',()=>{
 const a=wisesStudy.climbs.find(c=>c.name==='Wises Mill Road')!,b=wisesStudy.climbs.find(c=>c.name==='Valley Green Road')!;
 const camera={center:[-75.22,40.055] as [number,number],zoom:13.7};
 const first=selectionMove(a,camera,{width:1440,height:944,listOpen:false}),second=selectionMove(b,camera,{width:1440,height:944,listOpen:false});
 assert.equal(first.zoom,13.7);assert.equal(second.zoom,13.7);assert.notDeepEqual(first.center,second.center);
 assert.ok(second.offset[0]>0);assert.ok(second.offset[1]<0);
});
test('phone selection targets exposed geography above the inspection sheet',()=>{
 const move=selectionMove(wisesStudy.climbs[0],{center:[-75.22,40.05],zoom:14},{width:390,height:792,listOpen:false});
 assert.equal(move.zoom,14);assert.equal(move.offset[0],0);assert.ok(move.offset[1]<-80);
});
test('V3 destinations and snapshots cannot inherit V2 camera storage',()=>{
 const href=candidateHref(wisesStudy,'rider',wisesStudy.originId!,wisesStudy.originId,'map-v3');
 assert.equal(new URL(href,'http://localhost').searchParams.get('variant'),'map-v3');
 assert.notEqual(candidateSnapshotKey('wises','map-v3'),candidateSnapshotKey('wises','map-v2'));
 assert.equal(candidateSnapshotKey('wises','map-v2'),'br-map-v2:wises');
});
test('a queued camera message cannot cross candidates or scenario revisions',()=>{
 const context={variant:'map-v3' as const,revision:4,studyId:'wises'};
 assert.equal(isCurrentMapMessage({variant:'map-v2',revision:4,snapshot:{studyId:'wises'}},context),false);
 assert.equal(isCurrentMapMessage({variant:'map-v3',revision:3,snapshot:{studyId:'wises'}},context),false);
 assert.equal(isCurrentMapMessage({variant:'map-v3',revision:4,snapshot:{studyId:'other'}},context),false);
 assert.equal(isCurrentMapMessage({variant:'map-v3',revision:4,snapshot:{studyId:'wises'}},context),true);
});
