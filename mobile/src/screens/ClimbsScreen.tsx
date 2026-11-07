import React, { useCallback, useMemo, useRef, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  RefreshControl,
  ActivityIndicator,
  TouchableOpacity,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useFocusEffect, useNavigation } from '@react-navigation/native';
import * as Sentry from '@sentry/react-native';
import { api, ApiError, ClimbSummary } from '../lib/api';
import { useAuthStore } from '../stores/authStore';
import { ErrorBanner } from '../components/ErrorBanner';
import TopTabBar from '../components/navigation/TopTabBar';
import SegmentedControl from '../components/surfaces/SegmentedControl';
import RoutePreviewMap from '../components/route/RoutePreviewMap';
import {
  compareClimbCalBaseUnits,
  formatClimbCal,
  formatClimbDistance,
  formatClimbGrade,
  formatClimbVert,
  isPositiveClimbCal,
} from '../lib/climbDisplay';
import { mobileColors, mobileRadii } from '../theme/tokens';

type ClimbFilter = 'popular' | 'vaultLive';

function statusLineFor(climb: ClimbSummary): string {
  if (climb.hasVault) {
    return isPositiveClimbCal(climb.totalStakedBaseUnits)
      ? `Balance • ${formatClimbCal(climb.totalStakedBaseUnits)} CAL deposited`
      : 'Balance open';
  }
  if ((climb.totalCompletions ?? 0) > 0) {
    return `Leaderboard active • ${climb.totalCompletions} attempts`;
  }
  return 'No vault yet • Ride to activate';
}

export default function ClimbsScreen() {
  const [climbs, setClimbs] = useState<ClimbSummary[]>([]);
  const [popularClimbs, setPopularClimbs] = useState<ClimbSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [filter, setFilter] = useState<ClimbFilter>('popular');
  const hasLoadedOnceRef = useRef(false);
  const navigation = useNavigation();
  const isAuthenticated = useAuthStore((s) => s.status === 'authenticated' || s.status === 'refreshing');

  const fetchClimbs = useCallback(async () => {
    setError(null);
    try {
      if (!isAuthenticated) {
        setClimbs([]);
        setPopularClimbs([]);
        return;
      }
      const [popular, data] = await Promise.all([
        api.getPopularClimbs(20),
        api.getClimbs(20, 0),
      ]);
      setPopularClimbs(popular);
      setClimbs(data);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.type === 'session_expired') {
          return;
        }
        setError(err);
      } else {
        setError(new ApiError('Unexpected error', 'unknown'));
        Sentry.captureException(err);
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [isAuthenticated]);

  useFocusEffect(
    useCallback(() => {
      let cancelled = false;

      if (!hasLoadedOnceRef.current) {
        setLoading(true);
      }

      void (async () => {
        await fetchClimbs();
        if (!cancelled) {
          hasLoadedOnceRef.current = true;
          setLoading(false);
        }
      })();

      return () => {
        cancelled = true;
      };
    }, [fetchClimbs]),
  );

  const onRefresh = () => {
    setRefreshing(true);
    fetchClimbs();
  };

  const visibleClimbs = useMemo(() => {
    const filtered = filter === 'popular'
      ? popularClimbs
      : climbs.filter((climb) => climb.hasVault);

    return [...filtered].sort((a, b) => {
      const completionsDelta = (b.totalCompletions ?? 0) - (a.totalCompletions ?? 0);
      if (completionsDelta !== 0) return completionsDelta;

      const stakedDelta = compareClimbCalBaseUnits(
        b.totalStakedBaseUnits,
        a.totalStakedBaseUnits,
      );
      if (stakedDelta !== 0) return stakedDelta;

      return (b.elevGainM ?? 0) - (a.elevGainM ?? 0);
    });
  }, [climbs, popularClimbs, filter]);

  const handleClimbPress = useCallback((climbId: string) => {
    (
      navigation as {
        navigate: (
          screen: string,
          params: { climbId: string },
        ) => void;
      }
    ).navigate('ClimbDetail', { climbId });
  }, [navigation]);

  const renderClimb = ({ item }: { item: ClimbSummary }) => (
    <TouchableOpacity
      style={styles.climbCard}
      onPress={() => handleClimbPress(item.id)}
      activeOpacity={0.86}
      testID={`climb-card-${item.id}`}
    >
      <RoutePreviewMap
        preview={item.routePreview ?? null}
        height={156}
        testID={`climb-card-${item.id}-map`}
      />
      <View style={styles.climbCardBody}>
        <View style={styles.climbHeader}>
          <View style={styles.climbTitleBlock}>
            <Text style={styles.climbTitle}>{item.name || 'Unnamed Climb'}</Text>
            {item.region ? <Text style={styles.climbSubtitle}>{item.region}</Text> : null}
          </View>
          <Text style={styles.climbChevron}>›</Text>
        </View>
        <View style={styles.statsRow}>
          {[
            { label: 'Vert', value: formatClimbVert(item.elevGainM) },
            { label: 'Distance', value: formatClimbDistance(item.lengthM) },
            { label: 'Grade', value: formatClimbGrade(item.avgGradientPct) },
          ].map((stat) => (
            <View key={stat.label} style={styles.stat}>
              <Text style={styles.statValue}>{stat.value}</Text>
              <Text style={styles.statLabel}>{stat.label}</Text>
            </View>
          ))}
        </View>
        <Text style={styles.climbDetail}>{statusLineFor(item)}</Text>
      </View>
    </TouchableOpacity>
  );

  const renderListHeader = () => (
    <View style={styles.controlsWrap}>
      <SegmentedControl
        items={[
          { key: 'popular', label: 'Popular' },
          { key: 'vaultLive', label: 'Vaults' },
        ]}
        activeKey={filter}
        onChange={(key) => setFilter(key as ClimbFilter)}
      />
    </View>
  );

  const renderEmptyState = () => {
    if (error) return null;

    return (
      <View style={styles.emptyState}>
        <Text style={styles.emptyTitle}>
          {filter === 'vaultLive' ? 'No vault-live climbs yet' : 'No climbs found'}
        </Text>
        <Text style={styles.emptySubtitle}>
          {filter === 'vaultLive'
            ? 'This area has climbs, but none of them have a live vault yet. Switch back to Popular to keep exploring.'
            : 'Record rides with climbs to discover new community assets.'}
        </Text>
      </View>
    );
  };

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
        title="Climbs"
        testIdPrefix="climbs"
        onPressSearch={() => (navigation as { navigate: (screen: string) => void }).navigate('Search')}
        onPressProfile={() => (navigation as { navigate: (screen: string) => void }).navigate('Profile')}
      />

      {error && (
        <ErrorBanner
          message={error.retryable ? 'Connection issue' : 'Unable to load climbs'}
          onRetry={error.retryable ? fetchClimbs : undefined}
          onDismiss={() => setError(null)}
        />
      )}

      {!isAuthenticated ? (
        <View style={styles.emptyState}>
          <Text style={styles.emptyTitle}>Climbs</Text>
          <Text style={styles.emptySubtitle}>
            Sign in to explore climbs, compete on leaderboards, and back vaults
            where they&apos;re live.
          </Text>
        </View>
      ) : (
        <FlatList
          data={visibleClimbs}
          keyExtractor={(item) => item.id}
          renderItem={renderClimb}
          ListHeaderComponent={renderListHeader}
          ListEmptyComponent={renderEmptyState}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={onRefresh}
              tintColor={mobileColors.accent}
            />
          }
          contentContainerStyle={[
            styles.listContent,
            visibleClimbs.length === 0 && styles.listContentEmpty,
          ]}
        />
      )}
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
  listContentEmpty: {
    flexGrow: 1,
  },
  controlsWrap: {
    paddingHorizontal: 16,
    paddingBottom: 12,
  },
  climbCard: {
    backgroundColor: mobileColors.surface,
    marginHorizontal: 14,
    marginBottom: 12,
    borderRadius: mobileRadii.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: mobileColors.border,
    overflow: 'hidden',
    shadowColor: mobileColors.shadow,
    shadowOpacity: 0.055,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 5 },
    elevation: 1,
  },
  climbCardBody: {
    paddingHorizontal: 14,
    paddingTop: 12,
    paddingBottom: 14,
  },
  climbHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: 14,
  },
  climbTitleBlock: {
    flex: 1,
    minWidth: 0,
  },
  climbTitle: {
    color: mobileColors.text,
    fontSize: 17,
    fontWeight: '800',
  },
  climbSubtitle: {
    marginTop: 4,
    color: mobileColors.textMuted,
    fontSize: 12,
    fontWeight: '600',
  },
  climbChevron: {
    color: mobileColors.textSubtle,
    fontSize: 18,
    lineHeight: 18,
  },
  statsRow: {
    flexDirection: 'row',
    gap: 20,
    marginTop: 12,
  },
  stat: {
    alignItems: 'flex-start',
  },
  statValue: {
    color: mobileColors.text,
    fontSize: 15,
    fontWeight: '800',
  },
  statLabel: {
    color: mobileColors.textSubtle,
    fontSize: 11,
    marginTop: 2,
  },
  climbDetail: {
    color: mobileColors.textMuted,
    fontSize: 13,
    lineHeight: 18,
    marginTop: 12,
  },
  emptyState: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 40,
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
