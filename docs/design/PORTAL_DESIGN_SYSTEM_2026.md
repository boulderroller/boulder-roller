# Boulder Roller 2026 Portal Design-System Contract

**Status:** Active portal visual contract
**Date:** 2026-06-09
**Updated:** 2026-09-07 (amended; see
`docs/design/PORTAL_STANDARDS_AMENDMENT_2026-09-07.md` for palette, numerical
absence and route ownership)
**Tracking:** `boulderroller-v2-q7ki`; typography boundary gate
`boulderroller-v2-s9m4j`
**Audience:** Product, design, frontend, QA, future Codex agents

## Purpose

This contract translates the public-root direction into the active portal design
system. It is the bridge between `boulderroller.xyz`, public app previews, app
entry, and the authenticated rider portal.

The goal is not a broad redesign for its own sake. The goal is one coherent
Boulder Roller product world:

```text
public root -> app entry / public preview -> authenticated portal -> BoulderScan
```

Each surface has a different job, but they should no longer look like separate
products stitched together.

## Source Hierarchy

This file sits under the semantic and language contracts:

- `docs/PROTOCOL_TRUTHS.md`
- `docs/design/LANGUAGE_SPEC.md`
- `docs/design/BR_IDENTITY_SYSTEM.md`
- `docs/PORTAL_TRUTHS.md`
- `docs/design/PROOF_ECONOMY_PRIMITIVES.md`
- `docs/design/FIRST_TRAVERSE_PUBLIC_PREVIEW_ARCHITECTURE.md`

If this contract conflicts with protocol meaning, protocol wins. If it
conflicts with rider-facing copy rules, the language and proof/economy docs win.

## Governing Shape

Boulder Roller has one public-facing meta-shape with three states, not three
unrelated page systems. The public root, app entry, and public previews should
feel like siblings before the authenticated portal becomes denser.

| Mode | Surface | Job | Visual posture |
| --- | --- | --- | --- |
| Public root | `boulderroller.xyz` | Brand and product signal | expressive, spare, motion-led |
| Public app edge | app entry and public previews | Let outsiders understand the object before signing in | public-root sibling, controlled viewfinder |
| Authenticated portal | logged-in app | Repeated rider work | denser, quieter, object-first |

The public root can use editorial scale. The authenticated portal cannot. The
portal inherits the same paper, ink, route/elevation, and restrained component
language, but it must remain efficient for repeated scanning and action.

App entry should be the clearest proof of this rule: same paper/ink field, same
spare brand posture, same real route/elevation material, but with the account
task laid into the page instead of introduced as a separate portal-style login
screen.

## First Proofs

These surfaces are the first proof points for this contract:

- Public root: `web/org/src/components/Hero.tsx` and `web/org/src/app/globals.css`
- Full-page app entry: `boulderroller-v2-6l6g`, app-entry/auth redesign
- Public previews: `web/portal/src/pages/PublicPreview.tsx` and
  `docs/design/FIRST_TRAVERSE_PUBLIC_PREVIEW_ARCHITECTURE.md`

Future portal shell and object-page work should cite this file, not the older
current-state audit in `web/portal/DESIGN_SYSTEM_RULES.md`.

## What Carries From Public Root

Carry these public-root traits into app entry, public previews, and the portal:

- Paper background: warm neutral, not beige nostalgia.
- Ink-first text: black or near-black primary reading.
- Low chrome: fewer borders, fewer wrappers, fewer nested panels.
- Real route/elevation material: maps, route lines, elevation strips, record
  boards, and counted CAL are brand material.
- Restrained accents: terrain green, CAL blue, DUNG gold.
- Small square BR mark and literal brand text.
- Motion that reveals route or state, not decorative motion.
- CTAs that name real destinations or actions.

Do not carry public-root hero scale into dashboards, tables, cards, settings, or
deep object pages.

## What Changes Inside The Portal

The authenticated portal is a work surface. It should feel calm, not empty.

Portal pages should be:

- denser than the public root
- object-first before economy
- row/table/list friendly
- stable across reloads and route changes
- mobile-safe without becoming a shrunken desktop table
- clear about loading, pending, redacted, and settled states

The portal should not use oversized hero composition for normal pages. Page
headers should be compact and useful: object name, state, primary action, and
key metadata.

Object pages lead with the object itself and carry no page-level eyebrow.
Profile, Map, My Activities, Climb, Ride, Create Vault, and public-preview
surfaces must not add a decorative category, icon, kicker, or restatement
above the object title. Truth and status signals belong beside the data,
action, or state they qualify; data captions and panel metadata remain.

## Core Tokens

### Palette

Use this palette as the active direction.

| Token | Value | Use |
| --- | --- | --- |
| `paper` | `#f4f5f2` | public root, app entry, preview background |
| `paperSoft` | `#eceee8` | subtle bands and inactive surfaces |
| `ink` | `#0e1110` | primary text, primary buttons |
| `inkSoft` | `#323b37` | secondary emphasis |
| `inkMuted` | `#68716d` | metadata, nav, inactive text |
| `inkFaint` | `#8b9490` | placeholders and tertiary labels |
| `line` | `#d9ddd5` | dividers and quiet borders |
| `terrain` | `#177865` | route/topo/confirmed state |
| `cal` | `#1687d9` | CAL values and counted CAL highlights |
| `dung` | `#d6a629` | DUNG and settlement highlights |

Status colors must be quiet. Warning and destructive states can be stronger, but
they should not become the page palette.

Avoid:

- olive/brown dominance
- fantasy tavern warmth
- purple-blue crypto gradients
- one-note dark slate dashboards
- glowing economy cards as the default
- old 2008/social-dashboard chrome

### Typography

Target typeface:

- Geist Sans for product UI and editorial display.
- Geist Mono for numbers, ranks, times, balances, addresses, and hashes.

If a current surface still uses Inter or Cousine, treat that as migration debt
unless the implementation slice explicitly keeps it as a temporary fallback.

Product UI type is role-based and fixed. Do not fluid-scale controls, tables,
tabs, feed rows, labels, chips, or object-page modules.

| Role | Desktop target | Mobile target | Notes |
| --- | --- | --- | --- |
| Brand display | 88-112px | 44-56px | public root and app entry only |
| Page title | 36-44px | 28-34px | object pages and section starts |
| Module title | 22-28px | 20-24px | panels, cards, object modules |
| Body | 15-17px | 15-16px | readable prose and helper copy |
| Label | 12px / 16px | 12px / 16px | metadata, status, form labels, table/map/chart labels |
| Data | 12-15px mono | 12-14px mono | ranks, times, CAL, DUNG, balances |

Letter spacing should be `0` unless a legacy surface is being left untouched.
Do not make the whole screen feel like a terminal.

#### Portal typography migration boundary

`boulderroller-v2-s9m4j` is the decision gate for this boundary. The family
roles below are already approved:

- Geist Sans owns product UI, navigation, controls, body copy, labels, and
  headings.
- Geist Mono owns numeric and technical data: ranks, times, distances,
  balances, CAL, DUNG, addresses, hashes, and aligned table values.
- Ride's current sans-numeric overview treatment is the sole sanctioned
  exception. It does not extend to climb tables, ranks, technical disclosure,
  or any other route.
- Inter and Cousine are migration debt and temporary fallbacks, not approved
  final roles.

Tim ratified the remaining values below on 2026-07-28 as the boundary for later
implementation work:

| Rule | Ratified boundary |
| --- | --- |
| Label floor | 12px on desktop and mobile |
| Label line height | 16px; do not use line-height `1` for small text |
| Product UI weights | 400, 500, 600, and 700 only |
| Editorial weights | 800 or 900 only for public-root/app-entry display moments |
| Mono weights | 400, 500, 600, and 700 only |
| Micro-weights | 430, 440, 460, 520, 560, 620, 650, 720, 750, 760, 780, 820, 840, 850, 860, 870, and similar values are forbidden |
| Synthesis | Do not rely on synthesized weight or style to create hierarchy |
| Casing and tracking | Authored casing, `text-transform: none`, and `letter-spacing: 0`; preserve literal acronyms, units, and proper names |

No app-authored rider-visible portal text may render below 12px, including at
exact 390px. The floor includes status text, truth pills, form labels, table
headers, data captions, app-authored map controls and legends, chart axes,
ticks, and tooltip labels. Third-party basemap tile lettering is outside this
token because the app cannot style it. If a dense surface cannot fit at 12px,
shorten the label, change the layout, or expose detail on interaction.
Do not solve fit by shrinking the text.

A label does not become Mono merely because it captions a number. Only the
numeric value or technical identifier receives Geist Mono and tabular
numerals. State words such as `Waiting`, `Private`, and `Not counted` remain
Geist Sans.

Body copy uses 400/500, labels use 500 by default and 600 only for selected or
important state, headings use 600/700, and numeric values use 400/500/600 with
700 reserved for a primary total or record.

The Ride exception is family-only and local: the existing primary Ride
overview summary values may remain Geist Sans at their current display scale
with tabular numerals. The exception creates no reusable sans-data token and
does not cover Ride analysis charts, climb tables, leaderboard or rank rows,
CAL/DUNG/balance/receipt data, or technical identifiers. Expanding or removing
the exception requires Tim's ratification.

The canonical public variables are:

```css
--br-font-sans
--br-font-mono
```

During migration, the mounted cascade may temporarily map these existing
aliases to the canonical pair. An alias is a bridge, not proof that its
consuming component has migrated:

| Sans aliases | Mono aliases |
| --- | --- |
| `--portal-font-sans` | `--portal-font-mono` |
| `--access-font` | `--access-mono` |
| `--public-preview-font` | `--public-preview-mono` |
| `--font-sans` | `--font-mono` |

Tailwind's generated `--default-font-family` and
`--default-mono-font-family` remain derived from the `--font-*` framework
bridge. They are implementation internals, not product-facing tokens, and
sunset only with a deliberate Tailwind/base replacement.

Do not import `styles/globals.css` wholesale as a typography fix. It is not in
the runtime entry cascade and contains unrelated base rules. A future
foundation slice must define the canonical pair and compatibility mappings in
the mounted cascade deliberately.

No new selector, utility, or component may name Inter or Cousine first. When an
implementation bead touches a typography rule, that rule migrates to the
canonical role token in the same bead. A new family, product weight outside
400/500/600/700, sub-12px text, authenticated-portal fluid type, or expansion
of the Ride exception is `Tim-ratifies`.

Inter and Cousine may remain in the font request only while active
repo-authored selectors still name them. Sunset them together after all of
these are true:

1. Active runtime CSS and TSX contain no literal Inter or Cousine family
   declarations outside explicit migration tests or archived evidence.
2. Surface-local aliases consume only `--br-font-sans` or `--br-font-mono`.
3. Every migration slice has approved desktop and exact-390 evidence, including
   cold-cache fallback behavior and no text-driven overflow.
4. `web/portal/DESIGN_SYSTEM_RULES.md` is clearly retained as historical
   current-state evidence or updated so it no longer instructs agents to add
   Inter/Cousine.

Migration is sequenced, not swept:

1. **Foundation only:** define `--br-*` synchronously in the mounted cascade,
   bridge framework and surface aliases, align the requested font weights, and
   add a no-new-debt check. Do not migrate selectors in this slice.
2. **Entry and public preview:** migrate only `.access-*` and
   `.public-preview-*`, then remove their four local aliases.
3. **Shared shell and non-Ride UI:** migrate shell and shared primitives while
   excluding Ride, Admin, maps, and charts.
4. **Ride surfaces:** migrate `.ride-*`, `.ride-detail-*`, and
   `components/ride/**` while preserving the bounded sans-numeric overview
   exception.
5. **Admin, maps, and charts:** migrate Admin, app-authored map controls,
   Leaflet container boundaries, and inline/canvas chart styles.
6. **Cleanup:** remove compatibility aliases, stale compiled utilities and
   guidance, then stop requesting Inter/Cousine only after direct legacy
   first-family usage reaches zero and font-blocked fallback behavior passes.

The `s9m4j` packet ratifies this boundary only. It opens no implementation child
and changes no rider-visible code. Future children must have disjoint surface
ownership, observe the two-live-lanes cap, and carry their own desktop/exact-390,
200% resize, 320px-equivalent reflow, text-spacing, and font-blocked evidence
gates. Implementation mechanics can be agent-autonomous; Tim still approves
each rider-visible result. Ratifying this boundary does not claim that
portal-wide typography is already consistent.

### Spacing

Use an 8px rhythm with 4px only for tight inline adjustments.

| Use | Desktop | Mobile |
| --- | --- | --- |
| Page gutter | 40-56px | 16px |
| Major section gap | 40-64px | 24-32px |
| Object module gap | 20-32px | 16-24px |
| Row gap | 8-14px | 8-12px |
| Control height | 40-48px | 42-48px |

Dense does not mean cramped. Keep scan lines stable and avoid accidental
wrapping in controls.

### Radius And Shadow

Use controlled radius, not the old global zero-radius posture.

- Buttons, inputs, chips, and cards: 6-8px.
- Repeated object cards: 8px max.
- Avatars: circular when representing people.
- Page sections: do not turn whole sections into floating cards.

Shadow should be rare and soft. Use dividers and spacing before elevation.
Public root and app entry may use a soft paper-glass panel. Authenticated portal
pages should use lower elevation.

## Components

### Containers And Cards

Cards are for repeated objects, modals, and genuinely framed tools. Do not put
cards inside cards. Do not make every page section a floating card.

Preferred authenticated portal containers:

- rows
- tables
- lists
- maps
- elevation modules
- side panels
- object modules with a single quiet border

Use cards only when the user is comparing repeated rides, climbs, riders,
positions, receipts, or settings groups.

### Buttons And Inputs

Primary buttons:

- ink background
- paper text
- 6px radius
- icon when the action has a familiar symbol

Secondary buttons:

- transparent background
- line border
- ink text

Destructive buttons should be explicit but not oversized. Text-only actions are
for low-risk secondary navigation or footer utilities.

Inputs should belong to the paper system. They should not inherit old dark or
olive portal fills on public-root-adjacent surfaces.

### Tabs And Segmented Controls

Use tabs for changing views. Use segmented controls for mutually exclusive
modes. Use toggles or checkboxes for binary settings.

Avoid filled-pill tab bars across dense portal pages. Active state should prefer
text weight, underline, a quiet line, or a restrained selected background.

### Tables And Rows

Tables are a strength of the portal. They should be readable and compact.

Rules:

- Rank, time, distance, grade, CAL, DUNG, and balance columns may use mono.
- Names must truncate gracefully.
- Header labels stay short.
- Superseded 2026-09-07 by the Numerical Display Contract: a missing number
  has no glyph in its slot; state words go in an associated status area.
  Former rule: Empty cells should use `--`, `Waiting`, `Private`, or `Not counted` depending
  on the true state.
- Tables should not turn into card stacks on desktop.
- Mobile can switch to row modules when the table no longer scans.

### Maps And Elevation

Maps and elevation are first-class Boulder Roller material.

Use stable aspect ratios:

- feed map previews: square or compact landscape
- ride detail maps: large landscape, route legible
- climb cards: compact route/elevation shape
- climb detail: map/elevation near the top of the object page

Unavailable route states must feel designed:

- `Route GPS private`
- `Route preview unavailable`
- `Checking ride`

Do not show a blank gray box as the final state. Do not use decorative topo
wallpaper where a real route or elevation object should exist.

## Surface Contracts

### Public Root

The public root is not the browseable app.

It should contain:

- Boulder Roller as the first-viewport signal
- concise product copy
- real product visuals
- simple links to app, docs, and BoulderScan
- enough next-section visibility to imply depth

It should not host public object browsing or authenticated portal chrome.

### App Entry

App entry is a full-page account surface and a public-root sibling.

Rules:

- Reuse the public-root meta-shape: brand and entry copy on one side, real
  route/elevation or record material on the other, with low chrome.
- Email-first account entry.
- Request access happens by email.
- Invite-code entry is not the default visible path.
- Returning wallet is secondary.
- Wallet language stays secondary unless the rider chose wallet entry.
- Do not use gas, transaction, signature, explorer, or proof language in the
  primary account-entry copy.

### Public Previews

Public previews are app-domain object viewfinders, not a second app shell.

They should show:

- the athletic object first
- route, elevation, stats, record board, or public ride/rider context
- consequence state only after the object is understood
- a sign-in boundary that preserves return intent

Climb previews attach the Record Board to the climb. Do not create a top-level
public leaderboard product. If a real top-10 board exists, show the full top 10
rather than cropping it to top 3.

### Authenticated Shell

The shell should feel like the same product after login.

Rules:

- Navigation is quiet and predictable.
- The active section is visible without heavy fills.
- Loading, empty, stale, private, and pending states share one grammar.
- The shell does not compete with ride, climb, rider, and portfolio objects.
- Mobile navigation must not hide primary rider paths.

### Ride Pages

Ride pages start with the ride:

1. title, rider, date, privacy/state
2. map
3. stats and elevation
4. matched climbs
5. counted CAL and record/status consequence
6. receipt/proof links only when relevant

Do not make BoulderScan or proof internals the hero.

### Climb Pages

Climb pages start with the climb:

1. climb name and place context
2. route/elevation
3. best result and Record Board/leaderboard
4. rider relationship
5. legend/vault/economy strip
6. deeper vault or BoulderScan detail

Vault economics must attach to the climb instead of becoming a generic finance
panel.

### Rider Pages

Rider pages start with rider identity and public activity history.

Settings/setup/completeness states belong only in owner context. Public rider
pages should not feel like account settings.

### Portfolio

Portfolio can be economy-forward, but it remains object-backed.

Use:

- Boulder Roller Balance
- climbs/vaults tied to positions
- counted CAL
- pending/ready/collected DUNG
- receipts and withdrawals

Avoid generic wallet dashboards, price-chart-first composition, and crypto-first
copy.

### BoulderScan Links

BoulderScan is a destination, not portal chrome.

Portal can link to:

- receipt detail
- proof detail
- transaction or account detail in advanced contexts

Portal should not duplicate BoulderScan's raw protocol explorer UI.

## Modal Policy

Modals are rare. The active system rejects over-modal patterns.

Allowed:

- destructive confirmation
- one-decision confirmation
- unavoidable external wallet handoff
- temporary inspection panel where the user keeps context

Prefer:

- full pages
- inline states
- drawers
- side panels
- route-level recovery screens

Do not use modal stacks for app entry, login, invite, onboarding, upload, setup,
or recovery when a page or inline state can carry the flow.

### Modal Classification Inventory

This inventory is the active portal policy. New modal-like surfaces must be
classified here before they land.

| Surface | Classification | Rule |
| --- | --- | --- |
| App entry, login, invite, and waitlist | Delete as modal path | Full-page app entry only. No auth dialog over a preview shell. |
| First-run onboarding setup | Demote | Full-page setup surface only. No centered setup dialog. |
| Missing FTP/weight reprompt | Demote | Inline app reminder that links to Settings performance inputs. |
| Session expired or offline recovery | Demote | Full-page recovery surface. No alertdialog stack over the app. |
| Upload ride | Keep as sheet | The Search sheet's geometry, opened over the current room; /upload opens it over returnTo. |
| Search | Keep | Temporary inspection utility where the rider keeps context. |
| Notifications popover | Keep | Temporary inspection panel tied to the shell. |
| Settings delete account, disconnect wallet, revoke sessions | Keep | Destructive or security-sensitive confirmation. One decision only. |
| Settings avatar crop | Keep | Focused editor panel for an asset the rider is actively changing. |
| Ride delete confirmation | Keep | Destructive confirmation. |
| Ride photo lightbox | Keep | Temporary inspection panel for media. |
| Vault creation and vault creation success | Keep for now | Economy creation flow with unavoidable wallet/protocol handoff risk; must move toward inline/detail-route presentation as the gasless design settles. |
| Share, achievement, edit activity, invite friend, climb detail, store confirm components | Delete if still unused | Not active route/shell imports in the 2026 portal pass; do not reintroduce as first-traverse defaults. |
| Old InviteModal and RideUploadSuccessModal stylesheet blocks | Link to cleanup | Already tracked by `boulderroller-v2-l93b`; prune there without touching active InviteFriend or upload-page styles. |

## Copy And State Language

Use literal rider terms:

- `Record rides`
- `Upload a ride`
- `Matched climbs`
- `Browse climbs`
- `Counted CAL`
- `My position`
- `Deposit CAL`
- `Withdraw CAL`
- `Collect DUNG`
- `DUNG receipt`
- `Open in BoulderScan`

Avoid primary-surface terms:

- `gas`
- `transaction`
- `signature`
- `explorer`
- `yield`
- `harvest`
- `stake to farm`
- generic `proof` when the rider is looking at a ride, receipt, or status

Advanced/support/admin surfaces may use precise chain terminology, but they must
start from the rider object when possible.

## Mobile Rhythm

Mobile is not a compressed desktop portal.

Rules:

- Single-column by default.
- Object identity first.
- Primary action visible without crowding the header.
- Maps and elevation keep stable aspect ratios.
- Tables become readable row modules when columns no longer fit.
- Footer utilities stay secondary.
- Route, board, and economy details stack in the same order as desktop object
  hierarchy.

Do not hide essential rider paths behind decorative mobile chrome.

## Implementation Rules

When modernizing portal surfaces:

1. Name the object layer first: ride, climb, rider, route, position, receipt.
2. Place BR consequence second: CAL, DUNG, vault, settlement, proof link.
3. Use the core token direction before inventing new colors.
4. Use existing behavior primitives and only change styling/structure needed for
   the bead.
5. Keep density appropriate for repeated app use.
6. Verify desktop and mobile screenshots for any rendered surface change.
7. Run the quality gate matching the files changed.

## Review Checklist

Use this checklist before approving a portal modernization slice:

- Does the screen feel like a cycling app before it feels like an economy app?
- Is the first object a ride, climb, rider, route, position, or receipt?
- Is the public-root system present without turning the portal into a hero page?
- Are maps, elevation, leaderboards, tables, and stats doing real work?
- Are cards used only for repeated objects or framed tools?
- Is there any nested-card or social-dashboard clutter?
- Did we avoid old 2008-style portal chrome?
- Does mobile preserve object hierarchy without horizontal overflow?
- Are modals rare and justified?
- Did primary copy avoid gas, transaction, signature, explorer, yield, and
  harvest language?
- Can future shell/object-page work cite this file for a concrete rule?
