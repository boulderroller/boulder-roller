import React from 'react';
import { Linking } from 'react-native';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import NotificationsScreen from '../NotificationsScreen';

const mockNavigate = jest.fn();
const mockGoBack = jest.fn();

jest.mock('@react-navigation/native', () => {
  const actual = jest.requireActual('@react-navigation/native');
  return {
    ...actual,
    useNavigation: () => ({
      navigate: mockNavigate,
      goBack: mockGoBack,
      reset: jest.fn(),
    }),
  };
});

jest.mock('../../lib/api', () => {
  class MockApiError extends Error {
    type: string;
    retryable: boolean;
    statusCode?: number;

    constructor(message: string, type = 'unknown', statusCode?: number) {
      super(message);
      this.name = 'ApiError';
      this.type = type;
      this.statusCode = statusCode;
      this.retryable = type === 'network_error' || type === 'timeout';
    }
  }

  return {
    ApiError: MockApiError,
    api: {
      getNotifications: jest.fn(),
      markNotificationRead: jest.fn(),
      markAllNotificationsRead: jest.fn(),
      resolveLink: jest.fn(),
      resolveLinkUrl: jest.fn(),
    },
  };
});

const { api } = jest.requireMock('../../lib/api') as {
  api: {
    getNotifications: jest.Mock;
    markNotificationRead: jest.Mock;
    markAllNotificationsRead: jest.Mock;
    resolveLink: jest.Mock;
    resolveLinkUrl: jest.Mock;
  };
};

describe('NotificationsScreen', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    api.markNotificationRead.mockResolvedValue(undefined);
    api.markAllNotificationsRead.mockResolvedValue(undefined);
  });

  test('opens direct BoulderScan scan targets when actionUrl is absent', async () => {
    const openUrlSpy = jest.spyOn(Linking, 'openURL').mockResolvedValue(undefined);
    api.getNotifications.mockResolvedValue({
      unreadCount: 1,
      notifications: [
        {
          contractVersion: 'notification.v1',
          id: 'notification-1',
          notificationType: 'proof_recorded',
          title: 'BoulderScan transaction',
          message: 'Your ride proof is recorded.',
          read: false,
          createdAt: '2026-05-02T12:00:00Z',
          target: { type: 'scan_tx', id: 'sig-123' },
          actionUrl: null,
        },
      ],
    });
    api.resolveLink.mockResolvedValue({
      contractVersion: 'link.v1',
      status: 'resolved',
      target: { type: 'scan_tx', id: 'sig-123' },
      webPath: '/scan/tx/sig-123',
      canonicalUrl: 'https://scan.boulderroller.xyz/tx/sig-123',
      appUrl: 'boulderroller://scan/tx/sig-123',
      externalUrl: null,
      title: 'BoulderScan transaction',
      description: 'Transaction on BoulderScan.',
      access: { canView: true, reason: 'public', protocolPublic: true, requiresAuth: false },
      metadata: {},
      scanState: 'recorded',
      scanTargets: [
        {
          contractVersion: 'scan.v1',
          type: 'transaction',
          id: 'sig-123',
          state: 'recorded',
          label: 'Transaction',
          url: 'https://scan.boulderroller.xyz/tx/sig-123',
          source: 'scan_tx.direct',
        },
      ],
      share: {
        title: 'BoulderScan transaction',
        text: 'Transaction on BoulderScan.',
        url: 'https://scan.boulderroller.xyz/tx/sig-123',
      },
      openGraph: {
        title: 'BoulderScan transaction',
        text: 'Transaction on BoulderScan.',
        url: 'https://scan.boulderroller.xyz/tx/sig-123',
        type: 'scan_tx',
      },
    });

    render(<NotificationsScreen />);

    expect(await screen.findByText('Transaction')).toBeTruthy();
    expect(screen.getByText('Open in BoulderScan.')).toBeTruthy();
    fireEvent.press(await screen.findByTestId('notification-notification-1'));

    await waitFor(() => {
      expect(api.markNotificationRead).toHaveBeenCalledWith('notification-1');
      expect(api.resolveLink).toHaveBeenCalledWith('scan_tx', 'sig-123');
      expect(openUrlSpy).toHaveBeenCalledWith('https://scan.boulderroller.xyz/tx/sig-123');
    });
  });

  test('opens rider notification targets through public RiderDetail route', async () => {
    api.getNotifications.mockResolvedValue({
      unreadCount: 1,
      notifications: [
        {
          contractVersion: 'notification.v1',
          id: 'notification-rider-1',
          notificationType: 'follow_created',
          title: 'New follower',
          message: 'Tim followed you.',
          read: false,
          createdAt: '2026-05-02T12:00:00Z',
          target: { type: 'user', id: 'user-1' },
          actor: {
            id: 'user-1',
	            username: 'tim',
	            displayName: 'Tim',
	            avatarUrl: null,
	          },
        },
      ],
    });

    render(<NotificationsScreen />);

    fireEvent.press(await screen.findByTestId('notification-notification-rider-1'));

    await waitFor(() => {
      expect(api.markNotificationRead).toHaveBeenCalledWith('notification-rider-1');
      expect(mockNavigate).toHaveBeenCalledWith('RiderDetail', {
        identifier: 'tim',
        initialIdentity: {
          id: 'user-1',
          username: 'tim',
          displayName: 'Tim',
          avatarUrl: null,
          isPublic: undefined,
        },
        backLabel: 'Alerts',
      });
    });
  });

  test('opens report notifications through My Reports', async () => {
    api.getNotifications.mockResolvedValue({
      unreadCount: 1,
      notifications: [
        {
          contractVersion: 'notification.v1',
          id: 'notification-report-1',
          notificationType: 'report_resolved',
          title: 'Report reviewed',
          message: 'Your report was reviewed.',
          read: false,
          createdAt: '2026-05-02T12:00:00Z',
          target: { type: 'report', id: 'report-1' },
          primaryAction: 'open_report',
        },
      ],
    });

    render(<NotificationsScreen />);

    fireEvent.press(await screen.findByTestId('notification-notification-report-1'));

    await waitFor(() => {
      expect(api.markNotificationRead).toHaveBeenCalledWith('notification-report-1');
      expect(mockNavigate).toHaveBeenCalledWith('MyReports');
    });
  });
});
