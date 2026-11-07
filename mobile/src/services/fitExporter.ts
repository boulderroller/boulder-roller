/**
 * FIT file export — native upload format for mobile recordings.
 *
 * Wire format: Garmin FIT Protocol via @garmin/fitsdk. Backend's
 * workout-parse Rust crate parses FIT natively, so the wire format
 * is the same shape end-to-end as the wide SQLite sample row.
 *
 * Produces: FILE_ID → RECORD × N → SESSION → ACTIVITY. Minimum viable
 * activity file that workout-parse + training peaks + Garmin Connect
 * all accept.
 */

import { Encoder, Profile } from '@garmin/fitsdk';
import * as FileSystem from 'expo-file-system';
import * as Crypto from 'expo-crypto';
import { Buffer } from 'buffer';

import { getDatabase, getRide, getRideSamples, type GPSSampleRow } from './database';

// FIT epoch: 1989-12-31T00:00:00Z, 631065600 s after Unix epoch.
const FIT_EPOCH_OFFSET_MS = 631_065_600_000;

// Sport enum values (FIT SDK)
const SPORT_CYCLING = 2;
const SUB_SPORT_GENERIC = 0;

// Event enums
const EVENT_SESSION = 8;
const EVENT_ACTIVITY = 26;
const EVENT_TYPE_STOP = 1;

// File type: 4 = activity
const FILE_TYPE_ACTIVITY = 4;

// Manufacturer 255 = development. We are not Garmin.
const MANUFACTURER_DEVELOPMENT = 255;

// Activity type
const ACTIVITY_TYPE_MANUAL = 0;

function dateToFitTimestamp(unixMs: number): number {
  return Math.max(0, Math.floor((unixMs - FIT_EPOCH_OFFSET_MS) / 1000));
}

function degToSemicircles(deg: number): number {
  return Math.round((deg * 0x80000000) / 180);
}

function bytesToHex(bytes: Uint8Array): string {
  return Array.from(bytes)
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('');
}

/**
 * Returns true when any sample in the given set has sensor data (power,
 * heart rate, or cadence). Kept as a utility for sensor-specific tests
 * and UI copy; upload format selection no longer depends on it.
 */
export function rideHasSensorData(samples: GPSSampleRow[]): boolean {
  return samples.some(
    (s) =>
      s.power_w != null || s.heart_rate_bpm != null || s.cadence_rpm != null,
  );
}

/**
 * Generate FIT bytes for a ride. Reads samples from SQLite, walks them
 * into RECORD messages, caps with SESSION + ACTIVITY summary.
 */
export function generateFIT(rideId: string): Uint8Array {
  const db = getDatabase();
  const ride = getRide(db, rideId);
  if (!ride) {
    throw new Error(`Ride not found: ${rideId}`);
  }

  const samples = getRideSamples(db, rideId);
  const wallclockStart = ride.started_at;
  const wallclockEnd = ride.ended_at ?? wallclockStart + ride.duration_ms;
  const durationS = ride.duration_ms / 1000;
  const movingTimeS = ride.moving_time_ms / 1000;

  const enc = new Encoder();

  enc.writeMesg({
    mesgNum: Profile.MesgNum.FILE_ID,
    type: FILE_TYPE_ACTIVITY,
    manufacturer: MANUFACTURER_DEVELOPMENT,
    product: 0,
    timeCreated: dateToFitTimestamp(wallclockStart),
    serialNumber: 0,
  });

  for (const s of samples) {
    const mesg: { mesgNum: number; [key: string]: unknown } = {
      mesgNum: Profile.MesgNum.RECORD,
      timestamp: dateToFitTimestamp(wallclockStart + s.t_offset_ms),
      positionLat: degToSemicircles(s.latitude),
      positionLong: degToSemicircles(s.longitude),
    };
    if (s.altitude_m != null) mesg.altitude = s.altitude_m;
    if (s.speed_mps != null) mesg.speed = s.speed_mps;
    if (s.power_w != null) mesg.power = s.power_w;
    if (s.heart_rate_bpm != null) mesg.heartRate = s.heart_rate_bpm;
    if (s.cadence_rpm != null) mesg.cadence = s.cadence_rpm;
    enc.writeMesg(mesg);
  }

  enc.writeMesg({
    mesgNum: Profile.MesgNum.SESSION,
    timestamp: dateToFitTimestamp(wallclockEnd),
    startTime: dateToFitTimestamp(wallclockStart),
    totalElapsedTime: durationS,
    totalTimerTime: movingTimeS,
    totalDistance: ride.distance_m,
    totalAscent: Math.round(ride.elevation_gain_m),
    maxSpeed: ride.max_speed_mps,
    sport: SPORT_CYCLING,
    subSport: SUB_SPORT_GENERIC,
    event: EVENT_SESSION,
    eventType: EVENT_TYPE_STOP,
    firstLapIndex: 0,
    numLaps: 1,
  });

  enc.writeMesg({
    mesgNum: Profile.MesgNum.ACTIVITY,
    timestamp: dateToFitTimestamp(wallclockEnd),
    totalTimerTime: movingTimeS,
    numSessions: 1,
    type: ACTIVITY_TYPE_MANUAL,
    event: EVENT_ACTIVITY,
    eventType: EVENT_TYPE_STOP,
  });

  return enc.close();
}

/**
 * Export a ride to a .fit file on disk. Returns path + content hash +
 * byte size. Mirrors exportRideToGPX's shape so the upload queue can
 * treat them interchangeably.
 */
export async function exportRideToFIT(rideId: string): Promise<{
  filePath: string;
  fileHash: string;
  fileSize: number;
}> {
  const bytes = generateFIT(rideId);

  const ridesDir = `${FileSystem.documentDirectory}rides/`;
  await FileSystem.makeDirectoryAsync(ridesDir, { intermediates: true });

  const filePath = `${ridesDir}${rideId}.fit`;
  const base64 = Buffer.from(bytes).toString('base64');
  await FileSystem.writeAsStringAsync(filePath, base64, {
    encoding: FileSystem.EncodingType.Base64,
  });

  // Hash the exact bytes uploaded to storage. Backend duplicate detection
  // and direct-upload compatibility both define file_hash over file bytes,
  // not over the base64 persistence wrapper used by expo-file-system.
  const digest = await Crypto.digest(
    Crypto.CryptoDigestAlgorithm.SHA256,
    bytes,
  );
  const fileHash = bytesToHex(new Uint8Array(digest));

  return { filePath, fileHash, fileSize: bytes.byteLength };
}

/** Read a FIT file's base64 content for upload. */
export async function readFITFile(filePath: string): Promise<string> {
  return FileSystem.readAsStringAsync(filePath, {
    encoding: FileSystem.EncodingType.Base64,
  });
}

/** Delete a FIT file after successful upload. */
export async function deleteFITFile(filePath: string): Promise<void> {
  try {
    const info = await FileSystem.getInfoAsync(filePath);
    if (info.exists) {
      await FileSystem.deleteAsync(filePath);
    }
  } catch {
    // Ignore cleanup errors
  }
}
