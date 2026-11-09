import { PublicPageShell } from '../components/auth/PublicPageShell';
import { RideAnalysisLink } from '../components/auth/RideAnalysisLink';
import { browserPageName, composeBrowserTitle } from '../lib/browserTitle';
import { PageLoading } from '../components/loading/PageLoading';
import { FailureSheet, StateRow } from '../components/portal/FailureSpecies';
import ProfileGroundMap from '../components/profile/ProfileGroundMap';
import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useState,
} from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { usePublicPreview } from '../hooks/queries';
import { useFormatters } from '../hooks/useFormatters';
import type {
  ClimbPublicPreview,
  PublicPreviewRiderRef,
  RidePublicPreview,
  RiderPublicPreview,
  UserLeaderboardSummaryResponse,
} from '../lib/api';
import { getPublicPreviewRoute } from '../lib/publicPreviewRoutes';
import { formatDateTime } from '../lib/formatters';
import ClimbShapeGlyph from '../components/climbs/ClimbShapeGlyph';
import ClimbIdentity from '../components/climb/ClimbIdentity';
import ClimbGeography from '../components/climb/ClimbGeography';
import ClimbLeaderboard from '../components/climb/ClimbLeaderboard';
import { Stage1ClimbSection } from '../components/stage1/Stage1';
import {
  RidePageGeography,
  RidePageIdentity,
} from '../components/ride/RidePageComponents';
import ProfileLedgerColumn from '../components/profile/ProfileLedgerColumn';
import ProfileRecentRides from '../components/profile/ProfileRecentRides';
import { rideFromPublic } from '../components/profile/groundModel';
import '../styles/portal-public-pages.css';

const EMPTY: never[] = [];
const finite = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);
function riderName(rider: PublicPreviewRiderRef | null | undefined) {
  return rider?.identityHidden
    ? 'Rider'
    : rider?.displayName || rider?.displayLabel || rider?.username || 'Rider';
}
function riderPath(rider: PublicPreviewRiderRef | null | undefined) {
  if (!rider || rider.identityHidden) return null;
  const id = rider.username || rider.id;
  return id ? `/riders/${encodeURIComponent(id.replace(/^@+/, ''))}` : null;
}

function RidePreview({
  preview,
  openDoor,
}: {
  preview: RidePublicPreview;
  openDoor: () => void;
}) {
  const f = useFormatters(),
    ride = preview.ride;
  const routePreview =
    preview.assets.routePreview?.preview ?? ride.routePreview ?? null;
  const name = riderName(ride.rider);
  const media = preview.assets.media?.items ?? ride.media ?? [];
  const visibleMedia = media.filter((item) => item.url);
  const [photosOpen, setPhotosOpen] = useState(false);
  return (
    <div
      className="ride-detail-page ride-page portal-object-page portal-object-page--ride"
      data-object-page="ride"
    >
      <RidePageGeography
        viewer="stranger"
        routePreview={routePreview}
        samples={EMPTY}
        spans={EMPTY}
        power={EMPTY}
        identity={
          <RidePageIdentity
            viewer="stranger"
            riderProfileHref={riderPath(ride.rider)}
            riderDisplayName={name}
            riderAvatarUrl={
              ride.rider?.identityHidden ? null : ride.rider?.avatarUrl
            }
            riderInitials={name
              .split(/\s+/)
              .map((word) => word[0])
              .slice(0, 2)
              .join('')}
            rideStartedLabel={
              ride.startedAt || ride.createdAt
                ? formatDateTime(ride.startedAt || ride.createdAt)
                : ''
            }
            placeLabel={routePreview?.placeLabel}
            pageTitle={ride.title || preview.title}
            stats={[
              [
                'Distance',
                finite(ride.distanceM) ? f.distance(ride.distanceM) : null,
              ],
              [
                'Elevation',
                finite(ride.elevationM) ? f.elevation(ride.elevationM) : null,
              ],
              [
                'Time',
                finite(ride.durationS) ? f.duration(ride.durationS) : null,
              ],
            ]}
          />
        }
      >
        <RideAnalysisLink viewer="stranger" onOpen={openDoor} />
        {visibleMedia.length > 0 && (
          <section className="public-page-photos">
            <button
              className="ride-page-kv"
              type="button"
              aria-expanded={photosOpen}
              onClick={() => setPhotosOpen((value) => !value)}
            >
              <span>Ride photos</span>
              <span aria-hidden="true">›</span>
            </button>
            {photosOpen && (
              <div className="public-page-photo-grid">
                {visibleMedia.map((item) => (
                  <img key={item.id} src={item.url!} alt="Ride photo" />
                ))}
              </div>
            )}
          </section>
        )}
      </RidePageGeography>
    </div>
  );
}

function ClimbPreview({ preview }: { preview: ClimbPublicPreview }) {
  const climb = preview.climb;
  const board = climb.recordBoard ?? preview.assets.recordBoard?.preview;
  const routePreview =
    preview.assets.routePreview?.preview ?? climb.routePreview ?? null;
  return (
    <div
      className="climb-detail-page public-climb-detail portal-object-page"
      data-object-page="climb"
    >
      <div className="climb-detail-frame">
        <ClimbGeography
          viewer="stranger"
          key={climb.id}
          climb={{ ...climb, routePreview }}
          identity={
            <>
              {climb.elevationProfile?.length ? (
                <div className="climb-page-glyph">
                  <ClimbShapeGlyph profile={climb.elevationProfile} />
                </div>
              ) : null}
              <ClimbIdentity viewer="stranger" climb={climb} />
            </>
          }
        >
          {board && (
            <div className="public-page-climb-ledger">
              <ClimbLeaderboard
                viewer="stranger"
                entries={board.entries.map((entry) => ({
                  key: `${entry.rank}-${entry.completionId || 'result'}`,
                  seat: entry.position ?? entry.rank,
                  rank: entry.competitionRank ?? entry.rank,
                  tied: entry.isTied,
                  name: riderName(entry.rider),
                  path: riderPath(entry.rider),
                  identityHidden: entry.rider.identityHidden,
                  timeS: entry.bestTimeSeconds,
                  avgPowerW: entry.avgPowerW,
                  powerKind: entry.powerKind,
                  estimatedPowerW: entry.estimatedPowerW,
                  estimatedPowerRangeW: entry.estimatedPowerRangeW,
                  wPerKg: entry.wPerKg,
                  effortId: entry.effortId,
                  rideId: entry.rideId,
                  achievedAt: entry.achievedAt,
                }))}
              />
              <p className="climb-ledger-note">
                Names use public profiles only.
              </p>
            </div>
          )}
          <Stage1ClimbSection climbId={climb.canonId ? climb.id : undefined} />
        </ClimbGeography>
      </div>
    </div>
  );
}

function RiderPreview({ preview }: { preview: RiderPublicPreview }) {
  const navigate = useNavigate();
  const [tab, setTab] = useState<'overview' | 'rides'>('overview');
  const profile = preview.profile ?? {},
    rider = preview.rider;
  const canView =
    preview.seo.robots !== 'noindex,nofollow' &&
    preview.recentRides?.isPublic !== false;
  const leaderboard = preview.leaderboard as
    | Partial<UserLeaderboardSummaryResponse>
    | null
    | undefined;
  const positions =
    canView && Array.isArray(leaderboard?.positions)
      ? leaderboard.positions
      : [];
  const stats = canView ? leaderboard?.stats : null;
  const rides = canView
    ? (preview.recentRides?.rides ?? []).map(rideFromPublic)
    : [];
  // The preview contains leaderboard facts, but no canon geometry or canonical
  // climb IDs for these positions. Keep those rows read-only; do not fetch an
  // authenticated ground or turn an absent join into a fabricated map/ridden count.
  return (
    <div
      className="profile-page public-page-profile portal-object-page"
      data-object-page="rider"
    >
      <div className="portal-frame">
        <div className="profile-ground" data-object-layer="rider-ground">
          <ProfileGroundMap ground={EMPTY} onOpenClimb={() => {}} />
          <div className="profile-ground__fade" aria-hidden="true" />
        <div
          className="public-page-profile-column profile-ledger-layer"
          data-object-layer="rider-identity"
        >
          <ProfileLedgerColumn
            viewer="stranger"
            displayName={riderName(rider)}
            handle={
              rider?.identityHidden
                ? null
                : rider?.username?.replace(/^@+/, '') || null
            }
            location={null}
            bio={canView ? profile.bio || null : null}
            avatarUrl={
              rider?.identityHidden
                ? null
                : rider?.avatarUrl || profile.avatarUrl || null
            }
            createdAt={canView ? profile.createdAt || null : null}
            followerCount={
              canView && finite(profile.followerCount)
                ? profile.followerCount
                : null
            }
            followingCount={
              canView && finite(profile.followingCount)
                ? profile.followingCount
                : null
            }
            follow={null}
            menu={null}
            rides={
              canView && finite(profile.totalRides) ? profile.totalRides : null
            }
            seats={finite(stats?.top10Count) ? stats.top10Count : null}
            crowns={finite(stats?.komCount) ? stats.komCount : null}
            riddenCount={null}
            positionsState="ready"
            retryingPositions={false}
            onRetryPositions={() => {}}
            rows={positions
              .filter((position) => finite(position.rank) && position.rank > 0)
              .map((position) => ({
                key: `${position.vaultId}`,
                rank: position.rank,
                name: position.vaultName,
                sub: null,
                timeSeconds: finite(position.bestTimeSeconds)
                  ? position.bestTimeSeconds
                  : null,
                achievedAt: position.achievedAt,
              }))}
          >
            {!canView && (
              <div className="public-page-private">
                <strong>Private profile</strong>
                <p>Sign in to request full profile access.</p>
              </div>
            )}
          </ProfileLedgerColumn>
        </div>
        </div>
        {canView && (
          <>
            <div
              className="profile-tabs"
              role="tablist"
              aria-label="Profile sections"
            >
              {(['overview', 'rides'] as const).map((value) => (
                <button
                  key={value}
                  id={`preview-tab-${value}`}
                  type="button"
                  role="tab"
                  className="profile-tabs__tab"
                  aria-selected={tab === value}
                  aria-controls="preview-profile-content"
                  tabIndex={tab === value ? 0 : -1}
                  onClick={() => setTab(value)}
                  onKeyDown={(event) => {
                    if (
                      ['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(
                        event.key,
                      )
                    ) {
                      event.preventDefault();
                      const next =
                        event.key === 'Home'
                          ? 'overview'
                          : event.key === 'End'
                            ? 'rides'
                            : tab === 'overview'
                              ? 'rides'
                              : 'overview';
                      setTab(next);
                      document.getElementById(`preview-tab-${next}`)?.focus();
                    }
                  }}
                >
                  {value === 'overview' ? 'Overview' : 'Rides'}
                </button>
              ))}
            </div>
            <div
              id="preview-profile-content"
              className="profile-content"
              role="tabpanel"
              aria-labelledby={`preview-tab-${tab}`}
            >
              <div className="profile-boxes profile-boxes--single">
                <ProfileRecentRides
                  viewer="stranger"
                  rides={rides}
                  limit={tab === 'rides' ? rides.length : undefined}
                  title={tab === 'rides' ? 'Rides' : 'Recent rides'}
                  onOpenRide={(id) =>
                    navigate(`/rides/${encodeURIComponent(id)}`)
                  }
                />
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function PublicPreviewPage() {
  const location = useLocation();
  const route = useMemo(
    () => getPublicPreviewRoute(location.pathname),
    [location.pathname],
  );
  const previewQuery = usePublicPreview(route);
  const preview = previewQuery.data;

  useLayoutEffect(() => {
    document.title = previewQuery.isPlaceholderData ? composeBrowserTitle(null, browserPageName(location.pathname))
      : preview?.seo?.title || composeBrowserTitle(null, browserPageName(location.pathname));
  }, [location.pathname, preview?.seo?.title, previewQuery.isPlaceholderData]);

  useEffect(() => {
    if (!preview?.seo?.title) return;

    let robots = document.querySelector('meta[name="robots"]') as HTMLMetaElement | null;
    if (!robots) {
      robots = document.createElement('meta');
      robots.name = 'robots';
      document.head.appendChild(robots);
    }
    robots.content = preview.seo.robots || 'index,follow';
  }, [preview?.seo?.robots, preview?.seo?.title]);
  return (
    <PublicPageShell key={location.pathname}>
      {(openDoor) => {
        if (previewQuery.isLoading)
          return <PageLoading />;
        if (route && previewQuery.isError && (previewQuery.error as { statusCode?: number }).statusCode !== 404) return <PageLoading failure={<StateRow title="Preview unavailable" action={<button onClick={() => void previewQuery.refetch()}>Try again</button>} />} />;
        if (!route || !preview || previewQuery.isError)
          return (
            <FailureSheet title="Preview unavailable" description={null} doors={[{ label: 'Feed', href: '/' }, { label: 'Map', href: '/climbs' }, { label: 'Rides', href: '/profile?tab=rides' }]} />
          );
        if (preview.objectType === 'ride')
          return <RidePreview preview={preview} openDoor={openDoor} />;
        if (preview.objectType === 'climb')
          return <ClimbPreview preview={preview} />;
        return <RiderPreview preview={preview} />;
      }}
    </PublicPageShell>
  );
}
