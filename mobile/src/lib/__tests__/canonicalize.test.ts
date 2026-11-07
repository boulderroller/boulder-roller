/**
 * canonicalize TS port — symmetry tests against the Rust reference.
 *
 * Reference vectors live in workout-parse/src/canonicalize.rs (sample_activity
 * + canonicalize_v1_produces_expected_json + canonicalize_v1_hash_is_stable
 * test cases). The TS port must produce the same JSON and the same hash for
 * an equivalent input. If this drifts, the device-side preliminary ride
 * hash diverges from the backend's, and ride attestation breaks.
 *
 * Bump expected JSON / hash if (and ONLY if) workout-parse changes its
 * canonical algorithm, AND CURRENT_PARSER_VERSION is incremented in lockstep.
 */

import * as Crypto from 'expo-crypto';

import {
  canonicalize,
  canonicalizeV1,
  canonicalizeV2,
  canonicalizeV3,
  canonicalizeV4,
  canonicalizeV5,
  serializeCanonical,
  hashCanonicalRide,
  CURRENT_PARSER_VERSION,
  PARSER_VERSION_V1,
  PARSER_VERSION_V2,
  PARSER_VERSION_V3,
  PARSER_VERSION_V4,
  PARSER_VERSION_V5,
  type ParsedActivity,
} from '../canonicalize';

interface CanonicalRideVectorsFixture {
  parser_version: number;
  unsupported_parser_version: number;
  vectors: {
    rust_sample_activity: {
      activity: ParsedActivity;
      canonical_json: string;
      ride_hash: string;
    };
  };
}

interface CrossFormatVectorsFixture {
  parser_version: number;
  vectors: Record<string, { canonical_json: string; ride_hash: string }>;
}

function loadVectors(filename: string): CanonicalRideVectorsFixture {
  const fs = jest.requireActual('fs') as typeof import('fs');
  const path = jest.requireActual('path') as typeof import('path');
  const fixturePath = path.resolve(
    __dirname,
    `../../../../tests/fixtures/${filename}`,
  );
  return JSON.parse(fs.readFileSync(fixturePath, 'utf8')) as CanonicalRideVectorsFixture;
}

const V1_FIXTURE = loadVectors('canonical_ride_v1_vectors.json');
const V2_FIXTURE = loadVectors('canonical_ride_v2_vectors.json');
const V3_FIXTURE = loadVectors('canonical_ride_v3_vectors.json');
const V4_FIXTURE = loadVectors('canonical_ride_v4_vectors.json');
const V5_FIXTURE = loadVectors('canonical_ride_v5_vectors.json');
const V1_EXPECTED_JSON = V1_FIXTURE.vectors.rust_sample_activity.canonical_json;
const V1_EXPECTED_HASH = V1_FIXTURE.vectors.rust_sample_activity.ride_hash;
const V2_EXPECTED_JSON = V2_FIXTURE.vectors.rust_sample_activity.canonical_json;
const V3_EXPECTED_JSON = V3_FIXTURE.vectors.rust_sample_activity.canonical_json;
const V3_EXPECTED_HASH = V3_FIXTURE.vectors.rust_sample_activity.ride_hash;
const V4_EXPECTED_JSON = V4_FIXTURE.vectors.rust_sample_activity.canonical_json;
const V5_EXPECTED_JSON = V5_FIXTURE.vectors.rust_sample_activity.canonical_json;
const V5_EXPECTED_HASH = V5_FIXTURE.vectors.rust_sample_activity.ride_hash;
const CROSS_FORMAT_FIXTURE = loadVectors(
  'canonical_cross_format_v2_vectors.json',
) as unknown as CrossFormatVectorsFixture;

// Mirror of the Rust `sample_activity()` test fixture. Rust uses MISSING_*
// sentinels for missing values; TS uses null in the same array slots.
function sampleActivity(): ParsedActivity {
  return V1_FIXTURE.vectors.rust_sample_activity.activity;
}

describe('canonicalizeV1', () => {
  test('produces the canonical struct that matches the Rust reference vector', () => {
    const ride = canonicalizeV1(sampleActivity());
    expect(ride.parser_version).toBe(1);
    expect(ride.sport).toBe('cycling'); // ASCII-only + lowercase
    expect(ride.started_at_ms).toBe(1_000);
    expect(ride.samples).toHaveLength(4);

    // Spot-check the second 0 bucket — exercises rounded means + last-value
    expect(ride.samples[0]).toEqual({
      cadence_rpm: 81,
      dist_dm: 15,
      elev_dm: 101,
      hr_bpm: 120,
      lat_e6: 12_345_680,
      lon_e6: -98_765_430,
      power_w: 101,
      sec_offset: 0,
      speed_cms: 531,
    });

    // Empty bucket at sec_offset 2 (no input samples in that second)
    expect(ride.samples[2].sec_offset).toBe(2);
    expect(ride.samples[2].power_w).toBeNull();
    expect(ride.samples[2].lat_e6).toBeNull();
  });

  test('handles empty time_ms by returning zero samples', () => {
    const ride = canonicalizeV1({
      time_ms: [],
      sport: 'Cycling',
      started_at_ms: 0,
    });
    expect(ride.samples).toEqual([]);
    expect(ride.sport).toBe('cycling');
  });

  test('normalizes sport: trim, ASCII-only, lowercase', () => {
    expect(canonicalizeV1({ ...sampleActivity(), sport: '  CyCling🚵 ' }).sport).toBe(
      'cycling',
    );
    expect(canonicalizeV1({ ...sampleActivity(), sport: 'RIDE' }).sport).toBe('ride');
  });
});

describe('serializeCanonical', () => {
  test('byte-exact match with the Rust reference JSON', () => {
    const ride = canonicalizeV1(sampleActivity());
    expect(serializeCanonical(ride)).toBe(V1_EXPECTED_JSON);
  });
});

describe('parser version symmetry with Rust', () => {
  test('V5 is the current parser semantic version', () => {
    expect(CURRENT_PARSER_VERSION).toBe(5);
  });

  test('the permanent V1 fixture remains explicitly versioned as V1', () => {
    expect(V1_FIXTURE.parser_version).toBe(PARSER_VERSION_V1);
    expect(CURRENT_PARSER_VERSION).toBe(PARSER_VERSION_V5);
  });

  test('TS CURRENT_PARSER_VERSION matches workout-parse/src/canonicalize.rs', () => {
    const fs = jest.requireActual('fs') as typeof import('fs');
    const path = jest.requireActual('path') as typeof import('path');
    const rustSourcePath = path.resolve(
      __dirname,
      '../../../../workout-parse/src/canonicalize.rs',
    );
    const rustSource = fs.readFileSync(rustSourcePath, 'utf8');
    const match = rustSource.match(
      /pub const CURRENT_PARSER_VERSION:\s*u32\s*=\s*PARSER_VERSION_V5;/,
    );
    expect(match).not.toBeNull();
    expect(rustSource).toMatch(/pub const PARSER_VERSION_V2:\s*u32\s*=\s*2;/);
    expect(rustSource).toMatch(/pub const PARSER_VERSION_V3:\s*u32\s*=\s*3;/);
    expect(rustSource).toMatch(/pub const PARSER_VERSION_V4:\s*u32\s*=\s*4;/);
    expect(rustSource).toMatch(/pub const PARSER_VERSION_V5:\s*u32\s*=\s*5;/);
  });

  test('unknown parser_version fails closed', () => {
    expect(() =>
      canonicalize(sampleActivity(), V4_FIXTURE.unsupported_parser_version),
    ).toThrow(/unsupported canonicalization parser_version/);
  });

  test('V2 remains available for replay', () => {
    const ride = canonicalizeV2(sampleActivity());
    expect(ride.parser_version).toBe(PARSER_VERSION_V2);
    expect(serializeCanonical(ride)).toBe(V2_EXPECTED_JSON);
  });

  test('V3 remains available for authoritative-metrics replay', () => {
    const ride = canonicalizeV3(sampleActivity());
    expect(ride.parser_version).toBe(PARSER_VERSION_V3);
    expect(serializeCanonical(ride)).toBe(V3_EXPECTED_JSON);
  });

  test('V4 remains available for authoritative-climb replay', () => {
    const ride = canonicalizeV4(sampleActivity());
    expect(ride.parser_version).toBe(PARSER_VERSION_V4);
    expect(serializeCanonical(ride)).toBe(V4_EXPECTED_JSON);
  });

  test('V5/current emits the authoritative climb-power vector', () => {
    const ride = canonicalizeV5(sampleActivity());
    expect(ride.parser_version).toBe(PARSER_VERSION_V5);
    expect(serializeCanonical(ride)).toBe(V5_EXPECTED_JSON);
  });

  test('V2 mobile canonicalization matches the GPX-compatible cross-format vector', () => {
    const ride = canonicalizeV2({
      time_ms: [1_776_340_800_000, 1_776_340_801_000, 1_776_340_802_000],
      lat_e7: [399_500_000, 399_501_000, 399_502_000],
      lon_e7: [-751_600_000, -751_599_000, -751_598_000],
      elevation_m: [10, 20, 30],
      pwr_w: [200, 220, 240],
      hr_bpm: [140, 145, 150],
      cadence_rpm: [85, 88, 90],
      sport: 'cycling',
      started_at_ms: 1_776_340_800_000,
    });

    expect(CROSS_FORMAT_FIXTURE.parser_version).toBe(PARSER_VERSION_V2);
    expect(serializeCanonical(ride)).toBe(
      CROSS_FORMAT_FIXTURE.vectors.gpx.canonical_json,
    );
  });
});

describe('V2 timestamp parity with Rust', () => {
  test('rejects out-of-order samples', () => {
    expect(() => canonicalizeV2({ ...sampleActivity(), time_ms: [1_000, 999] }))
      .toThrow(/out of order/);
  });

  test('requires started_at_ms to equal the first sample', () => {
    expect(() => canonicalizeV2({ ...sampleActivity(), started_at_ms: 999 }))
      .toThrow(/does not match first sample/);
  });

  test('rejects an activity longer than 48 hours', () => {
    expect(() => canonicalizeV2({
      ...sampleActivity(),
      time_ms: [0, (48 * 60 * 60 * 1000) + 1],
      started_at_ms: 0,
    })).toThrow(/maximum 172800s/);
  });

  test('keeps V1 compatibility behavior separate from V2 validation', () => {
    expect(canonicalizeV1({ ...sampleActivity(), time_ms: [1_000, 999] }).samples)
      .toHaveLength(1);
  });

  test('rejects non-integer timestamps before allocating buckets', () => {
    expect(() => canonicalizeV2({ ...sampleActivity(), time_ms: [1_000, Number.NaN] }))
      .toThrow(/finite integer/);
  });
});

describe('hashCanonicalRide', () => {
  test('SHA256 hex matches the Rust reference vector', async () => {
    // jest.setup.ts mocks expo-crypto's digestStringAsync to return a
    // constant; re-implement once to do the actual SHA256 so we exercise
    // the real serialization end-to-end.
    const realCrypto = jest.requireActual('crypto') as typeof import('crypto');
    (Crypto.digestStringAsync as jest.Mock).mockImplementationOnce(
      async (_alg: string, data: string) =>
        realCrypto.createHash('sha256').update(data).digest('hex'),
    );

    const hash = await hashCanonicalRide(sampleActivity());
    expect(hash).toBe(V5_EXPECTED_HASH);
  });

  test('V3 remains hashable against its permanent fixture', async () => {
    const realCrypto = jest.requireActual('crypto') as typeof import('crypto');
    (Crypto.digestStringAsync as jest.Mock).mockImplementationOnce(
      async (_alg: string, data: string) =>
        realCrypto.createHash('sha256').update(data).digest('hex'),
    );

    await expect(hashCanonicalRide(sampleActivity(), PARSER_VERSION_V3)).resolves.toBe(
      V3_EXPECTED_HASH,
    );
  });

  test('V1 remains hashable against its permanent fixture', async () => {
    const realCrypto = jest.requireActual('crypto') as typeof import('crypto');
    (Crypto.digestStringAsync as jest.Mock).mockImplementationOnce(
      async (_alg: string, data: string) =>
        realCrypto.createHash('sha256').update(data).digest('hex'),
    );

    await expect(hashCanonicalRide(sampleActivity(), PARSER_VERSION_V1)).resolves.toBe(
      V1_EXPECTED_HASH,
    );
  });

  test('V2 mobile hash matches the GPX-compatible cross-format vector', async () => {
    const realCrypto = jest.requireActual('crypto') as typeof import('crypto');
    (Crypto.digestStringAsync as jest.Mock).mockImplementationOnce(
      async (_alg: string, data: string) =>
        realCrypto.createHash('sha256').update(data).digest('hex'),
    );

    await expect(hashCanonicalRide({
      time_ms: [1_776_340_800_000, 1_776_340_801_000, 1_776_340_802_000],
      lat_e7: [399_500_000, 399_501_000, 399_502_000],
      lon_e7: [-751_600_000, -751_599_000, -751_598_000],
      elevation_m: [10, 20, 30],
      pwr_w: [200, 220, 240],
      hr_bpm: [140, 145, 150],
      cadence_rpm: [85, 88, 90],
      sport: 'cycling',
      started_at_ms: 1_776_340_800_000,
    }, PARSER_VERSION_V2)).resolves.toBe(CROSS_FORMAT_FIXTURE.vectors.gpx.ride_hash);
  });
});
