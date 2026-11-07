/**
 * preliminaryHash — end-to-end test from SQLite-shaped input to hash bytes.
 * The canonicalize TS port is verified against the Rust reference vector
 * separately in canonicalize.test.ts; this file verifies the wiring.
 */

import * as Crypto from 'expo-crypto';

import { computePreliminaryHash, CURRENT_PARSER_VERSION, bytesToHex } from '../preliminaryHash';
import {
  getRide,
  getRideSamples,
  type RideRow,
  type GPSSampleRow,
} from '../../services/database';

jest.mock('../../services/database', () => {
  const actual = jest.requireActual('../../services/database');
  return {
    ...actual,
    getRide: jest.fn(),
    getRideSamples: jest.fn(),
  };
});

const mockGetRide = getRide as jest.MockedFunction<typeof getRide>;
const mockGetRideSamples = getRideSamples as jest.MockedFunction<typeof getRideSamples>;

function rideRow(overrides: Partial<RideRow> = {}): RideRow {
  return {
    id: 'ride-1',
    status: 'stopped',
    started_at: 1_000,
    ended_at: 5_000,
    duration_ms: 4_000,
    moving_time_ms: 4_000,
    distance_m: 100,
    elevation_gain_m: 5,
    max_speed_mps: 10,
    sport_type: 'ride',
    clock_drift_ms: null,
    sample_count: 4,
    rejected_samples: null,
    upload_id: null,
    notes: null,
    preliminary_ride_hash: null,
    parser_version: null,
    had_crash_recovery: 0,
    ...overrides,
  };
}

function gpsSample(t: number, overrides: Partial<GPSSampleRow> = {}): GPSSampleRow {
  return {
    ride_id: 'ride-1',
    t_offset_ms: t,
    latitude: 39.95 + t * 0.0001,
    longitude: -75.16 + t * 0.0001,
    altitude_m: 10,
    accuracy_m: 5,
    vert_accuracy_m: 3,
    speed_mps: 5,
    bearing_deg: 45,
    source: 'fused',
    ...overrides,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  // Use real SHA256 so we exercise the full canonicalize → hash chain.
  const realCrypto = jest.requireActual('crypto') as typeof import('crypto');
  (Crypto.digestStringAsync as jest.Mock).mockImplementation(
    async (_alg: string, data: string) =>
      realCrypto.createHash('sha256').update(data).digest('hex'),
  );
});

describe('computePreliminaryHash', () => {
  test('returns null hash when ride row is missing', async () => {
    mockGetRide.mockReturnValue(null);
    const result = await computePreliminaryHash('missing');
    expect(result.rideHash).toBeNull();
    expect(result.parserVersion).toBe(CURRENT_PARSER_VERSION);
  });

  test('returns 32-byte SHA256 for a real ride with samples', async () => {
    mockGetRide.mockReturnValue(rideRow());
    mockGetRideSamples.mockReturnValue([
      gpsSample(0),
      gpsSample(1000),
      gpsSample(2000),
      gpsSample(3000),
    ]);

    const result = await computePreliminaryHash('ride-1');
    expect(result.rideHash).not.toBeNull();
    expect(result.rideHash!.byteLength).toBe(32);
    expect(result.parserVersion).toBe(CURRENT_PARSER_VERSION);
  });

  test('produces deterministic hash — same input → same output', async () => {
    mockGetRide.mockReturnValue(rideRow());
    mockGetRideSamples.mockReturnValue([gpsSample(0), gpsSample(1000)]);

    const a = await computePreliminaryHash('ride-1');
    const b = await computePreliminaryHash('ride-1');
    expect(a.rideHash).toEqual(b.rideHash);
  });

  test('GPS-only FIT-shaped hashes include GPS speed', async () => {
    mockGetRide.mockReturnValueOnce(rideRow({ sport_type: 'ride' }));
    mockGetRideSamples.mockReturnValueOnce([
      gpsSample(0, { speed_mps: 4 }),
      gpsSample(1000, { speed_mps: 5 }),
    ]);
    const ride = await computePreliminaryHash('ride-1');

    mockGetRide.mockReturnValueOnce(rideRow({ sport_type: 'run' }));
    mockGetRideSamples.mockReturnValueOnce([
      gpsSample(0, { speed_mps: 10 }),
      gpsSample(1000, { speed_mps: 11 }),
    ]);
    const run = await computePreliminaryHash('ride-1');

    expect(Array.from(ride.rideHash!)).not.toEqual(Array.from(run.rideHash!));
  });

  test('GPS-only FIT-shaped hashes keep paused samples like FIT export', async () => {
    mockGetRide.mockReturnValueOnce(rideRow());
    mockGetRideSamples.mockReturnValueOnce([
      gpsSample(0),
      gpsSample(1000),
      gpsSample(2000, { latitude: 41, longitude: -76, altitude_m: 99 }),
      gpsSample(3000),
    ]);
    const withPausedOutlier = await computePreliminaryHash('ride-1');

    mockGetRide.mockReturnValueOnce(rideRow());
    mockGetRideSamples.mockReturnValueOnce([
      gpsSample(0),
      gpsSample(1000),
      gpsSample(2000, { latitude: 39, longitude: -75, altitude_m: -20 }),
      gpsSample(3000),
    ]);
    const withDifferentPausedOutlier = await computePreliminaryHash('ride-1');

    expect(Array.from(withPausedOutlier.rideHash!)).not.toEqual(
      Array.from(withDifferentPausedOutlier.rideHash!),
    );
  });

  test('GPS-only FIT-shaped hashes anchor started_at_ms to first exported point', async () => {
    mockGetRide.mockReturnValueOnce(rideRow({ started_at: 1_000 }));
    mockGetRideSamples.mockReturnValueOnce([
      gpsSample(1000, { latitude: 40.1, longitude: -75.1 }),
      gpsSample(2000, { latitude: 40.2, longitude: -75.2 }),
    ]);
    const startedEarlier = await computePreliminaryHash('ride-1');

    mockGetRide.mockReturnValueOnce(rideRow({ started_at: 2_000 }));
    mockGetRideSamples.mockReturnValueOnce([
      gpsSample(0, { latitude: 40.1, longitude: -75.1 }),
      gpsSample(1000, { latitude: 40.2, longitude: -75.2 }),
    ]);
    const firstPointSameTime = await computePreliminaryHash('ride-1');

    expect(Array.from(startedEarlier.rideHash!)).toEqual(
      Array.from(firstPointSameTime.rideHash!),
    );
  });

  test('GPS-only FIT-shaped hashes preserve missing elevation', async () => {
    mockGetRide.mockReturnValueOnce(rideRow());
    mockGetRideSamples.mockReturnValueOnce([
      gpsSample(0, { altitude_m: null }),
      gpsSample(1000, { altitude_m: 10 }),
    ]);
    const missingElevation = await computePreliminaryHash('ride-1');

    mockGetRide.mockReturnValueOnce(rideRow());
    mockGetRideSamples.mockReturnValueOnce([
      gpsSample(0, { altitude_m: 0 }),
      gpsSample(1000, { altitude_m: 10 }),
    ]);
    const parserDefaultElevation = await computePreliminaryHash('ride-1');

    expect(Array.from(missingElevation.rideHash!)).not.toEqual(
      Array.from(parserDefaultElevation.rideHash!),
    );
  });

  test('sensor rides keep sensor fields in the preliminary hash', async () => {
    mockGetRide.mockReturnValueOnce(rideRow());
    mockGetRideSamples.mockReturnValueOnce([
      gpsSample(0, { speed_mps: 4, power_w: 200 }),
      gpsSample(1000, { speed_mps: 5, power_w: 205 }),
    ]);
    const slower = await computePreliminaryHash('ride-1');

    mockGetRide.mockReturnValueOnce(rideRow());
    mockGetRideSamples.mockReturnValueOnce([
      gpsSample(0, { speed_mps: 4, power_w: 250 }),
      gpsSample(1000, { speed_mps: 5, power_w: 255 }),
    ]);
    const morePower = await computePreliminaryHash('ride-1');

    expect(Array.from(slower.rideHash!)).not.toEqual(Array.from(morePower.rideHash!));
  });
});

describe('bytesToHex', () => {
  test('empty array produces empty string', () => {
    expect(bytesToHex(new Uint8Array(0))).toBe('');
  });

  test('zero-pads single-digit bytes', () => {
    expect(bytesToHex(new Uint8Array([0x00, 0x01, 0x0a, 0x0f]))).toBe('00010a0f');
  });

  test('emits lowercase hex (backend compare assumes lowercase)', () => {
    expect(bytesToHex(new Uint8Array([0xde, 0xad, 0xbe, 0xef]))).toBe('deadbeef');
  });

  test('32-byte SHA256-shaped input serializes to 64 hex chars', () => {
    const bytes = new Uint8Array(32);
    for (let i = 0; i < 32; i++) bytes[i] = i;
    const hex = bytesToHex(bytes);
    expect(hex).toHaveLength(64);
    expect(hex.startsWith('000102030405')).toBe(true);
    expect(hex.endsWith('1c1d1e1f')).toBe(true);
  });

  test('round-trips with the computePreliminaryHash output', async () => {
    mockGetRide.mockReturnValue(rideRow());
    mockGetRideSamples.mockReturnValue([gpsSample(0), gpsSample(1000)]);
    const result = await computePreliminaryHash('ride-1');
    const hex = bytesToHex(result.rideHash!);
    expect(hex).toMatch(/^[0-9a-f]{64}$/);
  });
});
