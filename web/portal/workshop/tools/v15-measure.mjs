import {mkdir,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {launch,openPage,sizes,fileStem,domHelpers} from './page-tools.mjs';

const [baseUrl,outDir,...args]=process.argv.slice(2),paths=[],cards=['.c15-card'];
for(let i=0;i<args.length;i++){if(args[i]==='--card'){if(!args[i+1])throw new Error('--card needs a class or selector');const card=args[++i];cards.push(card.startsWith('.')?card:`.${card}`);}else paths.push(args[i]);}
if(!baseUrl||!outDir||!paths.length)throw new Error('Usage: node workshop/tools/v15-measure.mjs <baseUrl> <outDir> <path>... [--card class]');
await mkdir(outDir,{recursive:true});
const browser=await launch();
try{for(const path of paths)for(const size of sizes){
 const url=new URL(path,baseUrl).href,{page,context,consoleErrors}=await openPage(browser,url,size);
 const query=new URL(url).searchParams,state=query.get('state');
 if(query.get('feed-preview')==='1'&&['feed-v11','feed-v12','feed-v13'].includes(query.get('variant'))&&state){
  if(!['ready','loading','empty','error'].includes(state))throw new Error(`Unknown Feed state: ${state}`);
  // Exercise the same settings message as the parent workshop; preview URLs stay unchanged.
  await page.evaluate(state=>window.postMessage({type:'feed-settings',settings:{state}},location.origin),state);
  await page.waitForFunction(({state,variant})=>document.querySelector(`.f${variant.slice('feed-v'.length)}-page`)?.getAttribute('data-state')===state,{state,variant:query.get('variant')});
 }
 if(query.get('climb-preview')==='1'&&query.get('variant')==='climb-v16'&&state){
  if(!['ready','loading','empty','error'].includes(state))throw new Error(`Unknown Climb state: ${state}`);
  await page.evaluate(state=>window.postMessage({type:'climb-settings',settings:{state}},location.origin),state);
  await page.waitForFunction(state=>document.querySelector('.c16-page')?.getAttribute('data-state')===state,state);
 }
 const metrics=await page.evaluate(({helperSource,selector})=>{
  const {visible,domPath}=(0,eval)(`(${helperSource})`)();
  const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT),smallText=[];
  let totalTextArea=0,heavyTextArea=0,node;
  while((node=walker.nextNode())){
   const element=node.parentElement;if(!node.textContent.trim()||!element||!visible(element)||/^(SCRIPT|STYLE|NOSCRIPT)$/.test(element.tagName))continue;
   const range=document.createRange();range.selectNodeContents(node);
   const area=[...range.getClientRects()].reduce((sum,rect)=>sum+rect.width*rect.height,0);if(!area)continue;
   const style=getComputedStyle(element),weight=Number(style.fontWeight)||400,size=element instanceof SVGTextElement?Number((parseFloat(style.fontSize)*Math.hypot(element.getScreenCTM()?.a??1,element.getScreenCTM()?.b??0)).toFixed(3)):parseFloat(style.fontSize);
   totalTextArea+=area;if(weight>=500)heavyTextArea+=area;
   if(size<11)smallText.push({path:domPath(element),text:node.textContent.trim(),fontSize:size});
  }
  const gaps=[];
  for(const element of document.querySelectorAll(selector)){
   const next=element.nextElementSibling;if(!visible(element)||!next?.matches(selector)||!visible(next))continue;
   const a=element.getBoundingClientRect(),b=next.getBoundingClientRect();
   if(Math.min(a.right,b.right)>Math.max(a.left,b.left)&&b.top>=a.bottom)gaps.push(b.top-a.bottom);
   else if(Math.min(a.bottom,b.bottom)>Math.max(a.top,b.top)&&b.left>=a.right)gaps.push(b.left-a.right);
  }
  return {heavyShare:totalTextArea?heavyTextArea/totalTextArea:0,heavyTextArea,totalTextArea,smallText,cardGaps:[...new Set(gaps.map(gap=>Math.round(gap*100)/100))].sort((a,b)=>a-b),overflowX:document.documentElement.scrollWidth>innerWidth};
 },{helperSource:domHelpers.toString(),selector:cards.join(',')});
 const stem=join(outDir,`${fileStem(path)}-${size.name}`);
 await page.screenshot({path:`${stem}-first.png`,animations:'disabled'});
 await page.screenshot({path:`${stem}-full.png`,fullPage:true,animations:'disabled'});
 await writeFile(`${stem}.json`,JSON.stringify({url,viewport:{width:size.width,height:size.height},deviceScaleFactor:2,...metrics,consoleErrors},null,2)+'\n');
 console.log(`${stem}: heavy ${(metrics.heavyShare*100).toFixed(3)}%; small ${metrics.smallText.length}; gaps ${metrics.cardGaps.join(',')}; overflow ${metrics.overflowX}; errors ${consoleErrors.length}`);
 await context.close();
}}finally{await browser.close();}
