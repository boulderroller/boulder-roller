import {useMemo,useRef,useEffect,useState} from 'react';
import {ArrowUpRight,X} from 'lucide-react';
import {effortDate,historyEfforts,historyDomain,type ClimbInspection} from './climbV5Model';
import {historySelection,historyGap} from './climbV7Model';
import {v11Effort} from './climbV11Model';
import {resultTime} from './climbV6Model';
import {ClimbV7Link as Link} from './ClimbV7Link';
export {ClimbV11Board} from './ClimbV11Board';
export function ClimbV11History({personal}:{personal:NonNullable<ClimbInspection['personal']>}){
 const rows=useMemo(()=>historyEfforts(personal),[personal]),domain=useMemo(()=>historyDomain(rows),[rows]);
 const [selected,setSelected]=useState<string|null>(null),[hover,setHover]=useState<string|null>(null),[comparing,setComparing]=useState(false),[second,setSecond]=useState<string|null>(null),[order,setOrder]=useState('recent');
 const latest=rows.at(-1)!,best=rows.reduce((a,b)=>a.duration<=b.duration?a:b);
 const pinned=rows.find(r=>r.id===selected),comparison=rows.find(r=>r.id===second);
 const active=pinned??rows.find(r=>r.id===hover)??latest;
 const clear=()=>{setSelected(null);setSecond(null);setComparing(false);setHover(null);};
 const choose=(id:string)=>{if(comparing){if(id!==selected)setSecond(s=>s===id?null:id);}else {setSelected(s=>historySelection(s,id));setHover(null);}};
 const plot=useRef<SVGSVGElement>(null),[width,setWidth]=useState(680);
 useEffect(()=>{const el=plot.current;if(!el)return;const ro=new ResizeObserver(e=>setWidth(e[0].contentRect.width));ro.observe(el);return()=>ro.disconnect();},[]);
 const W=Math.max(width,280),H=232,L=52,R=25,T=21,B=35;
 const x=(r:typeof latest)=>L+(domain.end===domain.start ? .5 : (Date.parse(r.date)-domain.start)/(domain.end-domain.start))*(W-L-R);
 const y=(t:number)=>T+(t-domain.min)/(domain.max-domain.min)*(H-T-B);
 const pointX=(row:typeof latest)=>{const same=rows.filter(r=>Date.parse(r.date)===Date.parse(row.date)&&r.duration===row.duration),spacing=Math.min(24,(W-L-R)/Math.max(1,same.length-1)),half=(same.length-1)*spacing/2,center=Math.max(L+half,Math.min(W-R-half,x(row)));return center+(same.findIndex(r=>r.id===row.id)-(same.length-1)/2)*spacing;};
 const ticks=Array.from({length:Math.round((domain.max-domain.min)/domain.step)+1},(_,i)=>domain.min+i*domain.step);
 const ordered=[...rows].sort((a,b)=>order==='fastest'?a.duration-b.duration:Date.parse(b.date)-Date.parse(a.date));
 return <section className="c7-history" id="c7-history" onKeyDown={e=>{if(e.key==='Escape')clear();}}>
  <header className="c7-section-heading"><h2>Your history</h2><span>{rows.length} efforts</span></header>
  <div className="c7-history-body"><div className="c7-history-chart"><div className="c7-chart-legend"><span>Effort time</span><span>Personal best <strong>{resultTime(personal.best)}</strong></span></div>
   <svg ref={plot} viewBox={`0 0 ${W} ${H}`} role="group" aria-label="Effort history" onClick={clear} onPointerLeave={()=>setHover(null)}>
    <rect width={W} height={H} fill="transparent"/>
    {ticks.map(t=><g key={t}><line x1={L} x2={W-R} y1={y(t)} y2={y(t)} className="c7-grid"/><text x={L-12} y={y(t)+4} textAnchor="end" className="c7-axis">{resultTime(t)}</text></g>)}
    <line x1={L} x2={W-R} y1={y(best.duration)} y2={y(best.duration)} className="c7-pr-line"/>
    {rows.map((r,i)=><g key={r.id} role="button" tabIndex={0} aria-label={`Inspect effort ${effortDate(r.date)}, ${resultTime(r.duration)}`} aria-pressed={selected===r.id||second===r.id} className="c7-history-point" data-selected={selected===r.id} data-comparison={second===r.id} data-active={active.id===r.id} onPointerEnter={()=>setHover(r.id)} onFocus={()=>setHover(r.id)} onBlur={()=>setHover(null)} onClick={e=>{e.stopPropagation();choose(r.id);}} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose(r.id);}if(['ArrowRight','ArrowLeft'].includes(e.key)){e.preventDefault();e.currentTarget.parentElement?.querySelectorAll<SVGGElement>('.c7-history-point')[Math.max(0,Math.min(rows.length-1,i+(e.key==='ArrowRight'?1:-1)))]?.focus();}}}>
     <circle cx={pointX(r)} cy={y(r.duration)} r={18} fill="transparent"/><circle className="c7-halo" cx={pointX(r)} cy={y(r.duration)} r={11}/><circle className="c7-dot" cx={pointX(r)} cy={y(r.duration)} r={5}/>
     {comparing&&(selected===r.id||second===r.id)&&<text x={pointX(r)} y={y(r.duration)-17} textAnchor="middle" className="c7-point-letter">{selected===r.id?'A':'B'}</text>}
    </g>)}
    <text x={L} y={H-7} className="c7-axis">{effortDate(rows[0].date,true)}</text>{domain.end!==domain.start&&<text x={W-R} y={H-7} textAnchor="end" className="c7-axis">{effortDate(latest.date,true)}</text>}
   </svg>
  </div><div className="c7-history-list"><header><span>Date</span><select value={order} aria-label="Sort history" onChange={e=>setOrder(e.target.value)}><option value="recent">Recent</option><option value="fastest">Fastest</option></select></header><ol>{ordered.map(r=><li key={r.id}><button data-selected={selected===r.id} data-comparison={second===r.id} data-active={active.id===r.id} aria-pressed={selected===r.id||second===r.id} onClick={()=>choose(r.id)} onPointerEnter={()=>setHover(r.id)} onPointerLeave={()=>setHover(null)} aria-label={`Select effort ${effortDate(r.date)}`}><time dateTime={r.date}>{effortDate(r.date,true)}</time><small>{comparing&&selected===r.id?'A':comparing&&second===r.id?'B':r.id===best.id?'PR':''}</small><strong>{resultTime(r.duration)}</strong></button></li>)}</ol></div></div>
  <div className="c7-history-readout" data-comparing={comparing}>
   <div><span>{comparing?'A · '+effortDate(active.date):effortDate(active.date)}</span><strong>{resultTime(active.duration)}</strong></div>
   {comparing?<><div><span>{comparison?'B · '+effortDate(comparison.date):'Choose another effort'}</span>{comparison&&<strong>{resultTime(comparison.duration)}</strong>}</div>{comparison&&<div><span>B − A</span><strong>{historyGap(comparison.duration,active.duration)}<small>s</small></strong></div>}</>:<div><span>From personal best</span><strong>{historyGap(active.duration,best.duration)}<small>s</small></strong></div>}
   <div className="c7-history-actions">{!comparing&&<button onClick={()=>{setSelected(active.id);setComparing(true);setSecond(null);}}>Compare</button>}{(comparison??active).analysisHref&&<Link href={v11Effort((comparison??active).analysisHref!)}>Analyze effort<ArrowUpRight size={13}/></Link>}{(selected||comparing)&&<button onClick={clear} aria-label="Clear history selection"><X size={16}/></button>}</div>
  </div>
 </section>;
}
