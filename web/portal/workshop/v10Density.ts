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

export type RelationshipCell={xFrom:number;xTo:number;yFrom:number;yTo:number;seconds:number;selectedSeconds:number;row:number;column:number};
export function cadenceGradientDensity(points:AnalysisSample[],selection?:SampleRange|null) {
 const pairs:{grade:number;cadence:number;seconds:number;selected:boolean}[]=[];
 let minimum=0,maximum=0,cadenceMaximum=0,coveredSeconds=0;
 for(let i=0;i+1<points.length;i++) {
  const p=points[i],seconds=points[i+1].t-p.t;
  if(p.grade==null||p.cadence==null||!Number.isFinite(p.grade)||!Number.isFinite(p.cadence)||p.cadence<0||seconds<=0||seconds>30)continue;
  pairs.push({grade:p.grade,cadence:p.cadence,seconds,selected:!!selection&&p.index>=selection.startIndex&&points[i+1].index<=selection.endIndex});
  minimum=Math.min(minimum,p.grade);maximum=Math.max(maximum,p.grade);cadenceMaximum=Math.max(cadenceMaximum,p.cadence);coveredSeconds+=seconds;
 }
 const xStep=Math.max(1,Math.ceil((maximum-minimum)/60)),yStep=Math.max(5,Math.ceil(cadenceMaximum/63/5)*5),xMin=Math.floor(minimum/xStep)*xStep;
 const columns=Math.floor((maximum-xMin)/xStep)+1,rows=Math.floor(cadenceMaximum/yStep)+1;
 const xMax=xMin+columns*xStep,yMax=rows*yStep;
 const empty={cells:[] as RelationshipCell[],coveredSeconds,xStep,yStep,xMin,xMax,yMax,rows,columns};
 if(![xStep,yStep,xMin,xMax,yMax].every(Number.isFinite)||rows>64||columns>64)return {...empty,status:'unavailable' as const};
 if(!pairs.length)return {...empty,status:'empty' as const};
 const cells=Array.from({length:rows*columns},(_,i)=>{const row=Math.floor(i/columns),column=i%columns;return {row,column,xFrom:xMin+column*xStep,xTo:xMin+(column+1)*xStep,yFrom:row*yStep,yTo:(row+1)*yStep,seconds:0,selectedSeconds:0};});
 for(const p of pairs){const c=cells[Math.floor(p.cadence/yStep)*columns+Math.floor((p.grade-xMin)/xStep)];c.seconds+=p.seconds;if(p.selected)c.selectedSeconds+=p.seconds;}
 return {...empty,cells,status:'ready' as const};
}
export function relationshipDensity(points:AnalysisSample[],selection:SampleRange|null,kind:'power'|'gradient') {
 if(kind==='gradient')return cadenceGradientDensity(points,selection);
 const p=powerCadenceDensity(points,selection);
 return {cells:p.cells.map(c=>({row:c.row,column:c.column,xFrom:c.cadenceFrom,xTo:c.cadenceTo,yFrom:c.powerFrom,yTo:c.powerTo,seconds:c.seconds,selectedSeconds:c.selectedSeconds})),coveredSeconds:p.coveredSeconds,xMin:0,xMax:p.cadenceMax,yMax:p.powerMax,xStep:p.cadenceStep,yStep:p.powerStep,rows:p.rows,columns:p.columns,status:p.status};
}
