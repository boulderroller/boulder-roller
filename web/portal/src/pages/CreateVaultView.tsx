import { lazy, Suspense, useMemo } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { AlertTriangle, ArrowLeft, MapPinned, Mountain } from 'lucide-react';
import { WalletTransactionSignerBridge } from '../components/auth/WalletTransactionSignerBridge';
import { useDeferredWalletTransactionSigner } from '../components/auth/useDeferredWalletTransactionSigner';
import { LoadingRows } from '../components/loading/LoadingSystem';
import {
  StateRow,
  PortalFrame,
  PortalPage,
} from '../components/portal/PortalSpine';
import { useIsMobile } from '../components/ui/use-mobile';
import { CanonVaultCreationForm } from '../components/vault/CanonVaultCreationForm';
import { useCanonVaultCreation } from '../components/vault/useCanonVaultCreation';
import ClimbProfileHero from '../components/climb/ClimbProfileHero';
import { useClimbDetail } from '../hooks/queries';
import { useFormatters } from '../hooks/useFormatters';
import type { Climb, GpsPoint, RoutePreview } from '../lib/api';
import { ABSENT_VALUE } from '../lib/formatters';
import ClimbView from './ClimbView';

const RouteMap = lazy(() => import('../components/ride/RouteMap'));

function canonicalRoutePoints(routePreview: RoutePreview | null | undefined): GpsPoint[] {
  const bounds = routePreview?.bounds;
  const points = routePreview?.points ?? [];
  if (!bounds || points.length < 2) return [];
  const latSpan = bounds.maxLat - bounds.minLat;
  const lonSpan = bounds.maxLon - bounds.minLon;
  if (!(latSpan > 0) || !(lonSpan > 0)) return [];

  return points.flatMap((point, index) => {
    if (!Number.isFinite(point.x) || !Number.isFinite(point.y)) return [];
    const x = Math.max(0, Math.min(1, point.x));
    const y = Math.max(0, Math.min(1, point.y));
    return [{
      sequenceNum: index,
      timestamp: new Date(index * 1000).toISOString(),
      latitude: bounds.maxLat - (y * latSpan),
      longitude: bounds.minLon + (x * lonSpan),
    }];
  });
}

function ElevationSparkline({ climb }: { climb: Climb }) {
  const profile = (climb.elevationProfile ?? []).filter((point) => (
    Number.isFinite(point.distanceM) && Number.isFinite(point.elevationM)
  ));
  if (profile.length < 2) {
    return <span className="create-vault-identity__profile-empty">Profile unavailable</span>;
  }
  return (
    <div className="create-vault-identity__profile" aria-label="Elevation profile">
      <ClimbProfileHero profile={profile} compact />
    </div>
  );
}

function MobileCreateVaultView() {
  const { climbId } = useParams<{ climbId: string }>();
  const navigate = useNavigate();
  return (
    <ClimbView
      initialCreationOpen
      onCreationClose={() => navigate(`/climbs/${climbId ?? ''}`, { replace: true })}
    />
  );
}

function DesktopCreateVaultView() {
  const { climbId } = useParams<{ climbId: string }>();
  const navigate = useNavigate();
  const detailQuery = useClimbDetail(climbId);
  const { distance: formatDistance, elevation: formatElevation, percent: formatPercent } = useFormatters();
  const {
    setSignerRef,
    signerEnabled,
    signPreparedTransaction,
  } = useDeferredWalletTransactionSigner();
  const climb = detailQuery.data ?? null;
  const paymentMethods = climb?.vaultCreation?.paymentMethods ?? [];
  const canCreateVault = Boolean(
    climb
    && climb.vaultCreation?.state === 'available'
    && paymentMethods.length > 0
    && !climb.vaultEconomy?.hasVault
    && !climb.hasVault,
  );
  const creation = useCanonVaultCreation({
    climbId: climb?.id,
    canonId: climb?.canonId,
    canonVersion: climb?.version,
    enabled: canCreateVault,
    signPreparedTransaction,
  });
  const routePoints = useMemo(
    () => canonicalRoutePoints(climb?.routePreview),
    [climb?.routePreview],
  );
  const backPath = `/climbs/${climb?.id ?? climbId ?? ''}`;

  if (detailQuery.isLoading && !climb) {
    return (
      <PortalPage className="create-vault-page">
        <PortalFrame className="create-vault-frame">
          <LoadingRows
            label="Loading climb"
            description="Opening the route and Vault choices."
            rows={6}
          />
        </PortalFrame>
      </PortalPage>
    );
  }

  if (!climb || detailQuery.error) {
    return (
      <PortalPage className="create-vault-page">
        <PortalFrame className="create-vault-frame">
          <StateRow
            icon={<AlertTriangle size={34} aria-hidden="true" />}
            title="Could not open this climb"
            description={detailQuery.error instanceof Error ? detailQuery.error.message : 'The climb is unavailable.'}
            action={<Link to="/climbs" className="portal-action-button">All climbs</Link>}
          />
        </PortalFrame>
      </PortalPage>
    );
  }

  return (
    <PortalPage
      className="create-vault-page"
      data-object-page="create-vault"
      aria-busy={detailQuery.isFetching || creation.isBusy}
      aria-live="polite"
    >
      <WalletTransactionSignerBridge enabled={signerEnabled} onSignerReady={setSignerRef} />
      <PortalFrame className="create-vault-frame">
        <Link to={backPath} className="climb-detail-back create-vault-back">
          <ArrowLeft size={15} aria-hidden="true" />
          <span>Back to climb</span>
        </Link>

        <div className="create-vault-layout">
          <main className="create-vault-route-column">
            <section className="create-vault-identity" aria-label="Climb summary">
              <div className="create-vault-identity__mark" aria-hidden="true">
                <Mountain size={24} />
              </div>
              <div className="create-vault-identity__copy">
                <h1>{climb.name || 'Climb'}</h1>
                <span>{climb.region || climb.routePreview?.placeLabel || 'Climb route'}</span>
              </div>
              <div className="create-vault-identity__facts">
                <div><span>Distance</span><strong>{formatDistance(climb.lengthM)}</strong></div>
                <div><span>Elevation</span><strong>{formatElevation(climb.elevGainM)}</strong></div>
                <div><span>Grade</span><strong>{climb.avgGradientPct == null ? ABSENT_VALUE : formatPercent(climb.avgGradientPct)}</strong></div>
              </div>
              <ElevationSparkline climb={climb} />
            </section>

            <section className="create-vault-map" aria-label="Canonical climb route map">
              <div className="create-vault-map__label">
                <MapPinned size={15} aria-hidden="true" />
                <span>{climb.routePreview?.placeLabel || climb.region || 'Route map'}</span>
              </div>
              <Suspense fallback={<LoadingRows label="Loading route map" rows={4} />}>
                <RouteMap
                  gpsPoints={routePoints}
                  height="clamp(540px, calc(100vh - 270px), 760px)"
                  baseMapStyle="terrainBg"
                />
              </Suspense>
            </section>
          </main>

          <aside className="create-vault-workspace" aria-label="Create Vault">
            <header className="create-vault-workspace__heading">
              <span>Vault</span>
              <h2>Create Vault</h2>
              <p>Choose a cost and create the Vault attached to this climb.</p>
            </header>

            {canCreateVault ? (
              <CanonVaultCreationForm
                climbName={climb.name || 'Climb'}
                error={creation.error}
                onBack={() => navigate(backPath)}
                onConfirm={creation.createVault}
                onOpenVault={() => navigate(`${backPath}#climb-vault`)}
                paymentMethods={paymentMethods}
                phase={creation.phase}
                result={creation.result}
              />
            ) : (
              <StateRow
                icon={<Mountain size={32} aria-hidden="true" />}
                title={climb.vaultCreation?.state === 'reserved' ? 'Vault creation is in progress' : 'Vault creation is unavailable'}
                description={climb.vaultCreation?.state === 'active' ? 'This climb already has a Vault.' : 'Return to the climb for its current status.'}
                action={<Link to={backPath} className="portal-action-button">Back to climb</Link>}
              />
            )}
          </aside>
        </div>
      </PortalFrame>
    </PortalPage>
  );
}

export default function CreateVaultView() {
  const isMobile = useIsMobile();
  return isMobile ? <MobileCreateVaultView /> : <DesktopCreateVaultView />;
}
