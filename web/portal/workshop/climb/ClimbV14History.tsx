import {useMemo,useRef,useEffect,useState} from 'react';
import {ArrowUpRight,X} from 'lucide-react';
import {effortDate,historyEfforts,historyDomain,type ClimbInspection} from './climbV5Model';
import {historySelection,historyGap} from './climbV7Model';
import {resultTime} from './climbV6Model';
import {plural,v14Effort} from './climbV14Model';
import {ClimbV7Link as Link} from './ClimbV7Link';
/** V13's history logic as a chart card beside a ledger card. Both close on one bottom line, and their foot rules share a line too. */
export function ClimbV14History({personal}:{personal:NonNullable<ClimbInspection['personal']>}){
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
 const ticks=[domain.min,(domain.min+domain.max)/2,domain.max];
 const ordered=[...rows].sort((a,b)=>order==='fastest'?a.duration-b.duration:Date.parse(b.date)-Date.parse(a.date));
 const s=<>{' '}<span className="c14-unit">s</span></>,isBest=(r:typeof latest)=>r.id===best.id;
 return <section className="c14-section" id="c14-history" aria-labelledby="c14-history-title" onKeyDown={e=>{if(e.key==='Escape')clear();}}>
  <header className="c14-section-head"><h2 id="c14-history-title">Your history</h2><span className="c14-rule"/></header>
  <div className="c14-two-up">
   <div className="c14-card c14-history-chart"><div className="c14-chart-legend"><span>Effort time</span><span>Personal best <strong>{resultTime(personal.best)}</strong></span></div>
    <svg ref={plot} viewBox={`0 0 ${W} ${H}`} role="group" aria-label="Effort history" onClick={clear} onPointerLeave={()=>setHover(null)}>
     <rect width={W} height={H} fill="transparent"/>
     {ticks.map(t=><g key={t}><line x1={L} x2={W-R} y1={y(t)} y2={y(t)} className="c14-grid"/><text x={L-12} y={y(t)+4} textAnchor="end" className="c14-axis">{resultTime(t)}</text></g>)}
     <line x1={L} x2={W-R} y1={y(best.duration)} y2={y(best.duration)} className="c14-pr-line"/>
     {rows.map((r,i)=><g key={r.id} role="button" tabIndex={0} aria-label={`Inspect effort ${effortDate(r.date)}, ${resultTime(r.duration)}`} aria-pressed={selected===r.id||second===r.id} className="c14-point" data-best={isBest(r)} data-selected={selected===r.id} data-comparison={second===r.id} data-active={active.id===r.id} onPointerEnter={()=>setHover(r.id)} onFocus={()=>setHover(r.id)} onBlur={()=>setHover(null)} onClick={e=>{e.stopPropagation();choose(r.id);}} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose(r.id);}if(['ArrowRight','ArrowLeft'].includes(e.key)){e.preventDefault();e.currentTarget.parentElement?.querySelectorAll<SVGGElement>('.c14-point')[Math.max(0,Math.min(rows.length-1,i+(e.key==='ArrowRight'?1:-1)))]?.focus();}}}>
      <circle cx={pointX(r)} cy={y(r.duration)} r={18} fill="transparent"/><circle className="c14-halo" cx={pointX(r)} cy={y(r.duration)} r={11}/>{isBest(r)&&<circle className="c14-ring" cx={pointX(r)} cy={y(r.duration)} r={7}/>}<circle className="c14-dot" cx={pointX(r)} cy={y(r.duration)} r={4}/>
      {comparing&&(selected===r.id||second===r.id)&&<text x={pointX(r)} y={y(r.duration)-17} textAnchor="middle" className="c14-point-letter">{selected===r.id?'A':'B'}</text>}
     </g>)}
     <text x={L} y={H-7} className="c14-axis">{effortDate(rows[0].date,true)}</text>{domain.end!==domain.start&&<text x={W-R} y={H-7} textAnchor="end" className="c14-axis">{effortDate(latest.date,true)}</text>}
    </svg>
    <div className="c14-readout" data-comparing={comparing}>
     <div><span>{comparing?'A · '+effortDate(active.date):effortDate(active.date)}</span><strong>{resultTime(active.duration)}{!comparing&&isBest(active)&&<small className="c14-chip" data-tag="PR">PR</small>}</strong></div>
     {comparing?<><div><span>{comparison?'B · '+effortDate(comparison.date):'Choose another effort'}</span>{comparison&&<strong>{resultTime(comparison.duration)}</strong>}</div>{comparison&&<div><span>B − A</span><strong>{historyGap(comparison.duration,active.duration)}{s}</strong></div>}</>:!isBest(active)&&<div><span>From personal best</span><strong>{historyGap(active.duration,best.duration)}{s}</strong></div>}
     <div className="c14-readout-actions">{!comparing&&<button className="c14-text-button" onClick={()=>{setSelected(active.id);setComparing(true);setSecond(null);}}>Compare</button>}{(comparison??active).analysisHref&&<Link className="c14-button" href={v14Effort((comparison??active).analysisHref!)}>Analyze effort<ArrowUpRight aria-hidden="true"/></Link>}{(selected||comparing)&&<button className="c14-icon-button" onClick={clear} aria-label="Clear history selection"><X/></button>}</div>
    </div>
   </div>
   <div className="c14-card c14-ledger"><header><span>Date</span><select value={order} aria-label="Sort history" onChange={e=>setOrder(e.target.value)}><option value="recent">Recent</option><option value="fastest">Fastest</option></select></header><ol>{ordered.map(r=>{const tag=comparing&&selected===r.id?'A':comparing&&second===r.id?'B':r.id===best.id?'PR':'';return <li key={r.id}><button data-selected={selected===r.id} data-comparison={second===r.id} data-active={active.id===r.id} aria-pressed={selected===r.id||second===r.id} onClick={()=>choose(r.id)} onPointerEnter={()=>setHover(r.id)} onPointerLeave={()=>setHover(null)} aria-label={`Select effort ${effortDate(r.date)}`}><time dateTime={r.date}>{effortDate(r.date,true)}</time>{tag?<small className="c14-chip" data-tag={tag}>{tag}</small>:<span/>}<strong>{resultTime(r.duration)}</strong></button></li>;})}</ol><footer className="c14-ledger-foot">{plural(rows.length,'effort')}</footer></div>
  </div>
 </section>;
}
