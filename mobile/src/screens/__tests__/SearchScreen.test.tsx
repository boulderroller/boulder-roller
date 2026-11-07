import React from 'react';
import { Linking } from 'react-native';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import SearchScreen from '../SearchScreen';

const mockGoBack = jest.fn();
const mockNavigate = jest.fn();

jest.mock('@expo/vector-icons/Feather', () => {
  const React = require('react');
  const { Text } = require('react-native');
  return function FeatherMock({ name }: { name: string }) {
    return React.createElement(Text, null, name);
  };
});

jest.mock('@react-native-async-storage/async-storage', () => ({
  getItem: jest.fn(),
  setItem: jest.fn(),
}));

jest.mock('@react-navigation/native', () => {
  const actual = jest.requireActual('@react-navigation/native');
  return {
    ...actual,
    useNavigation: () => ({
      navigate: mockNavigate,
      goBack: mockGoBack,
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
      this.retryable = type === 'network_error';
    }
  }

  return {
    ApiError: MockApiError,
    api: {
      getSearchSuggestions: jest.fn(),
      search: jest.fn(),
    },
  };
});

const { api } = jest.requireMock('../../lib/api') as {
  api: {
    getSearchSuggestions: jest.Mock;
    search: jest.Mock;
  };
};
const AsyncStorage = jest.requireMock('@react-native-async-storage/async-storage') as {
  getItem: jest.Mock;
  setItem: jest.Mock;
};

describe('SearchScreen', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.spyOn(Linking, 'openURL').mockResolvedValue(undefined);
    AsyncStorage.getItem.mockResolvedValue(null);
    AsyncStorage.setItem.mockResolvedValue(undefined);
    api.getSearchSuggestions.mockResolvedValue({
      contractVersion: 'search.v1',
      sections: [
        {
          id: 'popular_climbs',
          title: 'Popular climbs',
          results: [
            {
              contractVersion: 'search.v1',
              id: 'climb:142',
              type: 'climb',
              title: 'Manayunk Wall',
              subtitle: 'Climb · Philadelphia',
              target: { type: 'climb', id: '142' },
              webPath: '/climbs/142',
              source: 'backend',
              privacy: null,
              stats: [{ label: 'Grade', value: '8.9%' }],
              score: 90,
              matchedFields: ['name'],
              scanState: 'recorded',
              scanTargets: [],
              metadata: {},
            },
          ],
        },
      ],
    });
    api.search.mockResolvedValue({
      contractVersion: 'search.v1',
      query: 'manayunk',
      normalizedQuery: 'manayunk',
      type: 'all',
      hasMore: false,
      results: [
        {
          contractVersion: 'search.v1',
          id: 'climb:142',
          type: 'climb',
          title: 'Manayunk Wall',
          subtitle: 'Climb · Philadelphia',
          target: { type: 'climb', id: '142' },
          webPath: '/climbs/142',
          source: 'backend',
          privacy: null,
          stats: [{ label: 'Grade', value: '8.9%' }],
          score: 90,
          matchedFields: ['name'],
          scanState: 'recorded',
          scanTargets: [],
          metadata: {},
        },
      ],
    });
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  test('searches and opens app targets through canonical navigation', async () => {
    render(<SearchScreen />);

    expect(screen.getByPlaceholderText('Search rides, climbs, riders, accounts')).toBeTruthy();
    expect(screen.getByText('BoulderScan')).toBeTruthy();
    expect(screen.queryByText('Records')).toBeNull();
    expect(screen.queryByText('Proofs')).toBeNull();

    fireEvent.changeText(screen.getByTestId('search-input'), 'manayunk');

    await waitFor(() => {
      expect(api.search).toHaveBeenCalledWith({ q: 'manayunk', type: 'all', limit: 20 });
    });
    await waitFor(() => {
      expect(screen.getByText('Manayunk Wall')).toBeTruthy();
    });

    fireEvent.press(screen.getByTestId('search-result-climb:142'));

    expect(mockNavigate).toHaveBeenCalledWith('ClimbDetail', {
      climbId: '142',
      backLabel: 'Search',
    });
    expect(AsyncStorage.setItem).toHaveBeenCalledWith(
      'br:search:recent:v1',
      JSON.stringify(['manayunk']),
    );
  });

  test('loads recent searches and backend suggestions before typing', async () => {
    AsyncStorage.getItem.mockResolvedValueOnce(JSON.stringify(['hawi', 'manayunk']));

    render(<SearchScreen />);

    await waitFor(() => {
      expect(api.getSearchSuggestions).toHaveBeenCalledWith({ limit: 4 });
    });
    expect(await screen.findByText('Recent searches')).toBeTruthy();
    expect(screen.getByText('hawi')).toBeTruthy();
    expect(screen.getByText('Popular climbs')).toBeTruthy();

    fireEvent.press(screen.getByTestId('recent-search-hawi'));

    expect(screen.getByDisplayValue('hawi')).toBeTruthy();
  });

  test('opens rider results through public RiderDetail route', async () => {
    api.search.mockResolvedValueOnce({
      contractVersion: 'search.v1',
      query: 'tim',
      normalizedQuery: 'tim',
      type: 'all',
      hasMore: false,
      results: [
        {
          contractVersion: 'search.v1',
          id: 'rider:tim',
          type: 'rider',
          title: 'Tim',
          subtitle: 'Rider · @tim',
          target: { type: 'rider', id: 'tim' },
          webPath: '/riders/tim',
          source: 'backend',
          privacy: null,
          stats: [],
          score: 90,
          matchedFields: ['username'],
          scanState: 'recorded',
          scanTargets: [],
          image: { kind: 'avatar', url: null },
	          metadata: {
	            rider: {
	              contractVersion: 'public_rider_ref.v1',
	              id: 'user-tim',
	              username: 'tim',
	              displayName: 'Tim',
	              avatarUrl: null,
	              isPublic: true,
	              viewerRelationship: 'none',
	            },
	            userId: 'user-tim',
	          },
	        },
      ],
    });

    render(<SearchScreen />);

    fireEvent.changeText(screen.getByTestId('search-input'), 'tim');

    await waitFor(() => {
      expect(screen.getByText('Tim')).toBeTruthy();
    });

    fireEvent.press(screen.getByTestId('search-result-rider:tim'));

    expect(mockNavigate).toHaveBeenCalledWith('RiderDetail', {
      identifier: 'tim',
	      initialIdentity: {
	        contractVersion: 'public_rider_ref.v1',
	        id: 'user-tim',
	        username: 'tim',
	        displayName: 'Tim',
	        avatarUrl: null,
	        isPublic: true,
	        viewerRelationship: 'none',
	      },
      backLabel: 'Search',
    });
  });

  test('switches categories and opens scan targets externally', async () => {
    api.search.mockResolvedValueOnce({
      contractVersion: 'search.v1',
      query: 'sig',
      normalizedQuery: 'sig',
      type: 'proofs',
      hasMore: false,
      results: [
        {
          contractVersion: 'search.v1',
          id: 'scan_tx:sig',
          type: 'proof',
          title: 'BoulderScan transaction',
          subtitle: 'Protocol transaction',
          target: { type: 'scan_tx', id: 'sig' },
          webPath: '/scan/tx/sig',
          source: 'indexer',
          privacy: null,
          stats: [],
          score: 100,
          matchedFields: ['id'],
          scanState: 'recorded',
          scanTargets: [
            { type: 'wallet', id: 'wallet', state: 'recorded', label: 'Wallet', url: 'https://scan.boulderroller.xyz/account/wallet', source: 'scan.wallet' },
            { type: 'transaction', id: 'sig', state: 'recorded', label: 'Transaction', url: 'https://scan.boulderroller.xyz/tx/sig', source: 'scan_tx.direct' },
          ],
          metadata: {},
        },
        {
          contractVersion: 'search.v1',
          id: 'scan_account:account-1',
          type: 'proof',
          title: 'BoulderScan account',
          subtitle: 'Protocol account',
          target: { type: 'scan_account', id: 'account-1' },
          webPath: '/scan/account/account-1',
          source: 'indexer',
          privacy: null,
          stats: [],
          score: 90,
          matchedFields: ['id'],
          scanState: 'recorded',
          scanTargets: [
            { type: 'account', id: 'account-1', state: 'recorded', label: 'Account', url: 'https://scan.boulderroller.xyz/account/account-1', source: 'scan_account.direct' },
          ],
          metadata: {},
        },
      ],
    });

    render(<SearchScreen />);

    fireEvent.press(screen.getByTestId('search-category-proofs'));
    fireEvent.changeText(screen.getByTestId('search-input'), 'sig');

    await waitFor(() => {
      expect(api.search).toHaveBeenCalledWith({ q: 'sig', type: 'proofs', limit: 20 });
    });
    expect(screen.getAllByText('BoulderScan').length).toBeGreaterThan(0);
    expect((await screen.findAllByText('Transaction')).length).toBeGreaterThanOrEqual(1);
    expect((await screen.findAllByText('Account')).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Open in BoulderScan')).toHaveLength(2);
    fireEvent.press(await screen.findByTestId('search-result-scan_tx:sig'));

    expect(Linking.openURL).toHaveBeenCalledWith('https://scan.boulderroller.xyz/tx/sig');
  });
});
