const {chromium,expect}=require('@playwright/test');
require('node:fs').mkdirSync('/tmp/boulder-v12-proof',{recursive:true});
(async()=>{const browser=await chromium.launch({headless:true,ignoreDefaultArgs:['--hide-scrollbars']});try{
 const page=await browser.newPage({viewport:{width:1500,height:1180},deviceScaleFactor:1}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://localhost:4318/?variant=candidate-v12&scenario=history');await page.getByRole('button',{name:'Desktop preview',exact:true}).click();const f=page.frameLocator('iframe');
 const rows=f.locator('.v12-result-row'),list=f.locator('.v12-result-scroll');
 await expect(rows).toHaveCount(3);await expect(f.getByText('Loading map',{exact:true})).toHaveCount(0,{timeout:15000});
 const short=await f.locator('.v12-workspace').evaluate(el=>{const list=el.querySelector('.v12-result-scroll');return{list:list.clientHeight,content:list.scrollHeight,footer:el.querySelector('.v12-analyze-link').getBoundingClientRect().bottom,geography:el.querySelector('.v12-geography').getBoundingClientRect().bottom};});
 expect(short.list).toBe(short.content);expect(short.footer).toBeLessThan(short.geography);
 await expect(f.getByRole('button',{name:'CAL',exact:true})).toBeVisible();await f.getByRole('button',{name:'CAL',exact:true}).click();await expect(f.getByRole('heading',{name:'Ride CAL',exact:true})).toBeVisible();await expect(f.getByText('Climb tribute',{exact:true})).toBeVisible();await f.getByRole('button',{name:'Overview',exact:true}).click();
 await page.locator('iframe').screenshot({path:'/tmp/boulder-v12-proof/three-1440.png'});
 // Selection from the elevation must retain the Overview rail too.
 await page.getByLabel('Ride scenario',{exact:true}).selectOption('layout-10');await list.hover();await page.mouse.wheel(0,400);await expect.poll(()=>list.evaluate(el=>el.scrollTop)).toBeGreaterThan(100);
 const beforeBrush=await list.evaluate(el=>el.scrollTop),profile=f.getByRole('slider',{name:'Inspect elevation profile',exact:true});await profile.scrollIntoViewIfNeeded();const pb=await profile.boundingBox();await page.mouse.move(pb.x+pb.width*.2,pb.y+40);await page.mouse.down();await page.mouse.move(pb.x+pb.width*.5,pb.y+40,{steps:10});await page.mouse.up();await expect(f.locator('.v12-selection-summary')).toBeVisible();await f.getByRole('button',{name:'Overview',exact:true}).click();await expect.poll(()=>list.evaluate(el=>el.scrollTop)).toBeCloseTo(beforeBrush,0);
 await page.getByLabel('Ride scenario',{exact:true}).selectOption('recorded');
 const results=[];
 for(const count of [10,30]){
  await page.getByLabel('Ride scenario',{exact:true}).selectOption(`layout-${count}`);await expect(rows).toHaveCount(count);await expect(f.getByText('Loading map',{exact:true})).toHaveCount(0,{timeout:15000});
  const metric=await f.locator('.v12-workspace').evaluate(el=>{const list=el.querySelector('.v12-result-scroll'),g=el.querySelector('.v12-geography').getBoundingClientRect(),footer=el.querySelector('.v12-analyze-link').getBoundingClientRect();return{gutter:list.offsetWidth-list.clientWidth,content:list.scrollHeight,viewport:list.clientHeight,geography:g.bottom,footer:footer.bottom,header:el.querySelector('.v12-results>header').getBoundingClientRect().top};});
  expect(metric.content).toBeGreaterThan(metric.viewport);expect(metric.gutter).toBeGreaterThan(0);expect(Math.abs(metric.footer-metric.geography)).toBeLessThan(1);
  await page.locator('iframe').screenshot({path:`/tmp/boulder-v12-proof/${count}-1440.png`});
  await list.hover();await page.mouse.wheel(0,680);await expect.poll(()=>list.evaluate(el=>el.scrollTop)).toBeGreaterThan(0);
  const fixed=await f.locator('.v12-results-rail').evaluate(el=>({footer:el.querySelector('.v12-analyze-link').getBoundingClientRect().bottom,header:el.querySelector('.v12-results>header').getBoundingClientRect().top}));expect(fixed.footer).toBe(metric.footer);expect(fixed.header).toBe(metric.header);
  const last=rows.last();await last.focus();await expect.poll(()=>last.evaluate(el=>{const a=el.getBoundingClientRect(),b=el.closest('.v12-result-scroll').getBoundingClientRect();return a.bottom<=b.bottom+1&&a.top>=b.top-1;})).toBe(true);
  const position=await list.evaluate(el=>el.scrollTop),climbId=await last.getAttribute('data-climb-id');await last.press('Enter');await expect(f.locator('.v12-selection-identity')).toContainText(`Study climb ${count}`);
  await page.goBack();await expect(list).toBeVisible();await expect(f.locator(`[data-climb-id="${climbId}"]`)).toBeFocused();await expect.poll(()=>list.evaluate(el=>el.scrollTop)).toBeCloseTo(position,0);
  await last.click();await f.getByRole('button',{name:'Overview',exact:true}).click();await expect(last).toBeFocused();await expect.poll(()=>list.evaluate(el=>el.scrollTop)).toBeCloseTo(position,0);
  await page.locator('iframe').screenshot({path:`/tmp/boulder-v12-proof/${count}-bottom-1440.png`});
  await page.getByLabel('Loading state',{exact:true}).selectOption('loading');await expect(rows).toHaveCount(count);await page.getByLabel('Loading state',{exact:true}).selectOption('ready');
  results.push({count,...metric,restoredScroll:position});
 }
 await page.reload();await page.getByRole('button',{name:'Desktop preview',exact:true}).click();await expect(rows).toHaveCount(30);
 await page.getByRole('button',{name:'Phone preview',exact:true}).click();
 const phone=await list.evaluate(el=>({height:el.clientHeight,content:el.scrollHeight,overflow:getComputedStyle(el).overflowY,viewport:innerWidth,pageWidth:document.documentElement.clientWidth,pageScrollWidth:document.documentElement.scrollWidth}));expect(phone.height).toBe(phone.content);expect(phone.overflow).toBe('visible');expect(phone.viewport).toBe(390);expect(phone.pageScrollWidth).toBe(phone.pageWidth);
 await rows.nth(6).scrollIntoViewIfNeeded();await page.locator('iframe').screenshot({path:'/tmp/boulder-v12-proof/long-name-390.png'});
 await rows.last().focus();await rows.last().press('Enter');await f.getByRole('button',{name:'Overview',exact:true}).click();await expect(rows.last()).toBeFocused();await expect.poll(()=>rows.last().evaluate(el=>{const r=el.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight;})).toBe(true);
 await page.locator('iframe').screenshot({path:'/tmp/boulder-v12-proof/thirty-bottom-390.png'});
 await page.getByLabel('Ride scenario',{exact:true}).selectOption('recorded');await expect(rows).toHaveCount(3);await expect(list).not.toHaveAttribute('tabindex','0');await page.getByRole('button',{name:'Desktop preview',exact:true}).click();await expect.poll(()=>list.evaluate(el=>el.scrollTop)).toBe(0);
 // Frozen V11 still presents its original navigation.
 await page.getByRole('button',{name:'Candidate v11',exact:true}).click();await expect(f.getByRole('button',{name:'CAL & tribute',exact:true})).toBeVisible();
 expect(errors).toEqual([]);console.log(JSON.stringify({short,results,phone,errors,checks:'3/10/30, fixed count/footer, native wheel, keyboard reachability, Back and Overview restoration, refresh, phone flow and long names, source reset, CAL labels, V11 preserved'}));
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});
