import {formatNumber} from '../../../src/lib/formatters';
import {useEffect,useRef,useState} from 'react';
export type ProfilePoint={d:number;elevation:number};
export type GradeBand={from:number;to:number;grade:number;rung:number};
export const gradeRung=(grade:number)=>grade>=12?4:grade>=9?3:grade>=6?2:grade>=3?1:0;
export function elevationAt(points:readonly ProfilePoint[],d:number):number {
 if(!points.length)return NaN;
 if(d<=points[0].d)return points[0].elevation;
 for(let i=1;i<points.length;i++)if(points[i].d>=d){const a=points[i-1],b=points[i];return b.d===a.d?b.elevation:a.elevation+(d-a.d)/(b.d-a.d)*(b.elevation-a.elevation);}
 return points.at(-1)!.elevation;
}
export function gradeBands(points:readonly ProfilePoint[]):GradeBand[] {
 if(points.length<2)return [];
 const start=points[0].d,end=points.at(-1)!.d,bands:GradeBand[]=[];
 const grade=(a:number,b:number)=>(elevationAt(points,b)-elevationAt(points,a))/(b-a)*100;
 for(let from=start;from<end;from+=100){const to=Math.min(from+100,end),value=grade(from,to),rung=gradeRung(value),previous=bands.at(-1);if(previous?.rung===rung){previous.to=to;previous.grade=grade(previous.from,to);}else bands.push({from,to,grade:value,rung});}
 return bands;
}
const label=(value:number)=>`${value<0?'−':''}${formatNumber(Math.abs(value),1,1)}%`;
export function GradeStrip({bands,start,end}:{bands:readonly GradeBand[];start:number;end:number}) {
 const ref=useRef<HTMLDivElement>(null),[width,setWidth]=useState(0);
 useEffect(()=>{const observer=new ResizeObserver(([entry])=>setWidth(entry.contentRect.width));if(ref.current)observer.observe(ref.current);return()=>observer.disconnect();},[]);
 const labelWidth=(text:string)=>[...text].reduce((w,c)=>w+(c==='%'?9:c==='.'?3:c==='−'?5:6.5),0)+6;
 const steepest=bands.reduce<GradeBand|undefined>((best,band)=>!best||band.grade>best.grade?band:best,undefined);
 return <div ref={ref} className="v15-grade-strip" role="img" aria-label={`Grade by section: ${bands.map(b=>label(b.grade)).join(', ')}`}>{bands.map(b=>{const share=(b.to-b.from)/(end-start),text=label(b.grade),available=width*share-1,fit=available>=labelWidth(text)?text:null;return <span key={b.from} data-rung={b.rung} title={text} style={{left:`${(b.from-start)/(end-start)*100}%`,width:`${share*100}%`}}>{fit}</span>;})}{width>0&&steepest&&width*(steepest.to-steepest.from)/(end-start)-1<labelWidth(label(steepest.grade))&&<span className="v15-grade-callout" aria-hidden="true" style={(steepest.to-start)/(end-start)>.5?{right:`${(end-steepest.to)/(end-start)*100}%`}:{left:`${(steepest.from-start)/(end-start)*100}%`}}>{label(steepest.grade)}</span>}</div>;
}
