# Mobile Rider Identity and Social Shape Spec

**Status:** Proposed canonical identity/social grammar  
**Date:** 2026-04-24  
**Audience:** Mobile, backend, product, design  
**Scope:** Rider identity, profile, author labels, social primitives, and mobile-facing copy boundaries

## 1. Purpose

Boulder Roller needs social shape, but it cannot become a generic wallet explorer or a generic activity feed.

This spec defines how mobile should present:
- rider identity
- wallets
- RiderSoul / Beetle Score
- BeetleCard
- follows and future social actions
- feed authorship

It is grounded in:
- [MOBILE_SURFACE_SYSTEM_SPEC.md](./MOBILE_SURFACE_SYSTEM_SPEC.md)
- [MOBILE_CONTENT_PRIMITIVES_SPEC.md](./MOBILE_CONTENT_PRIMITIVES_SPEC.md)
- [MOBILE_DETAIL_GRAMMAR_SPEC.md](./MOBILE_DETAIL_GRAMMAR_SPEC.md)
- [MOBILE_RIDER_SOCIAL_SPINE_IMPLEMENTATION_SPEC.md](./MOBILE_RIDER_SOCIAL_SPINE_IMPLEMENTATION_SPEC.md)
- [PROTOCOL_TRUTHS.md](../PROTOCOL_TRUTHS.md)

## 2. Product Truth

Boulder Roller is a cycling app with cryptographic depth, not a protocol dashboard.

The rider should feel:
- "this is my ride"
- "this climb matters"
- "this rider earned this"
- "I can inspect proof if I choose"

The rider should not feel:
- "I am browsing PDAs"
- "every screen is an attestation log"
- "the app is using my wallet address as my name"

## 3. Identity Layers

Rider identity has five distinct layers.

### 3.1 Rider Profile

Owner:
- backend

Includes:
- username
- display name
- avatar
- bio
- privacy settings
- follow/block relationships
- feed visibility

Mobile usage:
- primary visible identity on rider-facing surfaces
- author labels in feed rows
- Profile header
- future public rider detail screens

### 3.2 Wallet

Owner:
- chain/account system, surfaced through backend auth and wallet adapter

Includes:
- wallet address
- signing capability
- economic account ownership

Mobile usage:
- account/settings surfaces
- wallet-specific actions
- BoulderScan or proof off-ramp
- fallback only when no rider profile label exists

Wallet address is not the rider's social name.

### 3.3 RiderSoul / Beetle Score

Owner:
- protocol / indexed projections

Meaning:
- soulbound effort identity
- non-transferable proof of riding depth
- distinct from CAL and economic capital

Mobile usage:
- profile progression
- rider detail context
- future comparison surfaces

Do not present RiderSoul as money, XP, or a wallet balance.

### 3.4 BeetleCard

Owner:
- backend projection plus protocol/indexed state depending on the card field

Meaning:
- visible rider progression and collectible expression
- a social artifact of verified effort

Mobile usage:
- Profile
- future public rider profile
- future social/feed moments when a card changes meaningfully

BeetleCard is not the base social graph object. It is a visible expression of riderhood.

### 3.5 Feed / Social Graph

Owner:
- backend

Includes:
- follows
- blocks
- privacy
- moderation
- feed ranking
- comments/kudos if/when they exist

Mobile usage:
- consume backend projections
- do not infer social state from chain alone
- do not bolt on likes/comments until backend contracts own them

## 4. Label Fallback Grammar

When mobile needs a rider label, use this priority:

1. `displayName`
2. `@username`
3. `Rider abcd...wxyz` from wallet, only if a wallet exists
4. `Rider`

Rules:
- never hardcode `You` as an author label
- use `Your` only for perspective labels like `Your best` or `Your rides`
- never uppercase usernames or display names
- do not show raw wallet addresses on Home or list surfaces
- short wallet labels are acceptable in Profile account context

## 5. Surface Rules

### 5.1 Home

Home is a ride feed.

Rules:
- ride cards show rider identity as author
- the rider's own feed still uses their profile label, not `You`
- list copy should talk about ride state and consequences, not proof mechanics
- social footer actions wait for backend-owned contracts

### 5.2 Profile

Profile is the rider identity surface.

Rules:
- display name or username is primary
- wallet is secondary account context, not the main identity
- BeetleCard and RiderSoul can live here once the product model is ready
- settings/actions stay grouped by the mobile surface system

### 5.3 Ride Detail

Ride Detail is a rider-facing inspection of one ride.

Rules:
- summary, climbs, status, earnings, and BoulderScan off-ramp are the right modules
- proof-specific language stays behind the off-ramp
- raw hashes and commitments do not belong in the default mobile detail layer

### 5.4 Climb Detail

Climb Detail is about the shared climb asset.

Rules:
- climb is the base object
- leaderboard and legend can show rider labels
- vault is optional and attached to climb
- protocol mechanics stay below rider meaning

### 5.5 Post-Ride

Post-Ride is an outcome/reveal surface.

Rules:
- say what happened to the ride
- show ride metrics and earned outcomes
- show that deeper inspection exists through BoulderScan when available
- do not turn the screen into a proof dashboard

## 6. Social Shape

The first social layer should be conservative in backend shape and strong in product meaning.

Initial primitives:
- rider profile
- follow
- public/private profile visibility
- feed item authorship
- visible ride/climb outcomes

Later primitives:
- kudos/reactions
- comments
- profile mentions
- BeetleCard moments
- rider comparison slices

Rules:
- backend owns whether a viewer can see a rider, ride, comment, or follow state
- mobile should not synthesize privacy or graph state from wallet data
- on-chain state can prove effort/economics, but it is not the moderation layer

## 7. Copy Boundary

Rider-facing mobile surfaces may use:
- ride
- climb
- leaderboard
- legend
- CAL
- earned
- verified
- checking
- BoulderScan

Rider-facing mobile surfaces should avoid as default copy:
- protocol
- canonical
- attestation
- PDA
- hash
- commitment
- chain record
- proof dashboard

Those terms can exist in:
- internal code
- tests
- developer docs
- BoulderScan
- explicit proof/debug routes

## 8. Acceptance Criteria

The identity/social grammar is aligned when:

1. Home author labels come from rider identity, not hardcoded perspective.
2. Profile presents display name / username first and wallet second.
3. Post-ride and detail surfaces avoid raw proof mechanics by default.
4. BeetleCard and RiderSoul are treated as rider progression, not generic account widgets.
5. Future social work can cite backend ownership boundaries before adding mobile UI.
