# Mobile Surface System Spec

**Status:** Proposed canonical surface system  
**Date:** 2026-04-23  
**Audience:** Mobile, product, design  
**Scope:** Shared shell, spacing, and section rules for top-level mobile surfaces

## 1. Purpose

This spec defines the reusable shell language for Boulder Roller mobile.

It exists to stop drift between:
- `Home`
- `Climbs`
- `Profile`
- future top-level tabs and list surfaces

This spec is about **surface grammar**, not final brand polish.

It defines:
- how top-level tabs are framed
- how sections group content
- when to use rows vs cards
- how filters should behave
- how spacing and borders create hierarchy

It is grounded in:
- [HOME_FEED_SURFACE_SPEC.md](./HOME_FEED_SURFACE_SPEC.md)
- [MOBILE_HOME_FEED_IMPLEMENTATION_SPEC.md](./MOBILE_HOME_FEED_IMPLEMENTATION_SPEC.md)
- [MOBILE_CLIMBS_IMPLEMENTATION_SPEC.md](./MOBILE_CLIMBS_IMPLEMENTATION_SPEC.md)
- [MOBILE_RIDER_IDENTITY_SOCIAL_SHAPE_SPEC.md](./MOBILE_RIDER_IDENTITY_SOCIAL_SHAPE_SPEC.md)
- [LANGUAGE_SPEC.md](./LANGUAGE_SPEC.md)

## 2. System Layers

The mobile UI system has four layers:

1. `Header grammar`
2. `Surface grammar`
3. `Content primitives`
4. `Screen-specific composition`

This spec covers layer 2.

## 3. Header Grammar

Top-level tabs use one shared header system:
- centered title
- equal-width left spacer
- search + alerts cluster on the right
- compact vertical height

This is implemented by:
- [TopTabBar.tsx](../../mobile/src/components/navigation/TopTabBar.tsx)

Rules:
- titles should be optically centered, not fake-centered
- top-level titles are compact and quiet
- utility buttons are tools, not heroes
- no subtitles in the top bar

## 4. Surface Families

We do **not** want one universal card.

We want a small family of related surfaces:

### 4.1 Feed Surface

Used by `Home`.

Characteristics:
- edge-to-edge row feel
- low chrome
- separators rather than loud containers
- future media can live inside the row

### 4.2 Explorer Surface

Used by `Climbs`.

Characteristics:
- asset identity first
- compact stat cluster
- one status line
- more structured than feed, less boxed than old cards

### 4.3 Grouped Section Surface

Used by `Profile`.

Characteristics:
- grouped rows within one section shell
- dividers between actions
- less “stack of cards”, more “account/settings list”

## 5. Canonical Containers

### 5.1 `SectionCard`

Purpose:
- grouped shell for settings, stats, or account sections

Rules:
- use for grouped content, not for every individual row
- one `SectionCard` may hold multiple `ActionRow`s
- avoid stacking many single-row cards when one grouped section would do

Implementation:
- [SectionCard.tsx](../../mobile/src/components/surfaces/SectionCard.tsx)

### 5.2 Edge Rows

Purpose:
- list items that should read as part of a feed or explorer surface

Rules:
- use row separators and padding, not oversized container chrome
- rows may be tappable
- rows should not feel like floating tiles unless they truly need independent emphasis

## 6. Filter Controls

On mobile, list filters should default to a compact segmented control.

Rules:
- place directly under the top tab bar
- not sticky by default
- use only when there is a meaningful choice
- do not use large floating bubble chips for simple binary filters

Implementation:
- [SegmentedControl.tsx](../../mobile/src/components/surfaces/SegmentedControl.tsx)

## 7. Grouping Rules

Use grouped sections when the rider is choosing between related utilities.

Examples:
- `Profile` settings
- wallet + connection actions
- future account/privacy blocks

Do not use grouped sections when the rider is browsing independent objects.

Examples:
- climbs
- rides
- leaderboard rows

## 8. Spacing Rules

The system should feel uniform even when screens have different content.

Rules:
- top-level screen body padding is modest, not luxurious
- rows own their own internal padding
- section labels sit close to their grouped content
- avoid “header, then big gap, then bubble, then big gap, then content”

## 9. Border and Radius Rules

Use borders and radii intentionally:

- `TopTabBar` buttons: small pill radius
- grouped sections: medium-large radius
- feed/explorer rows: mostly separator-driven

Guideline:
- rows should not become cards by accident
- grouped sections should not become dashboards by accident

## 10. Surface Selection Guide

Use:
- `TopTabBar` for top-level tab framing
- `SegmentedControl` for compact mobile mode switching
- `SectionCard` for grouped settings/account content
- row surfaces for rides and climbs

Do not:
- create ad hoc bubbles to explain every tab
- create custom chip rows per screen when segmented control fits
- create one-off card shapes for every new feature

## 11. Acceptance Criteria

The surface system is aligned when:

1. `Home`, `Climbs`, and `Profile` feel like the same app.
2. The difference between screens comes from content, not arbitrary container styles.
3. New features can choose from a small named set of surfaces instead of inventing new ones.
4. Riders perceive hierarchy through rhythm and grouping, not loud boxes.
