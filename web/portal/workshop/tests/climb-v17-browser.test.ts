import {test} from 'node:test';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {expect} from '@playwright/test';

test('Climb V17 rendered interaction and privacy contract',{timeout:150000},async t=>{
 const {createServer}=await import('vite'),{chromium}=await import('@playwright/test');
 const server=await createServer({configFile:fileURLToPath(new URL('../vite.config.ts',import.meta.url)),server:{port:0,host:'127.0.0.1',strictPort:false}});
 await server.listen();const address=server.httpServer!.address();assert.ok(address&&typeof address!=='string');
 const browser=await chromium.launch(),context=await browser.newContext({viewport:{width:1440,height:900},reducedMotion:'reduce'}),page=await context.newPage(),errors:string[]=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
 const base=`http://127.0.0.1:${address.port}/?climb-preview=1&variant=climb-v17`;
 const open=async(extra='')=>{await page.goto(base+extra);await page.locator('.climb-page').waitFor();await page.evaluate(()=>document.fonts.ready);await page.waitForTimeout(220);};
 try{
  await t.test('rider name opens the profile; row opens that effort; Back retains period, tab and scroll',async()=>{
   for(const width of [1440,390]){
    await page.setViewportSize({width,height:width===390?844:900});await open('&period=2015');
    const row=page.locator('.v15-board-rows .v15-board-row').first(),rider=row.locator('.v15-rider-link');
    await rider.scrollIntoViewIfNeeded();const box=await rider.boundingBox();assert.ok(box);assert.equal(await rider.evaluate(el=>getComputedStyle(el,'::before').height),'44px');assert.ok(await rider.evaluate(el=>{const b=el.getBoundingClientRect();return [-21,21].every(d=>document.elementFromPoint(b.left+b.width/2,b.top+b.height/2+d)?.closest('a')===el);}));
    const y=await page.evaluate(()=>scrollY),profileHref=await rider.getAttribute('href');await rider.click();await expect(page).toHaveURL(new URL(profileHref!,base).href);await expect(page.getByRole('heading',{name:'Morgan',exact:true})).toBeVisible();
    await page.goBack();await expect(page.getByLabel('Period',{exact:true})).toHaveValue('2015');await expect.poll(()=>page.evaluate(()=>scrollY)).toBeGreaterThan(y-3);assert.ok(Math.abs(await page.evaluate(()=>scrollY)-y)<3);
    const effortHref=await row.locator('.v15-effort-link').getAttribute('href');const medal=await row.locator('.v15-board-place').boundingBox();assert.ok(medal);await page.mouse.click(medal.x+medal.width/2,medal.y+medal.height/2);await expect(page).toHaveURL(new URL(effortHref!,base).href);await expect(page.getByRole('button',{name:'Back',exact:true})).toBeVisible();await page.getByRole('button',{name:'Back',exact:true}).click();
    await expect(page.getByLabel('Period',{exact:true})).toHaveValue('2015');await expect(page.getByRole('button',{name:'Overall',exact:true})).toHaveAttribute('aria-pressed','true');await expect.poll(()=>page.evaluate(()=>scrollY)).toBeGreaterThan(y-3);assert.ok(Math.abs(await page.evaluate(()=>scrollY)-y)<3);
   }
  });
  await t.test('tabs and periods use URL history, dim retained rows, and show exact founder help',async()=>{
   await open();await page.evaluate(()=>{(window as any).climbLoading=[];const observer=new MutationObserver(()=>{const table=document.querySelector('.v15-board-table[aria-busy=true]'),rows=table?.querySelector('.v15-board-rows');if(rows)(window as any).climbLoading.push({count:rows.children.length,opacity:getComputedStyle(rows).opacity});});observer.observe(document.querySelector('.v15-leaderboard')!,{subtree:true,attributes:true,childList:true});});await page.getByRole('button',{name:'Power verified',exact:true}).click();await expect(page).toHaveURL(/tab=qualified/);await expect(page.getByText('No power-verified times yet',{exact:true})).toBeVisible();assert.ok(await page.evaluate(()=>(window as any).climbLoading.some((s:any)=>s.count>0&&s.opacity==='0.5')));
   await page.goBack();await expect(page.getByRole('button',{name:'Overall',exact:true})).toHaveAttribute('aria-pressed','true');await expect(page.locator('.v15-board-row').first()).toBeVisible();
   await page.getByLabel('Period',{exact:true}).selectOption('2016');await expect(page).toHaveURL(/period=2016/);await page.reload();await expect(page.getByLabel('Period',{exact:true})).toHaveValue('2016');
   await page.getByRole('button',{name:'About leaderboard views',exact:true}).click();await expect(page.getByText("Each rider's fastest ascent. Power with ⚡ was measured by a power meter. Power with ≈ is an estimate from the time and the climb, at a standard rider weight.",{exact:true})).toBeVisible();
  });
  await t.test('the pinned row keeps the true place and is absent for visitors and signed-out viewers',async()=>{
   for(const width of [1440,390]){
    await page.setViewportSize({width,height:width===390?844:900});await open('&scenario=black-rock');
    const row=page.locator('.v15-board-rows [data-current=true]');const id=await row.getAttribute('data-row-id');
    await row.evaluate(el=>window.scrollTo(0,el.getBoundingClientRect().bottom+scrollY+4));await expect(page.locator('.v15-board-pin')).toHaveAttribute('data-visible','true');
    const pin=page.locator('.v15-board-pin [data-pinned=true]');assert.equal(await pin.getAttribute('data-row-id'),id);assert.equal(await pin.locator('.v15-board-place').innerText(),await row.locator('.v15-board-place').innerText());
    await row.scrollIntoViewIfNeeded();await expect(page.locator('.v15-board-pin')).toHaveAttribute('data-visible','false');
   }
   for(const viewer of ['visitor','anon']){await open(`&viewer=${viewer}`);assert.equal(await page.locator('[data-current=true],.v15-board-pin').count(),0);}
  });
  await t.test('keyboard focus, inset row focus and both figure and comparison interactions work',async()=>{
   await open('&scenario=new-best');await expect(page.getByText('New best',{exact:true}).first()).toBeVisible();await expect(page.locator('[data-plot=gap]')).toBeVisible();const row=page.locator('.v15-effort-link').first();await row.focus();await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab');
   const focus=await row.evaluate(el=>{const style=getComputedStyle(el,'::after');return {width:style.outlineWidth,offset:style.outlineOffset};});assert.equal(focus.width,'2px');assert.ok(parseFloat(focus.offset)<0);
   const controls=page.locator('.climb-page button:visible:not(:disabled),.climb-page select:visible,.climb-page a:visible,.climb-page [role=slider]:visible,.climb-page tr[tabindex]:visible');
   for(let i=0;i<await controls.count();i++){
    const control=controls.nth(i);if(await control.evaluate(el=>getComputedStyle(el).visibility==='hidden'))continue;
    await control.focus();await page.keyboard.press('Tab');await page.keyboard.press('Shift+Tab');
    assert.ok(await control.evaluate(el=>{const s=getComputedStyle(el,el.classList.contains('v15-effort-link')?'::after':null);return parseFloat(s.outlineWidth)>0&&s.outlineStyle!=='none';}),await control.getAttribute('aria-label')??await control.innerText());
   }
   const cursor=page.getByRole('slider',{name:'Effort cursor',exact:true});await cursor.focus();await page.keyboard.press('Home');await page.keyboard.press('ArrowRight');assert.equal(await cursor.getAttribute('aria-valuenow'),'1');
   await page.getByRole('button',{name:/^Compare:/}).click();await page.getByRole('option',{name:'None',exact:true}).click();assert.equal(await page.locator('[data-plot=gap]').count(),0);await expect(page).toHaveURL(/compare=none/);await page.getByRole('button',{name:/^Compare:/}).click();await page.getByRole('option',{name:/^Previous best/}).click();await expect(page.locator('[data-plot=gap]')).toBeVisible();
  });
  await t.test('rendered public views disclose no owner physiology or personal history on any hill',async()=>{
   for(const scenario of ['wises','black-rock','wall','andorra-road'])for(const viewer of ['visitor','anon']){
    await open(`&scenario=${scenario}&viewer=${viewer}`);const text=await page.locator('.climb-page').innerText();
    assert.doesNotMatch(text,/\b(?:mass|Threshold|Intensity|Load|zones|max heart rate|72 kg)\b/i);assert.doesNotMatch(text,/Your efforts|You and this hill|Your best/);
    if(scenario==='wall'){await expect(page.getByRole('heading',{name:'Levering Street / Lyceum Avenue',exact:true})).toBeVisible();assert.equal(await page.locator('.v15-power[data-kind=estimated] .v15-bolt').count(),0);assert.ok(await page.locator('.v15-power-range').count()>0);await expect(page.getByRole('img',{name:/^Estimated.*standard rider weight$/}).first()).toBeVisible();}
    if(scenario==='andorra-road')await expect(page.getByRole('heading',{name:'Andorra Road',exact:true})).toBeVisible();
   }
  });
  await t.test('light terrain readouts use the readable light-surface label colour',async()=>{
   await open();const colors=await page.evaluate(()=>[getComputedStyle(document.querySelector('.v15-card .v15-readouts dt')!).color,getComputedStyle(document.querySelector('.v15-note')!).color]);assert.equal(colors[0],colors[1]);
  });
  await t.test('estimated power ranges retain the readable dark-surface colour',async()=>{
   await open('&scenario=wall');const colors=await page.evaluate(()=>[getComputedStyle(document.querySelector('.v15-power[data-tone=dark] .v15-power-range')!).color,getComputedStyle(document.querySelector('.v15-power[data-tone=dark] .v15-power-unit')!).color]);assert.equal(colors[0],colors[1]);
  });
  await t.test('long hill names leave every masthead stat visible at intermediate widths',async()=>{
   for(const width of [1440,1366,1280,1100,950,390]){
    await page.setViewportSize({width,height:900});await open('&scenario=wall');
    const clipped=await page.locator('.v15-masthead').first().evaluate(hero=>{const box=hero.getBoundingClientRect();return [...hero.querySelectorAll('.v15-title,.v15-masthead-stats dt,.v15-masthead-stats dd')].filter(el=>el.getBoundingClientRect().bottom>box.bottom).map(el=>el.textContent);});assert.deepEqual(clipped,[],String(width));
   }
  });
  await t.test('version links retain earlier results and the two no-vault scenarios say what is available',async()=>{
   await open('&scenario=successor');assert.equal(await page.locator('.v15-board-row').count(),0);await expect(page.getByText('No times on version 2 yet. Earlier times remain on version 1.',{exact:true})).toBeVisible();await page.getByRole('link',{name:'Earlier version · 1',exact:true}).click();await expect(page.locator('.climb-page')).toHaveAttribute('data-version','1');assert.ok(await page.locator('.v15-board-row').count()>0);await page.getByRole('link',{name:'Current version · 2',exact:true}).click();await expect(page.locator('.climb-page')).toHaveAttribute('data-version','2');
   await open('&scenario=no-vault-rides');await expect(page.getByText('From rides',{exact:true})).toBeVisible();assert.ok(await page.locator('.v15-board-row').count()>0);assert.equal(await page.locator('#backing').count(),0);
   await open('&scenario=no-vault-empty');await expect(page.getByText('No leaderboard is available for this climb without a vault.',{exact:true})).toBeVisible();assert.equal(await page.locator('.v15-board-row,#backing').count(),0);assert.doesNotMatch(await page.locator('.climb-page').innerText(),/Ride it to set the first time/);
  });
  await t.test('the supplied stage 1 states and deposit preview retain exact amounts without a transaction',async()=>{
   for(const bonding of ['prebond','bonded','stale','rehearsal']){
    await open(`&bonding=${bonding}`);const section=page.locator('#backing');assert.doesNotMatch(await section.innerText(),/DUNG|pledge/i);
    if(bonding==='rehearsal'){await expect(section.getByText('Deposits are closed during the test',{exact:true})).toBeVisible();assert.equal(await section.getByRole('button',{name:'Deposit',exact:true}).count(),0);continue;}
    if(bonding==='stale')await expect(section.getByText("At last epoch's rate",{exact:true})).toBeVisible();
    await section.getByRole('button',{name:'Deposit',exact:true}).click();await expect(page.getByRole('dialog')).toBeVisible();await expect(page.getByRole('dialog').getByText('0.0053 SOL',{exact:true})).toBeVisible();await page.getByRole('button',{name:'Continue',exact:true}).click();await expect(page.getByRole('button',{name:'Hold to confirm',exact:true})).toBeDisabled();await page.keyboard.press('Escape');await expect(page.getByRole('dialog')).not.toBeVisible();
   }
  });
  assert.deepEqual(errors,[]);
 }finally{await context.close();await browser.close();await server.close();}
});
