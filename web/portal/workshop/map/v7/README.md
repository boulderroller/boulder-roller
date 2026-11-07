# Map Candidate V7

Settled V7 with final consistency patch: <http://localhost:4328/?surface=map&variant=map-v7&scenario=wises&viewer=rider&origin=43f15658-a824-438d-9925-e61c67ddabe9>

Original V7 remains available on port 4327.

V7 is a restrained adjustment of **original V5**, following the user's rejection of V6's layered tile treatment. The name uses the full row width; a compact elevation trace sits alongside distance, rise and grade underneath. Rows retain V5's single surface, fine separators and selection wash, at 78px desktop / 76px phone minimum height. Short phone lists fit their contents within the existing maximum area.

V5's stylesheet, map canvas, ground, contours, landmarks and selected-card profile are directly reused. The V7 stylesheet only changes row composition, short-list sizing and inline leader spacing. There are no new row containers or inset plot panels. V1–V6 remain unchanged for comparison, as do the inherited Ride, Feed and Climb generations.

The small traces use only supplied samples, with the same twofold vertical exaggeration across climbs. Steep profiles fit both axes together, preserving comparative slope. Missing profiles leave no placeholder graphic. The selected card keeps V5's labeled elevation chart.

First place, when supplied, is a compact inline rank-one mark, public wallet and time. V6's source-bound public leaderboard validation is reused unchanged: no first-visible-row promotion, no invented names, portraits, activity counts or holder. The supplied geography scenarios still contain no public-holder snapshot. The isolated `tests/leader-layout.html` and `evidence/leader-component-390.jpg` use a **labeled synthetic fixture** to verify layout; they are not live results or workshop scenarios and are excluded from the build.

## Verification

- Focused red-to-green: truthful twofold trace scale and separate V7 candidate/snapshot identity.
- 114 workshop tests and workshop typecheck pass. Final workshop build passes with the existing large-chunk warning.
- Exact 1440×1000 and 390×844 renders without horizontal overflow. All six scenarios and three viewers use V7. Bounds-only import shows one marker, zero routes, zero profiles and no leader; an unbound leaderboard import is rejected.
- Keyboard selection closes the phone list and focuses Open climb. Native Back restores the exact camera, Wises origin, neighboring selection and focus. Selecting nearby Valley Green changes camera center at unchanged zoom.
- Clear, pointer pan, filters/reset, short and 57-row phone lists, loading/empty/error/retry, preserved V5/V6 switching and Strava reference checked. Browser warning/error logs are empty.

This is local responsive-browser proof, including pointer and keyboard interaction. Physical touch-device behavior and production integration/deployment are not claimed.

## Integration handoff

Final consistency patch: branch `codex/14idz-map-v7-alignment`, Bead `boulderroller-v2-14idz`, sibling worktree `map-v7-alignment`. Starts from refreshed `origin/main` and carries V7 dependency `0b74b9427368c393a6fa3989ccf62cf640262183`. Run the same workshop command below with port **4328** for this patch.

The final Ride V13 / Feed V9 comparison retains the settled composition, map ground, flat rows, quiet numeric units, circular identity treatment and shared production RankMark artwork. Ordinary controls now use Ride's two-pixel `#737e58` keyboard focus. A failed portrait falls back to initials using Ride V13's behavior; a subsequent valid portrait recovers. These are the only rendering changes. During production integration, use the common portal shell and identity components rather than preserving workshop-local duplicates.

Focused browser red: invalid portrait rendered a broken image without initials; ordinary keyboard focus was blue. Green: initials `ER`, no broken image, replacement portrait loaded, and `Open climb` keyboard focus is `rgb(115, 126, 88)`. `tests/identity-focus.html` is a labeled synthetic component fixture, excluded from the build. The patch passes all 114 workshop tests, typecheck and build (existing chunk-size warning); `evidence/alignment-*` records 1440×1000 and 390×844 layouts without horizontal overflow. Earlier candidate files and shared workshop registration are unchanged.

Branch `codex/7o4if-map-v7`; Bead `boulderroller-v2-7o4if`.

Created from refreshed `origin/main` (`a63ffc77f9638b78d3a404be2575aaa7ddd9c145`), carrying forward dependency `c815507c1d8be7ad75f5d564dd5b300d342a1df3` to retain V6. The new visual implementation is copied from V5, not V6.

Candidate implementation and tracker are one commit; shared registration is a separate small commit. Apply owned `v7/` files first, then reconcile the changes to `MapWorkshop.tsx`, `MapPreview.tsx`, `workbenchNavigation.ts`, `main.tsx` and the V7 test entrypoint. Preserve newer Climb or other workshop registrations; do not replace shared files wholesale.

Run `npm run workshop -- --host localhost --port 4327 --strictPort` from `web/portal`. All previous preview servers, including Climb on 4318 and V5/V6 on 4325/4326, were left running. Production remains separate.
