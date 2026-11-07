import { StateRow } from '../portal/FailureSpecies';
import { LoadingRows } from '../loading/LoadingSystem';
import { useId, useState } from 'react';
import { Link } from 'react-router-dom';
import * as Popover from '@radix-ui/react-popover';
import { ChevronRight } from 'lucide-react';
import { ABSENT_VALUE, formatMonthDay, formatInteger, formatRaceTime } from '../../lib/formatters';
import { resolveRankMarkAsset } from '../../assets/rankmarks';
import { type ClimbPowerFields } from '../../lib/api';
import { ClimbPower, climbPowerValue } from './ClimbPower';

export interface ClimbResultRow extends ClimbPowerFields {
  key: string;
  seat: number;
  rank: number;
  tied?: boolean;
  name: string;
  path?: string | null;
  identityHidden?: boolean;
  timeS?: number | null;
  effortId?: string | null;
  rideId?: string | null;
  isViewer?: boolean;
  achievedAt?: string | null;
}

function ResultRow({ entry, metric, viewer }: { entry: ClimbResultRow; metric: 'time' | 'power'; viewer: 'owner' | 'stranger' }) {
  const rideId = !entry.identityHidden ? entry.rideId : null;
  const effortPath = rideId ? `/activities/${encodeURIComponent(rideId)}/analysis` : null;
  const time = entry.timeS != null && entry.timeS > 0 ? formatRaceTime(entry.timeS) : viewer === 'owner' ? ABSENT_VALUE : null;
  const rank = `${entry.tied ? 'T-' : ''}${formatInteger(entry.rank)}`;
  const mark = entry.rank <= 3 ? resolveRankMarkAsset(entry.rank) : null;
  const name = entry.identityHidden ? 'Rider' : entry.name;
  const hasValue = metric === 'time' ? time !== null : climbPowerValue(entry) !== null;
  return <div className="climb-result-row" data-object-row="record-board" data-rank={entry.seat} data-viewer={entry.isViewer || undefined}>
    <span className="climb-result-rank" aria-label={`Rank ${rank}`}>
      {mark && !entry.tied ? <img src={mark.src} srcSet={mark.srcSet} alt="" /> : rank}
    </span>
    <span className="climb-result-rider">
      <strong>{entry.path && !entry.identityHidden ? <Link to={entry.path}>{name}</Link> : name}</strong>
      {entry.identityHidden ? <small>Rider profile private</small> : entry.achievedAt ? <small>{formatMonthDay(entry.achievedAt)}</small> : null}
    </span>
    {(hasValue || effortPath) && <span className="climb-result-value">
      {effortPath && <Link className="climb-result-effort" to={effortPath} aria-label={`${name}, ${time ?? 'ride'} — Open ride analysis`}>
        {metric === 'time' ? time : <span className="sr-only">Open ride analysis</span>}
      </Link>}
      {metric === 'time' ? (!effortPath && time) : <ClimbPower power={entry} />}
    </span>}
  </div>;
}

/** Display preferences never reorder or renumber the authoritative seats. */
export default function ClimbLeaderboard({ entries, loading, error, onRetry, hiddenRows = 0, viewer = 'owner', source, earlierVersionId }: {
  entries: ClimbResultRow[];
  loading?: boolean;
  error?: boolean;
  onRetry?: () => void;
  hiddenRows?: number;
  viewer?: 'owner' | 'stranger';
  source?: 'onchain' | 'rides';
  earlierVersionId?: string | null;
}) {
  // Privacy projection failures can revoke previously visible identities.
  // Fail closed for board data while the independent canon remains readable.
  if (error) entries = [];
  const id = useId();
  const [showAll, setShowAll] = useState(viewer === 'stranger');
  const [metric, setMetric] = useState<'time' | 'power'>('time');
  return <section className="climb-detail-record-board" data-object-layer="climb-record-board" aria-label="Climb leaderboard" aria-busy={loading}>
    <div className="profile-eyebrow"><div className="climb-section-heading">
      <div className="climb-board-title"><h2>Leaderboard</h2>
        {source === 'rides' && <span className="climb-ledger-note">From rides</span>}
        <Popover.Root>
          <Popover.Trigger asChild><button type="button" className="climb-board-help" aria-label="About this leaderboard">?</button></Popover.Trigger>
          <Popover.Portal><Popover.Content className="estimated-value__card" aria-label="About this leaderboard" sideOffset={6} collisionPadding={12}>
            Each rider's fastest ascent. Power with ⚡ was measured by a power meter. Power with ≈ is an estimate from the time and the climb, at a standard rider weight.
          </Popover.Content></Popover.Portal>
        </Popover.Root>
      </div>
      {entries.length > 0 && <fieldset className="climb-metric-picker">
        <legend className="climb-sr-only">Displayed leaderboard value</legend>
        {(['time', 'power'] as const).map((value) => <label key={value}>
          <input type="radio" name={`${id}-metric`} value={value} checked={metric === value}
            onChange={() => setMetric(value)} />
          <span>{value === 'time' ? 'Time' : 'Power'}</span>
        </label>)}
      </fieldset>}
    </div></div>
    <div className="climb-ledger-card climb-detail-leaderboard" data-show-all={showAll}>
      {loading && !entries.length ? <LoadingRows label="Loading leaderboard" rows={10} />
        : error && !entries.length ? <StateRow title="Could not load leaderboard" action={onRetry && <button type="button" onClick={onRetry}>Try again</button>} />
        : !entries.length ? source === 'rides'
          ? <StateRow title="No times on this version yet." description={earlierVersionId ? 'Earlier times remain on version 1.' : undefined} />
          : <StateRow title="No times yet" description="Ride it to set the first time." />
        : entries.map((entry) => <ResultRow key={entry.key} entry={entry} metric={metric} viewer={viewer} />)}
      {entries.length > 5 && !showAll && <button className="climb-navigation-row climb-top-ten" onClick={() => setShowAll(true)}><span>Top 10</span><ChevronRight className="climb-chevron" size={15} aria-hidden="true" /></button>}
    </div>
    {source === 'rides' && <p className="climb-ledger-note">Leaderboard from rides · this version only</p>}
    {hiddenRows > 0 && <p className="climb-ledger-note">{formatInteger(hiddenRows)} more rows require sign in.</p>}
  </section>;
}
