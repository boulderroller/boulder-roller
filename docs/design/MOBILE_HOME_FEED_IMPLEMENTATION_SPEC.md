# Mobile Home Feed Implementation Spec

**Status:** Proposed canonical implementation spec  
**Date:** 2026-04-23  
**Audience:** Mobile, backend, product, design  
**Scope:** Exact product and implementation shape for the mobile `Home` tab as a real feed instead of a ride archive

## 1. Purpose

This spec turns the current mobile `Home` tab into an honest `Home / Feed`
surface while preserving a clean migration path from the current archive-first
implementation.

It is grounded in:
- [HOME_FEED_SURFACE_SPEC.md](./HOME_FEED_SURFACE_SPEC.md)
- [MOBILE_RIDE_DETAIL_IMPLEMENTATION_SPEC.md](./MOBILE_RIDE_DETAIL_IMPLEMENTATION_SPEC.md)
- [PROTOCOL_TRUTHS.md](../PROTOCOL_TRUTHS.md)
- [LANGUAGE_SPEC.md](./LANGUAGE_SPEC.md)
- current mobile routing in [RootNavigator.tsx](../../mobile/src/navigation/RootNavigator.tsx)
- current mobile `Home` screen in [HomeScreen.tsx](../../mobile/src/screens/HomeScreen.tsx)

This spec defines:
- what the mobile rider sees
- what the current `Home` implementation is missing
- what data and routes are required
- what can ship immediately versus what needs backend feed support

## 2. Current State

Today, `HomeScreen.tsx` is a merged ride archive:
- reads local SQLite rides
- merges server rides when authenticated
- renders ride rows
- opens `RideDetail`

That is useful and resilient, but it is not a true home surface.

Current strengths:
- works offline
- never hides the rider's own rides
- survives auth or network failure gracefully

Current gaps:
- no utility header
- no social feed behavior
- no ride-card impact language
- no distinction between `Home` and `Archive`
- no place for community or commons signals

## 3. Product Position

Mobile `Home` should be:
- a ride feed
- socially legible
- compact and elegant
- deeper only after tap

Mobile `Home` should not be:
- a protocol event board
- a balance dashboard
- a generic archive list wearing a home label

## 4. Mobile Depth Grammar

`Home` must follow the same depth grammar already established for `Climbs`.

### Level 1 - Home Feed

The rider scans rides quickly.

### Level 2 - Ride Detail

The rider opens one ride and sees:
- map
- stats
- climb matches
- leaderboard consequences
- earnings and settlement progression where relevant

### Level 3 - Deep Slice

The rider drills into:
- climb detail
- leaderboard
- vault detail
- BoulderScan if they want proof depth

`Home` itself should stay calm. It should not try to expose all of this at once.

## 5. Target Screen Structure

Top to bottom:

1. Utility header
2. Optional light suggestion rail
3. Ride feed

No giant dashboard hero.

## 6. Header

The header should be light.

Recommended mobile contents:
- screen title: `Home` or `Feed`
- search affordance when it exists
- notifications affordance
- inbox / messages affordance when it exists

Rules:
- no large `Record Ride` CTA if recording already exists as a primary tab
- no oversized CAL balance hero
- no wallet-first framing

## 7. Feed Source Chips

Canonical source modes:
- `Following`
- `You`
- `Global`

Optional later:
- `Nearby`

Definitions:
- `Following`: rides from followed riders
- `You`: your recent rides, rendered in feed card grammar
- `Global`: public community feed
- `Nearby`: local community activity if and when that is coherent and privacy-safe

Surface rule:
- if only one source mode is live, do not show a fake lone chip
- source controls appear only once riders have a meaningful choice

## 8. Ride Card Shape

Every mobile feed card should have:
- rider identity
- timestamp
- ride summary stats
- optional route / climb context
- compact impact strip

### 8.1 Required Visible Content

- rider name
- relative or absolute time
- distance
- duration
- elevation gain

### 8.2 Impact Strip

The impact strip is where BR's additional dimensionality appears.

Valid examples:
- `+47 CAL`
- `#6 on Manayunk Wall`
- `Legend ride`
- `2 climbs matched`

Rules:
- max one or two lines
- do not dump multiple protocol facts
- if nothing meaningful happened, no impact strip is required

### 8.3 Tapping

Tap card -> `RideDetail`

The feed should not use nested CTAs on the card body unless clearly necessary.

## 9. Social Inserts

Mobile may include sparse inserts between ride cards:
- challenge suggestion
- rider suggestion
- group suggestion

Rules:
- inserts remain rare
- ride cards remain the dominant feed grammar
- no protocol inserts

## 10. Relationship To Archive

Archive does not disappear, but it should stop defining `Home`.

Target end state:
- `Home` = living feed
- `Profile` or `Your Rides` = archive

Migration rule:
- until the dedicated archive surface is ready, `You` mode may continue to use
  the existing archive-backed ride source
- that is a transitional implementation detail, not the product definition

## 11. Route Map

Current relevant routes:
- `Tabs`
- `RideDetail`
- `PostRide`
- `ClimbDetail`
- `ClimbLeaderboard`

Home feed route behavior:
- feed card tap -> `RideDetail`
- ride detail deep links -> `ClimbDetail` and `ClimbLeaderboard`
- proof depth, if linked, should off-ramp to BoulderScan or a future proof view

## 12. Data Requirements

## 12.1 Immediate Reusable Data

The current app already has enough to ship a first honest version:
- local ride archive data
- merged server rides from `api.getRides()`
- ride status / progression data on detail surfaces

This is enough for:
- `You` mode
- archive-backed feed cards
- ride card impact derived from known ride data where available

## 12.2 Missing Feed Data For Full Shape

A full social home feed needs a server-owned feed projection.

Preferred response shape:

`GET /feed`

Returns feed items whose primary object is a ride.

Suggested payload shape:
- `id`
- `ride`
- `actor`
- `visibility / source mode`
- `impact[]`
- `engagement summary`
- `createdAt`

Impact entries should stay compact and rider-facing.

Examples:
- `type: cal_earned`
- `type: leaderboard_rank`
- `type: legend_ride`
- `type: climb_match`

The app should not need to derive a social feed by stitching unrelated
endpoints client-side.

## 12.3 Transitional Rule

Until `GET /feed` exists in the needed form:
- ship `You` mode first on the current merged archive source
- add `Global` only if there is already a coherent backend ride feed
- defer `Following` until follow graph and feed payload are clean

This keeps the product honest.

## 13. Component Architecture

Recommended component split:

- `HomeScreen`
- `HomeHeader`
- `FeedSourceChips`
- `RideFeedList`
- `RideFeedCard`
- `RideImpactStrip`
- `FeedEmptyState`
- `FeedErrorBanner`

Guidelines:
- `HomeScreen` should orchestrate loading and source mode
- card rendering logic should live below the screen level
- impact-strip formatting should be isolated so it does not sprawl through the
  screen component

## 14. States

### Signed out

Show a calm feed shell with explanatory copy.

Copy direction:
- `Sign in to follow riders and see your ride feed.`

Do not make signed-out home feel like a broken screen.

### No rides

Copy direction:
- `No rides yet`
- `Record a ride to start your feed.`

### Empty filter

Examples:
- `No rides from people you follow yet.`
- `No nearby rides right now.`

### Network error

Keep the feed shell visible.

Show banner or inline retry.

Do not replace the full screen with a fatal error shell if local `You` data
still exists.

## 15. Shipping Phases

### Phase 1 - Honest Home

Goal:
- stop calling the archive list a finished home surface

Work:
- add light header
- rename / reshape cards into feed cards
- keep `You` source backed by current merged archive data, implied rather than
  rendered as a lone chip
- add impact strip where immediately derivable

No backend feed rewrite required.

### Phase 2 - Real Feed Source

Goal:
- introduce a real server-owned community ride feed

Work:
- add `Global`
- add `Following` only when follow graph and payload are coherent
- keep the exact same ride-card grammar

### Phase 3 - Archive Separation

Goal:
- move ride archive out of `Home`

Work:
- add `Your Rides` under `Profile` or equivalent
- let `Home` remain a living feed even for the rider's own rides

## 16. Portal Relationship

This mobile implementation spec should not define a separate object model from
portal.

Shared across both:
- ride card as primary object
- impact embedded inside the ride
- no event-taxonomy feed

Portal can add density.
Mobile must preserve clarity.

## 17. Acceptance Criteria

This implementation is aligned when:

1. The mobile rider experiences `Home` as a ride feed, not an archive list.
2. A ride that mattered on BR feels richer than a plain ride without creating
   a different card species.
3. Tapping a ride naturally reveals deeper climb and economic consequences.
4. Mobile and portal can share the same feed object model.
5. Archive migration is planned cleanly rather than hidden inside `Home`.

## 18. Recommended Build Order

1. Write this spec and lock the surface shape.
2. Add a lightweight header to the current `Home`.
3. Extract `RideFeedCard` and `RideImpactStrip` from the current row renderer.
4. Ship `You` mode honestly on current ride data.
5. Add source controls only when `Global` or `Following` are real.
6. Define the backend `GET /feed` contract for `Global` and `Following`.
7. Add archive separation under `Profile` once the feed is credible.
