import { deriveAttestationView } from '../attestation';
import type { RideStatus } from '../api';

describe('deriveAttestationView', () => {
  test('null status defaults to uploaded', () => {
    expect(deriveAttestationView(null)).toEqual({ state: 'uploaded' });
  });

  test('current-shape RideStatus without attestation signals maps to uploaded', () => {
    const status: RideStatus = {
      rideId: 'ride-1',
      status: 'completed',
      errorMessage: null,
      calEarned: 42,
      hasGps: true,
      hasPatterns: true,
      hasLeaderboards: true,
      hasAchievements: false,
      metrics: {
        tss: 120,
        kcals: 1800,
        distanceM: 30_000,
        elevationGainM: 200,
        durationSec: 3_600,
        avgPowerW: 220,
        normalizedPowerW: 240,
      },
    };
    expect(deriveAttestationView(status)).toEqual({ state: 'uploaded' });
  });

  test('canonical match without on-chain PDA maps to provisional', () => {
    const status: RideStatus = {
      rideId: 'ride-1',
      status: 'completed',
      errorMessage: null,
      canonicalMatch: true,
      rideHashHex: 'a'.repeat(64),
    };

    expect(deriveAttestationView(status)).toEqual({
      state: 'provisional',
      message: 'Still checking this ride.',
    });
  });

  test('verified RideAttestation maps to rider verification copy', () => {
    const status: RideStatus = {
      rideId: 'ride-1',
      status: 'completed',
      errorMessage: null,
      attestationStatus: 'attested',
      rideAttestationPda: '9xRideAttestationPda',
      rideAttestedAt: '2026-04-19T19:00:00Z',
    };

    expect(deriveAttestationView(status)).toEqual({
      state: 'attested',
      message: 'Verification complete.',
    });
  });

  test('canonical mismatch maps to under_review with backend reason', () => {
    const status: RideStatus = {
      rideId: 'ride-1',
      status: 'under_review',
      errorMessage: null,
      canonicalMatch: false,
      reviewReason: 'preliminary_hash_mismatch',
    };

    expect(deriveAttestationView(status)).toEqual({
      state: 'under_review',
      message: 'This ride needs a review before it counts.',
    });
  });

  // This test documents the compatibility contract — adding unknown fields
  // to RideStatus must never break the derivation.
  test('tolerates extra fields on the status object without crashing', () => {
    const status = {
      rideId: 'ride-1',
      status: 'completed',
      errorMessage: null,
      futureFlag: true,
      nested: { weirdness: 1 },
    } as unknown as RideStatus;
    expect(() => deriveAttestationView(status)).not.toThrow();
    expect(deriveAttestationView(status).state).toBe('uploaded');
  });
});
