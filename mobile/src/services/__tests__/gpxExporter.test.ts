/**
 * GPX Exporter Tests
 *
 * Validates GPX 1.1 format output from SQLite GPS samples.
 */

import { generateGPX } from '../gpxExporter';
import { getDatabase, getRide, getRideSamples, getPauseEvents } from '../database';

// Mock the database module
jest.mock('../database', () => ({
  getDatabase: jest.fn(),
  getRide: jest.fn(),
  getRideSamples: jest.fn(),
  getPauseEvents: jest.fn(),
}));

const mockGetDatabase = getDatabase as jest.MockedFunction<typeof getDatabase>;
const mockGetRide = getRide as jest.MockedFunction<typeof getRide>;
const mockGetRideSamples = getRideSamples as jest.MockedFunction<typeof getRideSamples>;
const mockGetPauseEvents = getPauseEvents as jest.MockedFunction<typeof getPauseEvents>;

describe('GPX Exporter', () => {
  const mockDb = {} as ReturnType<typeof getDatabase>;

  beforeEach(() => {
    jest.clearAllMocks();
    mockGetDatabase.mockReturnValue(mockDb);
    mockGetPauseEvents.mockReturnValue([]);
  });

  describe('generateGPX', () => {
    test('generates valid GPX 1.1 XML', () => {
      mockGetRide.mockReturnValue({
        id: 'ride-001',
        status: 'stopped',
        started_at: new Date('2026-03-28T14:30:00Z').getTime(),
        ended_at: new Date('2026-03-28T15:30:00Z').getTime(),
        duration_ms: 3600000,
        moving_time_ms: 3400000,
        distance_m: 25000,
        elevation_gain_m: 350,
        max_speed_mps: 15.5,
        sport_type: 'ride',
        clock_drift_ms: null,
        sample_count: 2,
        rejected_samples: null,
        upload_id: null,
        notes: null,
        preliminary_ride_hash: null,
        parser_version: null,
        had_crash_recovery: 0,
      });

      mockGetRideSamples.mockReturnValue([
        {
          ride_id: 'ride-001',
          t_offset_ms: 0,
          latitude: 39.9526,
          longitude: -75.1652,
          altitude_m: 15.3,
          accuracy_m: 5.0,
          vert_accuracy_m: 3.0,
          speed_mps: 0,
          bearing_deg: null,
          source: 'fused',
        },
        {
          ride_id: 'ride-001',
          t_offset_ms: 1000,
          latitude: 39.9530,
          longitude: -75.1648,
          altitude_m: 16.1,
          accuracy_m: 4.0,
          vert_accuracy_m: 2.5,
          speed_mps: 5.0,
          bearing_deg: 45.0,
          source: 'fused',
        },
      ]);

      const gpx = generateGPX('ride-001');

      // Verify XML header
      expect(gpx).toContain('<?xml version="1.0" encoding="UTF-8"?>');

      // Verify GPX root element with version 1.1
      expect(gpx).toContain('gpx version="1.1"');

      // Verify creator
      expect(gpx).toContain('creator="BoulderRoller"');

      // Verify namespace
      expect(gpx).toContain('xmlns="http://www.topografix.com/GPX/1/1"');

      // Verify metadata time
      expect(gpx).toContain('<time>2026-03-28T14:30:00.000Z</time>');

      // Verify track name
      expect(gpx).toContain('<name>BoulderRoller Ride</name>');
      expect(gpx).toContain('<type>Ride</type>');

      // Verify track points with 7 decimal places
      expect(gpx).toContain('lat="39.9526000"');
      expect(gpx).toContain('lon="-75.1652000"');
      expect(gpx).toContain('<ele>15.3</ele>');

      // Verify second point
      expect(gpx).toContain('lat="39.9530000"');
      expect(gpx).toContain('lon="-75.1648000"');

      // Verify timestamps are ISO 8601
      expect(gpx).toMatch(/<time>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/);

      // Verify proper closing tags
      expect(gpx).toContain('</trkseg>');
      expect(gpx).toContain('</trk>');
      expect(gpx).toContain('</gpx>');
    });

    test('keeps GPX output deterministic and free of app-version metadata', () => {
      mockGetRide.mockReturnValue({
        id: 'ride-001',
        status: 'stopped',
        started_at: new Date('2026-03-28T14:30:00Z').getTime(),
        ended_at: new Date('2026-03-28T15:30:00Z').getTime(),
        duration_ms: 3600000,
        moving_time_ms: 3400000,
        distance_m: 25000,
        elevation_gain_m: 350,
        max_speed_mps: 15.5,
        sport_type: 'ride',
        clock_drift_ms: null,
        sample_count: 2,
        rejected_samples: null,
        upload_id: null,
        notes: null,
        preliminary_ride_hash: null,
        parser_version: null,
        had_crash_recovery: 0,
      });

      mockGetRideSamples.mockReturnValue([
        {
          ride_id: 'ride-001',
          t_offset_ms: 0,
          latitude: 39.9526,
          longitude: -75.1652,
          altitude_m: 15.3,
          accuracy_m: 5.0,
          vert_accuracy_m: 3.0,
          speed_mps: 0,
          bearing_deg: null,
          source: 'fused',
        },
        {
          ride_id: 'ride-001',
          t_offset_ms: 1000,
          latitude: 39.953,
          longitude: -75.1648,
          altitude_m: 16.1,
          accuracy_m: 4.0,
          vert_accuracy_m: 2.5,
          speed_mps: 5.0,
          bearing_deg: 45.0,
          source: 'fused',
        },
      ]);

      const first = generateGPX('ride-001');
      const second = generateGPX('ride-001');

      expect(first).toBe(second);
      expect(first).toContain('creator="BoulderRoller"');
      expect(first).not.toContain('BoulderRoller/');
      expect(first).not.toContain('APP_VERSION');
    });

    test('uses ride notes as track name if provided', () => {
      mockGetRide.mockReturnValue({
        id: 'ride-001',
        status: 'stopped',
        started_at: Date.now(),
        ended_at: Date.now(),
        duration_ms: 1000,
        moving_time_ms: 800,
        distance_m: 100,
        elevation_gain_m: 0,
        max_speed_mps: 5,
        sport_type: 'ride',
        clock_drift_ms: null,
        sample_count: 1,
        rejected_samples: null,
        upload_id: null,
        notes: 'Morning Hill Repeats',
        preliminary_ride_hash: null,
        parser_version: null,
        had_crash_recovery: 0,
      });
      mockGetRideSamples.mockReturnValue([{
        ride_id: 'ride-001',
        t_offset_ms: 0,
        latitude: 39.95,
        longitude: -75.16,
        altitude_m: 10,
        accuracy_m: 5,
        vert_accuracy_m: null,
        speed_mps: null,
        bearing_deg: null,
        source: 'fused',
      }]);

      const gpx = generateGPX('ride-001');
      expect(gpx).toContain('<name>Morning Hill Repeats</name>');
    });

    test('handles samples with null altitude', () => {
      mockGetRide.mockReturnValue({
        id: 'ride-001',
        status: 'stopped',
        started_at: Date.now(),
        ended_at: Date.now(),
        duration_ms: 1000,
        moving_time_ms: 800,
        distance_m: 100,
        elevation_gain_m: 0,
        max_speed_mps: 5,
        sport_type: 'ride',
        clock_drift_ms: null,
        sample_count: 1,
        rejected_samples: null,
        upload_id: null,
        notes: null,
        preliminary_ride_hash: null,
        parser_version: null,
        had_crash_recovery: 0,
      });
      mockGetRideSamples.mockReturnValue([{
        ride_id: 'ride-001',
        t_offset_ms: 0,
        latitude: 39.95,
        longitude: -75.16,
        altitude_m: null,
        accuracy_m: 5,
        vert_accuracy_m: null,
        speed_mps: null,
        bearing_deg: null,
        source: 'fused',
      }]);

      const gpx = generateGPX('ride-001');
      expect(gpx).not.toContain('<ele>');
    });

    test('escapes XML special characters in ride name', () => {
      mockGetRide.mockReturnValue({
        id: 'ride-001',
        status: 'stopped',
        started_at: Date.now(),
        ended_at: Date.now(),
        duration_ms: 1000,
        moving_time_ms: 800,
        distance_m: 100,
        elevation_gain_m: 0,
        max_speed_mps: 5,
        sport_type: 'ride',
        clock_drift_ms: null,
        sample_count: 1,
        rejected_samples: null,
        upload_id: null,
        notes: 'Hills & Valleys <3',
        preliminary_ride_hash: null,
        parser_version: null,
        had_crash_recovery: 0,
      });
      mockGetRideSamples.mockReturnValue([{
        ride_id: 'ride-001',
        t_offset_ms: 0,
        latitude: 39.95,
        longitude: -75.16,
        altitude_m: 10,
        accuracy_m: 5,
        vert_accuracy_m: null,
        speed_mps: null,
        bearing_deg: null,
        source: 'fused',
      }]);

      const gpx = generateGPX('ride-001');
      expect(gpx).toContain('Hills &amp; Valleys &lt;3');
    });

    test('throws error for non-existent ride', () => {
      mockGetRide.mockReturnValue(null);
      expect(() => generateGPX('nonexistent')).toThrow('Ride not found');
    });
  });

  describe('pause/resume segment splitting', () => {
    function mkSample(t: number, lat = 39.95, lon = -75.16) {
      return {
        ride_id: 'ride-pause',
        t_offset_ms: t,
        latitude: lat,
        longitude: lon,
        altitude_m: 10,
        accuracy_m: 5,
        vert_accuracy_m: null,
        speed_mps: null,
        bearing_deg: null,
        source: 'fused',
        power_w: null,
        heart_rate_bpm: null,
        cadence_rpm: null,
      };
    }

    function mkRide() {
      mockGetRide.mockReturnValue({
        id: 'ride-pause',
        status: 'stopped',
        started_at: new Date('2026-04-16T12:00:00Z').getTime(),
        ended_at: new Date('2026-04-16T13:00:00Z').getTime(),
        duration_ms: 3600000,
        moving_time_ms: 3000000,
        distance_m: 10000,
        elevation_gain_m: 100,
        max_speed_mps: 10,
        sport_type: 'ride',
        clock_drift_ms: null,
        sample_count: 5,
        rejected_samples: null,
        upload_id: null,
        notes: null,
        preliminary_ride_hash: null,
        parser_version: null,
        had_crash_recovery: 0,
      });
    }

    test('splits into two trkseg when one pause/resume bracket samples', () => {
      mkRide();
      mockGetRideSamples.mockReturnValue([
        mkSample(0),
        mkSample(1000),
        mkSample(2000),  // pause at 1500, resume at 2500 — this sample falls in pause
        mkSample(3000),
        mkSample(4000),
      ]);
      mockGetPauseEvents.mockReturnValue([
        { ride_id: 'ride-pause', event_type: 'pause', t_offset_ms: 1500, reason: 'manual' },
        { ride_id: 'ride-pause', event_type: 'resume', t_offset_ms: 2500, reason: 'manual' },
      ]);

      const gpx = generateGPX('ride-pause');
      const trksegMatches = gpx.match(/<trkseg>/g) ?? [];
      expect(trksegMatches.length).toBe(2);
      // Sample at t=2000 should be excluded (in pause range)
      expect(gpx).not.toMatch(/2026-04-16T12:00:02\.000Z/);
      // Samples at t=0,1000 in seg 1; t=3000,4000 in seg 2
      expect(gpx).toMatch(/2026-04-16T12:00:00\.000Z/);
      expect(gpx).toMatch(/2026-04-16T12:00:01\.000Z/);
      expect(gpx).toMatch(/2026-04-16T12:00:03\.000Z/);
      expect(gpx).toMatch(/2026-04-16T12:00:04\.000Z/);
    });

    test('handles unclosed pause (stopped while paused) by excluding tail samples', () => {
      mkRide();
      mockGetRideSamples.mockReturnValue([
        mkSample(0),
        mkSample(1000),
        mkSample(2000),  // after pause at 1500, no resume — these are excluded
        mkSample(3000),
      ]);
      mockGetPauseEvents.mockReturnValue([
        { ride_id: 'ride-pause', event_type: 'pause', t_offset_ms: 1500, reason: 'manual' },
      ]);

      const gpx = generateGPX('ride-pause');
      const trksegMatches = gpx.match(/<trkseg>/g) ?? [];
      expect(trksegMatches.length).toBe(1);
      expect(gpx).toMatch(/2026-04-16T12:00:00\.000Z/);
      expect(gpx).toMatch(/2026-04-16T12:00:01\.000Z/);
      expect(gpx).not.toMatch(/2026-04-16T12:00:02\.000Z/);
      expect(gpx).not.toMatch(/2026-04-16T12:00:03\.000Z/);
    });

    test('handles multiple pause/resume cycles', () => {
      mkRide();
      mockGetRideSamples.mockReturnValue([
        mkSample(0),
        mkSample(1000),  // before pause 1
        mkSample(2000),  // in pause 1 (1500-2500)
        mkSample(3000),  // between pauses
        mkSample(4000),  // in pause 2 (3500-4500)
        mkSample(5000),  // after pause 2
      ]);
      mockGetPauseEvents.mockReturnValue([
        { ride_id: 'ride-pause', event_type: 'pause', t_offset_ms: 1500, reason: 'manual' },
        { ride_id: 'ride-pause', event_type: 'resume', t_offset_ms: 2500, reason: 'manual' },
        { ride_id: 'ride-pause', event_type: 'pause', t_offset_ms: 3500, reason: 'manual' },
        { ride_id: 'ride-pause', event_type: 'resume', t_offset_ms: 4500, reason: 'manual' },
      ]);

      const gpx = generateGPX('ride-pause');
      const trksegMatches = gpx.match(/<trkseg>/g) ?? [];
      expect(trksegMatches.length).toBe(3);
      expect(gpx).not.toMatch(/2026-04-16T12:00:02\.000Z/);
      expect(gpx).not.toMatch(/2026-04-16T12:00:04\.000Z/);
    });

    test('treats samples at exact resume offset as outside pause (half-open interval)', () => {
      mkRide();
      mockGetRideSamples.mockReturnValue([
        mkSample(0),
        mkSample(2500),  // exact resume offset — should be included
      ]);
      mockGetPauseEvents.mockReturnValue([
        { ride_id: 'ride-pause', event_type: 'pause', t_offset_ms: 1500, reason: 'manual' },
        { ride_id: 'ride-pause', event_type: 'resume', t_offset_ms: 2500, reason: 'manual' },
      ]);

      const gpx = generateGPX('ride-pause');
      expect(gpx).toMatch(/2026-04-16T12:00:02\.500Z/);
    });
  });
});
