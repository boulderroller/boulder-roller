# Live climb band — local/offline evidence

**Bead:** `boulderroller-v2-odmi6.4`

**Owner/status:** claude / locally complete, pending coordinator acceptance

**Evidence class:** local/offline only

**Input class:** deterministic clocked centerline-progress and distance fixtures;
no account, upload, protocol adjudication, CAL, DUNG, or permanent surface

## Externally checkable outcome

The production recording model now feeds a pure, constant-size lifecycle from
the already ordered canon response coordinates. A candidate inside the existing
35 m entry band stays hidden until a later fix establishes increasing ordered
progress. One projected-vertex regression holds the prior high-water progress;
two consecutive regressions invalidate the ascent until the existing 60 m exit
hysteresis resets it. Reverse-only and direction-valid partial paths therefore
record no local band ascent.

The Wall-shaped fixture travels 0→1, descends 1→0 on the same centerline, turns,
then travels 0→1 again. The first finish emits once at second 10 and remains
locked while the rider leaves the existing finish endpoint. Five fixes more
than 60 m from that endpoint release the lock without requiring an artificial
lateral corridor exit. The turnaround then arms a new candidate, and the second
finish emits once at second 29. The retained local session evidence contains
exactly two ascents, starting at seconds 0 and 18 with durations 10 and 11
seconds. No reverse descent, U-turn, partial pass, gate jitter, or duplicate fix
adds a third ascent.

Exact tolerance fixtures preserve the existing UI-band values: 35 m qualifies
for entry while 35.1 m does not; a 60 m fix clears pending exit evidence, and
five consecutive fixes at 60.1 m retire the lifecycle. The canon geometry,
gate/corridor definitions, and detector tuning are unchanged.

Successful canon-track replacement also uses the same deterministic seam. If
the tracked climb ID is absent—or the replacement is empty—the live lifecycle
and rendered band retire while already completed local ascents remain present.
If the ID survives, lifecycle and rendered state survive. Every successful
replacement restarts nearest-point projection at index 0, so a shorter or
re-sampled coordinate array cannot inherit an out-of-range/route-skipping
cursor. Fetch failures do not enter this replacement path and retain the prior
state.

The lifecycle retains only scalar candidate/active/reset state plus one record
per completed ascent. It does not retain or mirror a per-fix route array.

## Red to green

- Retained behavioral red: after the model was routed through the pure seam
  while preserving its prior lifecycle behavior, three direction/repeat/
  hysteresis fixtures produced 12 failures. The band appeared on the first
  candidate fix, reverse and partial paths recorded ascents, finish lockout was
  absent, and the Wall repeat shape produced three ascents instead of two.
- Retained refresh red: the successful-replacement fixture produced nine
  failures before reconciliation. Removed and empty replacements retained the
  old `wall` lifecycle/render state, and successful replacements retained
  projection indices 87, 143, and 55 instead of restarting at 0.
- Green: all five `ClimbBandLifecycleTests` pass on the booted arm64 iPhone 17
  simulator (iOS 26.3). The complete item 1–4 arm64 truth suite passes 30/30:
  five climb-band, six elevation, eight GPS, and eleven recording-metrics
  tests.

Commands:

```text
xcodebuild test -project ios/BoulderRoller.xcodeproj -scheme BoulderRoller \
  -destination platform=iOS\ Simulator,id=83285814-8448-43E4-9AB5-630A48FFF29C \
  -only-testing:BoulderRollerTests/ClimbBandLifecycleTests

xcodebuild test -project ios/BoulderRoller.xcodeproj -scheme BoulderRoller \
  -destination platform=iOS\ Simulator,id=83285814-8448-43E4-9AB5-630A48FFF29C \
  -only-testing:BoulderRollerTests/ClimbBandLifecycleTests \
  -only-testing:BoulderRollerTests/ElevationTruthPipelineTests \
  -only-testing:BoulderRollerTests/GPSTruthPipelineTests \
  -only-testing:BoulderRollerTests/RecordingMetricsTests
```

## Remaining boundary

This proof is simulated local/offline live-band behavior. It is not a
protocol-accepted D11 traversal, a Record Board result, CAL, DUNG, deployed
state, or physical rider/world-state evidence. Item 4 remains subject to exact-
commit coordinator review before item 5 can be admitted.
