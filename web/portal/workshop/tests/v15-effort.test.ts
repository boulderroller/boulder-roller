import {test} from 'node:test';
import assert from 'node:assert/strict';
import React, {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createRequire} from 'node:module';
import {buildSync} from 'esbuild';
import {Masthead} from '../v15/Masthead';
import {cursorStep} from '../v15/charts/EffortFigure';
import {boardFor,boardRecords,comparisonFor,findEffort,fixtures,signed,visibleEffort} from '../effort/model';

// The CLI test runner uses the portal's classic JSX transform.
Object.assign(globalThis,{React});
const require=createRequire(import.meta.url);
// Render the real page with Vite's environment replaced only at build time.
const compiled={exports:{} as typeof import('../effort/EffortView')};
const code=buildSync({entryPoints:[new URL('../effort/EffortView.tsx',import.meta.url).pathname],bundle:true,write:false,platform:'node',format:'cjs',packages:'external',loader:{'.css':'empty'},define:{'import.meta.env':'{}'}}).outputFiles[0].text;
new Function('require','module','exports',code)(require,compiled,compiled.exports);
const {EffortView}=compiled.exports;

test('a stacked figure masthead keeps its title, result and interactive figure in document order in both tones',()=>{
 for(const tone of ['dark','light'] as const){
  const html=renderToStaticMarkup(createElement(Masthead,{
   title:'Wises Mill Road',kicker:'Your effort',stats:[],kind:'figure',tone,
   layout:'stacked',subtitle:'1.10 km',summary:createElement('div',null,'3:20'),
   art:createElement('div',{role:'slider','aria-label':'Effort cursor'}),
  } as Parameters<typeof Masthead>[0]));
  assert.match(html,/data-layout="stacked"/);
  assert.match(html,new RegExp(`data-tone="${tone}"`));
  assert.ok(html.indexOf('Wises Mill Road')<html.indexOf('3:20'));
  assert.ok(html.indexOf('3:20')<html.indexOf('Effort cursor'));
 }
});

test('the recorded figure cursor moves by one second or ten seconds from its gate',()=>{
 const points=findEffort('wises','v2').samples;
 assert.equal(points[cursorStep(points,0,'ArrowRight')].elapsed_s,1);
 assert.equal(points[cursorStep(points,0,'ArrowRight',true)].elapsed_s,10);
 assert.equal(cursorStep(points,0,'ArrowLeft'),0);
 assert.equal(cursorStep(points,0,'End'),points.length-1);
});

test('the board contains each rider once and never ranks a slower personal effort',()=>{
 const effort=findEffort('wises','v2'),rows=boardFor(effort,'visitor');
 assert.equal(new Set(rows.map(r=>r.name)).size,rows.length);
 assert.ok(rows.length>1&&rows.length<=10,'show available riders up to ten');
 assert.equal(boardFor(findEffort('black-rock','v2'),'visitor').length,10,'cap the larger board at ten');
 assert.ok(!rows.some(r=>r.id===effort.id),'3:14 is history, not a leaderboard place');
 assert.ok(rows.some(r=>r.id==='wises-2015-06-05-2487'));
 for(const full of fixtures.efforts)for(const aggregate of fixtures.board_efforts){
  if(full.gates===aggregate.gates&&full.climb===aggregate.climb&&Math.abs(Date.parse(full.occurred_at)-Date.parse(aggregate.occurred_at))<1000)
   assert.equal(aggregate.rider_id,full.rider_id,'a corpus copy of a retained FIT cannot become another rider');
 }
});

test('Threshold is a dated estimate from prior power evidence, never an illustrative constant',()=>{
 for(const effort of fixtures.efforts){
  const threshold=effort.metrics.threshold;
  if(threshold){assert.equal(threshold.estimate,true);assert.equal(threshold.basis,'threshold_cp_3_7_15_v1');}
  else for(const key of ['intensity_factor','load','power_zone_s','power_zone_tops_w'])assert.ok(!(key in effort.metrics));
 }
});

test('best compares the whole recorded history and the fastest effort never means runner-up',()=>{
 const earlier=findEffort('wises-2013-10-20-2188','v2');
 assert.equal(comparisonFor(earlier,'best')?.id,'wises-2015-06-05-2487');
 const fastest=fixtures.efforts.filter(e=>e.gates==='v2'&&e.climb==='wises').sort((a,b)=>a.metrics.time_s-b.metrics.time_s)[0];
 assert.equal(comparisonFor(fastest,'best')?.id,earlier.id);
 assert.equal(comparisonFor(fastest,'fastest'),undefined);
});

test('rider identity and sharing are stable in every linked row, and the excluded Wall effort is absent',()=>{
 const riders=new Map<string,{name:string;share:boolean}>();
 for(const effort of fixtures.efforts){
  assert.notEqual(effort.id,'wall-2020-05-15-2065');
  const identity={name:effort.rider_name,share:effort.share_wkg};
  if(riders.has(effort.rider_id))assert.deepEqual(identity,riders.get(effort.rider_id));else riders.set(effort.rider_id,identity);
  for(const row of boardFor(effort,'visitor')){
   const source=boardRecords().find(e=>e.id===row.id&&e.gates===effort.gates)!;
   assert.equal(row.name,source.rider_name);
   assert.ok(row.profileHref,'every rider name opens a profile');
   assert.ok(row.effortHref?.includes(`effort=${source.id}`));
  }
  for(const row of boardFor(effort,'anon')){
   assert.ok(row.effortHref?.includes('viewer=anon'),'signed-out navigation stays signed out');
   assert.ok(row.profileHref?.includes('viewer=anon'));
  }
  const ownRow=boardFor(effort,'rider').find(r=>r.id===effort.id);
  if(ownRow&&effort.metrics.w_per_kg!==undefined)assert.equal(ownRow.power?.wkg,effort.metrics.w_per_kg,'the owner sees their known W/kg without sharing');
 }
 assert.equal(signed(8),'+8.0 s');assert.equal(signed(-13.4),'−13.4 s');
});

test('the best effort has a New best chip and truthful previous-best wording',()=>{
 const previous=Object.getOwnPropertyDescriptor(globalThis,'location');
 try{
  Object.defineProperty(globalThis,'location',{configurable:true,value:{search:'?effort=wises-2015-06-05-2487&viewer=rider'}});
  const html=renderToStaticMarkup(createElement(EffortView));
  assert.match(html,/New best/);assert.match(html,/to previous best/);assert.doesNotMatch(html,/to your best/);
 }finally{if(previous)Object.defineProperty(globalThis,'location',previous);else Reflect.deleteProperty(globalThis,'location');}
});

test('every public metric projection removes owner fields, including sections, and respects W/kg opt-in',()=>{
 for(const effort of fixtures.efforts)for(const viewer of ['visitor','anon'] as const){
  const projected=visibleEffort(effort,viewer);
  assert.ok(projected.samples.every(s=>s.hr_bpm===undefined),'public HR series cannot reconstruct owner-only maximum');
  const originals=[effort.metrics,...effort.sections.map(s=>s.metrics)];
  for(const [i,metrics] of [projected.metrics,...projected.sections.map(s=>s.metrics)].entries()){
   for(const key of ['threshold','intensity_factor','load','power_zone_s','power_zone_tops_w','max_hr_bpm'])assert.ok(!(key in metrics),`${effort.id}: ${key}`);
   assert.equal('w_per_kg' in metrics,effort.share_wkg&&'w_per_kg' in originals[i]);
  }
 }
});

test('every rendered public effort withholds body mass and owner training fields in every comparison mode',()=>{
 const previous=Object.getOwnPropertyDescriptor(globalThis,'location');
 const failures:string[]=[];
 try{
  for(const effort of fixtures.efforts)for(const viewer of ['visitor','anon'])for(const compare of ['best','fastest','none']){
   Object.defineProperty(globalThis,'location',{configurable:true,value:{search:`?effort=${effort.id}&gates=${effort.gates}&viewer=${viewer}&compare=${compare}`}});
   const html=renderToStaticMarkup(createElement(EffortView));
   const text=html.replace(/<[^>]*>/g,' ').replace(/\s+/g,' ').replaceAll('75 kg rider + 8 kg bicycle','');
   const context=`${effort.gates}/${effort.id}/${viewer}/${compare}`;
   if(/\b\d+(?:\.\d+)?\s?kg\b/.test(text))failures.push(`${context}: body mass`);
   if(/\b(?:Threshold|IF|Intensity|Load|Z[1-7])\b|Power zones|Max heart rate/.test(text))failures.push(`${context}: owner field`);
   for(const [,label,value,content] of html.matchAll(/data-metric="([^"]+)" data-value="([^"]+)"[^>]*>([\s\S]*?)<\/span>/g)){
    const displayed=content.replace(/<[^>]*>/g,'').replaceAll(',','').match(/\d+(?:\.\d+)?/)?.[0];
    if(Number(value)!==Number(displayed))failures.push(`${context}: ${label} attribute exceeds display precision`);
   }
  }
 }finally{if(previous)Object.defineProperty(globalThis,'location',previous);else Reflect.deleteProperty(globalThis,'location');}
 assert.deepEqual(failures,[]);
});
