import test from 'node:test';
import assert from 'node:assert/strict';
import {profileV4Study,parseProfileV4,projectV4,restoreV4State,initialV4State} from '../profile/v4/profileV4Model';

test('V4 composes one illustrative person across distinct rides and canonical climb standings',()=>{
 const s=profileV4Study('rider'),p=projectV4(s,'owner');
 assert.equal(s.source.kind,'illustrative');assert.equal(p.person?.name,'Alex Rivera');
 assert.equal(new Set(p.rides.map(r=>r.id)).size,12);
 assert.deepEqual(p.standings.map(r=>r.competitionRank),[1,3,7]);
 assert.equal(p.summary?.count,12);assert.ok(p.days.reduce((a,d)=>a+d.rides.length,0)===12);
 assert.ok(p.standings.every(r=>r.riderId===p.person!.id));
});
test('private profiles cannot carry hidden identity/history and public views clamp owner tabs',()=>{
 const s=profileV4Study('private');assert.equal(projectV4(s,'visitor').person,null);
 assert.throws(()=>parseProfileV4({...s,recording:{riderName:'Hidden rider',coordinates:[[1,2]]}}));
 assert.throws(()=>parseProfileV4({...s,person:profileV4Study('rider').person}));
 assert.equal(restoreV4State(s,'visitor',{...initialV4State(),tab:'portfolio',detailId:'ride-1'}).tab,'overview');
 assert.equal(restoreV4State(s,'visitor',{...initialV4State(),detailId:'ride-1'}).detailId,null);
});
test('partial history stays partial and an unknown sporting rank stays absent',()=>{
 const s=profileV4Study('sparse');assert.equal(projectV4(s,'owner').summary,null);
 const full=profileV4Study('rider');full.standings[0].competitionRank=null;
 assert.equal(projectV4(parseProfileV4(full),'owner').standings[0].competitionRank,null);
});
test('imports reject wrong rider, fabricated climb association, duplicate rides and unsafe media',()=>{
 const s=profileV4Study('rider');s.standings[0].riderId='another-person';assert.throws(()=>parseProfileV4(s));
 const bad=profileV4Study('rider');bad.standings[0].climbId='invented';assert.throws(()=>parseProfileV4(bad));
 const duplicate=profileV4Study('rider');duplicate.rides.push(duplicate.rides[0]);assert.throws(()=>parseProfileV4(duplicate));
 const media=profileV4Study('rider');media.person!.portrait='javascript:alert(1)';assert.throws(()=>parseProfileV4(media));
 const period=profileV4Study('rider');period.history.to='2027-09-13';assert.throws(()=>parseProfileV4(period));
});

test('timezone imports use the same UTC day for display, totals and selection',()=>{
 const s=profileV4Study('rider');s.rides[0].date='2026-09-14T00:30:00+02:00';
 const parsed=parseProfileV4(s),model=projectV4(parsed,'owner');
 assert.equal(parsed.rides[0].date,'2026-09-13T22:30:00.000Z');
 assert.equal(model.summary?.count,12);
 assert.equal(model.days.find(d=>d.date==='2026-09-13')?.rides.length,1);
});
