import {test} from 'node:test';
import assert from 'node:assert/strict';
import {resultTime} from '../climb/climbV6Model';
import {climbReturnHref,carryClimbOrigin} from '../climb/climbV3Navigation';

test('history uses available precision without an ornamental zero, while detailed comparisons retain tenths',()=>{
 assert.equal(resultTime(235),'3:55');
 assert.equal(resultTime(235.4),'3:55.4');
 assert.equal(resultTime(239.99),'4:00');
 assert.equal(resultTime(235,true),'3:55.0');
 assert.equal(resultTime(225.9,true),'3:45.9');
});
test('V6 returns from an effort to the same imported climb without elevating viewer access',()=>{
 const origin=new URLSearchParams({climbOrigin:'climb-import-test',climbOriginId:'43f15658',climbOriginViewer:'visitor',climbOriginVariant:'climb-v6',viewer:'visitor'});
 const hop=new URL(carryClimbOrigin('/?surface=ride&scenario=next&viewer=owner',origin),'http://local.test').searchParams;
 assert.equal(climbReturnHref(hop),'/?surface=climb&variant=climb-v6&scenario=climb-import-test&viewer=visitor');
 assert.equal(hop.get('viewer'),'visitor');
});
