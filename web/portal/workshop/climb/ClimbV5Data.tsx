import {useEffect,useMemo,useRef,useState,type MouseEvent,type ReactNode} from 'react';
import {ArrowUpRight,Check,X} from 'lucide-react';
import {RankMark} from '../../src/components/rankmarks/RankMark';
import {timeLabel,climbResult,climbSamples} from '../scenario';
import {analysisSamples,channelSummary} from '../v3Model';
import {effortDate,preciseTime,timeGap,historyEfforts,historyDomain,toggleHistorySelection,type ClimbInspection,type HistoryEffort,type BoardEffort} from './climbV5Model';

function ResultLink({href,children}:{href:string;children:ReactNode}){
 function visit(e:MouseEvent<HTMLAnchorElement>){if(e.button||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;e.preventDefault();window.parent.postMessage({type:'climb-open',href},location.origin);}
 return <a href={href} target="_top" onClick={visit}>{children}</a>;
}
function Time({value}:{value:number}){const [whole,fraction]=preciseTime(value).split('.');return <span className="c5-time">{whole}<small>.{fraction}</small></span>;}

function History({personal,effortHref}:{personal:NonNullable<ClimbInspection['personal']>;effortHref:(href:string)=>string}){
 const rows=useMemo(()=>historyEfforts(personal),[personal]);
 const domain=useMemo(()=>historyDomain(rows),[rows]);
 const [hover,setHover]=useState<string|null>(null),[selected,setSelected]=useState<string[]>([]),[order,setOrder]=useState('recent');
 const latest=rows.at(-1)!,best=rows.reduce((a,b)=>a.duration<=b.duration?a:b);
 const first=rows.find(r=>r.id===selected[0]),second=rows.find(r=>r.id===selected[1]);
 const active=rows.find(r=>r.id===hover)??second??first??latest;
 const reference=first&&(selected.length===2||first.id!==active.id)?first:best;
 const plot=useRef<SVGSVGElement>(null),[plotWidth,setPlotWidth]=useState(800);
 useEffect(()=>{const el=plot.current;if(!el)return;const observer=new ResizeObserver(entries=>setPlotWidth(entries[0].contentRect.width));observer.observe(el);return()=>observer.disconnect();},[]);
 const [W,H,L,R,T,B]=[Math.max(280,plotWidth),245,44,23,20,31],plotW=W-L-R,plotH=H-T-B;
 const x=(row:HistoryEffort)=>L+(domain.end===domain.start ? 0.5 : (Date.parse(row.date)-domain.start)/(domain.end-domain.start))*plotW;
 const y=(duration:number)=>T+(duration-domain.min)/(domain.max-domain.min)*plotH;
 const ticks=Array.from({length:Math.round((domain.max-domain.min)/domain.step)+1},(_,i)=>domain.min+i*domain.step);
 const points=rows.map(row=>{
  const same=rows.filter(r=>Date.parse(r.date)===Date.parse(row.date)&&r.duration===row.duration),spacing=Math.min(24,plotW/Math.max(1,same.length-1)),half=(same.length-1)*spacing/2,center=Math.max(L+half,Math.min(W-R-half,x(row))),offset=(same.findIndex(r=>r.id===row.id)-(same.length-1)/2)*spacing;
  return {...row,x:center+offset,y:y(row.duration)};
 });
 const choose=(id:string)=>setSelected(s=>toggleHistorySelection(s,id));
 const clear=()=>{setSelected([]);setHover(null);};
 const ordered=[...rows].sort((a,b)=>order==='fastest'?a.duration-b.duration:Date.parse(b.date)-Date.parse(a.date));
 return <section className="c5-history" id="c5-history" onKeyDown={e=>{if(e.key==='Escape'){clear();e.stopPropagation();}}}>
  <header className="c5-section-heading"><div><h2>Your history</h2><span>{rows.length} {rows.length===1?'effort':'efforts'}</span></div><span>{new Date(domain.start).getUTCFullYear()}{new Date(domain.end).getUTCFullYear()!==new Date(domain.start).getUTCFullYear()?` – ${new Date(domain.end).getUTCFullYear()}`:''}</span></header>
  <div className="c5-history-body">
   <div className="c5-history-instrument">
    <div className="c5-history-legend"><span>Time</span><span className="c5-pr-key">Personal best <strong>{timeLabel(personal.best)}</strong></span></div>
    <svg ref={plot} className="c5-history-plot" viewBox={`0 0 ${W} ${H}`} aria-label="Your effort history. Select efforts to compare times." onPointerLeave={()=>setHover(null)} onClick={clear}>
     <rect width={W} height={H} fill="transparent"/>
     {ticks.map(t=><g key={t}><line x1={L} x2={W-R} y1={y(t)} y2={y(t)} className="c5-grid-line"/><text x={L-12} y={y(t)+4} textAnchor="end" className="c5-axis-label">{timeLabel(t)}</text></g>)}
     <line x1={L} x2={W-R} y1={y(personal.best)} y2={y(personal.best)} className="c5-pr-line"/>
     {first&&second&&<rect x={Math.min(x(first),x(second))} y={T} width={Math.max(1,Math.abs(x(first)-x(second)))} height={plotH} className="c5-history-range"/>}
     {points.map((r,i)=><g key={r.id} role="button" tabIndex={0} aria-label={`${effortDate(r.date)}, ${preciseTime(r.duration)}${r.duration===personal.best?', personal best':''}`} aria-pressed={selected.includes(r.id)} className="c5-history-point" data-active={active.id===r.id} data-selected={selected.includes(r.id)} onPointerEnter={()=>setHover(r.id)} onFocus={()=>setHover(r.id)} onBlur={()=>setHover(null)} onClick={e=>{e.stopPropagation();choose(r.id);}} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose(r.id);}if(e.key==='ArrowRight'||e.key==='ArrowLeft'){e.preventDefault();const next=e.currentTarget.parentElement?.querySelectorAll<SVGGElement>('.c5-history-point')[Math.max(0,Math.min(points.length-1,i+(e.key==='ArrowRight'?1:-1)))];next?.focus();}}}>
      {active.id===r.id&&<line x1={r.x} x2={r.x} y1={T} y2={H-B} className="c5-cursor-line"/>}
      <circle cx={r.x} cy={r.y} r={17} fill="transparent"/>
      <circle className="c5-point-halo" cx={r.x} cy={r.y} r={12}/>
      <circle className="c5-point" cx={r.x} cy={r.y} r={5.5}/>
     </g>)}
     <text x={L} y={H-7} className="c5-axis-label">{effortDate(rows[0].date,true)}</text>
     {domain.end!==domain.start&&<text x={W-R} y={H-7} textAnchor="end" className="c5-axis-label">{effortDate(latest.date,true)}</text>}
    </svg>
   </div>
   <div className="c5-history-list"><header><span>Date</span><select aria-label="Sort history" value={order} onChange={e=>setOrder(e.target.value)}><option value="recent">Recent</option><option value="fastest">Fastest</option></select></header><ol>{ordered.map(r=><li key={r.id}><button data-active={active.id===r.id} data-selected={selected.includes(r.id)} aria-pressed={selected.includes(r.id)} aria-label={`Select effort ${effortDate(r.date)}, ${preciseTime(r.duration)}`} onPointerEnter={()=>setHover(r.id)} onPointerLeave={()=>setHover(null)} onFocus={()=>setHover(r.id)} onBlur={()=>setHover(null)} onClick={()=>choose(r.id)}><span className="c5-history-date"><time dateTime={r.date}>{effortDate(r.date,true)}</time>{r.duration===personal.best&&<small>PR</small>}</span><Time value={r.duration}/><span className="c5-selection-mark">{selected.includes(r.id)&&<Check size={12}/>}</span></button></li>)}</ol></div>
  </div>
  <div className="c5-history-reading" data-selected={selected.length>0}>
   <div><span>{selected.length===2?'Compared effort':selected.length===1?'Selected effort':'Effort'}</span><strong>{effortDate(active.date)}</strong></div>
   <div><span>Time</span><strong><Time value={active.duration}/></strong></div>
   <div className="c5-history-delta"><span>{reference===best?'From personal best':`From ${effortDate(reference.date,true)}`}</span><strong>{timeGap(active.duration,reference.duration)}<small>s</small></strong></div>
   <div className="c5-reading-actions">{active.analysisHref&&<ResultLink href={effortHref(active.analysisHref)}>Analyze effort<ArrowUpRight size={13}/></ResultLink>}{selected.length>0&&<button aria-label="Clear history selection" onClick={clear}><X size={15}/></button>}</div>
  </div>
 </section>;
}

function Leaderboard({data,effortHref}:{data:ClimbInspection;effortHref:(href:string)=>string}){
 const rows=data.board!.rows;
 const fastest=rows.reduce((a,b)=>a.duration<=b.duration?a:b);
 const [referenceId,setReferenceId]=useState(fastest.id),[hover,setHover]=useState<string|null>(null),[selected,setSelected]=useState<string|null>(null);
 const reference=rows.find(r=>r.id===referenceId)??fastest;
 const active=rows.find(r=>r.id===hover)??rows.find(r=>r.id===selected)??rows.find(r=>r.current)??fastest;
 const maxGap=Math.max(1,...rows.map(r=>Math.abs(r.duration-reference.duration)));
 const recording=data.recordings.find(r=>r.entry.ride.id===active.rideId);
 const climb=recording?.entry.ride.climbs.find(c=>c.id===new URL(recording.href,'https://workshop.local').searchParams.get('climb'));
 const result=recording&&climb?climbResult(recording.entry.ride,climb):undefined;
 const speed=useMemo(()=>recording&&climb?channelSummary(analysisSamples(climbSamples(recording.entry.ride,climb)),'speed').average:null,[recording,climb]);
 const date=recording?.entry.ride.ride.startedAt;
 const select=(row:BoardEffort)=>setSelected(s=>s===row.id?null:row.id);
 const clear=()=>{setSelected(null);setHover(null);};
 return <section className="c5-leaderboard" onKeyDown={e=>{if(e.key==='Escape'){clear();e.stopPropagation();}}}>
  <header className="c5-section-heading"><div><h2>Leaderboard</h2><span>All time</span></div><label className="c5-reference-control">Compare with <select aria-label="Leaderboard comparison reference" value={reference.id} onChange={e=>{setReferenceId(e.target.value);setHover(null);}}>{rows.map(r=><option value={r.id} key={r.id}>{r.name}{r.current?' · You':''}{r.rank===1?' · Fastest':''}</option>)}</select></label></header>
  <div className="c5-board-body" onPointerLeave={()=>setHover(null)} onBlur={e=>{if(!e.currentTarget.contains(e.relatedTarget))setHover(null);}}>
   <div className="c5-table-wrap"><table className="c5-table"><thead><tr><th scope="col">Place</th><th scope="col">Rider</th><th scope="col">Time</th><th scope="col">Gap <small>s</small></th></tr></thead><tbody>{rows.map(r=><tr key={r.id} data-current={r.current} data-active={active.id===r.id} data-selected={selected===r.id} onPointerEnter={()=>setHover(r.id)} onClick={()=>select(r)}>
    <td><span className="c5-board-rank"><RankMark rank={r.rank} size={44}/><span>{r.rank}</span></span></td>
    <th scope="row"><button aria-label={`Inspect ${r.name}, place ${r.rank}, ${preciseTime(r.duration)}`} aria-pressed={selected===r.id} onFocus={()=>setHover(r.id)} onClick={e=>{e.stopPropagation();select(r);}}>{r.name}{r.current&&<small>You</small>}</button></th>
    <td><Time value={r.duration}/></td>
    <td><span className="c5-gap" data-negative={r.duration<reference.duration}><span className="c5-gap-track" aria-hidden="true"><i style={{width:`${Math.abs(r.duration-reference.duration)/maxGap*100}%`}}/></span><span>{timeGap(r.duration,reference.duration)}</span></span></td>
   </tr>)}</tbody></table><div className="c5-board-foot"><span>Gap to {reference.name}</span>{data.board?.asOf&&<time dateTime={data.board.asOf}>As of {effortDate(data.board.asOf)}</time>}</div></div>
   <aside className="c5-effort-inspector" aria-label="Inspected leaderboard effort" data-pinned={selected!==null}>
    <header><span>{selected===active.id?'Selected effort':'Effort'}</span>{selected&&<button onClick={clear} aria-label="Clear leaderboard selection"><X size={14}/></button>}</header>
    <div className="c5-inspector-rider">{active.riderHref?<ResultLink href={active.riderHref}>{active.name}<ArrowUpRight size={12}/></ResultLink>:<strong>{active.name}</strong>}<span>#{active.rank}</span></div>
    <div className="c5-inspector-date">{date&&<time dateTime={date}>{effortDate(date)}</time>}</div>
    <div className="c5-inspector-time"><Time value={active.duration}/><span><strong>{timeGap(active.duration,reference.duration)}<small>s</small></strong><small>to {reference.name}</small></span></div>
    <div className="c5-inspector-measures">{result&&<dl className="c5-inspector-metrics">{speed!==null&&<div><dt>Avg speed</dt><dd>{(speed*3.6).toFixed(1)}<small>km/h</small></dd></div>}{result.power!==null&&<div><dt>Avg power</dt><dd>{Math.round(result.power)}<small>W</small></dd></div>}</dl>}</div>
    <div className="c5-inspector-actions"><button disabled={active.id===reference.id} onClick={()=>setReferenceId(active.id)}>{active.id===reference.id?<><Check size={12}/>Comparison reference</>:'Use as reference'}</button>{active.href&&<ResultLink href={effortHref(active.href)}>Analyze effort<ArrowUpRight size={13}/></ResultLink>}</div>
   </aside>
  </div>
 </section>;
}

export function ClimbV5Data({data,state,emptyLeaderboard,effortHref}:{data:ClimbInspection;state:string;emptyLeaderboard:boolean;effortHref:(href:string)=>string}){
 if(state==='loading')return <div className="c5-data c5-data-loading" aria-label="Loading climb results"><h2>Leaderboard</h2><div/><div/><div/></div>;
 const personal=state==='empty'?undefined:data.personal,rows=state==='empty'?[]:data.board?.rows??[];
 return <div className="c5-data">
  {personal&&<History personal={personal} effortHref={effortHref}/>}
  {rows.length>0?<Leaderboard data={data} effortHref={effortHref}/>:<section className="c5-leaderboard"><header className="c5-section-heading"><h2>Leaderboard</h2></header><div className="c4-quiet"><h3>{state==='empty'||emptyLeaderboard||data.board?'No times yet':'Leaderboard unavailable'}</h3>{(state==='empty'||emptyLeaderboard||data.board)&&<p>Ride it to set the first time.</p>}</div></section>}
 </div>;
}
