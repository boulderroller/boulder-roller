# Boulder Roller Canonical Protocol Truths

**Status:** ACTIVE  
**Date:** 2026-04-15  
**Amended:** 2026-10-13 - hill bonding: 6–13 Oct ratifications, prospective supersession and CAL-vault liability cutover in §16; 2026-09-01 - forward-only measured Climb-TSS Vault tribute ratified by Tim; 2026-08-30 - Option-A derived Threshold monotone closure and held-ride release contract ratified by Tim; 2026-08-24 - account deletion anonymization and retained-authority contract ratified by Tim; 2026-07-21 - co-KOM sporting recognition and deterministic legacy `kom_holder` representation ratified by Tim; bounded per-candidate canon capture tolerance, record continuity, and repeat-ride boundary-agreement metric ratified by Tim; 2026-07-17 - rider-scoped authority for Balance-funded Vault value actions ratified by Tim; 2026-07-16 - exact program-version compatibility gate; canonical SPL DUNG supply authority and protocol-burn accounting; historical fixed 10% power-weighted CAL tribute policy and visible Leaderboard vocabulary ratified by Tim; 2026-07-14 - completion evidence V2 binds exact tribute; 2026-07-13 - settlement clock, staker remainder, and DUNG tail policy ratified by Tim
**Audience:** Founding, product, protocol, backend, indexer  
**Purpose:** Semantic source of truth for Boulder Roller protocol design and alignment work

This document defines the canonical meanings of Boulder Roller's core objects,
roles, clocks, and system boundaries.

It sits above:
- [TRUTH_CONTRACT_V1](./TRUTH_CONTRACT_V1.md) for low-level detector and economic invariants
- [FRESHEST_SPEC](./FRESHEST_SPEC.md) for current live implementation details
- [PROTOCOL_ALIGNMENT_FIX_PLAN](./design/PROTOCOL_ALIGNMENT_FIX_PLAN.md) for execution sequencing

If the implementation or alignment plan conflicts with this document, this
document wins on semantics and the implementation must be brought back into
coherence.

> **Scope of the 13 Oct amendment:** [§16](#16-hill-bonding) states the
> prospective hill-bonding rules with dated sources. When this amendment was
> written the devnet program was the CAL-vault model ([CHECKLIST item 1][HB-READY];
> [authorities brief][HB-BRIEF]). **Since 18 Oct 2026 the devnet program is the
> stage-1 build (program version 77), for rehearsal only; production keeps
> stage 1 off for riders.** Earlier
> economics remain readable for history and existing liabilities. Their
> supersession applies only through the explicit future cutover in §16.8.

---

## 1. North Star

Boulder Roller exists to create **on-chain economic truth for cycling
geography**.

The protocol is climb-first. It turns real hills into permanent, shared,
cryptographically legible community assets.

The product is not "Strava with tokens." The product is:
- permanent geographic records
- rolling stewardship over living places
- open capital participation without confusing capital for effort
- settlement of economic claims on-chain

---

## 2. Core Objects

### 2.1 Climb

The primary protocol object is the **Climb**.

A Climb is:
- a permanent geographic object
- a canonical identity for a real hill
- the base surface on which records, stewardship, and economics attach

For now, Boulder Roller is explicitly **climb-first**.

Broader asset graph types remain on the roadmap:
- Route
- Zone
- Arena
- Event
- Season

### 2.2 Vault

A **Vault** is not the climb itself.

A Vault is:
- an optional economic module attached to a Climb
- the container for reward distribution, staking configuration, and economic state
- the surface through which a climb accrues and distributes value

The Climb is primary. The Vault is attached.

### 2.3 Ride Attestation

The protocol must eventually treat ride truth as a first-class object.

A ride attestation is the verifiable protocol commitment that:
- a ride happened
- it was interpreted under a specific attestation/parsing version
- it generated specific economic consequences exactly once

This document treats ride attestation as canonical protocol direction even where
current implementation is incomplete.

---

## 3. Three Temporal Truths

Boulder Roller has three kinds of truth over time.

### 3.1 Permanent Truth

These truths persist until directly dethroned or superseded:
- Climb identity
- canon Climb geometry and gates (per canon version)
- founder provenance
- KOM / co-KOM all-time fastest record
- all-time top 10 record board
- lifetime CAL committed to a climb
- rider lifetime soul / effort identity

### 3.2 Rolling Truth

These truths reflect recent activity and may go dormant:
- Local Legend
- recent attempt count
- recent activity heat
- recent rivalries and participation
- time-filtered heatmaps
- provisional social views

### 3.3 Settled Truth

These truths are finalized on a settlement cadence:
- DUNG distributions
- staker entitlements
- Record Royalty payouts
- Local Legend payouts
- treasury and POL allocations
- carry balances

---

## 4. Settlement Clock

> **Hill-bonding scope, ratified 6 Oct and 13 Oct 2026:** Monday 12:00 UTC
> and the 24-hour grace remain. The new module's seven-day upload-week
> admission and fixed boost ride-week cutoff supersede the oldest-open-week
> and 30-day economic admission below for that module only. Sporting
> provenance and legacy obligations are not rewritten. See [§16.4](#164-weekly-riding-and-money)
> and [STAGE1_SPEC §§2, 5–7][HB-S1].

`Epochs` are not the ontology of the protocol.

They are the **settlement clock** for economic state.

Product-facing language should prefer **Settlement Week** or equivalent
fitness-native phrasing.

The settlement clock exists to finalize:
- reward distributions
- staking entitlements
- payout obligations
- economic carry state

Settlement Weeks run from **Monday 12:00 UTC to Monday 12:00 UTC**. A
24-hour finalization grace follows the boundary, so the normal rider rhythm is
Monday training-week handoff and Tuesday DUNG receipts. The fixed UTC cadence
keeps every normal week exactly 604,800 seconds and leaves Sunday intact as a
race, event, or long-ride day.

Vault tribute is a **lifetime tribute flow meter**, not a set of ride-week
buckets. After an empty-week catch-up, every economically accepted completion
adds its tribute to the Vault's oldest open Settlement Week. Finalization pays
whatever entered that open flow since the prior finalization. A ride's
original `completed_at` remains the provenance for KOM and Record Board truth;
it does not select a payout bucket. The economic age guard remains 30-day:
exactly 30 days old is accepted, and anything older is rejected before CAL or
climb economics can complete.

The ratified forward-only ride tribute policy is
`cal_tribute_segment_tss_v2`. `credit_cal` credits the rider's full attested
CAL; tribute is a separate flow-meter amount, not a token deduction or a second
CAL mint. Each eligible Climb receives the TSS measured inside its own
authoritative power window:

```text
segment_tss_base_units_i = floor(
  segment_np_duration_s_i * segment_np_milliwatts_i^2 * 100 * 1_000_000_000
  / (reward_ftp_w^2 * 1_000_000 * 3_600)
)
exact_tribute_budget_base_units = sum(segment_tss_base_units_i)
```

NP is frozen to integer milliwatts and its pause-aware NP duration; each Climb
amount is floored independently to one CAL base unit. The immutable ride-time
reward FTP supplies the denominator, while mutable profile FTP never enters the
calculation. Missing, insufficient, or zero segment power produces zero tribute
with no gradient proxy; completion and leaderboard truth remain independently
eligible. One fastest qualifying traversal per ride and Vault supplies the
single receipt-backed Result already permitted by the protocol. Across files,
one physical pass earns at most one completion and tribute: overlapping windows
on the same Vault identify the same pass. A window wholly outside a plan's paid
seconds earns nothing. A partially paid pass can keep its completion when no
prior plan holds it; its tribute uses only the paid seconds. Overlapping
eligible climb windows require review instead of double-counting work. The sum
never exceeds full attested CAL. For a trimmed ride this is the paid CAL; an
excess goes to review, without capping or proration. The program binds every exact receipt amount
and enforces that full-CAL ceiling; the backend and PostgreSQL recompute the
versioned formula from frozen evidence. Historical plans retain their original
policy and are never reinterpreted.

The age decision happens once, when `record_ride` creates the immutable
`RideAttestation` and records `settled_at`. Receipt-backed completion and CAL
then revalidate the ride against that admission clock, not a later wall clock,
so a ride accepted at the exact 30-day boundary cannot age out halfway through
its transaction sequence. Aggregate `last_completed_at` is monotonic even when
older accepted rides arrive later.

Program 0x4E also bounds each attestation's economics on-chain.
`record_ride` and `authorize_held_ride_release` reject CAL above one whole CAL
per declared TSS (`cal_earned / 10^9 <= total_tss`, the same floor the backend
and PostgreSQL apply to one decimal TSS) and TSS above what intensity factor 40
sustains over the ride's elapsed time
(`total_tss * 36 <= (completed_at - started_at) * 40^2`). IF 40 is 2,000 W
normalized power at the 50 W reward-FTP floor, about 25 times the worst of 480
real power rides re-priced at that floor. This limits a single malformed call.
It is not a defence against a compromised backend attester key, which can
still declare any ride inside both limits.

A ride admitted before its rider has an established Threshold is still recorded
through this ordinary 30-day gate, but its parent `RideAttestation` must freeze
`total_tss = 0` and `cal_earned = 0`. The 200 W network default is only the
immutable ride-time display placeholder and cannot authorize ordinary CAL or
tribute. Under the ratified Option-A closure, every accepted source-eligible
fit is recorded, `economic_candidate_w` is the rider's lifetime maximum of all
valid 50-500 W fits, and economic authority is monotone even when the fitted
duration coordinates change. The first valid fit queues establishment at the
next Monday-noon boundary; later eligible promotions may raise but never lower
the sealed authority. Sealing isolates failures per rider in
`repair_required`, rather than weakening or blocking other riders' due
authority. Once the first derived Threshold is effective, one immutable
`HeldRideReleaseAuthority` child may bind the established authority commitment,
recomputed TSS and CAL, exact tribute budget, release-plan hash, release time,
and release Settlement Week. The interval from `RideAttestation.settled_at` to
Threshold effectiveness is eligible through exactly 16 weeks; a longer interval
lapses. If the Threshold predates a later historical upload, held duration is
zero. Eligibility is decided once, while transaction retries may finish later.
The release-plan hash is canonical authority evidence and excludes planner
leases or other retry ownership. Child authorization precedes the one-time CAL
credit; V3 completion receipts follow that durable CAL checkpoint, so repair
never remints CAL or repeats an already confirmed completion.

Program 0x4E removed the legacy `record_vault_completion` instruction, whose
aggregate account had no per-ride receipt and so could not make retry replay
safe, and the first receipt-backed `record_climb_completion` wire entry, whose
V1 receipt and hash proved ride/vault identity but not the exact tribute
applied on-chain. Both had failed closed before removal; their discriminators
now reach the program's empty fallback.

All new ordinary completion economics use `record_climb_completion_v2`. The V2 receipt
uses the same deterministic PDA seeds and a distinct account discriminator. It
stores `evidence_version = 2`, exact `cal_tributed`, and:

```text
SHA256(
  "BR_CLIMB_COMPLETION_V2"
  || ride_attestation_pubkey
  || vault_pubkey
  || completion_time_s_u32_le
  || cal_tribute_u64_le
)
```

The program recomputes this hash before any receipt, Vault, completion,
RideTributeBudget, KOM, or Record Board mutation. Historical V1 receipts remain
byte-for-byte readable as identity evidence, but they must never authorize an
exact tribute amount, automatic confirmation, or a non-reject review outcome.

V2 receipts also share one writable `RideTributeBudget` PDA derived from the
`RideAttestation`. The first remaining account on every live completion must be
that PDA. It records full attested CAL as the independent conservation ceiling
and the aggregate CAL tributed so far; a completion that would make aggregate
tribute exceed full attested CAL fails before any Vault, leaderboard, or receipt
mutation. Exact measured tribute is frozen and recomputed in the database plan,
then bound into each receipt hash. The writable PDA also serializes concurrent
completions for the same ride.

Threshold-release completions use `record_released_climb_completion` and an
evidence-version-3 receipt at the same structural replay PDA. Its hash binds the
child release authority in addition to the parent RideAttestation, Vault,
whole-second time, and exact tribute. A distinct `ReleasedRideTributeBudget`
discriminator occupies the ordinary ride-budget PDA, so ordinary and released
tribute paths cannot coexist for one ride. Each released completion retains the
parent's original `completed_at` for sporting truth but assigns tribute only to
the Settlement Week frozen in the child release authority. A Vault still on an
older nonempty flow must wait. The instruction may advance an empty,
finalizable lagging flow before enforcing exact equality; a Vault that has
advanced beyond the release week cannot be retargeted automatically. The V3
receipt, emitted completion flow, and release authority must carry the same
week. `credit_released_cal` is a
separate single-use receipt and applies the release's frozen TSS and CAL after
child authorization and before the completion loop; it does not mutate the
parent.

The deployed Vault layout retains `cal_tribute_accumulated_next` and
`pending_rewards_next_week` for compatibility. New completions never write
them. Any legacy value already present drains through the normal rollover into
the current flow; it is neither discarded nor treated as new ride-week
admission.

The prior `1704020400` anchor is historical implementation state, not the
ratified clock: it resolves to Sunday 11:00 UTC despite comments that called it
noon. Migration must use an explicit clock version or a clean test-state
cutover; previously indexed week numbers must never be silently reinterpreted.
On a live versioned cutover, preserving those numbers requires one explicit
transition week: it begins at the legacy Sunday 11:00 UTC boundary and ends at
the following v2 Monday 12:00 UTC boundary, lasting 694,800 seconds. That
one-time 25-hour extension is recorded as the cutover week. Every subsequent
week is the normal 604,800 seconds and finalizes Tuesday at 12:00 UTC.

The following do **not** depend on settlement weeks for their meaning:
- Climb identity
- founder provenance
- KOM
- all-time top 10
- lifetime tribute
- rider lifetime effort identity

---

## 5. Three Representation Layers

### 5.1 On-Chain Truth

Store on-chain anything that is economically binding or defines durable rights:
- Climb and Vault state
- current KOM state
- current Record Board state
- current Local Legend state
- final payout obligations
- finalized settlement outputs
- carry balances
- current staking positions
- RiderBalance lifecycle state and mint-scoped Balance token accounts

If it changes balances, rights, seats, or final records, it belongs on-chain.

#### Boulder Roller Balance Authority

The rider-scoped `RiderBalance` PDA is the authority for whether Boulder Roller
Balance is initialized, active, locked, recovering, or revoked. A wallet's
existence does not imply that its RiderBalance exists or is active. Balance-held
CAL, DUNG, and USDC are the exact SPL amounts in mint-scoped
`rider_balance_token` PDAs owned by the rider's `rider_balance_auth` PDA. They
are never aliases of wallet token accounts.

CAL and USDC Balance account addresses use the mints read from the same
finalized on-chain `ProgramConfig` observation. Readers validate the
RiderBalance program owner, rider, PDA bump, token program owner, token
authority, and mint. A missing account is a known `not_initialized` zero; an
unavailable or invalid read is unknown and fails closed rather than becoming
zero.

#### Program Compatibility

`protocol/program-version.json` is the canonical compatibility ledger for the
deployed Boulder Rollers program and every checked-in decoder. The frozen
V4-A ABI is `0x40`; the current V4-A patch ABI is `0x44`; `0x4B` remains
reserved for V4-B. Each breaking checked-in Anchor ABI change advances the
version by exactly one and creates an append-only ABI snapshot. Advancing the
version without an ABI change, changing the ABI without advancing the version,
skipping a version, or modifying a historical snapshot is invalid.

The `ProgramConfig.program_version` byte is the live compatibility truth. Its
admin-only transition accepts only the manifest's exact previous-to-current
step and changes no other account byte. Backend transaction construction,
indexer decoding, deployment validation, and mobile protocol verification use
generated expectations from the same manifest. An unavailable or unequal
version is incompatible and fails closed; a projection may remain visible, but
it cannot be treated as verified or used to construct economic writes.

The first `0x40` to `0x41` deployment is a controlled bootstrap because the
deployed `0x40` binary predates this guard. Economy writers remain paused while
the new binary and required account migrations land. The admin advances the
live byte only after those migrations finalize, and matching clients resume
only after finalized validation. Every later ABI transition uses the same
one-step gate before writers resume.

### 5.2 Attested Truth

Attested truth is verifiable but too heavy, private, or operational to live
fully on-chain:
- raw ride files
- sensitive GPS traces
- canonical ride hash inputs
- parser version and attestation version
- TSS derivation inputs
- geographic matching outputs
- canon compilation inputs (OSM extract, DEM tiles, compiler version)
- fraud and integrity analysis

Attested truth must be reproducible and versioned.

### 5.3 Projected Truth

Projected truth is for reading, exploration, and UX:
- dashboards
- feeds
- heatmaps
- rankings by time filter
- discovery surfaces
- BoulderScan views
- "this week / last 30 days / all time" projections

Projected truth is never authoritative for payouts.

---

## 6. Protocol Roles

These roles are distinct and must not be collapsed into one another.

### 6.1 Founder

> **Superseded for bonded hills, ratified 8 Oct 2026:** the backer whose
> pledge bonds the hill gets the Founder title only, without a paid bootstrap
> Local Legend seat. The following is retained CAL-vault role history;
> [§16.2](#162-roles-bonding-and-permanence) and [DIAMOND, Settled on
> 8 October][HB-DIAMOND] define the new role.

The **Founder** is the wallet that first brought the Climb into protocol form.

Founder rights are:
- permanent provenance
- metadata and cultural authorship within the protocol's rules
- bootstrap visibility and initial stewardship kickback via the first Local Legend stint

Founder rights are **not** permanent performance rights and are **not** implied
perpetual royalties.

### 6.2 KOM and co-KOM

The **KOM** is the current all-time fastest validated whole-second performance
on the Climb. When more than one seated rider shares that fastest time, every
one of those riders is a **co-KOM**.

KOM and co-KOM truth is:
- permanent record truth until a strictly faster validated time replaces the
  full prior KOM/co-KOM set
- shared by every seated rider tied at the fastest whole-second time
- shown as a crown and `T-1` for every co-KOM on detailed rider surfaces
- separate from stewardship
- separate from capital

The singular on-chain `Vault.kom_holder` field remains for ABI compatibility.
It is only the deterministic legacy representative of the current KOM/co-KOM
set: choose the earliest original ride `completed_at`, then wallet bytes as the
final tie-break. It receives no additional payout and has no sole-winner
sporting meaning. Projections enumerate co-KOMs from the seated Leaderboard,
not from `kom_holder` alone.

KOM/co-KOM recognition grants no metadata stewardship. After the Founder's
initial metadata-rights period, that role belongs to the active Local Legend
(§6.4). The current V4-A `update_vault_metadata` path still resolves expired
Founder rights through singular `kom_holder`; this is explicit transitional
compatibility behavior, not canonical role meaning. This amendment neither
extends that authority to every co-KOM nor treats the legacy representative as
the sporting basis for stewardship. Moving the path to Local Legend authority
requires its own explicit authority/ABI rollout. Until that rollout lands,
implementation must not rotate `kom_holder` for a late equal-fastest ride:
changing the scalar would also transfer live post-Founder metadata authority.
Whether that rollout needs a Local Legend data migration must be proven rather
than assumed.

### 6.3 Record Board

For bonded hills, cash uses the field and flat split in
[§16.4](#164-weekly-riding-and-money),
**ratified 6–7 Oct; mechanics 13 Oct 2026** ([DESIGN][HB-DESIGN];
[STAGE1_SPEC §§1, 5][HB-S1]). Whole-second sporting ties, original ride-time
provenance and the ten-person bound remain; a tie does not change cash among
the admitted seats. These sources do not separately ratify DUNG's within-board
division; [§16.5](#165-dung-issuance) identifies the reference-model behavior.

The **Record Board** is the climb's all-time top 10.

It is:
- permanent record truth
- ordered by all-time best performance
- economically meaningful in Boulder Roller

Equal whole-second times use standard competition ranking. Tied seated riders
share the first occupied rank in their group, consume one position each, and
split the pooled shares for those occupied positions equally. The on-chain
board remains bounded to ten riders. When an equal-time group crosses that
boundary, original ride `completed_at` decides seat membership, with wallet
bytes only as a final deterministic fallback; processing order never decides.
For additive `client.v1` compatibility, `rank` remains the occupied row
position while `competition_rank` carries this paid tie rank. Every seated
rider at the fastest time has `competition_rank = 1` and receives the co-KOM
crown and `T-1` presentation defined in §6.2. Boards activated before this rule
cannot reconstruct an omitted seat from their bounded account alone. Any
historical repair must be separately ratified, one-time, and bound to complete
completion evidence; active-board replacement does not become a normal
administrative power.

The all-time top 10 may remain hard to move. This is a feature, not a bug.

### 6.4 Local Legend

> **Bonded-hill amendment:** title-only Founder / earned Legend was **ratified
> 8 Oct 2026**; the season-long pool fallback was **settled 6 Oct**, with
> mechanics and claim nonexpiry **ratified 13 Oct**. The paid bootstrap and
> indefinite empty-seat carry below remain legacy CAL-vault rules. New
> unassigned money waits at most 26 weeks before becoming pool-only; assigned
> claims do not expire. See [§16.4](#164-weekly-riding-and-money), [DESIGN,
> Empty seats / Stranded money][HB-DESIGN], [DIAMOND][HB-DIAMOND] and
> [STAGE1_SPEC §§5–6][HB-S1].

The **Local Legend** is the active steward seat for a climb.

It is:
- rolling truth
- based on recent participation
- culturally authoritative, not permanently glorious

Alpha behavior is explicit:
- The Founder receives the first bootstrap Local Legend stint when a climb is created.
- Bootstrap is not an elected win: current protocol surfaces expose `is_bootstrap = true`; legacy V3/V4 rows may infer the same state from `election_period = 0` and `completions_at_election = 0`.
- A bootstrap seat may earn the Local Legend bucket while active, but it must be labeled as bootstrap/founder stewardship in rider-facing surfaces.
- Elected Local Legend seats are based on recent eligible completions over the configured term window. The current alpha term length is `local_legend_term_epochs` from program config, currently 8 epochs.
- The epoch processor runs Local Legend rollover before settlement finalization for an ended settlement week. It elects the top eligible recent-completion rider, re-elects the current holder if they win the next window, or submits a dormant-seat transaction when the window has no eligible completions.
- Each rollover starts exactly at the outgoing term's recorded `term_end_epoch`, even when a delayed crank is catching up several historical terms. The on-chain transition rejects skipped or wall-clock-derived starts, so candidate evidence and payout identity stay attached to the same Settlement Weeks.
- If no eligible recent participation exists when a term rolls, the seat becomes inactive/dormant. The previous holder remains historical memory, not the current steward.
- When the seat is inactive or absent, the Local Legend payout bucket carries forward inside `carry_local_legend`; it is not redistributed to Record Board, stakers, treasury, POL, or the Founder.

If the recent-participation window goes quiet:
- the active Local Legend seat may become inactive
- the last holder remains historical memory
- the Founder remains the Founder

### 6.5 Staker

The **Staker** is a capital participant in a climb's Vault.

Stakers support the climb economically, but capital must never impersonate
effort or record performance.

---

## 7. Token Meanings

### 7.1 CAL

**CAL** is the transferable work and currency token.

CAL is:
- born from attested TSS calculation
- transferable
- market-participation-capable
- stakeable into Vaults

CAL is **not**:
- rider XP
- soulbound effort identity
- proof of riderhood by itself

### 7.2 DUNG

For future bonded-hill DUNG, the recipient buckets below are superseded by
the rider/backer split in [§16.5](#165-dung-issuance), **ratified 6–8 Oct
2026** ([DESIGN][HB-DESIGN]; [DIAMOND][HB-DIAMOND]). The value-token role
and absence of a zero-start market remain distinct from funded rider pay.

**DUNG** is the value and reward token.

DUNG is:
- emitted from climb/Vault economics
- the asset distributed to record holders, stakers, stewards, and protocol buckets

### 7.3 Beetle Score / Soul

Rider identity, level, and lifetime effort must remain a separate soulbound
layer.

This layer is:
- non-transferable
- effort-derived
- distinct from capital position

Capital may buy exposure to a climb. Capital may not buy riderhood.

---

## 8. Canonical Economic Buckets

> **Legacy CAL-vault economics, retained.** For future bonded hills,
> §§8.1–8.5's 55/27/3/5/10 bucket split, wallet-count
> unlock and protocol/POL allocation are superseded by **6 Oct 2026** hill
> bonding; caps/halvings by **8 Oct** constant issuance. Stage-1 mechanics
> were **ratified 13 Oct**. See [§16](#16-hill-bonding), [DESIGN][HB-DESIGN],
> [DIAMOND][HB-DIAMOND] and [STAGE1_SPEC][HB-S1]. Cash uses a flat board split;
> DUNG's within-board division is not separately ratified, so the reference
> model's equal shares (§16.5) do not themselves supersede the legacy DUNG
> rank allocator. The detailed legacy CAL
> custody, consent, accounting and liability safeguards below remain in force
> for their existing positions; this amendment does not repurpose them.

### 8.1 Leaderboard Pool

The `55%` bucket is the **Leaderboard pool** in every human-readable surface.
Existing `record_royalty` names remain compatibility-sensitive program and
schema identifiers, not display vocabulary.

It pays the Climb's all-time Leaderboard:
- top 10
- rank split `30/20/15/10/8/6/5/3/2/1`

Those percentages belong to occupied positions. Equal-time groups pool their
occupied percentages and every seated member receives the same floored base-unit
amount. Any indivisible base-unit remainder stays in `carry_record_royalty`.
Co-KOM recognition does not create an eleventh seat, a new percentage, an
additional payout, or a different payout byte.

This is not a live-week challenger board by default. It is the permanent
benchmark royalty for canonical climb excellence.

### 8.2 Staker Bucket

The `27%` staker bucket is the maximum weekly allocation for capital support of
the Vault. The participation curve unlocks a percentage of that weekly amount
for eligible stakers.

The portion not unlocked in that Settlement Week flows immediately to the same
week's Leaderboard pool. It does not become retroactive staker carry and is not
re-tested against future staker counts. This preserves the published curve: a
one-staker week pays 1% of the 27% bucket, not a growing effective percentage
created by repeatedly unlocking old balances.

Integer dust after the unlocked allocation is calculated is distinct from the
policy-locked remainder. It must be assigned deterministically or retained as
already-unlocked staker dust; it must never pass through the unlock curve a
second time.

Settlement weights frozen LP, not the rider's mutable withdrawal balance. A
change exactly at a Settlement Week boundary is effective for that new week;
a change after the boundary is effective the following week. Top-ups and
withdrawals therefore never rewrite an already-open week's weight.

`VaultStake` stores one effective LP snapshot and one pending full-balance
target. Multiple changes aimed at the same effective week replace that target.
If a delayed crank would require preserving changes for two different future
weeks, the later transaction fails closed before moving tokens; unresolved
history must never be silently collapsed or overwritten.

Indexer projections retain the former `eligible_from_epoch` and deprecated
amount columns as legacy provenance. Snapshot columns are additive, and an
allocation's `snapshot_epoch` is derived from its canonical settlement `epoch`;
historical eligibility metadata is never relabeled as a snapshot.

Settlement must supply every settlement-relevant `VaultStake` account for the
Vault exactly once. A position remains relevant while its current LP, effective
snapshot LP, or pending snapshot LP is nonzero. This includes pending positions
and zero-current-LP tombstones whose frozen snapshot still carries weight. A
fully inert account drops from the required inventory, keeping settlement
bounded rather than growing with every historical depositor.

`Vault.staker_count` tracks that settlement-relevant inventory. Deposits,
withdrawals, re-entry, and snapshot promotion update it with checked transition
math. A mature full exit remains counted until its zero target takes effect; an
exit that never acquired effective weight can leave immediately.

The program validates every supplied account's owner, discriminator, Vault,
PDA, bump, uniqueness, and exact inventory count before distributing. Payout
eligibility is then derived independently from each account's frozen LP
snapshot. Omitting any position must never redistribute its share to the
positions that happened to be supplied.

The complete payout remains one atomic `distribute_epoch_rewards` instruction.
Recipient token-account creation is a separate idempotent preparation step;
it is never appended to the economic transaction. The backend carries the
full Leaderboard, active Local Legend, and complete settlement-relevant stake
inventory in a v0 transaction through a managed per-Vault address lookup table.
Before signing, finalized chain reads must prove the table active, correctly
owned, complete, and unchanged from the durable account-manifest hash.

An unsigned settlement whose lookup table or account manifest changed returns
to preparation without touching economic state. Once a deterministic payout
signature has been prepared or accepted, only reconciliation may advance it;
transport repair must never create a replacement economic signature.

A deposit that would round down to zero LP must fail atomically before CAL is
transferred or either the stake position or `staker_count` is changed.

`VaultStake.cal_staked` is the position's remaining deposited-principal basis.
`VaultStake.lp_tokens` is the position's recorded share of the Vault's current
gross CAL pool, whose aggregate inventory is `Vault.total_cal_staked`. These
quantities are not interchangeable once the pool ratio moves away from 1:1. A
withdrawal also requires matching internal LP custody and returns
`floor(LP burned * Vault CAL / LP supply)`, then takes the exit fee from those
gross proceeds. The retained principal basis is
`floor(prior principal * remaining LP / prior position LP)`; a full exit clears
it exactly. Fee math never changes that basis allocation.

One rider-and-Vault position has one deterministic LP custody token account,
derived from the rider and Vault ID. Both wallet and Boulder Roller Balance
deposits mint into that same account. The SPL token authority is the
`VaultStake` PDA, not the rider wallet or editable profile state, and the Vault
PDA remains both mint authority and freeze authority for the LP mint. The Vault
freezes the custody account between protocol instructions. First use prepends
an idempotent custody initializer in the same transaction as the deposit. A
checked deposit or withdrawal may thaw it only for the atomic mint or burn and
must refreeze it before returning. At instruction entry its mint and token
authority must be canonical and its exact token amount must equal
`VaultStake.lp_tokens`; only a fresh, empty position may begin unfrozen. A
withdrawal readiness observation also proves the LP mint is initialized under
the SPL Token Program and that both mint authorities remain the Vault PDA. This
makes Vault LP an internal pool-share ledger, not a transferable bearer asset,
and prevents both outbound transfer and unsolicited inbound LP from changing
redeemability.

Legacy wallet, custom-destination, and Balance LP remain quarantined after the
custody upgrade until their units are restored into the deterministic account.
Restoration may move existing units but never rewrites principal, rewards, or
Settlement Week snapshots. Missing, short, overfilled, wrong-mint,
wrong-authority, or unfrozen custody is not redeemable and fails closed.

This account-bound model does not prohibit a future managed strategy. A
separate program identity may deliberately own its own Vault position through
an explicit, versioned integration and issue a distinct bearer share for that
strategy. The core Boulder Roller position and its internal LP do not become
transferable by implication.

A current position remains active while `lp_tokens` is nonzero. Retained
principal can legitimately floor to zero before the final LP units are burned,
so indexers and read models must not hide a redeemable position merely because
`cal_staked` is zero. Positive recorded LP identifies an accounting position;
live custody validation determines whether a withdrawal can be prepared.

Balance custody is not rider consent. `deposit_cal_from_balance` and
`withdraw_cal_to_balance` require an active rider-configured
`BalanceVaultAuthority` session in addition to their canonical custody and
destination checks. The rider wallet signs session setup,
rotation, and revocation. A session binds the rider, one operation signer, a
nonzero policy hash, a generation, a sequential nonce, and an expiry no more
than seven days away. Locking, recovery, or revoking the RiderBalance clears
its active session header; changing the status back to active does not restore
the old grant.

Each Balance-funded Vault operation carries one domain-separated SHA-256 intent
over the exact program, rider, session signer, action, Vault, CAL/LP/USDC base
units, generation, nonce, and operation expiry. The configured signer must sign
the transaction. The program recomputes that intent, consumes the nonce exactly
once, and records the operation ID before value movement. A fee payer, backend
signer, login session, UI confirmation, or program custody account is never a
substitute for this grant. Quiet or gasless execution therefore means
authorized execution without a repeated wallet popup, not permissionless
movement. A wallet-signed action remains the fallback. Fixed-benefit actions
whose destination cannot harm the rider, such as canonical Collect DUNG, may
remain permissionless-for-rider.

LP withdrawal amounts are exact token base units. A partial withdrawal carries
the requested u64 as a decimal string. A full-position withdrawal reads the
current `VaultStake.lp_tokens` at the canonical rider-and-Vault PDA and burns
every base unit; it must never round a display amount or pass LP through a
binary float or JavaScript `Number`. A missing position and an unavailable or
invalid chain observation are different states and must fail separately. The
program remains final authority if the position changes between preparation
and execution.

### 8.3 Local Legend Bucket

The `3%` Local Legend bucket compensates rolling stewardship and recent
participation legitimacy.

### 8.4 Protocol and POL

The `10%` protocol bucket and `5%` POL bucket fund protocol operations and
liquidity.

### 8.5 DUNG Emission Schedule

> **Superseded prospectively for bonded-hill DUNG, ratified 8 Oct 2026:**
> 1 DUNG per 1,000 climb-TSS in every year, without halvings, lifetime caps or
> the 1-bps tail. [§16.5](#165-dung-issuance) states the rule and
> [§16.8](#168-supersession-cutover-and-source-boundaries) protects existing
> entitlements at an explicit cutover. [Source: DIAMOND, Settled on 8 October][HB-DIAMOND].

DUNG emission is activity-derived: Vault tribute supplies the amount to which
the emission rate applies. It is not an unconditional weekly faucet.

The rate starts at 10,000 basis points and halves automatically every 26
Settlement Weeks from one immutable emission-start week. Fresh initialization
anchors that start to the latest week whose Monday handoff and 24-hour grace
have elapsed; migration preserves the deployed start. Settlement applies all
elapsed halvings deterministically; no administrator call controls the clock.
The deployed `lastHalvingEpoch` account field retains its historical ABI name
but stores this start week; settlement never rewrites it. The policy rate
floors at 1 basis point. Capacity exhaustion can reduce admitted new emission
to zero, but it does not rewrite the policy rate.

Every admitted Community unit is reserved before settlement pays or defers it.
`community_reserved` equals all unclaimed `VaultStake.rewards_earned` plus all
Vault Record Royalty, staker, and Local Legend carry. A direct Community mint
consumes its reservation; a deferred claim or bucket-local carry retains it.
Cap pressure may clip only new, not-yet-admitted emission. Existing claims and
carry are never discarded, reclassified, or stranded to make a settlement fit.
POL and treasury recipients are always configured and available, so those
buckets mint immediately and their carry must remain zero.

The full-liability reservation contract is marked on-chain by
`reservation_policy_version = 1` in the 130-byte `DungMintState`. Settlement
and collection fail closed until that marker is present. The authority-gated
migration accepts the 121-byte legacy state or the 129-byte claim-only
predecessor, preserves every existing byte, and appends or tops up the exact
full liability. An unversioned state is migratable only while its emission
rate is still 10,000 bps, which proves that the historically mutable halving
field was never advanced before it becomes the immutable emission start.

Migration is a paused operation, not a normal maintenance call. It requires a
discriminator-complete census of every `VaultStake` and Vault, exact account
counts and liability total, a reviewed inventory hash, a pre-created address
lookup table, a signed simulation, and a reviewed transaction-plan hash. The
ProgramConfig admin authorizes the change while a distinct powerless payer
funds rent and transaction fees. Writers resume only after a finalized-slot
read proves policy version 1 and `community_reserved` equals the same complete
liability. The operational sequence is in
[`DUNG_RESERVATION_MIGRATION.md`](runbooks/DUNG_RESERVATION_MIGRATION.md).

The canonical split is 55% Record Royalty, 27% stakers, 3% Local Legend, 5%
POL, and 10% treasury. The configured DUNG mint, initialization authority,
emission start, and 26-week interval are ProgramConfig-bound policy; the split
is program-canonical rather than caller-selectable transaction input.

### 8.6 DUNG Supply Accounting

The lifetime-cap enforcement below belongs to the legacy CAL-vault model.
It is **superseded for new bonded-hill issuance, ratified 8 Oct 2026**
([DIAMOND][HB-DIAMOND]; [§16.5](#165-dung-issuance)). This does not erase
historical counters, burn records or liabilities, or substitute a model's
issuance for observed circulating supply.

`DungMintState.total_minted` is lifetime program issuance. It and the allocation
bucket counters enforce the immutable supply caps. Burning DUNG never reduces
those counters and never creates new emission headroom.

`DungMintState.total_burned` is narrower telemetry: DUNG burned by Boulder
Roller program instructions after protocol burn accounting is active. Every
program DUNG burn updates it atomically with the SPL burn and emits
`DungBurned`. It cannot observe a holder burning DUNG directly through the SPL
Token Program and is therefore not circulating-supply authority.

The configured SPL DUNG mint account's exact `supply` field is the only
circulating DUNG authority. Read models must project that base-unit value with
its own finalized Solana slot and verify the observed mint against the
immutable DUNG mint in finalized `ProgramConfig`. Missing or mismatched mint
authority fails closed. Read models must not derive circulation as
`total_minted - total_burned`, reuse the `DungMintState` account slot for the
mint observation, convert through floating point, or display a missing mint
observation as zero.

---

## 9. Economic Meaning of Quiet Climbs

For bonded hills, this continuing economic role is subject to the seasonal
field, live-yield gate and funded per-asset cap, **ratified 6–13 Oct 2026**
([§16.4](#164-weekly-riding-and-money); [DESIGN][HB-DESIGN]; [STAGE1_SPEC][HB-S1]).
Old record times alone do not establish current payout eligibility or money.

A climb can remain economically alive even when the record board is old.

If a climb continues to attract tribute and economic inflow, the Record Board
may continue to earn from that inflow even if the top times are historic.

This is intentional.

Boulder Roller honors:
- permanent excellence through the Record Board
- recent stewardship through Local Legend
- capital support through staking

The protocol does not require constant record churn for a climb to retain
economic significance.

---

## 10. Privacy and Cost Boundary

The protocol should be conservative about what it stores on-chain.

On-chain should hold:
- compact, binding state
- durable rights and payouts
- record and stewardship state
- settlement outputs

Off-chain attestation should hold:
- raw files
- precise private traces
- heavy verification inputs

The protocol's public objects should be sufficient to explain outcomes without
forcing raw ride privacy onto the chain.

### 10.1 Account Deletion and Retained Authority

Account deletion **anonymizes** retained protocol authority. It does not punch
holes in climb results, Leaderboard history, or finalized Settlement Weeks.
This policy was ratified by Tim on 2026-08-24.

The deletion contract is:

- **Remove:** authentication identities and sessions, profile/contact fields,
  provider links and device registrations, privacy/configuration data, raw ride
  files, precise private traces, media, and other personal off-chain evidence
  that is not required to preserve an authoritative sporting or settled row.
- **Anonymize:** the actor on retained climb times, attempt/Leaderboard history,
  Local Legend history, and settled economic records becomes a non-reversible
  anonymous marker. The original profile, name, contact identity, and wallet
  are not the public label for that marker.
- **Retain:** climb times and sporting placement remain public under the
  anonymous marker. Settled economic history remains available only through
  the same private/support authority that governs money elsewhere; deletion
  does not turn money into a public surface.

Deletion cannot begin merely because a request was accepted. The server owns a
durable request with explicit queued, processing, blocked, retryable-failure,
support, legacy-unverified, and completed states. Every destructive phase
re-runs authoritative preflight, and status remains readable by a scoped bearer
capability after authentication is removed. `completed` is valid only after the
identity removal, personal-data removal, anonymous retained-row rewrite, and
storage receipts all commit authoritatively.

Positive CAL, DUNG, or USDC value; active stakes; pending or unclaimed claims;
unavailable authority; and unresolved wallet/on-chain provenance block
automatic deletion. The 2026-08-24 ratification does not decide mid-week stake
handling, unclaimed DUNG disposition, or how immutable on-chain provenance is
represented. Those cases route to the owning Bead and support until separately
ratified; an implementation must not improvise a burn, transfer, forfeiture,
wallet rewrite, or completion claim.

Tim ratified the standing v1 human gate on 2026-08-24: the automatic destructive
boundary remains off, and value-bearing or unresolved disposition edges route to
durable blocked or `needs_support` status for human resolution. Filing that
request is not permission to dispatch destructive work. That boundary cannot be enabled until
writer-side serialization and two-connection race coverage prove that every
identity carrier is fenced across the final blocker/residue snapshots. This is
an engineering prerequisite, not permission to revisit anonymize-not-erase.

No rider-facing account-deletion copy may promise protocol permanence while the
mainnet gate remains open. Tim confirmed this shared portal/native sentence on
2026-08-24: “Your identity and personal data will be removed. Your climb times,
leaderboard history, and settled economics will remain linked to an anonymous
account.” No other explanatory keep/remove sentence ships without confirmation
on the owning Bead. In particular, N14's separate consent sentence for destroying
unuploaded ride recordings remains Tim-owned and blank in native code.

---

## 11. Naming Conventions

These names are canonical and should be used consistently:
- `Climb`
- `Climb Canon` and `canon version`
- `Vault`
- `Leaderboard` on every human-readable surface; existing `record_board`
  identifiers remain internal compatibility names
- `Leaderboard pool` on every human-readable surface; existing
  `record_royalty` identifiers remain internal compatibility names
- `KOM` for a sole fastest rider and `co-KOM` for each seated rider tied at the
  fastest validated whole-second time; detailed rider surfaces show crown and
  `T-1` for each co-KOM
- `Local Legend`
- `Settlement Week`
- `CAL`
- `DUNG`
- `Beetle Score` or equivalent soulbound effort identity

Avoid collapsing these into generic language where that would reduce semantic
clarity.

---

## 12. Alignment Implications

The current alignment project must be interpreted through this document.

### 12.1 Preserve

The `55%` instruction below is retained CAL-vault alignment history. For
bonded hills, preserve the board's sporting meaning with the new cash/DUNG
splits, **ratified 6 Oct 2026** ([§16](#16-hill-bonding); [DESIGN][HB-DESIGN]).

Keep and defend:
- all-time top 10 as on-chain record truth
- Leaderboard pool semantics for the 55% bucket
- Local Legend as recent stewardship
- CAL as transferable currency
- climb-first ontology

### 12.2 Repair

The alignment work must repair:
- ride-time vs ingestion-time confusion
- payout history reconstruction gaps
- replay/idempotency gaps in ride settlement
- on-chain/off-chain boundary drift
- role confusion inside the current `Vault` object

### 12.3 Demote

The alignment work must demote:
- `epoch` from protocol ontology to settlement clock
- the assumption that a Vault is the primary object

### 12.4 Prepare

The alignment work should prepare for, without requiring immediate full
migration to:
- first-class ride attestation objects
- broader geographic asset graph types beyond climbs
- a soulbound effort identity layer separate from CAL

---

## 13. Canonical Summary

Boulder Roller is a climb-first cycling protocol where:
- Climbs are permanent shared geographic assets
- Climb identity is compiled into a versioned open canon; rides are evidence, never identity
- Vaults are optional economic wrappers on those assets
- KOM/co-KOM and the all-time top 10 are permanent record truth
- Local Legend is rolling stewardship truth
- Settlement Weeks finalize economic truth
- CAL is transferable work/currency
- DUNG is the reward/value token
- The economy is zero-start: permanence before liquidity, triggers before dates
- Rider identity must remain distinct from capital
- Binding economic outcomes belong on-chain
- Heavy or private ride evidence belongs in attestation
- Read models and UX belong in projections

This is the semantic foundation for further protocol alignment and architectural
work.

---

## 14. Climb Canon

*(Added by amendment, ratified 2026-07-05.)*

### 14.1 Canon Is Identity

A Climb's identity is **compiled, not detected**.

The **Climb Canon** is a versioned registry of Climbs compiled from public
geography — the OSM road graph draped over elevation models — and ratified
through curation. A canon Climb has:

- a stable canon id
- a version
- a fixed corridor
- start and finish gates anchored to real-world features (intersections,
  gradient inflections)
- a canonical elevation profile

A Climb exists in canon before any rider has ridden it. No single ride, and
no detector output, mints Climb identity.

### 14.2 Rides Are Evidence

A ride bears three kinds of evidence, and only evidence:

- **Traversal** — the ride crossed a canon Climb's gates through its corridor
- **Measurement** — how fast, and with what effort
- **Verification** — whether the ride is honest

A ride may also **nominate**: sustained off-canon effort feeds discovery, and
repeated independent nomination is a strong signal that canon is missing a
real hill. Nomination proposes; curation ratifies; the canon registry decides
identity.

### 14.3 Identity Is Deterministic and Versioned, Never Learned

Resolution of a ride to a Climb is geometry: gates, corridors, direction,
coverage. Deterministic in, deterministic out, pinned to a canon version —
explainable in one sentence to the rider it affects.

Learned systems (ML) may rank worthiness, propose boundaries, and detect
fraud. They may not decide identity, and no record, payout, or seat may
depend on a model's judgment.

### 14.4 Canon Versioning and Record Continuity

- **Minor corrections** — profile refinement, corridor widening, metadata —
  carry all records forward under the same canon id.
- **Boundary changes** — moving a gate, changing the measured span — mint a
  new canon version with a fresh Record Board.
- Prior versions and their Record Boards remain **permanent truth** (§3.1).
  A new version opens a new benchmark; it does not erase an old one.

Capture tolerance is a bounded minor-correction case. Canon defaults remain a
25m perpendicular gate half-extent and a 25m corridor half-width. A curated
Climb may use an evidence-backed symmetric gate half-extent up to 40m and
corridor half-width up to 35m only when its gate anchor and center, gate
orientation, centerline, and measured span are unchanged. The exact override
and its evidence are deterministic provenance on the revision; the `canon_id`
and records continue. This is per Climb, never a global widening. Moving an
anchor or gate center, changing orientation or centerline, or changing the
measured span remains a boundary change with a fresh Record Board.

### 14.5 The Vault Binds to Canon

The statement below that founding economics are unchanged predates hill
bonding. For that new module, paid activation and paid Founder bootstrap are
**superseded, ratified 6 and 8 Oct 2026**, by pledge-to-bond and title-only
Founder status ([DESIGN][HB-DESIGN]; [DIAMOND][HB-DIAMOND];
[§16.2](#162-roles-bonding-and-permanence)). Canonical hill identity is retained.

A Vault is the economic activation of a canon Climb (§2.2 unchanged). The
Vault's on-chain commitment is derived from `(canon_id, version, canonical
profile hash)`. Founding economics and Founder rights (§6.1) are unchanged;
what the Founder brings into protocol form is a canon Climb.

Legacy generation-1 devnet Vault activations are read-only as of 2026-07-15.
They may settle existing pending state, return deposited CAL, and deliver DUNG
already owed, but they cannot accept new deposits, completions, or tribute.
New Vault economics require chain-derived activation generation 2 or later.
This quarantine preserves exits while the already-ratified clean V4-B program
replaces the unverifiable historical-seed generation.

### 14.6 Timing Truth

- Traversal times are gate-crossing times, recorded at whole-second
  precision; ties share rank.
- Canonical vertical is net rise: finish profile elevation minus start profile
  elevation. Cumulative positive gain does not define Climb identity or its
  economic vertical.
- Measured elevation for economic purposes comes from the canonical profile.
  Rider sensor data corroborates and verifies; it does not define the hill.

Repeat-ride boundary agreement is measured along the canonical centerline.
For each Climb and start/finish gate with observations from at least two
distinct rides, every crossing's absolute along-track deviation from that
Climb/gate's repeat median enters one pooled endpoint distribution. Cutover
requires p95 deviation **<=10m**. The strict maximum remains a reported
diagnostic, not the pass/fail statistic. The observation set is fixed before
the result is calculated; observations cannot be removed after their outcome
is known. The cutover scorecard reports eligible Climb/gate, ride, and endpoint
counts, p95, strict maximum, and input manifest hashes.

### 14.7 The Canon Is Open

The canon registry is derived from open geographic data and is itself an
open, attributed (ODbL) public surface. Canon pages are useful without an
account. The economy activates the canon; it does not gatekeep it.

---

## 15. Zero-Start Economic Posture

*(Added by amendment, ratified 2026-07-05.)*

There is **no TGE**. No token generation event, listing, or liquid market is
planned, scheduled, or may be presented as a horizon in any protocol, product,
or public surface.

The **13 Oct 2026** permission to sell earned CAL immediately applies once
CAL is tradable under the market trigger. It neither creates a market nor
schedules liquidity: stage 2 still waits for actual CAL buyers. The no-market
state here and the later sale option in §16.7 are distinct. Market language
needs Jon's review before any public promotion. [Sources: DIAMOND, Markets
and whales][HB-DIAMOND]; [DESIGN, Stage 2][HB-DESIGN]; [CHECKLIST item 12][HB-READY].

- What riders accumulate — Record Board seats, Local Legend terms, DUNG
  receipts, soulbound effort identity — is **permanent and provable**, and
  that permanence is the product.
- DUNG's meaning (§7.2) is unchanged; its market is deliberately absent.
- Any future liquidity decision is **trigger-based** — observable evidence
  that participants covet what is scarce — and never date-based.
- Status before liquidity: fraud incentive, securities exposure, and audit
  spend all scale with liquidity, so liquidity comes last.

---

## 16. Hill Bonding

### 16.1 Authority and evidence class

The [diamond][HB-DIAMOND] and [diamond.yaml][HB-PARAMS] remain the single
origin. This amendment folds their rules into protocol authority; the product
projection is [FRESHEST_SPEC §1a](FRESHEST_SPEC.md#1a-hill-bonding).
Each rule below states its status, date and source. The [settled DESIGN
calls][HB-DESIGN] establish the 6–8 Oct decisions; [STAGE1_SPEC][HB-S1]
records the 13 Oct money mechanics and [FUNDING][HB-FUNDING] the service-fee
direction. Later explicit ratifications and their resolutions of older source
wording are identified below.

**Deployed — devnet rehearsal only.** The [8 Oct CHECKLIST, items 1, 3–4][HB-READY]
and [13 Oct brief][HB-BRIEF] distinguish the devnet CAL-vault program of that
time from stage 1. **Since 18 Oct 2026 the devnet program is the stage-1 build
(program version 77; version 78 since 6 Nov 2026), for rehearsal only;
production keeps stage 1 off for riders.** STAGE1_SPEC's implementation
evidence is **local, offline reference behavior**, not on-chain custody,
verified people/rides, provider rates/liquidity or production authority.
Its §9 and [STAGE1_PLAN §7][HB-PLAN] retain those implementation gates.

**Money-admission gate, ratified 6 Oct 2026:** no money moves until counsel
clears public deposits. The checklist also requires the program timelock and
Jon's review of the language before money moves. These are outstanding gates,
not claims of clearance. [Sources: DESIGN, settled Cities call][HB-DESIGN];
[CHECKLIST, closing gate and item 12][HB-READY].

### 16.2 Roles, bonding and permanence

- **Ratified 6 Oct 2026; mechanics 13 Oct.** One canonical hill owns its
  backing, pay, records and DUNG; hills share money only through the later
  shared pool. Pledges sit in escrow, can be cancelled before bonding and
  keep pre-bond earnings for their owners. Crossing the immutable city line
  bonds atomically: cancellation either removes the pledge first or fails
  after it has joined the bond. Philadelphia's line is 10 SOL. All included
  pledges become founding lots. [Sources: DESIGN, Bonding and settled calls;
  DIAMOND principles 1–2; STAGE1_SPEC §§2–3.][HB-S1]
- **Ratified 8 Oct 2026.** The owner of the triggering pledge receives the
  Founder title only. No paid Local Legend seat or performance right follows
  from it. Founding pledges include the Founder's own triggering pledge and
  all other pledges included in the bond, including protocol seed pledges.
  The Founder therefore also participates as a founding backer; the title
  itself adds no paid seat. [Sources: DESIGN,
  Early bonus / Empty seats; DIAMOND, Settled on 8 October.][HB-DIAMOND]
- **Ratified 6 Oct 2026; mechanics 13 Oct.** Bonded is permanent; live is
  weekly. At opening, live requires an already bonded hill and non-exiting
  backing of at least half the city line. A lot counts as
  `min(B, floor(U * r))`, excluding owner reserves, yield above basis and
  rider/cash custody. Snapshot before transactions at the same timestamp;
  later changes affect the next opening. A midweek bond holds that week's
  rider yield and admits no partial-week DUNG. [Source: STAGE1_SPEC §§2–3;
  diamond.yaml `live_fraction`, `stage1.mechanics`.][HB-S1]
- **Ratified 7 Oct 2026; mechanics 13 Oct.** A hill needs five distinct
  admitted people in the city's current 26-week season for its board, paid
  records and DUNG. The city calendar starts at launch on Monday 12:00 UTC;
  the field resets each season. The ten-person board and whole-second
  sporting tie rules remain, with one seat per person; an earned Local Legend
  may also hold a board seat. Canon, identity uniqueness, board and election
  truth are attested inputs, not facts proved by the money model. [Sources:
  DESIGN, Minimum field; STAGE1_SPEC §§1–2, 5.][HB-S1]

### 16.3 Lot custody, fees and exits

- **Ratified 13 Oct 2026.** Each deposit creates an owner/hill/asset-bound
  lot with deposited units `U` and SOL-lamport basis
  `B = ceil(U * r_deposit)`. Rates are exact positive integer ratios. Return
  the deposited token against that basis, subject to the lot's own loss;
  no other lot repairs it. At bonding, segregate transferable pre-bond
  surplus into a fee-free owner reserve. Cancellation returns the actual
  units, with their gains/losses. [Source: STAGE1_SPEC §§1, 3.][HB-S1]
- **Ratified 13 Oct 2026.** A rate observation alone creates no income.
  Harvest transfers at most `max(0, U - ceil(B / r))` surplus token units into
  earnings custody. Below-basis lots contribute nothing until recovery.
  Payouts use the asset actually delivered, in kind; upstream costs already
  reflected in the rate are not deducted twice. SOL conversion and a backer's
  USDC-to-SOL backing require external adapters and do not promise USDC back.
  [Sources: STAGE1_SPEC §4; DESIGN, Custody / USDC settled call (6 Oct).][HB-S1]
- **Yield-only scope ratified 6 Oct 2026; 10% rate and integer mechanics
  ratified 13 Oct.** The protocol's cut is 10% of actually realized yield.
  For lifetime harvested units `R` in each deployment/asset, assess
  `floor((R + h) / 10) - floor(R / 10)` on harvest
  `h`; share the accumulator across hills, lots and owners. It never resets
  at a season, withdrawal, claim or lot exit. No protocol fee is deducted from
  sponsor-cash or boost rider budgets; release and claim do not charge again.
  Fees due stay funded liabilities. [Sources: DESIGN, Protocol fee on sponsor
  cash][HB-DESIGN]; [STAGE1_SPEC §4][HB-S1].
- **Service-fee direction ratified 13 Oct 2026; principle 7 wording pending
  Jon.** The company may separately charge for services outside the protocol,
  including running seasons and boosts, on top of, never out of, rider money.
  This adds no deduction from protocol cash or boost budgets. [Source:
  FUNDING, Decision and option C.][HB-FUNDING]
- **Ratified 13 Oct 2026.** Intake caps are 2,000 SOL per enabled staking
  token, 500 per hill and 5,000 per deployment. Increases wait at least
  604,800 seconds; replacement proposals restart the delay. Reductions are
  immediate and can block further intake without seizing existing positions.
  **Caps are running totals of deposit-time basis per staking token, hill
  and deployment.** Amounts/delay: STAGE1_SPEC §3 and diamond.yaml
  `stage1.pilot_caps`. **Measurement source: Tim, 13 Oct 2026; STAGE1_SPEC
  amendment pending on branch `codex/boulderroller-v2-0jc1s-stage1-custody`**
  ([authorities brief][HB-BRIEF]). The current §3 formula
  `max(B, ceil(U * r))` is resolved by that decision in favor of deposit-time
  basis totals. **Program state, 9 Nov 2026:** the amounts are implemented,
  the delay is not. `initialize_city` writes the three caps once
  (`stage1.rs:564` to `:566`) and no instruction raises or lowers them, so
  today only a program upgrade changes a cap, and the single upgrade key has
  no timelock.
- **Ratified 6 Oct 2026; mechanics 13 Oct.** Founding lots lock for 26
  elapsed weeks from bonding; later lots choose 0/13/26/52 weeks from deposit.
  Notice can start only after lock expiry, lasts four elapsed weeks and names
  a positive remaining basis amount. One pending request per lot; cancellation
  and restart begin a new full notice. Owner authorization applies at each action.
  Contractual eligibility is separate from provider liquidity. [Sources:
  DESIGN, Withdrawal notice / Stake added after bonding; STAGE1_SPEC §4.][HB-S1]
- **Ratified 13 Oct 2026, ordinary exit.** Sweep real surplus, then partition
  requested basis proportionally: `U_exit = floor(U * B_exit / B)`.
  Partition rounding dust belongs to the owner, never riders. Sub-token
  partial exits fail atomically. The exiting part leaves active backing and
  future DUNG weights immediately; ordinary donated yield continues through
  notice/deactivation until actual return, when surplus is swept again.
  Pre-bond reserves and owner dust, including their appreciation, stay with
  the owner. No instant liquidity is inferred from the model. [Source:
  STAGE1_SPEC §4.][HB-S1]
- **Ratified 13 Oct 2026, stale-rate exception.** If an asset's rate has
  been stale for seven days, an owner past their lock and notice may exit in
  kind with **all of the lot's remaining tokens**; unharvested yield leaves
  with them. **Source: Tim, 13 Oct 2026; STAGE1_SPEC amendment pending on
  branch `codex/boulderroller-v2-0jc1s-stage1-custody`** ([authorities
  brief][HB-BRIEF]). **Implemented in the program:** the seven days start
  when `record_stage1_provider_outage` (`lib.rs:3949`, `stage1.rs:379`) first
  records an outage, which it accepts only when the pool is unreadable or at
  least two epochs behind; `exit_rate` (`stage1.rs:1175`) then allows the
  in-kind exit. The clock therefore runs from the first recorded outage, not
  from the moment the rate went stale. Tested in
  `protocol/anchor/tests/stage1_rate_adapters.spec.ts:517`.
- **Ratified 13 Oct 2026, stale tokens count as zero.** While a staking
  token's rate is stale, a hill's pledges in that token count as zero toward
  its bonding line instead of blocking other pledges or the bond, so one stale
  or delisted token cannot jam a hill. Lots in a token that is stale when the
  hill bonds are not founding lots; they stay cancellable, and once the rate is
  fresh their owner may convert them into ordinary stake with a chosen lock.
  **Source: Tim, 13 Oct 2026, after the milestone 1a custody review;
  STAGE1_SPEC amendment pending on branch
  `codex/boulderroller-v2-0jc1s-stage1-custody`** ([round 3 brief][HB-R3]).
  **Implemented in the program:** `fresh_campaign` (`stage1.rs:760`) gives
  lagging and unreadable token slots zero value toward the line without
  blocking other tokens. Tested in
  `protocol/anchor/tests/stage1_rate_adapters.spec.ts:329` and `:451`.

### 16.4 Weekly riding and money

- **Ratified 6 Oct 2026; mechanics 13 Oct.** Weeks run Monday 12:00 UTC
  to Monday 12:00 UTC. Ordinary yield, sponsorship and DUNG admit uploads
  of rides at most seven days old into the upload week, preserving original
  sporting time. The earliest admitted upload owns the paid ascent for each
  hill/person/UTC ride day; duplicate paid ascents are excluded across weeks.
  Separately verified, genuine tribute receipts may contribute climb-TSS
  without another paid ascent. Freeze uploads, seats, earned Legend, field
  and assets at close; finalize in order after 86,400 seconds, including
  empty weeks. A late keeper never substitutes today's inputs or reopens a
  claim set. [Sources: DESIGN, Late uploads; STAGE1_SPEC §§2, 5.][HB-S1]
- **Ratified 6–7 Oct 2026; mechanics 13 Oct.** After the yield fee, split
  available rider money **65% ascents / 25% occupied top ten, equally /
  10% earned Local Legend**. Cash sponsorship/boosts pay that split without
  a fee deducted from the rider budget and can fund non-live or unbonded hills
  in an admitted city; donated yield is live-gated. Below five riders,
  ascent pay can flow while both
  record buckets wait. Empty ascent/board/Legend buckets wait with their
  identity intact. [Source: STAGE1_SPEC §§5–6; DESIGN, Stage 1 / Minimum
  field.][HB-S1]
- **Ratified 13 Oct 2026.** Use exact integer Hamilton apportionment:
  largest fractional remainder, then ascending UTF-8 key bytes. Coalesce
  equivalent funding tranches before allocation without losing source lineage,
  age or eligibility. Combine all positive entitlements per person/hill/week/
  asset, including released holds and inactive record holders. Exclude zeros;
  use the exact middle-pair mean for an even population. The cash cap is
  `floor(3 * median)`. Never add unlike assets at an invented price.
  Process pieces in original-week/source-ID/bucket order; redistribute excess
  by eligible ascents within the original fixed headroom, then hold any rest.
  DUNG is outside this cash cap. [Source: STAGE1_SPEC §5.][HB-S1]
- **Ratified 6 Oct 2026; ageing/claims ratified 13 Oct.** Non-live yield
  and unpaid buckets retain asset, hill, source, reason and original
  distribution week. At age 26 weeks, expiry takes precedence over release:
  reserve the money for the shared pool, with no later originating-hill claim.
  Until stage 3 exists it stays held; its eventual internal handoff is not
  new income. Assigned, unclaimed leaves never expire under this rule.
  [Sources: DESIGN, Stranded money; STAGE1_SPEC §6.][HB-S1]
- **Ratified 13 Oct 2026.** Boosts are fully escrowed, irrevocable USDC,
  starting in a future full week for 1–13 riding weeks. The immutable budget
  is shared equally across selected hills/ride weeks, with the normal split,
  field and cap, no fee, no DUNG and no refund. Qualifying ascents use the
  original ride week/window and must upload within seven days and strictly
  before that ride week's close plus 24 hours. Late uploads get no separate
  tail budget, reopened root or second boost week. Board/Legend shares use
  that ride week's frozen seats/field and need not be window riders. Excess
  stays with window-eligible ascents; unused cash retries only through the
  last riding-week settlement, then waits for the 26-week pool fallback.
  [Source: STAGE1_SPEC §§6, 9; diamond.yaml `stage1.boosts`,
  `stage1.mechanics`.][HB-S1]

### 16.5 DUNG issuance

**Ratified 8 Oct 2026; admission mechanics ratified 13 Oct.** Bonded-hill
DUNG is constant at **1 per 1,000 climb-TSS in every year**, without lifetime
caps, halvings or a tail. The hill must already be bonded at opening and have
the seasonal field; the original riding must occur at or after bonding. Use
the upload week's admitted tribute. The reference uses TSS in millionths and
DUNG in nano-units: potential issuance is
`floor(TSS_micros * 10^9 / (10^6 * 1000))`.
Sub-unit dust, below-field weeks and partial bonding weeks stay unminted with
no catch-up. Live controls donated yield, not this separate bonded/field
admission. [Sources: DIAMOND, Settled on 8 October; STAGE1_SPEC §§2, 7.][HB-S1]

**Ratified 6 Oct 2026; mechanics ratified 13 Oct.** Split potential issuance
**50% riders / 50% backers**. Within riders' half, **55% goes to top ten,
35% to post-bond verified ascents, 10% to earned Legend**. Missing recipients
leave their share unminted. Backer weight is opening
`min(basis, floor(units * rate)) * lock_weight * founder_multiplier`, aggregated
by owner; exiting lots/zero weights are excluded. The 0/13/26/52-week lock
weights are 0.25/0.5/0.75/1.0, falling to 0.25 at the first opening after
expiry. [Sources: DESIGN, DUNG split; STAGE1_SPEC §7.][HB-S1]

**Reference model: equal shares; not separately ratified.** The source text
sets the 55% top-ten bucket within the riders' half but does not define its
division among seats. The `_dung` reference implementation weights each board
seat equally. This implementation evidence does not independently ratify a
replacement DUNG rank allocator. [Source: `tools/stage1_reference/model.py`,
`_dung`][HB-MODEL].

**Ratified 8 Oct 2026, the one launch exception; timing ratified 13 Oct.**
Founding pledges, including seed pledges, double their weight **inside the
fixed backer half** for the hill's first 26 full opening-bonded weeks. A bond
in city week `b` starts the bonus at `b+1` and ends it at `b+27`; transactions
at a boundary follow the snapshot. Non-live/below-field weeks still count,
and city season boundaries do not truncate or restart it. Lock expiry can
lower the underlying weight independently. This never doubles issuance.
[Sources: DIAMOND, Settled on 8 October; STAGE1_SPEC §§7, 9.][HB-S1]

**Ratified 13 Oct 2026; local/offline evidence.** Reference `DungMint`
allocations plus unminted units equal potential. They are mint instruction
data, not mint transactions, market value or money for rider claims.
[Source: STAGE1_SPEC §7.][HB-S1]

### 16.6 Funded claims and accounting

**Ratified 13 Oct 2026.** Reserve each asset before publishing one immutable
Merkle-sum claim set per deployment/city/hill/week/asset, one positive leaf per
person bound to their registered recipient. Include empty roots for admitted
assets with no payable leaves. Authenticate claims and recipient, check
membership, mark each leaf once atomically, and prevent replay/redirection.
Publication cannot be repeated. Exact serialization, hash domains, sums and
proof rules are in STAGE1_SPEC §8. Durable proofs and authorized snapshot
attestation remain production requirements; membership never proves a person
rode or that the allocation is fair. [Source: STAGE1_SPEC §§2, 8.][HB-S1]

**Ratified 15 Oct 2026, automatic payout.** Once a week's claim set is final,
BoulderRoller's keeper submits every registered recipient's claim itself: cash
at once, DUNG after its 48-hour wait. A rider signs only to register their
recipient. Claims stay permissionless, and value can reach only the registered
recipient; a rider may still submit their own. After every leaf in a set is
paid, the set and that week's other records close, returning their rent to
whoever prepaid it. **Source: Tim, 15 Oct 2026, after the release review measured
permanent weekly-record rent at about 6.7 SOL a year for 10 hills;
implementation pending on PR #96 and the keeper.**

**Ratified 13 Oct 2026.** Enforce the invariant separately for each asset,
with outstanding holds/claims rather than counting repeated carries as new
lifetime obligations:

```text
paid_lifetime + fees_assessed_lifetime + claimable_outstanding + held_outstanding
    = realized_net_income_lifetime + admitted_cash_lifetime
earnings_custody = fees_due + claimable_outstanding + held_outstanding
deposits + admitted_cash
    = lot_units + owner_reserves + owner_returns + earnings_custody
      + paid_lifetime + fees_paid
```

Net income is after provider costs and before the protocol's yield fee; assessed
fees include due and paid exactly once. Principal, owner reserves, rate
appreciation, DUNG and internal carries are never new income. Claims move
outstanding value to paid, and rejected actions roll back atomically. A green
reference equality is not proof of production custody or ownership.
[Source: STAGE1_SPEC §8; DIAMOND principle 1.][HB-S1]

### 16.7 Later claims, shared pool and markets

- **Ratified 6 Oct 2026; field rule 8 Oct.** Stage 2 waits for actual CAL
  buyers. CAL remains one per eligible TSS; climb CAL is staked by default
  on its hill with a 104-week timer renewed by each ascent. Riders can take
  it back at any time, ending the claim. Capital locks for a chosen duration
  up to 104 weeks with no early exit.
  Claims take 20% of the riders' yield share (18% of yield); direct riding
  pay keeps 80% of that share. Below the field, claims wait and their share
  stays with every rider. The public unlock calendar and committed claim
  stream are conditional information, not a guaranteed market/redemption
  floor. [Sources: DESIGN, Stage 2 / Back and dump; DIAMOND, Settled on
  8 October / CAL's floor.][HB-DESIGN]
- **Proposed design details, not separately ratified.** The stage-2 weight
  formula, 40% capital weight and 12-week verified-work window come from
  DESIGN's Stage 2 body, not its settled CAL-claim call. The 40% describes
  weight, not a payout cap. The formula remains in that design source; this
  amendment does not supply definitions absent from it. [Source: DESIGN,
  Stage 2, Boost.][HB-DESIGN]
- **Ratified 6 Oct 2026.** Stage 3 starts with gifts and at least two bonded
  hills, independently of stage 2's market trigger. The shared pool contains
  gifted staking yield (principal retained, ordinary yield fee), fee-free
  cash, actual trading fees (assumed zero until observed) and season-stranded
  money. It pays riders only by the normal split and cash cap, never CAL
  claims, voters or backers. Cap each hill at twice its share of the week's
  verified bonded-hill ascents; send excess to other hills by ascents.
  [Source: DESIGN, Stage 3 and settled Pool cap / Pool start.][HB-DESIGN]
- **Ratified 6 Oct 2026.** DUNG voting weight is amount × weeks left / 104.
  A bonded-hill ascent renews a rider's timer; a backer's stays full while
  backing remains and decays after exit. Received DUNG votes only when
  time-locked, at 40% weight. Votes stay until changed and control only
  weekly pool money, not principal, records or rules. Pool gifts earn a
  title, never DUNG; no protocol bribe market or payment for voting exists
  in this design. DUNG stays transferable without a market under zero-start.
  [Source: DESIGN, Stage 3 and settled Vote weight / Bribes.][HB-DESIGN]
- **Ratified 13 Oct 2026.** Once CAL is tradable under the zero-start market
  trigger, earned CAL may be sold immediately or retained by choice; sale
  cash and held-token value are separate. This leaves §15's no-market posture
  intact until the trigger. Every payout is funded and riders are paid in
  every phase.
  "Rider pay does not guarantee a profit on retained tokens or cover every riding cost."
  Trading profit is separate: it can come from
  later buyers without new backing and does not establish prior rider
  funding. The earlier universal promise that no trader profits before
  paying riders is retired. Market language needs Jon's review before any
  public promotion. [Sources: DIAMOND, Markets and whales][HB-DIAMOND];
  [DESIGN, Stage 2][HB-DESIGN]; [CHECKLIST item 12][HB-READY].
- **Hardened ladder trigger ratified 13 Oct 2026.** Stage-2 price ladders
  require sufficient market depth, an independent price reference and a real
  riding field. **Proposed:** escrowed price steps, step caps, their activation
  mechanics and the no-unwind rule. Production oracle selection, numerical
  thresholds and the tournament's synthetic reference are not ratified
  production settings. [Sources: DIAMOND, Markets and whales / Price
  ladders][HB-DIAMOND]; [diamond.yaml `ladder` and `model.whale`][HB-PARAMS].

### 16.8 Supersession, cutover and source boundaries

**Prospective scope ratified 8 and 13 Oct 2026; cutover week open, not deployed.**
Only future bonded-hill issuance changes. Existing CAL principal, accrued
DUNG, carry/claims and historical receipts keep their original entitlement;
there is no retroactive resplit, remint or cancellation of old obligations.
The legacy reservation safeguards in §8 continue to protect those liabilities.
[Sources: DIAMOND, Settled on 8 October][HB-DIAMOND]; [STAGE1_SPEC §9][HB-S1].
The implementation plan calls for a new versioned module rather than repurposed
CAL-vault fields, with an explicit cutover Settlement Week before new issuance
begins. Only that week's choice remains open; no week or migration is selected
here. [Source: STAGE1_PLAN §1][HB-PLAN].

The precise retained-statement/replacement register is in
[FRESHEST_SPEC §1a](FRESHEST_SPEC.md#superseded-cal-vault-statements-and-cutover):

- **Ratified 6 Oct 2026:** paid activation becomes pledge-to-bond; the old
  55/27/3/5/10 split and wallet-count unlock become separate rider cash and
  rider/backer DUNG allocations; CAL's claim moves to stage 2; cash board
  allocation is flat; fee channels become yield-only; DUNG votes steer pool
  money, not rules. [Source: DESIGN, settled calls / current-model comparison.][HB-DESIGN]
- **Ratified 7–8 Oct 2026:** the five-rider field gates board/paid records
  and DUNG; CAL claims also wait; Founder is title only; bonded-hill DUNG
  lifetime caps and halvings retire in favor of constant issuance.
  [Sources: DESIGN, Minimum field; DIAMOND, Settled on 8 October.][HB-DIAMOND]
- **Ratified 6 Oct; mechanics 13 Oct 2026:** new-module paid weeks use
  seven-day upload admission, with the ratified boost ride-week exception;
  unassigned holds become pool-only after 26 weeks, while assigned claims
  never expire. These replace the legacy 30-day/oldest-open-week admission
  and indefinite empty-seat carries only for the new module. [Sources:
  DESIGN, Late uploads / Stranded money; STAGE1_SPEC §§5–6.][HB-S1]

**Proposed / unproven implementation — [STAGE1_PLAN §§2, 5–7][HB-PLAN],
[STAGE1_SPEC §9][HB-S1].** Candidate LST adapters (jitoSOL, mSOL, JupSOL),
accepted mints, freshness bounds, identity attestors, production TSS precision/integer
limits, durable proof access, custody authority and provider liquidity need
their own proof. A seven-day timelock multisig is the design's condition for
the fixed fee, not current deployment evidence; the plan's 3-of-5 threshold
and signer arrangement are proposals. The service-fee direction is **ratified
13 Oct 2026**; only principle 7 amendment wording awaits Jon ([FUNDING][HB-FUNDING]).
No legal conclusion or clearance is supplied here. Longer 104/208-week
backing locks, holder-concentration publication and a rider-app ban on buying
CAL also remain **proposed** ([DIAMOND, Seven alignment rules][HB-DIAMOND];
[diamond.yaml proposed keys][HB-PARAMS]).

**Source resolutions and remaining wording:**

1. **Resolved, ratified 13 Oct 2026:** in-kind payout replaces the SOL-only
   summaries. [STAGE1_SPEC §9, decisions 1–2][HB-S1].
2. **Resolved, ratified 13 Oct 2026:** deposit-time SOL basis replaces an
   original-token-count principal promise. [STAGE1_SPEC §9, decision 1][HB-S1].
3. **Resolved, ratified 13 Oct 2026:** held money and claims are outstanding
   balances, not lifetime sums of repeated carries. [STAGE1_SPEC §8][HB-S1].
4. **Resolved, ratified 13 Oct 2026:** losses stay with their lot
   ([STAGE1_SPEC §9, decision 1][HB-S1]), and principle 4 now reads "Backers
   risk only yield, plus any loss in their own staking token" (Tim, 13 Oct
   2026). Jon reviews the wording before public use.
5. **Resolved, ratified 13 Oct 2026:** boosts and the plan's mechanics are
   admitted by [STAGE1_SPEC §9][HB-S1] and [diamond.yaml `stage1`][HB-PARAMS].
   Ladder steps remain **proposed**; only the hardened trigger is ratified
   (Tim confirmed 13 Oct 2026 that steps, step caps and no-unwind stay proposed).
6. **Resolved, ratified 13 Oct 2026:** boosts have no per-ascent payment
   guarantee. Their money is irrevocable and reaches only riders, directly
   or through the riders-only pool, subject to field/cap/rounding/hold rules.
   [STAGE1_SPEC §§6, 9][HB-S1]; [DESIGN, Stage 3][HB-DESIGN].
7. **Resolved by Tim, 13 Oct 2026:** caps use running deposit-basis totals;
   STAGE1_SPEC amendment pending on `codex/boulderroller-v2-0jc1s-stage1-custody`.
   [Source: authorities brief][HB-BRIEF].
8. **Exception, not a conflict:** ordinary exit sweeps remain; Tim's
   **13 Oct** seven-day stale-rate exit is the narrow exception. Both hold;
   the spec amendment is pending on that custody branch. [STAGE1_SPEC §4][HB-S1];
   [authorities brief][HB-BRIEF].

[HB-DESIGN]: ../history/explainer-hill-bonding-2026-10-06/DESIGN.md
[HB-DIAMOND]: ../history/hill-bonding-diamond-2026-10-08/DIAMOND.md
[HB-PARAMS]: ../history/hill-bonding-diamond-2026-10-08/diamond.yaml
[HB-S1]: ../history/launch-readiness-2026-10-08/STAGE1_SPEC.md
[HB-PLAN]: ../history/launch-readiness-2026-10-08/STAGE1_PLAN.md
[HB-READY]: ../history/launch-readiness-2026-10-08/CHECKLIST.md
[HB-BRIEF]: ../history/codex-briefs-2026-10-13/authorities.md
[HB-R3]: ../history/codex-briefs-2026-10-13/stage1-custody-round3.md
[HB-FUNDING]: ../history/launch-readiness-2026-10-08/FUNDING.md
[HB-MODEL]: ../tools/stage1_reference/model.py
