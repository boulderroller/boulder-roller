import type { AnalysisSample, SampleRange } from './v3Model';

export type DensityCell = { powerFrom: number; powerTo: number; cadenceFrom: number; cadenceTo: number; seconds: number; selectedSeconds: number; row: number; column: number };
export function powerCadenceDensity(points: AnalysisSample[], selection?: SampleRange | null) {
 const intervals: { power: number; cadence: number; seconds: number; selected: boolean }[]=[];
 let powerMaximum=0, cadenceMaximum=0, coveredSeconds=0;
 for(let i=0;i+1<points.length;i++) {
  const {power,cadence}=points[i], seconds=points[i+1].t-points[i].t;
  if(power==null||cadence==null||!Number.isFinite(power)||!Number.isFinite(cadence)||power<0||cadence<0||seconds<=0||seconds>30) continue;
  intervals.push({power,cadence,seconds,selected:!!selection && points[i].index>=selection.startIndex && points[i+1].index<=selection.endIndex}); coveredSeconds+=seconds;
  powerMaximum=Math.max(powerMaximum,power); cadenceMaximum=Math.max(cadenceMaximum,cadence);
 }
 const powerStep=Math.max(25,Math.ceil(powerMaximum/63/25)*25), cadenceStep=Math.max(5,Math.ceil(cadenceMaximum/63/5)*5);
 const rows=Math.floor(powerMaximum/powerStep)+1, columns=Math.floor(cadenceMaximum/cadenceStep)+1;
 const powerMax=rows*powerStep, cadenceMax=columns*cadenceStep;
 if(!Number.isFinite(powerMax)||!Number.isFinite(cadenceMax)||rows>64||columns>64) return {cells:[] as DensityCell[],coveredSeconds,powerStep,cadenceStep,powerMax:0,cadenceMax:0,rows:0,columns:0,status:'unavailable' as const};
 if(!intervals.length) return {cells:[] as DensityCell[],coveredSeconds:0,powerStep,cadenceStep,powerMax,cadenceMax,rows,columns,status:'empty' as const};
 const cells=Array.from({length:rows*columns},(_,i)=>{const row=Math.floor(i/columns),column=i%columns;return {row,column,powerFrom:row*powerStep,powerTo:(row+1)*powerStep,cadenceFrom:column*cadenceStep,cadenceTo:(column+1)*cadenceStep,seconds:0,selectedSeconds:0};});
 for(const p of intervals) {const cell=cells[Math.floor(p.power/powerStep)*columns+Math.floor(p.cadence/cadenceStep)];cell.seconds+=p.seconds;if(p.selected)cell.selectedSeconds+=p.seconds;}
 return {cells,coveredSeconds,powerStep,cadenceStep,powerMax,cadenceMax,rows,columns,status:'ready' as const};
}
