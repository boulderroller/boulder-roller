/** Generation-aware return paths; retained candidates keep their original URLs. */
const modernOrigin=(query:URLSearchParams)=>['climb-v3','climb-v4','climb-v5','climb-v6','climb-v7','climb-v8','climb-v9','climb-v10','climb-v11','climb-v12','climb-v13','climb-v14','climb-v15','climb-v16'].includes(query.get('climbOriginVariant')??'');
export function climbReturnHref(query:URLSearchParams):string|null {
 const id=query.get('climbOrigin');if(!id)return null;
 const viewer=query.get('climbOriginViewer');
 return `/?${new URLSearchParams({surface:'climb',variant:modernOrigin(query)?query.get('climbOriginVariant')!:'climb-v2',scenario:id,viewer:viewer==='rider'||viewer==='signed-out'?viewer:'visitor'})}`;
}
export function climbV3EffortHref(href:string):string {
 const p=new URLSearchParams(href.slice(2));p.set('view','analysis');p.set('climbOriginVariant','climb-v3');if(p.get('climb'))p.set('climbOriginId',p.get('climb')!);return `/?${p}`;
}
export function carryClimbOrigin(href:string,origin:URLSearchParams):string {
 if(!modernOrigin(origin)||!origin.get('climbOrigin'))return href;
 const p=new URLSearchParams(href.slice(2));
 for(const key of ['climbOrigin','climbOriginViewer','climbOriginVariant','climbOriginId']){const value=origin.get(key);if(value)p.set(key,value);}
 if(origin.get('climbOriginViewer')!=='rider'||origin.get('viewer')!=='owner')p.set('viewer','visitor');
 return `/?${p}`;
}
/** Imported siblings must stay with their supplied ride context, never a same-ID fixture. */
export function climbV3Destination(id:string,origin:URLSearchParams,studies:readonly {id:string;climbId:string}[]):string|null {
 const back=climbReturnHref(origin);
 if(!back||!modernOrigin(origin))return null;
 if(origin.get('climbOriginId')===id)return back;
 if(origin.get('climbOrigin')?.startsWith('climb-import-'))return null;
 const study=studies.find(s=>s.climbId===id);if(!study)return null;
 const p=new URLSearchParams(back.slice(2));p.set('scenario',study.id);return `/?${p}`;
}
