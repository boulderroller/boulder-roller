# Mobile Content Primitives Spec

**Status:** Proposed canonical content primitive spec  
**Date:** 2026-04-23  
**Audience:** Mobile, product, design  
**Scope:** Shared inner anatomy for ride items, climb items, grouped settings, and detail modules

## 1. Purpose

This spec defines the layer below the surface system.

If the surface system answers:
- what kind of shell is this screen using?

This spec answers:
- what is the anatomy of the object inside that shell?

It exists to standardize:
- ride list items
- climb list items
- grouped account rows
- stat clusters
- impact strips
- detail modules

It is grounded in:
- [MOBILE_SURFACE_SYSTEM_SPEC.md](./MOBILE_SURFACE_SYSTEM_SPEC.md)
- [MOBILE_DETAIL_GRAMMAR_SPEC.md](./MOBILE_DETAIL_GRAMMAR_SPEC.md)
- [MOBILE_RIDER_IDENTITY_SOCIAL_SHAPE_SPEC.md](./MOBILE_RIDER_IDENTITY_SOCIAL_SHAPE_SPEC.md)
- [HOME_FEED_SURFACE_SPEC.md](./HOME_FEED_SURFACE_SPEC.md)
- [MOBILE_HOME_FEED_IMPLEMENTATION_SPEC.md](./MOBILE_HOME_FEED_IMPLEMENTATION_SPEC.md)
- [MOBILE_CLIMBS_IMPLEMENTATION_SPEC.md](./MOBILE_CLIMBS_IMPLEMENTATION_SPEC.md)

## 2. Primitive Set

The canonical content primitives are:

1. `RideFeedItem`
2. `ClimbListItem`
3. `ActionRow`
4. `StatCluster`
5. `ImpactStrip`
6. `DetailModule`

## 3. `RideFeedItem`

Purpose:
- the primary unit of `Home`

Current implementation:
- [RideFeedItem.tsx](../../mobile/src/components/home/RideFeedItem.tsx)

Anatomy:
- actor label
- date
- ride title
- status line
- stat cluster
- optional impact strip

Rules:
- rides are the object, not protocol events
- actor labels come from rider identity, not hardcoded perspective like `You`
- usernames and display names keep their natural casing
- status line explains the ride’s current meaning
- impact strip is optional and compact
- nested actions should be avoided in the list item

Future extension points:
- media slot
- map preview
- kudos/comments footer
- richer climb consequence summaries

## 4. `ClimbListItem`

Purpose:
- the primary unit of `Climbs`

Current implementation:
- [AssetRow.tsx](../../mobile/src/components/surfaces/AssetRow.tsx)

Anatomy:
- climb name
- region
- compact stat cluster
- status line

Rules:
- climb identity first
- status line explains why the climb matters now
- only one state line at list level
- deeper vault/legend/board complexity belongs after tap

## 5. `ActionRow`

Purpose:
- grouped list row for account/settings/utilities

Current implementation:
- [ActionRow.tsx](../../mobile/src/components/surfaces/ActionRow.tsx)

Anatomy:
- title
- optional subtitle
- optional chevron
- optional destructive treatment

Rules:
- use inside grouped sections
- do not wrap every action in a separate card if one grouped section fits
- subtitles explain the current state or capability, not full documentation

## 6. `StatCluster`

Purpose:
- shared metric presentation for rides, climbs, and profile summaries

Current implementation:
- [StatCluster.tsx](../../mobile/src/components/surfaces/StatCluster.tsx)

Anatomy:
- 2-4 metrics
- each metric has value + label
- optional divider-driven grouped mode

Rules:
- keep clusters short
- labels are quiet
- values carry the emphasis
- use grouped mode for profile/account contexts
- use freer row mode for rides/climbs

## 7. `ImpactStrip`

Purpose:
- compact BR-native consequence line(s)

Current implementation:
- [ImpactStrip.tsx](../../mobile/src/components/home/ImpactStrip.tsx)

Examples:
- `On device`
- `Upload pending`
- `Climbs available`
- `Earnings available`
- future: `+47 CAL`, `#6 on Manayunk Wall`, `Legend ride`

Rules:
- maximum two items
- short, scannable, secondary to the object
- do not let impact replace the ride or climb itself

## 8. `DetailModule`

Purpose:
- canonical block for detail screens

Canonical grammar:
- formalized in [MOBILE_DETAIL_GRAMMAR_SPEC.md](./MOBILE_DETAIL_GRAMMAR_SPEC.md)

Target anatomy:
- section title
- optional supporting line
- main content
- optional CTA

Rules:
- one idea per module
- 4-6 modules max on a detail screen
- detail modules should compose consistently across ride, climb, and future profile detail screens

This is the next layer to push harder in:
- `ClimbDetail`
- `RideDetail`

## 9. Selection Guide

Use:
- `RideFeedItem` in `Home`
- `ClimbListItem` in `Climbs`
- `ActionRow` in grouped settings/account sections
- `StatCluster` whenever 2-4 metrics need one shared rhythm
- `ImpactStrip` when BR-specific consequences matter in a list context

Do not:
- invent new list-item anatomy for every screen
- stuff multiple unrelated ideas into one row
- create separate list-item species for every protocol event type

## 10. Acceptance Criteria

The content primitive layer is aligned when:

1. `Home` uses a canonical ride item, not an ad hoc row.
2. `Climbs` uses a canonical climb item, not a leftover generic card.
3. `Profile` reads as grouped structure, not a deck of unrelated cards.
4. New list/detail work can reference named primitives instead of inventing structure from scratch.
