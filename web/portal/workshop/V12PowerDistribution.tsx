import { useEffect, useMemo, useRef, useState, type PointerEvent } from 'react';
import { powerDistribution, type PowerBin } from './v12Metrics';
import type { AnalysisSample } from './v3Model';
import { timeLabel } from './scenario';

type Band = [number, number];
type View = { bins: PowerBin[]; scope: Band | null; draft: Band | null; cursor: number | null };
const band = (a: number, b: number): Band => [Math.min(a,b), Math.max(a,b)];

export function V12PowerDistribution({ points, pending }: { points: AnalysisSample[]; pending: boolean }) {
  const host = useRef<HTMLElement>(null), [width, setWidth] = useState(880);
  const { bins, coveredSeconds, unavailable } = useMemo(() => powerDistribution(points), [points]);
  const [view, setView] = useState<View>(() => ({ bins, scope: null, draft: null, cursor: null }));
  const { scope, draft, cursor } = view.bins === bins ? view : { scope: null, draft: null, cursor: null };
  const gesture = useRef<{ id: number; x: number; y: number; index: number; moved: boolean; cancelled: boolean } | null>(null), anchor = useRef<number | null>(null);
  const update = (patch: Partial<Omit<View, 'bins'>>) => setView(previous => ({ ...(previous.bins === bins ? previous : { bins, scope: null, draft: null, cursor: null }), ...patch }));
  const clear = () => { if (document.activeElement?.tagName === 'BUTTON' && host.current?.contains(document.activeElement)) host.current.querySelector<SVGSVGElement>('svg[role="slider"]')?.focus(); update({ scope: null, draft: null, cursor: null }); anchor.current = null; gesture.current = null; };
  useEffect(() => { if (!host.current) return; const observer = new ResizeObserver(([entry]) => setWidth(Math.max(240, entry.contentRect.width))); observer.observe(host.current); return () => observer.disconnect(); }, []);
  useEffect(() => { setView({ bins, scope: null, draft: null, cursor: null }); gesture.current = null; anchor.current = null; }, [bins]);
  if (!bins.length) return <section ref={host} className="v12-power-room v12-distribution"><h2>Power distribution</h2><p>{unavailable ? 'The recorded power range is too large to display.' : 'No covered power measurements in this recording.'}</p></section>;
  const first = scope?.[0] ?? 0, last = scope?.[1] ?? bins.length - 1, visible = bins.slice(first,last + 1);
  const selectedSeconds = visible.reduce((sum,p) => sum + p.seconds,0), active = cursor === null ? null : bins[cursor];
  const height = width < 600 ? 240 : 290, left = 42, right = width - 16, top = 18, bottom = height - 38;
  const x = (index: number) => left + (index - first) / visible.length * (right - left), barWidth = (right - left) / visible.length;
  const maximumMinutes = Math.max(1, Math.ceil(Math.max(...bins.map(p => p.seconds)) / 60 / 5) * 5);
  const y = (seconds: number) => bottom - seconds / (maximumMinutes * 60) * (bottom - top);
  const locate = (e: PointerEvent<SVGSVGElement>) => { const rect = e.currentTarget.getBoundingClientRect(); return Math.max(first, Math.min(last, first + Math.floor(((e.clientX - rect.left) / rect.width * width - left) / (right - left) * visible.length))); };
  const apply = (next: Band) => { update({ scope: next, draft: null, cursor: null }); anchor.current = null; };
  const escape = () => { if (draft || gesture.current) { update({ draft: null, cursor: null }); gesture.current = null; anchor.current = null; } else clear(); };
  const tickStep = Math.max(1, Math.ceil(visible.length / (width < 600 ? 4 : 8)));
  return <section ref={host} className="v12-power-room v12-distribution" aria-label="Power distribution" onKeyDown={e => { if (e.key === 'Escape' && !e.defaultPrevented) { e.preventDefault(); escape(); } }}>
    <header><div><h2>Power distribution</h2><p>Time at each power level</p></div><div className="v12-power-reading"><strong>{pending ? '—' : timeLabel(active?.seconds ?? selectedSeconds)}</strong><span>{active ? `${active.from}–${active.to} W` : scope ? 'Selected power levels' : 'Recorded power'}</span></div></header>
    <div className="v12-duration-scope"><span>{scope ? `${bins[first].from}–${bins[last].to} W` : 'All power levels'}</span>{scope && <button onClick={clear}>Show all power</button>}</div>
    <svg viewBox={`0 0 ${width} ${height}`} role="slider" tabIndex={pending ? -1 : 0} aria-label="Inspect power distribution" aria-valuemin={bins[first].from} aria-valuemax={bins[last].to} aria-valuenow={active?.from ?? bins[first].from} aria-valuetext={pending ? 'Loading power distribution' : active ? `${active.from} to under ${active.to} watts, ${timeLabel(active.seconds)}` : 'Arrow keys inspect; Shift and arrows select power levels; Enter applies; Escape returns'}
      onPointerDown={e => { if (pending || e.button !== 0 || !e.isPrimary || gesture.current) return; anchor.current = null; update({ draft: null }); gesture.current = { id: e.pointerId, x: e.clientX, y: e.clientY, index: locate(e), moved: false, cancelled: false }; e.currentTarget.setPointerCapture(e.pointerId); }}
      onPointerMove={e => { if (pending || gesture.current && gesture.current.id !== e.pointerId) return; const g = gesture.current, index = locate(e); if (g && e.pointerType === 'touch' && !g.moved && Math.abs(e.clientY-g.y)>Math.abs(e.clientX-g.x)+5) g.cancelled=true; if(g?.cancelled) return; if(g && Math.abs(e.clientX-g.x)>6) { g.moved=true; update({ draft:band(g.index,index),cursor:index }); } else update({cursor:index}); }}
      onPointerUp={e => { const g=gesture.current; if(!g || g.id!==e.pointerId) return; gesture.current=null; if(!g.cancelled) { if(g.moved) apply(band(g.index,locate(e))); else if(scope) clear(); else update({cursor:locate(e)}); } update({draft:null}); }}
      onPointerCancel={() => {gesture.current=null;update({draft:null,cursor:null});}}
      onPointerLeave={() => {if(!gesture.current) update({cursor:null});}}
      onBlur={() => {if(!gesture.current) {update({cursor:null,draft:null});anchor.current=null;}}}
      onKeyDown={e => { if(pending || !['ArrowLeft','ArrowRight','Home','End','Enter','Escape'].includes(e.key)) return; e.preventDefault(); if(e.key==='Escape') {escape();return;} if(e.key==='Enter') {if(draft) apply(draft);return;} const current=cursor??first,next=e.key==='Home'?first:e.key==='End'?last:Math.max(first,Math.min(last,current+(e.key==='ArrowLeft'?-1:1))); if(e.shiftKey) {anchor.current??=current;update({draft:band(anchor.current,next),cursor:next});} else {anchor.current=null;update({draft:null,cursor:next});} }}>
      {[0,.25,.5,.75,1].map(f=><g key={f}><line className="v12-chart-grid" x1={left} x2={right} y1={y(maximumMinutes*60*f)} y2={y(maximumMinutes*60*f)}/><text textAnchor="end" x={left-8} y={y(maximumMinutes*60*f)+4}>{+(maximumMinutes*f).toFixed(1)}</text></g>)}
      <text x={left-8} y={top-7} textAnchor="end">min</text>
      {!pending && visible.map((p,i)=><rect key={p.from} className="v12-distribution-bin" data-active={cursor===first+i || undefined} x={x(first+i)+.4} y={y(p.seconds)} width={Math.max(.5,barWidth-.8)} height={bottom-y(p.seconds)}/>)}
      {draft && <rect className="v12-brush" x={x(draft[0])} y={top} width={x(draft[1]+1)-x(draft[0])} height={bottom-top}/>}
      {visible.map((p,i)=>i%tickStep===0 && i<visible.length-tickStep*.35 ? <text key={p.from} x={x(first+i)} y={height-14} textAnchor="start">{p.from}</text> : null)}<text x={right} y={height-14} textAnchor="end">{bins[last].to} W</text>
      {active && !pending && <line className="v12-cursor-line" x1={x(cursor!)+barWidth/2} x2={x(cursor!)+barWidth/2} y1={top} y2={bottom}/>}
    </svg>
    <details className="v12-measurement-details"><summary>About this distribution</summary><p>Each bar covers {bins[0].to - bins[0].from} watts, including its lower boundary. The bars total {timeLabel(coveredSeconds)} of recorded power. Measured zeros count; missing power and gaps over 30 seconds do not. This is covered time, not elapsed ride time.</p><p>Drag across power levels to inspect a narrower range. Click the chart or press Escape to return. Arrow keys inspect; Shift with arrows selects, and Enter applies.</p></details>
  </section>;
}
