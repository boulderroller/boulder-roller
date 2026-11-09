import { StateRow } from '../portal/FailureSpecies';
import { LoadingRows } from '../loading/LoadingSystem';
import { Slot } from '../loading/Slot';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import { api } from '../../lib/api';
import { useAuth } from '../../contexts/AuthContext';
import { ABSENT_VALUE, formatDate, formatInteger, formatOrdinal, formatRaceTime } from '../../lib/formatters';
import { ClimbNavigationRow, useClimbPanelPath } from './ClimbNavigation';

export default function ClimbRides({ vaultId, full = false, best = false, rank }: { vaultId: number; full?: boolean; best?: boolean; rank?: number | null }) {
  const { user } = useAuth();
  const path = useClimbPanelPath();
  const history = useQuery({ placeholderData: undefined, queryKey: ['climb-rides', vaultId, user?.id], queryFn: () => api.getMyVaultEffortHistory(vaultId), enabled: Boolean(user), staleTime: 60_000 });
  if (!user) return null;
  if (best) return <p className="climb-page-yours">Your best <b>{history.isPending ? <Slot variant="number" /> : !history.isError && history.data?.bestTimeSeconds ? formatRaceTime(history.data.bestTimeSeconds) : ABSENT_VALUE}</b> · {formatOrdinal(rank)}</p>;
  const completeRideHistory = !history.isError && history.data && history.data.efforts.length === history.data.totalCount && history.data.efforts.every(effort => Boolean(effort.rideId));
  const rideCount = completeRideHistory ? new Set(history.data!.efforts.map(effort => effort.rideId)).size : null;
  if (!full) return <div className="climb-ledger-card"><ClimbNavigationRow to={path('rides')} label="Your history" value={history.isPending ? <Slot /> : rideCount === null ? ABSENT_VALUE : `${formatInteger(rideCount)} rides`} /></div>;
  const data = history.data;
  return <section aria-label="Your history" aria-busy={history.isFetching}>
    {history.isPending ? <LoadingRows label="Loading your history" rows={4} /> : history.isError ? <StateRow title="Ride history unavailable" action={<button onClick={() => void history.refetch()}>Try again</button>} />
      : !data?.efforts.length ? <StateRow title="No attempts yet" description="Ride this climb to start tracking your progress." /> : <>
        <div className="climb-ledger-card"><div className="climb-kv"><span>PRs Set</span><strong>{formatInteger(data.totalPrs)}</strong></div><div className="climb-kv"><span>Best time</span><strong>{formatRaceTime(data.bestTimeSeconds)}</strong></div></div>
        <div className="climb-ledger-card climb-history-list">{data.efforts.map((effort) => {
          const content = <><span>{effort.achievedAt ? formatDate(effort.achievedAt) : ABSENT_VALUE}{effort.isPR && <small>PR</small>}</span><strong className="climb-row-value">{formatRaceTime(effort.timeSeconds)}</strong>{effort.rideId && <ChevronRight className="climb-chevron" size={15} aria-hidden="true" />}</>;
          return effort.rideId ? <Link className="climb-navigation-row" to={`/rides/${encodeURIComponent(effort.rideId)}`} key={effort.id}>{content}</Link> : <div className="climb-navigation-row" key={effort.id}>{content}</div>;
        })}</div>
      </>}
  </section>;
}
