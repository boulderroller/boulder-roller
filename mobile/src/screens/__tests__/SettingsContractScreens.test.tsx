import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import MyReportsScreen from '../MyReportsScreen';
import PrivacySettingsScreen from '../PrivacySettingsScreen';

const mockNavigate = jest.fn();

jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({
    navigate: mockNavigate,
    goBack: jest.fn(),
    reset: jest.fn(),
  }),
}));

jest.mock('../../lib/api', () => {
  class MockApiError extends Error {
    type: string;
    retryable: boolean;
    status?: number;

    constructor(message: string, type = 'unknown', status?: number) {
      super(message);
      this.name = 'ApiError';
      this.type = type;
      this.status = status;
      this.retryable = type === 'network' || type === 'timeout';
    }
  }

  return {
    ApiError: MockApiError,
    api: {
      getMySocialReports: jest.fn(),
      getPrivacySettings: jest.fn(),
      updatePrivacySettings: jest.fn(),
    },
  };
});

const { api, ApiError } = jest.requireMock('../../lib/api') as {
  ApiError: new (message: string, type?: string, status?: number) => Error;
  api: {
    getMySocialReports: jest.Mock;
    getPrivacySettings: jest.Mock;
    updatePrivacySettings: jest.Mock;
  };
};

describe('settings contract screens', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('privacy settings shows an honest unavailable state when the live contract is missing', async () => {
    api.getPrivacySettings.mockRejectedValue(new ApiError('Not found', 'unknown', 404));

    render(<PrivacySettingsScreen />);

    await waitFor(() => {
      expect(screen.getByText('Privacy unavailable')).toBeTruthy();
    });

    expect(screen.getByText('Unable to load privacy')).toBeTruthy();
    expect(screen.queryByText('Profile visibility')).toBeNull();
  });

  test('my reports does not show a false empty state when report history fails to load', async () => {
    api.getMySocialReports.mockRejectedValue(new ApiError('Not found', 'unknown', 404));

    render(<MyReportsScreen />);

    await waitFor(() => {
      expect(screen.getByText('Reports unavailable')).toBeTruthy();
    });

    expect(screen.queryByText('No reports submitted.')).toBeNull();
    expect(screen.queryByText('0 total')).toBeNull();
  });

  test('my reports opens user reports through public RiderDetail route', async () => {
    api.getMySocialReports.mockResolvedValue({
      reports: [
        {
          id: 'report-1',
          reporterId: 'viewer-1',
          targetType: 'user',
          targetId: 'user-2',
          reason: 'other',
          status: 'open',
          createdAt: '2026-05-02T12:00:00Z',
        },
      ],
      count: 1,
      limit: 50,
      offset: 0,
    });

    render(<MyReportsScreen />);

    await waitFor(() => {
      expect(screen.getByTestId('my-report-report-1')).toBeTruthy();
    });

    fireEvent.press(screen.getByTestId('my-report-report-1'));

    expect(mockNavigate).toHaveBeenCalledWith('RiderDetail', {
      identifier: 'user-2',
      initialIdentity: {
        id: null,
        username: null,
        displayName: null,
        avatarUrl: null,
        isPublic: undefined,
      },
      backLabel: 'Reports',
    });
  });

  test('my reports opens ride media reports through parent RideDetail route', async () => {
    api.getMySocialReports.mockResolvedValue({
      reports: [
        {
          id: 'report-media-1',
          reporterId: 'viewer-1',
          targetType: 'ride_media',
          targetId: 'photo-1',
          target: {
            type: 'ride_media',
            id: 'photo-1',
            metadata: { rideId: 'ride-1', mediaId: 'photo-1' },
          },
          reason: 'privacy',
          status: 'open',
          createdAt: '2026-05-02T12:00:00Z',
        },
      ],
      count: 1,
      limit: 50,
      offset: 0,
    });

    render(<MyReportsScreen />);

    await waitFor(() => {
      expect(screen.getByTestId('my-report-report-media-1')).toBeTruthy();
    });

    fireEvent.press(screen.getByTestId('my-report-report-media-1'));

    expect(mockNavigate).toHaveBeenCalledWith('RideDetail', {
      serverRideId: 'ride-1',
      backLabel: 'Reports',
    });
  });
});
