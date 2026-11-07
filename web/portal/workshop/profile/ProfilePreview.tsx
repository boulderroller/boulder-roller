import {useEffect,useState} from 'react';
import {ProfileV2,type ProfileAvailability} from './ProfileV2';
import {DraftProfileV2} from './DraftProfileV2';
import {profileScenario,parseProfileImport,profileStorageKey,retainProfileScenario,type ProfileScenario} from './profileModel';
import {profileDestination} from './profileNavigation';
import {savedWorkshop} from '../workbenchNavigation';
export function ProfilePreview(){
 const standalone=window.parent===window;
 const initial=()=>{if(!standalone)return null;try{const s=profileScenario(new URLSearchParams(location.search).get('scenario')??'owner'),saved=sessionStorage.getItem(profileStorageKey(s));return saved?parseProfileImport(JSON.parse(saved)):s;}catch{return profileScenario('error');}};
 const [scenario,setScenario]=useState<ProfileScenario|null>(initial),[availability,setAvailability]=useState<ProfileAvailability>(()=>{const s=initial();return s?.id==='error'?'error':s?.id==='stale'?'offline':s?.id==='loading'||!s?'loading':'ready';});
 useEffect(()=>{
  const receive=(e:MessageEvent)=>{if(e.origin!==location.origin||e.source!==window.parent||e.data?.type!=='profile-v2-data')return;try{const next=parseProfileImport(e.data.scenario);setScenario(previous=>retainProfileScenario(previous,next));setAvailability(e.data.availability);}catch{setAvailability('error');}};
  window.addEventListener('message',receive);window.parent.postMessage({type:'profile-v2-ready'},location.origin);
  return()=>window.removeEventListener('message',receive);
 },[]);
 const send=(type:string,extra:Record<string,unknown>={})=>{if(standalone){if(type==='profile-v2-recover')setAvailability('ready');if(type==='profile-v2-navigate'&&scenario&&typeof extra.href==='string'){const destination=profileDestination(scenario,extra.href);if(destination)location.assign(destination.restore?savedWorkshop(destination.page)?.href??destination.href:destination.href);}return;}window.parent.postMessage({type,...extra},location.origin);};
 const Candidate=new URLSearchParams(location.search).get('draft')==='original'?DraftProfileV2:ProfileV2;
 return <Candidate scenario={scenario??profileScenario('loading')} availability={scenario?availability:'loading'} onNavigate={href=>send('profile-v2-navigate',{href})} onRecover={()=>send('profile-v2-recover')}/>;
}
