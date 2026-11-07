# Map workshop — Candidate V2

Run from `web/portal`: `npm run workshop -- --port 4320`.

Open <http://localhost:4320/?surface=map&variant=map-v2&scenario=wises&viewer=rider>.
Map is in the shared Workshop page dropdown. Port 4318 and the Climb task's checkout are independent.

## Integration handoff

- Branch: `codex/kuyx3-map-workshop`; Bead: `boulderroller-v2-kuyx3`.
- Started from current `origin/main` (`78c9feb43`) and carried forward workshop dependency `8e8dfad0f` by fast-forward. Ride V1–V13, Feed V1–V9 and Climb V1–V3 implementations remain unchanged.
- The Map implementation, retained references, data, tests and evidence live in this directory. Shared registration is a separate commit: `main.tsx`, `workbenchNavigation.ts`, the Climb harness's destination dispatcher, and one workshop test entrypoint. Apply those small changes to the current harness; do not replace the entire Climb checkout.
- `mapExploreHref(climbId, viewer, scenario)` in `mapNavigation.ts` provides the V4 Explore link. Canonical UUIDs are preferred; a unique legacy eight-character ID prefix is accepted. Unknown origins show an unavailable notice without substituting Wises Mill.
- The Map candidate has its own geography detail view, using the preserved Climb map and profile primitives. `climb=<canonical UUID>` opens it; Explore climbs and browser Back restore map camera, selection, list position and focus. Hooking the separately evolving Climb V4 into this entry point is a subsequent integration change. No Climb candidate was rewritten.
- All six scenarios use V2. V1 is a retained production-design capture with fixture data, labeled accordingly. Current production `/climbs` required sign-in during inspection; this work does not establish a current authenticated live baseline.
- No production integration or deployment is included. Rider Profile remains the recommended next workshop.

## Data and interaction

The 57 supplied climbs come from the published Philadelphia geographic release of 9 September 2026. `data/philadelphia.json` retains canonical centerlines and correlated elevation profiles. Source climb-list SHA-256: `a96a1f40ac250b4daa10d5f04be894046ff91f524e667c9f99654e2471bb5dd6`. The source release is named in the data's `sourceUrl`; ODbL notices and source attribution are retained alongside it.

Elevation rise is finish minus start elevation, not accumulated ascent. Built-in scenarios supply no rider results, identity, social counts, Vault state or coverage claim. A supplied, identity-bound standing may render the accepted RankMark asset. Bounds-only and mixed scenarios deliberately omit geometry; bounds produce markers, never route lines.

Arriving from a hill frames it with supplied neighbors. Hover does not move the camera; panning retains selection; blank-map click or Escape clears selection while preserving the camera and origin. The phone sheet expands for search/results and contracts on selection. Search this area updates the list without resetting the camera.

Data supports validated JSON import, an inspectable/copyable JSON export, and Download JSON. Imports persist in session storage and are isolated by scenario ID. Missing imports expose recovery. Independent geometry and elevation profiles remain independently available; absent information stays absent.

## Local verification

- `npm run workshop:test`: 95 passing tests. Focused red-to-green covered geometry provenance, locality truth and unavailable-origin substitution.
- `npm run workshop:typecheck` and `npm run workshop:build`: pass. The existing large-workshop chunk warning remains.
- `evidence/map-v2-1440.png`: exact 1440×1000. `evidence/map-v2-390.png`: exact 390×844. Both have no horizontal overflow.
- `evidence/interactions.json`: keyboard selection, Escape, pointer map selection, panning, neighbor detail/return, native browser Back, phone sheet/search, viewer modes, all scenarios, loading/empty/error recovery, imports, JSON export/reimport, dropdown continuity and Strava reference toggle. Camera, zoom, selected ID and list scroll match before/after the desktop round trip; camera, zoom and selection also match on phone.
- Browser logs contained no errors or warnings. Phone evidence uses a 390×844 browser viewport and pointer/keyboard input; it is not a physical-device touch claim. Native download completion was not observable through browser tooling; inspectable JSON export and reimport were verified.

All proof is local workshop evidence using retained published geography, not deployed or physical-rider evidence.
