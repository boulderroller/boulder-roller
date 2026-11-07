# Map Candidate V4

Run `npm run workshop -- --port 4323` from `web/portal`.
Open <http://localhost:4323/?surface=map&variant=map-v4&scenario=wises&viewer=rider&origin=43f15658-a824-438d-9925-e61c67ddabe9>.

## Design

The selected-climb card uses an opaque warm surface, clearer title/locality hierarchy, a full-width supplied elevation profile with distance/elevation scales, and aligned measurements. The profile echoes the selected road's existing blue. The card is taller than V3; on phone, opening the list temporarily folds the profile away to make comparison usable. Missing profiles remain absent. Existing sourced identity and RankMark handling carry forward.

One Filters control exposes distance, average grade and elevation-rise ranges. These and name search narrow the map and list together; the list also respects the last searched area. Filters apply immediately, show an active count, and reset together. Excluding the selected climb clears its inspector without moving the camera. No-results and source-failure states remain distinct. The filter ranges are controls over supplied measurements, not coverage or rider-result claims. Place search and unsupported social/economic filters are outside V4.

Cartographic changes preserve the accepted v12Ground palette and its existing DEM/contour sources. Regular contours become quieter than index contours; local road labels appear slightly earlier as you zoom. Hover thickens green marks while selection owns blue. Climb labels face toward the map's center to stay legible near phone edges. MapLibre's metric scale control follows the real camera. No bounds become invented routes. Relevant label API: <https://maplibre.org/maplibre-style-spec/layers/#text-anchor>.

New phone arrivals fit the supplied origin's bounds above the card, capped at zoom 13.8, leaving surrounding ground visible. Explicit Fit surrounding climbs still fits the neighborhood. Neighbor selection preserves zoom and gently pans. Panning, filters, clearing and list disclosure do not reframe. Detail and browser Back preserve camera, filters, list position and selection. Keyboard dismissal returns focus to an available control.

## Integration

- Bead `boulderroller-v2-0x18y`; branch `codex/0x18y-map-v4`; visible sibling worktree `/Users/gabetemp/curahee/BoulderRoller-worktrees/map-v4`.
- Started from freshly fetched `origin/main` at `a63ffc77f`, explicitly merging completed Map V3 `2673c094d54deac52d672bc415e9cf4817f04d17`. Both dependency tracker sets were checked for exact preservation. The human root and active Climb checkout were not edited.
- V4 owns this directory. Earlier Ride, Feed, Climb and Map candidate files are unchanged. This dependency includes Climb V1–V3; the concurrently evolving Climb task remains separate until the shared-workshop owner consolidates completed commits.
- Shared registration is a separate commit: `map/MapWorkshop.tsx`, `map/MapPreview.tsx`, `workbenchNavigation.ts`, the Map count in `main.tsx`, and one test entrypoint. Reconcile these small edits into the evolving common harness; do not replace its whole files.
- `mapV4ExploreHref(climbId, viewer, scenario)` is the **fresh arrival** helper. Its one-use `arrival=climb` intent selects/reveals even a previously excluded same-origin hill and clears old filters/camera. Ordinary detail-return links omit that intent and restore browsing. The harness consumes it when writing its normal URL. These are local workshop behaviors, not claims about production URLs.
- Snapshot keys use `br-map-v4:<study-id>`. V2/V3 keys and behavior are retained. The V4 restoration adapter must accompany registration so filters survive preview messages and candidate/page switches.
- Preview 4323 leaves 4318, 4320 and 4322 available. No merge to main, deployment, or automatic cross-checkout synchronization. Rider Profile and retained-baseline consolidation remain outside this candidate.

## Verification

104 workshop tests, workshop typecheck and workshop build pass. Focused red-to-green covers metric filtering, restoration, invalid filter input, different-origin arrivals and same-origin fresh Explore. The existing large-workshop bundle warning remains.

Local browser checks cover all six scenarios, all three viewer modes, loading/empty/list-error/map-error and retry, filtered map/list consistency, no-match reset, keyboard selection/Escape, pointer selection/panning, detail return and native Back, old-candidate isolation, page switching, validated scenario import, inspectable export/reimport, Strava references, and desktop/phone controls.

Exact 1440×1000 and 390×844 views, plus the open filter surface at each size, are in `evidence/`. Both layouts have no document overflow. Terrain was reviewed at neighborhood and close zoom. Final fresh-page console error/warning logs are empty. A transient development hot-refresh component-type error was resolved by a fresh load.

Phone evidence uses keyboard and pointer input at 390×844. The in-app browser does not support synthetic touch dispatch; physical touch is unverified. Native download completion is not claimed. Built-in scenarios provide retained published geography, not live rider or Vault state. See `evidence/interactions.json` and the inherited `../README.md` source boundaries.
