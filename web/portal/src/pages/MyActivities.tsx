import { Slot } from '../components/loading/Slot';
import { useId, useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { Search } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { useFormatters, type Formatters } from '../hooks/useFormatters';
import { useRides } from '../hooks/queries';
import type { Ride } from '../lib/api';
import { ABSENT_VALUE, formatDateTime, formatInteger, formatMonth, formatMonthDay, formatMonthYear, formatTime, formatWeekday } from '../lib/formatters';
import ClimbShapeGlyph from '../components/climbs/ClimbShapeGlyph';
import { StateRow } from '../components/portal/PortalSpine';
import { UPLOAD_PROCESSING_FAILURE } from '../components/upload/uploadCopy';

// Rides — the rhythm log (Tim-ratified 2026-09-03; the concept from his
// 2026-08-24 boards on the Night Ledger kit). The log is time: rows sit apart
// by the real gap between rides, clamped so a long break is paper, not a
// screen of void. Months are marginalia on the left rail. Each row leads with
// the ride's own elevation cross-section when the list carries one (counted
// climb spans stroked cobalt; the column folds away until any ride has one), then the
// title, then one trailing value that follows the word (Distance · Elevation
// · Time · CAL). Filters are words. The log is chronological; the words
// choose the number. Own profile only.

type RideFilterType = 'ALL' | 'REWARDED' | 'LONG' | 'CLIMBING';
type RideValueWord = 'distance' | 'elevation' | 'time' | 'cal';
type RideCountState = 'counted' | 'held' | 'waiting' | 'not-counted';

const CONTRACT_EMPTY = ABSENT_VALUE;
const CONTRACT_WAITING = 'Waiting';
const CONTRACT_NOT_COUNTED = 'Not counted';
const IDLE_GAP_CAP_DAYS = 8;
const RIDE_LIMIT = 365;

const FILTER_OPTIONS: { value: RideFilterType; label: string }[] = [
  { value: 'ALL', label: 'All rides' },
  { value: 'REWARDED', label: 'With CAL' },
  { value: 'LONG', label: 'Long rides' },
  { value: 'CLIMBING', label: 'Climbing' },
];
const VALUE_WORDS: { value: RideValueWord; label: string }[] = [
  { value: 'distance', label: 'Distance' },
  { value: 'elevation', label: 'Elevation' },
  { value: 'time', label: 'Time' },
  { value: 'cal', label: 'CAL' },
];

const getRideReward = (ride: Ride): number => ride.calEarned ?? ride.dungEarned ?? 0;
const isFailedUpload = (ride: Ride): boolean => ride.status === 'failed';

const isRideWaiting = (ride: Ride): boolean => {
  const status = ride.attestationStatus?.toLowerCase();
  return status === 'processing' || status === 'pending' || status === 'uploaded' || status === 'queued';
};

function countStateFor(ride: Ride): RideCountState {
  const reward = getRideReward(ride);
  if (ride.thresholdEconomyState === 'held') return 'held';
  if (reward > 0 || ride.thresholdEconomyState === 'counted') return 'counted';
  if (isRideWaiting(ride)) return 'waiting';
  return 'not-counted';
}

function readValueWord(value: string | null): RideValueWord {
  return VALUE_WORDS.some((word) => word.value === value) ? (value as RideValueWord) : 'distance';
}

function climbCount(ride: Ride): number | null {
  const itemized = ride.calItemization?.climbs?.length;
  if (typeof itemized === 'number') return itemized;
  const patterns = ride.patterns?.filter((pattern) => pattern.type === 'climb').length;
  return typeof patterns === 'number' && (ride.patterns?.length ?? 0) > 0 ? patterns : null;
}

function dayNumber(value: string): number | null {
  const when = new Date(value);
  if (Number.isNaN(when.getTime())) return null;
  return Math.floor(new Date(when.getFullYear(), when.getMonth(), when.getDate()).getTime() / 86_400_000);
}

function monthOf(value: string, withYear: boolean): string {
  return withYear ? formatMonthYear(value) : formatMonth(value);
}

function trailingFor(ride: Ride, word: RideValueWord, formatters: Formatters): { text: string; state: RideCountState; faint: boolean } {
  const state = countStateFor(ride);
  if (word === 'cal') {
    if (state === 'counted') return { text: `${formatters.tokenAmount(getRideReward(ride))} CAL`, state, faint: false };
    if (state === 'held') return { text: 'Held', state, faint: false };
    if (state === 'waiting') return { text: CONTRACT_WAITING, state, faint: true };
    return { text: CONTRACT_NOT_COUNTED, state, faint: true };
  }
  if (word === 'time') {
    if (isRideWaiting(ride)) return { text: CONTRACT_WAITING, state, faint: true };
    return { text: formatters.durationCompact(ride.durationS), state, faint: false };
  }
  if (word === 'elevation') return { text: formatters.elevation(ride.elevationM), state, faint: false };
  return { text: formatters.distance(ride.distanceM), state, faint: false };
}

interface LogRow {
  ride: Ride;
  date?: string;
  idleDays: number;
  month: string | null;
}

function buildLog(rides: Ride[]): LogRow[] {
  const ordered = [...rides].sort((a, b) => new Date(b.startedAt).getTime() - new Date(a.startedAt).getTime());
  const rows: LogRow[] = [];
  let previousDay: number | null = null;
  let previousMonth: string | null = null;
  let firstYear: number | null = null;
  for (const ride of ordered) {
    const candidateDate = isFailedUpload(ride) ? ride.uploadedAt : ride.startedAt;
    const date = candidateDate && dayNumber(candidateDate) !== null ? candidateDate : undefined;
    const day = date ? dayNumber(date) : null;
    const idleDays = previousDay !== null && day !== null ? Math.max(0, previousDay - day - 1) : 0;
    const when = date ? new Date(date) : null;
    const yearKey = when?.getFullYear() ?? null;
    if (firstYear === null && yearKey !== null) firstYear = yearKey;
    const monthKey = when === null ? null : `${when.getFullYear()}-${when.getMonth()}`;
    const month = date && monthKey !== null && monthKey !== previousMonth
      ? monthOf(date, yearKey !== firstYear || rows.length === 0)
      : null;
    rows.push({ ride, date, idleDays: Math.min(IDLE_GAP_CAP_DAYS, idleDays), month });
    // Keep the next row adjacent to a failed upload instead of adding ride-idle space below it.
    previousDay = isFailedUpload(ride) ? null : day ?? previousDay;
    previousMonth = monthKey ?? previousMonth;
  }
  return rows;
}

function FailedUploadRow({ row, onUpload }: { row: LogRow; onUpload: () => void }) {
  const id = useId();
  const nameId = `${id}-name`;
  const dateId = `${id}-date`;
  const sentenceId = `${id}-sentence`;
  return (
    <div
      className="rides-log__row rides-log__row--failed"
      data-ride-id={row.ride.id}
      role="group"
      aria-labelledby={nameId}
      aria-describedby={row.date ? `${dateId} ${sentenceId}` : sentenceId}
      style={{ '--rides-log-idle-days': row.idleDays } as React.CSSProperties}
    >
      {row.month ? <span className="rides-log__month">{row.month}</span> : <span className="rides-log__rail" aria-hidden="true" />}
      <span className="rides-log__failure">
        <span className="rides-log__failure-heading">
          <strong id={nameId} className="rides-log__name">{row.ride.title || 'Untitled ride'}</strong>
          {row.date ? (
            <time id={dateId} className="rides-log__sub" dateTime={row.date} aria-label={formatDateTime(row.date)} title={formatDateTime(row.date)}>
              {formatMonthDay(row.date)}
            </time>
          ) : null}
          <button type="button" className="rides-log__retry rides-log__upload" onClick={onUpload} aria-describedby={`${nameId} ${sentenceId}`}>
            Upload ride
          </button>
        </span>
        <span id={sentenceId} className="rides-log__failure-sentence">{UPLOAD_PROCESSING_FAILURE}</span>
      </span>
    </div>
  );
}

function RideRow({ row, word, spines }: { row: LogRow; word: RideValueWord; spines: boolean }) {
  const formatters = useFormatters();
  const ride = row.ride;
  const title = ride.title || 'Untitled ride';
  const climbs = climbCount(ride);
  const startTime = formatTime(ride.startedAt);
  const sub = [
    `${formatWeekday(ride.startedAt)} ${formatMonthDay(ride.startedAt)}`,
    startTime === ABSENT_VALUE ? null : startTime,
    climbs === null ? null : climbs === 1 ? '1 climb' : `${formatInteger(climbs)} climbs`,
  ].filter(Boolean).join(' · ');
  const trailing = trailingFor(ride, word, formatters);
  const shape = ride.elevationProfile ?? undefined;

  return (
    <Link
      className="rides-log__row"
      to={`/activities/${encodeURIComponent(ride.id)}`}
      data-ride-id={ride.id}
      aria-label={[title, formatDateTime(ride.startedAt), climbs === null ? null : `${formatInteger(climbs)} ${climbs === 1 ? 'climb' : 'climbs'}`, trailing.text].filter(Boolean).join(' · ')}
      data-count-state={trailing.state}
      style={{ '--rides-log-idle-days': row.idleDays } as React.CSSProperties}
    >
      {row.month ? <span className="rides-log__month">{row.month}</span> : <span className="rides-log__rail" aria-hidden="true" />}
      {spines ? (
        <span className="rides-log__spine" aria-hidden="true">
          {shape && shape.length >= 2
            ? <ClimbShapeGlyph profile={shape} width={120} height={28} spans={ride.countedSpans ?? undefined} />
            : null}
        </span>
      ) : null}
      <span className="rides-log__identity">
        <strong className="rides-log__name">{title}</strong>
        <time className="rides-log__sub" dateTime={ride.startedAt}>{sub}</time>
      </span>
      <strong className={`rides-log__value${trailing.faint ? ' rides-log__value--faint' : ''}`} data-count-state={trailing.state}>
        {trailing.text}
      </strong>
    </Link>
  );
}

function RideRowSkeletons() {
  return (
    <div className="rides-log__rows rides-log__rows--loading" aria-label="Loading ride log">
      {Array.from({ length: RIDE_LIMIT }, (_, item) => item).map((item) => (
        <div key={item} className="rides-log__row rides-log__row--loading">
          <span className="rides-log__rail" aria-hidden="true" />
          <span className="rides-log__identity">
            <Slot variant="text" className="rides-log__skeleton-name" />
            <Slot variant="text" className="rides-log__skeleton-sub" />
          </span>
          <Slot variant="number" className="rides-log__skeleton-value" />
        </div>
      ))}
    </div>
  );
}

export default function MyActivities() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [searchQuery, setSearchQuery] = useState('');
  const [filterType, setFilterType] = useState<RideFilterType>('ALL');
  const valueWord = readValueWord(searchParams.get('value'));
  const openUpload = () => navigate('/upload', { state: { returnTo: '/profile?tab=rides' } });

  const knownRideTotal = typeof user?.totalRides === 'number' && Number.isFinite(user.totalRides)
    ? Math.max(0, Math.floor(user.totalRides))
    : null;
  const rideQuery = useRides({ limit: Math.max(RIDE_LIMIT, knownRideTotal ?? 0) });
  const rawRides = useMemo<Ride[]>(() => rideQuery.data ?? [], [rideQuery.data]);
  const rideCount = rawRides.filter((ride) => !isFailedUpload(ride)).length;
  const hasRideResult = rideQuery.data !== undefined;
  const loadUnavailable = !hasRideResult
    && (rideQuery.isError || rideQuery.fetchStatus === 'paused');
  const initialLoading = !hasRideResult
    && rideQuery.isPending
    && !loadUnavailable;
  const staleRideResult = rideQuery.isError && hasRideResult;
  const rideCountMismatch = hasRideResult
    && knownRideTotal !== null
    && rawRides.length !== knownRideTotal;
  const emptyRideResultNeedsRecovery = rawRides.length === 0
    && (staleRideResult || rideCountMismatch);
  const showRideResultWarning = rawRides.length > 0
    && (staleRideResult || rideCountMismatch);
  const canShowRideTotals = hasRideResult && !initialLoading && !loadUnavailable;
  const rideCountLabel = !canShowRideTotals
    ? CONTRACT_EMPTY
    // The profile total includes failed uploads, including any not loaded yet.
    // Keep it for reconciliation only; only loaded nonfailed rides can be counted.
    : `${formatInteger(rideCount)} rides`;
  const retryRideList = () => {
    void rideQuery.refetch();
  };
  const retryAction = (
    <button
      type="button"
      className="rides-log__retry"
      onClick={retryRideList}
      disabled={rideQuery.isFetching}
    >
      {rideQuery.isFetching ? 'Trying again' : 'Try again'}
    </button>
  );

  const filteredRides = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return rawRides.filter((ride) => {
      const title = (ride.title || 'Ride').toLowerCase();
      const matchesSearch = query.length === 0 || title.includes(query);
      const reward = getRideReward(ride);
      let matchesType = true;
      if (filterType === 'REWARDED') matchesType = reward > 0;
      if (filterType === 'LONG') matchesType = (ride.distanceM || 0) >= 40_000;
      if (filterType === 'CLIMBING') matchesType = (ride.elevationM || 0) >= 500;
      return matchesSearch && matchesType;
    });
  }, [filterType, rawRides, searchQuery]);
  const log = useMemo(() => buildLog(filteredRides), [filteredRides]);
  const spines = useMemo(() => rawRides.some((ride) => !isFailedUpload(ride) && (ride.elevationProfile?.length ?? 0) >= 2), [rawRides]);

  const handleValueWord = (word: RideValueWord) => {
    const next = new URLSearchParams(searchParams);
    if (word === 'distance') next.delete('value');
    else next.set('value', word);
    setSearchParams(next, { replace: true });
  };

  return (
    <section className={`rides-log${spines ? ' rides-log--spines' : ''}`} aria-label="Ride log">
      <header className="rides-log__header">
        <div className="rides-log__heading">
          <h2 className="rides-log__title">Rides</h2>
          <span className="rides-log__count">{rideCountLabel}</span>
        </div>
        <label className="rides-log__search">
          <Search aria-hidden="true" />
          <span className="sr-only">Search rides</span>
          <input
            type="search"
            placeholder="Search rides"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
          />
        </label>
      </header>

      <div className="rides-log__words">
        <div className="my-activities-filter-strip rides-log__filters" aria-label="Activity type filter">
          {FILTER_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              className="my-activities-filter-strip__item rides-log__filter"
              aria-pressed={filterType === option.value}
              onClick={() => setFilterType(option.value)}
            >
              <span>{option.label}</span>
            </button>
          ))}
        </div>
        <div className="rides-log__values" aria-label="Ride value">
          {VALUE_WORDS.map((word) => (
            <button
              key={word.value}
              type="button"
              className="rides-log__word"
              aria-pressed={valueWord === word.value}
              onClick={() => handleValueWord(word.value)}
            >
              {word.label}
            </button>
          ))}
        </div>
      </div>

      {showRideResultWarning ? (
        <div className="rides-log__state" role="status">
          <span>
            <strong>{staleRideResult ? 'Ride history may be out of date.' : 'Ride history may be incomplete.'}</strong>
            {' '}
            {staleRideResult
              ? `Showing ${formatInteger(rideCount)} previously loaded rides.`
              : 'Try again to reconcile the ride list with your profile.'}
          </span>
          {retryAction}
        </div>
      ) : null}

      {initialLoading ? (
        <RideRowSkeletons />
      ) : loadUnavailable ? (
        <StateRow
          role="alert"
          aria-live="polite"
          title="Ride history unavailable"
          description="We couldn't load your rides. Try again."
          action={retryAction}
        />
      ) : emptyRideResultNeedsRecovery ? (
        <StateRow
          role="alert"
          aria-live="polite"
          title={rideCountMismatch ? 'Ride history incomplete' : 'Ride history may be out of date'}
          description="No ride rows were returned. Try again."
          action={retryAction}
        />
      ) : rawRides.length === 0 ? (
        <StateRow
          title="No rides yet"
          description="Upload a ride to start your ride history."
          action={(
            <button type="button" className="rides-log__retry" onClick={openUpload}>
              Upload ride
            </button>
          )}
        />
      ) : log.length === 0 ? (
        <StateRow
          title="No matching rides"
          description="Clear the search or change the filter."
          action={(
            <button
              type="button"
              className="rides-log__retry"
              onClick={() => {
                setSearchQuery('');
                setFilterType('ALL');
              }}
            >
              Clear filters
            </button>
          )}
        />
      ) : (
        <div className="rides-log__rows">
          {log.map((row) => (
            isFailedUpload(row.ride)
              ? <FailedUploadRow key={row.ride.id} row={row} onUpload={openUpload} />
              : <RideRow key={row.ride.id} row={row} word={valueWord} spines={spines} />
          ))}
        </div>
      )}
    </section>
  );
}
