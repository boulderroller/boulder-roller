import { derivePostRideCascade } from '../postRideCascade';
import type { RideStatus } from '../api';

function statusWith(overrides: Partial<RideStatus>): RideStatus {
  return {
    rideId: 'ride-1',
    status: 'processing',
    errorMessage: null,
    ...overrides,
  };
}

describe('derivePostRideCascade', () => {
  test('keeps ride save as the first beat before backend status exists', () => {
    const cascade = derivePostRideCascade({ uploadState: 'uploading', status: null });

    expect(cascade.phase).toBe('uploading');
    expect(cascade.hero).toBeNull();
    expect(cascade.lines[0]).toMatchObject({
      key: 'uploaded',
      label: 'Ride saved',
      state: 'pending',
      truthSource: 'device',
    });
  });

  test('uploaded ride without server signals remains uploaded, not fake-provisional', () => {
    const cascade = derivePostRideCascade({ uploadState: 'uploaded', status: null });

    expect(cascade.phase).toBe('uploaded');
    expect(cascade.lines.find((line) => line.key === 'chain_record')?.state).toBe('pending');
  });

  test('backend ride check signals advance the cascade to provisional', () => {
    const cascade = derivePostRideCascade({
      uploadState: 'uploaded',
      status: statusWith({
        canonicalMatch: true,
        rideHashHex: 'a'.repeat(64),
      }),
    });

    expect(cascade.phase).toBe('provisional');
    expect(cascade.lines.find((line) => line.key === 'fingerprint')).toMatchObject({
      state: 'complete',
      truthSource: 'attested',
    });
    expect(cascade.lines.find((line) => line.key === 'chain_record')?.state).toBe('pending');
  });

  test('verified ride marks the hero stat and verification line as verified', () => {
    const cascade = derivePostRideCascade({
      uploadState: 'uploaded',
      status: statusWith({
        attestationStatus: 'attested',
        rideAttestationPda: '9xRideAttestationPda',
        metrics: {
          tss: 123.4,
          kcals: 1000,
          distanceM: 20_000,
          elevationGainM: 250,
          durationSec: 3600,
          avgPowerW: null,
          normalizedPowerW: null,
        },
        hasPatterns: true,
        hasLeaderboards: true,
        earnings: {
          contractVersion: 'client.v1',
          truthSource: 'onchain',
          rideId: 'ride-1',
          calEarned: 875,
          dungEarned: 2,
          finalizedAt: '2026-04-22T12:00:00Z',
        },
        climbEarnings: [
          {
            contractVersion: 'client.v1',
            truthSource: 'onchain',
            rideId: 'ride-1',
            climbId: '142',
            climbName: 'Manayunk Wall',
            vaultId: 142,
            vaultSignature: 'sig-1',
            calTribute: 104,
            tributeTruthSource: 'onchain',
            completionEvidenceVersion: 2,
            tributeBound: true,
            completionTimeS: 412,
            recordBoardRank: 1,
            recordBoardBestTimeS: 412,
            isNewPersonalBest: true,
            isNewKom: true,
            txSignature: 'climb-tx',
            completedAt: '2026-04-22T11:30:00Z',
          },
        ],
      }),
    });

    expect(cascade.phase).toBe('attested');
    expect(cascade.hero).toEqual({
      label: 'Ride TSS',
      value: '123.4',
      truthSource: 'onchain',
      verified: true,
    });
    expect(cascade.lines.find((line) => line.key === 'earnings')).toMatchObject({
      state: 'complete',
      value: '+875 CAL',
      truthSource: 'onchain',
    });
    expect(cascade.lines.find((line) => line.key === 'climb_earning:142')).toMatchObject({
      label: 'Manayunk Wall',
      state: 'complete',
      value: '+104 CAL · #1 · 6:52',
      truthSource: 'onchain',
    });
    expect(cascade.lines.find((line) => line.key === 'chain_record')).toMatchObject({
      label: 'Verification',
      state: 'complete',
    });
  });

  test('does not present a legacy copied tribute as on-chain CAL', () => {
    const cascade = derivePostRideCascade({
      uploadState: 'uploaded',
      status: statusWith({
        climbEarnings: [
          {
            contractVersion: 'client.v1',
            truthSource: 'onchain',
            rideId: 'ride-1',
            climbId: '142',
            climbName: 'Manayunk Wall',
            calTribute: 104,
            tributeTruthSource: 'projected',
            completionEvidenceVersion: 1,
            tributeBound: false,
            completionTimeS: 412,
          },
        ],
      }),
    });

    expect(cascade.lines.find((line) => line.key === 'climb_earning:142')).toMatchObject({
      label: 'Manayunk Wall',
      value: '6:52',
      truthSource: 'onchain',
    });
  });

  test('shows held CAL instead of a pending counted amount', () => {
    const cascade = derivePostRideCascade({
      uploadState: 'uploaded',
      status: statusWith({
        status: 'completed',
        attestationStatus: 'attested',
        effortPolicy: {
          rewardPolicy: 'threshold_provisional_hold_v1',
          thresholdEconomyState: 'held',
        },
        metrics: {
          tss: 78.2,
          thresholdTrainingState: 'pending',
          avgPowerW: null,
          normalizedPowerW: null,
        },
      }),
    });

    expect(cascade.lines.find((line) => line.key === 'earnings')).toMatchObject({
      label: 'CAL',
      state: 'complete',
      value: 'Held',
    });
    expect(cascade.hero).toMatchObject({
      label: 'Ride TSS',
      value: '78.2 · Pending',
      verified: false,
    });
  });

  test('ignores legacy cumulative progression and keeps derived ride TSS', () => {
    const cascade = derivePostRideCascade({
      uploadState: 'uploaded',
      status: statusWith({
        attestationStatus: 'provisional',
        progression: {
          contractVersion: 'client.v1',
          truthSource: 'projected',
          rideId: 'ride-1',
          tssDelta: 78.2,
          totalTssAfter: 1200.5,
          levelDelta: 1,
          levelAfter: 7,
        } as unknown as NonNullable<RideStatus['progression']>,
        metrics: {
          tss: 78.2,
          kcals: 1000,
          distanceM: 20_000,
          elevationGainM: 250,
          durationSec: 3600,
          avgPowerW: null,
          normalizedPowerW: null,
        },
      }),
    });

    expect(cascade.hero).toEqual({
      label: 'Ride TSS',
      value: '78.2',
      truthSource: 'attested',
      verified: false,
    });
    expect(cascade.lines.find((line) => line.key === 'progression')).toMatchObject({
      label: 'Progress',
      state: 'complete',
      value: '+78.2 TSS',
      truthSource: 'attested',
    });
  });

  test('ride mismatch is review, not failed economics', () => {
    const cascade = derivePostRideCascade({
      uploadState: 'uploaded',
      status: statusWith({
        canonicalMatch: false,
        reviewReason: 'preliminary_hash_mismatch',
      }),
    });

    expect(cascade.phase).toBe('under_review');
    expect(cascade.title).toBe('Needs review');
    expect(cascade.lines.find((line) => line.key === 'chain_record')?.state).toBe('review');
  });

  test('local permanent upload failures stay distinct from backend review', () => {
    const cascade = derivePostRideCascade({
      uploadState: 'failed',
      status: statusWith({ attestationStatus: 'provisional' }),
    });

    expect(cascade.phase).toBe('failed');
    expect(cascade.lines[0].state).toBe('failed');
  });

  test('incomplete local recordings do not surface completed-ride copy', () => {
    const cascade = derivePostRideCascade({
      uploadState: 'uploading',
      status: null,
      isIncomplete: true,
      incompleteReason: 'Not enough movement to score.',
    });

    expect(cascade.phase).toBe('incomplete');
    expect(cascade.title).toBe('Recording saved');
    expect(cascade.subtitle).toBe('Not enough movement to score.');
    expect(cascade.lines[0]).toMatchObject({
      key: 'uploaded',
      state: 'complete',
      truthSource: 'device',
    });
    expect(cascade.lines.find((line) => line.key === 'fingerprint')).toMatchObject({
      state: 'review',
      value: 'Not counted',
    });
  });
});
