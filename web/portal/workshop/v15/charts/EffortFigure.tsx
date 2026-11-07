import {useId,type ReactNode} from 'react';
import {Axis,autoRange,distanceTicks,type AxisRange} from './Axis';
import {GradeStrip,type GradeBand} from './GradeStrip';
import {ReadoutGrid,type Readout} from '../Analysis';
import {formatNumber} from '../../../src/lib/formatters';

/** Gate-local, generated samples. The figure only positions values; it does not calculate effort metrics. */
export type EffortPoint={elapsed_s:number;distance_m:number;elevation_m:number;grade_pct:number;power_5s_w?:number;speed_kmh?:number;cadence_rpm?:number;torque_nm?:number;hr_bpm?:number};
export type ComparisonPoint={power_w?:number;gap_s:number};
export function cursorStep(points:readonly EffortPoint[],index:number,key:string,shift=false):number{
 if(key==='Home')return 0;if(key==='End')return points.length-1;
 const direction=key==='ArrowRight'||key==='ArrowUp'?1:key==='ArrowLeft'||key==='ArrowDown'?-1:0;
 const target=Math.max(0,Math.min(points.at(-1)!.elapsed_s,points[index].elapsed_s+direction*(shift?10:1)));
 return points.reduce((best,p,i)=>Math.abs(p.elapsed_s-target)<Math.abs(points[best].elapsed_s-target)?i:best,0);
}
export function EffortFigure({points,bands,index,onIndex,comparison,comparisonLabel,average,highlight,readouts,stops}:{points:readonly EffortPoint[];bands:readonly GradeBand[];index:number;onIndex:(index:number)=>void;comparison?:readonly ComparisonPoint[];comparisonLabel?:ReactNode;average?:number;highlight?:readonly [number,number];readouts:readonly Readout[];stops?:readonly {start_m?:number;end_m?:number;label:ReactNode}[]}){
 const id=useId(),length=points.at(-1)!.distance_m,active=points[index],x=(d:number)=>d/length*1000;
 const power=autoRange('power',[...(average===undefined?[]:[average]),...points.flatMap(p=>p.power_5s_w===undefined?[]:[p.power_5s_w]),...(comparison??[]).flatMap(p=>p.power_w===undefined?[]:[p.power_w])]);
 const elevation=autoRange('elevation',points.map(p=>p.elevation_m))!,gap=comparison?autoRange('gap',comparison.map(p=>p.gap_s)):null;
 const y=(v:number,r:AxisRange)=>r.max===r.min?50:100-(v-r.min)/(r.max-r.min)*100;
 const path=(values:readonly (number|undefined)[],range:AxisRange)=>{let drawing=false;return values.map((v,i)=>{if(v===undefined){drawing=false;return '';}const command=drawing?'L':'M';drawing=true;return `${command}${x(points[i].distance_m)} ${y(v,range)}`;}).join(' ');};
 const cursor=<path className="v15-figure-cursor" d={`M${x(active.distance_m)} 0V100`} vectorEffect="non-scaling-stroke"/>;
 const selection=highlight?<rect className="v15-figure-selection" x={x(highlight[0])} y={0} width={x(highlight[1]-highlight[0])} height={100}/>:null;
 const grid=(range:AxisRange)=><path className="v15-figure-grid" d={range.ticks.map(t=>`M0 ${y(t,range)}H1000`).join(' ')} vectorEffect="non-scaling-stroke"/>;
 const pointer=(event:React.PointerEvent<Element>)=>{const box=event.currentTarget.getBoundingClientRect(),distance=Math.max(0,Math.min(length,(event.clientX-box.left)/box.width*length));onIndex(points.reduce((best,p,i)=>Math.abs(p.distance_m-distance)<Math.abs(points[best].distance_m-distance)?i:best,0));};
 const interaction={onPointerMove:pointer,onPointerDown:(event:React.PointerEvent<Element>)=>{event.currentTarget.closest<HTMLElement>('[role=slider]')?.focus({preventScroll:true});event.currentTarget.setPointerCapture(event.pointerId);pointer(event);}};
 const stopBands=stops?.filter(s=>s.start_m!==undefined&&s.end_m!==undefined).map((s,i)=><rect key={i} className="v15-figure-stop" x={x(s.start_m!)} y={0} width={Math.max(1,x(s.end_m!-s.start_m!))} height={100} vectorEffect="non-scaling-stroke"/>);
 const elevationPath=path(points.map(p=>p.elevation_m),elevation);
 return <div className="v15-effort-figure"><div className="v15-figure-legend">{power&&<span><i data-series="power"/>Power, 5 s</span>}{comparison&&<span><i data-series="comparison"/>{comparisonLabel}</span>}{average!==undefined&&<span><i data-series="average"/>{formatNumber(average)} W average</span>}<span>Elevation</span>{!!stops?.length&&<span><i data-series="stop"/>Stopped · locations below</span>}</div>
  <div className="v15-figure-interactive" role="slider" tabIndex={0} aria-label="Effort cursor" aria-describedby={id} aria-valuemin={0} aria-valuemax={points.at(-1)!.elapsed_s} aria-valuenow={active.elapsed_s} aria-valuetext={`${formatNumber(active.elapsed_s,1)} seconds, ${formatNumber(active.distance_m)} metres${active.power_5s_w===undefined?'':`, ${formatNumber(active.power_5s_w)} watts`}`} onKeyDown={event=>{if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(event.key)){event.preventDefault();onIndex(cursorStep(points,index,event.key,event.shiftKey));}}}>
   {power&&<div className="v15-figure-plot" data-plot="power"><Axis range={power} orientation="vertical" unit="W" format={v=>formatNumber(v)}/><svg viewBox="0 0 1000 100" preserveAspectRatio="none" aria-hidden="true" {...interaction}>{grid(power)}{selection}{stopBands}{average!==undefined&&<path className="v15-figure-average" d={`M0 ${y(average,power)}H1000`} vectorEffect="non-scaling-stroke"/>}{comparison&&<path className="v15-figure-comparison" d={path(comparison.map(p=>p.power_w),power)} vectorEffect="non-scaling-stroke"/>}<path className="v15-figure-power" d={path(points.map(p=>p.power_5s_w),power)} vectorEffect="non-scaling-stroke"/>{cursor}</svg></div>}
   <div className="v15-figure-plot" data-plot="elevation"><Axis range={elevation} orientation="vertical" unit="m" format={v=>formatNumber(v)}/><svg viewBox="0 0 1000 100" preserveAspectRatio="none" aria-hidden="true" {...interaction}>{grid(elevation)}<path className="v15-figure-elevation" d={`${elevationPath}L1000 100L0 100Z`}/>{selection}{stopBands}{cursor}</svg></div>
   <div className="v15-figure-grade" {...interaction}><GradeStrip bands={bands} start={0} end={length}/><div className="v15-grade-cursor" style={{left:`${active.distance_m/length*100}%`}}/></div>
   {gap&&comparison&&<><p className="v15-figure-gap-label">Gap to {comparisonLabel} · behind ↑ · ahead ↓</p><div className="v15-figure-plot" data-plot="gap"><Axis range={gap} orientation="vertical" unit="s" format={v=>`${v>0?'+':''}${formatNumber(v).replace('-','−')}`} /><svg viewBox="0 0 1000 100" preserveAspectRatio="none" aria-hidden="true" {...interaction}>{grid(gap)}{selection}<path className="v15-figure-comparison" d={path(comparison.map(p=>p.gap_s),gap)} vectorEffect="non-scaling-stroke"/>{cursor}</svg><span className="v15-gap-value" aria-label="Gap at finish" style={{top:`${Math.max(12,Math.min(88,y(comparison.at(-1)!.gap_s,gap)))}%`}}>{comparison.at(-1)!.gap_s<0?'−':comparison.at(-1)!.gap_s>0?'+':''}{formatNumber(Math.abs(comparison.at(-1)!.gap_s),1,1)} s</span></div></>}
   <div className="v15-figure-distance"><Axis range={{min:0,max:length,ticks:distanceTicks(length)}} unit="km" format={d=>formatNumber(d/1000,2)}/></div>
  </div>
  {stops?.length? <div className="v15-figure-stops">{stops.map((s,i)=><div key={i}>{s.label}</div>)}</div>:null}
  <div id={id}><ReadoutGrid items={readouts}/></div>
 </div>;
}
