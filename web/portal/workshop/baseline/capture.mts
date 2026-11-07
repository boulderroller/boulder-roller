// Local fixture captures only. Run from web/portal with: npx tsx workshop/baseline/capture.mts
import {chromium} from '@playwright/test';
import {mkdir,writeFile,readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {baselineRooms,baselineScenario} from './model';
const origin=process.env.WORKSHOP_URL??'http://localhost:4324';
const output=new URL('./evidence/',import.meta.url);await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true});
const filter=process.env.CAPTURE_ROOM;
const jobs=baselineRooms.filter(r=>!filter||r.id===filter).flatMap(room=>room.scenarios.flatMap(s=>[1440,390].map(width=>({room:room.id,id:s.id,width}))));
const records:any[]=filter?JSON.parse(await readFile(new URL('captures.json',output),'utf8')).filter((r:any)=>r.room!==filter):[];const failures:unknown[]=[];
async function worker(){while(jobs.length){const job=jobs.shift()!;const {room,id,width}=job;const viewport={width,height:width===1440?1000:844};const s=baselineScenario(room,id);const page=await browser.newPage({viewport});const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));const escaped:string[]=[];page.on('request',r=>{if(new URL(r.url()).hostname.includes('api.boulderroller'))escaped.push(r.url());});
 try{
 const url=`${origin}/baseline/index.html?room=${room}&scenario=${id}`;
 await page.goto(url);await page.waitForTimeout(['error','privacy-error'].includes(id)?7400:1500);
 let action='Scenario selected';
 if(id==='stale'){await page.evaluate(()=>window.postMessage({type:'baseline-stale'},location.origin));await page.waitForTimeout(room==='notifications'?7400:300);action='Data loaded, then retained-data unavailable control';}
 if(room==='upload'&&['uploading','processing','complete','duplicate','failure'].includes(id)){
 await page.locator('input[type=file]').setInputFiles({name:'first-ride.gpx',mimeType:'application/gpx+xml',buffer:Buffer.from('<gpx version="1.1"><trk><name>First ride</name></trk></gpx>')});
 await page.getByRole('dialog',{name:'Upload ride',exact:true}).getByRole('button',{name:'Upload ride',exact:true}).click();await page.waitForTimeout(1200);action='Supplied upload-entry file chosen; Upload ride pressed; selected local response';
 }
 const overflow=await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth);
 const file=`${room}-${id}-${width}.png`;const image=await page.screenshot({path:new URL(file,output).pathname,animations:'disabled'});
 const text=await page.locator('body').innerText();if(!text.trim())throw Error('Empty baseline');
 const record={room,candidate:s.candidate,scenario:id,viewer:s.viewer,viewport,url,sourceUrl:'https://app.boulderroller.xyz'+s.route,sourceRevision:s.source.revision,fixtureSource:s.source.file,capturedAt:new Date().toISOString(),kind:'local-implementation-baseline-supplied-fixture',action,file,sha256:createHash('sha256').update(image).digest('hex'),overflow,pageErrors:errors,escapedApiRequests:escaped,text:text.slice(0,350)};records.push(record);if(errors.length||escaped.length||overflow>1)failures.push(record);
 console.log(`${room}/${id}/${width}: ${errors.length?'ERROR':overflow>1?'OVERFLOW':'captured'}`);
 }catch(e){failures.push({...job,error:String(e)});console.log(`${room}/${id}/${width}: FAILED ${e}`);}finally{await page.close();}
}}
await Promise.all([worker(),worker(),worker()]);await browser.close();
await writeFile(new URL('captures.json',output),JSON.stringify(records,null,2)+'\n');
await writeFile(new URL('capture-checks.json',output),JSON.stringify({captured:records.length,failures},null,2)+'\n');
if(failures.length)process.exitCode=1;
