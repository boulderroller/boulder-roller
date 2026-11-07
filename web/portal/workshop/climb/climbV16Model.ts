import type {PaddingOptions} from 'maplibre-gl';
import type {ClimbStudy,ClimbViewer} from './climbModel';
import type {DiscoveryV4} from '../feed/feedV4Model';
import {inspectV7} from './climbV7Model';
import {v9Study} from './climbV9Model';
import {v13Effort,v13Ride} from './climbV13Model';
import {climbV4MapHref} from './climbV4Navigation';
import {destinationHref} from '../frame/destinations';
import {climbV3Destination} from './climbV3Navigation';
import {boardRows,boardGap} from './climbV14Model';
import type {V14BoardRow} from './climbV14Model';
import type {ClimbInspection} from './climbV5Model';
import type {ClimbV9Study} from './climbV9Model';
import {v8Power} from './climbV8Model';
import {climbMeasurements} from './climbV12Measurements';
export {boardRows,boardLeader,boardComplete,boardGap,plural,stripCells,roundTicks,distanceTicks,type BoardView,type V14BoardRow,type StripCell} from './climbV14Model';
const rideDestination=(href:string)=>{const p=new URL(href,'http://workshop.local').searchParams;p.set('variant','candidate-v14');p.set('climbOriginVariant','climb-v16');return `/?${p}`;};
export const v16Effort=(href:string)=>rideDestination(v13Effort(href));
export const v16Ride=(href:string)=>rideDestination(v13Ride(href));
export function v16MapHref(study:ClimbStudy,viewer:ClimbViewer):string|null{
 const href=climbV4MapHref(study,viewer);if(!href)return null;
 return destinationHref('map',{viewer,origin:new URL(href).searchParams.get('origin')!});
}


// Copied from src/lib/estimatedPower.ts. Estimates never accept a rider's private mass.
export const powerConstants={riderKg:75,bikeKg:8,g:9.80665,rho:1.225,cda:.32,crr:.005,drivetrain:.975} as const;
function steadyPower(length:number,gain:number,seconds:number,riderKg:number):number|null{
 if(![length,gain,seconds,riderKg].every(Number.isFinite)||length<=0||gain<0||seconds<=0||riderKg<=0)return null;
 const {bikeKg,g,rho,cda,crr,drivetrain}=powerConstants,m=riderKg+bikeKg,v=length/seconds,theta=Math.atan(gain/length);
 return (m*g*v*Math.sin(theta)+crr*m*g*v*Math.cos(theta)+.5*rho*cda*v**3)/drivetrain;
}
export function estimatedWatts(length:number,gain:number,seconds:number):number|null{
 const watts=steadyPower(length,gain,seconds,powerConstants.riderKg);return watts===null?null:Math.round(watts);
}
export type ExamplePowerRider={massKg:number;sharesWkg:boolean;variation:number};
// Stable fictional fixture names, never encounter-order rider ids. Imports acquire no example mass or recording.
export const examplePowerRiders:Readonly<Record<string,ExamplePowerRider>>={
 'Example Rider':{massKg:72,sharesWkg:false,variation:0},
 Jamie:{massKg:70,sharesWkg:true,variation:.02},
 Alex:{massKg:76,sharesWkg:false,variation:.01},
 Morgan:{massKg:80,sharesWkg:true,variation:.01},
 Rowan:{massKg:82,sharesWkg:false,variation:-.01},
 Sam:{massKg:68,sharesWkg:false,variation:-.02},
 Robin:{massKg:62,sharesWkg:true,variation:.03},
 Drew:{massKg:88,sharesWkg:true,variation:-.02},
};
/** Verification belongs to this rider's exact effort, not every effort by that rider. */
export function powerVerified(data:ClimbInspection,study:ClimbV9Study,row:V14BoardRow):boolean{
 return boardRows(data,study,'ready','qualified').some(q=>q.duration===row.duration&&(q.riderHref?q.riderHref===row.riderHref:!row.riderHref&&q.name===row.name));
}
export const sharedWkg=(watts:number,person:Pick<ExamplePowerRider,'massKg'|'sharesWkg'>|undefined,own:boolean)=>
 person&&person.massKg>0&&Number.isFinite(person.massKg)&&(own||person.sharesWkg)?Number((watts/person.massKg).toFixed(1)):null;
export type BoardPower={kind:'measured'|'estimated';watts:number;wkg:number|null;source:'recording'|'example'|'standard-mass'};
export function rowPower(data:ClimbInspection,study:ClimbV9Study,row:V14BoardRow):BoardPower|null{
 const recorded=row.href?v8Power(data.recordings,study.climbId,row.href):null;
 const example=['wises','black-rock','sprague','first-visit','vault'].includes(study.id)?examplePowerRiders[row.name]:undefined;
 if(recorded!==null&&Number.isFinite(recorded)){const watts=Math.round(recorded);return {kind:'measured',watts,wkg:sharedWkg(watts,example,!!row.current),source:'recording'};}
 const terrain=data.terrain;if(!terrain||terrain.profile.length<2)return null;
 const gain=climbMeasurements(terrain).gain;
 if(example&&powerVerified(data,study,row)){const value=steadyPower(terrain.length,gain,row.duration,example.massKg);if(value!==null){const watts=Math.round(value*(1+example.variation));return {kind:'measured',watts,wkg:sharedWkg(watts,example,!!row.current),source:'example'};}}
 const watts=estimatedWatts(terrain.length,gain,row.duration);
 return watts===null?null:{kind:'estimated',watts,wkg:null,source:'standard-mass'};
}

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
/** The Overall cell's basis for a rider with a board place and no history: the board time, then the gap to the fastest when the board holds 1st. */
export function overallBasis(current:Ranked|undefined,leader:Ranked|undefined):{duration:number;gap:number|null}|null{
 if(!current)return null;
 return {duration:current.duration,gap:boardGap(current.duration,leader)};
}

export type RailClimb={climbId:string;name:string;href:string;active:boolean;rank?:number};
/** The rail lists each distinct climb the scenarios hold, in study order, named from its own terrain and linked to V16 with the viewer and hero.
 *  A rider's board place shows only where the board holds one; the active climb takes its place from the study being viewed. */
export function railClimbs(studies:readonly ClimbStudy[],{current,viewer,hero,state}:{current:ClimbStudy;viewer:ClimbViewer;hero:Hero;state:'ready'|'loading'|'empty'|'error'}):RailClimb[]{
 const origin=new URLSearchParams({climbOrigin:current.id,climbOriginViewer:viewer,climbOriginVariant:'climb-v16'}),seen=new Set<string>(),items:RailClimb[]=[];
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
export function heroFitPadding16(width:number,height:number,phone:boolean,hero:Hero|'card'):PaddingOptions{
 const edge=(n:number,size:number)=>Math.min(Math.max(48,n),Math.round(size*.3));
 if(hero==='card')return {top:edge(48,height),right:edge(48,width),bottom:edge(48,height),left:edge(48,width)};
 if(phone){const bottom=hero==='c'?168:hero==='a'?236:176;return {top:edge(hero==='a'?76:48,height),right:edge(84,width),bottom:Math.min(bottom,Math.round(height*.6)),left:edge(48,width)};}
 return {left:Math.round(width*(hero==='c'?.52:.5))+24,right:edge(100,width),top:edge(48,height),bottom:edge(48,height)};
}
