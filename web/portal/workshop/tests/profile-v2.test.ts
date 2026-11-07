import {test} from 'node:test';
import assert from 'node:assert/strict';
import {profileScenario,profileView,parseProfileImport} from '../profile/profileModel';
test('Profile V2 binds standing to the viewed rider and refuses compatibility place',()=>{
 const own=profileView(profileScenario('owner'));
 assert.equal(own.identity?.name,'Dung Beetle Phoenix');
 assert.equal(own.standings[0].name,'Manayunk Wall');
 assert.equal(own.standings[0].time,610);
 assert.equal(own.standings[0].place,null);
 assert.equal(profileView(profileScenario('public')).standings.length,0);
});
test('private profiles disclose no redacted identity, ride history, or zero sentinel totals',()=>{
 const view=profileView(profileScenario('private'));
 assert.equal(view.private,true);assert.equal(view.identity,null);
 assert.deepEqual(view.rides,[]);assert.deepEqual(view.standings,[]);assert.equal(view.totalRides,null);
});
test('public history is a visible subset and contains no private economics',()=>{
 const view=profileView(profileScenario('public'));
 assert.equal(view.identity?.name,'Tim Trail');assert.equal(view.totalRides,12);assert.equal(view.rides.length,3);
 assert.equal(JSON.stringify(view).includes('cal_earned'),false);assert.equal(JSON.stringify(view).includes('wallet'),false);
});
test('imports are bound to the room, candidate, scenario and viewer',()=>{
 const own=profileScenario('owner');assert.deepEqual(parseProfileImport(own),own);
 for(const edit of [{room:'portfolio'},{candidate:'profile-v1'},{viewer:'public'},{route:'/profile?tab=training'}])assert.throws(()=>parseProfileImport({...own,...edit}));
});
test('nested public privacy and hidden profile modules fail closed',()=>{
 for(const mode of ['nested','module']){
  const s=profileScenario('public'),b=s.responses['GET /users/tim/profile'] as any;
  if(mode==='nested')b.profile.privacy.can_view=false;else b.modules.find((m:any)=>m.key==='profile').state='hidden';
  const view=profileView(parseProfileImport(s));assert.equal(view.private,true);assert.equal(view.identity,null);assert.deepEqual(view.rides,[]);
 }
});
test('accepted dates normalize before month filtering',()=>{
 const s=profileScenario('owner');(s.responses['GET /users/me'] as any).created_at='May 4, 2026';(s.responses['GET /rides?limit=400'] as any[])[0].started_at='May 4, 2026';
 const view=profileView(parseProfileImport(s));assert.match(view.identity!.since!,/^2026-05-04T/);assert.match(view.rides[0].date!,/^2026-05-04T/);
});
import {retainProfileScenario} from '../profile/profileModel';
test('same data keeps Profile history selection stable across room return and availability messages',()=>{
 const previous=profileScenario('owner'),message=structuredClone(previous);assert.equal(retainProfileScenario(previous,message),previous);
 const changed=structuredClone(previous);changed.label='Imported';assert.equal(retainProfileScenario(previous,changed),changed);
});
import {compatibleProfileDetail} from '../profile/profileModel';
test('detail links never substitute retained recordings for public or imported summaries',()=>{
 const own=profileScenario('owner');assert.equal(compatibleProfileDetail(own,'/rides/ride-1'),true);
 assert.equal(compatibleProfileDetail(profileScenario('public'),'/rides/ride-1'),false);
 const edited=structuredClone(own);(edited.responses['GET /rides?limit=400'] as any[])[0].title='Imported ride';assert.equal(compatibleProfileDetail(edited,'/rides/ride-1'),false);
 assert.equal(compatibleProfileDetail(own,'/rides/unknown'),false);
});
test('missing vault IDs cannot bind a time to an unrelated climb',()=>{
 const s=profileScenario('owner');(s.responses['GET /users/me/leaderboard-positions'] as any).positions=[{best_time_seconds:123}];s.responses['GET /climbs/list']={climbs:[{id:'unrelated',name:'Unrelated'}]};assert.deepEqual(profileView(s).standings,[]);
});
test('recent-rides module privacy denial hides that history',()=>{
 const s=profileScenario('public');(s.responses['GET /users/tim/profile'] as any).recent_rides.privacy.can_view=false;const view=profileView(s);assert.deepEqual(view.rides,[]);assert.equal(view.historyAvailable,false);
});
test('matching ID alone does not link Manayunk to a different retained Climb specimen',()=>{
 assert.equal(compatibleProfileDetail(profileScenario('owner'),'/climbs/climb-1'),false);
});
import {profileDestination} from '../profile/profileNavigation';
test('private Profile tabs restore their own workshop owner and candidate state',()=>{
 for(const room of ['rides','training','portfolio'])assert.equal(profileDestination(profileScenario('owner'),'/profile?tab='+room)?.restore,true);
 for(const room of ['training','portfolio'])assert.equal(profileDestination(profileScenario('public'),'/profile?tab='+room)?.page,'access');
});
