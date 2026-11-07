# BR Primitive Targets - 2026-05-12

This is the implementation bridge from the current capture audit. It names the
shared primitives worth designing/refining first, using current BR surfaces as
constraints.

Source evidence:
- `docs/design/renderings/current-captures/2026-05-12/`
- `docs/design/renderings/current-captures/2026-05-12/AUDIT.md`
- `docs/design/BR_IDENTITY_SYSTEM.md`

## Rule

Do not start by restyling whole pages. Start by stabilizing the primitives that
repeat across ride, climb, feed, rider, and mobile detail surfaces.

## 1. Ride Header

Owns:
- rider
- title
- date
- counted/private/status state
- primary receipt actions

Current evidence:
- `desktop-rideview.png`
- `responsive-mobile-rideview.png`

Keep:
- title and date as the first read
- counted state as a small trust marker
- compact rider identity

Fix:
- reduce title-adjacent utility buttons
- separate destructive/admin actions from primary ride reading
- define mobile wrapping rules for long titles and rider names

Do not:
- lead with proof internals
- make CAL/vault the hero before the ride is understood

## 2. Route Map

Owns:
- route shape
- map context
- optional elevation relationship
- route preview in feed

Current evidence:
- `desktop-rideview.png`
- `desktop-feedview-item.png`
- `responsive-mobile-climb-table-current.png`

Keep:
- map as the primary athletic visual
- simple route line

Fix:
- avoid washed-out large maps that feel empty
- remove technical map datum copy from feed-level surfaces
- create reliable crop/aspect rules so maps do not show dead gray zones

Do not:
- turn maps into decorative backgrounds
- let the route line be the only meaningful visual element on a large canvas

## 3. Consequence Strip

Owns:
- counted CAL
- matched climbs
- rank/result
- record/proof state

Current evidence:
- `desktop-rideview.png`
- `desktop-feedview-item.png`
- `desktop-rideview-vault-panel.png`

Keep:
- compact result language like `+96 CAL` and `#2`
- consequences attached to rides/climbs

Fix:
- make the strip explain what changed because of the ride
- keep proof language quiet and receipt-like

Do not:
- create generic wallet/dashboard widgets on ride surfaces
- let token facts outrank the athletic object

## 4. Climb Inspector

Owns:
- selected climb preview inside RideView
- desktop panel/popout candidate
- mobile bottom-sheet candidate

Current evidence:
- `desktop-climb-table-current.png`
- `responsive-mobile-climb-table-current.png`

Keep:
- climb name, distance, vert, grade
- elevation profile
- rider result values: time, speed, VAM, rank
- vault action when present

Fix:
- rename internal labels such as `Segment spine`
- make elevation shape more legible
- change `Clear` to selected-state language that reads like product

Do not:
- invent a separate popout that drops the current table data spine
- make mobile a shrunken desktop table

## 5. Climb Economy Strip / Popout

Owns:
- vault state
- counted efforts
- local legend
- active week
- future expand/collapse economy detail

Current evidence:
- `desktop-climbview-record-economy-module.png`
- `desktop-rideview-vault-panel.png`
- `desktop-vaultview-economy-reference.png`
- `responsive-mobile-climb-econ-current.png`

Keep:
- economy as attached context on a real climb
- short labels: vault, legend, week, entries

Fix:
- replace system-ish values like `Vault 1` with rider-readable names/states
- avoid four equal admin boxes as the primary presentation
- define an expandable detail pattern before building a popout

Do not:
- design this like a DeFi position panel
- imply a popout already exists

## 6. Leaderboard Row

Owns:
- rank
- rider identity
- time
- power
- VAM
- result state

Current evidence:
- `desktop-climbview.png`
- `desktop-climb-table-current.png`

Keep:
- dense tabular scanning
- time and rank as primary values

Fix:
- display-name/handle fallback rules
- truncation rules for long generated names
- empty-state rules for missing VAM/power

Do not:
- expose raw wallet-like/generated identifiers as the best available name when
  a better display label exists

## 7. Rider Header

Owns:
- avatar/no-avatar
- display name
- handle/beetle number
- public/private state
- follow/share/report/edit actions

Current evidence:
- `desktop-riderview.png`
- `responsive-mobile-profileview.png`

Keep:
- rider record framing
- compact social actions
- profile stats as supporting context

Fix:
- graceful no-avatar state that does not dominate the page
- hide or soften owner-only setup/completeness state outside owner context
- display rules for empty or suspicious stats

Do not:
- make public profiles feel like settings screens
- let account setup UI outrank rider activity

## First Implementation Order

1. Route Map + map crop/aspect rules.
2. Ride Header + Consequence Strip.
3. Climb Inspector.
4. Climb Economy Strip.
5. Leaderboard Row.
6. Rider Header.
7. Feed Activity Card polish after the above primitives are stable.

Reason: RideView and Climb Inspector are the highest leverage. They touch the
brand thesis directly: ride first, climb/result second, economy as consequence.

## Copy Rules To Lock Before Code

- `Segment spine` -> rider-facing selected climb label.
- `Vault 1` -> vault name or active vault state.
- `Record` -> use only where a receipt/proof fact is actually being shown.
- Empty numeric values -> hide, mark unavailable, or explain source state.
- Technical map labels -> details/debug only, not feed.

## Mobile Rule

Responsive portal captures are useful for hierarchy stress, but native mobile
needs its own primitives:

- mobile detail header
- climb inspector bottom sheet
- climb economy bottom sheet
- compact action bar

Do not treat responsive portal screenshots as native mobile truth.
