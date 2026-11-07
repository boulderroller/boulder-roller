# Climb Candidate V8

Local workshop review, 13 September 2026. Bead: boulderroller-v2-1szzk.

## Result

V8 replaces the Vault distribution bar, legend and separate history controls with one expandable settlement history. Each week opens its exact allocation amounts and settlement date. The personal position gives collectible DUNG visual priority, with deposited CAL and its controls below. The upper summary retains lifetime tribute and total deposited principal without repeating the selected week's figures.

The leaderboard has distinct destinations: date opens the whole ride, time opens the scoped effort, and rider name opens the rider profile. Average power comes from the bound recording and climb. Missing recordings and sensor values remain absent; historical fixture dates without a bound ride are plain text. Date moves beneath the rider name on phones, retaining its destination.

V1–V7 components and styles, and Ride/Feed candidate components, are unchanged. V8 is selectable independently in the existing harness. The data remains the existing V7 workshop example, including illustrative economics. These are local interaction and rendering results, not production, chain or real-rider evidence. No transaction is submitted.

## Functional evidence

- Focused routing test first failed against the former date-to-analysis behavior; V8 date routing then passed. Full workshop suite: 99 passed, zero failed. Typecheck and workshop build pass. The build retains the existing large all-candidates bundle warning.
- Actual date navigation opened In the bag, 128.7 km, as an overview. Actual time navigation opened the 1.16 km Wises Mill analysis at 3:55. Both returned to Climb V8.
- Bound examples displayed 272 W for Wises Mill, 373 W for Black Rock and 331 W for Sprague. Synthetic history and unbound climbs returned no wattage.
- All six built-in scenarios exercised under V8, plus returning rider, visitor and signed-out states. Private position values are not rendered for visitor or signed-out viewers. No Vault is invented for scenarios without Vault data.
- One settlement week opens at a time; clicking it again collapses it. Keyboard Enter opens a week. Escape closes the action dialog and returns focus to Collect DUNG.
- Deposit minimum and available amount checked: 99 CAL cannot advance, Max selects 486, review shows 1,686 CAL deposited afterward. Withdraw remains an explicit full-position review with a required quote. Collect shows the exact available amount and wallet destination; all actions stop at local review.
- Imported edge case checked: 1,200,000.123 ready DUNG, a 0.00001 allocation, category-specific carry of 2.5 DUNG, a week ID containing spaces, and an existing position without a funding account. Values remain visible on phone without horizontal overflow; Withdraw and Collect remain available while Deposit is absent.
- Loading, empty and recoverable error states checked; Try again restored the climb. Preserved V7 button selection and the Strava reference panel verified with pressed state and panel count.
- Final localhost:4318 delivery showed V8 selected, three settlement weeks, the recorded 272 W value and no browser warning/error logs. The separate 4319 review server was stopped. The other Map workshop on 4320 was preserved.

## Visual evidence

Saved in `history/climb-v8-workshop-2026-09-13/`:

- `v7-vault-1440.jpg`: preserved V7 comparison.
- `v8-vault-1440.jpg`: V8 Vault, reviewed alongside V7 in the same comparison pass.
- `v8-desktop-1440.jpg`: complete V8 desktop composition.
- `v8-phone-390.jpg`: complete V8 phone composition.

CSS viewports were 1440 × 1000 and 390 × 844. Browser screenshot output can omit the scrollbar and normalize image dimensions; the phone DOM measured client width 380 and scroll width 380. No screenshot resizing or editing was used. The desktop Vault uses a quiet open-row wash and aligned figures, with the position kept as a distinct but related panel. Phone layout stacks the position beneath the weekly history and keeps the board readable without horizontal scrolling.

The visible source and target confirm the bar/legend is gone, week totals now form a consistent scan line, and the strongest figure is the rider's collectible amount. Remaining production work includes binding actual settlement records and wallet actions through their existing truth contracts; this candidate does not implement those services.
