import { useLayoutEffect, useRef, useState } from 'react';
import type { Scenario } from './scenario';
import { analysisSamples, type Axis, type Channel, type SampleRange } from './v3Model';
import {bestPower,powerEffortRange} from './v12Model';

export type RideV14Mode='overview'|'analysis'|'power'|'heartRate'|'economics'|'vault';
export type RideV14OverviewReturn={sourceId:string;listScroll:number;pageScroll:number;climbId:string|null;desktop:boolean};
export type RideV14Location={mode:RideV14Mode;climbId:string|null;range:SampleRange|null;effortDuration:number|null;axis:Axis;mapHeight:number;expanded:boolean;scroll:number;hidden:Channel[];overview:RideV14OverviewReturn|null};
const initial=():RideV14Location=>({mode:'overview',climbId:null,range:null,effortDuration:null,axis:'distance',mapHeight:window.matchMedia('(max-width:600px)').matches?210:258,expanded:false,scroll:0,hidden:[],overview:null});
const host=()=>window.parent;
function read(scenario:Scenario):RideV14Location {
 const url=new URL(host().location.href), p=url.searchParams;
 if(p.get('variant')!=='candidate-v14') return initial();
 const saved=host().history.state?.r14 as Partial<RideV14Location>|undefined;
 const state={...initial(),...saved};
 state.mode=(['overview','analysis','power','heartRate','economics','vault'].includes(p.get('view')??'')?p.get('view'):'overview') as RideV14Mode;
 state.axis=p.get('axis')==='time'?'time':'distance';
 state.climbId=scenario.climbs.some(c=>c.id===p.get('climb'))?p.get('climb'):null;
 const start=Number(p.get('from')),end=Number(p.get('to'));
 state.range=p.has('from')&&p.has('to')&&Number.isInteger(start)&&Number.isInteger(end)&&start>=0&&end>start&&end<scenario.ride.samples.length?{startIndex:start,endIndex:end}:null;
 state.effortDuration=null;
 const duration=Number(p.get('effort'));
 if(state.mode==='analysis'&&p.has('effort')&&duration>0&&duration<=3600){const points=analysisSamples(scenario.ride.samples),best=bestPower(points,duration),bounds=best&&powerEffortRange(points,best);if(bounds){state.range={startIndex:bounds.startIndex,endIndex:bounds.endIndex};state.climbId=null;state.effortDuration=duration;}}
 if(state.mode==='vault'&&!state.climbId) state.mode='overview';
 state.mapHeight=Number.isFinite(state.mapHeight)?Math.max(180,Math.min(620,state.mapHeight)):258;
 state.scroll=Number.isFinite(state.scroll)?Math.max(0,state.scroll):0;
 state.hidden=Array.isArray(state.hidden)?state.hidden.filter(c=>['speed','power','cadence','heartRate'].includes(c)):[];
 const overview=state.overview;
 state.overview=overview&&overview.sourceId===scenario.id&&Number.isFinite(overview.listScroll)&&Number.isFinite(overview.pageScroll)&&typeof overview.desktop==='boolean'?{...overview,listScroll:Math.max(0,overview.listScroll),pageScroll:Math.max(0,overview.pageScroll),climbId:scenario.climbs.some(c=>c.id===overview.climbId)?overview.climbId:null}:null;
 return state;
}
export function r14Href(next:Pick<RideV14Location,'mode'|'climbId'|'range'|'axis'|'effortDuration'>) {
 const url=new URL(host().location.href);url.searchParams.set('variant','candidate-v14');
 for(const key of ['view','climb','from','to','axis','effort']) url.searchParams.delete(key);
 if(next.mode!=='overview') url.searchParams.set('view',next.mode);
 if(next.climbId) url.searchParams.set('climb',next.climbId);
 if(next.range) {url.searchParams.set('from',String(next.range.startIndex));url.searchParams.set('to',String(next.range.endIndex));}
 if(next.effortDuration)url.searchParams.set('effort',String(next.effortDuration));
 if(next.axis==='time') url.searchParams.set('axis','time');
 return url.href;
}
export function useRideV14Navigation(scenario:Scenario) {
 const [stored,setStored]=useState(()=>({scenario,value:read(scenario)}));
 const value=stored.scenario===scenario?stored.value:initial();
 const latest=useRef(value);latest.current=value;
 const changing=useRef(false);
 const write=(next:RideV14Location,push:boolean)=>{
  const current={...latest.current,scroll:window.scrollY};
  if(push) host().history.replaceState({...host().history.state,r14:current},'',host().location.href);
  host().history[push?'pushState':'replaceState']({...host().history.state,r14:next,r14Return:push?true:host().history.state?.r14Return},'',r14Href(next));
  latest.current=next;setStored({scenario,value:next});
 };
 const visit=(patch:Partial<RideV14Location>,push=true)=>{
  const next={...latest.current,...patch};
  if(patch.effortDuration===undefined&&(patch.mode!==undefined||patch.climbId!==undefined||patch.range!==undefined))next.effortDuration=null;
  if(patch.scroll===undefined) next.scroll=window.scrollY;
  write(next,push);
  if(patch.scroll!==undefined) {changing.current=true;requestAnimationFrame(()=>{window.scrollTo({top:next.scroll,behavior:'instant'});changing.current=false;});}
 };
 useLayoutEffect(()=>{
  if(stored.scenario!==scenario) write(initial(),false);
  const back=()=>{if(new URL(host().location.href).searchParams.get('variant')!=='candidate-v14')return;const next=read(scenario);latest.current=next;setStored({scenario,value:next});changing.current=true;requestAnimationFrame(()=>{window.scrollTo({top:next.scroll,behavior:'instant'});changing.current=false;});};
  const save=()=>{if(changing.current)return;const next={...latest.current,scroll:window.scrollY};host().history.replaceState({...host().history.state,r14:next},'',host().location.href);};
  host().addEventListener('popstate',back);window.addEventListener('scroll',save,{passive:true});
  return()=>{host().removeEventListener('popstate',back);window.removeEventListener('scroll',save);};
 },[scenario]);
 return {location:value,visit,href:(patch:Partial<RideV14Location>)=>r14Href({...value,...patch,effortDuration:patch.effortDuration??null})};
}

export type RideV14Navigation=ReturnType<typeof useRideV14Navigation>;
