import {test} from 'node:test';
import assert from 'node:assert/strict';
import * as guards from './v15-guards';
import {fileURLToPath} from 'node:url';
import {readFileSync,readdirSync} from 'node:fs';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import React from 'react';
import {PowerCell} from '../v15/Rows';
Object.assign(globalThis,{React});
const root=fileURLToPath(new URL('../',import.meta.url));
const read=(name:string)=>readFileSync(`${root}${name}`,'utf8');
const files=(dir:string):string[]=>readdirSync(`${root}${dir}`,{withFileTypes:true}).flatMap(e=>e.isDirectory()?files(`${dir}${e.name}/`):[`${dir}${e.name}`]);

test('the actual kit, candidate owners and exact registration sources satisfy all follow-up guards',()=>{
 for(const file of files('v15/')){
  if(file.endsWith('.css'))assert.deepEqual(guards.kitCssProblems(read(file),file.slice(4)),[],file);
  if(/\.tsx?$/.test(file))assert.deepEqual(guards.componentColourProblems(read(file)),[],file);
 }
 const manifest=JSON.parse(read('tests/v15-preserved-sha256.json'));
 for(const file of files('').filter(f=>f.endsWith('.css')&&!f.startsWith('v15/')&&!f.startsWith('tests/')&&!f.startsWith('baseline/')&&!manifest.sha256[f]))assert.deepEqual(guards.candidateCssProblems(read(file),file),[],file);
 for(const file of manifest.registration)assert.deepEqual(guards.registrationProblems(file,read(file)),[],file);
 for(const file of files('').filter(f=>f.endsWith('.tsx')&&!f.startsWith('v15/')&&!f.startsWith('tests/')&&!f.startsWith('baseline/')&&!manifest.sha256[f]&&!manifest.registration.includes(f)))assert.deepEqual(guards.candidateTsxProblems(read(file),file),[],file);
});

test('estimated power carries its supplied range and standard-weight basis without the bolt',()=>{
 const html=renderToStaticMarkup(createElement(PowerCell,{power:{kind:'estimated',watts:245,wkg:null,range:[200,290]}}));
 assert.match(html,/200–290 W/);assert.match(html,/standard rider weight/);assert.doesNotMatch(html,/v15-bolt/);
 assert.match(html,/role="img"[^>]*aria-label="Estimated/,'the interval has a nameable role, not a generic span');
 assert.match(read('v15/KitSpecimen.tsx'),/data-specimen="PowerCell range"/);
});

test('M2 binds room selectors to their owning file and protects registration surfaces',()=>{
 assert.deepEqual(guards.candidateCssProblems('.climb-page .climb-grid{display:grid}','climb/climb-v17.css'),[]);
 assert.ok(guards.candidateCssProblems('.effort-page .effort-grid{display:none}','climb/climb-v17.css').length);
 assert.ok(guards.candidateCssProblems('.c16-page .c16-row{display:none}','climb/climb-v17.css').length);
 assert.ok(guards.candidateCssProblems('.effort-page .effort-grid{display:none}','effort/extra.css').length);
 assert.ok(guards.candidateTsxProblems('<div className="v15-kit effort-page"/>','climb/ClimbV17.tsx').length);
 assert.ok(guards.registrationProblems('index.html','<style>.c16-page{display:none}</style>').length);
 assert.ok(guards.registrationProblems('main.tsx','const x=<div style={{display:"none"}} className="c16-page"/>').length);
 assert.ok(guards.registrationProblems('entry.ts','document.querySelector(".c16-page")?.remove()').length);
});

test('M4 checks every kit CSS file, scopes specimen rules and forbids imports',()=>{
 assert.deepEqual(guards.kitCssProblems(':where(.v15-kit) .v15-card{color:var(--v15-ink)}','extra.css'),[]);
 assert.ok(guards.kitCssProblems('@import "escape.css";','kit.css').length);
 assert.ok(guards.kitCssProblems('.v15-card{color:red}','extra.css').length);
 assert.ok(guards.kitCssProblems('.specimen-page .v15-card{display:none}','KitSpecimen.css').length);
});

test('L3 checks literal colours in JSX attributes, inline styles and style objects',()=>{
 for(const source of ['const View=()=> <div style={{color:"red"}}/>','const View=()=> <svg fill="#123456"/>','const color={background:"rgb(1 2 3)"};','const View=()=> <div style={{color:`blue`}}/>'])assert.ok(guards.componentColourProblems(source).length,source);
 assert.deepEqual(guards.componentColourProblems('const View=()=> <path fill={`url(#${id})`} style={{color:"var(--v15-ink)"}}/>'),[]);
});

test('L8 masthead figures remain inside the copy padding at all six widths',{timeout:90000},async()=>{
 const {createServer}=await import('vite'),{chromium}=await import('@playwright/test');
 const server=await createServer({configFile:fileURLToPath(new URL('../vite.config.ts',import.meta.url)),server:{port:0,host:'127.0.0.1',strictPort:false}});
 await server.listen();const address=server.httpServer!.address();assert.ok(address&&typeof address!=='string');
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage();await page.goto(`http://127.0.0.1:${address.port}/?kit-preview=1`);await page.locator('.v15-masthead').first().waitFor();await page.evaluate(()=>document.fonts.ready);
  for(const width of [1440,1366,1280,1100,950,390]){
   await page.setViewportSize({width,height:900});
   const failures=await page.evaluate(()=>[...document.querySelectorAll('.v15-masthead-copy')].flatMap(copy=>{
    const box=copy.getBoundingClientRect(),style=getComputedStyle(copy),edge=box.right-parseFloat(style.paddingRight);
    return [...copy.querySelectorAll('.v15-masthead-stats dt,.v15-masthead-stats dd')].flatMap(el=>{
     const range=document.createRange();range.selectNodeContents(el);const r=range.getBoundingClientRect();return r.right>edge+.5?[`${el.textContent}: ${r.right-edge}px into padding`]:[];
    });
   }));
   assert.deepEqual(failures,[],String(width));
  }
 }finally{await browser.close();await server.close();}
});
