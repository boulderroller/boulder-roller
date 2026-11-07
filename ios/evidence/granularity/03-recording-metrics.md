# Recording metrics — local/offline evidence

**Bead:** `boulderroller-v2-odmi6.3`

**Owner/status:** claude / corrective item 3 ready for coordinator review

**Evidence class:** local/offline

**Input class:** deterministic clocked power and motion fixtures; no account,
upload, CAL, or permanent surface

## Externally checkable outcome

Four sourced BLE power notifications of 100 W, 200 W, 300 W, and 500 W at
seconds 0, 1, 2, and 4 produce a 333 W three-second value and a 275 W ten-second
value. Polling the second-4 notification twice leaves the source count at four.
At second 7.1 both values are null because the source has dropped out; the UI
therefore cannot keep pacing on a carried-forward number.

The production `RecordingSession` seam proves that one 250 W source observation
enters one `RecordedSample` and one GPX extension even when a later GPS fix sees
the same notification. A 3.1-second dropout becomes null. While manually paused,
GPS fixes add no sample, distance, or elapsed time. A 300 W observation captured
during that pause is absent from the first resumed sample; a fresh 300 W
observation at second 8.5 is also absent from a batched GPS fix captured at second
8.25, then appears once on the second-9 fix and once in GPX.

A 4 m accepted jitter edge at 0 m/s adds no distance, a 10 m edge at 5 m/s with
0.5 m/s accuracy adds exactly 10 m, and a GPS gap adds none. Without independently
qualified speed, a raw 12 m edge with 4 m outside the accuracy envelopes adds only
4 m, while a raw 81 m edge with only 1 m of spatial evidence adds only 1 m. The
exact sequence good-moving 10 m/s at second 0, accuracy-ineligible speed at second
1, and good-stopped 0 m/s at second 2 clears scalar speed continuity: the stopped
fix remains 0 m/s, its sub-meter jitter adds no distance, and five subsequent
seconds of stopped evidence can auto-pause.

Auto-pause requires five continuous seconds at or below 0.5 m/s and physical
resume requires two continuous seconds at or above 1.5 m/s. Missing or
quality-ineligible speed and GPS segment breaks reset those clocks, so low-speed
or high-speed evidence cannot bridge an outage. Manual pause remains the rider's
intent state and alone exposes End plus Resume; auto-pause remains a physical
state with End only, rejects manual resume, and leaves only through sustained
motion. The fixes establishing physical resume are not recorded, and the next
recorded fix opens a new GPX segment.

`RecordingSession` is the sole retained owner of the sample array. The observable
model mirrors scalar UI projections only and never assigns a per-fix sample-array
snapshot, structurally avoiding a copy-on-write full-ride append path.

## Red to green

- Retained behavioral red: before the corrective production changes, the gap
  fixtures bridged low/high auto-pause clocks, an 81 m speedless edge counted all
  81 m from 1 m of evidence, and a later jitter edge inherited an ineligible
  speed and counted 0.5003778613677425 m.
- Retained provenance red: the production-session fixture carried pause-era
  power onto a resumed coordinate and attached a newer BLE observation to an
  older batched GPS fix, producing `[250, nil, 300, 300, nil]` instead of
  `[250, nil, nil, nil, 300]` and serializing 300 W twice.
- Final continuity red: the exact moving → ineligible → stopped fixture reported
  5.0 m/s at the stopped fix, counted 0.5003778613677425 m, and did not complete
  the stopped clock. The same test passed after clearing the scalar window.
- Green: `RecordingMetricsTests` passes on the booted arm64 iPhone 17 simulator
  (iOS 26.3), with the app target built from the regenerated XcodeGen project;
  all 11 focused tests and the complete 25-test iOS suite pass on that target.

Command:

```text
xcodebuild -project BoulderRoller.xcodeproj -scheme BoulderRoller \
  -destination platform=iOS\ Simulator,id=83285814-8448-43E4-9AB5-630A48FFF29C \
  CODE_SIGNING_ALLOWED=NO \
  -only-testing:BoulderRollerTests/RecordingMetricsTests test
```
