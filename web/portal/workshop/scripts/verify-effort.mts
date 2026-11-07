import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {chromium,type Page} from '@playwright/test';
import {boardFor,clock,comparisonFor,dateLabel,effortHref,findEffort,fixtures,historyFor,signed,visibleEffort,type Effort,type Viewer} from '../effort/model';
import {formatNumber} from '../../src/lib/formatters';
import {autoRange} from '../v15/charts/Axis';

const [base='http://127.0.0.1:4407',out='/tmp/effort-view-verification']=process.argv.slice(2);
await mkdir(out,{recursive:true});
const browser=await chromium.launch({headless:true}),errors:string[]=[],checks:string[]=[],captures:string[]=[];
const context=await browser.newContext({viewport:{width:1440,height:900},deviceScaleFactor:2,reducedMotion:'reduce',hasTouch:true}),page=await context.newPage();
await context.addInitScript('globalThis.__name = (fn) => fn');
page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
const f=(n:number,d=0)=>formatNumber(n,d,d);
const text=(s:string)=>s.replace(/\s+/g,' ').trim();
async function visit(e:Effort,viewer:Viewer='rider',extra:Record<string,string>={}){
 await page.goto(new URL(effortHref(e,viewer,extra),base).href,{waitUntil:'networkidle'});
 await page.locator('.effort-page').waitFor();await page.evaluate(()=>document.fonts.ready);
}
async function noLayoutFaults(label:string){
 const result=await page.evaluate(()=>{
  const small:string[]=[],axisOverlaps:string[]=[],walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);let node;
  const visible=(el:Element)=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&!el.closest('dialog:not([open]),[aria-hidden=true]');};
  while((node=walker.nextNode())){const el=node.parentElement;if(!node.textContent?.trim()||!el||!visible(el)||el.matches('script,style'))continue;const size=parseFloat(getComputedStyle(el).fontSize)*(el instanceof SVGTextElement?Math.hypot(el.getScreenCTM()?.a??1,el.getScreenCTM()?.b??0):1);if(size<10.999)small.push(node.textContent);}
  for(const axis of document.querySelectorAll('.v15-axis')){
   const spans=[...axis.querySelectorAll('span')].filter(el=>getComputedStyle(el).visibility!=='hidden');
   for(let i=0;i<spans.length;i++)for(let j=i+1;j<spans.length;j++){const a=spans[i].getBoundingClientRect(),b=spans[j].getBoundingClientRect();if(Math.min(a.right,b.right)>Math.max(a.left,b.left)+.5&&Math.min(a.bottom,b.bottom)>Math.max(a.top,b.top)+.5)axisOverlaps.push(`${spans[i].textContent} / ${spans[j].textContent}`);}
  }
  return {overflow:document.documentElement.scrollWidth>innerWidth,small,axisOverlaps};
 });
 assert.deepEqual(result,{overflow:false,small:[],axisOverlaps:[]},label);checks.push(`layout:${label}`);
}
async function numbers(e:Effort,viewer:Viewer){
 const visible=visibleEffort(e,viewer),m=visible.metrics,metrics:Record<string,number|undefined>={'NP':m.np_w,'Intensity':m.intensity_factor,'Load':m.load,'VI':m.variability_index,'VAM':m.vam_m_per_hour,'W/kg':m.w_per_kg,'Cadence':m.avg_cadence_rpm,'Max':m.max_power_w,'Best 30 s':m.best_30s_w,'Best 1 min':m.best_60s_w,'Torque':m.avg_torque_nm,'Peak torque':m.max_torque_nm,'Speed':m.avg_speed_mps*3.6,'Heart rate':m.avg_hr_bpm,'Max heart rate':m.max_hr_bpm};
 const actual=await page.locator('[data-metric]').evaluateAll(nodes=>Object.fromEntries(nodes.map(n=>[n.getAttribute('data-metric'),Number(n.getAttribute('data-value'))])));
 assert.deepEqual(actual,Object.fromEntries(Object.entries(metrics).filter(([,v])=>v!==undefined).map(([label,value])=>[label,Number(f(value!,['Intensity','VI'].includes(label)?2:['W/kg','Speed'].includes(label)?1:0).replaceAll(',',''))])),`${e.id} metric parity ${viewer}`);
 assert.equal(await page.locator('.v15-result-clock').textContent(),clock(m.time_s));
 assert.equal(await page.locator('.v15-masthead').getAttribute('data-tone'),viewer==='rider'?'dark':'light');
 const bases=await page.locator('.v15-result-summary .v15-result-basis').evaluateAll(nodes=>nodes.map(el=>({size:getComputedStyle(el).fontSize,leading:getComputedStyle(el).lineHeight,color:getComputedStyle(el).color,labelColor:getComputedStyle(el.parentElement!.querySelector('dt')!).color})));
 assert.ok(bases.every(b=>b.size==='12px'&&b.leading==='16px'&&b.color===b.labelColor),'result comparison and place details retain readable secondary type in both tones');
 const power=page.locator('.v15-result-summary .v15-power');
 assert.equal(await power.getAttribute('data-kind'),m.power_kind);
 assert.ok(text(await power.innerText()).includes(f(m.avg_power_w??m.estimated_power_w!)));
 assert.equal(await power.locator('.v15-wkg').count(),m.w_per_kg!==undefined&&m.power_kind==='measured'?1:0);
 const compare=comparisonFor(e,'best'),comparison=compare?e.comparisons[compare.id]:undefined;
 const columns=await page.getByRole('table',{name:'Effort sections',exact:true}).locator('thead th').allTextContents();
 const sectionRows=await page.getByRole('table',{name:'Effort sections',exact:true}).locator('tbody tr').evaluateAll(rows=>rows.map(row=>[...row.querySelectorAll('td')].map(td=>td.textContent)));
 for(const [i,s] of visible.sections.entries()){
  const expected=[`${f(s.from)}–${f(s.to)} m${f(s.grade,1)}%`,`${f(s.grade,1)}%`,clock(s.metrics.time_s),...(compare?[signed(comparison!.section_gaps_s[i])]:[]),s.metrics.power_kind==='measured'?f(s.metrics.avg_power_w!):`≈ ${f(s.metrics.estimated_power_w!)}`,...(m.w_per_kg!==undefined?[s.metrics.w_per_kg===undefined?'':f(s.metrics.w_per_kg,1)]:[]),...(m.avg_cadence_rpm!==undefined?[s.metrics.avg_cadence_rpm===undefined?'':f(s.metrics.avg_cadence_rpm)]:[]),...(m.avg_torque_nm!==undefined?[s.metrics.avg_torque_nm===undefined?'':f(s.metrics.avg_torque_nm)]:[])];
  assert.deepEqual(sectionRows[i],expected,`${e.id} section ${i}`);assert.equal(expected.length,columns.length);
 }
 const zoneRows=page.getByRole('table',{name:'Power zones',exact:true}).locator('tbody tr');
 assert.equal(await zoneRows.count(),m.power_zone_s?7:0);
 if(m.power_zone_s)for(const [i,seconds] of m.power_zone_s.entries()){
  const cells=await zoneRows.nth(i).locator('td').allTextContents();assert.equal(cells[2],clock(seconds));assert.equal(cells[3],`${f(seconds/m.power_zone_s.reduce((a,b)=>a+b,0)*100,1)}%`);
 }
 if(await page.evaluate(()=>innerWidth)<700)assert.ok(await page.locator('.v15-analysis-compact').first().isVisible(),'grade remains visible on phones');
 if(viewer!=='rider'){
  const content=await page.locator('.effort-page').innerText();assert.doesNotMatch(content,/to your best|\bThreshold\b|\bIF\b|\bLoad\b|Power zones|Max heart rate/);
 }
 // Mixed-rider boards can contain both kinds; only measured cells get a bolt.
 const powerKinds=await page.locator('.v15-power').evaluateAll(nodes=>nodes.map(n=>({kind:n.getAttribute('data-kind'),bolts:n.querySelectorAll('.v15-bolt').length})));
 assert.ok(powerKinds.every(p=>p.bolts===(p.kind==='measured'?1:0)));
 const elapsed=Number(await page.getByRole('slider',{name:'Effort cursor'}).getAttribute('aria-valuenow')),point=visible.samples.find(s=>s.elapsed_s===elapsed)!;
 const readouts=await page.locator('.v15-readouts>div').evaluateAll(nodes=>Object.fromEntries(nodes.map(n=>[n.querySelector('dt')!.textContent,n.querySelector('dd')!.textContent])));
 const expected:Record<string,string>={'Distance':`${f(point.distance_m/1000,2)} km`,'Elapsed':clock(point.elapsed_s),'Elevation':`${f(point.elevation_m)} m`,'Grade, 50 m':`${f(point.grade_pct,1)}%`};
 if(point.power_5s_w!==undefined)expected['Power, 5 s']=`${f(point.power_5s_w)} W`;
 if(comparison){const cp=comparison.points[visible.samples.indexOf(point)];if(cp.power_w!==undefined)expected[dateLabel(compare!.date)]=`${f(cp.power_w)} W`;expected.Gap=signed(cp.gap_s);}
 for(const [label,key,unit,decimals] of [['Speed','speed_kmh','km/h',1],['Cadence','cadence_rpm','rpm',0],['Torque','torque_nm','N·m',0],['Heart rate','hr_bpm','bpm',0]] as const)if(point[key]!==undefined)expected[label]=`${f(point[key]!,decimals)} ${unit}`;
 assert.deepEqual(readouts,expected,`${e.id} cursor values`);
 const values=[...e.samples.flatMap(p=>p.power_5s_w===undefined?[]:[p.power_5s_w]),...(comparison?.points??[]).flatMap(p=>p.power_w===undefined?[]:[p.power_w]),...(m.avg_power_w===undefined?[]:[m.avg_power_w])];
 if(values.length){const range=autoRange('power',values)!;assert.ok(values.every(n=>n>=range.min&&n<=range.max));}
 const elevation=autoRange('elevation',e.samples.map(s=>s.elevation_m))!;assert.ok(elevation.ticks.every(t=>t>=elevation.min&&t<=elevation.max));
 if(comparison){const range=autoRange('gap',comparison.points.map(p=>p.gap_s))!;assert.equal(range.min,-range.max);assert.ok(comparison.points.every(p=>Math.abs(p.gap_s)<=range.max));}
 assert.equal(visible.sections.reduce((sum,s)=>sum+s.metrics.time_s,0),m.time_s);
 checks.push(`numbers:${e.gates}:${e.id}:${viewer}`);
}
async function capture(name:string){const path=join(out,`${name}.png`);await page.screenshot({path,fullPage:true,animations:'disabled'});captures.push(path);}
try{
 for(const e of fixtures.efforts){await visit(e);await numbers(e,'rider');await noLayoutFaults(`${e.id}-${e.gates}`);}
 for(const width of [1440,1366,1280,1100,950,390]){
  await page.setViewportSize({width,height:width===390?844:900});await visit(findEffort('wises','v2'));await noLayoutFaults(`width-${width}`);
 }
 for(const width of [1440,390]){
  await page.setViewportSize({width,height:width===390?844:900});
  for(const gates of ['v2','v1'] as const)for(const viewer of ['rider','visitor','anon'] as const){const e=findEffort('wises',gates);await visit(e,viewer);await numbers(e,viewer);await noLayoutFaults(`${width}-${viewer}-${gates}`);await capture(`${width}-${viewer}-${gates}`);}
  for(const alias of ['estimated','interior']){const e=findEffort(alias,'v2');await visit(e);await numbers(e,'rider');await noLayoutFaults(`${width}-${alias}`);await capture(`${width}-${alias}`);}
  for(const viewer of ['rider','visitor'] as const){const e=findEffort('wises-2015-06-05-2487','v2');await visit(e,viewer);await numbers(e,viewer);assert.equal(await page.getByText('New best',{exact:true}).count(),1);assert.match(await page.locator('.v15-result-time .v15-result-basis').innerText(),/to previous best/);await noLayoutFaults(`${width}-new-best-${viewer}`);await capture(`${width}-new-best-${viewer}`);}
  await visit(findEffort('wises','v2'),'visitor');
  const boardIds=await page.locator('.v15-board-rows [data-row-id]').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('data-row-id')));
  assert.ok(!boardIds.includes(findEffort('wises','v2').id));
  assert.match(await page.locator('.effort-standing').innerText(),/Morgan’s standing · 1 of 6 · best 2:23.*This effort · \+51\.0 s to fastest/s);
  const aggregate=fixtures.board_efforts.find(e=>boardIds.includes(e.id))!;
  await page.locator(`[data-row-id="${aggregate.id}"] .v15-effort-link`).click();
  await page.getByText('Recording unavailable',{exact:true}).waitFor();
  assert.equal(await page.getByRole('slider').count(),0);
  assert.ok((await page.locator('.effort-page').innerText()).includes(`${aggregate.rider_name} · ${dateLabel(aggregate.date)}`));
  assert.ok((await page.locator('.v15-stat').first().innerText()).includes(clock(aggregate.metrics.time_s)));
  await page.getByRole('link',{name:'Open climb',exact:true}).click();await page.getByRole('heading',{name:'Leaderboard',exact:true}).waitFor();
  checks.push(`top-ten-standing-and-aggregate-summary:${width}`);
  const hr=fixtures.efforts.find(e=>e.gates==='v2'&&e.climb==='wises'&&e.metrics.avg_hr_bpm!==undefined)!;await visit(hr);await capture(`${width}-heart-rate`);
  const noShare=fixtures.efforts.find(e=>e.gates==='v2'&&!e.share_wkg&&e.metrics.power_kind==='measured')!;
  for(const viewer of ['visitor','anon'] as const){await visit(noShare,viewer);await numbers(noShare,viewer);assert.equal(await page.locator('[data-metric="W/kg"]').count(),0);}
  await visit(findEffort('wises','v2'));await page.getByRole('button',{name:/^Compare:/}).click();await capture(`${width}-compare-open`);
  await page.keyboard.press('Escape');assert.equal(await page.getByRole('listbox').count(),0);
 }
 await page.setViewportSize({width:1440,height:900});await visit(findEffort('wises','v2'));
 const slider=page.getByRole('slider',{name:'Effort cursor'});await slider.focus();await page.keyboard.press('Home');
 await page.keyboard.press('ArrowRight');assert.equal(await slider.getAttribute('aria-valuenow'),'1');
 await page.keyboard.press('Shift+ArrowRight');assert.equal(await slider.getAttribute('aria-valuenow'),'11');
 assert.notEqual(await slider.evaluate(el=>getComputedStyle(el).outlineStyle),'none');
 const grade=await page.locator('.v15-figure-grade').boundingBox();assert.ok(grade);await page.mouse.move(grade.x+grade.width*.3,grade.y+grade.height/2);
 const afterMouse=await slider.getAttribute('aria-valuenow');assert.notEqual(afterMouse,'11');
 const power=await page.locator('[data-plot=power]>svg').boundingBox();assert.ok(power);await page.touchscreen.tap(power.x+power.width*.7,power.y+power.height/2);
 assert.notEqual(await slider.getAttribute('aria-valuenow'),afterMouse);
 const cursors=await page.locator('.v15-figure-cursor').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('d')));assert.equal(new Set(cursors).size,1);
 const section=page.getByRole('table',{name:'Effort sections',exact:true}).locator('tbody tr').first();await section.hover();assert.ok(await page.locator('.v15-figure-selection').count()>=2);
 await page.getByRole('button',{name:/^Compare:/}).click();await page.keyboard.press('End');await page.keyboard.press('Enter');assert.ok(page.url().includes('compare=none'));assert.equal(await page.locator('[data-plot=gap]').count(),0);
 await page.getByRole('button',{name:/^Compare:/}).click();assert.ok(await page.getByRole('option',{name:'None',exact:true}).evaluate(el=>el===document.activeElement),'selected comparison receives focus');await page.getByRole('option',{name:/^Fastest/}).click();assert.ok(page.url().includes('compare=fastest'));assert.equal(await page.locator('[data-plot=gap]').count(),1);
 checks.push('mouse-grade, keyboard-1s-10s, focus, touch, shared-cursor, section-highlight, comparison-menu');
 await visit(findEffort('wises','v1'));const cost=page.getByRole('button',{name:/Estimated stop cost/}).first();await cost.click();assert.ok((await page.getByRole('dialog').innerText()).includes('Founder copy'));await page.keyboard.press('Escape');assert.equal(await page.getByRole('dialog').count(),0);assert.ok(await cost.evaluate(el=>el===document.activeElement));checks.push('estimated-stop-range-dialog-focus');
 for(const view of ['climb','ride']){
  await visit(findEffort('wises','v2'),'rider',{view});
  if(view==='climb')await page.getByRole('button',{name:'Power verified',exact:true}).click();
  const link=view==='climb'?page.locator('.v15-list-row').last():page.locator('.v15-list-row').first();await link.scrollIntoViewIfNeeded();
  const url=page.url(),scroll=await page.evaluate(()=>scrollY),target=await link.getAttribute('href');assert.ok(target?.includes('effort='));
  await link.click();await page.getByRole('slider',{name:'Effort cursor'}).waitFor();await page.getByRole('button',{name:'Back',exact:true}).click();await page.waitForURL(url);await page.waitForTimeout(150);
  assert.ok(Math.abs(await page.evaluate(()=>scrollY)-scroll)<2,`${view} back scroll`);
  if(view==='climb')assert.equal(await page.getByRole('button',{name:'Power verified',exact:true}).getAttribute('aria-pressed'),'true');
 }
 await visit(findEffort('wises','v2'),'rider',{view:'climb'});await page.locator('.v15-stat a').first().click();await page.getByRole('slider',{name:'Effort cursor'}).waitFor();checks.push('climb-time-link');
 await visit(findEffort('wises','v2'));const rows=await page.locator('.v15-board-rows [data-row-id]').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('data-row-id')));assert.deepEqual(rows,boardFor(findEffort('wises','v2'),'rider').map(r=>r.id));await page.locator('.v15-board-rows .v15-effort-link').first().click();await page.getByRole('slider',{name:'Effort cursor'}).waitFor();assert.ok(page.url().includes('viewer=rider'));checks.push('leaderboard-top-ten-row-link, history-and-ride-links, back-tab-scroll');
 await visit(findEffort('wises','v2'),'visitor');
 const riderLink=page.locator('.v15-board-rows .v15-rider-link').first();const riderName=await riderLink.innerText();
 assert.ok(await riderLink.evaluate(el=>{const s=getComputedStyle(el,'::before');return parseFloat(s.width)>=44&&parseFloat(s.height)>=44;}));
 await riderLink.click();await page.getByRole('heading',{name:riderName,exact:true}).waitFor();assert.ok(page.url().includes('view=profile'));
 await page.locator('.v15-list-row').first().click();await page.getByRole('slider',{name:'Effort cursor'}).waitFor();assert.ok((await page.locator('.v15-kicker').textContent())?.includes(riderName));assert.notEqual(await page.locator('.v15-account').innerText(),riderName);
 for(const alias of ['estimated','interior']){await visit(findEffort(alias,'v2'),'visitor');assert.ok(await page.locator('.v15-board-rows .v15-rider-link').first().evaluate(el=>{const s=getComputedStyle(el,'::before');return parseFloat(s.width)>=44&&parseFloat(s.height)>=44;}),`${alias} rider-name target`);}
 checks.push('stable-rider-profile-links-and-distinct-visitor-account');
 await visit(findEffort('wises','v1'),'visitor');
 assert.match(await page.locator('.v15-figure-stops').innerText(),/at [\d,]+ m/);
 assert.ok(await page.locator('.v15-figure-stop').first().evaluate(el=>getComputedStyle(el).vectorEffect==='non-scaling-stroke'&&parseFloat(getComputedStyle(el).strokeWidth)>=6));
 assert.equal(await page.locator('.v15-gap-value').count(),1);
 assert.doesNotMatch((await page.locator('[data-plot=gap] .v15-axis').innerText()),/-\d/);
 assert.equal(await page.getByRole('table',{name:'Effort sections',exact:true}).locator('tfoot tr').count(),1);
 assert.equal(await page.locator('.effort-history [aria-current=location]').count(),1);
 assert.match(await page.locator('.effort-history .v15-note').innerText(),/efforts · power recorded on/);
 await page.getByRole('link',{name:'Full leaderboard',exact:true}).click();await page.locator('#leaderboard').waitFor();assert.equal(new URL(page.url()).hash,'#leaderboard');
 checks.push('visible-stop-location-gap-label-total-history-and-full-leaderboard');
 await visit(findEffort('wises','v2'));
 await page.getByRole('link',{name:'Open ride',exact:true}).click();await page.getByRole('heading',{name:'Climbs on this ride'}).waitFor();checks.push('open-ride-action');
 assert.deepEqual(errors,[]);
 await writeFile(join(out,'verification.json'),JSON.stringify({status:'pass',checks,captures,consoleErrors:errors,fixtureCount:fixtures.efforts.length},null,2)+'\n');
 console.log(JSON.stringify({status:'pass',checks:checks.length,captures:captures.length,consoleErrors:errors.length}));
}catch(error){await writeFile(join(out,'verification-failure.json'),JSON.stringify({error:String(error),stack:(error as Error).stack,url:page.url(),checks,errors},null,2));await page.screenshot({path:join(out,'failure.png'),fullPage:true});throw error;}finally{await browser.close();}
