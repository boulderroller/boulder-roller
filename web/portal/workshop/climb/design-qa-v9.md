# Climb Candidate V9

Local workshop, Bead `boulderroller-v2-067at`. Builds additively from V8; prior candidate components, styles and fixtures are preserved. This is design evidence, not production qualification, payment, or chain evidence.

## Observable changes

- One dense leaderboard with Overall / Vault views. The qualifying view chooses independently supplied fastest qualifying attempts per rider, sorts by ascent time and preserves ties. Overall rank marks stay on Overall; Vault places use plain ordinals. Morgan demonstrates a fastest overall attempt and a separate slower qualifying attempt. Missing recordings remain unlinked and without fabricated wattage.
- Twelve explicitly authored weekly allocations form a discrete, time-positioned plot. Hover inspects freely; click selects, click back into the plot or Escape clears. Arrow keys inspect weeks. The readout distinguishes an inspected week from the pinned week and restores the pin on pointer exit.
- Historical allocation detail updates in one stable region. Current personal balance and deposited principal remain independent. Carried-forward amounts are separate from allocated totals. Candidate totals add in nanounits to avoid floating-point tails.
- Vault summary and current-position plates share neutral surfaces. Green belongs to selection and the Collect action. Retained action dialogs remain review-only, with no transaction submission.

## Verification

- Focused new test failed before the V9 module existed; four focused tests pass for independent attempts/ties, import bindings and overlap rejection, decimal totals, and date/effort return routes.
- 103 workshop tests pass, typecheck passes, workshop build passes. Existing build chunk-size advisory remains.
- Browser verification at CSS viewports 1440×1000 and 390×844. Saved captures are in `references/v9/`. No horizontal overflow in all six scenarios across rider, visitor and signed-out modes. No private position in either public viewer mode.
- Loading, empty, error and recovery states checked. Strava-reference toggle reports pressed and renders one panel. V9 is registered alongside all retained generations.
- Current date link opens full ride Overview; current time opens scoped ride Analysis; Back to climb returns to V9 and retains the selected board in the running workshop.
- Collect review shows exact 7.776 DUNG. Deposit rejects 99 CAL, accepts Max 486 and reviews resulting 1,686 CAL. Withdrawal requires a quote and does not invent net proceeds.
- Imported long-name/single-zero-week/positive-carry/large-position fixture renders without overflow; qualification metadata round-trips. Imports remain window-local, as before. Zero-week axis labels and mobile carry layout corrected during QA.
- Final browser console had no warnings/errors in the captured run. This is not a complete accessibility certification or real transaction test.

## Deferred implementation handoff

User accepted the design direction and explicitly deferred production work until climb candidates are complete. A future implementation agent must reconcile versioned effort qualification across completion evidence, paid leaderboard insertion, Local Legend counting, plans, receipts, indexing and settlement. Keep each rider's Overall best separate from their qualifying best; distinguish measured zero from missing power; settle provider/manual-file admission policy and the legacy-seat cutover; preserve prior claims. CAL depositor/founder rights require separate treatment from paid sporting eligibility. Bind historical allocations and personal claims to authoritative records, never today's rank or a ratio inferred from this fixture. This candidate changes none of those enforcement paths.
