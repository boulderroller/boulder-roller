# Boulder Roller Canonical Backend Truths

**Status:** ACTIVE
**Date:** 2026-04-17
**Updated:** 2026-10-20 - W/kg sharing by explicit default-off opt-in (Tim, 19–20 Oct); Threshold ratios (IF, percent of FTP, zones, training stress) owner-only, with on-chain training stress disclosed as revealing Threshold (Tim, 20 Oct); legacy W/kg effort leaderboards unmounted; 2026-09-01 - forward-only measured Climb-TSS Vault tribute ratified by Tim; 2026-08-30 - ratified Option-A derived Threshold closure, atomic provisional holds, and held-ride release/recovery contract; 2026-08-02 - Strava-pattern ride audience and map-visibility contract; launch public-place geocoding boundary; 2026-07-17 - rider-scoped Balance-funded Vault authority; 2026-07-16 - exact program-version compatibility gate; canonical SPL DUNG supply projection and protocol-burn telemetry; historical fixed 10% power-weighted CAL tribute policy
**Ratified:** 2026-04-17 by Tim
**Audience:** Founding, protocol, backend, indexer
**Purpose:** Semantic source of truth for Boulder Roller's off-chain backend,
bringing it into coherence with PROTOCOL_TRUTHS.

This document sits **under** [PROTOCOL_TRUTHS](./PROTOCOL_TRUTHS.md) and
**alongside** [MOBILE_TRUTHS](./MOBILE_TRUTHS.md).

It sits **above** [TRUTH_CONTRACT_V1](./TRUTH_CONTRACT_V1.md), which defines
the low-level detector and economic invariants the backend must enforce at
runtime.

When backend work conflicts with protocol truth, protocol wins. This document
defines what must remain true inside the services that ingest rides, attest
them, drive allocation, and bridge the mobile edge to the on-chain protocol.

If the implementation conflicts with this document, this document wins on
semantics and the implementation must be brought back into coherence.

---

## 1. North Star

The backend is the **attester**.

Its job is to receive rides, interpret them under a versioned canonical form,
and commit their economic consequences to the protocol with cryptographic
evidence — so that every CAL credited, every climb completion recorded, every
DUNG distributed can be independently verified by any observer who holds the
original ride file.

The backend is not the protocol. The protocol lives on-chain. The backend is
the trusted interpreter that reduces rider evidence into on-chain facts and
nothing more.

The product is:
- an honest translator from fitness evidence to economic truth
- an auditable witness whose work survives the backend itself disappearing
- a boundary where attestation and settlement meet

---

## 2. Core Objects on the Backend

### 2.1 Ride Ingest Pipeline

The **Ride Ingest Pipeline** is the path from uploaded file to attested ride.

It has ordered stages:
- receive and authenticate the upload
- parse under a specific `parser_version`
- canonicalize into the versioned canonical form
- compute the canonical hash
- compare against the mobile-stamped preliminary hash
- detect patterns (climbs, steady, exploration)
- commit attestation and economic consequences on-chain

Each stage is distinct. Skipping or reordering stages silently is a P0 bug.

Ride and RideStatus expose independent `subjectStates` (`subject_states` on
snake-case status responses). Storage is `saved` only for a stored ride; matching
is `finalized` only after successful Phase 2, `counting` while matching is pending,
or `needs_review` after a Phase 2 failure. CAL uses its own policy/review reason or
settlement-finalized evidence. Held CAL and attestation alone supply no CAL word.
Known machine reasons remain attached; no rider-facing sentences are generated.
The wire words map to Saved, Counting, Finalized, Needs review and Not counted.
Portfolio positions expose the same optional subject map. Active LP and pending
DUNG alone do not prove finality of position or collection, so those subjects are
omitted. Non-owner projections withhold the CAL subject with the existing economy
fields. Existing processing transitions and enums remain unchanged.

### 2.2 Ride Attestation

The **Ride Attestation** is the backend's primary output.

It is the cryptographic commitment — per PROTOCOL_TRUTHS §2.3 and FIX_PLAN P5 —
that a ride happened and was interpreted under a specific parser version. It
anchors either the ordinary economic consequences frozen at admission or the
single eligible Threshold-release child authority described below.

An attestation carries:
- `ride_hash` — deterministic from the canonicalized trace
- `parser_version` — the canonical form that produced the hash
- `completed_at` — ride event time, from the file (not upload time)
- `rider` — the wallet credited for the effort
- structural replay protection via child receipts

An attestation is immutable once committed. Economic consequences derive
from it and its receipt-protected child authorities, not from the raw file and
not from any projection.

### 2.3 CAL Allocation

**CAL Allocation** is the backend's direct credit of CAL to a rider for
attested effort.

Under V4-A, ordinary allocation is direct `credit_cal` tied to the
RideAttestation. The old Merkle-batched claim path is deleted. A provisional
Threshold release uses `credit_released_cal`, which is tied to both the same
RideAttestation and its one-time `HeldRideReleaseAuthority`; there is no
allocation step that does not reference an attestation.

CAL credited must equal CAL derivable from the attested ride. The backend
does not invent CAL that the attestation does not support.

Rewardable TSS comes only from the versioned `workout-parse` metrics engine.
That engine preserves explicit zero-watt coasting, excludes pause gaps over
30 seconds from effort duration, and records sensor sample count and coverage.
Automatic CAL requires at least 30 power samples, at least 50% power coverage,
and an NP-capable continuous power window. Route estimates, compatibility formulas, and
heart-rate-only estimates remain useful ride context but cannot mint CAL until
their required rider thresholds are independently trusted and versioned.

Manual rider-profile FTP is retired. Training display and CAL share the derived
Threshold authority, while CAL uses an immutable sealed snapshot selected for
the activity's economic authority time.
Verified versions are append-only and changes activate no earlier than the next
Monday 12:00 UTC training-week boundary. Under the ratified Option-A closure,
every accepted source-eligible fit is recorded and the rider's
`economic_candidate_w` is the lifetime maximum of all valid 50-500 W fits.
The first valid fit queues establishment; later eligible improvements can only
raise, never reduce, the sealed economic authority. Monday-noon sealing is
isolated per rider: one failure becomes `repair_required` for that rider and
does not block other due riders. The 200 W network default is a display
placeholder only: a power-rewardable ride whose snapshot source is
`network_default` freezes an ordinary parent plan with zero counted TSS, zero
CAL, and no ordinary completion economics.

That zero parent and its provisional hold evidence freeze in one database
transaction. A malformed or conflicting hold rolls the parent plan back too;
there is no plan-only admission window for a retry to strand. Parser retries
may recompute the retained raw power pair, but the database preserves the first
successful pair while allowing unrelated ride-processing progress to commit.

When the rider's first derived Threshold is sealed, an eligible held ride gets
a distinct append-only release snapshot. That snapshot binds the established
Threshold authority, recomputed TSS and CAL, exact tribute budget, release plan,
and one-time child PDA without mutating the 200 W ride-time snapshot or parent
RideAttestation. Eligibility is frozen at establishment: the interval from
chain admission to Threshold effectiveness is allowed through exactly 16 weeks,
and a longer interval lapses permanently. If the Threshold was already
effective when a historical ride is admitted, its held duration is zero and the
release moves forward from upload; neither a sealed authority nor a settled
week reopens. Profile edits and queue payloads cannot change either frozen plan.
The database computes the release-plan hash from canonical stored JSON; planner
lease owners and other operational fields never enter permanent evidence.

Release execution is checkpointed in the only safe economic order: authorize
the child authority, credit the rider's released CAL once, record every V3
completion receipt, reconcile projections, then expose terminal rider state.
Repair from review preserves confirmed authority, CAL, and completion receipts
and resumes only the first unconfirmed step. An immutable conflict discovered
at terminal projection also enters review from unprojected `complete`; repair
returns it to that terminal checkpoint without replaying economic receipts. A
release is attributed to the Settlement Week frozen by its child authority. A
Vault behind that week waits;
except that the on-chain instruction may deterministically advance an empty,
finalizable lagging flow before the equality check. A nonempty lagging Vault
still waits, and a Vault already ahead is an operator-review conflict. Receipt,
event flow, and indexed child authority must all carry that same week.

The joined lifecycle resolver exposes `held`, `lapsed`, `planning`,
`not_counted`, `under_review`, `releasing`, and `released`; ordinary rides skip
that read entirely. The private operations view and reason-required repair RPCs
are the supported exits from planner or execution review. Recovery isolates one
failed item from the rest of each lane, and its worker time limit stays shorter
than the database lease.

Deleting a mutable rider-visible ride does not erase its frozen economic
identity: the hold, chain-admission, parent plan, and release snapshot retain
the original UUID and canonical evidence without a restrictive ride foreign
key. If exact release economics finish after the mutable ride row is gone,
terminal recovery still validates the indexed chain authority and then records
the omitted rider projection as complete; it neither recreates the ride nor
loops forever.

The deployed API lifespan owns the live convergence clock independently of
NATS and legacy Celery configuration: sealing runs immediately and every 60
seconds, while held-ride release recovery runs immediately and every 15
seconds. Passes do not overlap, one failed pass retries on the next interval,
and each pass times out before its lease. If this runtime cannot initialize,
API startup fails instead of advertising a healthy service with inert
Threshold work. Explicitly disabling it also disables automatic convergence
and is not a production-ready state.

#### CAL Tribute Plan

The ratified forward-only policy is `cal_tribute_segment_tss_v2`. The rider
receives the full attested CAL through `credit_cal`; tribute is a separate Vault
flow-meter input and is neither withheld from the rider nor minted as CAL. For
each eligible Climb, the backend freezes its own measured TSS:

```text
segment_tss_base_units_i = floor(
  segment_np_duration_s_i * segment_np_milliwatts_i^2 * 100 * 1_000_000_000
  / (reward_ftp_w^2 * 1_000_000 * 3_600)
)
exact_tribute_budget_base_units = sum(segment_tss_base_units_i)
```

Climb-window NP must come from the same versioned, zero-preserving, pause-aware power
stream that authorized CAL. NP is frozen as integer milliwatts together with its
NP duration, and every Climb amount is floored independently to one CAL base
unit. The immutable ride-time reward FTP supplies the denominator; mutable
profile FTP never enters the plan. Missing, insufficient, or zero Climb-window
power produces zero tribute with no gradient proxy, while completion and
leaderboard evidence still proceeds. One fastest qualifying traversal per ride
and Vault supplies the existing single receipt. Overlapping eligible climb
windows require review rather than double counting, and the measured sum never
exceeds full attested CAL. Historical plans are preserved byte-for-byte.

The frozen plan records the tribute policy version, exact measured sum,
authoritative Climb-window NP evidence, immutable reward-FTP provenance, and
final base-unit amounts. PostgreSQL recomputes the formula. On-chain receipts
bind each exact amount and the ride PDA enforces the full-attested-CAL ceiling;
retries and historical plans must not reinterpret either under a later policy.

### 2.4 Settlement Week Execution

**Settlement Week Execution** is the backend's role in finalizing economic
truth on the settlement clock (PROTOCOL_TRUTHS §4, FIX_PLAN P7-P8).

The backend:
- waits for the 24-hour grace window after each wall-clock epoch boundary
- derives per-bucket distribution inputs from on-chain vault state
- submits the `finalize_settlement_week` instruction
- does not hold entitlement state itself — the chain does

Post-finalization, the backend must not retroactively rewrite the finalized
epoch. Rides attested after finalization with `completed_at` inside the
finalized window record on-chain for provenance but have zero economic
effect.

### 2.5 Indexer

The **Indexer** is the backend's projection engine.

It streams on-chain PDA changes into read-optimized tables that power
dashboards, leaderboards, feeds, and BoulderScan. It is a cache.

The indexer is never authoritative for transaction construction, settlement
math, or economic decisions. Transaction builders read from on-chain
`ProgramConfig` by RPC (PROTOCOL_TRUTHS §5, FIX_PLAN P11).

Backend and indexer compatibility is exact, not best-effort. Their expected
program version is generated from `protocol/program-version.json`. Before a
backend path uses `ProgramConfig` to construct an economic transaction, and
before the indexer projects versioned program state, it compares the on-chain
`ProgramConfig.program_version` with that generated value. Missing,
unavailable, older, or newer values all fail closed. The indexer must not write
a projection from a decoder whose ABI version does not match the live program.

### 2.6 Backend Authority

The **Backend Authority** is the signer the backend uses to invoke
restricted instructions.

It can:
- commit RideAttestations
- credit CAL to attested riders
- finalize settlement weeks
- elect Local Legends at term boundaries

It cannot:
- alter what a ride attested to after the fact
- bypass cryptographic commitment
- mint DUNG outside distribution rules
- modify on-chain program state without instruction authority

The Backend Authority is a signer, not a source of truth.

It is also not rider consent. For Balance-funded Deposit CAL, Withdraw CAL, and
CAL+USDC Vault creation, the coordinator must select `rider_session`, require a
live rider-session identifier, and build the exact on-chain operation intent.
The configured rider-session key signs; the Backend Authority and Boulder
Roller fee payer may not replace it. `app_balance`, Rider Account login, UI
confirmation, and custody ownership alone are invalid authority models for
these value actions. A route without a live session stops before transaction
construction or uses the explicit wallet-confirmation fallback.

---

## 3. Three Times

The backend reasons about three distinct timestamps per ride. They are not
interchangeable (FIX_PLAN P6).

### 3.1 `completed_at`

The event time of the ride, derived from the ride file itself.

Authoritative for:
- leaderboard ordering
- Local Legend eligibility
- Record Board insertion
- the 30-day economic age guard

It is preserved as the ride's historical provenance. It does not choose a
tribute payout bucket: accepted tribute enters the Vault's lifetime tribute
flow meter at the oldest open Settlement Week.

### 3.2 `settled_at`

The time the chain accepted the attestation.

Operational. Used for audit ordering and replay detection. Not authoritative
for any economic outcome.

### 3.3 `finalized_at`

The time one Settlement Week payout became immutable.

Authoritative for that payout and its resulting carry. It does not freeze the
all-time Record Board or reject an otherwise valid delayed ride. A later
accepted completion keeps its original `completed_at`, updates timeless climb
truth, and contributes to the oldest open Settlement Week rather than changing
the already finalized payout.

---

## 4. Three Representation Layers

Mirrors PROTOCOL_TRUTHS §5, interpreted for the backend.

### 4.1 On-Chain Truth

The chain holds binding state: climb identity, vault state, KOM, Record
Board, Local Legend seat, carry balances, stake positions, attestations.

The backend reads and writes this state through instructions whose authority
is explicit. The backend never treats its own tables as canonical over the
chain.

### 4.2 Attested Truth

Off-chain but cryptographically bound: raw ride files, GPS traces, parser
inputs, derivation intermediates.

Attested truth is reproducible. Given the file and `parser_version`, any
observer must be able to recompute `ride_hash` and verify the on-chain
attestation.

The backend retains what it needs to reproduce attestation. It does not
retain more.

### 4.3 Projected Truth

Indexer tables, leaderboard views, dashboard aggregates, BoulderScan surfaces,
feeds, heatmaps.

Projection serves reading. Projection is never the source of truth for
payouts, eligibility, or settlement. If the projection disagrees with the
chain, the chain wins and the projection is repaired.

---

## 5. Backend Roles

### 5.1 Attester

The role that ingests rides, canonicalizes them, and commits attestations.

Attestation is cryptographically committed (FIX_PLAN P13). The backend is
not a trusted issuer — it is an attester whose output is independently
verifiable.

### 5.2 Executor

The role that submits on-chain transactions against attested state:
`credit_cal`, `finalize_settlement_week`, `elect_local_legend`, Record Board
updates, `increment_beetle_score`.

The executor uses the Backend Authority signer and does not hold any
economic state the chain does not already hold.

### 5.3 Projector

The role that maintains the indexer and read-layer tables.

The projector is downstream of on-chain state. It may lag. When it lags,
UX surfaces must show that truth is pending, not fabricate it.

---

## 6. The Ingest Pipeline Truths

### 6.1 Parser Version Is Binding

The `parser_version` stamped at attestation time is the parser version that
produced the canonical form. Changing the parser in the codebase does not
change the attestation. Old attestations remain verifiable against the
parser version they were stamped with.

Parser version changes require a versioned canonicalizer and a migration
plan. Silent reinterpretation of old rides is forbidden.

Non-semantic edits to guarded parser files may retain the version only with
the declared and verified exemption in the
[parser semantic gate](design/RIDE_CANONICALIZATION_SPEC.md#parser-semantic-version-gate).

V5 is current. It retains V4 ride-field, metrics, and canonical-v2 geographic
matching semantics while binding the authoritative climb-window power metrics
used for CAL tribute allocation. V1-V4 remain replayable.

### 6.2 Canonical Hash Is Deterministic

`ride_hash` is a pure function of `(canonicalized_trace, parser_version)`.
Same inputs always yield the same hash. No randomness, no timestamps, no
ambient state.

This is the same invariant TRUTH_CONTRACT_V1 §1 enforces for climb
signatures, applied to rides.

### 6.3 Hash Compare Is the Attestation Gate

When the mobile-stamped preliminary hash is present, backend recomputation
must match it.

A match confirms the file arrived intact and was interpreted the same way on
both sides. A mismatch is a signal — parser drift, transport corruption, or
tampering. A mismatch must be surfaced (telemetry, Sentry) and must not be
silently laundered into a successful attestation.

Older rows created before the mobile attestation loop existed may be read
without a preliminary-hash comparison for backward compatibility. New ingest
must classify the ride by provenance tier before it can enter automatic
economics.

The preliminary hash is the first-party recorder witness, not the universal
definition of a trustworthy ride. Finished Boulder Roller must support multiple
trusted witness paths without weakening economic invariants:

- `first_party_recorded` rides are recorded by the BR client. They must carry
  the stop-time attestation stamp (`parser_version` + `preliminary_ride_hash`)
  described in MOBILE_TRUTHS. Missing or mismatched stamps force abstention from
  automatic economics until reviewed.
- `trusted_provider_sync` rides arrive from an authenticated provider sync
  (Garmin, Strava, Wahoo, etc.). They are not expected to carry BR's stop-time
  preliminary hash. Their witness is provider provenance: linked account,
  provider activity id, source payload/stream provenance, duplicate lock, and
  freshness/integrity checks. A trusted-provider source label without a provider
  activity id is not enough for automatic economics, and duplicate provider
  activity identity must abstain. The database enforces the provider activity
  id requirement and rejects duplicate normalized provider identities for new
  ride rows; retry paths must re-enqueue an existing pending provider ride
  instead of creating or marking a duplicate.
- `manual_file_upload` rides are user-supplied FIT/GPX/TCX files. They are
  allowed into automatic economics when canonical parse, timestamp sanity,
  effort evidence, integrity, duplicate/replay, and freshness checks pass. The
  source is lower-provenance than a recorder or provider sync, but it is not
  non-economic by definition.
- `legacy_unknown` rides remain readable/importable. They must not be used as a
  reason to weaken new ingest policy.

Automatic economic eligibility is therefore evidence-based:
canonical parse, timestamp sanity, effort/sensor integrity, duplicate/replay
protection, and a passing provenance tier. Source labels do not earn by
themselves; missing evidence abstains rather than guessing.

Overlapping files from one rider are admitted, but only seconds not already
claimed by an admitted plan can earn CAL. Claims use the canonical one-second
power buckets, excluding pauses longer than 30 seconds. Coggan TSS is computed
on the remaining runs; removed seconds never bridge an NP window. A fully
covered file freezes with zero CAL and no completions. Held plans claim their
seconds at admission, permanently, including after lapse or review. Legacy
plans keep their full recorded envelopes, with earlier plans winning any overlap.
Admission checks coverage atomically under the rider fence and recomputes after
a concurrent admission. There is no five-second overlap allowance.

Training TSS remains whole-file. When overlap trims a file, attested TSS is paid
TSS. An uncovered zero-value plan retains its whole-file integer TSS, as before;
clearing its empty CAL claim does not make it overlap-trimmed. Admission coverage
is frozen and bound into the plan hash so later claims cannot change that decision
on replay. Distance, vertical and ride count remain per file. Standard per-file Coggan TSS is not additive across
partitions. Missing native evidence needed for trimming, an integrity mismatch, or climb
tribute above paid CAL sends the ride to review. The stationary-recording gate applies to the
whole file and to its paid intervals. Copy slots S1 (partly counted), S2 (fully
covered), S3 (numeric caption) and S4 (iOS reveal note) remain empty for Tim;
no numeric caption or new iOS decoding is authorized by this change.

V5 plan hashes require a deploy boundary with no planned or phase-2-pending
plans. Migration 164 gives each ride frozen before it the effort span its plan
was backfilled with, so a replay compares that plan with itself, and a replayed
hold whose evidence hashes differently returns the stored plan (audited, or in
review if it was still live).

The canonical parse gate is format-neutral. FIT, GPX, and TCX must all reject
timestamps that move backward or span more than 48 hours before metrics or
canonical buckets are allocated. XML format detection uses the root element,
sensor extensions use namespace-local names, and missing elevation remains
missing rather than becoming sea level. Raw and decompressed inputs share the
same 100 MB ceiling.

### 6.4 Economic Consequences Are Derived Once

Per FIX_PLAN P5, every economic consequence of a ride (CAL mint, climb
completion, Record Board update, Local Legend participation, BeetleCard
score change) derives from a single RideAttestation, once. A provisional ride's
parent records zero counted TSS and CAL at upload; its only later economic path
is the one-time `HeldRideReleaseAuthority` child.

Replay protection is structural. Child receipts keyed by
`(ride_attestation, climb_id)` and `(ride_attestation, rider)` use on-chain
`init` semantics to prevent duplicates. The backend does not rely on its own
tables to prevent double-spend.

New ordinary climb-completion plans require evidence version 2. Before freezing
or submitting a step, the backend recomputes the chain's V2 hash over the
RideAttestation PDA, Vault PDA, whole-second time, and exact tribute base units.
The finalized receipt must decode as `ClimbCompletionReceiptV2` and match the
frozen version, amount, hash, and PDA before the step can be confirmed or
projected. Released completions use evidence version 3, whose hash additionally
binds the `HeldRideReleaseAuthority`; their receipts must also bind the release
Settlement Week and exact release-scoped tribute budget.

Historical V1 receipts remain readable, but they establish only completion
identity. They do not make a copied database tribute amount on-chain truth.
Pending V1 plans enter review at cutover; they cannot retry, auto-confirm, or
receive a non-reject review resolution. Client projections therefore expose
completion authority separately from tribute authority and may label an exact
tribute `onchain` only when `completion_evidence_version = 2` and the amount is
receipt-bound.

### 6.5 Vault Identity Is Ratified Canon

A ride may select the Vault that receives tribute only through a successful
traversal of one exact ratified canon revision. The match trace must carry the
registry row, stable `canon_id`, version, and canonical profile hash. Those
fields must decode to the same 64-byte D12 commitment stored by the indexed
V4-B Climb and its attached Vault.

Exactly one finalized Climb-to-Vault binding may survive. The Climb account,
Vault account, registry row, D12 commitment, and chain-derived activation
projection must agree. The fresh-empty constructor activation must have
`is_active = true` and exactly `seed_generation = 2`; operational status
strings are not authority.
Missing, multiple, stale, malformed, mismatched, or unfinalized bindings
abstain and cannot open a legacy fallback.

Detector-v1, detector-v2, DCT similarity, endpoint proximity, OSM tile
attribution, cached Vault IDs, and start-point-only matches are discovery
signals only. They may contribute privacy-bounded aggregate evidence to the
ClimbLab nomination queue, but they cannot authorize a completion, tribute,
Record Board write, Local Legend update, settlement input, or historical
replay. Detector output is stored with `economic_eligible = false` after the
cutover.

That demotion is unconditional: missing raw canon evidence, an under-review
ride, or a skipped economic-plan freeze does not restore detector authority.
Every retained detector climb carries `MATCH:canon_traversal_required`, its
top-level match trace is marked `discovery_only`, and detector-era
`vault_completions` are discarded before storage. An accepted D11 traversal
keeps its exact registry trace and proceeds to the activation gate. The plan
builder consumes the same frozen exact Climb/Vault/Activation binding returned
by that gate; it never replaces it with a generic Vault-by-ID row.

Vault creation accepts one immutable ratified registry-row ID. The backend
derives the name, metrics, canon lineage, version, profile hash, commitment,
and Climb PDA; the client cannot supply or override them. Prepare creates a
wallet-scoped, expiring reservation over that exact revision. Submit must match
the reserved transaction bytes and revalidate the same revision before chain
submission. Candidate, retired, stale, already attached, or changed revisions
fail closed.

The global `VaultCounter` is consumed only by that reservation path. Both live
wallet-funded constructors require `sponsor_authority` to sign and equal the
finalized `ProgramConfig.backend_authority`; `TxBuilder` partially signs the
exact prepared bytes with that authority before the rider signs. Direct DUNG,
direct admin, and Balance-funded creation helpers fail closed for V4-B because
they do not hold a canonical reservation. This prevents an otherwise valid
out-of-band constructor from taking a reserved ID, stranding the prepared row,
or creating a chain Vault the reservation-bound indexer must quarantine.

Registry measurements keep their compiler precision. The backend never rounds
or rewrites `canon_climbs.length_m`, `vert_m`, or `avg_gradient_pct` to make a
chain account fit. Its only scalar boundary is
`boulderroller_chain_metric_projection_v1`, evaluated with decimal
round-half-up arithmetic: length × 1 becomes whole meters, vertical gain × 10
becomes decimeters, and average gradient × 100 becomes basis points. Raw length
and vertical gain must be positive, raw gradient must be nonnegative, and the
projected integers must fit the V4-B `u32`, `u32`, and `u16` fields. The
post-publish registration artifact preserves the three raw values and carries a
separate, named `chain_metric_projection`; the registrar must recompute and
match every integer before submission.

The indexed Climb/Vault metric columns derived from those account integers are
immutable projections, not registry truth. The indexer binds them back to the
private registry with PostgreSQL `round(numeric)` at the same scales, including
explicit nonnegative checks, and quarantines an exact-projection mismatch. D12
does not contain these scalar fields: its commitment bytes and hash, Climb PDA,
and version-index PDA remain functions only of the frozen layout, `canon_id`,
revision, reserved bytes, and canonical-profile hash.

Quarantine is a projection state transition, not an audit-only log. A malformed
Climb or Vault observation atomically records the reason and closes any
same-or-older active projection. Quarantining a Climb also closes its attached
Vault while preserving the greater of the two observed slots, so out-of-order
callbacks cannot reopen economics. Stale valid observations remain closed;
only an exact valid re-observation at the preserved slot boundary or later can
recover each projection.

Once a reservation or on-chain attachment exists, committed canon fields and
corridor cells are database-immutable. A changed route, gate, profile, compiler
result, or provenance requires an explicit versioned successor; the predecessor
remains byte-identical. The current ratified revision is unique per `canon_id`.

The bounded V4-B bootstrap exposes only `new_record_board` successors. Although
canon policy reserves `carry_records_forward` for minor corrections, that mode
must fail closed until an on-chain continuity operation proves that the prior
Record Board survives on the successor. Storing the policy label without moving
the records is not continuity.

Receipt-less historical matches are never projected into
`vault_completions`. V4-A and malformed accounts are quarantined from new
economics. Generation-1 Vaults remain readable only for settlement of existing
pending state, Withdraw CAL, and Collect DUNG already owed; they cannot accept
a new activation.

### 6.6 Abstention Preserves Provenance

Per TRUTH_CONTRACT_V1 §7, rides or climbs that fail integrity thresholds
must abstain from economic actions but still record for display.

A ride that abstains is visible to the rider, attested off-chain, and
carries no CAL, no tribute, no Record Board, no BeetleCard delta. The
protocol owes nothing on abstained evidence.

### 6.7 Economic Ledger Append Is Database-Atomic

`economic_events` may be appended only through the service-owned
`append_economic_event` database function. The backend sends canonical decimal
text plus a required pipeline-version reference; PostgreSQL serializes each
wallet/denomination stream, derives `balance_after` from exact `NUMERIC`, computes
the event hash from those same stored values, and inserts the row in one
transaction.

Historical rows retain hash contract v1 and may retain NULL provenance. New rows
use the scale-neutral v2 hash contract and require provenance. Direct Data API
writes are not an alternate authority: rider roles cannot read or mutate the
ledger, and the service role receives read access plus execute access to the
append function, not direct table-write privileges.

---

## 7. Settlement Truths

### 7.1 The Settlement Clock Is The Chain's Clock

Settlement Week boundaries are wall-clock defined and enforced on-chain. The
backend submits finalization; the backend does not decide when a week ends.

### 7.2 The 24-Hour Grace Window Is Real

The grace window controls when the oldest open Settlement Week may pay. It is
not a ride-admission window. The backend must not finalize before the grace
closes, but a ride accepted by the 30-day economic age guard still records its
completion and enters the Vault's lifetime tribute flow meter after that
ride's historical week has finalized. Admission is frozen at the
`RideAttestation.settled_at` recorded by `record_ride`; completion and CAL do not
reopen the age decision against a later clock.

### 7.3 Finalization Is One-Way

Once `finalize_settlement_week` succeeds, that payout and its typed carry are
immutable. The all-time Record Board remains timeless: a later accepted ride
can enter at its original `completed_at`, and its tribute belongs to the oldest
open Settlement Week. The backend confirms every planned climb completion
before crediting CAL, so a chain failure is checkpointed as retryable
`recovery_pending` rather than silently producing CAL without climb effects.
The receipt-less legacy `record_vault_completion` and tribute-unbound V1
`record_climb_completion` ABI entry points fail closed. Backend production work
must use the V2 receipt-backed coordinator path. There is no V1 fallback after
cutover.

Threshold releases follow the same one-way rule through their separate V3
receipts. Their original `completed_at` remains sporting provenance, while the
child authority records the release week and every released tribute is proven
against that exact open Settlement Flow. The release coordinator confirms the
child authority, credits released CAL exactly once, confirms every completion,
then reconciles indexed receipt evidence before any terminal projection is
shown.

### 7.4 Per-Bucket Carry Is Typed

Empty or unfilled buckets carry forward **within their own bucket** (FIX_PLAN
P10). Record Royalty carry never funds stakers. Staker carry never funds
Local Legend. Stored carry never leaks between buckets.

The participation curve's current-week policy-locked staker amount is not
carry. It is reallocated into that same week's Record Royalty before either
bucket's post-allocation carry is calculated. `carry_stakers` therefore means
already-unlocked pro-rata integer dust only after the Vault carries the current
staker-remainder policy marker.

Deployed Vaults created before this policy used the same field for both locked
amounts and integer dust. Their first successful new-policy settlement
atomically moves the entire legacy value to Record Royalty, records
`StakerRemainderPolicyApplied`, and writes the policy marker into the retired
`reward_rate` layout slot. New Vaults start marked. BoulderScan must use that
event, not a guessed deployment date, when interpreting historical
`locked_staker_amount` events.

### 7.5 Allocation Is Discrete

Staker settlement is direct discrete allocation per settlement week, not
continuous accrual (FIX_PLAN P8). Harvest is a claim against
`VaultStake.unclaimed_rewards`, not a rate calculation.

The backend does not maintain parallel accrual tables. The chain holds the
entitlement; the backend only surfaces it.

### 7.6 Settlement Transport Is Prepared Before Signing

Settlement payout math remains one atomic on-chain instruction. Transport
preparation is separate: the backend creates missing recipient token accounts
idempotently, provisions or extends the Vault's managed v0 address lookup
table, and waits for finalized activation before an economic signature may
exist.

The frozen precondition binds the lookup-table generation, ordered settlement
account manifest, last extension slot, transaction version, and exact signed
size. The distribution builder rereads ProgramConfig, Vault, Leaderboard,
Local Legend, recipient accounts, and the complete `VaultStake` inventory at
finalized commitment. It must reproduce the frozen manifest and remain at or
below the 900-byte reviewed limit and 1,232-byte protocol limit.

Transport drift while the job is unsigned returns it to preparation. A job
with a prepared or accepted settlement signature is reconciliation-only and
must never be rebuilt as a legacy transaction. Lookup-table or recipient
preparation can retry without changing payout amounts, carry, recipient order,
or Settlement Week state.

Reconciliation blocks a missing Vault for operator review only when a successful
finalized response contains both a null Vault account and a valid VaultCounter
whose range excludes that Vault ID. Both accounts share the response slot. An
absence response must be strictly newer than the run's `source_slot_max`
(stored legacy NULL means zero); a counter alone cannot rule out a lagging node.
The SQL transition independently checks and locks that authoritative run floor.
An equal or older slot, in-scope hole, missing or invalid counter, RPC failure,
or non-finalized evidence remains `reconciling`. Proven absence records
`vault_absent_finalized` so automatic repairable-preflight recovery cannot reopen
the job. Only `confirmed` transitions
create settlement notification outbox events; a missing Vault sends no rider
notification.

Transient reconciliation failures use the existing `next_reconcile_at` schedule
and durable reconciliation evidence to back off exponentially, starting from
the greater of 60 seconds and the job's normal retry cadence, with a
3,600-second cap. Successful evidence resets the failure sequence. A fresh
job remains immediately eligible; submission attempts and lease ownership are
unchanged. This policy requires migration 167 before the corresponding worker
deployment.

### 7.7 Circulating DUNG Comes From The SPL Mint

The indexer projects two related but non-interchangeable chain truths into
`indexed_supply`:

- `DungMintState` supplies lifetime issuance, allocation-cap state, and
  Boulder Roller program-burn telemetry at its account response slot.
- The configured SPL DUNG mint supplies canonical circulating base units at a
  separately observed finalized slot.

The mint observation is written to `spl_mint_supply` with
`spl_mint_supply_slot` and is independently monotonic. Reconciliation reads and
repairs both sources. Before it subscribes or publishes a supply observation,
the indexer requires its configured mint address to match the immutable DUNG
mint decoded from finalized on-chain `ProgramConfig`; missing or mismatched
authority fails closed. BoulderScan, admin APIs, and any later read surface use
`spl_mint_supply` for circulation and carry exact decimal base-unit strings
across API boundaries. If the mint observation is absent, they report it as
unavailable; `total_minted - total_burned` and zero are not fallbacks.

---

## 8. Attester vs Authority

### 8.1 The Backend Signs, It Does Not Decree

Per FIX_PLAN P13: the backend is an **attester**, not an authority. What the
backend signs is cryptographically committed via `ride_hash` and
`attestation_commitment`.

A rider with the original ride file can recompute the canonical hash and
verify the backend attested correctly. If the backend attested falsely, the
rider sees the discrepancy; the cryptographic commitment exposes dishonest
attestation.

This is not trusted issuance. It is backend-attested with on-chain
cryptographic commitment.

### 8.2 Authority Is Granted By The Chain, Not Held By The Backend

The Backend Authority is a signer scoped by on-chain `ProgramConfig`. The
chain grants the backend explicit, narrow rights — commit attestations,
credit CAL, finalize settlement weeks, elect Local Legends at term
boundaries. That grant is the backend's authority. There is no authority
outside it.

The direction of the grant is single: **chain → backend → rider audits**.

- The chain delegates scoped rights to the backend via `ProgramConfig`.
- The backend acts within that delegation.
- The rider, holding their original ride file, audits whether the backend
  acted honestly.

Riders never delegate to the backend. This is the inverse of how most
software authorities work. In Boulder Roller the chain is the authority,
the backend is the scribe, and the rider is the auditor.

The backend may not:
- alter the Record Board except through on-chain instructions whose logic
  is fixed on-chain
- mint DUNG outside distribution rules
- change `ProgramConfig` without admin authority
- override abstention decisions without re-attesting under a changed parser
  version

### 8.3 Compromise of the Backend Does Not Compromise Attested Rides

If the Backend Authority key is compromised, the attacker can submit false
attestations **going forward**. Past attestations remain verifiable against
their ride files. The protocol's audit trail survives the backend.

This property is worth preserving in every design choice.

---

## 9. Privacy Boundary

The backend handles rider evidence across three layers with different
privacy postures. The boundary between them must never leak.

### 9.1 On-Chain

Per PROTOCOL_TRUTHS §5.1 and §10, on-chain holds compact binding state:
attestations, climb and vault state, KOM, Record Board, Local Legend, carry
balances, staker entitlements. Private ride evidence is never forced onto
the chain.

### 9.2 Attestation Keeps The Full Trace

Attested truth retains the original ride file, the canonicalizer inputs,
derived patterns, and sensor integrity report. Precise GPS traces live
here because verifiability requires them — the rider's ability to recompute
`ride_hash` against their own file is the payoff that makes attestation
trustworthy.

Attested truth is not a public surface.

### 9.3 Projection Respects Rider Endpoint Privacy

Projection surfaces — feeds, ride details, BoulderScan, leaderboards, maps
— default to trimming near the rider's declared private endpoints. Raw
polylines around ride starts and ends leak home, work, family. The rider
owns that boundary; projection honors it.

What the projection shows is the intersection of what the protocol needs
for its outcomes and what the rider has opted into surfacing.

Ride audience and map visibility are independent, frozen ride properties:

- rider-facing `Everyone`, `Followers`, and `Only you` map to stored
  `public`, `followers`, and `private`
- map visibility is stored as `show_all`, `hide_start_end`, or `hide_entire`
- the launch default for future rides is `public` plus `hide_start_end` at
  200 meters
- changing an account default affects only rides created afterward
- an explicit upload or provider-import override wins for that ride

The backend resolves and persists the complete privacy snapshot when it first
creates the ride row. File upload and provider import use the same request
contract. A missing, invalid, or unavailable settings read is not permission to
fall back to public; ride creation stops before route-file storage or a new
provider route/stream download begins. Retrying a pending provider import first
re-resolves, persists, and verifies the newly submitted snapshot on that exact
ride before it can be requeued. A completed duplicate is never rewritten.

`hide_start_end` removes points by cumulative traveled distance from the first
and last valid route points, not by a radius around a guessed address. Saved
privacy zones are then applied as an additional geographic mask. `hide_entire`
projects no route at all. The attestation layer retains the full trace, and the
owner receives that full trace; only non-owner projection is changed.

Zone masking applies to geometry, not only stored samples. If an original route
edge crosses or touches a saved privacy zone, that edge is hidden even
when neither sampled endpoint lies inside the zone. A public preview may reduce
detail only by preserving original adjacent edges as independent visible
fragments; it must never create a shortcut between non-adjacent points. Preview
serialization retains enough coordinate precision for the transmitted edge to
remain outside the mask. Fragment-aware clients render those pieces, while a
legacy single-line contract receives no points when doing so would reconnect a
hidden gap.

The server returns the resulting projection and its privacy metadata. Clients
must not decode a raw polyline and attempt their own privacy decisions. A
projection failure returns an unavailable or redacted-empty state, never the
unfiltered route and never a fabricated empty-success result.

Only `public` rides are eligible for public climb leaderboards. `followers`
and `private` rides may retain owner-visible completion and ranking context but
must not appear in public standings. For a public ride, a climb effort whose
measured start-to-finish span intersects a hidden endpoint or privacy-zone span
is also excluded from the public leaderboard. Privacy changes affect
projection eligibility, never whether the underlying ride traversed the Climb
or whether its attestation and economic consequences remain true.

Public climb, steady, and exploration leaderboards are projected from current
ride and rider privacy on every request. They are not served from a shared
response cache, so making a ride private or ineligible cannot leave its rider
identity publicly visible during a cache lifetime. Missing projection data
returns an unavailable response rather than a permissive or empty success.

The chain Record Board remains immutable technical and economic truth. The
rider-facing public Board is a read-time privacy projection: ineligible or
unresolvable entries are omitted, surviving entries keep their original chain
seat and competition rank, and no hidden seat is reranked or refilled. A KOM is
shown only when its exact winning entry remains publicly eligible; when it is
withheld, public contracts return no holder and no time rather than a
final-looking zero. Public preview responses are not shared-cacheable, so a
privacy edit cannot leave the former route or Board entry available through
stale cache.

Provider privacy metadata is not inherited. A Strava import applies the exact
Boulder Roller privacy snapshot supplied with the import request because
Strava map hiding is not transferred to third-party applications.

Raw power, heart-rate, cadence, speed, and temperature samples are owner-only;
non-owner ride views receive an explicit redacted-empty stream without querying
telemetry storage.

A rider's measured W/kg reaches signed-in and signed-out viewers only with
`users.share_wkg=true`, controlled through `/privacy/settings` (`privacy.v2`,
`shareWkg`). It defaults false. This consent applies wherever the effort is
otherwise visible, including the ride's climb list, and never changes ride or
map visibility. The owner always sees their known W/kg. Numeric body weight
is never returned to another viewer. Legacy `avg_power_w` / `avgPowerW` fields
remain measured-only; standard-mass estimates use separate kind, watts and
range fields. The legacy `/leaderboard` router remains unmounted until it
implements these viewer-specific rules.

A rider's Threshold (FTP) is owner-only in the same way. NP is public and FTP
equals NP divided by IF, so the API never gives another rider or a signed-out
reader a ratio against the Threshold or a value scaled by it, such as IF,
percent of FTP, zone tops and zone seconds, or training stress and Load.
Maximum heart rate is also owner-only. NP and
average power in watts stay public. The chain still carries Threshold-relative
values (the RideAttestation `total_tss` and the climb-TSS Vault tribute)
because CAL is paid from them, and the indexer serves them to BoulderScan.
With a ride's public NP and duration they reveal the Threshold. Tim decided on
20 Oct 2026 to keep them on-chain, keep every Threshold-scaled value
owner-only in the app, and say so plainly in the rider docs
(`docs/gitbook/rides/privacy.md`).

### 9.4 The Layers Do Not Leak Into Each Other

Projection does not override attested truth. Attested truth does not bleed
into projection. A rider's privacy zones shape what is shown, never what
is attested. An attestation challenge is answered with the attested file,
not with a projection.

### 9.5 External Geocoding Is A Narrow Public-Place Boundary

Launch public-place search may call a Nominatim-compatible provider only from
an authenticated backend endpoint after an explicit rider submission. The
backend normalizes but does not log the raw query, caches successful responses
including zero results in NATS under a hashed key, identifies Boulder Roller to
the provider, and keeps the upstream URL in server configuration. Provider,
configuration, cache, timeout, and malformed-response failures return an
explicit unavailable state; they never become an empty successful result.
Error monitoring strips request bodies, URL queries, referrers, and stack-frame
locals from both the geocoding and privacy-zone boundaries before an event or
transaction leaves the backend.

While public Nominatim is configured, the deployed API remains one process and
spaces aggregate upstream request starts by at least 1.05 seconds. A second API
worker or replica is forbidden until that timing gate has a shared coordinator
or the provider changes. This is a launch constraint, not a silent scaling
assumption.

Public-place geocoding never handles a rider's privacy-zone address. Privacy
zones use a device-provided or manually entered point sent only to Boulder
Roller; private home or work text is not forwarded to a public geocoder.

---

## 10. The Indexer Truth Boundary

### 10.1 The Indexer Is A Cache

The indexer is a projection of on-chain state. It may lag, it may stutter,
it may be rebuilt. It must never be authoritative.

Seat-lost notification transitions are event-time facts. When the notification
producer receives a board snapshot pair, it copies the recipient's before/after
places, climb identity, revision and occurrence time into persisted metadata;
Notification.transition and push transport expose that retained fact. Later board
reads never supply or rewrite it. Legacy rows without a snapshot omit the fact;
old_rank is insufficient evidence. No ordinal sentence is authorized by this
field. The currently disabled legacy board writer is not reactivated: an active
event-time seat-lost snapshot source is still required for runtime emission.

### 10.2 Transaction Builders Bypass The Indexer

Every transaction constructor — whether in the backend's executor, the
mobile app, or BoulderScan — reads canonical fields (`ProgramConfig`,
`last_distribution_epoch`, token account addresses, `backend_authority`)
from the chain via RPC.

The indexer is for reading about the protocol. It is not for participating
in it.

### 10.3 Indexer Drift Is Self-Healing

If the indexer falls out of sync with the chain, the fix is to reindex from
on-chain state. The fix is never to write directly to indexer tables to
reconcile.

The TypeScript indexer is the designated sole writer of chain-owned projection
fields. Every account write carries the exact finalized RPC context slot for the
bytes that were decoded. Conflict updates are null-aware for legacy rows and may
only advance `(chain_slot, indexed_at)`; account, replay, and snapshot cursors
follow the same nondecreasing rule. Reconciliation reads finalized account data
and uses that response's context slot, never a separately sampled head slot.
Gap-triggered and periodic replay requests share one in-flight sweep so
equal-slot transaction cursors cannot race within the indexer process.

Confirmed Vault creation records immutable v2/GPS evidence and replay intent in
`vault_creation_handoffs`; it never inserts `indexed_vaults`. Replay jobs reference
that handoff and remain `waiting_projection` until the finalized TypeScript
indexer creates a numbered Vault projection. Metadata-first and indexer-first
orders both attach only disjoint v2/GPS fields, preserve `chain_slot` and every
chain-owned value, and advance the operation ledger from pending to recorded
without allowing a later route write to regress it. If overlapping commits make
both insert-time triggers miss the other transaction, the periodic worker read
first reconciles every newly visible handoff/projection pair before dispatching
ready replay. Backend callers have RPC-only access to handoffs and replay state;
they have no direct table mutation grant.

During the migration-first rollout only, `queue_vault_backfill` converts a shell
inserted by a still-running old API process into the durable handoff. Null-slot
legacy jobs are demoted to `waiting_projection`, and no worker read or claim can
return them until a numbered TypeScript projection exists. Partial legacy GPS is
normalized to absent metadata during conversion rather than blocking migration.
The current API has no shell-insert path; the compatibility RPC branch is removed
after the new API is live and old processes have drained.

Backend services may enrich disjoint read metadata such as GPS or canonical
identity evidence. They may not run a second chain reader that overwrites Vault
economics, balances, carry, ranks, or supply without the indexer's ordering
contract. Completion recording writes idempotent evidence only to
`vault_completions`; it never mutates `indexed_vaults.total_completions`.
Migration 128 redefines both direct and ride-recovery completion projection
functions without that cross-owner write. The legacy
`increment_vault_completions` RPC is a service-role-only no-op tombstone for one
migration-first rollout; it cannot mutate the projection. The finalized
TypeScript Vault projection is the sole writer of the total and its ordering
provenance.

### 10.4 Transaction Success Comes From Signature Status

A submitted Solana signature is successful only when authoritative RPC status
has no execution `err` and satisfies the required commitment. Wallet-signed
submissions carry the prepare-time `last_valid_block_height`; an unseen
signature is checked in transaction history before being marked expired.

The signed transaction's deterministic signature is persisted before terminal
failure, expiry, or ambiguous confirmation state. Local projections begin only
after confirmation. Operation identity includes a client request ID when one is
provided and otherwise the exact prepared-message hash, so an exact replay is
fenced while a later same-amount action remains distinct.

### 10.5 Token API Boundaries Are Exact

CAL and DUNG use 9-decimal SPL base units. Money-bearing portfolio, Balance,
distribution, carry, pending-reward, harvest, and CAL-balance responses expose
base units as decimal strings. Human-unit values on those responses are also
exact decimal strings derived from the base-unit integer; they are display
values, never transaction inputs.

Portfolio `collectionSnapshot` quotes every wallet VaultStake from one confirmed,
context-bearing RPC inventory. Its revision binds the program, wallet and slot;
`asOf` records observation time. Readiness uses the pending-rewards quote's active
LP predicate and the on-chain unclaimed balance (reset on harvest), never indexed
cumulative `rewards_earned`. Rows and the exact uncollected total share that read.
Coverage counts validated accounts against the returned inventory; a decode or
identity failure makes it partial, preserving valid rows but withholding the total.
A complete empty or zero inventory has exact zero. RPC failure leaves the snapshot
absent. Legacy readiness fields now alias only this quote, remaining null without
it; transaction payloads and fee arithmetic are unchanged.

Current DUNG custody has two separate authorities. Wallet DUNG is the exact
amount in the rider's DUNG associated token account. Boulder Roller Balance
DUNG is the exact amount in the mint-scoped RiderBalance DUNG token PDA. The
legacy proof-linked `mint_events` aggregate is issuance history only; it is not
a current-balance source for either custody boundary. A missing token account is
reported as `not_initialized` with exact zero. An RPC or decode failure is
reported as `unavailable` with no amount and must never be serialized as zero.

Wallet CAL also carries direct RPC account-existence evidence:
`freshness.calStatus` is `live` for an initialized ATA, including exact zero,
`not_initialized` only when RPC returns no account, and `unavailable` on failure.
`calAccountExists` and `calAccountSlot` bind that observation to the same account
read as the amount. Mint, authority, program owner and initialized SPL state are
validated. Wallet DUNG retains the equivalent existing source status. Compatibility
CAL amount fields remain unchanged; existence is never inferred from an amount.

The RiderBalance header PDA is the only Balance lifecycle authority. The
backend decodes it through the current Anchor IDL and validates its program
owner, rider, and PDA bump; it never infers initialization or active status from
the presence of a wallet. Balance CAL and USDC come only from the mint-scoped
RiderBalance token PDAs derived with the CAL and USDC mints in the same verified
ProgramConfig snapshot. Each SPL account is bound to the Token Program, exact
mint, and RiderBalance authority PDA.

`portfolio.v5` and `portfolio_snapshot.v4` expose `wallet_dung` and
`balance_dung` plus the RiderBalance header and CAL/USDC Balance sources with
source status, account address, observed slot, and exact amount. A Balance
asset with an unavailable read has a null base-unit amount; only a confirmed
missing account has exact zero and `not_initialized`. The compatibility
`dung_balance` fields alias wallet DUNG only. The Balance lifecycle DUNG row
uses only the RiderBalance token PDA. The current Collect DUNG transaction
sends net DUNG to the rider wallet ATA, and its operation record and response
name that exact destination token account.

Indexed stake projections preserve `cal_staked`, `lp_tokens`, and
`rewards_earned` as base-unit decimal strings. Portfolio position and total
display values are derived from those strings, not from legacy claim-table
floats or fixture-only human-unit fields. `cal_staked` is remaining deposited
principal; `lp_tokens` is the position's recorded pool-share balance. A current
position is selected by `lp_tokens > 0`, because retained principal can floor to
zero while recorded LP remains. Both wallet and Boulder Roller Balance builders
derive the same rider-and-Vault position LP PDA; they never derive a wallet ATA
or Balance token PDA as the mint or burn destination. A first deposit prepends
the idempotent position initializer in the same transaction so the account is
created and frozen before the deposit instruction runs. The raw custody PDA and
`VaultStake` authority may be exposed in BoulderScan or support detail, while
primary rider surfaces call the aggregate object a position.

Positive indexed LP proves that the accounting position exists; it does not by
itself prove that a withdrawal is ready. Withdrawal preparation reads the live
deterministic token account and LP mint in one RPC snapshot. It requires the
canonical mint, `VaultStake` token authority, Vault-frozen state, exact equality
with `VaultStake.lp_tokens`, and the Vault PDA as both LP mint and freeze
authority. Missing, short, overfilled, unfrozen, uninitialized, authority-drifted,
or otherwise mismatched custody is `Needs review`, never redeemable. Legacy
restoration and rollout reports use the same checks and do not infer custody
from an indexed or SQL balance.

Balance-funded Vault builders additionally derive the rider's
`BalanceVaultAuthority` PDA and require an exact authorization containing a
32-byte operation ID, generation, nonce, and expiry. The operation ID is the
domain-separated SHA-256 of the program, rider, configured session signer,
action kind, Vault ID, exact primary and secondary base-unit amounts,
generation, nonce, and expiry. Backend and Rust share a frozen vector. Every
field is integer encoded; no amount or nonce passes through float or JavaScript
`Number`. A retry may resubmit the same prepared transaction while unconfirmed,
but a successful nonce cannot authorize another operation. Session expiry,
revocation, generation drift, signer drift, policy-hash drift, Balance lock, or
recovery fails closed.

Vault and Climb read models derive deposited CAL and total redeemable LP from
the exact sums of `indexed_stakes.cal_staked` and `indexed_stakes.lp_tokens`
over rows with positive LP. This deposited-principal sum is distinct from the
current gross pooled CAL inventory in `indexed_vaults.total_cal_staked`. The
deployed Vault's deprecated `total_staked` slot is old DUNG-layout provenance
and must never be read, sorted, or labeled as CAL. Vault and Climb responses
expose the deposited-principal sum as both an exact human-unit decimal string
and a base-unit decimal string; portal and mobile render the base-unit field
with integer arithmetic.

Clients parse and compare base-unit strings with integer arithmetic. They do
not route token amounts through JSON numbers, binary floats, or JavaScript
`Number`. Balance action requests accept decimal-string base units only and
reject values outside the on-chain `u64` range. Collection fee estimates use
the same integer floor operation as the protocol:

Vault withdrawal requests accept exactly one of
`lp_amount_base_units: "<u64>"` or `withdraw_all: true`. Both prepare and
submission resolve the canonical on-chain `VaultStake` and reject an overdraw
before building. `withdraw_all` uses its complete `lp_tokens` balance, including
fractional display units and values above JavaScript's safe-integer range. The
response exposes `lp_burned` and `lp_burned_base_units` as exact strings.
`cal_returned` remains unavailable until an authoritative chain projection or
receipt can support it; a legacy SQL projection is not promoted to chain truth.

```
fee_base_units = total_base_units * fee_bps // 10_000
net_base_units = total_base_units - fee_base_units
```

Before the First Cohort, d2df makes one intentional in-place exactness
correction to economic amount fields inside `client.v1`; there are no external
stable consumers, and portal and mobile move in the same change. This exception
ends with d2df. Future incompatible changes to a released client amount field
must bump the client contract. Portfolio's breaking amount correction was
versioned as `portfolio.v3` and `portfolio_snapshot.v2`; the later
custody-source correction is versioned as `portfolio.v4` and
`portfolio_snapshot.v3`; the independent RiderBalance header/CAL/USDC source
correction is versioned as `portfolio.v5` and `portfolio_snapshot.v4`. Balance
actions remain `portfolio_balance_action.v2`.

A configured fee of zero basis points is a valid live value. The launch
fallback applies only when ProgramConfig is absent or unreadable; it must not
replace an intentional zero.

Display rounding is an edge concern and cannot feed back into balance checks,
fee calculations, transaction construction, or ledger writes.

---

## 11. Meaning of Backend Downtime

The backend going down does not break the protocol.

- Already-attested rides remain on-chain. Their economic effects are already
  committed.
- Already-finalized settlement weeks remain final.
- Pending uploads queue at the mobile edge and upload when the backend
  returns.
- The indexer falls behind and catches up when restored.

What backend downtime **does** block:
- new attestation of rides uploaded during the outage
- new on-chain writes (CAL credits, Local Legend election, settlement
  finalization during the outage window)

A persistent backend outage that spans a settlement week boundary may require
manual finalization intervention. This is a known operational risk, not a
protocol bug.

---

## 12. Naming Conventions

These names are canonical inside the backend codebase, API surfaces, and
event emission:

- `RideAttestation` for the protocol's first-class ride primitive
- `Climb` and `Vault` as distinct objects (per PROTOCOL_TRUTHS §2)
- `Record Board` and `Record Royalty` for the 55% bucket
- `Local Legend` for the rolling stewardship seat
- `Settlement Week` in user-facing copy; `epoch` acceptable in internal math
  variables (per FIX_PLAN P4)
- `parser_version` for the canonical form identifier
- `completed_at`, `settled_at`, `finalized_at` as the three distinct
  timestamps
- `backend_authority` for the scoped signer
- In rider-facing copy: the backend **attests**, the chain **confirms**,
  the rider **verifies**. Do not describe the backend as an "authority."
  That inverts the grant direction (per §8.2) and implies riders answer
  to the backend, when in fact the backend answers to the chain and the
  rider audits the result.

Avoid:
- "segments" (use Climb)
- "points" (use CAL or DUNG, never both interchangeably)
- "challenger board" (use Record Board)

---

## 13. Alignment Implications

### 13.1 Preserve

- the backend as attester, not authority
- ride event time (`completed_at`) as the sporting and Record Board clock;
  chain admission time as the age and hold clock; release time as the release
  Settlement Week clock
- cryptographic commitment of attestations
- per-bucket carry with bucket identity preserved
- 24-hour settlement grace window
- on-chain `ProgramConfig` as the source of truth for transaction
  construction
- TRUTH_CONTRACT_V1 runtime invariants (determinism, boundary separation,
  signature stability, data quality guards)

### 13.2 Repair

- indexer-as-authority drift (transaction builders must read RPC, never
  indexer)
- Synthetix-style accrual math (replaced with discrete direct allocation)
- any path that credits CAL without a RideAttestation
- conflation of ride event time, chain admission time, and release time
- cross-bucket carry leakage
- `create_vault_points_period` naming remnants and other V3 rename
  propagation gaps
- ride ingest paths that do not compare mobile-stamped hash when present
- reprocess endpoints without idempotency guards

### 13.3 Demote

- the indexer from authoritative to projection-only
- the Merkle claim path (deleted in V4-A)
- "points" as a live concept (removed)
- upload time as sporting event time or as a reason to reopen historical
  authority and settlement

### 13.4 Prepare

- first-class `RideAttestation` PDA with child receipts (Phase 2)
- `Climb`/`Vault`/`RiderSoul` split in backend models and API shapes
  (Phase 2)
- hard rename propagation on the IDL-visible surface (Phase 2)
- broader asset graph types (Route, Zone, Arena, Event, Season) in ingest
  and projection layers
- sensor-integrity-aware attestation (TRUTH_CONTRACT_V1 §8 already defines
  the runtime bar)

### 13.5 Gate 1 (runtime-enforceable invariants)

Every invariant above that can be programmatically checked has a named test
under `backend/tests/truths/test_backend_truths_gate1.py`. Each test cites the
§N it enforces so a failing gate points a reviewer directly at the truth that
drifted. `docs/design/BACKEND_TRUTHS_GATE_1.md` tracks the coverage matrix,
the remaining documented PENDING item (§7.3 finalization one-way), and the
intentional DRIFT failure (§10.1 leaderboard inversion) that surfaces today —
the failure is the gate working, not a bug in the gate.

Gate 1 is static-scan based and runs without a live Solana / FastAPI boot, so
it executes in CI well before the integration tests. Gate 2 (full-stack
devnet smoke) is tracked separately under the protocol lane's
`backend/scripts/smoke_full_stack.py`.

---

## 14. Canonical Summary

Boulder Roller's backend is the protocol's attester:

- it receives rides, canonicalizes them under a versioned parser, and
  commits attestations on-chain
- every economic consequence derives from one attestation, once, with
  structural replay protection
- ride event time is the economic clock; upload time and settlement time
  are operational
- on-chain is authoritative, attested evidence is off-chain and
  reproducible, projections are for reading
- the backend signs but does not decree — attestations are cryptographically
  committed and independently verifiable
- per-bucket carry preserves bucket identity; discrete allocation replaces
  Synthetix accrual; the 24-hour grace window is respected in both
  directions
- the indexer is a cache, never authoritative; transaction builders read
  the chain directly
- backend downtime does not break the protocol; attested rides and
  finalized weeks survive the backend itself
- when anything conflicts with PROTOCOL_TRUTHS, PROTOCOL_TRUTHS wins

This is the semantic foundation for backend engineering work. The magic is
in how these truths interpret into services, pipelines, and operational
discipline — not in the truths themselves.


### Access invitations (2026-09-08)

New invitations store only normalized-code HMAC-SHA256 digests, keyed by
`INVITE_CODE_SECRET`; an unset key uses the refresh-token secret with a startup
warning. Migration backfill requires the same key as a transaction-local setting
and clears plaintext atomically. Existing shared invitations retain their limits,
expiry and active state. New invitations default to one use and seven days.

An optional intended recipient binds consumption to the signed wallet (case
sensitive) or provider-verified email (case insensitive). A pre-authentication
check does not consume or establish recipient identity; final signup checks it
under the invite row lock. Limited invitations cannot be consumed twice. Checked
invite cookies carry a separately authenticated digest, never the plaintext or
an unsigned digest usable from a database leak. Invite tables and RPCs retain
the server-only RLS and privilege boundary.

Cohort admission is separate from account creation and protocol authority.
`COHORT_ADMISSION_REQUIRED` defaults to false in every environment. When enabled,
the API refuses Deposit CAL (`/vaults/{vault_id}/stake/prepare`) and Collect DUNG
(`/vaults/{vault_id}/harvest/prepare`) preparation for a user without
`cohort_admitted_at`, with HTTP 403 `cohort_admission_required`. Account creation,
riding, results, reads, Balance funding, and withdrawal remain ungated by this
flag. The program is unchanged. `/auth/bootstrap` reports the required flag and,
for an authenticated caller, their current stored admission state.

Founder access administration uses the existing `require_admin` authority under
`/admin/access`: mint/list/deactivate invitations, admit/revoke a cohort user by
wallet, and revoke refresh sessions by wallet. Each accepted admin call, including
list and missing-target outcomes, appends actor, action, target, time and safe
details to `access_audit` in the same transaction. Audit failure rolls back the
action. Mint returns a random plaintext code once with `Cache-Control: no-store`;
list and audit omit both plaintext and digests. Refresh revocation resolves the
canonical identity and revokes active rows for every linked wallet, preserving
history. It does not change the expiry of already issued access tokens.

`/status` reports effective `invite_required` and `cohort_admission_required`.
The backend release preflight refuses a public environment unless
`invite_required` is explicitly true. Compose forwards invite enforcement,
admission enforcement and the invite HMAC key; empty invite enforcement retains
the environment-derived default. Invite precheck input requires eight characters.
