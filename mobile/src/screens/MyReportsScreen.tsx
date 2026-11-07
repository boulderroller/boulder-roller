import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import * as Sentry from '@sentry/react-native';

import { api, ApiError, type SocialReport } from '../lib/api';
import DetailHeader from '../components/detail/DetailHeader';
import DetailModule from '../components/detail/DetailModule';
import { ErrorBanner } from '../components/ErrorBanner';
import { goBackOrReset } from '../navigation/backNavigation';
import { riderProfileRouteParamsFromIdentifier } from '../lib/riderNavigation';
import { targetFromReport } from '../lib/targetActions';

function formatWhen(iso?: string | null): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleDateString();
}

export default function MyReportsScreen() {
  const navigation = useNavigation();
  const [reports, setReports] = useState<SocialReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const load = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const response = await api.getMySocialReports();
      setReports(response.reports);
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

  const handleReportPress = useCallback((report: SocialReport) => {
    const target = targetFromReport(report);
    if (!target?.id) return;
    const nav = navigation as {
      navigate: (screen: string, params?: object) => void;
    };
    if (target.type === 'ride') {
      nav.navigate('RideDetail', { serverRideId: target.id, backLabel: 'Reports' });
    } else if (target.type === 'rider') {
      const route = riderProfileRouteParamsFromIdentifier(target.id, null, { backLabel: 'Reports' });
      if (route) nav.navigate('RiderDetail', route);
    }
  }, [navigation]);

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <ScrollView contentContainerStyle={styles.scroll}>
        <DetailHeader
          backLabel="Profile"
          title="Reports"
          subtitle="Status of content you sent for review"
          onBack={() => goBackOrReset(navigation, 'Profile')}
        />

        {error && reports.length > 0 ? (
          <ErrorBanner
            message={error.retryable ? 'Connection issue' : 'Unable to load reports'}
            onRetry={error.retryable ? load : undefined}
            onDismiss={() => setError(null)}
          />
        ) : null}

        {loading ? (
          <View style={styles.center}>
            <ActivityIndicator size="large" color="#e5e5e5" />
          </View>
        ) : error && reports.length === 0 ? (
          <DetailModule
            title="Reports unavailable"
            subtitle="Your submitted report history could not be loaded"
            ctaLabel="Retry"
            onPressCta={load}
          >
            <Text style={styles.helpText}>
              Report history stays hidden until the app can confirm the live moderation contract.
            </Text>
          </DetailModule>
        ) : (
          <DetailModule title="Submitted reports" subtitle={`${reports.length} total`}>
            {reports.length > 0 ? (
              reports.map((report) => (
                <TouchableOpacity
                  key={report.id}
                  style={styles.reportRow}
                  onPress={() => handleReportPress(report)}
                  activeOpacity={0.84}
                  testID={`my-report-${report.id}`}
                >
                  <View style={styles.reportCopy}>
                    <Text style={styles.reportTitle}>
                      {report.targetType} • {report.reason}
                    </Text>
                    <Text style={styles.reportMeta}>
                      {report.status} • {formatWhen(report.createdAt)}
                    </Text>
                    {report.reporterMessage || report.reporterOutcome ? (
                      <Text style={styles.reportMessage}>
                        {report.reporterMessage ?? report.reporterOutcome}
                      </Text>
                    ) : null}
                  </View>
                  <Text style={styles.chevron}>›</Text>
                </TouchableOpacity>
              ))
            ) : (
              <Text style={styles.emptyText}>No reports submitted.</Text>
            )}
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
  reportRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingVertical: 13,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#2a2a2a',
  },
  reportCopy: {
    flex: 1,
    minWidth: 0,
  },
  reportTitle: {
    color: '#ededed',
    fontSize: 14,
    fontWeight: '700',
    textTransform: 'capitalize',
  },
  reportMeta: {
    color: '#8d8d8d',
    fontSize: 12,
    marginTop: 4,
    textTransform: 'capitalize',
  },
  reportMessage: {
    color: '#b4b4b4',
    fontSize: 13,
    lineHeight: 18,
    marginTop: 6,
  },
  chevron: {
    color: '#666666',
    fontSize: 18,
  },
  emptyText: {
    color: '#8a8a8a',
    fontSize: 14,
    lineHeight: 20,
  },
  helpText: {
    color: '#8d8d8d',
    fontSize: 13,
    lineHeight: 19,
  },
});
