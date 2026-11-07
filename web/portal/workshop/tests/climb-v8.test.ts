import {test} from 'node:test';
import assert from 'node:assert/strict';
import {v8Ride,v8Effort,v8Power} from '../climb/climbV8Model';
import {climbReturnHref} from '../climb/climbV3Navigation';
import {climbV7Studies,inspectV7} from '../climb/climbV7Model';

test('V8 date opens the whole ride and time opens its effort, retaining visitor return',()=>{
 const href='/?surface=ride&variant=candidate-v13&scenario=ride-1&viewer=visitor&view=analysis&climb=43f15658&from=45&to=80&axis=time&climbOrigin=wises&climbOriginViewer=visitor';
 const ride=new URL(v8Ride(href),'http://local.test').searchParams,effort=new URL(v8Effort(href),'http://local.test').searchParams;
 assert.equal(ride.get('view'),'overview');
 for(const key of ['climb','from','to','axis'])assert.equal(ride.has(key),false);
 assert.equal(effort.get('view'),'analysis');
 assert.equal(effort.get('climb'),'43f15658');
 assert.equal(climbReturnHref(effort),'/?surface=climb&variant=climb-v8&scenario=wises&viewer=visitor');
 assert.equal(ride.get('viewer'),'visitor');
});
test('wattage belongs to the bound climb recording and stays absent for synthetic history',()=>{
 const study=climbV7Studies.find(s=>s.id==='wises')!,data=inspectV7(study,'rider');
 const current=data.personal!.rows.find(r=>r.current)!,history=data.personal!.rows.find(r=>!r.current)!;
 assert.ok(v8Power(data.recordings,study.climbId,current.href!)!>0);
 assert.equal(v8Power(data.recordings,study.climbId,history.analysisHref!),null);
 assert.equal(v8Power(data.recordings,'unbound',current.href!),null);
});
