# Rider Experience Proof and Economy Grammar

**Status:** Active product grammar
**Date:** 2026-06-03
**Updated:** 2026-08-13
**Beads:** `boulderroller-v2-gyyg`, `boulderroller-v2-fk2d`, `boulderroller-v2-4kv6`, `boulderroller-v2-klrj.15`, `boulderroller-v2-m1wsl`

This file defines the literal Boulder Roller rider experience before it defines
internal proof/economy primitives. Agents should start from what a rider sees and
does, not from protocol taxonomy, slogans, or abstract product language.

`docs/design/LANGUAGE_SPEC.md` governs rider vocabulary and visibility. This
file governs how those words compose into compact and detailed product states.

This is not a tagline file. Do not make copy more literary than the actual
surface. Use the literal object, action, and state the rider is dealing with.

## Operating Rule

Every rider-visible string and agent-facing product doc should pass this order:

```text
user action -> user object -> visible state -> optional system/protocol detail
```

If copy starts from the system layer, rewrite it from the rider layer first.

Examples:

- Use `Record or upload a ride. Review the route, the climbs on it, and where
  you stand.`
- Do not use `Proof/economy primitives coordinate settlement outcomes.`
- Use `Deposit CAL` and `My position`.
- Do not use `Stake into a yield primitive` on rider surfaces.

Quick review questions:

- What did the rider just do?
- What object is the rider looking at: ride, climb, result, economic position,
  collection detail, or optional proof?
- What state is visible: matched, counted, pending, not counted, ready,
  deposited, withdrawn, or collected?
- Is any protocol term necessary on this surface, or should it move to
  BoulderScan/admin/debug detail?

## Rider Experience Flow

Use this order as the default mental model for portal, mobile, and BoulderScan
copy:

1. The rider records or uploads a ride.
2. Boulder Roller reads the route, effort, and climb profile.
3. The rider reviews the ride, matched climbs, and sporting results.
4. When CAL eligibility is the visible question, the app states it directly:
   `CAL counted`, `CAL pending`, or `CAL not counted`.
5. The rider browses climbs, times, results, leaderboards, and history.
6. If a climb has a vault, the rider can deposit CAL.
7. The rider reviews `My position`, deposited CAL, pending DUNG, and withdrawal
   state.
8. The rider reviews weekly DUNG, DUNG history, and collection state in
   Portfolio.
9. The rider can open collection details or BoulderScan when they want the
   underlying receipt/proof evidence.

The rider does not experience a `CountedCal` primitive, a settlement abstraction,
or a protocol proof system. The rider experiences rides, climbs on the route,
results, times, places, history, CAL when relevant, weekly DUNG, and collection
details. Receipts and raw proof stay optional and explicit.

## Literal Terms

Prefer these terms in user-visible surfaces:

- `Record a ride`
- `Upload a ride`
- `Matched climbs`
- `Browse climbs`
- `Result`
- `Best time`
- `Top 10 · 7th`
- `Rank #N`
- `Your history`
- `Start`
- `Finish`
- `CAL counted`
- `CAL pending`
- `CAL not counted`
- `Deposit CAL`
- `My position`
- `CAL deposited`
- `Withdraw CAL`
- `Weekly DUNG`
- `DUNG history`
- `Collection details`
- `Collect DUNG`
- `Open in BoulderScan`

Avoid these terms in user-visible surfaces unless the surface is explicitly
technical or administrative:

- `Proof/economy primitive`
- `Protocol primitive`
- `Token yield`
- `Reward opportunity`
- `Stake to farm`
- `Passive income`
- `Vault alpha`
- Generic `points`
- Generic `rewards` when the real object is CAL, DUNG, or a collection

## Rider-First Rules

- Athletic object first: ride, climb, result, time, power, place, route.
- Consequence second: CAL, DUNG, vault, economic position, collection,
  settlement.
- Say what is known: `matched`, `counted`, `confirmed`, `pending`,
  `needs review`, `Reviewing this result`, `not counted`.
- Use compact primitives in high-density surfaces and detailed primitives in
  object detail panels.
- BoulderScan owns raw protocol detail. Portal and mobile can link to it, but
  should not make hashes, PDAs, parser versions, or account names the headline.
- Prefer `deposit`, `position`, `collection details`, `collect`, and `withdraw`.
  Use `receipt` only when the rider explicitly opens proof detail or BoulderScan.
- Avoid rider-visible `yield`, `token`, `stake` as the primary noun, and
  generic `reward` when the real object is CAL, DUNG, or a collection.

## Internal Primitive Matrix

The matrix below is for implementation consistency. Do not expose these
primitive names directly to riders.

| Primitive | Compact Form | Detailed Form | Use |
|---|---|---|---|
| `RecordStatus` | `Rank #3`, `Leaderboard pending`, `No time yet` | Leaderboard row, best time, source state, last qualifying Result | Climb cards, ride summaries, climb detail |
| `CountedCal` | `47 CAL counted`, `CAL pending`, `CAL not counted` | CAL amount, reason, source Ride, matched-Climb context, pending/final state | Feed, ride detail, post-ride, portfolio |
| `VaultPosition` | `1.2K CAL deposited`, `No position`, `Withdraw CAL` | deposited CAL, since date, pending DUNG, collect/withdraw actions | Climb economy strip, Climb Vault section, portfolio |
| `LegendStatus` | `Legend: Tim`, `Waiting`, `Vacant` | holder, completions, term/week state, linked rider | Climb detail, Climb Vault section, leaderboard |
| `BoulderScanLink` | `View details`, `Open in BoulderScan` | target type, status, receipt/proof evidence, external link, short id | Technical-detail panels, collection rows, admin/debug off-ramp |
| `SettlementSummary` | `Week cleared`, `DUNG ready`, `Waiting` | week, receipts, DUNG amount, carry/cleared state | Portfolio, Climb Vault section, BoulderScan |

## Surface Guidance

### Portal

Portal should start with the rider's object and action, then show CAL, DUNG, or
collection state.

- Feed cards: `CountedCal`, `RecordStatus`, optional `BoulderScanLink`.
- `/climbs`: `RecordStatus` and compact `VaultPosition` only after climb
  identity is visible.
- `/climbs/:climbId`: detailed `VaultPosition`, `SettlementSummary`, and
  `LegendStatus` inside the attached Vault section when a Vault exists.
- `/portfolio`: detailed balances, positions, DUNG history, collection state,
  and optional receipt/proof detail. Do not headline it as a generic wallet
  page.

### Mobile

Mobile should keep the same rider-flow terms but use fewer fields.

- Post-ride: `matched`, `counted`, `pending`, `not counted`.
- Home/feed: `CAL counted`, `DUNG ready`, `Rank #N`, no generic points.
- Climb detail: `RecordStatus` first, `VaultPosition` second.
- Profile: show best times, counted outcomes, and DUNG history only when tied to
  real ride/climb objects. Receipt/proof detail remains opt-in.

### BoulderScan

BoulderScan is allowed to be technical after it states the user-facing object.

- Start with ride, climb, vault, leaderboard, receipt, or account.
- Then show signatures, hashes, account ids, parser versions, and raw events.
- Prefer `Receipt`, `Proof`, and `Account` over marketing language.

## Copy Examples

Use:

- `Record or upload a ride`
- `Matched climbs`
- `47 CAL counted`
- `1.2K CAL deposited`
- `My position`
- `DUNG ready`
- `Weekly settlement cleared`
- `Collection details`
- `Open in BoulderScan`

Avoid:

- `Proof economy primitives`
- `47 points`
- `Token yield`
- `Earn passive income`
- `Stake to farm`
- `Vault alpha opportunity`

## Implementation Targets

Near-term portal surfaces:

- `web/portal/src/pages/Portfolio.tsx`
- `web/portal/src/pages/VaultView.tsx`
- `web/portal/src/pages/ClimbView.tsx`
- `web/portal/src/pages/Climbs.tsx`
- `web/portal/src/components/vault/CanonVaultCreationModal.tsx`

Near-term mobile surfaces:

- `mobile/src/lib/feedDisplay.ts`
- mobile post-ride climb match and CAL reveal surfaces
- mobile climb detail/economy surfaces

Future component work should extract shared primitives only after two or more
surfaces need the same rendering behavior. Until then, this file is the copy and
composition contract.
