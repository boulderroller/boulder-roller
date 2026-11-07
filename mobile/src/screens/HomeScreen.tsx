/**
 * HomeScreen — Phase 1 "honest home".
 *
 * The product shape is a real ride feed, not a raw archive.
 * Following and Global use feed contracts; Mine keeps the rider's own
 * merged local/server ride history so device-first resilience survives.
 */
import React, { useCallback, useRef, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  RefreshControl,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useFocusEffect, useNavigation } from '@react-navigation/native';
import * as Sentry from '@sentry/react-native';
import { api, ApiError, type FeedActivity, type User } from '../lib/api';
import { useAuthStore } from '../stores/authStore';
import { ErrorBanner } from '../components/ErrorBanner';
import { getDatabase } from '../services/database';
import {
  loadLocalRides,
  mergeRideSources,
  type MergedRide,
} from '../lib/rides';
import RideFeedItem from '../components/home/RideFeedItem';
import TopTabBar from '../components/navigation/TopTabBar';
import SegmentedControl from '../components/surfaces/SegmentedControl';
import {
  buildFeedActivityCardDisplay,
  buildRideFeedCardDisplay,
  targetFromFeedActivity,
  type FeedSource,
} from '../lib/feedDisplay';
import {
  riderProfileRouteParams,
  riderProfileRouteParamsFromIdentifier,
  type RiderProfileRouteParams,
} from '../lib/riderNavigation';
import { mobileColors } from '../theme/tokens';

type HomeListItem =
  | { kind: 'ride'; key: string; ride: MergedRide }
  | { kind: 'event'; key: string; event: FeedActivity };

const FEED_SOURCE_ITEMS = [
  { key: 'following', label: 'Following' },
  { key: 'mine', label: 'Mine' },
  { key: 'global', label: 'Global' },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function HomeScreen() {
  const navigation = useNavigation();
  const [feedSource, setFeedSource] = useState<FeedSource>('following');
  const [rides, setRides] = useState<MergedRide[]>([]);
  const [activities, setActivities] = useState<FeedActivity[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [viewer, setViewer] = useState<User | null>(null);
  const [unreadCount, setUnreadCount] = useState(0);
  const hasLoadedOnceRef = useRef(false);
  const isAuthenticated = useAuthStore(
    (s) => s.status === 'authenticated' || s.status === 'refreshing',
  );
  const authWallet = useAuthStore((s) => s.wallet);

  // Pure local read — this is what runs offline and always succeeds as
  // long as SQLite is open. Wrapped in try/catch because an
  // uninitialised DB at app boot would throw (see database.ts).
  const readLocal = useCallback(() => {
    try {
      const db = getDatabase();
      return loadLocalRides(db);
    } catch (err) {
      console.error('[HomeScreen] Local ride read failed:', err);
      Sentry.captureException(err);
      return [];
    }
  }, []);

  const load = useCallback(async () => {
    setError(null);
    const locals = readLocal();

    if (feedSource === 'mine') {
      // Show local rides immediately so the rider never waits on the
      // network to see their own history.
      setRides(mergeRideSources(locals, null));
      setActivities([]);
    } else {
      setRides([]);
      setActivities([]);
    }

    if (!isAuthenticated) {
      setViewer(null);
      setUnreadCount(0);
      return;
    }

    const [profileResult, dataResult, notificationResult] = await Promise.allSettled([
      feedSource === 'mine' ? api.getMe() : Promise.resolve(null),
      feedSource === 'mine'
        ? api.getRides(50, 0)
        : api.getHomeFeed(feedSource === 'global' ? 'global' : 'following', 30),
      feedSource === 'mine' ? api.getNotifications({ limit: 1 }).catch(() => null) : Promise.resolve(null),
    ]);

    if (profileResult.status === 'fulfilled') {
      if (profileResult.value) {
        setViewer(profileResult.value);
      }
    } else if (profileResult.reason instanceof ApiError) {
      if (profileResult.reason.type === 'session_expired') return;
    } else {
      Sentry.captureException(profileResult.reason);
    }

    if (notificationResult.status === 'fulfilled') {
      setUnreadCount(notificationResult.value?.unreadCount ?? 0);
    }

    if (dataResult.status === 'fulfilled') {
      if (feedSource === 'mine') {
        setRides(mergeRideSources(locals, dataResult.value as Awaited<ReturnType<typeof api.getRides>>));
      } else {
        const home = dataResult.value as Awaited<ReturnType<typeof api.getHomeFeed>>;
        setActivities(home.feed?.activities ?? []);
        setUnreadCount(home.notifications?.unreadCount ?? 0);
      }
      return;
    }

    const err = dataResult.reason;
    {
      // Session-expired: let the auth layer handle it, keep local list.
      if (err instanceof ApiError) {
        if (err.type === 'session_expired') return;
        setError(err);
      } else {
        setError(new ApiError('Unexpected error', 'unknown'));
        Sentry.captureException(err);
      }
      // Local rides already displayed — keep them. The offline /
      // network-error banner fills in the rest.
    }
  }, [feedSource, isAuthenticated, readLocal]);

  useFocusEffect(
    useCallback(() => {
      let cancelled = false;

      if (!hasLoadedOnceRef.current) {
        setLoading(true);
      }

      void (async () => {
        await load();
        if (!cancelled) {
          hasLoadedOnceRef.current = true;
          setLoading(false);
        }
      })();

      return () => {
        cancelled = true;
      };
    }, [load]),
  );

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }, [load]);

  const handleRidePress = useCallback(
    (ride: MergedRide) => {
      (
        navigation as {
          navigate: (
            screen: string,
            params: { rideId?: string; serverRideId?: string },
          ) => void;
        }
      ).navigate('RideDetail', {
        rideId: ride.localRideId ?? undefined,
        serverRideId: ride.serverRideId ?? undefined,
      });
    },
    [navigation],
  );

  const handleActivityPress = useCallback(
    (activity: FeedActivity) => {
      const target = targetFromFeedActivity(activity);
      if (!target?.id) return;
      const nav = navigation as {
        navigate: (screen: string, params?: object) => void;
      };
      if (target.type === 'ride') {
        nav.navigate('RideDetail', { serverRideId: target.id, backLabel: 'Home' });
      } else if (target.type === 'rider') {
        const route = riderProfileRouteParamsFromIdentifier(target.id, null, { backLabel: 'Home' });
        if (route) nav.navigate('RiderDetail', route);
      } else if (target.type === 'climb' || target.type === 'record_board' || target.type === 'local_legend') {
        nav.navigate('ClimbDetail', { climbId: target.id, backLabel: 'Home' });
      }
    },
    [navigation],
  );

  const handleRiderPress = useCallback(
    (params: RiderProfileRouteParams | null) => {
      if (!params) return;
      (
        navigation as {
          navigate: (screen: string, params?: object) => void;
        }
      ).navigate('RiderDetail', params);
    },
    [navigation],
  );

  const renderRide = (item: MergedRide) => {
    const card = buildRideFeedCardDisplay({
      ride: item,
      viewer,
      authWallet,
    });
    const actorRoute = riderProfileRouteParams(card.actorIdentity, { backLabel: 'Home' });

    return (
      <RideFeedItem
        actorLabel={card.actorLabel}
        actorAvatarUrl={card.actorIdentity?.avatarUrl ?? null}
        title={card.title}
        dateLabel={card.dateLabel}
        summaryLine={card.summaryLine}
        statusLine={card.statusLine}
        stats={card.stats}
        routePreview={card.routePreview}
        primaryMediaUrl={card.primaryMedia?.url ?? null}
        mediaCount={card.mediaCount}
        impactItems={card.impactItems}
        onPress={() => handleRidePress(item)}
        onPressActor={actorRoute ? () => handleRiderPress(actorRoute) : undefined}
        testID={`ride-card-${item.key}`}
      />
    );
  };

  const renderFeedEvent = (event: FeedActivity) => {
    const card = buildFeedActivityCardDisplay(event);
    const actorRoute = riderProfileRouteParams(card.actorIdentity, { backLabel: 'Home' });
    return (
      <RideFeedItem
        actorLabel={card.actorLabel}
        actorAvatarUrl={card.actorIdentity?.avatarUrl ?? null}
        title={card.title}
        dateLabel={card.dateLabel}
        locationLabel={card.locationLabel}
        summaryLine={card.summaryLine}
        statusLine={card.statusLine}
        stats={card.stats}
        routePreview={card.routePreview}
        primaryMediaUrl={card.primaryMedia?.url ?? null}
        mediaCount={card.mediaCount}
        impactItems={card.impactItems}
        kudosCount={card.kudosCount}
        commentCount={card.commentCount}
        viewerHasKudos={card.viewerHasKudos}
        onPress={() => handleActivityPress(event)}
        onPressActor={actorRoute ? () => handleRiderPress(actorRoute) : undefined}
        testID={`feed-event-${event.id}`}
      />
    );
  };

  const renderItem = ({ item }: { item: HomeListItem }) => (
    item.kind === 'ride' ? renderRide(item.ride) : renderFeedEvent(item.event)
  );

  const renderEmptyState = () => {
    if (!isAuthenticated) {
      return (
        <View style={styles.emptyState}>
          <Text style={styles.emptyTitle}>Welcome to Boulder Roller</Text>
          <Text style={styles.emptySubtitle}>
            Sign in to sync your rides. Anything you record on this device stays
            here safely until you do.
          </Text>
        </View>
      );
    }

    return (
      <View style={styles.emptyState}>
        <Text style={styles.emptyTitle}>
          {feedSource === 'mine' ? 'Ready for your first ride' : 'No feed events yet'}
        </Text>
        <Text style={styles.emptySubtitle}>
          {feedSource === 'mine'
            ? 'Open Record when you are ready. Your rides stay on this device until they sync.'
            : 'Follow riders or check Global for public rides.'}
        </Text>
      </View>
    );
  };

  const listData: HomeListItem[] = feedSource === 'mine'
    ? rides.map((ride) => ({ kind: 'ride', key: `ride-${ride.key}`, ride }))
    : activities.map((event) => ({ kind: 'event', key: `event-${event.id}`, event }));

  if (loading) {
    return (
      <SafeAreaView style={styles.container}>
        <ActivityIndicator size="large" color={mobileColors.accent} style={styles.loader} />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <TopTabBar
        title="Home"
        testIdPrefix="home"
        unreadCount={unreadCount}
        onPressSearch={() => (
          navigation as { navigate: (screen: string) => void }
        ).navigate('Search')}
        onPressAlerts={() => (
          navigation as { navigate: (screen: string) => void }
        ).navigate('Notifications')}
        onPressProfile={() => (
          navigation as { navigate: (screen: string) => void }
        ).navigate('Profile')}
      />

      {error && (
        <ErrorBanner
          message={error.retryable ? 'Connection issue' : 'Unable to sync rides'}
          onRetry={error.retryable ? load : undefined}
          onDismiss={() => setError(null)}
        />
      )}

      <FlatList
        data={listData}
        extraData={feedSource}
        keyExtractor={(item) => item.key}
        renderItem={renderItem}
        ListHeaderComponent={(
          <View style={styles.sourceRail}>
            <SegmentedControl
              items={FEED_SOURCE_ITEMS}
              activeKey={feedSource}
              onChange={(key) => setFeedSource(key as FeedSource)}
            />
          </View>
        )}
        ListEmptyComponent={renderEmptyState}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor={mobileColors.accent}
          />
        }
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={[
          styles.listContent,
          listData.length === 0 && styles.listContentEmpty,
        ]}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: mobileColors.canvas,
  },
  loader: {
    flex: 1,
    justifyContent: 'center',
  },
  listContent: {
    paddingHorizontal: 0,
    paddingBottom: 24,
  },
  sourceRail: {
    paddingHorizontal: 16,
    paddingTop: 6,
    paddingBottom: 12,
  },
  listContentEmpty: {
    flexGrow: 1,
    paddingTop: 4,
  },
  emptyState: {
    flexGrow: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 40,
    paddingBottom: 48,
  },
  emptyTitle: {
    fontSize: 20,
    fontWeight: '600',
    color: mobileColors.text,
    marginBottom: 8,
    textAlign: 'center',
  },
  emptySubtitle: {
    fontSize: 14,
    color: mobileColors.textMuted,
    textAlign: 'center',
    lineHeight: 20,
  },
});
