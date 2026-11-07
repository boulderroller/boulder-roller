import {mkdir,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import assert from 'node:assert/strict';
import {launch,openPage,domHelpers} from '../tools/page-tools.mjs';

const [base,out,...only]=process.argv.slice(2);
if(!base||!out)throw Error('Usage: capture-climb-v17.mjs <base URL> <output directory> [state names]');
await mkdir(out,{recursive:true});
const browser=await launch(),results=[];
const states=[['owner','wises','rider'],['visitor','wises','visitor'],['signed-out','wises','anon'],['new-best','new-best','rider'],['successor','successor','rider'],['no-vault-rides','no-vault-rides','rider'],['no-vault-empty','no-vault-empty','rider']];
try{
 for(const width of [1440,390]){
  const size={width,height:width===390?844:900};
  const open=async(params)=>openPage(browser,`${base}/?${new URLSearchParams({'climb-preview':'1',variant:'climb-v17',...params})}`,size);
  const capture=async(name,opened,selector)=>{
   const {page,consoleErrors}=opened;
   const metrics=await page.evaluate(helper=>{
    const {visible}=(0,eval)(`(${helper})`)(),smallText=[];
    const walk=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);let node;
    while((node=walk.nextNode())){const el=node.parentElement;if(!node.textContent.trim()||!el||!visible(el)||['SCRIPT','STYLE'].includes(el.tagName))continue;const s=getComputedStyle(el),size=parseFloat(s.fontSize)*(el instanceof SVGTextElement?Math.hypot(el.getScreenCTM()?.a??1,el.getScreenCTM()?.b??0):1);if(size<10.99)smallText.push(node.textContent);}
    return {smallText,overflowX:document.documentElement.scrollWidth>innerWidth};
   },domHelpers.toString());
   assert.deepEqual(consoleErrors,[],name);assert.deepEqual(metrics.smallText,[],name);assert.equal(metrics.overflowX,false,name);
   await page.evaluate(()=>document.activeElement?.blur());
   const file=`${width}-${name}.png`;if(selector)await page.locator(selector).screenshot({path:join(out,file),animations:'disabled'});else await page.screenshot({path:join(out,file),fullPage:true,animations:'disabled'});
   results.push({file,url:page.url(),width,...metrics,consoleErrors:[...consoleErrors]});console.log(file);
  };
  for(const [name,scenario,viewer] of states.filter(([name])=>!only.length||only.includes(name))){const opened=await open({scenario,viewer});await capture(name,opened);await opened.context.close();}
  for(const bonding of only.length&&!only.includes('backing')?[]:['prebond','bonded','stale','rehearsal']){
   const opened=await open({bonding});await capture(`backing-${bonding}`,opened,'#backing');
   if(bonding==='bonded'||bonding==='prebond'){
    const {page}=opened;await page.getByRole('button',{name:'Deposit',exact:true}).click();
    if(bonding==='bonded')await capture('deposit-bonded-entry',opened,'dialog[open]');
    await page.getByRole('button',{name:'Continue',exact:true}).click();await capture(`deposit-${bonding}-ready`,opened,'dialog[open]');
    if(bonding==='bonded'){await page.getByRole('button',{name:'Token: jitoSOL',exact:true}).click();await page.getByRole('option',{name:'SOL',exact:true}).click();await capture('deposit-sol-ready',opened,'dialog[open]');}
   }
   await opened.context.close();
  }
 }
 await writeFile(join(out,only.length?`results-${only.join('-')}.json`:'results.json'),JSON.stringify(results,null,2)+'\n');
}finally{await browser.close();}
