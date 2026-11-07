import {test} from 'node:test';
import assert from 'node:assert/strict';
import {v11Effort,v11Ride} from '../climb/climbV11Model';
import {climbReturnHref} from '../climb/climbV3Navigation';
test('V11 dates and effort times retain the reviewed generation and viewer on return',()=>{
 const href='/?surface=ride&scenario=r&climb=c&from=1&to=2&climbOrigin=wises&climbOriginViewer=visitor';
 const ride=new URL(v11Ride(href),'http://local.test').searchParams,effort=new URL(v11Effort(href),'http://local.test').searchParams;
 assert.equal(ride.get('view'),'overview');assert.equal(ride.has('climb'),false);assert.equal(effort.get('view'),'analysis');
 for(const p of [ride,effort])assert.equal(climbReturnHref(p),'/?surface=climb&variant=climb-v11&scenario=wises&viewer=visitor');
});
