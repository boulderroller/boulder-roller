import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
  Alert,
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
  type BeetleCard,
  type FollowState,
  type PublicRiderProfileModule,
  type PublicRiderViewerCapabilities,
  type PublicRiderRideSummary,
  type ResolvedLink,
  type User,
  type UserLeaderboardSummary,
  type UserPublic,
} from '../lib/api';
import type { RiderIdentityFields } from '../lib/riderIdentity';
import { useAuthStore } from '../stores/authStore';
import DetailHeader from '../components/detail/DetailHeader';
import DetailModule from '../components/detail/DetailModule';
import { ErrorBanner } from '../components/ErrorBanner';
import FollowButton, { type FollowButtonState } from '../components/rider/FollowButton';
import RiderHeader from '../components/rider/RiderHeader';
import BeetleCardModule from '../components/rider/BeetleCardModule';
import { goBackOrReset } from '../navigation/backNavigation';
import { openResolvedProof as openResolvedBoulderScanTarget, shareResolvedPayload } from '../lib/linkActions';
import {
  buildRiderDetailDisplayModel,
  buildRiderLeaderboardPositionDisplay,
  buildRiderRecentRideDisplay,
} from '../lib/riderDisplay';

type RiderDetailRouteParams = {
  RiderDetail: {
    identifier: string;
    initialIdentity?: RiderIdentityFields;
    backLabel?: string;
  };
};

function followButtonState(
  profile: UserPublic | null,
  viewer: User | null,
  follow: FollowState | null,
  busy: boolean,
  failed: boolean,
): FollowButtonState | null {
  if (!profile || !viewer || profile.isPublic === false) return null;
  if (viewer.id && profile.id === viewer.id) return 'self';
  if (busy) return 'loading';
  if (failed) return 'error';
  if (!follow) return 'loading';
  if (follow.isMutualFollow) return 'mutual';
  return follow.isFollowing ? 'following' : 'not_following';
}

export default function RiderDetailScreen() {
  const navigation = useNavigation();
  const route = useRoute<RouteProp<RiderDetailRouteParams, 'RiderDetail'>>();
  const { identifier, initialIdentity, backLabel = 'Back' } = route.params;

  const isAuthenticated = useAuthStore(
    (s) => s.status === 'authenticated' || s.status === 'refreshing',
  );
  const authWallet = useAuthStore((s) => s.wallet);

  const [profile, setProfile] = useState<UserPublic | null>(null);
  const [viewer, setViewer] = useState<User | null>(null);
  const [leaderboard, setLeaderboard] = useState<UserLeaderboardSummary | null>(null);
  const [recentRides, setRecentRides] = useState<PublicRiderRideSummary[]>([]);
  const [beetleCards, setBeetleCards] = useState<BeetleCard[]>([]);
  const [modules, setModules] = useState<PublicRiderProfileModule[]>([]);
  const [capabilities, setCapabilities] = useState<PublicRiderViewerCapabilities | null>(null);
  const [resolvedLink, setResolvedLink] = useState<ResolvedLink | null>(null);
  const [follow, setFollow] = useState<FollowState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [followBusy, setFollowBusy] = useState(false);
  const [followFailed, setFollowFailed] = useState(false);
  const [reportStatus, setReportStatus] = useState<string | null>(null);
  const [reportBusy, setReportBusy] = useState(false);
  const [shareBusy, setShareBusy] = useState(false);
  const [reloadVersion, setReloadVersion] = useState(0);

  const displayModel = useMemo(
    () => buildRiderDetailDisplayModel({
      profile,
      initialIdentity,
      identifier,
      recentRideCount: recentRides.length,
      leaderboard,
      resolvedLink,
    }),
    [identifier, initialIdentity, leaderboard, profile, recentRides.length, resolvedLink],
  );
  const identity = displayModel.identity;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setFollow(null);
    setFollowFailed(false);
    setReportStatus(null);
    setProfile(null);
    setViewer(null);
    setLeaderboard(null);
    setRecentRides([]);
    setBeetleCards([]);
    setModules([]);
    setCapabilities(null);
    setResolvedLink(null);

    try {
      const profileBundle = await api.getPublicRiderProfile(identifier, 5);
      const publicProfile = profileBundle.profile;
      setProfile(publicProfile);
      setRecentRides(profileBundle.recentRides?.rides ?? []);
      setBeetleCards(profileBundle.beetleCards?.cards ?? []);
      setLeaderboard(profileBundle.leaderboard ?? null);
      setFollow(profileBundle.followState ?? null);
      setModules(profileBundle.modules ?? []);
      setCapabilities(profileBundle.viewerCapabilities ?? null);

      if (publicProfile.isPublic === false) {
        return;
      }

      const publicIdentifier = profileBundle.rider?.username
        ?? profileBundle.rider?.id
        ?? publicProfile.username
        ?? publicProfile.id;
      const [viewerResult, linkResult] = await Promise.allSettled([
        isAuthenticated ? api.getMe() : Promise.resolve(null),
        api.resolveLink('rider', publicIdentifier),
      ]);

      const viewerProfile = viewerResult.status === 'fulfilled' ? viewerResult.value : null;
      setViewer(viewerProfile);

      setResolvedLink(linkResult.status === 'fulfilled' ? linkResult.value : null);

      if (viewerProfile?.id && viewerProfile.id !== publicProfile.id && !profileBundle.followState) {
        try {
          setFollow(await api.getFollowState(publicProfile.id));
        } catch (err) {
          setFollowFailed(true);
          if (!(err instanceof ApiError)) Sentry.captureException(err);
        }
      }
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err);
      } else {
        setError(new ApiError('Unexpected error', 'unknown'));
        Sentry.captureException(err);
      }
    } finally {
      setLoading(false);
    }
  }, [identifier, isAuthenticated]);

  useEffect(() => {
    void load();
  }, [load, reloadVersion]);

  const handleFollowPress = useCallback(async () => {
    const targetState = followButtonState(profile, viewer, follow, followBusy, followFailed);
    if (!profile || !targetState || targetState === 'loading' || targetState === 'self') return;

    setFollowBusy(true);
    setFollowFailed(false);
    try {
      if (follow?.isFollowing || follow?.isMutualFollow) {
        await api.unfollowUser(profile.id);
        setFollow({
          isFollowing: false,
          isFollowedBy: follow?.isFollowedBy ?? false,
          isMutualFollow: false,
        });
      } else {
        await api.followUser(profile.id);
        setFollow({
          isFollowing: true,
          isFollowedBy: follow?.isFollowedBy ?? false,
          isMutualFollow: follow?.isFollowedBy ?? false,
        });
      }
    } catch (err) {
      setFollowFailed(true);
      if (!(err instanceof ApiError)) Sentry.captureException(err);
    } finally {
      setFollowBusy(false);
    }
  }, [follow, followBusy, followFailed, profile, viewer]);

  const handleClimbPress = useCallback((canonClimbId: string) => {
    (
      navigation as {
        navigate: (screen: string, params: { climbId: string; backLabel?: string }) => void;
      }
    ).navigate('ClimbDetail', {
      climbId: canonClimbId,
      backLabel: 'Rider',
    });
  }, [navigation]);

  const handleRidePress = useCallback((rideId: string) => {
    (
      navigation as {
        navigate: (screen: string, params: { serverRideId: string; backLabel?: string }) => void;
      }
    ).navigate('RideDetail', { serverRideId: rideId, backLabel: 'Rider' });
  }, [navigation]);

  const handleShareRider = useCallback(async () => {
    if (!profile || shareBusy) return;
    setShareBusy(true);
    try {
      const link = resolvedLink ?? await api.resolveLink('rider', profile.username ?? profile.id);
      setResolvedLink(link);
      await shareResolvedPayload(link.share);
    } catch (err) {
      Alert.alert('Share failed', 'Please try again in a moment.');
      if (!(err instanceof ApiError)) Sentry.captureException(err);
    } finally {
      setShareBusy(false);
    }
  }, [profile, resolvedLink, shareBusy]);

  const handleOpenBoulderScan = useCallback(() => {
    void openResolvedBoulderScanTarget(resolvedLink);
  }, [resolvedLink]);

  const submitRiderReport = useCallback(async () => {
    if (!profile?.id || reportBusy || reportStatus) return;

    setReportBusy(true);
    try {
      const report = await api.reportSocialContent(
        'user',
        profile.id,
        'other',
        'Reported from mobile rider profile',
      );
      setReportStatus(report.status);
    } catch (err) {
      Alert.alert('Report failed', 'Please try again in a moment.');
      if (!(err instanceof ApiError)) Sentry.captureException(err);
    } finally {
      setReportBusy(false);
    }
  }, [profile?.id, reportBusy, reportStatus]);

  const handleReportRider = useCallback(() => {
    if (reportStatus) return;
    Alert.alert(
      'Report rider',
      'Send this rider profile to the moderation queue for review?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Report',
          style: 'destructive',
          onPress: () => {
            void submitRiderReport();
          },
        },
      ],
    );
  }, [reportStatus, submitRiderReport]);

  const moduleState = useCallback(
    (moduleId: string) => modules.find((module) => module.id === moduleId)?.state,
    [modules],
  );
  const canFollowRider = capabilities?.canFollow !== false;
  const canShareRider = capabilities?.canShare !== false && profile?.isPublic !== false;
  const buttonState = canFollowRider ? followButtonState(profile, viewer, follow, followBusy, followFailed) : null;
  const canReportRider = Boolean(capabilities?.canReport && profile && viewer && profile.id !== viewer.id);
  const riderActions = (
    <View style={styles.riderActions}>
      {buttonState ? (
        <FollowButton
          state={buttonState}
          onPress={buttonState === 'self' ? undefined : handleFollowPress}
        />
      ) : null}
      {canReportRider ? (
        <TouchableOpacity
          style={[styles.reportButton, (reportBusy || !!reportStatus) && styles.reportButtonDisabled]}
          disabled={reportBusy || !!reportStatus}
          onPress={handleReportRider}
          activeOpacity={0.82}
          testID="rider-detail-report"
        >
          <Text style={styles.reportButtonText}>
            {reportStatus ? `Reported${reportStatus ? ` • ${reportStatus}` : ''}` : reportBusy ? 'Reporting' : 'Report'}
          </Text>
        </TouchableOpacity>
      ) : null}
      {canShareRider ? (
        <TouchableOpacity
          style={[styles.shareButton, shareBusy && styles.reportButtonDisabled]}
          disabled={shareBusy}
          onPress={handleShareRider}
          activeOpacity={0.82}
          testID="rider-detail-share"
        >
          <Text style={styles.shareButtonText}>{shareBusy ? 'Sharing' : 'Share'}</Text>
        </TouchableOpacity>
      ) : null}
    </View>
  );

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <ScrollView contentContainerStyle={styles.scroll}>
        <DetailHeader
          backLabel={backLabel}
          title={displayModel.title}
          subtitle={displayModel.subtitle}
          onBack={() => goBackOrReset(navigation, 'Profile')}
        />

        {error && (
          <ErrorBanner
            message={error.statusCode === 404 ? 'Rider profile not found' : 'Unable to load rider'}
            onRetry={() => setReloadVersion((value) => value + 1)}
            onDismiss={() => setError(null)}
          />
        )}

        {loading ? (
          <View style={styles.center}>
            <ActivityIndicator size="large" color="#e5e5e5" />
          </View>
        ) : (
          <>
            <RiderHeader
              identity={identity}
              bio={displayModel.bio}
              stats={displayModel.stats}
              action={(buttonState || canReportRider || canShareRider) ? riderActions : undefined}
              accountContext={!!authWallet && authWallet === identity.wallet}
            />

            {profile?.isPublic === false ? (
              <DetailModule title="Private Rider">
                <Text style={styles.body}>
                  This rider keeps their profile private.
                </Text>
              </DetailModule>
            ) : null}

            {profile?.isPublic !== false && moduleState('recent_rides') !== 'hidden' ? (
              <DetailModule
                title="Recent Rides"
                subtitle={displayModel.recentRidesSubtitle}
              >
                {recentRides.length > 0 ? (
                  recentRides.map((ride) => {
                    const rideDisplay = buildRiderRecentRideDisplay(ride);
                    return (
                      <TouchableOpacity
                        key={ride.id}
                        style={styles.rideRow}
                        onPress={() => handleRidePress(ride.id)}
                        activeOpacity={0.84}
                        testID={`rider-detail-ride-${ride.id}`}
                      >
                        <View style={styles.positionCopy}>
                          <Text style={styles.positionName}>{rideDisplay.title}</Text>
                          <Text style={styles.positionMeta}>
                            {rideDisplay.meta}
                          </Text>
                        </View>
                        <Text style={styles.positionTime}>
                          {rideDisplay.distanceLabel}
                        </Text>
                        <Text style={styles.chevron}>›</Text>
                      </TouchableOpacity>
                    );
                  })
                ) : (
                  <Text style={styles.body}>No public recent rides.</Text>
                )}
              </DetailModule>
            ) : null}

            {profile?.isPublic !== false && moduleState('beetle_cards') !== 'hidden' && beetleCards.length > 0 ? (
              <BeetleCardModule cards={beetleCards} />
            ) : null}

            {resolvedLink ? (
              <DetailModule
                title="BoulderScan"
                subtitle={displayModel.boulderScanSubtitle ?? undefined}
                ctaLabel={displayModel.boulderScanCtaLabel ?? undefined}
                onPressCta={handleOpenBoulderScan}
              >
                <Text style={styles.body}>{resolvedLink.description}</Text>
              </DetailModule>
            ) : null}

            {leaderboard ? (
              <DetailModule
                title="Top Climbs"
                subtitle={displayModel.topClimbsSubtitle ?? undefined}
              >
                {leaderboard.positions.length > 0 ? (
                  leaderboard.positions.slice(0, 4).map((position) => {
                    const positionDisplay = buildRiderLeaderboardPositionDisplay(position);
                    const canOpenClimb = Boolean(position.canonClimbId);
                    return (
                      <TouchableOpacity
                        key={`${position.vaultId}-${position.rank}`}
                        style={styles.positionRow}
                        disabled={!canOpenClimb}
                        onPress={position.canonClimbId
                          ? () => handleClimbPress(position.canonClimbId!)
                          : undefined}
                        activeOpacity={canOpenClimb ? 0.84 : 1}
                        testID={`rider-detail-climb-${position.vaultId}`}
                      >
                        <View style={styles.positionCopy}>
                          <Text style={styles.positionName}>{positionDisplay.name}</Text>
                          <Text style={styles.positionMeta}>
                            {positionDisplay.meta}
                          </Text>
                        </View>
                        <Text style={styles.positionTime}>
                          {positionDisplay.time}
                        </Text>
                        {canOpenClimb ? <Text style={styles.chevron}>›</Text> : null}
                      </TouchableOpacity>
                    );
                  })
                ) : (
                  <Text style={styles.body}>No top climb times yet.</Text>
                )}
              </DetailModule>
            ) : null}
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
  body: {
    color: '#b7b7b7',
    fontSize: 14,
    lineHeight: 20,
  },
  riderActions: {
    alignItems: 'flex-end',
    gap: 8,
  },
  reportButton: {
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: '#4a332f',
    backgroundColor: '#1a1010',
    paddingHorizontal: 10,
    paddingVertical: 7,
  },
  reportButtonDisabled: {
    opacity: 0.55,
  },
  reportButtonText: {
    color: '#e4b0a8',
    fontSize: 12,
    fontWeight: '700',
  },
  shareButton: {
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: '#3b3320',
    backgroundColor: '#171309',
    paddingHorizontal: 10,
    paddingVertical: 7,
  },
  shareButtonText: {
    color: '#d0af48',
    fontSize: 12,
    fontWeight: '700',
  },
  rideRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#2e2e2e',
  },
  positionRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#2e2e2e',
  },
  positionCopy: {
    flex: 1,
    minWidth: 0,
  },
  positionName: {
    color: '#ededed',
    fontSize: 14,
    fontWeight: '700',
  },
  positionMeta: {
    color: '#858585',
    fontSize: 12,
    marginTop: 3,
  },
  positionTime: {
    color: '#ededed',
    fontSize: 14,
    fontWeight: '700',
    fontVariant: ['tabular-nums'],
  },
  chevron: {
    color: '#666666',
    fontSize: 18,
    lineHeight: 18,
    marginLeft: 8,
  },
});
