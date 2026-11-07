import test from 'node:test';
import assert from 'node:assert/strict';
import {profileV5Study,parseProfileV5,projectV5,restoreV5State,initialV5State} from '../profile/v5/profileV5Model';

test('V5 keeps the V4 rider and complete period while binding new story content to specific rides',()=>{
 const s=profileV5Study(),p=projectV5(parseProfileV5(s),'owner');
 assert.equal(p.person?.name,'Alex Rivera');assert.equal(p.summary?.count,12);
 assert.equal(p.summary?.distance,558200);assert.equal(p.summary?.climbing,6770);
 assert.equal(p.rides[0].photo,'coffee');assert.equal(p.rides[2].moment?.climbId,p.rides[2].climbIds[0]);
 assert.equal(p.rides[2].moment?.timeSeconds,212);
 assert.equal(p.days.length,28);assert.equal(p.days.reduce((n,d)=>n+d.rides.length,0),12);
});
test('V5 imports reject unsupported personal data, unsafe images and unbound results',()=>{
 assert.throws(()=>parseProfileV5({...profileV5Study('private'),hidden:{identity:'private'}}));
 const s=profileV5Study();s.rides[0].photo='https://example.test/untrusted.png';assert.throws(()=>parseProfileV5(s));
 const bad=profileV5Study();bad.rides[2].moment!.climbId='invented';assert.throws(()=>parseProfileV5(bad));
 const unknown=profileV5Study();unknown.rides[2].moment!.kind='rank' as any;assert.throws(()=>parseProfileV5(unknown));
});
test('V5 partial and private cases retain absence, and dates and restored state stay coherent',()=>{
 const s=profileV5Study('sparse');assert.equal(projectV5(s,'owner').summary,null);
 assert.equal(s.rides.some(r=>r.photo||r.moment),false);
 const p=profileV5Study('private');assert.equal(projectV5(p,'visitor').person,null);
 assert.equal(restoreV5State(p,'visitor',{...initialV5State(),tab:'portfolio',detailId:'alex-ride-1'}).detailId,null);
 assert.equal(restoreV5State(p,'visitor',{tab:'training'}).tab,'overview');
 const offset=profileV5Study();offset.rides[0].date='2026-09-14T00:30:00+02:00';
 assert.equal(projectV5(parseProfileV5(offset),'owner').summary?.count,12);
});
