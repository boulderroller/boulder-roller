import { useEffect, useId, useMemo, useRef, useState, type PointerEvent } from 'react';
import { ArrowUpRight } from 'lucide-react';
import { powerCurve, powerAxis, type PowerBest } from './v12Model';
import { selectPowerEffort, type PowerSelection } from './v12PowerSelection';
import { type AnalysisSample } from './v3Model';
import { timeLabel } from './scenario';
const durationLabel = (t: number) => t < 60 ? `${t}s` : t % 60 === 0 ? `${t / 60} min` : timeLabel(t);
type Gesture = { pointerId: number; x: number; y: number; index: number; moved: boolean; cancelled: boolean };
type View = { curve: PowerBest[]; selection: PowerSelection | null; draft: PowerSelection | null; cursor: number | null };
const fresh = (curve: PowerBest[]): View => ({ curve, selection: null, draft: null, cursor: null });

export function V12PowerCurve({ points, pending, onEffort }: { points: AnalysisSample[]; pending: boolean; onEffort: (effort:PowerBest)=>void }) {
  const host = useRef<HTMLElement>(null), gesture = useRef<Gesture | null>(null), keyboardStart = useRef<number | null>(null);
  const clipId = useId();
  const [width,setWidth] = useState(880);
  const curve = useMemo(() => powerCurve(points), [points]);
  const [view,setView] = useState<View>(() => fresh(curve));
  const state = view.curve === curve ? view : fresh(curve);
  const update = (patch: Partial<Omit<View, 'curve'>>) => setView(previous => ({ ...(previous.curve === curve ? previous : fresh(curve)), ...patch }));
  useEffect(() => { if (!host.current) return; const observer = new ResizeObserver(([entry]) => setWidth(Math.max(280,entry.contentRect.width))); observer.observe(host.current); return () => observer.disconnect(); }, []);
  useEffect(() => { setView(fresh(curve)); gesture.current = null; keyboardStart.current = null; }, [curve]);
  useEffect(() => { if (pending) { gesture.current = null; keyboardStart.current = null; setView(previous => ({...previous, draft:null, cursor:null})); } }, [pending]);
  if (!curve.length) return <section ref={host} className="v12-power-room"><h2>Power curve</h2><p>No continuous power measurements lasting one second in this interval.</p></section>;
  const selection = pending ? null : state.selection, draft = pending ? null : state.draft;
  const active = pending || state.cursor === null ? null : curve[state.cursor];
  const preview = draft ?? selection;
  const minimumDuration = curve[0].duration, maximumDuration = curve[curve.length-1].duration;
  const scale = powerAxis(Math.max(1,...curve.map(p=>p.watts))), maximum = scale.max;
  const height = width < 600 ? 240 : 330, left = width < 600 ? 32 : 48, right = width - 16, bottom = height - 34;
  const logOrigin = Math.log(minimumDuration), logExtent = Math.log(maximumDuration) - logOrigin || 1;
  const x = (p: PowerBest) => left + (Math.log(p.duration) - logOrigin) / logExtent * (right-left);
  const y = (p: PowerBest) => bottom - p.watts / maximum * (bottom-22);
  const anchors = curve.filter(p => [5,15,30,60,300,1200,3600].includes(p.duration));
  const ticks = (width < 600 ? [1,30,300,1200] : [1,5,30,60,300,1200,3600]).filter(d => d <= maximumDuration);
  const path = curve.map((p,i) => `${i?'L':'M'}${x(p)},${y(p)}`).join('');
  const bandLeft = preview ? x(curve[preview.band[0]]) : 0, bandRight = preview ? x(curve[preview.band[1]]) : 0;
  const locate = (event: PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = Math.max(0,Math.min(1,((event.clientX-rect.left)/rect.width*width-left)/(right-left)));
    const target = logOrigin + ratio * logExtent;
    return curve.reduce((best,p,i) => Math.abs(Math.log(p.duration)-target) < Math.abs(Math.log(curve[best].duration)-target) ? i : best, 0);
  };
  const clear = () => { if (document.activeElement?.tagName === 'BUTTON' && host.current?.contains(document.activeElement)) host.current.querySelector<SVGSVGElement>('svg[role="slider"]')?.focus(); update({selection:null,draft:null,cursor:null}); gesture.current=null; keyboardStart.current=null; };
  const apply = (next: PowerSelection | null) => { update({selection:next,draft:null,cursor:null}); keyboardStart.current=null; };
  const cancel = () => { gesture.current=null; keyboardStart.current=null; update({draft:null,cursor:null}); };
  const escape = () => { if (gesture.current || draft) cancel(); else clear(); };
  return <section ref={host} className="v12-power-room" aria-label="Power curve" onKeyDown={e => { if (e.key === 'Escape' && !e.defaultPrevented) { e.preventDefault(); escape(); } }}><header><div><h2>Power curve</h2><p>Your strongest continuous efforts in this recording.</p></div><div className="v12-power-reading"><strong>{active ? Math.round(active.watts) : '—'}<small>W</small></strong><span>{active ? durationLabel(active.duration) : 'At cursor'}</span></div></header>
    <svg viewBox={`0 0 ${width} ${height}`} role="slider" tabIndex={pending ? -1 : 0} aria-label="Inspect power curve duration" aria-disabled={pending} aria-valuemin={minimumDuration} aria-valuemax={maximumDuration} aria-valuenow={active?.duration ?? selection?.effort.duration ?? minimumDuration} aria-valuetext={pending ? 'Loading measurements' : active ? `${durationLabel(active.duration)}, ${Math.round(active.watts)} watts` : selection ? `Selected best ${durationLabel(selection.effort.duration)}, ${Math.round(selection.effort.watts)} watts` : 'Arrow keys inspect; Shift and arrows select; Enter confirms; Escape clears'}
      onPointerDown={e => { if (pending || e.button !== 0 || !e.isPrimary || gesture.current) return; keyboardStart.current=null; update({draft:null}); gesture.current={pointerId:e.pointerId,x:e.clientX,y:e.clientY,index:locate(e),moved:false,cancelled:false}; e.currentTarget.setPointerCapture(e.pointerId); }}
      onPointerMove={e => {
        if(pending || gesture.current && gesture.current.pointerId !== e.pointerId) return;
        const g=gesture.current, index=locate(e);
        if(g && e.pointerType==='touch' && !g.moved && Math.abs(e.clientY-g.y)>Math.abs(e.clientX-g.x)+5) g.cancelled=true;
        if(g?.cancelled) return;
        if(g && Math.abs(e.clientX-g.x)>6) g.moved=true;
        update(g?.moved ? {draft:selectPowerEffort(curve,g.index,index),cursor:index} : {cursor:index});
      }}
      onPointerUp={e => { const g=gesture.current; if(!g || g.pointerId!==e.pointerId) return; gesture.current=null; if(pending || g.cancelled) { cancel(); return; } if(g.moved) apply(selectPowerEffort(curve,g.index,locate(e))); else if(selection) clear(); else apply(selectPowerEffort(curve,locate(e),locate(e))); }}
      onPointerCancel={cancel} onLostPointerCapture={() => { if(gesture.current)cancel(); }}
      onPointerLeave={() => { if(!gesture.current) update({cursor:null}); }} onBlur={() => { if(!gesture.current) { update({cursor:null,draft:null}); keyboardStart.current=null; } }}
      onKeyDown={e => {
        if(pending || !['ArrowLeft','ArrowRight','Home','End','Enter','Escape'].includes(e.key)) return;
        e.preventDefault();
        if(e.key==='Escape') { escape(); return; }
        if(e.key==='Enter') { if(draft) apply(draft); else if(state.cursor!==null) apply(selectPowerEffort(curve,state.cursor,state.cursor)); return; }
        const current=state.cursor??selection?.index??0, next=e.key==='Home'?0:e.key==='End'?curve.length-1:Math.max(0,Math.min(curve.length-1,current+(e.key==='ArrowLeft'?-1:1)));
        if(e.shiftKey) { keyboardStart.current ??= current; update({draft:selectPowerEffort(curve,keyboardStart.current,next),cursor:next}); } else { keyboardStart.current=null; update({draft:null,cursor:next}); }
      }}>
      {scale.ticks.map(value => {const f=value/maximum;return <g key={value}><line x1={left} x2={right} y1={bottom-f*(bottom-22)} y2={bottom-f*(bottom-22)} className="v12-chart-grid"/><text x={left-8} y={bottom+4-f*(bottom-22)} textAnchor="end">{value}</text></g>;})}
      {preview && <><defs><clipPath id={clipId}><rect x={bandLeft-1} y={0} width={Math.max(2,bandRight-bandLeft+2)} height={height}/></clipPath></defs><rect className="v12-curve-band" x={bandLeft} y={22} width={Math.max(1,bandRight-bandLeft)} height={bottom-22}/><line className="v12-curve-edge" x1={bandLeft} x2={bandLeft} y1={22} y2={bottom}/><line className="v12-curve-edge" x1={bandRight} x2={bandRight} y1={22} y2={bottom}/></>}
      {!pending && <><path className={`v12-power-line ${preview ? 'is-context' : ''}`} d={path}/>{preview && <path className="v12-power-line" clipPath={`url(#${clipId})`} d={path}/>}</>}
      {ticks.map(d => <text key={d} x={x({duration:d} as PowerBest)} y={height-9} textAnchor="middle">{durationLabel(d)}</text>)}
      {preview && <g className="v12-curve-endpoint"><line x1={x(preview.effort)} x2={x(preview.effort)} y1={y(preview.effort)} y2={bottom}/><circle cx={x(preview.effort)} cy={y(preview.effort)} r={4} fill="#613393" stroke="white" strokeWidth={2}/></g>}
      {active && <><line x1={x(active)} x2={x(active)} y1={22} y2={bottom} className="v12-cursor-line"/><circle cx={x(active)} cy={y(active)} r={3} fill="white" stroke="#613393" strokeWidth={1.5}/></>}
    </svg>
    <div className="v12-curve-selection" data-selected={selection ? '' : undefined} aria-live="polite">
      {selection ? <><div className="v12-curve-effort"><strong>Best {durationLabel(selection.effort.duration)}</strong><span>{timeLabel(selection.effort.start)}–{timeLabel(selection.effort.end)} elapsed</span></div><div className="v12-curve-average"><span>Average power</span><strong>{Math.round(selection.effort.watts)}<small>W</small></strong></div><button className="v12-curve-analyze" onClick={()=>onEffort(selection.effort)}>Analyze effort<ArrowUpRight size={14}/></button></> : <span className="v12-curve-empty">{pending ? 'Loading measurements' : 'Best efforts'}</span>}
    </div>
    <div className="v12-power-bests">{anchors.map(p => <button key={p.duration} disabled={pending} aria-label={`Select best ${durationLabel(p.duration)} effort`} aria-pressed={selection?.effort===p} onClick={() => apply(selectPowerEffort(curve,curve.indexOf(p),curve.indexOf(p)))} onMouseEnter={()=>update({cursor:curve.indexOf(p)})} onMouseLeave={()=>update({cursor:null})} onFocus={()=>update({cursor:curve.indexOf(p)})} onBlur={() => update({cursor:null})}><span>{durationLabel(p.duration)}</span><strong>{pending?'—':Math.round(p.watts)}<small>W</small></strong></button>)}</div>
    <details className="v12-measurement-details"><summary>About this curve</summary><p>Time-weighted power from this recording, including measured zeros. Each effort requires uninterrupted coverage. Missing power and recording gaps over 30 seconds break coverage; unavailable durations are omitted. The final reading has no invented duration. Chart smoothing is never used in this calculation.</p><p>The horizontal axis is effort duration. A drag selects the best effort at its finishing duration; the shading shows the durations explored. Average power and elapsed start and end belong to that one recorded effort. Choose Analyze effort to open it. Click the selected chart or press Escape to clear. Arrow keys inspect; Shift and arrows extend a selection, and Enter confirms it.</p></details>
  </section>;
}
