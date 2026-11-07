import test from 'node:test';
import assert from 'node:assert/strict';
import {profileV6Study,parseProfileV6,projectV6,studyForV6Viewer,restoreV6State} from '../profile/v6/profileV6Model';

test('V6 owner context binds positions and CAL to this rider and supplied hills or rides',()=>{
 const study=parseProfileV6(profileV6Study());
 const owner=projectV6(study,'owner');
 assert.equal(owner.economy?.positions.length,2);
 assert.equal(owner.summary?.distance,558200);
 assert.equal(owner.summary?.count,12);
 assert.equal(owner.economy?.positions[0].climbId,owner.standings[0].climbId);
 for(const change of [
  (s:any)=>s.economy.positions[0].riderId='another-rider',
  (s:any)=>s.economy.positions[0].climbId='invented-hill',
  (s:any)=>s.economy.positions[0].calDeposited=-1,
  (s:any)=>s.economy.positions.push(s.economy.positions[0]),
  (s:any)=>s.economy.positions[0].dung={state:'ready',amount:-4},
  (s:any)=>s.economy.rideCal[0].rideId='missing-ride',
  (s:any)=>s.economy.secret='unsupported',
  (s:any)=>s.economy.asOf='2026-01-01T00:00:00Z',
 ]){const s=profileV6Study();change(s);assert.throws(()=>parseProfileV6(s));}
});

test('V6 visitor projection and serialized preview data exclude owner economics',()=>{
 const study=profileV6Study();
 assert.equal(projectV6(study,'visitor').economy,null);
 const visitor=studyForV6Viewer(study,'visitor');
 assert.equal(visitor.economy,null);
 assert.equal(JSON.stringify(visitor).includes('calDeposited'),false);
 assert.equal(parseProfileV6(visitor).person?.name,'Alex Rivera');
 assert.equal(study.economy?.positions.length,2);
 assert.equal(restoreV6State(study,'visitor',{tab:'portfolio'}).tab,'overview');
 const privateStudy=profileV6Study('private');privateStudy.economy=study.economy;
 assert.throws(()=>parseProfileV6(privateStudy));
});

test('V6 absent economics and partial riding stay absent independently',()=>{
 for(const id of ['sparse','new-rider','private','no-economy']){
  const s=parseProfileV6(profileV6Study(id));assert.equal(projectV6(s,'owner').economy,null);
 }
 assert.equal(projectV6(profileV6Study('sparse'),'owner').summary,null);
 assert.equal(projectV6(profileV6Study('no-economy'),'owner').summary?.count,12);
 const s=profileV6Study();s.economy!.positions[0].dung=null;
 assert.equal(parseProfileV6(s).economy!.positions[0].dung,null);
});
