# Map Candidate V3

Run from `web/portal`: `npm run workshop -- --port 4322`.
Open <http://localhost:4322/?surface=map&variant=map-v3&scenario=wises&viewer=rider&origin=43f15658-a824-438d-9925-e61c67ddabe9>.

## Design intent

The geography occupies the full page. Search is a small upper-left control; the selected climb occupies a compact lower-left card. On phone, that card sits at the bottom. The optional list joins the same card instead of adding a second panel. This gives browsing more terrain and makes comparison a deliberate action. Opening the list costs one click or tap; it remains available for sorting, search and keyboard discovery.

Selecting a different hill makes a short pan at the current zoom, including when both hills are already visible. Hover, list disclosure and clearing selection leave the camera alone. Panning keeps the selection. Opening detail stops any remaining animation and saves the actual camera. Explore climbs and browser Back return to that camera, selection, list position and keyboard focus. V2 and V3 retain separate browsing snapshots.

The accepted map ground, typography and RankMark assets are reused. Search narrows the list while neighboring map geometry remains visible. Bounds produce markers; only supplied canonical centerlines produce routes. The inherited source and truth limits are documented in `../README.md`: retained published geography, no built-in rider results or invented coverage, and V1 explicitly labeled as a retained fixture capture. This is local workshop proof, not deployed or physical-rider evidence.

## Integration handoff

- Branch `codex/seb0i-map-v3`; Bead `boulderroller-v2-seb0i`; sibling worktree `BoulderRoller-worktrees/map-v3`.
- Started from fetched `origin/main` at `78c9feb43`, carrying V2 dependency `58b908ce99f6b1a9e749b9c742ef222f9206a2a4` and its Climb V3 dependency `8e8dfad0f` forward. Previous candidate implementations are unchanged.
- V3 code, tests and evidence are owned by this directory. Shared registration is committed separately: `MapWorkshop.tsx`, `MapPreview.tsx`, the Map default in `workbenchNavigation.ts`, the Map candidate count in `main.tsx`, and one test entrypoint. Apply those small changes to the current harness; do not replace the evolving Climb checkout.
- `mapV3ExploreHref(climbId, viewer, scenario)` in `mapV3Model.ts` is the workshop entry helper for later Climb integration. Detail and return URLs retain `variant=map-v3`. This does not assert those URL behaviors exist in production.
- Preview 4322 leaves 4320 and 4318 running. No production integration or deployment. Rider Profile remains outside this candidate.

## Verification

- All 99 workshop tests pass; typecheck and build pass. The existing large-workshop chunk warning remains.
- Focused red-to-green covers same-scale selection movement, phone framing, candidate URL/storage isolation and rejection of stale candidate/revision/study messages.
- Local browser checks covered all six scenarios, three viewer modes, loading/empty/error and map retry, keyboard selection/Escape, pointer map selection and panning, detail return and native Back, candidate/page switching, validated import, inspectable JSON export/reimport and the Strava reference.
- Phone evidence uses a 390×844 browser viewport with pointer/keyboard input; it does not establish physical-device touch behavior. Native download completion is not claimed; inspectable export/reimport was exercised.
- `evidence/interactions.json` records the observed outcomes and selected camera measurements from the browser session.
- Exact 1440×1000 and 390×844 layouts are saved as `evidence/map-v3-1440.jpg` and `evidence/map-v3-390.jpg`. Both have no document overflow. The browser reconnected after a temporary interruption; the final captures were saved successfully and browser error/warning logs were empty.
