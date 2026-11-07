import React, { useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  useNavigation,
  useRoute,
  type RouteProp,
} from '@react-navigation/native';
import * as Sentry from '@sentry/react-native';

import {
  api,
  ApiError,
  type ClimbSummary,
  type RecordBoard,
  type RecordBoardEntry,
  type ResolvedLink,
  type UserPublic,
} from '../lib/api';
import type { RiderIdentityFields } from '../lib/riderIdentity';
import { riderPrimaryLabel } from '../lib/riderIdentity';
import { riderProfileRouteParams } from '../lib/riderNavigation';
import DetailHeader from '../components/detail/DetailHeader';
import DetailModule from '../components/detail/DetailModule';
import RoutePreviewMap from '../components/route/RoutePreviewMap';
import { ErrorBanner } from '../components/ErrorBanner';
import {
  LocalObjectTabs,
  MetricBand,
  ObjectWindow,
  QuietProofRow,
} from '../components/surfaces/MobileSpine';
import RiderRow from '../components/rider/RiderRow';
import { goBackOrReset } from '../navigation/backNavigation';
import {
  openResolvedProof as openResolvedBoulderScanTarget,
  shareResolvedPayload,
} from '../lib/linkActions';
import {
  buildClimbDetailDisplayModel,
  formatClimbTime,
  previewRecordEntries,
} from '../lib/climbDisplay';
import { mobileColors, mobileRadii } from '../theme/tokens';

type ClimbDetailRouteParams = {
  ClimbDetail: {
    climbId: string;
    backLabel?: string;
  };
};

const CLIMB_OBJECT_TABS = [
  { key: 'overview', label: 'Overview' },
  { key: 'board', label: 'Leaderboard' },
  { key: 'legend', label: 'Legend' },
  { key: 'record', label: 'Verification' },
];

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

export default function ClimbDetailScreen() {
  const navigation = useNavigation();
  const route = useRoute<RouteProp<ClimbDetailRouteParams, 'ClimbDetail'>>();
  const { climbId, backLabel = 'Climbs' } = route.params;

  const [climb, setClimb] = useState<ClimbSummary | null>(null);
  const [leaderboard, setLeaderboard] = useState<RecordBoard | null>(null);
  const [resolvedLink, setResolvedLink] = useState<ResolvedLink | null>(null);
  const [riderProfiles, setRiderProfiles] = useState<Record<string, UserPublic>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [shareBusy, setShareBusy] = useState(false);
  const [reloadVersion, setReloadVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setError(null);
      try {
        const [climbResult, leaderboardResult, linkResult] = await Promise.all([
          api.getClimb(climbId),
          api.getClimbLeaderboard(climbId).catch((err) => {
            Sentry.captureException(err);
            return null;
          }),
          api.resolveLink('climb', climbId).catch((err) => {
            Sentry.captureException(err);
            return null;
          }),
        ]);

        if (cancelled) return;
        setClimb(climbResult);
        setLeaderboard(leaderboardResult ?? climbResult.recordBoard ?? null);
        setResolvedLink(linkResult);
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

  const entries = useMemo(() => previewRecordEntries(leaderboard), [leaderboard]);

  useEffect(() => {
    let cancelled = false;
    const wallets = Array.from(new Set([
      ...entries.map((entry) => entry.wallet),
      leaderboard?.komHolder,
      climb?.localLegend?.wallet,
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
  }, [climb?.localLegend?.wallet, entries, leaderboard?.komHolder]);

  const handleBack = () => {
    goBackOrReset(navigation, 'Climbs');
  };

  const handleRetry = () => {
    setLoading(true);
    setError(null);
    setClimb(null);
    setLeaderboard(null);
    setReloadVersion((value) => value + 1);
  };

  const handleLeaderboardPress = () => {
    if (!climb) return;
    (
      navigation as {
        navigate: (
          screen: string,
          params: { climbId: string; climbName?: string; backLabel?: string },
        ) => void;
      }
    ).navigate('ClimbLeaderboard', {
      climbId,
      climbName: climb.name,
      backLabel: 'Climb',
    });
  };

  const handleRiderPress = (identity: RiderIdentityFields) => {
    const route = riderProfileRouteParams(identity, {
      backLabel: 'Climb',
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

  const handleShareClimb = async () => {
    if (shareBusy) return;
    setShareBusy(true);
    try {
      const link = resolvedLink ?? await api.resolveLink('climb', climbId);
      setResolvedLink(link);
      await shareResolvedPayload(link.share);
    } catch {
      Alert.alert('Share failed', 'Please try again in a moment.');
    } finally {
      setShareBusy(false);
    }
  };

  const handleOpenBoulderScan = () => {
    void openResolvedBoulderScanTarget(resolvedLink);
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.container} edges={['top']}>
        <View style={styles.center}>
          <ActivityIndicator size="large" color={mobileColors.accent} />
        </View>
      </SafeAreaView>
    );
  }

  if (!climb) {
    return (
      <SafeAreaView style={styles.container} edges={['top']}>
        <ScrollView contentContainerStyle={styles.scroll}>
          <DetailHeader
            backLabel={backLabel}
            title="Climb"
            subtitle="We couldn't load this climb right now."
            onBack={handleBack}
          />
          <DetailModule title="Unavailable">
            <Text style={styles.sectionBody}>
              Try again from the climbs list.
            </Text>
          </DetailModule>
        </ScrollView>
      </SafeAreaView>
    );
  }

  const displayModel = buildClimbDetailDisplayModel({
    climb,
    leaderboard,
    resolvedLink,
    komLabel: riderPrimaryLabel(riderIdentityForWallet(leaderboard?.komHolder, riderProfiles)),
  });

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <ScrollView contentContainerStyle={styles.scroll}>
        <DetailHeader
          backLabel={backLabel}
          eyebrow="Climb"
          title={displayModel.title}
          subtitle={displayModel.subtitle}
          statusLabel={displayModel.heroStatusLabel}
          onBack={handleBack}
        >
          <MetricBand items={displayModel.heroStats} />
        </DetailHeader>

        <ObjectWindow style={styles.tabsWindow}>
          <LocalObjectTabs items={CLIMB_OBJECT_TABS} activeKey="overview" />
        </ObjectWindow>

        <RoutePreviewMap
          preview={climb.routePreview ?? null}
          variant="detail"
          height={224}
          style={styles.featuredMap}
          testID="climb-detail-route-preview"
        />

        {error && (
          <ErrorBanner
            message={error.retryable ? 'Connection issue' : 'Unable to load climb'}
            onRetry={error.retryable ? handleRetry : undefined}
            onDismiss={() => setError(null)}
          />
        )}

        <DetailModule title="Climb details" subtitle={displayModel.heroStateLine}>
          <QuietProofRow
            items={[
              {
                label: 'Top time',
                value: displayModel.topTimesSubtitle,
                tone: entries.length > 0 ? 'proof' : 'muted',
              },
              {
                label: 'Vault',
                value: displayModel.vaultValue,
                tone: climb.hasVault ? 'reward' : 'muted',
              },
            ]}
          />
        </DetailModule>

        <DetailModule
          title="BoulderScan"
          subtitle={displayModel.boulderScanSubtitle}
          ctaLabel={displayModel.boulderScanCtaLabel ?? undefined}
          onPressCta={displayModel.boulderScanCtaLabel ? handleOpenBoulderScan : undefined}
        >
          <View style={styles.actionRow}>
            <TouchableOpacity
              style={[styles.shareButton, shareBusy && styles.shareButtonDisabled]}
              disabled={shareBusy}
              onPress={handleShareClimb}
              activeOpacity={0.84}
              testID="climb-detail-share"
            >
              <Text style={styles.shareButtonText}>{shareBusy ? 'Sharing' : 'Share climb'}</Text>
            </TouchableOpacity>
            <Text style={styles.sectionMeta}>
              {displayModel.boulderScanTargetLabel}
            </Text>
          </View>
        </DetailModule>

        <DetailModule
          title="Leaderboard"
          subtitle={displayModel.topTimesSubtitle}
          ctaLabel="See Top 10"
          onPressCta={handleLeaderboardPress}
        >
          {entries.length > 0 ? (
            entries.map((entry) => {
              const identity = riderIdentityForWallet(entry.wallet, riderProfiles, entry);
              return (
                <RiderRow
                  key={`${entry.rank}-${entry.wallet}`}
                  testID={`climb-detail-rider-${entry.rank}`}
                  rankLabel={`#${entry.rank}`}
                  identity={identity}
                  subtitle="Top time"
                  value={formatClimbTime(entry.bestTimeSeconds)}
                  onPress={() => handleRiderPress(identity)}
                />
              );
            })
          ) : (
            <Text style={styles.sectionBody}>
              No times yet
            </Text>
          )}
        </DetailModule>

        <DetailModule title="Legend">
          {climb.localLegend?.wallet ? (
            <>
              <RiderRow
                identity={riderIdentityForWallet(climb.localLegend.wallet, riderProfiles)}
                subtitle={`${climb.localLegend.attemptsInWindow} recent rides`}
                onPress={() => handleRiderPress(
                  riderIdentityForWallet(climb.localLegend?.wallet, riderProfiles),
                )}
                withDivider={false}
              />
            </>
          ) : (
            <Text style={styles.sectionBody}>
              No current legend
            </Text>
          )}
        </DetailModule>

        {climb.hasVault ? (
          <DetailModule title="Vault">
            <Text style={styles.sectionBody}>
              {displayModel.vaultValue}
            </Text>
            <Text style={styles.sectionMeta}>
              {displayModel.vaultMeta}
            </Text>
          </DetailModule>
        ) : null}

        <DetailModule title="Your best">
          <Text style={styles.sectionBody}>
            Ride it to set a time.
          </Text>
        </DetailModule>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: mobileColors.canvas,
  },
  center: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 32,
  },
  scroll: {
    padding: 14,
    paddingBottom: 32,
  },
  tabsWindow: {
    marginTop: -2,
    paddingHorizontal: 4,
    paddingVertical: 2,
  },
  featuredMap: {
    marginBottom: 10,
  },
  sectionBody: {
    fontSize: 14,
    color: mobileColors.textMuted,
    lineHeight: 20,
  },
  sectionMeta: {
    fontSize: 13,
    color: mobileColors.textMuted,
    marginBottom: 12,
  },
  actionRow: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 10,
  },
  shareButton: {
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: mobileColors.borderStrong,
    backgroundColor: 'rgba(255, 253, 247, 0.42)',
    borderRadius: mobileRadii.sm,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  shareButtonDisabled: {
    opacity: 0.55,
  },
  shareButtonText: {
    color: mobileColors.accentMuted,
    fontSize: 12,
    fontWeight: '800',
  },
  boardRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 11,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: mobileColors.divider,
  },
  boardRank: {
    width: 34,
    fontSize: 14,
    fontWeight: '800',
    color: mobileColors.text,
  },
  boardWallet: {
    flex: 1,
    fontSize: 14,
    color: mobileColors.textMuted,
  },
  boardTime: {
    fontSize: 14,
    fontWeight: '800',
    color: mobileColors.text,
  },
});
