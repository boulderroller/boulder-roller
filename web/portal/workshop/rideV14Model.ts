import {channelSummary,channelValue,analysisSamples} from './v3Model';
import {rideFileStats} from './v12Metrics';
import {climbV3Destination} from './climb/climbV3Navigation';
import {railClimbs} from './climb/climbV15Model';
import type {ClimbStudy} from './climb/climbModel';
import {timeLabel} from './scenario';
import type {Scenario,Sample} from './scenario';
import type {ExampleEconomics} from './v12Example';
import type {V13Context} from './v13Context';
export type RideFact={label:string;value:string;unit?:string;state?:string};
/** V13's fields and order, with missing values omitted. Recording and CAL remain separate facts. */
export function rideFacts(scenario:Scenario,bundled:boolean,economics:ExampleEconomics|null):RideFact[]{
 const points=analysisSamples(scenario.ride.samples),stats=rideFileStats(points),facts:RideFact[]=[];
 for(const [channel,label,unit] of [['power','Avg power','W'],['cadence','Avg cadence','rpm'],['speed','Avg speed','km/h']] as const){const n=channelSummary(points,channel).average;if(n!==null)facts.push({label,value:channelValue(n,channel),unit});}
 if(stats.maxSpeed!==null)facts.push({label:'Max speed',value:channelValue(stats.maxSpeed,'speed'),unit:'km/h'});
 if(stats.maxPower!==null)facts.push({label:'Max power',value:Math.round(stats.maxPower).toLocaleString(),unit:'W'});
 if(stats.workKj!==null)facts.push({label:'Work',value:Math.round(stats.workKj).toLocaleString(),unit:'kJ'});
 if(bundled)facts.push({label:'Source',value:'FIT recording'});
 if(economics)facts.push({label:'Ride CAL',value:String(economics.riderCal.amount),unit:'CAL',state:economics.riderCal.state==='pending'?'Pending':'Counted'});
 return facts;
}
/** The existing destination resolver binds only known studies. Imported or unknown climbs receive no invented destination. */
export function rideClimbs(scenario:Scenario,context:V13Context|undefined,owner:boolean,query:URLSearchParams,studies:readonly ClimbStudy[],pending=false){
 return scenario.climbs.map((climb,i)=>{
  const study=studies.find(s=>s.climbId===climb.id),origin=new URLSearchParams(query);
  if(origin.get('climbOrigin')){origin.set('climbOriginVariant','climb-v15');if(!owner)origin.set('climbOriginViewer','visitor');}
  else if(study&&!/^(?:local-|feed-local-)/.test(query.get('scenario')??'')){origin.set('climbOrigin',study.id);origin.set('climbOriginId',climb.id);origin.set('climbOriginVariant','climb-v15');origin.set('climbOriginViewer',owner?'rider':'visitor');}
  const destination=climbV3Destination(climb.id,origin,studies);
  const rank=pending?undefined:context?.climbs.find(c=>c.climbId===climb.id)?.resultRank;
  const bound=study&&destination&&new URL(destination,'http://workshop').searchParams.get('scenario')===study.id;
  const railRank=owner&&!pending&&bound?railClimbs(studies,{current:study,viewer:'rider',hero:'a',state:'ready'}).find(c=>c.climbId===climb.id)?.rank:undefined;
  return {climb,number:i+1,href:destination,rank,railRank};
 });
}
/** Same 30-second discontinuity rule as V12Map. */
export function rideGeometry(points:Sample[]){
 const coordinates:number[][][]=[];let run:number[][]=[];
 points.forEach((p,i)=>{if(i>0&&p.t-points[i-1].t>30){if(run.length>1)coordinates.push(run);run=[];}run.push([p.lon,p.lat]);});
 if(run.length>1)coordinates.push(run);
 return {type:'Feature' as const,properties:{},geometry:{type:'MultiLineString' as const,coordinates}};
}

/** V13's originating-feed context, with the shell's Feed destination when there is no origin. */
export function rideFeedHref(query:URLSearchParams){
 const scenario=query.get('feedScenario');
 return `/?${new URLSearchParams({surface:'feed',variant:scenario?query.get('feedVariant')==='feed-v13'?'feed-v13':query.get('feedVariant')==='feed-v12'?'feed-v12':query.get('feedVariant')==='feed-v11'?'feed-v11':query.get('feedVariant')==='feed-v9'?'feed-v9':query.get('feedVariant')==='feed-v8'?'feed-v8':query.get('feedVariant')==='feed-v7'?'feed-v7':'feed-v6':'feed-v9',scenario:scenario??'mixed',filter:scenario&&query.get('feedFilter')==='following'?'following':'everyone'})}`;
}
/** Three to five round clock ticks, then the exact elapsed endpoint. */
export function rideTimeTicks(end:number){
 const steps=[900,1800,...Array.from({length:24},(_,i)=>(i+1)*3600)];
 const step=steps.find(step=>Math.ceil(end/step)>=3&&Math.ceil(end/step)<=5)??Math.max(900,Math.ceil(end/4/3600)*3600);
 const ticks=Array.from({length:Math.ceil(end/step)},(_,i)=>({value:i*step,label:`${Math.floor(i*step/3600)}:${String(i*step/60%60).padStart(2,'0')}`}));
 return [...ticks,{value:end,label:timeLabel(end)}];
}
