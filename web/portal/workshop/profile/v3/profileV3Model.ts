import {scenarios} from '../../scenarios';
import {parseScenario,climbResult,climbSamples,summarize,type Scenario} from '../../scenario';
export const TABS=['overview','rides','training','portfolio'] as const;
export type ProfileTab=typeof TABS[number];
export type Viewer='owner'|'visitor';
export type Availability='ready'|'loading'|'error'|'offline';
export type ProfileStudy={version:1;candidate:'profile-v3';id:string;label:string;source:string;private:boolean;recording:Scenario|null};
export const PROFILE_V3_SCENARIOS=[['recorded','Recorded ride · anonymous rider'],['sparse','Recorded ride · limited measurements'],['empty','No riding history'],['private','Private profile']] as const;
export function profileStudy(id='recorded'):ProfileStudy{
 const row=PROFILE_V3_SCENARIOS.find(s=>s[0]===id)??PROFILE_V3_SCENARIOS[0];
 const recording=row[0]==='private'||row[0]==='empty'?null:structuredClone(scenarios.find(s=>s.id==='recorded')!);
 if(row[0]==='sparse'&&recording){recording.ride.samples=recording.ride.samples.map(s=>({...s,elevation:null,power:null}));recording.source.description+=' Elevation and power omitted for the limited-measurements state.';}
 return {version:1,candidate:'profile-v3',id:row[0],label:row[1],source:recording?.source.description??'Workshop state study. No rider identity, riding history or economic values supplied.',private:row[0]==='private',recording};
}
export function parseProfileStudy(raw:unknown):ProfileStudy{
 const s=raw as ProfileStudy;
 if(!s||s.version!==1||s.candidate!=='profile-v3'||typeof s.private!=='boolean'||!s.id||typeof s.id!=='string'||s.id.length>100||typeof s.label!=='string'||!s.label.trim()||typeof s.source!=='string'||!s.source.trim())throw Error('Choose a Profile V3 scenario with its source.');
 if(s.private&&s.recording!==null)throw Error('A private Profile scenario must not contain hidden rider data.');
 if(JSON.stringify(raw).length>8*1024*1024)throw Error('Choose a scenario smaller than 8 MB.');
 const recording=s.recording===null?null:parseScenario(s.recording);
 return {version:1,candidate:'profile-v3',id:s.id,label:s.label,source:s.source,private:s.private,recording};
}
export const allowedTab=(tab:string|null,viewer:Viewer):ProfileTab=>viewer==='owner'&&TABS.includes(tab as ProfileTab)?tab as ProfileTab:'overview';
export const profileV3Key=(id:string)=>`br-profile-v3:${id}`;
export function profileProjection(study:ProfileStudy,_viewer:Viewer){
 const recording=study.private?null:study.recording;
 const efforts=recording?recording.climbs.map(climb=>({...climb,...climbResult(recording,climb),samples:climbSamples(recording,climb)})):[];
 return {private:study.private,name:study.private?null:recording?.ride.rider?.displayName??'Rider',portrait:recording?.ride.rider?.avatarDataUrl,recording,rides:recording?[recording]:[],efforts,totalRides:recording?1:0,totals:recording?summarize(recording.ride.samples):null};
}
// Geographic destinations from climbV4Navigation; no results transfer to canonical courses.
const retainedRecording=scenarios.find(s=>s.id==='recorded')!;
export const canonicalClimb=(id:string,recording:Scenario)=>recording.ride.samples.length!==retainedRecording.ride.samples.length||!recording.ride.samples.every((p,i)=>{const q=retainedRecording.ride.samples[i];return p.lat===q.lat&&p.lon===q.lon&&p.t===q.t;})||JSON.stringify(recording.climbs)!==JSON.stringify(retainedRecording.climbs)?undefined:({'43f15658':'43f15658-a824-438d-9925-e61c67ddabe9','b51920f8':'b51920f8-4707-4984-890d-656c7078f36a','4fd1981e':'4fd1981e-50a5-4abb-804a-5b7cacb7a523'} as Record<string,string>)[id];
export type ProfileState={tab:ProfileTab;selected:string|null;query:string;metric:'distance'|'gain'|'duration';detail:string|null};
export const initialProfileState=(viewer:Viewer,tab:string|null=null):ProfileState=>({tab:allowedTab(tab,viewer),selected:null,query:'',metric:'distance',detail:null});
export function resolveProfileStudy(id:string,raw:string|null){
 if(raw){const s=parseProfileStudy(JSON.parse(raw));if(s.id!==id)throw Error('Imported Profile ID does not match.');return s;}
 if(!PROFILE_V3_SCENARIOS.some(s=>s[0]===id))throw Error('Imported Profile scenario unavailable.');
 return profileStudy(id);
}
export function restoreProfileState(study:ProfileStudy,viewer:Viewer,raw:Partial<ProfileState>):ProfileState{
 const recording=study.private?null:study.recording,ids=recording?.climbs.map(c=>c.id)??[];
 return {tab:allowedTab(raw.tab??null,viewer),selected:raw.selected&&ids.includes(raw.selected)?raw.selected:null,detail:recording&&(raw.detail==='ride'||ids.includes(raw.detail??''))?raw.detail!:null,query:typeof raw.query==='string'?raw.query:'',metric:raw.metric==='gain'||raw.metric==='duration'?raw.metric:'distance'};
}
