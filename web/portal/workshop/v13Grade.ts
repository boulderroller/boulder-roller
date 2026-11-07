import type { Sample } from './scenario';

/** Selected terrain uses signed net rise, never the sum of uphill samples.
 * Match the existing grade trace's 50 m minimum and 30 s continuity boundary. */
export function selectedAverageGrade(points: readonly Sample[]): number | null {
 if(points.length<2)return null;
 const first=points[0],last=points.at(-1)!,distance=last.d-first.d;
 if(!Number.isFinite(distance)||distance<50)return null;
 for(let i=0;i<points.length;i++){
  const point=points[i];
  if(point.elevation===null||!Number.isFinite(point.elevation)||!Number.isFinite(point.d)||!Number.isFinite(point.t))return null;
  if(i>0){const previous=points[i-1],dt=point.t-previous.t;if(dt<=0||dt>30||point.d<previous.d)return null;}
 }
 return (last.elevation!-first.elevation!)/distance*100;
}
export function gradeLabel(grade:number|null):string {
 if(grade===null)return '—';
 const rounded=Math.round(Math.abs(grade)*10)/10;
 return `${rounded===0?'':grade>0?'+':'−'}${rounded.toFixed(1)}`;
}
