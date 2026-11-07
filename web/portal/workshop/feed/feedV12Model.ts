import {v9RideHref,v9RiderHref,v9RideContext,type FeedV9Scenario} from './feedV9Model';
import {climbStudies} from '../climb/climbModel';
import {ordinal} from '../climb/climbV7Model';
import {destinationHref} from '../frame/destinations';
import {distanceLabel,summarize,timeLabel,type Scenario} from '../scenario';
import {heroFitPadding15} from '../climb/climbV15Model';
import type {V15Item} from '../frame/V15Frame';
export type {FeedV9Scenario as FeedV12Scenario} from './feedV9Model';
export type {V9Rider as V12Rider} from './feedV9Model';
export {riderForEntry,riderForBoard,v9NetworkItems as v12NetworkItems} from './feedV9Model';
const origin=(href:string)=>{const u=new URL(href,'http://workshop.local');u.searchParams.set('feedVariant','feed-v12');u.searchParams.set('variant','candidate-v14');return u.pathname+u.search;};
export const v12RideHref=(...args:Parameters<typeof v9RideHref>)=>origin(v9RideHref(...args));
export const v12RiderHref=(...args:Parameters<typeof v9RiderHref>)=>{const u=new URL(v9RiderHref(...args),'http://workshop.local');u.searchParams.set('variant','feed-v12');return u.pathname+u.search;};
export const v12RideContext=(...args:Parameters<typeof v9RideContext>)=>{const c=v9RideContext(...args);return c?{...c,climbs:c.climbs.map(climb=>({...climb,leaderboard:climb.leaderboard.map(row=>({...row,...(row.href?{href:origin(row.href)}:{})}))}))}:undefined;};
export function v12ClimbHref(climbId:string){const study=climbStudies.find(s=>s.climbId===climbId);return study?destinationHref('climb',{variant:'climb-v15',scenario:study.id,viewer:'rider'}):undefined;}
export function v12RailItems(scenario:FeedV9Scenario):V15Item[]{
 return (scenario.workshopV3?.personal?.standings??[]).flatMap(standing=>{
  const entry=scenario.entries.find(e=>e.id===standing.entryId),climb=entry?.ride.climbs.find(c=>c.id===standing.climbId);
  return climb?[{id:`${standing.entryId}:${climb.id}`,label:climb.name,href:v12ClimbHref(climb.id),meta:ordinal(standing.rank)}]:[];
 });
}
export function v12RideFacts(scenario:Scenario){
 const totals=summarize(scenario.ride.samples);
 return [{label:'Distance',value:distanceLabel(totals.distance),unit:'km'},{label:'Elapsed time',value:timeLabel(totals.duration)},...(totals.gain===null?[]:[{label:'Elevation',value:Math.round(totals.gain).toLocaleString(),unit:'m'}])];
}
export function v12HeroPadding(width:number,height:number,phone:boolean,copyW:number){
 const padding=heroFitPadding15(width,height,phone,'a');
 // Phone copy flows below 200px of map; 48px also clears the rising fade and route stroke.
 return phone?{...padding,bottom:Math.max(padding.bottom??0,height-200+48)}:{...padding,left:copyW+140,right:48};
}
