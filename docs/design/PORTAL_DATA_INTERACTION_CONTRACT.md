# Portal Data-Interaction Contract

**Status:** ACTIVE — living document, extracted not legislated
**Date:** 2026-07-07
**Sits under:** `docs/design/PORTAL_DESIGN_SYSTEM_2026.md` (visual contract),
LANGUAGE_SPEC, PROTOCOL_TRUTHS
**Method note (Tim, 2026-07-07):** the public root is the proof of design;
every surface extrudes from it through the tree (root → entry → RideView →
portal). **RideView is the type specimen**: each object category gets its
first canonical treatment there, and that treatment — once Tim-approved —
is the standard this document records. Rules below exist because a shipped
surface established them. New rules enter the same way: solidify on the
specimen page, get approved, get extracted here with their numbers.

## 0. Inheritance principle

Inherit Strava's interaction grammar by default — two decades of riders'
muscle memory is a design asset we get for free. Deviate only where the
economy gives a reason (Counted CAL, records, receipts have no Strava
equivalent), and the deviation must pay for the relearning it costs.
We are not un-Strava-ing the layout; it is Strava's grammar wearing our
material and carrying our economy.

## 1. Quantified criteria

Applied at page lock-in (Phase C and later), measured on fixture rides via
the e2e capture harness. Not retrofit to parked pages.

| # | Criterion | Number | How measured |
|---|-----------|--------|--------------|
| 1 | Time-to-first-fact | Core facts (who/when/how far/long/climbing/hard/earned) inside first viewport; big three in top ~20% | capture screenshot, viewport annotation |
| 2 | Positional invariance | Same fact, same position, every instance of the page. Zero layout variance across fixture objects | Playwright bounding-box assertions |
| 3 | Recognition typography | Value:label size ratio ≥ 2.5:1; tabular numerals on all data | tokens + spot assertion |
| 4 | Linked highlighting | Coordinated views (map + profile + rows) respond to one hover/selection model; highlight latency < 100ms; no modes | Playwright hover assertion |
| 5 | Rows of consequence | Every object row carries its consequence (place / PR / CAL / receipt), not just metrics; row height ≤ 56px | fixture render check |
| 6 | Monotonic density | Data-points-per-100px only increases with scroll depth (≈2 hero → ≈5 material → ≈12 tables) | annotated capture at lock-in |
| 7 | Format invariants | One format per data type product-wide (times h:mm:ss, right-aligned numerics, shared units) — all formatting through the shared formatter module | grep + module import lint |

## 2. Extracted standards (the specimen record)

> **Palette status (2026-09-07):** The colour directions retained in this section are superseded by the [Portal Standards Amendment](PORTAL_STANDARDS_AMENDMENT_2026-09-07.md#1-palette-night-ledger); use its Night Ledger roles for current colour authority.

Established on RideView, Gate A soul pass (2026-07-07), Tim-approved:

- **Hero stat:** 30px Geist Mono ink value / 11px muted label, three per
  page maximum, top of page.
- **Metadata line:** secondary metrics as one 13px mono line, never a
  second grid.
- **Jewelry chip:** the economy renders as small bordered chips —
  cal-blue for Counted CAL, dung-gold for record results. Label 12px +
  mono value. Gold is spent on consequence only.
- **Material panel:** map/elevation are first-class material; route stroke
  terrain-green with gold climb spans and ink finish node; controls hidden
  until hover/focus; elevation strips have no masthead of their own.
- **Climax module:** the page's payoff moment gets the largest data type
  on the page (44px mono) and the gold accent; one truth per module (no
  error state beside a real result).
- **Motion:** staggered fade-up on load (~60ms steps, ≤480ms), hard
  mechanical treatment reserved for interaction states,
  `prefers-reduced-motion` respected.
- **One rendering per fact** per page (composition spec rule, standing).

New object categories (climb page, portfolio/receipts, feed rows) define
their canonical instance on their richest page, then extract here.

Established on ClimbView, Phase C 2.4 (2026-07-07):

- **Object-page hero:** the climb name is the page's only typographic event;
  identity facts sit in one mono line and three hero facts max. Do not duplicate
  the climb title in a window bar, card title, or tab label.
- **Climb material:** route/elevation owns a large 4:3 field before secondary
  tables. Map/profile material is not a thumbnail and does not need its own
  masthead.
- **Record board jewelry:** the all-time Record Board is visible on the
  primary page, with #1 on the DUNG/gold family and rows capped at 56px.
  Do not hide the board behind page chrome on the canonical climb detail.
- **Attached economy strip:** vault, deposited CAL, legend, and week state are
  compact chips attached to the climb. They are consequences of the place, not
  a finance panel. At the `4crx.11` cutover, an exact reviewed revision with no
  Vault may add one `Create Vault` action here when backend state is
  `available`; the action remains attached to the climb and never becomes the
  page headline.
- **Proof footer:** contract, climb id, and source identifiers are quiet footer
  facts unless the rider explicitly opens BoulderScan or an admin/debug surface.

## 2.5 Increment rule (Tim, 2026-07-07)

Design surfaces move in **single-element increments**: one module, one
screenshot, Tim's eyes, then the next. No whole-page redos, no multi-page
waves, nothing propagates on inference. The Wave-2 batch experiment
produced a hodgepodge and is retired for design work. Big bites are for
plumbing, never for surfaces.

## 3. Enforcement scope (honest cost)

- Shared formatter module: one-time build, then lint-level enforcement.
- Three Playwright measurements added to the existing gate-a capture
  harness (`Gate A capture › gate a contract measurements` writes
  `test-results/gate-a/rideview-contract-measurements.json`); run at lock-in,
  not in CI-per-commit, not in production.
- Criteria bind pages as Phase C touches them. RideView is the only
  retrofit and is substantially done; linked highlighting (criterion 4)
  is its remaining build item.
