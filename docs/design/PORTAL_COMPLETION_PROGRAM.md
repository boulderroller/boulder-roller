# Portal Completion Program

**Status:** CLIENT-COMPLETE (2026-07-07) — Waves 0–3 landed on main; the
remaining exit gate is the PRODUCTION stranger walk (`klrj.7`): real invite
code, real email delivery, staging pipeline, real GPX, production Strava
OAuth. The Playwright walk (`klrj.1`) proved the client flow and fixed the
email-code auth bridge; it does not prove ops.
**Date:** 2026-07-07

## Scale principle (Tim, 2026-07-07)

**The cohort scopes the order, not the ceiling.** Pages are built as the
permanent product: real pagination/cursor paths and virtualization on any
list that grows (feed already uses `VirtualizedFeedList` — keep that bar),
no hardcoded cohort sizes anywhere, empty states designed for zero AND for
thousands, ClimbView identity fields behind an adapter so canon cutover
swaps the source without a rebuild. "Cohort-sized" in this document always
means content priority, never capacity or code shortcuts.

## Post-Wave follow-ups (cut 2026-07-07)

- `klrj.7` — production stranger walk (the real exit gate; includes
  parked-page legibility sweep post-flip and `support@` email test)
- `qdyj.17` — counted-reveal moment on upload (the gold cascade; the
  loop's emotional payoff, ships before first invites)
- `qdyj.18` — `top_result` field in the rides-list API so My Rides rows
  carry results, not just CAL
- Formatter units rule: format-per-type is invariant; km/mi follows the
  rider's units setting (recorded in `qdyj.12`'s close notes)
- Notifications dropdown gets contract styling when the cohort's first
  record notifications fire (watch item, no bead yet)
**Method:** public root is the proof of design; surfaces extrude from it
through the tree. RideView (Gate A soul pass) is the approved type specimen.
Every remaining page composes from extracted specimen parts and locks in
against `docs/design/PORTAL_DATA_INTERACTION_CONTRACT.md` criteria 1–7.
**Definition of done:** all waves complete, the stranger walk passes, and
the contract measurements run green on every locked page.

## Wave 0 — Foundations landing (current portal lane)

| Step | Bead | Content | Gate |
|------|------|---------|------|
| 0.1 | `4kfh` | Land RideView soul-pass branch to main | landing gates |
| 0.2 | `4kfh` | Merge prepared global token-flip PR | after 0.1 |
| 0.3 | `4kfh.1` | Linked highlighting (map+profile+rows, <100ms) — completes the specimen | harness hover assertion |
| 0.4 | `qdyj.12` | Shared formatter module + 3 contract measurements in capture harness | grep-lint + one playwright tag |

Wave 0 closes `4kfh` and `pq4s`.

## Wave 1 — Frame and door (two parallel lanes, disjoint files)

| Step | Bead | Content | Notes |
|------|------|---------|-------|
| 1.1 | `7pds` | Phase B shell: top-nav-only complete, sidebar code paths deleted, header carries search/upload/notifications/account | Balance stays in account/Portfolio surfaces, not persistent header chrome |
| 1.2 | `klrj.6` | Entry soul pass R1–R5 per `history/ENTRY_SOUL_INSTRUCTIONS_2026-07-07.md` | fresh lane; starts after 0.2; owns components/auth + brand/RouteField extraction |

## Wave 2 — Cohort-path pages (Phase C: compose from the specimen)

Lock-in order = the rider's weekly route. Every page: contract criteria
measured, full-page screenshot, fact-appears-once check, formatter module
only, Evidence Rule. Grammar source = specimen record
(contract §2) — propagate, don't reinterpret.

| # | Page | Bead | Specimen application | Page-specific notes |
|---|------|------|---------------------|---------------------|
| 2.1 | Home feed (post-login landing) | `qdyj.13` | rows of consequence: each ride row = facts + Counted CAL + result jewelry; density gradient | cohort-sized: 10 riders seeing each other's rides is the community loop; kudos/comments follow established Strava conventions and are not a ratification question |
| 2.2 | Upload + Strava connect (incl. StravaCallback states) | `qdyj.14` | one typographic event; material panel for processing state | truthful states: parsing → matching → Counted; no spinner-only dead ends |
| 2.3 | My Rides list | `qdyj.15` | consequence rows ≤56px; positional invariance; format invariants | empty states per contract (`--`, `Waiting`, `Not counted`) |
| 2.4 | ClimbView | `qdyj.16` | becomes the SECOND specimen: canonical object-page grammar (identity hero, record board as jewelry, economy strip attached not headlined) | climb-first per AGENTS.md; display only — vault creation UX stays held for `4crx.11` |
| 2.5 | Portfolio / receipts | `qdyj.4` (existing) | economy surfaces: receipts as jewelry-grade rows; DUNG gold spent on records/receipts only | zero-start copy — receipts are permanent records, never money; no on-chain permanence claims (devnet posture) |

Tim review cadence: batched — 2.1+2.2 as one screenshot review, 2.3+2.4 as
one, 2.5 alone (economy copy needs his read).

## Wave 3 — The walk (exit gate)

| Step | Bead | Content |
|------|------|---------|
| 3.1 | `klrj.1` | Stranger walk: fresh account, real invite → first Counted ride → Collect (if position exists). Sign-in friction is a known suspect (Tim). Fix what the walk exposes; every screen passes language gates. |

Wave 3 closes the portal program and satisfies First Cohort's onboarding
acceptance.

## Parked (explicitly out of v1)

Settings, Achievements, Leaderboard, FindFriends, Map page, Docs page —
legibility-only fixes if the token flip broke them. Vault creation flow —
rebuilt once as canon activation after `4crx.11`. Mobile app — separate
parked lane (trusted-sensor).

## Standing rules

- Two live portal lanes max (main portal lane + entry lane until klrj.6
  lands; then one).
- Specimen changes (new object categories, new grammar) get extracted into
  the interaction contract §2 in the same PR that establishes them.
- No new decoration: the soul pass's restraint is the baseline; gold =
  consequence only; one typographic event per page.
