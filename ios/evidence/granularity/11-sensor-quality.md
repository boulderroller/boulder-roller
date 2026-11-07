# Trusted sensor data quality — local/offline evidence

**Bead:** `boulderroller-v2-odmi6.11`

**Owner/status:** claude / policy layer, resolution, calibration flow, and
surfaces implemented and unit-proven; hardware verification remains open

**Evidence class:** local/offline (pure state machines under test; simulator
render fixtures labeled simulated — the simulator has no radios)

**Input class:** deterministic clocked fixtures; no account, upload, CAL, or
permanent surface

## Externally checkable outcome

**Dropout policy is named constants, not accident** (`SensorStreamPolicy`):
heart rate and cadence hold at most 5 s; power is associated for at most 3 s,
recorded at most once per BLE notification, and never zero-filled or held.
The hold windows are enforced inside `RecordingSession` against the sample's
capture time, so the recorded GPX reflects policy deterministically — on
live capture and on custody replay alike. Testimony 4.9 s old records; 5.1 s
does not; a power notification present 4.1 s later records as absence.
Legacy journaled fixes without testimony timestamps replay exactly as
originally recorded.

**Conflicts resolve deterministically, never silently:** every device's
testimony is stored per peripheral; the published live value is the
resolver's choice — the rider's persisted pick while that device provides,
else the earliest-paired connected provider. Two connected power meters
surface an explicit Power Source picker in the Sensors room (same for
overlapping HR/cadence); selection persists. Recorded power carries its
source device id, and the GPX annotates `br:power-source` on the first
powered sample and on every switch — two annotations for A→A→B, not three.

**Zero-offset calibration** is the pure `PowerCalibrationFlow` machine over
the Cycling Power Control Point (0x2A66), gated by the 0x2A65 feature bit
(offset compensation supported). Device rows open a stock detail sheet;
gray Calibrate appears only where the meter's GATT actually supports it.
Result states are truthful only: meter-reported raw offset on success
(sint16, e.g. −340), distinct not-supported vs rejected vs write-failed vs
timed-out (10 s) vs disconnected. Unsolicited or malformed indications are
ignored; a late answer cannot rewrite a settled result; the flow is
re-runnable from any settled state.

## Captures (simulated — simulator, DEBUG render fixtures, frozen radio)

- `11-sensor-source-conflict-simulated.png` — two power meters connected:
  Power Source and Cadence Source pickers, checkmark on the resolved source
- `11-sensor-detail-calibrate-simulated.png` — device room, gray Calibrate,
  instruction footer
- `11-sensor-detail-calibrated-simulated.png` — "Calibrated. Offset -340."
- `11-sensor-detail-timeout-simulated.png` — "The sensor did not respond."

## Tests

`SensorDataQualityTests` (13): resolver determinism (explicit pick wins,
disconnected pick falls back, paired-order default, empty), selection
persistence + forget clears picks, calibration happy path with offset parse,
success-without-parameter, not-supported vs rejected, unrelated-indication
immunity + timeout finality, write-fail/disconnect/early-indication paths,
feature bitfield parsing, HR/cadence hold boundaries with legacy grandfather,
power dropout absence, source-switch provenance per sample and in GPX.
Full suite green.

## Hardware-verification gap (explicit)

The simulator has no Bluetooth. Everything above is proven at the policy
layer; the following remain physical-world gates, per lane precedent:

- Real zero-offset against a compatible meter (Favero/4iiii class):
  indication delivery, real offset values, per-vendor response quirks.
- Real dual-power-meter ride proving picker → recorded stream → backend
  parse end to end.
- Real dropout behavior of specific straps/meters vs the policy windows.

These belong to the physical REVIEW_DAY lane; the bead stays open with this
gap named until a hardware pass runs.
