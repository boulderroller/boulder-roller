# GPS truth pipeline — local/offline evidence

**Bead:** `boulderroller-v2-odmi6.1`

**Evidence class:** local/offline

**Input class:** deterministic simulated coordinates; no account, upload, CAL, or permanent surface

## Externally checkable outcome

The focused fixture supplies an accurate start, a labeled 2 m stationary-jitter
observation, an accurate moving fix at 9 m, a 90 m-accuracy fix, an impossible
900 m teleport, and a later accurate fix after a 13-second GPS outage. The
accepted route contains exactly the four original accepted coordinates,
including the unchanged jitter coordinate. The poor fix and teleport are
absent, the later fix begins a new fragment, and that fragment has no inferred
distance edge to the earlier one. The sum of all accepted distance edges equals
only the two observed adjacent edges from 0→2→9 m (less than 10 m); neither
rejected fix contributes an edge. GPX serialized directly from this accepted
fixture contains all four accepted coordinates unchanged at seven-decimal GPX
precision, contains neither rejected coordinate, and has exactly two `trkseg`
elements matching the accepted gap membership.

An explicit pause boundary produces the same disconnected result. GPX output
contains two `trkseg` elements. A two-fragment server preview remains two map
fragments. Zoom simplification retains only vertices present in the original
observation set and retains more of them at zoom 18 than zoom 11.

Saved GPS applies the same 8-second outage and 55 m/s credible-speed ceilings
when adjacent epoch timestamps exist: a 200 m/1 s point is absent from the
saved-route fragments, while the following credible point reconnects to the
last accepted observation; a 19-second outage produces two fragments. Without
adjacent timestamps the renderer filters the resulting single-point fragments
and therefore draws no unevidenced edge. Snapshot render identity includes every coordinate bit and fragment
boundary, so two routes with identical sizes/counts but different coordinates
cannot retain the same stale route or privacy image.

## Red to green

- Red: the focused test target failed before the implementation because the
  prior app had no `GPSObservation` / truth-pipeline / fragment-preserving API.
- Green: `GPSTruthPipelineTests` passes on the booted arm64 iPhone 17 simulator
  (iOS 26.3) after the implementation; the app target builds as part of the
  test run.
- Corrective evidence: the labeled stationary-jitter coordinate and direct
  rejected-edge distance assertions pass against the existing item-1 capture
  behavior. Direct `GpsResponse` fixtures exposed and then closed the saved-map
  policy gap, and a coordinate-content render-key test closes stale equal-count
  snapshots. Item 3 remains the owner of auto-pause and moving-distance policy.

Command:

```text
xcodebuild -project BoulderRoller.xcodeproj -scheme BoulderRoller \
  -destination platform=iOS\ Simulator,id=83285814-8448-43E4-9AB5-630A48FFF29C \
  CODE_SIGNING_ALLOWED=NO -only-testing:BoulderRollerTests/GPSTruthPipelineTests test
```

The generic simulator destination remains an invalid baseline for this branch
because the staged Rust XCFramework is arm64-simulator only; the actual arm64
simulator build is green.
