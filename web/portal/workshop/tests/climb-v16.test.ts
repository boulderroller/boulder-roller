import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {climbById,climbStudies} from '../climb/climbModel';
import {v9Study} from '../climb/climbV9Model';
import {inspectV7} from '../climb/climbV7Model';
import {boardRows,estimatedWatts,examplePowerRiders,powerConstants,powerVerified,rowPower,sharedWkg,v16Effort,v16Ride,v16MapHref} from '../climb/climbV16Model';
import {v8Power} from '../climb/climbV8Model';
import {climbReturnHref} from '../climb/climbV3Navigation';
const source=(file:string)=>readFileSync(new URL(`../${file}`,import.meta.url),'utf8');
test('Climb V16 is additive, registered and the shared climb destination',async()=>{
 assert.match(source('climb/ClimbWorkshop.tsx'),/id:'climb-v16',label:'Candidate v16'/);
 assert.match(source('climb/ClimbPreview.tsx'),/settings.variant==='climb-v16'/);
 const {destinationHref}=await import('../frame/destinations');
 assert.match(destinationHref('climb'),/variant=climb-v16/);
});
test('power constants and the Wises leader use reproducible standard-mass physics',()=>{
 assert.deepEqual(powerConstants,{riderKg:75,bikeKg:8,g:9.80665,rho:1.225,cda:.32,crr:.005,drivetrain:.975});
 assert.equal(estimatedWatts(1157.05,62.2,225.9),278);
 for(const args of [[NaN,62,200],[1000,NaN,200],[1000,60,0],[0,60,200],[1000,-1,200]])assert.equal(estimatedWatts(...args as [number,number,number]),null);
 const study=v9Study(climbById('wises')),data=inspectV7(study,'rider'),leader=boardRows(data,study,'ready','overall')[0];
 assert.deepEqual(rowPower(data,study,leader),{kind:'estimated',watts:278,wkg:null,source:'standard-mass'});
});
test('a recording wins over examples; imported riders never acquire fixture power or mass',()=>{
 const study=v9Study(climbById('wises')),data=inspectV7(study,'rider'),rows=boardRows(data,study,'ready','overall'),owner=rows.find(r=>r.current)!;
 assert.equal(rowPower(data,study,owner)!.watts,Math.round(v8Power(data.recordings,study.climbId,owner.href!)!));
 assert.equal(rowPower(data,study,owner)!.source,'recording');
 assert.equal(rowPower(data,{...study,id:'climb-import-example'},rows[1])!.kind,'estimated');
 assert.equal(rowPower(data,{...study,id:'climb-import-example'},owner)!.wkg,null);
 assert.equal(rowPower({...data,terrain:null},study,rows[0]),null);
});
test('W/kg requires sharing, except for the viewer looking at their own known weight',()=>{
 assert.equal(sharedWkg(300,{massKg:75,sharesWkg:false},false),null);
 assert.equal(sharedWkg(300,{massKg:75,sharesWkg:false},true),4);
 assert.equal(sharedWkg(300,{massKg:75,sharesWkg:true},false),4);
 assert.equal(sharedWkg(300,undefined,true),null);
 const study=v9Study(climbById('wises'));
 for(const viewer of ['rider','visitor','signed-out'] as const){
  const data=inspectV7(study,viewer),row=boardRows(data,study,'ready','overall').find(r=>r.name==='Example Rider')!;
  assert.equal(rowPower(data,study,row)!.wkg,viewer==='rider'?3.8:null);
 }
});
test('example riders have bounded fixed physics, and fictional measured power exactly matches verification',()=>{
 for(const person of Object.values(examplePowerRiders)){assert.ok(person.massKg>=55&&person.massKg<=90);assert.ok(Math.abs(person.variation)<=.03);}
 for(const input of climbStudies){const study=v9Study(input),data=inspectV7(study,'rider');
  for(const view of ['overall','qualified'] as const)for(const row of boardRows(data,study,'ready',view)){
   const power=rowPower(data,study,row);if(!power)continue;
   assert.ok(Number.isInteger(power.watts));assert.deepEqual(power,rowPower(data,study,row));
   if(power.kind==='estimated')assert.equal(power.wkg,null);
  }
 }
 for(const id of ['wises','black-rock','sprague','first-visit','vault']){
  const study=v9Study(climbById(id)),data=inspectV7(study,'rider'),qualified=boardRows(data,study,'ready','qualified');
  for(const view of ['overall','qualified'] as const)for(const row of boardRows(data,study,'ready',view)){
   const power=rowPower(data,study,row)!,verified=qualified.some(q=>q.riderHref===row.riderHref&&q.duration===row.duration);
   assert.equal(powerVerified(data,study,row),verified);
   if(view==='qualified')assert.equal(power.kind,'measured',`${id}: ${row.name} must have measured power`);
   if(power.source!=='recording')assert.equal(power.kind==='measured',verified,`${id}: ${row.name} ${row.duration} verification`);
  }
 }

});
test('V16 effort and ride round trips preserve the V16 origin and the existing time links',()=>{
 const study=v9Study(climbById('wises')),data=inspectV7(study,'rider'),href=boardRows(data,study,'ready','overall').find(r=>r.current)!.href!;
 for(const [target,view] of [[v16Effort(href),'analysis'],[v16Ride(href),'overview']]){
  const query=new URL(target,'http://test').searchParams;
  assert.match(climbReturnHref(query)!,/variant=climb-v16/);assert.equal(query.get('variant'),'candidate-v14');assert.equal(query.get('view'),view);
  assert.equal(query.has('climb'),view==='analysis');
 }

 const map=new URL(v16MapHref(study,'rider')!,'http://test').searchParams;assert.equal(map.get('variant'),'map-v7');assert.ok(map.get('origin'));
 assert.match(source('climb/ClimbV16.tsx'),/feedHref=destinationHref\('feed'/);
 assert.match(source('rideV14Model.ts'),/origin.set\('climbOriginVariant','climb-v15'\)/);
});

test('fixture masses and sharing bind to stable names in every allowed study',()=>{
 assert.deepEqual(Object.keys(examplePowerRiders).sort(),['Alex','Drew','Example Rider','Jamie','Morgan','Robin','Rowan','Sam'].sort());
 const names={wises:['Alex','Drew','Example Rider','Jamie','Morgan','Robin','Rowan','Sam'],'black-rock':['Alex','Example Rider','Jamie','Morgan'],sprague:['Morgan'],'first-visit':['Alex','Drew','Example Rider','Jamie','Morgan','Robin','Rowan','Sam'],vault:['Alex','Drew','Example Rider','Jamie','Morgan','Robin','Rowan','Sam']};
 for(const [id,expected] of Object.entries(names)){
  const study=v9Study(climbById(id)),data=inspectV7(study,'rider');
  const bound=[...new Set(['overall','qualified'].flatMap(view=>boardRows(data,study,'ready',view as 'overall'|'qualified').filter(row=>examplePowerRiders[row.name]).map(row=>row.name)))].sort();
  assert.deepEqual(bound,expected.sort(),id);
 }
 assert.equal(examplePowerRiders.Drew.sharesWkg,true);
});
