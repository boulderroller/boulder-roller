# Profile Candidate V5

Local workshop candidate, 14 September 2026. No production integration or deployment.

Open `http://localhost:4337/?surface=profile&variant=profile-v5&scenario=rider&viewer=owner&tab=overview&state=ready`.
Run from `web/portal` with `npm run workshop -- --port 4337`. V4 remains on 4336.

## Design delta

V4 established the accepted identity: personal banner and portrait, named hills, riding rhythm and a place map. V5 refines its proportions and gives recent rides more character without changing that hierarchy.

- Climb standing uses smaller accepted RankMarks, tighter housing, stronger hill names and clear best times. Phone standing occupies 258px for three rows, compared with 336px in V4.
- Recent rides use Feed-derived date/title/measurement grouping, thin separators and whole-entry interaction. An optional photograph, note or explicitly supplied personal best gives an entry its own character. The Rides tab and ride summary use the same presentation.
- The four-week calendar has weekday/week labels and exact readings. Hover and keyboard focus inspect a day; activation filters recent rides. Arrow keys move through dates, Home/End reach the period bounds, and Escape clears selection.
- Edit profile now supports local banner and portrait selection/removal. Image decoding, file limits, pending reads and persistence errors keep failed edits visible in the dialog.

Profile V1–V4 and earlier Ride, Feed, Climb, Map and baseline files remain unchanged.

## Truth and media

The V4 fictional Alex Rivera profile, twelve ride summaries, social counts and sporting standings remain explicitly illustrative. V5 retains the same complete 28-day history: 558.2km and 6,770m climbed across twelve rides. Sparse history produces no complete-period total; private profiles contain no rider, rides or standings.

The three personal-best moments are authored examples bound to the matching ride and canonical hill. They are not inferred from a current rank or represented as live activity. Wises Mill, Black Rock and Sprague ride bindings match their titles and standing examples. No new leaderboard category, economic state or real rider claim is introduced.

`assets/coffee.png` is a generated fictional cycling coffee-stop photograph. The banner and portrait reuse V4's generated assets. The photo and note on the Sunday ride are illustrative. Imports may supply PNG/JPEG/WebP data images; arbitrary remote media URLs are rejected. Edit profile accepts decoded images under 2MB, stores them only in this local browser session, and reports failures inline. JSON export is the transfer mechanism for local edits/imports.

Geography reuses Map V7's retained canonical collection and accepted terrain canvas. Supplied bounds are not converted into invented route lines. Ride detail is an authored summary with route unavailable. Portfolio retains unavailable balance. Real media persistence, edit/follow operations, public profile sharing and authorized rider/history/standing adapters remain production work.

## Verification

- 163 workshop tests, typecheck and build pass. Build retains the existing large-workshop chunk warning. The new model tests first failed for the absent V5 module, then passed with the implementation.
- Exact 1440×1000 and 390×844 screenshots in `evidence/`, plus the phone recent-rides view. No horizontal overflow; longer imported ride titles also fit the phone preview.
- Keyboard tabs, Rides search/climb filters, Training totals and unavailable Portfolio; ride entry/return restores the query, selection and focus. Named hill navigation and browser Back restore Profile.
- Calendar focus/hover inspect without filtering; activation filters, empty days show no rides, Escape clears, and ride return retains the selected day. All day targets are at least 24×24.
- Banner image selection/save, rejected oversized image, restored supplied scenario; independent review also checked pending read/save races and inline persistence failures.
- Owner/visitor, sparse/new/private and loading/unavailable/offline states. Strict JSON/text and file imports reject unknown fields; imported scenario survives reload and V1/V4/V5 switching. Export, Strava reference, squint and preview-size controls exercised. No browser errors on the final stable reload.

## Integration handoff

Branch `codex/31znc-profile-v5`, Bead `boulderroller-v2-31znc`, visible sibling worktree `/Users/gabetemp/curahee/BoulderRoller-worktrees/profile-v5`.
Started from current `origin/main` at `a63ffc77f9638b78d3a404be2575aaa7ddd9c145`, carrying the complete V4 workshop dependency `2d179421fc3445571d3e2dacad5f75d71c95c8ed`.

Candidate ownership is `workshop/profile/v5/` and `workshop/tests/profile-v5.test.ts`. Shared registration is kept in a separate commit, limited to `main.tsx` and `roomRegistry.ts`: V5 preview dispatch, wrapper import and Profile default. Apply those small edits to the current harness when integrating; do not replace the shared files wholesale. Earlier candidate servers and other task checkouts were left untouched.
