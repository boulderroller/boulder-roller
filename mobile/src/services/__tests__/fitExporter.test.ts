import { exportRideToFIT, generateFIT, rideHasSensorData } from '../fitExporter';
import { getDatabase, getRide, getRideSamples, type GPSSampleRow } from '../database';
import { Decoder, Stream } from '@garmin/fitsdk';
import * as Crypto from 'expo-crypto';
import * as FileSystem from 'expo-file-system';
import fs from 'fs';
import path from 'path';
import { createHash } from 'crypto';

jest.mock('../database', () => ({
  getDatabase: jest.fn(),
  getRide: jest.fn(),
  getRideSamples: jest.fn(),
}));

const mockGetDatabase = getDatabase as jest.MockedFunction<typeof getDatabase>;
const mockGetRide = getRide as jest.MockedFunction<typeof getRide>;
const mockGetRideSamples = getRideSamples as jest.MockedFunction<typeof getRideSamples>;
const mockDigest = Crypto.digest as jest.MockedFunction<typeof Crypto.digest>;
const mockWriteAsStringAsync = FileSystem.writeAsStringAsync as jest.MockedFunction<typeof FileSystem.writeAsStringAsync>;

const SHARED_SENSOR_FIT_FIXTURE = path.resolve(
  __dirname,
  '../../../../tests/fixtures/mobile_sensor_ride_fit_v1.base64',
);

function mkRide(overrides: Partial<ReturnType<typeof getRide> & object> = {}) {
  const base = {
    id: 'ride-fit',
    status: 'stopped',
    started_at: new Date('2026-04-16T12:00:00Z').getTime(),
    ended_at: new Date('2026-04-16T13:00:00Z').getTime(),
    duration_ms: 3_600_000,
    moving_time_ms: 3_500_000,
    distance_m: 25_000,
    elevation_gain_m: 250,
    max_speed_mps: 12,
    sport_type: 'ride',
    clock_drift_ms: null,
    sample_count: 3,
    rejected_samples: null,
    upload_id: null,
    notes: null,
    preliminary_ride_hash: null,
    parser_version: null,
    had_crash_recovery: 0,
  };
  return { ...base, ...overrides };
}

function mkSample(t: number, extras: Partial<GPSSampleRow> = {}): GPSSampleRow {
  return {
    ride_id: 'ride-fit',
    t_offset_ms: t,
    latitude: 39.95 + t * 0.0001,
    longitude: -75.16 + t * 0.0001,
    altitude_m: 10 + t * 0.01,
    accuracy_m: 5,
    vert_accuracy_m: 3,
    speed_mps: 5,
    bearing_deg: 45,
    source: 'fused',
    ...extras,
  };
}

function decodeFIT(bytes: Uint8Array): { messages: { recordMesgs?: unknown[]; sessionMesgs?: unknown[]; activityMesgs?: unknown[]; fileIdMesgs?: unknown[] } } {
  const stream = Stream.fromByteArray(bytes);
  const decoder = new Decoder(stream) as unknown as {
    read: () => { messages: { recordMesgs?: unknown[]; sessionMesgs?: unknown[]; activityMesgs?: unknown[]; fileIdMesgs?: unknown[] } };
  };
  return decoder.read();
}

function rawSha256Buffer(data: BufferSource): ArrayBuffer {
  const bytes = data instanceof ArrayBuffer
    ? Buffer.from(data)
    : Buffer.from(data.buffer, data.byteOffset, data.byteLength);
  const digest = createHash('sha256').update(bytes).digest();
  return digest.buffer.slice(digest.byteOffset, digest.byteOffset + digest.byteLength);
}

describe('rideHasSensorData', () => {
  test('returns false for GPS-only samples', () => {
    expect(
      rideHasSensorData([
        mkSample(0),
        mkSample(1000),
      ]),
    ).toBe(false);
  });

  test('returns true when any sample has power', () => {
    expect(
      rideHasSensorData([
        mkSample(0),
        mkSample(1000, { power_w: 240 }),
      ]),
    ).toBe(true);
  });

  test('returns true when any sample has heart rate', () => {
    expect(rideHasSensorData([mkSample(0, { heart_rate_bpm: 152 })])).toBe(true);
  });

  test('returns true when any sample has cadence', () => {
    expect(rideHasSensorData([mkSample(0, { cadence_rpm: 90 })])).toBe(true);
  });

  test('null and undefined both count as "missing"', () => {
    expect(
      rideHasSensorData([
        mkSample(0, { power_w: null, heart_rate_bpm: undefined, cadence_rpm: null }),
      ]),
    ).toBe(false);
  });

  test('empty sample list is false', () => {
    expect(rideHasSensorData([])).toBe(false);
  });
});

describe('generateFIT', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGetDatabase.mockReturnValue({} as never);
    mockDigest.mockImplementation(async (_algorithm, data) => rawSha256Buffer(data));
  });

  test('throws on non-existent ride', () => {
    mockGetRide.mockReturnValue(null);
    expect(() => generateFIT('missing')).toThrow(/Ride not found/);
  });

  test('produces valid FIT bytes with header CRC check', () => {
    mockGetRide.mockReturnValue(mkRide());
    mockGetRideSamples.mockReturnValue([
      mkSample(0, { power_w: 200, heart_rate_bpm: 140, cadence_rpm: 85 }),
      mkSample(1000, { power_w: 220, heart_rate_bpm: 145, cadence_rpm: 88 }),
      mkSample(2000, { power_w: 240, heart_rate_bpm: 150, cadence_rpm: 90 }),
    ]);

    const bytes = generateFIT('ride-fit');

    // Header: [0]=14 (header size), [8-11]='.FIT' ASCII
    expect(bytes.byteLength).toBeGreaterThan(20);
    expect(bytes[0]).toBe(14);
    expect(String.fromCharCode(bytes[8], bytes[9], bytes[10], bytes[11])).toBe('.FIT');

    // Round-trip decode should succeed without throwing — validates
    // that the encoder produced a well-formed file.
    const stream = Stream.fromByteArray(bytes);
    const decoder = new Decoder(stream);
    expect(decoder).toBeDefined();
  });

  test('encoded FIT contains record data matching input samples', () => {
    mockGetRide.mockReturnValue(mkRide());
    mockGetRideSamples.mockReturnValue([
      mkSample(0, { power_w: 200, heart_rate_bpm: 140, cadence_rpm: 85 }),
    ]);

    const bytes = generateFIT('ride-fit');

    const { messages } = decodeFIT(bytes);

    expect(messages.fileIdMesgs).toBeDefined();
    expect(messages.fileIdMesgs!.length).toBe(1);
    expect(messages.recordMesgs).toBeDefined();
    expect(messages.recordMesgs!.length).toBe(1);
    expect(messages.sessionMesgs).toBeDefined();
    expect(messages.activityMesgs).toBeDefined();

    const record = messages.recordMesgs![0] as Record<string, unknown>;
    expect(record.power).toBe(200);
    expect(record.heartRate).toBe(140);
    expect(record.cadence).toBe(85);
  });

  test('matches the shared backend ingestion fixture for sensor rides', () => {
    mockGetRide.mockReturnValue(mkRide());
    mockGetRideSamples.mockReturnValue([
      mkSample(0, {
        latitude: 39.95,
        longitude: -75.16,
        altitude_m: 10,
        speed_mps: 5,
        power_w: 200,
        heart_rate_bpm: 140,
        cadence_rpm: 85,
      }),
      mkSample(1000, {
        latitude: 39.9501,
        longitude: -75.1599,
        altitude_m: 20,
        speed_mps: 6,
        power_w: 220,
        heart_rate_bpm: 145,
        cadence_rpm: 88,
      }),
      mkSample(2000, {
        latitude: 39.9502,
        longitude: -75.1598,
        altitude_m: 30,
        speed_mps: 7,
        power_w: 240,
        heart_rate_bpm: 150,
        cadence_rpm: 90,
      }),
    ]);

    const bytes = generateFIT('ride-fit');
    const fixture = fs.readFileSync(SHARED_SENSOR_FIT_FIXTURE, 'utf8').trim();

    expect(Buffer.from(bytes).toString('base64')).toBe(fixture);
  });

  test('preserves sparse sensor evidence per FIT record', () => {
    mockGetRide.mockReturnValue(mkRide({ sample_count: 4 }));
    mockGetRideSamples.mockReturnValue([
      mkSample(0, { power_w: 255, heart_rate_bpm: null, cadence_rpm: null }),
      mkSample(1000, { power_w: null, heart_rate_bpm: 151, cadence_rpm: null }),
      mkSample(2000, { power_w: null, heart_rate_bpm: null, cadence_rpm: 92 }),
      mkSample(3000, { power_w: null, heart_rate_bpm: null, cadence_rpm: null }),
    ]);

    const bytes = generateFIT('ride-fit');
    const { messages } = decodeFIT(bytes);
    const records = messages.recordMesgs as Array<Record<string, unknown>>;

    expect(records).toHaveLength(4);
    expect(records[0]).toMatchObject({ power: 255 });
    expect(records[0].heartRate).toBeUndefined();
    expect(records[0].cadence).toBeUndefined();
    expect(records[1]).toMatchObject({ heartRate: 151 });
    expect(records[1].power).toBeUndefined();
    expect(records[1].cadence).toBeUndefined();
    expect(records[2]).toMatchObject({ cadence: 92 });
    expect(records[2].power).toBeUndefined();
    expect(records[2].heartRate).toBeUndefined();
    expect(records[3].power).toBeUndefined();
    expect(records[3].heartRate).toBeUndefined();
    expect(records[3].cadence).toBeUndefined();
  });

  test('omits sensor fields when samples have null values', () => {
    mockGetRide.mockReturnValue(mkRide());
    mockGetRideSamples.mockReturnValue([
      mkSample(0), // GPS-only
    ]);

    const bytes = generateFIT('ride-fit');

    const { messages } = decodeFIT(bytes);
    const record = messages.recordMesgs![0] as Record<string, unknown>;

    expect(record.power).toBeUndefined();
    expect(record.heartRate).toBeUndefined();
    expect(record.cadence).toBeUndefined();
    // GPS position should still be present (as semicircles)
    expect(record.positionLat).toBeDefined();
    expect(record.positionLong).toBeDefined();
  });

  test('converts lat/lon to semicircles correctly', () => {
    mockGetRide.mockReturnValue(mkRide());
    mockGetRideSamples.mockReturnValue([
      {
        ...mkSample(0),
        // 90° (lat max) → 2^30 = 0x40000000 semicircles
        latitude: 90,
        // 45° → 2^29 = 0x20000000 semicircles
        longitude: 45,
      },
    ]);

    const bytes = generateFIT('ride-fit');
    const { messages } = decodeFIT(bytes);
    const record = messages.recordMesgs![0] as Record<string, unknown>;

    expect(record.positionLat).toBe(0x40000000);
    expect(record.positionLong).toBe(0x20000000);
  });

  test('handles ride with no samples gracefully', () => {
    mockGetRide.mockReturnValue(mkRide({ sample_count: 0 }));
    mockGetRideSamples.mockReturnValue([]);

    const bytes = generateFIT('ride-fit');
    expect(bytes.byteLength).toBeGreaterThan(14); // header + CRC at minimum

    const { messages } = decodeFIT(bytes);
    expect(messages.recordMesgs ?? []).toHaveLength(0);
    expect(messages.sessionMesgs).toBeDefined(); // SESSION still written
  });
});

describe('exportRideToFIT', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGetDatabase.mockReturnValue({} as never);
    mockDigest.mockImplementation(async (_algorithm, data) => rawSha256Buffer(data));
  });

  test('hashes the raw uploaded FIT bytes, not the base64 storage wrapper', async () => {
    mockGetRide.mockReturnValue(mkRide());
    mockGetRideSamples.mockReturnValue([
      mkSample(0, { power_w: 200, heart_rate_bpm: 140, cadence_rpm: 85 }),
      mkSample(1000, { power_w: 220, heart_rate_bpm: 145, cadence_rpm: 88 }),
      mkSample(2000, { power_w: 240, heart_rate_bpm: 150, cadence_rpm: 90 }),
    ]);

    const bytes = generateFIT('ride-fit');
    const base64 = Buffer.from(bytes).toString('base64');
    const rawHash = createHash('sha256').update(Buffer.from(bytes)).digest('hex');
    const base64WrapperHash = createHash('sha256').update(base64).digest('hex');

    const exported = await exportRideToFIT('ride-fit');

    expect(exported.filePath).toBe('/mock/documents/rides/ride-fit.fit');
    expect(exported.fileSize).toBe(bytes.byteLength);
    expect(exported.fileHash).toBe(rawHash);
    expect(exported.fileHash).not.toBe(base64WrapperHash);
    expect(mockWriteAsStringAsync).toHaveBeenCalledWith(
      '/mock/documents/rides/ride-fit.fit',
      base64,
      { encoding: FileSystem.EncodingType.Base64 },
    );
  });
});
