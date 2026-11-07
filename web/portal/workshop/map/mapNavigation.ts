import {initialMapState,restoreMapState,type MapStudy,type MapState,type MapViewer} from './mapModel';
export function mapExploreHref(climbId:string,viewer:MapViewer='rider',scenario='wises'){
 const p=new URLSearchParams({surface:'map',variant:'map-v2',scenario,viewer,origin:climbId});return `/?${p}`;
}
export function mapDetailHref(study:MapStudy,viewer:MapViewer,id:string|null,originId?:string|null){const p=new URLSearchParams({surface:'map',variant:'map-v2',scenario:study.id,viewer});if(originId)p.set('origin',originId);if(id)p.set('climb',id);return `/?${p}`;}
export function stateFromQuery(study:MapStudy,p:URLSearchParams,saved?:unknown):MapState{
 const s=restoreMapState(study,saved??initialMapState(study));
 const origin=p.get('origin');if(origin){const matches=study.climbs.filter(c=>c.id===origin||c.id.split('-')[0]===origin);if(matches.length===1){if(s.originId!==matches[0].id){s.camera=null;s.area=null;s.query='';s.scrollTop=0;s.selectedId=matches[0].id;}s.originId=matches[0].id;s.missingOriginId=undefined;}else{s.originId=null;s.selectedId=null;s.camera=null;s.area=null;s.query='';s.scrollTop=0;s.missingOriginId=origin.slice(0,200);s.sheetExpanded=true;}}
 const detail=p.get('climb');s.detailId=detail&&study.climbs.some(c=>c.id===detail)?detail:null;return s;
}
export const mapSnapshotKey=(id:string)=>`br-map-v2:${id}`;
export function saveMapSnapshot(s:MapState){try{sessionStorage.setItem(mapSnapshotKey(s.studyId),JSON.stringify(s));}catch{/* The active window retains state when storage is full. */}}
export function readMapSnapshot(id:string):unknown{try{return JSON.parse(sessionStorage.getItem(mapSnapshotKey(id))??'null');}catch{return null;}}
export const readViewer=(value:string|null):MapViewer=>value==='visitor'||value==='signed-out'?value:'rider';
