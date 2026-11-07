# Climb V6 design QA

final result: passed

Local workshop candidate only. No production merge, deployment, new rider evidence, or protocol change.

## Source and target

V5 is the preserved visual baseline, with the user-approved V6 direction: stronger leaderboard composition, integrated effort inspector, coherent time precision, grouped leading times, fixed dark navigation, and the existing map and history interaction language.

Source captures: `evidence/climb-v5-1440.jpg`, `evidence/climb-v5-data-1440.jpg`, `evidence/climb-v5-history-390.jpg`, `evidence/climb-v5-board-390.jpg`.

Implementation: `evidence/climb-v6-1440.jpg`, `evidence/climb-v6-data-1440.jpg`, `evidence/climb-v6-comparison-1440.jpg`, `evidence/climb-v6-390.jpg`, `evidence/climb-v6-history-390.jpg`, `evidence/climb-v6-board-390.jpg`.

Desktop CSS viewport 1440 × 1000; screenshot raster 1430 × 993. Phone CSS viewport 390 × 844; raster 380 × 822. Same in-app screenshot scaling in V5 and V6. Compared same-size content regions; differing scroll offsets and changed content height were not treated as design drift. Browser DOM checks confirmed no horizontal overflow at both widths. The desktop map was fitted again after the phone viewport check before the final top capture.

States: Wises returning rider, default current-rider inspector, pinned effort, reference changes, two-effort history comparison; all supplied scenarios and viewer/loading options checked in the harness.

## Findings and corrections

- P2 fractional-time hierarchy: V5 applied a small-label rule to the fraction in its hero time. V6 uses an explicit fractional span. Historical whole seconds omit `.0`; meaningful tenths remain. Leaderboard and inspector retain consistent tenths. Current hero fraction is 35.2px beside the 44px time, on the same baseline.
- P2 table alignment in the first V6 render: inherited flex wrapping centered rider names within the rider column. Corrected column alignment and grouped the time and shared-zero gap visualization. Header, names, times, and gaps now have stable tracks.
- P2 phone inspector framing in the first V6 render: inherited padding inset the entire new header inside a second frame. Explicit zero outer padding restores a continuous table-to-inspector surface; corrected phone capture retained.
- Interaction correction: an already-used comparison reference stays keyboard focusable with `aria-disabled`, and its handler is inert. This avoids the inspector snapping back to another pinned rider when changing the reference disables the currently focused control.

No remaining actionable P0/P1/P2 findings in reviewed states.

## Required fidelity surfaces

- Typography: existing Geist and Geist Mono retained. Tabular numbers, inline fractional alignment, readable history values, quiet units, and grouped comparison numbers checked on desktop and phone.
- Spacing: shared table/inspector border, aligned outer edges, stable 384px desktop inspector, compact identity band, measured result area, secondary data, and grounded action footer. History remains a broad plot joined to one reading strip. Leading-time labels now sit beside their times. Phone table and inspector stack without horizontal overflow.
- Colors: existing dark navbar preserved. White, soft gray-green planes, green selection, and existing muted blue negative comparisons retained. No new brand palette. Small labels and focus states reviewed visually; this is not a full WCAG conformance audit.
- Assets: original rank images retained, modestly enlarged in table rows and present in the selected-effort identity area. No replacement artwork or invented rider portraits. Exact numerical fallback for unsupported ranks.
- Copy/content: no new product nouns, instructional paragraphs, fabricated dates, fabricated measurements, or artificial leaderboard rows. Comparison labels describe actual reference state. Existing source and workshop provenance stays in the harness.

Full upper-page V5/V6 captures and phone history captures were reviewed together. An independent read-only reviewer compared the desktop data captures together and found the connected composition materially stronger, with no P1/P2 visual defect. Focused live review covered decimals, rider-column alignment, rank placement, and inspector states; those regions are legible in the retained captures.

## Functional checks

- 94 workshop tests, typecheck, and workshop build passed. Existing large-bundle advisory remains a workshop limitation.
- Focused red before the change: history rendered `3:55.0` instead of `3:55`; V6 return origin was unrecognized. Both now pass.
- Shared-zero geometry outcome probe passed for first/last reference, positive and negative differences, and equal-time rows.
- June 26 4:23 plus August 28 3:55 gives −28.0s. Clear restores normal inspection.
- Pin Jamie, move keyboard focus to Alex, then use Alex as reference: Alex remains in the inspector, with −2.6/−1.3/0.0/+6.5s table gaps. Missing dates, sensor data, and Analyze links remain absent for unrecorded summaries. Desktop geometry stays fixed.
- All six scenarios render the V6 component: Wises, Black Rock, Sprague, first visit, Vault, public geography. No horizontal overflow in the checked harness state.
- Visitor and signed-out omit private history and Vault position. Returning rider retains both where supplied.
- Loading hides the new data inspector. Empty, error, and ready states remain usable and distinct.
- Analyze opens the bound Wises effort in Ride V13 analysis; Back to climb returns to V6 and the same scenario/viewer. Unit check covers imported context and preserving visitor access.
- V5 button still renders V5 and its original fractional history times. Its component, data model, and stylesheet are unchanged.
- Strava reference retains Overview, History, and Leaderboard views.
- Both standalone preview and workshop browser logs were empty for warning/error checks.
- React review: stable effort keys, functional selection updates, pure comparison derivation, existing memoized recordings, observer cleanup, semantic controls, and no new fetches/dependencies.

## Remaining boundaries

This is a local design candidate using retained terrain and supplied illustrative rider context. It does not establish live protocol positions, complete real-rider leaderboards, production performance, or deployment. The existing workshop carries all preserved generations in a large development bundle.
