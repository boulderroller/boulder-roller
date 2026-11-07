import { lazy, Suspense, useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAuth } from '../../contexts/AuthContext';
import { pledgeActions } from '../../lib/stage1Actions';
import type { Stage1Bonding } from '../../lib/stage1';
import { useStage1Owner, useStage1Mints } from '../../hooks/queries/useStage1';
import { useSystemStatus } from '../../hooks/useSystemStatus';
import { api } from '../../lib/api';
import { exactUnits, stage1Amount, stage1Backing, stage1Live, stage1ActionsLive, stage1StakingAssets, type Stage1Pay, type Stage1Pledge } from '../../lib/stage1';
import { stage1Copy as copy } from '../../lib/stage1Copy';
import { formatBaseUnits } from '../../lib/tokenAmounts';
import { formatDate, formatInteger, formatPercent } from '../../lib/formatters';
import '../../styles/stage1.css';
import { StateRow } from '../portal/FailureSpecies';
import { SlotRows } from '../loading/Slot';

type Surface = 'climb' | 'portfolio';
type QueryState = { isPending: boolean; isError: boolean; isFetching: boolean; refetch: () => unknown };

function Sheet({ surface, title, children }: { surface: Surface; title: string; children: ReactNode }) {
  return <section className={surface === 'climb' ? 'climb-stage1-sheet' : 'portfolio-sheet'} aria-label={title}>
    <div className={surface === 'climb' ? 'climb-section-heading' : 'portfolio-sheet__head'}><h3>{title}</h3></div>
    <div className={surface === 'climb' ? 'climb-ledger-card' : undefined}>{children}</div>
  </section>;
}
function Row({ surface, label, value, detail }: { surface: Surface; label: string; value?: ReactNode; detail?: ReactNode }) {
  return surface === 'climb'
    ? <div className="climb-kv stage1-row"><span>{label}{detail && <small>{detail}</small>}</span>{value != null && <strong>{value}</strong>}</div>
    : <div className="portfolio-row portfolio-row--static stage1-row"><span className="portfolio-row__copy"><strong>{label}</strong>{detail && <span>{detail}</span>}</span>{value != null && <span className="portfolio-row__trail"><strong>{value}</strong></span>}</div>;
}
const Action = lazy(() => import('./Stage1Action'));
const Transport = lazy(() => import('./Stage1Transport'));
export function Stage1State({ query, children, empty = false }: { query: QueryState; children?: ReactNode; empty?: boolean }) {
  if (query.isError) return <StateRow role="status" title={copy.unavailable} action={<button type="button" onClick={() => void query.refetch()} disabled={query.isFetching}>Try again</button>} />;
  if (query.isPending) return <div aria-busy="true" aria-label={copy.loading}><SlotRows count={3} /></div>;
  if (empty) return <StateRow title={copy.empty} />;
  return <>{children}</>;
}
function More({ query }: { query: { hasNextPage: boolean; isFetchingNextPage: boolean; fetchNextPage: () => unknown } }) {
  return query.hasNextPage ? <button type="button" className="climb-action-row" disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>{query.isFetchingNextPage ? copy.loading : 'Load more'}</button> : null;
}
function PayRow({ row, label, surface }: { row: Stage1Pay; label: string; surface: Surface }) {
  const amount = stage1Amount(row);
  return <Row surface={surface} label={label} value={amount == null ? null : <span title={row.mint}>{amount}</span>} detail={<>{row.week != null && exactUnits(String(row.week)) && <>Week {formatBaseUnits(String(row.week), 0, 0)}</>}{surface === 'portfolio' && row.climbName && <> · <span title={row.hill}>{row.climbName}</span></>}</>} />;
}
function timestamp(value?: string) {
  if (!exactUnits(value) || value === '0') return null;
  const n = Number(value);
  if (!Number.isSafeInteger(n) || n > 8640000000000) return null;
  return formatDate(new Date(n * 1000).toISOString());
}
function Pledge({ pledge: indexedPledge, surface, actionsEnabled }: { pledge: Stage1Pledge; surface: Surface; actionsEnabled: boolean }) {
  const { user } = useAuth();
  const [actionsOpen, setActionsOpen] = useState(false);
  const canOpen = actionsEnabled && indexedPledge.cancelled === false && exactUnits(indexedPledge.basisLamports) && BigInt(indexedPledge.basisLamports) > 0n;
  const eligibility = useQuery({ queryKey: ['stage1', user?.id, user?.wallet, 'eligibility', indexedPledge.address],
    queryFn: () => api.getStage1Eligibility(indexedPledge.address), retry: false, staleTime: 15_000,
    enabled: !!user && canOpen && actionsOpen, refetchOnWindowFocus: false,
    refetchInterval: query => query.state.data?.withdrawalsPausedUntil
      ? Math.max(1000, Number(query.state.data.withdrawalsPausedUntil) * 1000 - Date.now()) : false });
  const live = eligibility.isError ? undefined : eligibility.data;
  const pledge = { ...indexedPledge, chainTime: live?.chainTime, eligibilityWeek: live?.week, eligibility: live?.actions };
  const state = pledge.cancelled === true ? copy.cancelled
    : exactUnits(pledge.returnedUnits) && BigInt(pledge.returnedUnits) > 0n && pledge.units === '0' ? copy.returned : pledge.exiting === true ? copy.exiting
      : pledge.cancelled === false && pledge.exiting === false ? copy.active : null;
  const notices = [copy.noticePending, copy.noticeExiting, copy.noticeReturned, copy.noticeCancelled];
  return <div data-stage1-pledge={pledge.address}>
    <Row surface={surface} label={copy.pledge} value={<span title={pledge.mint}>{stage1Amount({ amount: pledge.units, mint: pledge.mint })}</span>} detail={<>{state}{surface === 'portfolio' && pledge.climbName && <> · <span title={pledge.hill}>{pledge.climbName}</span></>}</>} />
    {typeof pledge.lockWeeks === 'number' && <Row surface={surface} label={copy.lock} value={formatInteger(pledge.lockWeeks)} />}
    {timestamp(pledge.lockEnd) && <Row surface={surface} label={copy.lockEnd} value={timestamp(pledge.lockEnd)} />}
    {pledge.founding === true && <Row surface={surface} label={copy.founding} />}
    {pledge.withdrawals.map(notice => <div key={notice.address}>
      {timestamp(notice.data.noticeAt) && <Row surface={surface} label={copy.notice} value={timestamp(notice.data.noticeAt)} />}
      {timestamp(notice.data.eligibleAt) && <Row surface={surface} label={copy.eligible} value={timestamp(notice.data.eligibleAt)} />}
      {notice.data.status != null && notices[notice.data.status] && <Row surface={surface} label={notices[notice.data.status]} />}
    </div>)}
    {canOpen && <button type="button" className={surface === 'climb' ? 'climb-action-row' : 'portfolio-action-row'} aria-expanded={actionsOpen} onClick={() => setActionsOpen(open => !open)}>{copy.pledgeActions}</button>}
    {canOpen && actionsOpen && <Stage1State query={eligibility}>
      {live?.withdrawalsPausedUntil && pledge.withdrawals.some(w => w.data.status === 0 || w.data.status === 1) && <StateRow role="status" title={copy.withdrawalsPaused} />}
      <Suspense fallback={null}>{pledgeActions(pledge).map(({ action, withdrawal }) => <Action key={`${action}:${withdrawal?.address ?? ''}`} action={action} lot={pledge} withdrawal={withdrawal} surface={surface} />)}</Suspense>
    </Stage1State>}
  </div>;
}

function Owner({ hill, surface, bonding }: { hill?: string; surface: Surface; bonding?: Stage1Bonding }) {
  const { status } = useSystemStatus();
  const actionsEnabled = stage1ActionsLive(status);
  const { registration, pay, pledges, dung, claims } = useStage1Owner(hill, actionsEnabled);
  const lots = pledges.data?.pages.flatMap(p => p.pledges) ?? [];
  return <>
    <Sheet surface={surface} title={copy.registration}>
      <Stage1State query={registration}>
        {registration.data && <Row surface={surface} label={registration.data.registration ? copy.registered : copy.unregistered} />}
        {registration.data?.held.map((row, i) => <PayRow key={i} row={row} label={copy.held} surface={surface} />)}
        <Suspense fallback={null}>{actionsEnabled && registration.data?.registration === null && <Action surface={surface} action="registration" />}</Suspense>
      </Stage1State>
    </Sheet>
    {([{ query: pay, title: copy.pay }, { query: dung, title: 'DUNG' }] as const).map(({ query, title }) => {
      const paid = query.data?.pages.flatMap(p => p.paid) ?? [];
      const pending = query.data?.pages.flatMap(p => p.pending) ?? [];
      return <Sheet key={title} surface={surface} title={title}>
        <Stage1State query={query} empty={!paid.length && !pending.length}>
          {paid.map((row, i) => <PayRow key={`paid-${i}`} row={row} label={copy.paid} surface={surface} />)}
          {pending.map((row, i) => <PayRow key={`pending-${i}`} row={row} label={copy.pending} surface={surface} />)}
        </Stage1State>
        {!query.isError && <More query={query} />}
        {actionsEnabled && <><Stage1State query={claims}><Suspense fallback={null}>{claims.data?.pages.flatMap(p => p.claims).filter(c => c.intent.claimType === (title === 'DUNG' ? 'dung' : 'cash') && (!hill || c.intent.claims.every(l => l.hill === hill))).map(c => <Action key={`${c.reference.jobId}:${c.reference.role}:${c.reference.index}`} surface={surface} action="self-claim" claim={c} />)}</Suspense></Stage1State>
        <More query={claims} /></>}
      </Sheet>;
    })}
    <Suspense fallback={null}>{actionsEnabled && <Transport surface={surface} />}</Suspense>
    <Sheet surface={surface} title={copy.pledges}>
      <Stage1State query={pledges} empty={!lots.length}>
        {lots.map(pledge => <Pledge key={pledge.address} pledge={pledge} surface={surface} actionsEnabled={actionsEnabled} />)}
        <More query={pledges} />
      </Stage1State>
      <Suspense fallback={null}>{actionsEnabled && stage1StakingAssets(bonding).length > 0 && <Action surface={surface} action="pledge" bonding={bonding} />}</Suspense>
    </Sheet>
  </>;
}

export function Stage1Portfolio() {
  const { user } = useAuth();
  const { status } = useSystemStatus();
  useStage1Mints(stage1Live(status));
  if (!user || !stage1Live(status)) return null;
  return <section data-stage1="portfolio" className="stage1-group" aria-label={copy.group}>
    <h2 className="portfolio-sheet__head">{copy.group}</h2>
    <Owner key={`${user.id}:${user.wallet}`} surface="portfolio" />
  </section>;
}

export function Stage1ClimbSection({ climbId, fallback }: { climbId?: string; fallback?: ReactNode }) {
  const { status } = useSystemStatus();
  useStage1Mints(stage1Live(status));
  const enabled = stage1Live(status) && !!climbId;
  const hill = useQuery({ queryKey: ['stage1-hill', climbId], queryFn: () => api.getStage1Hill(climbId!), enabled, retry: false, staleTime: 15_000 });
  return <>{fallback}{enabled && (hill.isPending || hill.isError)
    ? <section className="stage1-group" aria-label={copy.group}><Stage1State query={hill} /></section>
    : enabled && hill.data?.hill ? <Stage1ClimbVault key={hill.data.hill} hill={hill.data.hill} /> : null}</>;
}

export function Stage1ClimbVault({ hill }: { hill: string }) {
  const { user } = useAuth();
  const query = useQuery({ queryKey: ['stage1-bonding', hill], queryFn: () => api.getStage1Bonding(hill), retry: false, staleTime: 15_000 });
  const data = query.isError ? undefined : query.data;
  const backing = data ? stage1Backing(data.assets) : null;
  return <div data-stage1="climb" data-object-layer="climb-economy" className="climb-vault-stack">
    <Sheet surface="climb" title={copy.hillHeading}>
      <Stage1State query={query}>
        {data && <>
          <Row surface="climb" label={copy.backing} value={backing != null ? `${formatBaseUnits(backing, 9, 9)} SOL` : null} />
          {exactUnits(data.lineLamports) && <Row surface="climb" label={copy.line} value={`${formatBaseUnits(data.lineLamports, 9, 9)} SOL`} />}
          {typeof data.bonded === 'boolean' && <Row surface="climb" label={data.bonded ? copy.bonded : copy.unbonded} />}
          {exactUnits(data.foundingCount) && <Row surface="climb" label={copy.founders} value={formatBaseUnits(data.foundingCount, 0, 0)} />}
          {data.assets.map(asset => <div key={asset.mint}>
            {asset.weekPool?.available != null && <PayRow surface="climb" label={copy.pool} row={{ hill, week: data.week!, mint: asset.mint, amount: asset.weekPool.available }} />}
            {asset.weekPool?.pool != null && <PayRow surface="climb" label={copy.sharedPool} row={{ hill, week: data.week!, mint: asset.mint, amount: asset.weekPool.pool }} />}
          </div>)}
          {data.split && <Row surface="climb" label={copy.split} detail={[copy.ascents, 'Leaderboard pool', 'Local Legend'].join(' / ')} value={[data.split.everyRiderByAscents, data.split.topTen, data.split.localLegend].every(n => typeof n === 'number') ? [data.split.everyRiderByAscents, data.split.topTen, data.split.localLegend].map(n => formatPercent(n, 0)).join(' / ') : null} />}
          {!data.assets.length && <StateRow title={copy.empty} />}
        </>}
      </Stage1State>
    </Sheet>
    {user && <Owner key={`${user.id}:${user.wallet}:${hill}`} hill={hill} surface="climb" bonding={data} />}
  </div>;
}
