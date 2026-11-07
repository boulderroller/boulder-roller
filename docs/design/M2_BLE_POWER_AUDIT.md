# M2 BLE Power Path Audit — First Slice

**Status:** HISTORICAL — Expo-era BLE audit
**Bead:** `boulderroller-v2-5hdl.2` — M2 BLE sensor pairing, power-first slice
**Date:** 2026-04-17
**Audience:** Any agent picking up the HR / cadence follow-on slice or
hardening the sensor lane on physical hardware
**Parent docs:**
- [MOBILE_TRUTHS](../MOBILE_TRUTHS.md) — §2.3 Connected Hardware, §4.2
  Physiological Evidence (absence vs zero), §5.2, §12 naming
- [HACKATHON_DEMO_SCRIPT](./HACKATHON_DEMO_SCRIPT.md) — Act 1 requires live
  power during recording

Current sensor semantics are governed by [MOBILE_TRUTHS.md](../MOBILE_TRUTHS.md), with the native lane described in [`ios/README.md`](../../ios/README.md).

---

## 1. Purpose

Record what the Cycling Power path looks like end-to-end, what the first
slice verified, and what remains for HR / cadence / physical-device
hardening. The next slice should not have to rediscover this surface.

This is the audit half of `5hdl.2`; the implementation half lands alongside.

---

## 2. End-to-end path, power-first

```
Device advertisement
  → BleSensorManager.startScan (filters on CYCLING_POWER_SERVICE + HR + CSC)
  → discovered device surfaces in usePairingStore.discovered
Rider taps Connect (PairingScreen)
  → usePairingStore.connect(deviceId, 'power', name)
  → bleSensorManager.connect
      → waitForPoweredOn (timeout 5s)
      → requestAndroidBlePermissions (SDK 31+ only)
      → connectToDevice (timeout 10s)
      → device.discoverAllServicesAndCharacteristics
      → new PowerMeterSource(device)
  → source.start()
      → monitorCharacteristicForService(0x1818/0x2A63) — measurement
      → monitorCharacteristicForService(0x1818/0x2A66) — control point
      → device.onDisconnected → markLost on drop
  → sensorRegistry.add(source)
  → pairingStore.connections[key] = { status: 'connected' }
  → pairingStore.known persisted to AsyncStorage

During ride:
  Each measurement notification → parsePowerMeasurement(bytes)
    → PowerSample stored in source.latest, lastReceivedAtMs stamped
  Each GPS tick from expo-location background task:
    → processLocationUpdate() in gpsRecording.ts
    → sensorRegistry.getLatestPower() (returns null if stale > 2000 ms)
    → power_w column written to gps_samples row (or null)

Disconnection paths converge on markLost():
  - User taps Disconnect → pairingStore.disconnect → source.stop()
  - BLE drop event → device.onDisconnected → source.markLost()
  - Adapter off (airplane mode, BT toggle) → onStateChange(!PoweredOn)
    → manager iterates registry → source.markLost()
  - App foreground sweep → bleSensorManager.auditStaleness()
    → any still-'connected' but stale source → markLost()
  - Logout → AuthInitializer watches auth state → disconnectAll()

markLost() is idempotent and clears both latest and the stale threshold
timestamp so getLatest() returns null cleanly — §4.2 absence-vs-zero holds.
```

---

## 3. What the first slice verified

### 3.1 Parser correctness (Cycling Power Measurement, char 0x2A63)

- Variable-length flags field parsed LE, RFU bits 13-15 masked via
  `FLAG_VALID_MASK = 0x1FFF` (early Stages/Quarq firmware known to dirty
  these bits)
- All 13 documented flag bits handled:
  - 0 Pedal Power Balance (uint8, ½% units)
  - 1 Balance reference (flag-only, left)
  - 2 Accumulated Torque (uint16, 1/32 Nm)
  - 3 Torque source (flag-only, crank vs wheel)
  - 4 Wheel Rev Data (uint32 + uint16)
  - 5 Crank Rev Data (uint16 + uint16)
  - 6 Extreme Force Magnitudes (2× int16) — mutex with 7
  - 7 Extreme Torque Magnitudes (2× int16 /32) — mutex with 6
  - 8 Extreme Angles (3 bytes packed 12-bit)
  - 9 Top Dead Spot (uint16 deg)
  - 10 Bottom Dead Spot (uint16 deg)
  - 11 Accumulated Energy (uint16 kJ)
  - 12 Offset Compensation (flag-only)
- Throws explicitly on packet shorter than 4 bytes
- Mutex between bits 6 and 7 honored (bit 6 wins if both set, defensive)
- Combined-field fixtures: Stages-typical, Favero dual-sided,
  all-flags-together (new in this slice), 4iiii/Quarq vendor bytes
  (new in this slice)

### 3.2 Stale detection and absence

- `STALE_TTL_MS = 2000` in `powerMeterSource.ts` (power meters advertise
  ~4 Hz, so 2 s = 8 missed samples)
- `getLatest()` returns `null` once `Date.now() - lastReceivedAtMs >
  STALE_TTL_MS` — MOBILE_TRUTHS §4.2 absence is preserved
- `isStale()` flips true under the same threshold but only after at least
  one sample has arrived. Pre-first-sample is "no data" not "lost data"

### 3.3 Disconnect paths

- `device.onDisconnected` listener fires markLost on unexpected BLE drop
- `bleSensorManager.onStateChange` fires markLost on every registered
  source when adapter leaves PoweredOn
- `bleSensorManager.auditStaleness()` runs on app foreground
  (AuthInitializer AppState subscription); flips connected-but-silent
  sources to lost and emits a Sentry breadcrumb so we can tell empirically
  whether iOS background suspension is biting us
- `pairingStore.disconnectAll()` runs on logout via AuthInitializer
  subscription to auth state transitions; clears transient discovery
  state too so the next rider doesn't inherit a stale session

### 3.4 Pairing persistence

- Zustand `persist` middleware writes `known` (list of KnownDevice) to
  AsyncStorage under key `pairing`; discovered / connections / scanning
  are not persisted (rebuilt on next launch via `reconnectKnown()`)
- `reconnectKnown()` does nothing if `known.length === 0` — avoids the
  iOS BLE permission prompt for users who never opened pairing
- Sequential reconnect (not parallel) because some BLE stacks flake on
  parallel connects; all-fail emits a Sentry breadcrumb so we can tell
  "no sensors paired" from "everything failed"

### 3.5 End-to-end recording integration

- `recordingPipeline.smoke.test.ts`:
  - GPS-only ride → all three sensor columns null on every row
  - Power meter paired → power_w populated, cadence derived from crank
    revs also populated, HR remains null
  - Power + HR paired → both columns populated on the merged row
  - Power-embedded cadence wins over a dedicated CSC source (avoids
    double-counting)
  - CSC-only source provides cadence when no power meter
  - Sensor stopped mid-ride → subsequent rows have null power (§4.2
    absence-vs-zero, verified via assertion not "looks right")

---

## 4. Permission config

### 4.1 Android

`app.config.ts` declares the full Android 12+ BLE permission set:

- `ACCESS_FINE_LOCATION`, `ACCESS_COARSE_LOCATION`,
  `ACCESS_BACKGROUND_LOCATION` (location)
- `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_LOCATION` (ride recording)
- `POST_NOTIFICATIONS` (foreground service notification)
- `BLUETOOTH`, `BLUETOOTH_CONNECT`, `BLUETOOTH_SCAN` (BLE)

Runtime prompts for `BLUETOOTH_SCAN` + `BLUETOOTH_CONNECT` are handled in
`bleSensorManager.ts` on Android API 31+ before startScan or connect.
`waitForPoweredOn` handles cold-start when adapter state is still
Unknown.

### 4.2 iOS

`app.config.ts` declares:

- `NSLocationWhenInUseUsageDescription` (location)
- `NSLocationAlwaysAndWhenInUseUsageDescription` (background location)
- `UIBackgroundModes: ['location']` — plus `bluetooth-central` auto-added
  by the `react-native-ble-plx` Expo config plugin when
  `isBackgroundEnabled: true`
- `NSBluetoothAlwaysUsageDescription` auto-added by the same plugin

`app.json` (legacy file, superseded by app.config.ts but still on disk)
has been brought back into sync so a reviewer glancing at app.json does
not see drift.

---

## 5. What's still missing (follow-on slices)

### 5.1 Sensor source provenance on each sample row (§2.3)

MOBILE_TRUTHS §2.3 says the app records what was connected. Today the
`power_w` column holds the instantaneous value but the sample row does
not record which device produced it. A single ride could switch power
meters mid-way (rare but legal — a rider might pair a trainer and a
pedal-based meter on the same session) and the ride would not record
which measurement came from which source.

Follow-on: add a ride-level or ride-scoped-sensor-session record that
captures `(ride_id, kind, device_id, device_name, first_seen_t_offset_ms,
last_seen_t_offset_ms)`. That schema lands in a later slice — noted
here so the HR slice doesn't forget it.

### 5.2 HR profile (0x180D) — COMPLETE (2026-04-17)

- `heartRateSource.ts` + `parsers/heartRateMeasurement.ts` are
  implemented at the same quality bar as the power path (stale TTL
  3000 ms, markLost on disconnect, RR intervals pass through for HRV)
- Registry and recording pipeline already merge HR into the wide row
- **Parser coverage extended** with vendor byte-vector fixtures
  (Polar H10 3-RR HRV packet, Garmin HRM-Dual with energy expended,
  Wahoo TICKR sweaty/poor-contact case, Magene H64 optical, Xiaomi
  generic, Garmin HRM-Pro Plus 4-RR high-HR packet, Polar OH1 optical
  16-bit HR) plus boundary cases (empty, single byte, flag-only demand,
  max values, truncated RR tail, 8-RR upper bound, RFU-bit tolerance)
- **Source-level parity** with power slice: idempotent `markLost`,
  `isStale` pre-first-sample false, disconnection clears cache to null
  not zero-object, stray error after disconnect does not resurrect,
  stale TTL returns null never zero-object, genuine zero bpm preserved.
- **Recording pipeline smoke:** HR-only ride populates `heart_rate_bpm`
  and leaves power/cadence null; mid-ride HR disconnect writes null to
  subsequent rows; logout path writes null after registry removal;
  genuine zero bpm with contact-lost flag preserved on the row.
- Sensor-contact status bit is already parsed; UI should surface it
  (amber chip "check strap contact") on future polish pass — still
  deferred, see §5.6.

### 5.3 CSC profile (0x1816) — COMPLETE (2026-04-17)

- `cadenceSource.ts` + `parsers/cscMeasurement.ts` are implemented
  similarly (stale TTL 5000 ms)
- Registry prefers power-embedded cadence; CSC fills the gap only when
  no power meter paired
- Wheel circumference is persisted per known device, applied to the
  source on connect
- **Parser coverage extended** with vendor byte-vector fixtures (Wahoo
  RPM cadence-only pod, Garmin GSC-10 combo, 4iiii CSC-only, wheel-
  magnet hub sensors with long event time, combo sensor at near-uint32
  max wheel revs) plus boundary cases (empty, flags-only, min legal
  wheel-only 7-byte, min legal crank-only 5-byte, max legal 11-byte,
  truncated wheel/crank payloads throw, RFU bits do not consume fields)
- **Derivation math coverage extended**: combined crank-rev AND event-
  time wraparound together, rider-coasting case returns 0 rpm (not
  null), wheel-speed event-time wraparound at high speed, wheel-speed
  scales linearly with circumference, zero-rev-with-time-delta
  preserves genuine 0 speed.
- **Source-level parity** with power slice: idempotent `markLost`,
  `isStale` pre-first-sample false, disconnection clears cache to null
  not zero-object, error after disconnect does not resurrect, stale
  TTL returns null never zero-object, first-packet-only yields null
  with isStale false, rider-coasting preserves 0 rpm.
- **Recording pipeline smoke:** CSC-only ride populates `cadence_rpm`
  and leaves power/HR null; mid-ride CSC disconnect writes null to
  subsequent rows; logout path writes null after registry removal;
  genuine zero cadence (coasting) preserved on the row.
- **All-three integration:** power + HR + CSC connected has power-
  embedded cadence winning; sequential drop (HR → power → CSC) each
  reflects absence honestly in the next batch; HR + CSC only (no power
  meter) populates both non-null columns.

### 5.3a HR/CSC parity slice — remaining gaps surfaced

These items came out of writing the parity tests and are deferred on purpose
(brief was first-slice scope, not exhaustive). Listed here so the next pass
or the physical-device slice does not have to rediscover them.

- **Physical device verification for HR and CSC** (mirror of §5.4 for
  power): confirm Polar H10 actually sends the flag combinations in §5.2
  fixtures; confirm Wahoo RPM crank-only vs. Garmin GSC-10 combo show up
  with distinct flag patterns on Seeker; confirm Xiaomi generic strap's
  0-bpm-on-contact-loss firmware behavior matches the fixture. Chest-
  strap-on-sweaty-rider case specifically — fixture is synthetic.
- **UI surface for `sensor_contact === false`** — parser has the field,
  recording pipeline passes it to the wide row via HR sample, but there
  is no amber chip yet on the recording screen. Blocks rider noticing
  that their HRM slipped mid-ride. (Related to §5.6 demo-blocking UI.)
- **RR-interval persistence** — HR sample includes `rr_intervals_ms[]`
  but the wide row column is just `heart_rate_bpm`. The RR stream is
  available at capture time but gets dropped at snapshot. When HRV
  analysis lands, RRs need their own table or a serialized JSON column
  on gps_samples. Not a blocker for the hackathon; flagged for post-
  Alpha protocol work.
- **CSC wheel-only riders** — some setups (wheel-magnet hubs,
  smart-trainer virtual CSC) expose wheel data without crank data. The
  parser handles this, the derivation computes wheel speed correctly,
  but `registry.getLatestCadence()` returns null in that case (crank-
  rev absence → null CadenceSample). The recording pipeline today has
  no column for `wheel_speed_mps`; GPS speed wins. A wheel-only CSC
  sensor therefore contributes nothing to the ride — the sensor is
  registered but its data is dropped. Decide whether to surface wheel
  speed as a separate column, merge into GPS speed when GPS is weak,
  or drop the feature entirely in a follow-on.
- **Energy-expended field on HR samples** — parser captures, type
  carries `energy_expended_kj`, but the recording pipeline does not
  persist it. Blocks rider getting the HR-device-reported kcal total
  in the post-ride summary. Low priority — our TSS math already
  computes calorie estimates.
- **CSC crank-only coasting detection** — the rider-coasting case
  (crank count static across packets, time advances) now returns 0 rpm
  rather than null. Behavior is now documented and tested, but think
  through whether the recording pipeline should promote this to "auto-
  paused" when coasting exceeds a threshold (today only GPS speed
  drives auto-pause). Deferred.

### 5.4 Physical Seeker verification (route to Alexei)

None of the BLE work has run on a real Seeker with a real power meter.
The `recordingPipeline.smoke.test.ts` end-to-end test proves the merge
logic in Node, not that iOS or Android BLE stacks emit what ble-plx
types say they will.

Physical items:
1. Confirm the Expo config plugin actually generates `bluetooth-central`
   in Info.plist after `npx expo prebuild --platform ios`
2. Confirm Android runtime prompt order (BLUETOOTH_SCAN, BLUETOOTH_CONNECT)
   on Android 14/15 Seeker firmware; AGP may change the default order
3. Pair a real power meter to a Seeker, record a short ride, verify
   `power_w` populated in the saved ride row
4. Disconnect the power meter mid-ride (walk out of range); verify the
   subsequent rows have `power_w = null` and the UI surfaces "Power lost"

### 5.5 FIT export (`5hdl.3` bead, depends on this)

- `fitExporter.ts` exists and already reads power_w / heart_rate_bpm /
  cadence_rpm from gps_samples
- `fitExporter.test.ts` should be extended after the provenance record
  lands (§5.1) to include the sensor session rows in the exported file

### 5.6 UI polish — demo-blocking items

- No amber chip when power meter went silent mid-ride (currently the UI
  still shows "connected" until audit runs; audit runs on foreground
  which may not happen mid-ride). Post-Seeker, add a more aggressive
  staleness poll for the recording screen specifically.
- No "Power meter connected" badge on the recording screen — Act 1 of
  the demo script needs the rider to see the live number and the
  hardware attribution at a glance. Surfacing `PowerSample.power_w`
  live is easy (already in registry); surfacing `deviceName` needs a
  selector in `pairingStore` that returns the current source's name.

---

## 6. Gift posture check

- §4.2 absence-vs-zero: ✅ a disconnected power meter returns null from
  `getLatestPower()` within the 2-second TTL; `recordingPipeline.smoke.test.ts`
  asserts `power_w === null` in the row following a sensor stop.
- §2.3 provenance: ⚠️ partial — device id flows to pairing store and
  registry, but does not flow to the persisted sample row. Flagged as
  follow-on (§5.1).
- Naming: ✅ "Connected Hardware" used in MOBILE_TRUTHS; code variables
  use `device` / `deviceId` / `deviceName` (ble-plx domain) but
  rider-facing copy in PairingScreen uses neutral "sensor" which is
  acceptable; "peripheral" / "devices" anti-patterns not present.
- Demo: if the power line goes flat because the peripheral went to sleep,
  `getLatest()` correctly returns null after 2 s and the ride row
  writes null rather than reusing the last value. The UI does not yet
  visually communicate that flatness — follow-on (§5.6).

---

## 7. Parameters and constants to remember

| Constant | File | Value | Rationale |
|----------|------|-------|-----------|
| `STALE_TTL_MS` (power) | `powerMeterSource.ts` | 2000 | ~4 Hz × 8 missed samples |
| `STALE_TTL_MS` (HR) | `heartRateSource.ts` | 3000 | ~1 Hz × 3 missed beats |
| `STALE_TTL_MS` (CSC) | `cadenceSource.ts` | 5000 | CSC sensors vary in rate |
| `CONNECT_TIMEOUT_MS` | `manager.ts` | 10000 | Most dials complete < 2 s |
| `CP_COMMAND_TIMEOUT_MS` | `powerMeterSource.ts` | 30000 | Spec-mandated |
| `FLAG_VALID_MASK` | `parsers/powerMeasurement.ts` | 0x1FFF | Ignore RFU bits |
| `ANDROID_RUNTIME_BT_PERMS_MIN_SDK` | `manager.ts` | 31 | Android 12+ |
| `DEFAULT_WHEEL_CIRCUMFERENCE_M` | `cadenceSource.ts` | 2.105 | 700×25c road default |
| `MIN_WHEEL_M` / `MAX_WHEEL_M` | `pairingStore.ts` | 1.0 / 3.0 | Physically plausible |

---

## 8. Test inventory (as of this slice)

| File | Count |
|------|-------|
| `sensors/__tests__/bleManager.test.ts` | ~25 tests (scan, connect, disconnect, destroy, auditStaleness, Android perms, adapter state monitor) |
| `sensors/__tests__/powerMeasurement.test.ts` | Parser unit tests — mandatory fields, every optional field, combined fixtures, RFU tolerance, vendor byte vectors |
| `sensors/__tests__/powerMeterSource.test.ts` | Source lifecycle, cadence derivation, stop/markLost, stale TTL, sendCommand, onDisconnected |
| `sensors/__tests__/powerControlPoint.test.ts` | CP opcode round trips |
| `sensors/__tests__/heartRateMeasurement.test.ts` | HR parser — base fields, 7 vendor byte vectors (Polar H10, HRM-Dual, TICKR, TICKR sweaty, Magene H64, Xiaomi generic, HRM-Pro Plus, Polar OH1), boundary cases (empty / single byte / max / truncated-RR-tail / 8-RR max / RFU-bit tolerance) — 35 tests |
| `sensors/__tests__/heartRateSource.test.ts` | HR source lifecycle + §4.2 parity (markLost idempotency, isStale pre-first-sample, disconnection clears to null not zero-object, stale-TTL null, genuine zero bpm preserved, error-after-disconnect does-not-resurrect) — 13 tests |
| `sensors/__tests__/cscMeasurement.test.ts` | CSC parser — field presence, error handling, 5 vendor byte vectors (Wahoo RPM, Garmin GSC-10, 4iiii CSC, wheel-magnet hub, near-uint32-max combo), boundary cases (min/max legal packet / RFU bits), extended cadence + wheel-speed math (combined wraparound, coasting, linear scaling) — 31 tests |
| `sensors/__tests__/cadenceSource.test.ts` | CSC source lifecycle + §4.2 parity (markLost idempotency, isStale pre-first-sample / first-packet-only, disconnection clears to null not zero-object, stale-TTL null, rider-coasting preserves 0 rpm, error-after-disconnect does-not-resurrect) — 15 tests |
| `sensors/__tests__/registry.test.ts` | Registry routing (power-embedded cadence precedence) |
| `sensors/__tests__/mockBleSource.test.ts` | Fixture source lifecycle |
| `stores/__tests__/pairingStore.test.ts` | Scan / connect / disconnect / disconnectAll / reconnectKnown / calibrate / wheel circumference |
| `services/__tests__/recordingPipeline.smoke.test.ts` | End-to-end merge of sensor data into gps_samples row. §4.2 pinned for all three kinds: HR-only ride, CSC-only ride, mid-ride HR disconnect, mid-ride CSC disconnect, logout-path removal, all-three connected, sequential drop-out, HR+CSC only, genuine zero preserved for each — 27 tests |

**Full-suite baseline after HR+CSC parity slice:** 500 passing (was 437 after
power-first slice). `npx tsc --noEmit` clean.

---

## 9. Changelog

- 2026-04-17 — Initial audit of the Cycling Power path for `5hdl.2`
  first slice. HR / CSC follow-on slice picks up from §5.2.
- 2026-04-17 — HR + CSC parity slice. §5.2 and §5.3 marked COMPLETE.
  20 new HR parser tests (vendor vectors, boundaries), 17 new CSC
  parser tests (vendor vectors, boundaries, extended derivation math),
  7 new HR source tests (§4.2 parity), 8 new CSC source tests (§4.2
  parity), 10 new recording pipeline smoke tests (HR-only ride,
  CSC-only ride, mid-ride HR/CSC disconnect, all-three sequential
  drop-out, HR+CSC no-power combined, genuine-zero-preserved per kind).
  Baseline 437 → 500 passing; `npx tsc --noEmit` clean. Remaining gaps
  catalogued in §5.3a.
