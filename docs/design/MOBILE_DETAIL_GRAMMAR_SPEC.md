# Mobile Detail Grammar Spec

**Status:** Proposed canonical detail-screen grammar  
**Date:** 2026-04-23  
**Audience:** Mobile, product, design  
**Scope:** Shared navigation, header, module, and state rules for detail and deep-slice mobile screens

## 1. Purpose

This spec defines the layer below top-level tabs and list surfaces:
- what happens after the rider taps into one object
- how detail screens should be framed
- how deep-slice screens should differ from object detail

It exists to stop drift between:
- `RideDetail`
- `ClimbDetail`
- `ClimbLeaderboard`
- future rider detail and vault detail screens

It is grounded in:
- [MOBILE_SURFACE_SYSTEM_SPEC.md](./MOBILE_SURFACE_SYSTEM_SPEC.md)
- [MOBILE_CONTENT_PRIMITIVES_SPEC.md](./MOBILE_CONTENT_PRIMITIVES_SPEC.md)
- [MOBILE_RIDER_IDENTITY_SOCIAL_SHAPE_SPEC.md](./MOBILE_RIDER_IDENTITY_SOCIAL_SHAPE_SPEC.md)
- [MOBILE_HOME_FEED_IMPLEMENTATION_SPEC.md](./MOBILE_HOME_FEED_IMPLEMENTATION_SPEC.md)
- [MOBILE_CLIMBS_IMPLEMENTATION_SPEC.md](./MOBILE_CLIMBS_IMPLEMENTATION_SPEC.md)
- [LANGUAGE_SPEC.md](./LANGUAGE_SPEC.md)

## 2. System Layer

The mobile system now has five layers:

1. `Header grammar`
2. `Surface grammar`
3. `Content primitives`
4. `Detail grammar`
5. `Screen-specific composition`

This spec covers layer 4.

## 3. Screen Classes

The canonical detail hierarchy has two classes:

### 3.1 Detail Screen

Purpose:
- understand one object clearly

Examples:
- `RideDetail`
- `ClimbDetail`
- future rider detail

Rules:
- object identity is primary
- 4-6 modules max
- one primary action row near the top if needed
- modules answer different questions about the same object

### 3.2 Deep Slice Screen

Purpose:
- inspect one aspect of an object deeply

Examples:
- `ClimbLeaderboard`
- future `ClimbVault`
- future payout or proof screens

Rules:
- one aspect only
- lighter header than object detail
- short summary, then focused content
- no competing CTAs

## 4. Detail Header Grammar

Top-level tabs use `TopTabBar`. Detail and deep-slice screens use a different grammar.

### 4.1 Structure

Top to bottom:
1. Back row
2. Title block
3. Optional hero or summary block

### 4.2 Back Row Rules

Placement:
- top-left
- above the title block
- always present when the screen is not a top-level tab

Tone:
- quiet
- navigational
- never the loudest element on the screen

### 4.3 Back Label Rules

Use the most stable meaningful parent label available.

Priority order:
1. parent tab or surface name
2. parent object class
3. `Back` as fallback only

Examples:
- `RideDetail` from `Home` -> `‹ Home`
- `ClimbDetail` from `Climbs` -> `‹ Climbs`
- `ClimbLeaderboard` from `ClimbDetail` -> `‹ Climb`
- modal or ambiguous fallback -> `‹ Back`

Do not:
- generate verbose labels like `Back to Activity Feed`
- use inconsistent copy between screens
- drop the label entirely in favor of a naked icon unless platform conventions demand it later

### 4.4 Title Block Rules

Detail-screen titles should be:
- left-aligned
- below the back row
- visually stronger than the back row

Deep-slice titles should be:
- left-aligned
- slightly quieter than full object detail

Optional supporting line:
- maximum one supporting line
- use for context, not explanation walls

Examples:
- ride date/time
- climb region
- `All-time top 10 for this climb`

## 5. Module Grammar

Detail screens are built from canonical modules.

### 5.1 `DetailModule` Anatomy

Each module may contain:
- section title
- optional supporting line
- main content
- optional CTA

Rules:
- one idea per module
- no mixed-purpose modules
- modules should stack in a stable order
- module CTA belongs at the bottom of the module, not floating elsewhere

### 5.2 Module Ordering

Preferred detail order:
1. identity / hero
2. primary actions
3. permanent or core context
4. rider-specific context
5. process / settlement / proof context
6. off-ramp

This keeps rider meaning ahead of protocol mechanics.

### 5.3 Module Count

Target:
- 4-6 modules max on a detail screen

Deep slices should usually have:
- 1 summary block
- 1 main content block

## 6. CTA Grammar

Rules:
- one primary CTA row near the top when the object truly supports action
- secondary CTAs live inside the relevant module
- deep slices should not compete with multiple actions

Examples:
- `ClimbDetail`: `View Leaderboard`, `Deposit CAL`
- `RideDetail`: usually no large top CTA; actions belong inside modules
- `ClimbLeaderboard`: no top CTA beyond navigation

## 7. State Grammar

State handling should preserve shape, not replace it.

### 7.1 Loading

Rules:
- lightweight loading state is acceptable
- do not lose navigational context unnecessarily
- once we have shared primitives, use skeletons before inventing per-screen spinners

### 7.2 Recoverable Error

Rules:
- keep the header/back affordance
- prefer a retry banner or inline retry module
- do not collapse the whole screen into a trap state if content shape can still stand

### 7.3 Empty State

Rules:
- preserve screen identity
- say what is absent
- say what the rider can do next

Examples:
- `No leaderboard entries yet`
- `No climb matches yet`

## 8. Language Rules

Mobile detail screens should stay rider-facing.

Use:
- `Leaderboard`
- `Legend`
- `Ride Status`
- `CAL Earned`
- `View on BoulderScan`

Avoid on mobile detail surfaces:
- `attestation` as a primary label
- `PDA`
- `commitment` as headline language
- raw event or instruction names

Deeper proof language belongs in BoulderScan or an explicit proof off-ramp.

## 9. Initial Canonical Models

This grammar implies four first-class detail models:

1. `RideDetail`
- ride hero
- ride summary
- climb matches
- ride status / processing
- earnings
- proof off-ramp

2. `ClimbDetail`
- climb hero
- primary actions
- leaderboard preview
- legend
- vault
- your relationship

3. `ClimbLeaderboard`
- summary
- all-time top 10

4. future `ClimbVault`
- summary
- current vault status
- deposit/position actions

## 10. Implementation Implications

This spec should lead to shared components such as:
- `DetailHeader`
- `DetailModule`
- `DetailSummaryBlock`

These are not required to land before the spec, but new detail work should conform to this grammar even before the components are fully extracted.

## 11. Acceptance Criteria

The detail grammar is aligned when:

1. Back navigation placement and wording no longer vary ad hoc between screens.
2. `RideDetail` and `ClimbDetail` feel like siblings, not unrelated pages.
3. Deep slices like `ClimbLeaderboard` feel narrower and more focused than object detail.
4. Loading, empty, and error states preserve navigational coherence.
5. Future detail work can cite named grammar rules instead of improvising layout.
