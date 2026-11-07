import {test} from 'node:test';
import assert from 'node:assert/strict';
import {existsSync, readFileSync, readdirSync, mkdirSync, writeFileSync, mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {candidateCssProblems,candidateTsxProblems,digest,literalColours,mainKitImports,preservationProblems} from './v15-guards';
import {fileURLToPath} from 'node:url';
import postcss from 'postcss';
import {ensureRetainedSource} from '../baseline/materialize-source.mjs';

const root=fileURLToPath(new URL('../',import.meta.url));
// Fresh/shallow checkouts have the immutable archive, not its ignored expansion.
ensureRetainedSource(`${root}baseline`);
const read=(name:string)=>readFileSync(`${root}${name}`,'utf8');
const files=(dir:string):string[]=>readdirSync(`${root}${dir}`,{withFileTypes:true}).flatMap(e=>e.isDirectory()?files(`${dir}${e.name}/`):[`${dir}${e.name}`]);
const manifest=JSON.parse(read('tests/v15-preserved-sha256.json'));
const registered=new Set(['index.html','main.tsx','roomRegistry.ts','tsconfig.json','entry.ts']);
const required=['tokens.css','kit.css','index.ts','Frame.tsx','destinations.ts','Masthead.tsx','Section.tsx','Card.tsx','Stat.tsx','Rows.tsx','Controls.tsx','Dialog.tsx','Avatar.tsx','marks.ts','charts/Profile.tsx','charts/GradeStrip.tsx','charts/Axis.tsx','mapGround.ts','KitSpecimen.tsx'];

test('the kit has one public entry and every admitted building block',()=>{
 for(const file of required)assert.ok(existsSync(`${root}v15/${file}`),file);
 assert.match(read('v15/index.ts'),/import ['"]\.\/tokens\.css['"]/);
 assert.match(read('v15/index.ts'),/import ['"]\.\/kit\.css['"]/);
 assert.match(read('v15/marks.ts'),/export.*Medal.*from ['"]\.\.\/marks\/Medal['"]/);
});
test('every effort building block has an inspectable specimen contract',()=>{
 for(const name of ['MenuSelect','ResultSummary','AnalysisTable','Zones','Estimate','Note','LinkButton','ReadoutGrid','EffortFigure'])assert.match(read('v15/KitSpecimen.tsx'),new RegExp(`data-specimen="${name}"`),name);
 assert.match(read('effort/Origins.tsx'),/kind="figure" layout="stacked"/,'light figures must use the admitted stacked layout');
});
test('kit styles are layered, scoped and use tokens for every colour',()=>{
 const css=postcss.parse(read('v15/kit.css'));
 assert.ok(css.nodes.some(n=>n.type==='atrule'&&n.name==='layer'&&n.params==='kit'));
 css.walkRules(rule=>{assert.ok(rule.selectors.every(s=>s.startsWith(':where(.v15-kit)')),rule.selector);});
 assert.deepEqual(literalColours(read('v15/kit.css')),[]);
 css.walkDecls(d=>{assert.ok(!d.prop.startsWith('--v15-'),`tokens belong in tokens.css: ${d.prop}`);});
 assert.doesNotMatch(read('v15/kit.css'),/clamp\(|\.v15-(?:frame|main-nav|rail-foot|topbar-action)\b/);
 const tokens=read('v15/tokens.css');
 assert.equal((tokens.match(/@font-face/g)||[]).length,1);
 assert.match(tokens,/:where\(\.v15-kit\)/);
 assert.doesNotMatch(tokens,/#(?:eef0e8|fbfbf8|f3f6ee|a9c48a)\b/i);
});
test('history is byte-identical and only the kit may declare kit selectors or tokens',()=>{
 assert.deepEqual(preservationProblems(root,manifest.sha256),[]);
 assert.deepEqual([...registered].sort(),manifest.registration);
 for(const file of files('').filter(f=>f.endsWith('.css')&&!f.startsWith('v15/')&&!f.startsWith('tests/'))){
  if(manifest.sha256[file]===digest(read(file)))continue;
  assert.deepEqual(candidateCssProblems(read(file)),[],file);
 }
 for(const file of files('v15/').filter(f=>/\.(tsx?|css)$/.test(f)))assert.doesNotMatch(read(file),/(?:import|export)[^;]*from\s*['"][^'"]*(?:ClimbV\d|FeedV\d|CandidateV\d|V15Frame|v15-frame|climb-v\d|feed-v\d)/,file);
});
test('the specimen is registered in the room list and has a standalone preview',()=>{
 assert.match(read('roomRegistry.ts'),/id:'kit'.*label:'V15 kit'/);
 assert.match(read('main.tsx'),/kit-preview/);
 assert.match(read('main.tsx'),/page==='kit'/);
});
test('each planted base-file edit is rejected without a Git checkout',()=>{
 const scratch=mkdtempSync(join(tmpdir(),'v15-manifest-'));
 try{
  const originals={'CandidateV14.tsx':'old ride\n','settings/settings.css':'old settings\n','balance/model.ts':'old balance\n','tools/census.mjs':'old tool\n','references/picture.png':Buffer.from([137,80,78,71,0,255]),'baseline/source.tar.gz':Buffer.from([31,139,0,255])};
  const hashes:Record<string,string>={};
  for(const [file,bytes] of Object.entries(originals)){mkdirSync(join(scratch,file,'..'),{recursive:true});writeFileSync(join(scratch,file),bytes);hashes[file]=digest(bytes);}
  assert.deepEqual(preservationProblems(scratch,hashes),[]);
  for(const [file,bytes] of Object.entries(originals)){writeFileSync(join(scratch,file),Buffer.concat([Buffer.from(bytes),Buffer.from('changed')]));assert.deepEqual(preservationProblems(scratch,hashes),[`changed ${file}`]);writeFileSync(join(scratch,file),bytes);}
  rmSync(join(scratch,'CandidateV14.tsx'));assert.deepEqual(preservationProblems(scratch,hashes),['missing CandidateV14.tsx']);
 }finally{rmSync(scratch,{recursive:true,force:true});}
});
test('planted colour literals fail the CSS value parser, including modern functions and nested fallbacks',()=>{
 assert.deepEqual(literalColours('.a{border:1px solid var(--v15-line);background:linear-gradient(0deg,var(--v15-band),var(--v15-clear));fill:none}'),[]);
 for(const value of ['red','rebeccapurple','#123456','transparent','currentColor','rgb(1 2 3)','oklab(.5 .1 .2)','lch(50 30 40)','hwb(0 10% 20%)','color(display-p3 1 0 0)','var(--v15-band,blue)','linear-gradient(red,var(--v15-band))'])assert.ok(literalColours(`.a{background:${value}}`).length,value);
});
test('planted TSX inline styles, style tags and template expressions cannot declare or reach kit styles',()=>{
 assert.deepEqual(candidateTsxProblems('const View=()=> <div className="v15-kit effort-page"><Card/></div>'),[]);
 for(const source of [
  'const View=()=> <div style={{"--v15-paper":"red"}}/>',
  'const View=()=> <style>{".v15-card{display:none}"}</style>',
  'const View=()=> <style>{`@media(min-width:0px){.v15-card{display:none}}`}</style>',
  'const View=()=> <div className={`v15-card ${active ? "on" : ""}`}/>',
  'const View=()=> <div className={"v15-card"}/>',
  'const style={"--v15-paper":"red"}; const View=()=> <div style={style}/>',
  'const className=`v15-${name}`; const View=()=> <div className={className}/>',
  'const View=()=> <style>.v15-card{"{"}display:none{"}"}</style>',
 ])assert.ok(candidateTsxProblems(source).length,source);
});
test('main never imports kit candidates, and normal preview dispatch owns the route table',()=>{
 assert.deepEqual(mainKitImports(`${root}main.tsx`),[]);
 const scratch=mkdtempSync(join(tmpdir(),'v15-import-graph-'));
 try{
  mkdirSync(join(scratch,'v15'));mkdirSync(join(scratch,'bridge'));
  writeFileSync(join(scratch,'v15/KitSpecimen.tsx'),'export const KitSpecimen=()=>null;');
  writeFileSync(join(scratch,'v15/WorkshopGate.tsx'),'export const WorkshopGate=()=>null;');
  writeFileSync(join(scratch,'bridge/index.ts'),'export * from "./nested";');
  writeFileSync(join(scratch,'bridge/nested.ts'),'export {KitSpecimen} from "../v15/KitSpecimen";');
  writeFileSync(join(scratch,'safe.ts'),'import "./main"; export {WorkshopGate} from "./v15/WorkshopGate";');
  for(const source of ['import {WorkshopGate} from "./v15/WorkshopGate"','void import(`./v15/WorkshopGate`)','import "/v15/WorkshopGate"','import "./safe"']){
   writeFileSync(join(scratch,'main.tsx'),source);assert.deepEqual(mainKitImports(join(scratch,'main.tsx')),[],source);
  }
  const planted=['import {KitSpecimen} from "./v15/KitSpecimen"','const candidate=import("./v15/KitSpecimen")','void import(`./v15/KitSpecimen`)','void import(`./v15/${candidate}`)','export {KitSpecimen} from "./v15/KitSpecimen"','import {KitSpecimen} from "./bridge"','void import(`./bridge`)','void import("/v15/KitSpecimen")','void import(`/v15/${candidate}`)'];
  const rejected=planted.map(source=>{writeFileSync(join(scratch,'main.tsx'),source);return mainKitImports(join(scratch,'main.tsx')).length>0;});
  assert.deepEqual(rejected,planted.map(()=>true),'every direct, template and re-export import must fail');
 }finally{rmSync(scratch,{recursive:true,force:true});}
 assert.match(read('main.tsx'),/import ['"]\.\/workshop\.css['"]/);
 assert.match(read('index.html'),/src="\/entry\.ts"/);
 assert.match(read('entry.ts'),/kitRoutes/);
 assert.match(read('main.tsx'),/WorkshopGate as Gate/);
 assert.match(read('v15/KitSpecimen.tsx'),/WorkshopGate/);
 assert.doesNotMatch(read('main.tsx')+read('v15/KitSpecimen.tsx'),/SHA-256|br-workshop-gate/);
 assert.doesNotMatch(read('v15/WorkshopGate.tsx'),/\.css|KitSpecimen|from ['"]\./);
 assert.doesNotMatch(read('entry.ts'),/import\(['"]\.\/v15\/entry/);
});

import {autoRange,distanceTicks,nextStep} from '../v15/charts/Axis';
import {gradeBands} from '../v15/charts/GradeStrip';
import {kitRoute} from '../entry';

test('kit routes select the normal room preview flag and variant without taking legacy previews',()=>{
 const route={preview:'effort-preview',variant:'effort-v15',title:'Effort',load:async()=>()=>null};
 assert.equal(kitRoute('?effort-preview=1&variant=effort-v15&scenario=wises',[route]),route);
 assert.equal(kitRoute('?effort-preview=1&variant=effort-v14',[route]),undefined);
 assert.equal(kitRoute('?surface=effort&variant=effort-v15',[route]),undefined);
 assert.equal(kitRoute('?climb-preview=1&variant=climb-v16'),undefined);
 assert.equal(kitRoute('?kit-preview=1')?.preview,'kit-preview');
});

test('axis ranges follow the 1 2 2.5 5 ladder, strict peaks and signed gaps',()=>{
 assert.deepEqual([99,100,200,249,250,500].map(nextStep),[100,200,250,250,500,1000]);
 assert.deepEqual(autoRange('power',[0,272,285]),{min:0,max:300,ticks:[0,100,200,300]});
 assert.deepEqual(autoRange('gap',[-12,22]),{min:-25,max:25,ticks:[-25,-12.5,0,12.5,25]});
 assert.deepEqual(autoRange('elevation',[44,18,67]),{min:18,max:67,ticks:[20,30,40,50,60]});
 assert.deepEqual(autoRange('elevation',[18,18]),{min:18,max:18,ticks:[18]});
 assert.deepEqual(autoRange('elevation',[90.8,105.9]),{min:90.8,max:105.9,ticks:[95,100,105]});
 assert.deepEqual(autoRange('elevation',[90.8,90.8]),{min:90.8,max:90.8,ticks:[]});
 assert.equal(autoRange('power',[]),null);
 assert.deepEqual(distanceTicks(1157),[0,250,500,750,1000,1157]);
 assert.deepEqual(distanceTicks(2500),[0,500,1000,1500,2000,2500]);
 assert.deepEqual(distanceTicks(5000),[0,1000,2000,3000,4000,5000]);
 assert.deepEqual(autoRange('elevation',[90.8,118]),{min:90.8,max:118,ticks:[95,100,105,110,115]});
 assert.deepEqual(distanceTicks(0),[]);
 assert.throws(()=>nextStep(Infinity),RangeError);
});
test('grade strips preserve signed terrain and merge adjacent 100 meter rungs',()=>{
 assert.deepEqual(gradeBands([{d:0,elevation:10},{d:100,elevation:15},{d:200,elevation:20},{d:300,elevation:17}]),[{from:0,to:200,grade:5,rung:1},{from:200,to:300,grade:-3,rung:0}]);
 assert.deepEqual(gradeBands([]),[]);
});
test('the source values and control dimensions stay in the single token file',()=>{
 const old=read('climb/climb-v15.css'),block=old.slice(old.indexOf('.c15-page{'),old.indexOf(' min-height:100vh'));
 const values=block.match(/--c15-[\w-]+:[^;\n]+;/g)!;
 assert.equal(values.length,37);
 for(const value of values)assert.ok(read('v15/tokens.css').includes(value.replace('--c15-','--v15-')),value);
 for(const name of ['power','power-metal','power-muted','power-dark','power-dark-muted','muted-on-dark','fade-dark','fade-light','fade-dark-phone','fade-light-phone','gold-foil','silver-foil','bronze-foil','sheen'])assert.ok(read('v15/tokens.css').includes(`--v15-${name}:`),name);
 assert.doesNotMatch(read('v15/Rows.tsx'),/setInterval|aria-sort/);
 assert.match(read('v15/Rows.tsx'),/v15:effort-landed/);
 assert.match(read('v15/Rows.tsx'),/addEventListener\('focus'/);
 assert.match(read('tsconfig.json'),/v15\/\*\*\/\*\.tsx/);
});

test('specimen browser contract: type, containment, dimensions, interaction and every width', {timeout:120000},async t=>{
 const {createServer}=await import('vite');
 const {chromium}=await import('@playwright/test');
 const server=await createServer({configFile:`${root}vite.config.ts`,server:{port:0,host:'127.0.0.1',strictPort:false}});
 await server.listen();const address=server.httpServer!.address();assert.ok(address&&typeof address!=='string');
 const browser=await chromium.launch({headless:true});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:900},reducedMotion:'reduce'}),page=await context.newPage(),errors:string[]=[];
  page.on('pageerror',error=>errors.push(error.message));page.on('console',message=>{if(message.type()==='error')errors.push(message.text());});
  await page.goto(`http://127.0.0.1:${address.port}/?kit-preview=1`);await page.locator('.v15-kit').waitFor();await page.evaluate(()=>document.fonts.ready);
  // tsx preserves function names with an esbuild helper inside serialized callbacks.
  await page.evaluate('globalThis.__name = (fn) => fn');
  for(const width of [1440,1366,1280,1100,950,390])await t.test(`type and geometry at ${width}`,async()=>{
   await page.setViewportSize({width,height:width===390?844:900});await page.evaluate(()=>new Promise(requestAnimationFrame));
   const result=await page.evaluate(()=>{
    const failures:string[]=[],seenSizes=new Set<number>(),seenWeights=new Set<number>(),sizes=[11,12,13,14,15,17,22,28,32,44,56],walker=document.createTreeWalker(document.querySelector('.v15-kit')!,NodeFilter.SHOW_TEXT);let node;
    while((node=walker.nextNode())){
     const el=node.parentElement!;if(!node.textContent?.trim()||!el.getClientRects().length||el.closest('dialog:not([open])')||getComputedStyle(el).visibility==='hidden')continue;
     const range=document.createRange();range.selectNodeContents(node);if(!range.getBoundingClientRect().width)continue;
     const style=getComputedStyle(el),raw=parseFloat(style.fontSize),size=el instanceof SVGTextElement?raw*Math.hypot(el.getScreenCTM()?.a??1,el.getScreenCTM()?.b??0):raw,weight=+style.fontWeight;
     seenSizes.add(Math.round(size*100)/100);seenWeights.add(weight);
     const medal=el instanceof SVGTextElement&&!!el.closest('svg[role=img]');
     const boardPower=!!el.closest('.v15-leaderboard')&&el.matches('.v15-power-value');
     const boardMedium=!!el.closest('.v15-leaderboard')&&el.matches('.v15-power-value,.v15-power-value>em,.v15-power-unit,.v15-wkg,.v15-board-you,.v15-board-cols>[role=columnheader]');
     const phoneStat=innerWidth<=700&&!!el.closest('.v15-stat-value,.v15-masthead-stats dd');
     if(size<10.99||(!sizes.some(s=>Math.abs(s-size)<.02)&&!(phoneStat&&Math.abs(size-20)<.02)&&!(medal&&Math.abs(size-16)<.02)&&!(boardPower&&size===19)))failures.push(`size ${size}: ${node.textContent}`);
     if(![400,440].includes(weight)&&!(weight===500&&boardMedium)&&!(weight===560&&el.matches('.v15-wordmark'))&&!([600,650].includes(weight)&&(medal||el.closest('.v15-board-time,.v15-power-value'))))failures.push(`weight ${weight}: ${node.textContent}`);
    }
    for(const masthead of document.querySelectorAll('.v15-masthead')){const box=masthead.getBoundingClientRect();for(const el of masthead.querySelectorAll('.v15-title,.v15-masthead-stats dd')){const r=el.getBoundingClientRect();if(r.bottom>box.bottom+.1||r.right>box.right+.1)failures.push(`clipped masthead ${el.textContent}`);}}
    for(const axis of document.querySelectorAll('.v15-axis[data-orientation=horizontal]')){const labels=[...axis.querySelectorAll('span')].filter(el=>getComputedStyle(el).visibility!=='hidden');for(let i=1;i<labels.length;i++)if(labels[i-1].getBoundingClientRect().right>labels[i].getBoundingClientRect().left+.1)failures.push('overlapping axis labels');}
    for(const callout of document.querySelectorAll('.v15-grade-callout')){const style=getComputedStyle(callout);if(style.color===style.backgroundColor)failures.push('invisible grade callout');}
    const escaped=[...document.querySelectorAll('[class*="v15-"]')].filter(el=>!el.closest('.v15-kit')).length;
    const box=(s:string)=>document.querySelector(s)!.getBoundingClientRect(),style=(s:string)=>getComputedStyle(document.querySelector(s)!);
    const attribution=box('.v15-map-attribution'),stats=box('.v15-masthead-stats'),attributionOverlap=attribution.left<stats.right&&attribution.right>stats.left&&attribution.top<stats.bottom&&attribution.bottom>stats.top;
    return {failures,sizes:[...seenSizes].sort((a,b)=>a-b),weights:[...seenWeights].sort((a,b)=>a-b),escaped,attributionOverlap,overflow:document.documentElement.scrollWidth>innerWidth,band:box('.v15-band').height,topbar:box('.v15-topbar').height,hero:box('.v15-masthead').height,seam:style('.v15-sheet').paddingLeft,primary:box('.v15-button[data-variant=primary]').height,secondary:box('.v15-button[data-variant=secondary]').height,row:box('.v15-board-row').height,plot:box('.v15-profile-plot').height};
   });
   if(process.env.V15_KIT_EVIDENCE_DIR){mkdirSync(process.env.V15_KIT_EVIDENCE_DIR,{recursive:true});writeFileSync(`${process.env.V15_KIT_EVIDENCE_DIR}/specimen-${width}.json`,JSON.stringify({width,...result},null,2)+'\n');}
   assert.deepEqual(result.failures,[]);assert.equal(result.escaped,0);assert.equal(result.overflow,false);assert.equal(result.attributionOverlap,false);
   assert.equal(result.band,34);assert.equal(result.topbar,width===390?56:68);assert.equal(result.hero,width===390?400:320);assert.equal(result.seam,width===390?'8px':'12px');assert.equal(result.primary,40);assert.equal(result.secondary,36);assert.equal(result.row,width===390?48:52);assert.equal(result.plot,width===390?112:150);
  });
  await t.test('the board-7 lock, small fixes and isolated preview styles hold at both widths',async()=>{
   for(const width of [1440,390]){
    await page.setViewportSize({width,height:width===390?844:900});
    const failures=await page.evaluate(()=>{
     const failures:string[]=[];
     const check=(selector:string,expected:Record<string,string>,pseudo?:string)=>{
      const el=document.querySelector(selector);if(!el){failures.push(`missing ${selector}`);return;}
      const style=getComputedStyle(el,pseudo);
      for(const [property,value] of Object.entries(expected))if(style.getPropertyValue(property)!==value)failures.push(`${selector} ${property}: ${style.getPropertyValue(property)} != ${value}`);
     };
     check('.v15-board-cols',{'font-size':'11px','line-height':'16px','font-weight':'500','letter-spacing':'0.88px'});
     check('.v15-board-row[data-metal=plain] .v15-power[data-kind=measured] .v15-power-value',{'font-size':'19px','line-height':'24px','font-weight':'650','letter-spacing':'-0.285px','color':'rgb(63, 106, 34)','column-gap':'3px'});
     check('.v15-leaderboard .v15-power[data-kind=estimated] .v15-power-value',{'font-size':'17px','line-height':'24px','font-weight':'500','letter-spacing':'-0.255px','color':'rgb(116, 124, 105)'});
     for(const kind of ['measured','estimated'])check(`.v15-leaderboard .v15-power[data-kind=${kind}] .v15-power-unit`,{'font-size':'12px','line-height':'24px','font-weight':'500','letter-spacing':'normal','margin-left':'1px'});
     check('.v15-leaderboard .v15-power-value>em',{'margin-right':'2px','font-style':'normal'});
     check('.v15-board-row[data-metal=plain] .v15-bolt',{'width':'9px','height':'13px','margin-right':'3px','fill':'rgb(63, 106, 34)'});
     check('.v15-leaderboard .v15-wkg',{'font-size':'13px','line-height':'20px','font-weight':'500','color':'rgb(95, 127, 69)'});
     check('.v15-board-time',{'font-size':'17px','line-height':'24px','font-weight':'600','letter-spacing':'-0.17px'});
     check('.v15-board-row[data-current=true]',{'background-color':'rgb(255, 255, 255)','background-image':'none'});
     check('.v15-board-row[data-current=true]',{'width':'4px','background-color':'rgb(34, 90, 173)'},'::before');
     check('.v15-board-rider',{'align-items':'baseline'});
     check('.v15-board-you',{'font-size':'11px','line-height':'16px','font-weight':'500','padding-top':'0px','padding-right':'6px','padding-bottom':'0px','padding-left':'6px','border-radius':'999px','background-color':'rgb(232, 238, 248)','color':'rgb(34, 90, 173)','text-transform':'none'});
     if(document.querySelector('.v15-board-you')?.textContent!=='You')failures.push('You case');
     for(const pseudo of [undefined,'::after'])check('.v15-board-row',{'transition-duration':'0s'},pseudo);
     check('.v15-segmented button[aria-pressed=false]',{'color':'rgb(99, 107, 92)','font-weight':'400'});
     check('.v15-segmented button[aria-pressed=true]',{'color':'rgb(41, 44, 39)','font-weight':'440'});
     check('.v15-board-tools [data-size=help]',{'border-top-width':'1px','border-top-style':'solid','width':'20px','height':'20px'});
     for(const el of document.querySelectorAll('.v15-board-power:has([data-kind=estimated])'))if(!el.getAttribute('aria-label')?.startsWith('Estimated '))failures.push('Estimated label on cell');
     // Effort V1 admits the light figure to the kit. Its specimen must prove
     // the paper/ink contract, while the existing board lock remains exact.
     if(document.querySelector('.v15-masthead[data-kind=figure][data-tone=light]:not([data-layout=stacked])'))failures.push('undefined light split figure');
     for(const tone of ['dark','light']){
      const selector=`.v15-masthead[data-kind=figure][data-layout=stacked][data-tone=${tone}]`;
      const el=document.querySelector(selector);
      if(!el){failures.push(`missing ${tone} figure`);continue;}
      const probe=document.createElement('span');probe.style.color=`var(--v15-${tone==='light'?'paper':'band'})`;el.append(probe);
      if(getComputedStyle(el).backgroundColor!==getComputedStyle(probe).color)failures.push(`${tone} figure background`);
      probe.style.color=`var(--v15-${tone==='light'?'ink':'bone'})`;
      if(getComputedStyle(el).color!==getComputedStyle(probe).color)failures.push(`${tone} figure text`);
      probe.remove();
     }
     for(const el of document.querySelectorAll('.v15-grade-strip span'))if(el.textContent&&!el.textContent.endsWith('%'))failures.push(`unitless grade ${el.textContent}`);
     const stats=document.querySelector('.v15-masthead-stats')!.textContent;
     if(!stats?.includes('62.2 m')||!stats.includes('5.2%')||stats.includes(' %'))failures.push(`format ${stats}`);
     if(innerWidth===1440){
      const stats=document.querySelector('.v15-masthead[data-kind=figure][data-size=card] .v15-masthead-stats')!;
      if(new Set([...stats.children].map(el=>el.getBoundingClientRect().top)).size!==1)failures.push('card figure stats wrap');
      if(getComputedStyle(stats).columnGap!=='20px')failures.push('card stat gap');
     }
     if([...document.querySelectorAll('style[data-vite-dev-id]')].some(el=>el.getAttribute('data-vite-dev-id')?.endsWith('/workshop.css')))failures.push('legacy stylesheet loaded');
     return failures;
    });
    assert.deepEqual(failures,[]);
    await page.emulateMedia({reducedMotion:'no-preference'});
    assert.deepEqual(await page.locator('.v15-board-row').first().evaluate(el=>[getComputedStyle(el).transitionProperty,getComputedStyle(el).transitionDuration,getComputedStyle(el,'::after').transitionProperty,getComputedStyle(el,'::after').transitionDuration]),['border-color','0.2s','opacity','0.2s']);
    await page.emulateMedia({reducedMotion:'reduce'});
   }
  });
  await t.test('analysis pieces expose their complete specimen contracts',async()=>{
   for(const name of ['MenuSelect','ResultSummary','AnalysisTable','Zones','Estimate','Note','LinkButton','ReadoutGrid','EffortFigure'])assert.equal(await page.locator(`[data-specimen="${name}"]`).count(),1,name);
   const select=page.getByRole('button',{name:'Specimen comparison: None',exact:true});await select.click();
   assert.ok(await page.getByRole('option',{name:'None',exact:true}).evaluate(el=>el===document.activeElement));
   await page.keyboard.press('ArrowUp');await page.keyboard.press('Enter');
   assert.equal(await page.locator('[data-specimen=EffortFigure] [data-plot=gap]').count(),1);
   const cursor=page.locator('[data-specimen=EffortFigure] [role=slider]');await cursor.focus();await page.keyboard.press('Home');await page.keyboard.press('ArrowRight');await page.keyboard.press('Shift+ArrowRight');assert.equal(await cursor.getAttribute('aria-valuenow'),'11');
   assert.equal(await page.getByRole('table',{name:'Specimen sections',exact:true}).locator('tfoot').innerText(),'Climb\t247 s\t251');
   assert.ok((await page.locator('[data-specimen=Zones] tbody tr td:last-child').allTextContents()).every(s=>s.endsWith('%')));
   const estimate=page.getByRole('button',{name:/^Specimen estimate:/});await estimate.click();assert.match(await page.getByRole('dialog').innerText(),/34.1–34.4 s/);await page.keyboard.press('Escape');assert.ok(await estimate.evaluate(el=>el===document.activeElement));
   const link=page.locator('[data-specimen=LinkButton] a');assert.ok(await link.getAttribute('href'));assert.equal((await link.boundingBox())!.height,36);
   assert.equal(await page.locator('[data-specimen=ReadoutGrid] dt').count(),2);assert.match(await page.locator('[data-specimen=Note]').innerText(),/illustrative training inputs/);
  });
  await t.test('menu, dialog focus, linked rows, pinned truth, URL and busy state',async()=>{
   await page.getByRole('button',{name:'Menu',exact:true}).click();await page.locator('.v15-rail[role=dialog]').waitFor();
   assert.equal(await page.locator('.v15-main').evaluate(el=>(el as HTMLElement).inert),true);
   await page.keyboard.press('Escape');assert.equal(await page.getByRole('button',{name:'Menu',exact:true}).evaluate(el=>el===document.activeElement),true);
   await page.setViewportSize({width:1440,height:900});
   const trigger=page.getByRole('button',{name:'Your effort history',exact:true});await trigger.click();
   assert.equal(await page.getByRole('dialog').evaluate(el=>el.getBoundingClientRect().width),440);
   assert.ok(await page.getByRole('dialog').evaluate(el=>el.contains(document.activeElement)));
   await page.keyboard.press('Escape');assert.equal(await trigger.evaluate(el=>el===document.activeElement),true);
   await page.getByRole('button',{name:'Activity details',exact:true}).first().click();assert.equal(await page.getByRole('dialog').evaluate(el=>el.getBoundingClientRect().width),680);await page.keyboard.press('Escape');
   await page.locator('.v15-board-cols').scrollIntoViewIfNeeded();await page.waitForFunction(()=>document.querySelector('.v15-board-pin')?.getAttribute('data-visible')==='true');
   const pinned=page.locator('.v15-board-pin .v15-board-row');assert.equal(await pinned.count(),1);assert.equal(await pinned.getByRole('img').getAttribute('aria-label'),'Rank 7');assert.equal(await pinned.locator('a').count(),2);
   await pinned.locator('.v15-rider-link').focus();assert.equal(await pinned.locator('.v15-rider-link').evaluate(el=>getComputedStyle(el,'::before').height),'44px');await page.keyboard.press('Tab');assert.equal(await pinned.locator('.v15-effort-link').evaluate(el=>el===document.activeElement),true);
   assert.deepEqual(await pinned.locator('.v15-effort-link').evaluate(el=>{const s=getComputedStyle(el,'::after');return [s.outlineWidth,s.outlineOffset];}),['2px','-2px']);
   await page.getByRole('button',{name:'You',exact:true}).click();assert.equal(await pinned.isVisible(),false);await page.getByRole('button',{name:'You',exact:true}).click();
   await page.getByRole('button',{name:'Power verified',exact:true}).first().click();assert.equal(new URL(page.url()).searchParams.get('tab'),'qualified');assert.equal(new URL(page.url()).searchParams.get('period'),'all-time');
   await page.waitForFunction(()=>document.querySelector('.v15-leaderboard [role=table]')?.getAttribute('aria-busy')==='false');
   await page.goBack();await page.waitForFunction(()=>document.querySelector('.v15-leaderboard button[aria-pressed=true]')?.textContent==='Overall');
   const count=await page.locator('.v15-board-rows .v15-board-row').count();await page.getByLabel('State',{exact:true}).selectOption('loading');assert.equal(await page.locator('.v15-board-rows .v15-board-row').count(),count);assert.equal(await page.locator('.v15-board-table').getAttribute('aria-busy'),'true');assert.equal(await page.locator('.v15-board-rows').evaluate(el=>getComputedStyle(el).opacity),'0.5');
   await page.getByLabel('State',{exact:true}).selectOption('empty');assert.equal(await page.getByText('No times yet',{exact:true}).count(),1);
   await page.getByLabel('State',{exact:true}).selectOption('error');assert.equal(await page.getByRole('alert').innerText(),'Leaderboard unavailable');await page.getByLabel('State',{exact:true}).selectOption('ready');
   const profile=page.getByRole('slider').first();await profile.focus();const before=await profile.getAttribute('aria-valuenow');await page.keyboard.press('ArrowRight');assert.notEqual(await profile.getAttribute('aria-valuenow'),before);await page.keyboard.press('Shift+ArrowRight');assert.equal(await page.locator('.v15-profile-selection').count(),1);await page.keyboard.press('Escape');assert.equal(await page.locator('.v15-profile-selection').count(),0);
  });
  await t.test('the sticky You copy rests in its board slot without covering later sections or moving layout',async()=>{
   await page.getByLabel('State',{exact:true}).selectOption('ready');
   for(const mode of ['excerpt','all'])for(const width of [1440,390]){
    const height=width===390?844:900;await page.setViewportSize({width,height});
    const toggle=page.getByRole('button',{name:mode==='all'?'Show all':'Show less',exact:true});if(await toggle.count())await toggle.click();
    await page.evaluate(()=>scrollTo(0,0));
    const end=await page.locator('.v15-leaderboard').evaluate(el=>Math.ceil(el.getBoundingClientRect().bottom+scrollY+100)),samples=[];
    for(let y=0;y<=end;y+=16){
     await page.evaluate(async y=>{scrollTo(0,y);await new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve())));},y);
     const result=await page.evaluate(async()=>{const {pinSample}=await import(/* @vite-ignore */ '/tests/v15-browser-fixture.tsx' as string);return pinSample();});
     samples.push(result);
    }
    if(process.env.V15_KIT_EVIDENCE_DIR)writeFileSync(`${process.env.V15_KIT_EVIDENCE_DIR}/pin-${mode}-${width}.json`,JSON.stringify(samples,null,2)+'\n');
    assert.ok(samples.every(row=>row.slotPosition==='sticky'&&row.slotBottom==='0px'&&row.directChild),'the sticky slot is a direct board child');
    assert.ok(samples.filter(row=>row.parentMinTop<=row.expectedTop).every(row=>Math.abs(row.pinTop-row.expectedTop)<.1),'pin.top == min(slot.top, innerHeight - pin.height)');
    // Before the board has a full row in view, native sticky positioning is
    // constrained by its parent. It must not move above the board to fit.
    assert.ok(samples.filter(row=>row.parentMinTop>row.expectedTop).every(row=>Math.abs(row.pinTop-row.parentMinTop)<.1&&row.pinTop+row.pinHeight>row.viewportHeight),'partially entering board retains its native sticky start boundary');
    assert.ok(samples.every(row=>row.position!=='fixed'&&row.pinTop>=row.boardTop&&row.pinTop+row.pinHeight<=row.boardBottom+.1),'the copy remains bounded by the board');
    assert.ok(samples.every(row=>row.visible===(!row.realOnScreen&&row.rowsOnScreen)),'only show the copy when the real row is off screen and rows sit above the slot');
    assert.deepEqual(samples.flatMap(row=>row.deadZone),[],'an empty pin slot never swallows clicks on the rows beneath it');
    assert.deepEqual(samples.flatMap(row=>row.coversOutsideBoard),[],'nothing outside the board sits under a visible pin');
    assert.equal(new Set(samples.map(row=>row.nextSectionDocTop)).size,1,'the next section must not move');
   }
  });
  await t.test('an inline periods array with stable values does not restore scroll on rerender',async()=>{
   const result=await page.evaluate(async()=>{const {inlinePeriodsScrollCalls}=await import(/* @vite-ignore */ '/tests/v15-browser-fixture.tsx' as string);return inlinePeriodsScrollCalls();});
   assert.equal(result,0);
  });
  if(process.env.V15_KIT_EVIDENCE_DIR)writeFileSync(`${process.env.V15_KIT_EVIDENCE_DIR}/browser-errors.json`,JSON.stringify(errors,null,2)+'\n');
  assert.deepEqual(errors,[]);await context.close();
 }finally{await browser.close();await server.close();}
});

test('every candidate compound starts with a room class, including functional pseudos',()=>{
 const legal=['.effort-page .effort-row:first-child','.effort-page>.effort-row:not(.effort-hidden)','.effort-page .effort-row:has(.effort-child)','.effort-page .effort-row:is(.effort-first,.effort-last):where(.effort-active)'];
 for(const selector of legal)assert.deepEqual(candidateCssProblems(`${selector}{display:grid}`),[],selector);
 const planted=['.effort-page :first-child','.effort-page :not(.effort-x)','.effort-page :has(.effort-child)','.effort-page .effort-row:not(button)','.effort-page .effort-row:has(.other-child)','.effort-page .effort-row:not(.effort-x,:first-child)','.effort-page .effort-row:has(.effort-x :first-child)'];
 assert.deepEqual(planted.map(selector=>candidateCssProblems(`${selector}{display:grid}`).length>0),planted.map(()=>true));
});

test('future candidate styles can lay out their own room but cannot fork or override kit properties',()=>{
 assert.deepEqual(candidateCssProblems('.effort-page .effort-grid{display:grid;gap:var(--v15-seam)}'),[]);
 for(const css of ['.effort-page .v15-card{padding:0}', '.effort-page{--v15-card:red}', '.effort-page button{font-size:18px}', '.effort-page button{display:grid}', '.effort-page section+section{display:grid}', '.effort-page [data-variant=primary]{display:grid}', '.effort-page h2{display:grid}', '.effort-page *{display:grid}', '.effort-page [class~="v15-card"]{display:grid}', '.effort-page :is(button,.effort-row){display:grid}', '.effort-page :where(.effort-row,div){display:grid}', '.effort-page .other-room{display:grid}', '.effort-grid{display:grid}', '.effort-page{color:var(--v15-ink)}'])assert.ok(candidateCssProblems(css).length,css);
 for(const file of files('').filter(f=>f.endsWith('.css')&&!f.startsWith('baseline/')&&!f.startsWith('v15/'))){if(manifest.sha256[file])continue;assert.deepEqual(candidateCssProblems(read(file)),[],file);}
 const additions=files('').filter(f=>f.endsWith('.tsx')&&!f.startsWith('baseline/')&&!f.startsWith('v15/')&&!f.startsWith('tests/')&&!manifest.sha256[f]&&!registered.has(f));
 for(const file of additions){const source=read(file);assert.deepEqual(candidateTsxProblems(source),[],file);if(!/className=["'][^"']*\b[\w-]+-page\b/.test(source))continue;assert.match(source,/className=["']v15-kit [\w-]+-page/,file);assert.match(source,/from ['"][^'"]*\/v15(?:\/index)?['"]/,file);assert.doesNotMatch(source,/className=["']v15-(?!kit\b)/,file);}
});
