# Boulder Roller Math Audit Phase 2 - 2026-07-12

Bead: `boulderroller-v2-m2au`

Base reviewed: `origin/main` at `450f6384` after the first audit and the
`boulderroller-v2-rbvd` Record Board validation fix landed.

Policy closure (Tim, 2026-07-13):

- The weekly staker maximum is independently unlocked each week; its locked
  share flows to that week's Record Royalty and never becomes retroactive
  staker carry.
- Settlement Weeks hand off Monday 12:00 UTC and normally finalize Tuesday
  12:00 UTC after the 24-hour grace.
- DUNG halves deterministically every 26 Settlement Weeks from an immutable
  start and floors at 1 bps until cap exhaustion; cap exhaustion settles at
  zero rather than failing.

Implementation was tracked by `scur`, `eanc`, and `dpol`; all three closed
before the final gate.

## Final remediation verdict - 2026-07-18

The verdict below records the pre-remediation state. The launch-critical gate
is now closed: the settlement and ride state machines are recoverable, payout
math is widened and conserved, deferred claims are reserved, weekly timing and
staker semantics are canonical, economic evidence and token units are exact,
and the complete settlement account set has a measured atomic transport.

Composition proof passed 97 Rust tests, 20 full local-validator scenarios, a
final full-board measurement of 314,192 CU under the 450,000-CU limit, 1,568
broad backend cases with only the three known missing-Supabase fixtures
deselected, and PostgreSQL 17 runtime cases. Release
`dc398fbbd541c305374f33a0cdea1bef99efd832` applied migration 137 and passed 27
schema requirements. A live Vault 16 retry reused its exact completion and
stake, prepared a 437-byte v0 settlement, distributed Settlement Week 131,
withdrew the exact LP position, and harvested the complete DUNG claim.

Residual work is bounded rather than hidden: canon compiler confidence and
geometry research remains P2, six inaccessible generated-key devnet LP fixtures
remain fail-closed, DUNG supply projection needs a five-minute fallback when a
WebSocket notification drops, and GitHub Actions billing must be restored. None
changes the first-cohort arithmetic or grants authority over those legacy
positions.

## Historical executive verdict (pre-remediation)

Boulder Roller was not yet economically seaworthy at the time of this pass.
The first audit found most
of the local formulas, but its strongest clean bill was too broad: weekly
settlement conserves integer amounts, yet the composed system can still pay the
wrong fraction, create DUNG claims that cannot be collected, and permanently
skip a settlement week. Conservation is necessary; it does not prove fairness,
solvency, or liveness.

Phase 2 found two P0 lifecycle failures:

1. The settlement cursor advances past vaults that were skipped or failed, and
   queue rows have terminal/stuck states with no automatic recovery.
2. The active NATS ride path tries to write climb economics before it creates
   the required on-chain `RideAttestation`; failures are swallowed, CAL is then
   credited, and the message is acknowledged.

It also found P1 failures in staker carry, deferred DUNG liabilities, stake
amount maturity, monetary-policy authority, epoch timing, transaction
confirmation, parser resource bounds, and rider-visible base-unit handling.

The shape is consistent across the program: exact arithmetic often exists in
one layer, but the lifecycle that invokes it is weaker than the arithmetic.

## Method and completeness

This pass used five lenses rather than another formula-only sweep:

- **Quantity authority:** identify the canonical writer, unit, rounding rule,
  and every reader for each economic or identity-bearing quantity.
- **Lifecycle composition:** trace upload through attestation, completion, CAL,
  election, settlement, collection, indexer, API, and rider display.
- **Adversarial time:** test late rides, quiet weeks, delayed cranks, delayed
  halvings, mid-week stake changes, response loss, and stale projections.
- **Dynamic diagnostics:** reproduce carry re-unlock, cap overcommit, queue
  capacity, empty-week deadlock, anchor drift, and delayed halving in
  `scripts/reproduce_settlement_lifecycle_failures.py`.
- **Input and precision boundaries:** inspect parser resource allocation,
  missing samples, XML namespaces, PostgreSQL numeric types, Python floats,
  JavaScript `number`, and raw SPL base-unit displays.

Coverage includes Anchor, backend services/routes/repositories, SQL migrations,
the indexer, portal, BoulderScan, mobile ride status, `workout-parse`, canon,
Strava reconstruction, and wallet transaction submission. Archived/dead UI is
excluded unless it can still mutate live state.

## Correction ledger

These statements in the landed audits are superseded by Phase 2:

| Prior statement | Phase 2 correction |
| --- | --- |
| "The on-chain settlement arithmetic is sound." | Only bucket conservation was demonstrated. Carry fairness, deferred-claim solvency, cap-edge liveness, and crank recoverability fail. |
| "Displayed rank and paid rank disagree on ties." | The primary portal reads the indexed on-chain array, so current display and payout use the same order. The actual defect is that live insertion order, historical seed order, and the ratified pooled-tie rule disagree. |
| BoulderScan is clean because it is display-only. | `formatAtomic` is exact, but displayed source fields and labels can still be false. At audit time, current remainder was labeled lifetime tribute, `total_cal_burned` was not a burn, and `total_burned` never changed; the DUNG supply case is remediated under `boulderroller-v2-dbrn`. |
| Mobile was out of scope. | Phase 2 checked ride-counting/finality semantics and found CAL credit is conflated with settlement finalization. |
| `1704020400` is Sunday noon UTC. | It is `2023-12-31T11:00:00Z`. Code and comments are consistently one hour apart. |
| Record Board validation remained open. | `boulderroller-v2-rbvd` is merged and closed; invalid DB times no longer reach the paid chain write. |
| The account-size script mechanically verified all 16 layouts. | The pre-Phase-2 script used an absolute root-checkout path and skipped or failed to parse seven layouts. It now reads the active worktree, resolves chained constants/enums/bounded vectors, and verifies 16 of 16. |

## Quantity authority map

| Quantity | Unit / rounding | Current authority | Other readers or writers | Audit state |
| --- | --- | --- | --- | --- |
| Canonical ride hash | SHA-256 of parser-version JSON | Rust `canonicalize.rs` | Mobile TypeScript reimplementation, backend adapter, chain | Version/provenance gap |
| Ride duration | seconds | Python first-to-last wall time in live CAL path | Rust moving-time metrics, tribute denominator | Divergent |
| NP / TSS | watts / TSS float | Python `ride_metrics.py` in live path | Rust metrics, adapter shim | Divergent and rewardable |
| Rewardable CAL | CAL base units, truncate `TSS * 1e9` | `ride_effort_policy.py` | Anchor attestation and mint receipt | Exact after TSS input |
| Climb boundary/time | sample indices / whole seconds | Rust persistence detector | Python records, Record Board | Corpus-bound; index mapping risk |
| Climb match | mixed score/gates | v1/v2/corridor paths | vault repository, canon registry | Multiple authorities |
| Ride tribute | CAL base units, deterministic largest remainder when normalization is required | backend frozen plan; Anchor `RideTributeBudget` + V2 receipt | indexer, API, settlement flow | Conserved and exact-amount bound after `zxoz` + `8346` |
| Settlement week | integer week | Anchor `Vault::current_epoch` | Python and SQL copies | Same wrong anchor; API also omits anchor |
| Pending DUNG | DUNG base units | Anchor CAL remainder conversion | backend queue | Exact on-chain; queue type too small |
| Distribution split | basis points, floor dust to Record Royalty | instruction-supplied config | docs constants, backend builder | Backend can choose any 10,000-bps split |
| Staker eligibility | week plus current LP balance | one timestamp on `VaultStake` | backend-supplied account list | Amount is not snapshotted |
| Staker carry | DUNG base units | Anchor vault carry | simulator and API | Prior locked carry is re-unlocked |
| Staker DUNG claim | DUNG base units | `VaultStake.rewards_earned` | harvest instruction | Liability is not reserved |
| DUNG supply | DUNG base units | `DungMintState` | indexer, BoulderScan | Burns are omitted |
| LP shares | LP base units, floor | Anchor u128 pro rata | backend integer/display routes | Formula sound; API exact-exit gap |
| Record Board rank | whole-second array position | Anchor leaderboard | indexer and portal | Tie policy not implemented |
| Local Legend winner | completion count | backend DB election query | Anchor trusts submitted winner/counts | DB evidence can lack chain success |
| DUNG wallet/Balance amount | DUNG base units | SPL token accounts | legacy `mint_events`, portfolio, portal copy | Competing sources |
| Transaction success | signature status plus `err` | Solana RPC | `TxBuilder`, coordinator, routes | One submitter ignores `err` |
| Circulating DUNG | minted minus burned | indexer API | BoulderScan | Deterministic but wrong upstream |

## New P0 findings

### P0.1 Settlement state machine can permanently strand a week

Evidence:

- `backend/app/services/epoch_processor.py:196-206` advances the global stored
  epoch after `_process_epoch_end` returns.
- `_process_epoch_end` returns successfully when the vault cache or Solana
  config is unavailable (`:225-237`), catches each vault failure (`:299-301`),
  and calls a queue helper that logs and swallows insert failures (`:692-755`).
- The executor selects only `pending` rows (`:873-880`), marks any exception
  `failed` (`:953-963`), and has no retry transition or stale-`processing`
  reaper. A process crash after claim can leave a row stuck forever.
- A quiet week with value already staged for next week is deterministically
  broken. The backend queues week N when `current_week_value == 0` and
  `next_week_value > 0` (`:255-288`). The chain first advances empty N to N+1
  (`lib.rs:2781`, `:4364-4369`) and then rejects the supplied week N (`:2782-2785`).
- Queue `dung_to_mint` and breakdown columns are PostgreSQL `INTEGER`
  (`20251231020000_epoch_state.sql:17-30`) while runtime writes raw DUNG base
  units (`epoch_processor.py:716-727`). They overflow above 2.147483647 DUNG,
  reached at about 2,147.483647 CAL of weekly tribute.

Impact: one transient cache, RPC, database, schema, or chain failure can advance
the global cursor while leaving a vault's on-chain week open forever. Later
weeks then fail the week-equality guard. This is a money-path liveness failure,
not an observability issue.

Required outcome: make queue insertion and cursor advancement transactional at
the per-vault/week level; use exact wide integers; define retryable/terminal
errors; reclaim stale processing rows; reconcile queue state from chain; and
prove quiet, failed, crashed, and delayed weeks eventually finalize exactly
once.

Follow-up: `boulderroller-v2-stlq`.

### P0.2 Active NATS ordering drops climb economics before crediting CAL

Evidence:

- The NATS consumer executes Phase 1, then Phase 2, then Phase 3 and ACKs the
  message (`backend/app/services/nats_consumer.py:152-185`).
- Phase 2 enables vault economics whenever the ride is tributable and has a
  hash (`ride_processor.py:1169-1222`).
- `RideEnrichmentService` calls `match_climbs_to_vault` immediately
  (`ride_enrichment_service.py:94-112`).
- `record_climb_completion` requires the `RideAttestation` PDA, but Phase 3 does
  not create that account until `ride_processor.py:1416-1426`.
- The DB completion is inserted before the chain call
  (`climb_economy_processor.py:275-284`). The chain error is raised inside one
  climb (`:315-367`) and then swallowed by the outer loop (`:226-227`). Phase 2
  reports success; Phase 3 records the attestation and credits CAL.
- The monolithic path orders attestation, completions, then CAL
  (`ride_processor.py:640-743`), so a final CAL failure can leave permanent
  completion/tribute writes without the rider's CAL credit. There is no common
  reconciliation state machine for either partial order.

Impact: a normal on-time upload can receive CAL while every climb, tribute, and
Record Board effect silently disappears. DB rows left by the failed attempts
can still influence Local Legend elections, whose query checks validation but
not `on_chain_tx` (`epoch_processor.py:522-578`).

Required outcome: one idempotent ride-economic state machine with explicit
attestation, CAL, completion, and reconciliation checkpoints; no swallowed
money-write errors; chain-confirmed evidence for chain-derived elections; and a
replay test for failure after every step.

Follow-up: `boulderroller-v2-reco`.

## New P1 findings

### P1.1 Locked staker carry is re-unlocked every week

`distribute_epoch_rewards` adds prior `carry_stakers` to the new 27% base
(`lib.rs:2814-2816`) and applies the current unlock percentage to the combined
amount (`:3028-3063`). Locked carry is therefore not merely waiting for the
staker count to change; it gets another chance to unlock every week.

The faithful 52-week model in `scripts/reproduce_settlement_lifecycle_failures.py` gives a permanent
one-staker vault 315.999311210 DUNG from 1,404 DUNG of cumulative staker bucket:
22.507%, not the published 1%. With enough time and a constant nonzero unlock,
nearly all prior carry eventually pays.

Ratified outcome: apply the curve independently to each week's 27% maximum and
add the locked share to that week's Record Royalty. Do not carry it into future
staker calculations. Follow-up: `boulderroller-v2-scur`
(**agent-autonomous after 2026-07-13 ratification**).

Remediation: `scur` pre-scans the eligible stake set, reallocates the current
week's locked amount before Record Royalty rank allocation, and limits
`carry_stakers` to already-unlocked pro-rata integer dust. The protocol suite
includes the original 52-week counterexample as a red-to-green regression.
Independent landing review found that existing on-chain `carry_stakers` could
not safely inherit the new meaning. The final remediation uses the retired
`reward_rate` account slot as a no-resize marker: an unmarked Vault's first
successful new-policy settlement reclassifies all legacy staker carry to Record
Royalty, emits `StakerRemainderPolicyApplied`, and marks the Vault. The same
event gates BoulderScan's old-versus-new historical event labels. The indexer
projects the account marker as `staker_remainder_policy_version` so current
carry is also classified correctly before, during, and after cutover retries.

### P1.2 Settlement creates unreserved staker DUNG liabilities

Record Board, Legend, POL, and Treasury mint and call `record_mint` during
settlement. Staker allocations only increment `VaultStake.rewards_earned`
(`lib.rs:3031-3057`). The Community cap is checked and recorded later at
collection (`:2509-2554`, `:2592-2632`).

Concrete case: with 60 DUNG of Community cap remaining, settlement can mint
58 DUNG immediately and credit a 27-DUNG staker claim. It succeeds with 2 DUNG
of cap left; the claim has an immediate 25-DUNG shortfall.

Required outcome: mint to escrow, reserve cap headroom as a liability, or make
the accounting cap include unclaimed allocations. A successful settlement must
never create an uncollectable claim. Follow-up: `boulderroller-v2-dres`.

### P1.3 Stake maturity applies to the account, not the amount

Initial or reactivated stake sets one `eligible_from_epoch`, but an active
top-up only increases `cal_staked` and `lp_tokens` (`lib.rs:1938-1959` and
`:2100-2120`). Settlement uses the entire current LP balance once the account
date is eligible (`:3007-3015`). A mature 100-CAL position can add 1,000,000 CAL
immediately before settlement and earn on all of it. Partial withdrawal before
settlement likewise changes the current-period weight.

The direct-wallet stake context also includes `vault_activation` without an
`is_active` constraint (`:5468-5489`), while Balance deposit enforces it
(`:5533-5537`).

Required outcome: snapshot eligible LP per settlement week or tranche stake
changes by effective week; apply the same activation gate to both deposit
paths. Follow-up: `boulderroller-v2-smat`.

### P1.4 Monetary policy is backend-selected and halving is not a schedule

- `DistributionConfig` is an instruction argument and validates only that five
  caller-supplied fields sum to 10,000 (`lib.rs:99-118`). It is not checked
  against `ProgramConfig` or the documented 55/27/3/5/10 split.
- `DistributeEpochRewards` does not constrain `dung_mint` to
  `program_config.dung_mint` (`:5970-5988`). A malicious/compromised backend can
  combine zero POL/Treasury shares with recipient accounts for another
  PDA-controlled mint while consuming DUNG accounting and advancing the week.
- `InitializeDungMintState` lets any signer initialize the global PDA and become
  its halving authority (`:2702-2720`, `:5889-5901`). This is a fresh-deployment
  front-run risk.
- `apply_halving` has no runtime caller. A call delayed by two intervals halves
  once and moves `last_halving_epoch` to now (`:2725-2745`), producing 50%
  instead of the deterministic 25% schedule.

Ratified outcome: bind initialization and monetary parameters to
`ProgramConfig` authority; constrain the mint; implement automatic catch-up
halving inside distribution; floor the rate at 1 bps until cap exhaustion; and
make cap exhaustion a successful zero-emission settlement. Follow-up:
`boulderroller-v2-dpol` (**agent-autonomous after 2026-07-13 ratification**).

### P1.5 The canonical epoch anchor is one hour early

`1704020400` is `2023-12-31T11:00:00Z`, not noon. The wrong comment is repeated
in Rust, Python, SQL, tests, and `FRESHEST_SPEC.md`. Separately,
`GET /epoch/current` computes `(epoch + 1) * 604800` with no anchor at all
(`routes/distributions.py:407-427`), yielding a 1972 countdown.

Because the 11:00 value is already shared by chain state and projections, this
is not a search-and-replace. The ratified target is Monday 12:00 UTC with a
24-hour grace and normal Tuesday receipts. Migrate clean test state or retain
an explicit historical clock version, then delete local conversions in favor
of one tested module. Preserving deployed numeric week IDs requires one
explicit 694,800-second transition week: the legacy Sunday 11:00 UTC start
through the following v2 Monday 12:00 UTC end. The resulting 25-hour extension
is confined to that recorded cutover week; every later week remains 604,800
seconds.

Follow-up: `boulderroller-v2-eanc`
(**agent-autonomous after 2026-07-13 ratification**).

### P1.6 Rider-visible DUNG endpoints expose raw base units as token amounts

- Distribution API `_parse_amount` casts indexed u64 strings directly to float
  (`routes/distributions.py:322-342`) and every DTO field is a float. Portal
  history prints those numbers as DUNG (`VaultView.tsx:725-740`).
- Pending collection reads raw `VaultStake.rewards_earned`, returns it as
  `total_pending`, and computes fees in that same base-unit number
  (`routes/vaults.py:1748-1768`, `:1842-1848`). Portal prints `.toFixed(2)
  DUNG` (`VaultView.tsx:779-795`). A 340-DUNG claim displays as
  `340000000000.00 DUNG`.
- JavaScript contracts use `number`, so values above `2^53 - 1` also lose exact
  base-unit precision.

This expands existing bead `boulderroller-v2-d2df`: all monetary API contracts
need explicit base-unit strings plus separate formatted display values.

### P1.7 DUNG balance and destination semantics have competing authorities

`TokenRepository.get_token_balances` derives DUNG from legacy `mint_events`
linked to proofs (`repositories/token.py:19-59`), not from the rider's SPL wallet
or Balance token account. Portfolio exposes that as the current DUNG balance.
Collection builds a mint to the rider wallet ATA (`tx_builder.py:424-467`),
while the portal says the DUNG was added to the rider's Balance
(`VaultView.tsx:110-114`).

Required outcome: name and expose wallet DUNG and Balance DUNG separately,
choose one authoritative source for each, and make collection copy match the
actual destination. Follow-up: `boulderroller-v2-dsrc`.

Remediated 2026-07-17 by `boulderroller-v2-dsrc`: `portfolio.v4` reads the
wallet ATA and RiderBalance DUNG token PDA independently, preserves missing
versus unavailable state, and excludes `mint_events` from current balance
authority. Collect DUNG records and returns the exact wallet ATA destination;
the portal labels wallet custody separately from Boulder Roller Balance.

### P1.8 Wallet submission can report a failed transaction as confirmed

`TxBuilder.submit_signed_transaction` waits on
`AsyncClient.confirm_transaction` and ignores the returned signature status
(`tx_builder.py:272-280`). The installed solana-py method stops when commitment
rank is high enough but does not raise when `resp.value[0].err` is non-null.
Routes can then mark a submitted operation and later synthesize confirmed state.

Vault action idempotency keys also omit the prepared message hash or client
request identity (`balance_route_adapters.py:245-260`), while the DB has a
global unique index. A legitimate later action with the same wallet, vault,
asset, adapter, and amount collides with the old operation.

Implemented outcome: `boulderroller-v2-txok` replaces the false-success path
with authoritative status polling that rejects `err`, uses the exact
prepare-time block-height expiry, searches transaction history before declaring
a signature absent, and reconciles the deterministic signed signature after a
lost send response. Balance operations persist confirmation before projection;
their identity uses a client request ID or exact prepared-message hash so exact
replays remain fenced without colliding with later same-amount actions.

### P1.9 Parser input handling can invent terrain or exhaust the process

- GPX and TCX missing elevation is written as `0.0` (`workout-parse/src/lib.rs:
  413`, `:577`), turning missing samples into sea-level cliffs. FIT correctly
  uses NaN as missing (`:245`).
- GPX tag matching compares raw qualified names, so common namespaced sensor
  tags such as `gpxtpx:hr` do not match `hr` (`:342-370`).
- Auto-detection treats every XML declaration as GPX before checking TCX
  (`:92-98`). The forced-file-type backend path avoids this, but fallback/dev
  callers do not.
- Canonicalization allocates one bucket per second through the final timestamp
  and indexes every earlier sample into that vector
  (`canonicalize.rs:113-121`). An extreme final timestamp can request unbounded
  memory; out-of-order input can index beyond the vector and panic.

Required outcome: preserve missingness, match XML local names, validate and
bound timestamp spans before allocation, sort or reject out-of-order records,
and fuzz malformed FIT/GPX/TCX. Follow-up: `boulderroller-v2-pins`.

### P1.10 Parser behavior changed without a provenance closure gate

`CURRENT_PARSER_VERSION` remains 1 while parser behavior is still changing.
The economic ledger accepts `pipeline_version_id`, but runtime callers do not
populate it. The reference canonical GPX vector proves one format, not semantic
equivalence across representative FIT/GPX/TCX files, mobile TypeScript, and the
Python compatibility path.

Required outcome: define which changes require a parser-version bump; store an
immutable pipeline/version reference with every economic event; maintain a
cross-format golden corpus whose same ride yields the same canonical trace and
hash where equivalence is promised. Follow-up: `boulderroller-v2-pver`.

### P1.11 Delayed Local Legend rollover used crank wall time

The backend freezes the outgoing Local Legend term and its candidate evidence,
but the on-chain election and deactivation instructions previously derived the
new term from the wall-clock week when the transaction executed. Catching up an
old `[10, 18)` term during week 40 could therefore install the historical
winner for `[40, 48)` and skip `[18, 26)`, while reconciliation accepted that
misaligned state.

Implemented outcome: `boulderroller-v2-8345` binds each transition to the
outgoing term's exact end, rejects future or non-sequential starts on-chain,
and requires reconciliation to observe the same start. Bootstrap may begin on
an unaligned historical week, but every established term advances by exactly
the configured term length.

### P1.12 V1 completion evidence did not bind exact tribute

**Resolved 2026-07-14 by `boulderroller-v2-8346`.** The historical
`ClimbCompletionReceipt` and V1 hash proved the ride/vault/time identity but did
not store or bind `cal_tribute`. Recovery could therefore observe the expected
PDA/hash and confirm a frozen database amount different from the amount that
had actually changed on-chain state.

V1 bytes and hash semantics remain frozen and readable, but new V1 writes fail
closed. `record_climb_completion_v2` recomputes SHA-256 over a fixed domain,
RideAttestation PDA, Vault PDA, whole-second time, and exact tribute before any
mutation. Its distinct 114-byte account stores version 2, exact tribute, hash,
and bump at the same replay-guard PDA. New plans require V2; pending V1 plans
enter review and cannot auto-confirm, retry, or receive a non-reject review
resolution. SQL finality joins version, vault, hash, and exact amount; API and
mobile distinguish completion identity from tribute authority.

Red-to-green evidence includes the original four-failure V2 gate, 94 focused
backend/PostgreSQL tests, 41 indexer tests including `u64::MAX`, 25 BoulderScan
tests, and a 12-scenario local-validator suite. The validator pass also exposed
that a four-staker settlement exceeds the default 200,000 compute-unit
transaction envelope; production headroom is tracked separately by
`boulderroller-v2-ijq4`.

### P1.13 Portfolio fabricated RiderBalance state and copied wallet CAL

Portfolio treated any authenticated wallet as an initialized, active
RiderBalance. It then copied the wallet CAL ATA amount into the Balance CAL row
and hardcoded Balance USDC as absent. The actual on-chain authorities already
existed: the RiderBalance header PDA and the configured CAL/USDC mint-scoped
RiderBalance token PDAs. A locked or revoked Balance could therefore render as
active, wallet and Balance CAL could display the same unrelated amount, and an
RPC failure could collapse into a false zero/setup state.

Required outcome: decode and bind the RiderBalance header; derive CAL and USDC
Balance token PDAs from verified ProgramConfig mints; preserve exact `u64`
amounts; distinguish missing accounts from unavailable reads; and use the same
state to gate Balance actions. Follow-up: `boulderroller-v2-r7e6`.

## New P2 findings

### P2.1 DUNG burn and circulating-supply accounting is dead

`DungMintState.total_burned` initializes to zero and is never incremented.
Actual DUNG burns happen in Beetle upgrades (`lib.rs:933-944`) and vault
creation (`:1023-1034`) without a `DungMintState` account. The indexer faithfully
projects zero, and BoulderScan computes circulating as
`total_minted - total_burned` (`indexer/src/api.ts:290-305`).

Required outcome: atomically account every protocol DUNG burn or derive
circulating supply from the SPL mint supply; reconcile both in the indexer.
Follow-up: `boulderroller-v2-dbrn`.

Remediated 2026-07-16. BeetleCard upgrades and DUNG-funded Vault creation now
increment checked program-burn telemetry atomically without reducing lifetime
issuance or reopening any allocation cap. The indexer separately projects the
configured SPL mint's exact supply and finalized response slot; BoulderScan and
the admin read model use that value and report a missing observation as
unavailable. The decisive numerical case remains intentionally divergent:
`100` lifetime minted and `5` program-recorded burns can coexist with `91`
circulating when another `4` units were burned outside Boulder Roller program
instructions. PostgreSQL accepts the exact `u64` maximum, rejects fractional,
out-of-range, and incomplete observations, and preserves canonical/deploy
migration parity.

### P2.2 Out-of-order indexer callbacks can regress projections

The stream callback is async and unsequenced (`indexer/src/modes/stream.ts:
51-84`). Generic upserts overwrite every non-key column with `EXCLUDED` and
have no `chain_slot` predicate (`writers/common.ts:32-58`). If an older callback
finishes after a newer one, it can overwrite the projection with older account
state while recording the older slot.

Required outcome: serialize per PDA or make each upsert conditional on
`EXCLUDED.chain_slot >= table.chain_slot`; test reversed completion order.
Follow-up: `boulderroller-v2-slot`.

Remediated 2026-07-15. All 15 account-projection writers now converge on a
null-aware atomic conflict guard that rejects lower slots and uses a strictly
ordered local observation timestamp for equal-slot callbacks. Stream and sync
cursors cannot regress. Reconciliation now decodes finalized account responses
and writes each response's exact context slot. The slot-less confirmed Python
vault writer was retired, leaving its signature cache read-only, and Backend CI
now runs the indexer suite for `indexer/**` changes. Four initially failing
assertions covered missing single and batch guards, sync regression, and
confirmed/head provenance; six companion assertions cover compatibility and
behavior. A cursor-input assertion and then a single-flight assertion for
overlapping timer/gap replay sweeps each failed separately. A final reviewer-led
case caught and repaired synchronous-throw release in that helper. The suite is
now 53/53. A PostgreSQL 17 interleaving run proved that slot 200 survives a
later slot-100 write, batch slot 300 survives slot 250, the latest equal-slot
observation wins, legacy null-slot rows accept their first numbered observation, and
the slot-900 replay cursor survives a slot-800 update.

The ownership census also found `increment_vault_completions`, a backend SQL
compatibility write that still mutates chain-owned `indexed_vaults.total_completions`
without advancing `chain_slot`. Its migration and idempotency repair is separated
as `boulderroller-v2-dyhn`; it blocks the final seaworthiness gate without
reopening this callback-ordering fix.

Remediated 2026-07-15. The direct completion RPC, its REST fallback, and the
ride-economic recovery reconciler now write only idempotent
`vault_completions` evidence. Forward migration 128 removes the legacy counter
mutation after redefining both live SQL functions. A restricted no-op RPC
tombstone protects the migration-first rollout until old API processes drain.
A PostgreSQL 17 interleaving
proved that evidence inserted before and after a finalized slot-900 projection,
including retries through both paths, leaves its chain total 77 and slot 900
unchanged while retaining exactly three unique completion rows; invoking the
tombstone under `service_role` also leaves both fields unchanged. Canonical and
deployed migrations are byte-identical.

Remediated 2026-07-16. Confirmed Vault creation now atomically stages immutable
v2/GPS evidence and replay intent in `vault_creation_handoffs`; it never inserts
`indexed_vaults`. The replay foreign key targets the handoff, and jobs wait until
the finalized TypeScript writer creates a numbered projection. PostgreSQL 17
interleavings proved metadata-first and indexer-first attachment, stable chain
totals and slots, idempotent retries, service-role-only RPC access, and a
monotonic pending-to-recorded operation transition. A deterministic two-session
barrier also reproduced the overlapping-commit blind spot: both triggers missed
the other uncommitted row, then the next bounded worker read reconciled metadata,
queued replay, and recorded the operation after both commits. Service-role has no
direct table mutation grant. Canonical migration 129 and deployed migration 137
are byte-identical. Migration-first compatibility converts shells from a
still-running old API into handoffs, normalizes partial legacy GPS, and demotes
every null-slot queued job until a numbered projection exists; its removal is a
post-deploy cleanup rather than part of the live writer contract.

## Existing findings sharpened

The following are not new beads; Phase 2 expands or corrects their acceptance:

- `boulderroller-v2-2l9f`: keep P0. Share products can overflow before cap
  checks; test actual Rust widths near cap, not Python integers.
- `boulderroller-v2-rtie`: implement the ratified pooled tied-spots rule with
  standard competition ranks. The portal and payout both use the chain array;
  the defect is policy/order inconsistency, not a separate DB display payer.
- `boulderroller-v2-lrwd`: landed 2026-07-14. The ratified lifetime tribute
  accumulator and timeless records replace the current/next-week ride-admission
  window while retaining and draining legacy layout fields. The admission clock
  is frozen at attestation creation, delayed aggregate timestamps are monotonic,
  and the receipt-less legacy instruction fails closed. Exact distribution
  attribution for delayed rides remains under `boulderroller-v2-4x3v` because
  the historical ride week is not the flow that paid them. Disabled legacy
  client and smoke paths are retired under `boulderroller-v2-29rm`.
- `boulderroller-v2-hdhh`: raise to P1. Live Python math drops zero power,
  uses wall time, self-normalizes HR TSS with the same ride's max HR, and can
  treat one positive HR sample as sensor-backed. Strava reconstruction also
  drops zero power through truthiness (`strava_service.py:813-820`).
- `boulderroller-v2-d2df`: include distribution history, carry, pending
  collection, fee calculation, and all JavaScript `number` crossings.
- `boulderroller-v2-9qii`: v2 H3 distance fails open when grid distance cannot
  be computed (`signature_v2.rs:430-435`); require geographic evidence for
  reward-grade matching and test Rust/Python sample-index parity.
- `boulderroller-v2-canc`: remediated 2026-07-18. Compiler v0.2 adds metric
  buffered corridor authority and conservative H3 coverage, geometry-bearing
  resampling-stable fingerprints, symmetric DEM seam checks, explicit raster
  registration, reachable confidence tiers, and ordered stale-cell replacement.
  Named-gate arbitration remains separate under `boulderroller-v2-4crx.7`.
- `boulderroller-v2-xkdbb`: remediated 2026-07-18. Compiler v0.2.1 preserves
  the complete v0.2.0 candidate set, then appends only threshold-valid,
  fingerprint-unique opposite-orientation spans. The Pennsylvania/Wissahickon
  diff was 1,870 common, zero removed, and 181 directional additions, with no
  common geometry, gate, profile, score, or confidence drift. Named-gate
  arbitration remains separate under `boulderroller-v2-4crx.7`.
- `boulderroller-v2-9su7`: completeness remains separate from transaction-size
  pagination. A complete, deduplicated eligible set must be proven before any
  allocation.
- `boulderroller-v2-8346`: V1 receipt identity is not exact tribute evidence.
  Preserve V1 bytes for history, require V2 for all new plans, and keep
  receipt/flow/DB amount equality in every finality join.

## App-surface consequences

- Portal settlement and pending DUNG can be wrong by `1e9` and imprecise above
  JavaScript's safe integer limit.
- Mobile labels CAL "Credited" only when `finalizedAt` exists
  (`RideDetailScreen.tsx:1029-1035`). SQL derives ride finalization only from
  settled chain completions (`089_finalized_at_settlement_projection.sql:
  83-125`), so a no-climb ride can have a CAL mint receipt forever while the UI
  says "Waiting to count."
- The on-chain `RideAttestation.finalized` flag is set once at account creation
  (`lib.rs:546-547`) and never updated. It is not a usable live finality field.
- BoulderScan's exact formatter is good, but `cal_tribute_accumulated` is only
  the current sub-threshold remainder, not lifetime "CAL Tributed," and
  `total_cal_burned` is tribute accounting rather than a token burn.
- Historical V1 completion rows may still prove that a completion happened,
  but their copied tribute amount is projected rather than on-chain truth.
  Rider surfaces may show exact climb CAL only when `tributeBound` is true.

These read states should be repaired as part of `reco`, `d2df`, `dsrc`, and
`r7e6`, and `dbrn`, not with UI-only arithmetic patches.

## What remains solid

- The merged `rbvd` gate now withholds the on-chain completion and tribute when
  DB time validation rejects a climb.
- CAL mint receipts and V1/V2 climb completion receipts are PDA-idempotent once
  the required attestation exists. Only V2 binds exact tribute.
- Anchor uses checked additions in most state totals, and LP mint/redeem uses
  u128 pro-rata intermediates.
- The indexer serializes u64 values to decimal strings; BoulderScan's
  `formatAtomic` keeps formatting in integer/string space.
- The Rust canonicalizer has a fixed canonical JSON/hash reference vector and
  preserves empty seconds.
- Strava imports are reconstructed into a file and pass through the normal
  parser pipeline rather than maintaining a second ride model.
- DB time validation and historical seed ordering are explicit and
  deterministic.
- Haversine, bearing, H3 wrappers, account-size calculations, and Borsh layout
  checks did not produce money-class defects.
- The repaired account-size verifier is red-green evidence for the audit tool
  itself: before the change it verified nine layouts and skipped/unparsed seven;
  after the change it verifies all 16 from the active worktree.

## Remediation order

1. `stlq`, `reco`, then `2l9f`: settlement and ride liveness before arithmetic
   widening is declared sufficient. `ijq4` must also prove a production
   settlement compute envelope with headroom.
2. `dres`, `scur`, `9su7`, `smat`: make staker allocation solvent, fair, complete,
   and period-correct.
3. `dpol`, `eanc`, `rtie`, `lrwd`, `zxoz`: land ratified protocol semantics and
   the remaining monetary-policy decisions. `rtie` and `lrwd` are landed;
   `4x3v` follows `lrwd` to repair exact delayed-flow projection.
4. `hdhh`, `ftpv`, `9qii`, `pins`, `pver`: harden evidence before it drives CAL
   or climb identity.
5. `8346`, `d2df`, `dsrc`, `r7e6`, `txok`, `ehsh`, `lpwx`: exact evidence,
   transaction, and rider-visible money boundaries.
6. `dbrn`, `slot`, `canc`, `hba4`: supply truth, projection monotonicity, canon
   freeze, and broader invariant coverage.

## Residual risk

The final gate adds validator, PostgreSQL, release, and live devnet proof to the
static/model-based audit. It still does not certify backend key custody, RPC
behavior under forks, the economic desirability of the token model, or a future
mainnet ceremony. Long-horizon property tests and parser fuzzing remain useful
defense in depth rather than unrecorded launch blockers.

Reproduce the Phase 2 diagnostics with:

```bash
python3 scripts/reproduce_settlement_lifecycle_failures.py
python3 scripts/settlement_sim.py
python3 scripts/anchor_size_audit.py
```
