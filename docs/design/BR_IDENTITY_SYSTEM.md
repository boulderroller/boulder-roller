# Boulder Roller Identity System

**Status:** Canonical identity contract
**Date:** 2026-05-12
**Updated:** 2026-07-21
**Owner:** Product + design + frontend

**Renderings:** `docs/design/renderings/br-identity-renderings.html`
**Refined renderings:** `docs/design/renderings/br-identity-refinement-board.html`
**Interaction renderings:** `docs/design/renderings/br-identity-interactions-board.html`
**State range renderings:** `docs/design/renderings/br-identity-state-range-board.html`
**Calibration packet:** `docs/design/renderings/BR_IDENTITY_VISUAL_PACKET_2026-05-12.pptx`
**Current captures:** `docs/design/renderings/current-captures/2026-05-12/`
**Primitive targets:** `docs/design/BR_PRIMITIVE_TARGETS_2026-05-12.md`
**Proof/economy primitives:** `docs/design/PROOF_ECONOMY_PRIMITIVES.md`
**Portal 2026 contract:** `docs/design/PORTAL_DESIGN_SYSTEM_2026.md`

## 1. Governing Thesis

Boulder Roller should feel like a serious cycling app that discovered an
economy, not a crypto app that discovered cycling.

The base product is cycling: rides, climbs, maps, results, leaderboards,
profiles, and rider history. The Boulder Roller layer is the verifiable
consequence of those rides and results: CAL, vaults, local legends, deposits,
settlement, payout history, and BoulderScan.

The brand tone is:

- measured
- athletic
- map-native
- precise
- slightly mythic
- never goofy

The speaker is a rider who understands the machinery: rider in perspective,
engineer in causality, and institution only when a recorded consequence needs
an exact state. The internal disposition reference is Lachlan Morton crossed
with Tadej Pogačar: high competence, low ceremony; respect for place,
preparation, clean competition, and the people who make the ride possible;
embarrassment at heroic self-mythology, suffering theater, status worship,
forced rider slang, and data presented as infallible.

Agent-written product copy must stay literal unless product leadership supplies
the line. Do not invent slogans, campaign language, or new named concepts to
make a surface feel branded. Use the shortest product-true phrase that says
what the surface does.

The app should make a rider feel:

- "I rode it."
- "Here are the climbs."
- "Here is where I stand."
- "Here is what changed."

Public and ambient product copy assumes the ride happened. Boulder Roller does
not grant legitimacy to the ride after the fact. Use `counted` or `confirmed`
only when the rider is looking at a real eligibility, correction, or finality
state. Keep CAL, DUNG, Balance, and other economic codes out of the first
public explanation; introduce them after the ride, climbs, times, and
leaderboards are understood.

## 2. Product Layering

Every surface must know which layer it belongs to.

### 2.1 Athletic Layer

This is the default layer. It owns first impression and primary hierarchy.

Use it for:

- feed
- ride recording
- ride detail
- climb detail
- leaderboards
- profiles
- settings
- training and performance data

Visual language:

- route maps
- elevation profiles
- tables
- compact stat clusters
- rider rows
- activity titles
- quiet metadata

Copy language:

- rode
- saved
- matched
- held
- cleared
- rank
- result
- record

### 2.2 BR Consequence Layer

This layer attaches to real athletic objects. It should not replace them.

Use it for:

- counted CAL
- vault deposits
- local legend status
- payout and settlement summaries
- ride status
- BoulderScan off-ramps
- earned outcomes

Visual language:

- compact status chips
- small consequence strips
- restrained color accents
- narrow side panels on desktop
- detail modules after the athletic object is understood

Copy language:

- CAL from this ride
- Ride status
- Status
- Week
- Legend
- Vault
- Deposit
- Payout

### 2.3 Technical Detail Layer

This layer is explicit and opt-in. It belongs behind details, disclosure, or
BoulderScan.

Use it for:

- attestation internals
- PDAs
- commitments
- parser versions
- raw source diagnostics
- instruction and event names
- low-level protocol state

Do not lead primary app surfaces with this layer.

## 3. Surface Rules

### 3.1 Feed

The feed is a human activity surface, not an event log.

Required hierarchy:

1. rider or actor
2. ride or climb object
3. core athletic stats
4. compact BR consequence, if relevant
5. social/action affordances

Allowed BR consequence examples:

- `+47 CAL`
- `3 climbs matched`
- `Ride ready`
- `#6 on Manayunk Wall`

Banned feed patterns:

- protocol event cards
- standalone token-transfer rows
- proof-first rows
- lore labels
- wallet-dashboard composition

### 3.2 Ride Detail

Ride detail is the ride page. It must start with the ride.

Required hierarchy:

1. title, rider, date, and privacy/state
2. route map
3. core stats
4. elevation and climb matches
5. status and verification
6. comments/actions

The verification module should feel like a footer or receipt, not a control
room. It may expose BoulderScan, but it should not make BoulderScan the main
event.

### 3.3 Climb Detail

Climb detail is a place/object surface.

Required hierarchy:

1. climb identity
2. map/elevation shape
3. leaderboard or best result
4. rider relationship to the climb
5. legend and vault context
6. deeper vault or BoulderScan off-ramp

Vault context must attach to the climb. Do not create a generic finance panel
that could belong to any token product.

For climb browsing, the page should read as `Climbs` and `Browse climbs`, not
as a vault catalog. Attached economics may borrow compact DeFi card patterns,
but the card identity remains the climb.

On Climb detail and its attached Vault detail, every seated rider tied at the
fastest validated whole-second time is a co-KOM. Give every co-KOM row equal
visual treatment: the same crown and `T-1` hierarchy. Sporting presentation
uses `competition_rank`; compatibility positional `rank` must not visually
demote a tied rider. Never promote singular `kom_holder` as the sole sporting
winner; it is only the deterministic legacy representative.

### 3.4 Portfolio

Portfolio is allowed to be economy-forward, but it still must be object-backed.

Required hierarchy:

1. rider balances and positions
2. climbs/vaults those positions belong to
3. earned/pending outcomes
4. transaction or settlement details

Banned portfolio patterns:

- generic DeFi dashboard widgets
- price-chart-first composition
- disconnected wallet tables
- language that makes the rider feel they left the cycling app

### 3.5 BoulderScan

BoulderScan may be technical, but it should remain legible.

It can expose:

- addresses
- signatures
- PDAs
- instruction names
- raw record facts
- event history

It should still use BR object names where possible: ride, climb, vault, legend,
record, payout.

## 4. Visual Rules

### 4.1 Overall Feel

Clean, beautiful, dense enough to trust, and quiet enough that the data leads.

The app should borrow from Strava and TrainingPeaks in the core flows:

- familiar activity pages
- strong maps
- readable stats
- confident tables
- low-chrome containers
- obvious navigation

Boulder Roller owns:

- topo and elevation forms
- climb/vault adjacency
- leaderboard and verification states
- local rivalry
- verifiable consequence
- warm restrained accents

### 4.2 Containers

Use quiet containers by default.

Default:

- 1px borders
- low-opacity dividers
- no glow
- no decorative heavy shadow
- 4-8px radius on modern app shells and cards

Reserve hard mechanical treatment for:

- primary buttons
- selected interactive controls
- deliberate BR economy objects
- rare emphasis states

Do not make every surface look like a stamped metal object.

### 4.3 Color

Use one primary alpha identity before reintroducing theme variety.

Default direction:

- neutral app background
- clear foreground text
- subdued map/elevation greens and terrain tones
- CAL as restrained electric blue
- DUNG/reward as restrained gold
- proof/status as quiet green
- warning/review as amber
- destructive as red

Avoid:

- brown/brass dominance
- fantasy tavern warmth
- cyberpunk neon panels
- purple-blue crypto gradients
- one-note dark slate dashboards
- glowing economy cards as the default state

### 4.4 Typography

Use Geist Sans as the primary Boulder Roller typeface. It is clean enough for
serious cycling surfaces, technical enough to support times and stats, and
plain enough that maps, leaderboards, and ride objects still lead.

Use Geist Mono only where precision matters:

- numbers
- times
- distances
- ranks
- balances
- hashes and addresses
- compact table cells that need scan alignment

Mono does not belong on every label, paragraph, navigation item, chip, or
button. If the whole screen feels like a terminal, the type system is failing
the product.

Product UI type must be stable and role-based. Do not fluid-scale labels,
tables, feed rows, stats, chips, tabs, or controls; these need predictable
fit, alignment, and density across devices.

Editorial brand type may use fluid `clamp()` sizing for large moments:

- deck covers
- campaign or launch pages
- first-viewport brand statements
- rare empty states that are intentionally expressive

The split is:

| Role | Treatment |
| --- | --- |
| Product UI | Geist Sans, fixed semantic tokens |
| Numeric data | Geist Mono, restrained and local |
| Editorial display | Geist Sans, fluid `clamp()` allowed |
| Technical disclosure | Geist Mono for addresses and signatures only |

Keep the scale small and named. Avoid arbitrary one-off font sizes when a
shared role exists.

### 4.5 Maps and Elevation

Maps and elevation are first-class brand material.

Prefer:

- route maps over generic illustration
- elevation profiles over abstract decoration
- terrain/topo lines where they clarify the object
- climb segment overlays where they explain the ride

Avoid:

- decorative topo wallpaper
- map textures that compete with data
- dark atmospheric map crops where the route cannot be read

## 5. Copy Rules

Voice: clean athletic editorial.

The rider-facing activity object is always `Ride`. Use `Status` for lifecycle,
`Verification` for optional proof detail, and `Leaderboard`, `KOM`, `PR`, or
`best time` for athletic achievement. Keep protocol identifiers exact in code
and technical disclosure.

Lead with the rider-facing outcome, then the consequence, then what is waiting.

Good patterns:

- `Saved to your log.`
- `No CAL from this ride.`
- `Effort data needed for CAL.`
- `Ride saved.`
- `Needs review.`
- `View on BoulderScan.`

Preferred replacements:

| Avoid | Use |
| --- | --- |
| Ride Proof | Verification |
| Proof state | Status |
| Rewardable CAL | CAL from this ride |
| Effort source | Data |
| Settlement week | Week |
| Source details | File details |
| Protocol state | System state |
| Processing ride data | Reading ride file |
| Processing in background | Checking ride |

Banned primary-surface language:

- attestation
- PDA
- commitment
- canonical
- route_only
- protocol state
- index state
- Merkle
- instruction
- event emit

These words may appear in BoulderScan or explicit technical details.

## 6. Component Rules

### 6.1 Web Portal

The active portal system must converge on:

- one primary BR theme for alpha
- shared semantic object colors
- quiet containers for content
- hard interaction physics only where useful
- shadcn/Radix for behavior
- BR wrappers for final visual grammar

`web/portal/DESIGN_SYSTEM_RULES.md` remains useful as a current-state audit, but
this document and `docs/design/PORTAL_DESIGN_SYSTEM_2026.md` govern identity and
public-root-to-portal implementation decisions.

### 6.2 Mobile

Mobile must get real shared tokens instead of screen-local hardcoded colors.

Start with:

- `mobile/src/theme/tokens.ts`
- `SectionCard`
- `DetailModule`
- `TopTabBar`
- `VerifyChip`
- ride/climb list primitives

Mobile should preserve its existing grammar:

- top tab bar for top-level surfaces
- row-first feed and climb browsing
- grouped sections for settings/profile
- detail modules after tap

But the visual finish should align with the same BR identity: athletic first,
economy attached, proof quiet.

### 6.3 Proof and Economy

Proof and economy should be implemented as reusable primitives:

- `RecordStatus`
- `CountedCal`
- `VaultPosition`
- `LegendStatus`
- `BoulderScanLink`
- `SettlementSummary`

They should have compact and detailed variants. Compact variants belong in feed,
lists, and headers. Detailed variants belong in ride detail, climb detail,
portfolio, and BoulderScan.

## 7. Review Checklist

Use this checklist in UI review:

- Does the screen still feel like a cycling app before the economy appears?
- Is the primary object a ride, climb, rider, route, or result?
- Is proof/status quiet unless the rider asked for details?
- Does CAL attach to effort or a position instead of floating as token content?
- Are maps, elevation, stats, and leaderboards doing real work?
- Can a non-crypto cyclist understand the screen in five seconds?
- Did we avoid raw protocol language on primary surfaces?
- Did we avoid fantasy, tavern, cyberpunk, and generic DeFi patterns?
- Are containers quieter than the content inside them?
- Is the copy short, confident, and rider-native?

## 8. Visual Review Artifacts

Pre-implementation renderings live in `docs/design/renderings/`.

- `br-identity-renderings.html` - first static direction board
- `br-identity-refinement-board.html` - refined beauty, surface, stress, and mobile pass
- `br-identity-interactions-board.html` - climb inspector, explorer, climb object, vocabulary, and mobile sheet
- `br-identity-state-range-board.html` - live, processing, social, and dark-mode states
- `BR_IDENTITY_VISUAL_PACKET_2026-05-12.pptx` - editable 6-page internal calibration packet for judging current surfaces before implementation

The rendering boards are exploratory. They do not establish product truth by
themselves. Implementation work should use current app captures, code-backed
behavior, and the rules in this document before treating any static rendering as
a target.

## 9. First Implementation Slices

The next work is tracked in bd and should land in small pieces:

| bd issue | Slice |
| --- | --- |
| `boulderroller-v2-4kfh` | Portal identity tokens and primary alpha theme |
| `boulderroller-v2-a2l1` | Mobile shared tokens and core primitive migration |
| `boulderroller-v2-gyyg` | Proof/economy primitive grammar |
| `boulderroller-v2-hill` | Brand and copy gate for primary surfaces |
| `boulderroller-v2-gwss` | Design-doc triage so old audits do not outrank this contract |

These slices should not redesign every screen at once. They should create the
rails that make future screen work converge.
