import {climbResult} from '../scenario';
import type {ClimbInspection} from './climbV5Model';
import {v7Effort} from './climbV7Model';
export const v8Effort=(href:string)=>{const p=new URL(v7Effort(href),'http://local.test').searchParams;p.set('climbOriginVariant','climb-v8');return `/?${p}`;};
export const v8Ride=(href:string)=>{const p=new URL(v8Effort(href),'http://local.test').searchParams;for(const key of ['climb','from','to','axis','effort'])p.delete(key);p.set('view','overview');return `/?${p}`;};
export function v8Power(recordings:ClimbInspection['recordings'],climbId:string,href:string):number|null{
 const id=new URL(href,'http://local.test').searchParams.get('scenario'),entry=recordings.find(r=>r.entry.ride.id===id)?.entry,climb=entry?.ride.climbs.find(c=>c.id===climbId);
 return entry&&climb?climbResult(entry.ride,climb).power:null;
}
