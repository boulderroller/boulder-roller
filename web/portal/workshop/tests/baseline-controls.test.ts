import {test} from 'node:test';
import assert from 'node:assert/strict';
import * as runtime from '../baseline/runtime';
import {baselineScenario} from '../baseline/model';

test('release held reads without replacing the selected room, viewer or imported responses',async()=>{
 const scenario={...baselineScenario('profile','loading'),responses:{'GET /retained-control':{source:'imported-control'}}};
 runtime.selectFixture(scenario);
 const pending=runtime.fixtureResponse(new URL('http://localhost/api/retained-control'),'GET');
 assert.ok(pending instanceof Promise);
 runtime.releaseData();
 const response=await pending;
 assert.deepEqual(await response.json(),{source:'imported-control'});
 assert.equal(runtime.selected,scenario);
});

test('restore availability keeps existing local read changes',async()=>{
 runtime.selectFixture(baselineScenario('notifications','stale'));
 await runtime.fixtureResponse(new URL('http://localhost/api/notifications/read-all'),'POST');
 runtime.setStale();
 assert.equal((await runtime.fixtureResponse(new URL('http://localhost/api/notifications'),'GET')).status,503);
 runtime.releaseData();
 const response=await runtime.fixtureResponse(new URL('http://localhost/api/notifications'),'GET');
 assert.equal(response.status,200);
 assert.equal((await response.json()).unread_count,0);
});
