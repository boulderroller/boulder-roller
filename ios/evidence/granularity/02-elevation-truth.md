# Elevation truth — local/offline evidence

**Beads:** `boulderroller-v2-odmi6.2`, `boulderroller-v2-odmi6.2.1`

**Evidence class:** local/offline only; no API deployment or physical ride

**Input class:** deterministic simulated altitude/pressure/route fixtures; no
account, upload, CAL, or permanent surface

## Externally checkable outcome

The iOS fixture anchors a phone-relative pressure reading at 100 m, then sends
a false 128 m GPS altitude while pressure rises by 1.5 m. The accepted altitude
is 101.5 m, not 128 m, and the recorded GPX retains the fused value, raw GPS
altitude, relative pressure altitude, source, and confidence. A 45 m one-second
pressure discontinuity breaks the gain chain and falls back to a qualified GPS
sample; missing pressure plus an 80 m-accuracy GPS altitude leaves both altitude
and climbing unavailable rather than `0`.

A repeated, still-fresh pressure callback at the same timestamp is reused only
when its relative altitude is identical: a false 130 m GPS value remains a
100 m barometer-fused value. A four-second-stale pressure callback invalidates
the pressure anchor and starts a new elevation evidence segment before falling
back to GPS, so the 100→140 m transition does not become 40 m of climbing.

The backend fixture replaces noisy raw values `[103, 76, 119]` with a versioned
repository-controlled DEM profile `[50, 51, 52]`, reports 2 m gain, and keeps the
raw values alongside the correction. A 50%-covered route reports
`insufficient_dem_coverage`, no corrected profile, and a null total. The actual
bundled local USGS 3DEP profile loads without contacting a route or elevation
provider.

The correction rule is explicitly versioned as
`dem_match8m_median3_hysteresis2m_v2`: fixes within 8 m of the last matched
progress anchor reuse that match, a three-point median cannot cross missing or
GPX-segment evidence, and gain requires a 2 m ascent hysteresis. Five stationary
fixes jittering between two DEM samples 6 m apart all remain at 50 m and produce
0 m gain instead of repeated ascent. Insufficient DEM evidence still returns
null, never 0.

The projection-only GPX adapter reads the exact source/confidence/raw GPS/
relative-barometer extensions emitted by `GPXWriter`. It keeps fused `<ele>` as
device elevation rather than relabeling it as raw GPS; plain GPX without the BR
contract reports provenance `unavailable`. In addition to the helper-level
fixtures, a focused integration fixture sends the GPX bytes through
`parse_ride_file_bytes_rust` and the compiled `workout_parse` parser before
building the correction route. The resulting four points retain distinct
fused values, raw GPS values, relative-barometer values, and segment starts.
The corrected profile retains `[50, 53, 100, 103]`, reports only the 6 m ascent
inside the two segments, and does not connect the 47 m gap between them.

## Red to green

- iOS red: the focused test target failed before implementation because the
  prior app had no elevation observation/fusion API.
- Retained behavioral red: before the corrective fix, a repeated pressure
  timestamp fell back to the false 130 m GPS value and fabricated 30 m gain;
  a stale pressure callback failed to mark a segment break and fabricated
  40 m gain. The focused test reported those exact failures before turning
  green.
- iOS green: `ElevationTruthPipelineTests` passes on the booted arm64 iPhone 17
  simulator (iOS 26.3).
- Backend red: test collection failed because no elevation-correction service
  existed in the original pass; the corrective GPX-segment test then failed
  because projection points carried no segment boundary.
- Backend green: nine focused correction/provenance tests pass locally,
  including the compiled production-parser integration above.

Commands:

```text
xcodebuild -project BoulderRoller.xcodeproj -scheme BoulderRoller \
  -destination platform=iOS\ Simulator,id=83285814-8448-43E4-9AB5-630A48FFF29C \
  CODE_SIGNING_ALLOWED=NO \
  -only-testing:BoulderRollerTests/ElevationTruthPipelineTests test

python3 -m pytest -q tests/services/test_elevation_correction.py
```

## Remaining gate

The backend service and container asset are implemented but are not wired into,
persisted by, or deployed through the production ride projection. The
coordinator explicitly ruled that this branch must not perform those actions.
Any future authorized storage must use separate projection-only status, source,
coverage, profile, and gain fields and **must not overwrite
`rides.elevation_gain_m`**, because that existing field feeds the frozen
economic plan and achievements. The backend child and parent therefore remain
open+blocked, and none of this evidence is live or physical-world proof.

## Resolution (2026-08-11)

The remaining gate above closed from outside this branch: the backend lane
shipped the DEM correction as a projection (`rides.elevation_correction_*` +
`elevation_corrected_gain_m`, migration 149; `rides.elevation_gain_m` never
overwritten) and deployed it to production with a legacy backfill. This
branch then wired the client half — corrected climbing totals on feed/ride
stats, the corrected-only relief with truthful gaps, and decode of the
provenance object. Production-read proof and the full capture list:
`live-contract-wiring-2026-08-11.md`.
