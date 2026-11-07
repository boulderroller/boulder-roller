# Hidden route points — local simulator evidence

Bead: `boulderroller-v2-0hpoo`. iPhone 17 / iOS 26.5, Xcode project generated from `ios/project.yml`. These are synthetic non-owner `RideDetailRenderFixture` responses rendered by the production ride view, not live rider/API evidence.

- `hidden-ends-before.png`: baseline `a669836fb` plus the new fixture/test seam; nullable GPS fails decoding, so the ride loses its map and relief.
- `hidden-ends-after.png`: identical fixture after the fix; first/last 200 m hidden, visible map and relief retained.
- `no-map-after.png`: every point hidden; existing map-absent presentation, no empty map.
- `hidden-middle-after.png`: hidden ends plus 12–17 km hidden; map and both elevation views break at the hidden stretch.
- `hidden-middle-viewer.png` and `hidden-middle-share-card.png`: tapping the map and opening Share Card retains the same gap. No share was sent.

Reproduce by launching the Debug app with `-BRRideDetailRenderFixture hiddenEnds`, `hiddenMiddle`, or `noMap`. The fixture serializes hidden coordinates, both elevations and timestamp as JSON null, retaining distance and `redacted: true`, then uses the normal snake-case decoder. Existing finished/sparse fixtures retain their data.

Validation: five new regression tests failed before the fix (null-coordinate decode errors and redaction ignored). After the fix, 29 XCTest tests and 15 Swift Testing tests passed across HiddenRouteTests, GPSTruthPipelineTests, LiveRideContractTests, ScrubFactsTests and UnitSystemTests.

Build preparation used `bash ios/scripts/build_parser.sh --skip-device` and `xcodegen generate --spec ios/project.yml`. The root's prebuilt parser artifacts were stale; regenerating them resolved the initial missing `RideSummary.elevationProfile` build error without changing parser source.

Test command:

```sh
xcodebuild -project ios/BoulderRoller.xcodeproj -scheme BoulderRoller \
  -destination 'platform=iOS Simulator,id=B1010156-F329-457E-8ADA-CF54D4232FB6' \
  -derivedDataPath /tmp/br-hidden-route-build test \
  -only-testing:BoulderRollerTests/HiddenRouteTests \
  -only-testing:BoulderRollerTests/GPSTruthPipelineTests \
  -only-testing:BoulderRollerTests/LiveRideContractTests \
  -only-testing:BoulderRollerTests/ScrubFactsTests \
  -only-testing:BoulderRollerTests/UnitSystemTests
```

Maps, map viewer and share cards share `RouteGeometry.fragments`; relief and the ride spine share `ReliefChart.elevationSegments`. Hidden samples also suppress scrub facts. Timing-derived speed, splits and climb-distance interpolation abstain on incomplete private tracks instead of joining separated samples. AppSession's current cache warmer calls `rideGps` directly; the API caches the decoded response without rebuilding points. No separate coordinate cache conversion remains there.
