import {chromium,expect} from '@playwright/test';
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {baselineScenario} from './model';
const output=new URL('./evidence/',import.meta.url),origin=process.env.WORKSHOP_URL??'http://localhost:4324';
const browser=await chromium.launch();const records:any[]=[];const checks:any[]=[];
for(const width of [1440,390]){
 const viewport={width,height:width===1440?1000:844};const p=await browser.newPage({viewport,hasTouch:width===390});
 for(const [room,id,detail]of [['portfolio','collection','funding'],['portfolio','collection','withdrawal'],['upload','file','audience'],['upload','file','invalid-file'],['search','results','rider-results'],['training','figures','power-curve']] as const){
  const s=baselineScenario(room,id),url=`${origin}/baseline/index.html?room=${room}&scenario=${id}`;const errors:string[]=[];const error=(e:Error)=>errors.push(e.message);p.on('pageerror',error);
  try{await p.goto(url);await p.waitForTimeout(1500);
  if(detail==='funding'||detail==='withdrawal'){await p.getByRole('button',{name:detail==='funding'?'Add funds':'Withdraw to wallet',exact:true}).click();await expect(p.getByRole('dialog')).toBeVisible();}
  if(detail==='audience'){await p.getByRole('button',{name:'Who can see this ride?',exact:true}).click();await expect(p.getByRole('radio',{name:'Only you',exact:true})).toBeVisible();if(width===390)await p.getByRole('radio',{name:'Only you',exact:true}).tap();else await p.getByRole('radio',{name:'Only you',exact:true}).check();}
  if(detail==='invalid-file'){await p.locator('input[type=file]').setInputFiles({name:'not-a-ride.txt',mimeType:'text/plain',buffer:Buffer.from('not a ride')});await expect(p.getByRole('dialog',{name:'Upload ride',exact:true}).getByRole('button',{name:'Upload ride',exact:true})).toBeDisabled();}
  if(detail==='rider-results'){await p.getByPlaceholder('Search rides, climbs, riders').fill('tim');await expect(p.getByText('Tim Trail',{exact:true}).last()).toBeVisible();}
  if(detail==='power-curve')await p.getByText('Power curve',{exact:true}).first().scrollIntoViewIfNeeded();
  const file=`${room}-${detail}-${width}.png`,image=await p.screenshot({path:new URL(file,output).pathname,animations:'disabled'});
  records.push({room,candidate:s.candidate,scenario:id,viewer:s.viewer,viewport,url,sourceUrl:'https://app.boulderroller.xyz'+s.route,sourceRevision:s.source.revision,fixtureSource:s.source.file,capturedAt:new Date().toISOString(),kind:'local-implementation-baseline-supplied-fixture',action:detail,file,sha256:createHash('sha256').update(image).digest('hex')});checks.push({width,detail,pass:errors.length===0,errors});
  }catch(e){checks.push({width,detail,pass:false,error:String(e)});}finally{p.off('pageerror',error);}
 }
 for(const [label,url]of [['sign-in','https://app.boulderroller.xyz/profile'],['public-climb','https://app.boulderroller.xyz/climbs/aec5dcc5-ea67-46ec-8b8a-4f0d77fa1862']]){
  try{await p.goto(url);await p.waitForTimeout(6000);const text=await p.locator('body').innerText();const file=`live-${label}-${width}.png`;const image=await p.screenshot({path:new URL(file,output).pathname,animations:'disabled'});records.push({room:label,viewer:'signed-out',viewport,url:p.url(),requestedUrl:url,sourceRevision:null,capturedAt:new Date().toISOString(),kind:'current-live-capture',file,sha256:createHash('sha256').update(image).digest('hex'),text:text.slice(0,1800)});}catch(e){checks.push({width,detail:'live-'+label,pass:false,error:String(e)});}
 }
 await p.close();
}
await browser.close();await writeFile(new URL('additional-captures.json',output),JSON.stringify(records,null,2)+'\n');await writeFile(new URL('additional-checks.json',output),JSON.stringify(checks,null,2)+'\n');console.log(JSON.stringify(checks));if(checks.some(c=>!c.pass))process.exitCode=1;
