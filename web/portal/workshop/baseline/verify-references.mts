import {chromium,expect} from '@playwright/test';
import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
import {stravaReferencesFor} from './referenceModel';
const origin=process.env.WORKSHOP_URL??'http://localhost:4324';
const output=new URL('./evidence/reference-controls/',import.meta.url);
await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true});
const results:{width:number;name:string;pass:boolean;error?:string}[]=[];
const captures:unknown[]=[];
try {for(const width of [1440,390]){
 const context=await browser.newContext({viewport:{width,height:width===1440?1000:844},hasTouch:width===390,permissions:['clipboard-read','clipboard-write']});
 const page=await context.newPage();page.setDefaultTimeout(12000);
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 const current=()=>page.locator('.baseline-workshop:not([hidden])');
 const frame=()=>current().locator('iframe').contentFrame();
 const choose=async(room:string,id?:string)=>{if(!page.url().startsWith(origin))await page.goto(`${origin}/?surface=${room}`);else await page.getByLabel('Workshop page',{exact:true}).selectOption(room);if(id){await current().getByLabel('Baseline scenario',{exact:true}).selectOption(id);await expect.poll(()=>current().locator('iframe').evaluate((e:HTMLIFrameElement)=>e.contentWindow!.location.search)).toContain('scenario='+id);}await expect(frame().locator('#root')).not.toBeEmpty();};
 const check=async(name:string,run:()=>Promise<void>)=>{try{await run();results.push({width,name,pass:true});console.log(`${width} ${name}: pass`);}catch(e){results.push({width,name,pass:false,error:String(e)});console.log(`${width} ${name}: FAIL ${e}`);}};
 const capture=async(name:string,fullPage=false)=>{const file=`${name}-${width}.png`;await page.screenshot({path:new URL(file,output).pathname,fullPage});captures.push({file,url:page.url(),viewport:{width,height:width===1440?1000:844},date:new Date().toISOString(),kind:'local retained V1 with historical Strava reference',sourceRevision:'a63ffc77f9638b78d3a404be2575aaa7ddd9c145'});};
 await check('Adjacent Strava sections, source widths and Squint on both images',async()=>{
  await choose('profile','owner');await expect(frame().getByRole('heading',{name:'Dung Beetle Phoenix',exact:true})).toBeVisible();
  await current().getByRole('button',{name:width===1440?'Desktop preview':'Phone preview',exact:true}).click();
  const reference=current().getByRole('button',{name:'Strava reference',exact:true});await reference.focus();await page.keyboard.press('Space');await expect(reference).toHaveAttribute('aria-pressed','true');
  const panel=current().getByRole('complementary',{name:'Strava reference'});await expect(panel).toBeVisible();
  const squint=current().getByRole('button',{name:'Squint',exact:true});await squint.focus();await page.keyboard.press('Space');await expect(squint).toHaveAttribute('aria-pressed','true');
  await expect(current().locator('.preview-size')).toHaveCSS('filter','blur(5px)');await expect(panel.locator('.reference-image')).toHaveCSS('filter','blur(5px)');
  if(width===1440)await capture('profile-squint');
  await squint.click();await expect(current().locator('.preview-size')).toHaveCSS('filter','none');
  const image=panel.locator('img');await expect(image).toHaveAttribute('alt',/1440 px capture/);
  if(width===1440){await expect.poll(()=>current().locator('iframe').evaluate((e:HTMLIFrameElement)=>e.contentWindow!.innerWidth)).toBe(1440);const a=await current().locator('.preview-stage').boundingBox(),b=await panel.boundingBox();assert.ok(a&&b&&b.x>=a.x+a.width-1);await capture('profile-reference');}
  for(const section of stravaReferencesFor('profile')){await panel.getByRole('button',{name:section.title,exact:true}).click();await expect(image).toHaveAttribute('src',new RegExp(section.file.replace('.','\\.')));await expect.poll(()=>image.evaluate((e:HTMLImageElement)=>e.naturalWidth)).toBe(section.pixelWidth);}
  if(width===390)await panel.getByRole('button',{name:'Phone',exact:true}).tap();else await panel.getByRole('button',{name:'Phone',exact:true}).click();await expect(panel.locator('figcaption')).toContainText('430 px phone source');
  if(width===390){await expect.poll(()=>current().locator('iframe').evaluate((e:HTMLIFrameElement)=>e.contentWindow!.innerWidth)).toBe(390);const a=await current().locator('.preview-stage').boundingBox(),b=await panel.boundingBox();assert.ok(a&&b&&b.y>=a.y+a.height-1);await capture('profile-stacked',true);await panel.locator('.reference-heading').scrollIntoViewIfNeeded();await capture('profile-phone-reference');}
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await panel.getByRole('button',{name:'Close reference',exact:true}).click();await expect(reference).toBeFocused();await expect(reference).toHaveAttribute('aria-pressed','false');
 });
 await check('Reference and Squint controls preserve imports, room returns and frame state',async()=>{
  await choose('rides','library');await expect(frame().getByPlaceholder('Search rides')).toBeVisible();
  await current().getByRole('button',{name:'Export scenario',exact:true}).click();const input=current().getByLabel('Baseline scenario JSON');await expect(input).not.toHaveValue('');const data=JSON.parse(await input.inputValue());data.responses['GET /retained-control']={source:'reference-control-roundtrip'};await input.fill(JSON.stringify(data));await current().getByRole('button',{name:'Load scenario',exact:true}).click();
  await expect(current().getByLabel('Baseline scenario').locator('option:checked')).toContainText('Imported data');await frame().getByPlaceholder('Search rides').fill('no supplied match');await expect(frame().getByText('No matching rides')).toBeVisible();
  await current().getByRole('button',{name:'Strava reference',exact:true}).click();await current().getByRole('button',{name:'Squint',exact:true}).click();await expect(current().locator('.baseline-reference img')).toHaveAttribute('alt',/My Activities/);
  await choose('training','figures');await current().getByRole('button',{name:'Strava reference',exact:true}).click();const panel=current().locator('.baseline-reference');for(const section of stravaReferencesFor('training')){await panel.getByRole('button',{name:section.title,exact:true}).click();await expect.poll(()=>panel.locator('img').evaluate((e:HTMLImageElement)=>e.naturalWidth)).toBe(section.pixelWidth);}
  await choose('settings','identity');await current().getByRole('button',{name:'Strava reference',exact:true}).click();await current().getByRole('button',{name:'More settings',exact:true}).click();await expect(current().locator('.baseline-reference img')).toHaveAttribute('src',/21-settings-y900/);
  await choose('rides');await expect(current().getByRole('button',{name:'Strava reference',exact:true})).toHaveAttribute('aria-pressed','true');await expect(current().getByRole('button',{name:'Squint',exact:true})).toHaveAttribute('aria-pressed','true');await expect(frame().getByPlaceholder('Search rides')).toHaveValue('no supplied match');await current().getByRole('button',{name:'Squint',exact:true}).click();
  await current().getByRole('button',{name:'Export scenario',exact:true}).click();await expect(input).not.toHaveValue('');assert.deepEqual(JSON.parse(await input.inputValue()).responses['GET /retained-control'],{source:'reference-control-roundtrip'});
  await current().getByRole('button',{name:'Copy JSON',exact:true}).click();await expect(current().getByRole('button',{name:'Copied',exact:true})).toBeVisible();assert.deepEqual(JSON.parse(await page.evaluate(()=>navigator.clipboard.readText())).responses['GET /retained-control'],{source:'reference-control-roundtrip'});
  await capture('data-controls');await current().getByRole('button',{name:'Restore supplied scenario',exact:true}).click();await expect(current().getByLabel('Baseline scenario').locator('option:checked')).not.toContainText('Imported data');await expect(frame().getByPlaceholder('Search rides')).toHaveValue('');
  await current().getByRole('button',{name:'Export scenario',exact:true}).click();await expect(input).not.toHaveValue('');assert.equal(JSON.parse(await input.inputValue()).responses['GET /retained-control'],undefined);await page.keyboard.press('Escape');await expect(current().getByRole('button',{name:'Data',exact:true})).toBeFocused();
 });
 await check('Provenance separates source evidence and absent Strava references',async()=>{
  await choose('profile');await current().getByRole('button',{name:'Provenance',exact:true}).click();await expect(current().locator('.workshop-info')).toContainText('Historical Boulder Roller fixture captures');await expect(current().locator('.workshop-info').getByRole('link',{name:'Phone · 390 px',exact:true})).toBeVisible();
  await choose('portfolio');await expect(current().getByRole('button',{name:'Strava reference',exact:true})).toHaveCount(0);await current().getByRole('button',{name:'Provenance',exact:true}).click();await expect(current().locator('.workshop-info')).toContainText('No corresponding Strava screenshot was retained');
 });
 await check('Held data releases in place and offline reads can recover',async()=>{
  await choose('profile','loading');await current().getByRole('button',{name:'Release data',exact:true}).click();await expect(frame().getByRole('heading',{name:'Dung Beetle Phoenix',exact:true})).toBeVisible();await expect(current().getByRole('button',{name:'Data released',exact:true})).toBeDisabled();assert.equal(new URL(page.url()).searchParams.get('scenario'),'loading');
  await choose('notifications','stale');await expect(frame().locator('.notifications-log__row')).toHaveCount(1);await frame().getByRole('button',{name:'Clear unread',exact:true}).click();await expect(frame().locator('.notifications-log__row')).toHaveAttribute('data-state','read');await current().getByRole('button',{name:'Make retained data unavailable',exact:true}).click();await current().getByRole('button',{name:'Restore data availability',exact:true}).click();await expect(frame().locator('.notifications-log__row')).toHaveAttribute('data-state','read');await expect(current().getByRole('button',{name:'Make retained data unavailable',exact:true})).toBeVisible();
  for(const room of ['access','shell']){await choose(room,'loading');await current().getByRole('button',{name:'Release data',exact:true}).click();await expect(current().getByRole('button',{name:'Data released',exact:true})).toBeDisabled();if(room==='access')await expect(frame().getByRole('button',{name:'Enter invite code',exact:true})).toBeVisible();else await expect(frame().getByRole('heading',{name:'Guide',exact:true})).toBeVisible();}
 });
 if(width===390)await check('Phone touch Squint and held fixture upload release',async()=>{
  await choose('profile','owner');await current().getByRole('button',{name:'Squint',exact:true}).tap();await expect(current().locator('.preview-size')).toHaveCSS('filter','blur(5px)');await current().getByRole('button',{name:'Squint',exact:true}).tap();
  await choose('upload','uploading');await frame().locator('input[type=file]').setInputFiles({name:'first-ride.gpx',mimeType:'application/gpx+xml',buffer:Buffer.from('<gpx version="1.1"><trk><name>First ride</name></trk></gpx>')});await frame().getByRole('dialog',{name:'Upload ride',exact:true}).getByRole('button',{name:'Upload ride',exact:true}).click();await expect(frame().getByText('Saving file',{exact:true})).toBeVisible();await expect(frame().getByRole('button',{name:'Open ride',exact:true})).toHaveCount(0);await current().getByRole('button',{name:'Release data',exact:true}).tap();await expect(frame().getByRole('button',{name:'Open ride',exact:true})).toBeVisible();
 });
 results.push({width,name:'No browser runtime errors',pass:errors.length===0,...(errors.length?{error:errors.join('\n')}:{})});
 await context.close();
}} finally {await browser.close();await writeFile(new URL('checks.json',output),JSON.stringify({results,captures},null,2)+'\n');}
if(results.some(r=>!r.pass))process.exitCode=1;
