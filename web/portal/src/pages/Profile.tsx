import { useBrowserTitleObject } from '../contexts/BrowserTitleContext';
import { PageLoading } from '../components/loading/PageLoading';
import { lazy, Suspense, useState, useEffect, useCallback, useMemo, type KeyboardEvent } from 'react';
import { useParams, useNavigate, useLocation } from 'react-router-dom';
import { Activity, AlertTriangle } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { LoadingRows } from '../components/loading/LoadingSystem';
import {
  StateRow,
  PortalFrame,
  PortalPage,
  PortalPanel,
  PortalPanelBody,
  PortalPanelHeader,
} from '../components/portal/PortalSpine';
import ProfileGroundMap from '../components/profile/ProfileGroundMap';
import ProfileLedgerColumn, { type LedgerRow } from '../components/profile/ProfileLedgerColumn';
import ProfilePhotoBand from '../components/profile/ProfilePhotoBand';
import ProfileRecentRides from '../components/profile/ProfileRecentRides';
import ProfileYearCard from '../components/profile/ProfileYearCard';
import {
  buildGround,
  collectPhotos,
  positionKind,
  rideFromOwn,
  rideFromPublic,
  ridesThisYear,
  sortRidesNewestFirst,
  type ProfileRide,
} from '../components/profile/groundModel';
import { api } from '../lib/api';
import { toast } from 'sonner';
import type { User, PublicProfile, PublicRiderProfileResponse } from '../lib/api';
import { normalizeRiderHandle } from '../lib/riderIdentity';
import { useFormatters } from '../hooks/useFormatters';
import { useClimbs, useFeedSocialCounts, useMyLeaderboardPositions, useRides, useUserLeaderboardPositions } from '../hooks/queries';

// Profile — Ground (Tim-ratified 2026-09-02). The map is the page: the
// rider's ground with the canon drawn faint, their climbs in ink, the ones
// they hold in cobalt; the ledger column floating on it; then the photo
// band, This year and Recent rides. Constitution law 6: times are public,
// money is private — this page never shows CAL or DUNG, theirs or yours.

const loadMyActivities = () => import('./MyActivities');
const loadData = () => import('./Data');
const loadPortfolio = () => import('./Portfolio');
const MyActivities = lazy(loadMyActivities);
const Data = lazy(loadData);
const Portfolio = lazy(loadPortfolio);

const PROFILE_TAB_IDS = ['overview', 'rides', 'training', 'portfolio'] as const;
type ProfileTabId = typeof PROFILE_TAB_IDS[number];

const CANON_CLIMB_LIMIT = 100;
const OWN_RIDE_LIMIT = 400;
const LEDGER_ROWS = 6;

function isProfileTab(value: string | null): value is ProfileTabId {
  return PROFILE_TAB_IDS.includes(value as ProfileTabId);
}

function readProfileTab(search: string): ProfileTabId {
  const tab = new URLSearchParams(search).get('tab');
  return isProfileTab(tab) ? tab : 'overview';
}

function profileTabSearch(search: string, tab: ProfileTabId): string {
  const params = new URLSearchParams(search);
  if (tab === 'overview') {
    params.delete('tab');
  } else {
    params.set('tab', tab);
  }
  const nextSearch = params.toString();
  return nextSearch ? `?${nextSearch}` : '';
}

function preloadProfileTab(tab: ProfileTabId) {
  if (tab === 'rides') void loadMyActivities();
  if (tab === 'training') {
    void loadData();
    void import('./DataCore');
  }
  if (tab === 'portfolio') void loadPortfolio();
}

export default function Profile() {
  const { beetleNumber, riderId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { user: authUser } = useAuth();
  const { distance: formatDistance, percent: formatPercent } = useFormatters();
  const [loading, setLoading] = useState(true);
  const [profile, setProfile] = useState<User | PublicProfile | null>(null);
  const [error, setError] = useState<string | null>(null);

  const profileId = beetleNumber || riderId;
  const [loadedProfileId, setLoadedProfileId] = useState<string | undefined>(undefined);
  useBrowserTitleObject(!loading && !error && loadedProfileId === profileId
    ? profile?.displayName || profile?.username || null : null);
  const isOwnProfile = !profileId || profileId === authUser?.wallet?.slice(0, 8);
  const ownSocialCounts = useFeedSocialCounts(authUser?.id ?? null, isOwnProfile);
  const requestedTab = readProfileTab(location.search);
  const activeTab = isOwnProfile ? requestedTab : 'overview';

  const handleTabChange = (tab: ProfileTabId) => {
    preloadProfileTab(tab);
    navigate({
      pathname: location.pathname,
      search: profileTabSearch(location.search, tab),
      hash: '',
    });
  };

  const [isFollowing, setIsFollowing] = useState(false);
  const [isFollowLoading, setIsFollowLoading] = useState(false);
  const [followStatusLoading, setFollowStatusLoading] = useState(false);
  const [linkCopied, setLinkCopied] = useState(false);
  const [profileReportStatus, setProfileReportStatus] = useState<string | null>(null);
  const [isReportingProfile, setIsReportingProfile] = useState(false);
  const [publicRides, setPublicRides] = useState<{ rides: ProfileRide[]; count: number } | null>(null);
  const [publicProfileBootstrap, setPublicProfileBootstrap] = useState<PublicRiderProfileResponse | null>(null);
  const publicFollowState = publicProfileBootstrap?.followState;

  useEffect(() => {
    if (isOwnProfile) preloadProfileTab(activeTab);
  }, [activeTab, isOwnProfile]);

  useEffect(() => {
    let cancelled = false;

    const fetchProfile = async () => {
      try {
        setLoading(true);
        setError(null);

        if (isOwnProfile && authUser) {
          setProfile(authUser);
          setPublicProfileBootstrap(null);
          setPublicRides(null);
          setProfileReportStatus(null);
        } else if (isOwnProfile) {
          const userData = await api.getMe();
          if (cancelled) return;
          setProfile(userData);
          setPublicProfileBootstrap(null);
          setPublicRides(null);
          setProfileReportStatus(null);
        } else if (profileId) {
          setFollowStatusLoading(!!authUser);
          const publicData = await api.getPublicRiderProfile(profileId, 30);
          if (cancelled) return;
          setPublicProfileBootstrap(publicData);
          setProfile(publicData.profile);
          setPublicRides(
            publicData.recentRides?.isPublic
              ? {
                rides: publicData.recentRides.rides.map(rideFromPublic),
                count: publicData.recentRides.count ?? publicData.recentRides.rides.length,
              }
              : { rides: [], count: 0 },
          );
          if (publicData.followState) {
            setIsFollowing(!!publicData.followState.isFollowing);
          }
          setProfileReportStatus(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Could not load profile');
          if (!isOwnProfile) {
            setPublicProfileBootstrap(null);
            setPublicRides(null);
          }
        }
      } finally {
        if (!cancelled) {
          setLoadedProfileId(profileId);
          setLoading(false);
          if (!isOwnProfile) setFollowStatusLoading(false);
        }
      }
    };

    void fetchProfile();

    return () => {
      cancelled = true;
    };
  }, [authUser, isOwnProfile, profileId]);

  useEffect(() => {
    if (!isOwnProfile && publicFollowState) {
      setIsFollowing(!!publicFollowState.isFollowing);
      setFollowStatusLoading(false);
      return;
    }

    if (isOwnProfile || !authUser || !profile?.id) {
      setFollowStatusLoading(false);
      return;
    }

    let cancelled = false;

    const fetchFollowStatus = async () => {
      try {
        setFollowStatusLoading(true);
        const followStatus = await api.checkIsFollowing(profile.id);
        if (!cancelled) setIsFollowing(followStatus.isFollowing);
      } catch {
        if (!cancelled) setIsFollowing(false);
      } finally {
        if (!cancelled) setFollowStatusLoading(false);
      }
    };

    void fetchFollowStatus();

    return () => {
      cancelled = true;
    };
  }, [authUser, isOwnProfile, profile?.id, publicFollowState]);

  // The ground's data. Own profile: every ride of the year (the year card
  // only mounts when the list is complete), your positions. Visitor: the
  // rider's public rides from the bootstrap, their positions by wallet.
  const ownRidesQuery = useRides({
    limit: OWN_RIDE_LIMIT,
    enabled: isOwnProfile && Boolean(profile) && activeTab === 'overview',
  });
  const myPositionsQuery = useMyLeaderboardPositions(isOwnProfile && Boolean(authUser));
  const riderPositionsQuery = useUserLeaderboardPositions(
    isOwnProfile ? null : profile?.wallet,
    !isOwnProfile && Boolean(profile?.wallet),
  );
  const climbsQuery = useClimbs({ limit: CANON_CLIMB_LIMIT });

  const positionsQuery = isOwnProfile ? myPositionsQuery : riderPositionsQuery;
  const positionsResponse = positionsQuery.isPlaceholderData ? undefined : positionsQuery.data;
  const positions = positionsResponse?.positions;
  const climbs = useMemo(() => climbsQuery.data?.climbs ?? [], [climbsQuery.data]);
  const climbsByVault = useMemo(() => {
    const byVault = new Map<number, (typeof climbs)[number]>();
    for (const climb of climbs) {
      if (climb.vaultId != null && !byVault.has(climb.vaultId)) byVault.set(climb.vaultId, climb);
    }
    return byVault;
  }, [climbs]);
  // Aggregate holdings can outlive their indexed detail bindings. Do not turn
  // an incomplete response or canon join into zero ridden / unheld ground.
  const reportedPositionCount = positionsResponse?.stats.totalPositions;
  const positionsComplete = !positionsQuery.isError
    && positions != null
    && Number.isInteger(reportedPositionCount)
    && reportedPositionCount === positions.length;
  const groundComplete = positionsComplete && !climbsQuery.isError && climbsQuery.data != null
    && positions.every((position) => Number.isFinite(position.rank) && position.rank >= 1
      && climbsByVault.has(position.vaultId));
  const positionsState = groundComplete ? 'ready'
    : positionsQuery.isLoading || climbsQuery.isLoading || positionsQuery.isPlaceholderData ? 'loading'
      : 'unavailable';
  const positionsRetrying = positionsQuery.isFetching || climbsQuery.isFetching;
  const ground = useMemo(
    () => groundComplete ? buildGround(climbs, positions) : [],
    [climbs, groundComplete, positions],
  );
  const retryPositions = () => {
    void Promise.all([positionsQuery.refetch(), climbsQuery.refetch()]);
  };

  const rides = useMemo<ProfileRide[]>(() => {
    if (isOwnProfile) return (ownRidesQuery.data ?? []).map(rideFromOwn);
    return publicRides?.rides ?? [];
  }, [isOwnProfile, ownRidesQuery.data, publicRides]);
  const ridesComplete = isOwnProfile
    ? Boolean(ownRidesQuery.data) && (ownRidesQuery.data?.length ?? 0) < OWN_RIDE_LIMIT
    : Boolean(publicRides) && (publicRides?.count ?? 0) <= (publicRides?.rides.length ?? 0);
  const yearRides = useMemo(() => (ridesComplete ? ridesThisYear(rides) : null), [rides, ridesComplete]);
  const photos = useMemo(() => collectPhotos(rides), [rides]);
  const recentRides = useMemo(() => sortRidesNewestFirst(rides), [rides]);

  const handleShareProfile = useCallback(async () => {
    let profileUrl = window.location.href;
    const identifier = profile?.username || profile?.wallet || profile?.id;

    if (identifier) {
      try {
        const link = await api.resolveLink('rider', identifier);
        profileUrl = link.share.url || link.canonicalUrl || profileUrl;
      } catch {
        profileUrl = `${window.location.origin}/riders/${identifier}`;
      }
    }

    try {
      await navigator.clipboard.writeText(profileUrl);
      setLinkCopied(true);
      window.setTimeout(() => setLinkCopied(false), 2000);
    } catch {
      toast.error('Could not copy link');
    }
  }, [profile?.id, profile?.username, profile?.wallet]);

  const handleFollowToggle = useCallback(async () => {
    if (!profile?.id || isFollowLoading) return;
    const nextFollowing = !isFollowing;
    setIsFollowLoading(true);
    setIsFollowing(nextFollowing);
    try {
      if (nextFollowing) {
        await api.followUser(profile.id);
      } else {
        await api.unfollowUser(profile.id);
      }
    } catch {
      setIsFollowing(!nextFollowing);
      toast.error(nextFollowing ? 'Could not follow' : 'Could not unfollow');
    } finally {
      setIsFollowLoading(false);
    }
  }, [isFollowLoading, isFollowing, profile?.id]);

  const handleReportProfile = useCallback(async () => {
    if (!profile?.id || isOwnProfile || isReportingProfile || profileReportStatus) return;
    try {
      setIsReportingProfile(true);
      const report = await api.reportSocialContent('user', profile.id, 'other', 'Reported from profile');
      setProfileReportStatus(report.status);
      toast.success('Report sent');
    } catch {
      toast.error('Could not report profile');
    } finally {
      setIsReportingProfile(false);
    }
  }, [isOwnProfile, isReportingProfile, profile?.id, profileReportStatus]);

  const overviewTab = { id: 'overview', label: 'Overview' } as const;
  const tabs = isOwnProfile
    ? [
      overviewTab,
      { id: 'rides', label: 'Rides' } as const,
      { id: 'training', label: 'Training' } as const,
      { id: 'portfolio', label: 'Portfolio' } as const,
    ]
    : [overviewTab];

  const handleTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>, tab: ProfileTabId) => {
    const current = tabs.findIndex((item) => item.id === tab);
    const next = event.key === 'ArrowRight' ? (current + 1) % tabs.length
      : event.key === 'ArrowLeft' ? (current - 1 + tabs.length) % tabs.length
        : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : null;
    if (next == null) return;
    event.preventDefault();
    const selected = tabs[next].id;
    event.currentTarget.parentElement?.querySelector<HTMLButtonElement>(`#profile-tab-${selected}`)?.focus();
    handleTabChange(selected);
  };

  if (loading) return <PageLoading />;

  if (error || !profile) {
    return (
      <PortalPage className="profile-v2-state">
        <PortalFrame>
          <PortalPanel>
            <StateRow
              icon={<AlertTriangle size={34} aria-hidden="true" />}
              title={error || 'Profile not found'}
              description={error === 'Unauthorized' ? 'Sign in to view your profile.' : 'Could not open this profile.'}
              action={isOwnProfile ? (
                <button type="button" className="portal-action-button" onClick={() => navigate('/')}>
                  <Activity size={14} aria-hidden="true" />
                  <span>Feed</span>
                </button>
              ) : undefined}
            />
          </PortalPanel>
        </PortalFrame>
      </PortalPage>
    );
  }

  const displayName = profile.displayName || profile.username || 'Unnamed Rider';
  const riderHandle = normalizeRiderHandle(profile.username) || null;
  const riderLocation = 'location' in profile && typeof profile.location === 'string' && profile.location.trim()
    ? profile.location.trim()
    : null;
  const isPrivatePublicProfile = !isOwnProfile && !profile.isPublic;
  const followerCount = isOwnProfile ? ownSocialCounts.data?.followerCount ?? null : 'followerCount' in profile && typeof profile.followerCount === 'number' ? profile.followerCount : null;
  const followingCount = isOwnProfile ? ownSocialCounts.data?.followingCount ?? null : 'followingCount' in profile && typeof profile.followingCount === 'number' ? profile.followingCount : null;
  const stats = positionsResponse?.stats;
  const totalRides = profile.totalRides ?? rides.length;

  const ledgerRows: LedgerRow[] = [...(positions ?? [])]
    .filter((position) => Number.isFinite(position.rank) && position.rank >= 1)
    .sort((a, b) => a.rank - b.rank || (a.bestTimeSeconds ?? 0) - (b.bestTimeSeconds ?? 0))
    .slice(0, LEDGER_ROWS)
    .map((position) => {
      const climb = climbsByVault.get(position.vaultId) ?? null;
      const kind = positionKind(position);
      const sub = [
        climb?.lengthM != null && climb.lengthM > 0 ? formatDistance(climb.lengthM) : null,
        climb?.avgGradientPct != null && Number.isFinite(climb.avgGradientPct) ? formatPercent(climb.avgGradientPct) : null,
        kind,
      ].filter(Boolean).join(' · ');
      return {
        key: `${position.vaultId}-${position.rank}`,
        rank: position.rank,
        name: climb?.name || position.vaultName,
        sub: sub || null,
        timeSeconds: Number.isFinite(position.bestTimeSeconds) ? position.bestTimeSeconds : null,
        achievedAt: position.achievedAt ?? null,
        onOpen: () => navigate(climb ? `/climbs/${climb.id}` : `/vaults/${position.vaultId}`),
      };
    });

  const riddenCount = groundComplete && climbs.length > 0
    ? { ridden: new Set(positions.map((position) => position.vaultId)).size, total: climbs.length }
    : null;

  const openClimb = (climbId: string) => navigate(`/climbs/${climbId}`);
  const openRide = (rideId: string) => navigate(`/activities/${rideId}`);

  const profileGround = (
        <div
          className={activeTab === 'overview' ? 'profile-ground' : 'profile-ground profile-ground--masthead'}
          data-object-layer="rider-ground"
        >
          <ProfileGroundMap ground={ground} onOpenClimb={openClimb} compact={activeTab !== 'overview'} />
          <div className="profile-ground__fade" aria-hidden="true" />
          {activeTab !== 'overview' ? (
            <div className="profile-masthead" data-object-layer="rider-identity">
              <span className="profile-masthead__avatar" aria-hidden="true">
                {profile.avatarUrl ? <img src={profile.avatarUrl} alt="" /> : <span>{displayName.trim().slice(0, 1).toUpperCase()}</span>}
              </span>
              <div className="profile-masthead__copy">
                <span className="profile-masthead__name">{displayName}</span>
                {riderHandle || riderLocation ? (
                  <span className="profile-masthead__meta">{[riderHandle ? `@${riderHandle}` : null, riderLocation].filter(Boolean).join(' · ')}</span>
                ) : null}
              </div>
            </div>
          ) : (
          <div className="profile-ledger-layer" data-object-layer="rider-identity">
            <ProfileLedgerColumn
              displayName={displayName}
              handle={riderHandle}
              location={riderLocation}
              bio={profile.bio?.trim() || null}
              avatarUrl={profile.avatarUrl || null}
              createdAt={profile.createdAt || null}
              followerCount={followerCount}
              followingCount={followingCount}
              follow={isOwnProfile ? null : {
                isFollowing,
                pending: isFollowLoading || followStatusLoading,
                onToggle: () => void handleFollowToggle(),
              }}
              menu={{
                onCopyLink: () => void handleShareProfile(),
                copied: linkCopied,
                onEdit: isOwnProfile ? () => navigate('/settings') : undefined,
                onReport: isOwnProfile ? undefined : () => void handleReportProfile(),
                reportStatus: profileReportStatus,
                reporting: isReportingProfile,
              }}
              rides={totalRides}
              seats={stats ? stats.top10Count : null}
              crowns={stats ? stats.komCount : null}
              rows={ledgerRows}
              riddenCount={riddenCount}
              positionsState={positionsState}
              retryingPositions={positionsRetrying}
              onRetryPositions={retryPositions}
            />
          </div>
          )}
        </div>
  );

  return (
    <PortalPage
      className="profile-page portal-object-page portal-object-page--rider"
      data-object-page="rider"
    >
      <PortalFrame>
        {activeTab !== 'overview' ? profileGround : null}

        <div className="profile-tabs" role="tablist" aria-label="Profile sections">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              role="tab"
              id={`profile-tab-${tab.id}`}
              aria-controls={`profile-panel-${tab.id}`}
              aria-selected={activeTab === tab.id}
              tabIndex={activeTab === tab.id ? 0 : -1}
              onKeyDown={(event) => handleTabKeyDown(event, tab.id)}
              className="profile-tabs__tab"
              onClick={() => handleTabChange(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {activeTab === 'overview' ? profileGround : null}

        <div
          id={`profile-panel-${activeTab}`}
          className="profile-content"
          role="tabpanel"
          aria-labelledby={`profile-tab-${activeTab}`}
        >
          {activeTab === 'overview' ? (
            <>
              {isPrivatePublicProfile ? (
                <p className="profile-private">
                  This profile is private. Public totals stay visible above.
                </p>
              ) : null}
              <ProfilePhotoBand photos={photos} onOpenRide={openRide} />
              {yearRides || recentRides.length > 0 ? (
                <div
                  className={yearRides && recentRides.length > 0 ? 'profile-boxes' : 'profile-boxes profile-boxes--single'}
                  data-object-layer="rider-activity-history"
                  aria-label="This year activity history"
                >
                  {yearRides ? <ProfileYearCard rides={yearRides} /> : null}
                  <ProfileRecentRides rides={recentRides} onOpenRide={openRide} />
                </div>
              ) : null}
            </>
          ) : null}

          {activeTab === 'rides' && isOwnProfile ? (
            <Suspense fallback={<LoadingRows label="Loading rides" rows={6} />}>
              <MyActivities />
            </Suspense>
          ) : null}

          {activeTab === 'training' && isOwnProfile ? (
            <Suspense fallback={<LoadingRows label="Loading training" rows={4} />}>
              <Data />
            </Suspense>
          ) : null}

          {activeTab === 'portfolio' && isOwnProfile ? (
            <Suspense fallback={<LoadingRows label="Loading Portfolio" rows={6} />}>
              <Portfolio />
            </Suspense>
          ) : null}
        </div>
      </PortalFrame>
    </PortalPage>
  );
}
