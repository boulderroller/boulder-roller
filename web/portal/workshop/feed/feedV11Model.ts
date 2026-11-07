import {v9RideHref,v9RiderHref,v9RideContext,type FeedV9Scenario} from './feedV9Model';
import {climbStudies} from '../climb/climbModel';
import {ordinal} from '../climb/climbV7Model';
import {destinationHref} from '../frame/destinations';
import {distanceLabel,summarize,timeLabel,type Scenario} from '../scenario';
import type {V15Item} from '../frame/V15Frame';
export type {FeedV9Scenario as FeedV11Scenario} from './feedV9Model';
export type {V9Rider as V11Rider} from './feedV9Model';
export {riderForEntry,riderForBoard,v9NetworkItems as v11NetworkItems} from './feedV9Model';
const origin=(href:string)=>{const u=new URL(href,'http://workshop.local');u.searchParams.set('feedVariant','feed-v11');u.searchParams.set('variant','candidate-v14');return u.pathname+u.search;};
export const v11RideHref=(...args:Parameters<typeof v9RideHref>)=>origin(v9RideHref(...args));
export const v11RiderHref=(...args:Parameters<typeof v9RiderHref>)=>{const u=new URL(v9RiderHref(...args),'http://workshop.local');u.searchParams.set('variant','feed-v11');return u.pathname+u.search;};
export const v11RideContext=(...args:Parameters<typeof v9RideContext>)=>{const c=v9RideContext(...args);return c?{...c,climbs:c.climbs.map(climb=>({...climb,leaderboard:climb.leaderboard.map(row=>({...row,...(row.href?{href:origin(row.href)}:{})}))}))}:undefined;};
export function v11ClimbHref(climbId:string){const study=climbStudies.find(s=>s.climbId===climbId);return study?destinationHref('climb',{variant:'climb-v15',scenario:study.id,viewer:'rider'}):undefined;}
export function v11RailItems(scenario:FeedV9Scenario):V15Item[]{
 return (scenario.workshopV3?.personal?.standings??[]).flatMap(standing=>{
  const entry=scenario.entries.find(e=>e.id===standing.entryId),climb=entry?.ride.climbs.find(c=>c.id===standing.climbId);
  return climb?[{id:`${standing.entryId}:${climb.id}`,label:climb.name,href:v11ClimbHref(climb.id),meta:ordinal(standing.rank)}]:[];
 });
}
export function v11RideFacts(scenario:Scenario){
 const totals=summarize(scenario.ride.samples);
 return [{label:'Distance',value:distanceLabel(totals.distance),unit:'km'},...(totals.gain===null?[]:[{label:'Elevation',value:Math.round(totals.gain).toLocaleString(),unit:'m'}]),{label:'Elapsed time',value:timeLabel(totals.duration)}];
}
