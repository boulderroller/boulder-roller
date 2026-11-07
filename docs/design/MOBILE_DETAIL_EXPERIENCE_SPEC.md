# Mobile Detail Experience Spec

**Status:** Canonical product-shaping pass  
**Date:** 2026-04-23  
**Audience:** Mobile, product, design  
**Scope:** Rider-facing detail, live recording, profile, and social-readiness grammar

## 1. Purpose

This spec sharpens the layer below the top-level surfaces. It turns the current
detail grammar into product-specific experience models for:

- `RideDetail`
- `ClimbDetail`
- `Record`
- `Profile`
- future social/public rider surfaces

It extends:

- [MOBILE_SURFACE_SYSTEM_SPEC.md](./MOBILE_SURFACE_SYSTEM_SPEC.md)
- [MOBILE_CONTENT_PRIMITIVES_SPEC.md](./MOBILE_CONTENT_PRIMITIVES_SPEC.md)
- [MOBILE_DETAIL_GRAMMAR_SPEC.md](./MOBILE_DETAIL_GRAMMAR_SPEC.md)
- [LANGUAGE_SPEC.md](./LANGUAGE_SPEC.md)

## 2. Product Spine

The mobile app should read as one continuous rider journey:

1. `Record` creates the raw ride truth.
2. `RideDetail` explains what that ride became.
3. `ClimbDetail` shows where that ride matters.
4. `Profile` summarizes the rider's identity and account state.
5. `BoulderScan` holds the deepest proof detail.

The rider app is not a protocol dashboard. Chain, attestation, and projection
truth should be visible only through fitness-native language and clear off-ramps.

## 3. RideDetail: Ride Receipt With Consequences

Purpose:
- make one ride understandable, memorable, and inspectable
- show what changed because the rider completed it

Canonical module order:

1. `Ride hero`
   - ride name/date
   - distance, duration, elevation, effort metric
   - one consequence line
2. `What changed`
   - matched climbs
   - rank, KOM, CAL, vault, or pending consequences
3. `Ride status`
   - rider-readable processing timeline
   - examples: `Recorded`, `Uploaded`, `Matched`, `Verified`, `Settled`
4. `CAL earned`
   - only when available or pending for this ride
5. `Verified ride`
   - proof confidence and BoulderScan off-ramp

Language rules:
- use `Verified ride`, not `attestation`
- use `Ride hash` only as secondary tiny copy if needed
- avoid `commitment`, `PDA`, instruction names, and raw tx labels as primary UI
- put proof details behind `View on BoulderScan`

## 4. ClimbDetail: Climb Monument And Challenge

Purpose:
- make one climb feel like a shared place with history
- keep `Climb` as the base object

Canonical module order:

1. `Climb hero`
   - name, region
   - distance, vert, grade
   - current state: leaderboard active, vault live, or undiscovered
2. `Leaderboard`
   - permanent all-time glory
   - top 3 preview
   - `See Top 10` deep slice
3. `Legend`
   - recent stewardship
   - active rider and attempts when available
4. `Vault`
   - optional economic layer attached to climb
   - deposit/withdraw actions live in future vault detail, not hero chrome
5. `Your line`
   - personal relationship to this climb
   - best time, attempts, gap, or invitation to ride it

Language rules:
- `Leaderboard` is rider-facing; `Record Board` stays internal/protocol-facing
- `Legend` is recent stewardship, not all-time rank
- `Vault` is optional and never replaces climb identity

## 5. Record: Live Cockpit

Purpose:
- make recording feel spatial, active, and trustworthy
- create the raw truth that later becomes ride detail

Record is a top-level tab, but it is not a normal list surface. It is a live
cockpit.

Canonical state model:

1. `Ready`
   - map/world layer background where available
   - compact GPS/location readiness
   - optional sensor readiness
   - one dominant start control
2. `Recording`
   - live timer
   - distance, speed, elevation
   - GPS integrity/sample signal
   - pause and stop controls
3. `Paused`
   - same shape as recording
   - clear paused tone
   - resume remains dominant
4. `Saving`
   - preserve ride context while finalizing
   - do not collapse into a contextless spinner

Map guidance:
- a map or route surface is the right background for the live cockpit
- until real map dependencies are ready, use a map-ready placeholder layer
- controls float above the world layer instead of being presented as a dashboard

## 6. Profile: Rider Identity And Account Surface

Current scope:
- private rider/account surface
- auth and wallet state
- ride totals
- CAL/account state when available
- device/sensor/sync settings

Future scope:
- public rider identity surface
- best climbs
- legends held
- leaderboard placements
- public rides when visibility exists
- BoulderScan off-ramps for proof-heavy moments

Rules:
- keep current Profile grouped and private
- do not invent a public profile before visibility/backend semantics exist
- avoid making account settings feel like social proof

## 7. Social Readiness Boundaries

Social shape should wait for backend truth:

- no fake global feed
- no synthetic follows, kudos, comments, or public activity rows
- no stale social projection bolted onto `Home`

Safe readiness now:

- ride rows can later gain visibility controls
- climb consequences can become shareable moments
- rider profile can later become a public detail object
- Home remains a truthful `You` feed until a real feed contract exists

## 8. Acceptance Criteria

The implementation is aligned when:

1. `RideDetail` feels like a ride receipt, not a debug/status page.
2. `ClimbDetail` feels like a climb monument, not a vault or protocol page.
3. `Record` feels like a live cockpit with spatial context.
4. `Profile` stays rider/account centered without fake social semantics.
5. Proof depth exits to BoulderScan instead of taking over mobile chrome.
