import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import * as Sentry from '@sentry/react-native';

import { api, ApiError, type NotificationPreferences } from '../lib/api';
import DetailHeader from '../components/detail/DetailHeader';
import DetailModule from '../components/detail/DetailModule';
import { ErrorBanner } from '../components/ErrorBanner';
import { goBackOrReset } from '../navigation/backNavigation';

type PreferenceKey = keyof NotificationPreferences;

interface PreferenceGroup {
  key: string;
  title: string;
  subtitle: string;
  fields: PreferenceKey[];
}

const GROUPS: PreferenceGroup[] = [
  {
    key: 'social',
    title: 'Social',
    subtitle: 'Follows, comments, and kudos',
    fields: ['socialActivity', 'newFollower', 'followCreated', 'commentCreated', 'kudosCreated'],
  },
  {
    key: 'rides',
    title: 'Ride status',
    subtitle: 'Completed, finalized, and failed ride updates',
    fields: ['rideUpdates', 'rideCompleted', 'rideFinalized', 'rideFailed'],
  },
  {
    key: 'proof',
    title: 'Rides and standings',
    subtitle: 'Ride verification, leaderboards, KOM, and Local Legend updates',
    fields: [
      'proofUpdated',
      'settlementFinalized',
      'leaderboardUpdates',
      'leaderboardEntered',
      'leaderboardBumped',
      'rankChanged',
      'recordRankMoved',
      'komAchieved',
      'localLegendMoved',
    ],
  },
  {
    key: 'payouts',
    title: 'Payouts',
    subtitle: 'CAL, DUNG, deposits, and Local Legend updates',
    fields: ['payoutAlerts', 'payoutReceived', 'stakePayout', 'legendPayout', 'stakingReward'],
  },
  {
    key: 'security',
    title: 'Security and systems',
    subtitle: 'New devices, sessions, Strava, connected apps, and announcements',
    fields: [
      'securityAlerts',
      'systemAnnouncements',
      'loginNewDevice',
      'sessionRevoked',
      'stravaRevoked',
      'connectedAppAlerts',
    ],
  },
];

function groupEnabled(prefs: NotificationPreferences, group: PreferenceGroup): boolean {
  return group.fields.every((field) => prefs[field] !== false);
}

export default function NotificationPreferencesScreen() {
  const navigation = useNavigation();
  const [prefs, setPrefs] = useState<NotificationPreferences | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setPrefs(await api.getNotificationPreferences());
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
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const rows = useMemo(() => {
    if (!prefs) return [];
    return GROUPS.map((group) => ({
      ...group,
      enabled: groupEnabled(prefs, group),
    }));
  }, [prefs]);

  const updateGroup = useCallback(async (group: PreferenceGroup, enabled: boolean) => {
    if (!prefs || savingKey) return;
    const previous = prefs;
    const next = { ...prefs };
    group.fields.forEach((field) => {
      next[field] = enabled;
    });
    setPrefs(next);
    setSavingKey(group.key);
    try {
      setPrefs(await api.updateNotificationPreferences(next));
    } catch (err) {
      setPrefs(previous);
      if (err instanceof ApiError) setError(err);
      else Sentry.captureException(err);
    } finally {
      setSavingKey(null);
    }
  }, [prefs, savingKey]);

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <ScrollView contentContainerStyle={styles.scroll}>
        <DetailHeader
          backLabel="Profile"
          title="Notifications"
          subtitle="Choose which app events can interrupt you"
          onBack={() => goBackOrReset(navigation, 'Profile')}
        />

        {error ? (
          <ErrorBanner
            message={error.retryable ? 'Connection issue' : 'Unable to save alerts'}
            onRetry={error.retryable ? load : undefined}
            onDismiss={() => setError(null)}
          />
        ) : null}

        {loading || !prefs ? (
          <View style={styles.center}>
            <ActivityIndicator size="large" color="#e5e5e5" />
          </View>
        ) : (
          <DetailModule title="Alert groups" subtitle="In-app preferences for the notification inbox">
            {rows.map((group, index) => (
              <View
                key={group.key}
                style={[styles.row, index > 0 && styles.rowDivider]}
              >
                <View style={styles.rowCopy}>
                  <Text style={styles.rowTitle}>{group.title}</Text>
                  <Text style={styles.rowSubtitle}>{group.subtitle}</Text>
                  {savingKey === group.key ? <Text style={styles.savingText}>Saving...</Text> : null}
                </View>
                <Switch
                  value={group.enabled}
                  disabled={!!savingKey}
                  onValueChange={(value) => updateGroup(group, value)}
                  trackColor={{ false: '#333333', true: '#6d5a1d' }}
                  thumbColor={group.enabled ? '#c4a035' : '#8a8a8a'}
                />
              </View>
            ))}
          </DetailModule>
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
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 16,
    paddingVertical: 13,
  },
  rowDivider: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: '#2a2a2a',
  },
  rowCopy: {
    flex: 1,
    minWidth: 0,
  },
  rowTitle: {
    color: '#ededed',
    fontSize: 15,
    fontWeight: '700',
  },
  rowSubtitle: {
    color: '#8d8d8d',
    fontSize: 12,
    lineHeight: 17,
    marginTop: 4,
  },
  savingText: {
    color: '#c4a035',
    fontSize: 11,
    fontWeight: '700',
    marginTop: 5,
  },
});
