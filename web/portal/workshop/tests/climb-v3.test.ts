import {test} from 'node:test';
import assert from 'node:assert/strict';
import {climbById,inspectClimb,climbStudies} from '../climb/climbModel';
import {climbReturnHref,climbV3EffortHref,carryClimbOrigin,climbV3Destination} from '../climb/climbV3Navigation';
test('V3 recording links open analysis and return to the same climb candidate',()=>{
 const s=climbById('wises'),data=inspectClimb(s,'rider');
 const href=climbV3EffortHref(data.personal!.rows.find(r=>r.href)!.href!);
 const p=new URL(href,'https://local.test').searchParams;
 assert.equal(p.get('view'),'analysis');assert.equal(p.get('climbOriginVariant'),'climb-v3');
 assert.equal(climbReturnHref(p),'/?surface=climb&variant=climb-v3&scenario=wises&viewer=rider');
 assert.equal(data.personal!.rows.filter(r=>r.href).length,1);
});
test('a second recording hop preserves V3 origin and cannot promote a visitor',()=>{
 const origin=new URLSearchParams({climbOrigin:'climb-import-123',climbOriginViewer:'visitor',climbOriginVariant:'climb-v3',viewer:'visitor'});
 const result=new URL(carryClimbOrigin('/?surface=ride&scenario=other&viewer=owner',origin),'https://local.test').searchParams;
 assert.equal(result.get('viewer'),'visitor');assert.equal(result.get('climbOrigin'),'climb-import-123');
 assert.equal(result.get('climbOriginViewer'),'visitor');assert.equal(result.get('climbOriginVariant'),'climb-v3');
});
test('V2 origins and unrelated ride links retain their existing behavior',()=>{
 assert.equal(climbReturnHref(new URLSearchParams('climbOrigin=wises&climbOriginViewer=rider')),'/?surface=climb&variant=climb-v2&scenario=wises&viewer=rider');
 assert.equal(carryClimbOrigin('/?viewer=owner',new URLSearchParams()),'/?viewer=owner');
});

test('imported sibling climbs never silently substitute built-in terrain or results',()=>{
 const p=new URLSearchParams({climbOrigin:'climb-import-123',climbOriginId:'43f15658',climbOriginViewer:'visitor',climbOriginVariant:'climb-v3'});
 assert.equal(climbV3Destination('43f15658',p,climbStudies),'/?surface=climb&variant=climb-v3&scenario=climb-import-123&viewer=visitor');
 assert.equal(climbV3Destination('b51920f8',p,climbStudies),null);
 p.set('climbOrigin','wises');
 assert.equal(climbV3Destination('b51920f8',p,climbStudies),'/?surface=climb&variant=climb-v3&scenario=black-rock&viewer=visitor');
});
