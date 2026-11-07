import React from 'react';
import { Alert } from 'react-native';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import EditProfileScreen from '../EditProfileScreen';

const mockGoBack = jest.fn();

jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({
    goBack: mockGoBack,
    reset: jest.fn(),
  }),
}));

jest.mock('expo-image-picker', () => ({
  MediaTypeOptions: { Images: 'Images' },
  requestMediaLibraryPermissionsAsync: jest.fn(),
  launchImageLibraryAsync: jest.fn(),
}));

jest.mock('../../lib/imageUpload', () => ({
  prepareNativeImageUpload: jest.fn(),
}));

jest.mock('../../lib/api', () => {
  class MockApiError extends Error {
    type: string;
    retryable: boolean;
    statusCode?: number;

    constructor(message: string, type = 'unknown', statusCode?: number) {
      super(message);
      this.name = 'ApiError';
      this.type = type;
      this.retryable = type === 'network_error';
      this.statusCode = statusCode;
    }
  }

  return {
    ApiError: MockApiError,
    api: {
      getMe: jest.fn(),
      updateProfile: jest.fn(),
      uploadAvatar: jest.fn(),
      deleteAvatar: jest.fn(),
    },
  };
});

const ImagePicker = jest.requireMock('expo-image-picker') as {
  requestMediaLibraryPermissionsAsync: jest.Mock;
  launchImageLibraryAsync: jest.Mock;
};
const { prepareNativeImageUpload } = jest.requireMock('../../lib/imageUpload') as {
  prepareNativeImageUpload: jest.Mock;
};
const { api } = jest.requireMock('../../lib/api') as {
  api: {
    getMe: jest.Mock;
    updateProfile: jest.Mock;
    uploadAvatar: jest.Mock;
    deleteAvatar: jest.Mock;
  };
};

const baseUser = {
  id: 'user-1',
  wallet: 'wallet-1',
  username: 'tim',
  displayName: 'Tim Trail',
  bio: 'Climbs dirt.',
  avatarUrl: null,
  isPublic: true,
  createdAt: '2026-05-01T00:00:00Z',
  totalRides: 3,
  totalTss: 120,
};

describe('EditProfileScreen avatar management', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.spyOn(Alert, 'alert').mockImplementation(() => undefined);
    api.getMe.mockResolvedValue(baseUser);
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  test('uploads a prepared avatar through the backend-backed avatar API', async () => {
    ImagePicker.requestMediaLibraryPermissionsAsync.mockResolvedValue({ granted: true });
    ImagePicker.launchImageLibraryAsync.mockResolvedValue({
      canceled: false,
      assets: [{ uri: 'file:///picked.jpg', width: 1600, height: 1200 }],
    });
    prepareNativeImageUpload.mockResolvedValue({
      uri: 'file:///prepared.jpg',
      name: 'rider-avatar.jpg',
      mimeType: 'image/jpeg',
      size: 1200,
    });
    api.uploadAvatar.mockResolvedValue({
      ...baseUser,
      avatarUrl: 'https://example.test/avatar.jpg',
    });

    render(<EditProfileScreen />);

    await waitFor(() => {
      expect(screen.getByText('Not set')).toBeTruthy();
    });

    fireEvent.press(screen.getByTestId('edit-profile-avatar-change'));

    await waitFor(() => {
      expect(api.uploadAvatar).toHaveBeenCalledWith({
        uri: 'file:///prepared.jpg',
        name: 'rider-avatar.jpg',
        mimeType: 'image/jpeg',
        size: 1200,
      });
    });
    expect(prepareNativeImageUpload).toHaveBeenCalledWith(
      { uri: 'file:///picked.jpg', width: 1600, height: 1200 },
      { fileNamePrefix: 'rider-avatar', maxDimension: 1024, maxBytes: 2 * 1024 * 1024 },
    );
    await waitFor(() => {
      expect(screen.getByText('Synced')).toBeTruthy();
    });
  });

  test('removes an existing avatar through the avatar delete API', async () => {
    api.getMe.mockResolvedValue({
      ...baseUser,
      avatarUrl: 'https://example.test/avatar.jpg',
    });
    api.deleteAvatar.mockResolvedValue(baseUser);

    render(<EditProfileScreen />);

    await waitFor(() => {
      expect(screen.getByText('Synced')).toBeTruthy();
    });

    fireEvent.press(screen.getByTestId('edit-profile-avatar-remove'));

    await waitFor(() => {
      expect(api.deleteAvatar).toHaveBeenCalled();
      expect(screen.getByText('Not set')).toBeTruthy();
    });
  });
});
