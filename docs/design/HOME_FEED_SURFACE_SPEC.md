# Home / Feed Surface Spec

**Status:** Proposed canonical surface spec  
**Date:** 2026-04-23  
**Audience:** Mobile, portal, backend, design, product  
**Scope:** Canonical product shape for Boulder Roller's `Home / Feed` surface across client platforms

## 1. Purpose

This spec defines what `Home` means in Boulder Roller.

It exists to prevent drift between:
- mobile `Home`
- portal `/` or feed surfaces
- backend feed payloads
- rider-facing language and expectations

This is a surface spec, not a platform-specific implementation plan.

It defines:
- what the rider is actually browsing
- what the primary feed object is
- what belongs in `Home`
- what must stay out of `Home`
- how the same product shape should translate across mobile and portal

Platform-specific implementation details live in companion specs.

Grounding:
- [PROTOCOL_TRUTHS.md](../PROTOCOL_TRUTHS.md)
- [LANGUAGE_SPEC.md](./LANGUAGE_SPEC.md)
- [MOBILE_CLIMBS_IMPLEMENTATION_SPEC.md](./MOBILE_CLIMBS_IMPLEMENTATION_SPEC.md)

## 2. Product Position

`Home` is not:
- a protocol event stream
- a vault dashboard
- a settlement log
- a raw archive of your rides

`Home` is:
- the rider's living social surface
- a feed of rides
- a place where ride consequences become legible without turning into middleware

The primary feed object is the **ride card**.

Protocol consequences, climb consequences, and social consequences must ride
inside the ride artifact, not replace it.

## 3. Canonical Home Thesis

The Boulder Roller rider should browse:
- rides by people
- their own recent rides
- meaningful signals attached to those rides

They should not browse a taxonomy of:
- settlement events
- board delta cards
- legend transition cards
- vault accounting tiles

Those are real facts, but they belong as:
- annotations on ride cards
- detail modules after tap
- notifications when urgent
- BoulderScan when the rider wants proof depth

This is the key distinction between:
- a cycling app with cryptographic depth
and
- a protocol dashboard with rides attached

## 4. Home Depth Grammar

`Home` follows the same depth grammar as `Climbs`.

### 4.1 Level 1 - Index

The rider scans a feed of rides quickly.

Answers:
- what happened?
- who rode?
- which ride matters enough to open?

### 4.2 Level 2 - Detail

The rider opens one ride and sees:
- the ride itself
- climb matches
- leaderboard consequences
- earnings and proof progression where relevant

### 4.3 Level 3 - Deep Slice

The rider drills into one aspect:
- climb detail
- leaderboard
- vault position
- BoulderScan / proof surface

`Home` should not try to collapse all three levels into one screen.

## 5. Information Hierarchy

The feed hierarchy is:

1. ride
2. ride impact
3. social context
4. protocol depth off-ramp

That means:
- the ride card is the object
- impact is a compact annotation
- protocol truth remains accessible, but off the main path

## 6. Screen Structure

Top to bottom:

1. Utility header
2. Optional lightweight prompt or suggestion rail
3. Ride feed

No heavyweight dashboard rail belongs above the feed.

## 7. Utility Header

The header should be light and utilitarian.

Recommended contents:
- search
- notifications
- inbox or messages when they exist
- profile / wallet affordance if needed by the platform

Hard rules:
- do not place a giant `Record Ride` CTA here if recording is already a primary tab
- do not place token balances as the hero of the home screen
- do not use the header as a mini dashboard

## 8. The Feed Object

The canonical feed object is a **ride card**.

Each ride card may represent:
- your own ride
- a followed rider's ride
- a community ride in global mode

Every card should answer:
- who rode?
- what ride was it?
- what happened on that ride?

## 9. Ride Card Anatomy

### 9.1 Required Fields

Every ride card should have:
- rider identity
- started-at time or relative timestamp
- distance
- duration
- elevation gain
- optional route / location summary

### 9.2 Impact Strip

Each ride card may include a compact impact strip.

This is where BR's additional dimensionality lives.

Valid impact examples:
- `+47 CAL`
- `#6 on Manayunk Wall`
- `Legend ride`
- `2 climbs matched`
- `Vault live on one of your climbs`

Hard rules:
- maximum one or two impact lines
- impact is subordinate to the ride itself
- impact should invite curiosity, not dump accounting

### 9.3 Optional Enhancements

Platform-specific enrichments may include:
- hero image / map preview
- kudos / social reactions
- comments preview
- equipment summary

These are optional and must not displace the ride core.

## 10. What Does Not Belong As Its Own Feed Card

Do not make standalone primary feed cards for:
- leaderboard movement without a ride anchor
- legend handoff without a ride anchor
- carry bucket settlement
- POL / treasury movement
- raw attestation status transitions

These facts should appear:
- inside a ride card
- in notifications
- on climb detail
- in BoulderScan

## 11. Sparse Non-Ride Inserts

Home may include occasional non-ride inserts, but they must stay sparse.

Allowed examples:
- challenge suggestions
- group suggestions
- rider suggestions
- featured climb or community moment

Rules:
- ride cards remain the overwhelming majority of the feed
- inserts should feel socially native
- protocol mechanics should not appear as promotional inserts

## 12. Truth Layering Inside Home

Home should reflect Boulder Roller's three kinds of truth cleanly:

- `On-chain`: final economic and privileged state
- `Attested`: backend-verified real-world ride evidence
- `Projected`: client-friendly read model and social presentation

Inside `Home`, this layering is implicit by default.

Rider-facing surfaces should show:
- resolved outcomes
- pending states only when they affect understanding

They should not lead with:
- `truthSource`
- attestation PDAs
- event names
- transaction signatures

Those belong in:
- ride detail
- climb detail
- BoulderScan

## 13. Relationship To Archive

Ride archive and home feed are not the same thing.

Definitions:
- `Home`: living feed of current rides and social movement
- `Archive`: durable library of your rides

Archive belongs under:
- `Profile`, or
- a dedicated `Your Rides` surface

Home may temporarily use archive data during transition, but the canonical
end state keeps these concepts separate.

## 14. Portal Translation

This spec should translate directly to portal.

The translation rules are:

### Same across platforms

- primary object remains the ride card
- impact remains embedded inside ride cards
- protocol truth remains a secondary layer
- feed is not decomposed into event taxonomy cards

### Portal may add

- denser side rails
- richer hover states
- modal previews
- comments / kudos with more room
- wider map/media treatment

### Portal may not change

- the primary object model
- the meaning of the feed
- the rule that rides anchor meaning

Portal can be denser. It should not become a different product.

## 15. Canonical Feed Modes

The feed may support different source modes:
- `Following`
- `You`
- `Global`
- later `Nearby` if socially coherent

These are source filters, not different feed species.

The card grammar remains the same across all modes.

## 16. Ranking and Relevance

Home should not create separate significance card types.

Instead:
- significance changes which rides rise in the feed
- significance changes which impact lines appear on a ride

This preserves one coherent feed language.

Examples:
- a follower's random recovery spin may still appear, but low
- a ride that changed a leaderboard, matched climbs, or earned CAL gets a
  stronger impact strip and may rank higher

## 17. Language Rules

Use rider-facing language:
- `Ride`
- `Leaderboard`
- `Legend`
- `Deposit CAL`
- `Climb`

Avoid surface copy like:
- attestation
- settlement event
- record board event
- vault signature
- truth source

BR users should feel the product is deep, not jargon-heavy.

## 18. Non-Goals

This spec does not define:
- exact social graph algorithms
- exact recommendation ranking
- final visual design system choices
- notification center behavior
- BoulderScan explorer layout

Those can evolve as long as they obey this surface shape.

## 19. Canonical Acceptance Criteria

The `Home / Feed` surface is aligned when:

1. A rider browsing home perceives it as a ride feed, not a protocol log.
2. Important climb and economic consequences are legible from the ride card.
3. Opening a ride reveals deeper detail without overloading the feed itself.
4. Mobile and portal use the same object model even if they differ in density.
5. Archive behavior is not confused with social home behavior.

