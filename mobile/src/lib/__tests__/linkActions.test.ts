import { Alert, Linking } from 'react-native';

import type { ResolvedLink } from '../api';
import {
  bestScanTarget,
  hasResolvedBoulderScanTarget,
  openResolvedProof,
  resolvedBoulderScanUrl,
} from '../linkActions';

const baseLink: ResolvedLink = {
  contractVersion: 'link.v1',
  status: 'resolved',
  target: { type: 'ride', id: 'ride-1' },
  webPath: '/rides/ride-1',
  canonicalUrl: 'https://boulderroller.app/rides/ride-1',
  appUrl: 'boulderroller://rides/ride-1',
  externalUrl: null,
  title: 'Ride',
  description: 'Ride on Boulder Roller.',
  access: { canView: true, reason: 'public', protocolPublic: true, requiresAuth: false },
  metadata: {},
  scanState: 'recorded',
  scanTargets: [],
  share: {
    title: 'Ride',
    text: 'Ride on Boulder Roller.',
    url: 'https://boulderroller.app/rides/ride-1',
  },
  openGraph: {
    title: 'Ride',
    text: 'Ride on Boulder Roller.',
    url: 'https://boulderroller.app/rides/ride-1',
    type: 'ride',
  },
};

describe('BoulderScan link actions', () => {
  beforeEach(() => {
    jest.restoreAllMocks();
  });

  test('prefers the most exact recorded scan target', () => {
    const link: ResolvedLink = {
      ...baseLink,
      scanTargets: [
        {
          contractVersion: 'scan.v1',
          type: 'wallet',
          id: 'wallet-1',
          state: 'recorded',
          label: 'Wallet account',
          url: 'https://scan.boulderroller.xyz/account/wallet-1',
          source: 'user.wallet',
        },
        {
          contractVersion: 'scan.v1',
          type: 'transaction',
          id: 'tx-1',
          state: 'recorded',
          label: 'Transaction',
          url: 'https://scan.boulderroller.xyz/tx/tx-1',
          source: 'ride.tx',
        },
      ],
    };

    expect(bestScanTarget(link)?.label).toBe('Transaction');
    expect(resolvedBoulderScanUrl(link)).toBe('https://scan.boulderroller.xyz/tx/tx-1');
    expect(hasResolvedBoulderScanTarget(link)).toBe(true);
  });

  test('does not treat app links or the scan root as a proof target', () => {
    expect(resolvedBoulderScanUrl(baseLink)).toBeNull();
    expect(resolvedBoulderScanUrl(baseLink, 'https://scan.boulderroller.xyz')).toBeNull();
    expect(hasResolvedBoulderScanTarget(baseLink)).toBe(false);
  });

  test('opens exact scan URLs and refuses generic fallbacks', async () => {
    const openUrlSpy = jest.spyOn(Linking, 'openURL').mockResolvedValue(undefined);
    const alertSpy = jest.spyOn(Alert, 'alert').mockImplementation(() => undefined);

    await openResolvedProof({
      ...baseLink,
      scanTargets: [
        {
          contractVersion: 'scan.v1',
          type: 'proof',
          id: 'proof-1',
          state: 'finalized',
          label: 'Ride proof',
          url: 'https://scan.boulderroller.xyz/proof/proof-1',
          source: 'ride.proof',
        },
      ],
    });

    expect(openUrlSpy).toHaveBeenCalledWith('https://scan.boulderroller.xyz/proof/proof-1');

    openUrlSpy.mockClear();
    await openResolvedProof(baseLink, 'https://scan.boulderroller.xyz');

    expect(openUrlSpy).not.toHaveBeenCalled();
    expect(alertSpy).toHaveBeenCalledWith('BoulderScan unavailable', 'No scan target yet.');
  });
});
