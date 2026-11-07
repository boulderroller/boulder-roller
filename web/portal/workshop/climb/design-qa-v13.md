# Climb V13 — settled workshop candidate

User decision, 14 September 2026: retain V12 metrics, fold them back into the accepted left cluster, then lock the design. V13 is the settled climb candidate for subsequent implementation. Preserve this generation; further exploratory changes require a new candidate.

V11 primary/secondary cluster restored. V12 calculation helper, all six labels, useful tenths and metric definitions remain unchanged. On phones, the three secondary label/value pairs stack within their columns to prevent crowding. No changes to accepted colors, map/profile, rider card, leaderboard, Vault or history behavior. The workshop marks V13 “Settled”.

Local proof: 112 workshop tests, typecheck and build pass (existing all-generations bundle-size advisory remains). New return-context test first failed by falling back to V2, then passed after registering V13. Six browser scenario headers match V12 values. Personal-best → analysis → Back to climb returns to V13. Exact 1440×1000 and 390×844 CSS viewports checked; no phone overflow. Clipped exports at those dimensions are in references/v13. No browser errors observed.

This locks the workshop design, not production integration, qualification enforcement or economic policy. Those handoff boundaries and the profile-derived gain versus canonical net-rise distinction from design-qa-v12.md remain in force. Earlier candidates and source data are preserved.
