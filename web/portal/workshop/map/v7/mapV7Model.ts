import {midpoint,type MapCamera,type MapClimb,type MapState,type MapStudy,type MapViewer} from '../mapModel';
export type MapCandidate='map-v1'|'map-v2'|'map-v3'|'map-v4'|'map-v5'|'map-v6'|'map-v7';
export const readCandidate=(value:string|null):MapCandidate=>value==='map-v1'||value==='map-v2'||value==='map-v3'||value==='map-v4'||value==='map-v5'||value==='map-v6'?value:'map-v7';
// An explicit selection pans at the existing scale. Restoring state never calls this.
export function selectionMove(climb:MapClimb,camera:MapCamera,view:{width:number;height:number;listOpen:boolean}){
 const phone=view.width<600;
 const targetX=phone?view.width/2:view.listOpen?(Math.min(390,view.width*.35)+view.width)/2:view.width*.55;
 const targetY=phone?(72+Math.max(100,view.height-360))/2:view.height*.43;
 return {center:midpoint(climb),zoom:camera.zoom,offset:[targetX-view.width/2,targetY-view.height/2] as [number,number]};
}
export function candidateHref(study:MapStudy,viewer:MapViewer,id:string|null,origin:string|null|undefined,variant:MapCandidate){
 const p=new URLSearchParams({surface:'map',variant,scenario:study.id,viewer});if(origin)p.set('origin',origin);if(id)p.set('climb',id);return `/?${p}`;
}
export const candidateSnapshotKey=(id:string,variant:MapCandidate)=>`br-${variant==='map-v7'?'map-v7':variant==='map-v6'?'map-v6':variant==='map-v5'?'map-v5':variant==='map-v4'?'map-v4':variant==='map-v3'?'map-v3':'map-v2'}:${id}`;
export function isCurrentMapMessage(message:unknown,context:{variant:MapCandidate;revision:number;studyId:string}){
 if(!message||typeof message!=='object')return false;
 const m=message as {variant?:unknown;revision?:unknown;snapshot?:{studyId?:unknown}};
 return m.variant===context.variant&&m.revision===context.revision&&m.snapshot?.studyId===context.studyId;
}
export function readCandidateSnapshot(id:string,variant:MapCandidate):unknown{try{return JSON.parse(sessionStorage.getItem(candidateSnapshotKey(id,variant))??'null');}catch{return null;}}
export function saveCandidateSnapshot(state:MapState,variant:MapCandidate){try{sessionStorage.setItem(candidateSnapshotKey(state.studyId,variant),JSON.stringify(state));}catch{/* Active tab retains the snapshot. */}}
export function mapV7ExploreHref(climbId:string,viewer:MapViewer='rider',scenario='wises'){return `/?${new URLSearchParams({surface:'map',variant:'map-v7',scenario,viewer,origin:climbId,arrival:'climb'})}`;}

export type MapFilters={distance:string;grade:string;rise:string};
export type MapV7State=MapState & {filters?:MapFilters};
export const EMPTY_FILTERS:MapFilters={distance:'any',grade:'any',rise:'any'};
export const FILTER_OPTIONS={
 distance:[['any','Any distance'],['0-1','Under 1 km'],['1-2','1–2 km'],['2-5','2–5 km'],['5+','5 km or more']],
 grade:[['any','Any grade'],['0-5','Under 5%'],['5-8','5–8%'],['8-12','8–12%'],['12+','12% or more']],
 rise:[['any','Any elevation rise'],['0-50','Under 50 m'],['50-100','50–100 m'],['100-200','100–200 m'],['200+','200 m or more']],
} as const;
export function normalizeFilters(raw:unknown):MapFilters{
 const obj=raw&&typeof raw==='object'?raw as Partial<MapFilters>:{};
 return Object.fromEntries(Object.entries(FILTER_OPTIONS).map(([key,options])=>[key,options.some(([v])=>v===obj[key as keyof MapFilters])?obj[key as keyof MapFilters]:'any'])) as MapFilters;
}
export const activeFilterCount=(filters:MapFilters)=>Object.values(filters).filter(v=>v!=='any').length;
const within=(n:number,value:string)=>{if(value==='any')return true;const [low,high]=value.replace('+','-').split('-').map(Number);return n>=low&&(!high||n<high);};
export function filterClimbs(climbs:MapClimb[],raw:unknown,query:string){
 const f=normalizeFilters(raw),q=query.trim().toLocaleLowerCase();
 return climbs.filter(c=>(!q||c.name.toLocaleLowerCase().includes(q))&&within(c.lengthM/1000,f.distance)&&within(c.gradePct,f.grade)&&within(c.riseM,f.rise));
}
import {restoreMapState} from '../mapModel';
import {stateFromQuery} from '../mapNavigation';
export function restoreCandidateState(study:MapStudy,raw:unknown,variant:MapCandidate):MapV7State{
 const base=restoreMapState(study,raw);
 if(variant!=='map-v7'&&variant!=='map-v6'&&variant!=='map-v5'&&variant!=='map-v4')return base;
 const saved=raw as MapV7State|null;
 return {...base,filters:normalizeFilters(saved?.studyId===study.id?saved.filters:null)};
}
export function stateFromCandidateQuery(study:MapStudy,p:URLSearchParams,raw?:unknown):MapV7State{
 const base=stateFromQuery(study,p,raw),restored=restoreCandidateState(study,raw,readCandidate(p.get('variant')));
 if(restored.filters&&p.get('arrival')==='climb'&&base.originId)return {...base,filters:{...EMPTY_FILTERS},selectedId:base.originId,camera:null,area:null,query:'',scrollTop:0,sheetExpanded:false};
 return {...base,...(restored.filters?{filters:base.originId!==restored.originId?{...EMPTY_FILTERS}:restored.filters}:{})};
}
