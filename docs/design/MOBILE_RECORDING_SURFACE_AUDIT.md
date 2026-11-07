# Mobile Recording Surface — TRUTHS Alignment Audit

**Status:** AUDIT — research-only, no code changes yet
**Date:** 2026-04-15
**Scope:** `mobile/src/services/gpxExporter.ts`, `gpsValidation.ts` (actually in `lib/`), `database.ts`, `uploadQueue.ts`, `stores/recordingStore.ts` + schema migrations
**Measured against:** `docs/design/MOBILE_PROTOCOL_TRUTHS_CROSSWALK.md` §6.9 Obligations 1–5
**Companions:** `docs/PROTOCOL_TRUTHS.md` §5.2 (attested truth layer), §10 (privacy & verifiability boundary)

Two web research agents ran in parallel with the code reads. Their findings on canonical ride file hashing (Agent A) and mobile GPS validation / anti-tamper (Agent B) are woven in per obligation. Findings cite sources where the agents had them.

---

## Summary

**Where Boulder Rollers mobile sits against the 5 obligations:**

| # | Obligation | Current state | Phase A actionable? |
|---|---|---|---|
| 1 | Bit-for-bit reproducibility | **Partial** — GPX export works but embeds `creator="BoulderRoller Mobile ${APP_VERSION}"` which varies across versions; no canonical hash computed on device | Yes (audit + strip non-canonical fields) |
| 2 | Tamper-evident local storage | **Missing** — no `preliminary_ride_hash` column, no local canonicalization path, `fileHash` in upload queue is SHA256 of GPX file bytes (different thing) | Yes with backend bridge (Phase A), upgraded in Phase C with UniFFI |
| 3 | Parser version pinning | **Missing** — no `parser_version` column, no stamping at ride stop, upload queue doesn't send it | Yes (one-migration fix + `fl3n` workout-parse const export) |
| 4 | GPS integrity at recording time | **Baseline-weak** — 5 checks present but thresholds lax vs. industry; no `isSimulatedBySoftware` (iOS) check; no `isFromMockProvider` (Android) soft-suspect tagging | Yes (tighten thresholds + add platform checks) |
| 5 | Crash recovery preserves canonical integrity | **Mostly aligned** — WAL mode, transactional flushes, no interpolation across gaps, unique-active-ride constraint. Missing: `had_crash_recovery` breadcrumb | Minor (add breadcrumb column) |

**Highest-priority finding** — the mobile app's `fileHash` is **not** the canonical ride hash. It's `SHA256(gpxContent)` computed at upload time, and it varies across app versions because the GPX includes `creator="BoulderRoller Mobile ${APP_VERSION}"`. A rider holding their ride file cannot independently reproduce this hash on a newer app version. This is not a bug in the upload queue (it works fine for idempotency dedup), but it **is not the hash TRUTHS §10 wants.** The crosswalk §6.9 Obligation 2 assumes a `preliminary_ride_hash` that doesn't exist yet.

**Second-highest finding** — the accuracy gate `MAX_ACCURACY_M = 100` is roughly 3× lax vs. industry norm (Avenza's default is 32 m; Agent B couldn't find a published Strava/Garmin number). 50 m is the conservative middle-ground recommendation.

**Defensible state overall** — none of the gaps are catastrophic or block current shipping. All fit into the Phase A mobile work window (post-wdvr.6) except the UniFFI-native canonicalization which is explicitly Phase C.

---

## 1. Obligation 1: Bit-for-bit reproducibility

> Two recordings of the same ride on two devices must produce the same `ride_hash` if the underlying data is identical. Non-canonical fields (device IDs, export timestamps, random UUIDs, app version strings) must not affect the hash.

### 1.1 Current state — file-level

**`mobile/src/services/gpxExporter.ts:100`:**
```ts
gpx += `<gpx version="1.1" creator="BoulderRoller Mobile ${escapeXml(APP_VERSION)}"\n`;
```
The `creator` attribute embeds the runtime `APP_VERSION` constant. Two devices on different app versions produce different GPX file bytes for the same ride.

**`gpxExporter.ts:114`:**
```ts
gpx += `      <trkpt lat="${s.latitude.toFixed(7)}" lon="${s.longitude.toFixed(7)}">\n`;
```
GPS coordinates are serialized with **7 decimal places** (not 6 as the crosswalk spec implies). This is actually *more* precise than the canonical target, which is fine — the canonicalization layer will quantize down to 6 anyway — but it means **the GPX file bytes aren't directly hash-comparable with the canonical surface.**

**`gpxExporter.ts:156–159`:**
```ts
const fileHash = await Crypto.digestStringAsync(
  Crypto.CryptoDigestAlgorithm.SHA256,
  gpxContent,
);
```
The hash computed on mobile is `SHA256(gpxContent)` — the GPX file bytes. This is then used at `uploadQueue.ts:105` as the `file_hash` in the upload init request.

**What this `fileHash` is:** a server-side idempotency dedup key. Works fine for that.
**What this `fileHash` is NOT:** the canonical ride hash per TRUTHS §10. It's not reproducible by a rider holding the same ride file on a different app version. It's not what the backend should commit on-chain.

### 1.2 Industry research (Agent A)

Relevant Agent A findings:

- **RFC 8785 (JSON Canonicalization Scheme / JCS)** — [IETF link](https://datatracker.ietf.org/doc/html/rfc8785). The IETF standards-track canonical JSON spec. Because our canonicalization emits only integers and `null` (no floats), our output is a **JCS-compatible subset** — we should either adopt JCS explicitly or state that deviation in the spec, so independent verifiers can use off-the-shelf JCS libraries to reproduce our hash.
- **XML-C14N / XML-C14N-EXC1 is the wrong layer** for GPX hashing. Canonicalizing the wire XML produces different outputs for two tools exporting the same ride because it captures whitespace and namespace decls of the exporter. **Our decision to canonicalize the parsed surface, not the file bytes, is correct** — this is the lesson the XML-DSig community learned the hard way.
- **No published canonical FIT spec exists.** Different Garmin SDK versions, optional field inclusion, and `developer_data_id` ordering all produce different bytes for semantically identical FITs. **Our approach (canonicalize above the file layer) is the only correct path.**
- **FIT CRC is not cryptographically adequate.** CRC-16 is trivially forgeable and binds to file bytes rather than ride content. We need our own canonicalization layer on top. *Treat FIT CRC as a pre-filter for corruption, nothing more.*
- **Determinism pitfalls (§4 of Agent A report):** forbid `f32` anywhere in canonicalization; don't compute derived quantities inside canonicalization (haversine, speed, DEM lookups — their libm differs per platform); close the canonical struct so no extra fields can leak in; mandate NFC for any text fields.

### 1.3 Gap

The mobile app does not compute the canonical ride hash on device. It computes a file-level SHA256 of the GPX export which is a separate primitive. The gap is:

- **GPX `creator` attribute** breaks cross-version reproducibility at the file-bytes level (minor — file bytes aren't the canonical hash anyway)
- **No canonical hash is computed on device at all** (major — crosswalk §6.9 Obligation 2 assumes `preliminary_ride_hash` exists)
- **`fileHash` is confused with canonical hash** in the mental model — it's in a column called `file_hash` which is correct, but the upload architecture currently treats it as sufficient integrity evidence, which per TRUTHS §10 it is not

### 1.4 Phase A fix tasks

1. **Audit `gpxExporter.ts:99–106` metadata block** — decide whether to keep `creator` at all. Options:
   - (a) **Strip `creator` entirely** from the GPX export. Simplest. GPX 1.1 schema requires the `creator` attribute on `<gpx>` but accepts any value — can be `"BoulderRoller"` without version. Still required by XSD, but cross-version-stable.
   - (b) **Keep `creator` but exclude it from the canonical slice.** This is already the case *for the canonical hash* (which hasn't been built yet), since canonicalization acts on the parsed surface, not GPX bytes. But `fileHash` continues to be unstable across versions.
   - **Recommendation: (a)** — rename constant to `GPX_CREATOR = "BoulderRoller"` (drop version), commit that change. Has the side benefit of making `fileHash` actually cross-version stable.

2. **Add a cross-device reproducibility unit test.** Given two synthetic `RideRow` + `GPSSampleRow[]` inputs with identical sample data but different `APP_VERSION`, assert that `generateGPX()` produces byte-identical output. Currently would FAIL — gate the fix by having this test land green.

3. **Do not re-implement canonicalization on mobile yet.** Phase A does not require local canonicalization — Phase B (backend bridge) and Phase C (UniFFI native) handle it. What Phase A DOES need: the `preliminary_ride_hash` *column* (Obligation 2) so there's a place to put the hash once Phase B lands, plus stripping the non-canonical `creator` version field so the current `fileHash` becomes at least honest across versions.

4. **Update `docs/design/RIDE_CANONICALIZATION_SPEC.md`** (separate doc) to explicitly state: JCS-compatible subset, integers + null only, ASCII keys only, forbid f32 in canon path, closed canonical struct. This is Agent A recommendation #1.

5. **Cross-arch CI for the Rust crate** — add a job matrix running canonical hash vectors on x86_64 Linux, aarch64 macOS, aarch64 iOS simulator. Agent A recommendation #6. This is where platform determinism bugs hide.

---

## 2. Obligation 2: Tamper-evident local storage

> Between ride-stop and upload-success, the file must be tamper-resistant. Backend re-canonicalizes and compares against a preliminary hash the mobile app computed at stop time. Divergence is a first-class non-silent error state.

### 2.1 Current state

**`database.ts:28–107` migration v1 `rides` table:**
```sql
CREATE TABLE rides (
  id TEXT PRIMARY KEY,
  status TEXT,
  started_at INTEGER,
  ended_at INTEGER,
  duration_ms INTEGER,
  moving_time_ms INTEGER,
  distance_m REAL,
  elevation_gain_m REAL,
  max_speed_mps REAL,
  sport_type TEXT,
  clock_drift_ms INTEGER,
  sample_count INTEGER,
  rejected_samples TEXT,
  upload_id TEXT,
  notes TEXT,
  created_at INTEGER,
  updated_at INTEGER
)
```

No `preliminary_ride_hash` column. No `parser_version` column. No `had_crash_recovery` column.

**`upload_queue` table (database.ts:88–100) has `file_hash TEXT`** — this gets populated at `uploadQueue.ts:82` from `exportRideToGPX()` return value. But as discussed in Obligation 1, this is the GPX file SHA, not the canonical ride hash.

**SQLite is in app-sandboxed storage (iOS default, Android internal)** — Agent B notes this is baseline tamper-resistance. A non-rooted/non-jailbroken device can't easily modify the DB file outside the app sandbox. A jailbroken device can, but that's out of scope pre-TGE.

**WAL journal mode** (`database.ts:123`) gives us crash-safe atomicity. Good.

### 2.2 Industry research (Agent A)

- The verifiability pattern TRUTHS §10 wants has precedent in **C2PA content credentials** ([c2pa.org/specifications](https://c2pa.org/specifications/)) and the **IoTeX W3bstream** DePIN framework. Both follow: device signs raw sensor payload → verifier replays canonical transform → hash commits on-chain. We're doing the same shape.
- Critically: **Agent A found no published STEPN/Sweatcoin/Walken architecture doc on how they commit to ride files.** Speculation (flagged): their integrity boundary is "our phone SDK said so," not rider-verifiable canonical hashing. **If true, our approach is stronger than theirs.**
- **Closed canonical struct** pattern (Agent A recommendation #3) — canonicalization should take `&CanonicalRide`, never `&ParsedActivity` directly. Any extra fields on the parser output can't silently leak into the hash.

### 2.3 Gap

Three missing pieces:

1. **No `preliminary_ride_hash` column** on `rides` table.
2. **No path to compute canonicalized bytes on device** — neither native (UniFFI, Phase C) nor backend-bridged (Phase B).
3. **`uploadQueue.ts` treats `file_hash` as sufficient integrity evidence** — it isn't.

### 2.4 Phase A fix tasks

6. **Migration v2: add `preliminary_ride_hash BLOB(32)`, `parser_version INTEGER`, `had_crash_recovery INTEGER DEFAULT 0` columns to `rides` table.** One migration, three columns, all nullable initially so existing records aren't invalidated. Specific SQL:
   ```sql
   -- in database.ts MIGRATIONS array, version 2
   ALTER TABLE rides ADD COLUMN preliminary_ride_hash BLOB;
   ALTER TABLE rides ADD COLUMN parser_version INTEGER;
   ALTER TABLE rides ADD COLUMN had_crash_recovery INTEGER NOT NULL DEFAULT 0;
   ```

7. **Add `mobile/src/lib/preliminaryHash.ts`** — new module that wraps the backend `/rides/preliminary-hash` endpoint (Phase B work, not building that endpoint in Phase A). Interface-only, implementation stubbed to return `null` until the backend endpoint exists. When Phase B lands, swap implementation.

8. **Extend `uploadQueue.ts` upload init payload** to include `preliminary_ride_hash` and `parser_version` when they're set. Backend can accept them as optional fields initially and validate once re-canonicalization exists (Phase B).

9. **Add `RideReviewBanner.tsx`** stub component for the "ride under review" state (when backend re-canonicalization diverges from mobile preliminary hash). Phase A ships the component structure with the state placeholder; Phase B wires it into real upload flow.

10. **Defensive note:** under Phase A, with no local canonicalization, all rides are treated as "trusted" by construction. Phase B adds the compare. This is OK because pre-TGE fraud motivation is low — we're building the rails, not enforcing them yet.

---

## 3. Obligation 3: Parser version pinning

> Each ride file must be stamped with the parser version used to canonicalize it. Past rides remain verifiable against their original parser_version forever.

### 3.1 Current state

**No `parser_version` column on `rides` table.** No code stamps it at ride stop. Upload queue doesn't send it.

**`workout-parse/src/canonicalize.rs` has `parser_version: 1` hardcoded inline** at lines 104 and 191 (confirmed earlier in session). **There is no `pub const CURRENT_PARSER_VERSION: u32 = 1;` exported** — tracked as beads `fl3n`.

### 3.2 Research

- **Agent A:** versioning pattern is correct and well-precedented (Git object type tags, JWT `alg` header, Protobuf schema evolution). The key discipline is: **never retroactively re-canonicalize old versions, even on bug discovery.** If v1 has a bug, the bug becomes part of v1's definition and v2 fixes it — Ethereum's consensus-bug handling is the canonical reference. Agent A recommendation #9: "Write the bug-forward policy into the spec now, before you have a v1 bug."
- **Test vector freezing** — agent A recommendation #7: freeze canonical hash vectors as binary fixtures in `workout-parse/tests/vectors/v1/`, one per required vector. Never regenerate at test time. Pattern from NIST CAVP.

### 3.3 Gap

Simple 3-way gap:
- Migration needed (covered by task 6 above)
- `workout-parse::CURRENT_PARSER_VERSION` const export needed (covered by beads `fl3n`)
- Stamping logic needed at ride-stop (new Phase A task)

### 3.4 Phase A fix tasks

11. **Close beads `fl3n`** — add `pub const CURRENT_PARSER_VERSION: u32 = 1;` to `workout-parse/src/canonicalize.rs` and export through PyO3 bindings. Trivial. Can fold into any next workout-parse touch.

12. **Add `const CURRENT_PARSER_VERSION = 1` to `mobile/src/lib/preliminaryHash.ts`** as a compile-time mirror. When Phase C lands UniFFI, this reads from the native module instead — but the exported value must match. Add a CI cross-check script that reads both values and asserts equality.

13. **Stamp `parser_version` at ride-stop in `recordingStore.ts.stopRide()`** — extend the stop flow to write `parser_version = CURRENT_PARSER_VERSION` into the `rides` row. Currently `recordingStore.ts:107-111` just transitions state to `'stopping'`; this needs to cascade to a DB write.

14. **Write the bug-forward policy** into `docs/design/RIDE_CANONICALIZATION_SPEC.md` (separate doc, not this audit). One sentence: *"If a v1 canonicalization bug is discovered after shipping, v1 semantics are frozen including the bug; fixes ship as v2."* Agent A recommendation #9.

---

## 4. Obligation 4: GPS integrity at recording time

> Mobile validation rejects obviously-bad samples before SQLite write. Rules should match backend validation constants (workout-parse) so the same trace validates consistently on both sides.

### 4.1 Current state — mobile

**`mobile/src/lib/gpsValidation.ts` — five rejection checks (lines 51–84):**

| Check | Threshold | Status vs industry |
|---|---|---|
| Null island `(0,0)` | hard reject | ✅ Universal |
| Coord range `|lat|>90 || |lon|>180` | hard reject | ✅ Universal |
| Accuracy `> MAX_ACCURACY_M = 100` meters | hard reject | ⚠️ **Lax** — Avenza default is 32 m; industry median ≈ 50 m |
| Device-reported speed `> MAX_SPEED_MPS = 50` m/s | hard reject | ✅ Matches physics ceiling (180 km/h) |
| Time travel `timestamp <= lastAccepted` | hard reject | ✅ Universal |

**Missing vs what Agent B identified as industry practice:**

- **No HDOP check.** iOS doesn't expose HDOP. Android sometimes does via `ExtraInfo` bundle. Agent B notes this is a limitation we probably cannot overcome without native module work — deferred.
- **No acceleration sanity gate.** Agent B recommends `~6 m/s²` ceiling (Parkin & Rotheram 2010 physiological maximum). Currently no inter-sample accel check on mobile.
- **No altitude jump gate.** Vertical VAM record is ~0.58 m/s; 5 m/s sample-to-sample altitude delta is an obvious spike. No published cycling-app threshold but physically reasonable.
- **No min/max altitude sanity.** Reject below −500 m or above 9,000 m. Universal-but-unsourced sentinel bounds.
- **No `CLLocationSourceInformation.isSimulatedBySoftware` check on iOS 15+.** **This is a free Apple-first-party anti-spoof signal we are not consuming.** Source: [Apple docs](https://developer.apple.com/documentation/corelocation/cllocationsourceinformation). Agent B's highest-priority Phase A recommendation.
- **No Android `isFromMockProvider()` soft-suspect tagging.** Bypassable by Xposed/LSPosed modules but still worth capturing as a weak signal, not as a hard rejection.

### 4.2 Current state — backend (for symmetry check)

**`workout-parse/src/climb/utils.rs`** (referenced by agent B):
- `MAX_STEP_DISTANCE_M = 500` — 500 m cap on per-sample haversine distance (acts as a distance *inflation* ceiling, not sample-rejection)
- `JUNCTION_MIN_SPEED_MPS = 1.5` — stationary epsilon for GPS jitter suppression
- `is_valid_gps()` at ~line 400 — the backend-side validation function

**Mobile and backend validation are not perfectly symmetric.** Mobile rejects samples pre-storage; backend rejects samples pre-processing. If mobile accepts a sample that backend rejects (or vice versa), the canonical trace produced by backend canonicalization differs from what the rider thinks they recorded. This can cause `preliminary_ride_hash` (Phase B) to disagree with backend canonicalization legitimately — not because of tampering, but because the validation layers disagree.

**Example drift:** mobile accepts a sample with `accuracy_m = 80` (below 100m threshold). Backend's `is_valid_gps()` might drop it if `MAX_ACCURACY` is lower there. Hash mismatch. User sees "ride under review" for no reason.

### 4.3 Research (Agent B)

Headline numbers from Agent B's sourced table:

| Parameter | Industry value | Source |
|---|---|---|
| Accuracy reject | **32 m default (Avenza), 8–16 m high-precision** | [Avenza GPS Settings](https://support.avenzamaps.com/hc/en-us/articles/4961280327956-GPS-Settings) |
| HDOP reject | **>5 marginal, >10 poor** | [GIS Geography HDOP](https://gisgeography.com/gps-accuracy-hdop-pdop-gdop-multipath/) |
| Max cycling speed | **~25 m/s realistic, 50 m/s ceiling** | unsourced; pro downhill ~36 m/s per race reports |
| Max cycling accel | **~6 m/s² ceiling** | [Parkin & Rotheram 2010](https://www.sciencedirect.com/science/article/abs/pii/S0967070X10000399) |
| Min sample freq | **1 Hz** | [Garmin GPS Accuracy FAQ](https://support.garmin.com/en-US/?faq=aZc8RezeAb9LjCDpJplTY7) |

Agent B Phase A recommendations (zero cost):
- Tighten accuracy gate `100 → 50 m` (still lenient vs Avenza 32m, but conservative)
- Add inter-sample acceleration gate at 6 m/s²
- Add `CLLocationSourceInformation.isSimulatedBySoftware` check (iOS)
- Add `isFromMockProvider()` soft-suspect tag (Android)
- Add altitude bounds `−500 m to 9000 m`

Agent B Phase B / pre-TGE:
- Play Integrity + App Attest for app-binary attestation (not location attestation, but backstops "this GPS was reported by a trusted binary")
- Accelerometer/gyro fusion sanity check (simple thresholding, no ML needed until fraud motivation rises)

Agent B reference incidents:
- **STEPN SMAC** — Turing Score ML anti-cheat ([whitepaper link](https://whitepaper.stepn.com/running-module/anti-cheating-system)). Single-signal defenses collapsed within weeks; sensor fusion is the floor.
- **Sweatcoin** — ~65% of reported steps validated ([Sweatcoin verification doc](https://sweatco.in/verification-algorithm)). Pet-walks and joystick apps were the main attack class.

### 4.4 Gap

**Current state is defensible pre-TGE** but:
- 100 m accuracy gate is 3× lax vs industry baseline
- iOS free-win `isSimulatedBySoftware` signal not consumed
- Mobile/backend validation not provably symmetric — risk of legitimate hash divergence post-Phase-B
- No inter-sample sanity (accel, altitude jump)

### 4.5 Phase A fix tasks

15. **Tighten `gpsValidation.ts:37` — `MAX_ACCURACY_M = 100 → 50`.** One-liner. Update the comment to cite Avenza's 32 m default and our conservative middle ground. Mirror on backend side.

16. **Add `MAX_ACCEL_MPS2 = 6` sanity gate.** New check in `validateGPSSample()` that requires a previous sample pointer to compute. Current signature takes `lastAcceptedTimestamp: number` only; extend to `lastAccepted: GPSSample | null` so speed/delta-time can be computed. Reject if implied acceleration > 6 m/s². Cite Parkin & Rotheram 2010 in comment.

17. **Add `ALT_MIN_M = -500`, `ALT_MAX_M = 9000` sanity gate.** Reject samples with altitudes outside these bounds. Reasoned from physical reality (Dead Sea surface / Everest summit), unsourced but universal.

18. **Add iOS `CLLocationSourceInformation.isSimulatedBySoftware` check.** This requires native-module or Expo-location-module work to surface the flag into TS. Expo's `expo-location` may not expose it directly — verify before promising Phase A delivery. If Expo doesn't pass it through, flag as Phase B (native patch work).
   - **Action:** verify whether `expo-location` exposes the flag. If yes, consume it. If no, file an upstream issue or write a small native module under `mobile/src/native/`.

19. **Add Android `isFromMockProvider()` soft-suspect tagging.** Same expo-location question as iOS. If available, tag samples (don't reject — Agent B notes it's trivially bypassed but still a signal worth capturing). Write into the `rejected_samples` JSON counter as a new category like `mock_location_android` (soft, not rejected).

20. **Reconcile mobile/backend validation constants with a shared source.**
    - **Option (a):** hand-maintain identical constants in both TS and Rust with a CI test that asserts equality. Fragile.
    - **Option (b):** generate TS constants from a Rust source file at build time. Robust.
    - **Option (c):** use a shared JSON/YAML config that both sides read at startup. Adds a new dependency but clean.
    - **Recommendation: (a) with a test.** `mobile/src/lib/__tests__/gpsValidation.constants.test.ts` parses `workout-parse/src/climb/utils.rs` for the constant values (regex), compares against the TS constants, fails if they differ. No build-time codegen needed; CI catches drift.

21. **Extend `is_valid_gps()` in `workout-parse`** to match whatever mobile rejects. If mobile adds acceleration and altitude gates, backend must add them too.

---

## 5. Obligation 5: Crash recovery preserves canonical integrity

> Crash recovery must not introduce non-canonical differences. Interpolation across crash gaps would produce a different hash than a clean recording with the same GPS points.

### 5.1 Current state

**`database.ts:123` — WAL mode + `synchronous = NORMAL`.** Atomic per-transaction, crash-safe.

**`database.ts:54–55` — unique active ride constraint:**
```sql
CREATE UNIQUE INDEX idx_rides_active
  ON rides(status) WHERE status IN ('recording', 'paused')
```
Prevents two rides being simultaneously active. Good.

**`database.ts:231–236` — `getActiveRide()` returns the single active ride row** — recovery helper, good.

**`database.ts:277–325` — `flushSampleBatch()` is transactional** — batch insert + aggregate update in one `withTransactionSync` block. Good.

**Pause/resume handling (`gpxExporter.ts:56–96`)** — track segments are split at pause events via `pauseOffsets` set. Clean recording with a pause produces one-segment-with-gap or two-segments (depending on pause behavior). **No interpolation across gaps.** Good — this is the canonically-honest behavior per Agent A recommendation #4.

**`uploadQueue.ts:282–291` — stuck `uploading` entries are reset on crash recovery:**
```ts
const stuckEntries = getUploadEntriesByStatus(db, 'uploading');
for (const entry of stuckEntries) {
  updateUploadEntry(db, entry.id, {
    status: 'failed_retryable',
    attempt_count: entry.attempt_count + 1,
    ...
  });
}
```
Good — no stuck uploads, no duplicate uploads on restart.

**What's missing:** `had_crash_recovery` breadcrumb column on `rides`. If a ride is recovered from a mid-recording crash, that should be flagged for later diagnostic traceability. Today, recovered rides and clean rides are indistinguishable to post-hoc analysis.

### 5.2 Gap

Minor — the architecture is correct, just missing a diagnostic breadcrumb.

### 5.3 Phase A fix tasks

22. **Covered by task 6 above** — add `had_crash_recovery INTEGER NOT NULL DEFAULT 0` column in the same migration as Obligation 2's columns.

23. **Set the breadcrumb flag** in the recovery path. When `getActiveRide()` returns a non-null row on app launch (meaning the last session crashed mid-ride), mark `had_crash_recovery = 1` on that row before continuing recording. This is a new code path — currently the recording store has no recovery-on-launch flow. The `recordingStore.ts` state machine starts at `idle`; a recovery step needs to run before idle is entered, checking `getActiveRide()` and either resuming or offering the user a dialog.
   - **This is actually more than a breadcrumb** — it's the missing recovery-on-launch logic. Mark as higher priority than a simple column addition.

24. **Cross-recording reproducibility test.** Unit test: record 30s of samples, force-close the store mid-session, reopen, record 30s more, stop, export GPX. The final exported GPX should have 60s of samples with an honest gap at the crash point, and the canonical hash (once local hashing exists in Phase B/C) should equal a clean 60s recording with the same GPS points. Test can be stubbed for Phase A (the hash comparison waits for Phase C).

---

## 6. Cross-cutting findings (not obligation-specific)

### 6.1 `fileHash` confusion needs an explicit mental model fix

The current code uses `file_hash` (in `upload_queue`) and `fileHash` (in `gpxExporter.ts`) for what is **SHA256 of GPX file bytes**. That's a legitimate thing — a server-side dedup key — but the name invites confusion with the canonical ride hash TRUTHS talks about.

**Recommendation:** when Phase B adds `preliminary_ride_hash`, rename the existing `file_hash` column in `upload_queue` to `upload_dedup_hash` (or similar) to disambiguate. Two separate primitives:
- `rides.preliminary_ride_hash` — canonical, TRUTHS §10 rider-verifiability
- `upload_queue.upload_dedup_hash` — server-side idempotency dedup, not cryptographic commitment

**Phase A impact:** don't rename yet (working tree thrash). Add the new column under its new name in the Phase A migration, leave the existing `file_hash` alone, and plan the rename for a single PR when Phase B lands.

### 6.2 Upload flow already sends a `file_hash` — consider extending the endpoint contract

`uploadQueue.ts:103–107`:
```ts
body: JSON.stringify({
  file_type: 'gpx',
  file_hash: fileHash,
  file_size: fileSize,
}),
```
Backend `/rides/upload/init` already accepts `file_hash`. Extending to accept `parser_version` and `preliminary_ride_hash` is an additive change. The backend can accept them as optional for Phase A without doing anything with them, and wire the re-canonicalization compare in Phase B.

### 6.3 `exportRideToGPX` is called on upload, not on ride-stop

`uploadQueue.ts:79`:
```ts
const { filePath, fileHash, fileSize } = await exportRideToGPX(rideId);
```
GPX export currently happens at upload time, not at ride-stop time. This means **the preliminary hash cannot be computed until upload time** unless we also move the canonicalization/export forward.

**Two options:**
- **(a)** At ride-stop, export GPX + compute preliminary hash, store both → upload flow reads them. Uses disk at ride-stop.
- **(b)** At ride-stop, compute canonical hash directly from SQLite (without exporting GPX first) → store hash. Upload flow exports GPX on demand. Cleaner separation.

**Recommendation: (b).** The canonical hash shouldn't depend on GPX serialization at all — it should derive from the same parsed-surface data that `workout-parse::canonicalize()` would produce from the GPX. When the Phase B backend bridge endpoint `/rides/preliminary-hash` lands, it can accept a SQLite-exported JSON payload of samples + aggregates directly, no GPX round-trip needed. This is closer to how Agent A described the correct architecture: canonicalize above the file layer.

### 6.4 Mobile currently has no ride-time-vs-ingestion-time discipline

TRUTHS §6 (ride time is the economic clock) and crosswalk §6.9 Obligation 3 both insist on ride time being the authoritative timestamp. The mobile `rides.started_at` is wallclock at ride start. Sample `t_offset_ms` is monotonic offset. These are both ride-time, not upload-time. Good.

But the backend-to-chain flow needs to preserve this. When Phase B wires the RideAttestation to on-chain state, `completed_at` must come from `ride.started_at + duration_ms` (mobile wallclock), not from the moment the upload hits the backend. This is a backend concern, not mobile — just noting so it isn't lost.

### 6.5 Agent A suggests CBOR for v2+ if floats ever enter the canonical slice

Not a Phase A action item, but worth filing: if we ever add `power_w`, `heart_rate_bpm`, or other sensor fields that are naturally floats, **deterministic CBOR (RFC 8949 §4.2.1)** is more robust than JCS for number formatting. Our current "integers + null only" scheme sidesteps the problem entirely for `parser_version: 1`. If/when we bump to `parser_version: 2` to include sensor samples, CBOR is the likely right move.

---

## 7. Phased action list

### Phase A (post-wdvr.6, before mobile read-layer work) — 10 concrete tasks

**Recording surface tasks:**
1. Strip `${APP_VERSION}` from `gpxExporter.ts:100` `creator` attribute (task 1)
2. Add cross-device GPX reproducibility unit test (task 2)
3. Migration v2: add `preliminary_ride_hash`, `parser_version`, `had_crash_recovery` columns (task 6)
4. Stub `mobile/src/lib/preliminaryHash.ts` interface (task 7)
5. Extend `uploadQueue.ts` upload init payload to send new fields as optional (task 8)
6. Stub `RideReviewBanner.tsx` component for Phase B wiring (task 9)
7. Stamp `parser_version = CURRENT_PARSER_VERSION` at ride-stop in `recordingStore.ts` (tasks 12, 13)
8. Tighten `MAX_ACCURACY_M = 100 → 50` + add `MAX_ACCEL_MPS2 = 6` + altitude bounds (tasks 15, 16, 17)
9. Consume iOS `isSimulatedBySoftware` + Android `isFromMockProvider` (tasks 18, 19). **Gate on Expo-location passthrough verification.**
10. Constants symmetry test between `gpsValidation.ts` and `workout-parse/src/climb/utils.rs` (tasks 20, 21)
11. Recovery-on-launch logic + `had_crash_recovery` breadcrumb (task 23)
12. Cross-recording reproducibility unit test (stub hash compare for Phase A, wire in Phase C) (task 24)

**Orthogonal but in-scope:**
13. `fl3n`: export `CURRENT_PARSER_VERSION` const from `workout-parse` (task 11)

### Phase B (post-wdvr.7, backend-bridge canonicalization)

- Write backend `POST /rides/preliminary-hash` endpoint (receives GPX or SQLite JSON, returns canonical bytes + hash)
- Implement `mobile/src/lib/preliminaryHash.ts` against the bridge (swap stub for real impl)
- Wire `RideReviewBanner.tsx` into upload flow — divergence is a real path
- Extend `uploadQueue.ts` to actually pass `preliminary_ride_hash` and check backend's re-canonicalization response
- Add `useRideLifecycle` 3-phase state machine (uploaded/provisional/attested per crosswalk §6.8.6)

### Phase C (post-Privy/Sentry native prebuild)

- UniFFI native canonicalization module (xcframework + AAR + Expo config plugin)
- Replace backend-bridge `preliminaryHash.ts` impl with native module call
- True local verifiability — rider can recompute hash entirely offline
- Cross-recording reproducibility test wired to real hash compare

### Cross-cutting (not phase-gated)

- Update `docs/design/RIDE_CANONICALIZATION_SPEC.md` with JCS-compatible subset declaration, forbid-f32 rule, closed canonical struct discipline, bug-forward policy (Agent A recommendations #1, #3, #9)
- Cross-arch CI for `workout-parse` canonical hash vectors (x86_64 Linux + aarch64 macOS + aarch64 iOS sim) — Agent A recommendation #6
- Freeze hash test vectors as binary fixtures in `workout-parse/tests/vectors/v1/` — Agent A recommendation #7

---

## 8. What's explicitly NOT in scope for this audit

- **UI state machines for ride recording** — covered in Phase 0 docs, not relitigated
- **Authentication / session management** — Phase 0 resolved
- **NATS event backbone on backend** — out of mobile scope
- **Haptic / audio feedback during ride** — UX, not integrity
- **Battery impact of background GPS** — operational, not TRUTHS-aligned
- **Native canonicalization module itself** — Phase C, tracked in crosswalk §6.8.3
- **Backend canonicalization endpoint** — Phase B backend work
- **App attestation (Play Integrity, App Attest)** — Phase B+ per Agent B; deferred to pre-TGE window

---

## Appendix A: Files audited

Mobile source:
- `mobile/src/services/gpxExporter.ts` (190 lines) — GPX serialization + file hash
- `mobile/src/services/database.ts` (451 lines) — SQLite schema + CRUD + upload queue helpers
- `mobile/src/services/uploadQueue.ts` (373 lines) — upload queue processor
- `mobile/src/stores/recordingStore.ts` (149 lines) — Zustand state machine
- `mobile/src/lib/gpsValidation.ts` (96 lines) — 5-check GPS validator

Backend reference (cited, not edited):
- `workout-parse/src/climb/utils.rs` — backend validation constants
- `workout-parse/src/canonicalize.rs` — canonical serialization (already shipped per `df58b14a`)
- `backend/app/routes/rides.py` — upload init/complete endpoints (not audited in detail)

## Appendix B: Research artifacts

- **Agent A** (general-purpose subagent, ~130s runtime, 1480 words) — "Canonical Ride File Hashing — Research Findings." Topics: RFC 8785 JCS, XML-C14N, FIT CRC adequacy, cross-platform determinism pitfalls, parser versioning best practices. 10 recommendations.
- **Agent B** (general-purpose subagent, ~390s runtime, 1500 words) — "Mobile GPS Validation + Anti-Tamper — Research Findings." Topics: industry GPS validation thresholds with sources, STEPN/Sweatcoin anti-cheat state of the art, iOS/Android mock location APIs, Play Integrity + App Attest, known incidents. 10 recommendations (Phase A/B/C split).

Both research reports cite sources inline and flag speculation vs cited facts. Summary tables are reproduced in the relevant obligation sections above.

---

**End of audit.** This document is research-only — no mobile code was edited. The 24 tasks in §7 are ready to be filed as beads issues (recommend a new epic `mobile-recording-a1` as child of `dg98` when the protocol agent returns and clears mobile phase decomposition), but NOT created now because the decomposition itself is still gated on `dg98`'s protocol-agent review.
