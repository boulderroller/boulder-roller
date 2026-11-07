import {test} from 'node:test';
import assert from 'node:assert/strict';
import {DESIGNS,designFromQuery} from '../designVariants';
import {roomDestination} from '../roomRegistry';
test('V14 is additive, registered, and leaves the Ride final at V13',()=>{
 assert.ok(DESIGNS.some(d=>String(d.id)==='candidate-v14'));
 assert.equal(designFromQuery('candidate-v14'),'candidate-v14');
 assert.match(roomDestination('ride'),/variant=candidate-v13/);
});

test('the complete facts keep V13 order, covered-time metrics and owner-only CAL',async()=>{
 const {rideFacts}=await import('../rideV14Model'),{scenarios}=await import('../scenarios'),{v12Economics}=await import('../v12Example');
 const ride=scenarios[0],facts=rideFacts(ride,true,v12Economics(ride,true));
 assert.deepEqual(facts.map(f=>f.label),['Avg power','Avg cadence','Avg speed','Max speed','Max power','Work','Source','Ride CAL']);
 const {analysisSamples,channelSummary,channelValue}=await import('../v3Model'),{rideFileStats}=await import('../v12Metrics'),points=analysisSamples(ride.ride.samples),stats=rideFileStats(points);
 const expected=[...(['power','cadence','speed'] as const).map(channel=>channelValue(channelSummary(points,channel).average!,channel)),channelValue(stats.maxSpeed!,'speed'),Math.round(stats.maxPower!).toLocaleString(),Math.round(stats.workKj!).toLocaleString(),'FIT recording',String(v12Economics(ride,true)!.riderCal.amount)];
 assert.deepEqual(facts.map(f=>f.value),expected);
 assert.equal(rideFacts(ride,true,null).some(f=>f.label==='Ride CAL'),false);
 const missing={...ride,ride:{...ride.ride,samples:ride.ride.samples.slice(0,1).map(p=>({...p,power:null,cadence:null,speed:null}))}};
 assert.deepEqual(rideFacts(missing,false,null),[],'no zero or placeholder fields');
});
test('ride climb destinations preserve traversal order, V15 viewer and truthful absence',async()=>{
 const {rideClimbs}=await import('../rideV14Model'),{scenarios}=await import('../scenarios'),{climbStudies}=await import('../climb/climbModel');
 const ride=scenarios[0],context={source:'provided' as const,climbs:[{climbId:ride.climbs[0].id,resultRank:7,leaderboard:[]}]};
 const rows=rideClimbs(ride,context,true,new URLSearchParams(),climbStudies);
 assert.deepEqual(rows.map(r=>r.number),[1,2,3]);assert.deepEqual(rows.map(r=>r.climb.name),ride.climbs.map(c=>c.name));
 for(const row of rows){assert.ok(row.href);const q=new URL(row.href!,'http://test').searchParams;assert.equal(q.get('variant'),'climb-v15');assert.equal(q.get('viewer'),'rider');}
 const {railClimbs}=await import('../climb/climbV15Model');
 const expected=railClimbs(climbStudies,{current:climbStudies[0],viewer:'rider',hero:'a',state:'ready'});
 assert.deepEqual(rows.map(r=>r.railRank),rows.map(r=>expected.find(c=>c.climbId===r.climb.id)?.rank));
 assert.equal(rideClimbs(ride,context,false,new URLSearchParams(),climbStudies)[0].railRank,undefined);
 assert.equal(rideClimbs(ride,context,true,new URLSearchParams(),climbStudies,true)[0].rank,undefined);
 const unknown={...ride,climbs:[{...ride.climbs[0],id:'unbound-import'}]};
 assert.equal(rideClimbs(unknown,undefined,true,new URLSearchParams(),climbStudies)[0].href,null);
});
test('route geometry preserves V12 gaps rather than drawing across missing recordings',async()=>{
 const {rideGeometry}=await import('../rideV14Model'),{scenarios}=await import('../scenarios');
 const p=scenarios[0].ride.samples[0],points=[0,10,60,70].map((t,i)=>({...p,t,lon:i}));
 assert.deepEqual(rideGeometry(points).geometry.coordinates.map(r=>r.map(p=>p[0])),[[0,1],[2,3]]);
 assert.deepEqual(rideGeometry([p]).geometry.coordinates,[]);
});
test('V14 hrefs isolate candidate navigation and preserve feed origin',async()=>{
 const {r14Href}=await import('../rideV14Navigation');
 const previous=globalThis.window;
 try{
  Object.assign(globalThis,{window:{parent:{location:{href:'http://test/?surface=ride&variant=candidate-v13&feedScenario=mixed&view=power'}}}});
  const href=new URL(r14Href({mode:'analysis',climbId:null,range:{startIndex:3,endIndex:8},axis:'time',effortDuration:null}));
  assert.equal(href.searchParams.get('variant'),'candidate-v14');assert.equal(href.searchParams.get('feedScenario'),'mixed');
  assert.equal(href.searchParams.get('view'),'analysis');assert.equal(href.searchParams.get('axis'),'time');assert.equal(href.searchParams.get('from'),'3');assert.equal(href.searchParams.get('to'),'8');
 }finally{Object.assign(globalThis,{window:previous});}
});
test('the rail uses the current board place while the ride row keeps its historical result',async()=>{
 const {rideClimbs}=await import('../rideV14Model'),{scenarios}=await import('../scenarios'),{climbStudies}=await import('../climb/climbModel'),ride=scenarios[0];
 const context={source:'provided' as const,climbs:[{climbId:ride.climbs[0].id,resultRank:7,leaderboard:[{id:'rider',name:'Example Rider',rank:2,duration:220,isCurrentRider:true}]}]};
 const row=rideClimbs(ride,context,true,new URLSearchParams(),climbStudies)[0];
 assert.equal(row.rank,7);const {railClimbs}=await import('../climb/climbV15Model');assert.equal(row.railRank,railClimbs(climbStudies,{current:climbStudies[0],viewer:'rider',hero:'a',state:'ready'}).find(c=>c.climbId===row.climb.id)?.rank);
});
test('an imported climb origin never borrows a same-ID fixture for a sibling',async()=>{
 const {rideClimbs}=await import('../rideV14Model'),{scenarios}=await import('../scenarios'),{climbStudies}=await import('../climb/climbModel'),ride=scenarios[0];
 const query=new URLSearchParams({climbOrigin:'climb-import-local',climbOriginId:ride.climbs[0].id,climbOriginVariant:'climb-v13',climbOriginViewer:'rider'});
 const rows=rideClimbs(ride,undefined,true,query,climbStudies);
 assert.equal(new URL(rows[0].href!,'http://test').searchParams.get('scenario'),'climb-import-local');
 assert.equal(rows[1].href,null);
 assert.equal(rideClimbs(ride,undefined,true,new URLSearchParams('scenario=local-recording'),climbStudies)[0].href,null);
});

test('time ticks use round clock labels and retain the exact elapsed endpoint',async()=>{
 const {rideTimeTicks}=await import('../rideV14Model');
 assert.deepEqual(rideTimeTicks(18727),[{value:0,label:'0:00'},{value:7200,label:'2:00'},{value:14400,label:'4:00'},{value:18727,label:'5:12:07'}]);
 for(const end of [45*60,90*60,3*3600,12*3600]){const ticks=rideTimeTicks(end),round=ticks.slice(0,-1);assert.ok(round.length>=3&&round.length<=5);assert.ok(round.every(t=>t.value%900===0));assert.equal(ticks.at(-1)?.value,end);}
});
