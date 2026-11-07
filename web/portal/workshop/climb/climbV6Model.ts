import {preciseTime} from './climbV5Model';
export function resultTime(seconds:number, precise=false){
 const value=preciseTime(seconds);
 return precise?value:value.replace(/\.0$/, '');
}
// All rows share one zero, using the same rounded tenths as the printed gaps.
export function gapScale(durations:number[], reference:number){
 const deltas=durations.map(t=>Math.round(t*10)-Math.round(reference*10));
 const min=Math.min(0,...deltas),max=Math.max(0,...deltas),span=max-min;
 const zero=span?Math.abs(min)/span*100:50;
 return {zero,bar:(duration:number)=>{
  const delta=Math.round(duration*10)-Math.round(reference*10);
  const point=span?(delta-min)/span*100:50;
  return {left:Math.min(zero,point),width:Math.abs(point-zero)};
 }};
}
