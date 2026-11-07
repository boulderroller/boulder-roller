import canonical from './data/philadelphia.json';
import {parseMapStudy, type MapStudy} from './mapModel';
export const wisesStudy=parseMapStudy(canonical);
export const mapStudies:MapStudy[]=[wisesStudy,
 {...wisesStudy,id:'area',label:'Philadelphia · supplied climbs',originId:undefined},
 {...wisesStudy,id:'valley-green',label:'Valley Green Road · arriving from a climb',originId:'8582724d-5ad5-43ae-a88f-7759b9e7ed61'},
 {...wisesStudy,id:'bounds-only',label:'Bounds only · no route lines',source:wisesStudy.source+' Route geometry and profiles intentionally omitted to exercise the list-response boundary.',climbs:wisesStudy.climbs.map(({geometry,geometrySource,profile,...c})=>({...c,source:c.source+' Bounds-only workshop projection.'}))},
 {...wisesStudy,id:'mixed-geography',label:'Mixed geometry · Wises route and nearby markers',source:wisesStudy.source+' Only the Wises centerline is included; neighboring climbs retain bounds.',climbs:wisesStudy.climbs.map(c=>c.id===wisesStudy.originId?c:(({geometry,geometrySource,profile,...rest})=>rest)(c))},
 {version:1,id:'no-climbs',label:'Empty supplied area',source:'Empty Map scenario; no geographic coverage is asserted.',climbs:[]}
];
export const mapImports=new Map<string,MapStudy>();
export function mapStudyById(id:string|null):MapStudy|undefined {const found=mapImports.get(id??'')??mapStudies.find(s=>s.id===id);if(found)return found;if(id?.startsWith('map-import-')&&typeof sessionStorage!=='undefined'){try{const raw=sessionStorage.getItem(`br-map-import:${id}`);if(raw){const s=parseMapStudy(JSON.parse(raw));if(s.id===id){mapImports.set(id,s);return s;}}}catch{/* Missing or invalid imports require explicit recovery. */}}return undefined;}
