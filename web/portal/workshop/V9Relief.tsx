import { useMemo } from 'react';
import type { Sample } from './scenario';

/** A compact view of the recorded terrain, shared by destination and place. */
export function V9Relief({points,className=''}:{points:Sample[];className?:string}) {
 const paths=useMemo(()=>{
  const known=points.filter(p=>p.elevation!==null);if(known.length<2)return [];
  const lo=known.reduce((v,p)=>Math.min(v,p.elevation!),Infinity),hi=known.reduce((v,p)=>Math.max(v,p.elevation!),-Infinity),extent=points.at(-1)!.d-points[0].d;
  const x=(p:Sample)=>extent>0?(p.d-points[0].d)/extent*300:0,y=(p:Sample)=>68-(p.elevation!-lo)/Math.max(15,hi-lo)*54;
  const runs:Sample[][]=[];let run:Sample[]=[];
  points.forEach((p,i)=>{if(p.elevation===null||i>0&&p.t-points[i-1].t>30){if(run.length>1)runs.push(run);run=[];}if(p.elevation!==null)run.push(p);});if(run.length>1)runs.push(run);
  return runs.map(r=>{const edge=r.map((p,i)=>`${i?'L':'M'}${x(p).toFixed(2)},${y(p).toFixed(2)}`).join(' ');return{edge,fill:`${edge} L${x(r.at(-1)!).toFixed(2)},76 L${x(r[0]).toFixed(2)},76 Z`};});
 },[points]);
 return <svg className={`v9-place-relief ${className}`} viewBox="0 0 300 80" preserveAspectRatio="none" aria-hidden="true">{paths.map((p,i)=><g key={i}><path className="v9-place-relief-fill" d={p.fill}/><path className="v9-place-relief-edge" d={p.edge}/></g>)}</svg>;
}
