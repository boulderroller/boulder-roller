# Route rendering unification — evidence (bead boulderroller-v2-zudgp)

**Evidence class:** simulated renders over real-fixture-derived data (labeled
`-simulated`), plus backend/unit proofs. Production-read captures of the
pre-change dotted route already exist
(`live-feed-corrected-climbing-production-read.png`, second card). The
post-change production feed render is gated on the backend deploy of this
branch's `feed_contracts.py` — named honestly below.

## Root cause (two layers, both fixed)

1. **Backend preview sampler (the actual dotted route).** For any track over
   the preview budget, `_sample_route_runs` emitted disconnected 2-point
   *original edges* (deliberately chord-free). Every real ride (>48 preview
   points) rendered as ~24 beads on the feed card and the public share page.
   The iOS client was drawing that wire data faithfully.
2. **iOS saved-track assembly borrowed the live-capture policy.** The 8 s
   capture outage rule shatters credible imports (Garmin smart recording
   spaces samples up to ~15 s), and preview-wide implausibility quarantine
   deleted whole previews over one GPS glitch.

## What changed

- `backend/app/feed_contracts.py` — bounded-deviation simplification
  (per-run RDP, original vertices only, budget 320 pts, tolerance ladder
  2→32 m) replaces edge-bead sampling. Privacy laws preserved and pinned by
  test: run boundaries (redactions/trims) never bridged; **no drawn edge
  crosses a saved privacy zone** — simplified edges are re-checked against the
  privacy engine's own `_segment_intersects_zone` predicate and refined back
  toward original vertices until clean (zones are threaded from every
  non-owner call site: ride detail, public previews, feed, public profile).
  Implausibility (>50 m/s at ≥25 m) now severs the single bad edge instead of
  quarantining the preview; `implausible_geometry` fallback remains only when
  nothing credible survives.
- `ios/BoulderRoller/Components/RouteMap.swift` — `RouteRenderPolicy`
  (documented constants): speed ceiling 55 m/s drops the point; outage
  threshold 60 s; a >60 s gap still *connects* when endpoints moved ≤100 m
  (stationary cafe pause) and *breaks* otherwise; timestampless adjacency
  draws no edge; **singleton rule: fragments under 2 points are skipped,
  never drawn as dots**. Shared stroke ledger `RouteMapStyle` + interactive
  `RouteMapContent` — the map viewer now draws through the same
  geometry/style pipeline as the snapshot bands (feed card, ride sheet band,
  climb band); only stroke scale differs by surface class.

## Fixture validation (real Philadelphia rides, main checkout)

Fixtures live at `/Users/gabetemp/curahee/BoulderRoller-v2/tests/validation/`
(gitignored FIT files; decoded with `fitdecode` in a scratch venv — the repo
has no real-Philadelphia GPX, so the FIT ride fixtures are the real-ride
source; noted per instructions):

| Fixture | Input points | Old sampler | New builder |
|---|---|---|---|
| `t_h_e_w_a_l_l.fit` | 467 | 24 × 2-pt beads | **1 run × 174 pts** |
| `05_07_2015_Philadelphia_Pennsylvania.fit` | 7,344 | 24 × 2-pt beads | 4 runs (71/91/81/17) — 3 genuinely implausible edges severed |

## Captures (simulated, real-fixture data, production render paths)

- `route-feed-wall-fixture-simulated.png` — feed card rendering the
  new backend preview of the real Wall ride: one continuous line.
- `route-viewer-wall-fixture-simulated.png` — map viewer, same
  fragments through the shared `RouteMapContent`: identical continuous
  geometry (Manayunk → Schuylkill → Brewerytown).
- Render seam: `ios/BoulderRoller/Debug/RouteRenderFixture.swift`
  (`-BRRouteRenderFixture feed|viewer` +
  `BR_ROUTE_RENDER_FIXTURE_PREVIEW_PATH`) — data injection only; drawing code
  paths are production.

## Tests

- Backend `tests/services/test_feed_contracts.py`: 13 passed — continuity
  regression (5,000-pt credible track → one run), zone edge law under
  simplification (the 200.1 m circle / 200 m zone knife-edge), per-edge
  severing, no-credible-edge quarantine.
- iOS suite: 220 passed / 0 failed (218 baseline + smart-recording
  continuity, moving-outage vs stationary-pause, singleton-skip).

## Production reads (test account "Rider HJTP", reads only, 2026-08-11)

The two lunch-ride screenshots below show a real route and are left out of
the public copy.

- `ride-sheet-lunch-ride-continuous-production-read.png` — a full
  production ride ("Lunch Ride", the Conshohocken/Merion loop) rendering
  one continuous route on the ride-sheet band from full production GPS
  through the new `RouteRenderPolicy` (the sheet's detail stats dash —
  the server withholds under-review metrics; truthful abstention).
- `viewer-lunch-ride-continuous-production-read.png` — the same ride
  in the map viewer via the shared `RouteMapContent`: identical continuous
  geometry, glass chrome.
- The production FEED still shows the beaded previews
  (`feed-production-read.png`, second card) — expected: the wire
  still carries the old 24-edge sampling until this branch's backend
  deploys. The 2015 34 mi ride's feed card still has NO map in production
  (the old preview-wide implausibility quarantine — exactly the failure
  the per-edge severing replaces; its fixture run above yields 4 credible
  runs).

## Honest gaps

- Post-deploy production feed captures remain gated on the backend deploy
  of this branch (previews regenerate on read; no backfill needed — they
  are built per-request from `gps_track`).
- The intended production-read target was the 34 mi 2015 import; the ride
  actually opened was the "Lunch Ride" loop — an equivalent (and longer
  than the sim rides) full-GPS continuity validation. The 2015 ride's
  sheet remains uncaptured.
