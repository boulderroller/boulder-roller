/** Field-sized Borsh spans permit erasure without destroying adjacent riders. */
import { createHash } from 'crypto';
import { loadIdl } from './decoder';
import { digest } from './stage1';
export function accountParts(type:string,raw:Buffer):{parts:any[];parts_digest:string} {
  const idl=loadIdl(),definitions=Object.fromEntries([...idl.accounts,...(idl.types??[])].map((a:any)=>[a.name,a.type]));
  const parts:any[]=[];let offset=0;
  const take=(length:number,path:string[],kind:string):Buffer=>{
    if(length<0||offset+length>raw.length)throw new Error('Truncated source span');
    const data=raw.subarray(offset,offset+length);
    parts.push({path,kind,offset,length,digest:createHash('sha256').update(data).digest('hex'),data:data.toString('base64')});offset+=length;return data;
  };
  const walk=(t:any,path:string[])=>{
    if(typeof t==='string') {
      if(t==='publicKey'){take(32,path,t);return;}
      if(t==='bool'){take(1,path,t);return;}
      if(/^[ui]\d+$/.test(t)){take(Number(t.slice(1))/8,path,t);return;}
      if(t==='bytes'||t==='string'){const n=take(4,[...path,'$length'],'u32').readUInt32LE();take(n,path,t);return;}
      throw new Error('Unsupported source scalar');
    }
    if(t.array){if(t.array[0]==='u8'){take(t.array[1],path,'u8array');return;}for(let i=0;i<t.array[1];i++)walk(t.array[0],[...path,String(i)]);return;}
    if(t.vec){const n=take(4,[...path,'$length'],'u32').readUInt32LE();if(n>65536)throw new Error('Unbounded source vector');for(let i=0;i<n;i++)walk(t.vec,[...path,String(i)]);return;}
    if(t.option){if(take(1,[...path,'$option'],'u8')[0])walk(t.option,path);return;}
    if(t.defined){walk(definitions[t.defined],path);return;}
    if(t.kind==='struct'){for(const f of t.fields)walk(f.type,[...path,f.name]);return;}
    if(t.kind==='enum'){const v=t.variants[take(1,[...path,'$variant'],'u8')[0]];if(v.fields?.length)throw new Error('Unsupported source enum');return;}
    throw new Error('Unsupported source type');
  };
  take(8,['$discriminator'],'bytes');
  let definition=definitions[type];
  if(type==='LocalLegend'&&raw.length===122)definition={...definition,fields:definition.fields.filter((f:any)=>f.name!=='isBootstrap')};
  walk(definition,[]);if(offset<raw.length){take(raw.length-offset,['$padding'],'bytes');delete parts[parts.length-1].data;parts[parts.length-1].discarded=true;}
  return {parts,parts_digest:digest(parts.map(({data,discarded,...p})=>p))};
}
