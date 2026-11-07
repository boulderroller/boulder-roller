import {test} from 'node:test';
import assert from 'node:assert/strict';
import {vaultAttempts,v9Study,parseV9Study,importV9Study,v9Effort,v9Ride,settlementTotal} from '../climb/climbV9Model';
import {climbStudies} from '../climb/climbModel';
import {climbReturnHref} from '../climb/climbV3Navigation';

test('Vault selects a separate qualifying best per rider and preserves tied places',()=>{
 const rows=vaultAttempts([{id:'a-slow',rowId:'a',duration:240,date:'2016-08-20'}, {id:'a-best',rowId:'a',duration:230,date:'2016-08-21'},{id:'b',rowId:'b',duration:230,date:'2016-08-22'},{id:'c',rowId:'c',duration:250,date:'2016-08-23'}]);
 assert.deepEqual(rows.map(r=>[r.id,r.rank]),[['a-best',1],['b',1],['c',3]]);
});
test('V9 imports preserve explicit qualification; absent metadata stays absent',()=>{
 const s=v9Study(climbStudies[0]);assert.ok(s.candidate9);assert.equal(s.candidate7!.economy!.weeks.length,12);
 const board=s.feed!.workshopV6!.leaderboards.find(b=>b.climbId===s.climbId)!;
 const overall=board.rows.find(r=>r.rank===1)!,qualifying=vaultAttempts(s.candidate9!.attempts).find(a=>a.rowId===overall.id)!;
 assert.ok(qualifying.duration>overall.duration);assert.notEqual(qualifying.rank,1);assert.equal(qualifying.entryId,undefined);
 const imported=importV9Study(s,'v9-check');assert.deepEqual(imported.candidate9,s.candidate9);
 const bad=structuredClone(s);bad.candidate9!.attempts[0].rowId='missing';assert.throws(()=>parseV9Study(bad));
 const naked=structuredClone(s);delete naked.candidate9;assert.equal(parseV9Study(naked).candidate9,undefined);
 const overlap=structuredClone(s);overlap.candidate7!.economy!.weeks[1].start=overlap.candidate7!.economy!.weeks[0].start;assert.throws(()=>parseV9Study(overlap));
});
test('allocated total retains nine-decimal precision, excluding carry',()=>{
 assert.equal(settlementTotal({allocations:{leaderboard:.1,positions:.2,legend:.000000001,pol:0,treasury:0}}),.300000001);
});
test('V9 date and time destinations return to V9 and retain viewer',()=>{
 const href='/?surface=ride&scenario=r&climb=c&from=1&to=2&climbOrigin=wises&climbOriginViewer=visitor';
 const ride=new URL(v9Ride(href),'http://local.test').searchParams,effort=new URL(v9Effort(href),'http://local.test').searchParams;
 assert.equal(ride.get('view'),'overview');assert.equal(ride.has('climb'),false);assert.equal(effort.get('view'),'analysis');
 assert.equal(climbReturnHref(effort),'/?surface=climb&variant=climb-v9&scenario=wises&viewer=visitor');
});
