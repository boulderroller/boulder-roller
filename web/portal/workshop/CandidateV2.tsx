import { useMemo, type ReactNode, type RefObject } from 'react';
import { ArrowLeft, ChevronRight, Trophy } from 'lucide-react';
import { WorkshopMap } from './WorkshopMap';
import { Elevation } from './Elevation';
import { climbResult, distanceLabel, integer, summarize, timeLabel, type Climb, type Scenario } from './scenario';
import { historyComparison } from './v2Model';
import './candidate-v2.css';

const dateLabel = (date: string) => new Date(date).toLocaleDateString('en-US', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'America/New_York' });
type Result = ReturnType<typeof climbResult>;
type ClimbRow = { climb: Climb; result: Result; number: number };

function Measure({ children, pending }: { children: ReactNode; pending: boolean }) {
  return <span className="v2-measure" data-pending={pending || undefined}><span aria-hidden={pending || undefined}>{children}</span></span>;
}

function Figures({ values, pending, compact = false }: { values: { label: string; value: string | null; unit?: string }[]; pending: boolean; compact?: boolean }) {
  return <dl className={`v2-figures ${compact ? 'v2-dimensions' : ''}`}>{values.filter(v => v.value !== null).map(v => <div key={v.label}>
    <dt>{v.label}</dt><dd><Measure pending={pending}>{v.value}{v.unit && <span className="v2-unit">{v.unit}</span>}</Measure></dd>
  </div>)}</dl>;
}

function PersonalResult({ result, date, pending }: { result: Result; date: string; pending: boolean }) {
  const best = result.improvement !== null && result.improvement > 0;
  return <section className="v2-personal" aria-label="Your result" aria-busy={pending}>
    <div className="v2-section-heading"><h2>Your result</h2><time>{dateLabel(date)}</time></div>
    <dl className="v2-performance">
      <div className="v2-time"><dt>Time</dt><dd><Measure pending={pending}>{timeLabel(result.duration)}</Measure></dd></div>
      {result.power !== null && <div className="v2-power"><dt>Avg power</dt><dd><Measure pending={pending}>{integer(result.power)}<span className="v2-unit">W</span></Measure></dd></div>}
    </dl>
    {best ? <p className="v2-best"><span aria-hidden={pending || undefined} style={pending ? { visibility: 'hidden' } : undefined}><Trophy size={14} /><strong>New best</strong><span>{timeLabel(result.improvement!)} faster</span></span></p>
      : result.previousBest !== null && <p className="v2-previous">Best time <Measure pending={pending}>{timeLabel(result.previousBest)}</Measure></p>}
  </section>;
}

function History({ scenario, climb, result, pending }: { scenario: Scenario; climb: Climb; result: Result; pending: boolean }) {
  const rows = useMemo(() => historyComparison(scenario.ride.startedAt, result.duration, climb.history), [scenario.ride.startedAt, result.duration, climb.history]);
  if (!rows.length) return null;
  return <section className="v2-history" aria-label="Your history" aria-busy={pending}>
    <div className="v2-section-heading"><h2>Your history</h2><span><Measure pending={pending}>{rows.length} rides</Measure></span></div>
    {rows.map((row, i) => <div key={`${row.date}-${i}`} className={`v2-history-row ${row.current ? 'this-ride' : ''}`}>
      <span><Measure pending={pending}>{row.current ? 'This ride' : new Date(row.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'America/New_York' })}</Measure></span>
      <span className="v2-history-track" aria-hidden="true"><i style={{ width: `${row.percent}%`, visibility: pending ? 'hidden' : undefined }} /></span>
      <strong><Measure pending={pending}>{timeLabel(row.duration)}</Measure></strong>
    </div>)}
  </section>;
}

function ClimbList({ rows, onSelect, pending, other = false }: { rows: ClimbRow[]; onSelect: (id: string) => void; pending: boolean; other?: boolean }) {
  if (other && !rows.length) return null;
  return <section className={`v2-climbs ${other ? 'v2-other-climbs' : ''}`} aria-label={other ? 'Other climbs on this ride' : 'Climbs on this ride'}>
    <div className="v2-section-heading"><h2>{other ? 'Other climbs on this ride' : 'Climbs on this ride'}</h2><span><Measure pending={pending}>{rows.length}</Measure></span></div>
    {rows.length ? <div className="v2-climb-list">{rows.map(({ climb, result, number }) => <button key={climb.id} className="v2-climb-row" onClick={() => onSelect(climb.id)} aria-label={`Open ${climb.name}`}>
      <span className="v2-climb-number">{number}</span>
      <span className="v2-climb-copy"><strong>{climb.name}</strong><small>{distanceLabel(result.distance)} km{result.gain !== null && <> · {integer(result.gain)} m</>}{result.grade !== null && <> · {result.grade.toFixed(1)}%</>}</small>
        {result.improvement !== null && result.improvement > 0 && <span className="v2-row-best" aria-hidden={pending || undefined} style={pending ? { visibility: 'hidden' } : undefined}><Trophy size={12} />New best</span>}
      </span>
      <span className="v2-climb-result"><strong><Measure pending={pending}>{timeLabel(result.duration)}</Measure></strong>{result.power !== null && <small><Measure pending={pending}>{integer(result.power)} W</Measure></small>}</span>
      <ChevronRight size={15} />
    </button>)}</div> : <p className="quiet-empty">No climbs on this ride.</p>}
  </section>;
}

export function CandidateV2({ scenario, selected, scrub, onScrub, onSelect, onBack, pending, focusTarget, metrics, onMetrics }: {
  scenario: Scenario; selected: string | null; scrub: number | null; onScrub: (index: number | null) => void;
  onSelect: (id: string) => void; onBack: () => void; pending: boolean; focusTarget: RefObject<HTMLHeadingElement | null>;
  metrics: boolean; onMetrics: () => void;
}) {
  const totals = useMemo(() => summarize(scenario.ride.samples), [scenario]);
  const rows = useMemo(() => scenario.climbs.map((climb, i) => ({ climb, result: climbResult(scenario, climb), number: i + 1 })), [scenario]);
  const active = rows.find(row => row.climb.id === selected), bests = rows.filter(row => (row.result.improvement ?? 0) > 0);
  const dimensions = active ? [
    { label: 'Distance', value: distanceLabel(active.result.distance), unit: 'km' },
    { label: 'Elevation', value: active.result.gain === null ? null : integer(active.result.gain), unit: 'm' },
    { label: 'Avg grade', value: active.result.grade === null ? null : active.result.grade.toFixed(1), unit: '%' },
  ] : [
    { label: 'Distance', value: distanceLabel(totals.distance), unit: 'km' },
    { label: 'Elevation', value: totals.gain === null ? null : integer(totals.gain), unit: 'm' },
    { label: 'Elapsed time', value: timeLabel(totals.duration) },
  ];
  return <main className={`candidate-page v2-page ${active ? 'v2-climb-page' : 'v2-ride-page'}`} aria-busy={pending}>
    <div className="ride-context">{active ? <button onClick={onBack}><ArrowLeft size={14} />{scenario.ride.title}<span>{distanceLabel(totals.distance)} km</span></button> : <span>{dateLabel(scenario.ride.startedAt)}<i>·</i>{scenario.ride.location}</span>}</div>
    <header className="v2-opening">
      <div className="v2-identity"><h1 ref={focusTarget} tabIndex={-1}>{active?.climb.name ?? scenario.ride.title}</h1>
        <p>{active ? scenario.ride.location : <>{rows.length} {rows.length === 1 ? 'climb' : 'climbs'} on this ride{bests.length > 0 && <span className="v2-best-count" aria-hidden={pending || undefined} style={pending ? { visibility: 'hidden' } : undefined}> · <button onClick={() => onSelect(bests[0].climb.id)}>{bests.length} new {bests.length === 1 ? 'best' : 'bests'}</button></span>}</>}</p>
      </div>
      <Figures values={dimensions} pending={pending} compact={!!active} />
    </header>
    <div className="v2-composition">
      {active && <aside className="v2-result-column">
        <PersonalResult result={active.result} date={scenario.ride.startedAt} pending={pending} />
        <History scenario={scenario} climb={active.climb} result={active.result} pending={pending} />
      </aside>}
      <div className="v2-geography-column"><div className="v2-geography"><WorkshopMap scenario={scenario} selected={selected} scrub={scrub} onScrub={onScrub} onSelect={onSelect} v2 />
        <Elevation scenario={scenario} selected={selected} scrub={scrub} onScrub={onScrub} onSelect={onSelect} detail={!!active} v2 />
      </div>
      {active && <div className="ride-overview v2-overview"><div className="overview-heading"><button onClick={onBack}><ArrowLeft size={13} />Whole ride</button><span>{distanceLabel(totals.distance)} km</span></div>
        <Elevation scenario={scenario} selected={selected} scrub={scrub} onScrub={onScrub} onSelect={onSelect} v2 overview />
      </div>}
      {active && <ClimbList rows={rows.filter(row => row.climb.id !== selected)} onSelect={onSelect} pending={pending} other />}
      </div>
      {!active && <aside className="v2-ride-results">
        <ClimbList rows={rows} onSelect={onSelect} pending={pending} />
        {totals.power !== null && <><button className="metrics-toggle" aria-expanded={metrics} onClick={onMetrics}>Ride metrics<ChevronRight size={16} className={metrics ? 'rotated' : ''} /></button>
          {metrics && <Figures values={[{ label: 'Avg power', value: integer(totals.power), unit: 'W' }]} pending={pending} />}</>}
      </aside>}
    </div>
    <footer className="ride-footnote">{active ? 'Route and dimensions show the recorded climb interval.' : scenario.source.kind === 'recorded' ? `Recorded on ${dateLabel(scenario.ride.startedAt)}.` : dateLabel(scenario.ride.startedAt)}</footer>
  </main>;
}
