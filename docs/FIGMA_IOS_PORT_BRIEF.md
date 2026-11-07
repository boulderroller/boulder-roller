# Figma Handoff — Port Web Portal UI to iOS (Boulder Rollers v2, Tile-Based Attestation)

> ⚠️ **OUTDATED CAL MODEL**: This brief references "daily CAL budget" and "score this
> pattern" flows which are deprecated. Current model: **CAL is earned from TSS on rides**,
> automatically tributed to vaults. No daily budget or manual scoring.

Purpose: Ingest the current web portal Figma (source of truth) into a new Figma Make file and produce an iOS design system + screen set that mirrors the portal, adapted for mobile. Keep components/tokens consistent; drop segment-era UI in favor of tile/pattern architecture.

## Inputs
- Source file: current web portal Figma (99% complete) — duplicate into a new Figma Make project.
- Architecture reference: `docs/PLATFORM_FEATURE_MATRIX.md`, `docs/PLATFORM_DELIVERY_CHECKLIST.md`, tile-based spec in the latest architecture note (effort/pattern-led, no user-created segments).

## Scope (must ship)
- Auth: nonce/verify flow, wallet binding, error/empty states.
- Home/Dashboard: daily CAL budget, “Nice ride!” summary, pattern highlights (Climb/Steady/Exploration).
- Ride Detail: polyline map, tile-derived patterns list, stats (vert, duration, W/kg if available), CAL mint/score affordance.
- Patterns: list + detail for Climb/Steady/Exploration (no segment language).
- Leaderboards: effort-based per arena (World Arena default); metric toggles (W/kg, vert/time).
- CAL/Scoring: daily budget view, “score this pattern” flow, success/fail states.
- Beetle Cards: card gallery + detail (Climb/Steady/Explorer scopes), level/score display; no marketplace/trading.
- Profile: wallet, balances (points/DUNG/CAL), ride history, referrals.
- Settings: base URL, theme toggle if present on web, support link.

## Out of Scope (do not port)
- Segment creation/matching UI, segment leaderboards, segment efforts.
- Marketplace/trading flows, governance voting, time-based Flow KOMs (future).
- Points→token conversion UI (not live yet).
- Push notifications; keep in-app toasts/banners only.

## Component/Tokens Guidance
- Reuse portal tokens: colors, typography, spacing, corner radius, shadows. If you must adapt, define iOS aliases mapping 1:1 to web tokens.
- Navigation: mobile tab bar for primary sections (Home, Rides, Patterns, Leaderboard, Profile). Secondary actions via sheets.
- Cards: adapt portal cards to mobile width; keep visual hierarchy (title, key metric, secondary metric, status/pill).
- Maps: use same map styling and pin/overlay system; include tile-derived pattern overlays abstractly (no tile IDs).
- CTAs: primary = scoring/CAL actions; secondary = navigation/back; tertiary = info.

## Copy/Voice (mirror web)
- Replace “segment” with “pattern”/“climb”/“steady”/“exploration”.
- Leaderboards: “Effort Rank”, “W/kg”, “Vert/time”, “Arena”.
- CAL: “Daily budget” not “energy credits”.
- Beetle Cards: “Climb Card”, “Steady Card”, “Explorer Card”.

## States to Design
- Loading/skeleton for lists, cards, leaderboards.
- Empty states for: no rides yet, no patterns detected, no CAL left, leaderboard empty (new arena).
- Error states: network failure, scoring failed, auth failed, CAL mint cooldown.
- Success toasts/sheets: ride uploaded, CAL minted, pattern scored, card updated.

## Data Alignment (tile/pattern model)
- User never sees tiles/H3 wording. Patterns are surfaced as “Climb” (vert/time), “Steady” (duration/intensity), “Exploration” (new areas).
- Arenas: start with “World Arena” only; allow future named arenas (Boulder North, Marin, etc.) via dropdown/picker.
- Leaderboards: effort-based (W/kg/effort score); time-based flows are v2, don’t design yet.

## Deliverables
- Figma Make file with: component library (colors, type, buttons, cards, lists, modals, tabs, charts), screen flows for all scoped features, documented variants/states.
- Redlines/notes on responsive behavior (iPhone 14/15 baseline), safe areas, hit targets.
- Handoff notes for iOS: component names/variants, expected props, sample data JSONs per screen.

## Quick Checklist for Agent
- [ ] Duplicate portal file into new Figma Make project; re-link components to new library.
- [ ] Create iOS design tokens mapped to portal tokens; avoid introducing a new palette.
- [ ] Build mobile nav (tab bar) and stack the portal layouts into mobile patterns (sheets, drawers, stacked lists).
- [ ] Replace all segment terminology with pattern/arena language.
- [ ] Include all required states (loading/empty/error/success) for each surface listed above.
- [ ] Provide sample data blocks for Patterns, Leaderboards, Beetle Cards, CAL balance, Rides.
- [ ] Export preview PDF of key flows (Home, Ride Detail, Pattern Detail, Leaderboard, Scoring, Card) for review.
