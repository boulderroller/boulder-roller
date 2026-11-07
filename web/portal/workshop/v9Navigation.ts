import { useLayoutEffect, useRef, useState } from 'react';
import type { Scenario } from './scenario';
import type { Axis, Channel, SampleRange } from './v3Model';

export type V9Mode='overview'|'analysis'|'power'|'heartRate'|'economics'|'vault';
export type V9Location={mode:V9Mode;climbId:string|null;range:SampleRange|null;axis:Axis;mapHeight:number;expanded:boolean;scroll:number;hidden:Channel[]};
const initial=():V9Location=>({mode:'overview',climbId:null,range:null,axis:'distance',mapHeight:window.matchMedia('(max-width:600px)').matches?210:258,expanded:false,scroll:0,hidden:[]});
const host=()=>window.parent;
function read(scenario:Scenario):V9Location {
 const url=new URL(host().location.href), p=url.searchParams;
 if(p.get('variant')!=='candidate-v9') return initial();
 const saved=host().history.state?.v9 as Partial<V9Location>|undefined;
 const state={...initial(),...saved};
 state.mode=(['overview','analysis','power','heartRate','economics','vault'].includes(p.get('view')??'')?p.get('view'):'overview') as V9Mode;
 state.axis=p.get('axis')==='time'?'time':'distance';
 state.climbId=scenario.climbs.some(c=>c.id===p.get('climb'))?p.get('climb'):null;
 const start=Number(p.get('from')),end=Number(p.get('to'));
 state.range=p.has('from')&&p.has('to')&&Number.isInteger(start)&&Number.isInteger(end)&&start>=0&&end>start&&end<scenario.ride.samples.length?{startIndex:start,endIndex:end}:null;
 if(state.mode==='vault'&&!state.climbId) state.mode='overview';
 state.mapHeight=Number.isFinite(state.mapHeight)?Math.max(180,Math.min(620,state.mapHeight)):258;
 state.scroll=Number.isFinite(state.scroll)?Math.max(0,state.scroll):0;
 state.hidden=Array.isArray(state.hidden)?state.hidden.filter(c=>['speed','power','cadence','heartRate'].includes(c)):[];
 return state;
}
export function v9Href(next:Pick<V9Location,'mode'|'climbId'|'range'|'axis'>) {
 const url=new URL(host().location.href);url.searchParams.set('variant','candidate-v9');
 for(const key of ['view','climb','from','to','axis']) url.searchParams.delete(key);
 if(next.mode!=='overview') url.searchParams.set('view',next.mode);
 if(next.climbId) url.searchParams.set('climb',next.climbId);
 if(next.range) {url.searchParams.set('from',String(next.range.startIndex));url.searchParams.set('to',String(next.range.endIndex));}
 if(next.axis==='time') url.searchParams.set('axis','time');
 return url.href;
}
export function useV9Navigation(scenario:Scenario) {
 const [stored,setStored]=useState(()=>({scenario,value:read(scenario)}));
 const value=stored.scenario===scenario?stored.value:initial();
 const latest=useRef(value);latest.current=value;
 const changing=useRef(false);
 const write=(next:V9Location,push:boolean)=>{
  const current={...latest.current,scroll:window.scrollY};
  if(push) host().history.replaceState({...host().history.state,v9:current},'',host().location.href);
  host().history[push?'pushState':'replaceState']({...host().history.state,v9:next,v9Return:push?true:host().history.state?.v9Return},'',v9Href(next));
  latest.current=next;setStored({scenario,value:next});
 };
 const visit=(patch:Partial<V9Location>,push=true)=>{
  const next={...latest.current,...patch};
  if(patch.scroll===undefined) next.scroll=window.scrollY;
  write(next,push);
  if(patch.scroll!==undefined) {changing.current=true;requestAnimationFrame(()=>{window.scrollTo({top:next.scroll,behavior:'instant'});changing.current=false;});}
 };
 useLayoutEffect(()=>{
  if(stored.scenario!==scenario) write(initial(),false);
  const back=()=>{if(new URL(host().location.href).searchParams.get('variant')!=='candidate-v9')return;const next=read(scenario);latest.current=next;setStored({scenario,value:next});changing.current=true;requestAnimationFrame(()=>{window.scrollTo({top:next.scroll,behavior:'instant'});changing.current=false;});};
  const save=()=>{if(changing.current)return;const next={...latest.current,scroll:window.scrollY};host().history.replaceState({...host().history.state,v9:next},'',host().location.href);};
  host().addEventListener('popstate',back);window.addEventListener('scroll',save,{passive:true});
  return()=>{host().removeEventListener('popstate',back);window.removeEventListener('scroll',save);};
 },[scenario]);
 return {location:value,visit,href:(patch:Partial<V9Location>)=>v9Href({...value,...patch})};
}
