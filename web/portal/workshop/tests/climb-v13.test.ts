import {test} from 'node:test';
import assert from 'node:assert/strict';
import {v13Effort,v13Ride} from '../climb/climbV13Model';
import {climbReturnHref} from '../climb/climbV3Navigation';
test('settled V13 remains the return destination from its rides and scoped efforts',()=>{
 const href='/?surface=ride&scenario=r&climb=c&from=1&to=2&climbOrigin=wises&climbOriginViewer=visitor';
 for(const destination of [v13Ride(href),v13Effort(href)])assert.equal(climbReturnHref(new URL(destination,'http://local.test').searchParams),'/?surface=climb&variant=climb-v13&scenario=wises&viewer=visitor');
});
