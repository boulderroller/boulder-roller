# Boulder Roller Canonical Portal Truths

**Status:** ACTIVE AS AMENDED (2026-09-07)  
**Date:** 2026-04-28  
**Updated:** 2026-09-07
**Audience:** Founding, product, portal, frontend  
**Purpose:** Semantic source of truth for Boulder Roller's web portal, bringing it into coherence with PROTOCOL_TRUTHS.

This document sits **under** [PROTOCOL_TRUTHS](./PROTOCOL_TRUTHS.md) and
**alongside** [MOBILE_TRUTHS](./MOBILE_TRUTHS.md) and
[BACKEND_TRUTHS](./BACKEND_TRUTHS.md).

When portal work conflicts with protocol truth, protocol wins. This document
defines what must remain true in the rider's browser surface.

---

## 1. North Star

The portal is the rider's **reading surface**.

Its job is to let riders, curators, and spectators browse protocol state:
rides, climbs, leaderboards, vault economics, wallets, and social context. It
can make chain state visible, but it is not authoritative over chain truth.

The portal is not the ride recorder. It is not the backend attester. It is not
the protocol. It is the high-context browser for what the protocol already
knows or is still processing.

---

## 2. Core Objects

### 2.1 Feed

The **Feed** is recent projected activity. It is a browsing layer, not settled
truth. It may combine indexed events, backend projections, and social metadata.

### 2.2 Ride Page

A **Ride Page** presents the ride: route, metrics, climbs crossed, status, CAL,
and links to optional verification detail.

### 2.3 Climb Page

A **Climb Page** is the primary geographic detail page. It shows the climb,
leaderboard, recent activity, and attached economics when a vault exists.

### 2.4 Vault Section

A **Vault Section** is the economic module attached to a Climb Page. It may show
deposits, settlement state, carry, the Leaderboard, Local Legend, and
participation economics. It is not a standalone room and must not imply that
the Vault is the Climb itself.

### 2.5 Wallet Surface

The **Wallet Surface** lets a rider connect identity and sign explicit actions.
It is a signer and balance surface, not ride truth.

### 2.6 Leaderboard

The **Leaderboard** is the rider-facing view of a Climb's all-time top 10. Its
chain-canonical source is the Record Board; it is not a recent social ranking.

On detailed rider surfaces, every seated rider tied at the fastest validated
whole-second time is shown as a co-KOM with a crown and `T-1`. The portal must
derive that set from the authoritative Leaderboard rows and their
`competition_rank`, not from singular `kom_holder` alone. Standard competition
ranks, the ten-seat cutoff, and pooled payouts remain unchanged; `kom_holder`
is only a deterministic legacy representative and must not be presented as the
sole sporting winner.

---

## 3. Three Read Layers

The portal reads three layers:

- **On-chain via RPC:** authoritative account state and transaction results.
- **Attested via backend API:** ride-processing and attestation state.
- **Projected via indexer:** fast read models for pages, feeds, and search.

The portal may compose these layers visually, but it must keep their meanings
distinct.

---

## 4. Writes

The portal does not write truth by itself.

Any write is one of:
- backend-attested action
- wallet-signed on-chain transaction
- local UI preference with no protocol meaning

If a portal action changes economics or protocol state, the user must know
which signer or authority is responsible.

---

## 5. Portal Roles

### 5.1 Rider

The **Rider** reads their rides, climbs, wallet, and protocol standing.

### 5.2 Curator

The **Curator** explores climb and vault surfaces, stewardship, and local
protocol activity.

### 5.3 Spectator

The **Spectator** can browse public truth without owning the underlying ride or
wallet.

---

## 6. Projection Boundary

Portal projections are caches.

They can be stale, missing, or temporarily inconsistent while the indexer
catches up. Portal UI should explain pending state without fabricating finality.

The portal never derives settlement math, Local Legend eligibility, or Record
Board authority from client-only computation.

---

## 7. Navigation

Canonical portal navigation is:

- `/climbs` for map-led Climb discovery
- `/climbs?hasVault=true` for Climb discovery filtered to attached Vaults
- `/climbs/:climbId` for Climb pages
- `/rides/:rideId` for Ride pages (canonical since the 2026-09-07 amendment;
  `/activities/:rideId` is a compatibility alias resolving the same Ride)
- `/profile` and `/athletes/:identifier` for rider identity surfaces
- `/notifications` for the rider's own push ledger (one chronological log of
  leaderboard moves, settlements, ride outcomes, and rider activity; each row
  deep-links to its surface). The alert switches live on the Settings rail at
  `/settings?tab=alerts`, not on the ledger.
- `/docs` for the Guide: the public docs' table of contents, each row opening
  its page on docs.boulderroller.xyz. The Portal carries no explanatory prose
  of its own; the docs site is the prose.

Legacy `/segments/:climbId` is a compatibility alias only. New portal work must
link to `/climbs/:climbId`.

The former top-level `/map` surface is also compatibility-only. It redirects to
`/climbs` while preserving the rider's query and fragment. Climb discovery owns
the governing map and its `With vaults` filter owns Vault discovery. Legacy
`/vaults` redirects to that filter; legacy `/vaults/:vaultId` resolves the
Vault's canonical Climb and redirects to `/climbs/:climbId`.

### 7.1 Location Search Provider Boundary

Launch public-place search may use public OpenStreetMap Nominatim only through
an authenticated Boulder Roller-controlled backend endpoint. Search is
triggered by an explicit rider submission, never by typing or client-side
autocomplete. The backend caches repeated queries, keeps aggregate upstream
traffic at or below one request per second, identifies Boulder Roller to the
provider, and keeps the upstream URL in server configuration so it can change
without a portal update.

The Portal displays OpenStreetMap attribution beside location results and
shows a literal unavailable state when the provider cannot answer. It labels
the search as public-place lookup and never invites confidential or personal
material as search text. Provider failure does not disable map movement or
`Search this area`.

Privacy-zone locations never use public Nominatim. A rider chooses that point
from their device location or enters coordinates, and the Portal sends it only
to Boulder Roller to define the private area.

---

## 8. Naming

Portal naming is fitness-first and protocol-aligned:

- **Climb** for the primary geography object
- **Vault** only for the attached economic module
- **Leaderboard** for the rider-facing all-time top 10
- **Record Board** only for chain-canonical or technical detail
- **Settlement Week** for economic finality cadence
- **Local Legend** for rolling stewardship

Avoid `segment` as a canonical product noun. It may appear in historical docs,
compatibility comments, file-format language, or geometry/chart internals where
it means a generic line segment rather than the protocol object.

For `/climbs`, visible browsing language is:

- primary navigation word: `Map` (the room is the city map; the index
  inside it is titled `Climbs`)
- page title: `Climbs`
- browse section: `Browse climbs`
- all tab: `All climbs`
- vault filter: `With vaults`
- rider tab: `My positions`
- search: `Search climbs`
- card action: `Open climb`

Vault language belongs on explicit deposit/withdraw/collect actions or inside
the attached economy strip and Vault section for a climb. Do not let vault
economics become the primary label for geography browsing.

---

## 9. Privacy

Portal privacy follows endpoint zones from MOBILE_TRUTHS §9.3:

- public browsing surfaces may show public rides, climbs, leaderboards, and
  public rider identity
- private rider surfaces require authenticated access
- local-only/mobile capture data is not a portal entitlement

The portal should not expose private route or identity data merely because an
indexer projection exists.

### 9.1 Ride Audience And Map Visibility Are Separate

The launch privacy model follows the familiar Strava control shape without
delegating Boulder Roller privacy to Strava:

- **Who can see this ride?** uses `Everyone`, `Followers`, and `Only you` in
  rider copy. The stored compatibility values remain `public`, `followers`,
  and `private`.
- **Map visibility** is a separate choice: show the full map, hide the first
  and last part, or hide the entire map. The stored values are `show_all`,
  `hide_start_end`, and `hide_entire`.
- A new account defaults future rides to `Everyone` and hides the first and
  last 200 meters of the map.
- Account defaults apply only to rides created after the change. They do not
  retroactively rewrite existing rides.
- File upload and provider import show the current defaults before submission
  and allow an explicit per-ride override. The same controls remain available
  when the rider later edits that ride.

The owner can always see the full retained route. Other viewers receive only
the server-produced projection after endpoint hiding, map visibility, and any
saved privacy zones have been applied. `Everyone` does not mean unredacted
GPS.

Only `Everyone` rides may appear on public climb leaderboards. `Followers` and
`Only you` rides remain visible to their owner, including their private climb
results, but do not contribute public entries. A climb effort whose measured
span falls inside a hidden part of an otherwise public route is also excluded
from the public leaderboard. The public view does not close up the gap: any
surviving entries retain their original chain positions, and a hidden winner
does not promote another rider or create a substitute KOM. A withheld KOM has
no public holder or time; the Portal renders that as waiting or unavailable,
never as a zero-second result.

Provider privacy does not transfer into Boulder Roller. In particular, a
Strava import uses the Boulder Roller audience and map choices displayed at
import time; the Portal states this before submission. Boulder Roller never
assumes that a route hidden in another service arrived with equivalent privacy
metadata.

### 9.2 Privacy Availability Fails Closed

The Portal must load the authenticated privacy contract before enabling file
upload or provider import. The pre-submit surface states:

- the selected ride audience
- the selected map visibility and endpoint distance
- whether saved privacy zones will also be applied

If defaults, zone status, or the server privacy contract are unavailable, the
Portal presents a blocking `Privacy settings unavailable` state. It does not
substitute `Everyone`, an empty zone list, or another final-looking fallback.
Provider unavailability is a separate honest state and does not disable file
upload.

Viewer identity is also a privacy boundary. Logging out, expiring a session,
or changing accounts clears all viewer-scoped query state before the next
viewer can render. Public previews revalidate whenever they are entered or
regain focus and retain no previous route as placeholder data; this mirrors the
server's no-store contract after a privacy edit. Saving an unrelated account
setting does not resend profile visibility unless the rider intentionally
changed that control.

---

## 10. Loading And Pending State

Pending is a first-class state.

Portal pages must distinguish:
- loading
- stale projection
- backend still processing
- on-chain transaction submitted but not indexed
- final settled result

Do not label projected state as final until the relevant authoritative layer
says it is final.

---

## 10.1 Boulder Roller Balance State Language

For normal rider flows, the portal presents Boulder Roller Balance before
chain plumbing.

Primary portal surfaces use:

- `Boulder Roller Balance`
- `CAL counted`, `DUNG ready`, `DUNG collected`
- `Deposit CAL`, `Withdraw CAL`, `Create Vault`, `Pay with USDC`
- `Add funds`, `Withdraw to wallet`
- `Pending`, `Delayed`, and `Needs review`

On a Vault position, `Withdraw CAL` is a full-position action. The Portal sends
`withdraw_all: true` and lets the backend resolve exact on-chain LP base units;
it does not convert `lpTokens` or `lpTokensBaseUnits` to a JavaScript number.
Programmatic partial withdrawal remains an exact base-unit API path, not a
rounded rider-facing input.

Primary portal surfaces do not lead with:

- gas, fee-payer, transaction, tx, signature, explorer, or raw BoulderScan copy
- harvest or unstake as action labels
- proof as the main event when the rider is looking at a ride, climb, position,
  or Balance state

### 10.2 Create Vault Starts From The Climb

Vault creation is available only from an exact reviewed Climb revision. The
Climbs page is the picker; a Climb page may show one `Create Vault` action in
its attached economy strip only when the backend reports that revision as
available and no Vault is attached.

The rider chooses only an offered payment method. The portal sends the exact
Climb row ID and an idempotency key. It does not send or let the rider edit the
Climb name, route metrics, version, signature, or canon commitment. Reserved,
active, stale, historical, and unavailable revisions do not show the action.
Raw commitment and PDA fields remain proof/debug detail rather than primary
rider copy.

Those technical words remain valid in BoulderScan, admin/support, detailed
disclosure, and backend-facing diagnostics. App entry and first-traverse
surfaces must not imply a wallet prompt is required before the rider has crossed
an explicit app-boundary action.

Portfolio custody labels are an explicit exception because the distinction is
the product fact: `Wallet CAL` and `Wallet DUNG` are wallet-held amounts, while
the `Boulder Roller Balance` asset rows are Balance-held amounts. Wallet CAL
and DUNG come from rider token accounts. Balance CAL, USDC, and DUNG come from
their mint-scoped RiderBalance token PDAs, and Balance lifecycle state comes
from the RiderBalance header PDA. The portal never infers that header from the
presence of a wallet, copies one custody amount into another, or uses mint
history as a balance. A missing account is shown as setup work; an unavailable
chain read shows no number and a `Delayed` state beside the row, never zero
(amended 2026-09-07; the former `--` glyph is retired). Current Collect DUNG
confirmation says the DUNG was received in the wallet because that is the
instruction's actual destination.

---

## 11. Wallet And Auth

Auth identifies the user for private portal surfaces. Wallet connection signs
transactions.

The portal must not blur:
- login session
- embedded wallet
- external wallet
- backend authority

Each has different authority.

---

## 12. BoulderScan Boundary

BoulderScan is the protocol explorer. The portal is the rider/browser app.

The portal may deep-link to BoulderScan for proof inspection, transaction
history, and explorer-grade detail. It should not duplicate BoulderScan's role
as the neutral public audit surface.

---

## 13. Alignment Implications

Preserve:
- Climb-first pages and links
- `/segments/:id` only as compatibility
- wallet-signed writes for protocol actions
- backend/indexer/RPC read-layer distinction

Repair:
- active portal copy that still says Segments for the protocol object
- vault-first links where the user is browsing geography
- UI that presents projections as settled truth

Demote:
- historical Strava-style segment language
- mock social surfaces that imply protocol authority

Prepare:
- PORTAL_GATE_1 smoke checks for Climb-first navigation and read-layer copy
- eventual retirement of `/segments/:id` once deployed clients no longer need it

---

## 14. Ratification

**ACTIVE AS AMENDED.** Adopted by Tim on 2026-09-07 through
`docs/design/PORTAL_STANDARDS_AMENDMENT_2026-09-07.md`, which resolves this
document's conflicts with the design-system contract and the language spec
(palette, numerical absence, route ownership, status). Where that amendment
names a rule here as superseded, the amendment controls; otherwise this
document stands as written. PROTOCOL_TRUTHS remains superior. Implementation
gaps are recorded in `history/portal-audit-2026-09-07/`, not here.
