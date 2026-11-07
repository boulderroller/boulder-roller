import { useId, useMemo } from 'react';
import type { Sample } from './scenario';

/** A compact view of the recorded terrain, shared by destination and place. */
export function V11Relief({points,className='',highlight}:{points:Sample[];className?:string;highlight?:{start:number;end:number}|null}) {
 const clip=useId();
 const extent=points.length?points.at(-1)!.d-points[0].d:0;
 const left=highlight&&extent>0?(highlight.start-points[0].d)/extent*300:0,right=highlight&&extent>0?(highlight.end-points[0].d)/extent*300:0;
 const paths=useMemo(()=>{
  const known=points.filter(p=>p.elevation!==null);if(known.length<2)return [];
  const lo=known.reduce((v,p)=>Math.min(v,p.elevation!),Infinity),hi=known.reduce((v,p)=>Math.max(v,p.elevation!),-Infinity),extent=points.at(-1)!.d-points[0].d;
  const x=(p:Sample)=>extent>0?(p.d-points[0].d)/extent*300:0,y=(p:Sample)=>68-(p.elevation!-lo)/Math.max(15,hi-lo)*54;
  const runs:Sample[][]=[];let run:Sample[]=[];
  points.forEach((p,i)=>{if(p.elevation===null||i>0&&p.t-points[i-1].t>30){if(run.length>1)runs.push(run);run=[];}if(p.elevation!==null)run.push(p);});if(run.length>1)runs.push(run);
  return runs.map(r=>{const edge=r.map((p,i)=>`${i?'L':'M'}${x(p).toFixed(2)},${y(p).toFixed(2)}`).join(' ');return{edge,fill:`${edge} L${x(r.at(-1)!).toFixed(2)},76 L${x(r[0]).toFixed(2)},76 Z`};});
 },[points]);
 return <svg className={`v11-place-relief ${className}`} viewBox="0 0 300 80" preserveAspectRatio="none" aria-hidden="true"><defs><clipPath id={clip}><rect x={left} width={Math.max(0,right-left)} y={0} height={80}/></clipPath></defs>{paths.map((p,i)=><g key={i}><path className="v11-place-relief-fill" d={p.fill}/><path className="v11-place-relief-edge" d={p.edge}/></g>)}{highlight&&<g clipPath={`url(#${clip})`} className="v11-place-relief-highlight">{paths.map((p,i)=><g key={i}><path d={p.fill} fill="#b4c895"/><path d={p.edge} fill="none" stroke="#587444" vectorEffect="non-scaling-stroke" strokeWidth={1.5}/></g>)}</g>}</svg>;
}
