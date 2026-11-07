# Mobile Ride Detail Implementation Spec

**Status:** Proposed canonical implementation spec  
**Date:** 2026-04-23  
**Audience:** Mobile, backend, product, design  
**Scope:** Exact product and implementation shape for mobile `RideDetail`

## 1. Purpose

This spec turns `RideDetail` from a truthful but transitional archival screen
into the canonical second-depth surface for rides.

It is grounded in:
- [PROTOCOL_TRUTHS.md](../PROTOCOL_TRUTHS.md)
- [HOME_FEED_SURFACE_SPEC.md](./HOME_FEED_SURFACE_SPEC.md)
- [MOBILE_HOME_FEED_IMPLEMENTATION_SPEC.md](./MOBILE_HOME_FEED_IMPLEMENTATION_SPEC.md)
- [MOBILE_DETAIL_GRAMMAR_SPEC.md](./MOBILE_DETAIL_GRAMMAR_SPEC.md)
- current implementation in [RideDetailScreen.tsx](../../mobile/src/screens/RideDetailScreen.tsx)

This spec defines:
- what the rider should understand after tapping a ride
- what modules belong on the screen
- how local truth, attested truth, and projected truth appear without jargon overload

## 2. Product Position

`RideDetail` is not:
- a raw database dump
- a proof dashboard
- a protocol explorer

`RideDetail` is:
- the rider's full view of one ride
- the place where ride facts and BR consequences meet
- the bridge from feed/archive into climbs, earnings, and deeper proof

## 3. Route Sources

Canonical entry points:
- `Home`
- `PostRide`
- future archive surface under `Profile`

Navigation rule:
- use the parent surface name when it is stable
- otherwise fall back to `‹ Back`

Examples:
- from `Home` -> `‹ Home`
- from post-ride flow -> `‹ Ride`
- fallback -> `‹ Back`

## 4. Mobile Depth Grammar

`RideDetail` is a **Level 2 detail screen**.

It should let the rider answer:
- what was this ride?
- what did Boulder Roller detect from it?
- what is still processing?
- what did I earn or affect?

It should deep-link into **Level 3** screens:
- `ClimbDetail`
- `ClimbLeaderboard`
- future BoulderScan / proof off-ramp

## 5. Layout

Top to bottom:
1. Detail header
2. Ride hero
3. Ride summary module
4. Climb matches module
5. Ride status module
6. Earnings module
7. Proof / BoulderScan module

Target:
- 5-6 modules max

## 6. Detail Header

Follows [MOBILE_DETAIL_GRAMMAR_SPEC.md](./MOBILE_DETAIL_GRAMMAR_SPEC.md):
- back row first
- left-aligned title block
- optional supporting line below title

Recommended title block:
- title: time-of-day ride title or route/title when available
- supporting line: full ride date/time

Do not:
- center the title like a tab header
- use a giant page hero before the rider knows what ride they opened

## 7. Module 1: Ride Hero

Purpose:
- anchor the ride immediately

Contents:
- ride title
- date/time
- optional rider identity if the ride is not yours

Rules:
- this should feel like one ride, not a generic metrics page
- if route naming is unavailable, use time-of-day naming consistently

## 8. Module 2: Ride Summary

Purpose:
- communicate the physical ride first

Contents:
- distance
- duration
- elevation gain
- average speed
- optional max speed

Implementation guidance:
- use `StatCluster`
- avoid oversized dashboard styling

## 9. Module 3: Climb Matches

Purpose:
- show which climbs this ride touched

Contents:
- matched climbs list when available
- each item should be tappable
- optional compact consequence line per climb

Examples:
- `Manayunk Wall`
- `#6 on Leaderboard`
- `Vault live`

Fallback:
- `No climbs matched on this ride`

This module is the main path from rides into the climb commons.

## 10. Module 4: Ride Status

Purpose:
- explain where the ride is in the BR pipeline

Use rider-facing language:
- `On device`
- `Upload pending`
- `Processing`
- `Ready`
- `Needs review`

Rules:
- do not headline `attestation` as the main noun on mobile
- status should feel like ride progress, not protocol internals

Implementation guidance:
- existing `RideReviewBanner` and `RideProcessingStages` are the current truth-bearing basis
- these should later be composed into a cleaner canonical module

## 11. Module 5: Earnings

Purpose:
- show the rider what the ride produced economically

Contents when available:
- `CAL Earned`
- optional settlement or finalized line
- optional note when results are still pending

Rules:
- earnings should not dominate the page above the ride itself
- if nothing is earned yet, either hide the module or show a compact pending state

## 12. Module 6: Proof / Off-Ramp

Purpose:
- expose deeper truth without burdening the whole screen

Mobile-facing copy should prefer:
- `Verification`
- `View on BoulderScan`
- `Ride hash` only when useful

Rules:
- this module is an off-ramp
- it should not read like the primary narrative of the screen
- raw commitment or protocol identifiers should be secondary

## 13. Truth Boundary on the Screen

`RideDetail` should represent three truth layers honestly:

1. `Local truth`
- local SQLite ride facts
- always available offline

2. `Attested truth`
- server processing / verification state
- ride hash / commitment / finalization as applicable

3. `Projected truth`
- earned CAL
- climb consequence summaries
- later social or community projections

Rules:
- do not claim projected data is on-chain if it is not
- do not hide local truth while waiting on server truth
- do not block the rider from seeing their own ride because the network is unavailable

## 14. States

### 14.1 Local-only / Offline

Show:
- ride hero
- ride summary
- compact note that server enrichment is unavailable

Do not:
- replace the whole screen with an error

### 14.2 Processing

Show:
- ride hero
- summary
- status module
- earnings module only if partially available

### 14.3 Complete

Show:
- full detail stack
- climb matches
- earnings
- verification off-ramp

## 15. Acceptance Criteria

The ride detail surface is aligned when:

1. Tapping a ride from `Home` or archive opens a clearly modeled detail screen, not a utilitarian dump.
2. Ride meaning comes before proof mechanics.
3. Climb consequences are visible and tappable from the ride.
4. Offline and processing states remain honest without breaking the screen.
5. The screen reads as the sibling of `ClimbDetail`, not as a one-off utility page.
