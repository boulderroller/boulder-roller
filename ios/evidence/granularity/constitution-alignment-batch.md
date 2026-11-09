# Constitution-alignment refinement batch — evidence (bead boulderroller-v2-c6l2l)

**Evidence class:** simulated renders (iPhone 17 simulator, iOS 26.x) through
production render paths; data injected via DEBUG fixtures
(`RecordingLayoutRenderFixture`, `RouteRenderFixture feedCards`). Labeled
`-simulated`. The gallery frames referenced are the ratified surface gallery
(artifact 98735d7a, Recording + Feed frames). Suite 222/222 green.

## Item status

1. **Recording screen to gallery spec** —
   `recording-power-hero-simulated.png` (TIME 48pt secondary above the
   64pt POWER hero, left-aligned Apple Workout stack at the 20pt margin,
   small metrics in leading grid rows, tracked labels, gallery unit casing),
   `recording-time-hero-climb-band-simulated.png` (TIME hero when no
   power source; live climb band fired on real canon data),
   `recording-paused-icon-only-quiet-dash-simulated.png` (icon-only
   End/Resume circles — text labels dropped, VoiceOver labels kept).
   Numeral tiers 64/48/32pt are the hand-drawn 52/40/26px at true scale,
   snapped to the 4pt grid.
   **Documented deltas from the gallery frame (never guessed design):**
   - Label reads `TIME`, not the sketch's `ELAPSED` — the bead text (newer,
     Tim-lens walk) names TIME as the alternate hero explicitly.
   - `10S POWER` (Garmin-shaped field, real telemetry already on the
     surface) is kept as a small metric; the sketch omits it.
   - Sensor provenance row renders only with live BLE devices — no simulator
     can show it; unchanged code path from the accepted recording surface.
2. **Liquid Glass on chrome only** — record pill upgraded from
   `.ultraThinMaterial` to `glassEffect(.regular.interactive(), in: .capsule)`
   (`feed-record-pill-glass-simulated.png`); the custom top bar became
   a `safeAreaBar` over the ScrollView's `.soft` top scroll-edge effect — the
   platform's iOS 26 bar treatment; content fades under the wordmark with no
   material on the content layer
   (`feed-topbar-soft-edge-simulated.png`). Map viewer ✕ and bottom
   card (chrome per the constitution's surface 9) moved to `glassEffect`
   circle/rect — real refraction over cartography, text legible
   (`map-viewer-glass-chrome-simulated.png`). Content never glass.
3. **x/y/z wink restored** — feed ride-card stat labels read
   `Distance x / Climbing y / Time z`, letters in muted italic (gray2),
   caption2, feed cards only (`FeedCardStat`). VoiceOver reads the fact, not
   the letter. `feed-cards-all-variants-simulated.png`.
4. **Label-above-value unified** — one `FeedCardStatTrio` grammar for
   RideCard, LocalSavedRideCard (previously inverted), and LocalRideCard;
   value font unified to `.numeral(.subheadline)` (gallery 15px rounded
   medium). Same capture.
5. **Empty-ride End acknowledgment** — ending with zero accepted samples
   shows one quiet alert: "No ride data was recorded." / single "Discard"
   (`recording-empty-end-acknowledgment-simulated.png`), wired through
   the existing truth boundaries: projection `sampleCount` (synced through
   the End cutoff) + the eligibility path. Discard runs the exact-owner
   custody discard saga (`discardFinalizedLocalRecording`) — never touching
   upload-eligible or handed-off evidence; a durability failure leaves the
   pending intent for the next activation. Unit-proven in
   `NativeGate1CustodyTests.testAcknowledgedEmptyRideDiscardRemovesCustodyButNeverEligibleEvidence`.
6. **Status out of the title slot** — LocalRideCard now titles with
   `Format.displayRideTitle` and renders status ("Processing", "Under
   review", "Processing failed", "Signed out") as a small gray caption under
   it; "This ride is under review." shortened to the caption-shaped "Under
   review" (Strava/Garmin-shaped system string class). Server RideCard adds
   the same caption for `under_review`. Route-less cards omit the map section
   entirely — verified: RideCard renders the band only when drawable
   fragments exist (the under-review card in the capture has none).
7. **Fail-closed dialog demoted** — the RootView "Ride evidence is
   unavailable" alert (the one with the "Sign out" remedy) is now a quiet
   inline card at the top of the feed with Retry only; sign-out stays in the
   avatar sheet. Same capture, top card. Scope note: the recorder's own
   mid-ride custody alert (Retry/Cancel, no sign-out) is a different truth
   boundary guarding live evidence and intentionally remains modal.

## Dynamic Type + VoiceOver

- `feed-cards-dynamic-type-accessibility-large-simulated.png` and
  `recording-dynamic-type-accessibility-large-simulated.png` —
  accessibility-large holds on both touched surfaces. Found and fixed in the
  same pass: the recording small-metric grid truncated values at
  accessibility sizes → the layout now stacks one metric per row when
  `dynamicTypeSize.isAccessibilitySize`.
- VoiceOver: label-level proofs in code (wink letter excluded from the
  accessibility label; dash reads "unavailable"; icon-only controls keep
  their verbs as `accessibilityLabel`; custody card exposes text + Retry
  button). Hardware VoiceOver remains on the existing lane-wide physical
  gate, consistent with prior evidence notes.

## Production read (test account "Rider HJTP", reads only, 2026-08-11)

`feed-production-read.png` — the live feed after DEV re-auth:

- The under-review upload job card now shows its real title ("Morning
  Ride") with the "Under review" caption — in the pre-change production
  capture the sentence sat in the title slot (item 6, production-proven).
- The x/y/z wink renders on every production card (item 3).
- The known stale-custody condition on this simulator reproduced item 7
  live: what used to be the blocking "Ride evidence is unavailable" modal
  with a Sign-out remedy is now the quiet inline Retry card, with the feed
  fully usable behind it.
- Route-less production cards omit the map section (item 6 verification).

## Honest gaps

- Power-hero and sensor rows cannot be produced by real BLE on a simulator;
  the fixture injects the sensor snapshot while every render/custody path
  stays production. Physical-device captures remain on the physical gate.
- The reveal flow, deposit sheets, and other untouched surfaces were not
  re-evidenced.
