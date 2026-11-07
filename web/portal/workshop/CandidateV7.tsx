import { useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from 'react';
import { ArrowRight, BarChart3, Bike, ChevronRight, Map as MapIcon, Activity, Heart, SlidersHorizontal, Trophy, X } from 'lucide-react';
import { V7Map } from './V7Map';
import { V7MapFrame } from './V7MapFrame';
import { V7ClimbMarks } from './V7ClimbMarks';
import { V7Profile } from './V7Profile';
import { V7PowerCurve } from './V7PowerCurve';
import { V7Social } from './V7Social';
import { V7Charts } from './V7Charts';
import { climbResult, distanceLabel, integer, summarize, timeLabel, type Rider, type Scenario } from './scenario';
import { analysisSamples, channelSummary, channelValue, nearestIndex, rangeForClimb, scopedSamples, type Axis, type Channel, type MapFocus, type SampleRange } from './v3Model';
import { boundSelection } from './v7Selection';
import './candidate-v7.css';

const dateLabel = (date: string) => new Date(date).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'America/New_York' });
function RiderIdentity({ rider, children }: { rider: Rider; children: ReactNode }) {
  const [failedPortrait, setFailedPortrait] = useState<string | null>(null);
  const initials = rider.displayName.split(/\s+/).filter(Boolean).map(part => Array.from(part)[0]).filter(Boolean);
  return <div className="v7-rider"><span className="v7-rider-avatar" aria-hidden="true">{rider.avatarDataUrl && failedPortrait !== rider.avatarDataUrl ? <img src={rider.avatarDataUrl} alt="" onError={() => setFailedPortrait(rider.avatarDataUrl!)} /> : `${initials[0] ?? ''}${initials.length > 1 ? initials.at(-1) : ''}`.toLocaleUpperCase()}</span><div className="v7-rider-text"><strong>{rider.displayName}{rider.source === 'illustrative' && <small>Illustrative</small>}</strong><div>{children}</div></div></div>;
}
function Value({ children, pending }: { children: ReactNode; pending: boolean }) {
  return <span className="v7-value" data-pending={pending || undefined}><span aria-hidden={pending || undefined}>{children}</span></span>;
}
function Figures({ values, pending, className = '' }: { values: { label: string; value: string | null; unit?: string }[]; pending: boolean; className?: string }) {
  return <dl className={`v7-figures ${className}`}>{values.filter(v => v.value !== null).map(v => <div key={v.label}><dt>{v.label}</dt><dd><Value pending={pending}>{v.value}{v.unit && <small>{v.unit}</small>}</Value></dd></div>)}</dl>;
}
function Results({ scenario, selected, pending, onSelect }: { scenario: Scenario; selected: string | null; pending: boolean; onSelect: (id: string) => void }) {
  const rows = scenario.climbs.map((climb, i) => ({ climb, number: i + 1, result: climbResult(scenario, climb) })).filter(row => row.climb.id !== selected);
  if (!rows.length) return null;
  return <section className="v7-results" aria-label={selected ? 'Other climbs on this ride' : 'Climbs on this ride'}><header><h2>{selected ? 'Other climbs' : 'Climbs on this ride'}</h2><span>{rows.length}</span></header>
    {rows.map(({ climb, number, result }) => <button className="v7-result-row" key={climb.id} onClick={() => onSelect(climb.id)} aria-label={`Open ${climb.name}, ${distanceLabel(result.distance)} kilometers${pending ? ', results loading' : `, ${timeLabel(result.duration)} elapsed${result.power === null ? '' : `, ${integer(result.power)} watts`}`}`}>
      <span className="v7-result-name"><i>{number}</i><strong>{climb.name}</strong><ChevronRight size={14} /></span>
      <span className="v7-result-dimensions">{distanceLabel(result.distance)} km{result.gain !== null && <> · {integer(result.gain)} m</>}{result.grade !== null && <> · {result.grade.toFixed(1)}%</>}</span>
      <span className="v7-result-performance"><strong><Value pending={pending}>{timeLabel(result.duration)}</Value></strong>{result.power !== null && <span><Value pending={pending}>{integer(result.power)} <small>W</small></Value></span>}{(result.improvement ?? 0) > 0 && <span className="v7-best"><Value pending={pending}><Trophy size={12} />New best</Value></span>}</span>
    </button>)}
  </section>;
}

export function CandidateV7({ scenario, selected, onSelect, onBack, pending, focusTarget }: {
  scenario: Scenario; selected: string | null; onSelect: (id: string) => void; onBack: () => void; pending: boolean; focusTarget: RefObject<HTMLHeadingElement | null>;
}) {
  const [mode, setMode] = useState<'overview' | 'analysis' | 'power' | 'heartRate'>(selected ? 'analysis' : 'overview'), [axis, setAxis] = useState<Axis>('distance');
  const [committed, setCommitted] = useState<SampleRange | null>(null), [draft, setDraft] = useState<SampleRange | null>(null);
  const [hover, setHover] = useState<number | null>(null), [hidden, setHidden] = useState<Channel[]>([]);
  const [editing, setEditing] = useState(false), [from, setFrom] = useState(''), [to, setTo] = useState(''), [error, setError] = useState('');
  const adjustButton = useRef<HTMLButtonElement>(null), editForm = useRef<HTMLFormElement>(null), previous = useRef(scenario);
  const profileContainer = useRef<HTMLDivElement>(null);
  const samples = useMemo(() => analysisSamples(scenario.ride.samples), [scenario]);
  const climb = scenario.climbs.find(c => c.id === selected);
  const climbRange = useMemo(() => rangeForClimb(samples, climb), [samples, climb]);
  const subject = useMemo(() => ({ startIndex: 0, endIndex: samples.length - 1 }), [samples]);
  const base = useMemo(() => scopedSamples(samples, subject), [samples, subject]);
  const sameContext = previous.current === scenario;
  const selection = sameContext ? committed ?? climbRange : null, preview = sameContext ? draft : null;
  const selectedRange = selection ?? subject, displayRange = preview ?? selectedRange;
  const detail = useMemo(() => selection ? scopedSamples(samples, selection) : base, [samples, base, selection]);
  const displayed = useMemo(() => samples.slice(displayRange.startIndex, displayRange.endIndex + 1), [samples, displayRange.startIndex, displayRange.endIndex]);
  const totals = useMemo(() => summarize(base), [base]), interval = useMemo(() => summarize(displayed), [displayed]);
  const stats = useMemo(() => ({ power: channelSummary(displayed, 'power'), basePower: channelSummary(base, 'power'), speed: channelSummary(base, 'speed'), cadence: channelSummary(base, 'cadence') }), [displayed, base]);
  const available = useMemo(() => (['speed', 'power', 'heartRate', 'cadence'] as Channel[]).filter(c => base.some(p => p[c] != null)), [base]);
  const channels = available.filter(c => !hidden.includes(c));
  const candidateCursor = sameContext ? hover : null;
  const cursor = candidateCursor !== null && candidateCursor >= subject.startIndex && candidateCursor <= subject.endIndex ? candidateCursor : null;
  const point = cursor === null ? null : samples[cursor];
  const outsideSelection = cursor !== null && selection !== null && (cursor < selection.startIndex || cursor > selection.endIndex);
  useEffect(() => {
    if (!sameContext) { if ((mode === 'heartRate' && !available.includes('heartRate')) || (mode === 'power' && !available.includes('power'))) setMode('analysis'); setCommitted(null); setDraft(null); setHover(null); setEditing(false); setError(''); setHidden([]); previous.current = scenario; }
  }, [scenario]);
  useEffect(() => { if (editing) editForm.current?.querySelector('input')?.focus(); }, [editing]);
  const clearInspection = () => { setHover(null); };
  const navigate = (id: string) => { if (mode === 'overview') requestAnimationFrame(() => { window.scrollTo({ top: 0, behavior: 'instant' }); focusTarget.current?.focus({ preventScroll: true }); }); setCommitted(null); setDraft(null); clearInspection(); setEditing(false); setMode('analysis'); if (selected === id) onBack(); else onSelect(id); };
  const switchMode = (next: typeof mode) => { if (next === mode) return; setMode(next); onBack(); setCommitted(null); setDraft(null); setEditing(false); clearInspection(); window.scrollTo({ top: 0, behavior: 'instant' }); };
  const selectRange = (next: SampleRange) => { onBack(); setCommitted(boundSelection(subject, next.startIndex, next.endIndex)); setDraft(null); setMode(current => current === 'heartRate' ? current : 'analysis'); clearInspection(); };
  const clearRange = () => {
    if (document.activeElement?.classList.contains('v7-clear-interval')) profileContainer.current?.querySelector<SVGSVGElement>('svg[role="slider"]')?.focus();
    if (document.activeElement?.classList.contains('v7-summary-clear')) adjustButton.current?.focus();
    onBack(); setCommitted(null); setDraft(null); clearInspection(); setEditing(false);
  };
  const onHover = (index: number | null) => setHover(index);
  const factor = axis === 'time' ? 60 : 1000, field = axis === 'time' ? 't' : 'd', unit = axis === 'time' ? 'min' : 'km';
  const editRange = () => { setFrom((samples[selectedRange.startIndex][field] / factor).toFixed(3)); setTo((samples[selectedRange.endIndex][field] / factor).toFixed(3)); setError(''); setEditing(true); };
  const closeEditor = () => { setEditing(false); requestAnimationFrame(() => adjustButton.current?.focus()); };
  const applyRange = () => {
    const a = Number(from), b = Number(to), min = samples[subject.startIndex][field] / factor, max = samples[subject.endIndex][field] / factor;
    if (!from.trim() || !to.trim() || !Number.isFinite(a) || !Number.isFinite(b) || a < min - .0005 || b > max + .0005 || b <= a) { setError(`Choose a start before the end, within ${min.toFixed(3)}–${max.toFixed(3)} ${unit}.`); return; }
    selectRange(boundSelection(subject, nearestIndex(samples, a * factor, axis), nearestIndex(samples, b * factor, axis))); closeEditor();
  };
  const focus: MapFocus | null = preview || selection ? { ...displayRange, kind: climb && !committed && !preview ? 'climb' : 'range' } : null;
  const bests = useMemo(() => scenario.climbs.filter(c => (climbResult(scenario, c).improvement ?? 0) > 0), [scenario]);
  return <div className={`v7-layout v7-${mode} ${mode !== 'overview' ? 'v7-analysis' : ''} v7-ride`} onPointerDown={e => { if (!(e.target as Element).closest('.v7-map, .v7-profile, .v7-charts, .v7-power-room')) clearInspection(); }} onKeyDown={e => { if (e.key === 'Escape' && !e.defaultPrevented) { e.preventDefault(); clearRange(); } }}>
    <aside className="v7-sidebar"><nav aria-label="Ride sections"><button aria-current={mode === 'overview' ? 'page' : undefined} onClick={() => switchMode('overview')}><MapIcon size={17} />Overview</button><button aria-current={mode === 'analysis' ? 'page' : undefined} onClick={() => switchMode('analysis')}><BarChart3 size={17} />Analysis</button></nav>
      <nav className="v7-sidebar-tools" aria-label="Recorded analysis">{available.includes('power') && <button aria-current={mode === 'power' ? 'page' : undefined} onClick={() => switchMode('power')}><Activity size={17}/>Power curve</button>}{available.includes('heartRate') && <button aria-current={mode === 'heartRate' ? 'page' : undefined} onClick={() => switchMode('heartRate')}><Heart size={17}/>Heart rate</button>}</nav>

    </aside>
    <main className="v7-main" aria-busy={pending}>
      <div className="v7-object-bar">{scenario.ride.rider ? <RiderIdentity rider={scenario.ride.rider}><span>Ride</span></RiderIdentity> : <div><Bike size={17} /><span>{scenario.source.kind === 'recorded' ? 'Recorded ride' : 'Illustrative ride'}</span></div>}<div className="v7-object-actions"><V7Social key={scenario.id} ride={scenario.ride}/></div></div>
      <header className="v7-identity"><div className="v7-title"><p>{scenario.ride.location}<span> · </span><time dateTime={scenario.ride.startedAt}>{dateLabel(scenario.ride.startedAt)}</time></p><h1 ref={focusTarget} tabIndex={-1}>{scenario.ride.title}</h1><div className="v7-title-detail">{scenario.climbs.length} {scenario.climbs.length === 1 ? 'climb' : 'climbs'}{bests.length > 0 && <button className="v7-best" onClick={() => navigate(bests[0].id)}><Value pending={pending}><Trophy size={13} />{bests.length} new {bests.length === 1 ? 'best' : 'bests'}</Value></button>}</div></div>
        <div className="v7-primary-result"><Figures pending={pending} values={[{ label: 'Distance', value: distanceLabel(totals.distance), unit: 'km' }, { label: 'Elapsed time', value: timeLabel(totals.duration) }, { label: 'Elevation', value: totals.gain === null ? null : integer(totals.gain), unit: 'm' }]} />
          <Figures className="v7-secondary-figures" pending={pending} values={[{ label: 'Avg power', value: stats.basePower.average === null ? null : channelValue(stats.basePower.average, 'power'), unit: 'W' }, { label: 'Avg cadence', value: stats.cadence.average === null ? null : channelValue(stats.cadence.average, 'cadence'), unit: 'rpm' }, { label: 'Avg speed', value: stats.speed.average === null ? null : channelValue(stats.speed.average, 'speed'), unit: 'km/h' }]} />
        </div>
      </header>

      {mode !== 'power' && <div className="v7-workspace">
        <div className="v7-geography"><V7MapFrame adjustable={mode !== 'overview'}><V7Map scenario={scenario} focus={focus} cameraKey={`${mode}:${selection?.startIndex ?? subject.startIndex}:${selection?.endIndex ?? subject.endIndex}`} scrub={cursor} onScrub={onHover} onLeave={() => onHover(null)} onSelect={navigate} onClearSelection={clearRange} /></V7MapFrame>
          <div className="v7-elevation-workspace" ref={profileContainer}><div className="v7-profile-heading"><h2>Ride elevation</h2><div className="v7-profile-controls">{selection && <button className="v7-clear-interval" onClick={clearRange} aria-label="Clear selected interval" aria-keyshortcuts="Escape"><X size={13} />Clear</button>}<div className="v7-axis" role="group" aria-label="Horizontal axis"><button aria-pressed={axis === 'distance'} onClick={() => { setAxis('distance'); if (editing) closeEditor(); }}>Distance</button><button aria-pressed={axis === 'time'} onClick={() => { setAxis('time'); if (editing) closeEditor(); }}>Time</button></div></div></div>
            <V7Profile samples={samples} subject={subject} selection={selection} draft={preview} axis={axis} cursor={cursor} onHover={onHover} onDraft={setDraft} onSelect={selectRange} onClearSelection={clearRange} />
            {mode !== 'overview' && <V7ClimbMarks scenario={scenario} samples={samples} axis={axis} selected={selected} onSelect={navigate}/>}
          </div>

        </div>
        {mode === 'overview' && <aside className="v7-results-rail"><Results scenario={scenario} selected={null} onSelect={navigate} pending={pending} /><button className="v7-analyze-link" onClick={() => switchMode('analysis')}><BarChart3 size={17} /><span>Analyze ride<small>Inspect your recorded measurements</small></span><ArrowRight size={15} /></button></aside>}
      </div>}
      {(mode === 'analysis' || mode === 'heartRate') && <section className="v7-analysis" aria-label="Ride analysis">
        <div className={`v7-selection-summary ${selection || preview ? 'has-selection' : ''}`} aria-live="polite"><div className="v7-selection-identity"><span>{preview ? 'Selecting' : climb && !committed ? 'Climb' : selection ? 'Selection' : 'Whole ride'}</span><strong>{climb && !committed && !preview ? climb.name : selection || preview ? axis === 'distance' ? `${(displayed[0].d / 1000).toFixed(2)}–${(displayed.at(-1)!.d / 1000).toFixed(2)} km` : `${timeLabel(displayed[0].t)}–${timeLabel(displayed.at(-1)!.t)}` : climb?.name ?? scenario.ride.title}</strong></div>
          <Figures pending={pending} className="v7-selection-figures" values={[{ label: 'Distance', value: distanceLabel(interval.distance), unit: 'km' }, { label: 'Elapsed time', value: timeLabel(interval.duration) }, { label: 'Elevation', value: interval.gain === null ? null : integer(interval.gain), unit: 'm' }, { label: 'Avg power', value: stats.power.average === null ? null : channelValue(stats.power.average, 'power'), unit: 'W' }]} />
          <div className="v7-selection-actions"><button ref={adjustButton} onClick={editRange} aria-expanded={editing}><SlidersHorizontal size={14} />{selection ? 'Adjust' : 'Set interval'}</button>{selection && <button className="v7-summary-clear" onClick={clearRange}><X size={14} />Clear selection</button>}</div>
        </div>
        {editing && <form ref={editForm} className="v7-range-editor" onSubmit={e => { e.preventDefault(); applyRange(); }} onKeyDown={e => { if (e.key === 'Escape') { e.preventDefault(); closeEditor(); } }}><div><strong>Adjust interval</strong><span>Within this ride</span></div><label>From ({unit})<input aria-label={`Interval start in ${axis === 'time' ? 'elapsed minutes' : 'kilometers'}`} type="number" step="any" value={from} onChange={e => setFrom(e.target.value)} /></label><label>To ({unit})<input aria-label={`Interval end in ${axis === 'time' ? 'elapsed minutes' : 'kilometers'}`} type="number" step="any" value={to} onChange={e => setTo(e.target.value)} /></label><button type="submit">Apply</button><button type="button" onClick={closeEditor}>Cancel</button>{error && <p role="alert">{error}</p>}</form>}
        <div className="v7-inspection-bar"><span>{point ? <>{outsideSelection ? 'Outside selected interval' : 'At cursor'}<strong>{(point.d / 1000).toFixed(2)} km</strong><span>{timeLabel(point.t)}</span></> : 'Move to inspect. Drag to select. Click to return.'}</span><small>Traces adapt to this view · readings remain exact</small></div>
        <V7Charts points={detail} channels={mode === 'heartRate' ? ['heartRate'] : channels} axis={axis} cursor={cursor} draft={preview} selected={!!selection} onHover={onHover} onDraft={setDraft} onSelect={selectRange} onClearSelection={clearRange} pending={pending} />
        <div hidden={mode === 'heartRate'} className="v7-channel-controls" role="group" aria-label="Visible measurements">{available.map(c => <label key={c}><input type="checkbox" checked={!hidden.includes(c)} disabled={!hidden.includes(c) && channels.length === 1} onChange={() => setHidden(current => current.includes(c) ? current.filter(x => x !== c) : [...current, c])} />{c === 'heartRate' ? 'Heart rate' : c[0].toUpperCase() + c.slice(1)}</label>)}</div>
        <details className="v7-measurement-details"><summary>About these measurements</summary><p>Chart averages include measured zeros and use covered time. Recording gaps over 30 seconds stay unconnected and are excluded from averages. Elapsed time includes pauses. Grade uses a centered 100 m window.</p><p>The cursor follows freely. Arrow keys inspect; leaving the chart clears the reading. Hold Shift with arrows to select in the measurement charts, then Enter to apply. A plain click in the map or chart, or Escape, returns to the whole ride. Drag inside the elevation selection to move it, or use its two edges to adjust the interval. Selection boundaries stay on recorded samples. Use Time to move a stationary interval.</p>{!available.includes('heartRate') && <p>Heart rate is not included in this ride.</p>}</details>
      </section>}
      {mode === 'power' && <V7PowerCurve points={base} pending={pending}/>}
      <footer className="v7-footnote">{scenario.source.kind === 'recorded' ? 'Recorded GPS and measurements.' : 'Illustrative GPS and measurements.'}{scenario.source.history === 'illustrative' && ' Previous results are illustrative.'}{scenario.ride.rider?.source === 'illustrative' && ' Rider identity is illustrative.'}</footer>
    </main>
  </div>;
}
