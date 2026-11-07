import {test} from 'node:test';
import assert from 'node:assert/strict';
import {baselineRooms,baselineScenario,baselineJourney,parseBaselineImport,baselineStorageKey,routeOwner,responseKey,withBaselineRoute} from '../baseline/model';
import {fixtureResponse,selectFixture} from '../baseline/runtime';
test('each retained room selects its own supported candidate and scenario',()=>{
 for(const room of baselineRooms){const scenario=baselineScenario(room.id,room.scenarios[0].id);assert.equal(scenario.room,room.id);assert.equal(scenario.candidate,`${room.id}-v1`);}
 assert.throws(()=>baselineScenario('guide','loading'));
 assert.equal(routeOwner('/profile?tab=training'),'training');
 assert.equal(routeOwner('/athletes/tim?tab=portfolio'),'profile');
 assert.equal(routeOwner('/activities/ride-1/analyze'),'legacy-analysis');
});
test('read exports retain stream types and cannot authorize writes',async()=>{
 const power=responseKey(new URL('http://local/api/rides/ride-1/streams?type=power'));
 const cadence=responseKey(new URL('http://local/api/rides/ride-1/streams?type=cadence'));
 assert.notEqual(power,cadence);
 const s={...baselineScenario('portfolio','balances'),responses:{'GET /privacy/settings':{success:true}}};selectFixture(s);
 assert.equal((await fixtureResponse(new URL('http://local/api/privacy/settings'),'DELETE')).status,503);
 selectFixture({...baselineScenario('public-rider','public'),responses:{'GET /portfolio/snapshot':{private:true}}});
 assert.equal((await fixtureResponse(new URL('http://local/api/portfolio/snapshot'),'GET')).status,503);
});
test('empty and establishing scenarios use compatible supplied responses',async()=>{
 const read=async(path:string)=>(await fixtureResponse(new URL('http://local/api'+path),'GET')).json();
 selectFixture(baselineScenario('rides','empty'));assert.deepEqual(await read('/rides'),[]);
 selectFixture(baselineScenario('rides','library'));assert.ok((await read('/rides')).some((r:any)=>r.attestation_status==='processing'));
 selectFixture(baselineScenario('portfolio','empty'));assert.deepEqual((await read('/portfolio/snapshot')).portfolio.stakedPositions,[]);
 selectFixture(baselineScenario('training','establishing'));assert.equal((await read('/analytics/fitness')).threshold_state,'establishing');
 selectFixture(baselineScenario('profile','private'));const profile=await read('/users/private/profile');assert.equal(profile.profile.is_public,false);assert.equal(profile.recent_rides.count,0);
});
test('explicit rider and tab destinations cannot restore unrelated private state',()=>{
 assert.equal(withBaselineRoute(baselineScenario('settings','identity'),'/settings?tab=alerts').route,'/settings?tab=alerts');
 assert.throws(()=>withBaselineRoute(baselineScenario('profile','owner'),'/athletes/tim'));
 assert.equal(withBaselineRoute(baselineScenario('profile','public'),'/athletes/tim').viewer,'public');
 assert.throws(()=>withBaselineRoute(baselineScenario('profile','public'),'/athletes/tim?tab=training'));
});
test('imports and storage cannot cross room, candidate or viewer boundaries',()=>{
 const own=baselineScenario('profile','owner');
 assert.deepEqual(parseBaselineImport(own,'profile'),own);
 assert.throws(()=>parseBaselineImport(own,'portfolio'));
 assert.throws(()=>parseBaselineImport({...own,candidate:'profile-v2'},'profile'));
 assert.notEqual(baselineStorageKey(own),baselineStorageKey({...own,viewer:'public'}));
 assert.throws(()=>parseBaselineImport({...baselineScenario('portfolio','balances'),viewer:'public'},'portfolio'));
});

test('imported notification reads preserve local read state',async()=>{
 const url=new URL('http://local/api/notifications');
 selectFixture(baselineScenario('notifications','unread'));
 const supplied=await (await fixtureResponse(url,'GET')).json();
 selectFixture({...baselineScenario('notifications','unread'),responses:{[responseKey(url)]:supplied}});
 await fixtureResponse(new URL('http://local/api/notifications/read-all'),'POST');
 const read=await (await fixtureResponse(url,'GET')).json();
 assert.equal(read.unread_count,0);
 assert.ok(read.notifications.every((n:any)=>n.read));
});
test('public profile imports cannot resolve the fixture owner through an alias',()=>{
 assert.throws(()=>withBaselineRoute(baselineScenario('profile','public'),'/athletes/11111111'));
});
test('public viewers cannot fetch private training or portfolio fixtures',async()=>{
 selectFixture(baselineScenario('profile','public'));
 for(const path of ['/portfolio/snapshot','/analytics/fitness','/users/me/threshold'])assert.equal((await fixtureResponse(new URL('http://local/api'+path),'GET')).status,503);
});

test('public journeys retain public viewers and gate private destinations',()=>{
 const s=baselineScenario('public-rider','public');
 assert.deepEqual(baselineJourney(s,'/rides/preview-ride'),{owner:'public-ride',href:'/rides/preview-ride'});
 assert.deepEqual(baselineJourney(s,'/profile?tab=portfolio'),{owner:'access',href:'/'});
 assert.equal(baselineJourney(s,'/climbs/preview-climb').owner,'public-climb');
});

test('public imports cannot replace auth identity or alias private riders to public data',async()=>{
 const auth=new URL('http://local/api/users/me');
 selectFixture({...baselineScenario('profile','public'),responses:{'GET /users/me':{wallet_address:'tim'}}});
 assert.notEqual((await (await fixtureResponse(auth,'GET')).json()).wallet_address,'tim');
 selectFixture(baselineScenario('public-rider','public'));
 const privateRider=await (await fixtureResponse(new URL('http://local/api/public/previews/riders/private'),'GET')).json();
 assert.equal(privateRider.recentRides.isPublic,false);assert.equal(privateRider.rider.username,'private');
 assert.equal((await fixtureResponse(new URL('http://local/api/public/previews/riders/unknown'),'GET')).status,404);
});
