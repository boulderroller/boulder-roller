import {mkdir,writeFile} from 'node:fs/promises';
import {dirname} from 'node:path';
import {launch,openPage,domHelpers} from './page-tools.mjs';

const [url,outFile,width='1440',height='900']=process.argv.slice(2);
if(!url||!outFile)throw new Error('Usage: node workshop/tools/census.mjs <url> <outFile> [width=1440] [height=900]');
const size={width:Number(width),height:Number(height)};
if(!Number.isInteger(size.width)||!Number.isInteger(size.height)||size.width<=0||size.height<=0)throw new Error('Viewport dimensions must be positive integers');
const browser=await launch();
try{
 const {page,context,consoleErrors}=await openPage(browser,url,size);
 const elements=await page.evaluate(helperSource=>{
  const {visible,domPath}=(0,eval)(`(${helperSource})`)();
  const properties=['color','backgroundColor','backgroundImage','borderTop','borderRight','borderBottom','borderLeft','borderRadius','fontFamily','fontSize','fontWeight','lineHeight','paddingTop','paddingRight','paddingBottom','paddingLeft','marginTop','marginRight','marginBottom','marginLeft','rowGap','columnGap','display','position'];
  return [...document.querySelectorAll('body, body *')].filter(visible).map(element=>{
   const rect=element.getBoundingClientRect(),style=getComputedStyle(element);
   return {path:domPath(element),box:Object.fromEntries(['x','y','width','height'].map(key=>[key,Math.round(rect[key])])),styles:Object.fromEntries(properties.map(key=>[key,style[key]]))};
  });
 },domHelpers.toString());
 await mkdir(dirname(outFile),{recursive:true});
 await writeFile(outFile,JSON.stringify({url,viewport:size,deviceScaleFactor:2,consoleErrors,elements},null,2)+'\n');
 console.log(`${outFile}: ${elements.length} visible elements; ${consoleErrors.length} console errors`);
 await context.close();
}finally{await browser.close();}
