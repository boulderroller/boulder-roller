import React, { useCallback, useState } from 'react';
import { View, Text, StyleSheet, ActivityIndicator, ScrollView, TouchableOpacity } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useFocusEffect, useNavigation } from '@react-navigation/native';
import type { NavigationProp } from '@react-navigation/native';
import { usePrivy } from '@privy-io/expo';
import * as Sentry from '@sentry/react-native';
import { api, ApiError, User } from '../lib/api';
import { useAuthStore } from '../stores/authStore';
import { logout } from '../services/authService';
import { ErrorBanner } from '../components/ErrorBanner';
import { usePairingStore } from '../stores/pairingStore';
import TopTabBar from '../components/navigation/TopTabBar';
import SectionCard from '../components/surfaces/SectionCard';
import ActionRow from '../components/surfaces/ActionRow';
import type { StatClusterItem } from '../components/surfaces/StatCluster';
import RiderHeader from '../components/rider/RiderHeader';
import BeetleCardModule from '../components/rider/BeetleCardModule';
import DetailModule from '../components/detail/DetailModule';
import type { BeetleCard, UserLeaderboardSummary } from '../lib/api';
import { mobileColors } from '../theme/tokens';

type RootParamList = {
  Pairing: undefined;
  Wallet: undefined;
  Search: undefined;
  Notifications: undefined;
  EditProfile: undefined;
  PrivacySettings: undefined;
  NotificationPreferences: undefined;
  MyReports: undefined;
  [k: string]: undefined | object;
};

export default function ProfileScreen() {
  const [user, setUser] = useState<User | null>(null);
  const [beetleCards, setBeetleCards] = useState<BeetleCard[]>([]);
  const [leaderboard, setLeaderboard] = useState<UserLeaderboardSummary | null>(null);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const isAuthenticated = useAuthStore((s) => s.status === 'authenticated' || s.status === 'refreshing');
  const authMethod = useAuthStore((s) => s.authMethod);
  const navigation = useNavigation<NavigationProp<RootParamList>>();
  const { logout: privyLogout } = usePrivy();
  const pairedCount = usePairingStore((s) => s.known.length);
  const connectedCount = usePairingStore(
    (s) => Object.values(s.connections).filter((c) => c.status === 'connected').length,
  );

  const fetchProfile = useCallback(async () => {
    if (!isAuthenticated) {
      setLoading(false);
      return;
    }
    setError(null);
    try {
      const snapshot = await api.getMyProfileBootstrap();
      setUser(snapshot.profile);
      setBeetleCards(snapshot.beetleCards?.cards ?? []);
      setLeaderboard(snapshot.leaderboard ?? null);
      setUnreadCount(snapshot.notifications?.unreadCount ?? 0);
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
    }
  }, [isAuthenticated]);

  useFocusEffect(
    useCallback(() => {
      void fetchProfile();
    }, [fetchProfile]),
  );

  const handleLogout = async () => {
    if (authMethod === 'privy') {
      try {
        await privyLogout();
      } catch (err) {
        if (err instanceof Error) {
          Sentry.captureException(err);
        }
      }
    }
    try {
      await logout();
    } catch (err) {
      // Force clear even on error, but report to Sentry
      if (err instanceof Error && !(err instanceof ApiError)) {
        Sentry.captureException(err);
      }
    }
    setUser(null);
    setBeetleCards([]);
    setLeaderboard(null);
  };

  const handleClimbPress = (canonClimbId: string) => {
    navigation.navigate('ClimbDetail', {
      climbId: canonClimbId,
      backLabel: 'Profile',
    });
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.container}>
        <ActivityIndicator size="large" color={mobileColors.accent} style={styles.loader} />
      </SafeAreaView>
    );
  }

  if (!isAuthenticated || !user) {
    return (
      <SafeAreaView style={styles.container} edges={['top']}>
        <TopTabBar
          title="Profile"
          testIdPrefix="profile"
          unreadCount={unreadCount}
          onPressSearch={() => navigation.navigate('Search')}
          onPressAlerts={() => navigation.navigate('Notifications')}
        />
        <View style={styles.emptyState}>
          <Text style={styles.emptyTitle}>Not signed in</Text>
          <Text style={styles.emptySubtitle}>
            Continue with email or your rider wallet to view your profile.
          </Text>
        </View>
      </SafeAreaView>
    );
  }

  const profileStats: StatClusterItem[] = [
    { label: 'Rides', value: String(user.totalRides ?? 0) },
    {
      label: 'Vert',
      value: user.totalElevationM != null
        ? `${Math.round(user.totalElevationM).toLocaleString()} m`
        : '—',
    },
  ];

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <TopTabBar
        title="Profile"
        testIdPrefix="profile"
        unreadCount={unreadCount}
        onPressSearch={() => navigation.navigate('Search')}
        onPressAlerts={() => navigation.navigate('Notifications')}
      />

      {error && (
        <ErrorBanner
          message={error.retryable ? 'Connection issue' : 'Unable to load profile'}
          onRetry={error.retryable ? fetchProfile : undefined}
          onDismiss={() => setError(null)}
        />
      )}

      <ScrollView
        contentContainerStyle={styles.scrollContent}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.heroSection}>
          <RiderHeader
            identity={user}
            bio={user.bio}
            stats={profileStats}
            accountContext
            testID="profile-rider-header"
          />
        </View>

        <BeetleCardModule cards={beetleCards} />

        {leaderboard ? (
          <DetailModule
            title="Top Climbs"
            subtitle={`${leaderboard.stats.komCount} KOMs • ${leaderboard.stats.podiumCount} podiums`}
            style={styles.section}
          >
              {leaderboard.positions.length > 0 ? (
                leaderboard.positions.slice(0, 3).map((position, index) => {
                  const canOpenClimb = Boolean(position.canonClimbId);
                  return (
                    <TouchableOpacity
                      key={`${position.vaultId}-${position.rank}`}
                      style={[styles.positionRow, index > 0 && styles.rowDivider]}
                      disabled={!canOpenClimb}
                      onPress={position.canonClimbId
                        ? () => handleClimbPress(position.canonClimbId!)
                        : undefined}
                      activeOpacity={canOpenClimb ? 0.84 : 1}
                      testID={`profile-climb-${position.vaultId}`}
                    >
                      <View style={styles.positionCopy}>
                        <Text style={styles.positionTitle}>{position.vaultName}</Text>
                        <Text style={styles.positionMeta}>
                          #{position.rank} of {position.totalRiders.toLocaleString()}
                        </Text>
                      </View>
                      <Text style={styles.positionValue}>
                        {position.isKom ? 'KOM' : `#${position.rank}`}
                      </Text>
                      {canOpenClimb ? <Text style={styles.chevron}>›</Text> : null}
                    </TouchableOpacity>
                  );
                })
              ) : (
                <Text style={styles.emptySectionText}>No top climb times yet.</Text>
              )}
          </DetailModule>
        ) : null}

        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Settings</Text>
          <SectionCard tone="strong">
            <ActionRow
              title="Edit profile"
              subtitle="Name, username, bio, and avatar"
              onPress={() => navigation.navigate('EditProfile')}
            />
            <ActionRow
              title="Privacy"
              subtitle={`${user.isPublic === false ? 'Private' : 'Public'} profile · rides default ${user.defaultRideVisibility ?? 'public'}`}
              onPress={() => navigation.navigate('PrivacySettings')}
              withDivider
            />
            <ActionRow
              title="Notifications"
              subtitle={`${unreadCount} unread · alert groups`}
              onPress={() => navigation.navigate('NotificationPreferences')}
              withDivider
            />
            <ActionRow
              title="Reports"
              subtitle="Submitted moderation reports"
              onPress={() => navigation.navigate('MyReports')}
              withDivider
            />
            <ActionRow
              title="Power, Heart Rate, Cadence"
              subtitle={`${connectedCount} connected · ${pairedCount} paired`}
              onPress={() => navigation.navigate('Pairing')}
              withDivider
            />
            <ActionRow
              title="Wallet"
              subtitle="Connected wallet and CAL"
              onPress={() => navigation.navigate('Wallet')}
              withDivider
            />
            <ActionRow
              title="Sign Out"
              destructive
              onPress={handleLogout}
              withDivider
            />
          </SectionCard>
        </View>
      </ScrollView>
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
  scrollContent: {
    paddingHorizontal: 14,
    paddingTop: 12,
    paddingBottom: 24,
  },
  heroSection: {
    marginBottom: 16,
  },
  section: {
    marginBottom: 16,
  },
  sectionTitle: {
    fontSize: 12,
    fontWeight: '800',
    color: mobileColors.textSubtle,
    letterSpacing: 0,
    textTransform: 'uppercase',
    marginBottom: 10,
  },
  positionRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 14,
  },
  rowDivider: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: mobileColors.divider,
  },
  positionCopy: {
    flex: 1,
  },
  positionTitle: {
    color: mobileColors.text,
    fontSize: 15,
    fontWeight: '700',
  },
  positionMeta: {
    color: mobileColors.textMuted,
    fontSize: 12,
    marginTop: 4,
  },
  positionValue: {
    color: mobileColors.accent,
    fontSize: 13,
    fontWeight: '800',
  },
  chevron: {
    color: mobileColors.textSubtle,
    fontSize: 18,
    lineHeight: 18,
    marginLeft: 8,
  },
  emptySectionText: {
    color: mobileColors.textMuted,
    fontSize: 14,
    paddingHorizontal: 16,
    paddingVertical: 16,
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
