import {test} from 'node:test';
import assert from 'node:assert/strict';
import {climbReturnHref,carryClimbOrigin} from '../climb/climbV3Navigation';
import {climbById,inspectClimb} from '../climb/climbModel';
import {effortDate,preciseTime,timeGap,historyEfforts,historyDomain,toggleHistorySelection} from '../climb/climbV5Model';

test('a V5 effort opens and returns to the selected climb generation without gaining owner access',()=>{
 const origin=new URLSearchParams({climbOrigin:'climb-import-test',climbOriginId:'43f15658',climbOriginViewer:'visitor',climbOriginVariant:'climb-v5',viewer:'visitor'});
 const hop=new URL(carryClimbOrigin('/?surface=ride&scenario=next&viewer=owner',origin),'http://local.test').searchParams;
 assert.equal(climbReturnHref(hop),'/?surface=climb&variant=climb-v5&scenario=climb-import-test&viewer=visitor');
 assert.equal(hop.get('viewer'),'visitor');
});

test('calendar history stays on its stated day while recording timestamps use the ride timezone',()=>{
 assert.equal(effortDate('2016-08-21'),'Aug 21, 2016');
 assert.equal(effortDate('2016-08-21T01:00:00Z'),'Aug 20, 2016');
});
test('gaps agree with displayed fractional durations, including rounding across a minute',()=>{
 assert.equal(preciseTime(239.99),'4:00.0');
 assert.equal(timeGap(235,225.9),'+9.1');
 assert.equal(timeGap(225.9,235),'−9.1');
 assert.equal(timeGap(235,235),'0.0');
});
test('repeated dates and equal times preserve individual efforts and a finite plot domain',()=>{
 const personal=inspectClimb(climbById('wises'),'rider').personal!;
 const single={...personal,rows:[{...personal.rows[0],date:'2016-08-21',duration:240}]};
 const repeated=historyEfforts({...single,rows:[...single.rows,...single.rows]});
 assert.equal(new Set(repeated.map(r=>r.id)).size,2);
 const d=historyDomain(repeated);assert.ok(d.max>d.min);assert.ok(Number.isFinite(d.start));
 assert.deepEqual(toggleHistorySelection(['a','b'],'c'),['a','c']);
 assert.deepEqual(toggleHistorySelection(['a','b'],'a'),['b']);
});
test('comparison does not create recordings for prior summaries or private history for other viewers',()=>{
 const data=inspectClimb(climbById('wises'),'rider');
 assert.deepEqual(data.board!.rows.map(r=>r.rank),[1,2,3,7]);
 assert.equal(historyEfforts(data.personal!).filter(r=>r.analysisHref).length,1);
 for(const viewer of ['visitor','signed-out'] as const){const d=inspectClimb(climbById('vault'),viewer);assert.equal(d.personal,undefined);assert.equal(d.vault,undefined);}
});
