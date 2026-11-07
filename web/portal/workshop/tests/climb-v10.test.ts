import {test} from 'node:test';
import assert from 'node:assert/strict';
import {vaultNumber,v10Effort,v10Ride} from '../climb/climbV10Model';
import {climbReturnHref} from '../climb/climbV3Navigation';

test('Vault readings omit padded zeros and retain meaningful nine-decimal precision',()=>{
 assert.deepEqual([54,32.4,7.776,0,.000000001,18426.72].map(vaultNumber),['54','32.4','7.776','0','0.000000001','18,426.72']);
});
test('V10 date and effort links return to their own candidate and viewer',()=>{
 const href='/?surface=ride&scenario=r&climb=c&from=1&to=2&climbOrigin=wises&climbOriginViewer=visitor';
 const ride=new URL(v10Ride(href),'http://local.test').searchParams,effort=new URL(v10Effort(href),'http://local.test').searchParams;
 assert.equal(ride.get('view'),'overview');assert.equal(ride.has('climb'),false);assert.equal(effort.get('view'),'analysis');
 for(const query of [ride,effort]) assert.equal(climbReturnHref(query),'/?surface=climb&variant=climb-v10&scenario=wises&viewer=visitor');
});
