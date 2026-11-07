import {chromium} from '@playwright/test';

export const sizes=[{name:'desktop',width:1440,height:900},{name:'phone',width:390,height:844}];
export async function launch(){return chromium.launch({headless:true});}
export async function openPage(browser,url,size){
 const context=await browser.newContext({viewport:{width:size.width,height:size.height},deviceScaleFactor:2,reducedMotion:'reduce'});
 const page=await context.newPage(),consoleErrors=[];
 page.on('pageerror',error=>consoleErrors.push(error.message));
 page.on('console',message=>{if(message.type()==='error')consoleErrors.push(message.text());});
 await page.goto(url,{waitUntil:'networkidle'});
 await page.evaluate(()=>document.fonts.ready);
 // Visit the entire document so an offscreen map's IntersectionObserver gets a turn.
 let y=0;
 while(y<await page.evaluate(()=>document.documentElement.scrollHeight)){
  await page.evaluate(y=>window.scrollTo(0,y),y);await page.waitForTimeout(500);y+=Math.round(size.height*.75);
 }
 await page.evaluate(()=>window.scrollTo(0,0));
 await page.evaluate(()=>document.fonts.ready);
 await page.waitForTimeout(1500);
 return {page,context,consoleErrors};
}
export function fileStem(path){
 const url=new URL(path,'http://workshop.test');
 return [url.pathname,...[...url.searchParams].map(([key,value])=>`${key}-${value}`)].join('-').replace(/[^a-z0-9_-]+/gi,'-').replace(/^-+|-+$/g,'');
}
// Used inside page.evaluate. Offscreen document content counts; hidden/disclosed content does not.
export function domHelpers(){
 const visible=element=>{
  const box=element.getBoundingClientRect();if(!box.width||!box.height)return false;
  for(let node=element;node;node=node.parentElement){
   const s=getComputedStyle(node);
   if(s.display==='none'||s.visibility==='hidden'||s.visibility==='collapse'||Number(s.opacity)===0||s.clipPath==='inset(50%)'||s.clip==='rect(0px, 0px, 0px, 0px)')return false;
   if(/hidden|clip|auto|scroll/.test(s.overflowX+' '+s.overflowY)){
    const r=node.getBoundingClientRect();if(box.right<=r.left||box.left>=r.right||box.bottom<=r.top||box.top>=r.bottom)return false;
   }
  }return true;
 };
 const domPath=element=>{
  const parts=[];for(let node=element;node;node=node.parentElement){
   let index=1;for(let sibling=node.previousElementSibling;sibling;sibling=sibling.previousElementSibling)if(sibling.tagName===node.tagName)index++;
   parts.unshift(`${node.tagName.toLowerCase()}:nth-of-type(${index})`);
  }return parts.join(' > ');
 };
 return {visible,domPath};
}
