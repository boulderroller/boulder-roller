import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';

test('medals keep RankMark names, rank metals, the plain 100+ fallback and unique paint ids',async()=>{
 const {Medal}=await import('../marks/Medal');
 const render=(rank:number,size=28)=>renderToStaticMarkup(createElement(Medal,{rank,size}));
 for(const [rank,colour] of [[1,'#FAEBB5'],[2,'#FBFCFD'],[3,'#F6D8BF'],[4,'#F3F4F0'],[99,'#F3F4F0']] as const){
  const html=render(rank);assert.match(html,new RegExp(`aria-label="Rank ${rank}"`));assert.match(html,/role="img"/);assert.match(html,/font-family="&#x27;Geist V15&#x27;, Geist, system-ui"/);assert.ok(html.includes(colour));
 }
 const plain=render(1000);assert.match(plain,/Rank 1,000/);assert.match(plain,/>1,000</);assert.doesNotMatch(plain,/<circle|<linearGradient/);
 const many=renderToStaticMarkup(createElement('div',null,[1,1,7].map((rank,i)=>createElement(Medal,{rank,size:24,key:i}))));
 const ids=[...many.matchAll(/ id="([^"]+)"/g)].map(m=>m[1]);assert.equal(ids.length,9);assert.equal(new Set(ids).size,9);
 for(const size of [20,22,24,28,32,40]){
  const html=render(12,size),css=size>=40?16:size>=32?13:11;
  assert.match(html,new RegExp(`font-size="${css*24/size}"`));assert.equal((html.match(/<line /g)??[]).length,size>=28?36:0);
 }
});
