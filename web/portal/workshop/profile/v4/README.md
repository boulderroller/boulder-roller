# Profile Candidate V4

Local workshop candidate, 14 September 2026. No production integration or deployment.

Open `http://localhost:4336/?surface=profile&variant=profile-v4&scenario=rider&viewer=owner&tab=overview&state=ready`.
Run from `web/portal` with `npm run workshop -- --port 4336`.

## Design

Person, standing on named hills, riding rhythm, then recent history. A personal photograph and overlapping portrait establish identity; a single green standing strip carries the accepted rank artwork. The smaller map connects those results to actual places. Ride summaries remain subordinate. Overview, Rides, Training and Portfolio live within one Profile workshop; visitors receive only the public Overview.

This responds to the rejection of V3 as too similar to Ride View. V1–V3 and every earlier Ride, Feed, Climb, Map and baseline generation remain unchanged.

## Evidence and data boundaries

- Alex Rivera, the photographs, twelve distinct ride summaries, social counts and current sporting standings are **illustrative**, authored specifically to evaluate a complete profile. They are not live rider evidence. The workshop labels this continuously.
- `assets/creek.png` and `assets/portrait.png` were generated with the built-in image tool. The fictional rider in the portrait is derived from the fictional rider in the creek photograph. Neither depicts or identifies a real supplied rider or claims a real photograph of the canonical climbs. The images may be replaced with supplied data images through scenario import.
- Geography is the retained canonical collection used by Map V7: Wises Mill Road, Black Rock Road and Sprague Road. V4 reuses the accepted Map V5 canvas/terrain (also used by Map V7) and the production RankMark renderer. Bounding rectangles never become route lines.
- Sporting rank is an explicitly supplied competition rank, independent of the date of the best time. Absent ranks remain absent. No gender category or KOM classification is inferred.
- The calendar and weekly totals derive from a declared complete 28-day history period. Partial history never produces complete-period totals. Imported timestamps normalize to UTC before display, aggregation or day selection.
- Ride detail in this candidate is an authored **summary**, with route unavailable. It does not attach an unrelated real recording to the fictional rider. Canonical climb links open Map V7 detail; browser Back restores Profile.
- Edit, Follow and Share are local workshop interactions. Imports and edits persist in this browser session. Copying a URL does not transfer an imported scenario; use the JSON file. Portfolio deliberately shows an unavailable balance.

## Verification

`workshop:test`: 160 passing; `workshop:typecheck`: passing; `workshop:build`: passing, with the existing large-workshop chunk warning.

Focused red-to-green covered coherent rider ownership, private payload rejection, missing rank and partial-history behavior, invalid import fields, bounded periods and UTC day consistency. Independent read-only review identified import and return issues which were corrected and probed.

Browser checks covered:

- Exact 1440 × 1000 and 390 × 844 layouts, no horizontal overflow, squint view and 24 × 24 calendar targets. Final exact PNG captures are in `evidence/`.
- Keyboard arrow/Home/End tab navigation, search and climb filtering, calendar day selection, ride summary entry and return to the active row and scroll position, including the last row on phone.
- Named climb navigation and browser Back; Profile remains mounted for continuity.
- Owner and visitor modes, Follow, Edit and photo dialog Escape/focus return; sparse, new, private, loading, unavailable/recovery and offline cases.
- JSON-text and file imports, rejected unknown fields, export/copy, imported scenario reload, V1/V2/V3/V4 switching, and selection surviving a reload in V1.
- Strava reference and Desktop/Phone controls. Retained V1 renders and returns to V4 with no new browser errors after dependency optimization completed.

## Integration handoff

Branch `codex/qdu0o-profile-v4`, Bead `boulderroller-v2-qdu0o`, visible sibling worktree `profile-v4`.
Started from `origin/main` at `a63ffc77f9638b78d3a404be2575aaa7ddd9c145`, carrying the complete Profile V3 workshop dependency at `06347df6f`.

Candidate ownership is `workshop/profile/v4/` plus `workshop/tests/profile-v4.test.ts`. Shared registration is a separate commit, limited to `main.tsx` and `roomRegistry.ts`: V4 preview dispatcher, wrapper import and Profile default. Integrate those small changes with the current shared registry; do not overwrite the other workshop registrations. The running local preview is 4336; earlier preview servers remain untouched.

Production needs real authorized rider/media/history/standing adapters and real edit/follow/share behavior. This candidate does not establish that those contracts or operations are live.
