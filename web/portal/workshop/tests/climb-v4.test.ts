import {test} from 'node:test';
import assert from 'node:assert/strict';
import {climbById,inspectClimb,climbStudies} from '../climb/climbModel';
import {climbReturnHref,carryClimbOrigin,climbV3Destination} from '../climb/climbV3Navigation';
test('V4 effort journeys retain the selected generation and viewer through subsequent ride hops',()=>{
 const origin=new URLSearchParams({climbOrigin:'wises',climbOriginId:'43f15658',climbOriginViewer:'visitor',climbOriginVariant:'climb-v4',viewer:'visitor'});
 assert.equal(climbReturnHref(origin),'/?surface=climb&variant=climb-v4&scenario=wises&viewer=visitor');
 const hop=new URL(carryClimbOrigin('/?surface=ride&scenario=next&viewer=owner',origin),'https://local.test').searchParams;
 assert.equal(hop.get('climbOriginVariant'),'climb-v4');assert.equal(hop.get('viewer'),'visitor');
 assert.equal(climbV3Destination('b51920f8',hop,climbStudies),'/?surface=climb&variant=climb-v4&scenario=black-rock&viewer=visitor');
 origin.set('climbOrigin','climb-import-custom');
 assert.equal(climbV3Destination('b51920f8',origin,climbStudies),null);
 assert.equal(climbV3Destination('43f15658',origin,climbStudies),'/?surface=climb&variant=climb-v4&scenario=climb-import-custom&viewer=visitor');
});
