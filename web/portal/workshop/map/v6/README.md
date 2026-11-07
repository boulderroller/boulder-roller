# Map Candidate V6

Local workshop: <http://localhost:4326/?surface=map&variant=map-v6&scenario=wises&viewer=rider&origin=43f15658-a824-438d-9925-e61c67ddabe9>

V6 makes the climb tiles and selected card one family: a warm cut edge, inset elevation shape, aligned measurements, and soft blue selection. The list stays optional. Profiles use the supplied samples across the available width; each inset prints its own elevation limits. Compare grade with the explicit percentage, not the visual slope of differently scaled profiles.

The accepted V5 map canvas, terrain, contours, landmark assets and camera behavior are directly reused. Earlier Map V1–V5, Ride V1–V13, Feed V1–V9 and Climb V1–V3 files are unchanged.

## First place and activity truth

The accepted rank-one artwork appears only for an explicit public holder whose wallet and time match a first-place entry. Ties remain ties. A missing or withheld holder is omitted; the first visible row is never promoted. Viewer standing is a separate fact.

Bounded unauthenticated API checks on 13 September 2026 at 21:27–21:28 UTC found no public holder for the supplied area: Wises had no active Vault; the 57-climb list had one active Vault, Shawmont Avenue (Vault ID **0**, a valid ID), whose public board was also empty. These are dated API observations, not ongoing live state. No rider counts or activity aggregates were supplied. Neither absent fact becomes a zero or an invented line of chrome.

The canonical leaderboard endpoint currently provides wallet identity, not rider names or portraits. V6 rejects non-null name/portrait fields attributed to that endpoint. Enriched rider identity requires a separately bound public identity source during integration.

V6 imports accept an optional `publicLeaderboard` on a climb with:

- `sourceUrl`: exactly `https://api.boulderroller.xyz/climbs/<canonical-climb-id>/leaderboard`.
- `capturedAt`: an ISO timestamp for the retained public response.
- `response`: the public response with matching `climb_id`, explicit `kom_holder` / `kom_time_s` (both null when absent), and original `entries` with `wallet`, `position`, `competition_rank`, `best_time_seconds`, `tie_size` and `is_tied`.

Imports validate consistency and source binding; they do not authenticate the capture or claim current public state. The capture date and source are available on the leader treatment. The isolated `tests/leader-layout.html` component check uses a **clearly labeled synthetic fixture**, is not a Map scenario, and is excluded from the workshop build. Its screenshot proves layout only.

## Local verification

- Focused red: the previous parser accepted another climb's leaderboard; V6 rejects it. Additional checks cover explicit holder selection, nulls, no promotion, viewer separation, ties, integer times and unsupported identity.
- An older candidate's unchecked import initially left the older design visible on a failed switch. The shared preview now shows the selected candidate's error state instead.
- 112 workshop tests, workshop typecheck and workshop build pass. Build retains the existing large-workshop chunk warning.
- Exact 1440×1000 and 390×844 captures, without horizontal overflow. Keyboard selection, gentle neighboring-climb pan, clear, pointer pan, filters, missing profile/route, loading/empty/error/retry, all scenarios/viewers, imports, candidate isolation and Strava toggle checked.
- Native Back from Valley Green detail restored the exact camera, Wises origin, selected neighboring climb, closed phone list and Open climb focus.
- Browser console checks found no errors or warnings. Phone evidence is responsive browser and pointer/keyboard proof, not physical touch-device proof.

See `evidence/` for dated local renders and interaction results.

## Integration handoff

Branch: `codex/87vw7-map-v6`. Bead: `boulderroller-v2-87vw7`.

Created from refreshed `origin/main` (`a63ffc77f9638b78d3a404be2575aaa7ddd9c145`) and carried forward V5 dependency `32659ed7bbebfaab5a51c277ef3f6bea372dd65e`.

Candidate implementation and tracker are one commit; small shared registration changes are a separate commit. Apply the candidate files first, then reconcile the registration diff in `MapWorkshop.tsx`, `MapPreview.tsx`, `workbenchNavigation.ts`, `main.tsx` and the single test entrypoint. Preserve any newer Climb registrations rather than replacing shared files wholesale. V6 has its own candidate URL and snapshot namespace.

Run `npm run workshop -- --host localhost --port 4326 --strictPort` from `web/portal`. V5 remains on 4325; the older Map and Climb previews were left running. Production integration and deployment are separate and have not been performed.
