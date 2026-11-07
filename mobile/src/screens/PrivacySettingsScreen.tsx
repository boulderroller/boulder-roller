import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import * as Sentry from '@sentry/react-native';

import { api, ApiError, type PrivacySettings, type RideVisibility } from '../lib/api';
import DetailHeader from '../components/detail/DetailHeader';
import DetailModule from '../components/detail/DetailModule';
import SegmentedControl from '../components/surfaces/SegmentedControl';
import { ErrorBanner } from '../components/ErrorBanner';
import { goBackOrReset } from '../navigation/backNavigation';

const PROFILE_ITEMS = [
  { key: 'public', label: 'Public' },
  { key: 'private', label: 'Private' },
];

const RIDE_ITEMS = [
  { key: 'public', label: 'Public' },
  { key: 'followers', label: 'Followers' },
  { key: 'private', label: 'Private' },
];

export default function PrivacySettingsScreen() {
  const navigation = useNavigation();
  const [settings, setSettings] = useState<PrivacySettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const load = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      setSettings(await api.getPrivacySettings());
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

  const updateProfileVisibility = useCallback(async (key: string) => {
    if (!settings || saving) return;
    const next = key === 'private' ? 'private' : 'public';
    const previous = settings;
    setSettings({ ...settings, profileVisibility: next });
    setSaving(true);
    try {
      setSettings(await api.updatePrivacySettings({ isPublic: next === 'public' }));
    } catch (err) {
      setSettings(previous);
      if (err instanceof ApiError) setError(err);
      else Sentry.captureException(err);
    } finally {
      setSaving(false);
    }
  }, [saving, settings]);

  const updateDefaultRideVisibility = useCallback(async (key: string) => {
    if (!settings || saving) return;
    const next = key as RideVisibility;
    const previous = settings;
    setSettings({ ...settings, defaultRideVisibility: next });
    setSaving(true);
    try {
      setSettings(await api.updatePrivacySettings({ defaultRideVisibility: next }));
    } catch (err) {
      setSettings(previous);
      if (err instanceof ApiError) setError(err);
      else Sentry.captureException(err);
    } finally {
      setSaving(false);
    }
  }, [saving, settings]);

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <ScrollView contentContainerStyle={styles.scroll}>
        <DetailHeader
          backLabel="Profile"
          title="Privacy"
          subtitle="Quiet defaults for future rides"
          onBack={() => goBackOrReset(navigation, 'Profile')}
        />

        {error ? (
          <ErrorBanner
            message={settings ? 'Unable to save privacy' : 'Unable to load privacy'}
            onRetry={!settings || error.retryable ? load : undefined}
            onDismiss={() => setError(null)}
          />
        ) : null}

        {loading ? (
          <View style={styles.center}>
            <ActivityIndicator size="large" color="#e5e5e5" />
          </View>
        ) : !settings ? (
          <DetailModule
            title="Privacy unavailable"
            subtitle="Your saved defaults could not be loaded"
            ctaLabel="Retry"
            onPressCta={load}
          >
            <Text style={styles.helpText}>
              Privacy controls stay hidden until the app can confirm the live backend contract.
            </Text>
          </DetailModule>
        ) : (
          <>
            <DetailModule title="Profile visibility" subtitle="Controls who can open your rider profile">
              <SegmentedControl
                items={PROFILE_ITEMS}
                activeKey={settings.profileVisibility}
                onChange={updateProfileVisibility}
              />
              <Text style={styles.helpText}>
                Private profiles hide public rider details, cards, and ride history.
              </Text>
            </DetailModule>

            <DetailModule title="Default ride visibility" subtitle="New rides start here unless you override them">
              <SegmentedControl
                items={RIDE_ITEMS}
                activeKey={settings.defaultRideVisibility}
                onChange={updateDefaultRideVisibility}
              />
              <Text style={styles.helpText}>
                Protocol facts can stay public while rider-facing GPS and profile details follow this setting.
              </Text>
            </DetailModule>

            {saving ? <Text style={styles.savingText}>Saving...</Text> : null}
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
  helpText: {
    color: '#8d8d8d',
    fontSize: 13,
    lineHeight: 19,
  },
  savingText: {
    color: '#c4a035',
    fontSize: 12,
    fontWeight: '700',
    marginLeft: 4,
  },
});
