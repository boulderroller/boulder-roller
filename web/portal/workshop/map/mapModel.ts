export type Point = [number, number];
export type Bounds = [number, number, number, number];
export type MapViewer = 'rider' | 'visitor' | 'signed-out';
export type MapLoadState = 'ready' | 'loading' | 'empty' | 'error' | 'map-error';
export type MapClimb = {
  id: string; name: string; locality?: string; lengthM: number; riseM: number; gradePct: number;
  bounds: Bounds; source: string; revision?: string;
  geometry?: {type: 'LineString'; coordinates: Point[]}; geometrySource?: 'canon_centerline';
  profile?: {distanceM: number; elevationM: number}[];
  standing?: {viewerId: string; name: string; rank: number; timeSeconds: number; source: string};
};
export type MapStudy = {version: 1; id: string; label: string; source: string; publishedAt?: string; sourceUrl?: string; attribution?: string[]; climbs: MapClimb[]; originId?: string; viewer?: {id: string; name: string; portrait?: string}};
export type MapCamera = {center: Point; zoom: number};
export type MapState = {studyId: string; originId: string|null; missingOriginId?: string; selectedId: string|null; detailId: string|null; camera: MapCamera|null; area: Bounds|null; query: string; sort: 'name'|'rise'|'grade'|'distance'; sheetExpanded: boolean; scrollTop: number};
function check(ok: unknown, message: string): asserts ok {if(!ok)throw Error(message);}
const finite = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n);
export const validPoint = (p: unknown): p is Point => Array.isArray(p) && p.length===2 && finite(p[0]) && Math.abs(p[0])<=180 && finite(p[1]) && Math.abs(p[1])<=85;
export const validBounds = (b: unknown): b is Bounds => Array.isArray(b)&&b.length===4&&validPoint([b[0],b[1]])&&validPoint([b[2],b[3]])&&b[0]<=b[2]&&b[1]<=b[3];
export const validCamera = (c: unknown): c is MapCamera => !!c && typeof c==='object' && validPoint((c as MapCamera).center) && finite((c as MapCamera).zoom) && (c as MapCamera).zoom>=3 && (c as MapCamera).zoom<=19;
const text = (s: unknown, max=600): s is string => typeof s==='string' && s.trim().length>0 && s.length<=max;
export const midpoint = (c: MapClimb): Point => [(c.bounds[0]+c.bounds[2])/2,(c.bounds[1]+c.bounds[3])/2];
export const intersects = (a:Bounds,b:Bounds) => a[0]<=b[2]&&a[2]>=b[0]&&a[1]<=b[3]&&a[3]>=b[1];
export function parseMapStudy(input: unknown): MapStudy {
 check(input&&typeof input==='object','Choose an exported Map scenario.');
 const s=structuredClone(input) as MapStudy;
 check(s.version===1&&text(s.id,200)&&text(s.label,300)&&text(s.source,2000),'Include Map identity and source.');
 check(Array.isArray(s.climbs)&&s.climbs.length<=1000,'Supply at most 1,000 climbs.');
 check(new Set(s.climbs.map(c=>c.id)).size===s.climbs.length,'Climb IDs must be unique.');
 if(s.attribution)check(Array.isArray(s.attribution)&&s.attribution.length<=10&&s.attribution.every(a=>text(a)),'Include valid source attribution.');
 if(s.sourceUrl)check(/^https:\/\//.test(s.sourceUrl),'Source links must use HTTPS.');
 if(s.viewer){check(text(s.viewer.id,200)&&text(s.viewer.name),'Include viewer identity.');if(s.viewer.portrait)check(/^https:\/\//.test(s.viewer.portrait),'Portrait links must use HTTPS.');}
 for(const c of s.climbs){
  check(text(c.id,200)&&text(c.name)&&text(c.source,2000)&&validBounds(c.bounds),'Include climb identity, source and valid bounds.');
  check(finite(c.lengthM)&&c.lengthM>0&&finite(c.riseM)&&c.riseM>=0&&finite(c.gradePct),'Include supplied climb measurements.');
  if(c.locality)check(text(c.locality),'Include a supplied locality.');
  if(c.geometry){check(c.geometrySource==='canon_centerline','Routes require an explicit canonical geometry source.');check(c.geometry.type==='LineString'&&Array.isArray(c.geometry.coordinates)&&c.geometry.coordinates.length>=2&&c.geometry.coordinates.length<=100000,'Include a complete canonical line.');check(c.geometry.coordinates.every(p=>validPoint(p)&&p[0]>=c.bounds[0]-1e-6&&p[0]<=c.bounds[2]+1e-6&&p[1]>=c.bounds[1]-1e-6&&p[1]<=c.bounds[3]+1e-6),'Invalid route coordinate or bounds.');}
  if(c.profile){check(Array.isArray(c.profile)&&c.profile.length>=2&&c.profile.length<=100000&&c.profile.every((p,i)=>finite(p.distanceM)&&finite(p.elevationM)&&(i===0?p.distanceM===0:p.distanceM>c.profile![i-1].distanceM))&&Math.abs(c.profile.at(-1)!.distanceM-c.lengthM)<.1,'Profile must cover the supplied climb distance.');}
  if(c.standing){const r=c.standing;check(!!s.viewer&&r.viewerId===s.viewer.id&&r.name===s.viewer.name&&text(r.source)&&Number.isInteger(r.rank)&&r.rank>=1&&r.rank<=50&&finite(r.timeSeconds)&&r.timeSeconds>0,'Standing must be sourced and bound to the supplied viewer.');}
 }
 if(s.originId)check(s.climbs.some(c=>c.id===s.originId),'The origin must be a supplied climb.');
 return s;
}
export function importMapStudy(input:unknown,key:string){const s=parseMapStudy(input);s.id=`map-import-${key}`;return s;}
export const mapLines = (s:MapStudy)=>s.climbs.filter(c=>c.geometry&&c.geometrySource==='canon_centerline');
export const initialMapState = (s:MapStudy):MapState=>({studyId:s.id,originId:s.originId??null,selectedId:s.originId??null,detailId:null,camera:null,area:null,query:'',sort:'name',sheetExpanded:s.climbs.length===0,scrollTop:0});
export function restoreMapState(study:MapStudy,raw:unknown):MapState{
 const base=initialMapState(study);if(!raw||typeof raw!=='object')return base;const s=raw as Partial<MapState>;
 if(s.studyId!==study.id)return base;
 const id=(v:unknown)=>typeof v==='string'&&study.climbs.some(c=>c.id===v)?v:null;
 return {...base,missingOriginId:typeof s.missingOriginId==='string'?s.missingOriginId.slice(0,200):undefined,originId:id(s.originId),selectedId:id(s.selectedId),detailId:id(s.detailId),camera:validCamera(s.camera)?s.camera:null,area:validBounds(s.area)?s.area:null,query:typeof s.query==='string'?s.query.slice(0,200):'',sort:['name','rise','grade','distance'].includes(s.sort??'')?s.sort!:base.sort,sheetExpanded:s.sheetExpanded===true,scrollTop:finite(s.scrollTop)?Math.max(0,s.scrollTop):0};
}
export const selectClimb=(s:MapState,id:string):MapState=>({...s,selectedId:id});
export const clearClimb=(s:MapState):MapState=>({...s,selectedId:null});
export const openClimb=(s:MapState,id:string):MapState=>({...s,detailId:id});
export const closeClimb=(s:MapState):MapState=>({...s,detailId:null});
export function surroundingBounds(study:MapStudy):Bounds{
 const origin=study.climbs.find(c=>c.id===study.originId)??study.climbs[0];if(!origin)return [-75.26,40.03,-75.19,40.075];
 const a=midpoint(origin),dist=(c:MapClimb)=>{const b=midpoint(c);return Math.hypot((a[0]-b[0])*Math.cos(a[1]*Math.PI/180),a[1]-b[1]);};
 const nearby=study.originId?[...study.climbs].filter(c=>dist(c)<.035).sort((a,b)=>dist(a)-dist(b)).slice(0,7):study.climbs;
 return [Math.min(...nearby.map(c=>c.bounds[0])),Math.min(...nearby.map(c=>c.bounds[1])),Math.max(...nearby.map(c=>c.bounds[2])),Math.max(...nearby.map(c=>c.bounds[3]))];
}
export function visibleClimbs(study:MapStudy,state:MapState){
 const q=state.query.trim().toLocaleLowerCase(),result=study.climbs.filter(c=>(!q||c.name.toLocaleLowerCase().includes(q))&&(!state.area||intersects(c.bounds,state.area)));
 return result.sort((a,b)=>state.sort==='name'?a.name.localeCompare(b.name):state.sort==='rise'?b.riseM-a.riseM:state.sort==='grade'?b.gradePct-a.gradePct:b.lengthM-a.lengthM);
}
