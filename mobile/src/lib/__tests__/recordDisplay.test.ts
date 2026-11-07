import type { RideStatus, ScanTarget } from '../api';
import {
  countedCalLabel,
  recordStateLabelFromScanState,
  recordTargetLabel,
  rideRecordRows,
  rideRecordStatusLabel,
  rideRecordSubtitle,
} from '../recordDisplay';

const attestedStatus: RideStatus = {
  rideId: 'ride-1',
  status: 'completed',
  errorMessage: null,
  attestationStatus: 'attested',
  finalizedAt: '2026-05-14T12:00:00Z',
  rideHashHex: 'abcdef1234567890',
  attestationCommitmentHex: '0123456789abcdef',
  earnings: {
    contractVersion: 'client.v1',
    truthSource: 'projected',
    rideId: 'ride-1',
    calEarned: 42.4,
    finalizedAt: '2026-05-14T12:00:00Z',
  },
};

describe('recordDisplay', () => {
  test('summarizes counted rides with quiet source detail', () => {
    expect(rideRecordStatusLabel(attestedStatus, true)).toBe('Counted');
    expect(countedCalLabel(attestedStatus)).toBe('+42');
    expect(rideRecordRows(attestedStatus)).toEqual([
      ['Status', 'Counted'],
      ['Counted CAL', '+42'],
      ['Ride file', 'abcdef1234...'],
      ['Chain', '0123456789...'],
    ]);
  });

  test('keeps a finalized held ride verified without calling its CAL counted', () => {
    const held = {
      ...attestedStatus,
      calEarned: null,
      earnings: null,
      effortPolicy: {
        rewardPolicy: 'threshold_provisional_hold_v1',
        thresholdEconomyState: 'held' as const,
      },
    };

    expect(rideRecordStatusLabel(held, true)).toBe('Verified');
    expect(rideRecordSubtitle(held)).toBe('Held — clears when your Threshold is established.');
    expect(rideRecordRows(held)[1]).toEqual(['CAL', 'Held']);
  });

  test('keeps BoulderScan states rider-facing without overstating availability', () => {
    expect(recordStateLabelFromScanState('finalized')).toBe('BoulderScan ready');
    expect(recordStateLabelFromScanState('pending')).toBe('BoulderScan pending');
    expect(recordStateLabelFromScanState('off_chain_only')).toBe('App only');
    expect(recordStateLabelFromScanState('missing')).toBe('Not in BoulderScan yet');
    expect(recordStateLabelFromScanState('failed')).toBe('BoulderScan unavailable');
    expect(recordStateLabelFromScanState('private')).toBe('Private');
  });

  test('maps protocol targets to plain BoulderScan labels', () => {
    expect(recordTargetLabel({
      contractVersion: 'scan.v1',
      type: 'transaction',
      id: 'tx-1',
      state: 'finalized',
      label: 'Transaction',
      url: 'https://scan.boulderroller.xyz/tx/tx-1',
      source: 'test',
    })).toBe('Transaction');

    expect(recordTargetLabel({
      contractVersion: 'scan.v1',
      type: 'vault',
      id: 'vault-1',
      state: 'recorded',
      label: 'Vault',
      url: 'https://scan.boulderroller.xyz/vault/vault-1',
      source: 'test',
    } satisfies ScanTarget)).toBe('Vault');

    expect(recordTargetLabel({
      contractVersion: 'scan.v1',
      type: 'account',
      id: 'account-1',
      state: 'recorded',
      label: 'Ride attestation account',
      url: 'https://scan.boulderroller.xyz/account/account-1',
      source: 'test',
    } satisfies ScanTarget)).toBe('Account');

    expect(recordTargetLabel({
      contractVersion: 'scan.v1',
      type: 'proof',
      id: 'proof-1',
      state: 'recorded',
      label: 'Ride proof',
      url: 'https://scan.boulderroller.xyz/proof/proof-1',
      source: 'test',
    } satisfies ScanTarget)).toBe('Verification');
  });
});
