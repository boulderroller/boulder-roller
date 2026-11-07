import { SlotRows } from '../loading/Slot';
import { useState, useEffect, useRef, Suspense, lazy, useCallback, useMemo, type KeyboardEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { useFormatters } from '../../hooks/useFormatters';
import { Activity, SuggestedRider, User } from '../../lib/api';
import { displayRideTitle } from '../../lib/rideTitle';
import { getPortalRiderIdentity, getPublicRiderDisplayName, normalizeRiderHandle, getPublicRiderPath, getRiderHandle } from '../../lib/riderIdentity';
import { ABSENT_VALUE, formatDateTime, formatDurationCompact, formatTokenAmount, roundToDigits } from '../../lib/formatters';
import { BeetleButton } from '../ui/beetle-button';
import { SEMANTIC_COLORS } from '../../constants/colors';
import FeedCrownCard from './FeedCrownCard';
import FeedWeekCard from './FeedWeekCard';
import FeedLeaderboardsCard from './FeedLeaderboardsCard';
import { ActivityFeedItem as ActivityFeedItemType } from '../../types';
import { AlertCircle, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import {
  StateRow,
  PortalFrame,
  PortalGrid,
  PortalMain,
  PortalPage,
  PortalPanel,
  PortalPanelBody,
  PortalRail,
  PortalStack,
} from '../portal/PortalSpine';
import { PortalUtilityLinks } from '../portal/PortalUtilityLinks';
import {
  useFeedSocialCounts,
  useFollowSuggestedRider,
  useGlobalFeed,
  useMyLeaderboardPositions,
  useRides,
  useSuggestedRiders,
} from '../../hooks/queries';

const VirtualizedFeedList = lazy(() => import('./VirtualizedFeedList'));

interface ActivityFeedProps {
  isConnected: boolean;
}

interface SuggestedBeetleCard {
  id: string;
  username: string;
  avatarUrl?: string | null;
  path: string;
  mutualFollowers: number;
  isFollowing: boolean;
}


type SuggestedRiderFeedRecord = SuggestedRider & {
  display_name?: string;
  mutualFollowers?: number;
  mutual_followers?: number;
  isFollowing?: boolean;
  is_following?: boolean;
  avatarUrl?: string | null;
  avatar_url?: string | null;
  rider?: { avatarUrl?: string | null };
};

const INITIAL_FEED_LIMIT = 15;
const FEED_PAGE_SIZE = 10;

const useStickyOffset = (headerOffset: number = 88, bottomPadding: number = 24) => {
  const ref = useRef<HTMLDivElement>(null);

  const state = useRef({
    lastScrollY: typeof window !== 'undefined' ? window.scrollY : 0,
    currTop: headerOffset,
  });

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    el.style.top = `${headerOffset}px`;

    const handleScroll = () => {
      const currentScrollY = window.scrollY;
      const { lastScrollY, currTop } = state.current;
      const delta = lastScrollY - currentScrollY;

      const sidebarHeight = el.offsetHeight;
      const windowHeight = window.innerHeight;

      if (sidebarHeight + headerOffset + bottomPadding <= windowHeight) {
        if (currTop !== headerOffset) {
          el.style.top = `${headerOffset}px`;
          state.current.currTop = headerOffset;
        }
        state.current.lastScrollY = currentScrollY;
        return;
      }

      const minTop = windowHeight - sidebarHeight - bottomPadding;
      const maxTop = headerOffset;
      let newTop = currTop + delta;

      if (newTop > maxTop) newTop = maxTop;
      if (newTop < minTop) newTop = minTop;

      if (newTop !== currTop) {
        el.style.top = `${newTop}px`;
        state.current.currTop = newTop;
      }

      state.current.lastScrollY = currentScrollY;
    };

    const handleResize = () => {
      if (ref.current) {
        state.current.currTop = headerOffset;
        ref.current.style.top = `${headerOffset}px`;
      }
      handleScroll();
    };

    window.addEventListener('scroll', handleScroll, { passive: true });
    window.addEventListener('resize', handleResize);

    handleScroll();

    return () => {
      window.removeEventListener('scroll', handleScroll);
      window.removeEventListener('resize', handleResize);
    };
  }, [headerOffset, bottomPadding]);

  return { ref };
};

const getDaysAgo = (createdAt: string): number => {
  const created = new Date(createdAt);
  if (Number.isNaN(created.getTime())) return 0;
  const now = new Date();
  return Math.max(0, Math.floor((now.getTime() - created.getTime()) / (1000 * 60 * 60 * 24)));
};


const formatSuggestedRiderHandle = (rider: SuggestedRiderFeedRecord): string => {
  const fallback = `rider_${rider.id.slice(0, 6)}`;
  return getRiderHandle(rider, fallback);
};

const getSuggestedRiderMutuals = (rider: SuggestedRiderFeedRecord): number => {
  const value = rider.mutualFollowers ?? rider.mutual_followers ?? 0;
  return Number.isFinite(value) ? Math.max(0, roundToDigits(value, 0)) : 0;
};

const isViewerActivity = (activity: Activity, viewer: User | null | undefined): boolean => {
  if (!viewer) return false;
  const actor = activity.actor ?? activity.user ?? null;
  if (!actor) return false;
  const actorRecord = actor as { id?: string | null; wallet?: string | null; username?: string | null };
  if (actorRecord.id && viewer.id && actorRecord.id === viewer.id) return true;
  if (actorRecord.wallet && viewer.wallet && actorRecord.wallet === viewer.wallet) return true;
  if (actorRecord.username && viewer.username && actorRecord.username === viewer.username) return true;
  return false;
};

const transformActivity = (
  activity: Activity,
  formatDistance: (meters: number | null | undefined) => string,
  formatElevation: (meters: number | null | undefined) => string,
  viewer: User | null | undefined,
): ActivityFeedItemType => {
  const createdDate = new Date(activity.createdAt);
  const dateStr = formatDateTime(createdDate);
  const displayType = activity.type.toUpperCase() as 'RIDE' | 'ACHIEVEMENT' | 'REWARD';
  const color = displayType === 'RIDE'
    ? SEMANTIC_COLORS.activityRide
    : displayType === 'ACHIEVEMENT'
      ? SEMANTIC_COLORS.activityAchievement
      : SEMANTIC_COLORS.activityReward;
  const summary = activity.resultSummary;
  const rideId = activity.target?.type === 'ride' ? activity.target.id : activity.id;
  // Use only the supplied feed projection, bound to this ride and revision.
  // Neither legacy metadata nor a detail fetch can recover a withheld result.
  const resultSummary = displayType === 'RIDE' && summary
    && typeof summary.climbId === 'string' && summary.climbId.trim()
    && typeof summary.rideId === 'string' && summary.rideId.trim() && summary.rideId === rideId
    && typeof summary.revision === 'string' && summary.revision.trim()
    && typeof summary.asOf === 'string' && Number.isFinite(Date.parse(summary.asOf))
    && typeof summary.timeSeconds === 'number' && Number.isFinite(summary.timeSeconds) && summary.timeSeconds >= 0
    ? summary : null;
  const meta = activity.metadata;
  const actor = activity.actor ?? activity.user ?? null;
  const distanceLabel = meta?.distanceM ? formatDistance(meta.distanceM) : null;
  const elevationM = meta?.elevationM ?? null;
  const calEarned = meta?.calEarned ?? 0;
  const dungEarned = meta?.dungEarned ?? 0;
  const tokenEarned = calEarned || dungEarned || 0;
  const tokenLabel = calEarned > 0 ? 'CAL' : dungEarned > 0 ? 'DUNG' : undefined;
  const primaryMedia = meta?.primaryMedia?.url ? meta.primaryMedia : null;
  const mediaCount = Array.isArray(meta?.media) ? meta.media.length : primaryMedia ? 1 : 0;
  return {
    id: activity.id,
    resultSummary,
    type: 'ride' as const,
    createdAt: activity.createdAt,
    title: displayRideTitle(activity.title, activity.createdAt, null),
    date: dateStr,
    distance: distanceLabel ?? ABSENT_VALUE,
    duration: formatDurationCompact(meta?.durationS),
    elevation: elevationM ? formatElevation(elevationM) : ABSENT_VALUE,
    avgPower: ABSENT_VALUE,
    location: '',
    tss: 0,
    dung: tokenEarned,
    tokenLabel,
    displayType,
    user: actor ? getPublicRiderDisplayName(actor) : 'Unknown rider',
    handle: normalizeRiderHandle(actor?.username),
    avatarUrl: actor?.avatarUrl ?? null,
    riderPath: actor ? getPublicRiderPath(actor) : null,
    action: displayType === 'RIDE' ? 'Ride' : displayType === 'ACHIEVEMENT' ? 'Achievement' : tokenLabel ? `${tokenLabel} receipt` : 'Receipt',
    time: dateStr,
    dungDisplay: tokenEarned > 0 ? `+${formatTokenAmount(tokenEarned)} ${tokenLabel ?? 'CAL'}` : `+${formatTokenAmount(0)}`,
    color,
    visualType: primaryMedia ? 'image' : 'none',
    visualUrl: primaryMedia?.url ?? '',
    mediaCount,
    claps: meta?.kudosCount ?? 0,
    comments: meta?.commentCount ?? 0,
    viewerHasKudos: Boolean(meta?.viewerHasKudos),
    viewerReported: Boolean(meta?.viewerReported),
    reportStatus: meta?.reportStatus ?? null,
    distanceM: meta?.distanceM ?? null,
    elevationM: elevationM,
    durationS: meta?.durationS ?? null,
    calEarned: calEarned > 0 ? calEarned : null,
    isOwn: isViewerActivity(activity, viewer),
    placeLabel: meta?.routePreview?.placeLabel ?? null,
    routePreview: meta?.routePreview ?? null,
  };
};

export default function ActivityFeed({ isConnected }: ActivityFeedProps) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const { distance: formatFeedDistance, elevation: formatFeedElevation } = useFormatters();

  const [filterType, setFilterType] = useState('all');
  const [scrollMargin, setScrollMargin] = useState(0);
  const [isMounted, setIsMounted] = useState(false);

  const feedScope = filterType === 'following' ? 'following' : 'global';
  const feedQuery = useGlobalFeed({
    scope: feedScope,
    initialLimit: INITIAL_FEED_LIMIT,
    pageSize: FEED_PAGE_SIZE,
    enabled: isConnected,
  });
  const homeContext = feedQuery.data?.pages[0]?.home ?? null;
  const suggestedRidersQuery = useSuggestedRiders(4, isConnected && !homeContext);
  const socialCountsQuery = useFeedSocialCounts(user?.id ?? null, isConnected && !homeContext);
  const followSuggestedRider = useFollowSuggestedRider(user?.id ?? null);
  const ownRidesQuery = useRides({ limit: 60 });
  const leaderboardPositionsQuery = useMyLeaderboardPositions(isConnected);

  const leftSidebar = useStickyOffset(88, 24);
  const rightSidebar = useStickyOffset(88, 24);
  const parentRef = useRef<HTMLDivElement>(null);

  const activities = useMemo(() => {
    const seenIds = new Set<string>();

    return (feedQuery.data?.pages ?? [])
      .flatMap((page) => page.activities)
      .map((activity) => transformActivity(activity, formatFeedDistance, formatFeedElevation, user))
      .filter((activity) => {
        if (seenIds.has(activity.id)) {
          return false;
        }

        seenIds.add(activity.id);
        return true;
      });
  }, [feedQuery.data, formatFeedDistance, formatFeedElevation, user]);

  const suggestedBeetles = useMemo<SuggestedBeetleCard[]>(() => {
    return (((homeContext?.suggestedRiders ?? suggestedRidersQuery.data) ?? []) as SuggestedRiderFeedRecord[]).map((rider) => ({
      id: rider.id,
      username: formatSuggestedRiderHandle(rider),
      avatarUrl: rider.avatarUrl ?? rider.avatar_url ?? rider.rider?.avatarUrl ?? null,
      path: getPublicRiderPath(rider),
      mutualFollowers: getSuggestedRiderMutuals(rider),
      isFollowing: Boolean(rider.isFollowing ?? rider.is_following),
    }));
  }, [homeContext?.suggestedRiders, suggestedRidersQuery.data]);


  const followerCount = homeContext?.socialCounts?.followerCount ?? socialCountsQuery.data?.followerCount ?? 0;
  const followingCount = homeContext?.socialCounts?.followingCount ?? socialCountsQuery.data?.followingCount ?? 0;
  const isInitialFeedLoading = isConnected && feedQuery.isLoading && activities.length === 0;
  const isFetchingMore = feedQuery.isFetchingNextPage;
  const hasMoreActivities = feedQuery.hasNextPage ?? false;
  const feedErrorMessage = feedQuery.error?.message ?? null;
  const showFeedErrorState = Boolean(feedErrorMessage) && activities.length === 0;
  const showStaleFeedWarning = Boolean(feedErrorMessage) && activities.length > 0;
  const isZeroRideRider = isConnected
    && Boolean(user)
    && (user?.totalRides === 0 || user?.totalRides === undefined);
  const pendingFollowRiderId = followSuggestedRider.variables?.riderId;

  useEffect(() => {
    const updateScrollMargin = () => {
      if (parentRef.current) {
        const rect = parentRef.current.getBoundingClientRect();
        const scrollTop = window.scrollY || document.documentElement.scrollTop;
        const newMargin = rect.top + scrollTop;
        setScrollMargin((prev) => (Math.abs(prev - newMargin) > 5 ? newMargin : prev));
        setIsMounted(true);
      }
    };

    const timeoutId = setTimeout(updateScrollMargin, 50);
    window.addEventListener('resize', updateScrollMargin);

    return () => {
      clearTimeout(timeoutId);
      window.removeEventListener('resize', updateScrollMargin);
    };
  }, [isConnected, isInitialFeedLoading, activities.length, user?.totalRides]);

  const riderIdentity = useMemo(() => getPortalRiderIdentity(user), [user]);
  const latestRideId = useMemo(() => {
    const rides = ownRidesQuery.data ?? [];
    if (rides.length === 0) return null;
    return [...rides].sort((a, b) => new Date(b.startedAt).getTime() - new Date(a.startedAt).getTime())[0]?.id ?? null;
  }, [ownRidesQuery.data]);

  const handleActivityClick = useCallback((activity: ActivityFeedItemType) => {
    navigate(`/activities/${activity.id}`);
  }, [navigate]);

  const handleFollow = useCallback(async (userId: string, username: string) => {
    try {
      await followSuggestedRider.mutateAsync({ riderId: userId });
      toast.success(`Now following @${username}`);
    } catch {
      toast.error('Could not follow rider');
    }
  }, [followSuggestedRider]);

  const handleRailItemKeyDown = useCallback((
    event: KeyboardEvent<HTMLDivElement>,
    route: string,
  ) => {
    if (event.target !== event.currentTarget) {
      return;
    }

    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      navigate(route);
    }
  }, [navigate]);

  const loadMoreActivities = useCallback(async () => {
    if (!hasMoreActivities || isFetchingMore) return;

    try {
      await feedQuery.fetchNextPage();
    } catch {
      toast.error('Could not load more rides');
    }
  }, [feedQuery, hasMoreActivities, isFetchingMore]);

  const retryFeedLoad = useCallback(async () => {
    if (!isConnected) return;

    try {
      const feedResult = await feedQuery.refetch();
      if (!homeContext) {
        await Promise.allSettled([
          suggestedRidersQuery.refetch(),
          socialCountsQuery.refetch(),
        ]);
      }

      if (feedResult.error) {
        toast.error('Could not load feed. Try again later.');
        return;
      }

      toast.success('Feed refreshed');
    } catch {
      toast.error('Could not load feed. Try again later.');
    }
  }, [
    feedQuery,
    homeContext,
    isConnected,
    socialCountsQuery,
    suggestedRidersQuery,
  ]);

  return (
    <PortalPage className="feed-page">
      <PortalFrame>
        <PortalGrid>
          <PortalRail
            ref={leftSidebar.ref}
            className="feed-rail feed-rail--smart-sticky"
          >
            <PortalStack>
              {isConnected && !isZeroRideRider && (
                <FeedCrownCard
                  name={riderIdentity.displayName}
                  handle={user?.username ?? null}
                  location={user?.location ?? null}
                  avatarUrl={user?.avatarUrl ?? null}
                  rides={user?.totalRides || 0}
                  seats={leaderboardPositionsQuery.data?.stats?.top10Count ?? null}
                  crowns={leaderboardPositionsQuery.data?.stats?.komCount ?? null}
                  standingPending={leaderboardPositionsQuery.isPending}
                  latestRideDate={user?.lastActivityDate ?? null}
                  latestRideId={latestRideId}
                />
              )}
            </PortalStack>
          </PortalRail>

          <PortalMain>
            <PortalStack className="portal-stack--loose">
              {isConnected && (
                <div className="feed-lens" role="group" aria-label="Feed scope">
                  <button
                    type="button"
                    className="feed-lens__word"
                    aria-pressed={filterType !== 'following'}
                    onClick={() => setFilterType('all')}
                  >
                    Everyone
                  </button>
                  <button
                    type="button"
                    className="feed-lens__word"
                    aria-pressed={filterType === 'following'}
                    onClick={() => setFilterType('following')}
                  >
                    Following
                  </button>
                </div>
              )}
              <div ref={parentRef}>
                {showStaleFeedWarning && (
                  <PortalPanel className="feed-state-panel feed-state-panel--warning">
                    <PortalPanelBody className="feed-state-panel__body">
                      <div className="feed-state-panel__copy">
                        <div className="feed-state-panel__title">
                          Feed paused
                        </div>
                        <div className="feed-state-panel__description">
                          Showing your last loaded rides while we retry.
                        </div>
                      </div>
                      <BeetleButton variant="primary" size="sm" onClick={retryFeedLoad}>
                        <RefreshCw className="feed-state-panel__button-icon" />
                        Refresh
                      </BeetleButton>
                    </PortalPanelBody>
                  </PortalPanel>
                )}

                {isInitialFeedLoading ? (
                  <SlotRows count={FEED_PAGE_SIZE} />
                ) : showFeedErrorState ? (
                  <PortalPanel>
                    <StateRow
                      icon={<AlertCircle className="feed-empty-icon feed-empty-icon--danger" />}
                      title="Could not load feed"
                      description={feedErrorMessage}
                      action={(
                        <BeetleButton
                          variant="primary"
                          size="sm"
                          onClick={retryFeedLoad}
                        >
                          <RefreshCw className="feed-state-panel__button-icon" />
                          Try again
                        </BeetleButton>
                      )}
                    />
                  </PortalPanel>
                ) : activities.length === 0 ? (
                  <PortalPanel>
                    <StateRow
                      title="No rides yet"
                      action={(
                        <BeetleButton
                          variant="primary"
                          size="sm"
                          onClick={() => navigate('/?search=riders')}
                        >
                          Find riders
                        </BeetleButton>
                      )}
                    />
                  </PortalPanel>
                ) : (
                  isMounted && (
                    <Suspense fallback={<SlotRows count={2} />}>
                      <VirtualizedFeedList
                        activities={activities}
                        scrollMargin={scrollMargin}
                        isLoading={isFetchingMore}
                        isConnected={isConnected && hasMoreActivities}
                        onLoadMore={loadMoreActivities}
                        onActivityClick={handleActivityClick}
                        onRiderClick={(path) => navigate(path)}
                      />
                    </Suspense>
                  )
                )}
              </div>

              {isFetchingMore && (
                <SlotRows count={2} />
              )}
              {activities.length > 0 && !isFetchingMore && (
                <div className="feed-scroll-footer">
                  <div className="feed-scroll-footer__label">
                    {hasMoreActivities ? 'Scroll for more' : 'You are all caught up'}
                  </div>
                </div>
              )}
            </PortalStack>
          </PortalMain>

          <PortalRail
            ref={rightSidebar.ref}
            className="feed-rail feed-rail--smart-sticky"
          >
            <PortalStack>
              {isConnected && !isZeroRideRider && (
                <FeedWeekCard rides={ownRidesQuery.data} loading={ownRidesQuery.isLoading} />
              )}

              {isConnected && (
                <FeedLeaderboardsCard positions={leaderboardPositionsQuery.data?.positions} />
              )}

              {isConnected && suggestedBeetles.length > 0 && (
                <section className="feed-box" aria-label="Follow picks">
                  <div className="feed-box__head">
                    <span className="feed-box__title">Follow picks</span>
                    <button type="button" className="feed-box__more" onClick={() => navigate('/?search=riders')}>See All</button>
                  </div>
                  {suggestedBeetles.map((beetle) => {
                    const isFollowPending = followSuggestedRider.isPending && pendingFollowRiderId === beetle.id;
                    return (
                      <div
                        key={beetle.id}
                        className="feed-row feed-row--tap feed-rail-rider"
                        role="button"
                        tabIndex={0}
                        onClick={() => navigate(beetle.path)}
                        onKeyDown={(event) => handleRailItemKeyDown(event, beetle.path)}
                      >
                        <span className="feed-row__lead">
                          <span className="feed-row__avatar" aria-hidden="true">
                            {beetle.avatarUrl ? <img src={beetle.avatarUrl} alt="" /> : beetle.username.slice(0, 1).toUpperCase()}
                          </span>
                          <span className="feed-row__label feed-row__label--ink">{beetle.username}</span>
                        </span>
                        <button
                          type="button"
                          className="feed-row__action"
                          data-state={beetle.isFollowing || isFollowPending ? 'disabled' : 'idle'}
                          onClick={(event) => {
                            event.stopPropagation();
                            if (!beetle.isFollowing && !isFollowPending) {
                              void handleFollow(beetle.id, beetle.username);
                            }
                          }}
                          disabled={beetle.isFollowing || isFollowPending}
                        >
                          {beetle.isFollowing ? 'Following' : isFollowPending ? 'Following...' : 'Follow'}
                        </button>
                      </div>
                    );
                  })}
                </section>
              )}
            </PortalStack>
            <PortalUtilityLinks placement="rail" />
          </PortalRail>
        </PortalGrid>
      </PortalFrame>
    </PortalPage>
  );
}
