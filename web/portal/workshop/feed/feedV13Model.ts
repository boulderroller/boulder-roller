import {riderForEntry} from './feedV9Model';
import type {FeedEntry} from './feedModel';
import {v9RideHref,v9RiderHref,v9RideContext,type FeedV9Scenario} from './feedV9Model';
import {climbStudies} from '../climb/climbModel';
import {ordinal} from '../climb/climbV7Model';
import {destinationHref} from '../frame/destinations';
import {distanceLabel,summarize,timeLabel,type Scenario} from '../scenario';
import {heroFitPadding15} from '../climb/climbV15Model';
import type {V15Item} from '../frame/V15Frame';
export type {FeedV9Scenario as FeedV13Scenario} from './feedV9Model';
export type {V9Rider as V13Rider} from './feedV9Model';
export {riderForEntry,riderForBoard,v9NetworkItems as v13NetworkItems} from './feedV9Model';
const origin=(href:string)=>{const u=new URL(href,'http://workshop.local');u.searchParams.set('feedVariant','feed-v13');u.searchParams.set('variant','candidate-v14');return u.pathname+u.search;};
export function v13RideHref(entry:FeedEntry,climb:string|undefined,view:'overview'|'analysis'|'vault',scenario:FeedV9Scenario,filter='everyone'){
 return origin(v9RideHref({...entry,owned:v13OwnRide(scenario,entry)},climb,view,scenario.id,filter));
}
export const v13RiderHref=(...args:Parameters<typeof v9RiderHref>)=>{const u=new URL(v9RiderHref(...args),'http://workshop.local');u.searchParams.set('variant','feed-v13');return u.pathname+u.search;};
export const v13RideContext=(...args:Parameters<typeof v9RideContext>)=>{const c=v9RideContext(...args);return c?{...c,climbs:c.climbs.map(climb=>({...climb,leaderboard:climb.leaderboard.map(row=>({...row,...(row.href?{href:origin(row.href)}:{})}))}))}:undefined;};
export function v13ClimbHref(climbId:string){const study=climbStudies.find(s=>s.climbId===climbId);return study?destinationHref('climb',{variant:'climb-v16',scenario:study.id,viewer:'rider'}):undefined;}
export function v13RailItems(scenario:FeedV9Scenario):V15Item[]{
 return (scenario.workshopV3?.personal?.standings??[]).flatMap(standing=>{
  const entry=scenario.entries.find(e=>e.id===standing.entryId),climb=entry?.ride.climbs.find(c=>c.id===standing.climbId);
  return climb?[{id:`${standing.entryId}:${climb.id}`,label:climb.name,href:v13ClimbHref(climb.id),meta:ordinal(standing.rank)}]:[];
 });
}
export function v13RideFacts(scenario:Scenario){
 const totals=summarize(scenario.ride.samples);
 return [{label:'Distance',value:distanceLabel(totals.distance),unit:'km'},{label:'Elapsed time',value:timeLabel(totals.duration)},...(totals.gain===null?[]:[{label:'Elevation',value:Math.round(totals.gain).toLocaleString(),unit:'m'}])];
}
export function v13HeroPadding(width:number,height:number,phone:boolean,copyW:number){
 const padding=heroFitPadding15(width,height,phone,'a');
 // Phone copy flows below 200px of map; 48px also clears the rising fade and route stroke.
 return phone?{...padding,bottom:Math.max(padding.bottom??0,height-200+48)}:{...padding,left:copyW+140,right:48};
}

/** Bound rider identity owns both the masthead and its ride destination; order and filter do not. */
export function v13OwnRide(scenario:FeedV9Scenario,entry:FeedEntry):boolean{
 const rider=riderForEntry(scenario,entry.id);return rider?!!rider.viewer:!!entry.owned;
}
