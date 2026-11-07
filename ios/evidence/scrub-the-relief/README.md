# Scrub-the-relief — simulator verification (2026-08-17)

Evidence class: **local simulator, fixture-fed** (`-BRRideDetailRenderFixture
finished`), touch injected via simctl-driven touch path, captured from a
screen recording during the live gesture.

## Proven

- **Engage**: long-press (0.15 s) on the elevation trace engages the scrub
  with one light haptic; a plain vertical drag on the chart scrubs without
  fighting the sheet's vertical scroll (page never moved during the drag).
- **Cursor** (`scrub-engaged.png`): hairline + white dot pinned to the trace
  at the finger's x; the cursor appears at the finger's first reported
  location and never at a guessed position (Health-app behavior).
- **Readout**: the section header line becomes the moment's facts
  ("7.8 mi · 308 ft" in the captured frame); layout height holds — no jump
  when the header swaps in and out.
- **Release** (`scrub-released.png`): lifting restores the ELEVATION header;
  no residue.
- **Abstention policy**: the fixture's 4 km point spacing and ~10-minute
  stream spacing correctly suppressed grade and power/HR — sparse evidence
  abstains rather than smearing. The policy is now extracted to
  `ScrubFacts` (pure functions) and pinned by `ScrubFactsTests`: dense
  tracks compute grade, sparse tracks abstain, correction gaps wall the
  window, stream facts honor the 15 s tolerance.

## Open

- **Map dot unverified visually**: MKMapSnapshotter produced no tiles in
  this fixture run (band fell back to the base color), so the marker overlay
  never had a canvas. The projection is `MKMapSnapshot.point(for:)` at 1:1
  rendered size; risk is low but a live-account run with real tiles should
  confirm before this is called fully proven.
- **Co-visibility finding (design, for Tim)**: on rides with photos, the
  248 pt photo carousel sits between the map band and the relief — map and
  trace are never in the same viewport, so the scrub's map linkage is
  invisible on exactly the rides most likely to be looked at. Options:
  accept for v1, reorder relief above photos, or a floating mini-map while
  scrubbing. Interacts with the ratified photo-lead hero decision.

## Analysis stack rebuild (same day, Tim-directed)

The standalone relief retired. Strava's analysis anatomy crossed with
Apple's framework: elevation is a context band stacked flush above the
metric chart (`analysis-stack-scrub.png`), both on one distance axis, both
scrubbed by the platform's chartXSelection — the hand-rolled long-press
gesture was deleted, not refined.

- **Cursor alignment measured, not eyeballed**: before the inset fix the
  band and metric cursors sat 25 px apart (the metric plot's leading y-axis
  compresses its plot area); the band now inherits the metric plot's
  measured insets via a preference key — cursors align within 1 px.
- **Stream mapping**: metric samples map time→distance through the GPS
  timeline (linear interpolation, monotonic cursor); samples beyond GPS
  evidence drop rather than extrapolate.
- **Fixture clock made self-consistent**: the render fixture's GPS spanned
  6 minutes against 73-minute streams, which truthfully starved the
  mapping; its timestamps now span the ride, which is what real tracks do.
- Facts row swaps Average/Maximum for the moment's facts under the
  scrubber (Strava's pattern); abstention policy unchanged and still
  pinned by ScrubFactsTests.
