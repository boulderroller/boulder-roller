# Boulder Roller First Traverse and Public Preview Architecture

**Status:** Candidate product engineering spec
**Date:** 2026-06-04
**Updated:** 2026-07-14
**Owner:** Product + frontend + backend + infrastructure
**Tracking:** `boulderroller-v2-s3km`
**Implementation umbrella:** `boulderroller-v2-bcxa`

## Purpose

This spec defines how a new rider or outside viewer first traverses Boulder
Roller:

```text
brand root -> app entry or public app object -> account/invite -> ride upload -> climbs on the route -> time and position -> optional CAL state -> DUNG receipt -> optional BoulderScan proof
```

The goal is to remove ecosystem confusion without flattening Boulder Roller's
real objects. The root site should be clean and expressive. The app should be a
full-page product, not a modal stack. Public app links should act like
buttoned-up viewfinder previews of real Boulder Roller objects, not like a
second logged-out app.

## Source Contracts

This spec sits under:

- `docs/PROTOCOL_TRUTHS.md`
- `docs/design/LANGUAGE_SPEC.md`
- `docs/design/BR_IDENTITY_SYSTEM.md`
- `docs/PORTAL_TRUTHS.md`
- `docs/design/PROOF_ECONOMY_PRIMITIVES.md`
- `docs/design/PRODUCT_PATH_REGISTRY.md`

If this document conflicts with protocol semantics, protocol wins. If it
conflicts with rider-facing copy grammar, the language and proof/economy docs
win.

## Reference Patterns

This spec borrows product posture, not implementation, from:

- Echo: clean public root and full-page account entry
  - `https://echo.xyz/`
  - `https://app.echo.xyz/login`
- Strava: public object links that reveal enough athletic value to invite
  sign-in, while deeper app interaction stays gated
  - activity object pages
  - segment object pages with attached leaderboards
  - route object pages
- Hyperliquid: deeper action gating where account/wallet prompts appear at the
  moment of intent instead of before the user understands the surface

## Decisions

### 1. Canonical Domain Spine

Canonical rider-facing domains:

| Surface | Canonical host | Role |
| --- | --- | --- |
| Public brand root | `boulderroller.xyz` | Public product and brand surface |
| App | `app.boulderroller.xyz` | Authenticated app plus public preview routes |
| Docs | `docs.boulderroller.xyz` | Product and technical docs |
| BoulderScan | `scan.boulderroller.xyz` | Public proof and protocol explorer |
| API | `api.boulderroller.xyz` | Backend API |

Redirect posture:

- `boulderroller.com` redirects into the canonical `.xyz` product world.
- `boulderroller.org` redirects into the canonical `.xyz` product world.
- `docs.boulderroller.org` redirects to `docs.boulderroller.xyz`.
- `api.boulderroller.org` continues to redirect to `api.boulderroller.xyz`.
- Historical grants, archived decks, and old support docs may keep `.org` text
  until they are intentionally refreshed, but new rider paths must not send a
  rider through `.org`.

Rationale: `.xyz` is acceptable as the primary identity if it is the only
identity. The current problem is not the TLD. The current problem is split
brand geography.

### 2. Public Root Is Not The Browsable App

`boulderroller.xyz` should be an Echo-like root:

- first-viewport brand and product signal
- restrained motion
- real product objects as composed visuals
- simple links to app, docs, and BoulderScan
- no protocol-first explanation
- no logged-out app shell
- no public object browsing as the main root-site experience

The root should sell the feeling and direction of Boulder Roller. It should not
try to host climb browsing, ride previews, or leaderboard interactions.

Required root destinations:

- `Log in` or `Sign in` -> `https://app.boulderroller.xyz`
- `Request invite` or `Join alpha` -> app account entry with invite request
- `Read docs` -> `https://docs.boulderroller.xyz`
- `Open BoulderScan` -> `https://scan.boulderroller.xyz`

CTAs must name real destinations or actions. Do not add placeholder hero CTAs.

### 3. Direct App Entry Is Full-Page Auth

When an unauthenticated rider visits `app.boulderroller.xyz` directly, the app
shows a full-page account entry surface. It does not show an auth modal over a
fake app shell.

Auth posture:

1. Account-first entry is primary.
2. Request access is email-based and visible from the entry surface.
3. Invite code entry is inline only for prefilled invite links, explicit
   recovery, admin, or test affordances.
4. Email, passkey, and/or Google-style account entry should be the front door.
5. Embedded rider wallet is created quietly when account entry needs it.
6. Existing Solana wallet is a secondary advanced path.
7. Wallet popups appear only when the rider is signing an action that needs a
   wallet signature.

Auth copy should follow rider-first language:

- Use `Sign in`, `Request access`, `Upload a ride`, `Continue with email`.
- Use `Invite code` only on invite links, recovery, admin, or test paths.
- Do not lead with `Connect wallet` unless the user chose wallet entry or is
  signing a protocol action.
- Do not describe login as proof, attestation, or protocol setup.

### 4. Public Preview Routes Live On The App Domain

Public previews are app-domain object routes that can be served to outsiders
without showing the full authenticated app.

Canonical public preview object routes:

| Object | Canonical route | Notes |
| --- | --- | --- |
| Climb | `/climbs/:climbId` | Primary public object. Includes attached record board. |
| Ride | `/rides/:rideId` | Public only when shareable. `/activities/:rideId` remains compatibility. |
| Rider | `/riders/:identifier` | Public identity preview when privacy allows. |
| BoulderScan proof | `scan.boulderroller.xyz/...` | External proof detail, not portal chrome. |

Non-decisions:

- No top-level `/leaderboards/:id` public object in the first pass.
- No generic logged-out `/leaderboard` as a public destination.
- No new `result` route as the root public share object.
- No `activity` as the primary Boulder Roller noun, even if legacy API and
  compatibility routes still use it.

Rationale: riders think `climb -> record board -> my position`, not
`leaderboard -> maybe climb`. Leaderboards are attached to climbs. The climb is
the object.

### 5. Public Preview Is A Viewfinder, Not A Second App

Public previews should feel alive and product-real, but they should not expose
the whole app service.

Preview rules:

- Show the athletic object first: ride, climb, rider, route, record.
- Then show the consequence layer: CAL counted, position, DUNG receipt, proof
  state.
- Render a composed, buttoned-up preview asset suitable for outside viewers.
- Use app data only through a public-preview contract that already applies
  privacy and display rules.
- Do not hydrate private app machinery for logged-out viewers.
- Do not expose raw GPS, private ride history, private identity, or unreviewed
  projections simply because an indexer row exists.

Interaction rules:

- Object-level viewing may be public.
- Clicks that cross into real app behavior route to full-page account entry.
- Disabled interactions should feel like intentional boundaries, not broken
  controls.
- If a preview looks clickable but is gated, the next screen should preserve
  return intent after sign-in.

### 6. Preview Asset Contract

The preview asset should preserve the impact value of the object. It should not
look like a cropped or weakened teaser.

Climb preview should include, when available:

- climb name and location context
- map or route/elevation shape
- distance, grade, elevation, attempts, or other core stats
- full visible top record board when the board is naturally small, such as top
  10
- current record or best time
- recent movement or participation context
- compact vault/economy strip only after the climb is understood
- `Open in BoulderScan` only when proof detail is present and relevant

Ride preview should include, when public:

- ride title, rider display, date, and privacy-safe state
- route snapshot or media preview
- distance, time, elevation, and effort summary
- matched climbs
- CAL counted or pending state
- proof or receipt status when available

Rider preview should include, when public:

- rider display identity
- records or positions tied to public climbs/rides
- recent public ride/climb context
- public proof links only when relevant

Record board preview rules:

- If the climb's real public board is top 10, show the top 10.
- Do not crop top 10 to top 3 just to create artificial scarcity.
- If there is deeper historical depth, summarize it with context such as
  `87 more riders` instead of exposing infinite rows.
- Rows should look like a real board, not a marketing card pretending to be one.

### 7. Gate Contract

These gates are engineering/security contracts, not decorative UI decisions.

| Intent | Gate |
| --- | --- |
| Visit `app.boulderroller.xyz` unauthenticated | Full-page account entry |
| View public climb preview | Public-preview contract |
| View public ride preview | Public-preview contract and ride privacy |
| View public rider preview | Public-preview contract and rider privacy |
| Upload a ride | Account + invite |
| View private rides | Account |
| View private profile settings | Account |
| Deposit CAL | Account + wallet signature |
| Withdraw CAL | Account + wallet signature |
| Collect DUNG | Account + wallet signature |
| Inspect raw proof detail | BoulderScan route |

The app should preserve return intent after auth:

```text
preview object -> gated action -> full-page auth -> original intended action or object
```

### 8. Auth And Wallet Boundary

Auth identifies the rider for private app surfaces. Wallet signs explicit
actions. The app must keep these separate:

- login session
- embedded wallet
- external wallet
- backend authority

Implementation implications:

- Account-first auth should not use wallet language as the headline.
- Embedded wallet state should be quiet unless an action requires it.
- External wallet connect should remain available for riders who intentionally
  choose it.
- Wallet-signing steps may use focused overlays only for unavoidable external
  wallet handoff; they should not define the whole account flow.
- Recovery states should be full-page or inline wherever possible.

### 9. Modal Posture

Modals are not the app architecture.

Allowed modal-like interruptions:

- destructive confirmation
- narrow one-decision confirmation
- unavoidable browser wallet handoff
- temporary inspection panels where the user stays in context

Not allowed as long-term architecture:

- invite gate as the main app entry
- login as the main app entry
- onboarding as the main app entry
- upload as a default interruption when a full page is available
- recovery/error flows that require stacking dialogs

Modal cleanup should happen after the domain, app entry, and preview contracts
are accepted. Do not polish the old modal system before replacing the first
traverse.

## Required Implementation Slices

### Slice 1: Domain Spine

**Bead:** `boulderroller-v2-ekuh`

Deliver:

- canonical `.xyz` routing map
- `.com` and `.org` redirect plan
- docs host migration plan from `.org` to `.xyz`
- environment/config audit for `.org` and `.com` references
- smoke checks for app, API, docs, scan, and redirects

### Slice 2: Public Root

**Bead:** `boulderroller-v2-d2z4`

Deliver:

- root-site design brief and implementation for `boulderroller.xyz`
- Echo-like restraint and motion without cloning Echo's brand
- real Boulder Roller object visuals: rides, climbs, maps, elevation profiles,
  and leaderboards
- updated root metadata and nav links
- no root-level object browsing

### Slice 3: Full-Page App Entry

**Bead:** `boulderroller-v2-wl66`

Deliver:

- unauthenticated app route shows full-page account entry
- invite is inline and prefillable
- primary account path is email/passkey/Google-style where available
- existing Solana wallet is secondary
- no auth modal as the default direct-app entry
- return-intent handling for gated public preview actions

### Slice 4: Public Preview Routes

**Bead:** `boulderroller-v2-l2nr`

Deliver:

- public-preview route mode for `/climbs/:climbId`
- public-preview route mode for `/rides/:rideId`
- public-preview route mode for `/riders/:identifier`
- compatibility handling for `/activities/:rideId`
- no top-level public `/leaderboards/:id`
- clear split between public preview and authenticated app shell

### Slice 5: Preview Data and Asset Pipeline

**Bead:** `boulderroller-v2-idhy`

Deliver:

- backend/API contract for preview-safe climb data
- backend/API contract for preview-safe ride data
- backend/API contract for preview-safe rider data
- privacy review for raw GPS, rider identity, and private ride leakage
- preview asset/image strategy for maps, route snapshots, and board snapshots
- cache/SEO/Open Graph strategy

### Slice 6: Auth And Wallet Standardization

**Bead:** `boulderroller-v2-5nwj`

Deliver:

- account-first auth copy and states
- quiet embedded wallet creation
- explicit external wallet path
- wallet signature prompts only for signature actions
- auth/session/wallet telemetry aligned to activation metrics
- tests that preserve login session vs wallet-signing distinction

### Slice 7: Modal Demotion

**Bead:** `boulderroller-v2-9veb`
**Hardening bead:** `boulderroller-v2-p0x3`

Deliver:

- inventory of auth, invite, onboarding, upload, setup, and recovery modals
- remove modal-first auth path after full-page entry lands
- move upload/setup/recovery to page or inline flows where appropriate
- keep only intentional modal-like interruptions
- keep the active inventory in `PORTAL_DESIGN_SYSTEM_2026.md`

## Acceptance Criteria

The first traverse is coherent when:

- a new rider knows which domain is real
- direct app entry does not ask them to understand wallet infrastructure first
- public object links feel like Boulder Roller without becoming a second app
- a climb preview reads as `climb -> record board -> position`, not as a
  generic leaderboard page
- a ride preview reads as `ride -> matched climbs -> CAL counted`, not as an
  abstract proof artifact
- wallet signing appears only when the rider is doing something that needs a
  signature
- BoulderScan is available for proof detail but does not become portal chrome
- root-site polish does not leak into app object architecture

## Open Decisions

- Whether passkey should be first-class in the first implementation slice or
  documented as a near-term auth target.
- Whether `boulderroller.com` redirects to `boulderroller.xyz` at the apex or to
  `www.boulderroller.xyz`.
- Whether docs migration should be a hard redirect immediately or a phased
  update with old `.org` docs links preserved temporarily.
- Whether public ride previews require explicit rider opt-in before launch or
  can use existing public/privacy state.
- Whether preview assets are server-rendered HTML, generated images, or a mixed
  model by object type.

## Non-Goals

- Redesigning every portal screen in this spec.
- Replacing BoulderScan.
- Shipping a public fully browseable logged-out app.
- Creating top-level public leaderboard routes before there is a real standalone
  board object.
- Resolving all mobile auth and onboarding surfaces.
- Cleaning every modal before the new first-traverse architecture exists.
