# Climb V5 — local workshop verification

final result: passed

V5 preserves the V4 terrain composition and adds linked personal history and a comparative leaderboard. The user's subsequent navbar correction restores V3's dark `#20251c` treatment in V5 only. V1–V4 source components and styles are unchanged. This is local workshop evidence, not production integration or independent rider proof.

## Visual evidence

- Source: `evidence/climb-v4-1440.jpg`; retained Strava upper capture plus `references/strava-climb-history.png` and `references/strava-climb-leaderboard.png`. The latter frames are the September 9 free-account capture, including subscription overlays. V5 exposes all three sections through the reference selector.
- Implementation: `evidence/climb-v5-1440.jpg`, `climb-v5-data-1440.jpg`, `climb-v5-comparison-1440.jpg`, `climb-v5-390.jpg`, `climb-v5-history-390.jpg`, `climb-v5-board-390.jpg`.
- Browser CSS viewports verified through the rendered DOM: 1440×1000 and 390×844. In-app screenshots are uniformly scaled to 1430×993 and 380×822 respectively. The V4 and V5 desktop source/implementation captures share the same raster scale and were opened together for comparison. No artificial crop or image alteration was used. Lower data and phone captures were inspected separately at readable scale.
- Typography: accepted Geist retained; tabular figures and selective Geist Mono gap/axis readings. Fractional time and gap use consistent tenths. The responsive SVG uses its measured width, preserving axis type and point targets on phone.
- Layout: upper map, plate, identity, and records retain their positions. History spans the page with aligned plot/list and a reserved reading strip. The lower table and inspector share the existing column rhythm. Phone stacks them without horizontal overflow; all five history rows are visible.
- Colors/assets: accepted rank imagery and map ground retained. Neutral chart grid, restrained PR reference and selection band, green positive gaps, muted blue negative gaps. No invented badges, economics, or sensor values.
- Content: calendar-only effort dates retain their stated day. Board snapshot date is labeled “As of.” Actual supplied ranks remain 1, 2, 3, 7; no percentile or complete-field claim. Missing recordings receive no Analyze action.

## Corrections and verification

1. First desktop render exposed centered rider buttons; left alignment now matches the Rider header. Updated data capture confirms the correction.
2. Fixed-width history coordinates would shrink mobile labels; responsive plotting dimensions now retain readable type. Updated 390 history capture confirms it.
3. Inspector content changes could shift the page under the pointer. Reserved desktop slots keep its geometry stable; phone omits empty slots. Hover remains through the table-to-inspector transition, and focus leaving a row for an inspector action no longer clears the preview. Browser probe: pin Jamie, focus Alex, click Use as reference → Gap to Alex.
4. Duplicate date/time points initially collided at plot bounds. Imported three identical summaries now render at distinct x=44,68,92. Imported recording navigation returns to the exact imported V5 study; no canonical Explore mapping is inferred.
5. June 26 → August 28 comparison shows −28.0s. Clicking blank chart space and Escape clear history selection. Jamie as reference yields Morgan −1.3s, Jamie 0.0s, Alex +1.3s, Example Rider +7.8s. Recorded Analyze opens scoped Ride V13 and Back to climb returns to V5. Speed uses the same time-weighted channel calculation as analysis (16.6km/h in this fixture), with 272W supported power.
6. All six bundled scenarios rendered in V5. Visitor/signed-out omit personal history and Vault. Loading hides chart points/table rows; empty omits results; error shows recovery. V4 remains separately selectable with its original sidebar history. Browser warning/error logs were empty.

Focused V5 return test failed before adding generation support, then passed. Final workshop suite: 92 tests; typecheck and build pass. The build retains the existing large-workshop-bundle advisory. Verification ran on the V5 server at4319; the identical worktree then replaced V4 at4318 and returned HTTP200. The desktop browser connection became unavailable during the final automatic tab handoff, so the final link is the reliable entry point.

No remaining actionable P0/P1/P2 findings. True time-gap-over-distance comparison still requires another independent recording and is outside this candidate.
