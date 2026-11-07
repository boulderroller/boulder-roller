import { useEffect, useMemo, useRef, useState, type PointerEvent } from 'react';
import { relationshipDensity } from './v11Density';
import { rangeForClimb, type AnalysisSample } from './v3Model';
import { timeLabel, type Scenario } from './scenario';

type Rect={x0:number;x1:number;y0:number;y1:number};
type CellPoint={x:number;y:number};
function ticks(low:number,high:number) {
 const raw=(high-low)/5, magnitude=10**Math.floor(Math.log10(Math.max(raw,0.001))), step=[1,2,2.5,5,10].find(n=>n*magnitude>=raw)!*magnitude;
 return Array.from({length:Math.max(0,Math.floor(high/step)-Math.ceil(low/step)+1)},(_,i)=>(Math.ceil(low/step)+i)*step);
}
const rect=(a:CellPoint,b:CellPoint):Rect=>({x0:Math.min(a.x,b.x),x1:Math.max(a.x,b.x),y0:Math.min(a.y,b.y),y1:Math.max(a.y,b.y)});
export function V11PowerCadence({points,scenario,pending}:{points:AnalysisSample[];scenario:Scenario;pending:boolean}) {
 const host=useRef<HTMLElement>(null),svg=useRef<SVGSVGElement>(null),[width,setWidth]=useState(880),[climbId,setClimbId]=useState(''),[kind,setKind]=useState<'power'|'gradient'>('power');
 const title=kind==='power'?'Power & cadence':'Cadence & gradient',xUnit=kind==='power'?'rpm':'%',yUnit=kind==='power'?'W':'rpm';
 const climb=scenario.climbs.find(c=>c.id===climbId),range=useMemo(()=>rangeForClimb(points,climb),[points,climb]);
 const model=useMemo(()=>relationshipDensity(points,range,kind),[points,range,kind]);
 const [stored,setStored]=useState<{model:typeof model;scope:Rect|null;draft:Rect|null;cursor:CellPoint|null}>({model,scope:null,draft:null,cursor:null});
 const state=stored.model===model?stored:{model,scope:null,draft:null,cursor:null};
 const update=(patch:Partial<Omit<typeof state,'model'>>)=>setStored(old=>({...(old.model===model?old:{model,scope:null,draft:null,cursor:null}),...patch}));
 const gesture=useRef<{id:number;start:CellPoint;x:number;y:number;moved:boolean;cancelled:boolean}|null>(null),anchor=useRef<CellPoint|null>(null);
 const clear=()=>{update({scope:null,draft:null,cursor:null});anchor.current=null;gesture.current=null;if(host.current?.contains(document.activeElement)&&document.activeElement?.tagName==='BUTTON')svg.current?.focus();};
 useEffect(()=>{if(!host.current)return;const observer=new ResizeObserver(([e])=>setWidth(Math.max(240,e.contentRect.width)));observer.observe(host.current);return()=>observer.disconnect();},[]);
 useEffect(()=>{setClimbId('');gesture.current=null;anchor.current=null;},[points]);
 useEffect(()=>{gesture.current=null;anchor.current=null;},[model]);
 const full:Rect={x0:0,x1:model.columns-1,y0:0,y1:model.rows-1},scope=state.scope??full;
 const height=width<600?270:330,left=46,right=width-18,top=16,bottom=height-42;
 const x=(column:number)=>left+(column-scope.x0)/(scope.x1-scope.x0+1)*(right-left),y=(row:number)=>bottom-(row-scope.y0)/(scope.y1-scope.y0+1)*(bottom-top);
 const locate=(e:PointerEvent<SVGSVGElement>):CellPoint=>{const box=e.currentTarget.getBoundingClientRect();return{x:Math.max(scope.x0,Math.min(scope.x1,Math.floor(scope.x0+((e.clientX-box.left)/box.width*width-left)/(right-left)*(scope.x1-scope.x0+1)))),y:Math.max(scope.y0,Math.min(scope.y1,Math.floor(scope.y0+(bottom-(e.clientY-box.top)/box.height*height)/(bottom-top)*(scope.y1-scope.y0+1))))};};
 const visible=model.cells.filter(c=>c.column>=scope.x0&&c.column<=scope.x1&&c.row>=scope.y0&&c.row<=scope.y1);
 const active=state.cursor?model.cells[state.cursor.y*model.columns+state.cursor.x]:null;
 const seconds=(cell:typeof model.cells[number])=>climb?cell.selectedSeconds:cell.seconds;
 const total=visible.reduce((sum,c)=>sum+seconds(c),0),maximum=Math.max(1,...model.cells.map(seconds));
 const apply=(r:Rect)=>{update({scope:r,draft:null,cursor:null});anchor.current=null;};
 const escape=()=>{if(state.draft||gesture.current){update({draft:null,cursor:null});gesture.current=null;anchor.current=null;}else{clear();setClimbId('');}};
 return <section ref={host} className="v11-power-room v11-density" data-relationship={kind} aria-label={title} onKeyDown={e=>{if(e.key==='Escape'&&!e.defaultPrevented){e.preventDefault();escape();}}}>
  <header><div><h2>{title}</h2><p>Time spent at each combination</p></div><div className="v11-power-reading"><strong>{pending?'—':timeLabel(active?seconds(active):total)}</strong><span>{active?`${active.xFrom}–${active.xTo} ${xUnit} · ${active.yFrom}–${active.yTo} ${yUnit}`:climb?.name??(kind==='power'?'Recorded power & cadence':'Estimated gradient · recorded cadence')}</span></div></header>
  <div className="v11-density-controls"><div className="v11-relationship-switch" role="group" aria-label="Measurement relationship"><button aria-pressed={kind==='power'} onClick={()=>setKind('power')}>Power & cadence</button><button aria-pressed={kind==='gradient'} onClick={()=>setKind('gradient')}>Cadence & gradient</button></div><label><span className="sr-only">Relationship effort</span><select aria-label="Relationship effort" value={climb?.id??''} onChange={e=>{clear();setClimbId(e.target.value);}}><option value="">Whole ride</option>{scenario.climbs.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></label><span className="v11-density-legend"><i/>Less time<span/><i/>More time</span>{(state.scope||climb)&&<button onClick={()=>{clear();setClimbId('');}}>Show all</button>}</div>
  {!model.cells.length?<p>{model.status==='unavailable'?'The recorded range is too large to display.':'No paired measurements in this recording.'}</p>:<svg ref={svg} viewBox={`0 0 ${width} ${height}`} role="slider" tabIndex={pending?-1:0} aria-label={`Inspect ${title.toLowerCase()}`} aria-valuemin={0} aria-valuemax={model.cells.length-1} aria-valuenow={state.cursor?state.cursor.y*model.columns+state.cursor.x:0} aria-valuetext={pending?'Loading measurements':active?`${active.xFrom} to under ${active.xTo} ${xUnit}, ${active.yFrom} to under ${active.yTo} ${yUnit}, ${timeLabel(seconds(active))}`:'Arrows inspect; Shift and arrows select a rectangle; Enter zooms; Escape returns'}
   onPointerDown={e=>{if(pending||e.button!==0||!e.isPrimary)return;gesture.current={id:e.pointerId,start:locate(e),x:e.clientX,y:e.clientY,moved:false,cancelled:false};anchor.current=null;e.currentTarget.setPointerCapture(e.pointerId);}}
   onPointerMove={e=>{if(pending)return;const p=locate(e),g=gesture.current;if(g&&g.id!==e.pointerId)return;if(g&&e.pointerType==='touch'&&!g.moved&&Math.abs(e.clientY-g.y)>Math.abs(e.clientX-g.x)+8)g.cancelled=true;if(g?.cancelled)return;if(g&&(Math.abs(e.clientX-g.x)>6||e.pointerType!=='touch'&&Math.abs(e.clientY-g.y)>6)){g.moved=true;update({draft:rect(g.start,p),cursor:p});}else update({cursor:p});}}
   onPointerUp={e=>{const g=gesture.current;if(!g||g.id!==e.pointerId)return;gesture.current=null;if(!g.cancelled){if(g.moved)apply(rect(g.start,locate(e)));else if(state.scope||climb){clear();setClimbId('');}else update({cursor:locate(e)});}update({draft:null});}}
   onPointerCancel={()=>{gesture.current=null;update({draft:null,cursor:null});}}
   onPointerLeave={()=>{if(!gesture.current)update({cursor:null});}}
   onBlur={()=>{if(!gesture.current){update({cursor:null,draft:null});anchor.current=null;}}}
   onKeyDown={e=>{if(pending||!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End','Enter','Escape'].includes(e.key))return;e.preventDefault();if(e.key==='Escape'){escape();return;}if(e.key==='Enter'){if(state.draft)apply(state.draft);return;}const p=state.cursor??{x:scope.x0,y:scope.y0};const next={x:Math.max(scope.x0,Math.min(scope.x1,e.key==='Home'?scope.x0:e.key==='End'?scope.x1:p.x+(e.key==='ArrowRight'?1:e.key==='ArrowLeft'?-1:0))),y:Math.max(scope.y0,Math.min(scope.y1,p.y+(e.key==='ArrowUp'?1:e.key==='ArrowDown'?-1:0)))};if(e.shiftKey){anchor.current??=p;update({draft:rect(anchor.current,next),cursor:next});}else{anchor.current=null;update({draft:null,cursor:next});}}}>
   <rect x={left} y={top} width={right-left} height={bottom-top} fill="#fafaf8"/>
   {ticks(scope.y0*model.yStep,(scope.y1+1)*model.yStep).map(value=>{const at=y(value/model.yStep);return <g key={value}><line className="v11-chart-grid" x1={left} x2={right} y1={at} y2={at}/><text x={left-8} y={at+4} textAnchor="end">{value}</text></g>;})}
   {ticks(model.xMin+scope.x0*model.xStep,model.xMin+(scope.x1+1)*model.xStep).map(value=><text key={value} x={x((value-model.xMin)/model.xStep)} y={height-15} textAnchor="middle">{value}</text>)}<text x={right} y={height-1} textAnchor="end">{xUnit}</text><text x={left-8} y={top-5} textAnchor="end">{yUnit}</text>
   {!pending&&visible.filter(c=>c.seconds>0).map(c=><rect key={`${c.row}:${c.column}`} x={x(c.column)+.1} y={y(c.row+1)+.1} width={Math.max(.5,x(c.column+1)-x(c.column)-.2)} height={Math.max(.5,y(c.row)-y(c.row+1)-.2)} fill={climb&&!c.selectedSeconds?'#d9dcd4':kind==='gradient'?'#007A61':'#613393'} opacity={climb&&c.selectedSeconds===0? .22 : .08+.92*Math.pow(seconds(c)/maximum,.65)}/>)}
   {state.draft&&<rect className="v11-brush" x={x(state.draft.x0)} y={y(state.draft.y1+1)} width={x(state.draft.x1+1)-x(state.draft.x0)} height={y(state.draft.y0)-y(state.draft.y1+1)}/>}
   {active&&!pending&&<rect x={x(active.column)} y={y(active.row+1)} width={x(active.column+1)-x(active.column)} height={y(active.row)-y(active.row+1)} fill="none" stroke={kind==='gradient'?'#005947':'#493069'} strokeWidth={1.25}/>}
  </svg>}
  <details className="v11-measurement-details"><summary>About {title.toLowerCase()}</summary><p>Each cell covers {model.xStep} {xUnit} and {model.yStep} {yUnit}. Color shows covered time, including measured zeros. Missing pairs and recording gaps over 30 seconds are excluded. Selecting levels adds their covered time wherever they occur; it does not select one continuous stretch of the ride.</p>{kind==='gradient'&&<p>Gradient is estimated from elevation over a centered 100 m window. Missing elevation and discontinuous windows remain absent. Whole-ride scales stay fixed when highlighting a climb.</p>}<p>Select a climb to see its measurements against the whole ride. Drag to zoom into measurement ranges; click or press Escape to return.</p></details>
 </section>;
}
