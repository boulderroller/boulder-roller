import type {ComponentType} from 'react';

type KitRoute={preview:string;variant?:string;title:string;load:()=>Promise<ComponentType>};
// Add each new kit candidate here with its usual room preview flag and variant.
// Dispatch happens before loading any styles; main.tsx keeps its own CSS imports.
export const kitRoutes:readonly KitRoute[]=[
 {preview:'kit-preview',title:'V15 kit',load:()=>import('./v15/KitSpecimen').then(module=>module.KitPreview)},
 {preview:'effort-preview',title:'Effort V1',load:()=>import('./effort/EffortView').then(module=>module.EffortPreview)},
 {preview:'climb-preview',variant:'climb-v17',title:'Climb V17',load:()=>import('./climb/ClimbV17').then(module=>module.ClimbV17Preview)},
];
export function kitRoute(search:string,routes:readonly KitRoute[]=kitRoutes){
 const params=new URLSearchParams(search);
 return routes.find(route=>params.has(route.preview)&&(!route.variant||params.get('variant')===route.variant));
}
if(typeof window!=='undefined')void(async()=>{
 const route=kitRoute(location.search);
 if(!route){await import('./main');if(new URLSearchParams(location.search).get('effort-links')==='1')await import('./effort/legacyLinks');return;}
 const [{createRoot},{createElement},Preview]=await Promise.all([import('react-dom/client'),import('react'),route.load()]);
 document.body.style.margin='0';document.title=`${route.title} · Boulder Roller`;
 createRoot(document.getElementById('root')!).render(createElement(Preview));
})();
