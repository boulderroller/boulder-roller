# Mobile Climbs Implementation Spec

**Status:** Proposed canonical implementation spec  
**Date:** 2026-04-23  
**Audience:** Mobile, backend, product, design  
**Scope:** Exact product and implementation shape for the mobile `Climbs` tab and its immediate deep links

## 1. Purpose

This spec turns the current passive `Climbs` tab into a coherent climb-first
product surface.

It is grounded in:
- [PROTOCOL_TRUTHS.md](../PROTOCOL_TRUTHS.md)
- [LANGUAGE_SPEC.md](./LANGUAGE_SPEC.md)
- [MOBILE_DETAIL_GRAMMAR_SPEC.md](./MOBILE_DETAIL_GRAMMAR_SPEC.md)
- current mobile routing in [RootNavigator.tsx](../../mobile/src/navigation/RootNavigator.tsx)
- current climb APIs in [climbs.py](../../backend/app/routes/climbs.py)

This spec is intentionally product-facing and implementation-facing at the
same time. It defines:
- what the rider sees
- what depth each page should support
- what routes, components, and APIs must exist to support that shape

## 2. Product Position

The `Climbs` tab is **not**:
- a staking dashboard
- a vault list
- a protocol explorer

The `Climbs` tab **is**:
- the rider's explorer for shared geographic assets
- the place to discover real hills that matter in Boulder Roller
- the place where record, stewardship, and optional economics meet

Climb is primary. Vault is attached.

## 3. App-Wide Depth Grammar

This is the canonical mobile depth grammar. `Climbs` is the first full
implementation of it, but the same structure should later apply to `Home`,
`Profile`, and other major tabs.

### 3.1 Three Levels

**Level 1 — Index**
- lets the rider scan many objects quickly
- answers: "what exists?" and "what matters now?"
- one primary action: enter detail

**Level 2 — Detail**
- lets the rider understand one object clearly
- answers: "what is this?" and "what can I do here?"
- 4-6 modules max

**Level 3 — Deep Slice**
- lets the rider inspect one aspect deeply
- examples: full leaderboard, vault actions, proof/explorer off-ramp
- one idea per screen

### 3.2 Density Rules

Every major surface should feel similarly elegant and similarly deep.

Rules:
- list cards may show identity, core stats, one state line, and one relationship line
- detail screens may show one hero block plus 4-6 modules
- deep-slice screens should cover exactly one aspect
- protocol detail is always an off-ramp, never the main body
- BoulderScan remains the deepest proof surface, not the mobile app

### 3.3 Language Rules

Use rider-facing copy from [LANGUAGE_SPEC.md](./LANGUAGE_SPEC.md):
- `Climb`, not `Segment`
- `Leaderboard`, not `Record Board` on rider surfaces
- `Legend`, not `LocalLegendStatus`
- `Deposit CAL`, not `Stake` in CTA copy
- `Created by`, not `Founder`

Do not surface:
- PDA
- vault signature
- truth source
- event names
- other protocol internals

## 4. Route Map

This spec adds three screens to the current mobile routing:

### Existing
- `Tabs`
- `PostRide`
- `RideDetail`
- `Pairing`
- `Wallet`

### Add
- `ClimbDetail`
- `ClimbLeaderboard`
- `ClimbVault` or reuse a future vault-detail route when it exists

## 5. Screen 1: Climbs Index

**Route:** tab root `Climbs`  
**Current file:** [ClimbsScreen.tsx](../../mobile/src/screens/ClimbsScreen.tsx)

### 5.1 Goal

The rider should be able to answer:
- what climbs exist here?
- why does each one matter?
- which one should I open?

### 5.2 Layout

Top to bottom:
1. Header: `Climbs`
2. Compact filter control
3. Scroll list of tappable climb rows

### 5.3 Header Copy

Header:
- `Climbs`

Do not use a large explainer bubble once the tab is legible through
header, filter control, and detail routing.

### 5.4 Filters

Canonical filter model:
- `Popular`
- `Vault Live`
- `Mine`
- `Nearby`

Shipping guidance:
- ship `Popular`, `Vault Live`, and `Mine` first
- add `Nearby` only when we have reliable current-location + bbox filtering
- if `Nearby` is unavailable, do not show a dead chip

Definitions:
- `Popular`: sorted by completions / activity
- `Vault Live`: `hasVault == true`
- `Mine`: climbs with rider relationship once that data exists
- `Nearby`: climbs intersecting a device-location bbox

Surface rule:
- on mobile, use a compact segmented control directly beneath the header
- do not use large floating chips or a sticky filter rail for this tab

### 5.5 Row Shape

Each row is fully tappable.

Row contents:
- name
- region if available
- three core stats: `Vert`, `Distance`, `Grade`
- one state line
- one rider-relationship line when available

Examples of valid state lines:
- `Vault live • 1,240 CAL deposited`
- `Leaderboard active • 87 attempts`
- `No vault yet • Ride to activate`

Examples of valid rider lines:
- `Your best: 6:14`
- `You're #8`
- `Legend: alexrider`

Hard rules:
- no second stat row
- no raw protocol language
- no more than one relationship line
- no CTAs inside the row other than tapping the row itself

### 5.6 Empty / Error States

**Signed out**
- title: `Climbs`
- copy: `Sign in to explore climbs, compete on leaderboards, and back vaults where they're live.`

**No climbs**
- title: `No climbs found`
- copy: `Record rides with climbs to discover new community assets.`

**Filter empty**
- `No vault-live climbs here yet.`
- `You haven't ridden any climbs yet.`

**Network error**
- keep the screen shape
- show banner
- do not collapse the whole view into an error shell

### 5.7 Primary Action

Tap row -> `ClimbDetail(climbId)`

## 6. Screen 2: Climb Detail

**Route:** `ClimbDetail`  
**Status:** new

### 6.1 Goal

The rider should be able to answer:
- what is this climb?
- what rights and competition live here?
- what can I do next?

### 6.2 Layout

Top to bottom:
1. Header with back
2. Identity hero
3. Primary actions row
4. Record Board preview module
5. Legend module
6. Vault module when live
7. Your relationship module
8. Optional BoulderScan off-ramp

### 6.3 Hero

Hero contents:
- climb name
- region
- core physical stats: distance, vert, grade
- optional status pill: `Vault Live`
- optional secondary line: `Created by ...`

Do not place more than one secondary line under the hero.

### 6.4 Primary Actions

Maximum two actions:
- `View Leaderboard`
- `Deposit CAL` when `hasVault == true`

If `hasVault == false`, only show `View Leaderboard`.

### 6.5 Record Board Preview Module

Purpose:
- communicate permanent glory first

Contents:
- section title: `Leaderboard`
- KOM holder and KOM time
- top 3 preview rows
- CTA: `See Top 10`

If there are no entries:
- show `No leaderboard entries yet`
- do not hide the section entirely

### 6.6 Legend Module

Purpose:
- communicate rolling stewardship

Contents:
- section title: `Legend`
- current legend wallet / rider label if known
- attempts in active window
- short explanation:
  `Most active recent rider helps steward this climb.`

If no current legend is available:
- show `No active legend yet`

### 6.7 Vault Module

Show only when `hasVault == true`.

Contents:
- section title: `Vault`
- total CAL deposited
- total attempts / completions
- one sentence:
  `This climb has a live vault. Riders and supporters can deposit CAL to participate in its economy.`
- CTA: `Deposit CAL`

Do not show carry math or distribution internals here.

### 6.8 Your Relationship Module

Purpose:
- make the climb feel personal, not abstract

Target fields:
- `Your best`
- `Your attempts`
- `Your rank` if on the board
- `Vault position` later when relevant

Shipping guidance:
- this module may ship with a placeholder state before rider-specific APIs exist
- if data is unavailable, show `Ride this climb to establish your line here.`

### 6.9 Proof Off-Ramp

Optional footer CTA:
- `View on BoulderScan`

This is an off-ramp only. No protocol body text belongs in the main screen.

## 7. Screen 3: Climb Leaderboard

**Route:** `ClimbLeaderboard`  
**Status:** new

### 7.1 Goal

Give the rider the full all-time top 10 without bloating `ClimbDetail`.

### 7.2 Layout

Top to bottom:
- header with back
- climb name
- KOM summary
- full top 10 list
- rider highlight row if current user is on the board

### 7.3 Row Shape

Each row shows:
- rank
- rider label / truncated wallet
- best time
- optional achieved date

No extra chrome. This is a quiet, prestige-first table.

## 8. Screen 4: Climb Vault

**Route:** `ClimbVault` or shared future vault-detail route  
**Status:** future but intentionally reserved now

This screen is the economic deep slice for a climb. It should not be embedded
into the main climb detail screen beyond the summary module in §6.7.

Contents:
- current deposited CAL
- rider position
- deposit / withdraw actions
- reward summary

Not in scope for the first `ClimbDetail` ship, but the route should be planned
now so the detail page does not have to be restructured later.

## 9. Data Contract

## 9.1 Current Data Available

The current mobile `ClimbSummary` contract in
[api.ts](../../mobile/src/lib/api.ts) already includes:
- `id`
- `name`
- `region`
- `lengthM`
- `elevGainM`
- `avgGradientPct`
- `hasVault`
- `vaultId`
- `vaultSignature`
- `totalStaked`
- `totalCompletions`
- optional `recordBoard`
- optional `localLegend`

### 9.2 Current Backend Reality

Current backend supports:
- `GET /climbs/list`
- `GET /climbs/{id}`
- `GET /climbs/{id}/leaderboard`

Current gap:
- `GET /climbs/{id}` does not currently hydrate `recordBoard`
- `GET /climbs/{id}` does not currently hydrate `localLegend`
- rider-specific climb relationship fields do not exist yet
- mobile API client does not yet expose `getClimbLeaderboard()`

### 9.3 Required API Additions

**Mobile client**
- add `api.getClimbLeaderboard(id: string): Promise<RecordBoard>`

**Backend**
- extend `GET /climbs/{id}` to populate:
  - `recordBoard`
  - `localLegend`
- OR add a dedicated detail endpoint if that shape is cleaner

**Later rider-personalization fields**
- `myBestTimeSeconds`
- `myAttemptCount`
- `myRank`
- `hasRidden`

These should be additive and optional.

## 10. Component Plan

Recommended component split:
- `ClimbCard`
- `ClimbFilterChips`
- `ClimbHero`
- `RecordBoardPreview`
- `LegendSummaryCard`
- `VaultSummaryCard`
- `ClimbRelationshipCard`
- `LeaderboardTable`

Rules:
- the index screen should compose cards, not inline giant render functions
- detail modules should each render one idea
- shared formatting helpers should live in a climb-specific UI module, not be copied screen to screen

## 11. Navigation Plan

### 11.1 Root Stack Changes

Add to [RootNavigator.tsx](../../mobile/src/navigation/RootNavigator.tsx):
- `ClimbDetail`
- `ClimbLeaderboard`
- `ClimbVault` or reserved placeholder

### 11.2 Tab Screen Changes

In [ClimbsScreen.tsx](../../mobile/src/screens/ClimbsScreen.tsx):
- wrap each card in `TouchableOpacity` or `Pressable`
- navigate with `{ climbId: item.id }`

## 12. Implementation Order

### Phase 1 — Make the tab coherent
- make climb cards pressable
- add explainer band
- add filter row
- add `ClimbDetail` route and screen shell

### Phase 2 — Make detail truthful
- add `getClimbLeaderboard()` client method
- wire `ClimbDetail` to `getClimb()` + leaderboard fetch
- add Record Board preview
- add Vault summary

### Phase 3 — Add stewardship and personalization
- hydrate `localLegend`
- add relationship module
- add `Mine` filter behavior

### Phase 4 — Add economic deep slice
- add `ClimbVault`
- connect deposit flow

## 13. Acceptance Criteria

The `Climbs` implementation is correct when:
- the index page explains itself in one sentence
- every climb card is tappable
- tapping a card opens a climb detail screen
- non-vault climbs still feel meaningful
- the detail screen leads with record and identity, not token mechanics
- the leaderboard can be opened as a dedicated deep slice
- vault detail is a separate deep slice, not stuffed into the main detail screen
- the mobile surface never exposes protocol jargon
- the screen density feels comparable to `Home` and `RideDetail`

## 14. Non-Goals

Not in scope for this implementation:
- full map-based climb browsing
- BoulderScan-quality proof detail inside mobile
- exposing vault signature / PDA / event payloads
- collapsing climb detail and vault detail into one giant screen

## 15. Why This Shape Is Canonical

This shape matches the protocol ontology:
- Climb is the primary object
- Record Board is permanent truth
- Legend is rolling truth
- Vault is optional attached economy

It also matches the product promise:
- a cycling app first
- cryptographic depth second
- shared geographic assets as the core experience
