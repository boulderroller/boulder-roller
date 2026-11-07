# Climb Candidate V10

Local workshop for `boulderroller-v2-3vyru`, additive from V9. No production qualification, payout or protocol changes. Earlier components, styles and fixtures are unchanged.

## The candidate

- Overall opens first. Qualified is the working second-board name; each board uses its own time-ranked places and RankMarks. Missing recordings and power remain absent. The qualifying fixture and enforcement handoff from V9 are unchanged.
- Vault follows the leaderboard, before personal history. The upper Vault summary and Your position use one `ClimbV10Plate` component, with the same neutral header, white body and numeric hierarchy. Collect uses the accepted flat Ride V12 action color. Rider identity inherits the accepted avatar/name scale and spacing.
- All V10 color literals come from `candidate-v12.css` or `feed/feed-v6.css`, inherited by accepted Ride/Feed generations. No new hues. The main navigation color remains unchanged.
- Hover uses a thin cursor without recoloring bars or painting a column. Selection uses one quiet band; hover can inspect another week and restores the pin on exit. Click back into the plot or Escape clears. Keyboard selection works.
- Financial readings trim padded zeros while retaining up to nine meaningful decimals. Large exact amounts wrap inside their plate.

## Local evidence

- Two focused tests reproduced padded-zero formatting and a V10 return incorrectly falling back to V2 before correction; both now pass. All 105 workshop tests, typecheck and build pass. The existing large-bundle advisory remains.
- Six bundled scenarios × rider, visitor and signed-out modes checked in desktop and phone previews. No horizontal overflow; public modes show no private position. Loading, empty, error and recovery verified.
- Desktop and phone visual inspections used CSS viewports 1440×1000 and 390×844. Captures are under `references/v10/`; the browser screenshot exporter crops/resizes the returned images to 1430×993 and 380×822, respectively.
- Overall has ten rows; Qualified has eight independently ranked rows with a RankMark each. Switching back to V9 retains its original Overall/Vault labels and design.
- Hover inspection, pinned restoration, click-to-clear, Enter selection and Escape tested. Default chart has no highlighted band, and all bar fills stay identical during hover.
- Date → full ride Overview; time → scoped ride Analysis; Back to climb → V10. Exact collect review remains 7.776 DUNG and explicitly submits no transaction. Strava reference renders one panel.
- Imported long-name, single zero-allocation week, nine-decimal positive carry, large balance and large lifetime-tribute data renders without clipping. The test caught and corrected clipping in the upper summary. Imports remain window-local.
- Final browser console: no warnings or errors. Independent source review found no truth, routing or viewer regression; its orphan CSS-rule finding was fixed. This is not a complete accessibility certification or real transaction evidence.

## Still deferred

The implementation handoff in `design-qa-v9.md` remains: authoritative qualification, per-rider qualifying bests, protocol settlement, historical entitlement and production indexing must be handled separately after these candidates. Qualified is a workshop label, not a ratified protocol term.
