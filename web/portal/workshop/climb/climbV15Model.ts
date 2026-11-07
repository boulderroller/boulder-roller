import type {PaddingOptions} from 'maplibre-gl';
import type {ClimbStudy,ClimbViewer} from './climbModel';
import type {DiscoveryV4} from '../feed/feedV4Model';
import {inspectV7} from './climbV7Model';
import {v9Study} from './climbV9Model';
import {v13Effort,v13Ride} from './climbV13Model';
import {climbV3Destination} from './climbV3Navigation';
import {boardRows,boardGap} from './climbV14Model';
export {boardRows,boardLeader,boardComplete,boardGap,podiumRows,powerColumn,plural,stripCells,roundTicks,distanceTicks,type BoardView,type V14BoardRow,type StripCell} from './climbV14Model';
export const v15Effort=(href:string)=>v13Effort(href).replace('climbOriginVariant=climb-v13','climbOriginVariant=climb-v15');
export const v15Ride=(href:string)=>v13Ride(href).replace('climbOriginVariant=climb-v13','climbOriginVariant=climb-v15');

/** The masthead direction: A the green map under a band fade (default), B the hill as the art, C one night plate holding plan and profile. */
export type Hero='a'|'b'|'c';
export const heroFor=(value:string|null|undefined):Hero=>value==='b'||value==='c'?value:'a';

type Point=DiscoveryV4['profile'][number];
/** Elevation at a distance along the climb, linear between supplied points (production's interpolateElevation). */
export function elevationAt(profile:readonly Point[],d:number):number{
 if(d<=profile[0].d)return profile[0].elevation;
 for(let i=1;i<profile.length;i++)if(profile[i].d>=d){const a=profile[i-1],b=profile[i],span=b.d-a.d;return span<=0?b.elevation:a.elevation+(d-a.d)/span*(b.elevation-a.elevation);}
 return profile.at(-1)!.elevation;
}
/** Production's rungs (ClimbProfileHero BAND_STEPS): 0 · 3 · 6 · 9 · 12+ %. */
export const gradeRung=(grade:number)=>grade>=12?4:grade>=9?3:grade>=6?2:grade>=3?1:0;
export type GradeBand={from:number;to:number;grade:number;rung:number};
/** Production's grade bands: fixed 100 m bins, signed net rise over run at interpolated bin edges, adjacent bins on one rung merged
 *  and their grade recomputed over the whole span. */
export function gradeBands(profile:readonly Point[],length:number,bin=100):GradeBand[]{
 if(profile.length<2||!(length>0))return [];
 const origin=profile[0].d,end=origin+length,grade=(a:number,b:number)=>(elevationAt(profile,b)-elevationAt(profile,a))/(b-a)*100,bands:GradeBand[]=[];
 for(let d0=origin;d0<end-1e-6;d0+=bin){
  const d1=Math.min(d0+bin,end),g=grade(d0,d1),rung=gradeRung(g),previous=bands.at(-1);
  if(previous&&previous.rung===rung){previous.to=d1;previous.grade=grade(previous.from,d1);}
  else bands.push({from:d0,to:d1,grade:g,rung});
 }
 return bands;
}
/** Local grade at a point: production's ±25 m window, clamped to the climb. */
export function localGrade(profile:readonly Point[],length:number,d:number):number{
 const origin=profile[0].d,w0=Math.max(origin,d-25),w1=Math.min(origin+length,d+25);
 return w1>w0?(elevationAt(profile,w1)-elevationAt(profile,w0))/(w1-w0)*100:0;
}

type Ranked={rank:number;duration:number;current?:boolean};
/** Gap bars scale to the largest gap in the current view; null when the board does not hold the fastest (partial or empty). */
export function gapScale(rows:readonly Ranked[]):((duration:number)=>number)|null{
 const leader=rows[0]?.rank===1?rows[0]:undefined;if(!leader)return null;
 const largest=Math.max(0,...rows.map(r=>boardGap(r.duration,leader)??0));
 return duration=>{const gap=boardGap(duration,leader)??0;return largest>0?Math.max(0,Math.min(1,gap/largest)):0;};
}
/** The Overall cell's basis for a rider with a board place and no history: the board time, then the gap to the fastest when the board holds 1st. */
export function overallBasis(current:Ranked|undefined,leader:Ranked|undefined):{duration:number;gap:number|null}|null{
 if(!current)return null;
 return {duration:current.duration,gap:boardGap(current.duration,leader)};
}

export type RailClimb={climbId:string;name:string;href:string;active:boolean;rank?:number};
/** The rail lists each distinct climb the scenarios hold, in study order, named from its own terrain and linked to V15 with the viewer and hero.
 *  A rider's board place shows only where the board holds one; the active climb takes its place from the study being viewed. */
export function railClimbs(studies:readonly ClimbStudy[],{current,viewer,hero,state}:{current:ClimbStudy;viewer:ClimbViewer;hero:Hero;state:'ready'|'loading'|'empty'|'error'}):RailClimb[]{
 const origin=new URLSearchParams({climbOrigin:current.id,climbOriginViewer:viewer,climbOriginVariant:'climb-v15'}),seen=new Set<string>(),items:RailClimb[]=[];
 const place=(s:ClimbStudy)=>{if(viewer!=='rider')return undefined;const study=v9Study(s),data=inspectV7(study,'rider');return boardRows(data,study,'ready','overall').find(r=>r.current)?.rank;};
 for(const s of studies){
  if(seen.has(s.climbId))continue;seen.add(s.climbId);
  const name=inspectV7(v9Study(s),viewer).terrain?.name,destination=climbV3Destination(s.climbId,origin,studies);
  if(!name||!destination)continue;
  const active=s.climbId===current.climbId,u=new URLSearchParams(destination.slice(2));u.set('hero',hero);
  // The open climb's place follows the page: none while its results load, are empty or fail.
  items.push({climbId:s.climbId,name,href:`/?${u}`,active,rank:active&&state!=='ready'?undefined:place(active?current:s)});
 }
 return items;
}

/** A pitch's grade to one decimal: a true minus below zero, never '-0.0', no plus sign. */
export const pitchGrade=(grade:number)=>{const rounded=Math.round(Math.abs(grade)*10)/10;return `${grade<0&&rounded>0?'−':''}${rounded.toFixed(1)}`;};

/** Start and Finish labels sit 8px off the end, on the side away from the line (the direction from its neighbour to the end). */
export function endLabelAnchor(end:[number,number],neighbour:[number,number]):{anchor:'left'|'right'|'top'|'bottom';offset:[number,number]}{
 const dx=(end[0]-neighbour[0])*Math.cos(end[1]*Math.PI/180),dy=-(end[1]-neighbour[1]);
 if(Math.abs(dx)>=Math.abs(dy))return dx>=0?{anchor:'left',offset:[8,0]}:{anchor:'right',offset:[-8,0]};
 return dy>=0?{anchor:'top',offset:[0,8]}:{anchor:'bottom',offset:[0,-8]};
}
/** The route fit per masthead. Every edge keeps at least 48px so an end label never clips; the copy's side keeps the copy's width, and the
 *  control column's side keeps room for a label beside the controls (32px buttons at 12px, then a label's width). */
export function heroFitPadding15(width:number,height:number,phone:boolean,hero:Hero|'card'):PaddingOptions{
 const edge=(n:number,size:number)=>Math.min(Math.max(48,n),Math.round(size*.3));
 if(hero==='card')return {top:edge(48,height),right:edge(48,width),bottom:edge(48,height),left:edge(48,width)};
 if(phone){const bottom=hero==='c'?168:hero==='a'?236:176;return {top:edge(hero==='a'?76:48,height),right:edge(84,width),bottom:Math.min(bottom,Math.round(height*.6)),left:edge(48,width)};}
 return {left:Math.round(width*(hero==='c'?.52:.5))+24,right:edge(100,width),top:edge(48,height),bottom:edge(48,height)};
}
