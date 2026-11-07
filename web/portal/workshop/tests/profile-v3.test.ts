import test from 'node:test';
import assert from 'node:assert/strict';
import {profileStudy,parseProfileStudy,profileProjection,allowedTab,profileV3Key,restoreProfileState,resolveProfileStudy,canonicalClimb} from '../profile/v3/profileV3Model';
test('recorded Profile keeps measured efforts without inventing sporting ranks or identity',()=>{
 const v=profileProjection(profileStudy('recorded'),'owner');
 assert.equal(v.name,'Rider');assert.equal(v.portrait,undefined);
 assert.deepEqual(v.efforts.map(e=>e.duration),[235,82,251]);
 assert.ok(v.efforts.every(e=>!('rank' in e)));
 assert.equal(v.rides.length,1);assert.equal(v.totalRides,1);
});
test('private Profile projects no identity, geography or results; visitors have only Overview',()=>{
 const v=profileProjection(profileStudy('private'),'owner');
 assert.equal(v.name,null);assert.equal(v.recording,null);assert.deepEqual(v.efforts,[]);
 assert.equal(allowedTab('training','visitor'),'overview');assert.equal(allowedTab('portfolio','owner'),'portfolio');
});
test('Profile imports validate the recording and preserve missing channels',()=>{
 const s=profileStudy('recorded');s.recording!.ride.samples[0].lat=100;
 assert.throws(()=>parseProfileStudy(s));
 const sparse=profileProjection(profileStudy('sparse'),'owner');
 assert.equal(sparse.totals?.power,null);
 assert.ok(sparse.efforts.every(e=>e.grade===null));
});
test('tab state and imports use a V3-only namespace',()=>{
 assert.equal(profileV3Key('recorded'),'br-profile-v3:recorded');
 assert.throws(()=>parseProfileStudy({...profileStudy('recorded'),candidate:'profile-v2'}));
});
test('custom imports survive re-entry by their exact ID and private deep links cannot blank the page',()=>{
 const custom={...profileStudy('recorded'),id:'my-recording'};
 assert.equal(resolveProfileStudy('my-recording',JSON.stringify(custom)).id,'my-recording');
 assert.throws(()=>resolveProfileStudy('missing',null));
 assert.equal(restoreProfileState(profileStudy('private'),'owner',{detail:'ride'}).detail,null);
 assert.equal(restoreProfileState(profileStudy('recorded'),'visitor',{tab:'portfolio',detail:'made-up'}).tab,'overview');
});

test('geographic destinations require the retained climb geometry, not an imported short ID',()=>{
 const s=profileStudy('recorded');
 assert.ok(canonicalClimb('43f15658',s.recording!));
 s.recording!.ride.samples[0].lat+=1;
 assert.equal(canonicalClimb('43f15658',s.recording!),undefined);
});
