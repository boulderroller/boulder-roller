import { useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from 'react';
import { ArrowLeft, ArrowRight, BarChart3, Bike, ChevronRight, Map as MapIcon, Pin, SlidersHorizontal, Trophy, X } from 'lucide-react';
import { V5Map } from './V5Map';
import { V5Profile } from './V5Profile';
import { V5Charts } from './V5Charts';
import { climbResult, distanceLabel, integer, summarize, timeLabel, type Climb, type Rider, type Scenario } from './scenario';
import { historyComparison } from './v2Model';
import { analysisSamples, channelSummary, channelValue, nearestIndex, rangeForClimb, scopedSamples, thinRun, traceRuns, type Axis, type Channel, type MapFocus, type SampleRange } from './v3Model';
import { boundSelection } from './v5Selection';
import './candidate-v5.css';

const dateLabel = (date: string) => new Date(date).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'America/New_York' });
function RiderIdentity({ rider, children }: { rider: Rider; children: ReactNode }) {
  const [failedPortrait, setFailedPortrait] = useState<string | null>(null);
  const initials = rider.displayName.split(/\s+/).filter(Boolean).map(part => Array.from(part)[0]).filter(Boolean);
  return <div className="v5-rider"><span className="v5-rider-avatar" aria-hidden="true">{rider.avatarDataUrl && failedPortrait !== rider.avatarDataUrl ? <img src={rider.avatarDataUrl} alt="" onError={() => setFailedPortrait(rider.avatarDataUrl!)} /> : `${initials[0] ?? ''}${initials.length > 1 ? initials.at(-1) : ''}`.toLocaleUpperCase()}</span><div className="v5-rider-text"><strong>{rider.displayName}{rider.source === 'illustrative' && <small>Illustrative</small>}</strong><div>{children}</div></div></div>;
}
function Value({ children, pending }: { children: ReactNode; pending: boolean }) {
  return <span className="v5-value" data-pending={pending || undefined}><span aria-hidden={pending || undefined}>{children}</span></span>;
}
function Figures({ values, pending, className = '' }: { values: { label: string; value: string | null; unit?: string }[]; pending: boolean; className?: string }) {
  return <dl className={`v5-figures ${className}`}>{values.filter(v => v.value !== null).map(v => <div key={v.label}><dt>{v.label}</dt><dd><Value pending={pending}>{v.value}{v.unit && <small>{v.unit}</small>}</Value></dd></div>)}</dl>;
}
function Results({ scenario, selected, pending, onSelect }: { scenario: Scenario; selected: string | null; pending: boolean; onSelect: (id: string) => void }) {
  const rows = scenario.climbs.map((climb, i) => ({ climb, number: i + 1, result: climbResult(scenario, climb) })).filter(row => row.climb.id !== selected);
  if (!rows.length) return null;
  return <section className="v5-results" aria-label={selected ? 'Other climbs on this ride' : 'Climbs on this ride'}><header><h2>{selected ? 'Other climbs' : 'Climbs on this ride'}</h2><span>{rows.length}</span></header>
    {rows.map(({ climb, number, result }) => <button className="v5-result-row" key={climb.id} onClick={() => onSelect(climb.id)} aria-label={`Open ${climb.name}, ${distanceLabel(result.distance)} kilometers${pending ? ', results loading' : `, ${timeLabel(result.duration)} elapsed${result.power === null ? '' : `, ${integer(result.power)} watts`}`}`}>
      <span className="v5-result-name"><i>{number}</i><strong>{climb.name}</strong><ChevronRight size={14} /></span>
      <span className="v5-result-dimensions">{distanceLabel(result.distance)} km{result.gain !== null && <> · {integer(result.gain)} m</>}{result.grade !== null && <> · {result.grade.toFixed(1)}%</>}</span>
      <span className="v5-result-performance"><strong><Value pending={pending}>{timeLabel(result.duration)}</Value></strong>{result.power !== null && <span><Value pending={pending}>{integer(result.power)} <small>W</small></Value></span>}{(result.improvement ?? 0) > 0 && <span className="v5-best"><Value pending={pending}><Trophy size={12} />New best</Value></span>}</span>
    </button>)}
  </section>;
}
function History({ scenario, climb, pending }: { scenario: Scenario; climb: Climb; pending: boolean }) {
  const result = climbResult(scenario, climb), rows = historyComparison(scenario.ride.startedAt, result.duration, climb.history);
  if (!rows.length) return null;
  return <section className="v5-history" aria-label="Your history"><header><h2>Your history</h2><span>{rows.length} rides</span></header>
    {rows.map((row, i) => <div className={`v5-history-row ${row.current ? 'is-current' : ''}`} key={`${row.date}-${i}`}><span>{row.current ? 'This ride' : dateLabel(row.date)}</span><strong><Value pending={pending}>{timeLabel(row.duration)}</Value></strong><span className="v5-history-track" aria-hidden="true"><i style={{ width: `${row.percent}%`, visibility: pending ? 'hidden' : undefined }} /></span></div>)}
    {scenario.source.history === 'illustrative' && <p>Illustrative previous results</p>}
  </section>;
}

export function CandidateV5({ scenario, selected, onSelect, onBack, pending, focusTarget }: {
  scenario: Scenario; selected: string | null; onSelect: (id: string) => void; onBack: () => void; pending: boolean; focusTarget: RefObject<HTMLHeadingElement | null>;
}) {
  const [mode, setMode] = useState<'overview' | 'analysis'>('overview'), [axis, setAxis] = useState<Axis>('distance');
  const [committed, setCommitted] = useState<SampleRange | null>(null), [draft, setDraft] = useState<SampleRange | null>(null);
  const [hover, setHover] = useState<number | null>(null), [pin, setPin] = useState<number | null>(null), [hidden, setHidden] = useState<Channel[]>([]);
  const [editing, setEditing] = useState(false), [from, setFrom] = useState(''), [to, setTo] = useState(''), [error, setError] = useState('');
  const adjustButton = useRef<HTMLButtonElement>(null), editForm = useRef<HTMLFormElement>(null), previous = useRef({ scenario, selected });
  const profileContainer = useRef<HTMLDivElement>(null);
  const samples = useMemo(() => analysisSamples(scenario.ride.samples), [scenario]);
  const climb = scenario.climbs.find(c => c.id === selected), result = useMemo(() => climb ? climbResult(scenario, climb) : null, [scenario, climb]);
  const subject = useMemo(() => rangeForClimb(samples, climb) ?? { startIndex: 0, endIndex: samples.length - 1 }, [samples, climb]);
  const base = useMemo(() => scopedSamples(samples, subject), [samples, subject]);
  const sameContext = previous.current.scenario === scenario && previous.current.selected === selected;
  const selection = sameContext ? committed : null, preview = sameContext ? draft : null;
  const selectedRange = selection ?? subject, displayRange = preview ?? selectedRange;
  const detail = useMemo(() => selection ? scopedSamples(samples, selection) : base, [samples, base, selection]);
  const displayed = useMemo(() => samples.slice(displayRange.startIndex, displayRange.endIndex + 1), [samples, displayRange.startIndex, displayRange.endIndex]);
  const totals = useMemo(() => summarize(base), [base]), interval = useMemo(() => summarize(displayed), [displayed]);
  const stats = useMemo(() => ({ power: channelSummary(displayed, 'power'), basePower: channelSummary(base, 'power'), speed: channelSummary(base, 'speed'), cadence: channelSummary(base, 'cadence') }), [displayed, base]);
  const available = useMemo(() => (['speed', 'power', 'heartRate', 'cadence'] as Channel[]).filter(c => base.some(p => p[c] != null)), [base]);
  const channels = available.filter(c => !hidden.includes(c));
  const candidateCursor = sameContext ? pin ?? hover : null;
  const cursor = candidateCursor !== null && candidateCursor >= subject.startIndex && candidateCursor <= subject.endIndex ? candidateCursor : null;
  const point = cursor === null ? null : samples[cursor];
  const outsideSelection = cursor !== null && selection !== null && (cursor < selection.startIndex || cursor > selection.endIndex);
  useEffect(() => {
    if (!sameContext) { setCommitted(null); setDraft(null); setHover(null); setPin(null); setEditing(false); setError(''); setHidden([]); previous.current = { scenario, selected }; }
  }, [scenario, selected]);
  useEffect(() => { if (editing) editForm.current?.querySelector('input')?.focus(); }, [editing]);
  const clearInspection = () => { setPin(null); setHover(null); };
  const navigate = (id: string) => { setCommitted(null); setDraft(null); clearInspection(); setEditing(false); onSelect(id); };
  const switchMode = (next: typeof mode) => { if (next === mode) return; setMode(next); setCommitted(null); setDraft(null); setEditing(false); clearInspection(); window.scrollTo({ top: 0, behavior: 'instant' }); };
  const selectRange = (next: SampleRange) => { setCommitted(boundSelection(subject, next.startIndex, next.endIndex)); setDraft(null); setMode('analysis'); clearInspection(); };
  const clearRange = () => {
    if (document.activeElement?.classList.contains('v5-clear-interval')) profileContainer.current?.querySelector<SVGSVGElement>('svg[role="slider"]')?.focus();
    if (document.activeElement?.classList.contains('v5-summary-clear')) adjustButton.current?.focus();
    setCommitted(null); setDraft(null); clearInspection(); setEditing(false);
  };
  const onHover = (index: number | null) => { if (pin === null) setHover(index); };
  const onPin = (index: number | null) => { setPin(index); if (index === null) setHover(null); };
  const factor = axis === 'time' ? 60 : 1000, field = axis === 'time' ? 't' : 'd', unit = axis === 'time' ? 'min' : 'km';
  const editRange = () => { setFrom((samples[selectedRange.startIndex][field] / factor).toFixed(3)); setTo((samples[selectedRange.endIndex][field] / factor).toFixed(3)); setError(''); setEditing(true); };
  const closeEditor = () => { setEditing(false); requestAnimationFrame(() => adjustButton.current?.focus()); };
  const applyRange = () => {
    const a = Number(from), b = Number(to), min = samples[subject.startIndex][field] / factor, max = samples[subject.endIndex][field] / factor;
    if (!from.trim() || !to.trim() || !Number.isFinite(a) || !Number.isFinite(b) || a < min - .0005 || b > max + .0005 || b <= a) { setError(`Choose a start before the end, within ${min.toFixed(3)}–${max.toFixed(3)} ${unit}.`); return; }
    selectRange(boundSelection(subject, nearestIndex(samples, a * factor, axis), nearestIndex(samples, b * factor, axis))); closeEditor();
  };
  const focus: MapFocus | null = preview || selection ? { ...displayRange, kind: 'range' } : climb ? { ...subject, kind: 'climb' } : null;
  const bests = useMemo(() => scenario.climbs.filter(c => (climbResult(scenario, c).improvement ?? 0) > 0), [scenario]);
  const mini = useMemo(() => {
    const stats = channelSummary(samples, 'elevation'), min = stats.min ?? 0, extent = Math.max(1, (stats.max ?? 0) - min), distance = Math.max(1, samples.at(-1)!.d);
    return traceRuns(samples, 'elevation').map(run => thinRun(run, 'elevation', 140).map(p => `${p.d / distance * 160},${44 - (p.elevation! - min) / extent * 38}`).join(' '));
  }, [samples]);
  return <div className={`v5-layout v5-${mode} ${climb ? 'v5-climb' : 'v5-ride'}`} onKeyDown={e => { if (e.key === 'Escape' && !e.defaultPrevented) { e.preventDefault(); clearRange(); } }}>
    <aside className="v5-sidebar"><nav aria-label="Ride sections"><button aria-current={mode === 'overview' ? 'page' : undefined} onClick={() => switchMode('overview')}><MapIcon size={17} />Overview</button><button aria-current={mode === 'analysis' ? 'page' : undefined} onClick={() => switchMode('analysis')}><BarChart3 size={17} />Analysis</button></nav>
      <div className="v5-sidebar-climbs"><h2>Climbs on this ride</h2>{scenario.climbs.map((c, i) => <button key={c.id} aria-current={selected === c.id ? 'location' : undefined} onClick={() => navigate(c.id)}><span>{i + 1}</span>{c.name}</button>)}</div>
      {climb && <div className="v5-ride-position"><span>Position on this ride</span><svg viewBox="0 0 160 50" role="img" aria-label={`Climb from ${(base[0].d / 1000).toFixed(1)} to ${(base.at(-1)!.d / 1000).toFixed(1)} kilometers on the full ride`}>{mini.map((points, i) => <polyline key={i} points={points} fill="none" stroke="#a6aba1" strokeWidth="1" />)}<rect x={base[0].d / Math.max(1, samples.at(-1)!.d) * 160} y={1} width={Math.max(2, (base.at(-1)!.d - base[0].d) / Math.max(1, samples.at(-1)!.d) * 160)} height={44} fill="#737e60" opacity=".35" /></svg><small>{(base[0].d / 1000).toFixed(1)}–{(base.at(-1)!.d / 1000).toFixed(1)} km</small></div>}
    </aside>
    <main className="v5-main" aria-busy={pending}>
      <div className="v5-object-bar">{scenario.ride.rider ? <RiderIdentity rider={scenario.ride.rider}>{climb ? <><button className="v5-parent-ride" onClick={() => { clearRange(); onBack(); }}><ArrowLeft size={13} />{scenario.ride.title}</button><ChevronRight size={11} /><span>Climb {scenario.climbs.findIndex(c => c.id === selected) + 1}</span></> : <span>Ride</span>}</RiderIdentity> : <div>{climb ? <button className="v5-parent-ride" onClick={() => { clearRange(); onBack(); }}><ArrowLeft size={15} />{scenario.ride.title}</button> : <><Bike size={17} /><span>{scenario.source.kind === 'recorded' ? 'Recorded ride' : 'Illustrative ride'}</span></>}{climb && <><ChevronRight size={13} /><span>Climb {scenario.climbs.findIndex(c => c.id === selected) + 1}</span></>}</div>}<time dateTime={scenario.ride.startedAt}>{dateLabel(scenario.ride.startedAt)}</time></div>
      <header className="v5-identity"><div className="v5-title"><p>{scenario.ride.location}</p><h1 ref={focusTarget} tabIndex={-1}>{climb?.name ?? scenario.ride.title}</h1><div className="v5-title-detail">{climb && result ? <>{distanceLabel(result.distance)} km<span>·</span>{result.gain === null ? '—' : integer(result.gain)} m elevation<span>·</span>{result.grade === null ? '—' : result.grade.toFixed(1)}% average grade</> : <>{scenario.climbs.length} {scenario.climbs.length === 1 ? 'climb' : 'climbs'}{bests.length > 0 && <button className="v5-best" onClick={() => navigate(bests[0].id)}><Value pending={pending}><Trophy size={13} />{bests.length} new {bests.length === 1 ? 'best' : 'bests'}</Value></button>}</>}</div></div>
        <div className="v5-primary-result"><Figures pending={pending} className={climb ? 'v5-effort-figures' : ''} values={climb && result ? [{ label: 'Your time', value: timeLabel(result.duration) }, { label: 'Avg power', value: result.power === null ? null : integer(result.power), unit: 'W' }] : [{ label: 'Distance', value: distanceLabel(totals.distance), unit: 'km' }, { label: 'Elapsed time', value: timeLabel(totals.duration) }, { label: 'Elevation', value: totals.gain === null ? null : integer(totals.gain), unit: 'm' }]} />
          {result && (result.improvement ?? 0) > 0 && <p className="v5-best v5-personal-best"><Value pending={pending}><Trophy size={14} /><strong>New best</strong><span>{timeLabel(result.improvement!)} faster</span></Value></p>}
        </div>
      </header>
      <div className="v5-supporting"><Figures className="v5-secondary-figures" pending={pending} values={[...(!climb ? [{ label: 'Avg power', value: stats.basePower.average === null ? null : channelValue(stats.basePower.average, 'power'), unit: 'W' }] : []), { label: 'Avg speed', value: stats.speed.average === null ? null : channelValue(stats.speed.average, 'speed'), unit: 'km/h' }, { label: 'Avg cadence', value: stats.cadence.average === null ? null : channelValue(stats.cadence.average, 'cadence'), unit: 'rpm' }]} /><span className="v5-room-label">{pending ? 'Loading results' : mode === 'analysis' ? 'Ride analysis' : climb ? 'Your climb' : 'Ride overview'}</span></div>
      <div className="v5-workspace">
        <div className="v5-geography"><V5Map scenario={scenario} focus={focus} cameraKey={`${mode}:${selection?.startIndex ?? subject.startIndex}:${selection?.endIndex ?? subject.endIndex}`} scrub={cursor} onScrub={onHover} onPin={onPin} onLeave={() => onHover(null)} onSelect={navigate} />
          <div className="v5-elevation-workspace" ref={profileContainer}><div className="v5-profile-heading"><h2>{climb ? 'Climb elevation' : 'Ride elevation'}</h2><div className="v5-profile-controls">{selection && <button className="v5-clear-interval" onClick={clearRange} aria-label="Clear selected interval" aria-keyshortcuts="Escape"><X size={13} />Clear</button>}<div className="v5-axis" role="group" aria-label="Horizontal axis"><button aria-pressed={axis === 'distance'} onClick={() => { setAxis('distance'); if (editing) closeEditor(); }}>Distance</button><button aria-pressed={axis === 'time'} onClick={() => { setAxis('time'); if (editing) closeEditor(); }}>Time</button></div></div></div>
            <V5Profile samples={samples} subject={subject} selection={selection} draft={preview} axis={axis} cursor={cursor} pinned={pin !== null} onHover={onHover} onPin={onPin} onDraft={setDraft} onSelect={selectRange} onClearSelection={clearRange} />
            <div className="v5-climb-marks" aria-label="Climbs along the ride">{scenario.climbs.map((c, i) => <button key={c.id} aria-pressed={selected === c.id} onClick={() => navigate(c.id)}><span>{i + 1}</span><strong>{c.name}</strong><small>{(scenario.ride.samples.find(p => p.t === c.start)!.d / 1000).toFixed(1)} km</small></button>)}</div>
          </div>
          {mode === 'overview' && climb && <V5Charts points={base} channels={['grade']} axis={axis} cursor={cursor} pinned={pin !== null} draft={null} onHover={onHover} onPin={onPin} onDraft={setDraft} onSelect={selectRange} compact />}
        </div>
        {mode === 'overview' && <aside className="v5-results-rail">{climb && <History scenario={scenario} climb={climb} pending={pending} />}<Results scenario={scenario} selected={selected} onSelect={navigate} pending={pending} /><button className="v5-analyze-link" onClick={() => switchMode('analysis')}><BarChart3 size={17} /><span>Analyze {climb ? 'this climb' : 'ride'}<small>Inspect your recorded measurements</small></span><ArrowRight size={15} /></button></aside>}
      </div>
      {mode === 'analysis' && <section className="v5-analysis" aria-label="Ride analysis">
        <div className={`v5-selection-summary ${selection || preview ? 'has-selection' : ''}`} aria-live="polite"><div className="v5-selection-identity"><span>{selection || preview ? 'Selected interval' : climb ? 'Full climb' : 'Whole ride'}</span><strong>{selection || preview ? axis === 'distance' ? `${(displayed[0].d / 1000).toFixed(2)}–${(displayed.at(-1)!.d / 1000).toFixed(2)} km` : `${timeLabel(displayed[0].t)}–${timeLabel(displayed.at(-1)!.t)}` : climb?.name ?? scenario.ride.title}</strong></div>
          <Figures pending={pending} className="v5-selection-figures" values={[{ label: 'Distance', value: distanceLabel(interval.distance), unit: 'km' }, { label: 'Elapsed time', value: timeLabel(interval.duration) }, { label: 'Elevation', value: interval.gain === null ? null : integer(interval.gain), unit: 'm' }, { label: 'Avg power', value: stats.power.average === null ? null : channelValue(stats.power.average, 'power'), unit: 'W' }]} />
          <div className="v5-selection-actions"><button ref={adjustButton} onClick={editRange} aria-expanded={editing}><SlidersHorizontal size={14} />{selection ? 'Adjust' : 'Set interval'}</button>{selection && <button className="v5-summary-clear" onClick={clearRange}><X size={14} />Clear selection</button>}</div>
        </div>
        {editing && <form ref={editForm} className="v5-range-editor" onSubmit={e => { e.preventDefault(); applyRange(); }} onKeyDown={e => { if (e.key === 'Escape') { e.preventDefault(); closeEditor(); } }}><div><strong>Adjust interval</strong><span>{climb ? `Within ${climb.name}` : 'Within this ride'}</span></div><label>From ({unit})<input aria-label={`Interval start in ${axis === 'time' ? 'elapsed minutes' : 'kilometers'}`} type="number" step="any" value={from} onChange={e => setFrom(e.target.value)} /></label><label>To ({unit})<input aria-label={`Interval end in ${axis === 'time' ? 'elapsed minutes' : 'kilometers'}`} type="number" step="any" value={to} onChange={e => setTo(e.target.value)} /></label><button type="submit">Apply</button><button type="button" onClick={closeEditor}>Cancel</button>{error && <p role="alert">{error}</p>}</form>}
        <div className="v5-inspection-bar"><span>{point ? <><Pin size={13} />{outsideSelection ? 'Outside selected interval' : pin !== null ? 'Pinned reading' : 'At cursor'}<strong>{(point.d / 1000).toFixed(2)} km</strong><span>{timeLabel(point.t)}</span></> : 'Move across the charts to inspect. Drag to select an interval.'}</span>{pin !== null && <button onClick={clearInspection}><X size={13} />Release reading</button>}</div>
        <V5Charts points={detail} channels={channels} axis={axis} cursor={cursor} pinned={pin !== null} draft={preview} onHover={onHover} onPin={onPin} onDraft={setDraft} onSelect={selectRange} onClearSelection={clearRange} pending={pending} />
        <div className="v5-channel-controls" role="group" aria-label="Visible measurements">{available.map(c => <label key={c}><input type="checkbox" checked={!hidden.includes(c)} disabled={!hidden.includes(c) && channels.length === 1} onChange={() => setHidden(current => current.includes(c) ? current.filter(x => x !== c) : [...current, c])} />{c === 'heartRate' ? 'Heart rate' : c[0].toUpperCase() + c.slice(1)}</label>)}</div>
        <details className="v5-measurement-details"><summary>About these measurements</summary><p>Chart averages include measured zeros and use covered time. Recording gaps over 30 seconds stay unconnected and are excluded from averages. Elapsed time includes pauses. Grade uses a centered 100 m window.</p><p>Click a reading to pin it. Arrow keys inspect; Enter pins. Escape clears the interval and pinned reading. You can also click outside the highlighted interval in the elevation chart to clear it. Drag inside the elevation selection to move it, or use its two edges to adjust the interval. Selection boundaries stay on recorded samples. Use Time to move a stationary interval.</p>{!available.includes('heartRate') && <p>Heart rate is not included in this ride.</p>}</details>
      </section>}
      <footer className="v5-footnote">{scenario.source.kind === 'recorded' ? 'Recorded GPS and measurements.' : 'Illustrative GPS and measurements.'}{scenario.source.history === 'illustrative' && ' Previous results are illustrative.'}{scenario.ride.rider?.source === 'illustrative' && ' Rider identity is illustrative.'}{climb && ' Climb dimensions follow this ride interval.'}</footer>
    </main>
  </div>;
}
