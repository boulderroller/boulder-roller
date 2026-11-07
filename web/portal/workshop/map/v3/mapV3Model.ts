import {midpoint,type MapCamera,type MapClimb,type MapState,type MapStudy,type MapViewer} from '../mapModel';
export type MapCandidate='map-v1'|'map-v2'|'map-v3';
export const readCandidate=(value:string|null):MapCandidate=>value==='map-v1'||value==='map-v2'?value:'map-v3';
// An explicit selection pans at the existing scale. Restoring state never calls this.
export function selectionMove(climb:MapClimb,camera:MapCamera,view:{width:number;height:number;listOpen:boolean}){
 const phone=view.width<600;
 const targetX=phone?view.width/2:view.listOpen?(Math.min(370,view.width*.35)+view.width)/2:view.width*.55;
 const targetY=phone?(72+Math.max(100,view.height-252))/2:view.height*.43;
 return {center:midpoint(climb),zoom:camera.zoom,offset:[targetX-view.width/2,targetY-view.height/2] as [number,number]};
}
export function candidateHref(study:MapStudy,viewer:MapViewer,id:string|null,origin:string|null|undefined,variant:MapCandidate){
 const p=new URLSearchParams({surface:'map',variant,scenario:study.id,viewer});if(origin)p.set('origin',origin);if(id)p.set('climb',id);return `/?${p}`;
}
export const candidateSnapshotKey=(id:string,variant:MapCandidate)=>`br-${variant==='map-v3'?'map-v3':'map-v2'}:${id}`;
export function isCurrentMapMessage(message:unknown,context:{variant:MapCandidate;revision:number;studyId:string}){
 if(!message||typeof message!=='object')return false;
 const m=message as {variant?:unknown;revision?:unknown;snapshot?:{studyId?:unknown}};
 return m.variant===context.variant&&m.revision===context.revision&&m.snapshot?.studyId===context.studyId;
}
export function readCandidateSnapshot(id:string,variant:MapCandidate):unknown{try{return JSON.parse(sessionStorage.getItem(candidateSnapshotKey(id,variant))??'null');}catch{return null;}}
export function saveCandidateSnapshot(state:MapState,variant:MapCandidate){try{sessionStorage.setItem(candidateSnapshotKey(state.studyId,variant),JSON.stringify(state));}catch{/* Active tab retains the snapshot. */}}
export function mapV3ExploreHref(climbId:string,viewer:MapViewer='rider',scenario='wises'){return `/?${new URLSearchParams({surface:'map',variant:'map-v3',scenario,viewer,origin:climbId})}`;}
