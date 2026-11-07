import {chromium,expect} from '@playwright/test';
import assert from 'node:assert/strict';
import {writeFile} from 'node:fs/promises';
const origin=process.env.WORKSHOP_URL??'http://localhost:4324';
const browser=await chromium.launch({headless:true});const results:unknown[]=[];
for(const width of [1440,390]){
 const page=await browser.newPage({viewport:{width,height:width===1440?1000:844}});page.setDefaultTimeout(10000);
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 const current=()=>page.locator('.baseline-workshop:not([hidden])');
 const frame=()=>current().locator('iframe').contentFrame();
 const choose=async(room:string,id?:string)=>{if(!page.url().startsWith(origin))await page.goto(`${origin}/?surface=${room}${id?'&scenario='+id:''}`);else await page.getByLabel('Workshop page',{exact:true}).selectOption(room);await expect(current()).toHaveCount(1);if(id)await current().getByLabel('Baseline scenario',{exact:true}).selectOption(id);await expect(frame().locator('body')).not.toBeEmpty();await page.waitForTimeout(600);};
 const check=async(name:string,run:()=>Promise<void>)=>{try{await run();results.push({width,name,pass:true});console.log(`${width} ${name}: pass`);}catch(e){results.push({width,name,pass:false,error:String(e)});console.log(`${width} ${name}: FAIL ${e}`);}};
 await check('Rides search, filters and upload cancellation',async()=>{
 await choose('rides','library');await expect(frame().getByRole('link',{name:/Waiting Ride/})).toBeVisible();
 const search=frame().getByPlaceholder('Search rides');await search.fill('no supplied match');await expect(frame().getByText('No matching rides')).toBeVisible();await search.fill('');
 for(const label of ['With CAL','Long rides','Climbing','All rides'])await frame().getByRole('button',{name:label,exact:true}).click();
 await frame().locator('header').getByRole('button',{name:'Upload ride',exact:true}).click();await expect(frame().getByRole('dialog',{name:'Upload ride',exact:true})).toBeVisible();
 await frame().getByRole('dialog',{name:'Upload ride',exact:true}).getByRole('button',{name:'Cancel',exact:true}).first().click();await expect(frame().getByPlaceholder('Search rides')).toBeVisible();
 });
 await check('Imported Portfolio survives real Profile tabs and export',async()=>{
 await choose('portfolio','collection');await expect(frame().getByRole('button',{name:'Collect DUNG',exact:true})).toBeVisible();
 await current().getByRole('button',{name:'Export scenario',exact:true}).click();const input=current().getByLabel('Baseline scenario JSON');await expect(input).not.toHaveValue('');await expect(input).not.toHaveValue('');const data=JSON.parse(await input.inputValue());data.responses['GET /retained-unrequested-response']={source:'import-roundtrip-control'};await input.fill(JSON.stringify(data));await current().getByRole('button',{name:'Load scenario',exact:true}).click();
 await frame().getByRole('tab',{name:'Overview',exact:true}).click();await expect(page.getByLabel('Workshop page',{exact:true})).toHaveValue('profile');await frame().getByRole('tab',{name:'Portfolio',exact:true}).click();await expect(current().getByLabel('Baseline scenario',{exact:true})).toHaveValue('collection');await expect(frame().getByText('5.05',{exact:true})).toBeVisible();
 await current().getByRole('button',{name:'Export scenario',exact:true}).click();await expect(input).not.toHaveValue('');assert.deepEqual(JSON.parse(await input.inputValue()).responses['GET /retained-unrequested-response'],{source:'import-roundtrip-control'});await current().getByRole('button',{name:'Close baseline data',exact:true}).click();
 await frame().getByRole('button',{name:'Add funds',exact:true}).click();await expect(frame().getByRole('dialog')).toBeVisible();await frame().getByRole('button',{name:/Cancel|Close/}).first().click();
 await frame().getByRole('button',{name:'Withdraw to wallet',exact:true}).click();await expect(frame().getByRole('dialog')).toBeVisible();await frame().getByRole('button',{name:/Cancel|Close/}).first().click();
 });
 await check('Notifications read, Alerts destination and Return',async()=>{
 await choose('notifications','unread');await frame().getByRole('button',{name:'Clear unread',exact:true}).click();await expect(frame().locator('.notifications-log__row')).toHaveAttribute('data-state','read');await frame().getByRole('link',{name:'Alerts',exact:true}).click();await expect(page.getByLabel('Workshop page',{exact:true})).toHaveValue('settings');await expect(current().getByLabel('Baseline scenario',{exact:true})).toHaveValue('alerts');await expect(frame().getByRole('switch',{name:'Rank moves',exact:true})).toBeVisible();await frame().getByRole('switch',{name:'Rank moves',exact:true}).click();await current().getByRole('button',{name:'Return',exact:true}).click();await expect(page.getByLabel('Workshop page',{exact:true})).toHaveValue('notifications');await expect(frame().locator('.notifications-log__row')).toHaveAttribute('data-state','read');
 });
 await check('Settings validation, local save and route export',async()=>{
 await choose('settings','performance');const weight=frame().locator('input[type=number]');await weight.fill('0');await weight.blur();await expect(frame().getByText(/Enter a weight between/)).toBeVisible();await weight.fill('75');await weight.blur();await frame().getByRole('button',{name:'Save',exact:true}).click();await expect(frame().getByText('Saved',{exact:true}).first()).toBeVisible();
 for(const label of ['Identity','Privacy','Connections','Alerts'])await frame().getByRole('button',{name:label,exact:true}).click();
 await current().getByRole('button',{name:'Export scenario',exact:true}).click();await expect(current().getByLabel('Baseline scenario JSON')).not.toHaveValue('');const data=JSON.parse(await current().getByLabel('Baseline scenario JSON').inputValue());assert.match(data.route,/tab=alerts/);await current().getByRole('button',{name:'Close baseline data',exact:true}).click();
 });
 await check('Search categories, result destination and public boundary',async()=>{
 await choose('search','results');const search=frame().getByPlaceholder('Search rides, climbs, riders');await search.fill('tim');await expect(frame().getByText('Tim Trail',{exact:true}).last()).toBeVisible();
 for(const label of ['Climbs','Rides','All','Riders'])await frame().locator('.search-sheet__words').getByRole('button',{name:label,exact:true}).click();
 await frame().getByText('Tim Trail',{exact:true}).last().click();await expect(page.getByLabel('Workshop page',{exact:true})).toHaveValue('profile');await expect(current().getByLabel('Baseline scenario',{exact:true})).toHaveValue('public');await expect(frame().getByRole('tab',{name:'Portfolio',exact:true})).toHaveCount(0);
 });
 await check('Private profile redaction and wrong-room import rejection',async()=>{
 await choose('profile','private');await expect(frame().getByText(/This profile is private/)).toBeVisible();await expect(frame().getByText('Turns climb repeats into signal.',{exact:true})).toHaveCount(0);await expect(frame().getByRole('tab',{name:'Training',exact:true})).toHaveCount(0);
 await current().getByRole('button',{name:'Export scenario',exact:true}).click();const input=current().getByLabel('Baseline scenario JSON');await expect(input).not.toHaveValue('');const data=JSON.parse(await input.inputValue());data.candidate='portfolio-v1';await input.fill(JSON.stringify(data));await current().getByRole('button',{name:'Load scenario',exact:true}).click();await expect(current().getByRole('alert')).toContainText('room, V1 candidate and viewer');await page.keyboard.press('Escape');await expect(current().getByRole('button',{name:'Data',exact:true})).toBeFocused();
 });
 await check('Upload validation, privacy and cancellation',async()=>{
 await choose('upload','file');const dialog=frame().getByRole('dialog',{name:'Upload ride',exact:true});await frame().locator('input[type=file]').setInputFiles({name:'not-a-ride.txt',mimeType:'text/plain',buffer:Buffer.from('not a ride')});await expect(dialog.getByRole('button',{name:'Upload ride',exact:true})).toBeDisabled();await frame().locator('input[type=file]').setInputFiles({name:'first-ride.gpx',mimeType:'application/gpx+xml',buffer:Buffer.from('<gpx version="1.1"><trk><name>First ride</name></trk></gpx>')});await expect(dialog.getByRole('button',{name:'Upload ride',exact:true})).toBeEnabled();await dialog.getByRole('button',{name:'Who can see this ride?',exact:true}).click();const audience=frame().getByRole('dialog',{name:'Who can see this ride?',exact:true});await audience.getByRole('radio',{name:'Only you',exact:true}).check();await audience.getByRole('button',{name:'Close',exact:true}).click();await dialog.getByRole('button',{name:'Cancel',exact:true}).first().click();await expect(page.getByLabel('Workshop page',{exact:true})).toHaveValue('rides');
 });
 results.push({width,name:'Browser runtime errors',pass:errors.length===0,errors});await page.close();
}
await browser.close();await writeFile(new URL('./evidence/interactions.json',import.meta.url),JSON.stringify(results,null,2)+'\n');if(results.some((r:any)=>!r.pass))process.exitCode=1;
