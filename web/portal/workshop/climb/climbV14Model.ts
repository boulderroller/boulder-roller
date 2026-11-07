import type {PaddingOptions} from 'maplibre-gl';
import type {ClimbInspection} from './climbV5Model';
import type {ClimbViewer} from './climbModel';
import {vaultAttempts,type ClimbV9Study} from './climbV9Model';
import {v13Effort,v13Ride} from './climbV13Model';
export const v14Effort=(href:string)=>v13Effort(href).replace('climbOriginVariant=climb-v13','climbOriginVariant=climb-v14');
export const v14Ride=(href:string)=>v13Ride(href).replace('climbOriginVariant=climb-v13','climbOriginVariant=climb-v14');
export type BoardView='overall'|'qualified';
export type V14BoardRow=NonNullable<ClimbInspection['board']>['rows'][number]&{date?:string};
type Ranked={rank:number;duration:number;current?:boolean};
/** V13's board derivation, unchanged: Overall rows carry their ride or authored date; Power verified rows come from the vault attempts. */
export function boardRows(data:ClimbInspection,study:ClimbV9Study,state:string,view:BoardView):V14BoardRow[]{
 const recordings=new Map(data.recordings.map(r=>[r.entry.ride.id,r.entry]));
 const overall=data.board?.rows.map(r=>({...r,date:(r.rideId?recordings.get(r.rideId)?.ride.ride.startedAt:undefined)??study.candidate7?.rowDates[r.id]}))??[];
 if(state==='empty')return [];
 if(view==='overall')return overall;
 return study.candidate9?vaultAttempts(study.candidate9.attempts).map(a=>{const row=overall.find(r=>r.id===a.rowId)!,record=data.recordings.find(r=>r.entry.id===a.entryId);return {...row,id:a.id,rank:a.rank,duration:a.duration,date:a.date,href:record?.href,rideId:record?.entry.ride.id};}):[];
}
/** The fastest row, only when the board holds first place. A partial board (one row at 3rd) has no known leader. */
export const boardLeader=<T extends Ranked>(rows:readonly T[]):T|undefined=>rows[0]?.rank===1?rows[0]:undefined;
/** The rider count is a fact only when the places run unbroken from 1st (ties share a place). */
export const boardComplete=(rows:readonly Ranked[])=>rows.length>0&&rows[0].rank===1&&rows.every((r,i)=>i===0||r.rank===rows[i-1].rank||r.rank===i+1);
/** Gap to the fastest row in tenths, as V13 prints it; null when the board does not hold the fastest. */
export const boardGap=(duration:number,leader:Ranked|undefined)=>leader?.rank===1?Math.round((duration-leader.duration)*10)/10:null;
/** The podium holds only places the data shows, and only when 1st is among them. */
export const podiumRows=<T extends Ranked>(rows:readonly T[]):T[]=>boardLeader(rows)?rows.filter(r=>r.rank<=3).slice(0,3):[];
/** A power column earns its width only when most rows carry a value; otherwise power rides in the date cell. */
export const powerColumn=(values:readonly (number|null)[])=>values.filter(v=>v!==null).length*2>values.length;
export const plural=(n:number,one:string,many=`${one}s`)=>`${n.toLocaleString('en-US')} ${n===1?one:many}`;
export type StripCell='best'|'overall'|'legend';
/** The rider's strip: your best, your place, and the hill's Local Legend. It summarises; it never restates the podium or the board foot,
 *  so a viewer without a place on the board has no strip and meets Local Legend in the board foot instead. */
export function stripCells({viewer,personal,overall,legend,economy}:{viewer:ClimbViewer;personal?:{rank?:number}|null;overall:readonly Ranked[];legend?:unknown;economy?:unknown}):StripCell[]{
 const cells:StripCell[]=[],current=overall.find(r=>r.current);
 if(viewer!=='rider'||!(personal||current))return cells;
 if(personal)cells.push('best');
 if(personal?.rank||current)cells.push('overall');
 if(economy&&legend)cells.push('legend');
 return cells;
}
/** Round ticks inside [min,max] on a 1·2·2.5·5 step, choosing the step whose count lands nearest `count` (the busier one on a tie).
 *  The extremes stay in the facts row, never on an axis, so no gridline claims an elevation the climb does not reach. */
export function roundTicks(min:number,max:number,count=3):number[]{
 const span=max-min;if(!(span>0))return [];
 const within=(step:number)=>{const ticks:number[]=[];for(let t=Math.ceil(min/step-1e-9)*step;t<=max+1e-9;t+=step)ticks.push(Math.round(t*1e6)/1e6||0);return ticks;};
 const power=10**Math.floor(Math.log10(span));
 let best:number[]=[];
 for(const step of [5,2.5,2,1,.5,.25,.2,.1].map(m=>m*power)){const ticks=within(step);if(!best.length||Math.abs(ticks.length-count)<Math.abs(best.length-count)||(Math.abs(ticks.length-count)===Math.abs(best.length-count)&&ticks.length>best.length))best=ticks;}
 return best;
}
/** Distance ticks in km from zero, dropping any that would crowd the labelled end (within a fifth of it). */
export function distanceTicks(lengthMeters:number):number[]{
 const km=lengthMeters/1000;return roundTicks(0,km,3).filter(t=>t<km*.8);
}
/** The map is the full-width masthead. On desktop the title sits on the scrim over its left half, so the route fits the clear right half;
 *  on phone the title sits below the map, so the route only keeps clear of the chrome (never more than a fifth of the pane). */
export function heroFitPadding(width:number,height:number,phone:boolean):PaddingOptions{
 const inset=(n:number,size:number)=>Math.min(n,Math.round(size*.2));
 return phone?{left:inset(24,width),right:inset(24,width),top:inset(48,height),bottom:inset(48,height)}:{left:Math.round(width*.5)+24,right:inset(64,width),top:inset(40,height),bottom:inset(56,height)};
}
