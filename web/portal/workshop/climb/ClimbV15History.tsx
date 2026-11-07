import {useMemo,useRef,useEffect,useState} from 'react';
import {ArrowUpRight,X} from 'lucide-react';
import {effortDate,historyEfforts,historyDomain,type ClimbInspection} from './climbV5Model';
import {historySelection,historyGap} from './climbV7Model';
import {resultTime} from './climbV6Model';
import {plural,v15Effort} from './climbV15Model';
import {ClimbV7Link as Link} from './ClimbV7Link';
/** V14's history with the hill's fastest time drawn as the target line when the board holds 1st. V13's history logic as a chart card beside a ledger card. Both close on one bottom line, and their foot rules share a line too. */
export function ClimbV15History({personal,fastest}:{personal:NonNullable<ClimbInspection['personal']>;fastest?:number}){
 const rows=useMemo(()=>historyEfforts(personal),[personal]),domain=useMemo(()=>{const d=historyDomain(rows);if(fastest===undefined||(fastest>=d.min&&fastest<=d.max))return d;return {...d,min:Math.min(d.min,Math.max(0,Math.floor(fastest/d.step)*d.step-d.step)),max:Math.max(d.max,Math.ceil(fastest/d.step)*d.step+d.step)};},[rows,fastest]);
 const [selected,setSelected]=useState<string|null>(null),[hover,setHover]=useState<string|null>(null),[comparing,setComparing]=useState(false),[second,setSecond]=useState<string|null>(null),[order,setOrder]=useState('recent');
 const latest=rows.at(-1)!,best=rows.reduce((a,b)=>a.duration<=b.duration?a:b);
 const pinned=rows.find(r=>r.id===selected),comparison=rows.find(r=>r.id===second);
 const active=pinned??rows.find(r=>r.id===hover)??latest;
 const clear=()=>{setSelected(null);setSecond(null);setComparing(false);setHover(null);};
 const choose=(id:string)=>{if(comparing){if(id!==selected)setSecond(s=>s===id?null:id);}else {setSelected(s=>historySelection(s,id));setHover(null);}};
 const plot=useRef<SVGSVGElement>(null),[width,setWidth]=useState(680),[height,setHeight]=useState(232);
 useEffect(()=>{const el=plot.current;if(!el)return;const ro=new ResizeObserver(e=>{setWidth(e[0].contentRect.width);setHeight(e[0].contentRect.height);});ro.observe(el);return()=>ro.disconnect();},[]);
 const W=Math.max(width,280),H=Math.max(120,Math.round(height)),L=52,R=25,T=21,B=35;
 const x=(r:typeof latest)=>L+(domain.end===domain.start ? .5 : (Date.parse(r.date)-domain.start)/(domain.end-domain.start))*(W-L-R);
 const y=(t:number)=>T+(t-domain.min)/(domain.max-domain.min)*(H-T-B);
 const pointX=(row:typeof latest)=>{const same=rows.filter(r=>Date.parse(r.date)===Date.parse(row.date)&&r.duration===row.duration),spacing=Math.min(24,(W-L-R)/Math.max(1,same.length-1)),half=(same.length-1)*spacing/2,center=Math.max(L+half,Math.min(W-R-half,x(row)));return center+(same.findIndex(r=>r.id===row.id)-(same.length-1)/2)*spacing;};
 const ticks=[domain.min,(domain.min+domain.max)/2,domain.max];
 const ordered=[...rows].sort((a,b)=>order==='fastest'?a.duration-b.duration:Date.parse(b.date)-Date.parse(a.date));
 const s=<>{' '}<span className="c15-unit">s</span></>,isBest=(r:typeof latest)=>r.id===best.id;
 return <section className="c15-section" id="c15-history" aria-labelledby="c15-history-title" onKeyDown={e=>{if(e.key==='Escape')clear();}}>
  <header className="c15-section-head"><h2 id="c15-history-title">Your history</h2><span className="c15-rule"/></header>
  <div className="c15-two-up">
   <div className="c15-card c15-history-chart"><div className="c15-chart-legend"><span>Effort time</span><span className="c15-chart-keys">{fastest!==undefined&&<span><svg className="c15-key" viewBox="0 0 16 8" aria-hidden="true"><line x1={0} x2={16} y1={4} y2={4} className="c15-fastest-line"/></svg>Fastest <strong>{resultTime(fastest)}</strong></span>}<span><svg className="c15-key" viewBox="0 0 16 8" aria-hidden="true"><line x1={0} x2={16} y1={4} y2={4} className="c15-pr-line"/></svg>Personal best <strong>{resultTime(personal.best)}</strong></span></span></div>
    <svg ref={plot} viewBox={`0 0 ${W} ${H}`} role="group" aria-label="Effort history" onClick={clear} onPointerLeave={()=>setHover(null)}>
     <rect width={W} height={H} fill="transparent"/>
     {ticks.map(t=><g key={t}><line x1={L} x2={W-R} y1={y(t)} y2={y(t)} className="c15-grid"/><text x={L-12} y={y(t)+4} textAnchor="end" className="c15-axis">{resultTime(t)}</text></g>)}
     {fastest!==undefined&&<line x1={L} x2={W-R} y1={y(fastest)} y2={y(fastest)} className="c15-fastest-line"/>}<line x1={L} x2={W-R} y1={y(best.duration)} y2={y(best.duration)} className="c15-pr-line"/>
     {rows.map((r,i)=><g key={r.id} role="button" tabIndex={0} aria-label={`Inspect effort ${effortDate(r.date)}, ${resultTime(r.duration)}`} aria-pressed={selected===r.id||second===r.id} className="c15-point" data-best={isBest(r)} data-selected={selected===r.id} data-comparison={second===r.id} data-active={active.id===r.id} onPointerEnter={()=>setHover(r.id)} onFocus={()=>setHover(r.id)} onBlur={()=>setHover(null)} onClick={e=>{e.stopPropagation();choose(r.id);}} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose(r.id);}if(['ArrowRight','ArrowLeft'].includes(e.key)){e.preventDefault();e.currentTarget.parentElement?.querySelectorAll<SVGGElement>('.c15-point')[Math.max(0,Math.min(rows.length-1,i+(e.key==='ArrowRight'?1:-1)))]?.focus();}}}>
      <circle cx={pointX(r)} cy={y(r.duration)} r={18} fill="transparent"/><circle className="c15-halo" cx={pointX(r)} cy={y(r.duration)} r={11}/>{isBest(r)&&<circle className="c15-ring" cx={pointX(r)} cy={y(r.duration)} r={7}/>}<circle className="c15-dot" cx={pointX(r)} cy={y(r.duration)} r={4}/>
      {comparing&&(selected===r.id||second===r.id)&&<text x={pointX(r)} y={y(r.duration)-17} textAnchor="middle" className="c15-point-letter">{selected===r.id?'A':'B'}</text>}
     </g>)}
     <text x={L} y={H-7} className="c15-axis">{effortDate(rows[0].date,true)}</text>{domain.end!==domain.start&&<text x={W-R} y={H-7} textAnchor="end" className="c15-axis">{effortDate(latest.date,true)}</text>}
    </svg>
    <div className="c15-readout" data-comparing={comparing}>
     <div><span>{comparing?'A · '+effortDate(active.date):effortDate(active.date)}</span><strong>{resultTime(active.duration)}{!comparing&&isBest(active)&&<small className="c15-chip" data-tag="PR">PR</small>}</strong></div>
     {comparing?<><div><span>{comparison?'B · '+effortDate(comparison.date):'Choose another effort'}</span>{comparison&&<strong>{resultTime(comparison.duration)}</strong>}</div>{comparison&&<div><span>B − A</span><strong>{historyGap(comparison.duration,active.duration)}{s}</strong></div>}</>:!isBest(active)&&<div><span>From personal best</span><strong>{historyGap(active.duration,best.duration)}{s}</strong></div>}
     <div className="c15-readout-actions">{!comparing&&<button className="c15-text-button" onClick={()=>{setSelected(active.id);setComparing(true);setSecond(null);}}>Compare</button>}{(comparison??active).analysisHref&&<Link className="c15-button" href={v15Effort((comparison??active).analysisHref!)}>Analyze effort<ArrowUpRight aria-hidden="true"/></Link>}{(selected||comparing)&&<button className="c15-icon-button" onClick={clear} aria-label="Clear history selection"><X/></button>}</div>
    </div>
   </div>
   <div className="c15-card c15-ledger"><header><span>Date</span><select value={order} aria-label="Sort history" onChange={e=>setOrder(e.target.value)}><option value="recent">Recent</option><option value="fastest">Fastest</option></select></header><ol>{ordered.map(r=>{const tag=comparing&&selected===r.id?'A':comparing&&second===r.id?'B':r.id===best.id?'PR':'';return <li key={r.id}><button data-selected={selected===r.id} data-comparison={second===r.id} data-active={active.id===r.id} aria-pressed={selected===r.id||second===r.id} onClick={()=>choose(r.id)} onPointerEnter={()=>setHover(r.id)} onPointerLeave={()=>setHover(null)} aria-label={`Select effort ${effortDate(r.date)}`}><time dateTime={r.date}>{effortDate(r.date,true)}</time>{tag?<small className="c15-chip" data-tag={tag}>{tag}</small>:<span/>}<strong>{resultTime(r.duration)}</strong></button></li>;})}</ol><footer className="c15-ledger-foot">{plural(rows.length,'effort')}</footer></div>
  </div>
 </section>;
}
