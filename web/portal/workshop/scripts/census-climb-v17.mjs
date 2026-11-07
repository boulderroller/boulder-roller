import {execFileSync} from 'node:child_process';
import {readFile,mkdir,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {join,resolve} from 'node:path';
import {launch,openPage,domHelpers} from '../tools/page-tools.mjs';

const [beforeBase,afterBase,out,startAt]=process.argv.slice(2);
if(!out)throw Error('Usage: census-climb-v17.mjs <main URL> <candidate URL> <output directory> [resume route]');
await mkdir(out,{recursive:true});
const repo=resolve(import.meta.dirname,'../../../..'),git=(...args)=>execFileSync('git',args,{cwd:repo,maxBuffer:100*1024*1024}),hash=data=>createHash('sha256').update(data).digest('hex');
const allowed=new Set(['entry.ts','main.tsx','roomRegistry.ts','tests/v15-guards.ts']);
const preserved=git('ls-tree','-r','--name-only','origin/main','web/portal/workshop').toString().trim().split('\n').filter(p=>!p.startsWith('web/portal/workshop/v15/')&&!allowed.has(p.replace('web/portal/workshop/','')));
const changed=[];
for(const path of preserved){const baseline=git('show',`origin/main:${path}`),current=await readFile(join(repo,path));if(hash(baseline)!==hash(current))changed.push(path);}
const source={base:git('rev-parse','origin/main').toString().trim(),checked:preserved.length,changed,effort:preserved.filter(p=>p.includes('/workshop/effort/')).length};
await writeFile(join(out,'sources.json'),JSON.stringify(source,null,2)+'\n');if(changed.length)throw Error(`Preservation failed: ${changed.join(', ')}`);

const routes=[];
const add=(name,params)=>routes.push({name,path:`/?${new URLSearchParams(params)}`});
for(const variant of ['current','candidate',...Array.from({length:13},(_,i)=>`candidate-v${i+2}`)])add(`ride-${variant}`,{preview:'1',variant,scenario:'recorded'});
for(let n=2;n<=16;n++)add(`climb-v${n}`,{'climb-preview':'1',variant:`climb-v${n}`,scenario:'wises',viewer:'rider'});
for(const n of [1,2,3,4,5,6,7,8,9,11,12,13])add(`feed-v${n}`,{'feed-preview':'1',variant:`feed-v${n}`,scenario:'mixed'});
for(let n=2;n<=7;n++)add(`map-v${n}`,{'map-preview':'1',variant:`map-v${n}`,scenario:'wises',viewer:'rider'});
add('profile-v2',{'profile-preview':'1',variant:'profile-v2',scenario:'owner'});
add('profile-v2-original',{'profile-preview':'1',variant:'profile-v2',scenario:'owner',draft:'original'});
for(let n=3;n<=6;n++)add(`profile-v${n}`,{[`profile-v${n}-preview`]:'1',variant:`profile-v${n}`,scenario:n===3?'recorded':'rider'});
for(const effort of ['wises','black-rock','estimated','interior'])for(const viewer of ['rider','visitor','anon'])add(`effort-${effort}-${viewer}`,{'effort-preview':'1',effort,gates:'v2',viewer});
const properties=['color','backgroundColor','backgroundImage','borderTop','borderRight','borderBottom','borderLeft','borderRadius','fontFamily','fontSize','fontWeight','lineHeight','paddingTop','paddingRight','paddingBottom','paddingLeft','marginTop','marginRight','marginBottom','marginLeft','rowGap','columnGap','display','position'];
const start=startAt?routes.findIndex(r=>r.name===startAt):0;
if(start<0)throw Error(`Unknown resume route: ${startAt}`);
const results=startAt?(JSON.parse(await readFile(join(out,'results.json'),'utf8'))).filter(r=>routes.slice(0,start).some(route=>route.name===r.name)):[];
if(startAt&&(results.length!==start*2||results.some(r=>r.differingProperties!==0)))throw Error('Resume requires a complete, passing prefix');
const browser=await launch();
try{
 const census=async(base,path,width)=>{
  // Use the canonical capture routine: visit lazy content and allow map camera
  // movements to finish. No elements or properties are excluded from comparison.
  const {context,page,consoleErrors:errors}=await openPage(browser,base+path,{width,height:width===390?844:900});
  const elements=await page.evaluate(({helper,properties})=>{
   const {visible,domPath}=(0,eval)(`(${helper})`)();
   return [...document.querySelectorAll('body,body *')].filter(visible).map(element=>{const rect=element.getBoundingClientRect(),style=getComputedStyle(element);return {path:domPath(element),box:Object.fromEntries(['x','y','width','height'].map(k=>[k,Math.round(rect[k])])),styles:Object.fromEntries(properties.map(k=>[k,style[k]]))};});
  },{helper:domHelpers.toString(),properties});
  await context.close();return {elements,errors};
 };
 for(const route of routes.slice(start))for(const width of [1440,390]){
  const before=await census(beforeBase,route.path,width),after=await census(afterBase,route.path,width),left=new Map(before.elements.map(e=>[e.path,e])),right=new Map(after.elements.map(e=>[e.path,e])),differences=[];
  for(const path of new Set([...left.keys(),...right.keys()])){
   const a=left.get(path),b=right.get(path);if(!a||!b){differences.push({path,property:'element',before:!!a,after:!!b});continue;}
   for(const group of ['box','styles'])for(const property of Object.keys(a[group]))if(a[group][property]!==b[group][property])differences.push({path,property:`${group}.${property}`,before:a[group][property],after:b[group][property]});
  }
  const row={...route,width,beforeCount:left.size,afterCount:right.size,differingProperties:differences.length,beforeSha256:hash(JSON.stringify(before.elements)),afterSha256:hash(JSON.stringify(after.elements)),beforeErrors:before.errors,afterErrors:after.errors};results.push(row);
  await writeFile(join(out,'results.json'),JSON.stringify(results,null,2)+'\n');
  console.log(`${route.name} ${width}: ${left.size}/${right.size} elements; ${differences.length} differences`);
  if(differences.length){await writeFile(join(out,'differences.json'),JSON.stringify({row,differences},null,2)+'\n');throw Error(`Rendered preservation failed: ${route.name} ${width}`);}
 }
}finally{await browser.close();}
