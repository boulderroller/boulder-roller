import { useEffect, useMemo, useRef, useState, type PointerEvent } from 'react';
import { powerCurve, powerAxis, type PowerBest } from './v10Model';
import { type AnalysisSample } from './v3Model';
import { timeLabel } from './scenario';
const durationLabel = (t: number) => t < 60 ? `${t}s` : t % 60 === 0 ? `${t / 60} min` : timeLabel(t);
type Band = [number, number];
type Gesture = { pointerId: number; x: number; y: number; index: number; moved: boolean; cancelled: boolean };
const band = (a: number, b: number): Band => [Math.min(a,b), Math.max(a,b)];

export function V10PowerCurve({ points, pending, onEffort }: { points: AnalysisSample[]; pending: boolean; onEffort: (effort:PowerBest)=>void }) {
  const host = useRef<HTMLElement>(null), gesture = useRef<Gesture | null>(null), keyboardStart = useRef<number | null>(null);
  const [width,setWidth] = useState(880);
  const curve = useMemo(() => powerCurve(points), [points]);
  type View = { curve: PowerBest[]; scope: Band | null; draft: Band | null; cursor: number | null };
  const [view,setView] = useState<View>(() => ({ curve, scope: null, draft: null, cursor: null }));
  const current = view.curve === curve;
  const activeScope = current ? view.scope : null, activeDraft = current ? view.draft : null, activeCursor = current ? view.cursor : null;
  const update = (patch: Partial<Omit<View, 'curve'>>) => setView(previous => ({ ...(previous.curve === curve ? previous : { curve, scope: null, draft: null, cursor: null }), ...patch }));
  const setScope = (scope: Band | null) => update({ scope }), setDraft = (draft: Band | null) => update({ draft }), setCursor = (cursor: number | null) => update({ cursor });
  useEffect(() => { if (!host.current) return; const observer = new ResizeObserver(([entry]) => setWidth(Math.max(280,entry.contentRect.width))); observer.observe(host.current); return () => observer.disconnect(); }, []);
  useEffect(() => { setView({ curve, scope: null, draft: null, cursor: null }); gesture.current = null; keyboardStart.current = null; }, [curve]);
  if (!curve.length) return <section ref={host} className="v10-power-room"><h2>Power curve</h2><p>No continuous power measurements lasting one second in this interval.</p></section>;
  const firstIndex = activeScope?.[0] ?? 0, lastIndex = activeScope?.[1] ?? curve.length - 1;
  const minimumDuration = curve[firstIndex].duration, maximumDuration = curve[lastIndex].duration;
  const scale=powerAxis(Math.max(1,...curve.map(p=>p.watts))),maximum=scale.max;
  const height = width < 600 ? 240 : 330, left = width < 600 ? 32 : 48, right = width - 16, bottom = height - 34;
  const logOrigin = Math.log(minimumDuration), logExtent = Math.log(maximumDuration) - logOrigin || 1;
  const x = (p: PowerBest) => left + (Math.log(p.duration) - logOrigin) / logExtent * (right-left);
  const y = (p: PowerBest) => bottom - p.watts / maximum * (bottom-22);
  const visible = curve.slice(firstIndex,lastIndex + 1), active = activeCursor === null ? null : curve[activeCursor];
  const anchors = curve.filter(p => [5,15,30,60,300,1200,3600].includes(p.duration));
  const tickDurations = activeScope ? [minimumDuration, ...[5,30,60,300,1200,3600].filter(d => d > minimumDuration * 1.5 && d < maximumDuration / 1.5), maximumDuration] : (width < 600 ? [1,30,300,1200] : [1,5,30,60,300,1200,3600]).filter(d => d <= maximumDuration);
  const ticks = tickDurations.filter((d,i,all) => i === 0 || x({duration:d} as PowerBest) - x({duration:all[i-1]} as PowerBest) > 42 || i === all.length - 1);
  const locate = (event: PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = Math.max(0,Math.min(1,((event.clientX-rect.left)/rect.width*width-left)/(right-left)));
    const target = logOrigin + ratio * logExtent;
    return visible.reduce((best,p,i) => Math.abs(Math.log(p.duration)-target) < Math.abs(Math.log(curve[best].duration)-target) ? firstIndex+i : best, firstIndex);
  };
  const clear = () => { if (document.activeElement?.tagName === 'BUTTON' && host.current?.contains(document.activeElement)) host.current.querySelector<SVGSVGElement>('svg[role="slider"]')?.focus(); setScope(null); setDraft(null); setCursor(null); keyboardStart.current = null; };
  const apply = (next: Band) => { if (next[0] !== next[1]) setScope(next); setDraft(null); setCursor(null); keyboardStart.current = null; };
  const escape = () => { if (gesture.current || activeDraft) { gesture.current=null; setDraft(null); setCursor(null); keyboardStart.current=null; } else clear(); };
  return <section ref={host} className="v10-power-room" aria-label="Power curve" onKeyDown={e => { if (e.key === 'Escape' && !e.defaultPrevented) { e.preventDefault(); escape(); } }}><header><div><h2>Power curve</h2><p>Your strongest continuous efforts in this recording.</p></div><div className="v10-power-reading" aria-live="polite"><strong>{pending || !active ? '—' : Math.round(active.watts)}<small>W</small></strong><span>{active ? durationLabel(active.duration) : 'Best power'}</span></div></header>
    <div className="v10-duration-scope" aria-live="polite"><span>{activeScope ? `Effort durations · ${durationLabel(minimumDuration)}–${durationLabel(maximumDuration)}` : 'All effort durations'}</span>{activeScope ? <button onClick={clear}>Show all durations</button> : null}</div>
    <svg viewBox={`0 0 ${width} ${height}`} role="slider" tabIndex={pending ? -1 : 0} aria-label="Inspect power curve duration" aria-valuemin={minimumDuration} aria-valuemax={maximumDuration} aria-valuenow={active?.duration ?? minimumDuration} aria-valuetext={active && !pending ? `${durationLabel(active.duration)}, ${Math.round(active.watts)} watts` : 'Arrow keys inspect; Shift and arrows select durations; Enter applies; Escape returns'}
      onPointerDown={e => { if (pending || e.button !== 0 || !e.isPrimary || gesture.current) return; keyboardStart.current=null; setDraft(null); gesture.current={pointerId:e.pointerId,x:e.clientX,y:e.clientY,index:locate(e),moved:false,cancelled:false}; e.currentTarget.setPointerCapture(e.pointerId); }}
      onPointerMove={e => {
        if(pending || gesture.current && gesture.current.pointerId !== e.pointerId) return;
        const g=gesture.current, index=locate(e);
        if(g && e.pointerType==='touch' && !g.moved && Math.abs(e.clientY-g.y)>Math.abs(e.clientX-g.x)+5) g.cancelled=true;
        if(g?.cancelled) return;
        if(g && Math.abs(e.clientX-g.x)>6) { g.moved=true; setDraft(band(g.index,index)); }
        setCursor(index);
      }}
      onPointerUp={e => { const g=gesture.current; if(!g || g.pointerId!==e.pointerId) return; gesture.current=null; if(!g.cancelled) { if(g.moved) apply(band(g.index,locate(e))); else if(activeScope) clear(); else onEffort(curve[locate(e)]); } setDraft(null); }}
      onPointerCancel={() => { gesture.current=null; setDraft(null); setCursor(null); }}
      onPointerLeave={() => { if(!gesture.current) setCursor(null); }} onBlur={() => { setCursor(null); if(!gesture.current) { setDraft(null); keyboardStart.current=null; } }}
      onKeyDown={e => {
        if(pending || !['ArrowLeft','ArrowRight','Home','End','Enter','Escape'].includes(e.key)) return;
        e.preventDefault();
        if(e.key==='Escape') { escape(); return; }
        if(e.key==='Enter') { if(activeDraft) apply(activeDraft); else if(active)onEffort(active); return; }
        const current=activeCursor??firstIndex, next=e.key==='Home'?firstIndex:e.key==='End'?lastIndex:Math.max(firstIndex,Math.min(lastIndex,current+(e.key==='ArrowLeft'?-1:1)));
        if(e.shiftKey) { keyboardStart.current ??= current; setDraft(band(keyboardStart.current,next)); } else { keyboardStart.current=null; setDraft(null); }
        setCursor(next);
      }}>
      {scale.ticks.map(value => {const f=value/maximum;return <g key={value}><line x1={left} x2={right} y1={bottom-f*(bottom-22)} y2={bottom-f*(bottom-22)} className="v10-chart-grid"/><text x={left-8} y={bottom+4-f*(bottom-22)} textAnchor="end">{value}</text></g>;})}
      {!pending && <path className="v10-power-line" d={visible.map((p,i) => `${i?'L':'M'}${x(p)},${y(p)}`).join('')}/>}
      {activeDraft && <rect className="v10-brush" x={x(curve[activeDraft[0]])} y={22} width={Math.max(1,x(curve[activeDraft[1]])-x(curve[activeDraft[0]]))} height={bottom-22}/>}
      {ticks.map((d,i) => <text key={d} x={x({duration:d} as PowerBest)} y={height-9} textAnchor={activeScope && i===0?'start':activeScope && i===ticks.length-1?'end':'middle'}>{durationLabel(d)}</text>)}
      {active && !pending && <><line x1={x(active)} x2={x(active)} y1={22} y2={bottom} className="v10-cursor-line"/><circle cx={x(active)} cy={y(active)} r={4} fill="#613393" stroke="white" strokeWidth={2}/></>}
    </svg><div className="v10-power-window">{active && !pending ? <>Best {durationLabel(active.duration)}: <strong>{timeLabel(active.start)}–{timeLabel(active.end)}</strong> elapsed</> : 'Each point is a best effort over its full duration.'}</div>
    <div className="v10-power-bests">{anchors.map(p => <button key={p.duration} disabled={pending} aria-label={`Analyze best ${durationLabel(p.duration)} effort`} onClick={() => onEffort(p)} onMouseEnter={()=>setCursor(p.duration>=minimumDuration&&p.duration<=maximumDuration?curve.indexOf(p):null)} onMouseLeave={()=>setCursor(null)} onFocus={()=>setCursor(p.duration>=minimumDuration&&p.duration<=maximumDuration?curve.indexOf(p):null)} onBlur={() => setCursor(null)}><span>{durationLabel(p.duration)}</span><strong>{pending?'—':Math.round(p.watts)}<small>W</small></strong></button>)}</div>
    <details className="v10-measurement-details"><summary>About this curve</summary><p>Time-weighted power from this recording, including measured zeros. Each effort requires uninterrupted coverage. Missing power and recording gaps over 30 seconds break coverage; unavailable durations are omitted. The final reading has no invented duration. Chart smoothing is never used in this calculation.</p><p>Drag to zoom the effort-duration axis. Click a point or press Enter to open that effort in Analysis. While zoomed, a plain click returns to all durations; Escape also returns. Arrow keys inspect; hold Shift with arrows to select, then Enter to zoom. A duration range contains separate best efforts, not one continuous ride interval.</p></details>
  </section>;
}
