import {chromium,expect} from '@playwright/test';
import {mkdir,writeFile,readFile} from 'node:fs/promises';
const dir=new URL('./evidence/correction/',import.meta.url).pathname;
await mkdir(dir,{recursive:true});
const browser=await chromium.launch({headless:true});
const records:unknown[]=[];
const sources=[
 {id:'profile',name:'Profile V2 · corrected',url:'http://localhost:4330/?profile-preview=1&scenario=owner',selector:'.p2-page'},
 {id:'draft',name:'Original Profile draft · preserved',url:'http://localhost:4330/?profile-preview=1&scenario=owner&draft=original',selector:'.pd2-page'},
 {id:'feed-v9',name:'Feed V9 · shared checkpoint',url:'http://localhost:4330/?feed-preview=1&variant=feed-v9&scenario=mixed',selector:'.f9-page'},
 {id:'ride-v13',name:'Ride V13 · shared checkpoint',url:'http://localhost:4330/?preview=1&variant=candidate-v13&scenario=recorded',selector:'.candidate-v13'},
 {id:'climb-v7',name:'Climb V7 · supplied local example',url:'http://localhost:4318/?climb-preview=1&variant=climb-v7&scenario=wises&viewer=rider',selector:'.c7-page'},
 {id:'map-v4',name:'Map V4 · local canonical geography',url:'http://localhost:4323/?map-preview=1&variant=map-v4&scenario=wises&viewer=rider',selector:'.m4-page'},
];
try{
 for(const width of [1440,390]){
  const height=width===1440?1000:844;
  for(const source of sources){
   const page=await browser.newPage({viewport:{width,height}});const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
   await page.goto(source.url);await expect(page.locator(source.selector)).toBeVisible();await page.evaluate(()=>document.fonts.ready);
   if(source.id==='climb-v7')await expect(page.locator('[data-map-ready=true]')).toBeVisible({timeout:30000});
   if(source.id==='map-v4')await expect(page.locator('[data-map-status=ready]')).toBeVisible({timeout:30000});
   if(source.id==='ride-v13')await expect(page.locator('.v12-map[data-map-ready=true]')).toBeVisible({timeout:30000});
   if(source.id==='feed-v9'){await expect(page.locator('.f3-map-canvas').first()).toHaveAttribute('data-map-ready','true',{timeout:30000});if(width===1440)await expect(page.locator('.f3-world-map-canvas')).toHaveAttribute('data-map-ready','true',{timeout:30000});}
   await page.screenshot({path:`${dir}${source.id}-${width}.png`});
   const layout=await page.evaluate(()=>({width:innerWidth,height:innerHeight,overflow:document.documentElement.scrollWidth>innerWidth}));
   records.push({id:source.id,url:page.url(),...layout,errors});console.log(source.id,width,layout.overflow?'OVERFLOW':'captured');await page.close();
  }
  for(const donor of sources.slice(1)){
   const page=await browser.newPage({viewport:{width:width*2,height:height+44}});
   const pics=await Promise.all([readFile(`${dir}profile-${width}.png`),readFile(`${dir}${donor.id}-${width}.png`)]);
   await page.setContent(`<style>*{box-sizing:border-box}body{margin:0;font:14px system-ui;background:#e5e8df;color:#30372a}main{display:flex}figure{margin:0;width:50%}figcaption{height:44px;padding:12px 18px}img{display:block;width:100%}</style><main><figure><figcaption>Profile V2 · corrected · ${width} × ${height}</figcaption><img src="data:image/png;base64,${pics[0].toString('base64')}"></figure><figure><figcaption>${donor.name} · ${width} × ${height}</figcaption><img src="data:image/png;base64,${pics[1].toString('base64')}"></figure></main>`);
   await page.locator('img').last().evaluate((el:HTMLImageElement)=>el.decode());
   await page.screenshot({path:`${dir}pair-${donor.id}-${width}.png`});await page.close();
  }
 }
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 await page.goto('http://localhost:4330/?surface=profile&variant=profile-v2&scenario=owner');
 const frame=()=>page.frameLocator('iframe[title="Interactive Profile V2"]');
 await expect(frame().locator('.p2-page')).toBeVisible();
 await page.getByRole('button',{name:'Original draft',exact:true}).click();await expect(frame().locator('.pd2-page')).toBeVisible();
 await expect(frame().getByRole('heading',{name:'Dung Beetle Phoenix'})).toBeVisible();
 await page.getByRole('button',{name:'Original draft',exact:true}).click();await expect(frame().locator('.p2-page')).toBeVisible();
 records.push({id:'original-draft-toggle',pass:true});
 await page.close();
 await writeFile(dir+'comparison.json',JSON.stringify({evidenceClass:'Local browser renders. Profile and donors contain supplied examples; no production or rider proof.',capturedAt:new Date().toISOString(),records},null,2)+'\n');
 const options=sources.slice(1).map(s=>`<option value="${s.id}">${s.name}</option>`).join('');
 await writeFile(dir+'comparison.html',`<!doctype html><meta charset="utf-8"><title>Profile workshop comparison</title><style>*{box-sizing:border-box}body{margin:0;background:#f3f4ef;color:#30372a;font:14px system-ui}header{padding:18px 24px;display:flex;gap:18px;align-items:center;position:sticky;top:0;background:#f3f4ef}h1{font-size:18px;margin:0}select{padding:8px}p{padding:0 24px;font-size:12px;color:#69765e}img{width:100%;height:auto;display:block}</style><header><h1>Profile V2 · workshop comparison</h1><select id="donor" aria-label="Comparison donor">${options}</select><select id="size" aria-label="Source viewport"><option value="1440">1440 × 1000</option><option value="390">390 × 844</option></select></header><p>Actual local browser renders at the selected source viewport. The pair scales together to fit. Donor data is independent from Profile. No production or physical-rider proof.</p><img id="pair" alt="Corrected Profile beside selected workshop donor"><script>function show(){pair.src='pair-'+donor.value+'-'+size.value+'.png'}donor.onchange=size.onchange=show;show()</script>`);
}finally{await browser.close();}
