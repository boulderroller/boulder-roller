import React, { useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  useNavigation,
  useRoute,
  type RouteProp,
} from '@react-navigation/native';
import * as Sentry from '@sentry/react-native';

import { api, ApiError, type RecordBoard, type RecordBoardEntry, type UserPublic } from '../lib/api';
import type { RiderIdentityFields } from '../lib/riderIdentity';
import { riderPrimaryLabel } from '../lib/riderIdentity';
import { riderProfileRouteParams } from '../lib/riderNavigation';
import DetailHeader from '../components/detail/DetailHeader';
import DetailModule from '../components/detail/DetailModule';
import { ErrorBanner } from '../components/ErrorBanner';
import RiderRow from '../components/rider/RiderRow';
import { goBackOrReset } from '../navigation/backNavigation';
import { formatClimbTime } from '../lib/climbDisplay';

type ClimbLeaderboardRouteParams = {
  ClimbLeaderboard: {
    climbId: string;
    climbName?: string;
    backLabel?: string;
  };
};

function riderIdentityForWallet(
  wallet: string | null | undefined,
  profiles: Record<string, UserPublic>,
  entry?: RecordBoardEntry,
): RiderIdentityFields {
  const profile = wallet ? profiles[wallet] : null;
  return {
    id: profile?.id ?? entry?.userId,
    wallet: profile?.wallet ?? wallet ?? entry?.wallet,
    username: profile?.username ?? entry?.username,
    displayName: profile?.displayName ?? entry?.displayName,
    avatarUrl: profile?.avatarUrl ?? entry?.avatarUrl,
    isPublic: profile?.isPublic,
  };
}

export default function ClimbLeaderboardScreen() {
  const navigation = useNavigation();
  const route = useRoute<RouteProp<ClimbLeaderboardRouteParams, 'ClimbLeaderboard'>>();
  const { climbId, climbName, backLabel = 'Climb' } = route.params;

  const [board, setBoard] = useState<RecordBoard | null>(null);
  const [riderProfiles, setRiderProfiles] = useState<Record<string, UserPublic>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [reloadVersion, setReloadVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setError(null);
      try {
        const result = await api.getClimbLeaderboard(climbId);
        if (!cancelled) setBoard(result);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError) {
          setError(err);
        } else {
          setError(new ApiError('Unexpected error', 'unknown'));
          Sentry.captureException(err);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();

    return () => {
      cancelled = true;
    };
  }, [climbId, reloadVersion]);

  const entries = useMemo(
    () => board?.entries?.length ? board.entries : (board?.leaderboard ?? []),
    [board],
  );

  useEffect(() => {
    let cancelled = false;
    const wallets = Array.from(new Set([
      ...entries.map((entry) => entry.wallet),
      board?.komHolder,
    ].filter((wallet): wallet is string => !!wallet)));

    if (wallets.length === 0) {
      setRiderProfiles({});
      return;
    }

    void (async () => {
      const results = await Promise.allSettled(wallets.map((wallet) => api.getUser(wallet)));
      if (cancelled) return;
      const next: Record<string, UserPublic> = {};
      results.forEach((result, index) => {
        if (result.status === 'fulfilled') {
          next[wallets[index]] = result.value;
        }
      });
      setRiderProfiles(next);
    })();

    return () => {
      cancelled = true;
    };
  }, [board?.komHolder, entries]);

  const handleRiderPress = (identity: RiderIdentityFields) => {
    const route = riderProfileRouteParams(identity, {
      backLabel: 'Leaderboard',
      allowWalletFallback: true,
    });
    if (!route) return;
    (
      navigation as {
        navigate: (
          screen: string,
          params: { identifier: string; initialIdentity?: RiderIdentityFields; backLabel?: string },
        ) => void;
      }
    ).navigate('RiderDetail', route);
  };

  const komIdentity = riderIdentityForWallet(board?.komHolder, riderProfiles);

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <ScrollView contentContainerStyle={styles.scroll}>
        <DetailHeader
          backLabel={backLabel}
          title={climbName ?? board?.climbName ?? 'Leaderboard'}
          subtitle="All-time top 10 for this climb."
          onBack={() => goBackOrReset(navigation, 'Climbs')}
          tone="deep"
        />

        {error && (
          <ErrorBanner
            message={error.retryable ? 'Connection issue' : 'Unable to load leaderboard'}
            onRetry={error.retryable ? () => {
              setLoading(true);
              setError(null);
              setReloadVersion((value) => value + 1);
            } : undefined}
            onDismiss={() => setError(null)}
          />
        )}

        {loading ? (
          <View style={styles.center}>
            <ActivityIndicator size="large" color="#e5e5e5" />
          </View>
        ) : (
          <>
            <DetailModule title="KOM">
              <Text style={styles.summaryValue}>
                {riderPrimaryLabel(komIdentity)} • {formatClimbTime(board?.komTimeS)}
              </Text>
            </DetailModule>

            <DetailModule title="Top 10">
              {entries.length > 0 ? (
                entries.map((entry) => {
                  const identity = riderIdentityForWallet(entry.wallet, riderProfiles, entry);
                  return (
                    <RiderRow
                      key={`${entry.rank}-${entry.wallet}`}
                      testID={`leaderboard-rider-${entry.rank}`}
                      rankLabel={`#${entry.rank}`}
                      identity={identity}
                      subtitle="Top time"
                      value={formatClimbTime(entry.bestTimeSeconds)}
                      onPress={() => handleRiderPress(identity)}
                    />
                  );
                })
              ) : (
                <Text style={styles.emptyText}>No leaderboard entries yet.</Text>
              )}
            </DetailModule>
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0a0a0a',
  },
  scroll: {
    padding: 20,
    paddingBottom: 32,
  },
  center: {
    paddingVertical: 48,
    alignItems: 'center',
  },
  summaryValue: {
    fontSize: 18,
    fontWeight: '700',
    color: '#ededed',
  },
  emptyText: {
    fontSize: 14,
    color: '#9a9a9a',
    paddingVertical: 16,
  },
});
