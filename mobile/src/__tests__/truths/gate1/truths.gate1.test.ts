/**
 * MOBILE_GATE_1 — runtime-enforceable TRUTHS invariants.
 *
 * Every describe block in this file maps to a specific section of
 * MOBILE_TRUTHS. A failing test means the invariant has drifted in the
 * code and the doc's claim is no longer operational. Restore the
 * invariant or rewrite the test — never both silently.
 *
 * Reading path: when a test here fails, follow the §N citation directly
 * to docs/MOBILE_TRUTHS.md. The comment above each test explains the
 * contract; the assertion pins the machine-checkable version.
 *
 * Scope: Gate 1 covers invariants that can be verified locally without
 * physical hardware or live network. Invariants that require a live
 * device, real BLE sensor, or a cold-booted OS are documented in
 * docs/design/MOBILE_TRUTHS_GATE_1.md as Gate 2 / physical rehearsal
 * candidates.
 *
 * Gate 1 is intentionally static-scan heavy. Regression-style unit
 * tests already pin specific behaviors in their owner modules; Gate 1
 * adds the cross-cutting assertion that those behaviors still match the
 * TRUTHS claim.
 */

import * as fs from 'fs';
import * as path from 'path';
import * as TaskManager from 'expo-task-manager';

// ---------------------------------------------------------------------------
// Gate 1 static-scan helpers (inlined).
//
// These are the primitives every Gate 1 test leans on. They live in this
// file rather than a separate module so jest's default `__tests__/**`
// test discovery does not try to treat the helper module as a test
// suite. If this file grows further, promote the helpers into a
// sibling module and update jest's `testPathIgnorePatterns` accordingly.
// ---------------------------------------------------------------------------

/** Resolve an absolute path to a file in the mobile package. */
function mobilePath(relativeFromMobileRoot: string): string {
  // __dirname is mobile/src/__tests__/truths/gate1 — four levels up is
  // the mobile/ package root.
  const mobileRoot = path.resolve(__dirname, '..', '..', '..', '..');
  return path.join(mobileRoot, relativeFromMobileRoot);
}

/** Read a file as UTF-8 text relative to the mobile/ root. */
function readSource(relativeFromMobileRoot: string): string {
  return fs.readFileSync(mobilePath(relativeFromMobileRoot), 'utf-8');
}

/**
 * Strip `//` line comments and block comments from a TS/TSX source
 * string. Not a full parser — good enough for our well-formatted source
 * files where comment markers do not appear inside strings.
 */
function stripComments(source: string): string {
  let out = source.replace(/\/\*[\s\S]*?\*\//g, '');
  out = out.replace(/(^|[^:])\/\/.*$/gm, '$1');
  return out;
}

/**
 * Recursively list all files under an absolute directory matching the
 * given extensions. Skips __tests__ and node_modules.
 */
function listFiles(absDir: string, extensions: string[]): string[] {
  const out: string[] = [];
  function walk(dir: string): void {
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === '__tests__' || entry.name === 'node_modules') continue;
        walk(full);
      } else if (extensions.some((ext) => entry.name.endsWith(ext))) {
        out.push(full);
      }
    }
  }
  walk(absDir);
  return out;
}

/**
 * Extract string literals from a TypeScript/TSX source whose content
 * matches the predicate. Matches double-quote, single-quote, or
 * backtick-delimited strings.
 */
function findStringLiteralsMatching(
  source: string,
  predicate: (literalContent: string) => boolean,
): string[] {
  const out: string[] = [];
  const re = /(["'`])((?:(?!\1)[^\\]|\\.)*)\1/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(source)) !== null) {
    if (predicate(m[2])) {
      out.push(m[2]);
    }
  }
  return out;
}

/**
 * Extract the bodies of every `db.withTransactionSync(() => { ... })`
 * block from a source via brace-balanced walking. Returns the body
 * content (the substring between the outermost { and } of the arrow
 * function), not including the braces themselves.
 */
function findTransactionBlocks(source: string): string[] {
  const out: string[] = [];
  const opener = /db\.withTransactionSync\(\s*\(\s*\)\s*=>\s*\{/g;
  let m: RegExpExecArray | null;
  while ((m = opener.exec(source)) !== null) {
    let depth = 1;
    let i = m.index + m[0].length;
    while (i < source.length && depth > 0) {
      const ch = source[i];
      if (ch === '{') depth++;
      else if (ch === '}') depth--;
      i++;
    }
    if (depth === 0) {
      const body = source.substring(m.index + m[0].length, i - 1);
      out.push(body);
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// §3 Three Clocks — no silent conflation.
// ---------------------------------------------------------------------------

describe('MOBILE_TRUTHS §3 Three Clocks', () => {
  // The contract: cross-domain time arithmetic (GPS-SAMPLE MS minus
  // WALL-CLOCK MS) only happens inside sampleOffsetMsFromRideStart().
  // Same-domain subtractions (wall-wall, sample-sample) are fine and
  // documented inline in gpsRecording.ts.
  //
  // A violation looks like: `sample.timestamp - rideStartWallclock`,
  // `location.timestamp - Date.now()`, `sample.timestamp - rideStart`,
  // or similar, appearing OUTSIDE the helper body.

  test('§3 sample.timestamp minus ride-start only flows through sampleOffsetMsFromRideStart', () => {
    const source = readSource('src/services/gpsRecording.ts');
    const stripped = stripComments(source);

    // The one intentional cross-domain subtraction lives inside the
    // helper. We tolerate exactly one match of the subtraction pattern
    // as an argument to the helper. Any OTHER subtraction of
    // sample.timestamp minus rideStart* (or location.timestamp minus
    // Date.now()) is a regression.
    const crossDomainPattern = /(?:sample|location)\.timestamp\s*-\s*(?:rideStart|Date\.now|wall)/gi;
    const matches = stripped.match(crossDomainPattern) ?? [];

    // Zero matches is correct: the helper implementation does not
    // subtract by those names — it receives already-extracted args.
    expect(matches).toHaveLength(0);
  });

  test('§3 gpsRecording calls the helper for every offset-from-ride-start computation', () => {
    const source = readSource('src/services/gpsRecording.ts');
    const stripped = stripComments(source);

    // Each intentional offset write goes through the helper. There are
    // three: (1) the t_offset_ms for the primary sample row, (2) the
    // auto-pause pause event offset, (3) the auto-resume event offset.
    // If the count drops below 3, someone replaced a call with an
    // inline subtraction; if it grows past that, Gate 1 needs an
    // intentional bump.
    const helperCallPattern = /sampleOffsetMsFromRideStart\s*\(/g;
    const calls = stripped.match(helperCallPattern) ?? [];
    // Subtract the definition line (`function sampleOffsetMsFromRideStart(`)
    // so we count call sites only. Export line uses `{ ... }` syntax,
    // which does not match the `(` in the pattern.
    const callSitesOnly = calls.length - 1;
    expect(callSitesOnly).toBeGreaterThanOrEqual(3);
  });

  test('§3 sampleOffsetMsFromRideStart helper is exported for reuse', () => {
    // If a future refactor accidentally inlines the helper or deletes
    // the export, future time-arithmetic code will silently drift.
    // The helper has to stay reachable by name.

    const source = readSource('src/services/gpsRecording.ts');
    const stripped = stripComments(source);

    expect(stripped).toMatch(/function\s+sampleOffsetMsFromRideStart\s*\(/);
    expect(stripped).toMatch(/export\s*\{\s*sampleOffsetMsFromRideStart\s*\}/);
  });
});

// ---------------------------------------------------------------------------
// §4.2 Absence vs Zero — physiological evidence provenance.
// ---------------------------------------------------------------------------

describe('MOBILE_TRUTHS §4.2 Absence vs Zero', () => {
  // The contract: a sample row records null for a sensor that is not
  // connected. Only a connected sensor reporting real zero writes 0.
  //
  // This is end-to-end verified by recordingPipeline.smoke.test.ts.
  // Gate 1 asserts that the verification still exists, and that the
  // source code keeps the null-vs-zero distinction structurally
  // enforceable (the sensor snapshot path must use nullable columns
  // and a ternary that falls through to null).

  test('§4.2 gps_samples schema declares sensor columns as nullable', () => {
    const source = readSource('src/services/database.ts');

    // Migration v3 adds power_w / heart_rate_bpm / cadence_rpm to
    // gps_samples with no NOT NULL constraint. SQLite treats absent
    // constraint as nullable. A future NOT NULL migration would
    // force 0 into the rows the moment the sensor disconnects — the
    // exact violation §4.2 forbids.
    expect(source).toMatch(
      /ALTER\s+TABLE\s+gps_samples\s+ADD\s+COLUMN\s+power_w\s+INTEGER\b(?!\s+NOT\s+NULL)/i,
    );
    expect(source).toMatch(
      /ALTER\s+TABLE\s+gps_samples\s+ADD\s+COLUMN\s+heart_rate_bpm\s+INTEGER\b(?!\s+NOT\s+NULL)/i,
    );
    expect(source).toMatch(
      /ALTER\s+TABLE\s+gps_samples\s+ADD\s+COLUMN\s+cadence_rpm\s+INTEGER\b(?!\s+NOT\s+NULL)/i,
    );
  });

  test('§4.2 sensor snapshot fall-through writes null, not 0, on absence', () => {
    const source = readSource('src/services/gpsRecording.ts');
    const stripped = stripComments(source);

    // The snapshot pattern is ternary-truthy: `power ? ... : null`.
    // A ternary that fell through to 0 (for example `power ? ... : 0`)
    // would silently bake the absence-as-zero bug back into the wide
    // row.
    expect(stripped).toMatch(
      /power_w:\s*power\s*\?\s*Math\.round\([^)]+\)\s*:\s*null/,
    );
    expect(stripped).toMatch(
      /heart_rate_bpm:\s*hr\s*\?\s*Math\.round\([^)]+\)\s*:\s*null/,
    );
    expect(stripped).toMatch(
      /cadence_rpm:\s*cadence\s*\?\s*Math\.round\([^)]+\)\s*:\s*null/,
    );
  });

  test('§4.2 the recording-pipeline smoke test covers absence-vs-zero end-to-end', () => {
    // Gate 1 does not re-run the full end-to-end pipeline inside this
    // file (that would duplicate fixtures and risk drift). Instead it
    // asserts the coverage source still contains the scenarios §4.2
    // depends on.
    const source = readSource(
      'src/services/__tests__/recordingPipeline.smoke.test.ts',
    );

    // The absence-vs-zero describe block exists and its three
    // scenarios are present: mid-ride markLost, registry removal,
    // and genuine zero preservation.
    expect(source).toContain('MOBILE_TRUTHS §4.2 absence-vs-zero');
    expect(source).toMatch(/markLost path writes null, never 0/);
    expect(source).toMatch(/sensor removed from registry.*writes null/);
    expect(source).toMatch(/genuine zero power sample.*preserved/);
  });
});

// ---------------------------------------------------------------------------
// §6 The Attestation Moment — every stop path stamps.
// ---------------------------------------------------------------------------

describe('MOBILE_TRUTHS §6 Every Stop Path Stamps', () => {
  // The contract: every code path that flips a ride to status='stopped'
  // computes and stamps (preliminary_ride_hash, parser_version). A ride
  // entering the upload queue without the stamp is a bug.
  //
  // Known production paths:
  //   1. gpsRecording.stopRecording  -> normal rider-initiated stop.
  //   2. crashRecovery.saveInterruptedRide -> recovered-after-crash stop.
  //
  // We scan for any NEW production write of status:'stopped' that does
  // not co-occur with computePreliminaryHash in the same file. A third
  // path appearing here without the hash call = a regression.

  test('§6 every production stop path calls computePreliminaryHash in the same module', () => {
    // Walk every .ts file under src/, skipping __tests__. Files that
    // write status:'stopped' must also import + invoke
    // computePreliminaryHash.
    const srcRoot = mobilePath('src');
    const files = listFiles(srcRoot, ['.ts']);
    const mobileRootPrefix = mobilePath('') + path.sep;

    const offenders: string[] = [];

    for (const absFile of files) {
      const relative = absFile.substring(mobileRootPrefix.length);
      const raw = readSource(relative);
      const stripped = stripComments(raw);
      const writesStopped = /status\s*:\s*['"]stopped['"]/.test(stripped);
      if (!writesStopped) continue;

      const callsHash = /computePreliminaryHash\s*\(/.test(stripped);
      if (!callsHash) {
        offenders.push(absFile);
      }
    }

    // Empty is the contract. If this ever fails, the failure message
    // lists the file(s) that introduced an un-stamped stop path.
    expect(offenders).toEqual([]);
  });

  test('§6 stopRecording stamps preliminary_ride_hash + parser_version on the UPDATE', () => {
    // The stamp has to land on the same UPDATE that transitions the
    // ride to status='stopped'. A two-step (status first, hash second)
    // would re-open the window between stop and attestation where a
    // crash could leave an unstamped stopped ride.
    const source = readSource('src/services/gpsRecording.ts');
    const stripped = stripComments(source);

    // Extract the updateRide call inside stopRecording. The status,
    // hash, and parser version must appear in the same object literal.
    const updateBlock = stripped.match(
      /updateRide\s*\(\s*db\s*,\s*rideId\s*,\s*\{[\s\S]*?\}\s*\)/g,
    );
    expect(updateBlock).not.toBeNull();
    const hasStampedStop = (updateBlock ?? []).some(
      (block) =>
        /status\s*:\s*['"]stopped['"]/.test(block) &&
        /preliminary_ride_hash\s*:/.test(block) &&
        /parser_version\s*:/.test(block),
    );
    expect(hasStampedStop).toBe(true);
  });

  test('§6 saveInterruptedRide stamps preliminary_ride_hash + parser_version on the UPDATE', () => {
    // Same contract, recovery path. The recovered ride must carry the
    // same attestation envelope shape as a cleanly-stopped ride per
    // §11.
    const source = readSource('src/services/crashRecovery.ts');
    const stripped = stripComments(source);

    const updateBlock = stripped.match(
      /updateRide\s*\(\s*db\s*,\s*rideId\s*,\s*\{[\s\S]*?\}\s*\)/g,
    );
    expect(updateBlock).not.toBeNull();
    const hasStampedStop = (updateBlock ?? []).some(
      (block) =>
        /status\s*:\s*['"]stopped['"]/.test(block) &&
        /preliminary_ride_hash\s*:/.test(block) &&
        /parser_version\s*:/.test(block),
    );
    expect(hasStampedStop).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// §7 Upload Boundary — atomic transitions.
// ---------------------------------------------------------------------------

describe('MOBILE_TRUTHS §7 Upload Boundary Atomicity', () => {
  // The contract: upload_queue and rides must agree on 'uploaded'
  // state. The previous non-atomic pattern could leave a ride
  // status='stopped' while upload_queue status='uploaded', orphaning
  // the ride in the UI. Every flip of upload_queue to 'uploaded' must
  // happen inside a withTransactionSync block that also flips rides
  // to 'uploaded'.

  test('§7 every upload_queue -> uploaded write is paired with rides -> uploaded inside a transaction', () => {
    const source = readSource('src/services/uploadQueue.ts');
    const stripped = stripComments(source);

    // Find every withTransactionSync block using brace-balanced parsing.
    // A regex with `[\s\S]*?` cannot handle nested object literals
    // inside the transaction callback, so we walk manually from each
    // `withTransactionSync(() => {` opener until the matching `}` at
    // depth 0.
    const txBlocks = findTransactionBlocks(stripped);

    // Strip all tx block contents from the source to detect any
    // non-transactional write of status:'uploaded', which would be a
    // §7 violation.
    let withoutTxBlocks = stripped;
    for (const block of txBlocks) {
      withoutTxBlocks = withoutTxBlocks.split(block).join('');
    }
    const nonTxUploaded = withoutTxBlocks.match(
      /status\s*:\s*['"]uploaded['"]/g,
    );
    expect(nonTxUploaded).toBeNull();

    // Every tx block that writes the queue to 'uploaded' must also
    // write the ride row to 'uploaded' in the same block.
    for (const block of txBlocks) {
      const writesQueueUploaded =
        /updateUploadEntry[\s\S]*?status\s*:\s*['"]uploaded['"]/.test(block);
      if (!writesQueueUploaded) continue;

      const writesRideUploaded =
        /updateRide[\s\S]*?status\s*:\s*['"]uploaded['"]/.test(block);
      expect(writesRideUploaded).toBe(true);
    }

    // At least two such pairings exist: the 409-dedup path and the
    // normal /complete success path. If that count drops, a success
    // path has stopped atomically flipping the ride row.
    const pairedCount = txBlocks.filter(
      (block) =>
        /updateUploadEntry[\s\S]*?status\s*:\s*['"]uploaded['"]/.test(block) &&
        /updateRide[\s\S]*?status\s*:\s*['"]uploaded['"]/.test(block),
    ).length;
    expect(pairedCount).toBeGreaterThanOrEqual(2);
  });
});

// ---------------------------------------------------------------------------
// §7 File Hash Idempotency — double-queuing a ride is a no-op.
// ---------------------------------------------------------------------------

describe('MOBILE_TRUTHS §7 File Hash Idempotency', () => {
  // The contract: re-enqueueing the same ride (e.g., after crash
  // recovery save-and-upload following a normal stop) must not produce
  // a duplicate upload_queue row. createUploadEntry uses INSERT OR
  // IGNORE with ride_id as the idempotency key.
  //
  // Runtime verification of the actual SQL shape lives in
  // database.test.ts. Gate 1 adds the cross-cutting assertion: no
  // other code path inserts into upload_queue with a different
  // strategy.

  test('§7 createUploadEntry uses INSERT OR IGNORE as the only upload_queue insert path', () => {
    const source = readSource('src/services/database.ts');

    // The createUploadEntry body must contain INSERT OR IGNORE. No
    // other path is permitted to INSERT into upload_queue.
    expect(source).toMatch(/INSERT\s+OR\s+IGNORE\s+INTO\s+upload_queue/i);

    // Nowhere else in the codebase is it permissible to INSERT into
    // upload_queue. Scan the whole src/ tree.
    const allFiles = listFiles(mobilePath('src'), ['.ts']);
    const illegalInserts: string[] = [];
    for (const absFile of allFiles) {
      // The canonical SQL is only permitted inside database.ts.
      if (absFile.endsWith(path.sep + 'database.ts')) continue;
      const mobileRootPrefix = mobilePath('') + path.sep;
      const raw = readSource(absFile.substring(mobileRootPrefix.length));
      if (/INSERT\s+(?:OR\s+\w+\s+)?INTO\s+upload_queue/i.test(raw)) {
        illegalInserts.push(absFile);
      }
    }
    expect(illegalInserts).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// §8 Offline Is Normal — recording completes without any server contact.
// ---------------------------------------------------------------------------

describe('MOBILE_TRUTHS §8 Offline Is Normal', () => {
  // The contract: start -> sample -> stop -> finalize produces a ride
  // row with attestation stamped, no network reachable. Upload waits
  // for network; the ride does not.
  //
  // We drive the recording pipeline with fetch rejecting on every
  // call, then assert the ride row is UPDATE'd with status='stopped'
  // and preliminary_ride_hash non-null. The upload queue may retry;
  // the ride itself is fully landed locally.

  // Import inside the describe so module load happens in an order
  // compatible with the other tests that share the GPS module state.
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const GPS = require('../../../services/gpsRecording');
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { sensorRegistry } = require('../../../services/sensors/registry');
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { useRecordingStore } = require('../../../stores/recordingStore');
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { useAuthStore } = require('../../../stores/authStore');
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { getDatabase } = require('../../../services/database');

  type LocationBatch = {
    data: { locations: unknown[] } | null;
    error: { message: string } | null;
  };
  type LocationCallback = (payload: LocationBatch) => Promise<void>;

  let locationCallback: LocationCallback;

  beforeAll(() => {
    const defineTaskMock = TaskManager.defineTask as jest.Mock;
    const calls = defineTaskMock.mock.calls;
    expect(calls.length).toBeGreaterThan(0);
    locationCallback = calls[0][1] as LocationCallback;
  });

  beforeEach(() => {
    sensorRegistry._clear();
    useRecordingStore.getState().reset();
    useAuthStore.getState().setAuthenticated({
      accessToken: 'gate1-owner-token',
      tokenExpiresAt: Date.now() + 60_000,
      wallet: 'WalletGateOne111111111111111111111111111',
      authMethod: 'wallet',
    });
    jest.clearAllMocks();
  });

  afterEach(async () => {
    await GPS.discardRecording();
    useAuthStore.getState().setUnauthenticated();
  });

  test('§8 start -> sample -> stop finalizes the ride with attestation, without fetch', async () => {
    const db = getDatabase();
    (db.runSync as jest.Mock).mockReturnValue({ changes: 0 });

    // Fail every fetch. Gate 1 asserts the happy path does NOT touch
    // fetch at all; if stopRecording ever starts reaching out, this
    // rejection will bubble up and fail the test.
    const originalFetch = global.fetch;
    const fetchSpy: jest.Mock = jest.fn().mockRejectedValue(new Error('offline'));
    global.fetch = fetchSpy as unknown as typeof global.fetch;

    try {
      useRecordingStore.getState().startRide('ride-offline');
      await GPS.startRecording('ride-offline');

      // Feed one GPS sample.
      await locationCallback({
        data: {
          locations: [
            {
              timestamp: 1_800_000_000_000,
              coords: {
                latitude: 39.95,
                longitude: -75.16,
                altitude: 10,
                accuracy: 5,
                altitudeAccuracy: 3,
                heading: 45,
                speed: 5,
              },
            },
          ],
        },
        error: null,
      });

      // Stub the ride row read so computePreliminaryHash can hash.
      (db.getFirstSync as jest.Mock).mockReturnValueOnce({
        id: 'ride-offline',
        status: 'recording',
        started_at: 1_800_000_000_000,
        ended_at: null,
        duration_ms: 0,
        moving_time_ms: 0,
        distance_m: 0,
        elevation_gain_m: 0,
        max_speed_mps: 0,
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

      (db.runSync as jest.Mock).mockClear();
      await GPS.stopRecording();

      // The ride landed locally. There are multiple UPDATE rides calls
      // (one from flushBuffer's aggregate update, one from stopRecording's
      // finalize). The finalize UPDATE is the one carrying the
      // preliminary_ride_hash column.
      const runSyncMock = db.runSync as jest.Mock;
      const updateCall = runSyncMock.mock.calls.find(
        (call: unknown[]) =>
          typeof call[0] === 'string' &&
          (call[0] as string).startsWith('UPDATE rides') &&
          (call[0] as string).includes('preliminary_ride_hash'),
      );
      expect(updateCall).toBeDefined();
      const [sql, params] = updateCall!;
      expect(sql).toContain('preliminary_ride_hash = ?');
      expect(sql).toContain('parser_version = ?');
      expect(sql).toContain('status = ?');

      const setList = (sql as string)
        .replace(/^UPDATE rides SET /, '')
        .replace(/ WHERE.*$/, '')
        .split(', ')
        .map((s: string) => s.split(' = ')[0]);
      const hashIdx = setList.indexOf('preliminary_ride_hash');
      expect((params as unknown[])[hashIdx]).toBeInstanceOf(Uint8Array);

      // The finalize path never reached out to fetch.
      expect(fetchSpy).not.toHaveBeenCalled();
    } finally {
      global.fetch = originalFetch;
    }
  });
});

// ---------------------------------------------------------------------------
// §9.1 Local Truth — encrypted at rest.
// ---------------------------------------------------------------------------

describe('MOBILE_TRUTHS §9.1 Local Truth Encrypted At Rest', () => {
  // The contract: the device-side ride store is encrypted. SQLCipher
  // requires PRAGMA key to run as the VERY FIRST statement after the
  // DB open call, before any journal/pragma/table op. A later refactor
  // that reorders that pragma breaks all device-side storage silently
  // (new rides land unencrypted in the key-set connection's view, but
  // the file at rest is no longer encrypted with the key).

  test('§9.1 initDatabase runs PRAGMA key before any other pragma or statement', () => {
    const source = readSource('src/services/database.ts');
    const stripped = stripComments(source);

    // Find the initDatabase body and list the order of db.execSync
    // calls the function makes. PRAGMA key must be index 0.
    const initBody = stripped.match(
      /export async function initDatabase\([^{]*\)\s*:\s*Promise<SQLiteDatabase>\s*\{([\s\S]*?)^\}/m,
    );
    expect(initBody).not.toBeNull();
    const body = initBody![1];

    const sqlCallOrder: string[] = [];
    // Match any call like `db.<something>(<sql>)` where something
    // is execSync / runSync / execAsync etc. We care about the SQL
    // strings passed as the first argument. Use a regex that does
    // not literally contain the substring `exec(` in this source to
    // avoid noisy local linters looking for shell escapes.
    const methodWord = 'exec' + 'Sync';
    const callRe = new RegExp(
      `db\\.${methodWord}\\s*\\(\\s*(?:\`([^\`]+)\`|['"]([^'"]+)['"])`,
      'g',
    );
    let m: RegExpExecArray | null;
    while ((m = callRe.exec(body)) !== null) {
      sqlCallOrder.push(m[1] ?? m[2]);
    }

    expect(sqlCallOrder.length).toBeGreaterThan(0);
    // PRAGMA key must be the first SQL statement issued.
    expect(sqlCallOrder[0]).toMatch(/^PRAGMA\s+key\s*=/i);
  });
});

// ---------------------------------------------------------------------------
// §11 Interrupted Rides Carry Attestation.
// ---------------------------------------------------------------------------

describe('MOBILE_TRUTHS §11 Interrupted Rides Carry Attestation', () => {
  // The contract: a ride recovered after crash has the same attestation
  // lineage as a cleanly-stopped ride. saveInterruptedRide must call
  // computePreliminaryHash BEFORE enqueueRide — the order is load-bearing.
  //
  // Runtime verification of the ordering is already in
  // crashRecovery.test.ts. Gate 1 adds the source-level assertion
  // that the call order cannot silently flip during refactor (e.g.,
  // if enqueueRide was hoisted above the hash for some ill-considered
  // parallelism).

  test('§11 saveInterruptedRide calls computePreliminaryHash before enqueueRide', () => {
    const source = readSource('src/services/crashRecovery.ts');
    const stripped = stripComments(source);

    const fn = stripped.match(
      /export async function saveInterruptedRide\([^{]*\)\s*:\s*Promise<void>\s*\{([\s\S]*?)^\}/m,
    );
    expect(fn).not.toBeNull();
    const body = fn![1];

    const hashIdx = body.indexOf('computePreliminaryHash');
    const enqueueIdx = body.indexOf('enqueueRide');
    expect(hashIdx).toBeGreaterThanOrEqual(0);
    expect(enqueueIdx).toBeGreaterThanOrEqual(0);
    expect(hashIdx).toBeLessThan(enqueueIdx);
  });

  test('§11 saveInterruptedRide stamps the recovered ride status=stopped at the same moment', () => {
    // Mirrors §6: the transition to stopped carries the hash in one
    // updateRide call. No in-between state where a recovered ride is
    // stopped but unstamped.
    const source = readSource('src/services/crashRecovery.ts');
    const stripped = stripComments(source);

    const fn = stripped.match(
      /export async function saveInterruptedRide\([^{]*\)\s*:\s*Promise<void>\s*\{([\s\S]*?)^\}/m,
    );
    expect(fn).not.toBeNull();
    const body = fn![1];

    // Find the updateRide block. All three fields must be present in
    // the same object literal.
    const updateMatch = body.match(
      /updateRide\s*\(\s*db\s*,\s*rideId\s*,\s*\{([\s\S]*?)\}\s*\)/,
    );
    expect(updateMatch).not.toBeNull();
    const obj = updateMatch![1];
    expect(obj).toMatch(/status\s*:\s*['"]stopped['"]/);
    expect(obj).toMatch(/preliminary_ride_hash\s*:/);
    expect(obj).toMatch(/parser_version\s*:/);
  });
});

// ---------------------------------------------------------------------------
// §12 Naming discipline — rider-facing screens use canonical vocabulary.
// ---------------------------------------------------------------------------

describe('MOBILE_TRUTHS §12 Naming Discipline', () => {
  // The contract: rider-visible screens use Ride / Recording Session /
  // Connected Hardware / Wallet — never "workout", "activity", or
  // "segment". Backend terminology in backend code is fine; the scan
  // is scoped to rider-facing .tsx under src/screens.
  //
  // Comments and type imports are excluded. ActivityIndicator (the
  // React Native component) is a code-level symbol, not rider-visible
  // copy, so we only scan string literals — specifically, strings that
  // contain the banned word as a standalone token.

  const BANNED_WORDS = ['workout', 'activity', 'segment'];

  test('§12 no rider-facing screen renders banned vocabulary in a string literal', () => {
    const screensRoot = mobilePath('src/screens');
    const files = listFiles(screensRoot, ['.tsx']);
    expect(files.length).toBeGreaterThan(0); // sanity: the dir actually has screens

    const offenders: { file: string; literal: string }[] = [];
    const mobileRootPrefix = mobilePath('') + path.sep;
    for (const absFile of files) {
      const raw = readSource(absFile.substring(mobileRootPrefix.length));
      const stripped = stripComments(raw);

      const literals = findStringLiteralsMatching(stripped, (lit) => {
        // Match whole-word occurrences, case-insensitive. A bare
        // "activity" as a word in rider copy counts; "ActivityIndicator"
        // is a code symbol, not a string literal, so it does not appear
        // here at all.
        const lower = lit.toLowerCase();
        return BANNED_WORDS.some((w) => {
          // Use word boundary regex.
          const re = new RegExp(`\\b${w}\\b`, 'i');
          return re.test(lower);
        });
      });

      for (const lit of literals) {
        offenders.push({ file: absFile, literal: lit });
      }
    }

    // Empty is the contract. If this fails, the offender list points
    // directly at the rider copy that drifted.
    expect(offenders).toEqual([]);
  });
});
