import { EstimatedValue } from '../components/EstimatedValue';
import { Slot, SlotRows } from '../components/loading/Slot';
import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { PortalTruthPill } from '../components/portal/PortalSpine';
import { useAuth } from '../contexts/AuthContext';
import { usePowerCurve, useRidingDays, useTrainingData } from '../hooks/queries';
import { useThresholdAuthority } from '../hooks/useThresholdAuthority';
import { useFormatters, type Formatters } from '../hooks/useFormatters';
import PowerCurveChart from '../components/training/PowerCurveChart';
import ConsistencyHeatmap, { heatmapSummary } from '../components/training/ConsistencyHeatmap';
import LoadFigure, { type LoadDay } from '../components/training/LoadFigure';
import { ABSENT_VALUE, formatDate, formatFixed, formatInteger, formatRaceTime, formatWatts } from '../lib/formatters';

// Training — figures on paper (Tim-ratified 2026-09-03). Four sheets and no
// dashboard: Load (the trio, then daily load as a figure whose window and
// read are words), Consistency (the heatmap), Threshold (rows in the
// ratified vocabulary), Power curve (the landed figure). State words are
// data, so ink or gray, never cobalt; cobalt only on a scrub. Nothing on
// this page explains itself; the numbers do.

type LoadWindow = '4-weeks' | '26-weeks' | 'year';
type LoadRead = 'stress' | 'time' | 'distance' | 'climbing';

const WINDOWS: { id: LoadWindow; label: string; days: number }[] = [
  { id: '4-weeks', label: '4 weeks', days: 28 },
  { id: '26-weeks', label: '26 weeks', days: 182 },
  { id: 'year', label: 'Year', days: 365 },
];
const READS: { id: LoadRead; label: string }[] = [
  { id: 'stress', label: 'Stress' },
  { id: 'time', label: 'Time' },
  { id: 'distance', label: 'Distance' },
  { id: 'climbing', label: 'Climbing' },
];
const SERIES_DAYS = 365;
const CONSISTENCY_WEEKS = 44;

function readWindow(value: string | null): LoadWindow {
  return WINDOWS.some((w) => w.id === value) ? (value as LoadWindow) : '26-weeks';
}

function readRead(value: string | null): LoadRead {
  return READS.some((r) => r.id === value) ? (value as LoadRead) : 'stress';
}

/** A local calendar day as one number (year, month, day), for joining series without building dates as text. */
function dayKey(date: Date): number {
  return date.getFullYear() * 10_000 + (date.getMonth() + 1) * 100 + date.getDate();
}

function dayKeyOfIso(iso: string): number | null {
  const date = new Date(`${iso}T00:00:00`);
  return Number.isNaN(date.getTime()) ? null : dayKey(date);
}

function formatMetric(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '';
  return formatFixed(value, 0);
}

/** The last `count` days ending today, oldest first, with the read's value per day. */
function seriesFor(count: number, valueByDay: Map<number, number | null>, end?: string, complete = true): LoadDay[] {
  const today = end ? new Date(`${end.slice(0, 10)}T00:00:00`) : new Date();
  const days: LoadDay[] = [];
  for (let offset = count - 1; offset >= 0; offset -= 1) {
    const date = new Date(today.getFullYear(), today.getMonth(), today.getDate() - offset);
    days.push({ date, value: valueByDay.has(dayKey(date)) ? valueByDay.get(dayKey(date))! : (complete ? 0 : null) });
  }
  return days;
}

function byIsoDay(entries: Array<{ date: string; value: number | null | undefined }>): Map<number, number | null> {
  const byDay = new Map<number, number | null>();
  for (const entry of entries) {
    const key = dayKeyOfIso(entry.date);
    if (key !== null) byDay.set(key, entry.value != null && Number.isFinite(entry.value) ? entry.value : null);
  }
  return byDay;
}

function readFormatters(read: LoadRead, formatters: Formatters): { value: (v: number) => string; tick: (v: number) => string; word: string } {
  if (read === 'time') return { value: (v) => formatters.durationCompact(v), tick: (v) => formatters.durationCompact(v), word: 'riding days' };
  if (read === 'distance') return { value: (v) => formatters.distance(v), tick: (v) => formatters.distanceValue(v), word: 'riding days' };
  if (read === 'climbing') return { value: (v) => formatters.elevation(v), tick: (v) => formatters.elevationValue(v), word: 'riding days' };
  return { value: (v) => formatMetric(v), tick: (v) => formatMetric(v), word: 'days with stress' };
}

function Word({ label, active, faint, onClick }: { label: string; active: boolean; faint?: boolean; onClick: () => void }) {
  return (
    <button type="button" className="training-word" aria-pressed={active} disabled={faint} onClick={onClick}>
      {label}
    </button>
  );
}

function Retry({ query }: { query: { isFetching: boolean; refetch: () => Promise<unknown> } }) {
  return <button type="button" className="training-sheet__retry" disabled={query.isFetching} aria-busy={query.isFetching} onClick={() => void query.refetch()}>{query.isFetching ? 'Retrying' : 'Try again'}</button>;
}

export default function DataCore() {
  const { user } = useAuth();
  const formatters = useFormatters();
  const [searchParams, setSearchParams] = useSearchParams();
  const window = readWindow(searchParams.get('window'));
  const read = readRead(searchParams.get('read'));
  const windowDays = WINDOWS.find((w) => w.id === window)?.days ?? 182;

  const training = useTrainingData(SERIES_DAYS);
  const ridingDays = useRidingDays(SERIES_DAYS);
  const powerCurve = usePowerCurve();
  const thresholdOwnerKey = user ? `${user.id}:${user.wallet}` : null;
  const thresholdQuery = useThresholdAuthority(thresholdOwnerKey);
  const threshold = thresholdQuery.data;

  const snapshot = training.data?.snapshot ?? null;
  const fitnessMetrics = training.data?.fitnessMetrics ?? null;
  const modelMetrics = snapshot?.fitnessMetrics ?? null;
  const trainingThreshold = fitnessMetrics?.trainingThreshold;
  const trainingLoad = snapshot?.trainingLoad ?? training.data?.trainingLoad ?? null;
  const dailyLoads = useMemo(() => trainingLoad?.dailyLoads ?? [], [trainingLoad]);
  const initialLoading = training.isLoading && !training.data;
  const trainingError = training.error instanceof Error ? training.error.message : null;
  const establishing = !snapshot || fitnessMetrics?.trainingAvailable === false;
  const thresholdPending = fitnessMetrics?.thresholdTrainingState === 'pending';
  const thresholdEstablished = Boolean(snapshot);

  const valueByDay = useMemo(() => {
    if (read === 'stress') return byIsoDay(dailyLoads.map((load) => ({ date: load.date, value: load.totalTss })));
    if (read === 'time') return byIsoDay((ridingDays.data?.days ?? []).map((day) => ({ date: day.date, value: day.movingS })));
    return byIsoDay((ridingDays.data?.days ?? []).map(day => ({ date: day.date, value: read === 'distance' ? day.distanceM : day.elevationGainM })));
  }, [dailyLoads, read, ridingDays.data]);
  const historyEnd = snapshot?.asOf ?? dailyLoads.map(load => load.date).sort().at(-1);
  const series = useMemo(() => seriesFor(windowDays, valueByDay, read === 'stress' ? historyEnd : ridingDays.data?.endDate, read === 'stress' ? snapshot?.coverage.completeness === 'complete' : !ridingDays.data?.undatedCount), [valueByDay, windowDays, read, historyEnd, snapshot, ridingDays.data]);
  const format = useMemo(() => readFormatters(read, formatters), [formatters, read]);
  const last7 = series.slice(-7).reduce((sum, day) => sum + (day.value ?? 0), 0);
  const previous7 = series.slice(-14, -7).reduce((sum, day) => sum + (day.value ?? 0), 0);
  const change = last7 - previous7;
  const daysWith = series.filter((day) => day.value !== null && day.value > 0).length;
  const readQuery = read === 'stress' ? training : ridingDays;
  const readHasData = readQuery.data !== undefined;
  const readUnavailable = readQuery.isError || readQuery.fetchStatus === 'paused';
  const readLoading = !readHasData && !readUnavailable;
  const readErrorLabel = read === 'stress' ? 'Could not load training' : read === 'time' ? 'Could not load riding days.' : 'Ride history unavailable';
  const figureEmpty = readHasData && (read === 'stress' ? establishing || !historyEnd : daysWith === 0);
  const truthWord = readLoading ? <Slot /> : readUnavailable ? readHasData ? 'Last loaded' : ABSENT_VALUE : thresholdPending && read === 'stress' ? 'Pending' : 'Ride based';

  const heatmapDays = useMemo(() => (
    (ridingDays.data?.days ?? []).map((day) => ({ date: day.date, value: day.movingS, rides: day.rideCount }))
  ), [ridingDays.data]);
  const heatmapLoadDays = useMemo(() => dailyLoads.map((load) => ({ date: load.date, value: load.totalTss, rides: 0 })), [dailyLoads]);
  const heatmapRead = searchParams.get('consistency') === 'load' && thresholdEstablished ? 'load' : 'time';
  const heatmapSeries = heatmapRead === 'time' ? heatmapDays : heatmapLoadDays;
  const heatmapQuery = heatmapRead === 'time' ? ridingDays : training;
  const heatmapEnd = heatmapRead === 'time' ? ridingDays.data?.endDate ?? null : historyEnd?.slice(0, 10) ?? null;
  const heatmapUnavailable = heatmapQuery.isError || heatmapQuery.fetchStatus === 'paused';
  const heatmapLoading = heatmapQuery.data === undefined && !heatmapUnavailable;
  const summary = heatmapEnd ? heatmapSummary(heatmapSeries, heatmapEnd, CONSISTENCY_WEEKS) : { activeDays: 0, streak: 0 };

  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(searchParams);
    if (value === null) next.delete(key);
    else next.set(key, value);
    setSearchParams(next, { replace: true });
  };

  const curve = powerCurve.data;
  const sampled = curve?.sampledRides ?? 0;
  const curveMeta = powerCurve.isLoading
    ? <Slot />
    : curve?.available
      ? `${formatInteger(sampled)} ${sampled === 1 ? 'ride' : 'rides'} with power`
      : ABSENT_VALUE;

  return (
    <section className="training-page" aria-label="Training" aria-busy={initialLoading}>
      <div className="training-page__column">
        <section className="training-sheet training-load" aria-labelledby="training-load-heading">
          <div className="training-sheet__head">
            <h2 id="training-load-heading" className="training-sheet__eyebrow">Load</h2>
            <div className="training-words" aria-label="Load window">
              {WINDOWS.map((option) => (
                <Word key={option.id} label={option.label} active={window === option.id} onClick={() => setParam('window', option.id === '26-weeks' ? null : option.id)} />
              ))}
            </div>
          </div>

          {snapshot ? <div className="training-sheet__meta training-load__snapshot" data-model-revision={snapshot.revision} data-initialization={snapshot.initialization} data-completeness={snapshot.coverage.completeness}>
            <time dateTime={snapshot.asOf}>{formatDate(snapshot.asOf)}</time>{' · '}{snapshot.coverage.population}
          </div> : null}
          <div className="training-trio" aria-label="Training metrics">
            <div className="training-trio__cell">
              <strong>{initialLoading ? <Slot variant="number" /> : establishing || !snapshot ? '' : <EstimatedValue measurement={{value: modelMetrics?.ctl, estimate: snapshot.estimate, basis: snapshot.basis}} formatValue={formatMetric} />}</strong>
              <span>Fitness</span>
            </div>
            <div className="training-trio__cell">
              <strong>{initialLoading ? <Slot variant="number" /> : establishing || !snapshot ? '' : <EstimatedValue measurement={{value: modelMetrics?.atl, estimate: snapshot.estimate, basis: snapshot.basis}} formatValue={formatMetric} />}</strong>
              <span>Fatigue</span>
            </div>
            <div className="training-trio__cell">
              <strong>
                {initialLoading ? <Slot variant="number" /> : establishing || modelMetrics?.tsb == null
                  ? ''
                  : <EstimatedValue measurement={{value: modelMetrics.tsb, estimate: snapshot?.estimate, basis: snapshot?.basis}} formatValue={v => `${v > 0 ? '+' : ''}${formatMetric(v)}`} />}
              </strong>
              <span>Form</span>
              {modelMetrics?.form ? <small>{modelMetrics.form}</small> : null}
            </div>
          </div>

          <div className="training-words training-words--reads" aria-label="Load read">
            {READS.map((option) => (
              <Word key={option.id} label={option.label} active={read === option.id} onClick={() => setParam('read', option.id === 'stress' ? null : option.id)} />
            ))}
          </div>

          {readLoading ? (
            <div className="training-sheet__empty" aria-busy="true"><SlotRows count={4} /><span className="sr-only" role="status">Loading</span></div>
          ) : !readHasData && readUnavailable ? (
            <div className="training-sheet__state" role="alert">
              <strong>{readErrorLabel}</strong><Retry query={readQuery} />
            </div>
          ) : figureEmpty ? (
            <p className="training-sheet__empty">{read === 'stress' ? establishing ? 'Upload rides with effort data to unlock load, fatigue, and form.' : '' : 'No rides in this window.'}</p>
          ) : (
            <div className="training-load__figure">
              <LoadFigure days={series} formatValue={format.value} formatTick={format.tick} ariaLabel="Daily load" />
            </div>
          )}

          {readUnavailable && readHasData ? (
            <div className="training-sheet__state" role="status">
              <span><strong>{readErrorLabel}</strong> Last loaded</span><Retry query={readQuery} />
            </div>
          ) : null}

          <div className="training-load__footer">
            {readHasData && !figureEmpty && (read !== 'stress' || snapshot) ? (
              <span className="training-load__facts">
                Last 7 days <strong>{format.value(last7)}</strong>
                {' · '}7 day change <strong>{`${change > 0 ? '+' : ''}${format.value(change)}`}</strong>
                {' · '}<strong>{formatInteger(daysWith)}</strong> of {formatInteger(series.length)} {format.word}
              </span>
            ) : null}
            <PortalTruthPill tone={trainingError && fitnessMetrics ? 'warning' : thresholdPending ? 'warning' : 'muted'}>{truthWord}</PortalTruthPill>
          </div>
        </section>

        <section className="training-sheet training-consistency" aria-busy={heatmapQuery.isFetching} aria-labelledby="training-consistency-heading">
          <div className="training-sheet__head">
            <h2 id="training-consistency-heading" className="training-sheet__eyebrow">Consistency</h2>
            <div className="training-words" aria-label="Consistency read">
              <Word label="Time" active={heatmapRead === 'time'} onClick={() => setParam('consistency', null)} />
              <Word label="Load" active={heatmapRead === 'load'} faint={!thresholdEstablished} onClick={() => setParam('consistency', 'load')} />
            </div>
          </div>
          {heatmapLoading ? (
            <div className="training-sheet__empty" aria-busy="true"><SlotRows count={4} /></div>
          ) : heatmapQuery.data && heatmapEnd ? (
            <div className="training-consistency__figure">
              <ConsistencyHeatmap
                days={heatmapSeries}
                endDate={heatmapEnd}
                weeks={CONSISTENCY_WEEKS}
                formatValue={heatmapRead === 'time' ? (v) => formatRaceTime(v) : (v) => `${formatMetric(v)} stress`}
              />
            </div>
          ) : (
            <p className="training-sheet__empty">{heatmapUnavailable ? ABSENT_VALUE : 'Upload rides to build the calendar.'}</p>
          )}
          {heatmapUnavailable ? (
            <div className="training-sheet__state" role="alert">
              <span><strong>{heatmapRead === 'time' ? 'Could not load riding days.' : 'Could not load training'}</strong>{heatmapQuery.data ? ' Last loaded' : ''}</span><Retry query={heatmapQuery} />
            </div>
          ) : null}
          {heatmapQuery.data && heatmapEnd && (heatmapRead !== 'load' || snapshot) ? (
            <div className="training-sheet__footer">
              Riding days <strong>{formatInteger(summary.activeDays)}</strong>{' · '}Current streak <strong>{formatInteger(summary.streak)}</strong>
            </div>
          ) : null}
        </section>
      </div>

      <div className="training-page__column">
        <section className="training-sheet training-threshold" aria-labelledby="training-threshold-heading">
          <div className="training-sheet__head">
            <h2 id="training-threshold-heading" className="training-sheet__eyebrow">Threshold</h2>
          </div>
          {trainingThreshold?.estimate ? (
            <div className="training-row">
              <span className="training-row__label">Current</span>
              <strong className="training-row__value"><EstimatedValue measurement={trainingThreshold} formatValue={formatWatts} align="end" /></strong>
            </div>
          ) : thresholdQuery.isError ? (
            <div className="training-row">
              <span className="training-row__label">Current</span>
              <span className="training-row__trail">
                <strong className="training-row__value">{formatWatts(null)}</strong>
                <button type="button" className="training-sheet__retry" onClick={() => void thresholdQuery.refetch()}>Try again</button>
              </span>
            </div>
          ) : threshold ? (
            threshold.state === 'establishing' ? (
              <div className="training-row">
                <span className="training-row__label">Status</span>
                <span className="training-row__value training-row__value--word">Establishing</span>
              </div>
            ) : (
              <>
                <div className="training-row">
                  <span className="training-row__label">Current</span>
                  <span className="training-row__trail">
                    <span className="training-row__sub">derived from your rides</span>
                    <strong className="training-row__value">{formatWatts(threshold.currentW)}</strong>
                  </span>
                </div>
                <div className="training-row">
                  <span className="training-row__label">{threshold.lastRaisedAt ? 'Last raised' : 'Established'}</span>
                  <span className="training-row__value training-row__value--word">{formatDate(threshold.lastRaisedAt ?? threshold.establishedAt)}</span>
                </div>
                {threshold.pendingMonday ? (
                  <div className="training-row">
                    <span className="training-row__label">Next Monday</span>
                    <strong className="training-row__value">{`${formatWatts(threshold.pendingMonday.watts)} · Pending`}</strong>
                  </div>
                ) : null}
              </>
            )
          ) : (
            <div className="training-row" aria-busy="true">
              <span className="training-row__label">Current</span>
              <strong className="training-row__value">{formatWatts(null)}</strong>
            </div>
          )}
        </section>

        <section className="training-sheet training-power" aria-busy={powerCurve.isFetching} aria-labelledby="training-power-heading">
          <div className="training-sheet__head">
            <h2 id="training-power-heading" className="training-sheet__eyebrow">Power curve</h2>
            <span className="training-sheet__meta">{curveMeta}</span>
          </div>
          {powerCurve.isPending && powerCurve.fetchStatus !== 'paused' ? (
            <div className="training-sheet__empty" aria-busy="true"><SlotRows count={4} /><span className="sr-only" role="status">Loading</span></div>
          ) : curve?.available ? (
            <div className="training-power__figure">
              <PowerCurveChart
                series={{
                  durationsS: curve.durationsS,
                  bestW: curve.bestW,
                  sealedW: curve.threshold?.sealedW ?? null,
                  candidateW: curve.threshold?.candidateW ?? null,
                  anchorsS: [180, 420, 900],
                }}
              />
            </div>
          ) : (
            <p className="training-sheet__empty">
              {powerCurve.isError || powerCurve.fetchStatus === 'paused' ? ABSENT_VALUE : 'Upload rides with power to build the curve.'}
            </p>
          )}
          {powerCurve.isError || powerCurve.fetchStatus === 'paused' ? (
            <div className="training-sheet__state" role="alert">
              <span><strong>Could not load the power curve.</strong>{curve ? ' Last loaded' : ''}</span><Retry query={powerCurve} />
            </div>
          ) : null}
        </section>
      </div>
    </section>
  );
}
