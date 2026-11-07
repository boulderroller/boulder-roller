import {useEffect,useRef,useState} from 'react';
import {formatNumber} from '../../../src/lib/formatters';
export type AxisRange={min:number;max:number;ticks:number[]};
/** Strictly above, including an exact rung. The scale is 1, 2, 2.5, 5 × 10^n. */
export function nextStep(value:number):number {
 if(!Number.isFinite(value)||value<0)throw new RangeError('Expected a finite nonnegative peak');
 if(value===0)return 1;
 const magnitude=10**Math.floor(Math.log10(value));
 for(const step of [1,2,2.5,5,10])if(step*magnitude>value*(1+1e-12))return step*magnitude;
 return 20*magnitude;
}
const round=(value:number)=>Number(value.toPrecision(12));
function steps(span:number):number[] {
 const exponent=Math.floor(Math.log10(span));
 return [-2,-1,0,1].flatMap(offset=>[1,2,2.5,5].map(step=>step*10**(exponent+offset)));
}
function ticksInside(min:number,max:number,step:number):number[] {
 const ticks:number[]=[];
 for(let i=Math.ceil(min/step);i<=Math.floor(max/step+1e-12);i++)ticks.push(round(i*step));
 return ticks;
}
export function distanceTicks(length:number):number[] {
 if(!Number.isFinite(length)||length<=0)return [];
 const candidates=steps(length).map(step=>{
  const ticks=ticksInside(0,length,step);
  if(Math.abs(ticks.at(-1)!-length)>1e-9){if(ticks.length>1&&length-ticks.at(-1)!<step*.45)ticks.pop();ticks.push(length);}
  return {step,ticks};
 }).filter(({ticks})=>ticks.length>=4&&ticks.length<=6);
 return candidates.sort((a,b)=>Math.abs(a.ticks.length-6)-Math.abs(b.ticks.length-6)||Math.abs(a.step-length/5)-Math.abs(b.step-length/5))[0].ticks;
}
export function autoRange(kind:'elevation'|'power'|'gap',values:readonly number[]):AxisRange|null {
 const finite=values.filter(Number.isFinite);if(!finite.length)return null;
 if(kind==='elevation'){
  const min=Math.min(...finite),max=Math.max(...finite);
  if(min===max)return {min,max,ticks:Number.isInteger(min)?[min]:[]};
  const choices=steps(max-min).filter(Number.isInteger).map(step=>({step,ticks:ticksInside(min,max,step)}));
  // Whole metres can leave fewer ticks on a small hill. Never invent a step
  // outside the ladder or a rounded label outside the supplied range.
  const ticks=choices.sort((a,b)=>Math.abs(a.ticks.length-5)-Math.abs(b.ticks.length-5)||b.step-a.step)[0]?.ticks??[];
  return {min,max,ticks};
 }
 if(kind==='gap'){const max=nextStep(Math.max(...finite.map(Math.abs)));return {min:-max,max,ticks:[-max,-max/2,0,max/2,max]};}
 const peak=Math.max(0,...finite);
 if(peak===0)return {min:0,max:1,ticks:[0,.2,.4,.6,.8,1]};
 const choices=steps(peak).map(step=>{const max=round((Math.floor(peak/step+1e-12)+1)*step);return {min:0,max,ticks:ticksInside(0,max,step)};}).filter(({ticks})=>ticks.length>=4&&ticks.length<=6);
 return choices.sort((a,b)=>a.max-b.max||Math.abs(a.ticks.length-6)-Math.abs(b.ticks.length-6))[0];
}
export function Axis({range,orientation='horizontal',format=(v)=>formatNumber(v,1),unit}:{range:AxisRange;orientation?:'horizontal'|'vertical';format?:(value:number)=>string;unit?:string}) {
 const ref=useRef<HTMLDivElement>(null),[hidden,setHidden]=useState<number[]>([]);
 const labels=range.ticks.map((value,i)=>`${format(value)}${i===range.ticks.length-1&&unit?` ${unit}`:''}`),signature=labels.join('|');
 useEffect(()=>{
  const element=ref.current!;
  const measure=()=>{
   if(orientation!=='horizontal'){setHidden([]);return;}
   const spans=[...element.querySelectorAll('span')],first=spans[0],last=spans.at(-1);if(!first||!last)return;
   const gap=parseFloat(getComputedStyle(element).getPropertyValue('--v15-space-8')),end=last.getBoundingClientRect().left-gap,omitted:number[]=[];let right=first.getBoundingClientRect().right+gap;
   spans.slice(1,-1).forEach((span,i)=>{const box=span.getBoundingClientRect();if(box.left<right||box.right>end)omitted.push(i+1);else right=box.right+gap;});
   setHidden(previous=>previous.join()===omitted.join()?previous:omitted);
  };
  const observer=new ResizeObserver(measure);observer.observe(element);let active=true;void document.fonts.ready.then(()=>{if(active)measure();});return()=>{active=false;observer.disconnect();};
 },[orientation,signature,range.min,range.max]);
 const percent=(v:number)=>range.max===range.min?50:(v-range.min)/(range.max-range.min)*100;
 return <div ref={ref} className="v15-axis" data-orientation={orientation} aria-hidden="true">{range.ticks.map((value,i)=><span key={value} data-edge={value===range.min?'first':value===range.max?'last':undefined} style={{...(orientation==='horizontal'?{left:`${percent(value)}%`}:{bottom:`${percent(value)}%`}),visibility:hidden.includes(i)?'hidden':undefined}}>{labels[i]}</span>)}</div>;
}
