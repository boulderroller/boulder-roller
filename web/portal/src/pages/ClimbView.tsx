import { useBrowserTitleObject } from '../contexts/BrowserTitleContext';
import { IdentitySlots } from '../components/loading/PageLoading';
import { SlotRows } from '../components/loading/Slot';
import { FailureSheet, StateRow } from '../components/portal/FailureSpecies';
import { useEffect, useRef, useState } from 'react';
import { Link, Navigate, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import ClimbShapeGlyph from '../components/climbs/ClimbShapeGlyph';
import { ArrowLeft } from 'lucide-react';
import { RouteLoadingFallback } from '../components/loading/LoadingSystem';
import { WalletTransactionSignerBridge } from '../components/auth/WalletTransactionSignerBridge';
import { useDeferredWalletTransactionSigner } from '../components/auth/useDeferredWalletTransactionSigner';
import { CanonVaultCreationModal } from '../components/vault/CanonVaultCreationModal';
import { useCanonVaultCreation } from '../components/vault/useCanonVaultCreation';
import { useIsMobile } from '../components/ui/use-mobile';
import { PortalFrame, PortalPage } from '../components/portal/PortalSpine';
import { useClimbDetail, useClimbLeaderboard, useVaultLeaderboard } from '../hooks/queries';
import { getPublicRiderPath } from '../lib/riderIdentity';
import ClimbVaultSection from './VaultView';
import ClimbIdentity from '../components/climb/ClimbIdentity';
import ClimbGeography from '../components/climb/ClimbGeography';
import ClimbLeaderboard, { type ClimbResultRow } from '../components/climb/ClimbLeaderboard';
import ClimbLegend from '../components/climb/ClimbLegend';
import ClimbRides from '../components/climb/ClimbRides';
import { useClimbPanelPath } from '../components/climb/ClimbNavigation';

export function LegacyVaultDetailRedirect() {
  const { vaultId } = useParams<{ vaultId: string }>();
  const parsedVaultId = vaultId && /^\d+$/.test(vaultId) ? Number(vaultId) : null;
  const numericVaultId = parsedVaultId !== null && Number.isSafeInteger(parsedVaultId)
    ? parsedVaultId
    : null;
  const leaderboardQuery = useVaultLeaderboard(numericVaultId ?? undefined, numericVaultId !== null);

  if (numericVaultId === null || leaderboardQuery.isError) {
    return <Navigate to="/climbs?hasVault=true" replace />;
  }

  if (leaderboardQuery.data?.climbId) {
    return <Navigate to={`/climbs/${encodeURIComponent(leaderboardQuery.data.climbId)}`} replace />;
  }

  return <RouteLoadingFallback />;
}


interface ClimbViewProps {
  initialCreationOpen?: boolean;
  onCreationClose?: () => void;
}

export default function ClimbView({ initialCreationOpen = false, onCreationClose }: ClimbViewProps = {}) {
  const { user } = useAuth();
  const { climbId } = useParams<{ climbId: string }>();
  const navigate = useNavigate();
  const [search] = useSearchParams();
  const panelPath = useClimbPanelPath();
  const panel = search.get('climbView');
  const isMobile = useIsMobile();
  const { setSignerRef, signerEnabled, signPreparedTransaction } = useDeferredWalletTransactionSigner();
  const [creationOpen, setCreationOpen] = useState(initialCreationOpen);
  const detailQuery = useClimbDetail(climbId);
  const climb = detailQuery.data;
  useBrowserTitleObject(detailQuery.isPlaceholderData ? null : climb?.name || null);
  const hasVault = Boolean(climb?.vaultEconomy?.hasVault || climb?.hasVault);
  const vaultId = hasVault ? climb?.vaultEconomy?.vaultId ?? climb?.vaultId : null;
  const boardQuery = useVaultLeaderboard(vaultId ?? undefined);
  const noVaultBoardQuery = useClimbLeaderboard(vaultId == null ? climbId : undefined);
  const board = vaultId != null ? boardQuery : noVaultBoardQuery;
  const methods = climb?.vaultCreation?.paymentMethods ?? [];
  const canCreate = !hasVault && climb?.vaultCreation?.state === 'available' && methods.length > 0;
  const creation = useCanonVaultCreation({ climbId: climb?.id, canonId: climb?.canonId, canonVersion: climb?.version, enabled: canCreate, signPreparedTransaction });
  const closeCreation = () => { if (!creation.isBusy) { setCreationOpen(false); onCreationClose?.(); } };
  useEffect(() => {
    if (initialCreationOpen && creationOpen && !detailQuery.isLoading && climb && !canCreate) {
      setCreationOpen(false); onCreationClose?.();
    }
  }, [initialCreationOpen, creationOpen, detailQuery.isLoading, climb, canCreate, onCreationClose]);

  const boardEntries = vaultId != null ? (boardQuery.data?.leaderboard ?? [])
    : (noVaultBoardQuery.data?.entries ?? []).map(entry => ({ ...entry, bestTimeSeconds: entry.timeS }));
  const viewerEntry = board.data?.viewerEntry;
  const visibleEntries = viewerEntry && !boardEntries.some(entry => entry.wallet === viewerEntry.wallet)
    ? [...boardEntries, viewerEntry] : boardEntries;
  const entries: ClimbResultRow[] = visibleEntries.map((entry) => {
    const isViewer = Boolean(user && (entry.userId === user.id || user.wallet && entry.wallet === user.wallet));
    const rider = isViewer ? user! : entry;
    const visibleIdentity = Boolean(!entry.identityHidden && (rider.displayName || rider.username));
    return { key: `${entry.position ?? entry.rank}-${entry.completionId ?? entry.wallet}`, seat: entry.position ?? entry.rank,
      rank: entry.competitionRank ?? entry.rank, tied: entry.isTied, name: rider.displayName || rider.username || 'Rider',
      identityHidden: entry.identityHidden, path: visibleIdentity ? getPublicRiderPath(rider) : null,
      timeS: entry.bestTimeSeconds, avgPowerW: entry.avgPowerW, powerKind: entry.powerKind,
      estimatedPowerW: entry.estimatedPowerW, estimatedPowerRangeW: entry.estimatedPowerRangeW,
      wPerKg: entry.wPerKg, effortId: entry.effortId, rideId: entry.rideId, achievedAt: visibleIdentity ? entry.achievedAt : null,
      isViewer };
  });
  const ownResult = !board.isError && user ? viewerEntry ?? boardEntries.find(entry => entry.userId === user.id || Boolean(user.wallet && entry.wallet === user.wallet)) : undefined;
  const panelNames: Record<string, string> = { rides: 'Your history', history: 'DUNG history', deposit: 'Deposit CAL', withdraw: 'Withdraw CAL', collect: 'Collect DUNG' };
  const showingPanel = vaultId != null && panel != null && Object.prototype.hasOwnProperty.call(panelNames, panel);
  const previousPanel = useRef<string | null>(null);
  const panelHeading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (showingPanel) panelHeading.current?.focus();
    else if (previousPanel.current) {
      const destination = panelPath(previousPanel.current as 'rides' | 'history' | 'deposit' | 'withdraw' | 'collect');
      Array.from(document.querySelectorAll<HTMLAnchorElement>('.climb-detail-frame a')).find((link) => link.getAttribute('href') === destination)?.focus();
    }
    previousPanel.current = showingPanel ? panel : null;
  }, [showingPanel, panel]);


  if (detailQuery.isError && /404|not.?found/i.test(detailQuery.error instanceof Error ? detailQuery.error.message : '')) {
    return <FailureSheet title="Climb not found" description={null} doors={[{ label: 'Map', href: '/climbs' }]} />;
  }

  return <PortalPage className="climb-detail-page portal-object-page portal-object-page--climb" data-object-page="climb">
    <WalletTransactionSignerBridge enabled={signerEnabled} onSignerReady={setSignerRef} />
    <PortalFrame className="climb-detail-frame">
      {showingPanel ? <Link to={panelPath()} className="climb-detail-back"><ArrowLeft size={15} aria-hidden="true" />Back</Link>
        : <Link to="/climbs" className="climb-detail-back climb-page-back"><ArrowLeft size={15} aria-hidden="true" />All climbs</Link>}
      {detailQuery.isPending ? <div aria-busy="true"><ClimbGeography identity={<IdentitySlots climb />}><div className="climb-detail-columns"><section><h2>Leaderboard</h2><SlotRows count={10} /></section><section><h2>Vault</h2><SlotRows count={4} /></section></div></ClimbGeography><span className="sr-only" role="status">Loading climb</span></div>
        : !climb ? <ClimbGeography identity={<StateRow title="Climb unavailable" action={<button type="button" onClick={() => void detailQuery.refetch()}>Try again</button>} />} />
        : <>
          {detailQuery.isError && <div className="climb-ledger-note" role="status">Showing the last loaded climb. <button className="climb-text-button" onClick={() => void detailQuery.refetch()}>Try again</button></div>}
          {showingPanel ? <div className="climb-reading-panel"><h1 ref={panelHeading} tabIndex={-1}>{panelNames[panel]}</h1><p className="climb-place">{climb.name}</p>
            {panel === 'rides' ? <ClimbRides key={`${vaultId}-rides`} vaultId={vaultId} full /> : <ClimbVaultSection key={vaultId} vaultId={vaultId} climbId={climb.canonId ? climb.id : undefined} panel={panel as 'deposit' | 'withdraw' | 'collect' | 'history'} />}
          </div> : <>
            <ClimbGeography key={climb.id} climb={climb} identity={<>
              <div className="climb-page-glyph"><ClimbShapeGlyph profile={climb.elevationProfile} /></div>
              <ClimbIdentity climb={climb} />
              {vaultId != null && <ClimbRides vaultId={vaultId} best rank={ownResult?.competitionRank ?? ownResult?.rank} />}
            </>}>
            <div className="climb-detail-columns">
              <div className="climb-record-stack">
                <ClimbLeaderboard entries={entries} loading={board.isPending} error={board.isError} onRetry={() => void board.refetch()}
                  source={vaultId == null ? noVaultBoardQuery.data?.source : undefined}
                  earlierVersionId={vaultId == null ? noVaultBoardQuery.data?.earlierVersionId : undefined} />
                {vaultId != null && <><ClimbLegend vaultId={vaultId} /><ClimbRides vaultId={vaultId} /></>}
              </div>
              <ClimbVaultSection key={climb.id} vaultId={vaultId} climbId={climb.canonId ? climb.id : undefined} fallback={<section id="climb-vault" aria-label="Vault" data-object-layer="climb-economy">
                <div className="climb-section-heading"><h2>Vault</h2></div>
                <div className="climb-ledger-card"><div className="climb-ledger-empty">{climb.vaultCreation?.state === 'reserved' ? 'This vault is still opening.' : 'No vault'}</div>
                  {canCreate && <button type="button" className="climb-action-row" onClick={() => { creation.reset(); if (isMobile) setCreationOpen(true); else navigate(`/climbs/${climb.id}/create-vault`); }}>Create Vault</button>}
                </div>
              </section>} />
            </div>
            </ClimbGeography>
          </>}
          {creationOpen && canCreate && <CanonVaultCreationModal climbName={climb.name || 'Climb'} error={creation.error} onClose={closeCreation} onConfirm={creation.createVault} onOpenVault={() => navigate(`/climbs/${climb.id}#climb-vault`)} paymentMethods={methods} phase={creation.phase} result={creation.result} />}
        </>}
    </PortalFrame>
  </PortalPage>;
}
