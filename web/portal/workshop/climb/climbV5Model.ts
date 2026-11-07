import {inspectClimb} from './climbModel';

export type ClimbInspection = ReturnType<typeof inspectClimb>;
export type HistoryEffort = NonNullable<ClimbInspection['personal']>['rows'][number] & {id:string};
export type BoardEffort = NonNullable<ClimbInspection['board']>['rows'][number];

// A calendar date is not a midnight UTC instant in the rider's timezone.
export function effortDate(value:string, short=false){
 const calendar=/^\d{4}-\d{2}-\d{2}$/.test(value);
 return new Date(value).toLocaleDateString('en-US',{month:'short',day:'numeric',...(short?{}:{year:'numeric'}),timeZone:calendar?'UTC':'America/New_York'});
}
export function preciseTime(seconds:number){
 const tenths=Math.round(seconds*10),minutes=Math.floor(tenths/600);
 return `${minutes}:${(Math.floor(tenths/10)%60).toString().padStart(2,'0')}.${tenths%10}`;
}
export function timeGap(seconds:number, reference:number){
 const tenths=Math.round(seconds*10)-Math.round(reference*10);
 return tenths===0?'0.0':`${tenths<0?'−':'+'}${(Math.abs(tenths)/10).toFixed(1)}`;
}
export function historyEfforts(personal:NonNullable<ClimbInspection['personal']>):HistoryEffort[]{
 return personal.rows.map((row,index)=>({...row,id:`effort-${index}`})).sort((a,b)=>Date.parse(a.date)-Date.parse(b.date));
}
export function historyDomain(rows:HistoryEffort[]){
 const dates=rows.map(r=>Date.parse(r.date)),times=rows.map(r=>r.duration);
 const lo=Math.min(...times),hi=Math.max(...times),step=Math.max(5,Math.ceil((hi-lo)/4/5)*5);
 const min=Math.max(0,Math.floor(lo/step)*step-step),max=Math.ceil(hi/step)*step+step;
 const start=Math.min(...dates),end=Math.max(...dates);
 return {min,max,start,end,step};
}
export function toggleHistorySelection(selected:string[],id:string){
 if(selected.includes(id))return selected.filter(value=>value!==id);
 return selected.length<2?[...selected,id]:[selected[0],id];
}
