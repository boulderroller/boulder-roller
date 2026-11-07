import {baselineJourney,baselineScenario,baselineRooms} from '../baseline/model';
import {roomDestination,type WorkshopPage} from '../roomRegistry';
import {compatibleProfileDetail,type ProfileScenario} from './profileModel';
export function profileDestination(s:ProfileScenario,href:string):{page:WorkshopPage;href:string;restore?:boolean}|null{
 if(!compatibleProfileDetail(s,href)||!href.startsWith('/')||href.startsWith('//'))return null;
 const journey=baselineJourney({...baselineScenario('profile',s.id),viewer:s.viewer},href),owner=journey.owner;
 if(owner==='profile'||!owner)return null;
 if(owner==='feed'||owner==='map')return {page:owner,href:roomDestination(owner)};
 const spec=baselineRooms.find(r=>r.id===owner);if(!spec)return null;
 if(s.viewer==='owner'&&['rides','training','portfolio'].includes(spec.id)&&new URL(href,'http://workshop.local').pathname==='/profile')return {page:spec.id,href:roomDestination(spec.id),restore:true};
 const id=spec.id==='settings'?'identity':spec.id.startsWith('public-')?'public':spec.scenarios[0].id;
 return {page:spec.id,href:`/?surface=${spec.id}&variant=${spec.id}-v1&scenario=${id}&route=${encodeURIComponent(journey.href)}&routeState=${encodeURIComponent(JSON.stringify({returnTo:s.route}))}`};
}
