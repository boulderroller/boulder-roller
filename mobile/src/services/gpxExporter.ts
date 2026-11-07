/**
 * GPX Export Service
 *
 * Reads GPS samples from SQLite and writes a valid GPX 1.1 XML file.
 * The file is then uploaded via the existing presigned upload flow.
 *
 * Per MOBILE_PHASE0_RESOLUTIONS.md FIX-3: GPX export on device,
 * upload via existing presigned flow. Zero new backend endpoints.
 */

import * as FileSystem from 'expo-file-system';
import * as Crypto from 'expo-crypto';

import { getDatabase, getRideSamples, getRide, getPauseEvents } from './database';
// APP_VERSION deliberately excluded from GPX creator attribute.
// Including it breaks cross-version file-hash reproducibility
// (MOBILE_RECORDING_SURFACE_AUDIT.md §1, Obligation 1).

// ---------------------------------------------------------------------------
// GPX generation
// ---------------------------------------------------------------------------

/**
 * Convert a wallclock start time + monotonic offset to ISO 8601 timestamp.
 */
function toISO8601(wallclockStartMs: number, tOffsetMs: number): string {
  return new Date(wallclockStartMs + tOffsetMs).toISOString();
}

/**
 * Escape XML special characters.
 */
function escapeXml(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

/**
 * Generate GPX XML string from a ride's SQLite data.
 */
export function generateGPX(rideId: string): string {
  const db = getDatabase();
  const ride = getRide(db, rideId);
  if (!ride) {
    throw new Error(`Ride not found: ${rideId}`);
  }

  const samples = getRideSamples(db, rideId);
  const pauses = getPauseEvents(db, rideId);
  const wallclockStart = ride.started_at;
  const rideName = ride.notes ?? 'BoulderRoller Ride';

  // Build paused intervals from pause/resume event pairs. Range matching
  // because exact-integer Set lookup never agreed across two clock domains.
  const pausedIntervals: Array<[number, number]> = [];
  let openPauseStart: number | null = null;
  for (const e of pauses) {
    if (e.event_type === 'pause') {
      if (openPauseStart === null) openPauseStart = e.t_offset_ms;
    } else if (e.event_type === 'resume') {
      if (openPauseStart !== null) {
        pausedIntervals.push([openPauseStart, e.t_offset_ms]);
        openPauseStart = null;
      }
    }
  }
  // Unclosed pause means ride was stopped while paused
  if (openPauseStart !== null) {
    pausedIntervals.push([openPauseStart, Number.POSITIVE_INFINITY]);
  }

  function isInPause(t: number): boolean {
    for (const [start, end] of pausedIntervals) {
      if (t >= start && t < end) return true;
    }
    return false;
  }

  // Split samples into segments at pause boundaries
  const segments: typeof samples[] = [];
  let currentSegment: typeof samples = [];
  let lastWasPaused = false;
  for (const sample of samples) {
    if (isInPause(sample.t_offset_ms)) {
      if (!lastWasPaused && currentSegment.length > 0) {
        segments.push(currentSegment);
        currentSegment = [];
      }
      lastWasPaused = true;
      continue;
    }
    currentSegment.push(sample);
    lastWasPaused = false;
  }
  if (currentSegment.length > 0) {
    segments.push(currentSegment);
  }

  // Build GPX XML
  let gpx = `<?xml version="1.0" encoding="UTF-8"?>\n`;
  gpx += `<gpx version="1.1" creator="BoulderRoller"\n`;
  gpx += `  xmlns="http://www.topografix.com/GPX/1/1"\n`;
  gpx += `  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n`;
  gpx += `  xsi:schemaLocation="http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd">\n`;
  gpx += `  <metadata>\n`;
  gpx += `    <time>${toISO8601(wallclockStart, 0)}</time>\n`;
  gpx += `  </metadata>\n`;
  gpx += `  <trk>\n`;
  gpx += `    <name>${escapeXml(rideName)}</name>\n`;
  gpx += `    <type>Ride</type>\n`;

  for (const segment of segments) {
    gpx += `    <trkseg>\n`;
    for (const s of segment) {
      gpx += `      <trkpt lat="${s.latitude.toFixed(7)}" lon="${s.longitude.toFixed(7)}">\n`;
      if (s.altitude_m !== null) {
        gpx += `        <ele>${s.altitude_m.toFixed(1)}</ele>\n`;
      }
      gpx += `        <time>${toISO8601(wallclockStart, s.t_offset_ms)}</time>\n`;
      gpx += `      </trkpt>\n`;
    }
    gpx += `    </trkseg>\n`;
  }

  gpx += `  </trk>\n`;
  gpx += `</gpx>\n`;

  return gpx;
}

// ---------------------------------------------------------------------------
// File operations
// ---------------------------------------------------------------------------

/**
 * Export a ride to a GPX file and compute its SHA-256 hash.
 * Returns the file path and hash.
 */
export async function exportRideToGPX(rideId: string): Promise<{
  filePath: string;
  fileHash: string;
  fileSize: number;
}> {
  const gpxContent = generateGPX(rideId);

  // Ensure rides directory exists
  const ridesDir = `${FileSystem.documentDirectory}rides/`;
  await FileSystem.makeDirectoryAsync(ridesDir, { intermediates: true });

  // Write GPX file
  const filePath = `${ridesDir}${rideId}.gpx`;
  await FileSystem.writeAsStringAsync(filePath, gpxContent, {
    encoding: FileSystem.EncodingType.UTF8,
  });

  // Compute SHA-256 hash
  const fileHash = await Crypto.digestStringAsync(
    Crypto.CryptoDigestAlgorithm.SHA256,
    gpxContent,
  );

  // Get file size
  const fileInfo = await FileSystem.getInfoAsync(filePath);
  const fileSize = fileInfo.exists && !fileInfo.isDirectory ? fileInfo.size : gpxContent.length;

  return { filePath, fileHash, fileSize };
}

/**
 * Read GPX file contents for upload.
 */
export async function readGPXFile(filePath: string): Promise<string> {
  return FileSystem.readAsStringAsync(filePath, {
    encoding: FileSystem.EncodingType.UTF8,
  });
}

/**
 * Delete a GPX file after successful upload.
 */
export async function deleteGPXFile(filePath: string): Promise<void> {
  try {
    const info = await FileSystem.getInfoAsync(filePath);
    if (info.exists) {
      await FileSystem.deleteAsync(filePath);
    }
  } catch {
    // Ignore cleanup errors
  }
}
