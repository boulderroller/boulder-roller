import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Linking,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import * as Sentry from '@sentry/react-native';

import { api, ApiError, type AppNotification } from '../lib/api';
import DetailHeader from '../components/detail/DetailHeader';
import DetailModule from '../components/detail/DetailModule';
import { ErrorBanner } from '../components/ErrorBanner';
import { openResolvedProof as openResolvedBoulderScanTarget } from '../lib/linkActions';
import { goBackOrReset } from '../navigation/backNavigation';
import { riderProfileRouteParamsFromIdentifier } from '../lib/riderNavigation';
import { isBoulderScanTargetType, targetFromNotification } from '../lib/targetActions';

function formatWhen(iso?: string): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleDateString();
}

function notificationTitle(notification: AppNotification): string {
  const target = targetFromNotification(notification);
  if (target?.type === 'scan_account') return 'Account';
  if (target?.type === 'scan_tx') return 'Transaction';
  if (target && isBoulderScanTargetType(target.type)) return 'BoulderScan';
  return notification.title;
}

function notificationMessage(notification: AppNotification): string {
  const target = targetFromNotification(notification);
  if (target && isBoulderScanTargetType(target.type)) return 'Open in BoulderScan.';
  return notification.message;
}

export default function NotificationsScreen() {
  const navigation = useNavigation();
  const [notifications, setNotifications] = useState<AppNotification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const response = await api.getNotifications({ limit: 50 });
      setNotifications(response.notifications);
      setUnreadCount(response.unreadCount);
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

  const openTarget = useCallback(async (notification: AppNotification) => {
    const target = targetFromNotification(notification);
    if (target?.id) {
      const nav = navigation as {
        navigate: (screen: string, params?: object) => void;
      };
      if (target.type === 'ride') {
        nav.navigate('RideDetail', { serverRideId: target.id, backLabel: 'Alerts' });
        return;
      }
      if (target.type === 'rider') {
        const route = riderProfileRouteParamsFromIdentifier(target.id, notification.actor, { backLabel: 'Alerts' });
        if (route) nav.navigate('RiderDetail', route);
        return;
      }
      if (target.type === 'climb' || target.type === 'record_board' || target.type === 'local_legend') {
        nav.navigate('ClimbDetail', { climbId: target.id, backLabel: 'Alerts' });
        return;
      }
      if (target.type === 'report') {
        nav.navigate('MyReports');
        return;
      }
      if (isBoulderScanTargetType(target.type)) {
        const resolved = await api.resolveLink(target.type, target.id);
        await openResolvedBoulderScanTarget(resolved, notification.actionUrl ?? resolved.canonicalUrl);
        return;
      }
      if (target.type === 'feed_event') {
        return;
      }
    }

    if (notification.actionUrl) {
      try {
        const resolved = await api.resolveLinkUrl(notification.actionUrl);
        const resolvedTarget = resolved.target;
        if (!resolvedTarget.id) return;
        const nav = navigation as {
          navigate: (screen: string, params?: object) => void;
        };
        if (resolvedTarget.type === 'ride') {
          nav.navigate('RideDetail', { serverRideId: resolvedTarget.id, backLabel: 'Alerts' });
        } else if (resolvedTarget.type === 'rider') {
          const route = riderProfileRouteParamsFromIdentifier(resolvedTarget.id, null, { backLabel: 'Alerts' });
          if (route) nav.navigate('RiderDetail', route);
        } else if (
          resolvedTarget.type === 'climb'
          || resolvedTarget.type === 'record_board'
          || resolvedTarget.type === 'local_legend'
        ) {
          nav.navigate('ClimbDetail', { climbId: resolvedTarget.id, backLabel: 'Alerts' });
        } else if (resolvedTarget.type === 'report') {
          nav.navigate('MyReports');
        } else if (isBoulderScanTargetType(resolvedTarget.type)) {
          await openResolvedBoulderScanTarget(resolved, notification.actionUrl);
        } else {
          await Linking.openURL(resolved.canonicalUrl);
        }
      } catch {
        await Linking.openURL(notification.actionUrl);
      }
    }
  }, [navigation]);

  const handlePress = useCallback(async (notification: AppNotification) => {
    setBusyId(notification.id);
    try {
      if (!notification.read) {
        await api.markNotificationRead(notification.id);
        setNotifications((current) => current.map((item) => (
          item.id === notification.id ? { ...item, read: true, readAt: new Date().toISOString() } : item
        )));
        setUnreadCount((current) => Math.max(0, current - 1));
      }
      await openTarget(notification);
    } catch (err) {
      Sentry.captureException(err);
    } finally {
      setBusyId(null);
    }
  }, [openTarget]);

  const handleReadAll = useCallback(async () => {
    setBusyId('all');
    try {
      await api.markAllNotificationsRead();
      setNotifications((current) => current.map((item) => ({
        ...item,
        read: true,
        readAt: item.readAt ?? new Date().toISOString(),
      })));
      setUnreadCount(0);
    } catch (err) {
      Sentry.captureException(err);
    } finally {
      setBusyId(null);
    }
  }, []);

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <ScrollView contentContainerStyle={styles.scroll}>
        <DetailHeader
          backLabel="Back"
          title="Alerts"
          subtitle={`${unreadCount} unread`}
          onBack={() => goBackOrReset(navigation, 'Home')}
        />

        {error ? (
          <ErrorBanner
            message={error.retryable ? 'Connection issue' : 'Unable to load alerts'}
            onRetry={error.retryable ? load : undefined}
            onDismiss={() => setError(null)}
          />
        ) : null}

        {loading ? (
          <View style={styles.center}>
            <ActivityIndicator size="large" color="#e5e5e5" />
          </View>
        ) : (
          <DetailModule
            title="Notifications"
            subtitle="Ride, social, BoulderScan, and account updates"
            ctaLabel={unreadCount > 0 ? 'Mark all read' : undefined}
            onPressCta={unreadCount > 0 ? handleReadAll : undefined}
          >
            {notifications.length > 0 ? (
              notifications.map((notification) => (
                <TouchableOpacity
                  key={notification.id}
                  style={[styles.notificationRow, !notification.read && styles.notificationUnread]}
                  onPress={() => handlePress(notification)}
                  disabled={busyId === notification.id || busyId === 'all'}
                  activeOpacity={0.84}
                  testID={`notification-${notification.id}`}
                >
                  <View style={styles.notificationCopy}>
                    <Text style={styles.notificationTitle}>{notificationTitle(notification)}</Text>
                    <Text style={styles.notificationMessage}>{notificationMessage(notification)}</Text>
                    <Text style={styles.notificationMeta}>
                      {formatWhen(notification.occurredAt ?? notification.createdAt)}
                    </Text>
                  </View>
                  {!notification.read ? <View style={styles.unreadDot} /> : null}
                </TouchableOpacity>
              ))
            ) : (
              <Text style={styles.emptyText}>No alerts yet.</Text>
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
  notificationRow: {
    flexDirection: 'row',
    gap: 12,
    paddingVertical: 13,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#2a2a2a',
  },
  notificationUnread: {
    backgroundColor: '#171407',
    marginHorizontal: -10,
    paddingHorizontal: 10,
  },
  notificationCopy: {
    flex: 1,
    minWidth: 0,
  },
  notificationTitle: {
    color: '#ededed',
    fontSize: 14,
    fontWeight: '700',
  },
  notificationMessage: {
    color: '#a7a7a7',
    fontSize: 13,
    lineHeight: 18,
    marginTop: 4,
  },
  notificationMeta: {
    color: '#6f6f6f',
    fontSize: 11,
    marginTop: 6,
  },
  unreadDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: '#c4a035',
    marginTop: 5,
  },
  emptyText: {
    color: '#8a8a8a',
    fontSize: 14,
    lineHeight: 20,
  },
});
